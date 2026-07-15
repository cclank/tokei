#!/usr/bin/env python3
# <bitbar.title>AI Usage Bar</bitbar.title>
# <bitbar.version>v0.1</bitbar.version>
# <bitbar.author>local</bitbar.author>
# <bitbar.desc>本地 AI coding tools token / 缓存命中 / 花费 / 额度</bitbar.desc>
# <swiftbar.runInBash>false</swiftbar.runInBash>
#
# 数据主要读自本地会话日志,不改动任何 CLI；Codex 额度会短缓存查询官方 live usage。
# 仅 --update-prices 显式联网更新价格表:
#   Claude Code: ~/.claude/projects/<proj>/<session>.jsonl  (assistant 行 message.usage,增量)
#   Codex:       ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl (token_count 事件,含额度)
#   Pi:          ~/.pi/agent/sessions/**/*.jsonl + ~/.omp/agent/sessions/**/*.jsonl
#   WorkBuddy:   ~/.workbuddy/projects/**/*.jsonl (逐次模型调用 message.usage)
#   Qwen Code:   ~/.qwen/usage/token-usage-*.jsonl (逐请求,usage_record.jsonl 补历史)

import os
import sys
import glob
import json
import re
from datetime import datetime, timedelta, date
from pathlib import Path

HOME = os.path.expanduser("~")
APPDATA = os.environ.get("APPDATA") or os.path.join(HOME, "AppData", "Roaming")
LOCALAPPDATA = os.environ.get("LOCALAPPDATA") or os.path.join(HOME, "AppData", "Local")


def _expand_path(path):
    if not path:
        return None
    value = os.fspath(path).strip()
    return os.path.abspath(os.path.expandvars(os.path.expanduser(value))) if value else None


def _path_candidates(env_name, *defaults):
    values = []
    configured = os.environ.get(env_name, "")
    if configured:
        values.extend(configured.split(os.pathsep))
    values.extend(defaults)
    result = []
    seen = set()
    for value in values:
        path = _expand_path(value)
        if not path:
            continue
        key = os.path.normcase(os.path.realpath(path))
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def _first_existing_file(paths):
    return next((path for path in paths if os.path.isfile(path)), None)


def _existing_dirs(paths):
    result = []
    seen = set()
    for path in paths:
        if not os.path.isdir(path):
            continue
        real = os.path.realpath(path)
        key = os.path.normcase(real)
        if key not in seen:
            seen.add(key)
            result.append(real)
    return result


CLAUDE_DIR = os.path.join(HOME, ".claude", "projects")
CODEX_DIR = os.path.join(HOME, ".codex", "sessions")
CODEX_AUTH = os.path.join(HOME, ".codex", "auth.json")
GEMINI_DIR = os.path.join(HOME, ".gemini", "tmp")
GEMINI_DIRS = _path_candidates(
    "TOKEI_GEMINI_DIR", GEMINI_DIR,
    os.path.join(HOME, ".gemini", "gemini-cli", "conversations"))
GROK_HOME = os.path.abspath(os.path.expanduser(
    os.environ.get("GROK_HOME", os.path.join(HOME, ".grok"))))
GROK_DIR = os.path.join(GROK_HOME, "sessions")
GROK_LOG = os.path.join(GROK_HOME, "logs", "unified.jsonl")
WORKBUDDY_DIR = os.path.join(HOME, ".workbuddy", "projects")
QODER_IDE_DB = os.path.join(HOME, "Library", "Application Support", "Qoder",
                            "SharedClientCache", "cache", "db", "local.db")
QODER_IDE_DB_PATHS = _path_candidates(
    "TOKEI_QODER_IDE_DB", QODER_IDE_DB,
    os.path.join(APPDATA, "Qoder", "SharedClientCache", "cache", "db", "local.db"),
    os.path.join(LOCALAPPDATA, "Qoder", "SharedClientCache", "cache", "db", "local.db"))


def _qoder_ide_db_path():
    return _first_existing_file(
        _path_candidates("TOKEI_QODER_IDE_DB", QODER_IDE_DB, *QODER_IDE_DB_PATHS))


HERMES_DB = os.path.join(HOME, ".hermes", "state.db")
OPENCODE_DATA_DIR = os.path.expanduser(os.environ.get(
    "OPENCODE_DATA_DIR", os.path.join(HOME, ".local", "share", "opencode")))
OPENCODE_DIR = os.path.join(OPENCODE_DATA_DIR, "storage", "message")
OPENCODE_DB = os.path.join(OPENCODE_DATA_DIR, "opencode.db")
OPENCODE_DATA_DIRS = _path_candidates(
    "TOKEI_OPENCODE_DATA_DIR", OPENCODE_DATA_DIR,
    os.path.join(APPDATA, "opencode"), os.path.join(LOCALAPPDATA, "opencode"))
ZCODE_DB = os.path.abspath(os.path.expanduser(os.environ.get(
    "TOKEI_ZCODE_DB", os.path.join(HOME, ".zcode", "cli", "db", "db.sqlite"))))
MIMOCODE_DB = os.path.abspath(os.path.expanduser(os.environ.get("TOKEI_MIMOCODE_DB", ""))) \
    if os.environ.get("TOKEI_MIMOCODE_DB") else ""
OPENCLAW_DB = os.path.join(HOME, ".openclaw", "tasks", "runs.sqlite")
OPENCLAW_AGENTS = os.path.join(HOME, ".openclaw", "agents")
PI_AGENT_DIR = os.path.expanduser(os.environ.get("PI_CODING_AGENT_DIR", os.path.join(HOME, ".pi", "agent")))
PI_SESSION_DIR = os.path.expanduser(os.environ.get("PI_CODING_AGENT_SESSION_DIR", os.path.join(PI_AGENT_DIR, "sessions")))
OMP_SESSION_DIR = os.path.expanduser(os.environ.get(
    "OMP_CODING_AGENT_SESSION_DIR", os.path.join(HOME, ".omp", "agent", "sessions")))
QWEN_CODE_DIR = os.path.abspath(os.path.expanduser(
    os.environ.get("QWEN_HOME", os.path.join(HOME, ".qwen"))))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_USER_DIR = os.path.join(HOME, ".tokei")

def _writable_path(name):
    """优先用 ~/.tokei/ 下的可写副本,没有则用脚本同目录(开发模式)。"""
    user = os.path.join(_USER_DIR, name)
    if os.path.isfile(user):
        return user
    base = os.path.join(BASE_DIR, name)
    if os.path.isfile(base):
        if ".app/" in BASE_DIR:
            os.makedirs(_USER_DIR, exist_ok=True)
            import shutil; shutil.copy2(base, user)
            return user
        return base
    return os.path.join(_USER_DIR, name)

PRICING_FILE = _writable_path("pricing.json")
OVERRIDES_FILE = _writable_path("pricing_overrides.json")
CODEX_QUOTA_CACHE = _writable_path("codex_quota_cache.json")

# 每 1M token 美元单价。基准价来自 OpenRouter,外置在 pricing.json(由 --update-prices 同步);
# pricing_overrides.json 做本地修正(write1h / 别名 / 缺漏),一键更新不覆盖它。
# write5m / write1h = 5 分钟 / 1 小时 缓存写入价(OpenRouter 只给一档 cache_write=5m,
# Anthropic 的 1h 写派生为 2×输入价)。

# 内置兜底:pricing.json 缺失时仍能离线工作(口径与 OpenRouter 一致)。
_DEFAULT_PRICES = {
    "anthropic/claude-opus-4.8":     {"in": 5.0,   "out": 25.0, "cache_read": 0.5,    "cache_write": 6.25},
    "anthropic/claude-sonnet-4.6":   {"in": 3.0,   "out": 15.0, "cache_read": 0.3,    "cache_write": 3.75},
    "anthropic/claude-haiku-4.5":    {"in": 1.0,   "out": 5.0,  "cache_read": 0.1,    "cache_write": 1.25},
    "openai/gpt-5.5":                {"in": 5.0,   "out": 30.0, "cache_read": 0.5,    "cache_write": 0.0},
    "qwen/qwen3.7-max":              {"in": 1.25,  "out": 3.75, "cache_read": 0.25,   "cache_write": 1.5625},
    "deepseek/deepseek-v4-pro":      {"in": 0.435, "out": 0.87, "cache_read": 0.0036, "cache_write": 0.0},
    "google/gemini-3.5-flash":       {"in": 1.5,   "out": 9.0,  "cache_read": 0.15,   "cache_write": 0.0833},
    "google/gemini-3.1-pro-preview": {"in": 2.0,   "out": 12.0, "cache_read": 0.2,    "cache_write": 0.375},
    "tencent/hy3":                   {"in": 0.14,  "out": 0.58, "cache_read": 0.035,  "cache_write": 0.0},
    "tencent/hy3-preview":           {"in": 0.063, "out": 0.21, "cache_read": 0.021,  "cache_write": 0.0},
}


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


_PRICING_DB = _load_json(PRICING_FILE, {}).get("models", {})
_OVERRIDES = _load_json(OVERRIDES_FILE, {})
_OV_MODELS = _OVERRIDES.get("models", {})
_OV_ALIASES = _OVERRIDES.get("aliases", {})

# 家族关键字 → 代表性 canonical id(精确匹配失败时回退)。
_FAMILY = [
    ("opus",     "anthropic/claude-opus-4.8"),
    ("sonnet",   "anthropic/claude-sonnet-4.6"),
    ("haiku",    "anthropic/claude-haiku-4.5"),
    ("gpt-5",    "openai/gpt-5.5"),
    ("qwen",     "qwen/qwen3.7-max"),
    ("deepseek", "deepseek/deepseek-v4-pro"),
    ("glm",      "z-ai/glm-5.2"),
    ("mimo",     "xiaomi/mimo-v2.5-pro"),
    ("hy3",      "tencent/hy3"),
]


def _normalize(model: str):
    """本地 model 名 → OpenRouter canonical id。免费档去 :free 按基础价;preview 后缀保留。"""
    m = (model or "").strip().lower()
    if not m or m == "<synthetic>":
        return None
    m = re.sub(r"\s+", "-", m)
    m = re.sub(r"[:\-]free$", "", m)                  # 免费档按基础价
    if "/" in m:
        return m                                      # 已是 OpenRouter 格式
    if m.startswith("claude"):
        m = re.sub(r"-(\d+)-(\d+)$", r"-\1.\2", m)    # claude-opus-4-8 → claude-opus-4.8
        return "anthropic/" + m
    if re.match(r"(gpt|o\d|chatgpt)", m):
        return "openai/" + m
    if m.startswith("gemini"):
        return "google/" + m
    if m.startswith("grok"):
        return "x-ai/" + m
    if m.startswith("qwen"):
        return "qwen/" + m
    if m.startswith("deepseek"):
        return "deepseek/" + m
    if m.startswith("glm"):
        return "z-ai/" + m
    if m.startswith("mimo"):
        return "xiaomi/" + m
    if m == "hy3":
        return "tencent/hy3"
    if m in ("hy3-preview", "hy3 preview"):
        return "tencent/hy3-preview"
    return m


def _resolve_id(model: str):
    """解析到 canonical id;未知按 opus 兜底(偏保守)。<synthetic> 返回 None。"""
    s = (model or "").strip()
    if not s or s.lower() == "<synthetic>":
        return None
    if s in _OV_ALIASES:
        return _OV_ALIASES[s]
    norm = _normalize(model)
    if norm and (norm in _OV_MODELS or norm in _PRICING_DB or norm in _DEFAULT_PRICES):
        return norm
    low = s.lower()
    if "gemini" in low:                               # gemini 版本繁多,按 pro/flash 粗分回退
        return "google/gemini-3.1-pro-preview" if "pro" in low else "google/gemini-3.5-flash"
    for kw, rep in _FAMILY:
        if kw in low:
            return rep
    return "anthropic/claude-opus-4.8"


def _known_id_or_raw(model: str):
    """Return a canonical priced ID when known, preserving unknown model names."""
    s = (model or "").strip()
    if not s or s.lower() == "<synthetic>":
        return None
    if s in _OV_ALIASES:
        return _OV_ALIASES[s]
    norm = _normalize(s)
    if norm and (norm in _OV_MODELS or norm in _PRICING_DB or norm in _DEFAULT_PRICES):
        return norm
    low = s.lower()
    if "gemini" in low:
        return "google/gemini-3.1-pro-preview" if "pro" in low else "google/gemini-3.5-flash"
    for keyword, representative in _FAMILY:
        if keyword in low:
            return representative
    return s


def _has_known_price(model: str):
    return _pricing_id(model) is not None


def _pricing_id(model: str):
    canonical = _known_id_or_raw(model)
    if canonical and (canonical in _OV_MODELS or canonical in _PRICING_DB or canonical in _DEFAULT_PRICES):
        return canonical
    # ZCode currently reports GLM-5.2, whose public price is not listed yet.
    # Use the documented GLM-5.1 equivalent until the pricing feed adds 5.2.
    normalized = _normalize(model)
    if normalized == "z-ai/glm-5.2" and "z-ai/glm-5.1" in _PRICING_DB:
        return "z-ai/glm-5.1"
    return None


def _raw_price(model: str):
    """统一查价 → {in,out,cache_read,cache_write,write1h?}。<synthetic>→全 0。"""
    cid = _resolve_id(model)
    if cid is None:
        return {"in": 0.0, "out": 0.0, "cache_read": 0.0, "cache_write": 0.0}
    p = dict(_DEFAULT_PRICES.get(cid, {}))            # 内置兜底打底
    p.update(_PRICING_DB.get(cid, {}))                # OpenRouter 基准
    p.update(_OV_MODELS.get(cid, {}))                 # 本地覆盖优先
    out = {"in": p.get("in", 0.0), "out": p.get("out", 0.0),
           "cache_read": p.get("cache_read", 0.0), "cache_write": p.get("cache_write", 0.0)}
    if "write1h" in p:
        out["write1h"] = p["write1h"]
    elif cid.startswith("anthropic/"):                # Anthropic 1h 写 = 2×输入价
        out["write1h"] = out["in"] * 2
    return out


def price_for(model: str):
    """Claude 成本用:补 write5m/write1h 两档(write5m = OpenRouter cache_write)。"""
    p = _raw_price(model)
    return {"in": p["in"], "out": p["out"], "cache_read": p["cache_read"],
            "write5m": p["cache_write"], "write1h": p.get("write1h", p["cache_write"])}


def gemini_price(model: str):
    """Gemini 成本用:in/out/cache_read 取统一查价(OpenRouter 已分版本,比正则更准)。"""
    return _raw_price(model)


RANGE_KEYS = ["today", "yesterday", "week", "last_week", "month", "year", "all"]
TOKEN_FIELDS = ("in", "out", "cr", "cw", "reason")


def nice_model(m: str) -> str:
    """claude-opus-4-7 → Opus 4.7;<synthetic> → 合成;其它去前缀/-free 后美化。"""
    if not m or m == "<synthetic>":
        return "合成"
    import re
    s = m.lower()
    for key, disp in (("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku")):
        if key in s:
            mt = re.search(r"(\d+)-(\d+)", s)
            return f"{disp} {mt.group(1)}.{mt.group(2)}" if mt else disp
    if "gpt" in s:
        mt = re.search(r"gpt[- ]?(\d+(?:\.\d+)?)", s)
        version = mt.group(1) if mt else ""
        suffix = " Mini" if "mini" in s else ""
        return f"GPT-{version}{suffix}" if version else "GPT"
    if "mimo" in s:
        name = m.split("/")[-1]
        version = re.sub(r"^mimo[- ]?v?", "", name, flags=re.I).strip()
        parts = [part for part in version.split("-") if part]
        if not parts:
            return "MiMo"
        head = "MiMo-V" + parts[0] if parts[0][0].isdigit() else "MiMo-" + parts[0]
        return "-".join([head] + [part.capitalize() for part in parts[1:]])
    name = re.sub(r"[-:](free|preview|latest)$", "", m.split("/")[-1]).replace("-", " ")
    return " ".join(w[:1].upper() + w[1:] if w[:1].isalpha() else w
                    for w in name.split())


def range_bounds():
    """返回今日/昨日/本周(周一起)/本月(1号起)/本年(1月1日起)的本地起点。"""
    now = datetime.now().astimezone()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    week = today - timedelta(days=today.weekday())   # 周一 0
    last_week_start = week - timedelta(days=7)       # 上周一
    month = today.replace(day=1)
    year = today.replace(month=1, day=1)
    return {"today": today, "yesterday": yesterday, "week": week,
            "last_week": last_week_start, "last_week_end": week, "month": month, "year": year}


def range_boundaries():
    """同步用:明确每个相对时间范围的日期边界,避免设备间按过期 range 误合并。"""
    b = range_bounds()
    next_month = (b["month"].replace(day=28) + timedelta(days=4)).replace(day=1)
    next_year = b["year"].replace(year=b["year"].year + 1)

    def day_s(dt):
        return dt.date().isoformat()

    return {
        "today": {"start": day_s(b["today"]), "end": day_s(b["today"] + timedelta(days=1))},
        "yesterday": {"start": day_s(b["yesterday"]), "end": day_s(b["today"])},
        "week": {"start": day_s(b["week"]), "end": day_s(b["week"] + timedelta(days=7))},
        "last_week": {"start": day_s(b["last_week"]), "end": day_s(b["week"])},
        "month": {"start": day_s(b["month"]), "end": day_s(next_month)},
        "year": {"start": day_s(b["year"]), "end": day_s(next_year)},
        "all": {"start": None, "end": None},
    }


def classify(dt, b):
    """给定本地化 dt,返回它命中的区间 key 列表(今日同时属本周/本月/本年)。"""
    return classify_date(dt.date(), b)


def classify_date(d, b):
    """给定本地日期,返回它命中的区间 key 列表。"""
    ks = ["all"]
    if d == b["today"].date():
        ks.append("today")
    if d == b["yesterday"].date():
        ks.append("yesterday")
    if d >= b["week"].date():
        ks.append("week")
    if b["last_week"].date() <= d < b["last_week_end"].date():
        ks.append("last_week")
    if d >= b["month"].date():
        ks.append("month")
    if d >= b["year"].date():
        ks.append("year")
    return ks


def parse_ts(s: str):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def human(n: float) -> str:
    n = float(n)
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}K"
    return f"{n:.0f}"


# ---------- 增量扫描缓存 ----------
import tempfile as _tempfile
_SCAN_CACHE_FILE = os.path.join(_tempfile.gettempdir(), "_tokei_scan_cache.json")
_SCAN_CACHE_VERSION = 17


def _load_scan_cache():
    try:
        with open(_SCAN_CACHE_FILE, "r") as f:
            c = json.load(f)
        if c.get("v") != _SCAN_CACHE_VERSION:
            return {"v": _SCAN_CACHE_VERSION, "_dirty": True}
        c["_keys"] = {k for k in c if not k.startswith("_")}
        c["_dirty"] = False
        return c
    except Exception:
        return {"v": _SCAN_CACHE_VERSION, "_dirty": True}


def _save_scan_cache(cache):
    prev_keys = cache.pop("_keys", set())
    current_keys = {k for k in cache if not k.startswith("_")}
    dirty = cache.pop("_dirty", False) or current_keys != prev_keys
    if not dirty:
        return
    cache["v"] = _SCAN_CACHE_VERSION
    tmp = None
    try:
        fd, tmp = _tempfile.mkstemp(prefix="_tokei_scan_cache.", suffix=".json",
                                    dir=os.path.dirname(_SCAN_CACHE_FILE))
        with os.fdopen(fd, "w") as f:
            json.dump(cache, f, separators=(',', ':'))
        os.replace(tmp, _SCAN_CACHE_FILE)
    except Exception:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        pass


def _empty_claude():
    ranges = {k: {"in": 0, "out": 0, "cr": 0, "cw": 0, "cost": 0.0,
                  "models": {}, "sessions": set()} for k in RANGE_KEYS}
    return {"ranges": ranges, "cur": {"in": 0, "out": 0, "cr": 0, "cw": 0, "name": "-"}}


def _empty_codex():
    ranges = {k: {"in": 0, "cached": 0, "out": 0, "reason": 0,
                  "cost": 0.0, "sessions": set(), "models": {}} for k in RANGE_KEYS}
    return {"ranges": ranges, "limits": None, "plan": None}


def _empty_gemini():
    ranges = {k: {"in": 0, "out": 0, "cached": 0, "thoughts": 0,
                  "cost": 0.0, "models": {}, "sessions": set()} for k in RANGE_KEYS}
    return {"ranges": ranges}


def _empty_grok():
    ranges = {k: {"tokens": 0, "in": 0, "out": 0, "cr": 0, "reason": 0,
                  "cost": 0.0, "models": {}, "usage_sessions": set(), "usage_calls": 0,
                  "sessions": set(), "turns": 0, "tools": 0,
                  "duration": 0, "ctx_used": 0, "ctx_window": 0, "errors": 0,
                  "cancellations": 0, "ttft_sum": 0, "response_sum": 0, "latency_count": 0}
              for k in RANGE_KEYS}
    return {"ranges": ranges, "model": None}


def _empty_qoder():
    ranges = {k: {"in": 0, "out": 0, "sessions": 0, "calls": 0, "sub_agents": 0,
                  "duration": 0, "turns": 0, "ctx_sum": 0.0, "ctx_count": 0} for k in RANGE_KEYS}
    return {"ranges": ranges, "model": None}


def _empty_hermes():
    ranges = {k: {"in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0,
                  "cost": 0.0, "sessions": 0, "models": {}} for k in RANGE_KEYS}
    return {"ranges": ranges}


def _empty_openclaw():
    ranges = {k: {"tasks": 0, "completed": 0, "failed": 0,
                  "in": 0, "out": 0, "cr": 0, "cw": 0,
                  "cost": 0.0, "sessions": set(), "models": {}} for k in RANGE_KEYS}
    return {"ranges": ranges}


def _empty_token_bucket():
    return {"in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0,
            "cost": 0.0, "sessions": set(), "models": {}}


def _empty_token_day():
    return {"in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0,
            "cost": 0.0, "models": {}, "hours": [0] * 24}


def _empty_token_ranges():
    return {k: _empty_token_bucket() for k in RANGE_KEYS}


def _empty_opencode():
    return {"ranges": _empty_token_ranges()}


def _empty_pi():
    return _empty_opencode()


def _empty_workbuddy():
    return _empty_opencode()


def _empty_qwencode():
    return _empty_opencode()


def _empty_zcode():
    return _empty_opencode()


def _empty_mimocode():
    return _empty_opencode()


def token_total(day):
    return sum(day.get(k, 0) for k in TOKEN_FIELDS)


def _sqlite_ro_uri(path):
    return Path(path).resolve().as_uri() + "?mode=ro"


def _sqlite_signature(path):
    parts = []
    for candidate in (path, path + "-wal", path + "-shm"):
        try:
            stat = os.stat(candidate)
        except OSError:
            continue
        parts.append(f"{candidate}:{stat.st_mtime_ns}:{stat.st_size}")
    return "|".join(parts) or None


def _iter_cached_token_days(tool_cache):
    for entry in tool_cache.values():
        if not isinstance(entry, dict):
            continue
        for day_key, day in entry.get("days", {}).items():
            if isinstance(day, dict):
                yield day_key, day
        day = entry.get("day")
        if isinstance(day, dict) and day.get("date"):
            yield day["date"], day


def _add_model_usage(models, model, inp=0, out=0, cr=0, cw=0, reason=0, cost=0.0):
    if not model:
        return
    mm = models.setdefault(model, {"in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0.0})
    mm["in"] += int(inp or 0); mm["out"] += int(out or 0)
    mm["cr"] += int(cr or 0); mm["cw"] += int(cw or 0); mm["reason"] += int(reason or 0)
    mm["cost"] += float(cost or 0)


def _add_token_usage(target, inp=0, out=0, cr=0, cw=0, reason=0, cost=0.0, model=None):
    target["in"] += int(inp or 0); target["out"] += int(out or 0)
    target["cr"] += int(cr or 0); target["cw"] += int(cw or 0); target["reason"] += int(reason or 0)
    target["cost"] += float(cost or 0)
    _add_model_usage(target.get("models", {}), model, inp, out, cr, cw, reason, cost)


def _merge_token_day(bucket, day, session=None):
    if session is not None:
        bucket["sessions"].add(session)
    _add_token_usage(bucket, day.get("in", 0), day.get("out", 0), day.get("cr", 0),
                     day.get("cw", 0), day.get("reason", 0), day.get("cost", 0))
    for model, mv in day.get("models", {}).items():
        _add_model_usage(bucket["models"], model, mv.get("in", 0), mv.get("out", 0),
                         mv.get("cr", 0), mv.get("cw", 0), mv.get("reason", 0), mv.get("cost", 0))


def _format_token_models(models, include_prices=True):
    result = []
    for n, v in sorted(models.items(), key=lambda kv: -kv[1].get("cost", 0)):
        price_id = _pricing_id(n) if include_prices else None
        p = _raw_price(price_id) if price_id else {
            "in": 0.0, "out": 0.0, "cache_read": 0.0, "cache_write": 0.0}
        result.append({"name": nice_model(n), "in": v.get("in", 0), "out": v.get("out", 0),
                        "cr": v.get("cr", 0), "cw": v.get("cw", 0), "reason": v.get("reason", 0),
                        "cost": v.get("cost", 0), "pin": p["in"], "pout": p["out"]})
    return result


def _safe_scan(name, fn, fallback, errors):
    try:
        return fn()
    except Exception as e:
        errors[name] = f"{type(e).__name__}: {e}"
        return fallback()


# ---------- Claude Code ----------
def _claude_event_total(event):
    return sum(int(event.get(key, 0) or 0) for key in ("in", "out", "cr", "cw"))


def _prefer_claude_event(candidate, existing):
    candidate_sidechain = bool(candidate.get("sidechain"))
    existing_sidechain = bool(existing.get("sidechain"))
    if candidate_sidechain != existing_sidechain:
        return existing_sidechain
    candidate_total = _claude_event_total(candidate)
    existing_total = _claude_event_total(existing)
    if candidate_total != existing_total:
        return candidate_total > existing_total
    return float(candidate.get("cost", 0) or 0) > float(existing.get("cost", 0) or 0)


def _dedupe_claude_events(file_events):
    selected = []
    exact = {}
    by_message = {}

    for source, event in file_events:
        message_id = event.get("mid")
        request_id = event.get("request_id")
        index = None
        exact_key = None
        if message_id:
            exact_key = ("message", message_id, request_id)
            index = exact.get(exact_key)
            if index is None:
                for candidate_index in by_message.get(message_id, []):
                    existing = selected[candidate_index][1]
                    if event.get("sidechain") or existing.get("sidechain"):
                        index = candidate_index
                        break
        elif event.get("event_id"):
            exact_key = ("event", event["event_id"])
            index = exact.get(exact_key)

        if index is not None:
            if _prefer_claude_event(event, selected[index][1]):
                selected[index] = (source, event)
                if exact_key is not None:
                    exact[exact_key] = index
            continue

        index = len(selected)
        selected.append((source, event))
        if exact_key is not None:
            exact[exact_key] = index
        if message_id:
            by_message.setdefault(message_id, []).append(index)
    return selected


def scan_claude(bounds, cache):
    fc = cache.setdefault("claude", {})
    changed = False
    B = {k: {"in": 0, "out": 0, "cr": 0, "cw": 0, "cost": 0.0, "models": {}, "sessions": set()}
         for k in RANGE_KEYS}
    cur_file, cur_mtime = None, -1.0
    if not os.path.isdir(CLAUDE_DIR):
        if fc:
            fc.clear()
            cache["_dirty"] = True
        return {"ranges": B, "cur": {"in": 0, "out": 0, "cr": 0, "cw": 0, "name": "-"}}

    today_d = bounds["today"].date()
    yest_d = bounds["yesterday"].date()
    week_d = bounds["week"].date()
    lw_start_d = bounds["last_week"].date()
    lw_end_d = bounds["last_week_end"].date()
    month_d = bounds["month"].date()
    year_d = bounds["year"].date()

    stale = set(fc.keys())

    for f in glob.glob(os.path.join(CLAUDE_DIR, "**", "*.jsonl"), recursive=True):
        stale.discard(f)
        try:
            st = os.stat(f)
        except OSError:
            continue
        mtime, size = st.st_mtime, st.st_size
        if mtime > cur_mtime:
            cur_mtime = mtime
            cur_file = f
        sig = f"{mtime}:{size}"
        entry = fc.get(f)
        if not entry or entry.get("sig") != sig:
            events = []
            proj = None
            try:
                with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                    for line_number, line in enumerate(fh, 1):
                        if '"usage"' not in line:
                            continue
                        u = _claude_usage(line, want_dt=True)
                        if not u:
                            continue
                        events.append({
                            "in": u["in"], "out": u["out"], "cr": u["cr"], "cw": u["cw"],
                            "cost": u["cost"], "model": u.get("model") or "unknown",
                            "cwd": u.get("cwd"), "mid": u.get("mid"),
                            "request_id": u.get("request_id"), "event_id": u.get("event_id"),
                            "sidechain": bool(u.get("sidechain")), "timestamp": u["dt"].isoformat(),
                            "line": line_number,
                        })
                        if proj is None and u.get("cwd"):
                            proj = u["cwd"]
            except OSError:
                continue
            events = [event for _, event in _dedupe_claude_events((f, item) for item in events)]
            fc[f] = {"sig": sig, "events": events, "proj": proj}
            changed = True

    for p in stale:
        fc.pop(p, None)
        changed = True

    all_events = []
    for path, entry in fc.items():
        for event in entry.get("events", []):
            all_events.append((path, event))
    selected_events = _dedupe_claude_events(all_events)

    aggregates = {
        path: {"days": {}, "hours": [0] * 24, "day_hours": {}, "dh": set(),
               "proj": entry.get("proj")}
        for path, entry in fc.items()
    }
    for path, event in selected_events:
        dt = parse_ts(event.get("timestamp", ""))
        if dt is None:
            continue
        dt = dt.astimezone()
        day_key = dt.date().isoformat()
        aggregate = aggregates[path]
        if not aggregate["proj"] and event.get("cwd"):
            aggregate["proj"] = event["cwd"]
        day = aggregate["days"].setdefault(
            day_key, {"in": 0, "out": 0, "cr": 0, "cw": 0, "cost": 0.0, "models": {}})
        day["in"] += event["in"]; day["out"] += event["out"]
        day["cr"] += event["cr"]; day["cw"] += event["cw"]
        day["cost"] += event["cost"]
        model = event.get("model") or "unknown"
        model_usage = day["models"].setdefault(
            model, {"in": 0, "out": 0, "cr": 0, "cw": 0, "cost": 0.0})
        model_usage["in"] += event["in"]; model_usage["out"] += event["out"]
        model_usage["cr"] += event["cr"]; model_usage["cw"] += event["cw"]
        model_usage["cost"] += event["cost"]
        amount = _claude_event_total(event)
        aggregate["hours"][dt.hour] += amount
        aggregate["day_hours"].setdefault(day_key, [0] * 24)[dt.hour] += amount
        aggregate["dh"].add(f"{day_key}:{dt.hour}")

    for path, aggregate in aggregates.items():
        entry = fc[path]
        values = {
            "days": aggregate["days"], "hours": aggregate["hours"],
            "day_hours": aggregate["day_hours"], "dh": sorted(aggregate["dh"]),
            "proj": aggregate["proj"],
        }
        for key, value in values.items():
            if entry.get(key) != value:
                entry[key] = value
                changed = True

    if changed:
        cache["_dirty"] = True

    # Assembly: per-day → range buckets
    for f, entry in fc.items():
        for dk, day in entry.get("days", {}).items():
            d = date.fromisoformat(dk)
            ks = ["all"]
            if d == today_d: ks.append("today")
            if d == yest_d: ks.append("yesterday")
            if d >= week_d: ks.append("week")
            if lw_start_d <= d < lw_end_d: ks.append("last_week")
            if d >= month_d: ks.append("month")
            if d >= year_d: ks.append("year")
            if not ks:
                continue
            for k in ks:
                b = B[k]
                b["sessions"].add(f)
                b["in"] += day["in"]; b["out"] += day["out"]
                b["cr"] += day["cr"]; b["cw"] += day["cw"]; b["cost"] += day["cost"]
                for mn, mv in day["models"].items():
                    mm = b["models"].setdefault(mn, {"in": 0, "out": 0, "cr": 0, "cw": 0, "cost": 0.0})
                    mm["in"] += mv["in"]; mm["out"] += mv["out"]
                    mm["cr"] += mv["cr"]; mm["cw"] += mv["cw"]; mm["cost"] += mv["cost"]

    # Current session: sum all days of the most recently modified file
    cur_in = cur_out = cur_cr = cur_cw = 0
    if cur_file:
        entry = fc.get(cur_file)
        if entry:
            for day in entry.get("days", {}).values():
                cur_in += day["in"]; cur_out += day["out"]
                cur_cr += day["cr"]; cur_cw += day["cw"]

    return {
        "ranges": B,
        "cur": {"in": cur_in, "out": cur_out, "cr": cur_cr, "cw": cur_cw,
                "name": os.path.basename(cur_file)[:8] if cur_file else "-"},
    }


def _claude_usage(line, want_dt=False):
    try:
        o = json.loads(line)
    except Exception:
        return None
    if o.get("type") != "assistant":
        return None
    dt = None
    if want_dt:
        # timestamp 是 UTC,转本地用于区间归类
        dt = parse_ts(o.get("timestamp", ""))
        if dt is None:
            return None
        dt = dt.astimezone()
    msg = o.get("message", {})
    u = msg.get("usage")
    if not u:
        return None
    inp = u.get("input_tokens", 0) or 0
    out = u.get("output_tokens", 0) or 0
    cr = u.get("cache_read_input_tokens", 0) or 0
    cw = u.get("cache_creation_input_tokens", 0) or 0
    p = price_for(msg.get("model"))
    cc = u.get("cache_creation") or {}
    w5 = cc.get("ephemeral_5m_input_tokens")
    w1 = cc.get("ephemeral_1h_input_tokens")
    if w5 is None and w1 is None:
        write_cost = cw / 1e6 * p["write5m"]
    else:
        write_cost = (w5 or 0) / 1e6 * p["write5m"] + (w1 or 0) / 1e6 * p["write1h"]
    cost = inp / 1e6 * p["in"] + out / 1e6 * p["out"] + cr / 1e6 * p["cache_read"] + write_cost
    res = {"in": inp, "out": out, "cr": cr, "cw": cw, "cost": cost,
           "model": msg.get("model"), "cwd": o.get("cwd"), "mid": msg.get("id"),
           "request_id": o.get("requestId") or o.get("request_id"),
           "event_id": o.get("uuid"), "sidechain": o.get("isSidechain") is True}
    if want_dt:
        res["dt"] = dt
    return res


# ---------- Codex ----------
_CODEX_QUOTA_TTL = 30
_CODEX_QUOTA_FALLBACK_TTL = 300


def _atomic_write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _window_from_codex_live(window):
    if not isinstance(window, dict):
        return None
    used = window.get("used_percent")
    reset_at = window.get("reset_at")
    reset_after = window.get("reset_after_seconds")
    if reset_at is None and reset_after is not None:
        reset_at = int(datetime.now().timestamp() + float(reset_after))
    out = {}
    if used is not None:
        out["used_percent"] = float(used)
    if window.get("limit_window_seconds") is not None:
        out["window_minutes"] = int(round(float(window["limit_window_seconds"]) / 60))
    if reset_at is not None:
        out["resets_at"] = int(reset_at)
    return out or None


def _codex_live_to_limits(data):
    rl = (data or {}).get("rate_limit") or {}
    primary = _window_from_codex_live(rl.get("primary_window"))
    secondary = _window_from_codex_live(rl.get("secondary_window"))
    if not primary and not secondary:
        return None
    return {
        "limit_id": "codex",
        "limit_name": None,
        "primary": primary,
        "secondary": secondary,
        "credits": data.get("credits"),
        "plan_type": data.get("plan_type"),
        "rate_limit_reached_type": rl.get("rate_limit_reached_type"),
    }


def _cached_codex_live_limits(max_age):
    cached = _load_json(CODEX_QUOTA_CACHE, {})
    fetched_at = cached.get("fetched_at")
    limits = cached.get("limits")
    if not fetched_at or not limits:
        return None
    if datetime.now().timestamp() - float(fetched_at) > max_age:
        return None
    return limits, cached.get("plan")


def fetch_codex_live_limits():
    if os.environ.get("TOKEI_CODEX_LIVE_QUOTA") == "0":
        return None
    cached = _cached_codex_live_limits(_CODEX_QUOTA_TTL)
    if cached:
        return cached
    auth = _load_json(CODEX_AUTH, {})
    tokens = auth.get("tokens") or {}
    access_token = tokens.get("access_token")
    if not access_token:
        return _cached_codex_live_limits(_CODEX_QUOTA_FALLBACK_TTL)
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://chatgpt.com/backend-api/wham/usage",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "User-Agent": "Tokei",
            },
        )
        account_id = tokens.get("account_id")
        if account_id:
            req.add_header("ChatGPT-Account-Id", account_id)
        with urllib.request.urlopen(req, timeout=3) as res:
            data = json.load(res)
        limits = _codex_live_to_limits(data)
        if not limits:
            return _cached_codex_live_limits(_CODEX_QUOTA_FALLBACK_TTL)
        plan = data.get("plan_type")
        _atomic_write_json(CODEX_QUOTA_CACHE, {
            "fetched_at": datetime.now().timestamp(),
            "limits": limits,
            "plan": plan,
        })
        return limits, plan
    except Exception:
        return _cached_codex_live_limits(_CODEX_QUOTA_FALLBACK_TTL)


def _codex_event_key(event):
    if not isinstance(event, list) or len(event) < 11:
        return None
    total_values = event[2:6]
    if not all(value is not None for value in total_values):
        return None
    return tuple(event[2:10])


def _codex_add_event(days, event):
    dk = event[1]
    li, lc, lo, lr, cost = event[6:11]
    day = days.setdefault(dk, {"in": 0, "cached": 0, "out": 0,
                               "reason": 0, "cost": 0.0, "models": {}, "hours": [0] * 24})
    day["in"] += li
    day["cached"] += lc
    day["out"] += lo
    day["reason"] += lr
    day["cost"] += cost
    model = event[11] if len(event) > 11 else None
    _add_model_usage(day["models"], model, max(li - lc, 0), lo, lc, 0, lr, cost)
    try:
        hour = datetime.fromisoformat(event[0]).astimezone().hour
        day["hours"][hour] += li + lo
    except (TypeError, ValueError):
        pass


def _codex_prefix_match_count(child_events, parent_events):
    n = 0
    while n < len(child_events) and n < len(parent_events):
        child_key = _codex_event_key(child_events[n])
        parent_key = _codex_event_key(parent_events[n])
        if child_key is None or child_key != parent_key:
            break
        n += 1
    return n


def _codex_replayed_event_indexes(file_cache):
    by_sid = {}
    ordered = []
    for file_path, entry in file_cache.items():
        events = entry.get("events") or []
        if events:
            ordered.append((file_path, entry))
        sid = entry.get("session_id")
        if sid:
            by_sid[sid] = (file_path, entry)

    drops = {}
    for file_path, entry in ordered:
        parent = by_sid.get(entry.get("forked_from_id"))
        if not parent or parent[0] == file_path:
            continue
        n = _codex_prefix_match_count(entry.get("events") or [], parent[1].get("events") or [])
        if n:
            drops.setdefault(file_path, set()).update(range(n))

    # Some Codex replay files do not carry fork metadata. Only use this
    # heuristic for longer matching prefixes; a one-event match can be a real
    # independent session with the same usage numbers.
    for file_path, entry in ordered:
        if drops.get(file_path):
            continue
        child_events = entry.get("events") or []
        if not child_events:
            continue
        child_first_ts = child_events[0][0]
        best = 0
        for parent_path, parent_entry in ordered:
            if parent_path == file_path:
                continue
            parent_events = parent_entry.get("events") or []
            if not parent_events or parent_events[0][0] >= child_first_ts:
                continue
            best = max(best, _codex_prefix_match_count(child_events, parent_events))
        if best >= 2:
            drops.setdefault(file_path, set()).update(range(best))
    return drops


def _codex_deduped_days(file_cache):
    """Return per-file daily usage after removing copied rollout prefixes."""
    drops = _codex_replayed_event_indexes(file_cache)
    days_by_file = {}
    for file_path, entry in file_cache.items():
        skip = drops.get(file_path, set())
        for event_index, event in enumerate(entry.get("events", [])):
            if event_index in skip or _codex_event_key(event) is None:
                if event_index in skip:
                    continue
                if not isinstance(event, list) or len(event) < 11:
                    continue
            _codex_add_event(days_by_file.setdefault(file_path, {}), event)
    return days_by_file


_CODEX_TOKEN_EVENT_HEADER = re.compile(
    rb'^\s*\{\s*"timestamp"\s*:\s*"[^"]+"\s*,\s*'
    rb'"type"\s*:\s*"event_msg"\s*,\s*'
    rb'"payload"\s*:\s*\{\s*"type"\s*:\s*"token_count"'
)
_CODEX_MODEL_RECORD_HEADER = re.compile(
    rb'^\s*\{\s*"timestamp"\s*:\s*"[^"]+"\s*,\s*'
    rb'"type"\s*:\s*"(?:turn_context|session_meta)"'
)
_CODEX_MODEL_FIELD = re.compile(rb'"model"\s*:\s*"((?:\\.|[^"\\])*)"')


def _iter_codex_usage_records(path, chunk_size=64 * 1024, header_limit=1024,
                              model_limit=4 * 1024):
    """Yield model changes and token records without buffering unrelated large JSONL lines."""
    prefix = bytearray()
    candidate = None
    kind = None

    with open(path, "rb", buffering=0) as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break

            start = 0
            while start < len(chunk):
                newline = chunk.find(b"\n", start)
                end = len(chunk) if newline < 0 else newline
                piece = memoryview(chunk)[start:end]

                if kind == "token":
                    candidate.extend(piece)
                elif kind == "model":
                    take = min(len(piece), model_limit - len(prefix))
                    prefix.extend(piece[:take])
                    match = _CODEX_MODEL_FIELD.search(prefix) if b'"model"' in prefix else None
                    if match:
                        raw_model = match.group(1)
                        try:
                            model = (raw_model.decode("utf-8") if b"\\" not in raw_model
                                     else json.loads(b'"' + raw_model + b'"'))
                        except Exception:
                            model = raw_model.decode("utf-8", errors="ignore")
                        if model:
                            yield "model", model
                        prefix = bytearray()
                        kind = "ignore"
                    elif len(prefix) >= model_limit:
                        prefix = bytearray()
                        kind = "ignore"
                elif kind is None and len(prefix) < header_limit:
                    take = min(len(piece), header_limit - len(prefix))
                    prefix.extend(piece[:take])
                    if b'"token_count"' in prefix and _CODEX_TOKEN_EVENT_HEADER.search(prefix):
                        candidate = prefix
                        prefix = bytearray()
                        kind = "token"
                        if take < len(piece):
                            candidate.extend(piece[take:])
                    elif ((b'"turn_context"' in prefix or b'"session_meta"' in prefix)
                          and _CODEX_MODEL_RECORD_HEADER.search(prefix)):
                        kind = "model"
                        if take < len(piece):
                            extra = min(len(piece) - take, model_limit - len(prefix))
                            prefix.extend(piece[take:take + extra])
                        match = _CODEX_MODEL_FIELD.search(prefix) if b'"model"' in prefix else None
                        if match:
                            raw_model = match.group(1)
                            try:
                                model = (raw_model.decode("utf-8") if b"\\" not in raw_model
                                         else json.loads(b'"' + raw_model + b'"'))
                            except Exception:
                                model = raw_model.decode("utf-8", errors="ignore")
                            if model:
                                yield "model", model
                            prefix = bytearray()
                            kind = "ignore"
                    elif len(prefix) >= header_limit:
                        prefix = bytearray()
                        kind = "ignore"

                if newline < 0:
                    break

                if candidate is not None:
                    yield "token", bytes(candidate)
                prefix = bytearray()
                candidate = None
                kind = None
                start = newline + 1

    if candidate is not None:
        yield "token", bytes(candidate)


def _iter_codex_token_lines(path, chunk_size=64 * 1024, header_limit=4 * 1024):
    """Compatibility iterator for callers that only need token_count records."""
    for kind, value in _iter_codex_usage_records(path, chunk_size, header_limit):
        if kind == "token":
            yield value


def _codex_session_meta(path, max_lines=20, max_line_bytes=2 * 1024 * 1024):
    try:
        with open(path, "rb", buffering=0) as fh:
            for _ in range(max_lines):
                line = fh.readline(max_line_bytes)
                if not line:
                    break
                if b'"session_meta"' not in line:
                    continue
                try:
                    o = json.loads(line.decode("utf-8", errors="ignore"))
                except Exception:
                    continue
                if o.get("type") != "session_meta":
                    continue
                meta = o.get("payload") or {}
                parent_id = meta.get("forked_from_id") or meta.get("parent_thread_id")
                if not parent_id:
                    source = meta.get("source") or {}
                    subagent = source.get("subagent") if isinstance(source, dict) else None
                    spawn = subagent.get("thread_spawn") if isinstance(subagent, dict) else None
                    if isinstance(spawn, dict):
                        parent_id = spawn.get("parent_thread_id")
                return meta.get("id") or meta.get("session_id"), parent_id
    except OSError:
        pass
    return None, None


def scan_codex(bounds, cache):
    fc = cache.setdefault("codex", {})
    B = {k: {"in": 0, "cached": 0, "out": 0, "reason": 0, "cost": 0.0,
             "sessions": set(), "models": {}}
         for k in RANGE_KEYS}
    if not os.path.isdir(CODEX_DIR):
        if fc:
            fc.clear()
            cache["_dirty"] = True
        return {"ranges": B, "cur_total": None, "limits": None, "plan": None}

    today_d = bounds["today"].date()
    yest_d = bounds["yesterday"].date()
    week_d = bounds["week"].date()
    lw_start_d = bounds["last_week"].date()
    lw_end_d = bounds["last_week_end"].date()
    month_d = bounds["month"].date()
    year_d = bounds["year"].date()

    cur_file, cur_mtime = None, -1.0
    stale = set(fc.keys())

    for f in glob.glob(os.path.join(CODEX_DIR, "**", "rollout-*.jsonl"), recursive=True):
        stale.discard(f)
        try:
            st = os.stat(f)
        except OSError:
            continue
        mtime, size = st.st_mtime, st.st_size
        if mtime > cur_mtime:
            cur_mtime = mtime
            cur_file = f
        sig = f"{mtime}:{size}"
        entry = fc.get(f)
        if not entry or entry.get("sig") != sig or entry.get("model_version") != 1:
            events = []
            session_id, forked_from_id = _codex_session_meta(f)
            file_limits = None; file_limits_ts = None; file_plan = None
            file_g_limits = None; file_g_ts = None; file_g_plan = None
            file_last_total = None
            prev_total_key = None
            file_model = None
            try:
                for record_kind, record in _iter_codex_usage_records(f):
                    if record_kind == "model":
                        file_model = record
                        continue
                    try:
                        o = json.loads(record.decode("utf-8", errors="ignore"))
                    except Exception:
                        continue
                    info = (o.get("payload") or {}).get("info") or {}
                    last = info.get("last_token_usage") or {}
                    total = info.get("total_token_usage") or {}
                    total_key = None
                    duplicate_total = False
                    if total:
                        total_key = (total.get("input_tokens", 0) or 0,
                                     total.get("cached_input_tokens", 0) or 0,
                                     total.get("output_tokens", 0) or 0,
                                     total.get("reasoning_output_tokens", 0) or 0)
                        duplicate_total = total_key == prev_total_key
                        prev_total_key = total_key
                        file_last_total = total
                    ts = parse_ts(o.get("timestamp", ""))
                    rl = (o.get("payload") or {}).get("rate_limits")
                    if ts and rl:
                        ts_iso = ts.isoformat()
                        if file_g_ts is None or ts_iso > file_g_ts:
                            file_g_ts = ts_iso
                            file_g_limits = rl
                            file_g_plan = rl.get("plan_type")
                        if rl.get("limit_id") == "codex" and (file_limits_ts is None or ts_iso > file_limits_ts):
                            file_limits_ts = ts_iso
                            file_limits = rl
                            file_plan = rl.get("plan_type")
                    # Codex may emit the same cumulative snapshot twice; in that case
                    # last_token_usage is repeated too, so counting it again overstates usage.
                    if ts and last and not duplicate_total:
                        dk = ts.astimezone().date().isoformat()
                        li = last.get("input_tokens", 0) or 0
                        lc = last.get("cached_input_tokens", 0) or 0
                        lo = last.get("output_tokens", 0) or 0
                        lr = last.get("reasoning_output_tokens", 0) or 0
                        model = _known_id_or_raw(file_model) or "openai/gpt-5.5"
                        price_model = model if _has_known_price(model) else "openai/gpt-5.5"
                        cx_base = _raw_price(price_model)
                        hi = li > 272_000
                        p_in = cx_base["in"] * (2 if hi else 1)
                        p_out = cx_base["out"] * (1.5 if hi else 1)
                        p_cr = cx_base["cache_read"] * (2 if hi else 1)
                        cost = (li - lc) / 1e6 * p_in + lc / 1e6 * p_cr + lo / 1e6 * p_out
                        totals = total_key if total_key is not None else (None, None, None, None)
                        # timestamp, local day, cumulative usage, incremental usage, cost
                        events.append([ts.isoformat(), dk, *totals, li, lc, lo, lr, cost, model])
            except OSError:
                continue
            fc[f] = {"sig": sig, "events": events, "days": {},
                     "session_id": session_id, "forked_from_id": forked_from_id,
                     "limits": file_limits, "limits_ts": file_limits_ts, "plan": file_plan,
                     "g_limits": file_g_limits, "g_ts": file_g_ts, "g_plan": file_g_plan,
                     "last_total": file_last_total, "model_version": 1}
            cache["_dirty"] = True

    for p in stale:
        fc.pop(p, None)
        cache["_dirty"] = True

    # Forked and subagent rollouts can replay parent history. Remove copied
    # prefixes while preserving independent sessions with matching snapshots.
    days_by_file = _codex_deduped_days(fc)
    for f, entry in fc.items():
        days = days_by_file.get(f, {})
        if entry.get("days") != days:
            entry["days"] = days
            cache["_dirty"] = True

    # Assembly: per-day → range buckets
    for f, entry in fc.items():
        for dk, day in entry.get("days", {}).items():
            d = date.fromisoformat(dk)
            ks = ["all"]
            if d == today_d: ks.append("today")
            if d == yest_d: ks.append("yesterday")
            if d >= week_d: ks.append("week")
            if lw_start_d <= d < lw_end_d: ks.append("last_week")
            if d >= month_d: ks.append("month")
            if d >= year_d: ks.append("year")
            if not ks:
                continue
            for k in ks:
                b = B[k]
                b["sessions"].add(f)
                b["in"] += day["in"]; b["cached"] += day["cached"]
                b["out"] += day["out"]; b["reason"] += day["reason"]; b["cost"] += day["cost"]
                for model, usage in day.get("models", {}).items():
                    _add_model_usage(b["models"], model, usage.get("in", 0), usage.get("out", 0),
                                     usage.get("cr", 0), usage.get("cw", 0),
                                     usage.get("reason", 0), usage.get("cost", 0))

    # Find latest limits across all cached files
    latest_limits = None; latest_ts = None; plan_type = None
    g_limits = None; g_ts = None
    for entry in fc.values():
        if entry.get("limits_ts"):
            if latest_ts is None or entry["limits_ts"] > latest_ts:
                latest_ts = entry["limits_ts"]
                latest_limits = entry["limits"]
                plan_type = entry["plan"]
        if entry.get("g_ts"):
            if g_ts is None or entry["g_ts"] > g_ts:
                g_ts = entry["g_ts"]
                g_limits = entry["g_limits"]

    if latest_limits is None and g_limits is not None:
        latest_limits = g_limits
        plan_type = (g_limits or {}).get("plan_type")

    live = fetch_codex_live_limits()
    if live:
        latest_limits, live_plan = live
        plan_type = live_plan or (latest_limits or {}).get("plan_type") or plan_type

    cur_total = None
    if cur_file:
        entry = fc.get(cur_file)
        if entry:
            cur_total = entry.get("last_total")

    return {
        "ranges": B,
        "cur_total": cur_total,
        "limits": latest_limits,
        "plan": plan_type,
    }


def _codex_quota_values(limits, now_epoch=None):
    """Map Codex rate-limit slots by duration; primary/secondary roles can change."""
    values = {"p5": None, "pw": None, "r5": None, "rw": None}
    for slot_name in ("primary", "secondary"):
        slot = (limits or {}).get(slot_name) or {}
        if not slot:
            continue
        minutes = slot.get("window_minutes")
        # Older logs use primary=5h and secondary=7d. Newer plans may expose
        # the 7d window as primary with no secondary, so duration is canonical.
        is_week = minutes == 7 * 24 * 60 or (minutes is None and slot_name == "secondary")
        pct_key, reset_key = ("pw", "rw") if is_week else ("p5", "r5")
        values[pct_key] = slot.get("used_percent")
        values[reset_key] = slot.get("resets_at")

    now_epoch = now_epoch if now_epoch is not None else int(datetime.now().timestamp())
    for pct_key, reset_key in (("p5", "r5"), ("pw", "rw")):
        reset = values[reset_key]
        if reset and now_epoch > reset:
            values[pct_key] = 0.0
            values[reset_key] = None
    return values


# ---------- Gemini CLI ----------
# 日志:~/.gemini/tmp/<projectHash>/chats/{session-*.json,session-*.jsonl,<parent>/*.jsonl}
# assistant 行 type=="gemini",tokens={input,output,cached,thoughts,total}
# (total=input+output+thoughts,cached⊂input)。JSONL 是追加日志，同消息 ID 以后写入的记录覆盖之前记录。
def _gemini_session_files():
    files = []
    roots = _path_candidates("TOKEI_GEMINI_DIR", GEMINI_DIR, *GEMINI_DIRS)
    patterns = []
    for root in roots:
        patterns.extend((
            os.path.join(root, "*", "chats", "session-*.json"),
            os.path.join(root, "*", "chats", "**", "*.jsonl"),
            os.path.join(root, "**", "session-*.json"),
            os.path.join(root, "**", "session-*.jsonl"),
        ))
    for pattern in patterns:
        files.extend(glob.glob(pattern, recursive=True))
    return sorted(set(os.path.realpath(path) for path in files if os.path.isfile(path)))


def _gemini_apply_messages(message_map, messages, replace=False):
    if replace:
        message_map.clear()
    if isinstance(messages, dict):
        messages = [messages]
    if not isinstance(messages, list):
        return
    for message in messages:
        if not isinstance(message, dict):
            continue
        message_id = message.get("id")
        if message_id:
            message_map[str(message_id)] = message


def _load_gemini_usage_file(path):
    metadata = {}
    messages = {}
    rank = 2 if path.endswith(".jsonl") else 1
    try:
        if rank == 1:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                record = json.load(handle)
            if not isinstance(record, dict):
                return None
            metadata.update(record)
            _gemini_apply_messages(messages, record.get("messages"))
        else:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    try:
                        record = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(record, dict):
                        continue
                    rewind_id = record.get("$rewindTo")
                    if isinstance(rewind_id, str):
                        keys = list(messages)
                        if rewind_id in messages:
                            for message_id in keys[keys.index(rewind_id):]:
                                messages.pop(message_id, None)
                        else:
                            messages.clear()
                        continue
                    if isinstance(record.get("id"), str):
                        messages[record["id"]] = record
                        continue
                    updates = record.get("$set")
                    if isinstance(updates, dict):
                        if isinstance(updates.get("messages"), list):
                            _gemini_apply_messages(messages, updates["messages"], replace=True)
                        metadata.update(updates)
                        continue
                    pushed = record.get("$push")
                    if isinstance(pushed, dict):
                        _gemini_apply_messages(messages, pushed.get("messages"))
                        continue
                    if isinstance(record.get("sessionId"), str):
                        metadata.update(record)
                        _gemini_apply_messages(messages, record.get("messages"))
    except OSError:
        return None

    events = []
    for message_id, message in messages.items():
        tokens = message.get("tokens")
        if message.get("type") != "gemini" or not isinstance(tokens, dict):
            continue
        timestamp = message.get("timestamp")
        if not timestamp:
            continue
        events.append({
            "id": message_id,
            "timestamp": timestamp,
            "model": message.get("model") or "unknown",
            "tokens": {
                "input": int(tokens.get("input", 0) or 0),
                "output": int(tokens.get("output", 0) or 0),
                "cached": int(tokens.get("cached", 0) or 0),
                "thoughts": int(tokens.get("thoughts", 0) or 0),
            },
        })
    return {
        "sid": metadata.get("sessionId") or os.path.basename(path),
        "updated": metadata.get("lastUpdated") or "",
        "rank": rank,
        "events": events,
    }


def scan_gemini(bounds, cache):
    fc = cache.setdefault("gemini", {})
    files = _gemini_session_files()
    if not files:
        if fc:
            fc.clear()
            cache["_dirty"] = True
        return _empty_gemini()

    stale = set(fc)
    for path in files:
        stale.discard(path)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        signature = f"{stat.st_mtime_ns}:{stat.st_size}"
        entry = fc.get(path)
        if entry and entry.get("sig") == signature:
            continue
        parsed = _load_gemini_usage_file(path)
        if parsed is None:
            continue
        parsed["sig"] = signature
        parsed["mtime"] = stat.st_mtime_ns
        fc[path] = parsed
        cache["_dirty"] = True

    for path in stale:
        fc.pop(path, None)
        cache["_dirty"] = True

    sessions = {}
    for path, entry in fc.items():
        sid = entry.get("sid") or path
        score = (int(entry.get("rank", 0)), entry.get("updated") or "", int(entry.get("mtime", 0)))
        current = sessions.get(sid)
        if current is None or score > current[0]:
            sessions[sid] = (score, entry)

    days = {}
    for sid, (_, entry) in sessions.items():
        for event in entry.get("events", []):
            dt = parse_ts(event.get("timestamp", ""))
            if dt is None:
                continue
            dt = dt.astimezone()
            tokens = event.get("tokens") or {}
            model = event.get("model") or "unknown"
            inp = int(tokens.get("input", 0) or 0)
            out = int(tokens.get("output", 0) or 0)
            cached = int(tokens.get("cached", 0) or 0)
            thoughts = int(tokens.get("thoughts", 0) or 0)
            price = gemini_price(model)
            cost = (max(inp - cached, 0) / 1e6 * price["in"]
                    + cached / 1e6 * price["cache_read"]
                    + (out + thoughts) / 1e6 * price["out"])
            day_key = dt.date().isoformat()
            day = days.setdefault(
                day_key, {"in": 0, "out": 0, "cached": 0, "thoughts": 0,
                          "cost": 0.0, "models": {}, "sessions": set(), "hours": [0] * 24})
            day["in"] += inp; day["out"] += out; day["cached"] += cached
            day["thoughts"] += thoughts; day["cost"] += cost; day["sessions"].add(sid)
            day["hours"][dt.hour] += inp + out + thoughts
            model_usage = day["models"].setdefault(
                model, {"in": 0, "out": 0, "cached": 0, "thoughts": 0, "cost": 0.0})
            model_usage["in"] += inp; model_usage["out"] += out
            model_usage["cached"] += cached; model_usage["thoughts"] += thoughts
            model_usage["cost"] += cost

    B = {k: {"in": 0, "out": 0, "cached": 0, "thoughts": 0, "cost": 0.0,
             "models": {}, "sessions": set()}
         for k in RANGE_KEYS}
    for dk, day in days.items():
        try:
            d = date.fromisoformat(dk)
        except ValueError:
            continue
        for key in classify_date(d, bounds):
            bucket = B[key]
            bucket["sessions"].update(day.get("sessions", set()))
            bucket["in"] += day.get("in", 0); bucket["out"] += day.get("out", 0)
            bucket["cached"] += day.get("cached", 0)
            bucket["thoughts"] += day.get("thoughts", 0); bucket["cost"] += day.get("cost", 0)
            for model, usage in day.get("models", {}).items():
                model_usage = bucket["models"].setdefault(
                    model, {"in": 0, "out": 0, "cached": 0,
                            "thoughts": 0, "cost": 0.0})
                for field in ("in", "out", "cached", "thoughts"):
                    model_usage[field] += usage.get(field, 0)
                model_usage["cost"] += usage.get("cost", 0)
    return {"ranges": B}


# ---------- Grok Build ----------
# 日志:~/.grok/sessions/<cwd>/<uuid>/{summary.json,signals.json,events.jsonl,updates.jsonl}
# Grok Build TUI 会把每次推理的真实 token 记入 logs/unified.jsonl；会话目录提供模型、
# 项目、上下文和运行指标。OAuth/订阅路径通常不落完整成本，因此只统计 token，不估价。
def _grok_log_signature(path):
    try:
        st = os.stat(path)
        return {"dev": st.st_dev, "ino": st.st_ino, "size": st.st_size,
                "mtime_ns": st.st_mtime_ns}
    except OSError:
        return None


def _grok_usage_record(obj):
    if obj.get("msg") != "shell.turn.inference_done":
        return None
    ctx = obj.get("ctx") or {}
    if not isinstance(ctx, dict):
        return None
    sid = str(obj.get("sid") or "")
    ts = str(obj.get("ts") or "")
    dt = parse_ts(ts)
    if not sid or dt is None:
        return None
    try:
        prompt = max(int(ctx.get("prompt_tokens") or 0), 0)
        cached = max(int(ctx.get("cached_prompt_tokens") or 0), 0)
        completion = max(int(ctx.get("completion_tokens") or 0), 0)
        reasoning = max(int(ctx.get("reasoning_tokens") or 0), 0)
    except (TypeError, ValueError):
        return None
    cached = min(cached, prompt)
    reasoning = min(reasoning, completion)
    try:
        loop_index = int(ctx.get("loop_index") or 0)
    except (TypeError, ValueError):
        loop_index = 0
    record_id = f"{sid}:{ts}:{loop_index}:{prompt}:{cached}:{completion}:{reasoning}"
    return {"id": record_id, "ts": ts, "sid": sid, "loop": loop_index,
            "in": prompt - cached, "cr": cached,
            "out": completion - reasoning, "reason": reasoning}


def _load_grok_usage_entries(cache=None):
    signature = _grok_log_signature(GROK_LOG)
    if signature is None:
        if cache is not None and cache.pop("grok_usage", None) is not None:
            cache["_dirty"] = True
        return []

    old = cache.get("grok_usage", {}) if cache is not None else {}
    same_file = old.get("dev") == signature["dev"] and old.get("ino") == signature["ino"]
    old_offset = int(old.get("offset", 0) or 0)
    can_append = same_file and signature["size"] >= old_offset
    if (can_append and old.get("size") == signature["size"]
            and old.get("mtime_ns") == signature["mtime_ns"]):
        return old.get("entries", [])

    entries = list(old.get("entries", [])) if can_append else []
    offset = old_offset if can_append else 0
    seen = {entry.get("id") for entry in entries if entry.get("id")}
    try:
        with open(GROK_LOG, "rb") as fh:
            fh.seek(offset)
            while True:
                line_start = fh.tell()
                raw = fh.readline()
                if not raw:
                    break
                if not raw.endswith(b"\n"):
                    offset = line_start
                    break
                offset = fh.tell()
                try:
                    obj = json.loads(raw.decode("utf-8", errors="ignore"))
                except Exception:
                    continue
                record = _grok_usage_record(obj)
                if record and record["id"] not in seen:
                    entries.append(record)
                    seen.add(record["id"])
    except OSError:
        return entries

    if cache is not None:
        updated = {**signature, "offset": offset, "entries": entries}
        if updated != old:
            cache["grok_usage"] = updated
            cache["_dirty"] = True
    return entries


def _grok_session_metadata():
    sessions = {}
    latest_mtime = -1.0
    latest_model = None
    if not os.path.isdir(GROK_DIR):
        return sessions, latest_model
    for sm in glob.glob(os.path.join(GROK_DIR, "*", "*", "summary.json")):
        try:
            with open(sm, "r", encoding="utf-8", errors="ignore") as fh:
                summary = json.load(fh)
            sid = str((summary.get("info") or {}).get("id") or os.path.basename(os.path.dirname(sm)))
            group_dir = os.path.dirname(os.path.dirname(sm))
            cwd_encoded = os.path.basename(group_dir)
            from urllib.parse import unquote
            project = unquote(cwd_encoded)
            cwd_file = os.path.join(group_dir, ".cwd")
            if os.path.isfile(cwd_file):
                try:
                    with open(cwd_file, "r", encoding="utf-8", errors="ignore") as fh:
                        project = fh.read().strip() or project
                except OSError:
                    pass
            model = summary.get("current_model_id")
            sessions[sid] = {"summary": summary, "path": sm,
                             "project": project if project.startswith("/") else "",
                             "model": model}
            mtime = os.path.getmtime(sm)
            if mtime > latest_mtime:
                latest_mtime = mtime
                latest_model = model
        except Exception:
            continue
    return sessions, latest_model


def scan_grok(bounds, cache=None):
    B = {k: {"tokens": 0, "in": 0, "out": 0, "cr": 0, "reason": 0,
             "cost": 0.0, "models": {}, "usage_sessions": set(), "usage_calls": 0,
             "sessions": set(), "turns": 0, "tools": 0,
             "duration": 0, "ctx_used": 0, "ctx_window": 0, "errors": 0,
             "cancellations": 0, "ttft_sum": 0, "response_sum": 0, "latency_count": 0}
         for k in RANGE_KEYS}
    sessions, latest_model = _grok_session_metadata()
    for sid, meta in sessions.items():
        sm = meta["path"]
        s = meta["summary"]
        dt = parse_ts(s.get("updated_at") or s.get("created_at") or "")
        if dt is None:
            continue
        ks = classify(dt.astimezone(), bounds)
        if not ks:
            continue
        sig = {}
        sj = os.path.join(os.path.dirname(sm), "signals.json")
        try:
            with open(sj, "r", encoding="utf-8", errors="ignore") as fh:
                sig = json.load(fh)
        except Exception:
            sig = {}

        mx = 0
        uj = os.path.join(os.path.dirname(sm), "updates.jsonl")
        try:
            with open(uj, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if "totalTokens" not in line:
                        continue
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    tt = (((o.get("params") or {}).get("_meta") or {}).get("totalTokens"))
                    if isinstance(tt, (int, float)) and tt > mx:
                        mx = int(tt)
        except OSError:
            pass

        event_turns = event_tools = event_duration = 0
        event_tool_errors = event_turn_errors = event_cancellations = 0
        ej = os.path.join(os.path.dirname(sm), "events.jsonl")
        try:
            with open(ej, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    typ = e.get("type")
                    if typ == "turn_started":
                        event_turns += 1
                    elif typ == "tool_completed":
                        event_tools += 1
                        event_duration += int(e.get("duration_ms") or 0)
                        if e.get("outcome") not in (None, "success"):
                            event_tool_errors += 1
                    elif typ == "turn_ended":
                        if e.get("outcome") == "cancelled":
                            event_cancellations += 1
                        elif e.get("outcome") == "error":
                            event_turn_errors += 1
        except OSError:
            pass

        turns = int(sig.get("turnCount") or event_turns or 0)
        tools = int(sig.get("toolCallCount") or event_tools or 0)
        duration = int(sig.get("sessionDurationSeconds") or 0)
        ctx_used = int(sig.get("contextTokensUsed") or mx or 0)
        ctx_window = int(sig.get("contextWindowTokens") or 0)
        signal_errors = int(sig.get("errorCount") or 0) + int(sig.get("toolFailureCount") or 0)
        errors = max(signal_errors, event_turn_errors, event_tool_errors)
        cancellations = max(int(sig.get("cancellationCount") or 0), event_cancellations)
        latency_count = int(sig.get("latencySampleCount") or turns or 0)
        ttft_sum = int(sig.get("avgTimeToFirstTokenMs") or 0) * latency_count
        response_sum = int(sig.get("avgResponseTimeMs") or 0) * latency_count

        for k in ks:
            b = B[k]
            b["sessions"].add(sid)
            b["turns"] += turns
            b["tools"] += tools
            b["duration"] += duration
            b["ctx_used"] += ctx_used
            b["ctx_window"] += ctx_window
            b["errors"] += errors
            b["cancellations"] += cancellations
            b["ttft_sum"] += ttft_sum
            b["response_sum"] += response_sum
            b["latency_count"] += latency_count

    for entry in _load_grok_usage_entries(cache):
        dt = parse_ts(entry.get("ts") or "")
        if dt is None:
            continue
        ks = classify(dt.astimezone(), bounds)
        if not ks:
            continue
        sid = entry.get("sid") or ""
        model = (sessions.get(sid) or {}).get("model") or latest_model or "grok"
        for k in ks:
            b = B[k]
            b["in"] += entry.get("in", 0)
            b["out"] += entry.get("out", 0)
            b["cr"] += entry.get("cr", 0)
            b["reason"] += entry.get("reason", 0)
            b["usage_calls"] += 1
            if sid:
                b["usage_sessions"].add(sid)
                b["sessions"].add(sid)
            _add_model_usage(b["models"], model, entry.get("in", 0), entry.get("out", 0),
                             entry.get("cr", 0), 0, entry.get("reason", 0), 0.0)
    return {"ranges": B, "model": latest_model}


# ---------- Qoder ----------
# QoderWork SQLite:~/Library/Application Support/QoderWork/data/agents.db
# messages.metadata 含 durationMs / numTurns, sub_chats.ext 含上下文快照。
_QODER_DB = os.path.join(HOME, "Library", "Application Support", "QoderWork", "data", "agents.db")
QODER_DB_PATHS = _path_candidates(
    "TOKEI_QODER_DB", _QODER_DB,
    os.path.join(APPDATA, "QoderWork", "data", "agents.db"),
    os.path.join(LOCALAPPDATA, "QoderWork", "data", "agents.db"))


def _qoder_db_path():
    return _first_existing_file(_path_candidates("TOKEI_QODER_DB", _QODER_DB, *QODER_DB_PATHS))


def scan_qoder(bounds, cache):
    import sqlite3 as _sqlite3
    fc = cache.setdefault("qoder", {})
    changed = False

    # --- Part 1: DB (all queries cached together by sig) ---
    db_days = {}
    sub_chat_days = {}  # date_str → count
    model = None
    qoder_db = _qoder_db_path()
    if qoder_db:
        sqlite_sig = _sqlite_signature(qoder_db)
        sig = f"{os.path.realpath(qoder_db)}|{sqlite_sig}" if sqlite_sig else None

        entry = fc.get("db")
        if sig and (not entry or entry.get("sig") != sig):
            conn = None
            try:
                conn = _sqlite3.connect(_sqlite_ro_uri(qoder_db), uri=True, timeout=1)
                conn.execute("PRAGMA query_only=ON")
                # messages: calls, sessions, tokens, duration, turns
                for row in conn.execute("""
                    SELECT date(created_at,'unixepoch','localtime') as day,
                           COUNT(*) as calls,
                           COUNT(DISTINCT chat_id) as sessions,
                           COALESCE(SUM(json_extract(metadata,'$.inputTokens')),0),
                           COALESCE(SUM(json_extract(metadata,'$.outputTokens')),0),
                           COALESCE(SUM(json_extract(metadata,'$.durationMs')),0),
                           COALESCE(SUM(json_extract(metadata,'$.numTurns')),0)
                    FROM messages WHERE metadata!='{}'
                    GROUP BY day
                """):
                    dk, calls, sessions, ti, to_, dur, turns = row
                    if dk:
                        db_days[dk] = {"calls": calls, "sessions": sessions,
                                       "in": int(ti or 0), "out": int(to_ or 0),
                                       "duration": int(dur or 0), "turns": int(turns or 0),
                                       "ctx_ratio": 0.0, "hours": [0] * 24}
                for row in conn.execute("""
                    SELECT date(created_at,'unixepoch','localtime') as day,
                           CAST(strftime('%H',created_at,'unixepoch','localtime') AS INTEGER),
                           COALESCE(SUM(json_extract(metadata,'$.inputTokens')),0) +
                           COALESCE(SUM(json_extract(metadata,'$.outputTokens')),0)
                    FROM messages WHERE metadata!='{}'
                    GROUP BY day, strftime('%H',created_at,'unixepoch','localtime')
                """):
                    dk, hour, tokens = row
                    if dk in db_days and hour is not None:
                        db_days[dk]["hours"][int(hour)] += int(tokens or 0)
                # sub_chats: ctx percentage per day
                for row in conn.execute("""
                    SELECT date(created_at,'unixepoch','localtime') as day,
                           AVG(CASE WHEN json_extract(ext,'$.contextUsageSnapshot.percentage')>0
                                    THEN json_extract(ext,'$.contextUsageSnapshot.percentage') END)
                    FROM sub_chats
                    WHERE ext IS NOT NULL AND ext != '{}'
                    GROUP BY day
                """):
                    dk, ctx_pct = row
                    if dk and ctx_pct and dk in db_days:
                        db_days[dk]["ctx_ratio"] = float(ctx_pct)
                # sub_chats: count per day (for sub_agents metric)
                for row in conn.execute("""
                    SELECT date(created_at,'unixepoch','localtime') as day, COUNT(*)
                    FROM sub_chats WHERE created_at IS NOT NULL
                    GROUP BY day
                """):
                    if row[0]:
                        sub_chat_days[row[0]] = int(row[1])
                # model level
                mrow = conn.execute("SELECT value FROM app_settings WHERE key='modelLevel'").fetchone()
                if mrow:
                    model = mrow[0].strip('"')
            except Exception:
                pass
            finally:
                if conn is not None:
                    conn.close()
            fc["db"] = {"sig": sig, "days": db_days,
                        "sub_chat_days": sub_chat_days, "model": model}
            changed = True
        else:
            db_days = (entry or {}).get("days", {})
            sub_chat_days = (entry or {}).get("sub_chat_days", {})
            model = (entry or {}).get("model")
    elif "db" in fc:
        fc.pop("db", None)
        changed = True

    # --- 汇总 DB 数据 ---
    B = {k: {"in": 0, "out": 0, "sessions": 0, "calls": 0, "sub_agents": 0,
             "duration": 0, "turns": 0, "ctx_sum": 0.0, "ctx_count": 0}
         for k in RANGE_KEYS}

    for dk, db_day in db_days.items():
        try:
            d = date.fromisoformat(dk)
        except ValueError:
            continue
        ks = classify_date(d, bounds)
        if not ks:
            continue

        calls = db_day.get("calls", 0)
        sessions = db_day.get("sessions", 0)
        duration = db_day.get("duration", 0)
        turns = db_day.get("turns", 0)
        ctx_ratio = db_day.get("ctx_ratio", 0)

        for k in ks:
            b = B[k]
            b["in"] += db_day.get("in", 0); b["out"] += db_day.get("out", 0)
            b["sessions"] += sessions; b["calls"] += calls
            b["sub_agents"] += sub_chat_days.get(dk, 0)
            b["duration"] += duration; b["turns"] += turns
            if ctx_ratio > 0:
                b["ctx_sum"] += ctx_ratio * calls
                b["ctx_count"] += calls

    if changed:
        cache["_dirty"] = True
    return {"ranges": B, "model": model}


# ---------- Qoder IDE ----------
# Qoder IDE: SQLite DB ~/Library/Application Support/Qoder/SharedClientCache/cache/db/local.db
# chat_message 表: token_info(JSON明文), model_info(JSON明文), gmt_create(毫秒时间戳)


def _empty_qoder_ide():
    ranges = {k: {"in": 0, "out": 0, "cached": 0, "sessions": 0, "sub_agents": 0,
                  "calls": 0, "messages": 0, "duration": 0} for k in RANGE_KEYS}
    return {"ranges": ranges, "model": None}


def scan_qoder_ide(bounds, cache):
    import sqlite3 as _sq
    fc = cache.setdefault("qoder_ide", {})
    empty = _empty_qoder_ide()

    # 默认关闭，需在 config.json 中显式启用
    try:
        with open(os.path.join(_USER_DIR, "config.json"), "r") as f:
            cfg = json.load(f)
        if not cfg.get("qoder_ide_enabled"):
            if fc:
                fc.clear()
                cache["_dirty"] = True
            return empty
    except (OSError, json.JSONDecodeError, ValueError):
        if fc:
            fc.clear()
            cache["_dirty"] = True
        return empty

    qoder_ide_db = _qoder_ide_db_path()
    if not qoder_ide_db:
        if fc:
            fc.clear()
            cache["_dirty"] = True
        return empty

    sqlite_sig = _sqlite_signature(qoder_ide_db)
    if not sqlite_sig:
        return empty
    sig = f"{os.path.realpath(qoder_ide_db)}|{sqlite_sig}"

    entry = fc.get("data")
    if not entry or entry.get("sig") != sig:
        days = {}  # date_str → {in, out, cached, session_ids, sub_agent_ids, calls, messages, duration}
        latest_model = None
        conn = None
        try:
            conn = _sq.connect(_sqlite_ro_uri(qoder_ide_db), uri=True, timeout=1)
            conn.execute("PRAGMA query_only=ON")
            # token 用量 & 计数 per day
            for row in conn.execute("""
                SELECT date(gmt_create/1000, 'unixepoch', 'localtime') as day,
                       COALESCE(SUM(json_extract(token_info, '$.prompt_tokens')), 0),
                       COALESCE(SUM(json_extract(token_info, '$.completion_tokens')), 0),
                       COALESCE(SUM(json_extract(token_info, '$.cached_tokens')), 0),
                       COUNT(DISTINCT request_id),
                       COUNT(*)
                FROM chat_message
                WHERE token_info IS NOT NULL AND token_info != ''
                GROUP BY day
            """):
                dk, ti, to_, cached, calls, msgs = row
                if not dk:
                    continue
                days[dk] = {"in": int(ti), "out": int(to_), "cached": int(cached),
                            "session_ids": [], "sub_agent_ids": [],
                            "calls": int(calls), "messages": int(msgs), "duration": 0,
                            "hours": [0] * 24}
            for row in conn.execute("""
                SELECT date(gmt_create/1000, 'unixepoch', 'localtime') as day,
                       CAST(strftime('%H', gmt_create/1000, 'unixepoch', 'localtime') AS INTEGER),
                       COALESCE(SUM(json_extract(token_info, '$.prompt_tokens')), 0) +
                       COALESCE(SUM(json_extract(token_info, '$.completion_tokens')), 0)
                FROM chat_message
                WHERE token_info IS NOT NULL AND token_info != ''
                GROUP BY day, strftime('%H', gmt_create/1000, 'unixepoch', 'localtime')
            """):
                dk, hour, tokens = row
                if dk in days and hour is not None:
                    days[dk]["hours"][int(hour)] += int(tokens or 0)
            # collect session_ids per day, split by type (user vs sub-agent)
            sub_agent_sids = set()
            try:
                for row in conn.execute("""
                    SELECT session_id FROM chat_session
                    WHERE session_type LIKE 'agent_sub_%'
                """):
                    sub_agent_sids.add(row[0])
            except Exception:
                pass
            for row in conn.execute("""
                SELECT date(gmt_create/1000, 'unixepoch', 'localtime') as day,
                       session_id
                FROM chat_message
                WHERE token_info IS NOT NULL AND token_info != ''
                GROUP BY day, session_id
            """):
                dk, sid = row
                if dk and dk in days and sid:
                    if sid in sub_agent_sids:
                        days[dk]["sub_agent_ids"].append(sid)
                    else:
                        days[dk]["session_ids"].append(sid)
            # duration per day (sum of per-request time spans)
            for row in conn.execute("""
                SELECT date(min_ts/1000, 'unixepoch', 'localtime') as day,
                       SUM(max_ts - min_ts) / 1000 as dur_sec
                FROM (SELECT request_id, MIN(gmt_create) as min_ts, MAX(gmt_create) as max_ts
                      FROM chat_message GROUP BY request_id HAVING COUNT(*) > 1) sub
                GROUP BY day
            """):
                dk, dur = row
                if dk and dk in days:
                    days[dk]["duration"] = int(dur)
            # latest model
            row = conn.execute("""
                SELECT json_extract(model_info, '$.model_key') FROM chat_message
                WHERE model_info IS NOT NULL AND model_info != ''
                ORDER BY gmt_create DESC LIMIT 1
            """).fetchone()
            if row and row[0]:
                latest_model = row[0]
        except Exception:
            pass
        finally:
            if conn is not None:
                conn.close()

        fc["data"] = {"sig": sig, "days": days, "model": latest_model}
        cache["_dirty"] = True
        entry = fc["data"]

    # 按时间范围聚合（sessions/sub_agents 用 set 去重，避免跨天会话被多算）
    B = {k: {"in": 0, "out": 0, "cached": 0, "sessions": 0, "sub_agents": 0,
             "calls": 0, "messages": 0, "duration": 0} for k in RANGE_KEYS}
    session_sets = {k: set() for k in RANGE_KEYS}
    sub_agent_sets = {k: set() for k in RANGE_KEYS}

    for dk, day in entry.get("days", {}).items():
        try:
            d = date.fromisoformat(dk)
        except ValueError:
            continue
        for k in classify_date(d, bounds):
            b = B[k]
            b["in"] += day["in"]
            b["out"] += day["out"]
            b["cached"] += day["cached"]
            b["calls"] += day["calls"]
            b["messages"] += day.get("messages", 0)
            b["duration"] += day.get("duration", 0)
            for sid in day.get("session_ids", []):
                session_sets[k].add(sid)
            for sid in day.get("sub_agent_ids", []):
                sub_agent_sets[k].add(sid)

    for k in RANGE_KEYS:
        B[k]["sessions"] = len(session_sets[k])
        B[k]["sub_agents"] = len(sub_agent_sets[k])

    return {"ranges": B, "model": entry.get("model")}


# ---------- Hermes ----------
# SQLite: ~/.hermes/state.db (旧布局) + ~/.hermes/profiles/*/state.db (profile 布局)
def _hermes_db_paths():
    paths = []
    if os.path.isfile(HERMES_DB):
        paths.append(HERMES_DB)
    profiles = os.path.join(HOME, ".hermes", "profiles")
    if os.path.isdir(profiles):
        for p in os.listdir(profiles):
            db = os.path.join(profiles, p, "state.db")
            if os.path.isfile(db):
                paths.append(db)
    return paths


def _scan_hermes_db(db_path, _sq):
    days = {}
    try:
        conn = _sq.connect(f"file:{db_path}?mode=ro", uri=True)
        for row in conn.execute("""
            SELECT date(started_at,'unixepoch','localtime') as day,
                   CAST(strftime('%H',started_at,'unixepoch','localtime') AS INTEGER) as hour,
                   COUNT(*) as cnt, model,
                   COALESCE(SUM(input_tokens),0),
                   COALESCE(SUM(output_tokens),0),
                   COALESCE(SUM(cache_read_tokens),0),
                   COALESCE(SUM(cache_write_tokens),0),
                   COALESCE(SUM(reasoning_tokens),0),
                   COALESCE(SUM(COALESCE(actual_cost_usd,estimated_cost_usd)),0)
            FROM sessions WHERE started_at > 0
            GROUP BY day, hour, model
        """):
            dk, hour, cnt, model, ti, to_, cr, cw, reason, cost = row
            if not dk:
                continue
            day = days.setdefault(dk, {"in": 0, "out": 0, "cr": 0, "cw": 0,
                                       "reason": 0, "cost": 0.0, "sessions": 0,
                                       "models": {}, "hours": [0] * 24})
            day["in"] += int(ti); day["out"] += int(to_)
            day["cr"] += int(cr); day["cw"] += int(cw)
            day["reason"] += int(reason); day["cost"] += float(cost)
            day["sessions"] += int(cnt)
            if hour is not None:
                day["hours"][int(hour)] += int(ti) + int(to_) + int(cr) + int(cw) + int(reason)
            if model:
                mm = day["models"].setdefault(
                    model, {"in": 0, "out": 0, "cr": 0, "cw": 0,
                            "reason": 0, "cost": 0.0})
                mm["in"] += int(ti); mm["out"] += int(to_)
                mm["cr"] += int(cr); mm["cw"] += int(cw)
                mm["reason"] += int(reason); mm["cost"] += float(cost)
        conn.close()
    except Exception:
        pass
    return days


def scan_hermes(bounds, cache):
    import sqlite3 as _sq
    fc = cache.setdefault("hermes", {})
    changed = False

    db_paths = _hermes_db_paths()
    if not db_paths:
        if fc:
            fc.clear()
            cache["_dirty"] = True
        return {"ranges": {k: {"in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0.0,
                                "sessions": 0, "models": {}} for k in RANGE_KEYS}}

    stale = set(fc.keys())
    for db_path in db_paths:
        stale.discard(db_path)
        try:
            sig = f"{os.path.getmtime(db_path)}:{os.path.getsize(db_path)}"
        except OSError:
            continue
        entry = fc.get(db_path)
        if not entry or entry.get("sig") != sig:
            days = _scan_hermes_db(db_path, _sq)
            fc[db_path] = {"sig": sig, "days": days}
            changed = True
    for p in stale:
        fc.pop(p, None)
        changed = True

    B = {k: {"in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0.0,
             "sessions": 0, "models": {}} for k in RANGE_KEYS}
    for db_path, entry in fc.items():
        for dk, day in entry.get("days", {}).items():
            try:
                d = date.fromisoformat(dk)
            except ValueError:
                continue
            for k in classify_date(d, bounds):
                b = B[k]
                b["in"] += day["in"]; b["out"] += day["out"]
                b["cr"] += day["cr"]; b["cw"] += day["cw"]
                b["reason"] += day["reason"]; b["cost"] += day["cost"]
                b["sessions"] += day["sessions"]
                for mn, mv in day.get("models", {}).items():
                    mm = b["models"].setdefault(
                        mn, {"in": 0, "out": 0, "cr": 0, "cw": 0,
                             "reason": 0, "cost": 0.0})
                    for key in TOKEN_FIELDS:
                        mm[key] += mv.get(key, 0)
                    mm["cost"] += mv.get("cost", 0)
    if changed:
        cache["_dirty"] = True
    return {"ranges": B}


# ---------- OpenClaw ----------
# SQLite: ~/.openclaw/tasks/runs.sqlite — 任务计数
# Session JSONL: ~/.openclaw/agents/*/sessions/*.jsonl — token 用量
def scan_openclaw(bounds, cache):
    import sqlite3 as _sq
    fc = cache.setdefault("openclaw", {})
    changed = False

    today_d = bounds["today"].date()
    yest_d = bounds["yesterday"].date()
    week_d = bounds["week"].date()
    lw_start_d = bounds["last_week"].date()
    lw_end_d = bounds["last_week_end"].date()
    month_d = bounds["month"].date()
    year_d = bounds["year"].date()

    def _day_keys(d):
        ks = ["all"]
        if d == today_d: ks.append("today")
        if d == yest_d: ks.append("yesterday")
        if d >= week_d: ks.append("week")
        if lw_start_d <= d < lw_end_d: ks.append("last_week")
        if d >= month_d: ks.append("month")
        if d >= year_d: ks.append("year")
        return ks

    B = {k: {"tasks": 0, "completed": 0, "failed": 0,
             "in": 0, "out": 0, "cr": 0, "cw": 0,
             "cost": 0.0, "sessions": set(), "models": {}} for k in RANGE_KEYS}

    # --- Part 1: SQLite task counts ---
    if os.path.isfile(OPENCLAW_DB):
        try:
            sig = f"{os.path.getmtime(OPENCLAW_DB)}:{os.path.getsize(OPENCLAW_DB)}"
        except OSError:
            sig = None
        if sig:
            entry = fc.get("_db")
            if not entry or entry.get("sig") != sig:
                task_days = {}
                try:
                    conn = _sq.connect(f"file:{OPENCLAW_DB}?mode=ro", uri=True)
                    for row in conn.execute("""
                        SELECT date(created_at/1000,'unixepoch','localtime') as day,
                               COUNT(*) as total,
                               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END),
                               SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END)
                        FROM task_runs WHERE created_at > 0
                        GROUP BY day
                    """):
                        dk, total, completed, failed = row
                        if dk:
                            task_days[dk] = {"tasks": int(total or 0), "completed": int(completed or 0),
                                             "failed": int(failed or 0)}
                    conn.close()
                except Exception:
                    pass
                fc["_db"] = {"sig": sig, "days": task_days}
                changed = True
            for dk, day in fc.get("_db", {}).get("days", {}).items():
                try:
                    d = date.fromisoformat(dk)
                except ValueError:
                    continue
                for k in _day_keys(d):
                    b = B[k]
                    b["tasks"] += day["tasks"]; b["completed"] += day["completed"]
                    b["failed"] += day["failed"]
    elif "_db" in fc:
        fc.pop("_db", None)
        changed = True

    # --- Part 2: Session JSONL token usage ---
    if os.path.isdir(OPENCLAW_AGENTS):
        stale = {k for k in fc if not k.startswith("_")}
        for f in glob.glob(os.path.join(OPENCLAW_AGENTS, "*", "sessions", "*.jsonl")):
            if f.endswith(".trajectory.jsonl"):
                continue
            stale.discard(f)
            try:
                st = os.stat(f)
            except OSError:
                continue
            sig = f"{st.st_mtime}:{st.st_size}"
            entry = fc.get(f)
            if not entry or entry.get("sig") != sig:
                days = {}
                try:
                    with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                        for line in fh:
                            if '"usage"' not in line:
                                continue
                            try:
                                o = json.loads(line)
                            except Exception:
                                continue
                            msg = o.get("message", {})
                            if msg.get("role") != "assistant":
                                continue
                            u = msg.get("usage")
                            if not u:
                                continue
                            dt = parse_ts(o.get("timestamp", ""))
                            if dt is None:
                                continue
                            dt = dt.astimezone()
                            inp = u.get("input", 0) or 0
                            out = u.get("output", 0) or 0
                            cr = u.get("cacheRead", 0) or 0
                            cw = u.get("cacheWrite", 0) or 0
                            if inp == 0 and out == 0:
                                continue
                            model = msg.get("model", "")
                            cid = _resolve_id(model)
                            cost_obj = u.get("cost")
                            raw_cost = float((cost_obj or {}).get("total", 0) or 0)
                            if raw_cost > 0:
                                cost = raw_cost
                            elif cid:
                                p = _raw_price(model)
                                cost = inp / 1e6 * p["in"] + out / 1e6 * p["out"] + cr / 1e6 * p["cache_read"] + cw / 1e6 * p["cache_write"]
                            else:
                                cost = 0.0
                            dk = dt.date().isoformat()
                            day = days.setdefault(dk, {"in": 0, "out": 0, "cr": 0, "cw": 0,
                                                       "cost": 0.0, "models": {},
                                                       "hours": [0] * 24})
                            day["in"] += inp; day["out"] += out
                            day["cr"] += cr; day["cw"] += cw; day["cost"] += cost
                            day["hours"][dt.hour] += inp + out + cr + cw
                            mn = cid or model or "unknown"
                            mm = day["models"].setdefault(
                                mn, {"in": 0, "out": 0, "cr": 0, "cw": 0,
                                     "reason": 0, "cost": 0.0})
                            mm["in"] += inp; mm["out"] += out
                            mm["cr"] += cr; mm["cw"] += cw; mm["cost"] += cost
                except OSError:
                    continue
                fc[f] = {"sig": sig, "days": days}
                changed = True

        for p in stale:
            fc.pop(p, None)
            changed = True

        for f, entry in fc.items():
            if f.startswith("_"):
                continue
            for dk, day in entry.get("days", {}).items():
                try:
                    d = date.fromisoformat(dk)
                except ValueError:
                    continue
                for k in _day_keys(d):
                    b = B[k]
                    b["sessions"].add(f)
                    b["in"] += day["in"]; b["out"] += day["out"]
                    b["cr"] += day["cr"]; b["cw"] += day["cw"]; b["cost"] += day["cost"]
                    for mn, mv in day["models"].items():
                        mm = b["models"].setdefault(
                            mn, {"in": 0, "out": 0, "cr": 0, "cw": 0,
                                 "reason": 0, "cost": 0.0})
                        for key in TOKEN_FIELDS:
                            mm[key] += mv.get(key, 0)
                        mm["cost"] += mv.get("cost", 0)
    else:
        for p in [key for key in fc if not key.startswith("_")]:
            fc.pop(p, None)
            changed = True

    if changed:
        cache["_dirty"] = True
    return {"ranges": B}


# ---------- Pi Coding Agent CLI ----------
# JSONL 文件: ~/.pi/agent/sessions/<encoded-cwd>/*.jsonl 或 ~/.omp/agent/sessions/<encoded-cwd>/*.jsonl
# assistant message 里保存 usage{input,output,cacheRead,cacheWrite,reasoningTokens,cost}。
def _pi_session_dirs():
    dirs = [
        PI_SESSION_DIR,
        os.path.join(PI_AGENT_DIR, "sessions"),
        os.path.join(HOME, ".pi", "agent", "sessions"),
        OMP_SESSION_DIR,
    ]
    out = []
    for d in dirs:
        d = os.path.realpath(os.path.abspath(os.path.expanduser(d)))
        if d not in out:
            out.append(d)
    return out


def _pi_model_id(msg):
    model = msg.get("model", "") or ""
    provider = msg.get("provider", "") or ""
    if provider and model and "/" not in model:
        return f"{provider}/{model}"
    return model or provider or "unknown"


def _pi_usage_int(usage, *fields):
    for field in fields:
        if field in usage and usage[field] is not None:
            return int(usage[field] or 0)
    return 0


def _pi_usage_cost(u, model):
    cost_obj = u.get("cost") or {}
    total = float(cost_obj.get("total", 0) or 0)
    if total > 0:
        return total
    parts = sum(float(cost_obj.get(k, 0) or 0) for k in ("input", "output", "cacheRead", "cacheWrite"))
    if parts > 0:
        return parts
    p = _raw_price(model)
    inp = _pi_usage_int(u, "input")
    out = _pi_usage_int(u, "output")
    cr = _pi_usage_int(u, "cacheRead", "cache_read")
    cw = _pi_usage_int(u, "cacheWrite", "cache_write")
    return inp / 1e6 * p["in"] + out / 1e6 * p["out"] + cr / 1e6 * p["cache_read"] + cw / 1e6 * p["cache_write"]


def scan_pi(bounds, cache):
    fc = cache.setdefault("pi", {})
    changed = False
    B = _empty_token_ranges()

    roots = [d for d in _pi_session_dirs() if os.path.isdir(d)]
    if not roots:
        if fc:
            fc.clear()
            cache["_dirty"] = True
        return {"ranges": B}

    seen_files = set()
    for root in roots:
        seen_files.update(glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True))
    stale = set(fc.keys())

    for f in sorted(seen_files):
        stale.discard(f)
        try:
            st = os.stat(f)
        except OSError:
            continue
        sig = f"{st.st_mtime}:{st.st_size}"
        entry = fc.get(f)
        if not entry or entry.get("sig") != sig:
            days = {}
            proj = None
            sid = os.path.basename(f)
            try:
                with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        if '"usage"' not in line and '"type":"session"' not in line and '"type": "session"' not in line:
                            continue
                        try:
                            o = json.loads(line)
                        except Exception:
                            continue
                        if o.get("type") == "session":
                            sid = o.get("id") or sid
                            proj = o.get("cwd") or proj
                            continue
                        if o.get("type") != "message":
                            continue
                        msg = o.get("message") or {}
                        if msg.get("role") != "assistant":
                            continue
                        u = msg.get("usage") or {}
                        if not u:
                            continue
                        dt = parse_ts(o.get("timestamp") or msg.get("timestamp") or "")
                        if dt is None:
                            continue
                        inp = _pi_usage_int(u, "input")
                        out = _pi_usage_int(u, "output")
                        cr = _pi_usage_int(u, "cacheRead", "cache_read")
                        cw = _pi_usage_int(u, "cacheWrite", "cache_write")
                        reason = _pi_usage_int(u, "reasoning", "reason", "reasoningTokens")
                        model = _pi_model_id(msg)
                        cost = _pi_usage_cost(u, model)
                        if inp + out + cr + cw + reason == 0 and cost <= 0:
                            continue
                        dk = dt.astimezone().date().isoformat()
                        day = days.setdefault(dk, _empty_token_day())
                        _add_token_usage(day, inp, out, cr, cw, reason, cost, model)
                        day["hours"][dt.astimezone().hour] += inp + out + cr + cw + reason
            except OSError:
                continue
            fc[f] = {"sig": sig, "days": days, "proj": proj, "sid": sid}
            changed = True

    for p in stale:
        fc.pop(p, None)
        changed = True

    for f, entry in fc.items():
        for dk, day in entry.get("days", {}).items():
            try:
                d = date.fromisoformat(dk)
            except ValueError:
                continue
            for k in classify_date(d, bounds):
                _merge_token_day(B[k], day, entry.get("sid") or f)
    if changed:
        cache["_dirty"] = True
    return {"ranges": B}


# ---------- WorkBuddy ----------
# JSONL 文件: ~/.workbuddy/projects/<encoded-cwd>/<session>.jsonl
# 每个带 usage 的 item 代表一次模型调用。providerData 中的同一份 usage 仅作字段补全，
# 不重复累计；reasoning_tokens 已包含在 output_tokens 中。
def _workbuddy_number(obj, *keys):
    if not isinstance(obj, dict):
        return None
    for key in keys:
        if key not in obj:
            continue
        value = obj.get(key)
        if isinstance(value, bool):
            continue
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            continue
    return None


def _workbuddy_detail_total(value, *keys):
    if isinstance(value, dict):
        return _workbuddy_number(value, *keys) or 0
    if isinstance(value, list):
        return sum(_workbuddy_number(item, *keys) or 0 for item in value if isinstance(item, dict))
    return 0


def _workbuddy_timestamp(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value) / 1000 if value > 10_000_000_000 else float(value)
        try:
            return datetime.fromtimestamp(seconds).astimezone()
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        dt = parse_ts(value)
        return dt.astimezone() if dt else None
    return None


def _workbuddy_usage_record(item):
    message = item.get("message") or {}
    if not isinstance(message, dict):
        message = {}
    provider = item.get("providerData") or message.get("providerData") or {}
    if not isinstance(provider, dict):
        provider = {}

    message_usage = message.get("usage") or {}
    normalized = provider.get("usage") or {}
    raw = provider.get("rawUsage") or {}
    sources = [x for x in (message_usage, normalized, raw) if isinstance(x, dict) and x]

    selected = None
    input_total = output = 0
    for source in sources:
        inp = _workbuddy_number(source, "input_tokens", "inputTokens", "input", "prompt_tokens")
        out = _workbuddy_number(source, "output_tokens", "outputTokens", "output", "completion_tokens")
        if (inp or 0) + (out or 0) > 0:
            selected = source
            input_total = inp or 0
            output = out or 0
            break
    if selected is None:
        return None

    cache_read_candidates = []
    cache_write_candidates = []
    total_candidates = []
    for source in sources:
        cache_read_candidates.extend([
            _workbuddy_number(source, "cache_read_input_tokens", "cacheReadInputTokens",
                              "cache_read", "cacheRead", "cached_tokens", "cachedTokens") or 0,
            _workbuddy_number(source, "prompt_cache_hit_tokens") or 0,
            _workbuddy_detail_total(source.get("inputTokensDetails"), "cached_tokens", "cachedTokens"),
            _workbuddy_detail_total(source.get("input_tokens_details"), "cached_tokens", "cachedTokens"),
            _workbuddy_detail_total(source.get("prompt_tokens_details"), "cached_tokens", "cachedTokens"),
        ])
        cache_write_candidates.extend([
            _workbuddy_number(source, "cache_creation_input_tokens", "cacheCreationInputTokens",
                              "cache_write_input_tokens", "cacheWriteInputTokens",
                              "prompt_cache_write_tokens", "cache_write", "cacheWrite") or 0,
        ])
        total = _workbuddy_number(source, "total_tokens", "totalTokens", "total")
        if total is not None:
            total_candidates.append(total)

    cache_read = max(cache_read_candidates, default=0)
    cache_write = max(cache_write_candidates, default=0)
    inclusive_input = any(total == input_total + output for total in total_candidates)
    if inclusive_input:
        cache_read = min(cache_read, input_total)
        cache_write = min(cache_write, max(input_total - cache_read, 0))
        input_tokens = max(input_total - cache_read - cache_write, 0)
    else:
        input_tokens = input_total

    timestamp_value = item.get("timestamp") or message.get("timestamp")
    dt = _workbuddy_timestamp(timestamp_value)
    if dt is None:
        return None

    model = (provider.get("requestModelName") or provider.get("requestModelId")
             or provider.get("model") or message.get("model") or item.get("model") or "unknown")
    price = _raw_price(str(model))
    cost = (input_tokens / 1e6 * price["in"] + output / 1e6 * price["out"]
            + cache_read / 1e6 * price["cache_read"]
            + cache_write / 1e6 * price["cache_write"])
    item_id = item.get("id") or provider.get("messageId") or ""
    return {
        "date": dt.date().isoformat(),
        "hour": dt.hour,
        "ts": dt.timestamp(),
        "ts_key": str(timestamp_value),
        "item_id": str(item_id),
        "in": input_tokens,
        "out": output,
        "cr": cache_read,
        "cw": cache_write,
        "reason": 0,
        "cost": cost,
        "model": str(model),
    }


def _iter_workbuddy_records(file_cache):
    items = []
    for path, entry in file_cache.items():
        if not isinstance(entry, dict):
            continue
        for record in entry.get("records", []):
            if isinstance(record, dict):
                items.append((record.get("ts", 0), path, entry, record))
    items.sort(key=lambda x: (x[0], x[1]))

    seen = set()
    for _, path, entry, record in items:
        key = record.get("dedup") or f"{path}:{record.get('line', 0)}:{record.get('ts_key', '')}"
        if key in seen:
            continue
        seen.add(key)
        yield path, entry, record


def scan_workbuddy(bounds, cache):
    fc = cache.setdefault("workbuddy", {})
    B = _empty_token_ranges()
    if not os.path.isdir(WORKBUDDY_DIR):
        return {"ranges": B}

    files = set(glob.glob(os.path.join(WORKBUDDY_DIR, "**", "*.jsonl"), recursive=True))
    stale = set(fc.keys())
    for path in sorted(files):
        stale.discard(path)
        try:
            st = os.stat(path)
        except OSError:
            continue
        sig = f"{st.st_mtime}:{st.st_size}"
        if isinstance(fc.get(path), dict) and fc[path].get("sig") == sig:
            continue

        records = []
        project = None
        session_id = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                for line_no, line in enumerate(fh, 1):
                    if '"usage"' not in line and '"cwd"' not in line:
                        continue
                    try:
                        item = json.loads(line)
                    except Exception:
                        continue
                    project = item.get("cwd") or project
                    session_id = item.get("sessionId") or session_id
                    record = _workbuddy_usage_record(item)
                    if record is None:
                        continue
                    record_session = str(item.get("sessionId") or session_id)
                    if record["item_id"]:
                        record["dedup"] = json.dumps(
                            [record_session, record["item_id"], record["ts_key"]], separators=(",", ":"))
                    else:
                        record["dedup"] = f"{path}:{line_no}:{record['ts_key']}"
                    record["session"] = record_session
                    record["line"] = line_no
                    records.append(record)
        except OSError:
            continue
        fc[path] = {"sig": sig, "records": records, "proj": project, "sid": str(session_id)}

    for path in stale:
        fc.pop(path, None)

    days = {}
    sessions = {}
    for _, _, record in _iter_workbuddy_records(fc):
        day = days.setdefault(record["date"], _empty_token_day())
        _add_token_usage(day, record["in"], record["out"], record["cr"], record["cw"],
                         0, record["cost"], record["model"])
        sessions.setdefault(record["date"], set()).add(record.get("session") or "unknown")

    for day_key, day in days.items():
        try:
            day_date = date.fromisoformat(day_key)
        except ValueError:
            continue
        for range_key in classify_date(day_date, bounds):
            _merge_token_day(B[range_key], day)
            B[range_key]["sessions"].update(sessions.get(day_key, set()))
    return {"ranges": B}


# ---------- OpenCode ----------
# SQLite: ~/.local/share/opencode/opencode.db；旧版 JSON 作为补充来源。
# JSON 文件: ~/.local/share/opencode/storage/message/<session>/msg_*.json
# 每条 assistant 消息有 tokens{input,output,reasoning,cache{read,write}} + cost + modelID。
def _opencode_db_paths():
    data_dirs = _path_candidates(
        "TOKEI_OPENCODE_DATA_DIR", OPENCODE_DATA_DIR, *OPENCODE_DATA_DIRS)
    direct = [OPENCODE_DB] + [os.path.join(root, "opencode.db") for root in data_dirs]
    database = _first_existing_file(direct)
    if database:
        return [os.path.realpath(database)]
    for parent in [os.path.dirname(OPENCODE_DB)] + data_dirs:
        channels = []
        for path in sorted(glob.glob(os.path.join(parent, "opencode-*.db"))):
            name = os.path.basename(path)
            channel = name[len("opencode-"):-len(".db")]
            if channel and all(ch.isalnum() or ch in "._-" for ch in channel):
                channels.append(os.path.realpath(path))
        if channels:
            return [channels[0]]
    return []


def _opencode_json_dirs():
    data_dirs = _path_candidates(
        "TOKEI_OPENCODE_DATA_DIR", OPENCODE_DATA_DIR, *OPENCODE_DATA_DIRS)
    defaults = [OPENCODE_DIR] + [os.path.join(root, "storage", "message") for root in data_dirs]
    return _existing_dirs(_path_candidates("TOKEI_OPENCODE_DIR", *defaults))


def _opencode_message_day(message, session_id="", created_ms=0, estimate_missing_cost=False):
    if message.get("role") != "assistant":
        return None
    timestamp = (message.get("time") or {}).get("created") or created_ms
    if not timestamp:
        return None
    tokens = message.get("tokens") or {}
    cache = tokens.get("cache") or {}
    model = message.get("modelID", "")
    created = datetime.fromtimestamp(int(timestamp) / 1000).astimezone()
    cost = float(message.get("cost", 0) or 0)
    if estimate_missing_cost and not cost:
        price_id = _pricing_id(model)
        if price_id:
            price = _raw_price(price_id)
            cost = ((int(tokens.get("input", 0) or 0) / 1e6) * price["in"]
                    + ((int(tokens.get("output", 0) or 0) + int(tokens.get("reasoning", 0) or 0)) / 1e6) * price["out"]
                    + (int(cache.get("read", 0) or 0) / 1e6) * price["cache_read"]
                    + (int(cache.get("write", 0) or 0) / 1e6) * price["cache_write"])
    day = {
        "date": created.strftime("%Y-%m-%d"),
        "in": int(tokens.get("input", 0) or 0),
        "out": int(tokens.get("output", 0) or 0),
        "reason": int(tokens.get("reasoning", 0) or 0),
        "cr": int(cache.get("read", 0) or 0),
        "cw": int(cache.get("write", 0) or 0),
        "cost": cost,
        "session": message.get("sessionID") or session_id,
        "models": {},
        "hours": [0] * 24,
    }
    day["hours"][created.hour] = token_total(day)
    _add_model_usage(day["models"], model, day["in"], day["out"], day["cr"],
                     day["cw"], day["reason"], day["cost"])
    return day


def _scan_opencode_database(path, estimate_missing_cost=False):
    import sqlite3

    days = {}
    message_ids = set()
    sessions = {}
    connection = sqlite3.connect(_sqlite_ro_uri(path), uri=True, timeout=1)
    try:
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute("SELECT id, session_id, time_created, data FROM message")
        for message_id, session_id, created_ms, raw in rows:
            try:
                message = json.loads(raw)
            except (TypeError, ValueError):
                continue
            day = _opencode_message_day(message, session_id or "", created_ms or 0,
                                        estimate_missing_cost=estimate_missing_cost)
            if not day:
                continue
            if message_id:
                message_ids.add(str(message_id))
            day_key = day.pop("date")
            target = days.setdefault(day_key, _empty_token_day())
            _add_token_usage(target, day["in"], day["out"], day["cr"], day["cw"],
                             day["reason"], day["cost"])
            for model, usage in day["models"].items():
                _add_model_usage(target["models"], model, usage["in"], usage["out"],
                                 usage["cr"], usage["cw"], usage["reason"], usage["cost"])
            for hour, amount in enumerate(day["hours"]):
                target["hours"][hour] += amount
            if day.get("session"):
                sessions.setdefault(day_key, set()).add(day["session"])
    finally:
        connection.close()
    for day_key, ids in sessions.items():
        days[day_key]["sessions"] = sorted(ids)
    return days, sorted(message_ids)


def scan_opencode(bounds, cache):
    fc = cache.setdefault("opencode", {})
    changed = False
    B = _empty_token_ranges()
    db_paths = _opencode_db_paths()
    json_dirs = _opencode_json_dirs()
    if not db_paths and not json_dirs:
        if fc:
            fc.clear()
            cache["_dirty"] = True
        return {"ranges": B}

    stale = set(fc.keys())
    db_message_ids = set()

    for db_path in db_paths:
        cache_key = "db:" + db_path
        stale.discard(cache_key)
        signature = _sqlite_signature(db_path)
        entry = fc.get(cache_key)
        if not entry or entry.get("sig") != signature:
            try:
                days, message_ids = _scan_opencode_database(db_path)
            except Exception:
                continue
            entry = {"sig": signature, "days": days, "message_ids": message_ids, "source": "sqlite"}
            fc[cache_key] = entry
            changed = True
        db_message_ids.update(entry.get("message_ids", []))
        for day_key, day in entry.get("days", {}).items():
            try:
                day_date = date.fromisoformat(day_key)
            except ValueError:
                continue
            for range_key in classify_date(day_date, bounds):
                _merge_token_day(B[range_key], day)
                B[range_key]["sessions"].update(day.get("sessions", []))

    seen_message_ids = set(db_message_ids)
    for json_dir in json_dirs:
        for sess_dir in glob.glob(os.path.join(json_dir, "ses_*")):
            for f in glob.glob(os.path.join(sess_dir, "msg_*.json")):
                file_id = os.path.splitext(os.path.basename(f))[0]
                if file_id in seen_message_ids:
                    continue
                try:
                    st = os.stat(f)
                except OSError:
                    continue
                sig = f"{st.st_mtime}:{st.st_size}"
                entry = fc.get(f)
                if entry and entry.get("sig") == sig:
                    day_data = entry.get("day")
                    message_id = entry.get("message_id") or file_id
                else:
                    try:
                        with open(f, encoding="utf-8") as handle:
                            d = json.load(handle)
                    except Exception:
                        continue
                    message_id = str(d.get("id") or file_id)
                    if message_id in seen_message_ids:
                        continue
                    day_data = _opencode_message_day(d)
                    fc[f] = {"sig": sig, "day": day_data, "message_id": message_id}
                    changed = True
                if message_id in seen_message_ids:
                    continue
                seen_message_ids.add(message_id)
                stale.discard(f)

                if not day_data:
                    continue
                try:
                    dd = date.fromisoformat(day_data["date"])
                except ValueError:
                    continue
                for k in classify_date(dd, bounds):
                    _merge_token_day(B[k], day_data, day_data.get("session"))

    for p in stale:
        fc.pop(p, None)
        changed = True
    if changed:
        cache["_dirty"] = True
    return {"ranges": B}


# ---------- ZCode ----------
# SQLite: ~/.zcode/cli/db/db.sqlite, model_usage rows use epoch milliseconds.
def _scan_zcode_database(path):
    import sqlite3

    def number(value):
        try:
            return max(int(value or 0), 0)
        except (TypeError, ValueError, OverflowError):
            return 0

    days = {}
    sessions = {}
    connection = sqlite3.connect(_sqlite_ro_uri(path), uri=True, timeout=1)
    try:
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute("""
            SELECT id, session_id, model_id, input_tokens, output_tokens,
                   reasoning_tokens, cache_creation_input_tokens,
                   cache_read_input_tokens, started_at, completed_at
            FROM model_usage
            ORDER BY started_at ASC
        """)
        for row_id, session_id, model, input_total, output_total, reasoning, cache_write, cache_read, started_at, completed_at in rows:
            timestamp_ms = number(completed_at) or number(started_at)
            if not timestamp_ms:
                continue
            try:
                created = datetime.fromtimestamp(timestamp_ms / 1000).astimezone()
            except (OSError, OverflowError, ValueError):
                continue
            input_total = number(input_total)
            output_total = number(output_total)
            reasoning = number(reasoning)
            cache_write = number(cache_write)
            cache_read = number(cache_read)
            fresh_input = max(input_total - cache_read - cache_write, 0)
            visible_output = max(output_total - reasoning, 0)
            if fresh_input + output_total + cache_read + cache_write <= 0:
                continue
            display_model = _known_id_or_raw(model) or str(model or "unknown")
            price_id = _pricing_id(model)
            cost = 0.0
            if price_id:
                price = _raw_price(price_id)
                cost = (fresh_input / 1e6 * price["in"]
                        + output_total / 1e6 * price["out"]
                        + cache_read / 1e6 * price["cache_read"]
                        + cache_write / 1e6 * price["cache_write"])
            day_key = created.date().isoformat()
            day = days.setdefault(day_key, _empty_token_day())
            _add_token_usage(day, fresh_input, visible_output, cache_read, cache_write,
                             reasoning, cost, display_model)
            day["hours"][created.hour] += fresh_input + output_total + cache_read + cache_write
            sessions.setdefault(day_key, set()).add(str(session_id or row_id or "unknown"))
    finally:
        connection.close()
    for day_key, session_ids in sessions.items():
        days[day_key]["sessions"] = sorted(session_ids)
    return days


def scan_zcode(bounds, cache):
    fc = cache.setdefault("zcode", {})
    B = _empty_token_ranges()
    if not os.path.isfile(ZCODE_DB):
        if fc:
            fc.clear()
            cache["_dirty"] = True
        return {"ranges": B}

    cache_key = "db:" + os.path.realpath(ZCODE_DB)
    signature = _sqlite_signature(ZCODE_DB)
    entry = fc.get(cache_key)
    if not entry or entry.get("sig") != signature or entry.get("version") != 1:
        entry = {"sig": signature, "days": _scan_zcode_database(ZCODE_DB), "version": 1}
        fc.clear()
        fc[cache_key] = entry
        cache["_dirty"] = True

    for day_key, day in entry.get("days", {}).items():
        try:
            day_date = date.fromisoformat(day_key)
        except ValueError:
            continue
        for range_key in classify_date(day_date, bounds):
            _merge_token_day(B[range_key], day)
            B[range_key]["sessions"].update(day.get("sessions", []))
    return {"ranges": B}


# ---------- MiMoCode ----------
# MiMoCode uses the OpenCode message schema and XDG data-directory rules.
def _mimocode_data_dirs():
    configured_home = os.environ.get("MIMOCODE_HOME")
    if configured_home:
        return [os.path.abspath(os.path.expanduser(os.path.join(configured_home, "data")))]
    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        return [os.path.abspath(os.path.expanduser(os.path.join(xdg_data, "mimocode")))]
    mac = os.path.join(HOME, "Library", "Application Support", "mimocode")
    linux = os.path.join(HOME, ".local", "share", "mimocode")
    windows = [os.path.join(LOCALAPPDATA, "mimocode"), os.path.join(APPDATA, "mimocode")]
    if os.name == "nt":
        ordered = windows + [linux, mac]
    else:
        ordered = [mac, linux] if sys.platform == "darwin" else [linux, mac]
    return list(dict.fromkeys(os.path.abspath(path) for path in ordered))


def _mimocode_db_paths():
    if MIMOCODE_DB:
        return [os.path.realpath(MIMOCODE_DB)] if os.path.isfile(MIMOCODE_DB) else []
    for data_dir in _mimocode_data_dirs():
        default = os.path.join(data_dir, "mimocode.db")
        if os.path.isfile(default):
            return [os.path.realpath(default)]
        channels = []
        for path in glob.glob(os.path.join(data_dir, "mimocode-*.db")):
            channel = os.path.basename(path)[len("mimocode-"):-len(".db")]
            if channel and all(ch.isalnum() or ch in "._-" for ch in channel):
                channels.append(path)
        if channels:
            active = max(channels, key=lambda path: os.path.getmtime(path))
            return [os.path.realpath(active)]
    return []


def scan_mimocode(bounds, cache):
    fc = cache.setdefault("mimocode", {})
    B = _empty_token_ranges()
    db_paths = _mimocode_db_paths()
    if not db_paths:
        if fc:
            fc.clear()
            cache["_dirty"] = True
        return {"ranges": B}

    db_path = db_paths[0]
    cache_key = "db:" + db_path
    signature = _sqlite_signature(db_path)
    entry = fc.get(cache_key)
    if not entry or entry.get("sig") != signature or entry.get("version") != 1:
        days, _ = _scan_opencode_database(db_path, estimate_missing_cost=True)
        entry = {"sig": signature, "days": days, "version": 1}
        fc.clear()
        fc[cache_key] = entry
        cache["_dirty"] = True

    for day_key, day in entry.get("days", {}).items():
        try:
            day_date = date.fromisoformat(day_key)
        except ValueError:
            continue
        for range_key in classify_date(day_date, bounds):
            _merge_token_day(B[range_key], day)
            B[range_key]["sessions"].update(day.get("sessions", []))
    return {"ranges": B}


# ---------- Qwen Code ----------
# 新版逐请求日志提供实时、按小时数据；旧版会话汇总用于补齐历史。
# 两种来源按 sessionId 去重，逐请求日志覆盖同一会话的汇总快照。
QWEN_CODE_USAGE = os.path.join(QWEN_CODE_DIR, "usage_record.jsonl")


def _qwen_number(value):
    if isinstance(value, bool):
        return 0
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _qwen_runtime_dirs():
    def resolve(path):
        return os.path.abspath(os.path.expanduser(str(path)))

    env_dir = os.environ.get("QWEN_RUNTIME_DIR")
    if env_dir:
        return [resolve(env_dir)]
    settings = _load_json(os.path.join(QWEN_CODE_DIR, "settings.json"), {})
    advanced = settings.get("advanced") if isinstance(settings, dict) else {}
    configured = advanced.get("runtimeOutputDir") if isinstance(advanced, dict) else None
    if isinstance(configured, str) and configured and (
            os.path.isabs(os.path.expanduser(configured)) or configured.startswith("~")):
        return [resolve(configured)]
    return [QWEN_CODE_DIR]


def _qwen_token_usage_files():
    files = set()
    for runtime_dir in _qwen_runtime_dirs():
        files.update(glob.glob(os.path.join(runtime_dir, "usage", "token-usage-*.jsonl")))
    return sorted(files)


def _qwen_datetime(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            seconds = float(value) / 1000 if value > 10_000_000_000 else float(value)
            return datetime.fromtimestamp(seconds).astimezone()
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        dt = parse_ts(value)
        return dt.astimezone() if dt else None
    return None


def _qwen_usage_parts(model, values):
    values = values if isinstance(values, dict) else {}
    input_total = _qwen_number(values.get("inputTokens"))
    cached = _qwen_number(values.get("cachedTokens"))
    if input_total == 0 and cached > 0:
        input_total = cached
    cached = min(cached, input_total)
    inp = max(input_total - cached, 0)
    out = _qwen_number(values.get("outputTokens"))
    reason = _qwen_number(values.get("thoughtsTokens"))
    price = _raw_price(model)
    cost = ((inp * price["in"] + cached * price["cache_read"]
             + (out + reason) * price["out"]) / 1e6)
    return inp, out, cached, reason, cost


def _qwen_request_entry(record):
    if not isinstance(record, dict):
        return None
    version = _qwen_number(record.get("schemaVersion"))
    record_id = str(record.get("id") or "").strip()
    session = str(record.get("sessionId") or "").strip()
    model = str(record.get("model") or "unknown")
    if not record_id or not session or version != 1:
        return None

    dt = _qwen_datetime(record.get("timestamp"))
    day_str = str(record.get("localDate") or "")
    try:
        date.fromisoformat(day_str)
    except ValueError:
        day_str = dt.date().isoformat() if dt else ""
    if not day_str:
        return None

    inp, out, cached, reason, cost = _qwen_usage_parts(model, record)
    models = {}
    _add_model_usage(models, model, inp, out, cached, 0, reason, cost)
    return {
        "date": day_str,
        "hour": dt.hour if dt else None,
        "in": inp,
        "out": out,
        "cr": cached,
        "cw": 0,
        "reason": reason,
        "cost": cost,
        "session": session,
        "models": models,
    }


def _qwen_summary_entry(record):
    if not isinstance(record, dict) or record.get("version") != 1:
        return None
    session = str(record.get("sessionId") or "").strip()
    dt = _qwen_datetime(record.get("timestamp") or record.get("startTime"))
    models_raw = record.get("models") or {}
    if not session or not dt or not isinstance(models_raw, dict):
        return None

    models = {}
    total_in = total_out = total_cr = total_reason = 0
    total_cost = 0.0
    for model, values in models_raw.items():
        inp, out, cached, reason, cost = _qwen_usage_parts(str(model), values)
        _add_model_usage(models, str(model), inp, out, cached, 0, reason, cost)
        total_in += inp
        total_out += out
        total_cr += cached
        total_reason += reason
        total_cost += cost
    return {
        "date": dt.date().isoformat(),
        "hour": dt.hour,
        "in": total_in,
        "out": total_out,
        "cr": total_cr,
        "cw": 0,
        "reason": total_reason,
        "cost": total_cost,
        "session": session,
        "project": record.get("project") or "",
        "models": models,
    }


def _qwen_read_jsonl(paths):
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    try:
                        value = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(value, dict):
                        yield value
        except OSError:
            continue


def _qwen_group_entries(entries):
    grouped = {}
    for entry in entries:
        key = (entry.get("session"), entry.get("date"), entry.get("hour"))
        target = grouped.get(key)
        if target is None:
            target = {
                "date": entry.get("date"),
                "hour": entry.get("hour"),
                "in": 0,
                "out": 0,
                "cr": 0,
                "cw": 0,
                "reason": 0,
                "cost": 0.0,
                "session": entry.get("session"),
                "project": entry.get("project") or "",
                "models": {},
            }
            grouped[key] = target
        _add_token_usage(target, entry.get("in", 0), entry.get("out", 0),
                         entry.get("cr", 0), entry.get("cw", 0), entry.get("reason", 0),
                         entry.get("cost", 0))
        for model, values in entry.get("models", {}).items():
            _add_model_usage(target["models"], model, values.get("in", 0), values.get("out", 0),
                             values.get("cr", 0), values.get("cw", 0), values.get("reason", 0),
                             values.get("cost", 0))
    return list(grouped.values())


def _qwen_entries(token_files, summary_file):
    request_entries = {}
    for record in _qwen_read_jsonl(token_files):
        record_id = str(record.get("id") or "").strip()
        entry = _qwen_request_entry(record)
        if record_id and entry is not None:
            request_entries[record_id] = entry

    entries = list(request_entries.values())
    request_sessions = set()
    for entry in entries:
        request_sessions.add(entry["session"])

    summaries = {}
    if summary_file:
        for record in _qwen_read_jsonl([summary_file]):
            session = str(record.get("sessionId") or "").strip()
            if session:
                summaries[session] = record
    for session, record in summaries.items():
        if session in request_sessions:
            continue
        entry = _qwen_summary_entry(record)
        if entry is not None:
            entries.append(entry)
    return _qwen_group_entries(entries)


def _qwen_source_signature(paths):
    import hashlib
    digest = hashlib.sha256()
    found = False
    for path in sorted(paths):
        try:
            st = os.stat(path)
        except OSError:
            continue
        found = True
        digest.update(path.encode("utf-8", errors="ignore"))
        digest.update(f"\0{st.st_mtime_ns}\0{st.st_size}\0".encode())
    return digest.hexdigest() if found else None


def scan_qwencode(bounds, cache):
    fc = cache.setdefault("qwencode", {})
    B = _empty_token_ranges()
    token_files = _qwen_token_usage_files()
    summary_file = QWEN_CODE_USAGE if os.path.isfile(QWEN_CODE_USAGE) else None
    sources = token_files + ([summary_file] if summary_file else [])
    sig = _qwen_source_signature(sources)
    if sig is None:
        if fc:
            fc.clear()
            cache["_dirty"] = True
        return {"ranges": B}

    if fc.get("sig") != sig:
        entries = _qwen_entries(token_files, summary_file)
        fc.clear()
        fc.update({"sig": sig, "entries": entries})
        cache["_dirty"] = True

    for entry in fc.get("entries", []):
        try:
            day = date.fromisoformat(entry["date"])
        except (TypeError, ValueError, KeyError):
            continue
        for key in classify_date(day, bounds):
            _merge_token_day(B[key], entry, entry.get("session"))
    return {"ranges": B}


def fmt_reset(epoch):
    try:
        return datetime.fromtimestamp(int(epoch)).astimezone().strftime("%m-%d %H:%M")
    except Exception:
        return "?"


# ---------- Claude 套餐用量(读 Claude Desktop 的 Chromium HTTP 缓存) ----------
# 数据来自桌面应用每 ~10min 轮询 /usage 的响应(zstd 压缩),纯本地只读。
CLAUDE_CACHE = os.path.join(
    HOME, "Library", "Application Support", "Claude", "Cache", "Cache_Data"
)
CLAUDE_CACHE_DIRS = _path_candidates(
    "TOKEI_CLAUDE_CACHE_DIR", CLAUDE_CACHE,
    os.path.join(APPDATA, "Claude", "Cache", "Cache_Data"),
    os.path.join(LOCALAPPDATA, "Claude", "Cache", "Cache_Data"))


def _claude_cache_files():
    cache_dirs = _existing_dirs(
        _path_candidates("TOKEI_CLAUDE_CACHE_DIR", CLAUDE_CACHE, *CLAUDE_CACHE_DIRS))
    files = []
    for cache_dir in cache_dirs:
        for path in glob.glob(os.path.join(cache_dir, "*_0")):
            try:
                files.append((os.path.getmtime(path), os.path.realpath(path)))
            except OSError:
                continue
    return [path for _, path in sorted(set(files), reverse=True)]


def _iso_to_epoch(s):
    dt = parse_ts(s) if s else None
    return int(dt.timestamp()) if dt else None


def _zstd_decompress(data):
    """纯 Python 解压,不调任何外部二进制。"""
    try:
        import zstandard
        return zstandard.ZstdDecompressor().decompress(data, max_output_size=len(data) * 20)
    except ImportError:
        pass
    except Exception:
        pass
    return None


def _scan_claude_plan_raw():
    files = _claude_cache_files()
    cand = None
    for f in files[:200]:
        try:
            data = open(f, "rb").read()
        except OSError:
            continue
        if b"organizations/" in data and b"/usage" in data and b"\x28\xb5\x2f\xfd" in data:
            cand = data
            break
    if cand is None:
        return {}
    data = cand
    i = data.find(b"\x28\xb5\x2f\xfd")
    if i < 0:
        return {}
    raw = _zstd_decompress(data[i:])
    if not raw:
        return {}
    try:
        j = json.loads(raw)
    except Exception:
        return {}
    fh_ = j.get("five_hour") or {}
    sd = j.get("seven_day") or {}
    return {
        "q5": fh_.get("utilization"),
        "q5_reset": _iso_to_epoch(fh_.get("resets_at")),
        "q7": sd.get("utilization"),
        "q7_reset": _iso_to_epoch(sd.get("resets_at")),
    }


# Claude 额度只存在 Claude Desktop 的易失缓存条目里,缓存被淘汰/重写的瞬间会读不到。
# 成功时落盘一份,失败时回退到最近一次有效值(30 分钟内,避免跨 reset 显示陈旧)。
_QUOTA_FALLBACK_TTL = 1800

def scan_claude_plan():
    import tempfile
    import time
    cache = os.path.join(tempfile.gettempdir(), "_tokei_claude_quota.json")
    r = _scan_claude_plan_raw()
    if r and r.get("q5") is not None:
        try:
            with open(cache, "w") as fh:
                json.dump({"t": time.time(), "v": r}, fh)
        except OSError:
            pass
        return r
    try:
        with open(cache) as fh:
            c = json.load(fh)
        if time.time() - c["t"] < _QUOTA_FALLBACK_TTL:
            return c["v"]
    except Exception:
        pass
    return r


def compute():
    bounds = range_bounds()
    cache = _load_scan_cache()
    errors = {}
    cc = _safe_scan("claude", lambda: scan_claude(bounds, cache), _empty_claude, errors)
    cx = _safe_scan("codex", lambda: scan_codex(bounds, cache), _empty_codex, errors)
    gm = _safe_scan("gemini", lambda: scan_gemini(bounds, cache), _empty_gemini, errors)
    gk = _safe_scan("grok", lambda: scan_grok(bounds, cache), _empty_grok, errors)
    qd = _safe_scan("qoderwork", lambda: scan_qoder(bounds, cache), _empty_qoder, errors)
    qi = _safe_scan("qoder_ide", lambda: scan_qoder_ide(bounds, cache), _empty_qoder_ide, errors)
    hm = _safe_scan("hermes", lambda: scan_hermes(bounds, cache), _empty_hermes, errors)
    zc = _safe_scan("zcode", lambda: scan_zcode(bounds, cache), _empty_zcode, errors)
    mc = _safe_scan("mimocode", lambda: scan_mimocode(bounds, cache), _empty_mimocode, errors)
    oc = _safe_scan("openclaw", lambda: scan_openclaw(bounds, cache), _empty_openclaw, errors)
    pi = _safe_scan("pi", lambda: scan_pi(bounds, cache), _empty_pi, errors)
    wb = _safe_scan("workbuddy", lambda: scan_workbuddy(bounds, cache), _empty_workbuddy, errors)
    ocode = _safe_scan("opencode", lambda: scan_opencode(bounds, cache), _empty_opencode, errors)
    qwc = _safe_scan("qwencode", lambda: scan_qwencode(bounds, cache), _empty_qwencode, errors)
    _save_scan_cache(cache)

    def claude_range(b):
        denom = b["cr"] + b["cw"] + b["in"]
        hit = (b["cr"] / denom * 100) if denom else 0.0
        models = []
        for n, v in sorted(b["models"].items(), key=lambda kv: -kv[1]["cost"]):
            p = price_for(n)
            models.append({"name": nice_model(n), "in": v["in"], "out": v["out"],
                           "cr": v["cr"], "cw": v["cw"], "cost": v["cost"],
                           "pin": p["in"], "pout": p["out"]})
        return {"hit": hit, "in": b["in"], "out": b["out"],
                "cr": b["cr"], "cw": b["cw"], "cost": b["cost"], "models": models,
                "sessions": len(b["sessions"])}

    def codex_range(b):
        hit = (b["cached"] / b["in"] * 100) if b["in"] else 0.0
        return {"hit": hit, "in": b["in"] - b["cached"], "cached": b["cached"],
                "out": b["out"], "reason": b["reason"], "cost": b["cost"],
                "sessions": len(b["sessions"]), "models": _format_token_models(b.get("models", {}))}

    def gemini_range(b):
        # tokens.input 含 cached,展示口径与 Codex 一致:输入=非缓存部分
        hit = (b["cached"] / b["in"] * 100) if b["in"] else 0.0
        models = []
        for n, v in sorted(b["models"].items(), key=lambda kv: -kv[1]["cost"]):
            p = gemini_price(n)
            models.append({"name": nice_model(n), "in": max(v["in"] - v["cached"], 0),
                           "out": v["out"], "cached": v["cached"], "thoughts": v["thoughts"],
                           "cost": v["cost"], "pin": p["in"], "pout": p["out"]})
        return {"hit": hit, "in": max(b["in"] - b["cached"], 0), "out": b["out"],
                "cached": b["cached"], "thoughts": b["thoughts"], "cost": b["cost"],
                "models": models, "sessions": len(b["sessions"])}

    def grok_range(b):
        latency_count = b.get("latency_count", 0)
        ctx_window = b.get("ctx_window", 0)
        ctx_pct = (b.get("ctx_used", 0) / ctx_window * 100) if ctx_window else 0.0
        usage_total = sum(b.get(key, 0) for key in ("in", "out", "cr", "reason"))
        usage_available = b.get("usage_calls", 0) > 0
        input_total = b.get("in", 0) + b.get("cr", 0)
        hit = (b.get("cr", 0) / input_total * 100) if input_total else 0.0
        return {"tokens": usage_total if usage_available else b.get("ctx_used", 0),
                "hit": hit,
                "in": b.get("in", 0), "out": b.get("out", 0),
                "cr": b.get("cr", 0), "reason": b.get("reason", 0),
                "cost": b.get("cost", 0),
                "models": _format_token_models(b.get("models", {}), include_prices=False),
                "usage_available": usage_available,
                "usage_calls": b.get("usage_calls", 0),
                "usage_sessions": len(b.get("usage_sessions", [])),
                "sessions": len(b.get("sessions", [])),
                "turns": b.get("turns", 0), "tools": b.get("tools", 0),
                "duration": b.get("duration", 0), "ctx_used": b.get("ctx_used", 0),
                "ctx_window": ctx_window, "ctx": ctx_pct,
                "errors": b.get("errors", 0), "cancellations": b.get("cancellations", 0),
                "ttft": int(b.get("ttft_sum", 0) / latency_count) if latency_count else 0,
                "response": int(b.get("response_sum", 0) / latency_count) if latency_count else 0}

    def qoderwork_range(b):
        ctx_count = b.get("ctx_count", 0)
        ctx = (b.get("ctx_sum", 0.0) / ctx_count * 100) if ctx_count else 0.0
        return {"in": b.get("in", 0), "out": b.get("out", 0),
                "sessions": b.get("sessions", 0), "calls": b.get("calls", 0),
                "sub_agents": b.get("sub_agents", 0),
                "turns": b.get("turns", 0),
                "duration": b.get("duration", 0), "ctx": ctx}

    def qoder_range(b):
        total_in = b.get("in", 0)
        cached = b.get("cached", 0)
        # cached is subset of in(prompt_tokens); show non-cached portion as "输入" (consistent with Codex/Gemini)
        ctx = (cached / total_in * 100) if total_in else 0.0
        return {"in": max(total_in - cached, 0), "out": b.get("out", 0), "cached": cached,
                "sessions": b.get("sessions", 0), "sub_agents": b.get("sub_agents", 0),
                "calls": b.get("calls", 0), "messages": b.get("messages", 0),
                "ctx": ctx, "duration": b.get("duration", 0)}

    cranges = {k: claude_range(cc["ranges"][k]) for k in RANGE_KEYS}
    xranges = {k: codex_range(cx["ranges"][k]) for k in RANGE_KEYS}
    granges = {k: gemini_range(gm["ranges"][k]) for k in RANGE_KEYS}
    kranges = {k: grok_range(gk["ranges"][k]) for k in RANGE_KEYS}
    qwranges = {k: qoderwork_range(qd["ranges"][k]) for k in RANGE_KEYS}
    qranges = {k: qoder_range(qi["ranges"][k]) for k in RANGE_KEYS}

    def hermes_range(b):
        denom = b["cr"] + b["cw"] + b["in"]
        hit = (b["cr"] / denom * 100) if denom else 0.0
        return {"hit": hit, "in": b["in"], "out": b["out"], "cr": b["cr"], "cw": b["cw"],
                "reason": b["reason"], "cost": b["cost"], "sessions": b["sessions"],
                "models": _format_token_models(b["models"])}

    def openclaw_range(b):
        denom = b["cr"] + b["cw"] + b["in"]
        hit = (b["cr"] / denom * 100) if denom else 0.0
        return {"tasks": b["tasks"], "completed": b["completed"], "failed": b["failed"],
                "hit": hit, "in": b["in"], "out": b["out"], "cr": b["cr"], "cw": b["cw"],
                "cost": b["cost"], "sessions": len(b["sessions"]),
                "models": _format_token_models(b["models"])}

    hranges = {k: hermes_range(hm["ranges"][k]) for k in RANGE_KEYS}
    oranges = {k: openclaw_range(oc["ranges"][k]) for k in RANGE_KEYS}

    def token_usage_range(b):
        denom = b["cr"] + b["cw"] + b["in"]
        hit = (b["cr"] / denom * 100) if denom else 0.0
        return {"hit": hit, "in": b["in"], "out": b["out"], "cr": b["cr"], "cw": b["cw"],
                "reason": b["reason"], "cost": b["cost"], "sessions": len(b["sessions"]),
                "models": _format_token_models(b["models"])}

    piranges = {k: token_usage_range(pi["ranges"][k]) for k in RANGE_KEYS}
    zcranges = {k: token_usage_range(zc["ranges"][k]) for k in RANGE_KEYS}
    mcranges = {k: token_usage_range(mc["ranges"][k]) for k in RANGE_KEYS}
    wbranges = {k: token_usage_range(wb["ranges"][k]) for k in RANGE_KEYS}
    ocranges = {k: token_usage_range(ocode["ranges"][k]) for k in RANGE_KEYS}
    qwcranges = {k: token_usage_range(qwc["ranges"][k]) for k in RANGE_KEYS}

    cur = cc["cur"]
    cur_total = cur["in"] + cur["out"] + cur["cr"] + cur["cw"]

    quota = _codex_quota_values(cx["limits"])
    p5, pw = quota["p5"], quota["pw"]
    r5, rw = quota["r5"], quota["rw"]

    plan = _safe_scan("claude_plan", scan_claude_plan, lambda: {}, errors) or {}

    result = {
        "claude": {
            "ranges": cranges,
            "session_name": cur["name"], "session_total": cur_total,
            "q5": plan.get("q5"), "q5_reset": plan.get("q5_reset"),
            "q7": plan.get("q7"), "q7_reset": plan.get("q7_reset"),
        },
        "codex": {
            "ranges": xranges,
            "p5": p5, "pw": pw, "r5": r5, "rw": rw,
            "plan": cx["plan"],
        },
        "gemini": {
            "ranges": granges,
        },
        "grok": {
            "ranges": kranges,
            "model": gk["model"],
        },
        "qoderwork": {
            "ranges": qwranges,
            "model": qd.get("model"),
        },
        "qoder": {
            "ranges": qranges,
            "model": qi.get("model"),
        },
        "hermes": {
            "ranges": hranges,
        },
        "zcode": {
            "ranges": zcranges,
        },
        "mimocode": {
            "ranges": mcranges,
        },
        "openclaw": {
            "ranges": oranges,
        },
        "pi": {
            "ranges": piranges,
        },
        "workbuddy": {
            "ranges": wbranges,
        },
        "opencode": {
            "ranges": ocranges,
        },
        "qwencode": {
            "ranges": qwcranges,
        },
    }
    if errors:
        result["_errors"] = errors
    _recalc_costs(result)
    return result


def _recalc_costs(result):
    """用本地最新价格表重算所有模型成本,修正历史/同步数据中的价格偏差。"""
    for tool_key in ("claude", "gemini", "zcode", "mimocode", "pi", "workbuddy",
                     "opencode", "qwencode", "hermes", "openclaw"):
        tool = result.get(tool_key)
        if not tool or "ranges" not in tool:
            continue
        ranges = tool["ranges"]
        for rk in RANGE_KEYS:
            r = ranges.get(rk)
            if not r or "models" not in r:
                continue
            total_cost = 0.0
            for m in r["models"]:
                name = m.get("name", "")
                price_id = _pricing_id(name)
                if not price_id:
                    total_cost += float(m.get("cost", 0) or 0)
                    m["pin"] = 0
                    m["pout"] = 0
                    continue
                p = _raw_price(price_id)
                ti = m.get("in", 0)
                to = m.get("out", 0)
                if tool_key == "claude":
                    cr = m.get("cr", 0)
                    cw = m.get("cw", 0)
                    pf = price_for(name)
                    cost = ti / 1e6 * pf["in"] + to / 1e6 * pf["out"] + cr / 1e6 * pf["cache_read"] + cw / 1e6 * pf["write5m"]
                elif tool_key == "gemini":
                    cached = m.get("cached", 0)
                    cost = ti / 1e6 * p["in"] + to / 1e6 * p["out"] + cached / 1e6 * p["cache_read"]
                elif tool_key in ("zcode", "mimocode"):
                    cr = m.get("cr", 0)
                    cw = m.get("cw", 0)
                    reason = m.get("reason", 0)
                    cost = (ti / 1e6 * p["in"] + (to + reason) / 1e6 * p["out"]
                            + cr / 1e6 * p["cache_read"] + cw / 1e6 * p["cache_write"])
                elif tool_key == "qwencode":
                    cr = m.get("cr", 0)
                    reason = m.get("reason", 0)
                    cost = (ti / 1e6 * p["in"] + (to + reason) / 1e6 * p["out"]
                            + cr / 1e6 * p["cache_read"])
                else:
                    cr = m.get("cr", 0)
                    cw = m.get("cw", 0)
                    cost = ti / 1e6 * p["in"] + to / 1e6 * p["out"] + cr / 1e6 * p["cache_read"] + cw / 1e6 * p["cache_write"]
                m["cost"] = round(cost, 6)
                m["pin"] = p["in"]
                m["pout"] = p["out"]
                total_cost += cost
            r["cost"] = round(total_cost, 6)


_TOKEI_CONFIG = os.path.join(HOME, ".tokei", "config.json")


def _load_tokei_config():
    try:
        with open(_TOKEI_CONFIG) as f:
            return json.load(f)
    except Exception:
        return None


def main_json():
    d = compute()
    meta = _load_json(PRICING_FILE, {}).get("_meta", {})
    d["_pricing"] = {"updated_at": meta.get("updated_at", ""), "count": meta.get("count", 0)}
    print(json.dumps(d, ensure_ascii=False))
    cfg = _load_tokei_config()
    if cfg:
        sync_dir = os.path.expanduser(cfg.get("sync_dir", ""))
        if not sync_dir:
            sync_dir = os.path.join(HOME, ".tokei", "sync")
        device_id = cfg.get("device_id", "")
        if device_id and os.path.isdir(sync_dir):
            import time
            d["_device"] = device_id
            d["_ts"] = int(time.time())
            d["_range_bounds"] = range_boundaries()
            d["_dashboard"] = {
                "daily": build_daily_costs("all", refresh=False).get("daily", []),
                "wrapped": {p: build_wrapped(p, refresh=False)
                            for p in ["all", "1d", "7d", "30d", "365d"]},
            }
            own_name = f"{device_id}.json"
            try:
                for fn in os.listdir(sync_dir):
                    if fn.lower() == own_name.lower():
                        own_name = fn
                        break
            except OSError:
                pass
            try:
                with open(os.path.join(sync_dir, own_name), "w") as f:
                    json.dump(d, f, ensure_ascii=False)
            except OSError:
                pass


def main():
    d = compute()
    c, x = d["claude"], d["codex"]
    ct = c["ranges"]["today"]
    xt = x["ranges"]["today"]
    cc_hit = ct["hit"]
    cc_cost = ct["cost"]
    cur = {"name": c["session_name"]}
    cur_total = c["session_total"]
    cx_hit = xt["hit"]
    p5, pw, r5, rw = x["p5"], x["pw"], x["r5"], x["rw"]

    # ---- menu bar 标题(紧凑):⚡Claude命中率  ◷Codex周额度 ----
    parts = [f"⚡{cc_hit:.0f}"]
    if p5 is not None:
        parts.append(f"◷{p5:.0f}")
    elif pw is not None:
        parts.append(f"◷{pw:.0f}")
    print(" ".join(parts))
    print("---")

    F = "| font=Menlo size=14"
    HEAD = "| font=Menlo-Bold size=15"
    # Claude 块
    print(f"Claude Code {HEAD}")
    print(f"命中率   {cc_hit:5.1f}% {F}")
    print(f"今日 输入   {human(ct['in']):>6} {F}")
    print(f"今日 输出   {human(ct['out']):>6} {F}")
    print(f"今日 缓存读 {human(ct['cr']):>6} {F}")
    print(f"今日 缓存写 {human(ct['cw']):>6} {F}")
    print(f"今日 ≈成本  ${cc_cost:.2f} {F}")
    print(f"  (按 API 价估,非订阅实付) | font=Menlo size=11")
    print(f"本会话({cur['name']}) {human(cur_total)} {F}")
    print("---")
    # Codex 块
    print(f"Codex {HEAD}")
    print(f"命中率   {cx_hit:5.1f}% {F}")
    print(f"今日 输入   {human(xt['in']):>6} {F}")
    print(f"今日 缓存读 {human(xt['cached']):>6} {F}")
    print(f"今日 输出   {human(xt['out']):>6} {F}")
    if xt.get("reason"):
        print(f"今日 推理   {human(xt['reason']):>6} {F}")
    print(f"今日 ≈成本  ${xt['cost']:.2f} {F}")
    print(f"  (按 API 价估,订阅实付不按此) | font=Menlo size=11")
    if p5 is not None:
        print(f"5h 额度  {p5:5.1f}%  reset {fmt_reset(r5)} {F}")
    if pw is not None:
        print(f"周额度   {pw:5.1f}%  reset {fmt_reset(rw)} {F}")
    if x["plan"]:
        print(f"plan: {x['plan']} {F}")
    print("---")
    # Gemini 块
    g = d["gemini"]
    gt = g["ranges"]["today"]
    print(f"Gemini CLI {HEAD}")
    print(f"命中率   {gt['hit']:5.1f}% {F}")
    print(f"今日 输入   {human(gt['in']):>6} {F}")
    print(f"今日 输出   {human(gt['out']):>6} {F}")
    print(f"今日 缓存   {human(gt['cached']):>6} {F}")
    if gt.get("thoughts"):
        print(f"今日 推理   {human(gt['thoughts']):>6} {F}")
    print(f"今日 ≈成本  ${gt['cost']:.2f} {F}")
    print(f"  (按 API 价估,非订阅实付) | font=Menlo size=11")
    print("---")
    # Grok Build 块：优先真实 token，旧日志降级为上下文快照。
    gk = d["grok"]
    kt = gk["ranges"]["today"]
    print(f"Grok Build {HEAD}")
    print(f"今日 会话   {kt['sessions']:>6} {F}")
    if kt.get("usage_available"):
        print(f"今日 输入   {human(kt['in']):>6} {F}")
        print(f"今日 缓存   {human(kt['cr']):>6} {F}")
        print(f"今日 输出   {human(kt['out']):>6} {F}")
        if kt.get("reason"):
            print(f"今日 推理   {human(kt['reason']):>6} {F}")
    else:
        print(f"上下文快照 {human(kt['ctx_used']):>6} {F}")
    if gk.get("model"):
        print(f"model: {gk['model']} {F}")
    print(f"  (成本未提供) | font=Menlo size=11")
    print("---")
    # Pi 块
    pt = d["pi"]["ranges"]["today"]
    if pt["sessions"] > 0:
        print(f"Pi Coding Agent {HEAD}")
        print(f"命中率   {pt['hit']:5.1f}% {F}")
        print(f"今日 输入   {human(pt['in']):>6} {F}")
        print(f"今日 输出   {human(pt['out']):>6} {F}")
        print(f"今日 缓存读 {human(pt['cr']):>6} {F}")
        print(f"今日 缓存写 {human(pt['cw']):>6} {F}")
        print(f"今日 ≈成本  ${pt['cost']:.2f} {F}")
        print("---")
    # WorkBuddy 块
    wt = d["workbuddy"]["ranges"]["today"]
    if wt["sessions"] > 0:
        print(f"WorkBuddy {HEAD}")
        print(f"命中率   {wt['hit']:5.1f}% {F}")
        print(f"今日 输入   {human(wt['in']):>6} {F}")
        print(f"今日 输出   {human(wt['out']):>6} {F}")
        print(f"今日 缓存读 {human(wt['cr']):>6} {F}")
        print(f"今日 ≈成本  ${wt['cost']:.2f} {F}")
        print("---")
    # Qwen Code 块
    qt = d["qwencode"]["ranges"]["today"]
    if qt["sessions"] > 0:
        print(f"Qwen Code {HEAD}")
        print(f"命中率   {qt['hit']:5.1f}% {F}")
        print(f"今日 输入   {human(qt['in']):>6} {F}")
        print(f"今日 输出   {human(qt['out']):>6} {F}")
        print(f"今日 缓存读 {human(qt['cr']):>6} {F}")
        if qt.get("reason"):
            print(f"今日 思考   {human(qt['reason']):>6} {F}")
        print(f"今日 ≈成本  ${qt['cost']:.2f} {F}")
        print("---")
    print("刷新 | refresh=true")


def update_prices():
    """显式联网:拉 OpenRouter /api/v1/models,刷新 pricing.json(不动 overrides)。"""
    import urllib.request
    try:
        with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=30) as r:
            data = json.load(r)["data"]
    except Exception as e:
        print(f"更新失败:{e}", file=sys.stderr)
        return 1

    def mtok(pr, k):
        try:
            return round(float(pr.get(k) or 0) * 1e6, 6)
        except (TypeError, ValueError):
            return 0.0

    models = {}
    for m in data:
        pr = m.get("pricing") or {}
        if not mtok(pr, "prompt") and not mtok(pr, "completion"):
            continue                              # 跳过无价(免费/路由占位)条目
        models[m["id"]] = {"in": mtok(pr, "prompt"), "out": mtok(pr, "completion"),
                           "cache_read": mtok(pr, "input_cache_read"),
                           "cache_write": mtok(pr, "input_cache_write")}
    payload = {"_meta": {"source": "openrouter/api/v1/models",
                         "updated_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z"),
                         "count": len(models)},
               "models": models}
    with open(PRICING_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"已更新 {len(models)} 个模型 → {PRICING_FILE}")
    try:
        os.remove(_SCAN_CACHE_FILE)
    except OSError:
        pass
    return 0


def _scan_local_models():
    """扫描本地所有日志,收集出现过的模型名。"""
    models = set()
    for f in glob.glob(os.path.join(CLAUDE_DIR, "**", "*.jsonl"), recursive=True):
        try:
            with open(f, encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if '"model"' not in line:
                        continue
                    try:
                        m = json.loads(line).get("message", {}).get("model", "")
                        if m and m != "<synthetic>":
                            models.add(m)
                    except Exception:
                        pass
        except OSError:
            pass
    for f in _gemini_session_files():
        parsed = _load_gemini_usage_file(f)
        if not parsed:
            continue
        for event in parsed.get("events", []):
            model = event.get("model")
            if model:
                models.add(model)
    for root in _pi_session_dirs():
        if not os.path.isdir(root):
            continue
        for f in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
            try:
                with open(f, encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        if '"usage"' not in line:
                            continue
                        try:
                            o = json.loads(line)
                            msg = o.get("message") or {}
                            if msg.get("role") == "assistant":
                                models.add(_pi_model_id(msg))
                        except Exception:
                            pass
            except OSError:
                pass
    for f in glob.glob(os.path.join(WORKBUDDY_DIR, "**", "*.jsonl"), recursive=True):
        try:
            with open(f, encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if '"usage"' not in line:
                        continue
                    try:
                        item = json.loads(line)
                        provider = item.get("providerData") or (item.get("message") or {}).get("providerData") or {}
                        model = (provider.get("requestModelName") or provider.get("requestModelId")
                                 or provider.get("model"))
                        if model:
                            models.add(str(model))
                    except Exception:
                        pass
        except OSError:
            pass
    for record in _qwen_read_jsonl(_qwen_token_usage_files()):
        model = record.get("model")
        if model:
            models.add(str(model))
    if os.path.isfile(QWEN_CODE_USAGE):
        for record in _qwen_read_jsonl([QWEN_CODE_USAGE]):
            raw_models = record.get("models") or {}
            if not isinstance(raw_models, dict):
                continue
            for model in raw_models.keys():
                models.add(str(model))
    return models


def _is_exact_match(model: str):
    """检查模型是否有精确价格(非回退)。"""
    s = (model or "").strip()
    if not s or s.lower() == "<synthetic>":
        return True
    if s in _OV_ALIASES:
        return True
    norm = _normalize(model)
    return norm and (norm in _OV_MODELS or norm in _PRICING_DB or norm in _DEFAULT_PRICES)


def _estimate_from_sibling(model: str):
    """尝试从同家族同 tier 的其他版本估价。"""
    low = model.lower()
    tiers = ["max", "plus", "flash", "lite", "turbo", "pro", "mini"]
    tier = None
    for t in tiers:
        if t in low:
            tier = t
            break
    if not tier:
        return None
    all_models = {}
    all_models.update(_PRICING_DB)
    all_models.update(_OV_MODELS)
    candidates = []
    for cid, p in all_models.items():
        if tier in cid.lower():
            family_match = False
            for kw, _ in _FAMILY:
                if kw in low and kw in cid.lower():
                    family_match = True
                    break
            if family_match:
                candidates.append((cid, p))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    best_cid, best_p = candidates[0]
    return {"source": best_cid, "in": best_p.get("in", 0), "out": best_p.get("out", 0),
            "cache_read": best_p.get("cache_read", 0), "cache_write": best_p.get("cache_write", 0)}


def update_unknown():
    """扫描本地日志找未知模型,尝试从 OpenRouter 或同族估价,写入 overrides。"""
    models = _scan_local_models()
    unknown = []
    for m in sorted(models):
        if _is_exact_match(m):
            continue
        rid = _resolve_id(m)
        cur = _raw_price(rid)
        est = _estimate_from_sibling(m)
        unknown.append({"model": m, "resolved_to": rid,
                        "current": {"in": cur["in"], "out": cur["out"]},
                        "estimate": est})

    if not unknown:
        result = {"status": "ok", "message": "所有模型价格已匹配", "count": 0, "added": []}
        print(json.dumps(result, ensure_ascii=False))
        return 0

    try:
        ovr = json.load(open(OVERRIDES_FILE, encoding="utf-8"))
    except Exception:
        ovr = {"models": {}, "aliases": {}}

    added = []
    for u in unknown:
        name = u["model"]
        norm = _normalize(name)
        if not norm:
            continue
        if u["estimate"]:
            e = u["estimate"]
            ovr["models"][norm] = {"in": e["in"], "out": e["out"],
                                   "cache_read": e["cache_read"], "cache_write": e["cache_write"]}
            if name != norm:
                ovr["aliases"][name] = norm
            added.append({"model": name, "canonical": norm, "price": e,
                          "method": f"estimated from {e['source']}"})
        else:
            if name != norm and norm not in ovr.get("aliases", {}):
                ovr["aliases"][name] = norm
            added.append({"model": name, "canonical": norm, "price": None,
                          "method": "no estimate available, using fallback"})

    with open(OVERRIDES_FILE, "w", encoding="utf-8") as f:
        json.dump(ovr, f, ensure_ascii=False, indent=2)
    try:
        os.remove(_SCAN_CACHE_FILE)
    except OSError:
        pass

    result = {"status": "ok", "count": len(added), "added": added}
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _arg_period(default="all"):
    period = default
    for i, a in enumerate(sys.argv):
        if a == "--period" and i + 1 < len(sys.argv):
            period = sys.argv[i + 1]
            break
    return period


def _period_cutoff(period):
    cutoff = None
    today = date.today()
    if period == "1d":
        cutoff = today.isoformat()
    elif period == "7d":
        cutoff = (today - timedelta(days=today.weekday())).isoformat()
    elif period == "30d":
        cutoff = today.replace(day=1).isoformat()
    elif period == "365d":
        cutoff = today.replace(month=1, day=1).isoformat()
    return cutoff


def build_daily_costs(period="all", refresh=True):
    """按天+按模型的成本 JSON 数据,从扫描缓存聚合。"""
    cutoff = _period_cutoff(period)
    if refresh:
        compute()
    cache = _load_scan_cache()
    days = {}
    models = {}

    _empty = lambda: {"claude": 0.0, "codex": 0.0, "zcode": 0.0, "mimocode": 0.0,
                       "pi": 0.0, "workbuddy": 0.0, "opencode": 0.0, "qwencode": 0.0,
                       "c_in": 0, "c_out": 0, "c_cr": 0, "c_cw": 0,
                       "x_in": 0, "x_out": 0, "x_cached": 0, "x_reason": 0,
                       "p_in": 0, "p_out": 0, "p_cr": 0, "p_cw": 0, "p_reason": 0,
                       "w_in": 0, "w_out": 0, "w_cr": 0, "w_cw": 0,
                       "q_in": 0, "q_out": 0, "q_cr": 0, "q_reason": 0,
                       "g_in": 0, "g_out": 0, "g_cr": 0, "g_reason": 0,
                       "tokens": 0, "sessions": 0}

    for fp, entry in cache.get("claude", {}).items():
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            d = days.setdefault(dk, _empty())
            d["claude"] += day.get("cost", 0)
            d["c_in"] += day.get("in", 0); d["c_out"] += day.get("out", 0)
            d["c_cr"] += day.get("cr", 0); d["c_cw"] += day.get("cw", 0)
            d["tokens"] += day.get("in", 0) + day.get("out", 0) + day.get("cr", 0) + day.get("cw", 0)
            d["sessions"] += 1
            for mn, mv in day.get("models", {}).items():
                nm = nice_model(mn)
                m = models.setdefault(nm, {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cw": 0, "tool": "claude"})
                m["cost"] += mv.get("cost", 0)
                m["in"] += mv.get("in", 0); m["out"] += mv.get("out", 0)
                m["cr"] += mv.get("cr", 0); m["cw"] += mv.get("cw", 0)

    for fp, entry in cache.get("codex", {}).items():
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            d = days.setdefault(dk, _empty())
            d["codex"] += day.get("cost", 0)
            d["x_in"] += day.get("in", 0); d["x_out"] += day.get("out", 0)
            d["x_cached"] += day.get("cached", 0); d["x_reason"] += day.get("reason", 0)
            d["tokens"] += day.get("in", 0) + day.get("out", 0)
            for mn, mv in day.get("models", {}).items():
                name = f"{nice_model(mn)} (Codex)"
                model = models.setdefault(name, {"cost": 0.0, "in": 0, "out": 0,
                                                  "cr": 0, "cw": 0, "reason": 0,
                                                  "tool": "codex"})
                model["cost"] += mv.get("cost", 0)
                for key in TOKEN_FIELDS:
                    model[key] += mv.get(key, 0)

    for fp, entry in cache.get("pi", {}).items():
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            d = days.setdefault(dk, _empty())
            d["pi"] += day.get("cost", 0)
            d["p_in"] += day.get("in", 0); d["p_out"] += day.get("out", 0)
            d["p_cr"] += day.get("cr", 0); d["p_cw"] += day.get("cw", 0)
            d["p_reason"] += day.get("reason", 0)
            d["tokens"] += token_total(day)
            for mn, mv in day.get("models", {}).items():
                nm = f"{nice_model(mn)} (Pi)"
                m = models.setdefault(nm, {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "tool": "pi"})
                m["cost"] += mv.get("cost", 0)
                for key in TOKEN_FIELDS:
                    m[key] += mv.get(key, 0)

    for dk, day_data in _iter_cached_token_days(cache.get("opencode", {})):
        if cutoff and dk < cutoff:
            continue
        d = days.setdefault(dk, _empty())
        d["opencode"] += day_data.get("cost", 0)
        d["tokens"] += token_total(day_data)
        for mn, mv in day_data.get("models", {}).items():
            nm = f"{nice_model(mn)} (OpenCode)"
            m = models.setdefault(nm, {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "tool": "opencode"})
            m["cost"] += mv.get("cost", 0)
            for key in TOKEN_FIELDS:
                m[key] += mv.get(key, 0)

    for tool_key, suffix in (("zcode", "ZCode"), ("mimocode", "MiMoCode")):
        for dk, day_data in _iter_cached_token_days(cache.get(tool_key, {})):
            if cutoff and dk < cutoff:
                continue
            d = days.setdefault(dk, _empty())
            d[tool_key] += day_data.get("cost", 0)
            d["tokens"] += token_total(day_data)
            for mn, mv in day_data.get("models", {}).items():
                name = f"{nice_model(mn)} ({suffix})"
                model = models.setdefault(name, {"cost": 0.0, "in": 0, "out": 0,
                                                  "cr": 0, "cw": 0, "reason": 0,
                                                  "tool": tool_key})
                model["cost"] += mv.get("cost", 0)
                for key in TOKEN_FIELDS:
                    model[key] += mv.get(key, 0)

    for _, _, record in _iter_workbuddy_records(cache.get("workbuddy", {})):
        dk = record.get("date")
        if not dk or (cutoff and dk < cutoff):
            continue
        d = days.setdefault(dk, _empty())
        d["workbuddy"] += record.get("cost", 0)
        d["w_in"] += record.get("in", 0); d["w_out"] += record.get("out", 0)
        d["w_cr"] += record.get("cr", 0); d["w_cw"] += record.get("cw", 0)
        d["tokens"] += token_total(record)
        name = f"{nice_model(record.get('model', 'unknown'))} (WorkBuddy)"
        m = models.setdefault(name, {"cost": 0.0, "in": 0, "out": 0, "cr": 0,
                                     "cw": 0, "reason": 0, "tool": "workbuddy"})
        m["cost"] += record.get("cost", 0)
        for key in TOKEN_FIELDS:
            m[key] += record.get(key, 0)

    qwencode_entries = cache.get("qwencode", {}).get("entries", [])
    for entry in qwencode_entries:
        dk = entry.get("date")
        if not dk:
            continue
        if cutoff and dk < cutoff:
            continue
        d = days.setdefault(dk, _empty())
        d["qwencode"] += entry.get("cost", 0)
        d["q_in"] += entry.get("in", 0); d["q_out"] += entry.get("out", 0)
        d["q_cr"] += entry.get("cr", 0); d["q_reason"] += entry.get("reason", 0)
        d["tokens"] += token_total(entry)
        for mn, mv in entry.get("models", {}).items():
            nm = f"{nice_model(mn)} (Qwen Code)"
            m = models.setdefault(nm, {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "tool": "qwencode"})
            m["cost"] += mv.get("cost", 0)
            for key in TOKEN_FIELDS:
                m[key] += mv.get(key, 0)

    grok_sessions, grok_latest_model = _grok_session_metadata()
    for entry in cache.get("grok_usage", {}).get("entries", []):
        dt = parse_ts(entry.get("ts") or "")
        if dt is None:
            continue
        local_dt = dt.astimezone()
        dk = local_dt.date().isoformat()
        if cutoff and dk < cutoff:
            continue
        d = days.setdefault(dk, _empty())
        d["g_in"] += entry.get("in", 0); d["g_out"] += entry.get("out", 0)
        d["g_cr"] += entry.get("cr", 0); d["g_reason"] += entry.get("reason", 0)
        d["tokens"] += token_total(entry)
        model_name = (grok_sessions.get(entry.get("sid")) or {}).get("model") or grok_latest_model or "grok"
        nm = f"{nice_model(model_name)} (Grok Build)"
        m = models.setdefault(nm, {"cost": 0.0, "in": 0, "out": 0, "cr": 0,
                                   "cw": 0, "reason": 0, "tool": "grok"})
        for key in TOKEN_FIELDS:
            m[key] += entry.get(key, 0)

    for fp, entry in cache.get("hermes", {}).items():
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            d = days.setdefault(dk, _empty())
            d["tokens"] += token_total(day)

    for fp, entry in cache.get("qoder", {}).items():
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            d = days.setdefault(dk, _empty())
            d["tokens"] += day.get("in", 0) + day.get("out", 0)

    for fp, entry in cache.get("qoder_ide", {}).items():
        model_name = entry.get("model") or "Qoder"
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            d = days.setdefault(dk, _empty())
            input_total = day.get("in", 0)
            cached = day.get("cached", 0)
            output = day.get("out", 0)
            d["tokens"] += input_total + output
            nm = f"{nice_model(model_name)} (Qoder)"
            m = models.setdefault(nm, {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "tool": "qoder"})
            m["in"] += max(input_total - cached, 0)
            m["out"] += output
            m["cr"] += cached

    codex_total = sum(d["codex"] for d in days.values())
    codex_in = sum(d["x_in"] for d in days.values())
    codex_out = sum(d["x_out"] for d in days.values())
    codex_reason = sum(d["x_reason"] for d in days.values())
    if codex_total > 0 and not any(v.get("tool") == "codex" for v in models.values()):
        models["GPT-5.5 (Codex)"] = {"cost": round(codex_total, 2), "in": codex_in, "out": codex_out,
                                      "reason": codex_reason, "tool": "codex"}

    daily = [{"date": dk, "claude": round(v["claude"], 2), "codex": round(v["codex"], 2),
              "zcode": round(v["zcode"], 2), "mimocode": round(v["mimocode"], 2), "pi": round(v["pi"], 2),
              "workbuddy": round(v["workbuddy"], 2), "qwencode": round(v["qwencode"], 2),
              "total": round(v["claude"] + v["codex"] + v["zcode"] + v["mimocode"]
                             + v["pi"] + v["workbuddy"]
                             + v["opencode"] + v["qwencode"], 2),
              "c_in": v["c_in"], "c_out": v["c_out"], "c_cr": v["c_cr"], "c_cw": v["c_cw"],
              "x_in": v["x_in"], "x_out": v["x_out"], "x_cached": v["x_cached"], "x_reason": v["x_reason"],
              "p_in": v["p_in"], "p_out": v["p_out"], "p_cr": v["p_cr"], "p_cw": v["p_cw"], "p_reason": v["p_reason"],
              "w_in": v["w_in"], "w_out": v["w_out"], "w_cr": v["w_cr"], "w_cw": v["w_cw"],
              "q_in": v["q_in"], "q_out": v["q_out"], "q_cr": v["q_cr"], "q_reason": v["q_reason"],
              "g_in": v["g_in"], "g_out": v["g_out"], "g_cr": v["g_cr"], "g_reason": v["g_reason"],
              "tokens": v["tokens"]}
             for dk, v in sorted(days.items())]

    def model_tokens(v):
        if v.get("tool") == "codex":
            return v["in"] + v.get("cr", 0) + v["out"]  # out 已含 reasoning
        return v["in"] + v["out"] + v.get("cr", 0) + v.get("cw", 0) + v.get("reason", 0)

    model_list = []
    for n, v in sorted(models.items(), key=lambda kv: (-kv[1]["cost"], -model_tokens(kv[1]))):
        total_tok = model_tokens(v)
        if v["cost"] <= 0 and total_tok <= 0:
            continue
        out_k = v["out"] / 1000 if v["out"] else 0
        cost_per_k = round(v["cost"] / out_k, 3) if out_k > 0 else 0
        out_ratio = round(v["out"] / total_tok * 100, 1) if total_tok > 0 else 0
        model_list.append({"name": n, "cost": round(v["cost"], 2),
                           "in": v["in"], "out": v["out"], "cr": v.get("cr", 0), "cw": v.get("cw", 0),
                           "reason": v.get("reason", 0), "tokens": total_tok, "tool": v["tool"],
                           "cost_per_k": cost_per_k, "out_ratio": out_ratio})

    return {"daily": daily, "models": model_list}


def daily_costs():
    """输出按天+按模型的成本 JSON(从扫描缓存读,无额外 I/O)。"""
    print(json.dumps(build_daily_costs(_arg_period()), ensure_ascii=False))


def _streak_info(dates):
    """dates: ISO 日期字符串列表。返回 (最长连续天数, 当前连续天数)。"""
    if not dates:
        return 0, 0
    ds = sorted(date.fromisoformat(x) for x in dates)
    max_run = run = 1
    for i in range(1, len(ds)):
        run = run + 1 if (ds[i] - ds[i - 1]).days == 1 else 1
        if run > max_run:
            max_run = run
    cur = 0
    if (date.today() - ds[-1]).days <= 1:   # 仅当最近活跃日是今/昨天才算"当前连续"
        cur = 1
        for i in range(len(ds) - 1, 0, -1):
            if (ds[i] - ds[i - 1]).days == 1:
                cur += 1
            else:
                break
    return max_run, cur


def build_wrapped(period="all", refresh=True):
    """Tokei 回顾数据。汇总全部工具,不联网。"""
    cutoff = _period_cutoff(period)
    if refresh:
        compute()
    cache = _load_scan_cache()

    hours = [0] * 24
    weekday = [0] * 7
    day_tokens = {}
    proj_tok = {}
    day_projs = {}
    model_tok = {}
    all_day_hours = set()
    total_tokens = 0
    total_cost = 0.0

    # --- Claude (有 hours / proj / models) ---
    fc = cache.get("claude", {})
    for f, entry in fc.items():
        if not isinstance(entry, dict):
            continue
        h = entry.get("hours")
        if h and len(h) == 24:
            for i in range(24):
                hours[i] += h[i]
        for dh_item in entry.get("dh", []):
            dk_part = dh_item.rsplit(":", 1)[0] if ":" in dh_item else ""
            if not cutoff or dk_part >= cutoff:
                all_day_hours.add(dh_item)
        proj_path = entry.get("proj") or ""
        proj = os.path.basename(proj_path.rstrip("/")) or "?"
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            tok = token_total(day)
            day_tokens[dk] = day_tokens.get(dk, 0) + tok
            total_tokens += tok
            total_cost += day.get("cost", 0)
            pt = proj_tok.setdefault(proj, [0, 0.0])
            pt[0] += tok; pt[1] += day.get("cost", 0)
            day_projs.setdefault(dk, set()).add(proj)
            weekday[date.fromisoformat(dk).weekday()] += tok
            for mn, mv in day.get("models", {}).items():
                nm = nice_model(mn)
                model_tok[nm] = model_tok.get(nm, 0) + token_total(mv)

    # --- Codex (in + out; in 已含 cached, out 已含 reason) ---
    for f, entry in cache.get("codex", {}).items():
        if not isinstance(entry, dict):
            continue
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            tok = day.get("in", 0) + day.get("out", 0)
            day_tokens[dk] = day_tokens.get(dk, 0) + tok
            total_tokens += tok
            total_cost += day.get("cost", 0)
            weekday[date.fromisoformat(dk).weekday()] += tok
            for hour, amount in enumerate(day.get("hours", [])):
                hours[hour] += amount
                if amount:
                    all_day_hours.add(f"{dk}:{hour}")
            for model, usage in day.get("models", {}).items():
                name = f"{nice_model(model)} (Codex)"
                model_tokens = usage.get("in", 0) + usage.get("cr", 0) + usage.get("out", 0)
                model_tok[name] = model_tok.get(name, 0) + model_tokens

    # --- Hermes (in + out + cr + cw + reason) ---
    for f, entry in cache.get("hermes", {}).items():
        if not isinstance(entry, dict):
            continue
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            tok = token_total(day)
            day_tokens[dk] = day_tokens.get(dk, 0) + tok
            total_tokens += tok
            total_cost += day.get("cost", 0)
            weekday[date.fromisoformat(dk).weekday()] += tok

    # --- OpenClaw (in + out + cr + cw) ---
    for f, entry in cache.get("openclaw", {}).items():
        if not isinstance(entry, dict):
            continue
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            tok = token_total(day)
            day_tokens[dk] = day_tokens.get(dk, 0) + tok
            total_tokens += tok
            total_cost += day.get("cost", 0)
            weekday[date.fromisoformat(dk).weekday()] += tok

    # --- OpenCode (in + out + cr + cw + reason) ---
    for dk, day in _iter_cached_token_days(cache.get("opencode", {})):
        if cutoff and dk < cutoff:
            continue
        tok = token_total(day)
        day_tokens[dk] = day_tokens.get(dk, 0) + tok
        total_tokens += tok
        total_cost += day.get("cost", 0)
        weekday[date.fromisoformat(dk).weekday()] += tok
        for hour, amount in enumerate(day.get("hours", [])):
            hours[hour] += amount
            if amount:
                all_day_hours.add(f"{dk}:{hour}")
        for model, usage in day.get("models", {}).items():
            name = f"{nice_model(model)} (OpenCode)"
            model_tok[name] = model_tok.get(name, 0) + token_total(usage)

    # --- ZCode / MiMoCode ---
    for tool_key, suffix in (("zcode", "ZCode"), ("mimocode", "MiMoCode")):
        for dk, day in _iter_cached_token_days(cache.get(tool_key, {})):
            if cutoff and dk < cutoff:
                continue
            tok = token_total(day)
            day_tokens[dk] = day_tokens.get(dk, 0) + tok
            total_tokens += tok
            total_cost += day.get("cost", 0)
            weekday[date.fromisoformat(dk).weekday()] += tok
            for hour, amount in enumerate(day.get("hours", [])):
                hours[hour] += amount
                if amount:
                    all_day_hours.add(f"{dk}:{hour}")
            for model, usage in day.get("models", {}).items():
                name = f"{nice_model(model)} ({suffix})"
                model_tok[name] = model_tok.get(name, 0) + token_total(usage)

    # --- Qwen Code (in + out + cr + reason) ---
    for entry in cache.get("qwencode", {}).get("entries", []):
        dk = entry.get("date")
        if not dk:
            continue
        if cutoff and dk < cutoff:
            continue
        tok = token_total(entry)
        day_tokens[dk] = day_tokens.get(dk, 0) + tok
        total_tokens += tok
        total_cost += entry.get("cost", 0)
        weekday[date.fromisoformat(dk).weekday()] += tok
        hour = entry.get("hour")
        if isinstance(hour, int) and 0 <= hour < 24:
            hours[hour] += tok
            all_day_hours.add(f"{dk}:{hour}")
        for mn, mv in entry.get("models", {}).items():
            nm = f"{nice_model(mn)} (Qwen Code)"
            model_tok[nm] = model_tok.get(nm, 0) + token_total(mv)

    # --- Pi Coding Agent (in + out + cr + cw + reason) ---
    for f, entry in cache.get("pi", {}).items():
        if not isinstance(entry, dict):
            continue
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            tok = token_total(day)
            day_tokens[dk] = day_tokens.get(dk, 0) + tok
            total_tokens += tok
            total_cost += day.get("cost", 0)
            weekday[date.fromisoformat(dk).weekday()] += tok
            for mn, mv in day.get("models", {}).items():
                nm = f"{nice_model(mn)} (Pi)"
                model_tok[nm] = model_tok.get(nm, 0) + token_total(mv)

    # --- WorkBuddy (逐次调用，output 已含 reasoning) ---
    for _, entry, record in _iter_workbuddy_records(cache.get("workbuddy", {})):
        dk = record.get("date", "")
        if not dk or (cutoff and dk < cutoff):
            continue
        tok = token_total(record)
        day_tokens[dk] = day_tokens.get(dk, 0) + tok
        total_tokens += tok
        total_cost += record.get("cost", 0)
        weekday[date.fromisoformat(dk).weekday()] += tok
        hour = record.get("hour")
        if isinstance(hour, int) and 0 <= hour < 24:
            hours[hour] += tok
            all_day_hours.add(f"{dk}:{hour}")
        project_path = entry.get("proj") or ""
        project = os.path.basename(project_path.rstrip("/")) or "WorkBuddy"
        pt = proj_tok.setdefault(project, [0, 0.0])
        pt[0] += tok; pt[1] += record.get("cost", 0)
        day_projs.setdefault(dk, set()).add(project)
        model_name = f"{nice_model(record.get('model', 'unknown'))} (WorkBuddy)"
        model_tok[model_name] = model_tok.get(model_name, 0) + tok

    # --- QoderWork (in + out, no cost) ---
    for f, entry in cache.get("qoder", {}).items():
        if not isinstance(entry, dict):
            continue
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            tok = day.get("in", 0) + day.get("out", 0)
            day_tokens[dk] = day_tokens.get(dk, 0) + tok
            total_tokens += tok
            weekday[date.fromisoformat(dk).weekday()] += tok

    # --- Qoder IDE (in + out, no cost; cached is subset of in) ---
    for f, entry in cache.get("qoder_ide", {}).items():
        if not isinstance(entry, dict):
            continue
        model_name = entry.get("model") or "Qoder"
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            tok = day.get("in", 0) + day.get("out", 0)
            day_tokens[dk] = day_tokens.get(dk, 0) + tok
            total_tokens += tok
            weekday[date.fromisoformat(dk).weekday()] += tok
            nm = f"{nice_model(model_name)} (Qoder)"
            model_tok[nm] = model_tok.get(nm, 0) + tok

    # --- Grok Build（unified 日志中的真实 token）---
    grok_sessions, grok_latest_model = _grok_session_metadata()
    for entry in cache.get("grok_usage", {}).get("entries", []):
        dt = parse_ts(entry.get("ts") or "")
        if dt is None:
            continue
        local_dt = dt.astimezone()
        dk = local_dt.date().isoformat()
        if cutoff and dk < cutoff:
            continue
        tok = token_total(entry)
        day_tokens[dk] = day_tokens.get(dk, 0) + tok
        total_tokens += tok
        weekday[local_dt.weekday()] += tok
        hours[local_dt.hour] += tok
        all_day_hours.add(f"{dk}:{local_dt.hour}")
        meta = grok_sessions.get(entry.get("sid")) or {}
        project_path = meta.get("project") or ""
        project = os.path.basename(project_path.rstrip("/")) or "?"
        if project != "?":
            pt = proj_tok.setdefault(project, [0, 0.0])
            pt[0] += tok
            day_projs.setdefault(dk, set()).add(project)
        model_name = meta.get("model") or grok_latest_model or "grok"
        display_name = f"{nice_model(model_name)} (Grok Build)"
        model_tok[display_name] = model_tok.get(display_name, 0) + tok

    # --- Gemini (无缓存,需重新扫描取 year 总量;仅 all/365d 包含) ---
    if period in ("all", "365d"):
        try:
            bounds = range_bounds()
            gm = scan_gemini(bounds, cache)
            yr = gm["ranges"].get("year", {})
            gm_tok = yr.get("in", 0) + yr.get("out", 0) + yr.get("cached", 0) + yr.get("thoughts", 0)
            total_tokens += gm_tok
            total_cost += yr.get("cost", 0)
        except Exception:
            pass

    active = sorted(day_tokens.keys())
    streak_max, streak_cur = _streak_info(active)
    busiest_dk, busiest_tok = (max(day_tokens.items(), key=lambda kv: kv[1])
                               if day_tokens else ("", 0))
    top_model_name, top_model_tok = (max(model_tok.items(), key=lambda kv: kv[1])
                                     if model_tok else ("-", 0))
    projects = sorted(
        ({"name": p, "tokens": v[0], "cost": round(v[1], 2)} for p, v in proj_tok.items()),
        key=lambda x: -x["tokens"])[:8]
    max_projs_day = max((len(s) for s in day_projs.values()), default=0)
    hours_total = sum(hours)
    night = sum(hours[0:6])
    night_share = round(night / hours_total * 100, 1) if hours_total else 0.0

    ach = []
    def add(icon, title, desc, tint):
        ach.append({"icon": icon, "title": title, "desc": desc, "tint": tint})

    # Token 里程碑(金,取最高档)
    if total_tokens >= 1_000_000_000_000:
        add("crown.fill", "万亿先生", f"{total_tokens/1e12:.2f} 万亿 token", "gold")
    elif total_tokens >= 100_000_000_000:
        add("hexagon.fill", "千亿先生", f"{total_tokens/1e8:.0f} 亿 token", "gold")
    elif total_tokens >= 10_000_000_000:
        add("diamond.fill", "百亿先生", f"{total_tokens/1e8:.0f} 亿 token", "gold")
    elif total_tokens >= 1_000_000_000:
        add("diamond", "十亿先生", f"{total_tokens/1e8:.1f} 亿 token", "gold")

    # 成本里程碑(绿,取最高档)
    if total_cost >= 100000:
        add("dollarsign.circle.fill", "十万刀", f"≈${int(total_cost):,}", "green")
    elif total_cost >= 10000:
        add("banknote.fill", "破万刀", f"≈${int(total_cost):,}", "green")
    elif total_cost >= 1000:
        add("banknote", "破千刀", f"≈${int(total_cost):,}", "green")

    # 连续打卡(火橙,取最高档)
    if streak_max >= 100:
        add("flame.fill", "百日筑基", f"连续 {streak_max} 天", "coral")
    elif streak_max >= 30:
        add("flame.fill", "铁人", f"连续 {streak_max} 天", "coral")
    elif streak_max >= 7:
        add("flame.fill", "坚持", f"连续 {streak_max} 天", "coral")

    # 单日爆发(火橙)
    if busiest_tok >= 1_000_000_000:
        add("bolt.fill", "爆肝日", f"单日 {busiest_tok/1e8:.0f} 亿 token", "coral")

    # 项目维度(青蓝)
    if max_projs_day >= 5:
        add("square.grid.3x3.fill", "多线作战", f"单日 {max_projs_day} 个项目", "blue")
    elif max_projs_day >= 3:
        add("square.grid.2x2.fill", "多面手", f"单日 {max_projs_day} 个项目", "blue")
    claude_tokens = sum(v[0] for v in proj_tok.values())
    top_share = (max(v[0] for v in proj_tok.values()) / claude_tokens * 100) if (proj_tok and claude_tokens) else 0
    if top_share >= 50:
        add("scope", "专一", f"主项目占 {top_share:.0f}%", "blue")
    if len(proj_tok) >= 10:
        add("rectangle.3.group.fill", "广撒网", f"{len(proj_tok)} 个项目", "blue")

    # 作息彩蛋(紫)
    active_hours = sum(1 for h in hours if h > 0)
    if active_hours >= 24:
        add("clock.badge.checkmark.fill", "永动机", "24h 每个时段都有活跃", "purple")
    # Loop 成就: 连续 N 天每天 24h 全时段有 agent 活跃
    day_hour_map = {}
    for item in all_day_hours:
        dk, h = item.rsplit(":", 1)
        day_hour_map.setdefault(dk, set()).add(int(h))
    full_days = sorted(dk for dk, hs in day_hour_map.items() if len(hs) >= 24)
    loop_streak = 0
    if full_days:
        cur = 1
        for i in range(1, len(full_days)):
            if (date.fromisoformat(full_days[i]) - date.fromisoformat(full_days[i - 1])).days == 1:
                cur += 1
            else:
                loop_streak = max(loop_streak, cur)
                cur = 1
        loop_streak = max(loop_streak, cur)
    if loop_streak >= 30:
        add("repeat.circle.fill", "Loop滴神", f"连续 {loop_streak} 天 24/7", "purple")
    elif loop_streak >= 3:
        add("repeat.circle", "Loop Engineering !!", f"连续 {loop_streak} 天 24/7", "purple")
    if night_share >= 5:
        add("moon.stars.fill", "夜猫子", f"{night_share:.0f}% 在凌晨", "purple")
    morning_share = (sum(hours[5:9]) / hours_total * 100) if hours_total else 0
    if morning_share >= 12:
        add("sunrise.fill", "早起鸟", f"{morning_share:.0f}% 在清晨", "purple")
    weekday_total = sum(weekday)
    weekend_share = ((weekday[5] + weekday[6]) / weekday_total * 100) if weekday_total else 0
    if weekend_share >= 30:
        add("beach.umbrella.fill", "周末战士", f"周末占 {weekend_share:.0f}%", "purple")

    # 资历(玫红)
    if len(active) >= 100:
        add("calendar", "元老", f"{len(active)} 天活跃", "pink")

    return {
        "total_tokens": total_tokens,
        "total_cost": round(total_cost, 2),
        "active_days": len(active),
        "streak_max": streak_max,
        "streak_cur": streak_cur,
        "busiest": {"date": busiest_dk, "tokens": busiest_tok},
        "top_model": {"name": top_model_name, "tokens": top_model_tok},
        "hours": hours,
        "weekday": weekday,
        "projects": projects,
        "max_projs_day": max_projs_day,
        "night_share": night_share,
        "first_day": cutoff if cutoff else (active[0] if active else ""),
        "achievements": ach,
        "period": period,
    }


def wrapped():
    """Tokei 回顾:作息 / 项目 / 连续 / 成就。汇总全部工具,不联网。"""
    print(json.dumps(build_wrapped(_arg_period()), ensure_ascii=False))


def projects():
    """项目足迹:从缓存聚合所有项目路径、活跃时间、session 数、token、成本。"""
    compute()
    cache = _load_scan_cache()

    proj_map = {}  # path → {sessions, tokens, cost, last_active, model_tok}

    # Claude sessions
    for f, entry in cache.get("claude", {}).items():
        if not isinstance(entry, dict):
            continue
        proj_path = entry.get("proj") or ""
        if not proj_path or proj_path == "?":
            continue
        p = proj_map.setdefault(proj_path, {"sessions": 0, "tokens": 0, "cost": 0.0,
                                             "last_active": "", "model_tok": {}, "tools": set()})
        p["sessions"] += 1
        p["tools"].add("claude")
        for dk, day in entry.get("days", {}).items():
            tok = token_total(day)
            p["tokens"] += tok
            p["cost"] += day.get("cost", 0)
            if dk > p["last_active"]:
                p["last_active"] = dk
            for mn, mv in day.get("models", {}).items():
                nm = nice_model(mn)
                p["model_tok"][nm] = p["model_tok"].get(nm, 0) + token_total(mv)

    # Pi sessions
    for f, entry in cache.get("pi", {}).items():
        if not isinstance(entry, dict):
            continue
        proj_path = entry.get("proj") or ""
        if not proj_path or proj_path == "?":
            continue
        p = proj_map.setdefault(proj_path, {"sessions": 0, "tokens": 0, "cost": 0.0,
                                             "last_active": "", "model_tok": {}, "tools": set()})
        p["sessions"] += 1
        p["tools"].add("pi")
        for dk, day in entry.get("days", {}).items():
            tok = token_total(day)
            p["tokens"] += tok
            p["cost"] += day.get("cost", 0)
            if dk > p["last_active"]:
                p["last_active"] = dk
            for mn, mv in day.get("models", {}).items():
                nm = f"{nice_model(mn)} (Pi)"
                p["model_tok"][nm] = p["model_tok"].get(nm, 0) + token_total(mv)

    # WorkBuddy sessions
    workbuddy_sessions = {}
    for _, entry, record in _iter_workbuddy_records(cache.get("workbuddy", {})):
        proj_path = entry.get("proj") or ""
        if not proj_path or proj_path == "?":
            continue
        p = proj_map.setdefault(proj_path, {"sessions": 0, "tokens": 0, "cost": 0.0,
                                             "last_active": "", "model_tok": {}, "tools": set()})
        p["tools"].add("workbuddy")
        p["tokens"] += token_total(record)
        p["cost"] += record.get("cost", 0)
        dk = record.get("date", "")
        if dk > p["last_active"]:
            p["last_active"] = dk
        model_name = f"{nice_model(record.get('model', 'unknown'))} (WorkBuddy)"
        p["model_tok"][model_name] = p["model_tok"].get(model_name, 0) + token_total(record)
        workbuddy_sessions.setdefault(proj_path, set()).add(record.get("session") or entry.get("sid"))
    for proj_path, session_ids in workbuddy_sessions.items():
        proj_map[proj_path]["sessions"] += len(session_ids)

    # Grok Build sessions + unified 日志真实 token
    grok_sessions, grok_latest_model = _grok_session_metadata()
    for meta in grok_sessions.values():
        grok_path = meta.get("project") or ""
        if not grok_path:
            continue
        summary = meta.get("summary") or {}
        dt = parse_ts(summary.get("updated_at") or summary.get("created_at") or "")
        p = proj_map.setdefault(grok_path, {"sessions": 0, "tokens": 0, "cost": 0.0,
                                             "last_active": "", "model_tok": {}, "tools": set()})
        p["sessions"] += 1
        p["tools"].add("grok")
        if dt is not None:
            dk = dt.astimezone().date().isoformat()
            if dk > p["last_active"]:
                p["last_active"] = dk
    for usage_entry in cache.get("grok_usage", {}).get("entries", []):
        meta = grok_sessions.get(usage_entry.get("sid")) or {}
        grok_path = meta.get("project") or ""
        if not grok_path:
            continue
        p = proj_map[grok_path]
        tok = token_total(usage_entry)
        p["tokens"] += tok
        model_name = meta.get("model") or grok_latest_model or "grok"
        display_name = f"{nice_model(model_name)} (Grok Build)"
        p["model_tok"][display_name] = p["model_tok"].get(display_name, 0) + tok
        dt = parse_ts(usage_entry.get("ts") or "")
        if dt is not None:
            dk = dt.astimezone().date().isoformat()
            if dk > p["last_active"]:
                p["last_active"] = dk

    # 检测本地 LISTEN 端口,匹配项目 cwd
    port_map = _detect_local_servers(set(proj_map.keys()))

    result = []
    for path, info in proj_map.items():
        name = os.path.basename(path.rstrip("/")) or path
        top_model = max(info["model_tok"].items(), key=lambda kv: kv[1])[0] if info["model_tok"] else ""
        entry = {
            "path": path,
            "name": name,
            "last_active": info["last_active"],
            "sessions": info["sessions"],
            "tokens": info["tokens"],
            "cost": round(info["cost"], 2),
            "top_model": top_model,
            "tools": sorted(info["tools"]),
        }
        if path in port_map:
            entry["ports"] = sorted(port_map[path])
        result.append(entry)
    result.sort(key=lambda x: x["last_active"], reverse=True)
    print(json.dumps(result, ensure_ascii=False))


def _detect_local_servers(project_paths):
    """检测哪些项目目录下有进程正在监听 TCP 端口。返回 {path: [port, ...]}。"""
    import subprocess
    try:
        # 1) pid → ports (LISTEN)
        out1 = subprocess.check_output(
            ["lsof", "-iTCP", "-sTCP:LISTEN", "-P", "-n", "-F", "pn"],
            stderr=subprocess.DEVNULL, timeout=10, text=True)
        pid_ports = {}
        cur_pid = None
        for line in out1.strip().split("\n"):
            if line.startswith("p"):
                cur_pid = line[1:]
            elif line.startswith("n") and cur_pid:
                addr = line[1:]
                port = addr.rsplit(":", 1)[-1] if ":" in addr else None
                if port and port.isdigit():
                    p = int(port)
                    if 1024 <= p <= 65535:
                        pid_ports.setdefault(cur_pid, set()).add(p)

        if not pid_ports:
            return {}

        # 2) pid → cwd (只查有监听端口的 pid，避免全系统扫描超时)
        pid_arg = ",".join(pid_ports.keys())
        out2 = subprocess.check_output(
            ["lsof", "-a", "-d", "cwd", "-p", pid_arg, "-F", "pn"],
            stderr=subprocess.DEVNULL, timeout=10, text=True)
        pid_cwd = {}
        cur_pid = None
        for line in out2.strip().split("\n"):
            if line.startswith("p"):
                cur_pid = line[1:]
            elif line.startswith("n") and cur_pid:
                pid_cwd[cur_pid] = line[1:]

        # 3) 交叉匹配: 进程 cwd 是项目路径或其子目录
        #    匹配最深(最长)的项目路径，避免 home 目录吃掉所有端口
        home = os.path.expanduser("~")
        sorted_projs = sorted(project_paths, key=len, reverse=True)
        result = {}
        for pid, ports in pid_ports.items():
            cwd = pid_cwd.get(pid, "")
            if not cwd or cwd == home:
                continue
            for proj in sorted_projs:
                if proj == home:
                    continue
                if cwd == proj or cwd.startswith(proj + "/"):
                    result.setdefault(proj, set()).update(ports)
                    break
        return result
    except Exception:
        return {}


if __name__ == "__main__":
    if "--update-prices" in sys.argv:
        sys.exit(update_prices())
    if "--update-unknown" in sys.argv:
        sys.exit(update_unknown())
    if "--daily-costs" in sys.argv:
        daily_costs()
    elif "--projects" in sys.argv:
        projects()
    elif "--wrapped" in sys.argv:
        wrapped()
    elif "--json" in sys.argv:
        main_json()
    else:
        main()
