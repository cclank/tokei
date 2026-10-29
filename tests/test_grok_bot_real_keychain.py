"""Opt-in acceptance test on real macOS Keychain ACLs, never the login keychain.

The historical/current credential code is unchanged. Queries are scoped to a
temporary keychain, and HTTP is replaced with synthetic quota data. A separately
signed, untrusted helper must fail, proving the ACL is actually being enforced.
"""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SWIFT = ROOT / "tests/swift"
BRIDGE = "Tokei/Sources/GrokBotBridge/GrokBotQuotaBridge.swift"
OPT_IN = (sys.platform == "darwin" and os.environ.get("GITHUB_ACTIONS") == "true"
          and os.environ.get("TOKEI_RUN_REAL_KEYCHAIN_TESTS") == "1")


@unittest.skipUnless(OPT_IN, "Real Keychain acceptance runs only on disposable CI hosts")
class GrokBotRealKeychainTests(unittest.TestCase):
    def test_upgrade_preserves_real_acl_and_background_reads_never_prompt(self):
        report_dir = Path(os.environ["TOKEI_KEYCHAIN_REPORT_DIR"])
        report_dir.mkdir(parents=True, exist_ok=True)
        self.report = {"passed": False, "os": subprocess.check_output(["sw_vers", "-productVersion"], text=True).strip(),
                       "architecture": platform.machine(), "checks": [], "real_keychain": True,
                       "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()}
        self.report_dir = report_dir
        self.started = time.monotonic()
        try:
            with tempfile.TemporaryDirectory(prefix="tokei-real-keychain-") as directory:
                self.exercise(Path(directory))
            self.report["passed"] = True
        finally:
            self.report["elapsed_seconds"] = round(time.monotonic() - self.started, 3)
            (report_dir / "report.json").write_text(json.dumps(self.report, indent=2))

    def command(self, args, *, env=None, timeout=30, expected=0):
        result = subprocess.run([str(x) for x in args], env=env, capture_output=True, text=True, timeout=timeout)
        self.assertEqual(result.returncode, expected, f"{args[0]} {args[1:]}\n{result.stderr}\n{result.stdout}")
        return result.stdout.strip()

    def compile(self, output, sources, flags=()):
        result = subprocess.run(["swiftc", "-O", "-parse-as-library", *flags,
                                 *map(str, sources), "-o", str(output)], capture_output=True, text=True)
        (self.report_dir / (output.name + "-compile.log")).write_text(result.stderr)
        self.assertEqual(result.returncode, 0, result.stderr[-6000:])
        self.command(["codesign", "--force", "--sign", "-", "--identifier", "com.tokei.fixture." + output.name, output])

    @staticmethod
    def fingerprint(path):
        return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "mtime_ns": path.stat().st_mtime_ns}

    def exercise(self, root):
        admin = root / "keychain-admin"
        resolver = root / "helper-resolver"
        self.compile(admin, [SWIFT / "GrokBotKeychainFixture.swift"])
        self.compile(resolver, [ROOT / "Tokei/Sources/Tokei/GrokBotHelperManager.swift",
                               SWIFT / "GrokBotRealKeychainResolver.swift"])
        helpers = {}
        for version in ["v1.0.47", "v1.0.48", "current"]:
            source = (ROOT / BRIDGE).read_text() if version == "current" else self.command(["git", "show", f"{version}:{BRIDGE}"])
            self.report.setdefault("bridge_source_sha256", {})[version] = hashlib.sha256(source.encode()).hexdigest()
            if version != "current":
                original = "let status = SecItemCopyMatching(query as CFDictionary, &item)"
                self.assertEqual(source.count(original), 1)
                source = source.replace(original, "let status = integrationKeychainRead(query as CFDictionary, &item)")
            source += "\nextension GrokBotQuotaBridge { static func integrationCredentialRead() -> Bool { credential(allowInteraction: false, requireMarker: true) != nil } }\n"
            source_file = root / f"bridge-{version}.swift"
            source_file.write_text(source)
            helper = root / f"helper-{version}"
            flags = ["-D", "TOKEI_GROK_BOT_KEYCHAIN_TEST"] if version == "current" else []
            self.compile(helper, [source_file, SWIFT / "GrokBotRealKeychainHelper.swift"], flags)
            helpers[version] = helper

        marker = root / "authorization-marker"
        marker.write_text("historical-consent\n")
        keychain = root / "fixture.keychain-db"
        service = "com.tokei.isolated.grok." + root.name
        status_path = root / "query-status"
        secrets = root / "sand-secrets.json"
        self.write_secrets(secrets)
        env = dict(os.environ, HOME=str(root), TOKEI_AUTO_PRICING="0",
                   TOKEI_TEST_KEYCHAIN=str(keychain), TOKEI_TEST_SERVICE=service,
                   TOKEI_TEST_READ_STATUS=str(status_path), TOKEI_GROK_BOT_AUTH_MARKER=str(marker),
                   TOKEI_GROK_BOT_SECRETS=str(secrets),
                   TOKEI_GROK_BOT_PERSISTENT_HELPER=str(helpers["v1.0.47"]),
                   TOKEI_GROK_BOT_BUNDLED_HELPER=str(helpers["current"]),
                   TOKEI_GROK_BOT_HELPER=str(helpers["v1.0.47"]), TOKEI_GROK_BOT_HELPER_BLOCKED="0")
        self.command([admin, "create", keychain, service, helpers["v1.0.47"]])
        current_keychain = root / "current-helper.keychain-db"
        current_created = False
        watcher = None
        watch_stop = root / "stop-window-watch"
        watch_output = self.report_dir / "authorization-windows.json"
        try:
            if os.environ.get("GITHUB_ACTIONS") == "true":
                self.command([admin, "window-preflight"])
                watcher = subprocess.Popen([str(admin), "watch-windows", str(watch_output), str(watch_stop)])
            before_marker = self.fingerprint(marker)
            before_helper = self.fingerprint(helpers["v1.0.47"])
            before_acl = self.command([admin, "acl", keychain, service])
            self.report["acl_sha256_before"] = hashlib.sha256(before_acl.encode()).hexdigest()
            with mock.patch.dict(os.environ, env):
                spec = importlib.util.spec_from_file_location("tokei_keychain_integration", ROOT / "usage.30s.py")
                usage = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(usage)
                usage.PROVIDER_QUOTA_CACHE = str(root / "quota.json")
                # Every read goes through the shipping collector's subprocess
                # wrapper, including its protection of the original grant.
                def read(name, expected_success=True, helper=None):
                    status_path.unlink(missing_ok=True)
                    Path(usage._grok_bot_helper_files()[0]).unlink(missing_ok=True)
                    processes = []
                    real_popen = subprocess.Popen

                    def spawn(*args, **kwargs):
                        process = real_popen(*args, **kwargs)
                        processes.append(process)
                        return process

                    with mock.patch.dict(os.environ, {"TOKEI_GROK_BOT_HELPER": str(helper or helpers["v1.0.47"])}), \
                            mock.patch.object(usage.subprocess, "Popen", side_effect=spawn):
                        self.assertEqual(usage._grok_bot_helper_start(name), (True, True))
                    began = time.monotonic()
                    try:
                        self.assertEqual(processes[0].wait(timeout=8), 0 if expected_success else 2)
                    finally:
                        if processes[0].poll() is None:
                            os.killpg(processes[0].pid, signal.SIGKILL)
                            processes[0].wait(timeout=5)
                    status = int(status_path.read_text())
                    self.assertEqual(status == 0, expected_success)
                    if not expected_success:
                        self.assertIn(status, (-25308, -25293),
                                      "Only a silent interaction/auth denial is acceptable; user cancellation (-128) is a failure")
                    self.assertEqual(self.fingerprint(marker), before_marker)
                    self.assertEqual(self.fingerprint(helpers["v1.0.47"]), before_helper)
                    self.report["checks"].append({"name": name, "keychain_status": status,
                                                  "seconds": round(time.monotonic() - began, 3)})
                    print(f"{name}: keychain={status}, original authorization preserved", flush=True)

                def resolve(helper):
                    changed = dict(env, TOKEI_GROK_BOT_PERSISTENT_HELPER=str(helper))
                    return json.loads(self.command([resolver, "--grok-bot-resolve-helper"], env=changed, timeout=6))

                self.assertEqual(resolve(helpers["v1.0.47"])["helper"], str(helpers["v1.0.47"]))
                read("authorized-before-upgrade")
                self.command([admin, "lock", keychain, service])
                read("locked-keychain", expected_success=False)
                self.command([admin, "unlock", keychain, service])
                read("unlock-reuses-existing-grant")
                for attempt in range(3):
                    read(f"untrusted-new-binary-{attempt}", expected_success=False, helper=helpers["current"])
                read("old-helper-still-authorized")
                before_denied = self.fingerprint(marker)
                denied_env = dict(env, TOKEI_GROK_BOT_HELPER=str(helpers["current"]))
                self.command([helpers["current"], "--grok-bot-data-json"], env=denied_env, timeout=8, expected=2)
                self.assertIn(int(status_path.read_text()), (-25308, -25293))
                self.assertEqual(self.fingerprint(marker), before_denied)
                self.command([admin, "create", current_keychain, service, helpers["current"]])
                current_created = True
                current_acl = self.command([admin, "acl", current_keychain, service])
                with mock.patch.dict(os.environ, {"TOKEI_TEST_KEYCHAIN": str(current_keychain)}):
                    read("current-helper-authorized", helper=helpers["current"])
                    self.command([admin, "lock", current_keychain, service])
                    read("current-helper-locked", expected_success=False, helper=helpers["current"])
                    self.command([admin, "unlock", current_keychain, service])
                    read("current-helper-unlocked", helper=helpers["current"])
                self.assertEqual(self.command([admin, "acl", current_keychain, service]), current_acl)
                self.assertIsNone(resolve(root / "missing-helper")["helper"])
                blocked = resolve(helpers["v1.0.48"])
                self.assertTrue(blocked["blocked"])
                self.assertIsNone(blocked["helper"])
                self.report["checks"].append({"name": "unsafe-v1.0.48-paused-before-keychain-access"})
                marker.rename(root / "saved-consent")
                with mock.patch.object(usage.subprocess, "Popen") as no_launch:
                    self.assertEqual(usage._grok_bot_helper_start("missing-consent"), (False, False))
                    no_launch.assert_not_called()
                (root / "saved-consent").rename(marker)
                self.assertEqual(self.fingerprint(marker), before_marker)
                read("grant-restored-without-reauthorization")
                # A changed app does not install or replace the already-trusted
                # helper. Each resolution uses a new process, as after restart.
                duration = int(os.environ.get("TOKEI_KEYCHAIN_SOAK_SECONDS", "620"))
                began = time.monotonic()
                iteration = 0
                while True:
                    self.assertEqual(resolve(helpers["v1.0.47"])["helper"], str(helpers["v1.0.47"]))
                    read(f"upgrade-refresh-{iteration}")
                    elapsed = time.monotonic() - began
                    if elapsed >= duration:
                        break
                    time.sleep(min(30, duration - elapsed))
                    iteration += 1
                self.report["continuous_refresh_seconds"] = round(time.monotonic() - began, 3)

            after_acl = self.command([admin, "acl", keychain, service])
            self.assertEqual(after_acl, before_acl)
            self.report.update(authorization_marker_unchanged=True, authorized_helper_unchanged=True,
                               actual_keychain_acl_unchanged=True,
                               acl_sha256_after=hashlib.sha256(after_acl.encode()).hexdigest())
        finally:
            try:
                if watcher is not None:
                    watch_stop.touch()
                    self.assertEqual(watcher.wait(timeout=5), 0)
                    windows = json.loads(watch_output.read_text())
                    self.report["window_observation"] = windows
                    self.assertGreater(windows["samples"], 0)
                    self.assertEqual(windows["authorizationWindows"], [])
            finally:
                if current_created:
                    self.command([admin, "delete", current_keychain, service])
                self.command([admin, "delete", keychain, service])

    @staticmethod
    def write_secrets(path):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7

        key = hashlib.pbkdf2_hmac("sha1", b"fixture-safe-storage-password", b"saltysalt", 1003, 16)

        def encrypted(value):
            padder = PKCS7(128).padder()
            padded = padder.update(value.encode()) + padder.finalize()
            cipher = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).encryptor()
            return base64.b64encode(b"v10" + cipher.update(padded) + cipher.finalize()).decode()

        claims = base64.urlsafe_b64encode(json.dumps({"sub": "fixture-user", "exp": int(time.time()) + 7200}).encode()).decode().rstrip('=')
        path.write_text(json.dumps({"cursor-machine-id": encrypted("fixture-machine"),
                                   "cursor-accounts": json.dumps({"active": "fixture-account", "accounts": {
                                       "fixture-account": {"cursor-access-token": encrypted("e30." + claims + ".fixture")}}})}))


if __name__ == "__main__":
    unittest.main()
