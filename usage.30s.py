#!/usr/bin/env python3
# TOKEI_COLLECTOR_REVISION=6
# <bitbar.title>AI Usage Bar</bitbar.title>
# <bitbar.version>v0.1</bitbar.version>
# <bitbar.author>local</bitbar.author>
# <bitbar.desc>本地 AI coding tools token / 缓存命中 / 花费 / 额度</bitbar.desc>
# <swiftbar.runInBash>false</swiftbar.runInBash>
#
# 数据主要读自本地会话日志,不改动任何 CLI；Codex 额度会短缓存查询官方 live usage。
# Grok 额度默认只读本地 unified.jsonl billing 日志；实时账单接口需显式开启
# (config grok_live_quota_enabled 或 TOKEI_GROK_LIVE_QUOTA=1)。
# 千问办公额度同样默认关闭；开启后仅访问官方桌面端的 127.0.0.1 MCP 适配器，
# 不读取或解密账号凭据 (config qwenwork_quota_enabled 或 TOKEI_QWENWORK_QUOTA=1)。
# Cursor / Zed / Sub2API / z.ai 额度默认关闭；开启卡片后才复用本机登录态或 Keychain
# API Key 查询对应官方/自托管接口。Antigravity 额度只探测已运行的 127.0.0.1 服务。
# --update-prices 仍只在用户显式触发时更新价格表。
#   Claude Code: ~/.claude/projects/<proj>/<session>.jsonl  (assistant 行 message.usage,增量)
#   Codex:       ~/.codex/{sessions,archived_sessions}/**/rollout-*.jsonl (token_count 事件,含额度)
#   Pi:          ~/.pi/agent/sessions/**/*.jsonl + ~/.omp/agent/sessions/**/*.jsonl
#   WorkBuddy:   ~/.workbuddy/projects/**/*.jsonl (逐次模型调用 message.usage)
#   WorkBuddy AI:~/.workbuddy-ai/projects/**/*.jsonl (国际版,同结构独立统计)
#   CodeBuddy:   ~/.codebuddy/projects/**/*.jsonl (逐次模型调用 message.usage)
#   Grok Bot:    ~/Library/Application Support/Grok Bot/sand-client-persistence/*.blob
#                (本地会话活动；当前快照不含 Token / 模型 / 成本)
#                额度默认关闭；授权后由 Tokei 原生 helper 临时读取 Keychain 登录态
#   DeepSeek:    ~/.dsh/sessions/**/*.jsonl.zstd (由 App 原生解压后增量扫描)
#   Qwen Code:   ~/.qwen/usage/token-usage-*.jsonl (逐请求,usage_record.jsonl 补历史)
#   Kimi Code:   ${KIMI_CODE_HOME:-~/.kimi-code}/sessions/*/*/agents/*/wire.jsonl
#                兼容旧版 ${KIMI_SHARE_DIR:-~/.kimi}/sessions/*/*/wire.jsonl
#   Muse Code:   ${TOKEI_MUSE_DIR:-~/.local/share/muse}/sessions/*/*/*/session.jsonl
#                (model_completed 事件 usage,自带模型名；无持久化成本，按价格表估算)
#   Command Code: ${TOKEI_CMDCODE_DIR:-~/.commandcode}/projects/*/*.jsonl
#                (assistant message 自带 usage + costUsd,按 message.id 去重;
#                 inputTokens 含 cached,与 Codex 同口径)

import os
import sys
import glob
import hashlib
import json
import math
import re
import sqlite3
import subprocess
import threading
from datetime import datetime, timedelta, date, timezone
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
CODEX_ARCHIVED_DIR = os.path.join(HOME, ".codex", "archived_sessions")
CODEX_AUTH = os.path.join(HOME, ".codex", "auth.json")
CODEX_CONFIG = os.path.join(HOME, ".codex", "config.toml")
GEMINI_DIR = os.path.join(HOME, ".gemini", "tmp")
ANTIGRAVITY_DIR = os.path.join(HOME, ".gemini", "antigravity-cli", "conversations")
GEMINI_DIRS = _path_candidates(
    "TOKEI_GEMINI_DIR", GEMINI_DIR,
    ANTIGRAVITY_DIR,
    os.path.join(HOME, ".gemini", "antigravity", "conversations"),
    os.path.join(HOME, ".gemini", "antigravity-ide", "conversations"),
    os.path.join(HOME, ".gemini", "gemini-cli", "conversations"),
    *([os.environ["TOKEI_ANTIGRAVITY_DIR"]] if "TOKEI_ANTIGRAVITY_DIR" in os.environ else []))
GROK_HOME = os.path.abspath(os.path.expanduser(
    os.environ.get("GROK_HOME", os.path.join(HOME, ".grok"))))
GROK_DIR = os.path.join(GROK_HOME, "sessions")
GROK_LOG = os.path.join(GROK_HOME, "logs", "unified.jsonl")
GROK_AUTH = os.path.join(GROK_HOME, "auth.json")
WORKBUDDY_DIR = os.path.join(HOME, ".workbuddy", "projects")
WORKBUDDY_AI_DIR = os.path.join(HOME, ".workbuddy-ai", "projects")
CODEBUDDY_DIR = os.path.abspath(os.path.expanduser(os.environ.get(
    "TOKEI_CODEBUDDY_DIR", os.path.join(HOME, ".codebuddy", "projects"))))
GROK_BOT_DIRS = _path_candidates(
    "TOKEI_GROK_BOT_DIR",
    os.path.join(HOME, "Library", "Application Support", "Grok Bot",
                 "sand-client-persistence"),
    os.path.join(APPDATA, "Grok Bot", "sand-client-persistence"),
    os.path.join(HOME, ".config", "Grok Bot", "sand-client-persistence"))
GROK_BOT_SECRET_PATHS = _path_candidates(
    "TOKEI_GROK_BOT_SECRETS",
    os.path.join(HOME, "Library", "Application Support", "Grok Bot",
                 "sand-secrets.json"),
    os.path.join(APPDATA, "Grok Bot", "sand-secrets.json"),
    os.path.join(HOME, ".config", "Grok Bot", "sand-secrets.json"))
GROK_BOT_AUTH_MARKER = _expand_path(os.environ.get(
    "TOKEI_GROK_BOT_AUTH_MARKER",
    os.path.join(HOME, ".tokei", "grok_bot_keychain_authorized")))
DEEPSEEK_HARNESS_DIR = os.path.abspath(os.path.expanduser(os.environ.get(
    "TOKEI_DSH_DECOMPRESSED_DIR", os.path.join(HOME, ".tokei", "cache", "dsh-sessions"))))
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
OPENCLAW_STATE_DIR = os.path.abspath(os.path.expanduser(
    os.environ.get("OPENCLAW_STATE_DIR", os.path.join(HOME, ".openclaw"))))
# Devin（Cognition）。桌面端是改名后的 Windsurf 编辑器：bundle id 仍是
# com.exafunction.windsurf，写出的键也仍叫 windsurf.*。Electron 的支持目录跟随
# 产品名，所以改名前装过 Windsurf 的机器留下 Windsurf/，新装的是 Devin/。
DEVIN_SUPPORT_DIRS = _path_candidates(
    "TOKEI_DEVIN_SUPPORT",
    os.path.join(HOME, "Library", "Application Support", "Devin"),
    os.path.join(HOME, "Library", "Application Support", "Windsurf"),
    os.path.join(APPDATA, "Devin"),
    os.path.join(APPDATA, "Windsurf"),
    os.path.join(HOME, ".config", "Devin"),
    os.path.join(HOME, ".config", "Windsurf"))
# Devin CLI 自己的会话库，和桌面端的套餐缓存互不相干。
DEVIN_CLI_DB_PATHS = _path_candidates(
    "TOKEI_DEVIN_CLI_DB",
    os.path.join(HOME, ".local", "share", "devin", "cli", "sessions.db"),
    os.path.join(HOME, "Library", "Application Support", "devin", "cli", "sessions.db"),
    os.path.join(APPDATA, "devin", "cli", "sessions.db"),
    os.path.join(LOCALAPPDATA, "devin", "cli", "sessions.db"))
OPENCLAW_DB = os.path.join(OPENCLAW_STATE_DIR, "tasks", "runs.sqlite")
OPENCLAW_STATE_DB = os.path.join(OPENCLAW_STATE_DIR, "state", "openclaw.sqlite")
OPENCLAW_AGENTS = os.path.join(OPENCLAW_STATE_DIR, "agents")
PI_AGENT_DIR = os.path.expanduser(os.environ.get("PI_CODING_AGENT_DIR", os.path.join(HOME, ".pi", "agent")))
PI_SESSION_DIR = os.path.expanduser(os.environ.get("PI_CODING_AGENT_SESSION_DIR", os.path.join(PI_AGENT_DIR, "sessions")))
PRIME_AGENT_DIR = os.path.expanduser(os.environ.get(
    "PRIME_AGENT_CODING_AGENT_DIR", os.path.join(HOME, ".prime", "agent")))
PRIME_AGENT_SESSION_DIR = os.path.expanduser(os.environ.get(
    "PRIME_AGENT_SESSION_DIR", os.environ.get(
        "PRIME_AGENT_CODING_AGENT_SESSION_DIR", os.path.join(PRIME_AGENT_DIR, "sessions"))))
OMP_SESSION_DIR = os.path.expanduser(os.environ.get(
    "OMP_CODING_AGENT_SESSION_DIR", os.path.join(HOME, ".omp", "agent", "sessions")))
QWEN_CODE_DIR = os.path.abspath(os.path.expanduser(
    os.environ.get("QWEN_HOME", os.path.join(HOME, ".qwen"))))
QWENWORK_HOME = os.path.abspath(os.path.expanduser(
    os.environ.get("TOKEI_QWENWORK_HOME", os.path.join(HOME, ".qwenworkcn"))))
QWENWORK_MCP_CONFIG = os.path.join(QWENWORK_HOME, "mcp-adaptor.config")
QWENWORK_STATUS = os.path.join(QWENWORK_HOME, ".status.json")
_KIMI_CODE_DEFAULT_DIR = os.path.join(HOME, ".kimi-code")
_KIMI_CODE_LEGACY_DIR = os.path.join(HOME, ".kimi")
KIMI_CODE_DIR = os.path.abspath(os.path.expanduser(
    os.environ.get("TOKEI_KIMI_DIR") or os.environ.get("KIMI_CODE_HOME")
    or os.environ.get("KIMI_SHARE_DIR") or _KIMI_CODE_DEFAULT_DIR))
_MUSE_DEFAULT_DIR = os.path.join(HOME, ".local", "share", "muse")
MUSE_DIR = os.path.abspath(os.path.expanduser(
    os.environ.get("TOKEI_MUSE_DIR") or _MUSE_DEFAULT_DIR))
_CMDCODE_DEFAULT_DIR = os.path.join(HOME, ".commandcode")
CMDCODE_DIR = os.path.abspath(os.path.expanduser(
    os.environ.get("TOKEI_CMDCODE_DIR") or _CMDCODE_DEFAULT_DIR))

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
CODEX_RESET_CARDS_CACHE = _writable_path("codex_reset_cards_cache.json")
CLAUDE_QUOTA_CACHE = _writable_path("claude_quota_cache.json")
GROK_QUOTA_CACHE = _writable_path("grok_quota_cache.json")
QWENWORK_QUOTA_CACHE = _writable_path("qwenwork_quota_cache.json")
PROVIDER_QUOTA_CACHE = _writable_path("provider_quota_cache.json")
ANTIGRAVITY_SCAN_CACHE = _writable_path("antigravity_scan_cache.json")

# 每 1M token 美元单价。基准价来自 OpenRouter,外置在 pricing.json(由 --update-prices 同步);
# pricing_overrides.json 做本地修正(write1h / 别名 / 缺漏),一键更新不覆盖它。
# write5m / write1h = 5 分钟 / 1 小时 缓存写入价(OpenRouter 只给一档 cache_write=5m,
# Anthropic 的 1h 写派生为 2×输入价)。

# 内置兜底:pricing.json 缺失时仍能离线工作。常用直连模型按官方 API 价，
# 其余模型由 pricing.json 的 OpenRouter 目录补齐。
_DEFAULT_PRICES = {
    "anthropic/claude-fable-5.1":   {"in": 10.0,  "out": 50.0, "cache_read": 0.25,   "cache_write": 12.5, "write1h": 20.0},
    "anthropic/claude-sonnet-5":    {"in": 2.0,   "out": 10.0, "cache_read": 0.2,    "cache_write": 2.5},
    "anthropic/claude-opus-4.8":     {"in": 5.0,   "out": 25.0, "cache_read": 0.5,    "cache_write": 6.25},
    "anthropic/claude-sonnet-4.6":   {"in": 3.0,   "out": 15.0, "cache_read": 0.3,    "cache_write": 3.75},
    "anthropic/claude-haiku-4.5":    {"in": 1.0,   "out": 5.0,  "cache_read": 0.1,    "cache_write": 1.25},
    "openai/gpt-5.6-sol":            {"in": 4.0,   "out": 20.0, "cache_read": 0.4,    "cache_write": 5.0},
    "openai/gpt-5.6-terra":          {"in": 2.0,   "out": 12.0, "cache_read": 0.2,    "cache_write": 2.5},
    "openai/gpt-5.6-luna":           {"in": 0.2,   "out": 1.2,  "cache_read": 0.02,   "cache_write": 0.25},
    "openai/gpt-5.5":                {"in": 5.0,   "out": 30.0, "cache_read": 0.5,    "cache_write": 0.0},
    "openai/gpt-6-astra":            {"in": 10.0,  "out": 50.0, "cache_read": 1.0,    "cache_write": 12.5},
    "openai/gpt-6-sol":              {"in": 2.0,   "out": 10.0, "cache_read": 0.2,    "cache_write": 2.5},
    "openai/gpt-6-luna":             {"in": 0.1,   "out": 0.5,  "cache_read": 0.01,   "cache_write": 0.125},
    "qwen/qwen3.8-max":              {"in": 2.0,   "out": 6.0,  "cache_read": 0.25,   "cache_write": 2.5},
    "qwen/qwen3.7-max":              {"in": 1.25,  "out": 3.75, "cache_read": 0.25,   "cache_write": 1.5625},
    "deepseek/deepseek-v4-pro":      {"in": 0.66,  "out": 1.98, "cache_read": 0.022,  "cache_write": 0.0},
    "google/gemini-3.5-flash":       {"in": 1.5,   "out": 9.0,  "cache_read": 0.15,   "cache_write": 0.0833},
    "google/gemini-3.1-pro-preview": {"in": 2.0,   "out": 12.0, "cache_read": 0.2,    "cache_write": 0.375},
    "x-ai/grok-4.6":                 {"in": 2.0,   "out": 6.0,  "cache_read": 0.5,    "cache_write": 0.0},
    "x-ai/grok-4.5":                 {"in": 2.0,   "out": 6.0,  "cache_read": 0.3,    "cache_write": 0.0},
    "tencent/hy3":                   {"in": 0.14,  "out": 0.58, "cache_read": 0.035,  "cache_write": 0.0},
    "tencent/hy3-preview":           {"in": 0.063, "out": 0.21, "cache_read": 0.021,  "cache_write": 0.0},
}

# DeepSeek Harness 的 deepseek-official 路由按官方直连价和调用时间计算。
# 2026-08-16 16:00 UTC 起工作日分峰谷时段；单位为 CNY / 1M tokens。
_DEEPSEEK_LEGACY_PRICES = {
    "deepseek-v4-pro": {
        "in": 3.0, "out": 6.0, "cache_read": 0.025, "cache_write": 0.0,
    },
    "deepseek-v4-flash": {
        "in": 1.0, "out": 2.0, "cache_read": 0.02, "cache_write": 0.0,
    },
}
_DEEPSEEK_CURRENT_PRICES = {
    "deepseek-v4-pro": {
        "off_peak": {"in": 4.5, "out": 13.5, "cache_read": 0.15, "cache_write": 0.0},
        "peak": {"in": 9.0, "out": 27.0, "cache_read": 0.30, "cache_write": 0.0},
    },
    "deepseek-v4-flash": {
        "off_peak": {"in": 1.5, "out": 4.5, "cache_read": 0.05, "cache_write": 0.0},
        "peak": {"in": 3.0, "out": 9.0, "cache_read": 0.10, "cache_write": 0.0},
    },
}
# Official CNY schedule: https://api-docs.deepseek.com/zh-cn/quick_start/pricing/
# September 10 announcement: effective at 04:00 UTC; Pro remains unchanged.
_DEEPSEEK_FLASH_20260910_PRICES = {
    "off_peak": {"in": 1.0, "out": 4.0, "cache_read": 0.02, "cache_write": 0.0},
    "peak": {"in": 2.0, "out": 8.0, "cache_read": 0.04, "cache_write": 0.0},
}
_DEEPSEEK_FLASH_20260910_START = datetime(2026, 9, 10, 4, tzinfo=timezone.utc)
_DEEPSEEK_NEW_PRICING_START = datetime(2026, 8, 16, 16, tzinfo=timezone.utc)


def _deepseek_official_model_id(model):
    model_id = (_normalize(model) or "").rsplit("/", 1)[-1]
    if model_id in ("deepseek-v4-pro", "deepseek-v4-pro-0813"):
        return "deepseek-v4-pro"
    if model_id in ("deepseek-v4-flash", "deepseek-v4-flash-0731",
                    "deepseek-v4-flash-vision-exp", "deepseek-flash", "deepseek-v4.1-flash"):
        return "deepseek-v4-flash"
    return None


def _deepseek_official_price(model, at=None):
    model_id = _deepseek_official_model_id(model)
    if model_id is None:
        return None
    if at is None:
        when = datetime.now(timezone.utc)
    elif isinstance(at, (int, float)):
        seconds = float(at) / 1000 if abs(float(at)) >= 100_000_000_000 else float(at)
        try:
            when = datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    elif isinstance(at, datetime):
        when = at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at.astimezone(timezone.utc)
    else:
        return None
    if when < _DEEPSEEK_NEW_PRICING_START:
        price = _DEEPSEEK_LEGACY_PRICES.get(model_id)
        return dict(price) if price else None
    peak = when.weekday() < 5 and (1 <= when.hour < 4 or 6 <= when.hour < 10)
    schedule = _DEEPSEEK_CURRENT_PRICES.get(model_id, {})
    if model_id == "deepseek-v4-flash" and when >= _DEEPSEEK_FLASH_20260910_START:
        schedule = _DEEPSEEK_FLASH_20260910_PRICES
    price = schedule.get("peak" if peak else "off_peak")
    return dict(price) if price else None


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


_PRICING_DB = _load_json(PRICING_FILE, {}).get("models", {})

# 已安装版本会保留用户自己的 pricing_overrides.json。关键官方修正也随脚本内置，
# 这样升级后立即生效；用户仍可覆盖单价，已确认的官方别名保持固定映射。
_BUILTIN_OVERRIDE_MODELS = {
    # OpenAI Standard API rates, verified 2026-09-23:
    # https://developers.openai.com/api/docs/pricing
    **{model: dict(_DEFAULT_PRICES[model]) for model in (
        "openai/gpt-6-astra", "openai/gpt-6-sol", "openai/gpt-6-luna",
    )},
    "openai/gpt-5.6-sol": {
        "in": 4.0, "out": 20.0, "cache_read": 0.4, "cache_write": 5.0,
    },
}
_BUILTIN_OVERRIDE_ALIASES = {
    "gpt-5.6": "openai/gpt-5.6-sol",
    "qwen3.8-max-0902": "qwen/qwen3.8-max",
    "qwen3.8-max-2026-09-02": "qwen/qwen3.8-max",
    "qwen3.8-max-preview": "qwen/qwen3.8-max",
    "qwen3.8:27b": "qwen/qwen3.8-27b",
}


def _merge_pricing_overrides(overrides):
    overrides = overrides if isinstance(overrides, dict) else {}
    user_models = overrides.get("models")
    user_aliases = overrides.get("aliases")
    models = dict(_BUILTIN_OVERRIDE_MODELS)
    if isinstance(user_models, dict):
        models.update(user_models)
    aliases = dict(user_aliases) if isinstance(user_aliases, dict) else {}
    aliases.update(_BUILTIN_OVERRIDE_ALIASES)
    return models, aliases


_OVERRIDES = _load_json(OVERRIDES_FILE, {})
_OV_MODELS, _OV_ALIASES = _merge_pricing_overrides(_OVERRIDES)


def _effective_pricing_map(catalog=None):
    fields = ("in", "out", "cache_read", "cache_write", "write1h")
    catalog = catalog if isinstance(catalog, dict) else _PRICING_DB
    model_ids = set(_DEFAULT_PRICES) | set(catalog) | set(_OV_MODELS)
    result = {}
    for model in model_ids:
        value = dict(_DEFAULT_PRICES.get(model, {}))
        value.update(catalog.get(model, {}))
        value.update(_OV_MODELS.get(model, {}))
        result[model] = {field: value.get(field, 0.0) for field in fields}
    return result


_PRICING_EFFECTIVE = _effective_pricing_map()


def _make_pricing_fingerprint():
    payload = {
        "prices": _PRICING_EFFECTIVE,
        "aliases": _OV_ALIASES,
        "deepseek_legacy": _DEEPSEEK_LEGACY_PRICES,
        "deepseek_current": _DEEPSEEK_CURRENT_PRICES,
        "deepseek_flash_20260910": _DEEPSEEK_FLASH_20260910_PRICES,
        "deepseek_flash_20260910_start": _DEEPSEEK_FLASH_20260910_START.isoformat(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_PRICING_FINGERPRINT = _make_pricing_fingerprint()
_BUILTIN_REPRICE_MODELS = (
    set(_BUILTIN_OVERRIDE_MODELS)
    | set(_BUILTIN_OVERRIDE_ALIASES)
    | set(_BUILTIN_OVERRIDE_ALIASES.values())
    | {
        "anthropic/claude-fable-5.1", "anthropic/claude-sonnet-5",
        "qwen/qwen3.8-max", "qwen/qwen3.8-27b", "x-ai/grok-4.6",
        "deepseek-v4-pro", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp",
    }
)
_BUILTIN_REPRICE_MULTIPLIERS = {
    # OpenRouter previously supplied 2/10/0.2; current OpenAI direct rates are
    # exactly 2x for every token class, including long-context multipliers.
    "openai/gpt-5.6-sol": 2.0,
}

# 家族关键字 → 代表性 canonical id(精确匹配失败时回退)。
_FAMILY = [
    ("fable",    "anthropic/claude-fable-5.1"),
    ("opus",     "anthropic/claude-opus-4.8"),
    ("sonnet",   "anthropic/claude-sonnet-5"),
    ("haiku",    "anthropic/claude-haiku-4.5"),
    ("gpt-5",    "openai/gpt-5.6-sol"),
    ("qwen",     "qwen/qwen3.8-max"),
    ("deepseek", "deepseek/deepseek-v4-pro"),
    ("grok",     "x-ai/grok-4.6"),
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
    seg = m.rsplit("/", 1)[-1]
    if seg.startswith("muse-"):
        return "meta/" + seg                         # 网关前缀(如 vercel/meta/)剥离
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
    if m.startswith("muse-"):
        return "meta/" + m
    if m.startswith("mimo"):
        return "xiaomi/" + m
    if m == "hy3":
        return "tencent/hy3"
    if m in ("hy3-preview", "hy3 preview"):
        return "tencent/hy3-preview"
    return m


def _override_alias(model: str):
    value = (model or "").strip()
    return _OV_ALIASES.get(value) or _OV_ALIASES.get(value.lower())


def _resolve_id(model: str):
    """解析到 canonical id;未知按 opus 兜底(偏保守)。<synthetic> 返回 None。"""
    s = (model or "").strip()
    if not s or s.lower() == "<synthetic>":
        return None
    alias = _override_alias(s)
    if alias:
        return alias
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
    alias = _override_alias(s)
    if alias:
        return alias
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


def _model_identity_id(model: str):
    """Resolve only exact catalog identities; never guess an unknown model family."""
    s = (model or "").strip()
    if not s or s.lower() == "<synthetic>":
        return None
    alias = _override_alias(s)
    if alias:
        return alias
    norm = _normalize(s)
    if norm and (norm in _OV_MODELS or norm in _PRICING_DB or norm in _DEFAULT_PRICES):
        return norm
    for model_id, entry in _PRICING_DB.items():
        if not isinstance(entry, dict):
            continue
        slug = entry.get("canonical_slug")
        if isinstance(slug, str) and _normalize(slug) == norm:
            return model_id
    return s


def _exact_pricing_id(model: str):
    """Return a catalog pricing ID without family-based fallback."""
    if model and (model in _OV_MODELS or model in _PRICING_DB or model in _DEFAULT_PRICES):
        return model
    return None


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


def _pricing_model_keys(model):
    if not model:
        return set()
    raw = str(model).strip()
    candidates = {raw.lower()}
    normalized = _normalize(raw)
    if normalized:
        candidates.add(normalized.lower())
    resolved = _resolve_id(raw)
    if resolved:
        candidates.add(str(resolved).lower())
    return candidates


def _model_has_pricing_change(model, changed_models):
    changed = {str(value).strip().lower() for value in changed_models if value}
    return bool(_pricing_model_keys(model).intersection(changed))


def _pricing_change_multiplier(model, multipliers):
    normalized = {str(key).strip().lower(): value for key, value in multipliers.items()}
    for key in _pricing_model_keys(model):
        if key in normalized:
            try:
                return float(normalized[key])
            except (TypeError, ValueError):
                return None
    return None


def _cached_entry_has_pricing_change(entry, changed_models):
    if not isinstance(entry, dict):
        return False
    models = set()
    active_model = entry.get("active_model")
    if active_model:
        models.add(active_model)
    for field in ("days", "deduped_days"):
        days = entry.get(field)
        if not isinstance(days, dict):
            continue
        for day in days.values():
            if isinstance(day, dict) and isinstance(day.get("models"), dict):
                models.update(day["models"])
    if not models and isinstance(entry.get("events"), list):
        models.update(event.get("model") for event in entry["events"]
                      if isinstance(event, dict) and event.get("model"))
    return any(_model_has_pricing_change(model, changed_models) for model in models)


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
    if m == "unknown":
        return "未知"
    import re
    s = m.lower()
    for key, disp in (("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku")):
        if key in s:
            mt = re.search(r"(\d+)-(\d+)", s)
            return f"{disp} {mt.group(1)}.{mt.group(2)}" if mt else disp
    if "gpt" in s:
        # Luna Reserve 的内部标识,展示为 Luna Reserve 而不是裸 GPT。
        if re.search(r"(?:^|[-_/ ])reserve(?:$|[-_/ ])", s):
            return "Luna Reserve"
        mt = re.search(r"gpt[- ]?(\d+(?:\.\d+)?)", s)
        version = mt.group(1) if mt else ""
        variant_labels = []
        for token, label in (("astra", "Astra"), ("sol", "Sol"), ("luna", "Luna"), ("terra", "Terra"),
                             ("mini", "Mini"), ("pro", "Pro")):
            if re.search(rf"(?:^|[-_/ ]){token}(?:$|[-_/ ])", s):
                variant_labels.append(label)
        suffix = f" {' '.join(variant_labels)}" if variant_labels else ""
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
import time as _time
_LEGACY_SCAN_CACHE_FILE = os.path.join(
    _tempfile.gettempdir(), "_tokei_scan_cache.json")
_SCAN_CACHE_DIR = os.environ.get("TOKEI_CACHE_DIR") or os.path.join(
    HOME, ".tokei", "cache")
_DEFAULT_SCAN_CACHE_FILE = os.path.join(
    _SCAN_CACHE_DIR, "scan_cache.json")
_SCAN_CACHE_FILE = _DEFAULT_SCAN_CACHE_FILE
_SCAN_CACHE_VERSION = 21
_SCAN_CACHE_MIGRATABLE_VERSION = 19
_CODEX_EVENT_CACHE_SUFFIX = ".codex-events"
_CODEX_PARSER_VERSION = 8
_CODEX_ACCOUNTING_VERSION = 7


# ---------- Codex Luna Reserve ----------
# Luna Reserve 是 OpenAI 给 Codex 的第二缸油:常规高级模型额度见底后,
# 会话切到 gpt-reserve(单独计量、单独重置),用完不影响主额度读数。
# 日志特征:turn_context/session_meta 的 payload.model 为 "gpt-reserve",
# token_count 事件的 rate_limits.limit_name 为 "gpt-reserve",
# limit_id 为 "base_model_inference"(主额度是 "codex")。
_CODEX_RESERVE_MODEL = "gpt-reserve"
_CODEX_RESERVE_LIMIT_NAMES = frozenset({"gpt-reserve"})
_CODEX_RESERVE_LIMIT_IDS = frozenset({"base_model_inference"})
# Reserve 按 Luna 级别计价(官方 API 价 $0.20/$1.20,见 pricing.json)。
_CODEX_RESERVE_PRICE_MODEL = "openai/gpt-5.6-luna"


def _codex_is_reserve_model(model):
    if not isinstance(model, str):
        return False
    m = model.strip().lower()
    if m == _CODEX_RESERVE_MODEL:
        return True
    # _known_id_or_raw 之后可能是 openai/gpt-reserve。
    return m.rsplit("/", 1)[-1] == _CODEX_RESERVE_MODEL


def _codex_is_reserve_limits(rl):
    if not isinstance(rl, dict):
        return False
    name = rl.get("limit_name")
    if isinstance(name, str) and name.strip().lower() in _CODEX_RESERVE_LIMIT_NAMES:
        return True
    limit_id = rl.get("limit_id")
    return isinstance(limit_id, str) and limit_id.strip() in _CODEX_RESERVE_LIMIT_IDS


_CODEX_SCAN_CHECKPOINT_INTERVAL = 5.0
_GEMINI_DAYS_CACHE_KEY = "_gemini_dashboard_days"
_GROK_DAYS_CACHE_KEY = "_grok_dashboard_days"
_CURSOR_PROVIDER_DAYS_CACHE_KEY = "_cursor_provider_days"
_ZAI_PROVIDER_DAYS_CACHE_KEY = "_zai_provider_days"
_GROK_BOT_PROVIDER_DAYS_CACHE_KEY = "_grok_bot_provider_days"


def _remove_codex_event_cache_dir():
    import shutil
    shutil.rmtree(f"{_SCAN_CACHE_FILE}{_CODEX_EVENT_CACHE_SUFFIX}", ignore_errors=True)


def _migrate_legacy_scan_cache():
    if (_SCAN_CACHE_FILE != _DEFAULT_SCAN_CACHE_FILE
            or os.path.exists(_SCAN_CACHE_FILE)
            or not os.path.isfile(_LEGACY_SCAN_CACHE_FILE)):
        return

    import shutil
    directory = os.path.dirname(_SCAN_CACHE_FILE)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass

    fd, tmp = _tempfile.mkstemp(prefix=".scan-cache-", suffix=".json", dir=directory)
    try:
        os.close(fd)
        shutil.copyfile(_LEGACY_SCAN_CACHE_FILE, tmp)
        os.chmod(tmp, 0o600)
        legacy_events = f"{_LEGACY_SCAN_CACHE_FILE}{_CODEX_EVENT_CACHE_SUFFIX}"
        current_events = _codex_event_cache_dir()
        if os.path.isdir(legacy_events) and not os.path.exists(current_events):
            shutil.copytree(legacy_events, current_events)
            try:
                os.chmod(current_events, 0o700)
            except OSError:
                pass
        os.replace(tmp, _SCAN_CACHE_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _load_scan_cache():
    _migrate_legacy_scan_cache()
    try:
        with open(_SCAN_CACHE_FILE, "r") as f:
            c = json.load(f)
        version = c.get("v")
        if version not in (_SCAN_CACHE_VERSION, _SCAN_CACHE_MIGRATABLE_VERSION):
            _remove_codex_event_cache_dir()
            return {"v": _SCAN_CACHE_VERSION, "_dirty": True}
        if version == _SCAN_CACHE_MIGRATABLE_VERSION:
            c["v"] = _SCAN_CACHE_VERSION
            c["_dirty"] = True
        else:
            c["_dirty"] = False
        if c.get("_pricing_fingerprint") != _PRICING_FINGERPRINT:
            # Keep token caches intact. Claude/Codex reprice compact events in place;
            # other estimated-cost tools are recalculated from cached model totals.
            pending = set(c.get("_pricing_changed_models") or [])
            previous = c.get("_pricing_effective")
            multipliers = dict(c.get("_pricing_cost_multipliers") or {})
            if isinstance(previous, dict):
                for model in set(previous) | set(_PRICING_EFFECTIVE):
                    if previous.get(model) != _PRICING_EFFECTIVE.get(model):
                        pending.add(model)
            else:
                pending.update(_BUILTIN_REPRICE_MODELS)
                multipliers.update(_BUILTIN_REPRICE_MULTIPLIERS)
            previous_aliases = c.get("_pricing_aliases")
            if isinstance(previous_aliases, dict):
                for alias in set(previous_aliases) | set(_OV_ALIASES):
                    old_target = previous_aliases.get(alias)
                    new_target = _OV_ALIASES.get(alias)
                    if old_target != new_target:
                        pending.update(value for value in (alias, old_target, new_target) if value)
            c["_pricing_changed"] = True
            c["_pricing_changed_models"] = sorted(str(value) for value in pending)
            c["_pricing_cost_multipliers"] = multipliers
            c["_dirty"] = True
        c["_keys"] = {k for k in c if not k.startswith("_")}
        return c
    except Exception:
        _remove_codex_event_cache_dir()
        return {"v": _SCAN_CACHE_VERSION, "_dirty": True,
                "_pricing_fingerprint": _PRICING_FINGERPRINT,
                "_pricing_effective": _PRICING_EFFECTIVE,
                "_pricing_aliases": _OV_ALIASES}


def _save_scan_cache(cache):
    prev_keys = cache.pop("_keys", set())
    current_keys = {k for k in cache if not k.startswith("_")}
    dirty = cache.pop("_dirty", False) or current_keys != prev_keys
    if not dirty:
        return
    cache["v"] = _SCAN_CACHE_VERSION
    tmp = None
    try:
        directory = os.path.dirname(_SCAN_CACHE_FILE)
        if directory:
            os.makedirs(directory, mode=0o700, exist_ok=True)
            try:
                os.chmod(directory, 0o700)
            except OSError:
                pass
        fd, tmp = _tempfile.mkstemp(prefix="_tokei_scan_cache.", suffix=".json",
                                    dir=directory or None)
        payload = json.dumps(cache, separators=(',', ':')).encode("utf-8")
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        os.chmod(tmp, 0o600)
        os.replace(tmp, _SCAN_CACHE_FILE)
    except Exception:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        pass


# ---------- 持久账本(来源快照 + 旧版每日高水位兼容) ----------
# 目的:CLI(如 Claude Code 默认 30 天清理)删除旧日志后,历史用量不再缩水。
# 已接入来源标识的扫描器保留每个来源的日快照，缺失来源与新增来源可同时累计。
# 仅有日汇总的旧数据保留无法归属的余额，不能反推升级前已丢失的调用明细。
# 独立于 scan cache 的版本机制,永不因解析器/缓存升级而失效。
_LEDGER_FILE = os.path.join(HOME, ".tokei", "ledger.json")
_LEDGER_VERSION = 1
_LEDGER_FIELDS = ("in", "out", "cr", "cw", "reason", "cached", "cost")


_LEDGER_CACHE = {"data": None, "dirty": False}


def _load_ledger():
    if _LEDGER_CACHE["data"] is not None:
        return _LEDGER_CACHE["data"]
    _LEDGER_CACHE["data"] = _load_ledger_from_disk()
    return _LEDGER_CACHE["data"]


def _load_ledger_from_disk():
    try:
        with open(_LEDGER_FILE, "r") as f:
            ledger = json.load(f)
        if isinstance(ledger, dict) and ledger.get("v") == _LEDGER_VERSION:
            return ledger
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    # 自愈:本地账本缺失/损坏时,从同步仓中本机快照的 _ledger 备份恢复
    try:
        cfg = _load_tokei_config() or {}
        device = (cfg.get("device_id") or "").strip()
        sync_dir = (cfg.get("sync_dir") or "").strip()
        if device and sync_dir:
            snap_path = os.path.join(os.path.expanduser(sync_dir), f"{device}.json")
            with open(snap_path, "r") as f:
                backup = json.load(f).get("_ledger")
            if (isinstance(backup, dict) and backup.get("v") == _LEDGER_VERSION
                    and backup.get("tools")):
                _save_ledger(backup)
                return backup
    except Exception:
        pass
    return {"v": _LEDGER_VERSION, "tools": {}}


def ledger_flush():
    """把内存账本变更落盘:短锁内与磁盘最新状态做天级高水位合并后原子写。
    每轮扫描只调一次,替代此前每工具一次的 15 轮锁+读+写(性能回归根因)。"""
    if not _LEDGER_CACHE["dirty"] or _LEDGER_CACHE["data"] is None:
        return
    lock_fd = None
    try:
        import fcntl
        os.makedirs(os.path.dirname(_LEDGER_FILE), mode=0o700, exist_ok=True)
        lock_fd = os.open(f"{_LEDGER_FILE}.lock", os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
    except OSError:
        lock_fd = None
    try:
        fresh = _load_ledger_from_disk()
        memo = _LEDGER_CACHE["data"]
        memo_qodercli_schema = int(memo.get("qodercli_schema", 0) or 0)
        fresh_qodercli_schema = int(fresh.get("qodercli_schema", 0) or 0)
        if memo_qodercli_schema > fresh_qodercli_schema:
            fresh.setdefault("tools", {})["qodercli"] = dict(
                memo.get("tools", {}).get("qodercli", {}))
            fresh["qodercli_schema"] = memo_qodercli_schema
        for tool, days in memo.get("tools", {}).items():
            stored = fresh["tools"].setdefault(tool, {})
            for dk, day in days.items():
                kept = stored.get(dk)
                if (tool == "codex" and kept
                        and _ledger_record_version(day) > _ledger_record_version(kept)):
                    # Reserve attribution upgrades may lower Codex totals. Replace the
                    # old mixed day before source merging can recreate its remainder.
                    stored[dk] = day
                elif day.get("_sources") is not None:
                    stored[dk] = _ledger_merge_sources(kept, day["_sources"], tool)
                    for key in ("projects", "sessions"):
                        if isinstance(day.get(key), list):
                            stored[dk][key] = sorted(set(stored[dk].get(key) or []) | set(day[key]))
                elif (tool == "opencode" and kept
                        and _ledger_token_sum(kept, tool) > _ledger_token_sum(day, tool)):
                    continue  # Preserve concurrent historical snapshots too.
                elif tool == "codex" and kept and "_sources" not in kept:
                    stored[dk] = _codex_legacy_day(day if _ledger_source_preferred(day, kept) else kept)
                elif (kept is None
                        or _ledger_record_version(day) > _ledger_record_version(kept)
                        or (_ledger_record_version(day) == _ledger_record_version(kept)
                            and _ledger_day_total(day) > _ledger_day_total(kept))):
                    stored[dk] = day
        _save_ledger(fresh)
        _LEDGER_CACHE["data"] = fresh
        _LEDGER_CACHE["dirty"] = False
    finally:
        if lock_fd is not None:
            try:
                import fcntl
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(lock_fd)


def _save_ledger(ledger):
    tmp = None
    try:
        directory = os.path.dirname(_LEDGER_FILE)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        fd, tmp = _tempfile.mkstemp(prefix=".ledger-", suffix=".json", dir=directory)
        with os.fdopen(fd, "w") as f:
            json.dump(ledger, f, separators=(',', ':'))
        os.chmod(tmp, 0o600)
        os.replace(tmp, _LEDGER_FILE)
    except Exception:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _ledger_day_total(day):
    """字段无关的当日体量:累加所有数值字段(cost/cost_cny 除外),适配任意工具的 day 结构。"""
    return sum(float(v) for k, v in day.items()
               if isinstance(v, (int, float)) and not isinstance(v, bool)
               and k not in ("cost", "cost_cny") and not k.startswith("_"))


def _ledger_record_version(day):
    """Return the schema version for a persisted daily record.

    ``_cost_version`` is retained for existing collectors.  New parsers can use
    the broader ``_ledger_version`` when a deduplication or token-accounting
    change must replace an older high-water value, even when the new total is
    lower.
    """
    if not isinstance(day, dict):
        return 0
    value = day.get("_ledger_version", day.get("_cost_version", 0))
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


# 账本天的 token 口径:白名单直加字段。cached 不单独相加——所有记录 cached 的工具
# (codex/gemini/qoder_ide)其 cached 均为 in 的子集,计完整 in 即已"含 cached",
# 再加一次会重复计数。est/calls/duration/tools/turns/sessions 等计数字段永远不算 token。
# Codex 的 reason 也是 out 子集，由 _ledger_token_sum 按工具排除。
_LEDGER_TOKEN_FIELDS = ("in", "out", "cr", "cw", "reason", "thoughts")


def _ledger_token_sum(day, tool=None):
    tok = 0
    for field in _LEDGER_TOKEN_FIELDS:
        if tool in ("codex", "codex_reserve", "openclaw", "musecode") and field == "reason":
            continue
        value = day.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            tok += int(value)
    return tok


def _ledger_values(left, right, subtract=False):
    """Combine JSON day counters, including model/hour details; never sum metadata."""
    result = {}
    for key in left.keys() | right.keys():
        if key == "_sources":
            continue
        a, b = left.get(key), right.get(key)
        if isinstance(a, dict) or isinstance(b, dict):
            result[key] = _ledger_values(a if isinstance(a, dict) else {},
                                         b if isinstance(b, dict) else {}, subtract)
        elif key.startswith("_"):
            result[key] = max(a or 0, b or 0)
        elif isinstance(a, (int, float)) or isinstance(b, (int, float)):
            result[key] = max((a or 0) - (b or 0), 0) if subtract else (a or 0) + (b or 0)
        elif key == "hours":
            aa, bb = a or [0] * 24, b or [0] * 24
            result[key] = [max(x-y, 0) if subtract else x+y for x, y in zip(aa, bb)]
        elif isinstance(a, (list, set)) or isinstance(b, (list, set)):
            result[key] = sorted(set(a or []) - set(b or []) if subtract else set(a or []) | set(b or []))
        elif a is not None or b is not None:
            result[key] = a if subtract else b if b is not None else a
    return result


def _ledger_source_preferred(candidate, kept):
    if kept is None:
        return True
    revision = lambda value: (value.get("_accounting_version", 0), _ledger_record_version(value))
    return (revision(candidate) > revision(kept) or
            (revision(candidate) == revision(kept) and
             _ledger_day_total(candidate) >= _ledger_day_total(kept)))


def _codex_legacy_day(day):
    """Keep historical totals, but do not invent attribution for an old remainder."""
    day = dict(day)
    inp, out = day.get("in", 0), day.get("out", 0)
    day["cached"] = min(day.get("cached", 0), inp)
    day["reason"] = min(day.get("reason", 0), out)
    expected = {"in": inp - day["cached"], "out": out, "cr": day["cached"],
                "cw": 0, "reason": day["reason"], "cost": day.get("cost", 0)}
    models = day.get("models") or {}
    if any(sum(v.get(k, 0) for v in models.values()) != expected[k] for k in TOKEN_FIELDS):
        day["models"] = {"unknown": expected} if inp + out or expected["cost"] else {}
    hours = day.get("hours") or []
    if sum(hours) > inp + out:
        day["hours"] = [0] * 24  # Unreliable old hour allocation is explicitly absent.
    return day


def _ledger_merge_sources(kept, current, tool=None):
    """Retain absent sources and replace known sources, never max the whole day."""
    kept = kept or {}
    sources = dict(kept.get("_sources") or {})
    if "_sources" not in kept and kept:
        live = {}
        for snapshot in current.values():
            live = _ledger_values(live, snapshot)
        # v1 had no provenance. Preserve only its unattributed remainder, not
        # the whole old total plus all currently visible sessions.
        sources["legacy"] = _ledger_values(kept, live, subtract=True)
    for source, snapshot in current.items():
        authoritative_codex_source = (
            tool in ("codex", "codex_reserve")
            and snapshot.get("_accounting_version", 0) >= _CODEX_ACCOUNTING_VERSION
        )
        if authoritative_codex_source or _ledger_source_preferred(snapshot, sources.get(source)):
            sources[source] = snapshot
    # A fully reconstructed token remainder has no remaining token-priced cost.
    # This also repairs orphan USD from an earlier aggregate-to-CNY migration.
    if (tool == "deepseek_harness" and "legacy" in sources
            and current and any(day.get("cost_cny", 0) > 0 for day in current.values())
            and _ledger_token_sum(kept, tool) > 0
            and _ledger_token_sum(sources["legacy"], tool) == 0):
        legacy = sources["legacy"] = dict(sources["legacy"])
        legacy["cost"] = 0.0
        legacy["cost_cny"] = 0.0
        legacy["models"] = {}
    if tool == "codex" and "legacy" in sources:
        sources["legacy"] = _codex_legacy_day(sources["legacy"])
    result = {}
    for snapshot in sources.values():
        result = _ledger_values(result, snapshot)
    result["_sources"] = sources
    return result


def _ledger_file_sources(file_cache, identity_field=None, accounting_version=1):
    """Per-file contributions after scanner deduplication; logical IDs survive moves."""
    sources = {}
    for path, entry in file_cache.items():
        if not isinstance(entry, dict) or not entry.get("days"):
            continue
        identity = (identity_field(path, entry) if callable(identity_field) else
                    entry.get(identity_field) if identity_field else None)
        target = sources.setdefault(str(identity or path), {})
        for dk, day in entry["days"].items():
            target[dk] = _ledger_values(target.get(dk, {}), day)
            if dk in (entry.get("day_hours") or {}):
                target[dk]["hours"] = list(entry["day_hours"][dk])
            target[dk]["_accounting_version"] = accounting_version
    return sources


def _ledger_add_record_source(sources, identity, day_key, record, hour=None):
    days = sources.setdefault(str(identity), {})
    contribution = {
        field: record.get(field, 0)
        for field in (*TOKEN_FIELDS, "cost", "cost_cny", "credits")
    }
    if record.get("models"):
        contribution["models"] = record["models"]
    elif record.get("model"):
        contribution["models"] = {record["model"]: dict(contribution)}
    if isinstance(hour, int) and 0 <= hour < 24:
        contribution["hours"] = [0] * 24
        contribution["hours"][hour] = token_total(record)
    days[day_key] = _ledger_values(days.get(day_key, {}), contribution)


def ledger_reconcile(tool, live_days, source_days=None):
    """对账:live_days={day: day_dict}(现存日志实时聚合,任意字段结构)。

    返回 {day: day_data} 的完整视图:
    - 实时值 >= 账本值的天:以实时为准,并把账本刷新到实时(高水位上移)
    - 实时值 < 账本值的天(日志被部分/全部清理):返回账本存档值
    - 账本独有的天(日志已整体消失):账本兜底
    天级整取整用,不做字段级混合,天然避免重复计数。
    纯内存操作;落盘由 compute() 末尾的 ledger_flush() 统一完成(锁内高水位合并)。"""
    ledger = _load_ledger()
    stored = ledger["tools"].setdefault(tool, {})
    dirty = False
    merged = {}
    # 日志中偶发的坏时间戳(如 2024-01-08)不入账本,防止污染永久数据
    max_day = (date.today() + timedelta(days=1)).isoformat()
    if source_days is not None:
        by_day = {}
        for source, days in source_days.items():
            source_id = hashlib.sha256(str(source).encode()).hexdigest()
            for dk, day in days.items():
                by_day.setdefault(dk, {})[source_id] = _ledger_values({}, day)
        for dk in stored.keys() | live_days.keys() | by_day.keys():
            kept = stored.get(dk)
            current = by_day.get(dk, {})
            if not current:
                value = kept if kept is not None else live_days.get(dk, {})
                if tool == "codex" and kept:
                    value = (_ledger_merge_sources(kept, {}, tool) if "_sources" in kept
                             else _codex_legacy_day(kept))
                    if value != kept:
                        stored[dk] = value
                        dirty = True
                merged[dk] = value
                continue
            value = _ledger_merge_sources(kept, current, tool)
            # Preserve non-counter attribution supplied by the scanner.
            for key in ("projects", "sessions"):
                live = live_days.get(dk, {}).get(key)
                if isinstance(live, (list, set)):
                    value[key] = sorted(set(value.get(key) or []) | set(live))
            merged[dk] = value
            if "2025-01-01" <= dk <= max_day and kept != value:
                stored[dk] = value
                dirty = True
        if dirty:
            _LEDGER_CACHE["dirty"] = True
        return merged
    for dk, live in live_days.items():
        kept = stored.get(dk)
        kept_version = _ledger_record_version(kept)
        live_version = _ledger_record_version(live)
        # An aggregate OpenCode day cannot distinguish repricing from deleted
        # logs. Keep its historical snapshot until the full token total returns.
        if (tool == "opencode" and kept
                and _ledger_token_sum(kept, tool) > _ledger_token_sum(live, tool)):
            merged[dk] = kept
            continue
        if (kept and kept_version > live_version
                or (kept and kept_version == live_version
                    and _ledger_day_total(kept) > _ledger_day_total(live))):
            merged[dk] = kept
        else:
            merged[dk] = live
            if not ("2025-01-01" <= dk <= max_day):
                continue
            snapshot = {k: v for k, v in live.items()
                        if not isinstance(v, set)}
            if kept != snapshot:
                stored[dk] = snapshot
                dirty = True
    for dk, kept in stored.items():
        if dk not in merged:
            merged[dk] = kept          # 日志已整体消失的天:账本兜底
    if dirty:
        _LEDGER_CACHE["dirty"] = True
    return merged


def ledger_touch(tool):
    """确保账本 tools 中存在该工具的键(暂无数据时写空占位),标记 scanner 已接入。"""
    try:
        ledger = _load_ledger()
        if tool not in ledger.get("tools", {}):
            ledger.setdefault("tools", {})[tool] = {}
            _LEDGER_CACHE["dirty"] = True
    except Exception:
        pass


def _with_scan_cache_lock(fn):
    def locked(*args, **kwargs):
        try:
            import fcntl
        except ImportError:
            return fn(*args, **kwargs)

        lock_path = f"{_SCAN_CACHE_FILE}.lock"
        lock_dir = os.path.dirname(lock_path)
        if lock_dir:
            os.makedirs(lock_dir, exist_ok=True)
        lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            return fn(*args, **kwargs)
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
    return locked


def _cache_dashboard_days(cache, key, days):
    def serializable(value):
        if isinstance(value, dict):
            return {str(k): serializable(v) for k, v in value.items()}
        if isinstance(value, set):
            return sorted(serializable(v) for v in value)
        if isinstance(value, (list, tuple)):
            return [serializable(v) for v in value]
        return value

    payload = serializable(days if isinstance(days, dict) else {})
    if cache.get(key) != payload:
        cache[key] = payload
        cache["_dirty"] = True


def _merge_dashboard_days(cache, key, days):
    if not isinstance(days, dict) or not days:
        return
    existing = cache.get(key)
    merged = dict(existing) if isinstance(existing, dict) else {}
    merged.update(days)
    _cache_dashboard_days(cache, key, merged)


def _empty_claude():
    ranges = {k: {"in": 0, "out": 0, "cr": 0, "cw": 0, "cost": 0.0,
                  "models": {}, "sessions": set()} for k in RANGE_KEYS}
    return {"ranges": ranges, "cur": {"in": 0, "out": 0, "cr": 0, "cw": 0, "name": "-"}}


def _empty_codex():
    def _blank():
        return {k: {"in": 0, "cached": 0, "out": 0, "reason": 0,
                    "cost": 0.0, "sessions": set(), "models": {}} for k in RANGE_KEYS}
    return {"ranges": _blank(), "reserve_ranges": _blank(),
            "reserve_quota": None, "limits": None, "plan": None,
            "limits_updated": None, "limits_consumed": None}


def _empty_gemini():
    ranges = {k: {"in": 0, "out": 0, "cached": 0, "thoughts": 0,
                  "cost": 0.0, "models": {}, "sessions": set()} for k in RANGE_KEYS}
    return {"ranges": ranges, "days": {}}


def _empty_grok():
    ranges = {k: {"tokens": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0,
                  "cost": 0.0, "models": {}, "usage_sessions": set(), "usage_calls": 0,
                  "sessions": set(), "turns": 0, "tools": 0,
                  "duration": 0, "ctx_used": 0, "ctx_window": 0, "errors": 0,
                  "cancellations": 0, "ttft_sum": 0, "response_sum": 0, "latency_count": 0}
              for k in RANGE_KEYS}
    return {"ranges": ranges, "model": None, "days": {}}


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
                  "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0,
                  "cost": 0.0, "sessions": set(), "models": {}} for k in RANGE_KEYS}
    return {"ranges": ranges}


def _empty_token_bucket():
    return {"in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0,
            "cost": 0.0, "credits": 0.0, "sessions": set(), "models": {}}


def _empty_token_day():
    return {"in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0,
            "cost": 0.0, "credits": 0.0, "models": {}, "hours": [0] * 24}


def _empty_token_ranges():
    return {k: _empty_token_bucket() for k in RANGE_KEYS}


def _empty_opencode():
    return {"ranges": _empty_token_ranges()}


def _empty_pi():
    return _empty_opencode()


def _empty_prime_agent():
    return _empty_opencode()


def _empty_workbuddy():
    return _empty_opencode()


def _empty_grok_bot():
    ranges = {key: {"sessions": set(), "calls": 0, "turns": 0,
                    "tools": 0, "duration": 0}
              for key in RANGE_KEYS}
    return {"ranges": ranges}


def _empty_deepseek_harness():
    return _empty_opencode()


def _empty_qwencode():
    return _empty_opencode()


def _empty_kimicode():
    return _empty_opencode()


def _empty_musecode():
    return _empty_opencode()


def _empty_cmdcode():
    return _empty_opencode()


def _empty_zcode():
    return _empty_opencode()


def _empty_devin():
    return _empty_opencode()


def _empty_mimocode():
    return _empty_opencode()


def token_total(day):
    return sum(day.get(k, 0) for k in TOKEN_FIELDS)


def _sqlite_ro_uri(path):
    return Path(path).resolve().as_uri() + "?mode=ro"


def _sqlite_signature(path):
    parts = []
    # SHM 的 mtime 会被只读 SQLite 连接更新，不能作为数据变化信号。
    for candidate in (path, path + "-wal"):
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


def _add_model_usage(models, model, inp=0, out=0, cr=0, cw=0, reason=0,
                     cost=0.0, credits=0.0, cost_cny=0.0):
    if not model:
        return
    mm = models.setdefault(model, {"in": 0, "out": 0, "cr": 0, "cw": 0,
                                    "reason": 0, "cost": 0.0, "credits": 0.0,
                                    "cost_cny": 0.0})
    mm["in"] += int(inp or 0); mm["out"] += int(out or 0)
    mm["cr"] += int(cr or 0); mm["cw"] += int(cw or 0); mm["reason"] += int(reason or 0)
    mm["cost"] += float(cost or 0)
    mm["credits"] = float(mm.get("credits", 0) or 0) + float(credits or 0)
    mm["cost_cny"] = mm.get("cost_cny", 0.0) + float(cost_cny or 0)


def _add_token_usage(target, inp=0, out=0, cr=0, cw=0, reason=0, cost=0.0,
                     model=None, credits=0.0, cost_cny=0.0):
    target["in"] += int(inp or 0); target["out"] += int(out or 0)
    target["cr"] += int(cr or 0); target["cw"] += int(cw or 0); target["reason"] += int(reason or 0)
    target["cost"] += float(cost or 0)
    target["credits"] = float(target.get("credits", 0.0) or 0.0) + float(credits or 0)
    target["cost_cny"] = target.get("cost_cny", 0.0) + float(cost_cny or 0)
    _add_model_usage(target.get("models", {}), model, inp, out, cr, cw, reason, cost,
                     credits=credits, cost_cny=cost_cny)


def _merge_token_day(bucket, day, session=None):
    if session is not None:
        bucket["sessions"].add(session)
    _add_token_usage(bucket, day.get("in", 0), day.get("out", 0), day.get("cr", 0),
                     day.get("cw", 0), day.get("reason", 0), day.get("cost", 0),
                     credits=day.get("credits", 0), cost_cny=day.get("cost_cny", 0))
    for model, mv in day.get("models", {}).items():
        _add_model_usage(bucket["models"], model, mv.get("in", 0), mv.get("out", 0),
                         mv.get("cr", 0), mv.get("cw", 0), mv.get("reason", 0),
                         mv.get("cost", 0), credits=mv.get("credits", 0),
                         cost_cny=mv.get("cost_cny", 0))


def _merge_live_token_day(agg, day):
    """跨文件合并同日数据(token 字段/models/hours,均 JSON 兼容),用作 ledger 的 live_days。"""
    _add_token_usage(agg, day.get("in", 0), day.get("out", 0), day.get("cr", 0),
                     day.get("cw", 0), day.get("reason", 0), day.get("cost", 0),
                     credits=day.get("credits", 0), cost_cny=day.get("cost_cny", 0))
    for model, mv in (day.get("models") or {}).items():
        _add_model_usage(agg["models"], model, mv.get("in", 0), mv.get("out", 0),
                         mv.get("cr", 0), mv.get("cw", 0), mv.get("reason", 0),
                         mv.get("cost", 0), credits=mv.get("credits", 0),
                         cost_cny=mv.get("cost_cny", 0))
    hours = day.get("hours")
    if isinstance(hours, list):
        agg_hours = agg.setdefault("hours", [0] * 24)
        for hour, amount in enumerate(hours[:24]):
            agg_hours[hour] += amount


def _format_token_models(models, include_prices=True):
    # Raw log aliases can resolve to the same SwiftUI row ID. Merge before
    # sorting, preserving accumulated costs rather than repricing usage.
    canonical_models = {}
    for model, usage in models.items():
        model_id = _model_identity_id(model)
        merged = canonical_models.setdefault(model_id, {})
        for field in ("in", "out", "cr", "cw", "reason", "cost", "cost_cny", "credits"):
            merged[field] = merged.get(field, 0) + usage.get(field, 0)
    result = []
    sort_key = (lambda kv: -kv[1].get("cost", 0)) if include_prices else (
        lambda kv: -token_total(kv[1]))
    for model_id, v in sorted(canonical_models.items(), key=sort_key):
        price_id = _exact_pricing_id(model_id) if include_prices else None
        p = _raw_price(price_id) if price_id else {
            "in": 0.0, "out": 0.0, "cache_read": 0.0, "cache_write": 0.0}
        result.append({"model_id": model_id, "name": nice_model(model_id),
                       "in": v.get("in", 0), "out": v.get("out", 0),
                        "cr": v.get("cr", 0), "cw": v.get("cw", 0), "reason": v.get("reason", 0),
                        "cost": v.get("cost", 0), "cost_cny": v.get("cost_cny", 0),
                        "credits": v.get("credits", 0),
                        "pin": 0 if v.get("cost_cny") else p["in"],
                        "pout": 0 if v.get("cost_cny") else p["out"]})
    return result


def _safe_scan(name, fn, fallback, errors):
    try:
        return fn()
    except Exception as e:
        errors[name] = f"{type(e).__name__}: {e}"
        return fallback()


# ---------- Claude Code ----------
def _claude_event_cost(event):
    p = price_for(event.get("model"))
    inp = int(event.get("in", 0) or 0)
    out = int(event.get("out", 0) or 0)
    cr = int(event.get("cr", 0) or 0)
    cw = int(event.get("cw", 0) or 0)
    w5 = event.get("cw5")
    w1 = event.get("cw1")
    if w5 is None and w1 is None:
        write_cost = cw / 1e6 * p["write5m"]
    else:
        write_cost = (int(w5 or 0) / 1e6 * p["write5m"]
                      + int(w1 or 0) / 1e6 * p["write1h"])
    return (inp / 1e6 * p["in"] + out / 1e6 * p["out"]
            + cr / 1e6 * p["cache_read"] + write_cost)


def _reprice_claude_events(file_cache, changed_models):
    changed = False
    for entry in file_cache.values():
        if not _cached_entry_has_pricing_change(entry, changed_models):
            continue
        for event in entry.get("events", []):
            if not isinstance(event, dict):
                continue
            cost = _claude_event_cost(event)
            if not math.isclose(float(event.get("cost", 0) or 0), cost,
                                rel_tol=0.0, abs_tol=1e-12):
                event["cost"] = cost
                changed = True
    return changed


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
    if (cache.get("_pricing_changed")
            and _reprice_claude_events(fc, cache.get("_pricing_changed_models") or [])):
        changed = True
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
                            "cw5": u.get("cw5"), "cw1": u.get("cw1"),
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
    def classify(d):
        ks = ["all"]
        if d == today_d: ks.append("today")
        if d == yest_d: ks.append("yesterday")
        if d >= week_d: ks.append("week")
        if lw_start_d <= d < lw_end_d: ks.append("last_week")
        if d >= month_d: ks.append("month")
        if d >= year_d: ks.append("year")
        return ks

    live_days = {}
    day_projects = {}
    for f, entry in fc.items():
        proj_name = os.path.basename((entry.get("proj") or "").rstrip("/"))
        for dk, day in entry.get("days", {}).items():
            agg = live_days.setdefault(
                dk, {"in": 0, "out": 0, "cr": 0, "cw": 0, "cost": 0.0, "models": {}})
            agg["in"] += day["in"]; agg["out"] += day["out"]
            agg["cr"] += day["cr"]; agg["cw"] += day["cw"]; agg["cost"] += day["cost"]
            if proj_name:
                day_projects.setdefault(dk, set()).add(proj_name)
            for mn, mv in day["models"].items():
                mm = agg["models"].setdefault(mn, {"in": 0, "out": 0, "cr": 0, "cw": 0, "cost": 0.0})
                mm["in"] += mv["in"]; mm["out"] += mv["out"]
                mm["cr"] += mv["cr"]; mm["cw"] += mv["cw"]; mm["cost"] += mv["cost"]
            # 会话数只能来自现存日志(被清日志无从归属)
            try:
                d = date.fromisoformat(dk)
            except ValueError:
                continue
            for k in classify(d):
                B[k]["sessions"].add(f)
    # 项目名随天入账本(list 会被 snapshot 原样存档;_ledger_day_total 只加数值,不受影响),
    # 日志被清理后回顾页仍能回答"那天在干什么"。
    for dk, names in day_projects.items():
        live_days[dk]["projects"] = sorted(names)[:3]

    for dk, day in ledger_reconcile("claude", live_days, _ledger_file_sources(
            fc, lambda path, _: os.path.basename(path))).items():
        try:
            d = date.fromisoformat(dk)
        except ValueError:
            continue
        for k in classify(d):
            b = B[k]
            b["in"] += day.get("in", 0); b["out"] += day.get("out", 0)
            b["cr"] += day.get("cr", 0); b["cw"] += day.get("cw", 0)
            b["cost"] += day.get("cost", 0.0)
            for mn, mv in (day.get("models") or {}).items():
                mm = b["models"].setdefault(mn, {"in": 0, "out": 0, "cr": 0, "cw": 0, "cost": 0.0})
                mm["in"] += mv.get("in", 0); mm["out"] += mv.get("out", 0)
                mm["cr"] += mv.get("cr", 0); mm["cw"] += mv.get("cw", 0)
                mm["cost"] += mv.get("cost", 0.0)

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
    cc = u.get("cache_creation") or {}
    w5 = cc.get("ephemeral_5m_input_tokens")
    w1 = cc.get("ephemeral_1h_input_tokens")
    res = {"in": inp, "out": out, "cr": cr, "cw": cw, "cw5": w5, "cw1": w1,
           "model": msg.get("model"), "cwd": o.get("cwd"), "mid": msg.get("id"),
           "request_id": o.get("requestId") or o.get("request_id"),
           "event_id": o.get("uuid"), "sidechain": o.get("isSidechain") is True}
    res["cost"] = _claude_event_cost(res)
    if want_dt:
        res["dt"] = dt
    return res


# ---------- Codex ----------
# TTL 曾等于 App 的 30s 刷新间隔,缓存每轮刚好过期 —— 等于每次刷新都真打一次官方
# 接口(约 2880 次/天)。额度对应的是周窗口,变化很慢,拉长到 5 分钟没有感知差别。
_CODEX_QUOTA_TTL = 300
_CODEX_QUOTA_FALLBACK_TTL = 300
_CODEX_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
_CODEX_USAGE_MAX_RESPONSE_BYTES = 256 * 1024
_CODEX_RESET_CARDS_URL = "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits"
_CODEX_RESET_CARDS_REFRESH_INTERVAL = 6 * 3600
_CODEX_RESET_CARDS_RETRY_INTERVAL = 6 * 3600
_CODEX_RESET_CARDS_MAX_RESPONSE_BYTES = 256 * 1024


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


def _codex_limits_have_active_window(limits, now_epoch=None):
    now = float(now_epoch if now_epoch is not None else datetime.now().timestamp())
    for slot_name in ("primary", "secondary"):
        slot = (limits or {}).get(slot_name) or {}
        reset = slot.get("resets_at")
        try:
            if reset is not None and float(reset) > now:
                return True
        except (TypeError, ValueError, OverflowError):
            continue
    return False


def _cached_codex_live_limits(max_age, allow_active_window=False, account_key=None):
    cached = _load_json(CODEX_QUOTA_CACHE, {})
    fetched_at = cached.get("fetched_at")
    limits = cached.get("limits")
    if not fetched_at or not limits:
        return None
    cached_account_key = cached.get("account_key")
    if account_key and cached_account_key and cached_account_key != account_key:
        return None
    try:
        fetched_at = float(fetched_at)
    except (TypeError, ValueError, OverflowError):
        return None
    age = datetime.now().timestamp() - fetched_at
    if age > max_age and not (
            allow_active_window and _codex_limits_have_active_window(limits)):
        return None
    return limits, cached.get("plan"), fetched_at


def _codex_live_snapshot_is_current(live_updated, local_updated):
    if live_updated is None or not local_updated:
        return True
    local_epoch = _iso_to_epoch(local_updated)
    if local_epoch is None:
        return True
    try:
        return float(live_updated) >= local_epoch
    except (TypeError, ValueError, OverflowError):
        return False


def _decode_jwt_claims(token):
    if not isinstance(token, str) or token.count(".") < 2:
        return {}
    try:
        import base64
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        return decoded if isinstance(decoded, dict) else {}
    except Exception:
        return {}


def _codex_config():
    """→ {"model_provider": str|None, "model_providers": [名字]};读不到返回空。

    tomllib 是 3.11+ 才有的,而没装 Homebrew Python 的机器会落到 /usr/bin/python3
    (macOS 自带 3.9),模块级 import 会让整个脚本崩掉 —— 所以惰性导入 + 最小回退。
    """
    try:
        with open(CODEX_CONFIG, "rb") as f:
            raw = f.read(64 * 1024)
    except OSError:
        return {}
    try:
        import tomllib
    except ImportError:
        # 3.9 回退:只认顶层 model_provider = "x" 和 [model_providers.x] 段名。
        text = raw.decode("utf-8", errors="ignore")
        hit = re.search(r'^\s*model_provider\s*=\s*["\']([^"\']+)["\']', text, re.M)
        return {
            "model_provider": hit.group(1) if hit else None,
            "model_providers": re.findall(
                r'^\s*\[\s*model_providers\.([^\]\s.]+)', text, re.M),
        }
    try:
        data = tomllib.loads(raw.decode("utf-8", errors="ignore")) or {}
    except Exception:
        return {}
    provider = data.get("model_provider")
    return {
        "model_provider": provider if isinstance(provider, str) else None,
        "model_providers": list((data.get("model_providers") or {}).keys()),
    }


def _codex_is_custom_provider():
    """True 表示 Codex 已切到非 OpenAI 的 provider(cc Switch 之类)。

    只认显式声明:光有 [model_providers.x] 段、但没把 model_provider 指过去的用户
    仍在用官方额度,误判会把他们的额度卡整块藏掉。
    """
    provider = _codex_config().get("model_provider")
    return bool(provider) and provider != "openai"


def _codex_auth_context(auth):
    if not isinstance(auth, dict):
        return {}
    nested = auth.get("tokens")
    tokens = nested if isinstance(nested, dict) else {}

    def value(*names):
        for source in (tokens, auth):
            for name in names:
                item = source.get(name)
                if isinstance(item, str) and item:
                    return item
        return None

    access_token = value("access_token", "accessToken")
    if not access_token:
        return {}
    id_token = value("id_token", "idToken")
    claims = _decode_jwt_claims(access_token)
    id_claims = _decode_jwt_claims(id_token)
    auth_claim = claims.get("https://api.openai.com/auth")
    id_auth_claim = id_claims.get("https://api.openai.com/auth")
    auth_claim = auth_claim if isinstance(auth_claim, dict) else {}
    id_auth_claim = id_auth_claim if isinstance(id_auth_claim, dict) else {}
    account_id = value("account_id", "accountId")
    account_id = account_id or auth_claim.get("chatgpt_account_id")
    account_id = account_id or id_auth_claim.get("chatgpt_account_id")
    identity = account_id or claims.get("sub") or id_claims.get("sub") or access_token
    return {
        "access_token": access_token,
        "account_id": str(account_id) if account_id else None,
        "account_key": hashlib.sha256(str(identity).encode("utf-8")).hexdigest(),
        "auth_key": hashlib.sha256(access_token.encode("utf-8")).hexdigest(),
    }


def fetch_codex_live_limits():
    if os.environ.get("TOKEI_CODEX_LIVE_QUOTA") == "0":
        return None
    # When the user has switched to a third-party provider (cc Switch, etc.),
    # the official OpenAI quota endpoint is no longer relevant. Skip it and
    # clear any stale cached official quota so the dashboard falls back to
    # showing only token usage/cost.
    if _codex_is_custom_provider():
        try:
            if os.path.exists(CODEX_QUOTA_CACHE):
                os.remove(CODEX_QUOTA_CACHE)
        except Exception:
            pass
        return None
    cached = _cached_codex_live_limits(_CODEX_QUOTA_TTL)
    if cached:
        return cached
    auth = _load_json(CODEX_AUTH, {})
    auth_context = _codex_auth_context(auth)
    access_token = auth_context.get("access_token")
    account_key = auth_context.get("account_key")
    auth_key = auth_context.get("auth_key")
    if not access_token or not account_key:
        return None
    cache_state = _load_json(CODEX_QUOTA_CACHE, {})
    cached = _cached_codex_live_limits(_CODEX_QUOTA_TTL, account_key=account_key)
    if cached:
        return cached
    # 失败退避:网络不可达(如公司代理拦截)时 5 分钟内不再联网重试,
    # 否则每轮 30s 刷新都会白等约 6s 超时
    last_failure = cache_state.get("last_failure_at", 0)
    if cache_state.get("account_key") not in (None, account_key):
        last_failure = 0
    if cache_state.get("account_key") == account_key \
            and cache_state.get("auth_key") not in (None, auth_key):
        last_failure = 0
    try:
        failure_is_recent = (
            bool(last_failure)
            and datetime.now().timestamp() - float(last_failure) < 300)
    except (TypeError, ValueError, OverflowError):
        failure_is_recent = False
    if failure_is_recent:
        return _cached_codex_live_limits(
            _CODEX_QUOTA_FALLBACK_TTL, allow_active_window=True,
            account_key=account_key)
    try:
        import urllib.request
        from urllib.parse import urlparse
        req = urllib.request.Request(_CODEX_USAGE_URL)
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "Tokei")
        req.add_unredirected_header("Authorization", f"Bearer {access_token}")
        account_id = auth_context.get("account_id")
        if account_id:
            req.add_unredirected_header("ChatGPT-Account-Id", account_id)
        with urllib.request.urlopen(req, timeout=3) as res:
            final_url = urlparse(res.geturl())
            if final_url.scheme != "https" or final_url.hostname != "chatgpt.com":
                raise ValueError("unexpected Codex usage redirect")
            raw = res.read(_CODEX_USAGE_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _CODEX_USAGE_MAX_RESPONSE_BYTES:
            raise ValueError("Codex usage response is too large")
        data = json.loads(raw)
        limits = _codex_live_to_limits(data)
        if not limits:
            raise ValueError("invalid Codex usage response")
        plan = data.get("plan_type")
        fetched_at = datetime.now().timestamp()
        _atomic_write_json(CODEX_QUOTA_CACHE, {
            "fetched_at": fetched_at,
            "limits": limits,
            "plan": plan,
            "account_key": account_key,
            "auth_key": auth_key,
            "source": "live",
        })
        return limits, plan, fetched_at
    except Exception:
        try:
            state = _load_json(CODEX_QUOTA_CACHE, {})
            if state.get("account_key") not in (None, account_key):
                state = {}
            state["last_failure_at"] = datetime.now().timestamp()
            state["account_key"] = account_key
            state["auth_key"] = auth_key
            _atomic_write_json(CODEX_QUOTA_CACHE, state)
        except Exception:
            pass
        return _cached_codex_live_limits(
            _CODEX_QUOTA_FALLBACK_TTL, allow_active_window=True,
            account_key=account_key)


def _normalize_codex_reset_cards(data, now_epoch):
    if not isinstance(data, dict) or not isinstance(data.get("credits"), list):
        return None
    expires = []
    for credit in data["credits"]:
        if not isinstance(credit, dict) or credit.get("status") != "available":
            continue
        if credit.get("is_supported_by_plan") is False:
            continue
        expires_at = parse_ts(credit.get("expires_at") or "")
        if expires_at is None:
            continue
        epoch = int(expires_at.timestamp())
        if epoch > now_epoch:
            expires.append(epoch)
    ordered = sorted(expires)
    return {
        "count": len(ordered),
        "expires": ordered,
        "updated": int(now_epoch),
    }


def _cached_codex_reset_cards(state, now_epoch):
    cards = state.get("cards") if isinstance(state, dict) else None
    if not isinstance(cards, dict):
        return {}
    expires = []
    for value in cards.get("expires") or []:
        try:
            epoch = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if epoch > now_epoch:
            expires.append(epoch)
    expires.sort()
    return {
        "count": len(expires),
        "expires": expires,
        "updated": cards.get("updated"),
    }


def _codex_reset_cards_next_attempt(cards, now_epoch):
    next_daily = int(now_epoch + _CODEX_RESET_CARDS_REFRESH_INTERVAL)
    expires = []
    for value in cards.get("expires") or []:
        try:
            epoch = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if epoch > now_epoch:
            expires.append(epoch)
    return min(next_daily, min(expires) + 60) if expires else next_daily


def _save_codex_reset_cards_state(state):
    try:
        _atomic_write_json(CODEX_RESET_CARDS_CACHE, state)
        os.chmod(CODEX_RESET_CARDS_CACHE, 0o600)
    except Exception:
        pass


def fetch_codex_reset_cards(now_epoch=None):
    """Return available reset-card expirations with a persistent low-frequency cache."""
    if os.environ.get("TOKEI_CODEX_LIVE_QUOTA") == "0":
        return {}
    # 重置卡是 OpenAI 账号级资产,不随 CLI 当前指向的 provider 变化 —— 临时切到
    # 第三方中转的人手上那几张卡还在,切回来就要用,所以这里不按 provider 屏蔽。
    now_epoch = int(datetime.now().timestamp()) if now_epoch is None else int(now_epoch)
    auth = _load_json(CODEX_AUTH, {})
    auth_context = _codex_auth_context(auth)
    access_token = auth_context.get("access_token")
    account_key = auth_context.get("account_key")
    auth_key = auth_context.get("auth_key")
    if not access_token or not account_key or not auth_key:
        return {}

    state = _load_json(CODEX_RESET_CARDS_CACHE, {})
    if not isinstance(state, dict) or state.get("account_key") != account_key:
        state = {"account_key": account_key, "auth_key": auth_key}
    elif state.get("auth_key") and state.get("auth_key") != auth_key:
        # Codex refreshed or replaced the token after an auth failure. Retry once now.
        state["next_attempt_at"] = 0
        state.pop("last_error", None)
    state["auth_key"] = auth_key
    cached = _cached_codex_reset_cards(state, now_epoch)
    try:
        next_attempt_at = int(state.get("next_attempt_at") or 0)
    except (TypeError, ValueError, OverflowError):
        next_attempt_at = 0
    # Older versions cached successful responses for 24 hours. Clamp that saved
    # deadline so newly granted cards become visible after upgrading.
    try:
        last_success_at = int(state.get("fetched_at") or cached.get("updated") or 0)
    except (TypeError, ValueError, OverflowError):
        last_success_at = 0
    if next_attempt_at and last_success_at:
        next_attempt_at = min(
            next_attempt_at,
            last_success_at + _CODEX_RESET_CARDS_REFRESH_INTERVAL,
        )
    if now_epoch < next_attempt_at:
        return cached

    try:
        import urllib.request
        from urllib.parse import urlparse
        request = urllib.request.Request(_CODEX_RESET_CARDS_URL)
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", "Tokei")
        request.add_unredirected_header("Authorization", f"Bearer {access_token}")
        account_id = auth_context.get("account_id")
        if account_id:
            request.add_unredirected_header("ChatGPT-Account-Id", str(account_id))
        with urllib.request.urlopen(request, timeout=3) as response:
            final_url = urlparse(response.geturl())
            if final_url.scheme != "https" or final_url.hostname != "chatgpt.com":
                raise ValueError("unexpected Codex reset-card redirect")
            raw = response.read(_CODEX_RESET_CARDS_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _CODEX_RESET_CARDS_MAX_RESPONSE_BYTES:
            raise ValueError("Codex reset-card response is too large")
        cards = _normalize_codex_reset_cards(json.loads(raw), now_epoch)
        if cards is None:
            raise ValueError("invalid Codex reset-card response")
        state = {
            "account_key": account_key,
            "auth_key": auth_key,
            "fetched_at": now_epoch,
            "last_attempt_at": now_epoch,
            "next_attempt_at": _codex_reset_cards_next_attempt(cards, now_epoch),
            "cards": cards,
        }
        _save_codex_reset_cards_state(state)
        return cards
    except Exception as exc:
        status = getattr(exc, "code", None)
        if status in (401, 403):
            state["last_error"] = "auth"
        elif status in (404, 410):
            state["last_error"] = "unsupported"
        else:
            state["last_error"] = "request"
        state["last_attempt_at"] = now_epoch
        retry_interval = (
            _CODEX_RESET_CARDS_REFRESH_INTERVAL
            if status in (404, 410)
            else _CODEX_RESET_CARDS_RETRY_INTERVAL
        )
        state["next_attempt_at"] = now_epoch + retry_interval
        _save_codex_reset_cards_state(state)
        return cached


def _codex_event_key(event):
    if not isinstance(event, list) or len(event) < 11:
        return None
    total_values = event[2:6]
    if not all(value is not None for value in total_values):
        return None
    return tuple(event[2:10])


def _codex_events_match(left, right):
    if len(left) > 12 and left[12] and len(right) > 12 and right[12]:
        return left[12] == right[12]
    key = _codex_event_key(left)
    return key is not None and key == _codex_event_key(right)


def _codex_event_cache_dir():
    return f"{_SCAN_CACHE_FILE}{_CODEX_EVENT_CACHE_SUFFIX}"


def _codex_event_cache_path(file_path):
    normalized = os.path.normcase(os.path.realpath(file_path))
    digest = hashlib.sha256(normalized.encode("utf-8", errors="surrogatepass")).hexdigest()
    return os.path.join(_codex_event_cache_dir(), f"{digest}.jsonl")


def _codex_event_cache_has_expected_events(file_path, expected_count):
    """Validate a shortened sidecar without loading its events into memory."""
    if expected_count < 0:
        return False
    count = 0
    last_byte = b""
    try:
        with open(_codex_event_cache_path(file_path), "rb", buffering=0) as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                count += chunk.count(b"\n")
                if count > expected_count:
                    return False
                last_byte = chunk[-1:]
    except OSError:
        return False
    return count == expected_count and (expected_count == 0 or last_byte == b"\n")


def _codex_event_cache_ready(file_path, entry, repair_short=False):
    if not isinstance(entry, dict) or entry.get("event_count") is None:
        return False
    try:
        expected_size = int(entry.get("event_cache_size", -1))
        actual_size = os.path.getsize(_codex_event_cache_path(file_path))
    except (OSError, TypeError, ValueError):
        return False
    if expected_size < 0:
        return False
    if actual_size >= expected_size:
        return True
    if not repair_short:
        return False
    try:
        expected_count = int(entry.get("event_count", -1))
    except (TypeError, ValueError):
        return False
    if not _codex_event_cache_has_expected_events(file_path, expected_count):
        return False
    # Repricing can make serialized floating-point costs a few bytes shorter.
    # The event count proves the atomic sidecar is complete, so retain it and
    # repair the append boundary instead of reparsing the source rollout.
    entry["event_cache_size"] = actual_size
    return True


def _codex_write_event_cache(file_path, events):
    directory = _codex_event_cache_dir()
    os.makedirs(directory, mode=0o700, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    destination = _codex_event_cache_path(file_path)
    fd, tmp = _tempfile.mkstemp(prefix=".codex-events-", suffix=".jsonl", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, destination)
        return os.path.getsize(destination)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _codex_append_event_cache(file_path, events, expected_size):
    destination = _codex_event_cache_path(file_path)
    with open(destination, "r+b") as handle:
        current_size = os.fstat(handle.fileno()).st_size
        if current_size < expected_size:
            raise OSError("Codex event cache is shorter than its committed size")
        handle.truncate(expected_size)
        handle.seek(expected_size)
        for event in events:
            payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            handle.write(payload.encode("utf-8"))
            handle.write(b"\n")
        return handle.tell()


def _codex_remove_event_cache(file_path):
    try:
        os.remove(_codex_event_cache_path(file_path))
    except OSError:
        pass


def _codex_clear_event_cache(file_cache):
    for file_path in list(file_cache):
        _codex_remove_event_cache(file_path)
    file_cache.clear()


def _iter_codex_cached_events(file_path, start_index=0, limit=None):
    emitted = 0
    with open(_codex_event_cache_path(file_path), "r", encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if index < start_index:
                continue
            if limit is not None and emitted >= limit:
                break
            try:
                event = json.loads(line)
            except (TypeError, ValueError):
                raise OSError("Codex event cache contains invalid JSON")
            if not isinstance(event, list):
                raise OSError("Codex event cache contains an invalid event")
            emitted += 1
            yield event


def _codex_event_metadata(events):
    keys = []
    first_ts = None
    last_ts = None
    for event in events:
        if first_ts is None and event:
            first_ts = str(event[0])
        if event:
            last_ts = str(event[0])
        if len(keys) < 2:
            key = _codex_event_key(event)
            if key is not None:
                keys.append(list(key))
    return {
        "event_count": len(events),
        "first_keys": keys,
        "first_event_ts": first_ts,
        "last_event_ts": last_ts,
    }


def _codex_days_from_cached_events(file_path, start_index=0, event_count=None, seen_responses=None):
    days = {}
    limit = None if event_count is None else max(int(event_count) - start_index, 0)
    for event in _iter_codex_cached_events(
            file_path, start_index=start_index, limit=limit):
        response_id = event[12] if len(event) > 12 else None
        if seen_responses is not None and response_id:
            if response_id in seen_responses:
                continue
            seen_responses.add(response_id)
        _codex_add_event(days, event)
    return days


def _codex_entry_prefix_key(entry):
    values = entry.get("first_keys") or []
    if len(values) < 2:
        return None
    try:
        return tuple(values[0]), tuple(values[1])
    except TypeError:
        return None


def _codex_cached_prefix_match_count(
        child_path, parent_path, child_count=None, parent_count=None):
    count = 0
    child_events = _iter_codex_cached_events(child_path, limit=child_count)
    parent_events = _iter_codex_cached_events(parent_path, limit=parent_count)
    for child, parent in zip(child_events, parent_events):
        if not _codex_events_match(child, parent):
            break
        count += 1
    return count


def _codex_cached_burst_count(file_path, start_index, event_count):
    burst_second = None
    count = 0
    for event in _iter_codex_cached_events(
            file_path, start_index=start_index,
            limit=max(int(event_count) - start_index, 0)):
        if not event:
            break
        if len(event) > 12 and event[12]:
            break  # Identified responses are real calls, even in the same second.
        event_second = str(event[0])[:19]
        if burst_second is None:
            burst_second = event_second
        elif event_second != burst_second:
            break
        count += 1
    return count if count >= 5 else 0


def _codex_cached_drop_count(file_path, entry, file_cache):
    by_sid = {
        candidate.get("session_id"): (path, candidate)
        for path, candidate in file_cache.items()
        if candidate.get("session_id")
    }
    event_count = int(entry.get("event_count", 0) or 0)
    drop_count = 0
    prefix_open = False

    parent = by_sid.get(entry.get("forked_from_id"))
    if parent and parent[0] != file_path:
        drop_count = _codex_cached_prefix_match_count(
            file_path, parent[0], event_count, parent[1].get("event_count"))
        prefix_open = drop_count > 0 and drop_count == event_count

    prefix_key = _codex_entry_prefix_key(entry)
    if drop_count == 0 and prefix_key is not None and event_count >= 2:
        child_first_ts = str(entry.get("first_event_ts") or "")
        best = 0
        for parent_path, parent_entry in file_cache.items():
            if parent_path == file_path or _codex_entry_prefix_key(parent_entry) != prefix_key:
                continue
            parent_first_ts = str(parent_entry.get("first_event_ts") or "")
            if not parent_first_ts or parent_first_ts >= child_first_ts:
                continue
            best = max(best, _codex_cached_prefix_match_count(
                file_path, parent_path, event_count, parent_entry.get("event_count")))
        if best >= 2:
            drop_count = best
            prefix_open = drop_count == event_count

    burst_count = _codex_cached_burst_count(file_path, drop_count, event_count)
    if burst_count:
        drop_count += burst_count

    if event_count < 2 and not entry.get("forked_from_id"):
        prefix_open = True
    elif entry.get("forked_from_id") and parent is None:
        prefix_open = True
    return min(drop_count, event_count), prefix_open


def _codex_migrate_event_cache(file_cache):
    if not any(isinstance(entry, dict) and "events" in entry for entry in file_cache.values()):
        return False

    canonical = _codex_canonical_file_cache(file_cache)
    drops = _codex_replayed_event_indexes(canonical)
    days_by_file = _codex_deduped_days(canonical)
    prepared = {}
    for file_path, entry in file_cache.items():
        events = entry.get("events") or []
        cache_size = _codex_write_event_cache(file_path, events)
        metadata = _codex_event_metadata(events)
        skipped = drops.get(file_path, set())
        drop_count = 0
        while drop_count in skipped:
            drop_count += 1
        prepared[file_path] = {
            **metadata,
            "event_cache_size": cache_size,
            "drop_count": drop_count,
            "dedupe_open": bool(drop_count and drop_count == len(events)),
            "deduped_days": days_by_file.get(file_path, {}),
            "canonical": file_path in canonical,
        }

    for file_path, entry in file_cache.items():
        entry.update(prepared[file_path])
        entry["days"] = entry["deduped_days"] if entry["canonical"] else {}
        entry.pop("events", None)
    return True


def _codex_estimated_cost(model, inp, cached, out):
    if _codex_is_reserve_model(model):
        # Reserve 单独计量,按 Luna 级别计价,不吃 gpt-5.5 兜底。
        price_model = _CODEX_RESERVE_PRICE_MODEL
    else:
        price_model = model if _has_known_price(model) else "openai/gpt-5.5"
    base = _raw_price(price_model)
    high_context = inp > 272_000
    input_price = base["in"] * (2 if high_context else 1)
    output_price = base["out"] * (1.5 if high_context else 1)
    cache_price = base["cache_read"] * (2 if high_context else 1)
    return ((inp - cached) / 1e6 * input_price + cached / 1e6 * cache_price
            + out / 1e6 * output_price)


def _scale_codex_cached_days(entry, changed_models, multipliers):
    days = []
    seen = set()
    for field in ("days", "deduped_days"):
        values = entry.get(field)
        if not isinstance(values, dict):
            continue
        for day in values.values():
            if isinstance(day, dict) and id(day) not in seen:
                seen.add(id(day))
                days.append(day)

    targets = []
    for day in days:
        models = day.get("models")
        if not isinstance(models, dict):
            continue
        for model, usage in models.items():
            if not _model_has_pricing_change(model, changed_models):
                continue
            multiplier = _pricing_change_multiplier(model, multipliers)
            if multiplier is None:
                return None
            targets.append((usage, multiplier))
    if not targets:
        return None

    updated = set()
    for usage, multiplier in targets:
        if id(usage) in updated:
            continue
        usage["cost"] = float(usage.get("cost", 0) or 0) * multiplier
        updated.add(id(usage))
    for day in days:
        models = day.get("models") or {}
        if isinstance(models, dict):
            day["cost"] = sum(float(value.get("cost", 0) or 0)
                              for value in models.values() if isinstance(value, dict))
    return True


def _reprice_codex_event_caches(file_cache, changed_models, multipliers=None):
    multipliers = multipliers if isinstance(multipliers, dict) else {}
    changed = False
    for file_path, entry in file_cache.items():
        if not _cached_entry_has_pricing_change(entry, changed_models):
            continue
        scaled = _scale_codex_cached_days(entry, changed_models, multipliers)
        if scaled:
            changed = True
            continue
        if not _codex_event_cache_ready(file_path, entry):
            continue
        try:
            count = int(entry.get("event_count", 0) or 0)
            events = list(_iter_codex_cached_events(file_path, limit=count))
            for event in events:
                if len(event) < 11:
                    raise OSError("Codex event cache contains a short event")

            days = {}
            drop_count = min(max(int(entry.get("drop_count", 0) or 0), 0), len(events))
            for event in events[drop_count:]:
                _codex_add_event(days, event)
            if entry.get("deduped_days") != days:
                entry["deduped_days"] = days
            expected_days = days if entry.get("canonical") else {}
            if entry.get("days") != expected_days:
                entry["days"] = expected_days
            changed = True
        except (OSError, TypeError, ValueError):
            # Let the normal scanner rebuild only this damaged entry from its source.
            _codex_remove_event_cache(file_path)
            entry["event_cache_size"] = -1
            changed = True
    return changed


def _codex_day():
    return {"in": 0, "cached": 0, "out": 0, "reason": 0,
            "cost": 0.0, "models": {}, "hours": [0] * 24,
            "model_hours": {}}


def _codex_add_event(days, event):
    dk = event[1]
    li, lc, lo, lr, _ = event[6:11]
    model = event[11] if len(event) > 11 else None
    cost = _codex_estimated_cost(model, li, lc, lo)
    day = days.setdefault(dk, _codex_day())
    day["in"] += li
    day["cached"] += lc
    day["out"] += lo
    day["reason"] += lr
    day["cost"] += cost
    _add_model_usage(day["models"], model, max(li - lc, 0), lo, lc, 0, lr, cost)
    try:
        hour = datetime.fromisoformat(event[0]).astimezone().hour
        amount = li + lo
        day["hours"][hour] += amount
        model_hours = day.setdefault("model_hours", {}).setdefault(model, [0] * 24)
        model_hours[hour] += amount
    except (TypeError, ValueError):
        pass


def _codex_day_has_usage(day):
    return bool(day.get("models")) or any(day.get(key, 0) for key in (
        "in", "cached", "out", "reason", "cost"))


def _codex_split_day(day):
    """Split one parsed Codex day without losing event-level hour attribution."""
    main, reserve = _codex_day(), _codex_day()
    models = day.get("models") or {}
    if not models:
        for key in ("in", "cached", "out", "reason", "cost"):
            main[key] = day.get(key, 0)
        main["hours"] = list((day.get("hours") or [0] * 24)[:24])
        main["hours"] += [0] * (24 - len(main["hours"]))
        return main, reserve

    model_hours = day.get("model_hours") or {}
    for model, usage in models.items():
        target = reserve if _codex_is_reserve_model(model) else main
        li = usage.get("in", 0)
        lc = usage.get("cr", 0)
        lo = usage.get("out", 0)
        lr = usage.get("reason", 0)
        cost = usage.get("cost", 0)
        target["in"] += li + lc
        target["cached"] += lc
        target["out"] += lo
        target["reason"] += lr
        target["cost"] += cost
        _add_model_usage(target["models"], model, li, lo, lc,
                         usage.get("cw", 0), lr, cost)
        allocated = model_hours.get(model)
        if isinstance(allocated, list):
            for hour, amount in enumerate(allocated[:24]):
                target["hours"][hour] += amount

    # v7 writes model_hours for mixed days. A day whose models all belong to one
    # bucket remains unambiguous even when loaded from an older split ledger.
    if not model_hours:
        has_reserve = any(_codex_is_reserve_model(model) for model in models)
        has_main = any(not _codex_is_reserve_model(model) for model in models)
        if has_reserve != has_main:
            target = reserve if has_reserve else main
            target["hours"] = list((day.get("hours") or [0] * 24)[:24])
            target["hours"] += [0] * (24 - len(target["hours"]))
    return main, reserve


def _codex_split_sources(file_cache):
    main_days, reserve_days = {}, {}
    main_sources, reserve_sources = {}, {}
    main_sessions, reserve_sessions = {}, {}
    for path, entry in file_cache.items():
        if not isinstance(entry, dict):
            continue
        identity = str(entry.get("session_id") or path)
        for dk, day in (entry.get("days") or {}).items():
            main, reserve = _codex_split_day(day)
            has_main = _codex_day_has_usage(main)
            has_reserve = _codex_day_has_usage(reserve)
            if has_main:
                main_days[dk] = _ledger_values(main_days.get(dk, {}), main)
                main_sessions.setdefault(dk, set()).add(identity)
            if has_reserve:
                reserve_days[dk] = _ledger_values(reserve_days.get(dk, {}), reserve)
                reserve_sessions.setdefault(dk, set()).add(identity)
            if has_main:
                source_days = main_sources.setdefault(identity, {})
                source_days[dk] = _ledger_values(source_days.get(dk, {}), main)
                source_days[dk]["_accounting_version"] = _CODEX_ACCOUNTING_VERSION
                source_days[dk]["_ledger_version"] = _CODEX_ACCOUNTING_VERSION
            if has_reserve:
                source_days = reserve_sources.setdefault(identity, {})
                source_days[dk] = _ledger_values(source_days.get(dk, {}), reserve)
                source_days[dk]["_accounting_version"] = _CODEX_ACCOUNTING_VERSION
                source_days[dk]["_ledger_version"] = _CODEX_ACCOUNTING_VERSION
    return main_days, reserve_days, main_sources, reserve_sources, main_sessions, reserve_sessions


def _codex_migrate_mixed_ledger(main_sources, reserve_sources):
    """Replace pre-split Codex source snapshots using the reconstructed v7 split."""
    stored = _load_ledger().setdefault("tools", {}).setdefault("codex", {})
    main_by_day, reserve_by_day = {}, {}
    for target, sources in ((main_by_day, main_sources), (reserve_by_day, reserve_sources)):
        for identity, days in sources.items():
            source_id = hashlib.sha256(str(identity).encode()).hexdigest()
            for dk, day in days.items():
                target.setdefault(dk, {})[source_id] = day

    changed = False
    for dk, reserve_current in reserve_by_day.items():
        kept = stored.get(dk)
        if not isinstance(kept, dict):
            continue
        main_current = main_by_day.get(dk, {})
        if "_sources" not in kept:
            actual = {}
            for source_id in main_current.keys() | reserve_current.keys():
                actual = _ledger_values(actual, main_current.get(source_id, {}))
                actual = _ledger_values(actual, reserve_current.get(source_id, {}))
            legacy = _codex_legacy_day(_ledger_values(kept, actual, subtract=True))
            legacy["_accounting_version"] = _CODEX_ACCOUNTING_VERSION
            legacy["_ledger_version"] = _CODEX_ACCOUNTING_VERSION
            sources = {"legacy": legacy} if _codex_day_has_usage(legacy) else {}
        else:
            sources = dict(kept.get("_sources") or {})

        for source_id, reserve_snapshot in reserve_current.items():
            replacement = main_current.get(source_id)
            if replacement is None:
                replacement = {"_accounting_version": _CODEX_ACCOUNTING_VERSION,
                               "_ledger_version": _CODEX_ACCOUNTING_VERSION}
            # The current v7 event cache is authoritative for this visible source.
            # Replace even at the same accounting version so an incremental
            # response-first backfill can move usage out of the main ledger.
            if sources.get(source_id) != replacement:
                sources[source_id] = replacement

        result = {}
        for snapshot in sources.values():
            result = _ledger_values(result, snapshot)
        result["_sources"] = sources
        result["_ledger_version"] = _CODEX_ACCOUNTING_VERSION
        if kept != result:
            stored[dk] = result
            changed = True
    if changed:
        _LEDGER_CACHE["dirty"] = True


def _codex_accounted_days(cache, reserve=False):
    """Use the retained main or Reserve day/model/hour counters."""
    live = {}
    for entry in cache.get("codex", {}).values():
        if not isinstance(entry, dict):
            continue
        for dk, day in (entry.get("days") or {}).items():
            main, reserve_day = _codex_split_day(day)
            selected = reserve_day if reserve else main
            if _codex_day_has_usage(selected):
                live[dk] = _ledger_values(live.get(dk, {}), selected)
    tool = "codex_reserve" if reserve else "codex"
    for dk, kept in _load_ledger().get("tools", {}).get(tool, {}).items():
        if dk not in live or _ledger_day_total(kept) >= _ledger_day_total(live[dk]):
            live[dk] = kept
    return live


def _codex_reclassify_reserve_event(event):
    if not isinstance(event, list) or len(event) < 12:
        return False
    li, lc, lo = event[6], event[7], event[8]
    cost = _codex_estimated_cost(_CODEX_RESERVE_MODEL, li, lc, lo)
    if event[11] == _CODEX_RESERVE_MODEL and event[10] == cost:
        return False
    event[10] = cost
    event[11] = _CODEX_RESERVE_MODEL
    return True


def _codex_backfill_reserve_mirror(file_path, events, entry, mirror):
    """Route a response already emitted before its Reserve legacy mirror."""
    candidates = events
    cached = False
    if not candidates and isinstance(entry, dict):
        try:
            candidates = list(_iter_codex_cached_events(file_path))
            cached = True
        except OSError:
            return False
    for event in reversed(candidates):
        if len(event) > 9 and list(event[6:10]) == mirror:
            changed = _codex_reclassify_reserve_event(event)
            if changed and cached:
                entry["event_cache_size"] = _codex_write_event_cache(file_path, candidates)
            return changed
    return False


def _codex_link_segment_mirrors(file_cache):
    """Give dual-written events one response ID across resumed thread segments."""
    groups = {}
    for path, entry in file_cache.items():
        if isinstance(entry, dict):
            groups.setdefault(entry.get("session_id") or path, []).append(path)

    changed_paths = set()
    for paths in groups.values():
        if len(paths) < 2:
            continue
        loaded = {}
        identified = {}
        try:
            for path in paths:
                events = list(_iter_codex_cached_events(path))
                loaded[path] = events
                for event in events:
                    key = _codex_event_key(event)
                    response_id = event[12] if len(event) > 12 else None
                    if key is not None and response_id:
                        identified.setdefault(key, (response_id, event, path))
        except OSError:
            continue

        for path, events in loaded.items():
            for event in events:
                key = _codex_event_key(event)
                response_id = event[12] if len(event) > 12 else None
                match = identified.get(key)
                if key is None or response_id or match is None:
                    continue
                matched_id, response_event, response_path = match
                while len(event) <= 12:
                    event.append(None)
                event[12] = matched_id
                changed_paths.add(path)
                if (_codex_is_reserve_model(event[11])
                        or _codex_is_reserve_model(response_event[11])):
                    if _codex_reclassify_reserve_event(event):
                        changed_paths.add(path)
                    if _codex_reclassify_reserve_event(response_event):
                        changed_paths.add(response_path)

        for path in changed_paths.intersection(paths):
            entry = file_cache[path]
            entry["event_cache_size"] = _codex_write_event_cache(path, loaded[path])
    return changed_paths


def _codex_prefix_match_count(child_events, parent_events):
    n = 0
    while n < len(child_events) and n < len(parent_events):
        if not _codex_events_match(child_events[n], parent_events[n]):
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
    prefix_candidates = {}
    for file_path, entry in ordered:
        events = entry.get("events") or []
        if len(events) < 2:
            continue
        first = _codex_event_key(events[0])
        second = _codex_event_key(events[1])
        if first is not None and second is not None:
            prefix_candidates.setdefault((first, second), []).append((file_path, entry))

    for file_path, entry in ordered:
        if drops.get(file_path):
            continue
        child_events = entry.get("events") or []
        if len(child_events) < 2:
            continue
        first = _codex_event_key(child_events[0])
        second = _codex_event_key(child_events[1])
        if first is None or second is None:
            continue
        child_first_ts = child_events[0][0]
        best = 0
        for parent_path, parent_entry in prefix_candidates.get((first, second), []):
            if parent_path == file_path:
                continue
            parent_events = parent_entry.get("events") or []
            if not parent_events or parent_events[0][0] >= child_first_ts:
                continue
            best = max(best, _codex_prefix_match_count(child_events, parent_events))
        if best >= 2:
            drops.setdefault(file_path, set()).update(range(best))

    # 兜底:文件开头同一秒内 ≥5 条 token 事件必是回放转储(真实 API 一秒内
    # 不可能完成 5 次响应)。覆盖从父会话中段(如 compact 后)分叉、
    # 累计值与父文件开头对不上导致前缀匹配失效的场景。
    for file_path, entry in ordered:
        events = entry.get("events") or []
        if len(events) < 5:
            continue
        already = drops.get(file_path, set())
        start = 0
        while start in already:
            start += 1
        if start + 4 >= len(events):
            continue
        first_ev = events[start]
        if not isinstance(first_ev, list) or not first_ev:
            continue
        burst_sec = str(first_ev[0])[:19]
        n = start
        while n < len(events):
            ev = events[n]
            if not isinstance(ev, list) or not ev or str(ev[0])[:19] != burst_sec:
                break
            n += 1
        if n - start >= 5:
            drops.setdefault(file_path, set()).update(range(start, n))
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


_CODEX_MODEL_RECORD_TYPES = {"turn_context", "session_meta"}
_CODEX_USAGE_RECORD_MARKERS = (
    b'"token_count"', b'"token_usage_record"', b'"task_started"',
    b'"turn_context"', b'"session_meta"',
)


def _codex_decode_json_string(raw):
    try:
        if b"\\" not in raw:
            return raw.decode("utf-8")
        return json.loads(b'"' + raw + b'"')
    except Exception:
        return raw.decode("utf-8", errors="ignore")


def _codex_probe_record_header(data):
    """Read selected JSON fields from a bounded record prefix.

    Codex adds top-level metadata fields over time. This structural probe tracks
    object depth instead of depending on serialized key order, while leaving
    large unrelated JSONL records bounded by the caller's prefix limits.
    """
    timestamp = None
    root_type = None
    payload_type = None
    model = None
    pending_keys = {}
    containers = []
    payload_depth = None
    depth = 0
    i = 0
    size = len(data)

    while i < size:
        ch = data[i]
        if ch in b" \t\r\n":
            i += 1
            continue

        if ch == 0x22:  # JSON string
            start = i + 1
            i = start
            while i < size:
                if data[i] == 0x5C:  # escape
                    i += 2
                    continue
                if data[i] == 0x22:
                    break
                i += 1
            if i >= size:
                break

            value = _codex_decode_json_string(bytes(data[start:i]))
            i += 1
            lookahead = i
            while lookahead < size and data[lookahead] in b" \t\r\n":
                lookahead += 1
            if lookahead < size and data[lookahead] == 0x3A:  # colon
                pending_keys[depth] = value
                i = lookahead + 1
                continue

            key = pending_keys.pop(depth, None)
            if depth == 1:
                if key == "timestamp":
                    timestamp = value
                elif key == "type":
                    root_type = value
            elif payload_depth is not None and depth == payload_depth:
                if key == "type":
                    payload_type = value
                elif key == "model":
                    model = value
            i = lookahead
            continue

        if ch in (0x7B, 0x5B):  # object or array open
            parent_depth = depth
            key = pending_keys.pop(parent_depth, None)
            containers.append(ch)
            depth += 1
            if ch == 0x7B and parent_depth == 1 and key == "payload":
                payload_depth = depth
            i += 1
            continue

        if ch in (0x7D, 0x5D):  # object or array close
            pending_keys.pop(depth, None)
            if payload_depth == depth:
                payload_depth = None
            if containers:
                containers.pop()
            depth = max(0, depth - 1)
            i += 1
            continue

        if ch == 0x2C:  # comma
            pending_keys.pop(depth, None)
        i += 1

    return timestamp, root_type, payload_type, model


def _iter_codex_usage_records(path, chunk_size=64 * 1024, header_limit=1024,
                              model_limit=64 * 1024, start_offset=0, end_offset=None):
    """Yield model changes and token records without buffering unrelated large JSONL lines."""
    # Recent permission profiles put payload.model beyond the old 4 KB prefix.
    # Keep model probing bounded so large instructions never require full buffering.
    prefix = bytearray()
    candidate = None
    kind = None

    with open(path, "rb", buffering=0) as fh:
        if start_offset:
            fh.seek(start_offset)
        while True:
            if end_offset is not None:
                remaining = end_offset - fh.tell()
                if remaining <= 0:
                    break
                chunk = fh.read(min(chunk_size, remaining))
            else:
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
                    _, _, _, model = _codex_probe_record_header(prefix)
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
                    if any(marker in prefix for marker in _CODEX_USAGE_RECORD_MARKERS):
                        timestamp, root_type, payload_type, model = (
                            _codex_probe_record_header(prefix)
                        )
                    else:
                        timestamp = root_type = payload_type = model = None
                    if timestamp and (root_type == "token_usage_record" or
                            (root_type == "event_msg" and payload_type in ("token_count", "task_started"))):
                        candidate = prefix
                        prefix = bytearray()
                        kind = "token"
                        if take < len(piece):
                            candidate.extend(piece[take:])
                    elif timestamp and root_type in _CODEX_MODEL_RECORD_TYPES:
                        kind = "model"
                        if take < len(piece):
                            extra = min(len(piece) - take, model_limit - len(prefix))
                            prefix.extend(piece[take:take + extra])
                        _, _, _, model = _codex_probe_record_header(prefix)
                        if model:
                            yield "model", model
                            prefix = bytearray()
                            kind = "ignore"
                    elif (root_type is not None
                          and root_type not in _CODEX_MODEL_RECORD_TYPES
                          and (root_type != "event_msg"
                               or (payload_type is not None
                                   and payload_type != "token_count"))):
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


def _codex_complete_offset(path, size, chunk_size=64 * 1024):
    """Return the byte offset after the last complete JSONL record."""
    if size <= 0:
        return 0
    try:
        with open(path, "rb", buffering=0) as fh:
            fh.seek(size - 1)
            if fh.read(1) == b"\n":
                return size
            position = size
            while position > 0:
                start = max(0, position - chunk_size)
                fh.seek(start)
                data = fh.read(position - start)
                newline = data.rfind(b"\n")
                if newline >= 0:
                    return start + newline + 1
                position = start
    except OSError:
        return 0
    return 0


def _codex_offset_guard(path, offset, guard_size=4096):
    if offset <= 0:
        return ""
    try:
        import hashlib
        with open(path, "rb", buffering=0) as fh:
            start = max(0, offset - guard_size)
            fh.seek(start)
            data = fh.read(offset - start)
        return hashlib.sha256(data).hexdigest()
    except OSError:
        return None


def _iter_codex_token_lines(path, chunk_size=64 * 1024, header_limit=4 * 1024):
    """Compatibility iterator for callers that only need token_count records."""
    for kind, value in _iter_codex_usage_records(path, chunk_size, header_limit):
        if kind == "token":
            yield value


# 每轮扫描最多回填多少个会话的项目路径。
#
# cwd 就在会话文件第 0 行，但光是打开一个文件就要约 10ms——几千个历史会话
# 合起来是几十秒，不能让升级后的第一次刷新扛下来。所以分摊到多轮，并且
# 按最近活跃优先：项目足迹本来就按 last_active 排序，用户看得见的那几行
# 第一轮就补齐，长尾在后台几分钟内自然补完。
_CODEX_PROJECT_BACKFILL_PER_SCAN = 150


def _codex_session_cwd(path, max_lines=8, max_line_bytes=128 * 1024):
    """会话的工作目录。cwd 在文件头部的 session_meta 记录里，所以只读前几行——
    为了一个字段重解析几千个会话文件是不值当的。

    只认 session_meta 那一行：按 cwd 匹配会一路扫到后面的大事件行上去,
    几千个会话累计起来就是几十秒。"""
    try:
        with open(path, "rb", buffering=0) as fh:
            for _ in range(max_lines):
                line = fh.readline(max_line_bytes)
                if not line:
                    break
                if b'"session_meta"' not in line:
                    continue
                try:
                    record = json.loads(line.decode("utf-8", errors="ignore"))
                except Exception:
                    continue
                payload = record.get("payload")
                cwd = payload.get("cwd") if isinstance(payload, dict) else record.get("cwd")
                if isinstance(cwd, str) and cwd.startswith("/"):
                    return cwd
    except OSError:
        return None
    return None


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


def _codex_rollout_files():
    roots = _existing_dirs(
        _path_candidates("TOKEI_CODEX_DIR", CODEX_DIR) +
        _path_candidates("TOKEI_CODEX_ARCHIVED_DIR", CODEX_ARCHIVED_DIR)
    )
    files = []
    seen = set()
    for root in roots:
        for path in sorted(glob.glob(os.path.join(root, "**", "rollout-*.jsonl"), recursive=True)):
            real = os.path.realpath(path)
            key = os.path.normcase(real)
            if key not in seen and os.path.isfile(real):
                seen.add(key)
                files.append(real)
    return files


def _codex_canonical_file_cache(file_cache):
    """Keep resumed segments; discard only copies covered by another segment."""
    canonical = {}
    groups = {}
    for path, entry in file_cache.items():
        if not isinstance(entry, dict):
            continue
        sid = entry.get("session_id")
        key = ("session", str(sid)) if sid else ("rollout", os.path.basename(path))
        groups.setdefault(key, []).append((path, entry))
    def score(item):
        entry = item[1]
        events = entry.get("events") or []
        timestamps = [str(e[0]) for e in events if isinstance(e, list) and e]
        return (int(entry.get("event_count", len(events)) or 0),
                str(entry.get("last_event_ts") or max(timestamps, default="")),
                int(entry.get("parsed_size", 0) or 0))
    for copies in groups.values():
        covered = set()
        legacy_selected = False
        for path, entry in sorted(copies, key=score, reverse=True):
            ids = set(entry.get("response_ids") or [])
            if ids:
                if ids <= covered:
                    continue
                covered.update(ids)
            else:
                if legacy_selected:
                    continue
                legacy_selected = True
            canonical[path] = entry
    return canonical


def scan_codex(bounds, cache):
    ledger_touch("codex")
    fc = cache.setdefault("codex", {})
    if _codex_migrate_event_cache(fc):
        cache["_dirty"] = True
    if (cache.get("_pricing_changed")
            and _reprice_codex_event_caches(
                fc, cache.get("_pricing_changed_models") or [],
                cache.get("_pricing_cost_multipliers") or {})):
        cache["_dirty"] = True
    B = {k: {"in": 0, "cached": 0, "out": 0, "reason": 0, "cost": 0.0,
             "sessions": set(), "models": {}}
         for k in RANGE_KEYS}
    rollout_files = _codex_rollout_files()
    today_d = bounds["today"].date()
    yest_d = bounds["yesterday"].date()
    week_d = bounds["week"].date()
    lw_start_d = bounds["last_week"].date()
    lw_end_d = bounds["last_week_end"].date()
    month_d = bounds["month"].date()
    year_d = bounds["year"].date()

    cur_file, cur_mtime = None, -1.0
    stale = set(fc.keys())
    dedupe_paths = set()
    active_root = os.path.realpath(CODEX_DIR) if os.path.isdir(CODEX_DIR) else None
    next_checkpoint = _time.monotonic() + _CODEX_SCAN_CHECKPOINT_INTERVAL

    for f in rollout_files:
        stale.discard(f)
        try:
            st = os.stat(f)
        except OSError:
            continue
        mtime, size = st.st_mtime, st.st_size
        try:
            is_active = active_root is not None and os.path.commonpath((f, active_root)) == active_root
        except ValueError:
            is_active = False
        if is_active and mtime > cur_mtime:
            cur_mtime = mtime
            cur_file = f
        sig = f"{st.st_mtime_ns}:{size}"
        entry = fc.get(f)
        previous_event_cache_size = (
            entry.get("event_cache_size") if isinstance(entry, dict) else None
        )
        event_cache_ready = _codex_event_cache_ready(f, entry, repair_short=True)
        if (event_cache_ready and isinstance(entry, dict)
                and entry.get("event_cache_size") != previous_event_cache_size):
            cache["_dirty"] = True
        if (not entry or entry.get("sig") != sig
                or entry.get("parser_version") != _CODEX_PARSER_VERSION
                or entry.get("accounting_version") != _CODEX_ACCOUNTING_VERSION
                or not event_cache_ready):
            complete_offset = _codex_complete_offset(f, size)
            file_id = f"{st.st_dev}:{st.st_ino}"
            append_from = None
            if (isinstance(entry, dict)
                    and entry.get("parser_version") == _CODEX_PARSER_VERSION
                    and entry.get("accounting_version") == _CODEX_ACCOUNTING_VERSION):
                old_offset = int(entry.get("parsed_size", 0) or 0)
                if (entry.get("file_id") == file_id and old_offset <= complete_offset
                        and entry.get("parsed_guard") == _codex_offset_guard(f, old_offset)
                        and event_cache_ready):
                    append_from = old_offset

            if append_from is None:
                events = []
                session_id, forked_from_id = _codex_session_meta(f)
                file_limits = None; file_limits_ts = None; file_plan = None
                file_g_limits = None; file_g_ts = None; file_g_plan = None
                file_r_limits = None; file_r_ts = None
                file_last_total = None
                prev_total_key = None
                file_model = None
                response_ids = set()
                pending_responses = []
                last_legacy_snapshot = None
                parse_start = 0
            else:
                events = []
                session_id = entry.get("session_id")
                forked_from_id = entry.get("forked_from_id")
                file_limits = entry.get("limits"); file_limits_ts = entry.get("limits_ts")
                file_plan = entry.get("plan")
                file_g_limits = entry.get("g_limits"); file_g_ts = entry.get("g_ts")
                file_g_plan = entry.get("g_plan")
                file_r_limits = entry.get("reserve_limits"); file_r_ts = entry.get("reserve_limits_ts")
                file_last_total = entry.get("last_total")
                previous = entry.get("prev_total_key")
                prev_total_key = tuple(previous) if isinstance(previous, (list, tuple)) else None
                file_model = entry.get("active_model")
                response_ids = set(entry.get("response_ids") or [])
                pending_responses = list(entry.get("pending_responses") or [])
                last_legacy_snapshot = entry.get("last_legacy_snapshot")
                parse_start = append_from

            try:
                for record_kind, record in _iter_codex_usage_records(
                        f, start_offset=parse_start, end_offset=complete_offset):
                    if record_kind == "model":
                        file_model = record
                        continue
                    try:
                        o = json.loads(record.decode("utf-8", errors="ignore"))
                    except Exception:
                        continue
                    ts = parse_ts(o.get("timestamp", ""))
                    if not ts:
                        continue
                    payload = o.get("payload") or {}
                    if payload.get("type") == "task_started":
                        pending_responses = []
                        last_legacy_snapshot = None
                        continue
                    is_response = o.get("type") == "token_usage_record"
                    response_id = None
                    if is_response:
                        usage = payload.get("usage") or {}
                        if not isinstance(usage, dict):
                            continue
                        # Persist the mirror across incremental scans split between the
                        # authoritative record and its legacy token_count notification.
                        response_usage = [usage.get(k, 0) or 0 for k in (
                            "input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")]
                        raw_id = payload.get("response_id")
                        response_id = hashlib.sha256(str(raw_id).encode()).hexdigest() if raw_id else None
                        if response_id and response_id in response_ids:
                            continue
                        if response_id:
                            response_ids.add(response_id)
                        response_total = payload.get("thread_token_usage") or {}
                        snapshot_key = [response_total.get(k, 0) or 0 for k in (
                            "input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")] + response_usage
                        if response_total and snapshot_key == last_legacy_snapshot:
                            # Attach identity to the legacy event already counted, so
                            # overlapping runtime segments can deduplicate it too.
                            prior_events = events
                            if not prior_events and append_from is not None:
                                prior_events = list(_iter_codex_cached_events(f))
                            if (response_id and prior_events
                                    and list(prior_events[-1][2:10]) == snapshot_key):
                                prior_events[-1][12] = response_id
                                if prior_events is not events:
                                    entry["event_cache_size"] = _codex_write_event_cache(f, prior_events)
                                    dedupe_paths.add(f)
                            last_legacy_snapshot = None
                            continue  # Legacy-first dual write, already counted.
                        pending_responses.append(response_usage)
                        owner = payload.get("thread_id")
                        if owner and session_id and owner != session_id:
                            continue  # A fork copied a parent's response and its mirror.
                        info = {"last_token_usage": usage,
                                "total_token_usage": payload.get("thread_token_usage") or {}}
                    else:
                        info = payload.get("info") or {}
                    last = info.get("last_token_usage") or {}
                    total = info.get("total_token_usage") or {}
                    total_key = None
                    duplicate_total = False
                    if total:
                        total_key = (total.get("input_tokens", 0) or 0,
                                     total.get("cached_input_tokens", 0) or 0,
                                     total.get("output_tokens", 0) or 0,
                                     total.get("reasoning_output_tokens", 0) or 0)
                        duplicate_total = not is_response and total_key == prev_total_key
                        prev_total_key = total_key
                        file_last_total = total
                    if not is_response and last:
                        mirror = [last.get(k, 0) or 0 for k in (
                            "input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")]
                        last_legacy_snapshot = list(total_key or (None,) * 4) + mirror
                        if mirror in pending_responses:
                            duplicate_total = True
                            pending_responses.remove(mirror)
                            if _codex_is_reserve_limits(payload.get("rate_limits")):
                                if _codex_backfill_reserve_mirror(f, events, entry, mirror):
                                    dedupe_paths.add(f)
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
                        # Reserve 是第二缸油:额度独立展示,不混入主额度读数。
                        if _codex_is_reserve_limits(rl) and (file_r_ts is None or ts_iso > file_r_ts):
                            file_r_ts = ts_iso
                            file_r_limits = rl
                    # Codex may emit the same cumulative snapshot twice; in that case
                    # last_token_usage is repeated too, so counting it again overstates usage.
                    if ts and last and not duplicate_total:
                        dk = ts.astimezone().date().isoformat()
                        li = last.get("input_tokens", 0) or 0
                        lc = last.get("cached_input_tokens", 0) or 0
                        lo = last.get("output_tokens", 0) or 0
                        lr = last.get("reasoning_output_tokens", 0) or 0
                        # 无模型字段(老版本 CLI 日志/截断会话)标为 unknown,不冒充 gpt-5.5;
                        # 计费仍按 gpt-5.5 保守估算(下行 price_model 兜底)
                        model = _model_identity_id(file_model) or "unknown"
                        # 同一文件可先走主额度后切 Reserve:事件级额度优先于文件级模型。
                        if _codex_is_reserve_limits(rl):
                            model = _CODEX_RESERVE_MODEL
                        cost = _codex_estimated_cost(model, li, lc, lo)
                        totals = total_key if total_key is not None else (None, None, None, None)
                        # timestamp, local day, cumulative usage, incremental usage, cost
                        if li or lc or lo or lr:
                            events.append([ts.isoformat(), dk, *totals, li, lc, lo, lr, cost, model, response_id])
            except OSError:
                continue

            if append_from is None:
                event_cache_size = _codex_write_event_cache(f, events)
                metadata = _codex_event_metadata(events)
                deduped_days = {}
                drop_count = 0
                dedupe_open = True
                was_canonical = False
                dedupe_paths.add(f)
            else:
                event_cache_size = _codex_append_event_cache(
                    f, events, int(entry.get("event_cache_size", 0) or 0))
                metadata = {
                    "event_count": int(entry.get("event_count", 0) or 0) + len(events),
                    "first_keys": entry.get("first_keys") or [],
                    "first_event_ts": entry.get("first_event_ts"),
                    "last_event_ts": (
                        str(events[-1][0]) if events else entry.get("last_event_ts")
                    ),
                }
                if len(metadata["first_keys"]) < 2 and metadata["event_count"]:
                    prefix_events = list(_iter_codex_cached_events(f, limit=2))
                    prefix_metadata = _codex_event_metadata(prefix_events)
                    metadata["first_keys"] = prefix_metadata["first_keys"]
                    metadata["first_event_ts"] = prefix_metadata["first_event_ts"]
                deduped_days = entry.get("deduped_days")
                if not isinstance(deduped_days, dict):
                    deduped_days = dict(entry.get("days") or {})
                drop_count = int(entry.get("drop_count", 0) or 0)
                dedupe_open = bool(entry.get("dedupe_open"))
                was_canonical = bool(entry.get("canonical"))
                if dedupe_open:
                    dedupe_paths.add(f)
                else:
                    for event in events:
                        _codex_add_event(deduped_days, event)

            fc[f] = {
                "sig": sig, "days": entry.get("days", {}) if isinstance(entry, dict) else {},
                "deduped_days": deduped_days,
                "session_id": session_id, "forked_from_id": forked_from_id,
                "limits": file_limits, "limits_ts": file_limits_ts, "plan": file_plan,
                "g_limits": file_g_limits, "g_ts": file_g_ts, "g_plan": file_g_plan,
                "reserve_limits": file_r_limits, "reserve_limits_ts": file_r_ts,
                "last_total": file_last_total, "prev_total_key": prev_total_key,
                "active_model": file_model, "parser_version": _CODEX_PARSER_VERSION,
                "accounting_version": _CODEX_ACCOUNTING_VERSION,
                "response_ids": sorted(response_ids), "pending_responses": pending_responses,
                "last_legacy_snapshot": last_legacy_snapshot,
                "file_id": file_id, "parsed_size": complete_offset,
                "parsed_guard": _codex_offset_guard(f, complete_offset),
                "event_cache_size": event_cache_size,
                "event_count": metadata["event_count"],
                "first_keys": metadata["first_keys"],
                "first_event_ts": metadata["first_event_ts"],
                "last_event_ts": metadata["last_event_ts"],
                "drop_count": drop_count, "dedupe_open": dedupe_open,
                "canonical": was_canonical,
                "dedupe_peers": entry.get("dedupe_peers") if isinstance(entry, dict) else None,
            }
            cache["_dirty"] = True
            if _time.monotonic() >= next_checkpoint:
                _save_scan_cache(cache)
                next_checkpoint = _time.monotonic() + _CODEX_SCAN_CHECKPOINT_INTERVAL

    for p in stale:
        fc.pop(p, None)
        _codex_remove_event_cache(p)
        cache["_dirty"] = True

    linked_paths = _codex_link_segment_mirrors(fc)
    if linked_paths:
        dedupe_paths.update(linked_paths)
    # 项目路径按需补齐,让 Codex 参与项目足迹与回顾页。没读到也写空串占位,
    # 免得每轮扫描都为同一批读不出 cwd 的会话重复开文件。
    pending = [(str(entry.get("last_event_ts") or ""), f, entry)
               for f, entry in fc.items()
               if isinstance(entry, dict) and "proj" not in entry]
    if pending:
        pending.sort(reverse=True)      # 最近活跃的会话先补，排序用缓存里现成的时间戳
        for _, f, entry in pending[:_CODEX_PROJECT_BACKFILL_PER_SCAN]:
            entry["proj"] = _codex_session_cwd(f) or ""
        cache["_dirty"] = True

    # A session can briefly exist in active and archived directories together.
    # Select the more complete copy before applying fork/replay deduplication.
    canonical_fc = _codex_canonical_file_cache(fc)
    for f, entry in fc.items():
        is_canonical = f in canonical_fc
        if is_canonical and not entry.get("canonical"):
            dedupe_paths.add(f)
        if entry.get("canonical") != is_canonical:
            entry["canonical"] = is_canonical
            cache["_dirty"] = True

    # Different runtime segments can overlap responses while sharing a thread ID.
    # Rebuild these groups together so a warm scan cannot retain a stale duplicate.
    session_groups = {}
    for path, entry in canonical_fc.items():
        session_groups.setdefault(entry.get("session_id") or path, []).append(path)
    shared_seen = {}
    for sid, paths in session_groups.items():
        peers = sorted(paths)
        for path in paths:
            entry = canonical_fc[path]
            if entry.get("dedupe_peers") != peers:
                entry["dedupe_peers"] = peers
                dedupe_paths.add(path)
                cache["_dirty"] = True
        if len(paths) > 1:
            seen = set()
            for path in paths:
                shared_seen[path] = seen
                dedupe_paths.add(path)

    for f in sorted(dedupe_paths):
        entry = canonical_fc.get(f)
        if entry is None:
            continue
        try:
            drop_count, dedupe_open = _codex_cached_drop_count(f, entry, canonical_fc)
            deduped_days = _codex_days_from_cached_events(
                f, start_index=drop_count, event_count=entry.get("event_count"),
                seen_responses=shared_seen.get(f))
        except OSError:
            _codex_clear_event_cache(fc)
            cache["_dirty"] = True
            raise
        if (entry.get("drop_count") != drop_count or
                entry.get("dedupe_open") != dedupe_open or
                entry.get("deduped_days") != deduped_days):
            entry["drop_count"] = drop_count
            entry["dedupe_open"] = dedupe_open
            entry["deduped_days"] = deduped_days
            cache["_dirty"] = True

    for f, entry in fc.items():
        days = entry.get("deduped_days", {}) if f in canonical_fc else {}
        if entry.get("days") != days:
            entry["days"] = days
            cache["_dirty"] = True

    # Assembly: per-day → range buckets
    def _codex_range_keys(d):
        ks = ["all"]
        if d == today_d: ks.append("today")
        if d == yest_d: ks.append("yesterday")
        if d >= week_d: ks.append("week")
        if lw_start_d <= d < lw_end_d: ks.append("last_week")
        if d >= month_d: ks.append("month")
        if d >= year_d: ks.append("year")
        return ks

    (live_days, live_reserve_days, main_sources, reserve_sources,
     main_sessions, reserve_sessions) = _codex_split_sources(canonical_fc)
    _codex_migrate_mixed_ledger(main_sources, reserve_sources)

    merged_days = ledger_reconcile("codex", live_days, main_sources)
    merged_reserve_days = ledger_reconcile(
        "codex_reserve", live_reserve_days, reserve_sources)

    def _assemble_codex_ranges(target, days, sessions):
        for dk, day in days.items():
            try:
                d = date.fromisoformat(dk)
            except ValueError:
                continue
            for key in _codex_range_keys(d):
                bucket = target[key]
                bucket["in"] += day.get("in", 0)
                bucket["cached"] += day.get("cached", 0)
                bucket["out"] += day.get("out", 0)
                bucket["reason"] += day.get("reason", 0)
                bucket["cost"] += day.get("cost", 0.0)
                bucket["sessions"].update(sessions.get(dk, ()))
                for model, usage in (day.get("models") or {}).items():
                    _add_model_usage(
                        bucket["models"], model, usage.get("in", 0),
                        usage.get("out", 0), usage.get("cr", 0),
                        usage.get("cw", 0), usage.get("reason", 0),
                        usage.get("cost", 0))

    _assemble_codex_ranges(B, merged_days, main_sessions)

    # Reserve is independently attributed down to source, session, day and hour.
    RB = {k: {"in": 0, "cached": 0, "out": 0, "reason": 0, "cost": 0.0,
              "sessions": set(), "models": {}}
          for k in RANGE_KEYS}
    _assemble_codex_ranges(RB, merged_reserve_days, reserve_sessions)

    # Find latest limits across all cached files
    latest_limits = None; latest_ts = None; plan_type = None
    reserve_limits = None; reserve_ts = None
    g_limits = None; g_ts = None
    for entry in fc.values():
        if entry.get("limits_ts"):
            if latest_ts is None or entry["limits_ts"] > latest_ts:
                latest_ts = entry["limits_ts"]
                latest_limits = entry["limits"]
                plan_type = entry["plan"]
        if entry.get("reserve_limits_ts"):
            if reserve_ts is None or entry["reserve_limits_ts"] > reserve_ts:
                reserve_ts = entry["reserve_limits_ts"]
                reserve_limits = entry["reserve_limits"]
        if entry.get("g_ts"):
            if g_ts is None or entry["g_ts"] > g_ts:
                g_ts = entry["g_ts"]
                g_limits = entry["g_limits"]

    selected_limits_ts = latest_ts
    if (latest_limits is None and g_limits is not None
            and not _codex_is_reserve_limits(g_limits)):
        latest_limits = g_limits
        plan_type = (g_limits or {}).get("plan_type")
        selected_limits_ts = g_ts

    # 读数时间:live 真正胜出时用抓取时刻,否则用日志里那条记录的时间。
    # live_updated 只在 if live 分支内有定义,先在外面兜底。
    limits_updated = _iso_to_epoch(selected_limits_ts)
    live = fetch_codex_live_limits()
    if live:
        live_limits, live_plan, live_updated = live
        if _codex_live_snapshot_is_current(live_updated, selected_limits_ts):
            latest_limits = live_limits
            plan_type = live_plan or (live_limits or {}).get("plan_type") or plan_type
            limits_updated = int(live_updated)

    # 窗口翻篇后本机又消耗了多少 —— 用来区分「确实回满了」和「读数已经失真」。
    # now_epoch=0 让映射函数只做槽位归类,不触发过期处理。
    slots = _codex_quota_values(latest_limits, now_epoch=0)
    limits_consumed = {
        "p5": _codex_used_since(merged_days, slots["r5"]),
        "pw": _codex_used_since(merged_days, slots["rw"]),
    }

    # For third-party providers the official OpenAI quota is not meaningful,
    # and stale limits from older sessions must not be shown.
    if _codex_is_custom_provider():
        latest_limits = None
        reserve_limits = None
        plan_type = None

    cur_total = None
    if cur_file:
        entry = fc.get(cur_file)
        if entry:
            cur_total = entry.get("last_total")

    reserve_quota = None
    if reserve_limits:
        r_primary = (reserve_limits.get("primary") or {})
        is_week = r_primary.get("window_minutes") == 7 * 24 * 60
        pct_key, reset_key = ("pw", "rw") if is_week else ("p5", "r5")
        initial = _codex_quota_values(reserve_limits, now_epoch=0)
        consumed = _codex_used_since(merged_reserve_days, initial[reset_key])
        normalized = _codex_quota_values(
            reserve_limits, consumed={pct_key: consumed})
        reserve_quota = {
            "used_percent": normalized[pct_key],
            "resets_at": normalized[reset_key],
            "window_minutes": r_primary.get("window_minutes"),
            "plan": reserve_limits.get("plan_type"),
            "updated": _iso_to_epoch(reserve_ts),
            "stale": normalized[f"{pct_key}_stale"],
        }

    return {
        "ranges": B,
        "reserve_ranges": RB,
        "reserve_quota": reserve_quota,
        "cur_total": cur_total,
        "limits": latest_limits,
        "plan": plan_type,
        "limits_updated": limits_updated,
        "limits_consumed": limits_consumed,
    }


def _codex_used_since(days, since_epoch):
    """since_epoch 之后本机消耗的 codex token;拿不到就返回 None。

    账本里 in 已含 cached,所以口径是 in+out(与 hours 一致)。起始那天按 hours[24]
    从重置小时切起;宁可把重置那个整点全算进来,也不要漏报消耗——漏报会让一份
    已经失真的额度读数被当成"还满着"。
    """
    if not isinstance(days, dict) or not since_epoch:
        return None
    try:
        start = datetime.fromtimestamp(float(since_epoch))
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    start_day = start.date().isoformat()
    total = 0
    for dk, day in days.items():
        if not isinstance(day, dict) or dk < start_day:
            continue
        whole_day = int(day.get("in", 0) or 0) + int(day.get("out", 0) or 0)
        if dk > start_day:
            total += whole_day
            continue
        hours = day.get("hours") or []
        # 没有小时分布(老账本条目)就整天算,保守方向是宁多勿少
        total += sum(int(h or 0) for h in hours[start.hour:24]) if hours else whole_day
    return total


def _codex_quota_values(limits, now_epoch=None, consumed=None):
    """Map Codex rate-limit slots by duration; primary/secondary roles can change.

    consumed = {"p5": n, "pw": n}:该窗口 resets_at 之后本机又消耗了多少 token。
    """
    values = {"p5": None, "pw": None, "r5": None, "rw": None,
              "p5_stale": False, "pw_stale": False}
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
        if not reset or now_epoch <= reset:
            continue
        # 窗口已经翻篇。此后一个 token 都没用 = 确实回满了;用过 = 这份读数已经
        # 失真,标出来让界面说"已过期"。谎报满额比承认不知道危险得多(issue #63)。
        if (consumed or {}).get(pct_key) == 0:
            values[pct_key] = 0.0
            values[reset_key] = None
        elif values[pct_key] is not None:
            values[f"{pct_key}_stale"] = True
    return values


# ---------- Gemini / Antigravity CLI ----------
# 日志:
# - Gemini CLI: ~/.gemini/tmp/<projectHash>/chats/{session-*.json,session-*.jsonl,<parent>/*.jsonl}
#   assistant 行 type=="gemini",tokens={input,output,cached,thoughts,total}
# - Antigravity CLI: ~/.gemini/antigravity-cli/conversations/<uuid>.db
#   gen_metadata 表存储 protobuf 逐步生成指标(包含 input, output, cached, thoughts, model, start_time)
def _gemini_session_files():
    files = []
    roots = _path_candidates("TOKEI_GEMINI_DIR", GEMINI_DIR, *GEMINI_DIRS)
    patterns = []
    for root in roots:
        patterns.extend((
            os.path.join(root, "*.db"),
            os.path.join(root, "**", "*.db"),
            os.path.join(root, "*", "chats", "session-*.json"),
            os.path.join(root, "*", "chats", "**", "*.jsonl"),
            os.path.join(root, "**", "session-*.json"),
            os.path.join(root, "**", "session-*.jsonl"),
        ))
    for pattern in patterns:
        files.extend(glob.glob(pattern, recursive=True))
    return sorted(set(os.path.realpath(path) for path in files
                      if os.path.isfile(path) and not path.endswith("conversation_summaries.db")))


_PROTO_VARINT_MAX_BYTES = 10  # protobuf 规范:64 位整数最多 10 个字节


def _decode_proto_varint(data, offset):
    """坏数据不封顶会让 val 长成百万位大整数,每轮 |= 都是 O(n),整体退化成 O(n²)。"""
    val = 0
    shift = 0
    for _ in range(_PROTO_VARINT_MAX_BYTES):
        if offset >= len(data):
            break
        b = data[offset]
        offset += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            return val, offset
        shift += 7
    raise ValueError("varint 超过 64 位,当坏数据处理")


def _parse_proto_fields(data):
    i = 0
    fields = []
    while i < len(data):
        try:
            key, i = _decode_proto_varint(data, i)
            field_num = key >> 3
            wire_type = key & 0x7
            if wire_type == 0:
                val, i = _decode_proto_varint(data, i)
            elif wire_type == 2:
                length, i = _decode_proto_varint(data, i)
                # 越界不能靠切片静默截短:截出来的碎片会被当成合法子消息继续解析。
                if length < 0 or i + length > len(data):
                    break
                val = data[i:i + length]
                i += length
            elif wire_type in (1, 5):
                width = 8 if wire_type == 1 else 4
                if i + width > len(data):
                    break
                val = data[i:i + width]
                i += width
            else:
                break
        except Exception:
            break
        fields.append((field_num, wire_type, val))
    return fields


# gen_metadata.data 的字段号是逆向出来的,没有官方 schema:
# 1 = 单次生成记录,其中 19=模型名, 4={2:输入(不含缓存), 3:输出, 5:缓存读, 9:思考},
# 9→4→1 = 生成开始时间(秒)。Google 一改编号这里就会静默解出错数,所以下面做了上界校验。
_ANTIGRAVITY_MAX_TOKENS = 100_000_000  # 单次生成的 token 上界,超了就是解析错位
_ANTIGRAVITY_MIN_TS = 1_577_836_800    # 2020-01-01,更早的时间戳必然是错位


def _antigravity_gen_step(record, fallback_ts=None):
    """解一条生成记录 → (model, input, output, cached, thoughts, ts_sec);解不出返回 None。"""
    model = "unknown"
    inp = out = cached = thoughts = 0
    ts_sec = None
    for sfn, swt, sval in _parse_proto_fields(record):
        if sfn == 19 and swt == 2:
            try:
                model = sval.decode("utf-8")
            except UnicodeDecodeError:
                pass
        elif sfn == 4 and swt == 2:
            for tfn, twt, tval in _parse_proto_fields(sval):
                if twt != 0:
                    continue
                if tfn == 2:
                    inp = tval
                elif tfn == 3:
                    out = tval
                elif tfn == 5:
                    cached = tval
                elif tfn == 9:
                    thoughts = tval
        elif sfn == 9 and swt == 2:
            for tfn, twt, tval in _parse_proto_fields(sval):
                if tfn == 4 and twt == 2:
                    for stfn, stwt, stval in _parse_proto_fields(tval):
                        if stfn == 1 and stwt == 0:
                            ts_sec = stval
    # 账本是逐日高水位,虚高数字一旦写进去就永久留着且无法纠正 —— 宁可丢也不能记错。
    if not isinstance(ts_sec, int) or not (_ANTIGRAVITY_MIN_TS <= ts_sec <= 1 << 34):
        ts_sec = fallback_ts
    if not isinstance(ts_sec, int) or not (_ANTIGRAVITY_MIN_TS <= ts_sec <= 1 << 34):
        return None
    if max(inp, out, cached, thoughts) > _ANTIGRAVITY_MAX_TOKENS:
        return None
    if not model or len(model) > 120 or not model.isprintable():
        model = "unknown"
    return model, inp, out, cached, thoughts, ts_sec


def _decode_packed_varints(data):
    values = []
    offset = 0
    while offset < len(data):
        value, offset = _decode_proto_varint(data, offset)
        values.append(value)
    return values


def _antigravity_step_timestamp(metadata):
    """Current Antigravity stores a google.protobuf.Timestamp in steps.metadata field 1."""
    for field_num, wire_type, value in _parse_proto_fields(metadata or b""):
        if field_num != 1 or wire_type != 2:
            continue
        for sub_num, sub_wire, sub_value in _parse_proto_fields(value):
            if sub_num == 1 and sub_wire == 0 \
                    and _ANTIGRAVITY_MIN_TS <= sub_value <= 1 << 34:
                return sub_value
    return None


def _load_antigravity_db(path):
    """从 Antigravity conversations/*.db 的 gen_metadata 表解析逐步 token 用量"""
    events = []
    max_ts = ""
    conn = None
    try:
        conn = sqlite3.connect(_sqlite_ro_uri(path), uri=True, timeout=1)
        rows = conn.execute("SELECT idx, data FROM gen_metadata ORDER BY idx ASC").fetchall()
        try:
            step_rows = conn.execute("SELECT idx, metadata FROM steps").fetchall()
        except sqlite3.Error:
            step_rows = []
    except Exception:
        return None
    finally:
        if conn is not None:
            conn.close()

    step_timestamps = {
        int(step_idx): timestamp
        for step_idx, metadata in step_rows
        if (timestamp := _antigravity_step_timestamp(metadata)) is not None
    }

    for idx, data in rows:
        if not data:
            continue
        fields = _parse_proto_fields(data)
        referenced_steps = []
        for fn, wt, val in fields:
            if fn == 2 and wt == 2:
                try:
                    referenced_steps.extend(_decode_packed_varints(val))
                except ValueError:
                    pass
        fallback_ts = next((step_timestamps.get(step_idx) for step_idx in referenced_steps
                            if step_timestamps.get(step_idx) is not None), None)
        record_index = 0
        for fn, wt, val in fields:
            if fn != 1 or wt != 2:
                continue
            # 逐条兜异常:一行坏数据不该把同一个库里的好数据一起带走。
            try:
                step = _antigravity_gen_step(val, fallback_ts=fallback_ts)
            except Exception:
                step = None
            if step is None:
                continue
            model, inp, out, cached, thoughts, ts_sec = step
            iso_ts = datetime.fromtimestamp(ts_sec, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if iso_ts > max_ts:
                max_ts = iso_ts
            events.append({
                "id": f"{os.path.basename(path)}:{idx}:{record_index}",
                "timestamp": iso_ts,
                "model": model,
                "tokens": {
                    "input": inp + cached,
                    "output": out,
                    "cached": cached,
                    "thoughts": thoughts,
                },
            })
            record_index += 1

    if not events:
        return None
    sid = os.path.basename(path)
    if sid.endswith(".db"):
        sid = sid[:-3]
    return {
        "sid": sid,
        "updated": max_ts,
        "rank": 3,
        "events": events,
    }


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
    if path.endswith(".db"):
        return _load_antigravity_db(path)
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
    ledger_touch("gemini")
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
        # SQLite 的新数据可能全在 -wal 里,主库 mtime/size 一动不动 —— 只看主库会永不刷新。
        signature = (_sqlite_signature(path) if path.endswith(".db")
                     else f"{stat.st_mtime_ns}:{stat.st_size}")
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
    # 会话数只能来自现存日志(被清日志无从归属)
    for dk, day in days.items():
        try:
            d = date.fromisoformat(dk)
        except ValueError:
            continue
        for key in classify_date(d, bounds):
            B[key]["sessions"].update(day.get("sessions", set()))

    for dk, day in ledger_reconcile("gemini", days).items():
        try:
            d = date.fromisoformat(dk)
        except ValueError:
            continue
        for key in classify_date(d, bounds):
            bucket = B[key]
            bucket["in"] += day.get("in", 0); bucket["out"] += day.get("out", 0)
            bucket["cached"] += day.get("cached", 0)
            bucket["thoughts"] += day.get("thoughts", 0); bucket["cost"] += day.get("cost", 0)
            for model, usage in (day.get("models") or {}).items():
                model_usage = bucket["models"].setdefault(
                    model, {"in": 0, "out": 0, "cached": 0,
                            "thoughts": 0, "cost": 0.0})
                for field in ("in", "out", "cached", "thoughts"):
                    model_usage[field] += usage.get(field, 0)
                model_usage["cost"] += usage.get("cost", 0)
    return {"ranges": B, "days": days}


# ---------- Grok Build ----------
# 会话目录提供项目、模型和运行指标；新版 unified.jsonl 额外记录逐次推理 token。
# 旧版 inference_done 没有 token 字段，只用于上下文快照，不能计入总用量。
def _grok_file_signature(paths):
    parts = []
    for path in paths:
        try:
            stat = os.stat(path)
        except OSError:
            continue
        parts.append(f"{path}:{stat.st_mtime_ns}:{stat.st_size}")
    return "|".join(parts)


def _load_grok_session(summary_path, signature, mtime_ns):
    try:
        with open(summary_path, "r", encoding="utf-8", errors="ignore") as fh:
            summary = json.load(fh)
    except Exception:
        return None
    dt = parse_ts(summary.get("updated_at") or summary.get("created_at") or "")
    if dt is None:
        return None
    dt = dt.astimezone()
    session_dir = os.path.dirname(summary_path)

    signals_path = os.path.join(session_dir, "signals.json")
    try:
        with open(signals_path, "r", encoding="utf-8", errors="ignore") as fh:
            signals = json.load(fh)
    except Exception:
        signals = {}

    max_total = 0
    updates_path = os.path.join(session_dir, "updates.jsonl")
    try:
        with open(updates_path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if "totalTokens" not in line:
                    continue
                try:
                    update = json.loads(line)
                except Exception:
                    continue
                total = (((update.get("params") or {}).get("_meta") or {}).get("totalTokens"))
                if isinstance(total, (int, float)) and total > max_total:
                    max_total = int(total)
    except OSError:
        pass

    event_turns = event_tools = event_duration = 0
    event_tool_errors = event_turn_errors = event_cancellations = 0
    events_path = os.path.join(session_dir, "events.jsonl")
    try:
        with open(events_path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                event_type = event.get("type")
                if event_type == "turn_started":
                    event_turns += 1
                elif event_type == "tool_completed":
                    event_tools += 1
                    event_duration += int(event.get("duration_ms") or 0)
                    if event.get("outcome") not in (None, "success"):
                        event_tool_errors += 1
                elif event_type == "turn_ended":
                    if event.get("outcome") == "cancelled":
                        event_cancellations += 1
                    elif event.get("outcome") == "error":
                        event_turn_errors += 1
    except OSError:
        pass

    turns = int(signals.get("turnCount") or event_turns or 0)
    tools = int(signals.get("toolCallCount") or event_tools or 0)
    duration = int(signals.get("sessionDurationSeconds") or 0)
    ctx_used = int(signals.get("contextTokensUsed") or max_total or 0)
    ctx_window = int(signals.get("contextWindowTokens") or 0)
    signal_errors = int(signals.get("errorCount") or 0) + int(signals.get("toolFailureCount") or 0)
    errors = max(signal_errors, event_turn_errors, event_tool_errors)
    cancellations = max(int(signals.get("cancellationCount") or 0), event_cancellations)
    latency_count = int(signals.get("latencySampleCount") or turns or 0)
    group_dir = os.path.dirname(os.path.dirname(summary_path))
    from urllib.parse import unquote
    project = unquote(os.path.basename(group_dir))
    cwd_file = os.path.join(group_dir, ".cwd")
    try:
        with open(cwd_file, "r", encoding="utf-8", errors="ignore") as fh:
            project = fh.read().strip() or project
    except OSError:
        pass
    return {
        "sig": signature,
        "mtime": mtime_ns,
        "date": dt.date().isoformat(),
        "hour": dt.hour,
        "sid": (summary.get("info") or {}).get("id") or summary_path,
        "model": summary.get("current_model_id") or "unknown",
        "project": project if os.path.isabs(project) else "",
        "tokens": ctx_used or max_total,
        "turns": turns,
        "tools": tools,
        "duration": duration,
        "ctx_used": ctx_used,
        "ctx_window": ctx_window,
        "errors": errors,
        "cancellations": cancellations,
        "ttft_sum": int(signals.get("avgTimeToFirstTokenMs") or 0) * latency_count,
        "response_sum": int(signals.get("avgResponseTimeMs") or 0) * latency_count,
        "latency_count": latency_count,
    }


def _grok_usage_record(obj):
    if obj.get("msg") != "shell.turn.inference_done":
        return None
    ctx = obj.get("ctx") or {}
    if not isinstance(ctx, dict):
        return None
    token_keys = ("prompt_tokens", "cached_prompt_tokens", "completion_tokens", "reasoning_tokens")
    if not any(key in ctx for key in token_keys):
        return None
    sid = str(obj.get("sid") or "")
    ts = str(obj.get("ts") or "")
    if not sid or parse_ts(ts) is None:
        return None
    try:
        prompt = max(int(ctx.get("prompt_tokens") or 0), 0)
        cached = max(int(ctx.get("cached_prompt_tokens") or 0), 0)
        completion = max(int(ctx.get("completion_tokens") or 0), 0)
        reasoning = max(int(ctx.get("reasoning_tokens") or 0), 0)
        loop_index = int(ctx.get("loop_index") or 0)
        attempts = int(ctx.get("attempts") or 0)
    except (TypeError, ValueError, OverflowError):
        return None
    cached = min(cached, prompt)
    reasoning = min(reasoning, completion)
    record_id = f"{sid}:{ts}:{loop_index}:{attempts}:{prompt}:{cached}:{completion}:{reasoning}"
    return {"id": record_id, "ts": ts, "sid": sid,
            "in": prompt - cached, "cr": cached,
            "out": completion - reasoning, "reason": reasoning}


def _grok_usage_cost(record, model):
    price_id = _pricing_id(model)
    if not price_id:
        return 0.0
    price = _raw_price(price_id)
    cost = (
        int(record.get("in", 0) or 0) * price["in"]
        + int(record.get("cr", 0) or 0) * price["cache_read"]
        + (int(record.get("out", 0) or 0) + int(record.get("reason", 0) or 0))
        * price["out"]
    ) / 1_000_000
    # Grok 4.6 bills the whole request at double price once prompt tokens reach 200K.
    prompt_tokens = int(record.get("in", 0) or 0) + int(record.get("cr", 0) or 0)
    if price_id == "x-ai/grok-4.6" and prompt_tokens >= 200_000:
        cost *= 2
    return cost


def _load_grok_usage_records(cache):
    old = cache.get("grok_usage", {})
    if not isinstance(old, dict):
        old = {}
    try:
        stat = os.stat(GROK_LOG)
    except OSError:
        if cache.pop("grok_usage", None) is not None:
            cache["_dirty"] = True
        return []

    signature = f"{stat.st_mtime_ns}:{stat.st_size}"
    complete_offset = _codex_complete_offset(GROK_LOG, stat.st_size)
    file_id = f"{stat.st_dev}:{stat.st_ino}"
    if (old.get("sig") == signature
            and int(old.get("parsed_size", 0) or 0) == complete_offset):
        return list(old.get("records") or [])

    append_from = None
    if isinstance(old, dict):
        old_offset = int(old.get("parsed_size", 0) or 0)
        if (old.get("file_id") == file_id and old_offset <= complete_offset
                and old.get("parsed_guard") == _codex_offset_guard(GROK_LOG, old_offset)):
            append_from = old_offset

    cached_records = old.get("records") or []
    if not isinstance(cached_records, list):
        cached_records = []
    records = [record for record in cached_records if isinstance(record, dict)] \
        if append_from is not None else []
    seen = {record.get("id") for record in records if record.get("id")}
    parse_start = append_from or 0
    try:
        with open(GROK_LOG, "rb") as fh:
            fh.seek(parse_start)
            while fh.tell() < complete_offset:
                raw = fh.readline()
                if not raw or fh.tell() > complete_offset:
                    break
                try:
                    obj = json.loads(raw.decode("utf-8", errors="ignore"))
                except Exception:
                    continue
                record = _grok_usage_record(obj)
                if record and record["id"] not in seen:
                    records.append(record)
                    seen.add(record["id"])
    except OSError:
        return records

    updated = {
        "sig": signature,
        "file_id": file_id,
        "parsed_size": complete_offset,
        "parsed_guard": _codex_offset_guard(GROK_LOG, complete_offset),
        "records": records,
    }
    if updated != old:
        cache["grok_usage"] = updated
        cache["_dirty"] = True
    return records


def _grok_usage_days(records, sessions, latest_model):
    days = {}
    for record in records:
        dt = parse_ts(record.get("ts") or "")
        if dt is None:
            continue
        local_dt = dt.astimezone()
        day_key = local_dt.date().isoformat()
        day = days.setdefault(day_key, {
            "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0.0,
            "tokens": 0, "calls": 0, "sessions": set(), "hours": [0] * 24,
            "models": {}, "projects": {},
        })
        sid = record.get("sid") or ""
        meta = sessions.get(sid) or {}
        model = meta.get("model") or latest_model or "grok"
        amount = token_total(record)
        cost = _grok_usage_cost(record, model)
        _add_token_usage(day, record.get("in", 0), record.get("out", 0),
                         record.get("cr", 0), 0, record.get("reason", 0), cost, model)
        day["tokens"] += amount
        day["calls"] += 1
        if sid:
            day["sessions"].add(sid)
        day["hours"][local_dt.hour] += amount

        project = meta.get("project") or ""
        if project:
            project_day = day["projects"].setdefault(
                project, {"tokens": 0, "cost": 0.0, "sessions": set(), "models": {}})
            project_day["tokens"] += amount
            project_day["cost"] += cost
            if sid:
                project_day["sessions"].add(sid)
            project_day["models"][model] = project_day["models"].get(model, 0) + amount
    return days


# ---------- Grok 额度 (默认只读本地日志;实时 API 需显式开启) ----------
# 本地: ~/.grok/logs/unified.jsonl 中 `billing: fetched credits config`
# 可选: GET https://cli-chat-proxy.grok.com/v1/billing?format=credits
# 开关: ~/.tokei/config.json 的 grok_live_quota_enabled, 或 TOKEI_GROK_LIVE_QUOTA=1
_GROK_QUOTA_TTL = 30
_GROK_QUOTA_FALLBACK_TTL = 300
_GROK_QUOTA_LOG_SCAN_BYTES = 2 * 1024 * 1024
_GROK_BILLING_MAX_RESPONSE_BYTES = 1024 * 1024
_GROK_BILLING_MSG = "billing: fetched credits config"
_GROK_LIVE_BILLING_URL = "https://cli-chat-proxy.grok.com/v1/billing?format=credits"


def _tokei_config():
    cfg = _load_json(os.path.join(_USER_DIR, "config.json"), {})
    return cfg if isinstance(cfg, dict) else {}


def _grok_live_quota_enabled():
    """实时额度默认关闭;仅用户显式开启或环境变量强制时才联网。"""
    env = os.environ.get("TOKEI_GROK_LIVE_QUOTA")
    if env == "0":
        return False
    if env == "1":
        return True
    return bool(_tokei_config().get("grok_live_quota_enabled"))


def _grok_auth_token():
    auth = _load_json(GROK_AUTH, {})
    if not isinstance(auth, dict):
        return None
    for entry in auth.values():
        if not isinstance(entry, dict):
            continue
        token = entry.get("key") or entry.get("access_token")
        if isinstance(token, str) and token.strip():
            return token.strip()
    return None


def _normalize_grok_billing(config, *, plan=None, source=None, updated=None,
                            now_epoch=None):
    if not isinstance(config, dict):
        return None
    period = config.get("currentPeriod") if isinstance(config.get("currentPeriod"), dict) else {}
    end = period.get("end") or config.get("billingPeriodEnd")
    reset = _iso_to_epoch(end) if end else None
    pct_raw = config.get("creditUsagePercent")
    if "creditUsagePercent" not in config:
        # Grok 的 protobuf JSON 会省略 0 值；仅完整的统一账单周期可安全视为 0% 已用。
        has_period = bool(period.get("start") and reset is not None)
        if config.get("isUnifiedBillingUser") is not True or not has_period:
            return None
        pct_raw = 0.0
    elif pct_raw is None:
        return None
    try:
        pct = float(pct_raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(pct):
        return None
    pct = min(100.0, max(0.0, pct))
    products = []
    for item in config.get("productUsage") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("product") or item.get("name")
        if not name:
            continue
        usage_pct = item.get("usagePercent")
        try:
            normalized_pct = float(usage_pct) if usage_pct is not None else None
            if normalized_pct is not None:
                normalized_pct = (min(100.0, max(0.0, normalized_pct))
                                  if math.isfinite(normalized_pct) else None)
            products.append({
                "name": str(name),
                "pct": normalized_pct,
            })
        except (TypeError, ValueError):
            products.append({"name": str(name), "pct": None})
    now = int(now_epoch if now_epoch is not None else datetime.now().timestamp())
    stale = bool(reset is not None and reset <= now)
    if stale:
        # 周期已过重置点,本地快照不再代表当前额度。
        pct = 0.0
        for item in products:
            if item.get("pct") is not None:
                item["pct"] = 0.0
    period_type = period.get("type") or ""
    if "WEEKLY" in str(period_type).upper():
        window = "week"
    elif "MONTH" in str(period_type).upper():
        window = "month"
    else:
        window = "week"
    plan_name = plan
    if not plan_name:
        plan_name = config.get("subscriptionTier") or config.get("plan")
    return {
        "pct": pct,
        "reset": None if stale else reset,
        "plan": plan_name,
        "products": products,
        "window": window,
        "source": source,
        "updated": int(updated) if updated is not None else now,
        "stale": stale,
    }


def _scan_grok_billing_from_log(path=None, max_bytes=_GROK_QUOTA_LOG_SCAN_BYTES):
    """从 unified.jsonl 尾部读取最近一次 billing: fetched credits config。"""
    log_path = path or GROK_LOG
    try:
        size = os.path.getsize(log_path)
    except OSError:
        return None
    if size <= 0:
        return None
    start = max(0, size - max_bytes)
    latest = None
    latest_ts = None
    try:
        with open(log_path, "rb") as fh:
            fh.seek(start)
            if start:
                fh.readline()  # 丢掉半行
            for raw in fh:
                if _GROK_BILLING_MSG.encode("utf-8") not in raw:
                    continue
                try:
                    obj = json.loads(raw.decode("utf-8", errors="ignore"))
                except Exception:
                    continue
                if obj.get("msg") != _GROK_BILLING_MSG:
                    continue
                ctx = obj.get("ctx") or {}
                if not isinstance(ctx, dict):
                    continue
                config = ctx.get("config")
                if not isinstance(config, dict):
                    continue
                ts = obj.get("ts")
                if latest_ts is None or (isinstance(ts, str) and ts >= latest_ts):
                    latest_ts = ts if isinstance(ts, str) else latest_ts
                    latest = {
                        "config": config,
                        "plan": ctx.get("subscriptionTier") or ctx.get("plan"),
                        "ts": ts,
                    }
    except OSError:
        return None
    if not latest:
        return None
    updated = _iso_to_epoch(latest.get("ts"))
    return _normalize_grok_billing(
        latest["config"], plan=latest.get("plan"), source="log", updated=updated)


def _cached_grok_quota(max_age):
    cached = _load_json(GROK_QUOTA_CACHE, {})
    if not isinstance(cached, dict):
        return None
    quota = cached.get("quota")
    fetched_at = cached.get("fetched_at")
    if not isinstance(quota, dict) or fetched_at is None:
        return None
    try:
        age = datetime.now().timestamp() - float(fetched_at)
    except (TypeError, ValueError):
        return None
    if age > max_age:
        return None
    out = dict(quota)
    out.setdefault("source", cached.get("source") or out.get("source") or "cache")
    return out


def _save_grok_quota_cache(quota):
    if not isinstance(quota, dict) or quota.get("pct") is None:
        return
    try:
        os.makedirs(os.path.dirname(GROK_QUOTA_CACHE) or _USER_DIR, exist_ok=True)
        _atomic_write_json(GROK_QUOTA_CACHE, {
            "fetched_at": datetime.now().timestamp(),
            "source": quota.get("source"),
            "quota": quota,
        })
        try:
            os.chmod(GROK_QUOTA_CACHE, 0o600)
        except OSError:
            pass
    except Exception:
        pass


def fetch_grok_live_quota():
    """仅在用户开启时请求 Grok billing API;失败回退到短缓存。"""
    if not _grok_live_quota_enabled():
        return None
    cached = _cached_grok_quota(_GROK_QUOTA_TTL)
    if cached and cached.get("source") == "live":
        return cached
    token = _grok_auth_token()
    if not token:
        return _cached_grok_quota(_GROK_QUOTA_FALLBACK_TTL)
    try:
        import urllib.request
        req = urllib.request.Request(
            _GROK_LIVE_BILLING_URL,
            headers={
                "Accept": "application/json",
                "User-Agent": "Tokei",
            },
        )
        # urllib copies regular headers to redirects. Keep the credential in the
        # initial-request-only header set and reject any redirected response.
        req.add_unredirected_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=3) as res:
            final_url = res.geturl() if hasattr(res, "geturl") else _GROK_LIVE_BILLING_URL
            if final_url != _GROK_LIVE_BILLING_URL:
                return _cached_grok_quota(_GROK_QUOTA_FALLBACK_TTL)
            payload = res.read(_GROK_BILLING_MAX_RESPONSE_BYTES + 1)
            if len(payload) > _GROK_BILLING_MAX_RESPONSE_BYTES:
                return _cached_grok_quota(_GROK_QUOTA_FALLBACK_TTL)
            data = json.loads(payload)
        config = data.get("config") if isinstance(data, dict) else None
        plan = None
        if isinstance(data, dict):
            plan = data.get("subscriptionTier") or data.get("plan")
        quota = _normalize_grok_billing(config, plan=plan, source="live")
        if not quota:
            return _cached_grok_quota(_GROK_QUOTA_FALLBACK_TTL)
        _save_grok_quota_cache(quota)
        return quota
    except Exception:
        return _cached_grok_quota(_GROK_QUOTA_FALLBACK_TTL)


def scan_grok_quota():
    """默认优先本地日志;仅显式开启时才走实时 API。"""
    log_quota = _scan_grok_billing_from_log()
    if log_quota and not log_quota.get("stale"):
        _save_grok_quota_cache(log_quota)

    if _grok_live_quota_enabled():
        live = fetch_grok_live_quota()
        if live and live.get("pct") is not None:
            return live

    if log_quota and log_quota.get("pct") is not None:
        return log_quota

    cached = _cached_grok_quota(_GROK_QUOTA_FALLBACK_TTL * 12)  # 本地缓存放宽到约 1 小时
    if cached and cached.get("pct") is not None:
        out = dict(cached)
        out["source"] = "cache"
        # 过期周期仍标 stale
        reset = out.get("reset")
        now = int(datetime.now().timestamp())
        if reset is not None and int(reset) <= now:
            out["stale"] = True
            out["pct"] = 0.0
            out["reset"] = None
        return out
    return {}


# ---------- 千问办公额度 (官方桌面端本机 MCP；需显式开启) ----------
# 千问办公负责登录、token 刷新和服务端额度请求。Tokei 只调用它监听在
# 127.0.0.1 的只读 qwenwork.usage 资源，不读取 auth-v2.dat 或浏览器 Cookie。
_QWENWORK_QUOTA_TTL = 300
_QWENWORK_QUOTA_FALLBACK_TTL = 3600
_QWENWORK_MCP_TIMEOUT = 3
_QWENWORK_MCP_MAX_CONFIG_BYTES = 16 * 1024
_QWENWORK_MCP_MAX_RESPONSE_BYTES = 1024 * 1024
_QWENWORK_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _qwenwork_quota_enabled():
    """默认关闭；开启后千问办公可能通过自己的登录态访问官方额度接口。"""
    env = os.environ.get("TOKEI_QWENWORK_QUOTA")
    if env == "0":
        return False
    if env == "1":
        return True
    return bool(_tokei_config().get("qwenwork_quota_enabled"))


def _read_qwenwork_mcp_config(path=None):
    """读取千问办公本机 MCP capability，拒绝宽权限文件和非 loopback URL。"""
    import stat
    from urllib.parse import urlsplit

    config_path = path or QWENWORK_MCP_CONFIG
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = None
    try:
        fd = os.open(config_path, flags)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode)
                or info.st_size <= 0
                or info.st_size > _QWENWORK_MCP_MAX_CONFIG_BYTES):
            return None
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            return None
        # x-api-key 可调用适配器的其他工具；只信任当前用户私有的 0600 风格文件。
        if stat.S_IMODE(info.st_mode) & 0o077:
            return None
        with os.fdopen(fd, "r", encoding="utf-8") as fh:
            fd = None
            config = json.load(fh)
    except Exception:
        return None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    if not isinstance(config, dict):
        return None
    url = config.get("url")
    token = config.get("token")
    if not isinstance(url, str) or not isinstance(token, str):
        return None
    try:
        parsed = urlsplit(url.strip())
        port = parsed.port
    except ValueError:
        return None
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.username is not None or parsed.password is not None
            or port is None or not 1 <= port <= 65535
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        return None
    token = token.strip()
    if re.fullmatch(r"[0-9a-fA-F]{64}", token) is None:
        return None
    mtime_ns = getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000))
    # .status.json 内容含账号资料，Tokei 不读取；仅把其文件 generation 纳入
    # cache marker，使登录、退出或切换账号后的快照不会沿用旧额度。
    status_marker = _qwenwork_private_file_marker(QWENWORK_STATUS)
    marker = f"{info.st_dev}:{info.st_ino}:{mtime_ns}:{port}:{status_marker}"
    return {"port": port, "token": token, "marker": marker}


def _qwenwork_private_file_marker(path):
    """只读取私有普通文件的元数据 generation，不读取文件内容。"""
    import stat

    try:
        info = os.lstat(path)
    except OSError:
        return "missing"
    if (not stat.S_ISREG(info.st_mode)
            or (hasattr(os, "getuid") and info.st_uid != os.getuid())
            or stat.S_IMODE(info.st_mode) & 0o077):
        return "untrusted"
    mtime_ns = getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000))
    return f"{info.st_dev}:{info.st_ino}:{mtime_ns}:{info.st_size}"


def _qwenwork_mcp_rpc(config):
    """固定调用 qwenwork.usage；http.client 不使用代理，也不会跟随重定向。"""
    import http.client

    request_body = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "qw_query",
            "arguments": {"key": "qwenwork.usage"},
        },
    }, separators=(",", ":")).encode("utf-8")
    connection = http.client.HTTPConnection(
        "127.0.0.1", config["port"], timeout=_QWENWORK_MCP_TIMEOUT)
    try:
        connection.request("POST", "/", body=request_body, headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "User-Agent": "Tokei",
            "x-api-key": config["token"],
        })
        response = connection.getresponse()
        if response.status != 200:
            return None
        payload = response.read(_QWENWORK_MCP_MAX_RESPONSE_BYTES + 1)
        if len(payload) > _QWENWORK_MCP_MAX_RESPONSE_BYTES:
            return None
        text = payload.decode("utf-8")
        content_type = (response.getheader("Content-Type") or "").lower()
        if "text/event-stream" in content_type:
            for line in text.splitlines():
                if line.startswith("data:"):
                    candidate = line[5:].strip()
                    if candidate:
                        return json.loads(candidate)
            return None
        return json.loads(text)
    except Exception:
        return None
    finally:
        connection.close()


def _qwenwork_mcp_data(payload):
    if not isinstance(payload, dict):
        return None
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    envelope = result.get("structuredContent")
    if not isinstance(envelope, dict):
        # Older MCP clients may expose the same JSON envelope as text content.
        for item in result.get("content") or []:
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                continue
            try:
                candidate = json.loads(item["text"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(candidate, dict):
                envelope = candidate
                break
    if not isinstance(envelope, dict) or envelope.get("ok") is False:
        return None
    if envelope.get("key") not in (None, "qwenwork.usage"):
        return None
    data = envelope.get("data")
    if isinstance(data, dict):
        return data
    # Be tolerant if a future adapter returns the resource body directly.
    if any(key in envelope for key in ("available", "segments", "planCredits")):
        return envelope
    return None


def _qwenwork_number(value, *, percent=False):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    upper = 100.0 if percent else 1_000_000_000_000_000.0
    return min(upper, max(0.0, number))


def _qwenwork_epoch(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return None
        epoch = float(value)
        if epoch > 1_000_000_000_000:
            epoch /= 1000
        return int(epoch) if 0 < epoch < 253_402_300_800 else None
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return _qwenwork_epoch(float(stripped))
        except ValueError:
            return _iso_to_epoch(stripped)
    return None


def _qwenwork_safe_name(value, default):
    value = str(value or "").strip()
    return value if _QWENWORK_SAFE_NAME_RE.fullmatch(value) else default


def _normalize_qwenwork_segment(item, index, *, default_id=None, default_kind=None):
    if not isinstance(item, dict):
        return None
    segment_id = _qwenwork_safe_name(
        item.get("id"), default_id or f"segment_{index + 1}")
    kind = _qwenwork_safe_name(
        item.get("kind"), default_kind or segment_id)
    unit = item.get("unit")
    unit = _qwenwork_safe_name(unit, "") if unit is not None else None
    if not unit:
        unit = None
    total = _qwenwork_number(item.get("total"))
    percentage_used = _qwenwork_number(
        item.get("percentageUsed", item.get("percentage")), percent=True)
    # total=0 means the denominator is unknown in current QwenWork responses.
    # Keep the absolute balance, but do not turn percentageUsed=0 into a fake 100% remaining bar.
    if total is None or total <= 0:
        percentage_used = None
    out = {
        "id": segment_id,
        "kind": kind,
        "total": total,
        "used": _qwenwork_number(item.get("used")),
        "remaining": _qwenwork_number(item.get("remaining")),
        "percentage_used": percentage_used,
        "unit": unit,
        "renews_at": _qwenwork_epoch(item.get("renewsAt", item.get("renews_at"))),
        "expires_at": _qwenwork_epoch(item.get(
            "expiresAt", item.get("planExpiration", item.get("expires_at")))),
    }
    if all(out.get(key) is None for key in ("total", "used", "remaining", "percentage_used")):
        return None
    return out


def _normalize_qwenwork_shared(item):
    if not isinstance(item, dict):
        return None
    unit = item.get("unit")
    unit = _qwenwork_safe_name(unit, "") if unit is not None else None
    if not unit:
        unit = None
    total = _qwenwork_number(
        item.get("total", item.get("cap", item.get("allowance"))))
    percentage_used = _qwenwork_number(
        item.get("percentageUsed", item.get("percentage")), percent=True)
    if total is None or total <= 0:
        percentage_used = None
    out = {
        "total": total,
        "used": _qwenwork_number(item.get("used")),
        "remaining": _qwenwork_number(item.get("remaining")),
        "percentage_used": percentage_used,
        "unit": unit,
        "expires_at": _qwenwork_epoch(item.get("expiresAt", item.get("expires_at"))),
    }
    numeric_keys = ("total", "used", "remaining", "percentage_used", "expires_at")
    return out if any(out.get(key) is not None for key in numeric_keys) else None


def _normalize_qwenwork_usage(data, *, updated=None):
    if not isinstance(data, dict) or data.get("available") is False:
        return None

    segments = []
    raw_segments = data.get("segments")
    if isinstance(raw_segments, list):
        for index, item in enumerate(raw_segments[:8]):
            segment = _normalize_qwenwork_segment(item, index)
            if segment:
                segments.append(segment)

    # planCredits/addOnCredits are mirrors of segments, never sum both shapes.
    if not segments:
        aliases = (
            ("planCredits", "plan", "plan_credits"),
            ("addOnCredits", "add_on", "add_on_credits"),
        )
        for key, segment_id, kind in aliases:
            segment = _normalize_qwenwork_segment(
                data.get(key), len(segments), default_id=segment_id, default_kind=kind)
            if segment:
                segments.append(segment)

    remaining_values = []
    for segment in segments:
        unit = (segment.get("unit") or "").lower()
        kind = segment.get("kind") or ""
        is_credit = (unit in ("credit", "credits")) if unit else "credit" in kind.lower()
        if segment.get("remaining") is not None and is_credit:
            remaining_values.append(segment["remaining"])
    remaining = sum(remaining_values) if remaining_values else None
    if remaining is None:
        remaining = _qwenwork_number(data.get("remaining", data.get("balance")))

    remaining_pct = _qwenwork_number(data.get("aggregateRemainingPercent"), percent=True)
    shared_source = data.get("sharedResourcePackage")
    if not isinstance(shared_source, dict):
        shared_source = data.get("sharedAddOnCredits")
    shared = _normalize_qwenwork_shared(shared_source)
    if remaining is None and remaining_pct is None and not segments and shared is None:
        return None
    return {
        "available": True,
        "remaining": remaining,
        "remaining_pct": remaining_pct,
        "exceeded": data.get("isQuotaExceeded") is True,
        "is_team": data.get("isTeamPlan") is True,
        "expires_at": _qwenwork_epoch(data.get("expiresAt")),
        "plan_expiration": _qwenwork_epoch(data.get("planExpiration")),
        "segments": segments,
        "shared": shared,
        "source": "mcp",
        "updated": int(updated if updated is not None else datetime.now().timestamp()),
        "stale": False,
    }


def _cached_qwenwork_quota(config_marker, max_age, *, stale=False):
    cached = _load_json(QWENWORK_QUOTA_CACHE, {})
    if not isinstance(cached, dict) or cached.get("config_marker") != config_marker:
        return None
    quota = cached.get("quota")
    fetched_at = cached.get("fetched_at")
    if not isinstance(quota, dict) or fetched_at is None:
        return None
    try:
        age = datetime.now().timestamp() - float(fetched_at)
    except (TypeError, ValueError):
        return None
    if age < -60 or age > max_age:
        return None
    out = dict(quota)
    if stale:
        out["source"] = "cache"
        out["stale"] = True
    return out


def _save_qwenwork_quota_cache(quota, config_marker):
    if not isinstance(quota, dict) or not quota.get("available"):
        return
    try:
        _atomic_write_json(QWENWORK_QUOTA_CACHE, {
            "fetched_at": datetime.now().timestamp(),
            "config_marker": config_marker,
            "quota": quota,
        })
        os.chmod(QWENWORK_QUOTA_CACHE, 0o600)
    except Exception:
        pass


def _clear_qwenwork_quota_cache():
    try:
        os.remove(QWENWORK_QUOTA_CACHE)
    except OSError:
        pass


def scan_qwenwork_quota():
    """读取千问办公官方本机额度资源；不可用时静默降级，不自动启动客户端。"""
    if not _qwenwork_quota_enabled():
        return {}
    config = _read_qwenwork_mcp_config()
    if not config:
        return {}
    cached = _cached_qwenwork_quota(config["marker"], _QWENWORK_QUOTA_TTL)
    if cached:
        return cached

    latest_config = config
    for attempt in range(2):
        if attempt:
            latest_config = _read_qwenwork_mcp_config()
            if not latest_config:
                break
        payload = _qwenwork_mcp_rpc(latest_config)
        data = _qwenwork_mcp_data(payload)
        if isinstance(data, dict) and data.get("available") is False:
            _clear_qwenwork_quota_cache()
            return {}
        quota = _normalize_qwenwork_usage(data)
        if quota:
            _save_qwenwork_quota_cache(quota, latest_config["marker"])
            return quota

    fallback = _cached_qwenwork_quota(
        latest_config["marker"], _QWENWORK_QUOTA_FALLBACK_TTL, stale=True)
    return fallback or {}


# ---------- CodexBar-compatible provider quotas ----------
# Remote providers are opt-in. Antigravity is the exception: it only probes an
# already-running loopback language server and never starts the app/CLI.
_PROVIDER_QUOTA_TTL = 300
_PROVIDER_QUOTA_FALLBACK_TTL = 3600
_PROVIDER_QUOTA_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_PROVIDER_QUOTA_CACHE_LOCK = threading.Lock()
_PROVIDER_QUOTA_ENV = {
    "cursor": "TOKEI_CURSOR_QUOTA",
    "grok_bot": "TOKEI_GROK_BOT_QUOTA",
    "zed": "TOKEI_ZED_QUOTA",
    "sub2api": "TOKEI_SUB2API_QUOTA",
    "zai": "TOKEI_ZAI_QUOTA",
    "antigravity": "TOKEI_ANTIGRAVITY_QUOTA",
    "devin": "TOKEI_DEVIN_QUOTA",
}


def _provider_quota_enabled(provider):
    env_key = _PROVIDER_QUOTA_ENV.get(provider)
    env = os.environ.get(env_key) if env_key else None
    if env == "0":
        return False
    if env == "1":
        return True
    default = provider in ("antigravity", "devin")
    return bool(_tokei_config().get(f"{provider}_quota_enabled", default))


def _provider_config_string(env_key, config_key):
    value = os.environ.get(env_key)
    if not isinstance(value, str) or not value.strip():
        value = _tokei_config().get(config_key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _provider_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except (TypeError, ValueError):
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _provider_integer(value):
    number = _provider_number(value)
    return int(number) if number is not None and number.is_integer() else None


def _provider_percent(value):
    number = _provider_number(value)
    return round(max(0.0, min(100.0, number)), 6) if number is not None else None


def _provider_epoch(value):
    number = _provider_number(value)
    if number is not None:
        if number > 100_000_000_000:
            number /= 1000.0
        return int(number) if number > 0 else None
    parsed = parse_ts(value) if isinstance(value, str) else None
    return int(parsed.timestamp()) if parsed else None


def _provider_money(value, unit="USD"):
    number = _provider_number(value)
    if number is None:
        return None
    if str(unit or "USD").upper() == "USD":
        return f"${number:,.2f}"
    return f"{number:,.2f} {unit}"


_PROVIDER_USAGE_FIELDS = ("in", "out", "cr", "cw", "reason")


def _provider_usage_int(value):
    number = _provider_integer(value)
    return number if number is not None and number >= 0 else 0


def _provider_usage_from_days(days, *, bounds=None, limited_coverage=None):
    bounds = bounds or range_bounds()
    buckets = {
        key: {"tokens": 0, "in": 0, "out": 0, "cr": 0, "cw": 0,
              "reason": 0, "cost": 0.0, "requests": 0, "models": {}}
        for key in RANGE_KEYS
    }
    clean_days = days if isinstance(days, dict) else {}
    for day_key, day in clean_days.items():
        if not isinstance(day, dict):
            continue
        try:
            local_day = date.fromisoformat(str(day_key)[:10])
        except ValueError:
            continue
        components = {field: _provider_usage_int(day.get(field))
                      for field in _PROVIDER_USAGE_FIELDS}
        total = _provider_usage_int(day.get("tokens")) or sum(components.values())
        cost = _provider_number(day.get("cost")) or 0.0
        cost = cost if cost >= 0 else 0.0
        requests = _provider_usage_int(day.get("requests"))
        models = day.get("models") if isinstance(day.get("models"), dict) else {}
        for range_key in classify_date(local_day, bounds):
            bucket = buckets[range_key]
            bucket["tokens"] += total
            bucket["cost"] += cost
            bucket["requests"] += requests
            for field, value in components.items():
                bucket[field] += value
            for raw_name, raw_usage in models.items():
                if not isinstance(raw_usage, dict):
                    continue
                model = bucket["models"].setdefault(
                    str(raw_name or "unknown"),
                    {"tokens": 0, "in": 0, "out": 0, "cr": 0, "cw": 0,
                     "reason": 0, "cost": 0.0})
                model_components = {field: _provider_usage_int(raw_usage.get(field))
                                    for field in _PROVIDER_USAGE_FIELDS}
                model["tokens"] += _provider_usage_int(raw_usage.get("tokens")) \
                    or sum(model_components.values())
                for field, value in model_components.items():
                    model[field] += value
                model_cost = _provider_number(raw_usage.get("cost")) or 0.0
                if model_cost >= 0:
                    model["cost"] += model_cost

    ranges = {}
    for range_key, bucket in buckets.items():
        formatted = {}
        for raw_name, usage in bucket.pop("models").items():
            display_name = nice_model(raw_name)
            model = formatted.setdefault(
                display_name,
                {"name": display_name, "tokens": 0, "in": 0, "out": 0,
                 "cr": 0, "cw": 0, "reason": 0, "cost": 0.0})
            for field in ("tokens",) + _PROVIDER_USAGE_FIELDS:
                model[field] += usage[field]
            model["cost"] += usage["cost"]
        row = dict(bucket)
        input_total = row["in"] + row["cr"] + row["cw"]
        row["hit"] = row["cr"] / input_total * 100 if input_total else 0.0
        row["cost"] = round(row["cost"], 6)
        row["models"] = sorted(
            formatted.values(), key=lambda item: (-item["tokens"], item["name"]))
        for model in row["models"]:
            model["cost"] = round(model["cost"], 6)
        if limited_coverage and range_key in {"year", "all"}:
            row["coverage"] = limited_coverage
        ranges[range_key] = row
    return {"ranges": ranges, "days": clean_days}


def _provider_window(window_id, title, used_pct=None, reset=None, window_minutes=None,
                     detail=None, usage_known=True):
    return {
        "id": str(window_id),
        "title": str(title),
        "used_pct": _provider_percent(used_pct),
        "reset": _provider_epoch(reset),
        "window_minutes": int(window_minutes) if isinstance(window_minutes, (int, float))
        and window_minutes > 0 else None,
        "detail": str(detail) if detail else None,
        "usage_known": bool(usage_known),
    }


def _provider_credential_marker(provider, *parts):
    material = "\0".join(str(part or "") for part in (provider,) + parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _cached_provider_quota(provider, marker, max_age, now_epoch=None, stale=False):
    with _PROVIDER_QUOTA_CACHE_LOCK:
        root = _load_json(PROVIDER_QUOTA_CACHE, {})
    entry = (root.get("providers") or {}).get(provider) if isinstance(root, dict) else None
    if not isinstance(entry, dict) or entry.get("marker") != marker:
        return None
    fetched_at = _provider_number(entry.get("fetched_at"))
    quota = entry.get("quota")
    now_epoch = int(now_epoch if now_epoch is not None else datetime.now().timestamp())
    if fetched_at is None or not isinstance(quota, dict):
        return None
    age = now_epoch - int(fetched_at)
    if age < -300 or age > max_age:
        return None
    out = json.loads(json.dumps(quota))
    if stale:
        out["stale"] = True
        out["source"] = "cache"
    return out


def _latest_cached_provider_quota(provider, max_age=None, now_epoch=None, stale=False):
    """Return the latest aggregate, optionally enforcing a maximum age."""
    with _PROVIDER_QUOTA_CACHE_LOCK:
        root = _load_json(PROVIDER_QUOTA_CACHE, {})
    entry = (root.get("providers") or {}).get(provider) if isinstance(root, dict) else None
    if not isinstance(entry, dict):
        return None
    fetched_at = _provider_number(entry.get("fetched_at"))
    quota = entry.get("quota")
    now_epoch = int(now_epoch if now_epoch is not None else datetime.now().timestamp())
    if fetched_at is None or not isinstance(quota, dict):
        return None
    age = now_epoch - int(fetched_at)
    if age < -300 or (max_age is not None and age > max_age):
        return None
    out = json.loads(json.dumps(quota))
    if stale:
        out["stale"] = True
        out["source"] = "cache"
    return out


def _save_provider_quota_cache(provider, marker, quota, fetched_at=None):
    usage = quota.get("usage") if isinstance(quota, dict) else None
    usage_ranges = usage.get("ranges") if isinstance(usage, dict) else None
    has_usage = isinstance(usage_ranges, dict) and any(
        isinstance(row, dict) and (
            _provider_usage_int(row.get("tokens")) > 0
            or _provider_usage_int(row.get("requests")) > 0
        )
        for row in usage_ranges.values()
    )
    if not isinstance(quota, dict) or (not quota.get("available") and not has_usage):
        return
    with _PROVIDER_QUOTA_CACHE_LOCK:
        root = _load_json(PROVIDER_QUOTA_CACHE, {})
        if not isinstance(root, dict):
            root = {}
        providers = root.get("providers")
        if not isinstance(providers, dict):
            providers = {}
        providers[provider] = {
            "marker": marker,
            "fetched_at": int(fetched_at if fetched_at is not None else datetime.now().timestamp()),
            "quota": quota,
        }
        root = {"version": 1, "providers": providers}
        try:
            _atomic_write_json(PROVIDER_QUOTA_CACHE, root)
            os.chmod(PROVIDER_QUOTA_CACHE, 0o600)
        except OSError:
            pass


def _provider_quota_recent_attempt_result(provider, marker, max_age, now_epoch=None):
    with _PROVIDER_QUOTA_CACHE_LOCK:
        root = _load_json(PROVIDER_QUOTA_CACHE, {})
    entry = (root.get("providers") or {}).get(provider) if isinstance(root, dict) else None
    if not isinstance(entry, dict) or entry.get("marker") != marker:
        return None
    attempted_at = _provider_number(entry.get("attempted_at"))
    if attempted_at is None:
        return None
    now_epoch = int(now_epoch if now_epoch is not None else datetime.now().timestamp())
    age = now_epoch - int(attempted_at)
    if not -300 <= age <= max_age:
        return None
    result = entry.get("attempt_result")
    return result if result in {"empty", "failed"} else "failed"


def _save_provider_quota_attempt(provider, marker, attempted_at=None, result="failed"):
    with _PROVIDER_QUOTA_CACHE_LOCK:
        root = _load_json(PROVIDER_QUOTA_CACHE, {})
        if not isinstance(root, dict):
            root = {}
        providers = root.get("providers")
        if not isinstance(providers, dict):
            providers = {}
        previous = providers.get(provider)
        entry = dict(previous) if isinstance(previous, dict) \
            and previous.get("marker") == marker else {"marker": marker}
        entry["attempted_at"] = int(
            attempted_at if attempted_at is not None else datetime.now().timestamp())
        entry["attempt_result"] = result if result in {"empty", "failed"} else "failed"
        providers[provider] = entry
        root = {"version": 1, "providers": providers}
        try:
            _atomic_write_json(PROVIDER_QUOTA_CACHE, root)
            os.chmod(PROVIDER_QUOTA_CACHE, 0o600)
        except OSError:
            pass


def _provider_json_request(url, *, headers=None, method="GET", body=None, timeout=5,
                           max_bytes=_PROVIDER_QUOTA_MAX_RESPONSE_BYTES,
                           allow_insecure_loopback_tls=False):
    import ssl
    import urllib.error
    import urllib.request
    from urllib.parse import urlsplit

    raw_body = None
    request_headers = dict(headers or {})
    if body is not None:
        raw_body = json.dumps(body, separators=(",", ":")).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request_headers.setdefault("Accept", "application/json")
    request = urllib.request.Request(
        url, data=raw_body, headers=request_headers, method=method)
    context = None
    parsed = urlsplit(url)
    if allow_insecure_loopback_tls and parsed.scheme == "https" \
            and parsed.hostname in {"127.0.0.1", "::1", "localhost"}:
        context = ssl._create_unverified_context()
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, response_headers, new_url):
            return None

    handlers = [NoRedirect()]
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(request, timeout=timeout) as response:
            data = response.read(max_bytes + 1)
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        raise RuntimeError(f"HTTP {status}") from error
    if len(data) > max_bytes:
        raise ValueError("provider response too large")
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("provider response was not valid JSON") from error


# ----- Cursor -----

_CURSOR_USAGE_PAGE_SIZE = 1000
_CURSOR_USAGE_MAX_PAGES = 200


def _cursor_app_auth_paths():
    return _path_candidates(
        "TOKEI_CURSOR_AUTH_DB",
        os.path.join(HOME, "Library", "Application Support", "Cursor",
                     "User", "globalStorage", "state.vscdb"),
        os.path.join(HOME, ".config", "Cursor", "User",
                     "globalStorage", "state.vscdb"))


def _cursor_app_session(path=None, now_epoch=None):
    db_path = path or _first_existing_file(_cursor_app_auth_paths())
    if not db_path or not os.path.isfile(db_path):
        return None
    try:
        connection = sqlite3.connect(_sqlite_ro_uri(db_path), uri=True, timeout=0.25)
        row = connection.execute(
            "SELECT value FROM ItemTable WHERE key = ? LIMIT 1",
            ("cursorAuth/accessToken",)).fetchone()
        connection.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    token = row[0]
    if isinstance(token, bytes):
        token = token.decode("utf-8", "ignore")
    if not isinstance(token, str) or not token.strip():
        return None
    token = token.strip()
    claims = _decode_jwt_claims(token) or {}
    subject = claims.get("sub") if isinstance(claims.get("sub"), str) else None
    user_id = subject.rsplit("|", 1)[-1] if subject else None
    if not user_id or not re.fullmatch(r"[A-Za-z0-9._-]+", user_id):
        return None
    expiration = _provider_number(claims.get("exp"))
    now_epoch = int(now_epoch if now_epoch is not None else datetime.now().timestamp())
    if expiration is None or expiration <= now_epoch + 60:
        return None
    email = claims.get("email") if isinstance(claims.get("email"), str) else None
    return {
        "cookie": f"WorkosCursorSessionToken={user_id}%3A%3A{token}",
        "account": email.strip() if email and email.strip() else subject,
        "subject": subject,
        "user_id": user_id,
        "marker": _provider_credential_marker("cursor", subject, token),
    }


def _cursor_cookie_session(cookie):
    if not isinstance(cookie, str) or not cookie.strip():
        return None
    from urllib.parse import unquote

    account = subject = user_id = None
    for component in cookie.split(";"):
        name, separator, value = component.strip().partition("=")
        if separator and name == "WorkosCursorSessionToken":
            token = unquote(value).split("::")[-1]
            claims = _decode_jwt_claims(token) or {}
            subject = claims.get("sub") if isinstance(claims.get("sub"), str) else None
            user_id = subject.rsplit("|", 1)[-1] if subject else None
            email = claims.get("email")
            account = email.strip() if isinstance(email, str) and email.strip() else subject
            break
    return {
        "cookie": cookie.strip(),
        "account": account,
        "subject": subject,
        "user_id": user_id,
        "marker": _provider_credential_marker("cursor", cookie.strip()),
    }


def _cursor_session():
    manual = _provider_config_string("TOKEI_CURSOR_COOKIE", "cursor_cookie")
    return _cursor_cookie_session(manual) if manual else _cursor_app_session()


def _cursor_plan_name(raw):
    names = {
        "enterprise": "Enterprise", "express": "Start", "free": "Free",
        "free_trial": "Pro Trial", "hobby": "Hobby", "pro": "Pro",
        "pro_student": "Pro", "pro_plus": "Pro+", "team": "Team",
        "ultra": "Ultra",
    }
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = names.get(raw.strip().lower(), raw.strip())
    return f"Cursor {value}"


def _normalize_cursor_usage_events(events, *, bounds=None):
    days = {}
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue
        timestamp = _provider_number(event.get("timestamp"))
        usage = event.get("tokenUsage")
        if timestamp is None or timestamp <= 0 or not isinstance(usage, dict):
            continue
        timestamp_seconds = timestamp / 1000.0 if timestamp > 100_000_000_000 else timestamp
        try:
            dt = datetime.fromtimestamp(timestamp_seconds, timezone.utc).astimezone()
        except (OverflowError, OSError, ValueError):
            continue
        components = {
            "in": _provider_usage_int(usage.get("inputTokens")),
            "out": _provider_usage_int(usage.get("outputTokens")),
            "cr": _provider_usage_int(usage.get("cacheReadTokens")),
            "cw": _provider_usage_int(usage.get("cacheWriteTokens")),
            "reason": 0,
        }
        total = sum(components.values())
        if total <= 0:
            continue
        cents = _provider_number(usage.get("totalCents"))
        cost = cents / 100.0 if cents is not None and cents >= 0 else 0.0
        model_name = event.get("model")
        model_name = model_name.strip() if isinstance(model_name, str) and model_name.strip() else "unknown"
        day_key = dt.date().isoformat()
        day = days.setdefault(
            day_key,
            {"tokens": 0, "in": 0, "out": 0, "cr": 0, "cw": 0,
             "reason": 0, "cost": 0.0, "requests": 0, "models": {},
             "hours": [0] * 24})
        day["tokens"] += total
        day["cost"] += cost
        day["requests"] += 1
        day["hours"][dt.hour] += total
        for field, value in components.items():
            day[field] += value
        model = day["models"].setdefault(
            model_name,
            {"tokens": 0, "in": 0, "out": 0, "cr": 0, "cw": 0,
             "reason": 0, "cost": 0.0})
        model["tokens"] += total
        model["cost"] += cost
        for field, value in components.items():
            model[field] += value
    return _provider_usage_from_days(days, bounds=bounds)


def _cursor_boundary_overlap(previous, current):
    limit = min(len(previous), len(current))
    for count in range(limit, 0, -1):
        if previous[-count:] == current[:count]:
            return count
    return 0


def _fetch_cursor_usage_events(session, now=None):
    now = now or datetime.now().astimezone()
    start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    headers = {"Cookie": session["cookie"], "Origin": "https://cursor.com"}
    pages = []
    expected_total = None
    completed = False
    for page_number in range(1, _CURSOR_USAGE_MAX_PAGES + 1):
        payload = _provider_json_request(
            "https://cursor.com/api/dashboard/get-filtered-usage-events",
            headers=headers, method="POST", timeout=15, max_bytes=16 * 1024 * 1024,
            body={
                "page": page_number,
                "pageSize": _CURSOR_USAGE_PAGE_SIZE,
                "startDate": str(int(start.timestamp() * 1000)),
                "endDate": str(int(now.timestamp() * 1000)),
            })
        reported = _provider_integer(payload.get("totalUsageEventsCount")) \
            if isinstance(payload, dict) else None
        if reported is not None and reported < 0:
            raise ValueError("cursor usage event count cannot be negative")
        if reported is not None:
            if expected_total is not None and reported != expected_total:
                raise ValueError("cursor usage pagination count changed")
            expected_total = reported
        events = payload.get("usageEventsDisplay") if isinstance(payload, dict) else None
        if not isinstance(events, list):
            raise ValueError("cursor usage events response was invalid")
        if not events:
            completed = True
            break
        pages.append(events)
        if len(events) < _CURSOR_USAGE_PAGE_SIZE:
            completed = True
            break
    if not completed:
        raise ValueError("cursor usage pagination did not complete")
    raw = [event for page in pages for event in page]
    if expected_total is None:
        return raw
    if len(raw) < expected_total:
        raise ValueError("cursor usage pagination was incomplete")
    if len(raw) == expected_total:
        return raw
    removals = len(raw) - expected_total
    reconciled = list(pages[0]) if pages else []
    for index in range(1, len(pages)):
        overlap = min(_cursor_boundary_overlap(pages[index - 1], pages[index]), removals)
        reconciled.extend(pages[index][overlap:])
        removals -= overlap
    if removals or len(reconciled) != expected_total:
        raise ValueError("cursor usage pagination was inconsistent")
    return reconciled


def _normalize_cursor_quota(summary, *, request_usage=None, sand_usage=None, user_info=None,
                            identity=None, updated=None):
    if not isinstance(summary, dict):
        return {}
    individual = summary.get("individualUsage") if isinstance(
        summary.get("individualUsage"), dict) else {}
    team = summary.get("teamUsage") if isinstance(summary.get("teamUsage"), dict) else {}
    plan = individual.get("plan") if isinstance(individual.get("plan"), dict) else {}
    overall = individual.get("overall") if isinstance(individual.get("overall"), dict) else {}
    pooled = team.get("pooled") if isinstance(team.get("pooled"), dict) else {}

    plan_used = _provider_number(plan.get("used")) or 0.0
    plan_limit = _provider_number(plan.get("limit")) or 0.0
    auto_pct = _provider_percent(plan.get("autoPercentUsed"))
    api_pct = _provider_percent(plan.get("apiPercentUsed"))
    total_pct = _provider_percent(plan.get("totalPercentUsed"))
    if total_pct is None and auto_pct is not None and api_pct is not None:
        total_pct = _provider_percent((auto_pct + api_pct) / 2)
    if total_pct is None:
        total_pct = api_pct if api_pct is not None else auto_pct
    if total_pct is None and plan_limit > 0:
        total_pct = _provider_percent(plan_used / plan_limit * 100)
    if total_pct is None:
        for block in (overall, pooled):
            used = _provider_number(block.get("used"))
            limit = _provider_number(block.get("limit"))
            if used is not None and limit is not None and limit > 0:
                total_pct = _provider_percent(used / limit * 100)
                plan_used, plan_limit = used, limit
                break
    total_pct = total_pct if total_pct is not None else 0.0

    request_block = request_usage.get("gpt-4") if isinstance(request_usage, dict) \
        and isinstance(request_usage.get("gpt-4"), dict) else {}
    requests_used = _provider_number(
        request_block.get("numRequestsTotal") if request_block.get("numRequestsTotal") is not None
        else request_block.get("numRequests"))
    requests_limit = _provider_number(request_block.get("maxRequestUsage"))
    legacy = requests_used is not None and requests_limit is not None and requests_limit > 0

    cycle_start = _provider_epoch(summary.get("billingCycleStart"))
    cycle_end = _provider_epoch(summary.get("billingCycleEnd"))
    window_minutes = int((cycle_end - cycle_start) / 60) \
        if cycle_start and cycle_end and cycle_end > cycle_start else None
    if legacy:
        total_pct = _provider_percent(requests_used / requests_limit * 100)
        primary_detail = f"{int(requests_used)} / {int(requests_limit)} requests"
        windows = [_provider_window(
            "cursor-total", "总额度", total_pct, cycle_end, window_minutes, primary_detail)]
    else:
        # $70 是 Other Models 池。plan.used 经常是套餐面额，按 apiPercentUsed 折算。
        spend = plan_used
        if plan_limit > 0 and abs(plan_used / plan_limit * 100 - total_pct) > 5:
            spend_pct = api_pct if api_pct is not None else total_pct
            spend = plan_limit * spend_pct / 100.0
        spend_detail = (
            f"{_provider_money(spend / 100)} / {_provider_money(plan_limit / 100)}"
            if plan_limit > 0 else None)
        windows = []
        if auto_pct is not None:
            windows.append(_provider_window(
                "cursor-auto", "Cursor 模型", auto_pct, cycle_end, window_minutes))
        if api_pct is not None:
            windows.append(_provider_window(
                "cursor-api", "第三方模型", api_pct, cycle_end, window_minutes))
    details = []
    if plan_limit > 0 and not legacy:
        details.append({
            "label": "套餐用量",
            "value": spend_detail or (
                f"{_provider_money(plan_used / 100)} / {_provider_money(plan_limit / 100)}"),
        })
    on_demand = individual.get("onDemand") if isinstance(individual.get("onDemand"), dict) else {}
    team_on_demand = team.get("onDemand") if isinstance(team.get("onDemand"), dict) else {}
    on_used = _provider_number(on_demand.get("used")) or 0.0
    on_limit = _provider_number(on_demand.get("limit"))
    if not on_limit or on_limit <= 0:
        team_limit = _provider_number(team_on_demand.get("limit"))
        if team_limit and team_limit > 0:
            on_used = _provider_number(team_on_demand.get("used")) or 0.0
            on_limit = team_limit
    if on_limit and on_limit > 0:
        details.append({
            "label": "按量预算",
            "value": f"{_provider_money(on_used / 100)} / {_provider_money(on_limit / 100)}",
        })

    user_info = user_info if isinstance(user_info, dict) else {}
    identity = identity if isinstance(identity, dict) else {}
    account = user_info.get("email") or identity.get("account")
    return {
        "available": True,
        "plan": _cursor_plan_name(summary.get("membershipType")),
        "account": account,
        "windows": windows,
        "details": details,
        "source": "cursor-api",
        "updated": int(updated if updated is not None else datetime.now().timestamp()),
        "stale": False,
    }


def _grok_bot_active_account_id(path=None):
    secrets_path = path or _first_existing_file(GROK_BOT_SECRET_PATHS)
    if not secrets_path or not os.path.isfile(secrets_path):
        return None
    try:
        if os.path.getsize(secrets_path) > _PROVIDER_QUOTA_MAX_RESPONSE_BYTES:
            return None
        outer = _load_json(secrets_path, {})
        encoded = outer.get("cursor-accounts") if isinstance(outer, dict) else None
        if not isinstance(encoded, str) or len(encoded) > _PROVIDER_QUOTA_MAX_RESPONSE_BYTES:
            return None
        container = json.loads(encoded)
    except (OSError, ValueError, TypeError):
        return None
    active = container.get("active") if isinstance(container, dict) else None
    accounts = container.get("accounts") if isinstance(container, dict) else None
    if not isinstance(active, str) or not re.fullmatch(r"[0-9a-f]{64}", active):
        return None
    return active if isinstance(accounts, dict) and isinstance(accounts.get(active), dict) else None


def _grok_bot_authorization_generation(path=None):
    marker = path or GROK_BOT_AUTH_MARKER
    if not marker:
        return None
    try:
        stat = os.stat(marker, follow_symlinks=False)
    except OSError:
        return None
    return stat.st_mtime_ns if os.path.isfile(marker) else None


def _grok_bot_helper_path():
    configured = os.environ.get("TOKEI_GROK_BOT_HELPER")
    candidates = [configured] if isinstance(configured, str) and configured.strip() else []
    if sys.platform == "darwin":
        candidates.append("/Applications/Tokei.app/Contents/MacOS/Tokei")
    for candidate in candidates:
        path = _expand_path(candidate)
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def _grok_bot_helper_sand_usage():
    helper = _grok_bot_helper_path()
    if not helper:
        return None
    try:
        result = subprocess.run(
            [helper, "--grok-bot-data-json"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=35,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or len(result.stdout) > 16 * 1024 * 1024:
        return None
    try:
        payload = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _grok_bot_repair_authorization_marker():
    """Restore a missing local marker when Keychain access is still valid."""
    helper = _grok_bot_helper_path()
    if not helper:
        return False
    try:
        result = subprocess.run(
            [helper, "--grok-bot-verify"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and _grok_bot_authorization_generation() is not None


def _grok_bot_usage_from_bridge(payload):
    if not isinstance(payload, dict) or payload.get("usageFetched") is not True:
        return None
    events = payload.get("usageEventsDisplay")
    if not isinstance(events, list):
        return None
    unique = []
    seen = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        try:
            marker = json.dumps(event, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            continue
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(event)
    usage = _normalize_cursor_usage_events(unique)
    all_range = (usage.get("ranges") or {}).get("all") if isinstance(usage, dict) else None
    if isinstance(all_range, dict):
        all_range["coverage"] = "本年"
    return usage


def _grok_bot_provider_data(payload, *, updated=None):
    if not isinstance(payload, dict):
        return {}
    is_bridge_payload = "quotaFetched" in payload or "usageFetched" in payload
    sand_usage = payload.get("sandUsage") if is_bridge_payload else payload
    quota = _normalize_grok_bot_quota(
        sand_usage, updated=updated, source="grok-bot-api")
    usage = _grok_bot_usage_from_bridge(payload) if is_bridge_payload else None
    ranges = usage.get("ranges") if isinstance(usage, dict) else None
    has_usage = isinstance(ranges, dict) and any(
        isinstance(row, dict) and (
            _provider_usage_int(row.get("tokens")) > 0
            or _provider_usage_int(row.get("requests")) > 0
        )
        for row in ranges.values()
    )
    if has_usage:
        if not quota:
            quota = {
                "available": False,
                "plan": None,
                "account": None,
                "windows": [],
                "details": [],
                "source": "grok-bot-api",
                "updated": int(updated if updated is not None else datetime.now().timestamp()),
                "stale": False,
            }
        quota["usage"] = usage
    return quota


def _normalize_grok_bot_quota(sand_usage, *, user_info=None, identity=None, updated=None,
                              source="cursor-sand-api"):
    if not isinstance(sand_usage, dict):
        return {}
    used_pct = _provider_percent(sand_usage.get("usagePercent"))
    if used_pct is None or sand_usage.get("hasNonZeroIncludedLimit") is False:
        return {}
    period_start = _provider_epoch(sand_usage.get("currentPeriodStart"))
    reset = _provider_epoch(sand_usage.get("nextResetTimestampUtc"))
    window_minutes = int((reset - period_start) / 60) \
        if period_start and reset and reset > period_start else None
    plan = sand_usage.get("grokPlanLabel") or sand_usage.get("planLabel") \
        or sand_usage.get("plan")
    plan = plan.strip() if isinstance(plan, str) and plan.strip() else None
    return {
        "available": True,
        "plan": plan,
        "account": None,
        "windows": [_provider_window(
            "grok-bot-period", "本周期额度", used_pct, reset, window_minutes)],
        "details": [],
        "source": source,
        "updated": int(updated if updated is not None else datetime.now().timestamp()),
        "stale": False,
    }


def _grok_bot_quota_from_cursor(cursor_quota):
    if not isinstance(cursor_quota, dict):
        return {}
    source_window = next((window for window in cursor_quota.get("windows", [])
                          if isinstance(window, dict)
                          and window.get("id") == "cursor-grok-bot"), None)
    if source_window is None:
        return {}
    window = dict(source_window)
    window["id"] = "grok-bot-period"
    window["title"] = "本周期额度"
    plan = window.pop("detail", None)
    return {
        "available": True,
        "plan": plan,
        "account": None,
        "windows": [window],
        "details": [],
        "source": "cursor-sand-api",
        "updated": cursor_quota.get("updated"),
        "stale": bool(cursor_quota.get("stale")),
    }


def fetch_cursor_quota(session=None, force=False):
    session = session or _cursor_session()
    if not session:
        return {}
    marker = _provider_credential_marker("cursor-usage-v1", session["marker"])
    if not force:
        cached = _cached_provider_quota("cursor", marker, _PROVIDER_QUOTA_TTL)
        if cached:
            return cached
    headers = {"Cookie": session["cookie"]}
    base = "https://cursor.com"
    try:
        summary = _provider_json_request(base + "/api/usage-summary", headers=headers)
        user_info = None
        try:
            user_info = _provider_json_request(base + "/api/auth/me", headers=headers)
        except Exception:
            pass
        request_usage = None
        user_id = (user_info or {}).get("sub") if isinstance(user_info, dict) else None
        user_id = user_id or session.get("subject") or session.get("user_id")
        if isinstance(user_id, str) and user_id:
            user_id = user_id.rsplit("|", 1)[-1]
            from urllib.parse import quote
            try:
                request_usage = _provider_json_request(
                    base + "/api/usage?user=" + quote(user_id, safe=""), headers=headers)
            except Exception:
                pass
        sand_usage = None
        try:
            sand_usage = _provider_json_request(
                base + "/api/dashboard/get-sand-usage-status",
                headers={**headers, "Origin": base}, method="POST", body={})
        except Exception:
            pass
        usage = _provider_usage_from_days({})
        try:
            usage = _normalize_cursor_usage_events(_fetch_cursor_usage_events(session))
        except Exception:
            pass
        quota = _normalize_cursor_quota(
            summary, request_usage=request_usage, sand_usage=sand_usage,
            user_info=user_info, identity=session)
        quota["usage"] = usage
        _save_provider_quota_cache("cursor", marker, quota)
        grok_bot_quota = _normalize_grok_bot_quota(
            sand_usage, user_info=user_info, identity=session)
        if grok_bot_quota:
            _save_provider_quota_cache("grok_bot", marker, grok_bot_quota)
        return quota
    except Exception:
        fallback = _cached_provider_quota(
            "cursor", marker, _PROVIDER_QUOTA_FALLBACK_TTL, stale=True)
        if fallback:
            return fallback
        raise


def scan_cursor_quota():
    return fetch_cursor_quota() if _provider_quota_enabled("cursor") else {}


def _grok_bot_usage_only_fallback():
    cached = _latest_cached_provider_quota(
        "grok_bot", max_age=None, stale=True)
    usage = cached.get("usage") if isinstance(cached, dict) else None
    ranges = usage.get("ranges") if isinstance(usage, dict) else None
    if not isinstance(ranges, dict) or not any(
            isinstance(row, dict) and _provider_usage_int(row.get("tokens")) > 0
            for row in ranges.values()):
        return {}
    return {
        "available": False,
        "plan": None,
        "account": None,
        "windows": [],
        "details": [],
        "usage": usage,
        "source": "cache",
        "updated": cached.get("updated"),
        "stale": True,
    }


def fetch_grok_bot_quota(session=None):
    native_fallback = _latest_cached_provider_quota(
        "grok_bot", _PROVIDER_QUOTA_FALLBACK_TTL, stale=True) \
        or _grok_bot_usage_only_fallback()
    if session is None:
        account_id = _grok_bot_active_account_id()
        authorization_generation = _grok_bot_authorization_generation()
        if account_id and authorization_generation is None:
            repair_marker = _provider_credential_marker(
                "grok-bot-auth-repair-v1", account_id)
            recent_repair = _provider_quota_recent_attempt_result(
                "grok_bot_auth", repair_marker, _PROVIDER_QUOTA_TTL)
            if recent_repair is None:
                if _grok_bot_repair_authorization_marker():
                    authorization_generation = _grok_bot_authorization_generation()
                else:
                    _save_provider_quota_attempt(
                        "grok_bot_auth", repair_marker, result="failed")
        if account_id and authorization_generation is not None:
            native_marker = _provider_credential_marker(
                "grok-bot-account-v1", account_id, authorization_generation)
            cached = _cached_provider_quota(
                "grok_bot", native_marker, _PROVIDER_QUOTA_TTL)
            if cached:
                return cached
            native_fallback = _cached_provider_quota(
                "grok_bot", native_marker, _PROVIDER_QUOTA_FALLBACK_TTL, stale=True) \
                or native_fallback
            recent_attempt = _provider_quota_recent_attempt_result(
                "grok_bot", native_marker, _PROVIDER_QUOTA_TTL)
            if recent_attempt == "empty":
                return {}
            if recent_attempt is None:
                payload = _grok_bot_helper_sand_usage()
                if payload is not None:
                    quota = _grok_bot_provider_data(
                        payload, updated=payload.get("updated"))
                    if quota:
                        _save_provider_quota_cache("grok_bot", native_marker, quota)
                        return quota
                    if payload.get("quotaFetched") is True or "quotaFetched" not in payload:
                        _save_provider_quota_attempt(
                            "grok_bot", native_marker, result="empty")
                        return {}
                _save_provider_quota_attempt("grok_bot", native_marker)

    session = session or _cursor_session()
    if not session:
        return native_fallback
    marker = _provider_credential_marker("cursor-usage-v1", session["marker"])
    cached = _cached_provider_quota("grok_bot", marker, _PROVIDER_QUOTA_TTL)
    if cached:
        return cached
    cursor_quota = fetch_cursor_quota(session, force=True)
    cached = _cached_provider_quota("grok_bot", marker, _PROVIDER_QUOTA_TTL)
    if cached:
        return cached
    quota = _grok_bot_quota_from_cursor(cursor_quota)
    if quota:
        _save_provider_quota_cache("grok_bot", marker, quota)
        return quota
    return _cached_provider_quota(
        "grok_bot", marker, _PROVIDER_QUOTA_FALLBACK_TTL, stale=True) or native_fallback


def scan_grok_bot_quota():
    return fetch_grok_bot_quota() if _provider_quota_enabled("grok_bot") else {}


# ----- Zed -----


def _zed_connection_settings(settings):
    settings = settings if isinstance(settings, dict) else {}
    credentials = settings.get("credentials_url")
    server = settings.get("server_url")
    credentials = credentials.strip() if isinstance(credentials, str) and credentials.strip() else None
    server = server.strip().rstrip("/") if isinstance(server, str) and server.strip() else "https://zed.dev"
    service = credentials or server
    trusted = server in {"https://zed.dev", "https://staging.zed.dev"}
    if not trusted and credentials and credentials.rstrip("/") != server:
        return None
    from urllib.parse import urlsplit
    parsed = urlsplit(server)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password \
            or parsed.query or parsed.fragment:
        return None
    api_base = "https://cloud.zed.dev" if trusted else server
    return {"service": service, "api_url": api_base + "/client/users/me"}


def _load_zed_connection_settings(path=None):
    path = path or _provider_config_string(
        "TOKEI_ZED_SETTINGS", "zed_settings_path") \
        or os.path.join(HOME, ".config", "zed", "settings.json")
    settings = _load_json(path, {}) if os.path.isfile(path) else {}
    return _zed_connection_settings(settings)


def _zed_plan_name(raw):
    names = {
        "zed_free": "Zed Free", "zed_pro": "Zed Pro",
        "zed_pro_trial": "Zed Pro Trial", "zed_student": "Zed Student",
        "zed_business": "Zed Business", "student": "Student",
        "vip": "VIP", "zed_vip": "Zed VIP",
    }
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip()
    return names.get(value.lower(), " ".join(word.capitalize() for word in value.split("_")))


def _normalize_zed_quota(payload, updated=None):
    if not isinstance(payload, dict):
        return {}
    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
    usage = plan.get("usage") if isinstance(plan.get("usage"), dict) else {}
    predictions = usage.get("edit_predictions") if isinstance(
        usage.get("edit_predictions"), dict) else {}
    used = max(0.0, _provider_number(predictions.get("used")) or 0.0)
    limit_value = predictions.get("limit")
    if isinstance(limit_value, dict):
        limit_value = limit_value.get("limited")
    windows = []
    if isinstance(limit_value, str) and limit_value.lower() == "unlimited":
        windows.append(_provider_window(
            "zed-predictions", "Edit Predictions", 0, detail="Unlimited"))
    else:
        limit = _provider_number(limit_value)
        if limit is not None and limit > 0:
            clamped = min(used, limit)
            windows.append(_provider_window(
                "zed-predictions", "Edit Predictions", clamped / limit * 100,
                detail=f"{int(clamped)} / {int(limit)} predictions"))

    period = plan.get("subscription_period") if isinstance(
        plan.get("subscription_period"), dict) else {}
    start = _provider_epoch(period.get("started_at"))
    end = _provider_epoch(period.get("ended_at"))
    now = int(updated if updated is not None else datetime.now().timestamp())
    if start and end and end > start:
        windows.append(_provider_window(
            "zed-cycle", "订阅周期", (now - start) / (end - start) * 100, end,
            int((end - start) / 60)))
    if plan.get("has_overdue_invoices") is True:
        windows.append(_provider_window(
            "zed-overdue", "账单", None, detail="Overdue invoices", usage_known=False))

    details = []
    if isinstance(user.get("name"), str) and user["name"].strip():
        details.append({"label": "账号", "value": user["name"].strip()})
    organization_plans = payload.get("plans_by_organization")
    organization_plans = organization_plans if isinstance(organization_plans, dict) else {}
    default_organization_id = payload.get("default_organization_id")
    default_organization_id = str(default_organization_id) \
        if isinstance(default_organization_id, (str, int)) \
        and not isinstance(default_organization_id, bool) else None
    plan_names = []
    for organization in payload.get("organizations", []):
        if not isinstance(organization, dict):
            continue
        organization_id = organization.get("id")
        organization_id = str(organization_id) \
            if isinstance(organization_id, (str, int)) \
            and not isinstance(organization_id, bool) else None
        name = organization.get("name")
        name = name.strip() if isinstance(name, str) and name.strip() else None
        if not organization_id or not name:
            continue
        plan_name = _zed_plan_name(organization_plans.get(organization_id))
        if not plan_name:
            continue
        if plan_name not in plan_names:
            plan_names.append(plan_name)
        detail = {"label": name, "value": plan_name}
        if organization_id == default_organization_id:
            detail["secondary"] = "当前组织"
        details.append(detail)
    displayed_plan = " + ".join(plan_names) if plan_names else _zed_plan_name(plan.get("plan_v3"))
    return {
        "available": bool(windows or plan or plan_names),
        "plan": displayed_plan,
        "account": user.get("github_login"),
        "windows": windows,
        "details": details,
        "source": "zed-cloud",
        "updated": now,
        "stale": False,
    }


def fetch_zed_quota():
    user_id = _provider_config_string("TOKEI_ZED_USER_ID", "zed_user_id")
    token = _provider_config_string("TOKEI_ZED_ACCESS_TOKEN", "zed_access_token")
    connection = _load_zed_connection_settings()
    if not user_id or not token or not connection:
        return {}
    marker = _provider_credential_marker(
        "zed", user_id, token, connection["service"], connection["api_url"])
    cached = _cached_provider_quota("zed", marker, _PROVIDER_QUOTA_TTL)
    if cached:
        return cached
    try:
        payload = _provider_json_request(
            connection["api_url"], headers={
                "Authorization": f"{user_id} {token}",
                # Zed Cloud rejects urllib's default Python-urllib/... user agent.
                "User-Agent": "Tokei/1.0",
            })
        quota = _normalize_zed_quota(payload)
        _save_provider_quota_cache("zed", marker, quota)
        return quota
    except Exception:
        fallback = _cached_provider_quota(
            "zed", marker, _PROVIDER_QUOTA_FALLBACK_TTL, stale=True)
        if fallback:
            return fallback
        raise


def scan_zed_quota():
    return fetch_zed_quota() if _provider_quota_enabled("zed") else {}


# ----- sub2api -----


def _local_timezone_name():
    configured = os.environ.get("TZ")
    if configured and configured.strip():
        return configured.strip()
    try:
        target = os.path.realpath("/etc/localtime")
        marker = "/zoneinfo/"
        if marker in target:
            return target.split(marker, 1)[1]
    except OSError:
        pass
    zone = datetime.now().astimezone().tzinfo
    return getattr(zone, "key", None) or datetime.now().astimezone().tzname() or "UTC"


def _sub2api_usage_url(base_url, timezone_name=None):
    if not isinstance(base_url, str) or not base_url.strip():
        return None
    import ipaddress
    from urllib.parse import urlencode, urlsplit, urlunsplit

    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"https", "http"} or not parsed.hostname \
            or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None
    if parsed.scheme == "http":
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = parsed.hostname.lower() == "localhost"
        if not loopback:
            return None
    path = parsed.path.rstrip("/")
    if not re.search(r"/v1(?:/usage)?$", path):
        path += "/v1"
    if not path.endswith("/usage"):
        path += "/usage"
    query = urlencode({"days": 30, "timezone": timezone_name or _local_timezone_name()})
    return urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))


def _normalize_sub2api_quota(data, updated=None):
    if not isinstance(data, dict) or data.get("isValid") is False:
        return {}
    unit = data.get("unit") if isinstance(data.get("unit"), str) else "USD"
    windows = []

    def add_window(window_id, title, used, limit, minutes=None, reset=None, value_unit=None):
        used_number = _provider_number(used)
        limit_number = _provider_number(limit)
        if used_number is None or limit_number is None or limit_number <= 0:
            return
        detail = f"{_provider_money(used_number, value_unit or unit)} / " \
            f"{_provider_money(limit_number, value_unit or unit)}"
        windows.append(_provider_window(
            window_id, title, used_number / limit_number * 100, reset, minutes, detail))

    subscription = data.get("subscription") if isinstance(data.get("subscription"), dict) else None
    quota = data.get("quota") if isinstance(data.get("quota"), dict) else None
    if subscription:
        add_window("sub2api-daily", "日额度", subscription.get("daily_usage_usd"),
                   subscription.get("daily_limit_usd"), 1440)
        add_window("sub2api-weekly", "周额度", subscription.get("weekly_usage_usd"),
                   subscription.get("weekly_limit_usd"), 10080)
        add_window("sub2api-monthly", "月额度", subscription.get("monthly_usage_usd"),
                   subscription.get("monthly_limit_usd"), 43200)
    elif quota:
        quota_unit = quota.get("unit") if isinstance(quota.get("unit"), str) else unit
        add_window("sub2api-quota", "额度", quota.get("used"), quota.get("limit"),
                   value_unit=quota_unit)

    rate_minutes = {"5h": 300, "1d": 1440, "7d": 10080}
    rate_titles = {"5h": "5h 额度", "1d": "日限额", "7d": "周限额"}
    rates = data.get("rate_limits") if isinstance(data.get("rate_limits"), list) else []
    for index, rate in enumerate(rates):
        if not isinstance(rate, dict):
            continue
        name = str(rate.get("window") or f"rate-{index}")
        add_window(
            f"sub2api-{name}", rate_titles.get(name.lower(), f"{name} 限额"),
            rate.get("used"), rate.get("limit"), rate_minutes.get(name.lower()),
            rate.get("reset_at"))

    details = []
    balance = _provider_number(data.get("balance"))
    if balance is not None:
        details.append({"label": "余额", "value": _provider_money(balance, unit)})
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    for key, label in (("today", "今日"), ("total", "累计")):
        row = usage.get(key) if isinstance(usage.get(key), dict) else None
        if not row:
            continue
        requests = 0 if row.get("requests") is None else _provider_integer(row.get("requests"))
        tokens = 0 if row.get("total_tokens") is None else _provider_integer(row.get("total_tokens"))
        if requests is None or tokens is None:
            raise ValueError(f"sub2api {key} usage counts must be integers")
        cost = _provider_number(row.get("actual_cost")) or 0
        details.append({"label": f"{label}请求", "value": f"{requests:,}"})
        token_row = {"label": f"{label} Token", "value": f"{tokens:,}"}
        if cost:
            token_row["secondary"] = _provider_money(cost)
        details.append(token_row)

    expiration = (subscription or {}).get("expires_at") or data.get("expires_at")
    expiration_epoch = _provider_epoch(expiration)
    if expiration_epoch:
        details.append({"label": "套餐到期", "value": str(expiration_epoch)})
    plan_name = data.get("planName") if isinstance(data.get("planName"), str) else None
    return {
        "available": bool(windows or details or plan_name),
        "plan": plan_name,
        "account": None,
        "windows": windows,
        "details": details,
        "source": "sub2api",
        "updated": int(updated if updated is not None else datetime.now().timestamp()),
        "stale": False,
    }


def fetch_sub2api_quota():
    api_key = _provider_config_string("SUB2API_API_KEY", "sub2api_api_key")
    base_url = _provider_config_string("SUB2API_BASE_URL", "sub2api_base_url")
    usage_url = _sub2api_usage_url(base_url) if base_url else None
    if not api_key or not usage_url:
        return {}
    marker = _provider_credential_marker("sub2api", api_key, usage_url)
    cached = _cached_provider_quota("sub2api", marker, _PROVIDER_QUOTA_TTL)
    if cached:
        return cached
    try:
        payload = _provider_json_request(
            usage_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=15)
        if isinstance(payload, dict) and payload.get("isValid") is False:
            raise PermissionError("sub2api rejected the API key")
        quota = _normalize_sub2api_quota(payload)
        _save_provider_quota_cache("sub2api", marker, quota)
        return quota
    except Exception:
        fallback = _cached_provider_quota(
            "sub2api", marker, _PROVIDER_QUOTA_FALLBACK_TTL, stale=True)
        if fallback:
            return fallback
        raise


def scan_sub2api_quota():
    return fetch_sub2api_quota() if _provider_quota_enabled("sub2api") else {}


# ----- z.ai / GLM -----


def _zai_quota_url(url, scope="personal"):
    if scope != "team":
        return url
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    parsed = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if key != "type"]
    query.append(("type", "2"))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def _zai_model_usage_url(base, scope="personal", now=None):
    from urllib.parse import urlencode
    now = now or datetime.now().astimezone()
    start = (now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(minute=59, second=59, microsecond=0)
    query = {
        "startTime": start.strftime("%Y-%m-%d %H:%M:%S"),
        "endTime": end.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if scope == "team":
        query["type"] = "3"
    return base.rstrip("/") + "/api/monitor/usage/model-usage?" + urlencode(query)


def _normalize_zai_model_usage(payload, *, bounds=None):
    if not isinstance(payload, dict) or payload.get("success") is not True \
            or _provider_number(payload.get("code")) != 200:
        return _provider_usage_from_days({}, bounds=bounds, limited_coverage="近30天")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    labels = data.get("x_time") if isinstance(data.get("x_time"), list) else []
    models = data.get("modelDataList") \
        if isinstance(data.get("modelDataList"), list) else []
    parsed_labels = []
    for label in labels:
        if not isinstance(label, str):
            parsed_labels.append(None)
            continue
        try:
            parsed_labels.append(datetime.fromisoformat(label).astimezone())
        except ValueError:
            parsed_labels.append(None)
    days = {}
    for model in models:
        if not isinstance(model, dict):
            continue
        name = model.get("modelName")
        name = name.strip() if isinstance(name, str) and name.strip() else "unknown"
        values = model.get("tokensUsage") if isinstance(model.get("tokensUsage"), list) else []
        for index, dt in enumerate(parsed_labels):
            if dt is None or index >= len(values):
                continue
            tokens = _provider_usage_int(values[index])
            if tokens <= 0:
                continue
            day_key = dt.date().isoformat()
            day = days.setdefault(
                day_key,
                {"tokens": 0, "in": 0, "out": 0, "cr": 0, "cw": 0,
                 "reason": 0, "cost": 0.0, "requests": 0, "models": {},
                 "hours": [0] * 24})
            day["tokens"] += tokens
            day["hours"][dt.hour] += tokens
            usage = day["models"].setdefault(name, {"tokens": 0})
            usage["tokens"] += tokens
    return _provider_usage_from_days(days, bounds=bounds, limited_coverage="近30天")


def _zai_limit(raw):
    if not isinstance(raw, dict) or raw.get("type") not in {
            "TOKENS_LIMIT", "CREDIT_LIMIT", "TIME_LIMIT"}:
        return None
    unit = _provider_integer(raw.get("unit"))
    number = _provider_integer(raw.get("number"))
    percent_raw = _provider_integer(raw.get("percentage"))
    percent = _provider_percent(percent_raw)
    if unit is None or number is None or percent is None:
        return None
    usage = _provider_number(raw.get("usage"))
    current = _provider_number(raw.get("currentValue"))
    remaining = _provider_number(raw.get("remaining"))
    if usage is not None and usage > 0:
        used = None
        if remaining is not None:
            used = max(usage - remaining, current if current is not None else usage - remaining)
        elif current is not None:
            used = current
        if used is not None:
            percent = _provider_percent(max(0, min(usage, used)) / usage * 100)
    multipliers = {1: 1440, 3: 60, 5: 1, 6: 10080}
    unit_int, number_int = unit, number
    minutes = number_int * multipliers[unit_int] \
        if number_int > 0 and unit_int in multipliers else None
    if raw.get("type") == "TIME_LIMIT" and unit_int == 5 and number_int == 1:
        minutes = 30 * 24 * 60
    details = raw.get("usageDetails") if isinstance(raw.get("usageDetails"), list) else []
    return {
        "raw": raw, "usage": usage, "current": current, "remaining": remaining,
        "percent": percent, "window_minutes": minutes,
        "reset": _provider_epoch(raw.get("nextResetTime")), "details": details,
    }


def _zai_limit_detail(limit):
    parts = []
    if limit.get("usage") is not None:
        parts.append(f"{limit['usage']:g} limit")
    if limit.get("remaining") is not None:
        parts.append(f"{limit['remaining']:g} remaining")
    return " · ".join(parts) or None


def _normalize_zai_quota(payload, *, region="global", balance=None, updated=None):
    if not isinstance(payload, dict) or payload.get("success") is not True \
            or _provider_number(payload.get("code")) != 200:
        return {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    limits = [_zai_limit(item) for item in data.get("limits", [])]
    limits = [item for item in limits if item]
    token_limits = sorted(
        [item for item in limits if item["raw"].get("type") in {"TOKENS_LIMIT", "CREDIT_LIMIT"}],
        key=lambda item: item.get("window_minutes") or sys.maxsize)
    time_limits = [item for item in limits if item["raw"].get("type") == "TIME_LIMIT"]
    token_limit = token_limits[-1] if token_limits else None
    session_limit = token_limits[0] if len(token_limits) >= 2 else None
    time_limit = time_limits[-1] if time_limits else None
    primary = session_limit or token_limit or time_limit
    windows = []
    if primary:
        windows.append(_provider_window(
            "zai-primary", "会话额度" if session_limit else "额度", primary["percent"],
            primary.get("reset"), primary.get("window_minutes"), _zai_limit_detail(primary)))
    if session_limit and token_limit:
        windows.append(_provider_window(
            "zai-secondary", "周期额度", token_limit["percent"], token_limit.get("reset"),
            token_limit.get("window_minutes"), _zai_limit_detail(token_limit)))
    if time_limit and (token_limit or session_limit):
        windows.append(_provider_window(
            "zai-mcp", "MCP", time_limit["percent"], time_limit.get("reset"),
            time_limit.get("window_minutes"), _zai_limit_detail(time_limit)))

    details = []
    if token_limit:
        label = "Credit quota" if token_limit["raw"].get("type") == "CREDIT_LIMIT" else "Token quota"
        details.append({"label": label, "value": f"{token_limit['percent']:g}% used",
                        "secondary": _zai_limit_detail(token_limit)})
    if session_limit:
        label = "Session credit quota" if session_limit["raw"].get("type") == "CREDIT_LIMIT" \
            else "Session token quota"
        details.append({"label": label, "value": f"{session_limit['percent']:g}% used",
                        "secondary": _zai_limit_detail(session_limit)})
    if time_limit:
        details.append({"label": "MCP quota", "value": f"{time_limit['percent']:g}% used",
                        "secondary": _zai_limit_detail(time_limit)})
        for item in time_limit.get("details", [])[:20]:
            if isinstance(item, dict) and isinstance(item.get("modelCode"), str):
                value = _provider_number(item.get("usage"))
                if value is not None and value >= 0:
                    details.append({"label": item["modelCode"], "value": f"{int(value):,}"})

    if region == "bigmodel-cn" and isinstance(balance, dict) and balance.get("success") is True:
        balance_data = balance.get("data") if isinstance(balance.get("data"), dict) else {}
        available = _provider_number(balance_data.get("availableBalance"))
        current = _provider_number(balance_data.get("balance"))
        amount = available if available is not None else current
        if amount is not None:
            secondary = []
            for key, label in (("rechargeAmount", "recharged"),
                               ("giveAmount", "granted"),
                               ("totalSpendAmount", "spent")):
                value = _provider_number(balance_data.get(key))
                if value is not None and (key != "giveAmount" or value > 0):
                    secondary.append(f"{label} ¥{value:.2f}")
            row = {"label": "Account balance", "value": f"¥{amount:.2f}"}
            if secondary:
                row["secondary"] = " · ".join(secondary)
            details.append(row)

    plan_name = next((data.get(key).strip() for key in (
        "planName", "plan", "plan_type", "packageName", "level")
        if isinstance(data.get(key), str) and data.get(key).strip()), None)
    return {
        "available": bool(windows or details or plan_name),
        "plan": plan_name,
        "account": None,
        "windows": windows,
        "details": details,
        "source": "zai-api",
        "updated": int(updated if updated is not None else datetime.now().timestamp()),
        "stale": False,
    }


def fetch_zai_quota():
    region = (_provider_config_string("Z_AI_REGION", "zai_region") or "global").lower()
    if region not in {"global", "bigmodel-cn"}:
        return {}
    scope = (_provider_config_string("Z_AI_USAGE_SCOPE", "zai_usage_scope") or "personal").lower()
    if scope not in {"personal", "team"}:
        return {}
    api_key = _provider_config_string("Z_AI_API_KEY", "zai_api_key")
    if not api_key and region == "bigmodel-cn":
        api_key = _provider_config_string("BIGMODEL_API_KEY", "zai_api_key")
    organization = _provider_config_string("Z_AI_ORGANIZATION", "zai_organization")
    project = _provider_config_string("Z_AI_PROJECT", "zai_project")
    if not api_key or (scope == "team" and (not organization or not project)):
        return {}
    base = "https://open.bigmodel.cn" if region == "bigmodel-cn" else "https://api.z.ai"
    quota_url = _zai_quota_url(base + "/api/monitor/usage/quota/limit", scope)
    marker = _provider_credential_marker(
        "zai-usage-v1", api_key, region, scope, organization, project, quota_url)
    cached = _cached_provider_quota("zai", marker, _PROVIDER_QUOTA_TTL)
    if cached:
        return cached
    headers = {"Authorization": f"Bearer {api_key}"}
    if scope == "team":
        headers["Bigmodel-Organization"] = organization
        headers["Bigmodel-Project"] = project
    try:
        payload = _provider_json_request(quota_url, headers=headers)
        balance = None
        if region == "bigmodel-cn":
            try:
                balance = _provider_json_request(
                    "https://www.bigmodel.cn/api/biz/account/query-customer-account-report",
                    headers=headers, timeout=5)
            except Exception:
                pass
        quota = _normalize_zai_quota(payload, region=region, balance=balance)
        usage = _provider_usage_from_days({}, limited_coverage="近30天")
        try:
            model_payload = _provider_json_request(
                _zai_model_usage_url(base, scope), headers=headers, timeout=15,
                max_bytes=8 * 1024 * 1024)
            usage = _normalize_zai_model_usage(model_payload)
        except Exception:
            pass
        quota["usage"] = usage
        _save_provider_quota_cache("zai", marker, quota)
        return quota
    except Exception:
        fallback = _cached_provider_quota(
            "zai", marker, _PROVIDER_QUOTA_FALLBACK_TTL, stale=True)
        if fallback:
            return fallback
        raise


def scan_zai_quota():
    return fetch_zai_quota() if _provider_quota_enabled("zai") else {}


# ----- Antigravity loopback quota -----

# 没装/没开 Antigravity 时 ps 全表扫描恒为空,但每 30 秒一个 tick 都要付一次
# spawn(30ms+)。扫空后在这段时间内不重扫;90 秒也把新启动 Antigravity 的
# 发现延迟压在两三个 tick 内。
_ANTIGRAVITY_SCAN_MISS_TTL = 90


def _antigravity_extract_flag(command, flag):
    match = re.search(re.escape(flag) + r"(?:=|\s+)([^\s]+)", command, re.I)
    return match.group(1) if match else None


def _antigravity_process_kind(command):
    lower = command.lower()
    language_server = re.search(
        r"(^|[/\\])language(?:_|-)server(?:[_-][a-z0-9]+)*(?:\.exe)?(?:\s|$)", lower)
    app_match = ("--app_data_dir" in lower and "antigravity" in lower) or any(
        marker in lower for marker in ("antigravity.app/", "/gemini.app/",
                                       "antigravity ide.app/"))
    if language_server and app_match:
        return "ide"
    if re.search(r"(^|[/\\])(antigravity-cli|antigravity_cli|agy)(?:\s|[/\\]|$)", lower):
        return "cli"
    return None


def _antigravity_process_infos(output):
    results = []
    for line in str(output or "").splitlines():
        match = re.match(r"^\s*(\d+)\s+(.+)$", line)
        if not match:
            continue
        pid, command = int(match.group(1)), match.group(2)
        kind = _antigravity_process_kind(command)
        if not kind:
            continue
        csrf = _antigravity_extract_flag(command, "--csrf_token")
        if kind != "cli" and not csrf:
            continue
        extension_port = _provider_integer(
            _antigravity_extract_flag(command, "--extension_server_port"))
        if extension_port is not None and not 0 < extension_port <= 65535:
            extension_port = None
        results.append({
            "pid": pid, "kind": kind, "csrf_token": csrf or "",
            "extension_port": extension_port,
            "extension_csrf_token": _antigravity_extract_flag(
                command, "--extension_server_csrf_token"),
        })
    return results


def _antigravity_scan_recently_empty(now_epoch=None):
    """上一轮 ps 扫空后的 TTL 内直接判定没跑,省掉每 tick 一次 ps 进程。"""
    root = _load_json(ANTIGRAVITY_SCAN_CACHE, {})
    empty_at = _provider_number(root.get("empty_at")) if isinstance(root, dict) else None
    if empty_at is None:
        return False
    now = int(now_epoch if now_epoch is not None else datetime.now().timestamp())
    return 0 <= now - int(empty_at) < _ANTIGRAVITY_SCAN_MISS_TTL


def _record_antigravity_scan(found, now_epoch=None):
    if found:
        try:
            os.remove(ANTIGRAVITY_SCAN_CACHE)
        except OSError:
            pass
        return
    try:
        _atomic_write_json(ANTIGRAVITY_SCAN_CACHE, {
            "empty_at": int(now_epoch if now_epoch is not None else datetime.now().timestamp()),
        })
    except OSError:
        pass


def _antigravity_running_processes(now_epoch=None):
    if _antigravity_scan_recently_empty(now_epoch):
        return []
    try:
        result = subprocess.run(
            ["/bin/ps", "-ax", "-o", "pid=,command="],
            capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    processes = _antigravity_process_infos(result.stdout)
    _record_antigravity_scan(bool(processes), now_epoch)
    return processes


def _antigravity_listening_ports(pid):
    lsof = next((path for path in ("/usr/sbin/lsof", "/usr/bin/lsof")
                 if os.path.isfile(path) and os.access(path, os.X_OK)), None)
    if not lsof:
        return []
    try:
        result = subprocess.run(
            [lsof, "-nP", "-iTCP", "-sTCP:LISTEN", "-a", "-p", str(pid)],
            capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    return sorted({int(value) for value in re.findall(r":(\d+)\s+\(LISTEN\)", result.stdout)})


def _antigravity_endpoints(process):
    endpoints = []
    extension_port = process.get("extension_port")
    if extension_port:
        for token in (process.get("extension_csrf_token"), process.get("csrf_token")):
            if token is not None:
                endpoints.append(("http", extension_port, token, True))
    for port in _antigravity_listening_ports(process["pid"]):
        endpoints.append(("https", port, process.get("csrf_token") or "",
                          process.get("kind") != "cli"))
    unique = []
    for endpoint in endpoints:
        if endpoint not in unique:
            unique.append(endpoint)
    return unique


def _antigravity_request(endpoint, path, body):
    scheme, port, csrf, requires_csrf = endpoint
    headers = {"Connect-Protocol-Version": "1"}
    if requires_csrf:
        headers["X-Codeium-Csrf-Token"] = csrf
    return _provider_json_request(
        f"{scheme}://127.0.0.1:{port}{path}", headers=headers, method="POST", body=body,
        timeout=2, allow_insecure_loopback_tls=True)


def _antigravity_remaining(value):
    if not isinstance(value, dict):
        return None
    raw = value.get("remainingFraction")
    if raw is None and value.get("case") == "remainingFraction":
        raw = value.get("value")
    number = _provider_number(raw)
    return max(0.0, min(1.0, number)) if number is not None else None


_ANTIGRAVITY_QUOTA_WINDOWS = (
    ("gemini-weekly", "Gemini 周", 10080),
    ("gemini-5h", "Gemini 5h", 300),
    ("3p-weekly", "Claude/GPT 周", 10080),
    ("3p-5h", "Claude/GPT 5h", 300),
)


def _normalize_antigravity_quota_summary(payload, updated=None):
    root = payload.get("response") if isinstance(payload, dict) \
        and isinstance(payload.get("response"), dict) else payload
    groups = root.get("groups") if isinstance(root, dict) and isinstance(root.get("groups"), list) else []
    buckets = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        display = str(group.get("displayName") or "").lower()
        if "gemini" in display:
            family = "gemini"
        elif any(name in display for name in ("claude", "gpt", "third")):
            family = "3p"
        else:
            continue
        for bucket in group.get("buckets") or []:
            if not isinstance(bucket, dict) or bucket.get("disabled") is True:
                continue
            cadence = " ".join(str(bucket.get(key) or "") for key in
                               ("window", "bucketId", "displayName")).lower().replace("_", "-")
            if any(marker in cadence for marker in ("weekly", "week", "7d")):
                cadence_id = "weekly"
            elif any(marker in cadence for marker in ("5h", "5-hour", "five hour",
                                                       "five-hour", "session")):
                cadence_id = "5h"
            else:
                continue
            buckets.setdefault(f"{family}-{cadence_id}", bucket)
    rows = []
    # Match the official shared quota groups, never individual model variants.
    # Missing windows stay unknown; a model quota cannot stand in for a week.
    if buckets:
        for bucket_id, title, minutes in _ANTIGRAVITY_QUOTA_WINDOWS:
            bucket = buckets.get(bucket_id, {})
            # Connect JSON flattens the oneof; older clients wrap `remaining`.
            remaining = _antigravity_remaining(bucket)
            if remaining is None:
                remaining = _antigravity_remaining(bucket.get("remaining"))
            rows.append(_provider_window(
                "antigravity-" + bucket_id, title,
                (1 - remaining) * 100 if remaining is not None else None,
                bucket.get("resetTime"), minutes,
                "暂时无法读取" if remaining is None else None,
                usage_known=remaining is not None))
    return {
        "available": bool(rows),
        "plan": None, "account": None, "windows": rows, "details": [],
        "source": "antigravity-local",
        "updated": int(updated if updated is not None else datetime.now().timestamp()),
        "stale": False,
    }


def _antigravity_user_identity(payload):
    if not isinstance(payload, dict):
        return {}
    status = payload.get("userStatus") if isinstance(payload.get("userStatus"), dict) else payload
    tier = status.get("userTier") if isinstance(status.get("userTier"), dict) else {}
    plan_status = status.get("planStatus") if isinstance(status.get("planStatus"), dict) else {}
    plan_info = plan_status.get("planInfo") if isinstance(plan_status.get("planInfo"), dict) else {}
    plan = next((value.strip() for value in (
        tier.get("name"), plan_info.get("planName"), plan_info.get("planDisplayName"),
        plan_info.get("displayName"), plan_info.get("productName"),
        plan_info.get("planShortName")) if isinstance(value, str) and value.strip()), None)
    account = status.get("email") if isinstance(status.get("email"), str) else None
    return {"plan": plan, "account": account}


def fetch_antigravity_quota():
    paths = {
        "summary": "/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary",
        "status": "/exa.language_server_pb.LanguageServerService/GetUserStatus",
    }
    metadata = {"metadata": {
        "ideName": "antigravity", "extensionName": "antigravity",
        "ideVersion": "unknown", "locale": "en",
    }}
    last_error = None
    for process in _antigravity_running_processes():
        endpoints = _antigravity_endpoints(process)
        if not endpoints:
            continue
        marker = _provider_credential_marker(
            "antigravity", "quota-summary-v3", process.get("pid"),
            process.get("csrf_token"), endpoints)
        cached = _cached_provider_quota("antigravity", marker, _PROVIDER_QUOTA_TTL)
        if cached:
            return cached
        for endpoint in endpoints:
            try:
                summary_payload = _antigravity_request(
                    endpoint, paths["summary"], {"forceRefresh": True})
                quota = _normalize_antigravity_quota_summary(summary_payload)
                if quota.get("available"):
                    try:
                        identity_payload = _antigravity_request(endpoint, paths["status"], metadata)
                        identity = _antigravity_user_identity(identity_payload)
                        quota["plan"] = identity.get("plan")
                        quota["account"] = identity.get("account")
                    except Exception:
                        pass
                    _save_provider_quota_cache("antigravity", marker, quota)
                    return quota
            except Exception as error:
                last_error = error
        fallback = _cached_provider_quota(
            "antigravity", marker, _PROVIDER_QUOTA_FALLBACK_TTL, stale=True)
        if fallback:
            return fallback
    if last_error:
        raise last_error
    return {}


def scan_antigravity_quota():
    return fetch_antigravity_quota() if _provider_quota_enabled("antigravity") else {}


# ---------- Devin（桌面端保存的套餐）----------
# Devin.app 是改名后的 Windsurf 编辑器，本质是一个 VS Code fork，因此它的
# globalStorage 就是一个普通 SQLite 文件，账号最近一次读到的套餐是其中一行。
# 不需要任何凭据、不联网、不碰 Keychain，也不需要完全磁盘访问权限。
_DEVIN_PLAN_KEY_PATTERNS = (
    "windsurf.reactSettings.cachedPlanInfoData%",
    "windsurf.settings.cachedPlanInfo%",
)
# 这一行是「启动时」写入的，不是运行中持续刷新的。所以读数的落款是那次启动，
# 超过这个时长就按快照展示（卡片上会写“额度数据已过期”）而不是当作实时值。
_DEVIN_SNAPSHOT_FRESH = 10 * 60
# 超过一天没重启过，这行数据不再展示：解法就是打开 Devin，那会写入新的一行。
_DEVIN_SNAPSHOT_MAX_AGE = 24 * 60 * 60


def _devin_support_dir():
    """含 state.vscdb 的支持目录，取最新的一个。"""
    best = None
    for root in DEVIN_SUPPORT_DIRS:
        if not os.path.isfile(os.path.join(root, "User", "globalStorage", "state.vscdb")):
            continue
        try:
            stamp = os.path.getmtime(root)
        except OSError:
            stamp = 0.0
        if best is None or stamp > best[0]:
            best = (stamp, root)
    return best[1] if best else None


def _devin_launch_stamp(name):
    """logs/ 下每次运行建一个目录，目录名就是启动时刻：20260914T092003（本地时区）。

    用目录名而不是目录的修改时间：修改时间会往后跑——在已有文件里追加不动它，
    但会话进行一小时后新建的日志文件会把它顶上去，顶上去多少分钟，卡片就把
    这份自启动起就没变过的读数少算多少分钟。
    """
    if not isinstance(name, str) or len(name) != 15:
        return None
    try:
        parsed = datetime.strptime(name, "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    if parsed.strftime("%Y%m%dT%H%M%S") != name:
        return None
    return parsed.astimezone()


def _devin_last_launch(support):
    logs = os.path.join(support, "logs")
    try:
        entries = os.listdir(logs)
    except OSError:
        return None
    newest = None
    for name in entries:
        if not os.path.isdir(os.path.join(logs, name)):
            continue
        stamp = _devin_launch_stamp(name)
        if stamp is not None and (newest is None or stamp > newest):
            newest = stamp
    return newest


def _devin_plan(db_path):
    """(套餐, 本机账号行数)。

    一台机器上登录过两个账号就会有两行，而文件里没有任何字段说明哪个是当前的。
    取 endTimestamp 最远的一行：还在订阅期内的套餐优先于已过期的。
    """
    import sqlite3 as _sq

    rows = []
    conn = None
    try:
        conn = _sq.connect(_sqlite_ro_uri(db_path), uri=True, timeout=1)
        conn.execute("PRAGMA query_only=ON")
        for pattern in _DEVIN_PLAN_KEY_PATTERNS:
            found = list(conn.execute(
                "SELECT key, value FROM ItemTable WHERE key LIKE ?", (pattern,)))
            if found:
                rows = found
                break
    except Exception:
        return None, 0
    finally:
        if conn is not None:
            conn.close()

    best = None
    parsed_rows = 0
    for _key, value in rows:
        if isinstance(value, (bytes, bytearray)):
            try:
                value = bytes(value).decode("utf-8")
            except UnicodeDecodeError:
                continue
        try:
            plan = json.loads(value)
        except (TypeError, ValueError):
            continue
        if not isinstance(plan, dict):
            continue
        parsed_rows += 1
        end = _provider_number(plan.get("endTimestamp")) or 0.0
        if best is None or end > best[0]:
            best = (end, plan)
    return (best[1] if best else None), parsed_rows


def _devin_plan_number(plan, field):
    """布尔值也是数字类型的一种，True 会被读成 1。hideDailyQuota 走到这里会
    变成 1%，所以布尔一律不当数字。"""
    value = plan.get(field)
    return None if isinstance(value, bool) else _provider_number(value)


def _normalize_devin_plan(plan, launched_at, now=None, accounts=1):
    """一行缓存的套餐在 now 时刻意味着什么。

    没有可信落款的快照不展示，而不是拿抓取时刻替它落款：数据库自身的修改时间
    被文件里其它每一个键刷新着，早餐时读到的数会显示成一秒前的。
    """
    now = int(now if now is not None else datetime.now().timestamp())
    launched = int(launched_at.timestamp()) if launched_at is not None else None
    if launched is None or launched > now or now - launched > _DEVIN_SNAPSHOT_MAX_AGE:
        return {}

    windows = []
    # Devin 自己同时给出两个百分比和两个重置时刻，所以 used = 100 - remaining，
    # 窗口长度也用它真的给了的那个，没有一处是推算出来的。
    for field, reset_field, hide_field, window_id, title, minutes in (
        ("dailyRemainingPercent", "dailyResetAtUnix", "hideDailyQuota",
         "devin-daily", "日额度", 1440),
        ("weeklyRemainingPercent", "weeklyResetAtUnix", "hideWeeklyQuota",
         "devin-weekly", "周额度", 10080),
    ):
        if plan.get(hide_field):
            continue
        remaining = _devin_plan_number(plan, field)
        if remaining is None:
            # 不报日额度的套餐就不画这个环，而不是画一个满环。
            continue
        reset = _provider_epoch(plan.get(reset_field))
        # 重置时刻已经过去的窗口直接丢掉而不是继续挂着：那个数字属于一个
        # 已经不存在的窗口。另一个窗口和余额（本来就没有重置）照常保留。
        if reset is not None and reset <= now:
            continue
        windows.append(_provider_window(window_id, title, 100 - remaining, reset, minutes))

    # 免费套餐给的是一池消息数。-1 是付费套餐表示「不适用」的写法，不是计数，
    # 按计数读会画出「负一分之负一」，所以任一端为负都按没有这项处理。
    total = _devin_plan_number(plan, "totalMessages")
    remaining_messages = _devin_plan_number(plan, "remainingMessages")
    if (total is not None and remaining_messages is not None
            and total > 0 and remaining_messages >= 0):
        windows.append(_provider_window(
            "devin-messages", "消息额度",
            (total - remaining_messages) / total * 100, None, None,
            f"剩余 {int(remaining_messages):,} / {int(total):,} 条"))

    details = []
    # 字段名就写了是 micros：10,000,000 即十美元。
    balance = _devin_plan_number(plan, "overageBalanceMicros")
    if balance is not None:
        details.append({"label": "超额余额", "value": _provider_money(balance / 1_000_000)})
    if accounts > 1:
        details.append({"label": "本机账号", "value": f"{accounts} 个",
                        "secondary": "取订阅期最长的一个"})

    if not windows and not details:
        return {}

    plan_name = plan.get("planName")
    plan_name = plan_name.strip() if isinstance(plan_name, str) and plan_name.strip() else None
    # 这一行自己带了人类可读的账号（实测形如 "someone@example.com - My Team"），
    # 比键里那串 user-<32 hex> 有用得多；没有就留空，不拿那串 id 顶上。
    account = plan.get("accountIdentityText")
    account = account.strip() if isinstance(account, str) and account.strip() else None
    return {
        "available": True,
        "plan": f"Devin {plan_name}" if plan_name else None,
        "account": account,
        "windows": windows,
        "details": details,
        "source": "devin-app-cache",
        "updated": launched,
        "stale": now - launched > _DEVIN_SNAPSHOT_FRESH,
    }


def fetch_devin_quota():
    support = _devin_support_dir()
    if not support:
        return {}
    plan, accounts = _devin_plan(
        os.path.join(support, "User", "globalStorage", "state.vscdb"))
    if not plan:
        return {}
    return _normalize_devin_plan(plan, _devin_last_launch(support), accounts=accounts)


def scan_devin_quota():
    return fetch_devin_quota() if _provider_quota_enabled("devin") else {}


def scan_provider_quotas(errors=None):
    from concurrent.futures import ThreadPoolExecutor, as_completed

    all_scans = {
        "zed": scan_zed_quota,
        "sub2api": scan_sub2api_quota,
        "zai": scan_zai_quota,
        "antigravity": scan_antigravity_quota,
        "devin": scan_devin_quota,
    }
    result = {name: {} for name in (*all_scans, "cursor", "grok_bot")}
    scans = {name: scan for name, scan in all_scans.items()
             if _provider_quota_enabled(name)}
    cursor_enabled = _provider_quota_enabled("cursor")
    grok_bot_enabled = _provider_quota_enabled("grok_bot")
    if cursor_enabled or grok_bot_enabled:
        def cursor_bundle():
            session = _cursor_session()
            cursor_quota = fetch_cursor_quota(session) \
                if cursor_enabled and session else {}
            # Native Grok Bot authorization is always tried first. Its own
            # fallback can reuse Cursor when the native login is unavailable.
            grok_bot_quota = fetch_grok_bot_quota() if grok_bot_enabled else {}
            return cursor_quota, grok_bot_quota
        scans["cursor_bundle"] = cursor_bundle
    if not scans:
        return result
    with ThreadPoolExecutor(max_workers=len(scans), thread_name_prefix="tokei-quota") as pool:
        futures = {pool.submit(scan): name for name, scan in scans.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                value = future.result()
                if name == "cursor_bundle":
                    cursor_quota, grok_bot_quota = value
                    if cursor_enabled:
                        result["cursor"] = cursor_quota
                    if grok_bot_enabled:
                        result["grok_bot"] = grok_bot_quota
                else:
                    result[name] = value if isinstance(value, dict) else {}
            except Exception as error:
                if errors is not None:
                    error_name = "cursor" if name == "cursor_bundle" else name
                    errors[f"{error_name}_quota"] = f"{type(error).__name__}: {error}"
    return result


def scan_grok(bounds, cache=None):
    ledger_touch("grok")
    cache = cache if cache is not None else {"v": _SCAN_CACHE_VERSION}
    file_cache = cache.setdefault("grok", {})
    B = {k: {"tokens": 0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0,
             "cost": 0.0, "models": {}, "usage_sessions": set(), "usage_calls": 0,
             "sessions": set(), "turns": 0, "tools": 0,
             "duration": 0, "ctx_used": 0, "ctx_window": 0, "errors": 0,
             "cancellations": 0, "ttft_sum": 0, "response_sum": 0, "latency_count": 0}
         for k in RANGE_KEYS}
    latest_mtime = -1
    latest_model = None
    summary_paths = (sorted(glob.glob(os.path.join(GROK_DIR, "*", "*", "summary.json")))
                     if os.path.isdir(GROK_DIR) else [])
    stale = set(file_cache)
    for summary_path in summary_paths:
        stale.discard(summary_path)
        session_dir = os.path.dirname(summary_path)
        related = [
            summary_path,
            os.path.join(session_dir, "signals.json"),
            os.path.join(session_dir, "updates.jsonl"),
            os.path.join(session_dir, "events.jsonl"),
        ]
        signature = _grok_file_signature(related)
        try:
            mtime_ns = os.stat(summary_path).st_mtime_ns
        except OSError:
            continue
        existing = file_cache.get(summary_path)
        if isinstance(existing, dict) and existing.get("sig") == signature:
            continue
        parsed = _load_grok_session(summary_path, signature, mtime_ns)
        if parsed is None:
            if summary_path in file_cache:
                file_cache.pop(summary_path, None)
                cache["_dirty"] = True
            continue
        file_cache[summary_path] = parsed
        cache["_dirty"] = True

    for summary_path in stale:
        file_cache.pop(summary_path, None)
        cache["_dirty"] = True

    sessions = {}
    for path, entry in file_cache.items():
        if not isinstance(entry, dict):
            continue
        sid = entry.get("sid") or path
        current = sessions.get(sid)
        if current is None or int(entry.get("mtime", 0)) > int(current.get("mtime", 0)):
            sessions[sid] = entry

    metrics = ("tokens", "turns", "tools", "duration", "ctx_used", "ctx_window",
               "errors", "cancellations", "ttft_sum", "response_sum", "latency_count")
    for sid, entry in sessions.items():
        day_key = entry.get("date")
        try:
            day_date = date.fromisoformat(day_key)
        except (TypeError, ValueError):
            continue
        mtime = int(entry.get("mtime", 0) or 0)
        if mtime > latest_mtime:
            latest_mtime = mtime
            latest_model = entry.get("model") or "unknown"
        for range_key in classify_date(day_date, bounds):
            bucket = B[range_key]
            bucket["sessions"].add(sid)
            for field in metrics:
                bucket[field] += int(entry.get(field, 0) or 0)

    usage_days = _grok_usage_days(_load_grok_usage_records(cache), sessions, latest_model)
    # 会话数只能来自现存日志(被清日志无从归属)
    for day_key, day in usage_days.items():
        try:
            day_date = date.fromisoformat(day_key)
        except ValueError:
            continue
        for range_key in classify_date(day_date, bounds):
            bucket = B[range_key]
            bucket["usage_sessions"].update(day.get("sessions", set()))
            bucket["sessions"].update(day.get("sessions", set()))

    # sessions(set)/projects(含嵌套 set)不进账本,只保留 JSON 兼容字段
    grok_live_days = {
        day_key: {k: v for k, v in day.items() if k not in ("sessions", "projects")}
        for day_key, day in usage_days.items()}
    for day_key, day in ledger_reconcile("grok", grok_live_days).items():
        try:
            day_date = date.fromisoformat(day_key)
        except ValueError:
            continue
        for range_key in classify_date(day_date, bounds):
            bucket = B[range_key]
            _add_token_usage(bucket, day.get("in", 0), day.get("out", 0),
                             day.get("cr", 0), 0, day.get("reason", 0), day.get("cost", 0), cost_cny=day.get("cost_cny", 0))
            for model, usage in (day.get("models") or {}).items():
                _add_model_usage(bucket["models"], model, usage.get("in", 0),
                                 usage.get("out", 0), usage.get("cr", 0), 0,
                                 usage.get("reason", 0), usage.get("cost", 0))
            bucket["usage_calls"] += int(day.get("calls", 0) or 0)
    return {"ranges": B, "model": latest_model, "days": usage_days}


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
    ledger_touch("qoderwork")
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
                # 只统计 assistant 行:user 行也可能带 metadata,会虚增任务数
                for row in conn.execute("""
                    SELECT date(created_at,'unixepoch','localtime') as day,
                           COUNT(*) as calls,
                           COUNT(DISTINCT chat_id) as sessions,
                           COALESCE(SUM(json_extract(metadata,'$.inputTokens')),0),
                           COALESCE(SUM(json_extract(metadata,'$.outputTokens')),0),
                           COALESCE(SUM(json_extract(metadata,'$.durationMs')),0),
                           COALESCE(SUM(json_extract(metadata,'$.numTurns')),0)
                    FROM messages WHERE metadata!='{}' AND role='assistant'
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
                    FROM messages WHERE metadata!='{}' AND role='assistant'
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

    # 天级整取整用:sub_chats 计数并入 day dict,连同会话计数一起进账本
    live_days = {}
    for dk, db_day in db_days.items():
        day = dict(db_day)
        day["sub_agents"] = int(sub_chat_days.get(dk, 0) or 0)
        live_days[dk] = day

    for dk, day in ledger_reconcile("qoderwork", live_days).items():
        try:
            d = date.fromisoformat(dk)
        except ValueError:
            continue
        ks = classify_date(d, bounds)
        if not ks:
            continue

        calls = day.get("calls", 0)
        sessions = day.get("sessions", 0)
        duration = day.get("duration", 0)
        turns = day.get("turns", 0)
        ctx_ratio = day.get("ctx_ratio", 0)

        for k in ks:
            b = B[k]
            b["in"] += day.get("in", 0); b["out"] += day.get("out", 0)
            b["sessions"] += sessions; b["calls"] += calls
            b["sub_agents"] += day.get("sub_agents", 0)
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

    ledger_touch("qoder_ide")
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
    # 仅 enabled 且正常扫描才会走到这里,disabled 分支在上方早已返回,绝不触碰账本
    B = {k: {"in": 0, "out": 0, "cached": 0, "sessions": 0, "sub_agents": 0,
             "calls": 0, "messages": 0, "duration": 0} for k in RANGE_KEYS}
    session_sets = {k: set() for k in RANGE_KEYS}
    sub_agent_sets = {k: set() for k in RANGE_KEYS}

    for dk, day in ledger_reconcile("qoder_ide", entry.get("days", {})).items():
        try:
            d = date.fromisoformat(dk)
        except ValueError:
            continue
        for k in classify_date(d, bounds):
            b = B[k]
            b["in"] += day.get("in", 0)
            b["out"] += day.get("out", 0)
            b["cached"] += day.get("cached", 0)
            b["calls"] += day.get("calls", 0)
            b["messages"] += day.get("messages", 0)
            b["duration"] += day.get("duration", 0)
            for sid in day.get("session_ids") or []:
                session_sets[k].add(sid)
            for sid in day.get("sub_agent_ids") or []:
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
        conn = _sq.connect(_sqlite_ro_uri(db_path), uri=True)
        conn.row_factory = _sq.Row

        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "sessions" not in tables:
            conn.close()
            return days

        def columns(table):
            return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}

        def expr(alias, available, name, fallback="0"):
            if name in available:
                return f'{alias}."{name}"'
            return fallback

        session_columns = columns("sessions")
        session_query = f"""
            SELECT s.id AS session_id,
                   {expr('s', session_columns, 'started_at')} AS started_at,
                   {expr('s', session_columns, 'model', "''")} AS model,
                   {expr('s', session_columns, 'cwd', "''")} AS cwd,
                   {expr('s', session_columns, 'input_tokens')} AS input_tokens,
                   {expr('s', session_columns, 'output_tokens')} AS output_tokens,
                   {expr('s', session_columns, 'cache_read_tokens')} AS cache_read_tokens,
                   {expr('s', session_columns, 'cache_write_tokens')} AS cache_write_tokens,
                   {expr('s', session_columns, 'reasoning_tokens')} AS reasoning_tokens,
                   {expr('s', session_columns, 'estimated_cost_usd')} AS estimated_cost_usd,
                   {expr('s', session_columns, 'actual_cost_usd', 'NULL')} AS actual_cost_usd
            FROM sessions s
        """
        sessions = {row["session_id"]: dict(row) for row in conn.execute(session_query)}

        # Hermes 0.19 / schema v22 会把旧表改名为 session_model_usage_v21，再创建
        # 带 task 维度的新表。旧库含孤立用量行时迁移会被外键约束中断，两张表会
        # 同时保留；因此两张都读，并按完整主键去重。
        usage_rows = {}
        for table in ("session_model_usage_v21", "session_model_usage"):
            if table not in tables:
                continue
            usage_columns = columns(table)
            if "session_id" not in usage_columns:
                continue
            usage_query = f"""
                SELECT u.session_id AS session_id,
                       {expr('u', usage_columns, 'model', "''")} AS model,
                       {expr('u', usage_columns, 'billing_provider', "''")} AS billing_provider,
                       {expr('u', usage_columns, 'billing_base_url', "''")} AS billing_base_url,
                       {expr('u', usage_columns, 'billing_mode', "''")} AS billing_mode,
                       {expr('u', usage_columns, 'task', "''")} AS task,
                       {expr('u', usage_columns, 'input_tokens')} AS input_tokens,
                       {expr('u', usage_columns, 'output_tokens')} AS output_tokens,
                       {expr('u', usage_columns, 'cache_read_tokens')} AS cache_read_tokens,
                       {expr('u', usage_columns, 'cache_write_tokens')} AS cache_write_tokens,
                       {expr('u', usage_columns, 'reasoning_tokens')} AS reasoning_tokens,
                       {expr('u', usage_columns, 'estimated_cost_usd')} AS estimated_cost_usd,
                       {expr('u', usage_columns, 'actual_cost_usd', 'NULL')} AS actual_cost_usd,
                       {expr('u', usage_columns, 'first_seen', 'NULL')} AS first_seen,
                       {expr('u', usage_columns, 'last_seen', 'NULL')} AS last_seen
                FROM "{table}" u
            """
            for row in conn.execute(usage_query):
                item = dict(row)
                key = tuple(item.get(name) or "" for name in (
                    "session_id", "model", "billing_provider", "billing_base_url",
                    "billing_mode", "task"))
                previous = usage_rows.get(key)
                if previous and token_total({
                    "in": previous.get("input_tokens", 0),
                    "out": previous.get("output_tokens", 0),
                    "cr": previous.get("cache_read_tokens", 0),
                    "cw": previous.get("cache_write_tokens", 0),
                    "reason": previous.get("reasoning_tokens", 0),
                }) > token_total({
                    "in": item.get("input_tokens", 0),
                    "out": item.get("output_tokens", 0),
                    "cr": item.get("cache_read_tokens", 0),
                    "cw": item.get("cache_write_tokens", 0),
                    "reason": item.get("reasoning_tokens", 0),
                }):
                    continue
                usage_rows[key] = item

        records = list(usage_rows.values())
        main_usage_sessions = {
            row.get("session_id") for row in records if not (row.get("task") or "")}

        # 没有用量明细表或主循环明细缺失时，回退到 sessions 汇总。这样既兼容
        # 老版本，也不会把 v22 的主循环行与 sessions 再算一次。
        for session_id, session in sessions.items():
            if session_id in main_usage_sessions:
                continue
            records.append({
                **session,
                "task": "",
                "first_seen": session.get("started_at"),
                "last_seen": session.get("started_at"),
            })

        def row_cost(row):
            actual = row.get("actual_cost_usd")
            return float(actual if actual is not None else row.get("estimated_cost_usd", 0) or 0)

        records_by_session = {}
        for row in records:
            records_by_session.setdefault(row.get("session_id"), []).append(row)
        for session_id, session_records in records_by_session.items():
            session = sessions.get(session_id)
            if not session or any(row_cost(row) for row in session_records):
                continue
            fallback_cost = row_cost(session)
            if not fallback_cost:
                continue
            main_records = [row for row in session_records if not (row.get("task") or "")]
            if not main_records:
                continue
            target = next(
                (row for row in main_records if row.get("model") == session.get("model")),
                main_records[0],
            )
            target["actual_cost_usd"] = session.get("actual_cost_usd")
            target["estimated_cost_usd"] = session.get("estimated_cost_usd")

        session_first_seen = {}
        for row in records:
            session_id = row.get("session_id")
            if not session_id:
                continue
            session = sessions.get(session_id) or {}
            timestamp = session.get("started_at") or row.get("first_seen") or row.get("last_seen")
            try:
                timestamp = float(timestamp)
                if timestamp > 100_000_000_000:
                    timestamp /= 1000.0
            except (TypeError, ValueError):
                continue
            if timestamp <= 0:
                continue
            session_first_seen[session_id] = min(
                timestamp, session_first_seen.get(session_id, timestamp))

        day_sessions = {}
        for row in records:
            session_id = row.get("session_id")
            timestamp = session_first_seen.get(session_id)
            if timestamp is None:
                continue
            local_dt = datetime.fromtimestamp(timestamp).astimezone()
            dk = local_dt.date().isoformat()
            day = days.setdefault(dk, {"in": 0, "out": 0, "cr": 0, "cw": 0,
                                       "reason": 0, "cost": 0.0, "sessions": 0,
                                       "models": {}, "hours": [0] * 24})
            inp = int(row.get("input_tokens") or 0)
            out = int(row.get("output_tokens") or 0)
            cr = int(row.get("cache_read_tokens") or 0)
            cw = int(row.get("cache_write_tokens") or 0)
            reason = int(row.get("reasoning_tokens") or 0)
            _add_token_usage(day, inp, out, cr, cw, reason, row_cost(row),
                             _model_identity_id(row.get("model")))
            day["hours"][local_dt.hour] += inp + out + cr + cw + reason
            if session_id in sessions:
                day_sessions.setdefault(dk, set()).add(session_id)
            workdir = (sessions.get(session_id) or {}).get("cwd")
            if isinstance(workdir, str) and workdir.startswith("/"):
                bucket = day.setdefault("projects", {}).setdefault(
                    workdir, {"tokens": 0, "cost": 0.0, "models": {}, "sessions": []})
                total = inp + out + cr + cw + reason
                bucket["tokens"] += total
                bucket["cost"] += row_cost(row)
                model_id = _model_identity_id(row.get("model")) or "unknown"
                bucket["models"][model_id] = bucket["models"].get(model_id, 0) + total
                if session_id and session_id not in bucket["sessions"]:
                    bucket["sessions"].append(str(session_id))

        for dk, session_ids in day_sessions.items():
            days[dk]["sessions"] = len(session_ids)
        conn.close()
    except Exception:
        pass
    return days


# ---------- Qoder CLI ----------
# Qoder CLI 与新版 Qoder App 共用 ~/.qoder/projects Agent transcript。
# 旧 Qoder Desktop 的 transcript/ 镜像由 local.db 统计，不进入此采集器。
_QODERCLI_DIR = os.path.join(HOME, ".qoder", "projects")
_QODERCLI_PARSER_VERSION = 2
_QODERCLI_LEDGER_VERSION = 1


def _prepare_qodercli_ledger():
    ledger = _load_ledger()
    if ledger.get("qodercli_schema") == _QODERCLI_LEDGER_VERSION:
        return
    ledger.setdefault("tools", {})["qodercli"] = {}
    ledger["qodercli_schema"] = _QODERCLI_LEDGER_VERSION
    _LEDGER_CACHE["dirty"] = True


def _qodercli_dir():
    return os.path.abspath(os.path.expanduser(
        os.environ.get("TOKEI_QODERCLI_DIR", _QODERCLI_DIR)))


def _empty_qodercli():
    ranges = {k: {"in": 0, "out": 0, "cr": 0, "cw": 0, "credits": 0.0,
                  "usage_calls": 0, "usage_available": False,
                  "sessions": 0, "calls": 0, "sub_agents": 0,
                  "duration": 0, "turns": 0, "tools": 0, "est": 0,
                  "ctx_sum": 0.0, "ctx_count": 0, "models": {}}
              for k in RANGE_KEYS}
    return {"ranges": ranges, "model": None}


def _est_tokens(text):
    """CJK 感知估算:汉字/全角 ≈1 token,其余字符 ≈1/4 token(英文 4 字符/token 经验值)。"""
    if not text:
        return 0.0
    cjk = sum(1 for ch in text if "\u3000" <= ch <= "\u9fff" or "\uff00" <= ch <= "\uffef")
    return cjk + (len(text) - cjk) / 4


def _qodercli_int(value):
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _qodercli_usage(message):
    usage = message.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    raw_in = _qodercli_int(usage.get("input_tokens"))
    cr = _qodercli_int(usage.get("cache_read_input_tokens"))
    if "cache_creation_input_tokens" in usage:
        cw = _qodercli_int(usage.get("cache_creation_input_tokens"))
    else:
        cache_creation = usage.get("cache_creation") or {}
        cw = sum(_qodercli_int(cache_creation.get(key)) for key in (
            "ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens"))
    out = _qodercli_int(usage.get("output_tokens"))
    inp = max(raw_in - cr - cw, 0)
    credit_value = usage.get("credits")
    if credit_value is None:
        credit_value = usage.get("original_credits")
    try:
        credits = max(float(credit_value or 0), 0.0)
    except (TypeError, ValueError):
        credits = 0.0
    request_id = usage.get("request_id")
    return {"in": inp, "out": out, "cr": cr, "cw": cw, "credits": credits,
            "usage_available": raw_in + out + cr + cw > 0,
            "request_id": str(request_id) if request_id else None}


def _merge_qodercli_event(existing, candidate):
    if existing is None:
        return dict(candidate)
    existing_tokens = sum(existing.get(key, 0) for key in ("in", "out", "cr", "cw"))
    candidate_tokens = sum(candidate.get(key, 0) for key in ("in", "out", "cr", "cw"))
    merged = dict(candidate if candidate_tokens > existing_tokens else existing)
    other = existing if candidate_tokens > existing_tokens else candidate
    merged["credits"] = max(float(existing.get("credits", 0) or 0),
                              float(candidate.get("credits", 0) or 0))
    merged["tools"] = sorted(set(existing.get("tools") or []) | set(candidate.get("tools") or []))
    merged["est"] = max(float(existing.get("est", 0) or 0),
                         float(candidate.get("est", 0) or 0))
    merged["usage_available"] = bool(
        existing.get("usage_available") or candidate.get("usage_available"))
    if not merged.get("model"):
        merged["model"] = other.get("model")
    return merged


def _parse_qodercli_file(path):
    """解析单个 Qoder Agent transcript，保留请求事件供跨文件去重。"""
    days = {}
    responses = {}
    message_requests = {}
    model = None
    prev_ts = None
    with open(path, "r", errors="replace") as f:
        for line_number, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            typ = row.get("type")
            if typ == "runtime-config":
                configured_model = row.get("model")
                if configured_model:
                    model = configured_model
                continue
            if typ not in ("user", "assistant"):
                continue
            dt = parse_ts(row.get("timestamp") or "")
            if dt is None:
                continue
            dt = dt.astimezone()
            dk = dt.date().isoformat()
            day = days.setdefault(dk, {"turns": 0, "est": 0.0, "active": 0.0})
            ts = dt.timestamp()
            if prev_ts is not None:
                gap = ts - prev_ts
                if 0 < gap <= 300:
                    day["active"] += gap
            prev_ts = ts
            message = row.get("message") or {}
            content = message.get("content")
            if typ == "assistant":
                usage = _qodercli_usage(message)
                message_id = message.get("id")
                row_id = row.get("uuid") or row.get("id")
                if usage["request_id"]:
                    response_id = usage["request_id"]
                    if message_id:
                        message_key = str(message_id)
                        prior = None if message_key in message_requests \
                            else responses.pop(message_key, None)
                        message_requests[message_key] = response_id
                    else:
                        prior = None
                elif message_id and str(message_id) in message_requests:
                    response_id = message_requests[str(message_id)]
                    prior = None
                else:
                    response_id = str(message_id or row_id or f"{path}:{line_number}")
                    prior = None
                assistant_est = 0.0
                tool_ids = set()
                if isinstance(content, list):
                    for index, block in enumerate(content):
                        if not isinstance(block, dict):
                            continue
                        block_type = block.get("type")
                        if block_type == "tool_use":
                            tool_ids.add(str(block.get("id") or f"{response_id}:{index}"))
                            try:
                                assistant_est += _est_tokens(json.dumps(
                                    block.get("input") or {}, ensure_ascii=False))
                            except (TypeError, ValueError):
                                pass
                        elif block_type == "text":
                            assistant_est += _est_tokens(block.get("text"))
                        elif block_type == "thinking":
                            assistant_est += _est_tokens(block.get("thinking"))
                event_model = message.get("model") or model
                if event_model:
                    model = event_model
                event = {"id": str(response_id), "day": dk, "hour": dt.hour,
                         "model": event_model, "est": assistant_est,
                         "tools": sorted(tool_ids), **usage}
                existing = responses.get(str(response_id))
                if prior is not None:
                    existing = _merge_qodercli_event(existing, prior)
                responses[str(response_id)] = _merge_qodercli_event(existing, event)
            elif not row.get("isMeta") and not row.get("isSidechain"):
                texts = []
                if isinstance(content, str):
                    texts = [content]
                elif isinstance(content, list):
                    texts = [block.get("text") for block in content
                             if isinstance(block, dict) and block.get("type") == "text"]
                texts = [text for text in texts if text and not text.startswith("<")]
                if texts:
                    day["turns"] += 1
                    day["est"] += sum(_est_tokens(text) for text in texts)
    return {"days": days, "responses": list(responses.values()), "model": model}


def _qodercli_usage_days(entries, use_cached=True):
    cached_days = entries.get("_usage_days")
    if use_cached and isinstance(cached_days, dict):
        return cached_days
    request_index = entries.get("_requests")
    if isinstance(request_index, dict):
        responses = request_index
    else:
        responses = {}
        for path, entry in entries.items():
            if path.startswith("_") or not isinstance(entry, dict):
                continue
            for event in entry.get("responses", []):
                event_id = event.get("id")
                if not event_id:
                    continue
                responses[event_id] = _merge_qodercli_event(
                    responses.get(event_id), event)

    days = {}
    for event in responses.values():
        dk = event.get("day")
        try:
            date.fromisoformat(dk)
        except (TypeError, ValueError):
            continue
        day = days.setdefault(dk, {"in": 0, "out": 0, "cr": 0, "cw": 0,
            "credits": 0.0, "usage_calls": 0, "calls": 0, "tools": 0,
            "est": 0, "duration": 0, "models": {}, "hours": [0] * 24,
            "_cost_version": _QODERCLI_LEDGER_VERSION})
        day["calls"] += 1
        day["tools"] += len(event.get("tools") or [])
        day["est"] += int(event.get("est", 0))
        day["credits"] += float(event.get("credits", 0.0) or 0.0)
        token_total = 0
        for field in ("in", "out", "cr", "cw"):
            value = int(event.get(field, 0) or 0)
            day[field] += value
            token_total += value
        if event.get("usage_available") and token_total > 0:
            day["usage_calls"] += 1
        hour = event.get("hour")
        if isinstance(hour, int) and 0 <= hour < 24:
            day["hours"][hour] += token_total
        model_name = event.get("model")
        if model_name and (token_total > 0 or event.get("credits", 0)):
            model_usage = day["models"].setdefault(model_name,
                {"in": 0, "out": 0, "cr": 0, "cw": 0, "credits": 0.0})
            for field in ("in", "out", "cr", "cw"):
                model_usage[field] += int(event.get(field, 0) or 0)
            model_usage["credits"] += float(event.get("credits", 0.0) or 0.0)
    return days


def scan_qodercli(bounds, cache):
    _prepare_qodercli_ledger()
    ledger_touch("qodercli")
    fc = cache.setdefault("qodercli", {})
    if fc.get("_parser") != _QODERCLI_PARSER_VERSION:
        fc.clear()
        fc["_parser"] = _QODERCLI_PARSER_VERSION
        fc["_requests"] = {}
        cache["_dirty"] = True
    request_index = fc.setdefault("_requests", {})
    root = _qodercli_dir()
    paths = []
    if os.path.isdir(root):
        paths = glob.glob(os.path.join(root, "*", "*.jsonl"))
        paths += glob.glob(os.path.join(root, "*", "*", "subagents", "*.jsonl"))
        paths = sorted(set(paths))

    stale = set(fc)
    for internal_key in ("_model", "_parser", "_requests", "_usage_days"):
        stale.discard(internal_key)
    latest_model = fc.get("_model")
    latest_mtime = -1
    for path in paths:
        stale.discard(path)
        try:
            st = os.stat(path)
        except OSError:
            continue
        sig = f"{st.st_size}|{st.st_mtime_ns}"
        entry = fc.get(path)
        if (isinstance(entry, dict) and entry.get("sig") == sig
                and entry.get("parser") == _QODERCLI_PARSER_VERSION):
            if entry.get("model") and st.st_mtime_ns > latest_mtime:
                latest_mtime = st.st_mtime_ns
                latest_model = entry["model"]
            continue
        try:
            parsed = _parse_qodercli_file(path)
        except OSError:
            continue
        for event in parsed["responses"]:
            event_id = event.get("id")
            if event_id:
                request_index[event_id] = _merge_qodercli_event(
                    request_index.get(event_id), event)
        fc[path] = {"sig": sig, "parser": _QODERCLI_PARSER_VERSION,
                    "days": parsed["days"], "model": parsed["model"],
                    "sub": (os.sep + "subagents" + os.sep) in path}
        cache["_dirty"] = True
        if parsed["model"] and st.st_mtime_ns > latest_mtime:
            latest_mtime = st.st_mtime_ns
            latest_model = parsed["model"]
    for path in stale:
        fc.pop(path, None)
        cache["_dirty"] = True
    if latest_model and fc.get("_model") != latest_model:
        fc["_model"] = latest_model
        cache["_dirty"] = True

    B = _empty_qodercli()["ranges"]
    live_days = _qodercli_usage_days(fc, use_cached=False)
    range_sessions = {key: set() for key in RANGE_KEYS}
    range_subagents = {key: set() for key in RANGE_KEYS}
    for path, entry in fc.items():
        if path.startswith("_") or not isinstance(entry, dict):
            continue
        is_sub = entry.get("sub", False)
        for dk, day in entry.get("days", {}).items():
            try:
                d = date.fromisoformat(dk)
            except ValueError:
                continue
            agg = live_days.setdefault(dk, {"in": 0, "out": 0, "cr": 0, "cw": 0,
                "credits": 0.0, "usage_calls": 0, "calls": 0, "tools": 0,
                "est": 0, "duration": 0, "models": {}, "hours": [0] * 24,
                "_cost_version": _QODERCLI_LEDGER_VERSION})
            agg["est"] += int(day.get("est", 0))
            agg["duration"] += int(day.get("active", 0.0) * 1000)
            for key in classify_date(d, bounds):
                if is_sub:
                    range_subagents[key].add(path)
                else:
                    range_sessions[key].add(path)
                    B[key]["turns"] += day.get("turns", 0)

    if fc.get("_usage_days") != live_days:
        fc["_usage_days"] = live_days
        cache["_dirty"] = True
    for key in RANGE_KEYS:
        B[key]["sessions"] = len(range_sessions[key])
        B[key]["sub_agents"] = len(range_subagents[key])
    for dk, day in ledger_reconcile("qodercli", live_days).items():
        try:
            d = date.fromisoformat(dk)
        except ValueError:
            continue
        for key in classify_date(d, bounds):
            target = B[key]
            for field in ("in", "out", "cr", "cw", "calls", "tools",
                          "usage_calls", "est", "duration"):
                target[field] += int(day.get(field, 0) or 0)
            target["credits"] += float(day.get("credits", 0.0) or 0.0)
            target["usage_available"] = target["usage_calls"] > 0
            for model_name, usage in (day.get("models") or {}).items():
                model_target = target["models"].setdefault(model_name,
                    {"in": 0, "out": 0, "cr": 0, "cw": 0, "credits": 0.0})
                for field in ("in", "out", "cr", "cw"):
                    model_target[field] += int(usage.get(field, 0) or 0)
                model_target["credits"] += float(usage.get("credits", 0.0) or 0.0)
    return {"ranges": B, "model": fc.get("_model")}


# 解析口径版本。加 1 可让旧缓存失效重扫（例如新增了按项目的用量拆分）。
_HERMES_SCAN_VERSION = 2


def scan_hermes(bounds, cache):
    import sqlite3 as _sq
    ledger_touch("hermes")
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
        sig = _sqlite_signature(db_path)
        if not sig:
            continue
        entry = fc.get(db_path)
        if (not entry or entry.get("sig") != sig
                or entry.get("version") != _HERMES_SCAN_VERSION):
            days = _scan_hermes_db(db_path, _sq)
            fc[db_path] = {"sig": sig, "days": days, "version": _HERMES_SCAN_VERSION}
            changed = True
    for p in stale:
        fc.pop(p, None)
        changed = True

    B = {k: {"in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "cost": 0.0,
             "sessions": 0, "models": {}} for k in RANGE_KEYS}
    live_days = {}
    for db_path, entry in fc.items():
        for dk, day in entry.get("days", {}).items():
            try:
                date.fromisoformat(dk)
            except ValueError:
                continue
            agg = live_days.setdefault(
                dk, {"in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0,
                     "cost": 0.0, "sessions": 0, "models": {}, "hours": [0] * 24})
            agg["in"] += day.get("in", 0); agg["out"] += day.get("out", 0)
            agg["cr"] += day.get("cr", 0); agg["cw"] += day.get("cw", 0)
            agg["reason"] += day.get("reason", 0); agg["cost"] += day.get("cost", 0)
            agg["sessions"] += day.get("sessions", 0)
            for mn, mv in (day.get("models") or {}).items():
                _add_model_usage(agg["models"], mn, mv.get("in", 0), mv.get("out", 0),
                                 mv.get("cr", 0), mv.get("cw", 0),
                                 mv.get("reason", 0), mv.get("cost", 0),
                                 cost_cny=mv.get("cost_cny", 0))
            for hour, amount in enumerate((day.get("hours") or [])[:24]):
                agg["hours"][hour] += amount

    for dk, day in ledger_reconcile("hermes", live_days).items():
        try:
            d = date.fromisoformat(dk)
        except ValueError:
            continue
        for k in classify_date(d, bounds):
            b = B[k]
            b["in"] += day.get("in", 0); b["out"] += day.get("out", 0)
            b["cr"] += day.get("cr", 0); b["cw"] += day.get("cw", 0)
            b["reason"] += day.get("reason", 0); b["cost"] += day.get("cost", 0)
            b["sessions"] += day.get("sessions", 0)
            for mn, mv in (day.get("models") or {}).items():
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
# 全局 SQLite: $OPENCLAW_STATE_DIR/state/openclaw.sqlite（任务 + agent DB 注册表）
# Agent SQLite: agent_databases.path -> transcript_events.event_json（新版 token 用量）
# Session JSONL: $OPENCLAW_STATE_DIR/agents/*/sessions/*.jsonl（旧版 token 用量）
_OPENCLAW_PARSER_VERSION = 2
_OPENCLAW_LEDGER_VERSION = 2


def _openclaw_db_paths():
    return [path for path in _path_candidates(
        "TOKEI_OPENCLAW_DB", OPENCLAW_STATE_DB, OPENCLAW_DB) if os.path.isfile(path)]


def _openclaw_connect(db_path, sqlite_module):
    conn = sqlite_module.connect(_sqlite_ro_uri(db_path), uri=True, timeout=1)
    conn.execute("PRAGMA query_only=ON")
    return conn


def _openclaw_task_db_path(sqlite_module):
    for path in _openclaw_db_paths():
        conn = None
        try:
            conn = _openclaw_connect(path, sqlite_module)
            found = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_runs'"
            ).fetchone()
            columns = ({row[1] for row in conn.execute("PRAGMA table_info(task_runs)")}
                       if found else set())
            if {"status", "created_at"}.issubset(columns):
                return path
        except Exception:
            continue
        finally:
            if conn is not None:
                conn.close()
    return None


def _scan_openclaw_db(db_path, sqlite_module):
    conn = _openclaw_connect(db_path, sqlite_module)
    try:
        task_days = {}
        for row in conn.execute("""
            SELECT date(created_at/1000,'unixepoch','localtime') as day,
                   COUNT(*) as total,
                   SUM(CASE WHEN lower(status) IN ('completed','succeeded','success') THEN 1 ELSE 0 END),
                   SUM(CASE WHEN lower(status) IN ('failed','error') THEN 1 ELSE 0 END)
            FROM task_runs WHERE created_at > 0
            GROUP BY day
        """):
            dk, total, completed, failed = row
            if dk:
                task_days[dk] = {"tasks": int(total or 0), "completed": int(completed or 0),
                                 "failed": int(failed or 0)}
        return task_days
    finally:
        conn.close()


def _openclaw_agent_db_paths(sqlite_module):
    """Discover agent databases from the global registry.

    OpenClaw stores registry paths relative to its state directory on current
    releases.  Absolute paths remain supported for compatible installations.
    The boolean result distinguishes an authoritative empty registry from a
    transient read failure so cached agent data is not discarded on lock/I/O
    errors.
    """
    read_failed = False
    for registry_path in _openclaw_db_paths():
        conn = None
        try:
            conn = _openclaw_connect(registry_path, sqlite_module)
            found = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_databases'"
            ).fetchone()
            if not found:
                continue
            columns = {row[1] for row in conn.execute("PRAGMA table_info(agent_databases)")}
            if "path" not in columns:
                continue
            root = os.path.dirname(os.path.realpath(os.path.abspath(OPENCLAW_AGENTS)))
            paths = []
            seen = set()
            for (raw_path,) in conn.execute("SELECT path FROM agent_databases"):
                if not isinstance(raw_path, str) or not raw_path.strip():
                    continue
                expanded = os.path.expandvars(os.path.expanduser(raw_path.strip()))
                resolved = expanded if os.path.isabs(expanded) else os.path.join(root, expanded)
                resolved = os.path.realpath(os.path.abspath(resolved))
                key = os.path.normcase(resolved)
                if key not in seen:
                    seen.add(key)
                    paths.append(resolved)
            return True, paths
        except Exception:
            read_failed = True
        finally:
            if conn is not None:
                conn.close()
    return not read_failed, []


def _openclaw_number(value):
    if isinstance(value, bool):
        return 0
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _openclaw_cost_number(value):
    if isinstance(value, bool):
        return 0.0
    try:
        return max(float(value or 0), 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _openclaw_token_total(usage):
    # OpenClaw's reasoningTokens is already included in output.
    return sum(usage.get(key, 0) for key in ("in", "out", "cr", "cw"))


def _openclaw_datetime(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value) / 1000 if value > 10_000_000_000 else float(value)
        try:
            return datetime.fromtimestamp(seconds).astimezone()
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        parsed = parse_ts(value)
        return parsed.astimezone() if parsed else None
    return None


def _openclaw_usage_record(event, created_at=None, session_model=None):
    if not isinstance(event, dict):
        return None
    message = event.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None

    # The persisted event timestamp is authoritative. created_at mirrors it on
    # current databases and is the stable fallback when optional JSON fields are
    # absent; message.timestamp can precede persistence by several seconds.
    occurred_at = (_openclaw_datetime(event.get("timestamp"))
                   or _openclaw_datetime(created_at)
                   or _openclaw_datetime(message.get("timestamp")))
    if occurred_at is None:
        return None

    inp = _openclaw_number(usage.get("input"))
    out = _openclaw_number(usage.get("output"))
    cr = _openclaw_number(usage.get("cacheRead"))
    cw = _openclaw_number(usage.get("cacheWrite"))
    reason = _openclaw_number(usage.get("reasoningTokens"))

    raw_model = next((candidate.strip() for candidate in (
        message.get("responseModel"), message.get("model"), session_model
    ) if isinstance(candidate, str) and candidate.strip()), "")
    model = _model_identity_id(raw_model) or raw_model or "unknown"

    cost_obj = usage.get("cost")
    if isinstance(cost_obj, dict):
        cost = _openclaw_cost_number(cost_obj.get("total"))
        if cost <= 0:
            cost = sum(_openclaw_cost_number(cost_obj.get(field)) for field in (
                "input", "output", "cacheRead", "cacheWrite"))
    else:
        cost = _openclaw_cost_number(cost_obj)
    pricing_id = _exact_pricing_id(model)
    if cost <= 0 and pricing_id:
        price = _raw_price(pricing_id)
        cost = (inp / 1e6 * price["in"] + out / 1e6 * price["out"]
                + cr / 1e6 * price["cache_read"] + cw / 1e6 * price["cache_write"])

    return {"date": occurred_at.date().isoformat(), "hour": occurred_at.hour,
            "in": inp, "out": out, "cr": cr, "cw": cw, "reason": reason,
            "cost": cost, "model": model}


def _openclaw_add_record(days, record):
    day = days.setdefault(record["date"], _empty_token_day())
    _add_token_usage(day, record["in"], record["out"], record["cr"], record["cw"],
                     record["reason"], record["cost"], record["model"])
    day["hours"][record["hour"]] += _openclaw_token_total(record)


def _openclaw_event_key(event, raw_event):
    event_id = event.get("id") if isinstance(event, dict) else None
    if isinstance(event_id, str) and event_id:
        return "id:" + event_id
    material = raw_event if isinstance(raw_event, str) else json.dumps(
        event, sort_keys=True, separators=(",", ":"))
    return "hash:" + hashlib.sha256(
        material.encode("utf-8", errors="surrogatepass")
    ).hexdigest()


def _scan_openclaw_agent_db(db_path, sqlite_module):
    conn = _openclaw_connect(db_path, sqlite_module)
    try:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if "transcript_events" not in tables:
            raise sqlite_module.OperationalError("missing transcript_events")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(transcript_events)")}
        if not {"session_id", "seq", "event_json", "created_at"}.issubset(columns):
            raise sqlite_module.OperationalError("incompatible transcript_events")

        session_models = {}
        if "session_windows" in tables:
            window_columns = {row[1] for row in conn.execute(
                "PRAGMA table_info(session_windows)"
            )}
            if {"session_id", "model"}.issubset(window_columns):
                session_models = {str(session_id): model for session_id, model in conn.execute(
                    "SELECT session_id, model FROM session_windows"
                )}

        sessions = {}
        seen_events = {}
        for session_id, seq, raw_event, created_at in conn.execute(
                "SELECT session_id, seq, event_json, created_at "
                "FROM transcript_events ORDER BY session_id, seq"):
            try:
                event = json.loads(raw_event)
            except (TypeError, ValueError):
                continue
            session_key = str(session_id)
            event_key = _openclaw_event_key(event, raw_event)
            session_seen = seen_events.setdefault(session_key, set())
            if event_key in session_seen:
                continue
            session_seen.add(event_key)
            record = _openclaw_usage_record(
                event, created_at, session_models.get(session_key))
            if record is None:
                continue
            session = sessions.setdefault(session_key, {"days": {}, "events": 0})
            _openclaw_add_record(session["days"], record)
            session["events"] += 1
        return sessions
    finally:
        conn.close()


def _scan_openclaw_jsonl(path):
    session_id = os.path.basename(path)[:-6]
    days = {}
    events = 0
    seen = set()
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if '"usage"' not in line and '"type"' not in line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if (event.get("type") == "session" and isinstance(event.get("id"), str)
                    and event["id"]):
                session_id = event["id"]
            event_key = _openclaw_event_key(event, line)
            if event_key in seen:
                continue
            seen.add(event_key)
            record = _openclaw_usage_record(event)
            if record is None:
                continue
            _openclaw_add_record(days, record)
            events += 1
    return session_id, {"days": days, "events": events}


def _openclaw_session_score(copy, source):
    token_count = sum(_openclaw_token_total(day) for day in copy.get("days", {}).values())
    return token_count, int(copy.get("events", 0)), 1 if source == "sqlite" else 0


def _openclaw_selected_sessions(tool_cache):
    selected = {}
    for entry_key, entry in tool_cache.items():
        if entry_key.startswith("_") or not isinstance(entry, dict):
            continue
        if entry.get("parser_version") != _OPENCLAW_PARSER_VERSION:
            continue
        source = entry.get("source")
        if source == "sqlite":
            copies = (entry.get("sessions") or {}).items()
        elif source == "jsonl":
            copies = [(entry.get("session_id") or entry_key, {
                "days": entry.get("days", {}), "events": entry.get("events", 0)})]
        else:
            continue
        for session_id, copy in copies:
            if not isinstance(copy, dict):
                continue
            session_key = str(session_id)
            score = _openclaw_session_score(copy, source)
            previous = selected.get(session_key)
            if previous is None or score > previous[0]:
                selected[session_key] = (score, copy)
    return {session_id: copy for session_id, (_, copy) in selected.items()}


def scan_openclaw(bounds, cache):
    import sqlite3 as _sq
    ledger_touch("openclaw")
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
             "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0,
             "cost": 0.0, "sessions": set(), "models": {}} for k in RANGE_KEYS}

    # --- Part 1: SQLite task counts ---
    db_path = _openclaw_task_db_path(_sq)
    if db_path:
        sig = _sqlite_signature(db_path)
        entry = fc.get("_db")
        if sig and (not entry or entry.get("path") != db_path or entry.get("sig") != sig):
            try:
                task_days = _scan_openclaw_db(db_path, _sq)
            except Exception:
                task_days = entry.get("days", {}) if entry and entry.get("path") == db_path else {}
            else:
                fc["_db"] = {"path": db_path, "sig": sig, "days": task_days}
                changed = True
        active_entry = fc.get("_db", {})
        if active_entry.get("path") != db_path:
            active_entry = {}
        for dk, day in active_entry.get("days", {}).items():
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

    # --- Part 2: dynamically discovered agent SQLite usage ---
    registry_ok, agent_db_paths = _openclaw_agent_db_paths(_sq)
    active_sqlite_keys = set()
    for agent_db_path in agent_db_paths:
        entry_key = "sqlite:" + os.path.realpath(agent_db_path)
        active_sqlite_keys.add(entry_key)
        sig = _sqlite_signature(agent_db_path)
        entry = fc.get(entry_key)
        needs_scan = (not entry or entry.get("parser_version") != _OPENCLAW_PARSER_VERSION
                      or entry.get("path") != agent_db_path or entry.get("sig") != sig)
        if sig and needs_scan:
            try:
                sessions = _scan_openclaw_agent_db(agent_db_path, _sq)
            except Exception:
                continue
            fc[entry_key] = {"source": "sqlite", "path": agent_db_path, "sig": sig,
                             "parser_version": _OPENCLAW_PARSER_VERSION,
                             "sessions": sessions}
            changed = True
    if registry_ok:
        for entry_key, entry in list(fc.items()):
            if (isinstance(entry, dict) and entry.get("source") == "sqlite"
                    and entry_key not in active_sqlite_keys):
                fc.pop(entry_key, None)
                changed = True

    # --- Part 3: legacy JSONL usage, excluding trajectory logs ---
    jsonl_files = set()
    if os.path.isdir(OPENCLAW_AGENTS):
        jsonl_files = {
            path for path in glob.glob(
                os.path.join(OPENCLAW_AGENTS, "*", "sessions", "*.jsonl"))
            if not path.endswith(".trajectory.jsonl")
        }
    for path in sorted(jsonl_files):
        try:
            stat = os.stat(path)
        except OSError:
            continue
        sig = f"{stat.st_mtime_ns}:{stat.st_size}"
        entry = fc.get(path)
        if (entry and entry.get("source") == "jsonl"
                and entry.get("parser_version") == _OPENCLAW_PARSER_VERSION
                and entry.get("sig") == sig):
            continue
        try:
            session_id, copy = _scan_openclaw_jsonl(path)
        except OSError:
            continue
        fc[path] = {"source": "jsonl", "sig": sig,
                    "parser_version": _OPENCLAW_PARSER_VERSION,
                    "session_id": session_id, "days": copy["days"],
                    "events": copy["events"]}
        changed = True

    for entry_key, entry in list(fc.items()):
        if entry_key.startswith("_") or not isinstance(entry, dict):
            continue
        is_jsonl = entry.get("source") == "jsonl" or (
            entry.get("source") is None and entry_key.endswith(".jsonl"))
        if is_jsonl and entry_key not in jsonl_files:
            fc.pop(entry_key, None)
            changed = True

    # Select one complete copy per logical session across SQLite/JSONL sources.
    live_days = {}
    live_sessions = {}
    selected_sessions = _openclaw_selected_sessions(fc)
    for session_id, copy in selected_sessions.items():
        for day_key, day in copy.get("days", {}).items():
            agg = live_days.setdefault(day_key, _empty_token_day())
            _merge_live_token_day(agg, day)
            live_sessions.setdefault(day_key, set()).add(session_id)
    for day in live_days.values():
        day["_ledger_version"] = _OPENCLAW_LEDGER_VERSION

    if fc.get("_selected_days") != live_days:
        fc["_selected_days"] = live_days
        changed = True

    # 会话数只来自现存 session 副本；账本无法可靠恢复被清日志的归属。
    for day_key, session_ids in live_sessions.items():
        try:
            day_date = date.fromisoformat(day_key)
        except ValueError:
            continue
        for range_key in _day_keys(day_date):
            B[range_key]["sessions"].update(session_ids)

    for dk, day in ledger_reconcile(
            "openclaw", live_days, _ledger_file_sources(selected_sessions)).items():
        try:
            d = date.fromisoformat(dk)
        except ValueError:
            continue
        for k in _day_keys(d):
            b = B[k]
            b["in"] += day.get("in", 0); b["out"] += day.get("out", 0)
            b["cr"] += day.get("cr", 0); b["cw"] += day.get("cw", 0)
            b["reason"] += day.get("reason", 0)
            b["cost"] += day.get("cost", 0)
            for mn, mv in (day.get("models") or {}).items():
                mm = b["models"].setdefault(
                    mn, {"in": 0, "out": 0, "cr": 0, "cw": 0,
                         "reason": 0, "cost": 0.0})
                for key in TOKEN_FIELDS:
                    mm[key] += mv.get(key, 0)
                mm["cost"] += mv.get("cost", 0)

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
    ledger_touch("pi")
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

    live_days = {}
    for f, entry in fc.items():
        session = entry.get("sid") or f
        for dk, day in entry.get("days", {}).items():
            try:
                d = date.fromisoformat(dk)
            except ValueError:
                continue
            _merge_live_token_day(live_days.setdefault(dk, _empty_token_day()), day)
            # 会话数只能来自现存日志(被清日志无从归属)
            for k in classify_date(d, bounds):
                B[k]["sessions"].add(session)

    for dk, day in ledger_reconcile("pi", live_days, _ledger_file_sources(fc, "sid")).items():
        try:
            d = date.fromisoformat(dk)
        except ValueError:
            continue
        for k in classify_date(d, bounds):
            _merge_token_day(B[k], day)
    if changed:
        cache["_dirty"] = True
    return {"ranges": B}


# ---------- Prime Agent ----------
# JSONL 文件: ~/.prime/agent/sessions/*.jsonl plus session-artifacts/**/**/*.jsonl.
# Prime Agent uses the Pi Coding Agent Usage shape; child attribution records are bookkeeping only.
def _prime_agent_session_dirs():
    explicit = os.environ.get("TOKEI_PRIME_AGENT_SESSION_DIR")
    if explicit:
        return _existing_dirs([explicit])
    agent_dir = os.path.expanduser(os.environ.get(
        "PRIME_AGENT_CODING_AGENT_DIR", PRIME_AGENT_DIR))
    session_override = os.environ.get(
        "PRIME_AGENT_SESSION_DIR", os.environ.get("PRIME_AGENT_CODING_AGENT_SESSION_DIR"))
    return _existing_dirs([
        session_override or os.path.join(agent_dir, "sessions"),
        os.path.join(agent_dir, "session-artifacts"),
    ])


def _parse_prime_session_file(path):
    days = {}
    events = []
    project = None
    session_id = os.path.basename(path)
    model = ""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            for line_no, line in enumerate(fh, 1):
                if '"type"' not in line and '"usage"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("type") == "session":
                    session_id = str(obj.get("id") or session_id)
                    project = obj.get("cwd") or project
                    continue
                if obj.get("type") == "model_change":
                    model = _pi_model_id({"provider": obj.get("provider"),
                                           "model": obj.get("modelId")})
                    continue
                if obj.get("type") != "message":
                    continue
                msg = obj.get("message") or {}
                if msg.get("role") != "assistant":
                    continue
                usage = msg.get("usage") or {}
                if not usage:
                    continue
                dt = parse_ts(obj.get("timestamp") or msg.get("timestamp") or "")
                if dt is None:
                    continue
                current_model = _pi_model_id(msg)
                current_model = current_model if current_model != "unknown" else model
                inp = _pi_usage_int(usage, "input")
                out = _pi_usage_int(usage, "output")
                cr = _pi_usage_int(usage, "cacheRead", "cache_read")
                cw = _pi_usage_int(usage, "cacheWrite", "cache_write")
                reason = _pi_usage_int(usage, "reasoning", "reason", "reasoningTokens")
                cost = _pi_usage_cost(usage, current_model)
                if inp + out + cr + cw + reason == 0 and cost <= 0:
                    continue
                event_id = obj.get("id") or msg.get("id") or msg.get("responseId")
                key = f"{session_id}:{event_id}" if event_id else f"{session_id}:{line_no}"
                events.append({"key": key, "date": dt.astimezone().date().isoformat(),
                               "hour": dt.astimezone().hour, "in": inp, "out": out,
                               "cr": cr, "cw": cw, "reason": reason, "cost": cost,
                               "model": current_model})
    except OSError:
        return {"session": session_id, "proj": project, "events": [], "days": {}}
    for event in events:
        day = days.setdefault(event["date"], _empty_token_day())
        _add_token_usage(day, event["in"], event["out"], event["cr"], event["cw"],
                         event["reason"], event["cost"], event["model"])
        day["hours"][event["hour"]] += token_total(event)
    return {"session": session_id, "sid": session_id, "proj": project,
            "events": events, "days": days}


def scan_prime_agent(bounds, cache):
    ledger_touch("prime_agent")
    fc = cache.setdefault("prime_agent", {})
    B = _empty_token_ranges()
    roots = _prime_agent_session_dirs()
    seen_files = set()
    for root in roots:
        seen_files.update(os.path.realpath(f) for f in glob.glob(
            os.path.join(root, "**", "*.jsonl"), recursive=True))
    stale = set(fc.keys()) - seen_files
    changed = bool(stale)
    for path in sorted(seen_files):
        try:
            st = os.stat(path)
        except OSError:
            continue
        sig = f"{st.st_mtime_ns}:{st.st_size}"
        entry = fc.get(path)
        if not isinstance(entry, dict) or entry.get("sig") != sig:
            parsed = _parse_prime_session_file(path)
            parsed["sig"] = sig
            fc[path] = parsed
            changed = True
    for path in stale:
        fc.pop(path, None)
    # Prefer one physical copy of a logical session, then dedupe message IDs globally.
    canonical = {}
    for path, entry in fc.items():
        if not isinstance(entry, dict):
            continue
        sid = entry.get("sid") or path
        old = canonical.get(sid)
        if old is None or len(entry.get("events", [])) > len(old[1].get("events", [])):
            canonical[sid] = (path, entry)
    canonical_paths = {path for path, _ in canonical.values()}
    for path in list(fc):
        if not path.startswith("_") and path not in canonical_paths:
            fc.pop(path, None)
            changed = True
    used = set()
    days = {}
    ledger_sources = {}
    day_sessions = {}
    day_projects = {}
    for path, entry in canonical.values():
        sid = entry.get("sid") or path
        proj_name = os.path.basename((entry.get("proj") or "").rstrip("/"))
        for event in entry.get("events", []):
            if event.get("key") in used:
                continue
            used.add(event.get("key"))
            day_key = event.get("date")
            try:
                date.fromisoformat(day_key)
            except (TypeError, ValueError):
                continue
            _ledger_add_record_source(ledger_sources, sid, day_key, event, event.get("hour"))
            day = days.setdefault(day_key, _empty_token_day())
            _add_token_usage(day, event.get("in", 0), event.get("out", 0),
                             event.get("cr", 0), event.get("cw", 0), event.get("reason", 0),
                             event.get("cost", 0), event.get("model"))
            hour = event.get("hour")
            if isinstance(hour, int) and 0 <= hour < 24:
                day["hours"][hour] += token_total(event)
            day_sessions.setdefault(day_key, set()).add(sid)
            if proj_name:
                day_projects.setdefault(day_key, set()).add(proj_name)
        B["all"]["sessions"].add(sid)
    if changed:
        cache["_dirty"] = True
    # 会话与项目名随天入账本:日志被清理后,那天的会话数与"在干什么"仍答得出。
    for day_key, day in days.items():
        day["sessions"] = sorted(day_sessions.get(day_key, set()))
        day["projects"] = sorted(day_projects.get(day_key, set()))[:3]

    for day_key, day in ledger_reconcile("prime_agent", days, ledger_sources).items():
        try:
            day_date = date.fromisoformat(day_key)
        except (TypeError, ValueError):
            continue
        for range_key in classify_date(day_date, bounds):
            _merge_token_day(B[range_key], day)
            B[range_key]["sessions"].update(day.get("sessions", []))
    return {"ranges": B}


# ---------- WorkBuddy ----------
# JSONL 文件: ~/.workbuddy/projects 和 ~/.workbuddy-ai/projects 下的会话文件。
# 两个独立 App 共用解析逻辑,但缓存、账本和展示分别统计。
# 每个带 usage 的 item 代表一次模型调用。providerData 中的同一份 usage 仅作字段补全，
# 不重复累计；reasoning_tokens 已包含在 output_tokens 中。
_WORKBUDDY_PARSER_VERSION = 2


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


def _workbuddy_float(obj, *keys):
    if not isinstance(obj, dict):
        return None
    for key in keys:
        if key not in obj:
            continue
        value = obj.get(key)
        if isinstance(value, bool):
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            return max(value, 0.0)
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


def _workbuddy_usage_record(item, model_id_first=False):
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

    credits = max(
        (_workbuddy_float(source, "credit", "credits") or 0.0 for source in sources),
        default=0.0,
    )
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
        if credits <= 0:
            return None
        selected = sources[0]

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

    model_keys = (("requestModelId", "requestModelName") if model_id_first else
                  ("requestModelName", "requestModelId"))
    model = (provider.get(model_keys[0]) or provider.get(model_keys[1])
             or provider.get("model") or message.get("model") or item.get("model") or "unknown")
    price = _raw_price(str(model))
    cost = (input_tokens / 1e6 * price["in"] + output / 1e6 * price["out"]
            + cache_read / 1e6 * price["cache_read"]
            + cache_write / 1e6 * price["cache_write"])
    # CodeBuddy already records its native Credit value. Do not turn an
    # unrecognised model into a guessed dollar estimate; keep the Credit
    # total authoritative and leave USD at zero until an exact price exists.
    if model_id_first and not _exact_pricing_id(_model_identity_id(str(model))):
        cost = 0.0
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
        "credits": credits,
        "model": str(model),
        "message_id": str(provider.get("messageId") or ""),
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

    selected = {}
    for _, path, entry, record in items:
        key = record.get("dedup") or f"{path}:{record.get('line', 0)}:{record.get('ts_key', '')}"
        current = selected.get(key)
        if current is None:
            selected[key] = (path, entry, record)
            continue
        _, _, existing = current
        current_score = (token_total(current[2]), float(current[2].get("credits", 0) or 0))
        candidate_score = (token_total(record), float(record.get("credits", 0) or 0))
        if candidate_score > current_score:
            selected[key] = (path, entry, record)

    for path, entry, record in sorted(
            selected.values(), key=lambda item: (item[2].get("ts", 0), item[0])):
        yield path, entry, record


def _scan_workbuddy_root(bounds, cache, root, tool_key):
    ledger_touch(tool_key)
    fc = cache.setdefault(tool_key, {})
    B = _empty_token_ranges()
    files = (set(glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True))
             if os.path.isdir(root) else set())
    stale = set(fc.keys())
    changed = False
    for path in sorted(files):
        stale.discard(path)
        try:
            st = os.stat(path)
        except OSError:
            continue
        sig = f"{st.st_mtime}:{st.st_size}"
        if (isinstance(fc.get(path), dict) and fc[path].get("sig") == sig
                and fc[path].get("parser") == _WORKBUDDY_PARSER_VERSION):
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
                    record = _workbuddy_usage_record(
                        item, model_id_first=tool_key == "codebuddy")
                    if record is None:
                        continue
                    record_session = str(item.get("sessionId") or session_id)
                    dedup_id = record.get("message_id") or record["item_id"]
                    if tool_key == "codebuddy" and record.get("message_id"):
                        record["dedup"] = "codebuddy:" + hashlib.sha256(
                            record["message_id"].encode("utf-8")
                        ).hexdigest()
                    elif dedup_id:
                        record["dedup"] = json.dumps(
                            [record_session, dedup_id, record["ts_key"]], separators=(",", ":"))
                    else:
                        record["dedup"] = f"{path}:{line_no}:{record['ts_key']}"
                    record["session"] = record_session
                    record["line"] = line_no
                    records.append(record)
        except OSError:
            continue
        fc[path] = {"sig": sig, "parser": _WORKBUDDY_PARSER_VERSION,
                    "records": records, "proj": project, "sid": str(session_id)}
        changed = True

    for path in stale:
        fc.pop(path, None)
        changed = True

    days = {}
    ledger_sources = {}
    sessions = {}
    day_projects = {}
    for path, entry, record in _iter_workbuddy_records(fc):
        _ledger_add_record_source(ledger_sources, record.get("session") or entry.get("sid") or path,
                                  record["date"], record, record.get("hour"))
        day = days.setdefault(record["date"], _empty_token_day())
        _add_token_usage(day, record["in"], record["out"], record["cr"], record["cw"],
                         0, record["cost"], record["model"], credits=record.get("credits", 0))
        sessions.setdefault(record["date"], set()).add(record.get("session") or "unknown")
        proj_name = os.path.basename((entry.get("proj") or "").rstrip("/"))
        if proj_name:
            day_projects.setdefault(record["date"], set()).add(proj_name)
    # 项目名随天入账本(同 scan_claude):日志被清理后仍能回答"那天在干什么"。
    for day_key, names in day_projects.items():
        days[day_key]["projects"] = sorted(names)[:3]

    # 会话数只能来自现存日志(被清日志无从归属)
    for day_key, day in days.items():
        try:
            day_date = date.fromisoformat(day_key)
        except ValueError:
            continue
        for range_key in classify_date(day_date, bounds):
            B[range_key]["sessions"].update(sessions.get(day_key, set()))

    for day_key, day in ledger_reconcile(tool_key, days, ledger_sources).items():
        try:
            day_date = date.fromisoformat(day_key)
        except ValueError:
            continue
        for range_key in classify_date(day_date, bounds):
            _merge_token_day(B[range_key], day)
    if changed:
        cache["_dirty"] = True
    return {"ranges": B}


def scan_workbuddy(bounds, cache):
    return _scan_workbuddy_root(bounds, cache, WORKBUDDY_DIR, "workbuddy")


def scan_workbuddy_ai(bounds, cache):
    return _scan_workbuddy_root(bounds, cache, WORKBUDDY_AI_DIR, "workbuddy_ai")


def scan_codebuddy(bounds, cache):
    return _scan_workbuddy_root(bounds, cache, CODEBUDDY_DIR, "codebuddy")


# ---------- Grok Bot ----------
# Grok Bot persists transcript snapshots as JSON blobs. They currently expose
# message/activity metadata, but no model, token, or billing fields. Keep this
# scanner activity-only so text length can never be mistaken for token usage.
_GROK_BOT_MAX_BLOB_BYTES = 64 * 1024 * 1024
_GROK_BOT_ACTIVE_GAP_SECONDS = 5 * 60


def _grok_bot_parse_blob(path):
    try:
        size = os.path.getsize(path)
        if size <= 0 or size > _GROK_BOT_MAX_BLOB_BYTES:
            return {"kind": "ignored"}
        with open(path, "r", encoding="utf-8") as handle:
            root = json.load(handle)
    except (OSError, UnicodeDecodeError, ValueError):
        return {"kind": "ignored"}
    value = root.get("value") if isinstance(root, dict) else None
    if not isinstance(value, dict):
        return {"kind": "ignored"}

    rows = value.get("rows")
    if isinstance(rows, list):
        clean_rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_id = row.get("id")
            markers = []
            for candidate in (row.get("lastMessageId"), row.get("newestEntryId")):
                if isinstance(candidate, str) and candidate:
                    markers.append(candidate)
            last_entry = row.get("lastEntry")
            if isinstance(last_entry, dict):
                for candidate in (last_entry.get("id"), last_entry.get("requestId")):
                    if isinstance(candidate, str) and candidate:
                        markers.append(candidate)
            if isinstance(row_id, str) and row_id:
                clean_rows.append({
                    "id": row_id,
                    "markers": sorted(set(markers)),
                })
        return {"kind": "roster", "rows": clean_rows}

    entries = value.get("entries")
    if not isinstance(entries, list):
        return {"kind": "ignored"}
    days = {}
    entry_ids = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_timestamp = _provider_number(entry.get("timestampMs"))
        if raw_timestamp is None or raw_timestamp <= 0:
            continue
        timestamp = raw_timestamp / 1000.0 if raw_timestamp > 100_000_000_000 \
            else raw_timestamp
        try:
            dt = datetime.fromtimestamp(timestamp, timezone.utc).astimezone()
        except (OverflowError, OSError, ValueError):
            continue
        day_key = dt.date().isoformat()
        day = days.setdefault(day_key, {
            "turn_ids": set(), "call_ids": set(), "tool_ids": set(), "timestamps": [],
        })
        entry_id = entry.get("id")
        stable_id = entry_id if isinstance(entry_id, str) and entry_id \
            else f"{path}:{len(entry_ids)}:{int(timestamp * 1000)}"
        if isinstance(entry_id, str) and entry_id:
            entry_ids.append(entry_id)
        day["timestamps"].append(timestamp)
        kind = entry.get("kind")
        if kind == "message" and entry.get("role") == "user":
            day["turn_ids"].add(stable_id)
        if kind == "send-message":
            request_id = entry.get("requestId")
            call_id = request_id if isinstance(request_id, str) and request_id else stable_id
            day["call_ids"].add(call_id)
            message = entry.get("message")
            if isinstance(message, dict) and message.get("type") == "connector":
                day["tool_ids"].add(stable_id)

    clean_days = {}
    for day_key, day in days.items():
        timestamps = sorted(set(day["timestamps"]))
        duration = sum(
            int(current - previous)
            for previous, current in zip(timestamps, timestamps[1:])
            if 0 < current - previous <= _GROK_BOT_ACTIVE_GAP_SECONDS
        )
        clean_days[day_key] = {
            "turns": len(day["turn_ids"]),
            "calls": len(day["call_ids"]),
            "tools": len(day["tool_ids"]),
            "duration": duration,
        }
    marker_ids = entry_ids[:4] + entry_ids[-64:]
    fingerprint_material = "\0".join([
        str(len(entry_ids)), entry_ids[0] if entry_ids else "",
        entry_ids[-1] if entry_ids else "",
    ])
    fingerprint = hashlib.sha256(fingerprint_material.encode("utf-8")).hexdigest()
    return {
        "kind": "transcript",
        "days": clean_days,
        "markers": sorted(set(marker_ids)),
        "fingerprint": fingerprint,
    }


def scan_grok_bot(bounds, cache):
    ledger_touch("grok_bot")
    file_cache = cache.setdefault("grok_bot", {})
    roots = _existing_dirs(GROK_BOT_DIRS)
    seen = set()
    for root in roots:
        real_root = os.path.realpath(root)
        for path in glob.glob(os.path.join(root, "*.blob")):
            try:
                real_path = os.path.realpath(path)
                if os.path.commonpath((real_root, real_path)) != real_root:
                    continue
                stat = os.stat(real_path)
            except (OSError, ValueError):
                continue
            seen.add(real_path)
            signature = (stat.st_mtime_ns, stat.st_size)
            old = file_cache.get(real_path)
            if isinstance(old, dict) and old.get("sig") == list(signature):
                continue
            parsed = _grok_bot_parse_blob(real_path)
            parsed["sig"] = list(signature)
            file_cache[real_path] = parsed
            cache["_dirty"] = True
    for path in list(file_cache):
        if path not in seen:
            del file_cache[path]
            cache["_dirty"] = True

    roster_rows = []
    transcripts = []
    for path, entry in file_cache.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("kind") == "roster":
            roster_rows.extend(entry.get("rows") or [])
        elif entry.get("kind") == "transcript":
            transcripts.append((path, entry))

    # Some releases keep more than one key for the same transcript snapshot.
    # Use its stable entry boundary to avoid counting those copies twice.
    unique = {}
    for path, entry in transcripts:
        fingerprint = entry.get("fingerprint") or path
        current = unique.get(fingerprint)
        if current is None or (entry.get("sig") or [0])[0] > (current[1].get("sig") or [0])[0]:
            unique[fingerprint] = (path, entry)
    transcripts = list(unique.values())

    unused_rows = set(range(len(roster_rows)))
    assigned = {}
    for path, entry in transcripts:
        markers = set(entry.get("markers") or [])
        match = next((index for index in unused_rows
                      if markers.intersection(roster_rows[index].get("markers") or [])), None)
        if match is not None:
            assigned[path] = roster_rows[match]
            unused_rows.remove(match)
    if len(transcripts) == 1 and len(roster_rows) == 1 and transcripts[0][0] not in assigned:
        assigned[transcripts[0][0]] = roster_rows[0]

    ranges = _empty_grok_bot()["ranges"]
    for path, entry in transcripts:
        row = assigned.get(path) or {}
        sid = row.get("id") or entry.get("fingerprint") or path
        if entry.get("sid") != sid or "project" in entry:
            entry["sid"] = sid
            entry.pop("project", None)
            cache["_dirty"] = True
        for day_key, day in (entry.get("days") or {}).items():
            try:
                local_day = date.fromisoformat(day_key)
            except (TypeError, ValueError):
                continue
            for range_key in classify_date(local_day, bounds):
                bucket = ranges[range_key]
                bucket["sessions"].add(sid)
                bucket["calls"] += int(day.get("calls", 0) or 0)
                bucket["turns"] += int(day.get("turns", 0) or 0)
                bucket["tools"] += int(day.get("tools", 0) or 0)
                bucket["duration"] += int(day.get("duration", 0) or 0)
    return {"ranges": ranges}


# ---------- DeepSeek Harness ----------
# Harness 会为同一次调用写 usage chunk 和最终 message。按 session/turn/step
# 只保留最终 message；异常中断时再用 usage chunk 兜底。
_DEEPSEEK_HARNESS_COST_VERSION = 5


def _deepseek_harness_usage_record(item, fallback_model="", fallback_provider="deepseek-official"):
    if not isinstance(item, dict):
        return None
    event_type = item.get("type")
    data = item.get("data") or {}
    if not isinstance(data, dict):
        return None

    priority = 0
    usage = None
    model = fallback_model
    provider = fallback_provider
    if event_type == "assistant/message":
        usage = data.get("usage")
        message = data.get("message") or {}
        source = message.get("source") or {} if isinstance(message, dict) else {}
        if isinstance(source, dict):
            model = source.get("model") or model
            provider = source.get("provider") or provider
        priority = 2
    elif event_type == "assistant/chunk":
        chunk = data.get("chunk") or {}
        if isinstance(chunk, dict) and chunk.get("type") == "usage":
            usage = chunk.get("usage")
            priority = 1
    if not isinstance(usage, dict):
        return None

    timestamp = item.get("time")
    try:
        dt = datetime.fromtimestamp(int(timestamp) / 1000).astimezone()
    except (TypeError, ValueError, OSError, OverflowError):
        return None
    try:
        turn = int(data.get("turn"))
        step = int(data.get("step"))
    except (TypeError, ValueError):
        return None

    inp = max(int(usage.get("inputTokens", 0) or 0), 0)
    raw_out = max(int(usage.get("outputTokens", 0) or 0), 0)
    cr = max(int(usage.get("cacheReadTokens", 0) or 0), 0)
    cw = max(int(usage.get("cacheWriteTokens", 0) or 0), 0)
    reason = min(max(int(usage.get("reasoningTokens", 0) or 0), 0), raw_out)
    out = raw_out - reason
    if inp + raw_out + cr + cw <= 0:
        return None
    model = str(model or "deepseek-v4-pro")
    provider = str(provider or "")
    cost = 0.0
    price = (_deepseek_official_price(model, dt) if provider == "deepseek-official" else None)
    official_cny = price is not None
    if price is None:
        price_id = _pricing_id(model)
        price = _raw_price(price_id) if price_id else None
    if price:
        cost = (inp / 1e6 * price["in"] + raw_out / 1e6 * price["out"]
                + cr / 1e6 * price["cache_read"] + cw / 1e6 * price["cache_write"])
    return {
        "date": dt.strftime("%Y-%m-%d"), "hour": dt.hour, "ts": int(timestamp),
        "turn": turn, "step": step, "priority": priority, "model": model,
        "provider": provider,
        "in": inp, "out": out, "cr": cr, "cw": cw, "reason": reason,
        "cost": 0.0 if official_cny else cost,
        "cost_cny": cost if official_cny else 0.0,
    }


def _iter_deepseek_harness_records(file_cache):
    records = []
    for path, entry in file_cache.items():
        if not isinstance(entry, dict):
            continue
        session = str(entry.get("sid") or path)
        for record in entry.get("records", []):
            if isinstance(record, dict):
                records.append((record.get("ts", 0), path, entry, session, record))
    records.sort(key=lambda value: (value[0], value[1]))
    seen = set()
    for _, path, entry, session, record in records:
        key = (session, record.get("turn"), record.get("step"))
        if key in seen:
            continue
        seen.add(key)
        yield path, entry, record


def scan_deepseek_harness(bounds, cache):
    ledger_touch("deepseek_harness")
    fc = cache.setdefault("deepseek_harness", {})
    B = _empty_token_ranges()
    if not os.path.isdir(DEEPSEEK_HARNESS_DIR):
        if fc:
            fc.clear()
            cache["_dirty"] = True
        return {"ranges": B}

    files = set(glob.glob(os.path.join(DEEPSEEK_HARNESS_DIR, "**", "*.jsonl"), recursive=True))
    stale = set(fc.keys())
    for path in sorted(files):
        stale.discard(path)
        try:
            st = os.stat(path)
        except OSError:
            continue
        sig = f"{st.st_mtime_ns}:{st.st_size}"
        if (isinstance(fc.get(path), dict) and fc[path].get("sig") == sig
                and fc[path].get("cost_version") == _DEEPSEEK_HARNESS_COST_VERSION):
            continue

        session_id = os.path.splitext(os.path.basename(path))[0]
        project = ""
        current_model = "deepseek-v4-pro"
        current_provider = "deepseek-official"
        candidates = {}
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    if '"type"' not in line or not any(value in line for value in (
                            '"session"', '"request/header"',
                            '"assistant/chunk"', '"assistant/message"')):
                        continue
                    try:
                        item = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    event_type = item.get("type")
                    if event_type == "session":
                        session_id = str(item.get("id") or session_id)
                        project = item.get("cwd") or project
                        continue
                    if event_type == "request/header":
                        data = item.get("data") or {}
                        header = data.get("header") or {} if isinstance(data, dict) else {}
                        config = header.get("config") or {} if isinstance(header, dict) else {}
                        if isinstance(config, dict):
                            current_model = config.get("model") or current_model
                            current_provider = config.get("provider") or current_provider
                        continue
                    record = _deepseek_harness_usage_record(
                        item, current_model, current_provider)
                    if record is None:
                        continue
                    key = (record["turn"], record["step"])
                    previous = candidates.get(key)
                    if previous is None or record["priority"] >= previous["priority"]:
                        candidates[key] = record
        except OSError:
            continue
        records = sorted(candidates.values(), key=lambda record: record["ts"])
        fc[path] = {"sig": sig, "records": records, "proj": project, "sid": session_id,
                    "cost_version": _DEEPSEEK_HARNESS_COST_VERSION}
        cache["_dirty"] = True

    for path in stale:
        fc.pop(path, None)
        cache["_dirty"] = True

    days = {}
    ledger_sources = {}
    sessions = {}
    day_projects = {}
    for path, entry, record in _iter_deepseek_harness_records(fc):
        _ledger_add_record_source(ledger_sources, entry.get("sid") or path,
                                  record["date"], record, record.get("hour"))
        day = days.setdefault(record["date"], _empty_token_day())
        _add_token_usage(day, record["in"], record["out"], record["cr"], record["cw"],
                         record["reason"], record["cost"], record["model"],
                         cost_cny=record.get("cost_cny", 0))
        day["hours"][record["hour"]] += token_total(record)
        session = str(entry.get("sid") or "unknown")
        sessions.setdefault(record["date"], set()).add(session)
        project = entry.get("proj") or ""
        project_name = os.path.basename(project.rstrip("/"))
        if project_name:
            day_projects.setdefault(record["date"], set()).add(project_name)
    for day_key, names in day_projects.items():
        days[day_key]["projects"] = sorted(names)[:3]
    for day in days.values():
        day["_cost_version"] = _DEEPSEEK_HARNESS_COST_VERSION
    for source in ledger_sources.values():
        for day in source.values():
            day["_cost_version"] = _DEEPSEEK_HARNESS_COST_VERSION

    for day_key, day in days.items():
        try:
            day_date = date.fromisoformat(day_key)
        except ValueError:
            continue
        for range_key in classify_date(day_date, bounds):
            B[range_key]["sessions"].update(sessions.get(day_key, set()))

    for day_key, day in ledger_reconcile("deepseek_harness", days, ledger_sources).items():
        try:
            day_date = date.fromisoformat(day_key)
        except ValueError:
            continue
        for range_key in classify_date(day_date, bounds):
            _merge_token_day(B[range_key], day)
    return {"ranges": B}


# ---------- OpenCode ----------
# SQLite: ~/.local/share/opencode/opencode.db；旧版 JSON 作为补充来源。
# JSON 文件: ~/.local/share/opencode/storage/message/<session>/msg_*.json
# 每条 assistant 消息有 tokens{input,output,reasoning,cache{read,write}} + cost + modelID。
_OPENCODE_COST_CACHE_VERSION = 2


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
    cost_cny = 0.0
    official = (_deepseek_official_price(model, created)
                if message.get("providerID") in ("deepseek", "deepseek-official") else None)
    if official:
        cost_cny = (int(tokens.get("input", 0) or 0) * official["in"]
                    + (int(tokens.get("output", 0) or 0) + int(tokens.get("reasoning", 0) or 0)) * official["out"]
                    + int(cache.get("read", 0) or 0) * official["cache_read"]
                    + int(cache.get("write", 0) or 0) * official["cache_write"]) / 1e6
        cost = 0.0
    day = {
        "date": created.strftime("%Y-%m-%d"),
        "in": int(tokens.get("input", 0) or 0),
        "out": int(tokens.get("output", 0) or 0),
        "reason": int(tokens.get("reasoning", 0) or 0),
        "cr": int(cache.get("read", 0) or 0),
        "cw": int(cache.get("write", 0) or 0),
        "cost": cost, "cost_cny": cost_cny,
        "session": message.get("sessionID") or session_id,
        "models": {},
        "hours": [0] * 24,
    }
    day["hours"][created.hour] = token_total(day)
    _add_model_usage(day["models"], model, day["in"], day["out"], day["cr"],
                     day["cw"], day["reason"], day["cost"], cost_cny=cost_cny)
    return day


def _scan_opencode_database(path, estimate_missing_cost=False):
    import sqlite3

    days = {}
    message_ids = set()
    sessions = {}
    connection = sqlite3.connect(_sqlite_ro_uri(path), uri=True, timeout=1)
    try:
        connection.execute("PRAGMA query_only=ON")
        # 会话自带工作目录，让 OpenCode / MiMoCode 参与项目足迹与回顾页。
        session_projects = {}
        session_columns = {row[1] for row in connection.execute("PRAGMA table_info(session)")}
        if {"id", "directory"} <= session_columns:
            try:
                for session_id, directory in connection.execute(
                        "SELECT id, directory FROM session"):
                    if isinstance(directory, str) and directory.startswith("/"):
                        session_projects[session_id] = directory
            except sqlite3.Error:
                pass
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
                             day["reason"], day["cost"], cost_cny=day.get("cost_cny", 0))
            for model, usage in day["models"].items():
                _add_model_usage(target["models"], model, usage["in"], usage["out"],
                                 usage["cr"], usage["cw"], usage["reason"], usage["cost"],
                                 cost_cny=usage.get("cost_cny", 0))
            for hour, amount in enumerate(day["hours"]):
                target["hours"][hour] += amount
            if day.get("session"):
                sessions.setdefault(day_key, set()).add(day["session"])
            proj_path = session_projects.get(session_id)
            if proj_path:
                bucket = target.setdefault("projects", {}).setdefault(
                    proj_path, {"tokens": 0, "cost": 0.0, "models": {}, "sessions": []})
                total = day["in"] + day["out"] + day["cr"] + day["cw"] + day["reason"]
                bucket["tokens"] += total
                bucket["cost"] += day["cost"]
                for model, usage in day["models"].items():
                    amount = (usage["in"] + usage["out"] + usage["cr"]
                              + usage["cw"] + usage["reason"])
                    bucket["models"][model] = bucket["models"].get(model, 0) + amount
                marker = day.get("session") or session_id
                if marker and marker not in bucket["sessions"]:
                    bucket["sessions"].append(str(marker))
    finally:
        connection.close()
    for day_key, ids in sessions.items():
        days[day_key]["sessions"] = sorted(ids)
    return days, sorted(message_ids)


def scan_opencode(bounds, cache):
    ledger_touch("opencode")
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
    live_days = {}
    live_sessions = {}

    for db_path in db_paths:
        cache_key = "db:" + db_path
        stale.discard(cache_key)
        signature = _sqlite_signature(db_path)
        entry = fc.get(cache_key)
        if (not entry or entry.get("sig") != signature
                or entry.get("cost_version") != _OPENCODE_COST_CACHE_VERSION):
            try:
                days, message_ids = _scan_opencode_database(
                    db_path, estimate_missing_cost=True)
            except Exception:
                continue
            entry = {
                "sig": signature,
                "days": days,
                "message_ids": message_ids,
                "source": "sqlite",
                "cost_version": _OPENCODE_COST_CACHE_VERSION,
            }
            fc[cache_key] = entry
            changed = True
        db_message_ids.update(entry.get("message_ids", []))
        for day_key, day in entry.get("days", {}).items():
            try:
                date.fromisoformat(day_key)
            except ValueError:
                continue
            _merge_live_token_day(live_days.setdefault(day_key, _empty_token_day()), day)
            live_sessions.setdefault(day_key, set()).update(day.get("sessions", []))

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
                if (entry and entry.get("sig") == sig
                        and entry.get("cost_version") == _OPENCODE_COST_CACHE_VERSION):
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
                    day_data = _opencode_message_day(d, estimate_missing_cost=True)
                    fc[f] = {
                        "sig": sig,
                        "day": day_data,
                        "message_id": message_id,
                        "cost_version": _OPENCODE_COST_CACHE_VERSION,
                    }
                    changed = True
                if message_id in seen_message_ids:
                    continue
                seen_message_ids.add(message_id)
                stale.discard(f)

                if not day_data:
                    continue
                dk = day_data["date"]
                try:
                    date.fromisoformat(dk)
                except (TypeError, ValueError):
                    continue
                _merge_live_token_day(live_days.setdefault(dk, _empty_token_day()), day_data)
                session = day_data.get("session")
                if session is not None:
                    live_sessions.setdefault(dk, set()).add(session)

    for p in stale:
        fc.pop(p, None)
        changed = True

    for day_key, day in live_days.items():
        day["sessions"] = sorted(live_sessions.get(day_key, set()))
        day["_cost_version"] = _OPENCODE_COST_CACHE_VERSION

    for day_key, day in ledger_reconcile("opencode", live_days).items():
        try:
            day_date = date.fromisoformat(day_key)
        except ValueError:
            continue
        for range_key in classify_date(day_date, bounds):
            _merge_token_day(B[range_key], day)
            B[range_key]["sessions"].update(day.get("sessions", []))

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
    ledger_touch("zcode")
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

    for day_key, day in ledger_reconcile("zcode", entry.get("days", {})).items():
        try:
            day_date = date.fromisoformat(day_key)
        except ValueError:
            continue
        for range_key in classify_date(day_date, bounds):
            _merge_token_day(B[range_key], day)
            B[range_key]["sessions"].update(day.get("sessions", []))
    return {"ranges": B}


# ---------- Devin CLI ----------
# SQLite: ~/.local/share/devin/cli/sessions.db。
# message_nodes.chat_message 是整条消息的 JSON，assistant 那条在 metadata.metrics
# 里带着自己的用量：
#
#   {"role":"assistant","metadata":{"generation_model":"…","created_at":…,
#     "metrics":{"input_tokens":11486,"output_tokens":254,
#                "cache_read_tokens":6450,"cache_creation_tokens":null}}}
#
# input_tokens 与两个缓存桶并列（Anthropic 的口径），不做相减。
# 这和桌面端的套餐缓存是两个互不相干的库：一个是 CLI 自己的对话记录，
# 一个是账号额度，彼此不知道对方的存在。
# 计量口径版本。改动解析口径时 +1：账本按 _cost_version 取新不取大，
# 否则被高水位规则记下的旧数（例如兄弟节点翻倍那版）会一直压住修正后的值。
# 同一个常量也用作扫描缓存的版本，两边一起失效。
_DEVIN_COST_VERSION = 3


def _devin_cli_db_path():
    return _first_existing_file(DEVIN_CLI_DB_PATHS)


def _scan_devin_cli_database(path):
    import sqlite3

    def number(value):
        try:
            return max(int(value or 0), 0)
        except (TypeError, ValueError, OverflowError):
            return 0

    days = {}
    sessions = {}
    seen = set()
    connection = sqlite3.connect(_sqlite_ro_uri(path), uri=True, timeout=1)
    try:
        connection.execute("PRAGMA query_only=ON")
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "message_nodes" not in tables:
            return {}

        # 会话表给出模型兜底（generation_model 缺失时用会话声明的模型）
        # 与项目路径（working_directory），后者让 Devin 参与项目足迹与回顾页。
        session_models, session_projects = {}, {}
        if "sessions" in tables:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(sessions)")}
            if "id" in columns:
                directory = "working_directory" if "working_directory" in columns else "NULL"
                model_col = "model" if "model" in columns else "NULL"
                try:
                    for session_id, model, workdir in connection.execute(
                            f"SELECT id, {model_col}, {directory} FROM sessions"):
                        if isinstance(model, str) and model.strip():
                            session_models[session_id] = model.strip()
                        if isinstance(workdir, str) and workdir.startswith("/"):
                            session_projects[session_id] = workdir
                except sqlite3.Error:
                    pass

        # node_id 只在合并键的兜底分支里用到，老版本没有这一列也能读。
        columns = {row[1] for row in connection.execute(
            "PRAGMA table_info(message_nodes)")}
        if not {"session_id", "chat_message", "created_at"} <= columns:
            return {}
        node = "node_id" if "node_id" in columns else "rowid"
        rows = connection.execute(f"""
            SELECT session_id, {node}, chat_message, created_at
            FROM message_nodes
            ORDER BY created_at ASC, {node} ASC
        """)
        for session_id, node_id, message, created_at in rows:
            if isinstance(message, (bytes, bytearray)):
                try:
                    message = bytes(message).decode("utf-8")
                except UnicodeDecodeError:
                    continue
            try:
                root = json.loads(message)
            except (TypeError, ValueError):
                continue
            if not isinstance(root, dict):
                continue
            metadata = root.get("metadata")
            if not isinstance(metadata, dict):
                continue
            metrics = metadata.get("metrics")
            if not isinstance(metrics, dict):
                continue

            input_total = number(metrics.get("input_tokens"))
            output_total = number(metrics.get("output_tokens"))
            cache_read = number(metrics.get("cache_read_tokens"))
            cache_write = number(metrics.get("cache_creation_tokens"))
            if input_total + output_total + cache_read + cache_write <= 0:
                continue

            # 时刻优先取消息自己的 created_at（ISO 字符串，微秒精度，是这次回复
            # 真正的时间）；行上的 created_at 只精确到秒，作兜底。缺时间戳的
            # 消息跳过，不拿文件修改时间顶替。
            stamp_source = metadata.get("created_at")
            stamp = _provider_epoch(stamp_source)
            if stamp is None:
                stamp_source = None
                stamp = _provider_epoch(created_at)
            if stamp is None or stamp <= 0:
                continue
            try:
                created = datetime.fromtimestamp(stamp).astimezone()
            except (OSError, OverflowError, ValueError):
                continue

            model = metadata.get("generation_model")
            model = model.strip() if isinstance(model, str) and model.strip() else None
            model = model or session_models.get(session_id)

            # message_nodes 是一片森林：同一次回复会被写进共用一个 parent 的
            # 两个兄弟节点，metrics 与 metadata.created_at 完全一致。照单全收
            # 会把用量翻一倍（实测如此），所以同一会话里「同一微秒时刻 + 同一
            # 组 metrics + 同一模型」只计一次。两次不同的调用不会既同时刻又
            # 同用量；而没有微秒落款可比时退回按节点计，宁可不合并也不丢数。
            key = (session_id, stamp_source if stamp_source is not None else node_id,
                   model, input_total, output_total, cache_read, cache_write)
            if key in seen:
                continue
            seen.add(key)

            display_model = (_known_id_or_raw(model) or model) if model else "devin"
            cost = 0.0
            price_id = _pricing_id(model) if model else None
            if price_id:
                price = _raw_price(price_id)
                cost = (input_total / 1e6 * price["in"]
                        + output_total / 1e6 * price["out"]
                        + cache_read / 1e6 * price["cache_read"]
                        + cache_write / 1e6 * price["cache_write"])

            day_key = created.date().isoformat()
            day = days.setdefault(day_key, _empty_token_day())
            day["_cost_version"] = _DEVIN_COST_VERSION
            _add_token_usage(day, input_total, output_total, cache_read, cache_write,
                             0, cost, display_model)
            proj_path = session_projects.get(session_id)
            if proj_path:
                by_project = day.setdefault("projects", {})
                bucket = by_project.setdefault(
                    proj_path, {"tokens": 0, "cost": 0.0, "models": {}, "sessions": []})
                total = input_total + output_total + cache_read + cache_write
                bucket["tokens"] += total
                bucket["cost"] += cost
                bucket["models"][display_model] = \
                    bucket["models"].get(display_model, 0) + total
                if session_id not in bucket["sessions"]:
                    bucket["sessions"].append(str(session_id))
            day["hours"][created.hour] += input_total + output_total + cache_read + cache_write
            sessions.setdefault(day_key, set()).add(str(session_id or "unknown"))
    finally:
        connection.close()
    for day_key, session_ids in sessions.items():
        days[day_key]["sessions"] = sorted(session_ids)
    return days


def scan_devin(bounds, cache):
    ledger_touch("devin")
    fc = cache.setdefault("devin", {})
    B = _empty_token_ranges()
    db_path = _devin_cli_db_path()
    if not db_path:
        if fc:
            fc.clear()
            cache["_dirty"] = True
        return {"ranges": B}

    db_path = os.path.realpath(db_path)
    cache_key = "db:" + db_path
    signature = _sqlite_signature(db_path)
    entry = fc.get(cache_key)
    if not entry or entry.get("sig") != signature \
            or entry.get("version") != _DEVIN_COST_VERSION:
        entry = {"sig": signature, "days": _scan_devin_cli_database(db_path),
                 "version": _DEVIN_COST_VERSION}
        fc.clear()
        fc[cache_key] = entry
        cache["_dirty"] = True

    for day_key, day in ledger_reconcile("devin", entry.get("days", {})).items():
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


# 解析口径版本。加 1 可让旧缓存失效重扫（例如新增了按项目的用量拆分）。
_MIMOCODE_SCAN_VERSION = 2


def scan_mimocode(bounds, cache):
    ledger_touch("mimocode")
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
    if (not entry or entry.get("sig") != signature
            or entry.get("version") != _MIMOCODE_SCAN_VERSION):
        days, _ = _scan_opencode_database(db_path, estimate_missing_cost=True)
        entry = {"sig": signature, "days": days, "version": _MIMOCODE_SCAN_VERSION}
        fc.clear()
        fc[cache_key] = entry
        cache["_dirty"] = True

    for day_key, day in ledger_reconcile("mimocode", entry.get("days", {})).items():
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
        entry = _qwen_summary_entry(record)
        if entry is not None:
            if session in request_sessions:
                # A retained request file need not contain the whole session.
                # Only fill the per-model remainder of the cumulative summary;
                # never add the summary again or discard the known request times.
                for request in request_entries.values():
                    if request["session"] != session:
                        continue
                    for model, values in request["models"].items():
                        target = entry["models"].get(model)
                        if target is not None:
                            for field in (*TOKEN_FIELDS, "cost", "cost_cny"):
                                target[field] = target.get(field, 0) - values.get(field, 0)
                for values in entry["models"].values():
                    # Cache detail can be more complete in request logs than in
                    # the summary. Preserve that detail without inflating total input.
                    remaining_input = max(sum(values.get(k, 0) for k in ("in", "cr", "cw")), 0)
                    for field in (*TOKEN_FIELDS, "cost", "cost_cny"):
                        values[field] = max(values.get(field, 0), 0)
                    values["cr"] = min(values["cr"], remaining_input)
                    values["cw"] = min(values["cw"], remaining_input - values["cr"])
                    values["in"] = remaining_input - values["cr"] - values["cw"]
                for field in (*TOKEN_FIELDS, "cost", "cost_cny"):
                    entry[field] = sum(v.get(field, 0) for v in entry["models"].values())
                entry["hour"] = None  # The summary does not locate missing calls in time.
            if token_total(entry):
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
    ledger_touch("qwencode")
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

    if fc.get("sig") != sig or fc.get("accounting_version") != 2:
        entries = _qwen_entries(token_files, summary_file)
        fc.clear()
        fc.update({"sig": sig, "entries": entries, "accounting_version": 2})
        cache["_dirty"] = True

    live_days = {}
    ledger_sources = {}
    for entry in fc.get("entries", []):
        try:
            day = date.fromisoformat(entry["date"])
        except (TypeError, ValueError, KeyError):
            continue
        _ledger_add_record_source(ledger_sources, entry.get("session") or "unknown", entry["date"], entry, entry.get("hour"))
        agg = live_days.setdefault(entry["date"], _empty_token_day())
        _add_token_usage(agg, entry.get("in", 0), entry.get("out", 0), entry.get("cr", 0),
                         entry.get("cw", 0), entry.get("reason", 0), entry.get("cost", 0))
        for model, mv in (entry.get("models") or {}).items():
            _add_model_usage(agg["models"], model, mv.get("in", 0), mv.get("out", 0),
                             mv.get("cr", 0), mv.get("cw", 0), mv.get("reason", 0),
                             mv.get("cost", 0))
        hour = entry.get("hour")
        if isinstance(hour, int) and 0 <= hour < 24:
            agg["hours"][hour] += token_total(entry)
        # 会话数只能来自现存日志(被清日志无从归属)
        session = entry.get("session")
        if session is not None:
            for key in classify_date(day, bounds):
                B[key]["sessions"].add(session)

    for dk, day_usage in ledger_reconcile("qwencode", live_days, ledger_sources).items():
        try:
            day = date.fromisoformat(dk)
        except (TypeError, ValueError):
            continue
        for key in classify_date(day, bounds):
            _merge_token_day(B[key], day_usage)
    return {"ranges": B}


# ---------- Kimi Code CLI ----------
# protocol 1 使用主 wire 中的 StatusUpdate/SubagentEvent；protocol 1.5 把每个
# Agent 的 usage.record 独立写入 agents/*/wire.jsonl。两者都只读 session 目录，
# 不扫描 server/events 镜像，避免重复累计。
_KIMI_PARSER_VERSION = 3


def _kimi_roots():
    configured = (os.environ.get("TOKEI_KIMI_DIR") or os.environ.get("KIMI_CODE_HOME")
                  or os.environ.get("KIMI_SHARE_DIR"))
    if configured:
        candidates = [configured]
    elif os.path.normcase(KIMI_CODE_DIR) != os.path.normcase(_KIMI_CODE_DEFAULT_DIR):
        # Tests and embedders may replace KIMI_CODE_DIR after importing this module.
        candidates = [KIMI_CODE_DIR]
    else:
        candidates = [_KIMI_CODE_DEFAULT_DIR, _KIMI_CODE_LEGACY_DIR]
    roots = []
    seen = set()
    for candidate in candidates:
        root = os.path.abspath(os.path.expanduser(candidate))
        key = os.path.normcase(os.path.realpath(root))
        if key not in seen:
            seen.add(key)
            roots.append(root)
    return roots


# ---------- Kimi Code 官方额度 ----------
# 凭据由 Kimi Code CLI 自己写入并刷新;Tokei 只读、绝不代刷 —— refresh_token 通常带
# rotation,抢刷会顶掉 CLI 自己的登录态。access_token 有效期很短(实测约 30 分钟),
# 过期时直接走缓存并标 stale:显示一个过期读数比承认不知道危险得多(同 issue #63)。
KIMI_QUOTA_CACHE = _writable_path("kimi_quota_cache.json")
_KIMI_QUOTA_TTL = 300
_KIMI_QUOTA_FALLBACK_TTL = 300
_KIMI_QUOTA_STALE_AFTER = 1800
_KIMI_CODE_DEFAULT_BASE_URL = "https://api.kimi.com/coding/v1"
_KIMI_USAGE_URL = _KIMI_CODE_DEFAULT_BASE_URL + "/usages"
_KIMI_USAGE_MAX_RESPONSE_BYTES = 256 * 1024
_KIMI_FIVE_HOUR_MINUTES = 300
_KIMI_TIME_UNITS = {
    "TIME_UNIT_MINUTE": 1,
    "TIME_UNIT_HOUR": 60,
    "TIME_UNIT_DAY": 60 * 24,
    "TIME_UNIT_WEEK": 60 * 24 * 7,
}


def _kimi_epoch_seconds(value):
    """expires_at 可能按秒也可能按毫秒写。"""
    if isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num <= 0:
        return None
    return num / 1000.0 if num > 1e11 else num


def _kimi_amount(value):
    """接口把额度数字写成字符串("100"),直接参与运算会 TypeError。"""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _kimi_credential_files():
    return [os.path.join(root, "credentials", "kimi-code.json")
            for root in _kimi_roots()]


def _kimi_auth_context(now_epoch=None):
    """只读 CLI 写好的 access_token;过期时标记出来,由调用方决定不发请求。"""
    now = now_epoch if now_epoch is not None else datetime.now().timestamp()
    for path in _kimi_credential_files():
        creds = _load_json(path, {})
        if not isinstance(creds, dict):
            continue
        token = creds.get("access_token")
        if not isinstance(token, str) or not token:
            continue
        expires_at = _kimi_epoch_seconds(creds.get("expires_at"))
        return {
            "access_token": token,
            "expires_at": expires_at,
            "expired": bool(expires_at is not None and now >= expires_at),
            "auth_key": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        }
    return {}


def _kimi_window_minutes(window):
    if not isinstance(window, dict):
        return None
    duration = _kimi_amount(window.get("duration"))
    unit = _KIMI_TIME_UNITS.get(window.get("timeUnit"))
    if duration is None or unit is None:
        return None
    return int(round(duration * unit))


def _kimi_slot(detail):
    """detail = {limit, used, remaining, resetTime} → 已用百分比 + 重置时刻。"""
    if not isinstance(detail, dict):
        return None
    limit = _kimi_amount(detail.get("limit"))
    used = _kimi_amount(detail.get("used"))
    remaining = _kimi_amount(detail.get("remaining"))
    if used is None and limit is not None and remaining is not None:
        used = limit - remaining
    if limit is None or limit <= 0 or used is None:
        return None
    slot = {"used_percent": max(0.0, min(100.0, 100.0 * used / limit))}
    reset = _iso_to_epoch(detail.get("resetTime") or detail.get("reset_time")
                          or detail.get("resetAt") or detail.get("reset_at"))
    if reset is not None:
        slot["resets_at"] = reset
    return slot


def _kimi_ratio_slot(detail):
    if not isinstance(detail, dict):
        return None
    ratio = _kimi_amount(detail.get("used_ratio"))
    if ratio is None or not math.isfinite(ratio) or ratio < 0:
        return None
    slot = {"used_percent": min(1.0, ratio) * 100.0}
    reset = _iso_to_epoch(detail.get("reset_time") or detail.get("resetTime"))
    if reset is not None:
        slot["resets_at"] = reset
    return slot


def _kimi_usage_target():
    from urllib.parse import urlparse, urlunparse
    raw = os.environ.get("KIMI_CODE_BASE_URL", _KIMI_CODE_DEFAULT_BASE_URL).strip()
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username \
            or parsed.password or parsed.query or parsed.fragment:
        return None
    path = parsed.path.rstrip("/")
    if path.endswith("/usages"):
        usage_path = path
    elif path.endswith("/coding/v1"):
        usage_path = path + "/usages"
    elif path.endswith("/coding"):
        usage_path = path + "/v1/usages"
    else:
        usage_path = path + "/coding/v1/usages"
    try:
        port = parsed.port
    except ValueError:
        return None
    url = urlunparse(("https", parsed.netloc, usage_path, "", "", ""))
    return url, parsed.hostname.lower(), port


def _kimi_live_to_limits(data):
    """Normalize current ratio pools and the legacy limit/detail response."""
    if not isinstance(data, dict):
        return None
    pools = data.get("usages") if isinstance(data.get("usages"), dict) else {}
    five_hour = _kimi_ratio_slot(pools.get("limit_5h"))
    subscription = next((slot for slot in (
        _kimi_ratio_slot(pools.get("limit_month_total")),
        _kimi_ratio_slot(pools.get("limit_month")),
        _kimi_ratio_slot(pools.get("limit_7d")),
    ) if slot), None)
    if not five_hour:
        for item in data.get("limits") or []:
            if not isinstance(item, dict):
                continue
            if _kimi_window_minutes(item.get("window")) == _KIMI_FIVE_HOUR_MINUTES:
                five_hour = _kimi_slot(item.get("detail"))
                break
    if not subscription:
        subscription = _kimi_slot(data.get("usage"))
    if not five_hour and not subscription:
        return None
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    membership = user.get("membership") if isinstance(user.get("membership"), dict) else {}
    return {
        "limit_id": "kimicode",
        "five_hour": five_hour,
        "subscription": subscription,
        "plan": membership.get("level"),
        "user_id": user.get("userId"),
    }


def _kimi_limits_have_active_window(limits, now_epoch=None):
    now = float(now_epoch if now_epoch is not None else datetime.now().timestamp())
    for key in ("five_hour", "subscription"):
        slot = (limits or {}).get(key) or {}
        reset = slot.get("resets_at")
        try:
            if reset is not None and float(reset) > now:
                return True
        except (TypeError, ValueError, OverflowError):
            continue
    return False


def _cached_kimi_live_limits(max_age, auth_key, allow_active_window=False):
    cached = _load_json(KIMI_QUOTA_CACHE, {})
    if not auth_key or cached.get("auth_key") != auth_key:
        return None
    fetched_at = cached.get("fetched_at")
    limits = cached.get("limits")
    if not fetched_at or not limits:
        return None
    try:
        fetched_at = float(fetched_at)
    except (TypeError, ValueError, OverflowError):
        return None
    age = datetime.now().timestamp() - fetched_at
    if age > max_age and not (
            allow_active_window and _kimi_limits_have_active_window(limits)):
        return None
    return limits, cached.get("plan"), fetched_at


def fetch_kimi_live_limits():
    if os.environ.get("TOKEI_KIMI_LIVE_QUOTA") == "0":
        return None
    target = _kimi_usage_target()
    if not target:
        return None
    usage_url, expected_host, expected_port = target
    auth = _kimi_auth_context()
    token = auth.get("access_token")
    if not token:
        return None
    auth_key = auth.get("auth_key")
    cached = _cached_kimi_live_limits(_KIMI_QUOTA_TTL, auth_key)
    if cached:
        return cached
    if auth.get("expired"):
        return _cached_kimi_live_limits(
            _KIMI_QUOTA_FALLBACK_TTL, auth_key, allow_active_window=True)
    cache_state = _load_json(KIMI_QUOTA_CACHE, {})
    if cache_state.get("auth_key") != auth_key:
        cache_state = {"auth_key": auth_key}
    last_failure = cache_state.get("last_failure_at", 0)
    try:
        failure_is_recent = (
            bool(last_failure)
            and datetime.now().timestamp() - float(last_failure) < 300)
    except (TypeError, ValueError, OverflowError):
        failure_is_recent = False
    if failure_is_recent:
        return _cached_kimi_live_limits(
            _KIMI_QUOTA_FALLBACK_TTL, auth_key, allow_active_window=True)
    try:
        import urllib.request
        from urllib.parse import urlparse
        req = urllib.request.Request(usage_url)
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "Tokei")
        req.add_unredirected_header("Authorization", "Bearer " + token)
        with urllib.request.urlopen(req, timeout=3) as res:
            final_url = urlparse(res.geturl())
            final_port = final_url.port or 443
            if final_url.scheme != "https" or final_url.hostname != expected_host \
                    or final_port != (expected_port or 443):
                raise ValueError("unexpected Kimi usage redirect")
            raw = res.read(_KIMI_USAGE_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _KIMI_USAGE_MAX_RESPONSE_BYTES:
            raise ValueError("Kimi usage response is too large")
        limits = _kimi_live_to_limits(json.loads(raw))
        if not limits:
            raise ValueError("invalid Kimi usage response")
        plan = limits.get("plan")
        fetched_at = datetime.now().timestamp()
        _atomic_write_json(KIMI_QUOTA_CACHE, {
            "fetched_at": fetched_at,
            "limits": limits,
            "plan": plan,
            "user_id": limits.get("user_id"),
            "auth_key": auth_key,
            "source": "live",
        })
        return limits, plan, fetched_at
    except Exception:
        try:
            state = _load_json(KIMI_QUOTA_CACHE, {})
            if state.get("auth_key") != auth_key:
                state = {"auth_key": auth_key}
            state["last_failure_at"] = datetime.now().timestamp()
            _atomic_write_json(KIMI_QUOTA_CACHE, state)
        except Exception:
            pass
    return _cached_kimi_live_limits(
        _KIMI_QUOTA_FALLBACK_TTL, auth_key, allow_active_window=True)


def _kimi_quota_values(limits, now_epoch=None, updated_at=None):
    """→ p5/pw + 重置时刻 + stale,字段语义与 Codex 卡片保持一致。

    两种 stale:窗口已经翻篇(读数必然失真),或读数本身太旧(CLI 久未刷新 token)。
    Kimi 的额度单位是调用次数而非 token,没法像 Codex 那样用本机消耗反推"确实回满了",
    所以翻篇一律标 stale —— 宁可说不知道,也不谎报满额。
    """
    values = {"p5": None, "pw": None, "r5": None, "rw": None,
              "p5_stale": False, "pw_stale": False}
    mapping = (("five_hour", "p5", "r5"), ("subscription", "pw", "rw"))
    for slot_key, pct_key, reset_key in mapping:
        slot = (limits or {}).get(slot_key) or {}
        if not slot:
            continue
        values[pct_key] = slot.get("used_percent")
        values[reset_key] = slot.get("resets_at")

    now = now_epoch if now_epoch is not None else int(datetime.now().timestamp())
    try:
        updated_age = (now - float(updated_at)) if updated_at else None
    except (TypeError, ValueError, OverflowError):
        updated_age = None
    for _, pct_key, reset_key in mapping:
        if values[pct_key] is None:
            continue
        reset = values[reset_key]
        if reset and now > float(reset):
            values[pct_key + "_stale"] = True
        elif updated_age is not None and updated_age > _KIMI_QUOTA_STALE_AFTER:
            values[pct_key + "_stale"] = True
    return values


def _kimi_wire_groups():
    """按会话产出 (agent_wires, root_wire);定深有界遍历,不碰 server/events 等镜像目录。

    protocol 1 只写会话根 wire.jsonl,protocol 1.5 写 agents/<agent>/wire.jsonl。
    过渡版本可能两者并存,所以两类都要交给上层,由记录级去重决定谁算谁不算。"""
    groups = []
    for root in _kimi_roots():
        sessions_dir = os.path.join(root, "sessions")
        for session_dir in glob.glob(os.path.join(sessions_dir, "*", "*")):
            if not os.path.isdir(session_dir):
                continue
            agent_wires = sorted(os.path.abspath(path) for path in glob.glob(
                os.path.join(session_dir, "agents", "*", "wire.jsonl")))
            root_wire = os.path.join(session_dir, "wire.jsonl")
            root_wire = os.path.abspath(root_wire) if os.path.isfile(root_wire) else None
            if agent_wires or root_wire:
                groups.append((agent_wires, root_wire))
    return groups


def _kimi_wire_files(groups=None):
    files = set()
    for agent_wires, root_wire in _kimi_wire_groups() if groups is None else groups:
        files.update(agent_wires)
        if root_wire:
            files.add(root_wire)
    return sorted(files)


def _kimi_mirror_sources(groups):
    """→ {根 wire: (同会话的 agent wire...)},只含两者并存的会话。"""
    return {root_wire: tuple(agent_wires)
            for agent_wires, root_wire in groups
            if root_wire and agent_wires}


def _kimi_group_signature(paths):
    parts = []
    for path in paths:
        try:
            stat = os.stat(path)
        except OSError:
            parts.append(f"{path}:-")
            continue
        parts.append(f"{path}:{stat.st_mtime_ns}:{stat.st_size}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _kimi_record_counts(paths):
    """把这些 wire 里每条记录的去重键计成多重集,用作根 wire 的排除表。"""
    counts = {}
    for path in paths:
        _scan_kimi_wire(path, seen=counts)
    return counts


def _kimi_project_map():
    result = {}
    for root in _kimi_roots():
        metadata = _load_json(os.path.join(root, "kimi.json"), {})
        for item in metadata.get("work_dirs", []) if isinstance(metadata, dict) else []:
            if not isinstance(item, dict):
                continue
            project = item.get("path")
            if not isinstance(project, str) or not project:
                continue
            digest = hashlib.md5(project.encode("utf-8")).hexdigest()
            result[digest] = project
            kaos = item.get("kaos")
            if isinstance(kaos, str) and kaos:
                result[f"{kaos}_{digest}"] = project
    return result


def _kimi_wire_context(path, legacy_projects):
    agent_dir = os.path.dirname(path)
    agents_dir = os.path.dirname(agent_dir)
    if os.path.basename(agents_dir) == "agents":
        session_dir = os.path.dirname(agents_dir)
        state = _load_json(os.path.join(session_dir, "state.json"), {})
        if not isinstance(state, dict):
            state = {}
        session_id = state.get("id") or os.path.basename(session_dir)
        project = state.get("cwd")
        return {
            "sid": str(session_id),
            "proj": project if isinstance(project, str) and project else None,
            "agent": os.path.basename(agent_dir),
        }
    session_dir = agent_dir
    work_dir_hash = os.path.basename(os.path.dirname(session_dir))
    return {
        "sid": os.path.basename(session_dir),
        "proj": legacy_projects.get(work_dir_hash),
        "agent": "main",
    }


def _kimi_events(message, scope="main"):
    if not isinstance(message, dict):
        return
    msg_type = message.get("type")
    payload = message.get("payload")
    if not isinstance(payload, dict):
        return
    if msg_type == "SubagentEvent":
        agent = payload.get("agent_id") or payload.get("parent_tool_call_id") \
            or payload.get("task_tool_call_id")
        child_scope = f"{scope}/{agent}" if isinstance(agent, str) and agent else scope
        yield from _kimi_events(payload.get("event"), child_scope)
    elif msg_type == "StatusUpdate":
        yield scope, payload


def _kimi_token(value):
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _kimi_datetime(record, key):
    value = record.get(key) if isinstance(record, dict) else None
    try:
        epoch = float(value)
        if not math.isfinite(epoch):
            return None
        if epoch > 100_000_000_000:
            epoch /= 1000
        return datetime.fromtimestamp(epoch).astimezone()
    except (TypeError, ValueError, OverflowError, OSError):
        parsed = parse_ts(value) if isinstance(value, str) else None
        return parsed.astimezone() if parsed is not None else None


def _scan_kimi_wire(path, exclude=None, seen=None):
    """exclude:记录键多重集,命中就跳过并抵扣(根 wire 去掉 agent wire 的镜像)。
    seen:传进来就把本文件的记录键计进去,供上层构造 exclude。

    键只在同一种记录形态内可比:protocol 1.5 的 usage.record 没有 id,只能按
    时刻+模型+四个 token 值定身份;protocol 1 有 message_id 就用它。跨形态的
    镜像(根 wire 是 protocol 1、agent wire 是 1.5)认不出来,不在此列。"""
    days = {}
    seen_messages = set()
    # 绝大多数会话没有根 wire 镜像,这时一条记录键都不用建。
    track = exclude is not None or seen is not None
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if ('"usage.record"' not in line and '"StatusUpdate"' not in line
                        and '"SubagentEvent"' not in line):
                    continue
                try:
                    record = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if not isinstance(record, dict):
                    continue
                if record.get("type") == "usage.record":
                    usage = record.get("usage")
                    dt = _kimi_datetime(record, "time")
                    if not isinstance(usage, dict) or dt is None:
                        continue
                    inp = _kimi_token(usage.get("inputOther"))
                    out = _kimi_token(usage.get("output"))
                    cr = _kimi_token(usage.get("inputCacheRead"))
                    cw = _kimi_token(usage.get("inputCacheCreation"))
                    if inp + out + cr + cw == 0:
                        continue
                    model = record.get("model")
                    if not isinstance(model, str) or not model.strip():
                        model = None
                    if track:
                        key = ("u", round(dt.timestamp() * 1000), model, inp, out, cr, cw)
                        if exclude:
                            left = exclude.get(key, 0)
                            if left > 0:
                                exclude[key] = left - 1
                                continue
                        if seen is not None:
                            seen[key] = seen.get(key, 0) + 1
                    day = days.setdefault(dt.date().isoformat(), _empty_token_day())
                    _add_token_usage(day, inp, out, cr, cw, model=model)
                    day["hours"][dt.hour] += inp + out + cr + cw
                    continue

                dt = _kimi_datetime(record, "timestamp")
                if dt is None:
                    continue
                message = record.get("message")
                for scope, payload in _kimi_events(message):
                    usage = payload.get("token_usage")
                    if not isinstance(usage, dict):
                        continue
                    message_id = payload.get("message_id")
                    if isinstance(message_id, str) and message_id:
                        dedup_key = f"{scope}:{message_id}"
                        if dedup_key in seen_messages:
                            continue
                        seen_messages.add(dedup_key)
                    else:
                        message_id = None
                    inp = _kimi_token(usage.get("input_other"))
                    out = _kimi_token(usage.get("output"))
                    cr = _kimi_token(usage.get("input_cache_read"))
                    cw = _kimi_token(usage.get("input_cache_creation"))
                    if inp + out + cr + cw == 0:
                        continue
                    if track:
                        key = (("m", scope, message_id) if message_id else
                               ("t", round(dt.timestamp() * 1000), scope, inp, out, cr, cw))
                        if exclude:
                            left = exclude.get(key, 0)
                            if left > 0:
                                exclude[key] = left - 1
                                continue
                        if seen is not None:
                            seen[key] = seen.get(key, 0) + 1
                    day = days.setdefault(dt.date().isoformat(), _empty_token_day())
                    _add_token_usage(day, inp, out, cr, cw)
                    day["hours"][dt.hour] += inp + out + cr + cw
    except OSError:
        return {}
    return days


def scan_kimicode(bounds, cache):
    ledger_touch("kimicode")
    fc = cache.setdefault("kimicode", {})
    B = _empty_token_ranges()
    groups = _kimi_wire_groups()
    files = _kimi_wire_files(groups)
    if not files:
        if fc:
            fc.clear()
            cache["_dirty"] = True

    projects = _kimi_project_map()
    mirrors = _kimi_mirror_sources(groups)
    stale = set(fc)
    changed = False
    for path in files:
        stale.discard(path)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        signature = f"{stat.st_mtime_ns}:{stat.st_size}"
        mirror_of = mirrors.get(path)
        if mirror_of:
            # 排除表来自 agent wire,它们一变根 wire 就得重算,否则镜像抵扣会错位。
            signature = f"{signature}:{_kimi_group_signature(mirror_of)}"
        entry = fc.get(path)
        context = _kimi_wire_context(path, projects)
        if (not isinstance(entry, dict) or entry.get("sig") != signature
                or entry.get("parser_version") != _KIMI_PARSER_VERSION):
            fc[path] = {
                "sig": signature,
                "days": _scan_kimi_wire(
                    path, exclude=_kimi_record_counts(mirror_of) if mirror_of else None),
                "sid": context["sid"],
                "proj": context["proj"],
                "agent": context["agent"],
                "parser_version": _KIMI_PARSER_VERSION,
            }
            changed = True
        elif any(entry.get(key) != context[key] for key in ("sid", "proj", "agent")):
            entry.update(context)
            changed = True

    for path in stale:
        fc.pop(path, None)
        changed = True

    live_days = {}
    live_sessions = {}
    live_projects = {}
    for path, entry in fc.items():
        if not isinstance(entry, dict):
            continue
        for day_key, day in entry.get("days", {}).items():
            try:
                date.fromisoformat(day_key)
            except (TypeError, ValueError):
                continue
            _merge_live_token_day(live_days.setdefault(day_key, _empty_token_day()), day)
            session = entry.get("sid") or path
            live_sessions.setdefault(day_key, set()).add(session)
            project = entry.get("proj")
            if isinstance(project, str) and project:
                live_projects.setdefault(day_key, set()).add(project)

    for day_key, day in live_days.items():
        day["sessions"] = sorted(live_sessions.get(day_key, set()))
        day["_cost_version"] = _OPENCODE_COST_CACHE_VERSION
        day["projects"] = sorted(live_projects.get(day_key, set()))

    for day_key, day in ledger_reconcile("kimicode", live_days, _ledger_file_sources(fc, "sid")).items():
        try:
            local_day = date.fromisoformat(day_key)
        except (TypeError, ValueError):
            continue
        for range_key in classify_date(local_day, bounds):
            _merge_token_day(B[range_key], day)
            B[range_key]["sessions"].update(day.get("sessions", []))
    if changed:
        cache["_dirty"] = True
    return {"ranges": B}


# ---------- Muse Code CLI ----------
# 会话日志 sessions/YYYY/MM/DD/<sid>/session.jsonl,顶层 JSONL 记录:
#   payload_type=runtime.session.metadata → payload.record.workspace_root(项目)
#   payload_type=run.model.configured → payload.record.run_stream.id/model_id(运行→模型)
#   payload.kind=run 且 event.kind=model_completed → event.usage + event.model(用量事件)
# input_tokens 含 cached(与 Codex 同口径):输入=input-cached,缓存读=cached,推理视为输出子集。
# 日志不持久化成本,按价格表估算(muse-* → meta/muse-*,见 _normalize)。
_MUSE_PARSER_VERSION = 1
_MUSE_SESSION_PATTERNS = (
    os.path.join("sessions", "*", "*", "*", "*", "session.jsonl"),
    os.path.join("sessions", "*", "session.jsonl"),
)


def _muse_roots():
    configured = os.environ.get("TOKEI_MUSE_DIR")
    if configured:
        candidates = [configured]
    elif os.path.normcase(MUSE_DIR) != os.path.normcase(_MUSE_DEFAULT_DIR):
        # Tests and embedders may replace MUSE_DIR after importing this module.
        candidates = [MUSE_DIR]
    else:
        candidates = [_MUSE_DEFAULT_DIR]
    roots = []
    seen = set()
    for candidate in candidates:
        root = os.path.abspath(os.path.expanduser(candidate))
        key = os.path.normcase(os.path.realpath(root))
        if key not in seen:
            seen.add(key)
            roots.append(root)
    return roots


def _muse_session_files():
    files = []
    for root in _muse_roots():
        for pattern in _MUSE_SESSION_PATTERNS:
            for path in glob.glob(os.path.join(root, pattern)):
                if os.path.isfile(path):
                    files.append(os.path.abspath(path))
    return sorted(set(files))


def _muse_number(value):
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _muse_datetime(value):
    try:
        epoch = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(epoch):
        return None
    if epoch > 100_000_000_000_000:  # 微秒
        epoch /= 1_000_000
    elif epoch > 100_000_000_000:  # 毫秒
        epoch /= 1000
    try:
        return datetime.fromtimestamp(epoch).astimezone()
    except (OSError, OverflowError, ValueError):
        return None


def _muse_token_total(usage):
    return sum(usage.get(key, 0) for key in ("in", "out", "cr", "cw"))


def _muse_event_cost(model, inp, out, cr, cw):
    price_id = _pricing_id(model)
    if not price_id:
        return 0.0
    price = _raw_price(price_id)
    return (inp / 1e6 * price["in"] + out / 1e6 * price["out"]
            + cr / 1e6 * price["cache_read"] + cw / 1e6 * price["cache_write"])


def _scan_muse_session(path):
    """→ (days, sid, proj)。只认 model_completed 用量事件,按 source_run_record_id 去重。"""
    days = {}
    seen_records = set()
    sid = None
    proj = None
    run_models = {}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if ('"model_completed"' not in line
                        and '"run.model.configured"' not in line
                        and '"runtime.session.metadata"' not in line):
                    continue
                try:
                    record = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if not isinstance(record, dict):
                    continue
                stream = record.get("stream")
                if sid is None and isinstance(stream, dict):
                    stream_id = stream.get("id")
                    if isinstance(stream_id, str) and stream_id:
                        sid = stream_id
                payload_type = record.get("payload_type")
                payload = record.get("payload")
                if not isinstance(payload, dict):
                    continue
                if payload_type == "runtime.session.metadata":
                    meta = payload.get("record")
                    if isinstance(meta, dict):
                        workspace = meta.get("workspace_root")
                        if isinstance(workspace, str) and workspace:
                            proj = workspace
                    continue
                if payload_type == "run.model.configured":
                    meta = payload.get("record")
                    if isinstance(meta, dict):
                        run_stream = meta.get("run_stream")
                        model_id = meta.get("model_id")
                        if (isinstance(run_stream, dict) and isinstance(model_id, str)
                                and model_id and model_id != "same-as-main"):
                            run_id = run_stream.get("id")
                            if isinstance(run_id, str) and run_id:
                                run_models[run_id] = model_id
                    continue
                if payload_type != "runtime.session" or payload.get("kind") != "run":
                    continue
                event = payload.get("event")
                if not isinstance(event, dict) or event.get("kind") != "model_completed":
                    continue
                usage = event.get("usage")
                if not isinstance(usage, dict):
                    continue
                input_total = _muse_number(usage.get("input_tokens"))
                cached = _muse_number(usage.get("cached_tokens",
                                                usage.get("cache_read_tokens")))
                cached = min(cached, input_total)
                inp = input_total - cached
                out = _muse_number(usage.get("output_tokens"))
                cw = _muse_number(usage.get("cache_write_tokens"))
                reason = _muse_number(usage.get("reasoning_tokens"))
                if inp + out + cached + cw + reason == 0:
                    continue
                record_id = record.get("source_run_record_id")
                if isinstance(record_id, str) and record_id:
                    if record_id in seen_records:
                        continue
                    seen_records.add(record_id)
                model = event.get("model")
                if not isinstance(model, str) or not model or model == "same-as-main":
                    model = run_models.get(payload.get("run_id", ""), "")
                if not model:
                    model = None
                display_model = _known_id_or_raw(model) if model else None
                cost = _muse_event_cost(model or "unknown", inp, out, cached, cw)
                dt = _muse_datetime(record.get("recorded_at"))
                if dt is None:
                    continue
                day = days.setdefault(dt.date().isoformat(), _empty_token_day())
                _add_token_usage(day, inp, out, cached, cw, reason, cost, display_model)
                day["hours"][dt.hour] += inp + out + cached + cw
    except OSError:
        return {}, sid, proj
    return days, sid, proj


def scan_musecode(bounds, cache):
    ledger_touch("musecode")
    fc = cache.setdefault("musecode", {})
    B = _empty_token_ranges()
    files = _muse_session_files()
    if not files:
        if fc:
            fc.clear()
            cache["_dirty"] = True
    stale = set(fc)
    changed = False
    for path in files:
        stale.discard(path)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        signature = f"{stat.st_mtime_ns}:{stat.st_size}"
        entry = fc.get(path)
        if (not isinstance(entry, dict) or entry.get("sig") != signature
                or entry.get("parser_version") != _MUSE_PARSER_VERSION):
            days, sid, proj = _scan_muse_session(path)
            fc[path] = {
                "sig": signature,
                "days": days,
                "sid": sid or path,
                "proj": proj,
                "parser_version": _MUSE_PARSER_VERSION,
            }
            changed = True

    for path in stale:
        fc.pop(path, None)
        changed = True

    live_days = {}
    live_sessions = {}
    live_projects = {}
    for path, entry in fc.items():
        if not isinstance(entry, dict):
            continue
        for day_key, day in entry.get("days", {}).items():
            try:
                date.fromisoformat(day_key)
            except (TypeError, ValueError):
                continue
            _merge_live_token_day(live_days.setdefault(day_key, _empty_token_day()), day)
            session = entry.get("sid") or path
            live_sessions.setdefault(day_key, set()).add(session)
            project = entry.get("proj")
            if isinstance(project, str) and project:
                live_projects.setdefault(day_key, set()).add(project)

    for day_key, day in live_days.items():
        day["sessions"] = sorted(live_sessions.get(day_key, set()))
        day["projects"] = sorted(live_projects.get(day_key, set()))

    for day_key, day in ledger_reconcile("musecode", live_days).items():
        try:
            local_day = date.fromisoformat(day_key)
        except (TypeError, ValueError):
            continue
        for range_key in classify_date(local_day, bounds):
            _merge_token_day(B[range_key], day)
            B[range_key]["sessions"].update(day.get("sessions", []))
    if changed:
        cache["_dirty"] = True
    return {"ranges": B}


# ---------- Command Code CLI ----------
# 会话日志 projects/<project-slug>/<session-id>.jsonl。usage 的 input/cache 桶彼此独立,
# costUsd 为日志持久化的真实成本。事件按消息身份跨转录文件去重。
_CMDCODE_PARSER_VERSION = 3
_CMDCODE_SESSION_PATTERNS = (
    os.path.join("projects", "*", "*.jsonl"),
)


def _cmdcode_roots():
    configured = os.environ.get("TOKEI_CMDCODE_DIR")
    if configured:
        candidates = [configured]
    elif os.path.normcase(CMDCODE_DIR) != os.path.normcase(_CMDCODE_DEFAULT_DIR):
        # Tests and embedders may replace CMDCODE_DIR after importing this module.
        candidates = [CMDCODE_DIR]
    else:
        candidates = [_CMDCODE_DEFAULT_DIR]
    roots = []
    seen = set()
    for candidate in candidates:
        root = os.path.abspath(os.path.expanduser(candidate))
        key = os.path.normcase(os.path.realpath(root))
        if key not in seen:
            seen.add(key)
            roots.append(root)
    return roots


def _cmdcode_session_files():
    files = []
    for root in _cmdcode_roots():
        for pattern in _CMDCODE_SESSION_PATTERNS:
            for path in glob.glob(os.path.join(root, pattern)):
                name = os.path.basename(path)
                stem = name[:-len(".jsonl")] if name.endswith(".jsonl") else name
                if name.startswith("hooks-audit-") or "." in stem:
                    continue
                if os.path.isfile(path):
                    files.append(os.path.abspath(path))
    return sorted(set(files))


def _cmdcode_number(value):
    if isinstance(value, bool):
        return 0
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _cmdcode_cost(value):
    if isinstance(value, bool):
        return 0.0
    try:
        amount = float(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return amount if math.isfinite(amount) and 0 <= amount <= 1_000_000 else 0.0


def _cmdcode_datetime(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone()
    except (OSError, OverflowError, ValueError):
        return None


def _scan_cmdcode_session(path):
    """→ (events, sid, proj)。保留事件身份,供转录文件之间统一去重。"""
    events = []
    seen_messages = set()
    sid = None
    proj = None
    active_model = None
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if not any(marker in line for marker in ('"assistant"', '"session"', '"model_change"')):
                    continue
                try:
                    record = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if not isinstance(record, dict):
                    continue
                record_type = record.get("type")
                if record_type == "session":
                    session_id = record.get("id") or record.get("sessionId")
                    if isinstance(session_id, str) and session_id and sid is None:
                        sid = session_id
                    workspace = record.get("cwd")
                    if isinstance(workspace, str) and workspace and proj is None:
                        proj = workspace
                    model = record.get("model")
                    if isinstance(model, str) and model:
                        active_model = model
                    continue
                if record_type == "model_change":
                    model = record.get("model")
                    if isinstance(model, str) and model:
                        active_model = model
                    continue
                message = record.get("message")
                nested = message if isinstance(message, dict) else {}
                role = nested.get("role") or record.get("role")
                if role != "assistant" or record_type not in (None, "message"):
                    continue
                session_id = record.get("sessionId") or record.get("session_id")
                if isinstance(session_id, str) and session_id and sid is None:
                    sid = session_id
                usage = record.get("usage")
                if not isinstance(usage, dict):
                    usage = nested.get("usage")
                if not isinstance(usage, dict):
                    continue
                inp = _cmdcode_number(usage.get("inputTokens"))
                out = _cmdcode_number(usage.get("outputTokens"))
                cr = _cmdcode_number(usage.get("cacheReadTokens"))
                cw = _cmdcode_number(usage.get("cacheWriteTokens"))
                cost = _cmdcode_cost(usage.get("costUsd"))
                if inp + out + cr + cw == 0 and cost == 0:
                    continue
                timestamp = record.get("timestamp") or nested.get("timestamp")
                dt = _cmdcode_datetime(timestamp)
                if dt is None:
                    continue
                message_id = record.get("id") or record.get("messageId") or nested.get("id")
                if isinstance(message_id, str) and message_id:
                    identity_text = f"{message_id}\0{timestamp}"
                else:
                    identity_text = json.dumps(
                        {"timestamp": timestamp, "usage": usage,
                         "model": record.get("model") or nested.get("model") or active_model},
                        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                    )
                identity = hashlib.sha256(identity_text.encode("utf-8")).hexdigest()
                if identity in seen_messages:
                    continue
                seen_messages.add(identity)
                model = record.get("model") or nested.get("model") or active_model
                display_model = _known_id_or_raw(model) if isinstance(model, str) and model else None
                events.append({
                    "id": identity, "day": dt.date().isoformat(), "hour": dt.hour,
                    "in": inp, "out": out, "cr": cr, "cw": cw, "reason": 0,
                    "cost": cost, "model": display_model,
                })
    except OSError:
        return [], sid, proj
    return events, sid, proj


def scan_cmdcode(bounds, cache):
    ledger_touch("cmdcode")
    fc = cache.setdefault("cmdcode", {})
    B = _empty_token_ranges()
    files = _cmdcode_session_files()
    if not files and fc:
        fc.clear()
        cache["_dirty"] = True
    stale = set(fc)
    changed = False
    for path in files:
        stale.discard(path)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        signature = f"{stat.st_mtime_ns}:{stat.st_size}"
        entry = fc.get(path)
        if (not isinstance(entry, dict) or entry.get("sig") != signature
                or entry.get("parser_version") != _CMDCODE_PARSER_VERSION):
            events, sid, proj = _scan_cmdcode_session(path)
            fc[path] = {
                "sig": signature,
                "events": events,
                "days": {},
                "sid": sid or path,
                "proj": proj,
                "parser_version": _CMDCODE_PARSER_VERSION,
            }
            changed = True

    for path in stale:
        fc.pop(path, None)
        changed = True

    live_days = {}
    live_sessions = {}
    live_projects = {}
    source_days = {}
    seen_events = set()
    for path, entry in sorted(fc.items()):
        if not isinstance(entry, dict):
            continue
        entry_days = {}
        for event in entry.get("events", []):
            if not isinstance(event, dict):
                continue
            identity = event.get("id")
            day_key = event.get("day")
            hour = event.get("hour")
            if not identity or identity in seen_events:
                continue
            try:
                date.fromisoformat(day_key)
            except (TypeError, ValueError):
                continue
            seen_events.add(identity)
            day = entry_days.setdefault(day_key, _empty_token_day())
            _add_token_usage(
                day, event.get("in", 0), event.get("out", 0),
                event.get("cr", 0), event.get("cw", 0), event.get("reason", 0),
                event.get("cost", 0), event.get("model"),
            )
            if isinstance(hour, int) and 0 <= hour < 24:
                day["hours"][hour] += token_total(event)
            _ledger_add_record_source(source_days, identity, day_key, event, hour)
            source_days[identity][day_key]["_accounting_version"] = _CMDCODE_PARSER_VERSION
        if entry.get("days") != entry_days:
            entry["days"] = entry_days
            changed = True
        for day_key, day in entry_days.items():
            _merge_live_token_day(live_days.setdefault(day_key, _empty_token_day()), day)
            session = entry.get("sid") or path
            live_sessions.setdefault(day_key, set()).add(session)
            project = entry.get("proj")
            if isinstance(project, str) and project:
                live_projects.setdefault(day_key, set()).add(project)

    for day_key, day in live_days.items():
        day["sessions"] = sorted(live_sessions.get(day_key, set()))
        day["projects"] = sorted(live_projects.get(day_key, set()))

    for day_key, day in ledger_reconcile("cmdcode", live_days, source_days).items():
        try:
            local_day = date.fromisoformat(day_key)
        except (TypeError, ValueError):
            continue
        for range_key in classify_date(local_day, bounds):
            _merge_token_day(B[range_key], day)
            B[range_key]["sessions"].update(live_sessions.get(day_key, set()))
    if changed:
        cache["_dirty"] = True
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


def _claude_cache_records():
    cache_dirs = _existing_dirs(
        _path_candidates("TOKEI_CLAUDE_CACHE_DIR", CLAUDE_CACHE, *CLAUDE_CACHE_DIRS))
    records = {}
    for cache_dir in cache_dirs:
        # realpath 会对路径每一级都 lstat 一遍。这一万个文件共享同一个目录前缀,
        # 逐个 realpath 等于把同样的目录解析重复一万次,所以前缀只解析一次。
        real_dir = os.path.realpath(cache_dir)
        for path in glob.glob(os.path.join(cache_dir, "*_0")):
            try:
                if os.path.islink(path):
                    real = os.path.realpath(path)
                    st = os.stat(real)
                else:
                    real = os.path.join(real_dir, os.path.basename(path))
                    st = os.stat(path)
                records[real] = {
                    "path": real,
                    "mtime_ns": st.st_mtime_ns,
                    "size": st.st_size,
                }
            except OSError:
                continue
    return sorted(records.values(), key=lambda r: (r["mtime_ns"], r["path"]), reverse=True)


def _claude_cache_files():
    return [record["path"] for record in _claude_cache_records()]


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


# 首次全量定位 /usage，之后只检查变化项并复用最近一次有效候选。
_CLAUDE_QUOTA_STATE_VERSION = 3
_CLAUDE_QUOTA_STALE_TTL = 1800
_CLAUDE_QUOTA_FULL_SCAN_INTERVAL = 6 * 3600
_CLAUDE_QUOTA_RETRY_SCAN_INTERVAL = 5 * 60
_CLAUDE_CACHE_FILE_LIMIT = 16 * 1024 * 1024
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
# 水位线只认不超过当前时间的 mtime(留 5 分钟容差防时钟微偏);未来时间戳的
# 文件不参与水位线计算,只读一次记入 scan_boundary(issue #71)。
_CLAUDE_QUOTA_FUTURE_SKEW = 5 * 60


def _claude_record_signature(record):
    return f'{record["path"]}|{record["mtime_ns"]}|{record["size"]}'


def _load_claude_quota_state():
    state = _load_json(CLAUDE_QUOTA_CACHE, {})
    if not isinstance(state, dict) or state.get("version") != _CLAUDE_QUOTA_STATE_VERSION:
        return {"version": _CLAUDE_QUOTA_STATE_VERSION}
    return state


def _save_claude_quota_state(state):
    try:
        _atomic_write_json(CLAUDE_QUOTA_CACHE, state)
        os.chmod(CLAUDE_QUOTA_CACHE, 0o600)
    except Exception:
        pass


def _parse_claude_quota_record(record):
    if record["size"] <= 0 or record["size"] > _CLAUDE_CACHE_FILE_LIMIT:
        return None
    try:
        with open(record["path"], "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    if b"organizations/" not in data or b"/usage" not in data:
        return None
    pos = data.find(_ZSTD_MAGIC)
    if pos < 0:
        return None
    raw = _zstd_decompress(data[pos:])
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    five_hour = payload.get("five_hour") or {}
    seven_day = payload.get("seven_day") or {}
    if not isinstance(five_hour, dict):
        five_hour = {}
    if not isinstance(seven_day, dict):
        seven_day = {}
    fable_limit = {}
    limits = payload.get("limits") or []
    if isinstance(limits, list):
        for limit in limits:
            if not isinstance(limit, dict) or limit.get("kind") != "weekly_scoped":
                continue
            scope = limit.get("scope") or {}
            model = scope.get("model") or {} if isinstance(scope, dict) else {}
            display_name = model.get("display_name") if isinstance(model, dict) else None
            if isinstance(display_name, str) and display_name.casefold() == "fable":
                fable_limit = limit
                break
    result = {
        "q5": five_hour.get("utilization"),
        "q5_reset": _iso_to_epoch(five_hour.get("resets_at")),
        "q7": seven_day.get("utilization"),
        "q7_reset": _iso_to_epoch(seven_day.get("resets_at")),
        "qf": fable_limit.get("percent"),
        "qf_reset": _iso_to_epoch(fable_limit.get("resets_at")),
        "q_updated": int(record["mtime_ns"] // 1_000_000_000),
    }
    return result if any(result[key] is not None for key in ("q5", "q7", "qf")) else None


def _claude_quota_with_freshness(snapshot, now=None):
    if not isinstance(snapshot, dict):
        return {}
    import time
    now = int(time.time()) if now is None else int(now)
    result = dict(snapshot)
    try:
        updated = int(result.get("q_updated"))
    except (TypeError, ValueError):
        updated = 0
    age = now - updated
    source_stale = updated <= 0 or age > _CLAUDE_QUOTA_STALE_TTL or age < -300
    for value_key, reset_key, stale_key in (
        ("q5", "q5_reset", "q5_stale"),
        ("q7", "q7_reset", "q7_stale"),
        ("qf", "qf_reset", "qf_stale"),
    ):
        reset = result.get(reset_key)
        try:
            reset_expired = reset is not None and int(reset) <= now
        except (TypeError, ValueError):
            reset_expired = False
        result[stale_key] = bool(result.get(value_key) is not None and
                                 (source_stale or reset_expired))
    return result


def _claude_quota_from_environment(now=None):
    """Read the native Swift decoder result passed by Tokei.

    The bundled app can decompress Chromium's zstd response without depending on
    a user-installed Python module. Only quota percentages and reset timestamps
    cross the process boundary.
    """
    raw = os.environ.get("TOKEI_CLAUDE_QUOTA_JSON")
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    allowed = {
        "q5", "q5_reset", "q7", "q7_reset", "qf", "qf_reset", "q_updated",
    }
    snapshot = {key: payload[key] for key in allowed if key in payload}
    if not any(snapshot.get(key) is not None for key in ("q5", "q7", "qf")):
        return None
    return _claude_quota_with_freshness(snapshot, now=now)


def _scan_claude_plan_raw(now=None):
    import time
    now = int(time.time()) if now is None else int(now)
    records = _claude_cache_records()
    records_by_path = {record["path"]: record for record in records}
    original = _load_claude_quota_state()
    state = dict(original)
    initial_scan = "scan_mtime_ns" not in state
    snapshot = state.get("snapshot") if isinstance(state.get("snapshot"), dict) else None
    candidate = state.get("candidate") if isinstance(state.get("candidate"), dict) else None
    last_scan_ns = int(state.get("scan_mtime_ns") or -1)
    scan_boundary = set(state.get("scan_boundary") or [])

    changed = [
        record for record in records
        if record["mtime_ns"] > last_scan_ns or
        (record["mtime_ns"] == last_scan_ns and
         _claude_record_signature(record) not in scan_boundary)
    ]
    inspected = set()
    selected = None

    def inspect(record):
        inspected.add(record["path"])
        parsed = _parse_claude_quota_record(record)
        return (record, parsed) if parsed else None

    horizon_ns = (now + _CLAUDE_QUOTA_FUTURE_SKEW) * 1_000_000_000
    for record in changed:
        # 未来时间戳文件跳过内容解析:签名已在 scan_boundary,只读一次。
        if record["mtime_ns"] > horizon_ns:
            inspected.add(record["path"])
            continue
        selected = inspect(record)
        if selected:
            break

    candidate_invalid = False
    candidate_record = records_by_path.get(candidate.get("path")) if candidate else None
    if selected is None and candidate:
        if candidate_record is None:
            candidate_invalid = True
        else:
            candidate_changed = (
                candidate_record.get("mtime_ns") != candidate.get("mtime_ns") or
                candidate_record.get("size") != candidate.get("size")
            )
            if candidate_changed and candidate_record["path"] not in inspected:
                selected = inspect(candidate_record)
                candidate_invalid = selected is None
            elif candidate_changed:
                candidate_invalid = True

    if initial_scan:
        state["last_full_scan"] = now

    last_full_scan = int(state.get("last_full_scan") or 0)
    retry_interval = (_CLAUDE_QUOTA_RETRY_SCAN_INTERVAL if snapshot is None
                      else _CLAUDE_QUOTA_FULL_SCAN_INTERVAL)
    needs_full_scan = (candidate_invalid or now - last_full_scan >= retry_interval)
    if selected is None and needs_full_scan:
        for record in records:
            if record["path"] in inspected:
                continue
            selected = inspect(record)
            if selected:
                break
        state["last_full_scan"] = now

    if selected:
        record, snapshot = selected
        state["candidate"] = {
            "path": record["path"],
            "mtime_ns": record["mtime_ns"],
            "size": record["size"],
        }
        state["snapshot"] = snapshot
    elif candidate_invalid:
        state.pop("candidate", None)

    if records:
        horizon_ns = (now + _CLAUDE_QUOTA_FUTURE_SKEW) * 1_000_000_000
        past = [record for record in records if record["mtime_ns"] <= horizon_ns]
        future = [record for record in records if record["mtime_ns"] > horizon_ns]
        base = past or records
        newest_mtime = base[0]["mtime_ns"]
        state["scan_mtime_ns"] = newest_mtime
        state["scan_boundary"] = [
            _claude_record_signature(record)
            for record in base if record["mtime_ns"] == newest_mtime
        ] + [
            # 未来时间戳文件只读一次,不再每轮重复读取,也不参与水位线。
            _claude_record_signature(record)
            for record in future if record["path"] not in inspected
        ]
    else:
        state["scan_mtime_ns"] = -1
        state["scan_boundary"] = []
    state["version"] = _CLAUDE_QUOTA_STATE_VERSION
    if state != original:
        _save_claude_quota_state(state)
    return _claude_quota_with_freshness(snapshot, now=now)


def scan_claude_plan():
    return _claude_quota_from_environment() or _scan_claude_plan_raw()


@_with_scan_cache_lock
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
    qcli = _safe_scan("qodercli", lambda: scan_qodercli(bounds, cache), _empty_qodercli, errors)
    hm = _safe_scan("hermes", lambda: scan_hermes(bounds, cache), _empty_hermes, errors)
    zc = _safe_scan("zcode", lambda: scan_zcode(bounds, cache), _empty_zcode, errors)
    dv = _safe_scan("devin", lambda: scan_devin(bounds, cache), _empty_devin, errors)
    mc = _safe_scan("mimocode", lambda: scan_mimocode(bounds, cache), _empty_mimocode, errors)
    oc = _safe_scan("openclaw", lambda: scan_openclaw(bounds, cache), _empty_openclaw, errors)
    pi = _safe_scan("pi", lambda: scan_pi(bounds, cache), _empty_pi, errors)
    prime = _safe_scan("prime_agent", lambda: scan_prime_agent(bounds, cache), _empty_prime_agent, errors)
    wb = _safe_scan("workbuddy", lambda: scan_workbuddy(bounds, cache), _empty_workbuddy, errors)
    wbai = _safe_scan("workbuddy_ai", lambda: scan_workbuddy_ai(bounds, cache),
                      _empty_workbuddy, errors)
    cb = _safe_scan("codebuddy", lambda: scan_codebuddy(bounds, cache),
                    _empty_workbuddy, errors)
    grok_bot = _safe_scan("grok_bot", lambda: scan_grok_bot(bounds, cache),
                          _empty_grok_bot, errors)
    dsh = _safe_scan("deepseek_harness", lambda: scan_deepseek_harness(bounds, cache),
                     _empty_deepseek_harness, errors)
    ocode = _safe_scan("opencode", lambda: scan_opencode(bounds, cache), _empty_opencode, errors)
    qwc = _safe_scan("qwencode", lambda: scan_qwencode(bounds, cache), _empty_qwencode, errors)
    kimi = _safe_scan("kimicode", lambda: scan_kimicode(bounds, cache), _empty_kimicode, errors)
    muse = _safe_scan("musecode", lambda: scan_musecode(bounds, cache), _empty_musecode, errors)
    cmdcode = _safe_scan("cmdcode", lambda: scan_cmdcode(bounds, cache), _empty_cmdcode, errors)
    _cache_dashboard_days(cache, _GEMINI_DAYS_CACHE_KEY, gm.get("days", {}))
    _cache_dashboard_days(cache, _GROK_DAYS_CACHE_KEY, gk.get("days", {}))
    if cache.pop("_pricing_changed", False):
        cache.pop("_pricing_changed_models", None)
        cache.pop("_pricing_cost_multipliers", None)
        cache["_pricing_fingerprint"] = _PRICING_FINGERPRINT
        cache["_pricing_effective"] = _PRICING_EFFECTIVE
        cache["_pricing_aliases"] = _OV_ALIASES
        cache["_dirty"] = True
    _save_scan_cache(cache)
    ledger_flush()

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
        b = b or {}
        hit = (b.get("cached", 0) / b["in"] * 100) if b.get("in") else 0.0
        return {"hit": hit, "in": b.get("in", 0) - b.get("cached", 0), "cached": b.get("cached", 0),
                "out": b.get("out", 0), "reason": b.get("reason", 0), "cost": b.get("cost", 0.0),
                "sessions": len(b.get("sessions", set())), "models": _format_token_models(b.get("models", {}))}

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
        usage_total = sum(int(b.get(key, 0) or 0) for key in ("in", "out", "cr", "reason"))
        usage_available = b.get("usage_calls", 0) > 0
        input_total = b.get("in", 0) + b.get("cr", 0)
        hit = (b.get("cr", 0) / input_total * 100) if input_total else 0.0
        return {"tokens": usage_total if usage_available else b.get("ctx_used", 0),
                "hit": hit, "in": b.get("in", 0), "out": b.get("out", 0),
                "cr": b.get("cr", 0), "reason": b.get("reason", 0),
                "cost": b.get("cost", 0.0),
                "models": _format_token_models(b.get("models", {}), include_prices=True),
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
    xreserveranges = {k: codex_range(cx.get("reserve_ranges", {}).get(k, {}))
                      for k in RANGE_KEYS}
    granges = {k: gemini_range(gm["ranges"][k]) for k in RANGE_KEYS}
    kranges = {k: grok_range(gk["ranges"][k]) for k in RANGE_KEYS}
    qwranges = {k: qoderwork_range(qd["ranges"][k]) for k in RANGE_KEYS}
    qranges = {k: qoder_range(qi["ranges"][k]) for k in RANGE_KEYS}

    def qodercli_range(b):
        r = qoderwork_range(b)
        input_total = b.get("in", 0) + b.get("cr", 0) + b.get("cw", 0)
        r.update({
            "cr": b.get("cr", 0),
            "cw": b.get("cw", 0),
            "credits": b.get("credits", 0.0),
            "usage_calls": b.get("usage_calls", 0),
            "usage_available": bool(b.get("usage_calls", 0)),
            "hit": (b.get("cr", 0) / input_total * 100) if input_total else 0.0,
            "models": _format_token_models(b.get("models", {}), include_prices=False),
            "tools": b.get("tools", 0),
            "est": int(b.get("est", 0)),
        })
        return r

    qcliranges = {k: qodercli_range(qcli["ranges"][k]) for k in RANGE_KEYS}

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
                "reason": b["reason"], "cost": b["cost"], "sessions": len(b["sessions"]),
                "models": _format_token_models(b["models"])}

    hranges = {k: hermes_range(hm["ranges"][k]) for k in RANGE_KEYS}
    oranges = {k: openclaw_range(oc["ranges"][k]) for k in RANGE_KEYS}

    def token_usage_range(b):
        denom = b["cr"] + b["cw"] + b["in"]
        hit = (b["cr"] / denom * 100) if denom else 0.0
        return {"hit": hit, "in": b["in"], "out": b["out"], "cr": b["cr"], "cw": b["cw"],
                "reason": b["reason"], "cost": b["cost"], "cost_cny": b.get("cost_cny", 0),
                "credits": b.get("credits", 0.0), "sessions": len(b["sessions"]),
                "models": _format_token_models(b["models"])}

    piranges = {k: token_usage_range(pi["ranges"][k]) for k in RANGE_KEYS}
    paranges = {k: token_usage_range(prime["ranges"][k]) for k in RANGE_KEYS}
    zcranges = {k: token_usage_range(zc["ranges"][k]) for k in RANGE_KEYS}
    dvranges = {k: token_usage_range(dv["ranges"][k]) for k in RANGE_KEYS}
    mcranges = {k: token_usage_range(mc["ranges"][k]) for k in RANGE_KEYS}
    wbranges = {k: token_usage_range(wb["ranges"][k]) for k in RANGE_KEYS}
    wbairanges = {k: token_usage_range(wbai["ranges"][k]) for k in RANGE_KEYS}
    cbranges = {k: token_usage_range(cb["ranges"][k]) for k in RANGE_KEYS}
    grok_bot_ranges = {
        key: {
            "in": 0, "out": 0,
            "sessions": len(grok_bot["ranges"][key].get("sessions", [])),
            "calls": grok_bot["ranges"][key].get("calls", 0),
            "turns": grok_bot["ranges"][key].get("turns", 0),
            "tools": grok_bot["ranges"][key].get("tools", 0),
            "duration": grok_bot["ranges"][key].get("duration", 0),
        }
        for key in RANGE_KEYS
    }
    dshranges = {k: token_usage_range(dsh["ranges"][k]) for k in RANGE_KEYS}
    ocranges = {k: token_usage_range(ocode["ranges"][k]) for k in RANGE_KEYS}
    qwcranges = {k: token_usage_range(qwc["ranges"][k]) for k in RANGE_KEYS}
    kimiranges = {k: token_usage_range(kimi["ranges"][k]) for k in RANGE_KEYS}
    museranges = {k: token_usage_range(muse["ranges"][k]) for k in RANGE_KEYS}

    cmdcranges = {k: token_usage_range(cmdcode["ranges"][k]) for k in RANGE_KEYS}

    cur = cc["cur"]
    cur_total = cur["in"] + cur["out"] + cur["cr"] + cur["cw"]

    quota = _codex_quota_values(cx["limits"], consumed=cx.get("limits_consumed"))
    p5, pw = quota["p5"], quota["pw"]
    r5, rw = quota["r5"], quota["rw"]

    plan = _safe_scan("claude_plan", scan_claude_plan, lambda: {}, errors) or {}
    grok_quota = _safe_scan("grok_quota", scan_grok_quota, lambda: {}, errors) or {}
    qwenwork_quota = _safe_scan(
        "qwenwork_quota", scan_qwenwork_quota, lambda: {}, errors) or {}
    kimi_live = _safe_scan("kimi_quota", fetch_kimi_live_limits, lambda: None, errors)
    kimi_limits, kimi_plan, kimi_updated = kimi_live if kimi_live else (None, None, None)
    kimi_quota = _kimi_quota_values(kimi_limits, updated_at=kimi_updated)
    provider_quotas = scan_provider_quotas(errors)
    _cache_dashboard_days(
        cache, _CURSOR_PROVIDER_DAYS_CACHE_KEY,
        ((provider_quotas.get("cursor") or {}).get("usage") or {}).get("days", {}))
    _cache_dashboard_days(
        cache, _ZAI_PROVIDER_DAYS_CACHE_KEY,
        ((provider_quotas.get("zai") or {}).get("usage") or {}).get("days", {}))
    _merge_dashboard_days(
        cache, _GROK_BOT_PROVIDER_DAYS_CACHE_KEY,
        ((provider_quotas.get("grok_bot") or {}).get("usage") or {}).get("days", {}))
    grok_bot_days = cache.get(_GROK_BOT_PROVIDER_DAYS_CACHE_KEY)
    if isinstance(grok_bot_days, dict) and grok_bot_days:
        grok_bot_quota = dict(provider_quotas.get("grok_bot") or {})
        if not grok_bot_quota:
            grok_bot_quota = {
                "available": False, "plan": None, "account": None,
                "windows": [], "details": [], "source": "cache",
                "updated": None, "stale": True,
            }
        grok_bot_quota["usage"] = _provider_usage_from_days(grok_bot_days)
        provider_quotas["grok_bot"] = grok_bot_quota
    _save_scan_cache(cache)
    codex_reset_cards = _safe_scan(
        "codex_reset_cards", fetch_codex_reset_cards, lambda: {}, errors) or {}

    result = {
        "claude": {
            "ranges": cranges,
            "session_name": cur["name"], "session_total": cur_total,
            "q5": plan.get("q5"), "q5_reset": plan.get("q5_reset"),
            "q7": plan.get("q7"), "q7_reset": plan.get("q7_reset"),
            "qf": plan.get("qf"), "qf_reset": plan.get("qf_reset"),
            "q_updated": plan.get("q_updated"),
            "q5_stale": plan.get("q5_stale"), "q7_stale": plan.get("q7_stale"),
            "qf_stale": plan.get("qf_stale"),
        },
        "codex": {
            "ranges": xranges,
            "reserve_ranges": xreserveranges,
            "reserve_quota": cx.get("reserve_quota"),
            "p5": p5, "pw": pw, "r5": r5, "rw": rw,
            "q_updated": cx.get("limits_updated"),
            "p5_stale": quota["p5_stale"], "pw_stale": quota["pw_stale"],
            "plan": cx["plan"],
            "reset_cards": codex_reset_cards if codex_reset_cards.get("count", 0) > 0 else None,
        },
        "gemini": {
            "ranges": granges,
        },
        "antigravity": provider_quotas["antigravity"],
        "devin": {
            "ranges": dvranges,
            "quota": provider_quotas["devin"],
        },
        "cursor": provider_quotas["cursor"],
        "zed": provider_quotas["zed"],
        "sub2api": provider_quotas["sub2api"],
        "zai": provider_quotas["zai"],
        "grok": {
            "ranges": kranges,
            "model": gk["model"],
            "pct": grok_quota.get("pct"),
            "reset": grok_quota.get("reset"),
            "plan": grok_quota.get("plan"),
            "products": grok_quota.get("products") or [],
            "window": grok_quota.get("window"),
            "source": grok_quota.get("source"),
            "q_updated": grok_quota.get("updated"),
            "stale": grok_quota.get("stale"),
        },
        "grok_bot": {
            "ranges": grok_bot_ranges,
            "quota": provider_quotas["grok_bot"],
        },
        "qwenwork": qwenwork_quota,
        "qoderwork": {
            "ranges": qwranges,
            "model": qd.get("model"),
        },
        "qoder": {
            "ranges": qranges,
            "model": qi.get("model"),
        },
        "qodercli": {
            "ranges": qcliranges,
            "model": qcli.get("model"),
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
        "prime_agent": {
            "ranges": paranges,
        },
        "workbuddy": {
            "ranges": wbranges,
        },
        "workbuddy_ai": {
            "ranges": wbairanges,
        },
        "codebuddy": {
            "ranges": cbranges,
        },
        "deepseek_harness": {
            "ranges": dshranges,
        },
        "opencode": {
            "ranges": ocranges,
        },
        "qwencode": {
            "ranges": qwcranges,
        },
        "kimicode": {
            "ranges": kimiranges,
            "p5": kimi_quota["p5"], "pw": kimi_quota["pw"],
            "r5": kimi_quota["r5"], "rw": kimi_quota["rw"],
            "q_updated": int(kimi_updated) if kimi_updated else None,
            "p5_stale": kimi_quota["p5_stale"], "pw_stale": kimi_quota["pw_stale"],
            "plan": kimi_plan,
        },
        "musecode": {
            "ranges": museranges,
        },
        "cmdcode": {
            "ranges": cmdcranges,
        },
    }
    if errors:
        result["_errors"] = errors
    _recalc_costs(result)
    return result


def _recalc_costs(result):
    """只重算缺少权威账单的工具；已有日志成本的工具保留原值。"""
    for tool_key in ("gemini", "grok", "hermes", "zcode", "mimocode", "workbuddy",
                     "workbuddy_ai", "codebuddy",
                     "deepseek_harness", "qwencode", "devin"):
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
                model_id = m.get("model_id")
                price_id = (_exact_pricing_id(model_id) if isinstance(model_id, str) else None)
                if not price_id:
                    price_id = _pricing_id(name)
                authoritative_cost = float(m.get("cost", 0) or 0)
                if tool_key == "deepseek_harness":
                    total_cost += authoritative_cost
                    m["pin"] = 0
                    m["pout"] = 0
                    continue
                if tool_key == "hermes" and authoritative_cost:
                    total_cost += authoritative_cost
                    if price_id:
                        price = _raw_price(price_id)
                        m["pin"] = price["in"]
                        m["pout"] = price["out"]
                    continue
                if not price_id:
                    total_cost += authoritative_cost
                    m["pin"] = 0
                    m["pout"] = 0
                    continue
                p = _raw_price(price_id)
                ti = m.get("in", 0)
                to = m.get("out", 0)
                if tool_key == "gemini":
                    cached = m.get("cached", 0)
                    thoughts = m.get("thoughts", 0)
                    cost = (ti / 1e6 * p["in"] + (to + thoughts) / 1e6 * p["out"]
                            + cached / 1e6 * p["cache_read"])
                elif tool_key == "deepseek_harness":
                    cr = m.get("cr", 0)
                    cw = m.get("cw", 0)
                    reason = m.get("reason", 0)
                    p = _deepseek_official_price(name) or p
                    # 扫描阶段已按每次请求的 UTC 时刻套用峰谷价，聚合后保留该结果。
                    cost = authoritative_cost or (
                        ti / 1e6 * p["in"] + (to + reason) / 1e6 * p["out"]
                        + cr / 1e6 * p["cache_read"] + cw / 1e6 * p["cache_write"])
                elif tool_key in ("hermes", "zcode", "mimocode", "devin"):
                    cr = m.get("cr", 0)
                    cw = m.get("cw", 0)
                    reason = m.get("reason", 0)
                    cost = (ti / 1e6 * p["in"] + (to + reason) / 1e6 * p["out"]
                            + cr / 1e6 * p["cache_read"] + cw / 1e6 * p["cache_write"])
                elif tool_key == "grok":
                    cr = m.get("cr", 0)
                    reason = m.get("reason", 0)
                    # Grok is priced per request so the 200K context tier cannot be
                    # reconstructed from aggregate tokens. Keep the scanner's exact cost.
                    cost = authoritative_cost or (
                        ti / 1e6 * p["in"] + (to + reason) / 1e6 * p["out"]
                        + cr / 1e6 * p["cache_read"])
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


def _sync_snapshot_filename(device_id):
    if not isinstance(device_id, str):
        return None
    value = device_id.strip()
    if (not value or value in (".", "..") or len(value) > 128
            or any(ch in "/\\\0" or ord(ch) < 32 for ch in value)):
        return None
    return f"{value}.json"


def _write_sync_snapshot(sync_dir, device_id, payload):
    own_name = _sync_snapshot_filename(device_id)
    if not own_name or not os.path.isdir(sync_dir):
        return False

    sync_root = os.path.realpath(sync_dir)
    try:
        for fn in os.listdir(sync_root):
            if fn.casefold() == own_name.casefold():
                own_name = fn
                break
    except OSError:
        return False

    destination = os.path.abspath(os.path.join(sync_root, own_name))
    try:
        if os.path.commonpath((sync_root, destination)) != sync_root:
            return False
    except ValueError:
        return False

    tmp = None
    try:
        fd, tmp = _tempfile.mkstemp(prefix=".tokei-sync-", suffix=".json", dir=sync_root)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, destination)
        return True
    except OSError:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False


def _sync_safe_usage_payload(payload):
    snapshot = dict(payload)
    # Provider quotas are account-local, are not merged by SyncManager, and may
    # contain an email/login label. Keep them in the local cache only.
    for key in ("cursor", "zed", "sub2api", "zai", "antigravity"):
        snapshot.pop(key, None)
    kimi = snapshot.get("kimicode")
    if isinstance(kimi, dict):
        kimi = dict(kimi)
        for key in ("p5", "pw", "r5", "rw", "q_updated",
                    "p5_stale", "pw_stale", "plan"):
            kimi.pop(key, None)
        snapshot["kimicode"] = kimi
    # Grok Bot has no account label in its normalized output. Its official
    # aggregate stays in the snapshot so peers can adopt the freshest copy;
    # SyncManager replaces this quota instead of adding account totals.
    return snapshot


def _write_configured_sync_snapshot(d):
    cfg = _load_tokei_config()
    if not cfg:
        return False
    sync_dir = os.path.expanduser(cfg.get("sync_dir", ""))
    if not sync_dir:
        sync_dir = os.path.join(HOME, ".tokei", "sync")
    device_id = cfg.get("device_id", "")
    if not _sync_snapshot_filename(device_id) or not os.path.isdir(sync_dir):
        return False

    import time
    snapshot = _sync_safe_usage_payload(d)
    snapshot["_device"] = device_id
    snapshot["_ts"] = int(time.time())
    snapshot["_range_bounds"] = range_boundaries()
    cache = _load_scan_cache()
    snapshot["_dashboard"] = {
        "daily": build_daily_costs("all", refresh=False, _cache=cache).get("daily", []),
        "wrapped": {p: build_wrapped(p, refresh=False, _cache=cache)
                    for p in ["all", "1d", "7d", "30d", "365d"]},
    }
    return _write_sync_snapshot(sync_dir, device_id, snapshot)


def main_json():
    d = compute()
    meta = _load_json(PRICING_FILE, {}).get("_meta", {})
    d["_pricing"] = {"updated_at": meta.get("updated_at", ""), "count": meta.get("count", 0)}
    print(json.dumps(d, ensure_ascii=False))
    if "--no-sync-snapshot" not in sys.argv:
        _write_configured_sync_snapshot(d)


def write_sync_snapshot():
    d = compute()
    meta = _load_json(PRICING_FILE, {}).get("_meta", {})
    d["_pricing"] = {"updated_at": meta.get("updated_at", ""), "count": meta.get("count", 0)}
    # 账本随快照进同步仓:异地备份,本地账本丢失时可自愈恢复
    ledger = _load_ledger()
    if ledger.get("tools"):
        d["_ledger"] = ledger
    # 周期边界推不出来,只有观测到的那台机器知道 —— 不发布,别的机器就永远补不齐历史。
    anchors = _load_quota_anchors()
    if anchors:
        d["_quota_anchors"] = anchors
    return 0 if _write_configured_sync_snapshot(d) else 1


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
    p5_stale, pw_stale = x.get("p5_stale"), x.get("pw_stale")

    # ---- menu bar 标题(紧凑):⚡Claude命中率  ◷Codex周额度 ----
    parts = [f"⚡{cc_hit:.0f}"]
    if p5 is not None and not p5_stale:
        parts.append(f"◷{p5:.0f}")
    elif pw is not None and not pw_stale:
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
        if p5_stale:
            print(f"5h 额度  已过期 {F}")
        else:
            print(f"5h 额度  {p5:5.1f}%  reset {fmt_reset(r5)} {F}")
    if pw is not None:
        if pw_stale:
            print(f"周额度   已过期 {F}")
        else:
            print(f"周额度   {pw:5.1f}%  reset {fmt_reset(rw)} {F}")
    if x["plan"]:
        print(f"plan: {x['plan']} {F}")
    print("---")
    # Gemini / Antigravity 块
    g = d["gemini"]
    gt = g["ranges"]["today"]
    print(f"Gemini / Antigravity {HEAD}")
    print(f"命中率   {gt['hit']:5.1f}% {F}")
    print(f"今日 输入   {human(gt['in']):>6} {F}")
    print(f"今日 输出   {human(gt['out']):>6} {F}")
    print(f"今日 缓存   {human(gt['cached']):>6} {F}")
    if gt.get("thoughts"):
        print(f"今日 推理   {human(gt['thoughts']):>6} {F}")
    print(f"今日 ≈成本  ${gt['cost']:.2f} {F}")
    print(f"  (按 API 价估,非订阅实付) | font=Menlo size=11")
    print("---")
    # Grok Build 块：新版日志展示真实 token，旧版日志降级为上下文快照。
    gk = d["grok"]
    kt = gk["ranges"]["today"]
    print(f"Grok Build {HEAD}")
    print(f"今日 会话   {kt['sessions']:>6} {F}")
    if gk.get("pct") is not None and not gk.get("stale"):
        remaining = 100 - float(gk["pct"])
        print(f"周剩余   {remaining:5.1f}%  reset {fmt_reset(gk.get('reset'))} {F}")
        if gk.get("plan"):
            print(f"plan: {gk['plan']} {F}")
    if kt.get("usage_available"):
        print(f"今日 输入   {human(kt['in']):>6} {F}")
        print(f"今日 缓存   {human(kt['cr']):>6} {F}")
        print(f"今日 输出   {human(kt['out']):>6} {F}")
        if kt.get("reason"):
            print(f"今日 推理   {human(kt['reason']):>6} {F}")
        if kt.get("cost", 0) > 0:
            print(f"今日 ≈成本  ${kt['cost']:.2f} {F}")
    else:
        print(f"上下文快照 {human(kt['ctx_used']):>6} {F}")
    if gk.get("model"):
        print(f"model: {gk['model']} {F}")
    print(f"  (成本按 API 价估,订阅实付不按此) | font=Menlo size=11")
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
    # WorkBuddy AI 国际版块
    wat = d["workbuddy_ai"]["ranges"]["today"]
    if wat["sessions"] > 0:
        print(f"WorkBuddy Intl. {HEAD}")
        print(f"命中率   {wat['hit']:5.1f}% {F}")
        print(f"今日 输入   {human(wat['in']):>6} {F}")
        print(f"今日 输出   {human(wat['out']):>6} {F}")
        print(f"今日 缓存读 {human(wat['cr']):>6} {F}")
        print(f"今日 ≈成本  ${wat['cost']:.2f} {F}")
        print("---")
    # CodeBuddy 块：Credit 是产品原生消耗单位，不换算成美元。
    cbt = d["codebuddy"]["ranges"]["today"]
    if cbt["sessions"] > 0:
        print(f"CodeBuddy {HEAD}")
        print(f"命中率   {cbt['hit']:5.1f}% {F}")
        print(f"今日 输入   {human(cbt['in']):>6} {F}")
        print(f"今日 输出   {human(cbt['out']):>6} {F}")
        print(f"今日 缓存读 {human(cbt['cr']):>6} {F}")
        if cbt.get("credits", 0) > 0:
            print(f"今日 Credit {cbt['credits']:>6.2f} {F}")
        if cbt.get("cost", 0) > 0:
            print(f"今日 ≈成本  ${cbt['cost']:.2f} {F}")
        print("  (Credit 为 CodeBuddy 原生消耗单位；美元仅按已知价格估算) | font=Menlo size=11")
        print("---")
    # DeepSeek Harness 块
    dt = d["deepseek_harness"]["ranges"]["today"]
    if dt["sessions"] > 0:
        print(f"DeepSeek Harness {HEAD}")
        print(f"命中率   {dt['hit']:5.1f}% {F}")
        print(f"今日 输入   {human(dt['in']):>6} {F}")
        print(f"今日 输出   {human(dt['out']):>6} {F}")
        print(f"今日 缓存读 {human(dt['cr']):>6} {F}")
        if dt.get("reason"):
            print(f"今日 推理   {human(dt['reason']):>6} {F}")
        print(f"今日 ≈成本  ${dt['cost']:.2f} + ¥{dt.get('cost_cny', 0):.2f} {F}")
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
    # Kimi Code 块（protocol 1.5 提供模型，但 wire 不持久化实际成本）
    kt = d["kimicode"]["ranges"]["today"]
    if kt["sessions"] > 0:
        print(f"Kimi Code {HEAD}")
        print(f"命中率   {kt['hit']:5.1f}% {F}")
        print(f"今日 输入   {human(kt['in']):>6} {F}")
        print(f"今日 输出   {human(kt['out']):>6} {F}")
        print(f"今日 缓存读 {human(kt['cr']):>6} {F}")
        if kt.get("cw"):
            print(f"今日 缓存写 {human(kt['cw']):>6} {F}")
        print("---")
    # Muse Code 块（model_completed 自带模型名；无持久化成本，按价格表估算）
    mt = d["musecode"]["ranges"]["today"]
    if mt["sessions"] > 0:
        print(f"Muse Code {HEAD}")
        print(f"命中率   {mt['hit']:5.1f}% {F}")
        print(f"今日 输入   {human(mt['in']):>6} {F}")
        print(f"今日 输出   {human(mt['out']):>6} {F}")
        print(f"今日 缓存读 {human(mt['cr']):>6} {F}")
        if mt.get("cw"):
            print(f"今日 缓存写 {human(mt['cw']):>6} {F}")
        if mt.get("reason"):
            print(f"今日 思考   {human(mt['reason']):>6} {F}")
        print(f"今日 ≈成本  ${mt['cost']:.2f} {F}")
        print("---")
    # Command Code 块（assistant message 自带 usage + 真实 costUsd）
    cct = d["cmdcode"]["ranges"]["today"]
    if cct["sessions"] > 0:
        print(f"Command Code {HEAD}")
        print(f"命中率   {cct['hit']:5.1f}% {F}")
        print(f"今日 输入   {human(cct['in']):>6} {F}")
        print(f"今日 输出   {human(cct['out']):>6} {F}")
        print(f"今日 缓存读 {human(cct['cr']):>6} {F}")
        if cct.get("cw"):
            print(f"今日 缓存写 {human(cct['cw']):>6} {F}")
        print(f"今日 成本  ${cct['cost']:.2f} {F}")
        print("---")
    print("刷新 | refresh=true")


def _record_pricing_changes(models):
    changed = {str(model) for model in models if model}
    if not changed:
        return

    def mark():
        cache = _load_scan_cache()
        pending = set(cache.get("_pricing_changed_models") or [])
        pending.update(changed)
        cache["_pricing_changed"] = True
        cache["_pricing_changed_models"] = sorted(pending)
        cache["_dirty"] = True
        _save_scan_cache(cache)

    _with_scan_cache_lock(mark)()


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
        entry = {"in": mtok(pr, "prompt"), "out": mtok(pr, "completion"),
                 "cache_read": mtok(pr, "input_cache_read"),
                 "cache_write": mtok(pr, "input_cache_write")}
        for field in ("name", "canonical_slug", "owned_by"):
            value = m.get(field)
            if isinstance(value, str) and value.strip():
                entry[field] = value.strip()
        models[m["id"]] = entry
    active_count = len(models)
    old_models = _load_json(PRICING_FILE, {}).get("models", {})
    retained_count = 0
    if isinstance(old_models, dict):
        for model, old_entry in old_models.items():
            if model in models or not isinstance(old_entry, dict):
                continue
            retained = dict(old_entry)
            retained["retired"] = True
            models[model] = retained
            retained_count += 1
    old_effective = _effective_pricing_map(old_models)
    new_effective = _effective_pricing_map(models)
    changed_models = {
        model for model in set(old_effective) | set(new_effective)
        if old_effective.get(model) != new_effective.get(model)
    }
    payload = {"_meta": {"source": "openrouter/api/v1/models",
                         "updated_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z"),
                         "count": len(models),
                         "active_count": active_count,
                         "retained_count": retained_count},
               "models": models}
    with open(PRICING_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)
    _record_pricing_changes(changed_models)
    suffix = f"，保留 {retained_count} 个历史模型" if retained_count else ""
    print(f"已更新 {active_count} 个在线模型{suffix} → {PRICING_FILE}")
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
    for root in (WORKBUDDY_DIR, WORKBUDDY_AI_DIR, CODEBUDDY_DIR):
        for f in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
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
    if _override_alias(s):
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
    if added:
        try:
            os.remove(_SCAN_CACHE_FILE)
        except OSError:
            pass
        _remove_codex_event_cache_dir()

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


def _gemini_token_total(day):
    input_total = int(day.get("in", 0) or 0)
    cached = min(int(day.get("cached", 0) or 0), input_total)
    return max(input_total - cached, 0) + cached + int(day.get("out", 0) or 0) \
        + int(day.get("thoughts", 0) or 0)


def _cny_breakdown(cache, cutoff=None):
    """Native CNY only; combine retained ledger days with live cache without FX."""
    by_tool = {"deepseek_harness": {}, "opencode": {}}
    for _, _, record in _iter_deepseek_harness_records(cache.get("deepseek_harness", {})):
        day = by_tool["deepseek_harness"].setdefault(record["date"], {})
        model = record["model"]
        day[model] = day.get(model, 0.0) + record.get("cost_cny", 0.0)
    for dk, record in _iter_cached_token_days(cache.get("opencode", {})):
        day = by_tool["opencode"].setdefault(dk, {})
        for model, mv in record.get("models", {}).items():
            day[model] = day.get(model, 0.0) + mv.get("cost_cny", 0.0)
    for tool, days in by_tool.items():
        for dk, record in _load_ledger().get("tools", {}).get(tool, {}).items():
            if "cost_cny" in record:
                days[dk] = {model: mv.get("cost_cny", 0.0)
                            for model, mv in record.get("models", {}).items()}
    daily, models, daily_tools = {}, {}, {}
    for tool, days in by_tool.items():
        for dk, amounts in days.items():
            if cutoff and dk < cutoff:
                continue
            daily[dk] = daily.get(dk, 0.0) + sum(amounts.values())
            daily_tools.setdefault(dk, {})[tool] = sum(amounts.values())
            for model, amount in amounts.items():
                key = (tool, nice_model(model))
                models[key] = models.get(key, 0.0) + amount
    return daily, models, daily_tools


def build_daily_costs(period="all", refresh=True, _cache=None):
    """按天+按模型的成本 JSON 数据,从扫描缓存聚合。"""
    cutoff = _period_cutoff(period)
    if refresh:
        compute()
    cache = _cache if _cache is not None else _load_scan_cache()
    days = {}
    models = {}
    live_tool_tokens = {}   # {day: {ledger工具名: 实时token}},供账本逐工具高水位合并

    def _add_day_tokens(d, dk, tool, amount):
        d["tokens"] += amount
        per_tool = live_tool_tokens.setdefault(dk, {})
        per_tool[tool] = per_tool.get(tool, 0) + amount

    _empty = lambda: {"claude": 0.0, "codex": 0.0, "codex_reserve": 0.0,
                       "gemini": 0.0, "grok": 0.0,
                       "zcode": 0.0, "mimocode": 0.0, "devin": 0.0, "pi": 0.0,
                       "workbuddy": 0.0, "workbuddy_ai": 0.0, "codebuddy": 0.0,
                       "deepseek_harness": 0.0,
                       "opencode": 0.0, "qwencode": 0.0, "kimicode": 0.0,
                       "musecode": 0.0, "cmdcode": 0.0,
                       "prime_agent": 0.0,
                       "hermes": 0.0, "openclaw": 0.0,
                       "c_in": 0, "c_out": 0, "c_cr": 0, "c_cw": 0,
                       "x_in": 0, "x_out": 0, "x_cached": 0, "x_reason": 0,
                       "xr_in": 0, "xr_out": 0, "xr_cached": 0, "xr_reason": 0,
                       "p_in": 0, "p_out": 0, "p_cr": 0, "p_cw": 0, "p_reason": 0,
                        "pa_in": 0, "pa_out": 0, "pa_cr": 0, "pa_cw": 0, "pa_reason": 0,
                       "w_in": 0, "w_out": 0, "w_cr": 0, "w_cw": 0,
                       "wa_in": 0, "wa_out": 0, "wa_cr": 0, "wa_cw": 0,
                       "cb_in": 0, "cb_out": 0, "cb_cr": 0, "cb_cw": 0,
                       "cb_credits": 0.0,
                       "d_in": 0, "d_out": 0, "d_cr": 0, "d_cw": 0, "d_reason": 0,
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
            _add_day_tokens(d, dk, "claude",
                            day.get("in", 0) + day.get("out", 0) + day.get("cr", 0) + day.get("cw", 0))
            d["sessions"] += 1
            for mn, mv in day.get("models", {}).items():
                nm = nice_model(mn)
                m = models.setdefault(nm, {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cw": 0, "tool": "claude"})
                m["cost"] += mv.get("cost", 0)
                m["in"] += mv.get("in", 0); m["out"] += mv.get("out", 0)
                m["cr"] += mv.get("cr", 0); m["cw"] += mv.get("cw", 0)

    for dk, day in _codex_accounted_days(cache).items():
        if cutoff and dk < cutoff:
            continue
        d = days.setdefault(dk, _empty())
        d["codex"] += day.get("cost", 0)
        d["x_in"] += day.get("in", 0)
        d["x_out"] += day.get("out", 0)
        d["x_cached"] += day.get("cached", 0)
        d["x_reason"] += day.get("reason", 0)
        _add_day_tokens(d, dk, "codex", day.get("in", 0) + day.get("out", 0))
        for mn, mv in day.get("models", {}).items():
            name = f"{nice_model(mn)} (Codex)"
            model = models.setdefault(name, {"cost": 0.0, "in": 0, "out": 0,
                                              "cr": 0, "cw": 0, "reason": 0,
                                              "tool": "codex"})
            model["cost"] += mv.get("cost", 0)
            for key in TOKEN_FIELDS:
                model[key] += mv.get(key, 0)

    for dk, day in _codex_accounted_days(cache, reserve=True).items():
        if cutoff and dk < cutoff:
            continue
        d = days.setdefault(dk, _empty())
        d["codex_reserve"] += day.get("cost", 0)
        d["xr_in"] += day.get("in", 0)
        d["xr_out"] += day.get("out", 0)
        d["xr_cached"] += day.get("cached", 0)
        d["xr_reason"] += day.get("reason", 0)
        _add_day_tokens(
            d, dk, "codex_reserve", day.get("in", 0) + day.get("out", 0))
        for mn, mv in day.get("models", {}).items():
            name = f"{nice_model(mn)} (Codex Reserve)"
            model = models.setdefault(name, {"cost": 0.0, "in": 0, "out": 0,
                                              "cr": 0, "cw": 0, "reason": 0,
                                              "tool": "codex_reserve"})
            model["cost"] += mv.get("cost", 0)
            for key in TOKEN_FIELDS:
                model[key] += mv.get(key, 0)

    for dk, day in cache.get(_GEMINI_DAYS_CACHE_KEY, {}).items():
        if cutoff and dk < cutoff:
            continue
        d = days.setdefault(dk, _empty())
        d["gemini"] += day.get("cost", 0)
        _add_day_tokens(d, dk, "gemini", _gemini_token_total(day))
        for model_name, usage in day.get("models", {}).items():
            cached = min(int(usage.get("cached", 0) or 0), int(usage.get("in", 0) or 0))
            name = f"{nice_model(model_name)} (Gemini)"
            model = models.setdefault(
                name, {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cw": 0,
                       "reason": 0, "tool": "gemini"})
            model["cost"] += usage.get("cost", 0)
            model["in"] += max(int(usage.get("in", 0) or 0) - cached, 0)
            model["out"] += int(usage.get("out", 0) or 0)
            model["cr"] += cached
            model["reason"] += int(usage.get("thoughts", 0) or 0)

    for fp, entry in cache.get("prime_agent", {}).items():
        if not isinstance(entry, dict):
            continue
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            d = days.setdefault(dk, _empty())
            d["prime_agent"] += day.get("cost", 0)
            d["pa_in"] += day.get("in", 0); d["pa_out"] += day.get("out", 0)
            d["pa_cr"] += day.get("cr", 0); d["pa_cw"] += day.get("cw", 0)
            d["pa_reason"] += day.get("reason", 0)
            d["tokens"] += token_total(day)
            for model_name, usage in day.get("models", {}).items():
                name = f"{nice_model(model_name)} (Prime Agent)"
                model = models.setdefault(name, {"cost": 0.0, "in": 0, "out": 0,
                                                 "cr": 0, "cw": 0, "reason": 0,
                                                 "tool": "prime_agent"})
                model["cost"] += usage.get("cost", 0)
                for key in TOKEN_FIELDS:
                    model[key] += usage.get(key, 0)

    for dk, day in cache.get(_GROK_DAYS_CACHE_KEY, {}).items():
        if cutoff and dk < cutoff:
            continue
        d = days.setdefault(dk, _empty())
        d["grok"] += day.get("cost", 0)
        d["g_in"] += day.get("in", 0); d["g_out"] += day.get("out", 0)
        d["g_cr"] += day.get("cr", 0); d["g_reason"] += day.get("reason", 0)
        _add_day_tokens(d, dk, "grok", token_total(day))
        for model_name, usage in day.get("models", {}).items():
            name = f"{nice_model(model_name)} (Grok Build)"
            model = models.setdefault(
                name, {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cw": 0,
                       "reason": 0, "tool": "grok"})
            model["cost"] += usage.get("cost", 0)
            for key in TOKEN_FIELDS:
                model[key] += int(usage.get(key, 0) or 0)

    for fp, entry in cache.get("pi", {}).items():
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            d = days.setdefault(dk, _empty())
            d["pi"] += day.get("cost", 0)
            d["p_in"] += day.get("in", 0); d["p_out"] += day.get("out", 0)
            d["p_cr"] += day.get("cr", 0); d["p_cw"] += day.get("cw", 0)
            d["p_reason"] += day.get("reason", 0)
            _add_day_tokens(d, dk, "pi", token_total(day))
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
        _add_day_tokens(d, dk, "opencode", token_total(day_data))
        for mn, mv in day_data.get("models", {}).items():
            nm = f"{nice_model(mn)} (OpenCode)"
            m = models.setdefault(nm, {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "tool": "opencode"})
            m["cost"] += mv.get("cost", 0)
            for key in TOKEN_FIELDS:
                m[key] += mv.get(key, 0)

    for tool_key, suffix in (("zcode", "ZCode"), ("mimocode", "MiMoCode"),
                             ("devin", "Devin")):
        for dk, day_data in _iter_cached_token_days(cache.get(tool_key, {})):
            if cutoff and dk < cutoff:
                continue
            d = days.setdefault(dk, _empty())
            d[tool_key] += day_data.get("cost", 0)
            _add_day_tokens(d, dk, tool_key, token_total(day_data))
            for mn, mv in day_data.get("models", {}).items():
                name = f"{nice_model(mn)} ({suffix})"
                model = models.setdefault(name, {"cost": 0.0, "in": 0, "out": 0,
                                                  "cr": 0, "cw": 0, "reason": 0,
                                                  "tool": tool_key})
                model["cost"] += mv.get("cost", 0)
                for key in TOKEN_FIELDS:
                    model[key] += mv.get(key, 0)

    for tool_key, field_prefix, suffix in (
            ("workbuddy", "w", "WorkBuddy"),
            ("workbuddy_ai", "wa", "WorkBuddy Intl."),
            ("codebuddy", "cb", "CodeBuddy")):
        for _, _, record in _iter_workbuddy_records(cache.get(tool_key, {})):
            dk = record.get("date")
            if not dk or (cutoff and dk < cutoff):
                continue
            d = days.setdefault(dk, _empty())
            d[tool_key] += record.get("cost", 0)
            d[f"{field_prefix}_in"] += record.get("in", 0)
            d[f"{field_prefix}_out"] += record.get("out", 0)
            d[f"{field_prefix}_cr"] += record.get("cr", 0)
            d[f"{field_prefix}_cw"] += record.get("cw", 0)
            if tool_key == "codebuddy":
                d["cb_credits"] += record.get("credits", 0)
            _add_day_tokens(d, dk, tool_key, token_total(record))
            name = f"{nice_model(record.get('model', 'unknown'))} ({suffix})"
            m = models.setdefault(name, {"cost": 0.0, "in": 0, "out": 0, "cr": 0,
                                         "cw": 0, "reason": 0, "credits": 0.0,
                                         "tool": tool_key})
            m["cost"] += record.get("cost", 0)
            for key in TOKEN_FIELDS:
                m[key] += record.get(key, 0)
            m["credits"] += record.get("credits", 0)

    for _, _, record in _iter_deepseek_harness_records(cache.get("deepseek_harness", {})):
        dk = record.get("date")
        if not dk or (cutoff and dk < cutoff):
            continue
        d = days.setdefault(dk, _empty())
        d["deepseek_harness"] += record.get("cost", 0)
        d["d_in"] += record.get("in", 0); d["d_out"] += record.get("out", 0)
        d["d_cr"] += record.get("cr", 0); d["d_cw"] += record.get("cw", 0)
        d["d_reason"] += record.get("reason", 0)
        _add_day_tokens(d, dk, "deepseek_harness", token_total(record))
        name = f"{nice_model(record.get('model', 'deepseek-v4-pro'))} (DeepSeek Harness)"
        model = models.setdefault(name, {"cost": 0.0, "in": 0, "out": 0,
                                         "cr": 0, "cw": 0, "reason": 0,
                                         "tool": "deepseek_harness"})
        model["cost"] += record.get("cost", 0)
        for key in TOKEN_FIELDS:
            model[key] += record.get(key, 0)

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
        _add_day_tokens(d, dk, "qwencode", token_total(entry))
        for mn, mv in entry.get("models", {}).items():
            nm = f"{nice_model(mn)} (Qwen Code)"
            m = models.setdefault(nm, {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "tool": "qwencode"})
            m["cost"] += mv.get("cost", 0)
            for key in TOKEN_FIELDS:
                m[key] += mv.get(key, 0)

    for _, entry in cache.get("kimicode", {}).items():
        if not isinstance(entry, dict):
            continue
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            d = days.setdefault(dk, _empty())
            _add_day_tokens(d, dk, "kimicode", token_total(day))
            for mn, mv in day.get("models", {}).items():
                name = f"{nice_model(mn)} (Kimi Code)"
                model = models.setdefault(
                    name, {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cw": 0,
                           "reason": 0, "tool": "kimicode"})
                for key in TOKEN_FIELDS:
                    model[key] += mv.get(key, 0)

    for _, entry in cache.get("musecode", {}).items():
        if not isinstance(entry, dict):
            continue
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            d = days.setdefault(dk, _empty())
            d["musecode"] += day.get("cost", 0)
            _add_day_tokens(d, dk, "musecode", _muse_token_total(day))
            for mn, mv in day.get("models", {}).items():
                name = f"{nice_model(mn)} (Muse Code)"
                model = models.setdefault(
                    name, {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cw": 0,
                           "reason": 0, "tool": "musecode"})
                model["cost"] += mv.get("cost", 0)
                for key in TOKEN_FIELDS:
                    model[key] += mv.get(key, 0)

    for _, entry in cache.get("cmdcode", {}).items():
        if not isinstance(entry, dict):
            continue
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            d = days.setdefault(dk, _empty())
            d["cmdcode"] += day.get("cost", 0)
            _add_day_tokens(d, dk, "cmdcode", token_total(day))
            for mn, mv in day.get("models", {}).items():
                name = f"{nice_model(mn)} (Command Code)"
                model = models.setdefault(
                    name, {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cw": 0,
                           "reason": 0, "tool": "cmdcode"})
                model["cost"] += mv.get("cost", 0)
                for key in TOKEN_FIELDS:
                    model[key] += mv.get(key, 0)

    for fp, entry in cache.get("hermes", {}).items():
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            d = days.setdefault(dk, _empty())
            d["hermes"] += day.get("cost", 0)
            _add_day_tokens(d, dk, "hermes", token_total(day))
            for mn, mv in day.get("models", {}).items():
                name = f"{nice_model(mn)} (Hermes)"
                model = models.setdefault(
                    name, {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cw": 0,
                           "reason": 0, "tool": "hermes"})
                model["cost"] += mv.get("cost", 0)
                for key in TOKEN_FIELDS:
                    model[key] += mv.get(key, 0)

    for dk, day in cache.get("openclaw", {}).get("_selected_days", {}).items():
        if cutoff and dk < cutoff:
            continue
        d = days.setdefault(dk, _empty())
        d["openclaw"] += day.get("cost", 0)
        _add_day_tokens(d, dk, "openclaw", _openclaw_token_total(day))
        for mn, mv in day.get("models", {}).items():
            name = f"{nice_model(mn)} (OpenClaw)"
            model = models.setdefault(
                name, {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cw": 0,
                       "reason": 0, "tool": "openclaw"})
            model["cost"] += mv.get("cost", 0)
            for key in TOKEN_FIELDS:
                model[key] += mv.get(key, 0)

    for fp, entry in cache.get("qoder", {}).items():
        model_name = entry.get("model") or "QoderWork"
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            d = days.setdefault(dk, _empty())
            input_tokens = day.get("in", 0)
            output_tokens = day.get("out", 0)
            _add_day_tokens(d, dk, "qoderwork", input_tokens + output_tokens)
            name = f"{nice_model(model_name)} (QoderWork)"
            model = models.setdefault(
                name, {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cw": 0,
                       "reason": 0, "tool": "qoderwork"})
            model["in"] += input_tokens
            model["out"] += output_tokens

    for fp, entry in cache.get("qoder_ide", {}).items():
        model_name = entry.get("model") or "Qoder"
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            d = days.setdefault(dk, _empty())
            input_total = day.get("in", 0)
            cached = day.get("cached", 0)
            output = day.get("out", 0)
            _add_day_tokens(d, dk, "qoder_ide", input_total + output)
            nm = f"{nice_model(model_name)} (Qoder)"
            m = models.setdefault(nm, {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cw": 0, "reason": 0, "tool": "qoder"})
            m["in"] += max(input_total - cached, 0)
            m["out"] += output
            m["cr"] += cached

    for dk, day in _qodercli_usage_days(cache.get("qodercli", {})).items():
        if cutoff and dk < cutoff:
            continue
        d = days.setdefault(dk, _empty())
        _add_day_tokens(d, dk, "qodercli", token_total(day))
        for model_name, usage in day.get("models", {}).items():
            name = f"{nice_model(model_name)} (Qoder CLI)"
            model = models.setdefault(
                name, {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cw": 0,
                       "reason": 0, "tool": "qodercli"})
            for field in ("in", "out", "cr", "cw"):
                model[field] += int(usage.get(field, 0) or 0)

    # --- 持久账本高水位合并:逐工具逐日取 max,被清理的历史天由账本兜底补进序列 ---
    # 同一份数据的存档与实时绝不相加:cost 直接与该工具当日成本列取 max;
    # tokens 列只补"账本白名单token(_ledger_token_sum) 超出该工具当日实时token"的差额。
    # 输出结构保持完全不变(qoderwork/qoder_ide/qodercli 无成本列,只参与 token 合并)。
    _LEDGER_COST_COLUMNS = frozenset((
        "claude", "codex", "codex_reserve", "gemini", "grok", "hermes", "openclaw", "zcode",
        "mimocode", "devin", "pi", "workbuddy", "workbuddy_ai", "codebuddy", "deepseek_harness",
        "opencode", "qwencode", "musecode", "cmdcode"))
    for tool, tool_days in _load_ledger().get("tools", {}).items():
        if not isinstance(tool_days, dict):
            continue
        column = tool if tool in _LEDGER_COST_COLUMNS else None
        for dk, day in tool_days.items():
            if not isinstance(day, dict):
                continue
            if cutoff and dk < cutoff:
                continue
            ledger_tok = _ledger_token_sum(day, tool)
            cost = day.get("cost")
            ledger_cost = (float(cost) if isinstance(cost, (int, float))
                           and not isinstance(cost, bool) else 0.0)
            credit_value = day.get("credits")
            ledger_credits = (float(credit_value) if isinstance(credit_value, (int, float))
                              and not isinstance(credit_value, bool) else 0.0)
            if ledger_tok <= 0 and ledger_cost <= 0 and ledger_credits <= 0:
                continue
            d = days.setdefault(dk, _empty())
            live_tok = live_tool_tokens.get(dk, {}).get(tool, 0)
            if ledger_tok > live_tok:
                d["tokens"] += ledger_tok - live_tok
            if column and ledger_cost > d[column]:
                d[column] = ledger_cost
            if tool == "codebuddy" and ledger_credits > d["cb_credits"]:
                d["cb_credits"] = ledger_credits

    codex_total = sum(d["codex"] for d in days.values())
    codex_in = sum(d["x_in"] for d in days.values())
    codex_out = sum(d["x_out"] for d in days.values())
    codex_reason = sum(d["x_reason"] for d in days.values())
    if codex_total > 0 and not any(v.get("tool") == "codex" for v in models.values()):
        models["GPT-5.5 (Codex)"] = {"cost": round(codex_total, 2), "in": codex_in, "out": codex_out,
                                      "reason": codex_reason, "tool": "codex"}
    reserve_total = sum(d["codex_reserve"] for d in days.values())
    if reserve_total > 0 and not any(
            v.get("tool") == "codex_reserve" for v in models.values()):
        models["Luna Reserve (Codex Reserve)"] = {
            "cost": round(reserve_total, 2),
            "in": sum(d["xr_in"] - d["xr_cached"] for d in days.values()),
            "out": sum(d["xr_out"] for d in days.values()),
            "cr": sum(d["xr_cached"] for d in days.values()),
            "reason": sum(d["xr_reason"] for d in days.values()),
            "tool": "codex_reserve",
        }

    daily = [{"date": dk, "claude": round(v["claude"], 2), "codex": round(v["codex"], 2),
              "codex_reserve": round(v["codex_reserve"], 2),
              "gemini": round(v["gemini"], 2), "grok": round(v["grok"], 2),
              "hermes": round(v["hermes"], 2),
              "openclaw": round(v["openclaw"], 2),
              "zcode": round(v["zcode"], 2), "mimocode": round(v["mimocode"], 2),
              "devin": round(v["devin"], 2), "pi": round(v["pi"], 2),
              "workbuddy": round(v["workbuddy"], 2),
              "workbuddy_ai": round(v["workbuddy_ai"], 2),
              "codebuddy": round(v["codebuddy"], 2),
              "deepseek_harness": round(v["deepseek_harness"], 2),
              "qwencode": round(v["qwencode"], 2),
              "kimicode": round(v["kimicode"], 2),
              "musecode": round(v["musecode"], 2),
              "cmdcode": round(v["cmdcode"], 2),
              "prime_agent": round(v["prime_agent"], 2),
              "total": round(v["claude"] + v["codex"] + v["codex_reserve"]
                             + v["gemini"] + v["grok"] + v["zcode"]
                             + v["mimocode"] + v["pi"] + v["workbuddy"] + v["workbuddy_ai"]
                             + v["codebuddy"]
                             + v["deepseek_harness"] + v["opencode"] + v["qwencode"]
                             + v["kimicode"] + v["musecode"] + v["cmdcode"] + v["prime_agent"] + v["hermes"]
                             + v["openclaw"] + v["devin"], 2),
              "c_in": v["c_in"], "c_out": v["c_out"], "c_cr": v["c_cr"], "c_cw": v["c_cw"],
              "x_in": v["x_in"], "x_out": v["x_out"], "x_cached": v["x_cached"], "x_reason": v["x_reason"],
              "xr_in": v["xr_in"], "xr_out": v["xr_out"],
              "xr_cached": v["xr_cached"], "xr_reason": v["xr_reason"],
              "p_in": v["p_in"], "p_out": v["p_out"], "p_cr": v["p_cr"], "p_cw": v["p_cw"], "p_reason": v["p_reason"],
               "pa_in": v["pa_in"], "pa_out": v["pa_out"], "pa_cr": v["pa_cr"], "pa_cw": v["pa_cw"], "pa_reason": v["pa_reason"],
              "w_in": v["w_in"], "w_out": v["w_out"], "w_cr": v["w_cr"], "w_cw": v["w_cw"],
              "wa_in": v["wa_in"], "wa_out": v["wa_out"], "wa_cr": v["wa_cr"], "wa_cw": v["wa_cw"],
              "cb_in": v["cb_in"], "cb_out": v["cb_out"], "cb_cr": v["cb_cr"], "cb_cw": v["cb_cw"],
              "cb_credits": round(v["cb_credits"], 3),
              "d_in": v["d_in"], "d_out": v["d_out"], "d_cr": v["d_cr"],
              "d_cw": v["d_cw"], "d_reason": v["d_reason"],
              "q_in": v["q_in"], "q_out": v["q_out"], "q_cr": v["q_cr"], "q_reason": v["q_reason"],
              "g_in": v["g_in"], "g_out": v["g_out"], "g_cr": v["g_cr"], "g_reason": v["g_reason"],
              "tokens": v["tokens"]}
             for dk, v in sorted(days.items())]

    def model_tokens(v):
        if v.get("tool") in ("codex", "codex_reserve"):
            return v["in"] + v.get("cr", 0) + v["out"]  # out 已含 reasoning
        if v.get("tool") == "openclaw":
            return _openclaw_token_total(v)
        if v.get("tool") == "musecode":
            return _muse_token_total(v)
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
                           "reason": v.get("reason", 0), "credits": round(v.get("credits", 0), 3),
                           "tokens": total_tok, "tool": v["tool"],
                           "cost_per_k": cost_per_k, "out_ratio": out_ratio})

    def account_model_rows(specs):
        aggregated = {}
        for cache_key, tool, suffix in specs:
            for day_key, day in (cache.get(cache_key) or {}).items():
                if cutoff and day_key < cutoff or not isinstance(day, dict):
                    continue
                for raw_name, raw_usage in (day.get("models") or {}).items():
                    if not isinstance(raw_usage, dict):
                        continue
                    display_name = nice_model(raw_name)
                    name = f"{display_name} ({suffix})" if suffix else display_name
                    model = aggregated.setdefault(
                        name,
                        {"name": name, "cost": 0.0, "in": 0, "out": 0,
                         "cr": 0, "cw": 0, "reason": 0, "tokens": 0,
                         "tool": tool})
                    components = {field: _provider_usage_int(raw_usage.get(field))
                                  for field in _PROVIDER_USAGE_FIELDS}
                    model["tokens"] += _provider_usage_int(raw_usage.get("tokens")) \
                        or sum(components.values())
                    for field, value in components.items():
                        model[field] += value
                    cost = _provider_number(raw_usage.get("cost")) or 0.0
                    if cost >= 0:
                        model["cost"] += cost

        rows = []
        for model in sorted(
                aggregated.values(), key=lambda item: (-item["tokens"], item["name"])):
            out_k = model["out"] / 1000 if model["out"] else 0
            rows.append({
                **model,
                "cost": round(model["cost"], 2),
                "cost_per_k": round(model["cost"] / out_k, 3) if out_k > 0 else 0,
                "out_ratio": round(model["out"] / model["tokens"] * 100, 1)
                if model["tokens"] > 0 else 0,
            })
        return rows

    model_list.extend(account_model_rows((
        (_GROK_BOT_PROVIDER_DAYS_CACHE_KEY, "grok_bot", None),
    )))
    provider_model_list = account_model_rows((
        (_CURSOR_PROVIDER_DAYS_CACHE_KEY, "cursor", "Cursor 账号"),
        (_ZAI_PROVIDER_DAYS_CACHE_KEY, "zai", "z.ai 账号"),
    ))

    cny_days, cny_models, cny_tools = _cny_breakdown(cache, cutoff)
    for day in daily:
        day["cost_cny"] = cny_days.get(day["date"], 0.0)
        day["cny_by_tool"] = cny_tools.get(day["date"], {})
    for model in model_list:
        base_name = model["name"].rsplit(" (", 1)[0]
        model["cost_cny"] = cny_models.get((model["tool"], base_name), 0.0)
    return {"daily": daily, "models": model_list, "provider_models": provider_model_list}


def daily_costs():
    """输出按天+按模型的成本 JSON(从扫描缓存读,无额外 I/O)。"""
    cache = _load_dashboard_cache()
    print(json.dumps(build_daily_costs(_arg_period(), refresh=False, _cache=cache), ensure_ascii=False))


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


def build_wrapped(period="all", refresh=True, _cache=None):
    """Tokei 回顾数据。汇总全部工具,不联网。"""
    cutoff = _period_cutoff(period)
    if refresh:
        compute()
    cache = _cache if _cache is not None else _load_scan_cache()

    hours = [0] * 24
    weekday = [0] * 7
    day_tokens = {}
    day_cost = {}
    proj_tok = {}
    proj_cny = {}
    day_projs = {}
    model_tok = {}
    all_day_hours = set()

    def add_hours(day_key, values):
        if not isinstance(values, list) or len(values) != 24:
            return
        for hour, amount in enumerate(values):
            amount = int(amount or 0)
            hours[hour] += amount
            if amount:
                all_day_hours.add(f"{day_key}:{hour}")

    # --- Claude (有 hours / proj / models) ---
    fc = cache.get("claude", {})
    for f, entry in fc.items():
        if not isinstance(entry, dict):
            continue
        for day_key, day_hours in entry.get("day_hours", {}).items():
            if not cutoff or day_key >= cutoff:
                add_hours(day_key, day_hours)
        proj_path = entry.get("proj") or ""
        proj = os.path.basename(proj_path.rstrip("/")) or "?"
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            tok = token_total(day)
            day_tokens[dk] = day_tokens.get(dk, 0) + tok
            day_cost[dk] = day_cost.get(dk, 0.0) + day.get("cost", 0)
            pt = proj_tok.setdefault(proj, [0, 0.0])
            pt[0] += tok; pt[1] += day.get("cost", 0)
            day_projs.setdefault(dk, set()).add(proj)
            weekday[date.fromisoformat(dk).weekday()] += tok
            for mn, mv in day.get("models", {}).items():
                nm = nice_model(mn)
                model_tok[nm] = model_tok.get(nm, 0) + token_total(mv)

    # --- Codex + Luna Reserve (in includes cached; out includes reasoning) ---
    for reserve, suffix in ((False, "Codex"), (True, "Codex Reserve")):
        for dk, day in _codex_accounted_days(cache, reserve=reserve).items():
            if cutoff and dk < cutoff:
                continue
            tok = day.get("in", 0) + day.get("out", 0)
            day_tokens[dk] = day_tokens.get(dk, 0) + tok
            day_cost[dk] = day_cost.get(dk, 0.0) + day.get("cost", 0)
            weekday[date.fromisoformat(dk).weekday()] += tok
            add_hours(dk, day.get("hours"))
            for model, usage in day.get("models", {}).items():
                name = f"{nice_model(model)} ({suffix})"
                model_tokens = (usage.get("in", 0) + usage.get("cr", 0)
                                + usage.get("out", 0))
                model_tok[name] = model_tok.get(name, 0) + model_tokens

    # --- Gemini (input 含 cached，thoughts 按输出 token 计入) ---
    for dk, day in cache.get(_GEMINI_DAYS_CACHE_KEY, {}).items():
        if cutoff and dk < cutoff:
            continue
        tok = _gemini_token_total(day)
        day_tokens[dk] = day_tokens.get(dk, 0) + tok
        day_cost[dk] = day_cost.get(dk, 0.0) + day.get("cost", 0)
        weekday[date.fromisoformat(dk).weekday()] += tok
        add_hours(dk, day.get("hours"))
        for model, usage in day.get("models", {}).items():
            name = f"{nice_model(model)} (Gemini)"
            amount = _gemini_token_total(usage)
            model_tok[name] = model_tok.get(name, 0) + amount

    # --- Grok Build（unified 日志中的真实 token）---
    for dk, day in cache.get(_GROK_DAYS_CACHE_KEY, {}).items():
        if cutoff and dk < cutoff:
            continue
        tok = token_total(day)
        day_tokens[dk] = day_tokens.get(dk, 0) + tok
        day_cost[dk] = day_cost.get(dk, 0.0) + day.get("cost", 0)
        weekday[date.fromisoformat(dk).weekday()] += tok
        add_hours(dk, day.get("hours"))
        for model, usage in day.get("models", {}).items():
            name = f"{nice_model(model)} (Grok Build)"
            model_tok[name] = model_tok.get(name, 0) + token_total(usage)

    # --- Hermes (in + out + cr + cw + reason) ---
    for f, entry in cache.get("hermes", {}).items():
        if not isinstance(entry, dict):
            continue
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            tok = token_total(day)
            day_tokens[dk] = day_tokens.get(dk, 0) + tok
            day_cost[dk] = day_cost.get(dk, 0.0) + day.get("cost", 0)
            weekday[date.fromisoformat(dk).weekday()] += tok
            add_hours(dk, day.get("hours"))
            for model, usage in day.get("models", {}).items():
                name = f"{nice_model(model)} (Hermes)"
                model_tok[name] = model_tok.get(name, 0) + token_total(usage)

    # --- OpenClaw (reasoning is a subset of output) ---
    for dk, day in cache.get("openclaw", {}).get("_selected_days", {}).items():
        if cutoff and dk < cutoff:
            continue
        tok = _openclaw_token_total(day)
        day_tokens[dk] = day_tokens.get(dk, 0) + tok
        day_cost[dk] = day_cost.get(dk, 0.0) + day.get("cost", 0)
        weekday[date.fromisoformat(dk).weekday()] += tok
        add_hours(dk, day.get("hours"))
        for model, usage in day.get("models", {}).items():
            name = f"{nice_model(model)} (OpenClaw)"
            model_tok[name] = model_tok.get(name, 0) + _openclaw_token_total(usage)

    # --- OpenCode (in + out + cr + cw + reason) ---
    for dk, day in _iter_cached_token_days(cache.get("opencode", {})):
        if cutoff and dk < cutoff:
            continue
        tok = token_total(day)
        day_tokens[dk] = day_tokens.get(dk, 0) + tok
        day_cost[dk] = day_cost.get(dk, 0.0) + day.get("cost", 0)
        weekday[date.fromisoformat(dk).weekday()] += tok
        for hour, amount in enumerate(day.get("hours", [])):
            hours[hour] += amount
            if amount:
                all_day_hours.add(f"{dk}:{hour}")
        for model, usage in day.get("models", {}).items():
            name = f"{nice_model(model)} (OpenCode)"
            model_tok[name] = model_tok.get(name, 0) + token_total(usage)

    # --- ZCode / MiMoCode / Devin ---
    for tool_key, suffix in (("zcode", "ZCode"), ("mimocode", "MiMoCode"),
                             ("devin", "Devin")):
        for dk, day in _iter_cached_token_days(cache.get(tool_key, {})):
            if cutoff and dk < cutoff:
                continue
            tok = token_total(day)
            day_tokens[dk] = day_tokens.get(dk, 0) + tok
            day_cost[dk] = day_cost.get(dk, 0.0) + day.get("cost", 0)
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
        day_cost[dk] = day_cost.get(dk, 0.0) + entry.get("cost", 0)
        weekday[date.fromisoformat(dk).weekday()] += tok
        hour = entry.get("hour")
        if isinstance(hour, int) and 0 <= hour < 24:
            hours[hour] += tok
            all_day_hours.add(f"{dk}:{hour}")
        for mn, mv in entry.get("models", {}).items():
            nm = f"{nice_model(mn)} (Qwen Code)"
            model_tok[nm] = model_tok.get(nm, 0) + token_total(mv)

    # --- Kimi Code (legacy StatusUpdate and protocol 1.5 usage.record) ---
    for _, entry in cache.get("kimicode", {}).items():
        if not isinstance(entry, dict):
            continue
        project_path = entry.get("proj") or ""
        project = os.path.basename(project_path.rstrip("/")) or "Kimi Code"
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            tok = token_total(day)
            day_tokens[dk] = day_tokens.get(dk, 0) + tok
            weekday[date.fromisoformat(dk).weekday()] += tok
            add_hours(dk, day.get("hours"))
            pt = proj_tok.setdefault(project, [0, 0.0])
            pt[0] += tok
            day_projs.setdefault(dk, set()).add(project)
            for mn, mv in day.get("models", {}).items():
                model_name = f"{nice_model(mn)} (Kimi Code)"
                model_tok[model_name] = model_tok.get(model_name, 0) + token_total(mv)

    # --- Muse Code (model_completed usage;成本按价格表估算) ---
    for _, entry in cache.get("musecode", {}).items():
        if not isinstance(entry, dict):
            continue
        project_path = entry.get("proj") or ""
        project = os.path.basename(project_path.rstrip("/")) or "Muse Code"
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            tok = _muse_token_total(day)
            day_tokens[dk] = day_tokens.get(dk, 0) + tok
            day_cost[dk] = day_cost.get(dk, 0.0) + day.get("cost", 0)
            weekday[date.fromisoformat(dk).weekday()] += tok
            add_hours(dk, day.get("hours"))
            pt = proj_tok.setdefault(project, [0, 0.0])
            pt[0] += tok
            pt[1] += day.get("cost", 0)
            day_projs.setdefault(dk, set()).add(project)
            for mn, mv in day.get("models", {}).items():
                model_name = f"{nice_model(mn)} (Muse Code)"
                model_tok[model_name] = model_tok.get(model_name, 0) + _muse_token_total(mv)

    # --- Command Code (assistant message usage + 真实 costUsd) ---
    for _, entry in cache.get("cmdcode", {}).items():
        if not isinstance(entry, dict):
            continue
        project_path = entry.get("proj") or ""
        project = os.path.basename(project_path.rstrip("/")) or "Command Code"
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            tok = token_total(day)
            day_tokens[dk] = day_tokens.get(dk, 0) + tok
            day_cost[dk] = day_cost.get(dk, 0.0) + day.get("cost", 0)
            weekday[date.fromisoformat(dk).weekday()] += tok
            add_hours(dk, day.get("hours"))
            pt = proj_tok.setdefault(project, [0, 0.0])
            pt[0] += tok
            pt[1] += day.get("cost", 0)
            day_projs.setdefault(dk, set()).add(project)
            for mn, mv in day.get("models", {}).items():
                model_name = f"{nice_model(mn)} (Command Code)"
                model_tok[model_name] = model_tok.get(model_name, 0) + token_total(mv)

    # --- Pi Coding Agent (in + out + cr + cw + reason) ---
    for f, entry in cache.get("pi", {}).items():
        if not isinstance(entry, dict):
            continue
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            tok = token_total(day)
            day_tokens[dk] = day_tokens.get(dk, 0) + tok
            day_cost[dk] = day_cost.get(dk, 0.0) + day.get("cost", 0)
            weekday[date.fromisoformat(dk).weekday()] += tok
            add_hours(dk, day.get("hours"))
            for mn, mv in day.get("models", {}).items():
                nm = f"{nice_model(mn)} (Pi)"
                model_tok[nm] = model_tok.get(nm, 0) + token_total(mv)

    # --- Prime Agent (Pi-compatible persisted assistant usage) ---
    for f, entry in cache.get("prime_agent", {}).items():
        if not isinstance(entry, dict):
            continue
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            tok = token_total(day)
            day_tokens[dk] = day_tokens.get(dk, 0) + tok
            day_cost[dk] = day_cost.get(dk, 0.0) + day.get("cost", 0)
            weekday[date.fromisoformat(dk).weekday()] += tok
            add_hours(dk, day.get("hours"))
            for mn, mv in day.get("models", {}).items():
                nm = f"{nice_model(mn)} (Prime Agent)"
                model_tok[nm] = model_tok.get(nm, 0) + token_total(mv)

    # --- WorkBuddy 国内版与国际版（逐次调用，output 已含 reasoning） ---
    for tool_key, suffix in (("workbuddy", "WorkBuddy"),
                             ("workbuddy_ai", "WorkBuddy Intl."),
                             ("codebuddy", "CodeBuddy")):
        for _, entry, record in _iter_workbuddy_records(cache.get(tool_key, {})):
            dk = record.get("date", "")
            if not dk or (cutoff and dk < cutoff):
                continue
            tok = token_total(record)
            day_tokens[dk] = day_tokens.get(dk, 0) + tok
            day_cost[dk] = day_cost.get(dk, 0.0) + record.get("cost", 0)
            weekday[date.fromisoformat(dk).weekday()] += tok
            hour = record.get("hour")
            if isinstance(hour, int) and 0 <= hour < 24:
                hours[hour] += tok
                all_day_hours.add(f"{dk}:{hour}")
            project_path = entry.get("proj") or ""
            project = os.path.basename(project_path.rstrip("/")) or suffix
            pt = proj_tok.setdefault(project, [0, 0.0])
            pt[0] += tok; pt[1] += record.get("cost", 0)
            day_projs.setdefault(dk, set()).add(project)
            model_name = f"{nice_model(record.get('model', 'unknown'))} ({suffix})"
            model_tok[model_name] = model_tok.get(model_name, 0) + tok

    # --- DeepSeek Harness (最终 message 优先，异常中断用 usage chunk) ---
    for _, entry, record in _iter_deepseek_harness_records(cache.get("deepseek_harness", {})):
        dk = record.get("date", "")
        if not dk or (cutoff and dk < cutoff):
            continue
        tok = token_total(record)
        day_tokens[dk] = day_tokens.get(dk, 0) + tok
        day_cost[dk] = day_cost.get(dk, 0.0) + record.get("cost", 0)
        weekday[date.fromisoformat(dk).weekday()] += tok
        hour = record.get("hour")
        if isinstance(hour, int) and 0 <= hour < 24:
            hours[hour] += tok
            all_day_hours.add(f"{dk}:{hour}")
        project_path = entry.get("proj") or ""
        project = os.path.basename(project_path.rstrip("/")) or "DeepSeek Harness"
        pt = proj_tok.setdefault(project, [0, 0.0])
        pt[0] += tok; pt[1] += record.get("cost", 0)
        proj_cny[project] = proj_cny.get(project, 0.0) + record.get("cost_cny", 0)
        day_projs.setdefault(dk, set()).add(project)
        model_name = f"{nice_model(record.get('model', 'deepseek-v4-pro'))} (DeepSeek Harness)"
        model_tok[model_name] = model_tok.get(model_name, 0) + tok

    # --- QoderWork (in + out, no cost) ---
    for f, entry in cache.get("qoder", {}).items():
        if not isinstance(entry, dict):
            continue
        model_name = entry.get("model") or "QoderWork"
        for dk, day in entry.get("days", {}).items():
            if cutoff and dk < cutoff:
                continue
            tok = day.get("in", 0) + day.get("out", 0)
            day_tokens[dk] = day_tokens.get(dk, 0) + tok
            weekday[date.fromisoformat(dk).weekday()] += tok
            add_hours(dk, day.get("hours"))
            name = f"{nice_model(model_name)} (QoderWork)"
            model_tok[name] = model_tok.get(name, 0) + tok

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
            weekday[date.fromisoformat(dk).weekday()] += tok
            add_hours(dk, day.get("hours"))
            nm = f"{nice_model(model_name)} (Qoder)"
            model_tok[nm] = model_tok.get(nm, 0) + tok

    # --- Qoder CLI (deduplicated transcript usage, no cost) ---
    for dk, day in _qodercli_usage_days(cache.get("qodercli", {})).items():
        if cutoff and dk < cutoff:
            continue
        tok = token_total(day)
        day_tokens[dk] = day_tokens.get(dk, 0) + tok
        weekday[date.fromisoformat(dk).weekday()] += tok
        add_hours(dk, day.get("hours"))
        for model_name, usage in day.get("models", {}).items():
            name = f"{nice_model(model_name)} (Qoder CLI)"
            model_tok[name] = model_tok.get(name, 0) + token_total(usage)

    # --- 持久账本合并:全部指标统一账本口径 ---
    # 账本是同一份数据的高水位存档:同一天取 max(账本合计, 实时值),绝不相加以免重复计数
    # (天级整取整用;账本理论上 ≥ 实时,max 只是保险)。token 按白名单口径求和(含 cached/thoughts,
    # 见 _ledger_token_sum),cost 同理逐日取 max。被清理日志的历史天由账本兜底补回,
    # 让 total/active/streak/busiest/peak 与 peak_days 同口径,避免同页口径分裂。
    # 每日项目与项目足迹同源：谁出现在项目足迹，谁就出现在回顾页，不会一边有
    # 一边没有。账本归档的项目名在下面并入，负责日志被清理后的历史天。
    for day_key, names in _project_day_names(cache).items():
        if cutoff and day_key < cutoff:
            continue
        if names:
            day_projs.setdefault(day_key, set()).update(names)

    ledger_day_tokens = {}
    ledger_day_cost = {}
    for tool, tool_days in _load_ledger().get("tools", {}).items():
        if not isinstance(tool_days, dict):
            continue
        for dk, day in tool_days.items():
            if not isinstance(day, dict):
                continue
            if cutoff and dk < cutoff:
                continue
            tok = _ledger_token_sum(day, tool)
            if tok:
                ledger_day_tokens[dk] = ledger_day_tokens.get(dk, 0) + tok
            cost = day.get("cost")
            if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost > 0:
                ledger_day_cost[dk] = ledger_day_cost.get(dk, 0.0) + float(cost)
            projects = day.get("projects")
            if isinstance(projects, list):  # 账本存档的项目名:日志被清后"那天在干什么"的记忆
                names = {p for p in projects if isinstance(p, str) and p}
                if names:
                    day_projs.setdefault(dk, set()).update(names)
    for dk, tok in ledger_day_tokens.items():
        day_tokens[dk] = max(day_tokens.get(dk, 0), tok)
    for dk, cost in ledger_day_cost.items():
        day_cost[dk] = max(day_cost.get(dk, 0.0), cost)
    total_tokens = sum(day_tokens.values())
    total_cost = sum(day_cost.values())

    active = sorted(day_tokens.keys())
    streak_max, streak_cur = _streak_info(active)

    # --- 巅峰日 Top 3:直接取合并后的 day_tokens,与 total_tokens/active_days 同一份数据 ---
    peak_days = [
        {"date": dk, "tokens": tok,
         "projects": sorted(day_projs.get(dk) or ())[:3]}  # 账本天的项目名同样能命中
        for dk, tok in sorted(day_tokens.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        if tok > 0
    ]
    # busiest 向后兼容保留,取值 = peak_days[0],保证两者一致;成就计算同样用合并后的冠军值。
    busiest_merged = ({"date": peak_days[0]["date"], "tokens": peak_days[0]["tokens"]}
                      if peak_days else {"date": "", "tokens": 0})
    busiest_tok = busiest_merged["tokens"]
    top_model_name, top_model_tok = (max(model_tok.items(), key=lambda kv: kv[1])
                                     if model_tok else ("-", 0))
    projects = sorted(
        ({"name": p, "tokens": v[0], "cost": round(v[1], 2), "cost_cny": proj_cny.get(p, 0)} for p, v in proj_tok.items()),
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
        "cost_cny": sum(_cny_breakdown(cache, cutoff)[0].values()),
        "active_days": len(active),
        "streak_max": streak_max,
        "streak_cur": streak_cur,
        "busiest": busiest_merged,
        "peak_days": peak_days,
        "day_projects": {dk: sorted(projs)[:3] for dk, projs in day_projs.items() if projs},
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
    cache = _load_dashboard_cache()
    print(json.dumps(build_wrapped(_arg_period(), refresh=False, _cache=cache), ensure_ascii=False))


def _load_dashboard_cache():
    """复用主刷新生成的扫描缓存；首次运行或缓存损坏时才补一次扫描。"""
    cache = _load_scan_cache()
    if cache.get("_dirty"):
        compute()
        cache = _load_scan_cache()
    return cache


# ---------- 周额度消耗 ----------
# 一个周期 = 两次「余量 100%」之间,起点取 resets_at - 7天。
# 实测:resets_at 会不定期重锚(观测到的间隔有 0.75 / 2.1 / 7.0 天),所以历史边界
# 推不出来,只能观测一次记一次 —— 见 _QUOTA_ANCHOR_FILE。
# 周期边界落在半天,日级账本切不出来,所以整日部分取账本(权威,不受 CLI 清理旧日志
# 影响),首尾半天取更细的来源:本机用带时间戳的事件缓存,peer 用日条目里的 hours[24]。
# 详情最多带回约一年的周周期；界面默认展示 8 个，其余由用户按需展开。
_QUOTA_CYCLE_HISTORY = 52
_QUOTA_WEEK_HOURS = 7 * 24
_QUOTA_SELF_DEVICE = "本机"
_QUOTA_ANCHOR_FILE = os.path.join(HOME, ".tokei", "quota_cycles.json")
# resets_in_seconds 是整秒截断的,同一个锚点读出来会有几秒抖动。
_QUOTA_ANCHOR_JITTER = 120
_QUOTA_CYCLE_MIN_USED_PCT = 2
# 有周额度窗口的三个工具 → 日表里的短键。
_QUOTA_TOOLS = (("claude", "c"), ("codex", "x"), ("grok", "g"))


def _quota_local_day_range(day_key):
    base = datetime.strptime(day_key, "%Y-%m-%d")
    start = base.astimezone()
    end = (base + timedelta(days=1)).astimezone()
    return int(start.timestamp()), int(end.timestamp())


def _quota_device_ledgers():
    """→ ([(设备名, 账本 tools, 快照, 日表)], [peer 锚点表]) —— 本机 + 各 peer;本机快照为 None。

    额度% 是账号级的,只算本机会对不上(活儿可能全在另一台机器上干的);
    额度读数本身也可能只有另一台机器有(比如 Grok 只在 Air 上登录)。
    """
    own_tools = (_load_ledger() or {}).get("tools") or {}
    devices = [(_QUOTA_SELF_DEVICE, own_tools, None, _quota_daily_from_tools(own_tools))]
    peer_anchors = []
    cfg = _load_tokei_config() or {}
    sync_dir = (os.path.expanduser(cfg.get("sync_dir") or "")
                or os.path.join(HOME, ".tokei", "sync"))
    own = _sync_snapshot_filename(cfg.get("device_id", "")) or ""
    try:
        names = sorted(os.listdir(sync_dir))
    except OSError:
        return devices, peer_anchors
    for name in names:
        # 自己那份快照是本地账本的副本,再算一遍就是双倍。
        if not name.endswith(".json") or name.casefold() == own.casefold():
            continue
        try:
            with open(os.path.join(sync_dir, name), encoding="utf-8") as f:
                snapshot = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(snapshot, dict):
            continue
        # 锚点不看 _ledger:周期历史推不出来,哪台机器观测到的都得收下。
        incoming = snapshot.get("_quota_anchors")
        if isinstance(incoming, dict):
            peer_anchors.append(incoming)
        tools = (snapshot.get("_ledger") or {}).get("tools")
        if isinstance(tools, dict) and tools:
            devices.append((snapshot.get("_device") or name[:-5], tools, snapshot,
                            _quota_daily_from_tools(tools)))
    return devices, peer_anchors


def _quota_day_tokens(tool, entry):
    """一天的 token 数。三个工具口径不同,别混。"""
    if not isinstance(entry, dict):
        return 0
    if tool == "claude":
        return sum(int(entry.get(k, 0) or 0) for k in ("in", "out", "cr", "cw"))
    if tool == "codex":
        # 账本里的 codex "in" 已含 cached(与 ranges 相反,那边 in 是未缓存部分),
        # 再加 cached 会翻倍。
        return sum(int(entry.get(k, 0) or 0) for k in ("in", "out"))
    if entry.get("tokens") is not None:
        return int(entry["tokens"] or 0)
    return sum(int(entry.get(k, 0) or 0) for k in ("in", "out", "cr", "reason"))


def _quota_daily_from_tools(tools):
    """账本日表 → {日: {"c": …, "x": …, "g": …}}。"""
    out = {}
    for tool, key in _QUOTA_TOOLS:
        for day, entry in (tools.get(tool) or {}).items():
            if isinstance(entry, dict):
                out.setdefault(day, {k: 0 for _t, k in _QUOTA_TOOLS})[key] = \
                    _quota_day_tokens(tool, entry)
    return out


def _quota_window_days(start, end):
    """[start, end) 覆盖的本地自然日 → (完整落在窗口内的, 只覆盖一部分的)。"""
    interior, boundary = set(), []
    cursor = datetime.fromtimestamp(start).date()
    last = datetime.fromtimestamp(max(end - 1, start)).date()
    while cursor <= last:
        key = cursor.isoformat()
        day_start, day_end = _quota_local_day_range(key)
        if day_start >= start and day_end <= end:
            interior.add(key)
        else:
            boundary.append(key)
        cursor += timedelta(days=1)
    return interior, boundary


def _quota_day_hour_bounds(day_key, start, end):
    """该自然日与 [start, end) 相交的小时下标 [lo, hi);无交集返回 None。"""
    day_start, day_end = _quota_local_day_range(day_key)
    lo, hi = max(start, day_start), min(end, day_end)
    if lo >= hi:
        return None
    lo_hour = 0 if lo <= day_start else datetime.fromtimestamp(lo).hour
    if hi >= day_end:
        hi_hour = 24
    else:
        moment = datetime.fromtimestamp(hi)
        hi_hour = moment.hour + (1 if moment.minute or moment.second else 0)
    return lo_hour, max(hi_hour, lo_hour + 1)


def _quota_claude_events(cache=None):
    """去重后的 Claude 事件 → [(epoch, 本地日, tokens)]。去重逻辑与 scan_claude 一致。"""
    file_cache = (cache if cache is not None else _load_scan_cache()).get("claude") or {}
    all_events = []
    for path, entry in file_cache.items():
        if isinstance(entry, dict):
            for event in entry.get("events", []):
                all_events.append((path, event))
    events = []
    for _path, event in _dedupe_claude_events(all_events):
        dt = parse_ts(event.get("timestamp", ""))
        if dt is None:
            continue
        dt = dt.astimezone()
        events.append((int(dt.timestamp()), dt.date().isoformat(),
                       _claude_event_total(event)))
    return events


def _quota_codex_events(spans, cache=None):
    """只读与 spans 有交集的事件文件。行内 idx6 已含 cached,故 tokens = idx6 + idx8。

    续接会话会把父会话的事件整段重放,口径必须和账本一致(见 :1862):只认 canonical
    文件,并跳过开头 drop_count 行重放,否则重的日子能比账本多出几十倍。
    """
    if not spans:
        return []
    lo_min = min(lo for lo, _ in spans)
    hi_max = max(hi for _, hi in spans)
    file_cache = (cache if cache is not None else _load_scan_cache()).get("codex") or {}
    events = []
    for path, entry in file_cache.items():
        if not isinstance(entry, dict) or not entry.get("event_count"):
            continue
        if not entry.get("canonical"):
            continue
        first = _iso_to_epoch(entry.get("first_event_ts"))
        last = _iso_to_epoch(entry.get("last_event_ts"))
        if first is not None and first > hi_max:
            continue
        if last is not None and last < lo_min:
            continue
        try:
            for row in _iter_codex_cached_events(
                    path, start_index=int(entry.get("drop_count", 0) or 0)):
                if len(row) < 9:
                    continue
                dt = parse_ts(row[0])
                if dt is None:
                    continue
                events.append((int(dt.timestamp()), str(row[1]),
                               int(row[6] or 0) + int(row[8] or 0)))
        except (OSError, ValueError):
            continue
    return events


def _quota_peer_boundary(tools, tool, day_key, bounds, day_total):
    """没有事件缓存时:有 hours[24] 就按小时切,没有就按覆盖小时数折算。"""
    lo_hour, hi_hour = bounds
    entry = (tools.get(tool) or {}).get(day_key)
    hours = entry.get("hours") if isinstance(entry, dict) else None
    if isinstance(hours, list) and len(hours) >= 24:
        return sum(int(hours[h] or 0) for h in range(lo_hour, hi_hour)), False
    return day_total * (hi_hour - lo_hour) // 24, True


def _quota_window_tokens(devices, tool, key, start, end, self_events):
    """→ (合计, {设备: token}, 是否含折算值)。self_events 为 None 时本机也走 hours。"""
    interior, boundary = _quota_window_days(start, end)
    self_by_day = {}
    for ts, day, amount in self_events or ():
        if start <= ts < end and day not in interior:
            self_by_day[day] = self_by_day.get(day, 0) + amount

    per_device = {}
    approx = False
    for name, tools, _snapshot, daily in devices:
        own = name == _QUOTA_SELF_DEVICE and self_events is not None
        total = sum(int((daily.get(day) or {}).get(key, 0)) for day in interior)
        for day in boundary:
            bounds = _quota_day_hour_bounds(day, start, end)
            if bounds is None:
                continue
            day_total = int((daily.get(day) or {}).get(key, 0))
            # 事件有就用事件(最准);事件空但账本当天有量 = 日志被清理过,退回折算。
            if own and (self_by_day.get(day) or not day_total):
                total += self_by_day.get(day, 0)
                continue
            amount, guessed = _quota_peer_boundary(tools, tool, day, bounds, day_total)
            total += amount
            approx = approx or (guessed and amount > 0)
        per_device[name] = total
    return sum(per_device.values()), per_device, approx


def _quota_tool_reading(source, tool):
    """从一份 payload/同步快照里取 (used_pct, reset_epoch, 读数时间);取不到返回 None。"""
    data = (source or {}).get(tool) or {}
    if tool == "claude":
        if data.get("q7_stale"):
            return None
        used, reset, updated = data.get("q7"), data.get("q7_reset"), data.get("q_updated")
    elif tool == "codex":
        if data.get("pw_stale"):
            return None
        used, reset, updated = data.get("pw"), data.get("rw"), data.get("q_updated")
    else:
        # Grok 也可能是月套餐,月窗口长度不定又没有数据可验证,先只认周。
        if data.get("stale") or data.get("window") != "week":
            return None
        used, reset, updated = data.get("pct"), data.get("reset"), data.get("q_updated")
    if not isinstance(reset, (int, float)):
        reset = _iso_to_epoch(reset)
    if not isinstance(reset, (int, float)) or reset <= 0:
        return None
    return used, int(reset), int(updated or 0)


def _load_quota_anchors():
    try:
        with open(_QUOTA_ANCHOR_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    anchors = data.get("anchors") if isinstance(data, dict) else None
    return anchors if isinstance(anchors, dict) else {}


def _save_quota_anchors(anchors):
    directory = os.path.dirname(_QUOTA_ANCHOR_FILE)
    tmp = None
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp = _tempfile.mkstemp(prefix=".tokei-cycles-", suffix=".json", dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"anchors": anchors}, f, ensure_ascii=False)
        os.replace(tmp, _QUOTA_ANCHOR_FILE)
    except OSError:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _record_quota_anchor(anchors, tool, reset, used, now, confirmed_reset=False):
    """记下一次额度读数。同一个锚点只留一条,used 取见过的最大值。

    额度从有消耗的旧窗口回到 0%,同时 reset 前移到新窗口,已经足以确认提前重置。
    后续空闲时 reset 继续漂移不会连开新周期:只有紧邻的上一锚点有真实消耗时
    才确认这次 0% 重置。
    """
    used = float(used or 0)
    rows = anchors.setdefault(tool, [])
    previous = [
        row for row in rows
        if int(row.get("reset", 0)) < reset - _QUOTA_ANCHOR_JITTER
    ]
    latest_previous = max(previous, key=lambda row: int(row.get("reset", 0)), default=None)
    confirmed_reset = bool(
        confirmed_reset or
        used >= _QUOTA_CYCLE_MIN_USED_PCT or
        (latest_previous and
         latest_previous.get("max_used", 0) >= _QUOTA_CYCLE_MIN_USED_PCT)
    )
    for row in rows:
        if abs(int(row.get("reset", 0)) - reset) <= _QUOTA_ANCHOR_JITTER:
            changed = (
                used > row.get("max_used", 0) or
                now > row.get("last_seen", 0) or
                (confirmed_reset and not row.get("confirmed_reset"))
            )
            row["max_used"] = max(row.get("max_used", 0), used)
            row["last_seen"] = max(row.get("last_seen", 0), now)
            if confirmed_reset:
                row["confirmed_reset"] = True
            return changed
    row = {"reset": reset, "first_seen": now, "last_seen": now, "max_used": used}
    if confirmed_reset:
        row["confirmed_reset"] = True
    rows.append(row)
    return True


def _merge_quota_anchors(anchors, incoming):
    """把 peer 快照里的锚点并进内存表 —— 只为渲染,不回写自己的账。

    周期边界只有亲眼观测到的那台机器知道,所以谁看到都算数。抖动对齐交给
    _record_quota_anchor:同一个窗口在两台机器上读出的 reset 差几秒也能并成一条。
    """
    known = {tool for tool, _key in _QUOTA_TOOLS}
    for tool, rows in (incoming or {}).items():
        if tool not in known or not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            # 快照是别的进程写的,字段可能是任何东西 —— 挑不出数的直接跳过。
            reset, used, seen = row.get("reset"), row.get("max_used"), row.get("last_seen")
            if not isinstance(reset, (int, float)) or reset <= 0:
                continue
            _record_quota_anchor(
                anchors, tool, int(reset),
                used if isinstance(used, (int, float)) else 0,
                int(seen) if isinstance(seen, (int, float)) else 0,
                confirmed_reset=row.get("confirmed_reset") is True)
    return anchors


def _quota_anchor_cycles(anchors, tool, span, limit, now):
    """→ [(start, end, max_used, 是否进行中)]，最新的排最前。

    按 reset 排序而不是按观测顺序:陈旧的会话记录偶尔会抢赢新记录,
    照观测顺序切会切出负时长的区间。排序后每段时长天然为正。
    """
    rows = sorted(anchors.get(tool) or [], key=lambda r: int(r.get("reset", 0)))
    # 窗口空着的时候 reset 会一直跟着 now+7d 漂,那不是真周期。真实消耗和
    # 「旧窗口有消耗后回到 0%」两种证据都能确认周期;没有证据时只展示最新读数。
    rows = [
        row for row in rows
        if row.get("max_used", 0) >= _QUOTA_CYCLE_MIN_USED_PCT or
        row.get("confirmed_reset") is True
    ] or rows[-1:]

    cycles = []
    for index, row in enumerate(rows):
        reset = int(row["reset"])
        start = reset - span
        if index + 1 < len(rows):
            end = min(reset, int(rows[index + 1]["reset"]) - span)
        else:
            end = reset
        if end > start:
            # 读数断了就不会再有新锚点,最后一条也可能早已过期 —— 那是历史,不是进行中。
            # 但「进行中」仍只能是最后一条:多标一条会被前端当成当前卡片,另一条就没了。
            current = index + 1 == len(rows) and reset > now
            cycles.append((start, end, row.get("max_used", 0), current))
    return cycles[-limit:][::-1]


def _quota_cycle_specs(payload, devices, peer_anchors, now):
    """→ (能切出周期的工具, 一条锚点都没有的工具, 锚点表)，顺便把这次读到的锚点落盘。

    额度是账号级的:本机读不到就用同步过来的(Grok 只在 Air 上登录就属于这种),
    所以每台设备的读数都记 —— 谁先看到重锚都算数。

    落盘只写本机这轮亲眼读到的;peer 锚点在落盘之后才并进来,免得把别人的记录
    反复回写成自己的观测。
    """
    anchors = _load_quota_anchors()
    dirty = False
    for tool, _key in _QUOTA_TOOLS:
        for _name, _tools, snapshot, _daily in devices:
            reading = _quota_tool_reading(snapshot if snapshot else payload, tool)
            if reading:
                dirty |= _record_quota_anchor(anchors, tool, reading[1], reading[0], now)
    if dirty:
        _save_quota_anchors(anchors)
    for incoming in peer_anchors:
        _merge_quota_anchors(anchors, incoming)
    # 当前读数断了不等于历史没了 —— 有锚点就照旧切周期,
    # 只有一条都没有才算真没有,那才需要提示怎么把额度读数找回来。
    charted = [tool for tool, _key in _QUOTA_TOOLS if anchors.get(tool)]
    missing = [tool for tool, _key in _QUOTA_TOOLS if not anchors.get(tool)]
    return charted, missing, anchors


def _recent_quota_detail_payload():
    path = os.path.join(HOME, ".tokei", "last_usage.json")
    try:
        with open(path, encoding="utf-8") as f:
            age = datetime.now().timestamp() - os.fstat(f.fileno()).st_mtime
            if 0 <= age <= 60:
                payload = json.load(f)
                if isinstance(payload, dict) and all(
                        isinstance(payload.get(tool), dict) for tool, _ in _QUOTA_TOOLS):
                    return payload
    except (OSError, ValueError):
        pass
    return None


def _quota_detail_payload():
    """Reuse the app's recent local snapshot; standalone/cold calls still collect."""
    return _recent_quota_detail_payload() or compute()


def _quota_detail_inputs():
    cache = _load_scan_cache()
    payload = None if cache.get("_dirty") else _recent_quota_detail_payload()
    if payload is not None:
        return payload, cache
    return compute(), _load_scan_cache()


def build_quota_detail():
    payload, cache = _quota_detail_inputs()
    now = int(datetime.now().timestamp())
    devices, peer_anchors = _quota_device_ledgers()
    span = _QUOTA_WEEK_HOURS * 3600
    charted, missing, anchors = _quota_cycle_specs(payload, devices, peer_anchors, now)

    planned = []
    for tool in charted:
        for start, end, used, current in _quota_anchor_cycles(
                anchors, tool, span, _QUOTA_CYCLE_HISTORY, now):
            planned.append((tool, start, end, used, current))

    codex_spans = [(s, e) for tool, s, e, _u, _c in planned if tool == "codex"]
    keys = dict(_QUOTA_TOOLS)
    events = {}
    cycles = []
    for tool, start, end, used, current in planned:
        if tool not in events:
            # Grok 没有带时间戳的事件缓存,只能靠账本的 hours。
            events[tool] = (_quota_claude_events(cache) if tool == "claude"
                            else _quota_codex_events(codex_spans, cache) if tool == "codex"
                            else None)
        tokens, per_device, approx = _quota_window_tokens(
            devices, tool, keys[tool], start, end, events[tool])
        cycles.append({
            "tool": tool,
            "start": start,
            "end": end,
            "used_pct": used,
            "tokens": tokens,
            "devices": per_device,
            "approx": approx,
            "current": current,
        })

    merged = {}
    for _name, _tools, _snapshot, daily in devices:
        for day, value in daily.items():
            agg = merged.setdefault(day, {key: 0 for _t, key in _QUOTA_TOOLS})
            for _tool, key in _QUOTA_TOOLS:
                agg[key] += value.get(key, 0)

    return {
        "daily": [dict(d=day, **value) for day, value in sorted(merged.items())],
        "cycles": cycles,
        "devices": [name for name, _tools, _snapshot, _daily in devices],
        "missing": missing,
        "now": now,
    }


def quota_detail():
    print(json.dumps(build_quota_detail(), ensure_ascii=False))


def build_dashboard(period="all"):
    cache = _load_dashboard_cache()
    result = build_daily_costs(period, refresh=False, _cache=cache)
    result["wrapped"] = build_wrapped(period, refresh=False, _cache=cache)
    return result


def dashboard():
    print(json.dumps(build_dashboard(_arg_period()), ensure_ascii=False))


# ---------- 项目维度：唯一数据源 ----------
# 项目足迹页与 Wrapped 的每日项目都从 _project_contributions 派生。历史上两边
# 各写各的，结果 pi 只出现在项目足迹、grok 只出现在项目足迹而不在回顾页，
# WorkBuddy 的回顾页项目名还是会话时间戳目录而不是真实项目——同一份事实分两处
# 维护必然分裂。这里合成一股流，两个页面消费同一个来源。
#
# 接入一个新 harness：让它的 scanner 在缓存条目上写 proj（项目绝对路径），
# 再在 _PROJECT_SOURCES 加一行，两个页面同时生效，不必各改一遍。
#
# session 取值：
#   "entry" —— 一个缓存条目就是一次会话，按条目计数；
#   "sid"   —— 条目上的 sid 才是会话标识，跨条目去重（一次会话写多个文件）。
# tokens 用哪个函数数：多数工具用 token_total，Muse Code 的推理并进输出，
# 口径不同，所以按工具指定，避免统一成一个"差不多"的算法。
_PROJECT_SOURCES = (
    # tool_key,      显示名,            记成本, session, token 计数
    ("claude",       "Claude",          True,  "entry", "token_total"),
    ("codex",        "Codex",           True,  "entry", "token_total"),
    ("pi",           "Pi",              True,  "entry", "token_total"),
    ("prime_agent",  "Prime Agent",     True,  "entry", "token_total"),
    # Kimi 的 wire 不持久化真实成本，卡片也刻意不显示，这里同样不记。
    ("kimicode",     "Kimi Code",       False, "sid",   "token_total"),
    ("musecode",     "Muse Code",       True,  "sid",   "_muse_token_total"),
    ("cmdcode",      "Command Code",    True,  "sid",   "token_total"),
)

# 第二种形状：一个库里装着多个项目（数据库型工具）。项目挂在「天」上：
#   entry["days"][日期]["projects"][项目路径] = {tokens, cost, models, sessions}
# 一文件一会话的工具用上面 _PROJECT_SOURCES 的形状，两种都走同一个贡献流。
_PROJECT_DAY_SOURCES = (
    # tool_key,  显示名
    ("devin",    "Devin"),
    ("hermes",   "Hermes"),
    ("opencode", "OpenCode"),
    ("mimocode", "MiMoCode"),
)

# 缓存是 records 而非 days 的工具，各自的去重逻辑已在迭代器里。
_PROJECT_RECORD_SOURCES = (
    ("workbuddy",        "WorkBuddy",        "_iter_workbuddy_records",        None),
    ("workbuddy_ai",     "WorkBuddy Intl.",  "_iter_workbuddy_records",        None),
    ("codebuddy",        "CodeBuddy",        "_iter_workbuddy_records",        None),
    ("deepseek_harness", "DeepSeek Harness", "_iter_deepseek_harness_records", "deepseek-v4-pro"),
)


def _project_contribution(tool, label, path, day, tokens, cost, models, session,
                          cost_cny=0.0):
    return {"tool": tool, "label": label, "path": path, "day": day or "",
            "tokens": int(tokens or 0), "cost": float(cost or 0.0),
            "cost_cny": float(cost_cny or 0.0),
            "models": models or {}, "session": session}


def _project_contributions(cache):
    """项目维度的原子贡献流，供项目足迹与 Wrapped 共用。

    每条是「某工具在某项目某天产生了多少 token / 成本 / 哪些模型 / 属于哪次会话」。
    """
    for tool_key, label, with_cost, session_mode, counter_name in _PROJECT_SOURCES:
        count = globals().get(counter_name, token_total)
        tool_cache = cache.get(tool_key)
        if not isinstance(tool_cache, dict):
            continue
        for entry_key, entry in tool_cache.items():
            if not isinstance(entry, dict):
                continue
            proj_path = entry.get("proj") or ""
            if not proj_path or proj_path == "?":
                continue
            session = entry.get("sid") if session_mode == "sid" else entry_key
            for day_key, day in (entry.get("days") or {}).items():
                if not isinstance(day, dict):
                    continue
                models = {f"{nice_model(name)} ({label})": count(usage)
                          for name, usage in (day.get("models") or {}).items()}
                yield _project_contribution(
                    tool_key, label, proj_path, day_key, count(day),
                    day.get("cost", 0) if with_cost else 0.0, models, session)

    for tool_key, label, iterator_name, default_model in _PROJECT_RECORD_SOURCES:
        iterator = globals().get(iterator_name)
        tool_cache = cache.get(tool_key)
        if not callable(iterator) or not isinstance(tool_cache, dict):
            continue
        for entry_path, entry, record in iterator(tool_cache):
            proj_path = entry.get("proj") or ""
            if not proj_path or proj_path == "?":
                continue
            model_name = record.get("model") or default_model or "unknown"
            tokens = token_total(record)
            yield _project_contribution(
                tool_key, label, proj_path, record.get("date"), tokens,
                record.get("cost", 0),
                {f"{nice_model(model_name)} ({label})": tokens},
                record.get("session") or entry.get("sid") or entry_path,
                cost_cny=record.get("cost_cny", 0))

    for tool_key, label in _PROJECT_DAY_SOURCES:
        tool_cache = cache.get(tool_key)
        if not isinstance(tool_cache, dict):
            continue
        for entry in tool_cache.values():
            if not isinstance(entry, dict):
                continue
            for day_key, day in (entry.get("days") or {}).items():
                if not isinstance(day, dict):
                    continue
                by_project = day.get("projects")
                if not isinstance(by_project, dict):
                    continue    # 名字列表是给账本归档用的，不是这里的按项目用量
                for proj_path, usage in by_project.items():
                    if not proj_path or not isinstance(usage, dict):
                        continue
                    models = {f"{nice_model(name)} ({label})": int(amount or 0)
                              for name, amount in (usage.get("models") or {}).items()}
                    session_ids = [sid for sid in (usage.get("sessions") or []) if sid]
                    yield _project_contribution(
                        tool_key, label, proj_path, day_key,
                        usage.get("tokens", 0), usage.get("cost", 0), models,
                        tuple(session_ids))

    # Grok 的缓存已经是「按天按项目」的富结构，直接转成同一种贡献。
    grok_cache = cache.get("grok")
    if isinstance(grok_cache, dict):
        for entry in grok_cache.values():
            if not isinstance(entry, dict):
                continue
            proj_path = entry.get("project") or ""
            if not proj_path:
                continue
            # 只带会话与日期，token 由下面按天的那份给出，避免重复计数。
            yield _project_contribution(
                "grok", "Grok Build", proj_path, entry.get("date"), 0, 0.0, {},
                entry.get("sid"))
    grok_days = cache.get(_GROK_DAYS_CACHE_KEY)
    if isinstance(grok_days, dict):
        for day_key, day in grok_days.items():
            if not isinstance(day, dict):
                continue
            for proj_path, usage in (day.get("projects") or {}).items():
                if not proj_path:
                    continue
                models = {f"{nice_model(name)} (Grok Build)": int(amount or 0)
                          for name, amount in (usage.get("models") or {}).items()}
                sessions = [sid for sid in (usage.get("sessions") or []) if sid]
                yield _project_contribution(
                    "grok", "Grok Build", proj_path, day_key,
                    usage.get("tokens", 0), usage.get("cost", 0), models,
                    sessions[0] if len(sessions) == 1 else tuple(sessions))


def _project_day_names(cache):
    """{日期: {项目名}}。Wrapped 的每日项目由此而来，与项目足迹同源。"""
    names = {}
    for hit in _project_contributions(cache):
        if not hit["day"]:
            continue
        name = os.path.basename(hit["path"].rstrip("/")) or hit["path"]
        names.setdefault(hit["day"], set()).add(name)
    return names


def projects():
    """项目足迹:从缓存聚合所有项目路径、活跃时间、session 数、token、成本。

    数据来自 _project_contributions —— 和 Wrapped 的每日项目同一个来源。
    """
    compute()
    cache = _load_scan_cache()

    proj_map = {}   # path → {sessions, tokens, cost, last_active, model_tok, tools}
    sessions = {}   # path → {会话标识}
    for hit in _project_contributions(cache):
        proj_path = hit["path"]
        p = proj_map.setdefault(proj_path, {"sessions": 0, "tokens": 0, "cost": 0.0,
                                            "last_active": "", "model_tok": {}, "tools": set()})
        p["tools"].add(hit["tool"])
        p["tokens"] += hit["tokens"]
        p["cost"] += hit["cost"]
        if hit["cost_cny"]:
            p["cost_cny"] = p.get("cost_cny", 0) + hit["cost_cny"]
        if hit["day"] > p["last_active"]:
            p["last_active"] = hit["day"]
        for name, tokens in hit["models"].items():
            p["model_tok"][name] = p["model_tok"].get(name, 0) + tokens
        session = hit["session"]
        if isinstance(session, tuple):
            sessions.setdefault(proj_path, set()).update(session)
        elif session:
            sessions.setdefault(proj_path, set()).add(session)
    for proj_path, session_ids in sessions.items():
        proj_map[proj_path]["sessions"] += len(session_ids)

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
            "cost": round(info["cost"], 2), "cost_cny": info.get("cost_cny", 0),
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
    if "--dashboard" in sys.argv:
        dashboard()
    elif "--quota-detail" in sys.argv:
        quota_detail()
    elif "--daily-costs" in sys.argv:
        daily_costs()
    elif "--write-sync" in sys.argv:
        sys.exit(write_sync_snapshot())
    elif "--projects" in sys.argv:
        projects()
    elif "--wrapped" in sys.argv:
        wrapped()
    elif "--json" in sys.argv:
        main_json()
    else:
        main()
