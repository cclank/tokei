"""Windows native integrations. Credentials never leave this process.

The collector imports quota functions; Tauri runs authorization and launch
reporting as short-lived processes using its bundled Python runtime.
"""
import argparse
import base64
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

MAX_FILE = 2 * 1024 * 1024
MAX_USAGE = 16 * 1024 * 1024
CLAUDE_URL = "https://api.anthropic.com/api/oauth/usage?at_wall=1&skip_spend=1"
GROK_QUOTA_URL = "https://api2.cursor.sh/aiserver.v1.DashboardService/GetSandUsageStatus"
GROK_USAGE_URL = "https://api2.cursor.sh/aiserver.v1.DashboardService/GetFilteredUsageEvents"
ACTIVITY_URL = "https://tokei-ops.lanshuagent.com/v1/heartbeat"
WINDOWS = sys.platform == "win32"


class BridgeError(Exception):
    """Only fixed, non-sensitive status codes may cross the process boundary."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_json(path, limit=MAX_FILE):
    with Path(path).open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise BridgeError("unavailable")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise BridgeError("unavailable")
    return value


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            os.chmod(temporary, 0o600)
            json.dump(value, handle, ensure_ascii=False, allow_nan=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def state_dir():
    return Path(os.environ.get("TOKEI_WINDOWS_STATE_DIR") or Path.home() / ".tokei")


def config_enabled(key):
    try:
        return read_json(state_dir() / "config.json").get(key) is True
    except (OSError, ValueError, BridgeError):
        return False


def request_json(url, headers, body=None, timeout=8, limit=MAX_FILE):
    if url not in {CLAUDE_URL, GROK_QUOTA_URL, GROK_USAGE_URL}:
        raise BridgeError("unavailable")
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout) as response:
        if response.status != 200 or response.geturl() != url:
            raise BridgeError("unavailable")
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise BridgeError("unavailable")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise BridgeError("unavailable")
    return value


def percent(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) and 0 <= value <= 100 else None


def epoch(value):
    if not isinstance(value, str):
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return int(date.timestamp()) if date.tzinfo else None
    except (ValueError, OverflowError):
        return None


def claude_snapshot(payload, now):
    snapshot = {"q_updated": now}
    for field, source in (("q5", payload.get("five_hour")), ("q7", payload.get("seven_day"))):
        if isinstance(source, dict) and percent(source.get("utilization")) is not None:
            snapshot[field] = percent(source["utilization"])
            snapshot[field + "_reset"] = epoch(source.get("resets_at"))
    for limit in payload.get("limits", []) if isinstance(payload.get("limits"), list) else []:
        if not isinstance(limit, dict):
            continue
        scope = limit.get("scope")
        model = scope.get("model") if isinstance(scope, dict) else None
        if limit.get("kind") == "weekly_scoped" and isinstance(model, dict) \
                and str(model.get("display_name", "")).lower() == "fable" \
                and percent(limit.get("percent")) is not None:
            snapshot["qf"] = percent(limit["percent"])
            snapshot["qf_reset"] = epoch(limit.get("resets_at"))
    return snapshot if any(k in snapshot for k in ("q5", "q7", "qf")) else None


def quota_freshness(snapshot, now):
    result = dict(snapshot)
    age = now - result.get("q_updated", 0)
    for field in ("q5", "q7", "qf"):
        reset = result.get(field + "_reset")
        result[field + "_stale"] = field in result and (age > 1800 or age < -300 \
            or isinstance(reset, (int, float)) and reset <= now)
    return result


def fetch_claude_quota(desktop, now=None, credentials=None, directory=None, requester=request_json):
    """Desktop first; CLI fallback uses a five-minute cache and failure backoff."""
    now = int(time.time()) if now is None else now
    if all(percent(desktop.get(k)) is not None and desktop.get(k + "_stale") is not True for k in ("q5", "q7")):
        return desktop
    credentials = Path(credentials or Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / ".credentials.json")
    directory = Path(directory or state_dir())
    cache = directory / "claude_cli_quota_cache.json"
    try:
        stat = credentials.stat()
        if stat.st_size > 1024 * 1024:
            return desktop
        stamp = hashlib.sha256(str(credentials.resolve()).encode()).hexdigest() + f":{stat.st_mtime_ns}:{stat.st_size}"
        try:
            state = read_json(cache)
        except (OSError, ValueError, BridgeError):
            state = {}
        if state.get("credential_stamp") != stamp:
            state = {"credential_stamp": stamp}
        for field in ("fetched_at", "failed_at", "blocked_until"):
            value = state.get(field, 0)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                state = {"credential_stamp": stamp}
                break
        snapshot = state.get("snapshot")
        snapshot = snapshot if isinstance(snapshot, dict) and isinstance(snapshot.get("q_updated"), int) \
            and all(percent(snapshot[k]) is not None for k in ("q5", "q7", "qf") if k in snapshot) else None
        def answer():
            if snapshot and snapshot.get("q_updated", 0) >= desktop.get("q_updated", 0):
                return {**desktop, **quota_freshness(snapshot, now)}
            return desktop
        expired = snapshot and any(isinstance(snapshot.get(k + "_reset"), (int, float)) \
            and snapshot[k + "_reset"] <= now for k in ("q5", "q7", "qf"))
        if snapshot and -300 <= now - state.get("fetched_at", 0) < 300 and not expired:
            return answer()
        if state.get("blocked_until", 0) > now or state.get("failed_at", 0) > 0 \
                and -300 <= now - state["failed_at"] < 300:
            return answer()
        oauth = read_json(credentials, 1024 * 1024).get("claudeAiOauth")
        if not isinstance(oauth, dict):
            raise BridgeError("login_required")
        token = oauth.get("accessToken")
        if not isinstance(token, str) or not token or len(token) > 32768 \
                or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in token):
            raise BridgeError("login_required")
        expiry = oauth.get("expiresAt")
        if isinstance(expiry, (int, float)):
            expiry = expiry * 1000 if expiry < 10_000_000_000 else expiry
            if expiry <= (now + 30) * 1000:
                raise BridgeError("expired")
        state["failed_at"] = now  # Save a cooldown even if the request is interrupted.
        atomic_json(cache, state)
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json",
                   "Content-Type": "application/json", "Cache-Control": "no-store",
                   "anthropic-beta": "oauth-2025-04-20", "User-Agent": "claude-code/2.1.0"}
        try:
            payload = requester(CLAUDE_URL, headers)
            fresh = claude_snapshot(payload, now)
            if fresh:
                snapshot = fresh
                state.update(snapshot=fresh, fetched_at=now, failed_at=0, blocked_until=0)
        except urllib.error.HTTPError as error:
            if error.code == 429:
                retry = error.headers.get("Retry-After", "")
                try:
                    until = now + max(0, int(retry))
                except (ValueError, TypeError):
                    try:
                        until = int(parsedate_to_datetime(retry).timestamp())
                    except (ValueError, TypeError, OverflowError):
                        until = now + 300
                state["blocked_until"] = max(now + 300, until)
        except (OSError, ValueError, BridgeError):
            pass
        atomic_json(cache, state)
        return answer()
    except (OSError, ValueError, BridgeError):
        return desktop


def dpapi_decrypt(blob):
    if not WINDOWS:
        raise BridgeError("unsupported_platform")
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]
    data = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    source = Blob(len(blob), data)
    result = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    crypt.CryptUnprotectData.restype = wintypes.BOOL
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise BridgeError("unavailable")
    try:
        if result.cbData > MAX_FILE:
            raise BridgeError("unavailable")
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        if result.pbData:
            ctypes.memset(result.pbData, 0, result.cbData)
            kernel.LocalFree(result.pbData)


def decrypt_secret(encoded, profile, unprotect=None):
    unprotect = unprotect or dpapi_decrypt
    if not isinstance(encoded, str) or len(encoded) > MAX_FILE:
        raise BridgeError("unavailable")
    if encoded.startswith("scoped:v1:"):
        encoded = encoded.rsplit(":", 1)[-1]
    try:
        blob = base64.b64decode(encoded, validate=True)
        if blob.startswith((b"v10", b"v11")):
            local = read_json(Path(profile) / "Local State")
            key = base64.b64decode(local["os_crypt"]["encrypted_key"], validate=True)
            if not key.startswith(b"DPAPI") or len(blob) < 31:
                raise BridgeError("unavailable")
            key = unprotect(key[5:])
            if len(key) != 32:
                raise BridgeError("unavailable")
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            plain = AESGCM(key).decrypt(blob[3:15], blob[15:], None)
        elif blob.startswith(b"v20"):
            # App-bound encryption must be handled by the owning application.
            raise BridgeError("unsupported_format")
        else:
            plain = unprotect(blob)
        return plain.decode("utf-8")
    except BridgeError:
        raise
    except Exception:
        raise BridgeError("unavailable") from None


def grok_profile():
    configured = os.environ.get("TOKEI_GROK_BOT_SECRETS")
    return Path(configured) if configured else Path(os.environ.get("APPDATA") or Path.home() / "AppData/Roaming") / "Grok Bot/sand-secrets.json"


def grok_metadata(path=None):
    path = Path(path or grok_profile())
    outer = read_json(path)
    accounts = json.loads(outer.get("cursor-accounts", "{}"))
    active = accounts.get("active") if isinstance(accounts, dict) else None
    entries = accounts.get("accounts") if isinstance(accounts, dict) else None
    if not isinstance(active, str) or not re.fullmatch(r"[0-9a-f]{64}", active) \
            or not isinstance(entries, dict) or not isinstance(entries.get(active), dict):
        raise BridgeError("login_required")
    return outer, entries[active], active, hashlib.sha256(str(path.resolve()).encode()).hexdigest()


def grok_grant_path():
    return Path(os.environ.get("TOKEI_GROK_BOT_AUTH_MARKER") or state_dir() / "grok_bot_keychain_authorized")


def matching_grant(active, profile, now=None):
    now = time.time() if now is None else now
    try:
        grant = read_json(grok_grant_path())
    except (OSError, ValueError, BridgeError):
        raise BridgeError("authorization_required") from None
    if grant.get("version") != 1 or grant.get("account") != active or grant.get("profile") != profile:
        raise BridgeError("authorization_required")
    # The grant belongs to the account, not to a particular expiring access token.
    return grant


def grok_status():
    if not WINDOWS:
        return {"status": "unsupported_platform"}
    try:
        _, _, active, profile = grok_metadata()
        matching_grant(active, profile)
        return {"status": "authorized"}
    except BridgeError as error:
        return {"status": str(error)}
    except (OSError, ValueError):
        return {"status": "login_required"}


def grok_credential(require_grant=True, now=None, decryptor=None):
    decryptor = decryptor or decrypt_secret
    now = time.time() if now is None else now
    if not WINDOWS:
        raise BridgeError("unsupported_platform")
    if not config_enabled("grok_bot_quota_enabled"):
        raise BridgeError("disabled")
    outer, account, active, profile = grok_metadata()
    grant = matching_grant(active, profile, now) if require_grant else None
    token = decryptor(account.get("cursor-access-token"), grok_profile().parent)
    machine = decryptor(outer.get("cursor-machine-id"), grok_profile().parent)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,32768}", token) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,512}", machine):
        raise BridgeError("login_required")
    try:
        encoded = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        expires = claims["exp"]
        subject = claims["sub"].rsplit("|", 1)[-1]
        if not isinstance(expires, (int, float)) or not math.isfinite(expires) \
                or not re.fullmatch(r"[A-Za-z0-9._-]+", subject):
            raise ValueError()
    except (ValueError, KeyError, IndexError, TypeError):
        raise BridgeError("login_required") from None
    if expires <= now + 60:
        raise BridgeError("expired")
    return {"token": token, "machine": machine, "account": active, "profile": profile,
            "expires_at": expires, "grant": grant}


def authorize_grok():
    try:
        credential = grok_credential(require_grant=False)
        atomic_json(grok_grant_path(), {"version": 1, "account": credential["account"],
            "profile": credential["profile"], "expires_at": credential["expires_at"],
            "generation": uuid.uuid4().hex})
        return {"status": "authorized"}
    except BridgeError as error:
        return {"status": str(error)}
    except (OSError, ValueError):
        return {"status": "login_required"}


def checksum(machine, now=None):
    bucket = max(0, int((time.time() if now is None else now) / 1000))
    data = bytearray(bucket.to_bytes(6, "big"))
    previous = 165
    for i, value in enumerate(data):
        data[i] = ((value ^ previous) + i) & 255
        previous = data[i]
    return base64.urlsafe_b64encode(data).decode().rstrip("=") + machine


def sanitize_event(event):
    if not isinstance(event, dict) or str(event.get("clientType", "sand")).lower() != "sand":
        return None
    try:
        timestamp = int(event.get("timestamp", 0))
    except (ValueError, TypeError, OverflowError):
        return None
    source = event.get("tokenUsage")
    if timestamp <= 0 or not isinstance(source, dict):
        return None
    usage = {}
    for key in ("inputTokens", "outputTokens", "cacheWriteTokens", "cacheReadTokens"):
        try:
            usage[key] = max(0, int(source.get(key, 0)))
        except (ValueError, TypeError, OverflowError):
            usage[key] = 0
    if not any(usage.values()):
        return None
    cents = source.get("totalCents")
    if isinstance(cents, (int, float)) and math.isfinite(cents) and cents >= 0:
        usage["totalCents"] = cents
    clean = {"timestamp": str(timestamp), "tokenUsage": usage, "clientType": "sand",
             "eventKey": hashlib.sha256(json.dumps(event, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    model = event.get("model")
    if isinstance(model, str) and 0 < len(model.strip()) <= 200:
        clean["model"] = model.strip()
    return clean


def fetch_grok_data(since=None, requester=request_json):
    credential = grok_credential()
    started = time.monotonic()
    def request(url, body, limit=MAX_FILE):
        if time.monotonic() - started > 570:
            raise BridgeError("unavailable")
        # Do not issue another page after the user switches accounts or disables lookup.
        _, _, active, profile = grok_metadata()
        grant = matching_grant(active, profile)
        if not config_enabled("grok_bot_quota_enabled") or active != credential["account"] \
                or grant.get("generation") != credential["grant"].get("generation"):
            raise BridgeError("authorization_required")
        headers = {"Authorization": "Bearer " + credential["token"], "Content-Type": "application/json",
            "Accept": "application/json", "Connect-Protocol-Version": "1", "x-cursor-client-type": "sand",
            "x-cursor-client-version": "0.30.0", "x-sand-box-namespace": "prod", "x-ghost-mode": "true",
            "x-cursor-checksum": checksum(credential["machine"]), "x-request-id": str(uuid.uuid4())}
        return requester(url, headers, body, timeout=10, limit=limit)
    output = {"quotaFetched": False, "usageFetched": False, "updated": int(time.time())}
    try:
        quota = request(GROK_QUOTA_URL, {})
        output["sandUsage"] = {k: quota[k] for k in ("usagePercent", "hasNonZeroIncludedLimit", "currentPeriodStart",
            "nextResetTimestampUtc", "grokPlanLabel", "planLabel", "plan") if k in quota}
        output["quotaFetched"] = True
    except (OSError, ValueError, BridgeError):
        pass
    now = datetime.now().astimezone()
    start = int(now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    end = int(now.timestamp() * 1000)
    if isinstance(since, int) and start <= since <= end:
        start = since
    events = []
    expected = None
    try:
        for page in range(1, 101):
            response = request(GROK_USAGE_URL, {"page": page, "pageSize": 1000, "startDate": str(start),
                "endDate": str(end), "clientType": "sand"}, limit=MAX_USAGE)
            raw = response.get("usageEventsDisplay")
            count = response.get("totalUsageEventsCount")
            if not isinstance(raw, list) or len(raw) > 1000:
                raise BridgeError("unavailable")
            if isinstance(count, int) and count >= 0:
                if expected is not None and expected != count:
                    raise BridgeError("unavailable")
                expected = count
            events.extend(clean for clean in map(sanitize_event, raw) if clean)
            if len(raw) < 1000 or expected is not None and page * 1000 >= expected:
                output.update(usageFetched=True, usageEventsDisplay=events,
                    totalUsageEventsCount=expected if expected is not None else len(events), usageStartDate=str(start))
                break
    except (OSError, ValueError, BridgeError):
        pass
    # Reject the entire result if permission changed while a request was in flight.
    _, _, active, profile = grok_metadata()
    grant = matching_grant(active, profile)
    if not config_enabled("grok_bot_quota_enabled") or active != credential["account"] \
            or grant.get("generation") != credential["grant"].get("generation"):
        raise BridgeError("authorization_required")
    return output if output["quotaFetched"] or output["usageFetched"] else None


def activity_payload(installation, version, os_version):
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version):
        raise BridgeError("unavailable")
    parsed = uuid.UUID(installation)
    if parsed.version != 4 or not re.fullmatch(r"\d+\.\d+", os_version):
        raise BridgeError("unavailable")
    return {"installation_id": str(parsed), "app_version": version, "os_name": "Windows", "os_version": os_version}


def report_activity(directory, version, sender=None):
    """One attempt per launched helper, no retry or upload queue."""
    path = Path(directory) / "state.json"
    try:
        state = read_json(path) if path.exists() else {"installation_id": str(uuid.uuid4())}
        os_parts = platform.version().split(".")
        os_version = ".".join(os_parts[:2])
        payload = activity_payload(state["installation_id"], version, os_version)
        state["last_attempt_at"] = int(time.time())
        atomic_json(path, state)
        if sender is None:
            def sender(value):
                req = urllib.request.Request(ACTIVITY_URL, data=json.dumps(value).encode(),
                    headers={"Content-Type": "application/json", "User-Agent": "Tokei/" + version})
                with urllib.request.build_opener(NoRedirect()).open(req, timeout=10) as response:
                    return response.status == 204 and response.geturl() == ACTIVITY_URL
        if sender(payload):
            state["last_successful_day"] = datetime.now(timezone.utc).date().isoformat()
            atomic_json(path, state)
    except Exception:
        pass  # Never print installation IDs or interrupt the application.


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["grok-status", "grok-authorize", "grok-data", "activity"])
    parser.add_argument("--since", type=int)
    parser.add_argument("--result")
    parser.add_argument("--directory")
    parser.add_argument("--version")
    args = parser.parse_args()
    if args.mode == "activity":
        if WINDOWS and args.directory and args.version:
            report_activity(args.directory, args.version)
        return
    if args.mode == "grok-status":
        print(json.dumps(grok_status()))
    elif args.mode == "grok-authorize":
        print(json.dumps(authorize_grok()))
    else:
        if not args.result or Path(args.result).resolve() != (state_dir() / "grok_bot_helper.json").resolve():
            raise BridgeError("unavailable")
        output = fetch_grok_data(args.since)
        if output:
            atomic_json(args.result, output)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # No traceback: it could contain credential-bearing request objects.
        sys.exit(2)
