# Tokei 计算逻辑

Tokei 读取本地 AI CLI 工具的日志,统计 token 用量与成本。所有数据纯本地读取,不联网。

---

## 1. 数据源

| 工具 | 日志路径 | 格式 |
|------|---------|------|
| Claude Code | `~/.claude/*/*.jsonl` | JSONL, `type=assistant` 行含 `message.usage` |
| Codex | `~/.codex/**/rollout-*.jsonl` | JSONL, `payload.info.last_token_usage` |
| Gemini CLI | `~/.gemini/*/chats/session-*.json` | JSON, `messages[].tokens` |
| Grok Build | `${GROK_HOME:-~/.grok}/logs/unified.jsonl` + `sessions/*/*/{summary,signals}.json` | JSONL, `shell.turn.inference_done` + 会话指标 |
| Qoder | `~/Library/Application Support/QoderWork/data/agents.db` | SQLite, `messages.metadata` |
| Hermes | `~/.hermes/state.db` + `~/.hermes/profiles/*/state.db` | SQLite, `session_model_usage*` 用量表，回退 `sessions` 表 |
| OpenClaw | `~/.openclaw/agents/*/sessions/*.jsonl` + `~/.openclaw/state/openclaw.sqlite` | JSONL 用量 + SQLite 任务 |
| Pi Coding Agent CLI | `~/.pi/agent/sessions/<project>/*.jsonl` | JSONL, `message.usage` |
| WorkBuddy | `~/.workbuddy/projects/<project>/*.jsonl` | JSONL, `message.usage` / `providerData.usage` |
| OpenCode | `~/.local/share/opencode/opencode.db`，旧版回退 `~/.local/share/opencode/storage/message/ses_*/msg_*.json` | SQLite/JSON, `tokens` + `cost` |
| Qwen Code | `${QWEN_RUNTIME_DIR:-~/.qwen}/usage/token-usage-*.jsonl` + `~/.qwen/usage_record.jsonl` | JSONL,逐请求记录 + 会话汇总 |
| DeepSeek Harness | `${DSH_HOME:-~/.dsh}/sessions/**/session.jsonl.zstd`，兼容 `session.jsonl` | zstd 压缩或明文 JSONL，`assistant/message.data.usage` |

---

## 2. Token 字段含义

不同工具的 API 返回口径不同,Tokei 统一为以下展示口径:

| 字段 | 含义 |
|------|------|
| `输入` | 非缓存输入 token(不含 cache_read) |
| `输出` | 输出 token |
| `缓存读` | 命中缓存的输入 token |
| `缓存写` | 写入缓存的输入 token |
| `推理` | 推理/思考 token(Codex reasoning, Gemini thoughts) |

### 各工具原始字段映射

**Claude Code** — `input_tokens` 仅包含非缓存输入:
- 输入 = `input_tokens`
- 输出 = `output_tokens`
- 缓存读 = `cache_read_input_tokens`
- 缓存写 = `cache_creation_input_tokens`

**Codex** — `input_tokens` 已包含缓存,`output_tokens` 已包含推理:
- 输入 = `input_tokens - cached_input_tokens`
- 输出 = `output_tokens`（含 `reasoning_output_tokens`）
- 缓存 = `cached_input_tokens`（`input_tokens` 的子集）
- 推理 = `reasoning_output_tokens`（`output_tokens` 的子集）
- 总量 = `input_tokens + output_tokens`（即 `total_tokens`）

Codex 的子代理和分叉 rollout 可能重放父任务历史。Tokei 使用 `session_meta.id`
识别当前会话,再从 `forked_from_id` 或
`source.subagent.thread_spawn.parent_thread_id` 找到父会话,并用
`total_token_usage + last_token_usage` 组成快照键扣除子会话开头复制的父会话前缀。
缺少父会话元数据时,只对较长的相同前缀做保守去重,避免把两个独立会话里偶然相同的
token 快照误删。

**Gemini CLI** — `tokens.input` 已包含缓存:
- 输入 = `tokens.input - tokens.cached`
- 输出 = `tokens.output`
- 缓存 = `tokens.cached`
- 思考 = `tokens.thoughts`

**Hermes** — 字段独立,与 Claude 一致:
- 输入 = `input_tokens`
- 输出 = `output_tokens`
- 缓存读 = `cache_read_tokens`
- 缓存写 = `cache_write_tokens`
- 推理 = `reasoning_tokens`

优先合并 `session_model_usage` 与升级中断时保留的 `session_model_usage_v21`，按会话、模型、
计费端点和任务维度去重；主循环明细不存在时才回退 `sessions` 汇总。这样既包含 0.19 新增的
审批、标题生成等辅助调用，也保留已删除会话留下的历史用量；会话数仍以 `sessions` 中
可见的会话为准，避免把内部清理记录重复算作对话。

**OpenCode** — 字段独立:
- 输入 = `tokens.input`
- 输出 = `tokens.output`
- 缓存读 = `tokens.cache.read`
- 缓存写 = `tokens.cache.write`
- 推理 = `tokens.reasoning`

**Pi Coding Agent CLI** — 字段独立,与 OpenCode 展示口径一致:
- 输入 = `usage.input`
- 输出 = `usage.output`
- 缓存读 = `usage.cacheRead`
- 缓存写 = `usage.cacheWrite`
- 推理 = `usage.reasoning`(如果存在)
- 成本 = `usage.cost.total`(优先使用)

**Qwen Code** — `inputTokens` 已包含缓存,`thoughtsTokens` 独立:
- 输入 = `inputTokens - cachedTokens`
- 输出 = `outputTokens`
- 缓存读 = `cachedTokens`
- 思考 = `thoughtsTokens`
- 总量 = `inputTokens + outputTokens + thoughtsTokens`

Tokei 优先读取逐请求日志以获得进行中会话和小时分布。旧版 `usage_record.jsonl`
按 `sessionId` 取最后一份快照,用于补齐逐请求日志出现前的历史。同一会话同时存在两种来源时,
逐请求日志优先,避免重复累计。

**DeepSeek Harness** — usage bucket 相互独立，但 `reasoningTokens` 是 `outputTokens` 的子集:
- 输入 = `inputTokens`
- 输出 = `outputTokens - reasoningTokens`
- 缓存读 = `cacheReadTokens`
- 缓存写 = `cacheWriteTokens`
- 推理 = `reasoningTokens`
- 总量 = `inputTokens + outputTokens + cacheReadTokens + cacheWriteTokens`

同一次调用会先出现 `assistant/chunk` usage，再出现 `assistant/message` 最终 usage。Tokei
按 `(turn, step)` 使用后者覆盖前者，避免重复计数；模型取该调用之前最近的
`request/context`，会话 identity 取日志首行 `session.id`。当前只接受官方 session format v0，
遇到未来版本会保留上次成功缓存并在诊断中报告，而不会按未知 schema 猜测。

**Grok Build** — `unified.jsonl` 中每条带 token 字段的 `shell.turn.inference_done` 代表一次模型调用：
- 输入 = `prompt_tokens - cached_prompt_tokens`
- 缓存读 = `cached_prompt_tokens`
- 输出 = `completion_tokens - reasoning_tokens`
- 推理 = `reasoning_tokens`
- 总量 = 输入 + 缓存读 + 输出 + 推理

记录按自身 `ts` 归入日期和小时，并通过 `sid` 关联 `summary.json` 中的模型与项目路径。
旧版 `inference_done` 没有 token 字段，只在卡片中降级展示上下文快照；上下文快照不会计入
Dashboard、Wrapped 或项目 token 总量。

**Qoder** — `inputTokens` / `outputTokens` 目前全为 0,仅 `durationMs` 和 `contextUsageRatio` 有值。

**OpenClaw** — Session JSONL 的 `message.usage` 提供输入、输出、缓存读写和成本；
`state/openclaw.sqlite` 的 `task_runs` 提供任务状态。旧版
`~/.openclaw/tasks/runs.sqlite` 仍作为兼容回退。

---

## 3. 缓存命中率

两种公式,取决于 `input` 是否包含缓存:

### Claude / Grok Build / Hermes / Pi / WorkBuddy / OpenCode / Qwen Code(input 不含缓存)

```
hit% = cache_read / (cache_read + cache_write + input) × 100
```

分母是全部输入 token(缓存读 + 缓存写 + 非缓存输入)。

### Codex / Gemini(input 已含缓存)

```
hit% = cached / input × 100
```

`input` 本身已包含 `cached`,所以直接用 `cached / input`。

---

## 4. 成本估算

### 定价来源(三级查找)

```
优先级: pricing_overrides.json > pricing.json > _DEFAULT_PRICES(内置兜底)
```

- `pricing.json` — 从 OpenRouter API 同步(`--update-prices`),每 1M token 美元单价
- `pricing_overrides.json` — 本地修正(write1h 价格、别名、缺漏),更新不覆盖
- `_DEFAULT_PRICES` — 内置硬编码,离线兜底

### 模型名归一化

本地模型名 → OpenRouter canonical ID:
- `claude-opus-4-8` → `anthropic/claude-opus-4.8`
- `gpt-5.5` → `openai/gpt-5.5`
- `gemini-3.5-flash` → `google/gemini-3.5-flash`
- `:free` / `-free` 后缀去除,按基础价计算
- 未知模型按 `anthropic/claude-opus-4.8` 兜底(偏保守)

### Claude Code 成本公式

```
cost = input/1M × price_in
     + output/1M × price_out
     + cache_read/1M × price_cache_read
     + write_cost

write_cost:
  如果 API 返回 cache_creation.ephemeral_5m/1h 分档:
    = ephemeral_5m/1M × write5m_price + ephemeral_1h/1M × write1h_price
  否则:
    = cache_write/1M × write5m_price
```

缓存写入价格两档:
- `write5m` = OpenRouter 的 `cache_write` 价(5 分钟 TTL)
- `write1h` = Anthropic 为 `2 × input_price`(1 小时 TTL)

### Codex 成本公式

```
cost = (input - cached)/1M × price_in
     + cached/1M × price_cache_read
     + output/1M × price_out
```

高上下文加价(input > 272K tokens):
- 输入价 × 2
- 缓存价 × 2
- 输出价 × 1.5

### Gemini CLI 成本公式

```
cost = non_cached_input/1M × price_in
     + cached/1M × price_cache_read
     + (output + thoughts)/1M × price_out
```

思考 token 按输出价计费。

### Qwen Code 成本公式

```
cost = non_cached_input/1M × price_in
     + cached/1M × price_cache_read
     + (output + thoughts)/1M × price_out
```

采集后 `input` 已转换为非缓存输入,成本重算时直接按拆分后的输入、缓存和思考字段计算。

### Hermes 成本

优先使用数据库中的 `actual_cost_usd`,回退到 `estimated_cost_usd`；两者都为 0 时按统一
价格表估算，避免 Hermes 自定义供应商未写入账单金额时把成本显示为 0。

### Pi Coding Agent CLI / OpenCode 成本

Pi 优先使用会话 JSONL 中的 `usage.cost.total`；OpenCode 优先读取 SQLite `message.data` 中的 `cost` 字段，旧版 JSON 文件同口径。若 Pi 成本字段缺失，或 OpenCode 成本为 0 且模型能匹配价格表，则按统一价格表用 input/output/cache_read/cache_write 回退估算。

### Grok Build / Qoder / OpenClaw

不估算成本。Grok Build 的 OAuth/订阅交互日志没有完整成本，缺失值不会显示为 0 美元；
只有 token 参与聚合和排行。

---

## 5. 额度/配额

### Claude(套餐用量)

从 Claude Desktop 的 Chromium HTTP 缓存读取 `/usage` 响应(zstd 压缩):
- `q5` — 5 小时窗口已用百分比
- `q7` — 日窗口已用百分比
- `q5_reset` / `q7_reset` — 重置时间

### Codex(rate_limits)

从 rollout JSONL 中 `rate_limits` 字段读取:
- 根据 `window_minutes` 识别窗口,不依赖 primary / secondary 的固定含义
- `p5` — 5 小时窗口已用百分比(`window_minutes=300`)
- `pw` — 周窗口已用百分比(`window_minutes=10080`)
- `r5` / `rw` — 重置时间
- `plan_type` — 套餐类型

兼容 Codex 新旧返回结构:旧结构通常是 primary=5h、secondary=周;新结构可能只有 primary=周。

重置卡使用当前 Codex 登录态只读查询
`/backend-api/wham/rate-limit-reset-credits`。本地仅缓存可用数量和到期时间，不保存卡片
ID、邀请信息或个人资料；每天最多自动查询一次，最近一张卡到期后立即更新，失败后
6 小时再试。未登录或仅使用 API Key 时不请求；401/403 静默隐藏或沿用未过期缓存，
Codex 刷新登录 Token 后立即重试。

### Grok Build(credits)

默认**只读本地日志**，不访问网络：

- 来源：`${GROK_HOME:-~/.grok}/logs/unified.jsonl` 中
  `billing: fetched credits config`
- `pct` — 当前周期已用百分比（`creditUsagePercent`）
- `reset` — 周期结束/重置时间
- `plan` — 套餐名（日志里的 `subscriptionTier`，如 SuperGrok）
- `window` — `week` / `month`（由 `currentPeriod.type` 推断）
- `source` — `log` / `live` / `cache`

可选实时接口（**默认关闭**，需用户显式开启）：

- 配置：`~/.tokei/config.json` 中 `grok_live_quota_enabled: true`
- 或环境变量：`TOKEI_GROK_LIVE_QUOTA=1`（`0` 强制关闭）
- 接口：`GET https://cli-chat-proxy.grok.com/v1/billing?format=credits`
- 鉴权：`~/.grok/auth.json` 中的 Bearer token
- 额外字段：`products[]`（如 GrokBuild / Api 分产品已用百分比）

策略：

1. 始终优先解析本地日志
2. 仅当用户开启实时查询时，才请求账单接口覆盖为最新值
3. 失败时回退到本地日志或短缓存，不报错

### Qoder(credit)

从 QoderWork 日志 `main.log` 中提取 `userQuota`:
- `totalCredits` / `usedCredits` / `isQuotaExceeded`

---

## 6. 时间区间

所有工具按相同的 6 个区间聚合:

| 区间 | 含义 |
|------|------|
| `today` | 今天(本地时区) |
| `yesterday` | 昨天 |
| `week` | 本周(周一起) |
| `last_week` | 上周 |
| `month` | 本月 |
| `year` | 本年 |

同一条记录可能同时属于多个区间(如今天的数据同时计入 today / week / month / year)。

---

## 7. 总 Token 数

菜单栏显示的"总 token"是当前会话(最近修改的 JSONL 文件)的全部 token 总和:

```
session_total = input + output + cache_read + cache_write
```

卡片内各区间的总 token 同理,按区间累加各字段后求和。
