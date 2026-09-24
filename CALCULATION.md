# Tokei 计算逻辑

Tokei 主要读取本地 AI 工具日志，统计 token 用量与成本。额度查询按工具使用本地日志或已有的本机登录态；需要联网的查询会明确标注并提供开关。

---

## 1. 数据源

| 工具 | 日志路径 | 格式 |
|------|---------|------|
| Claude Code | `~/.claude/*/*.jsonl` | JSONL, `type=assistant` 行含 `message.usage` |
| Gemini / Antigravity CLI | `~/.gemini/antigravity-cli/conversations/*.db` / `~/.gemini/*/chats/session-*.json` | SQLite (`gen_metadata` protobuf) / JSON (`messages[].tokens`) |
| Grok Build | `${GROK_HOME:-~/.grok}/logs/unified.jsonl` + `sessions/*/*/{summary,signals}.json` | JSONL, `shell.turn.inference_done` + 会话指标 |
| Grok Bot | `~/Library/Application Support/Grok Bot/sand-client-persistence/*.blob` | JSON 快照；会话、消息、响应、工具调用、时间 |
| Qoder Desktop | `~/Library/Application Support/Qoder/SharedClientCache/cache/db/local.db` | SQLite, `chat_message.token_info` / `model_info` |
| QoderWork | `~/Library/Application Support/QoderWork/data/agents.db` | SQLite, `messages.metadata` |
| Qoder CLI | `~/.qoder/projects/**/*.jsonl` | JSONL, 会话/调用/工具/时长；文本量估算 Token |
| Qoder CN | `~/.qoder-cn/projects/**/*.jsonl` | 与 Qoder CLI 同格式同口径，独立键 `qodercli_cn` 统计 |
| Hermes | `~/.hermes/state.db` + `~/.hermes/profiles/*/state.db` | SQLite, `session_model_usage*` 用量表，回退 `sessions` 表 |
| OpenClaw | `~/.openclaw/state/openclaw.sqlite` + agent SQLite；兼容旧 JSONL | SQLite/JSONL 用量 + SQLite 任务 |
| Pi Coding Agent CLI | `~/.pi/agent/sessions/<project>/*.jsonl` | JSONL, `message.usage` |
| Prime Agent | `~/.prime/agent/sessions/*.jsonl` + `session-artifacts/**/**/*.jsonl` | JSONL, assistant `message.usage` |
| WorkBuddy | `~/.workbuddy/projects/<project>/*.jsonl` | JSONL, `message.usage` / `providerData.usage` |
| WorkBuddy Intl. | `~/.workbuddy-ai/projects/<project>/*.jsonl` | JSONL, `message.usage` / `providerData.usage` |
| CodeBuddy Code | `~/.codebuddy/projects/**/*.jsonl`（含主会话与 `subagents`） | JSONL, `message.usage` / `providerData.rawUsage` / `providerData.messageId` |
| DeepSeek Harness | `~/.dsh/sessions/**/session.jsonl.zstd` | 多帧 zstd JSONL，最终 `assistant/message.data.usage` |
| OpenCode | `~/.local/share/opencode/opencode.db`，旧版回退 `~/.local/share/opencode/storage/message/ses_*/msg_*.json` | SQLite/JSON, `tokens` + `cost` |
| Qwen Code | `${QWEN_RUNTIME_DIR:-~/.qwen}/usage/token-usage-*.jsonl` + `~/.qwen/usage_record.jsonl` | JSONL,逐请求记录 + 会话汇总 |
| 千问办公（QwenWork） | `~/.qwenworkcn/mcp-adaptor.config` + `.status.json` 文件元数据 + 官方桌面端 `127.0.0.1` MCP | JSON-RPC，`qw_query` / `qwenwork.usage`（默认关闭） |
| Kimi Code | `${KIMI_CODE_HOME:-~/.kimi-code}/sessions/*/*/agents/*/wire.jsonl`；兼容旧版 `${KIMI_SHARE_DIR:-~/.kimi}/sessions/*/*/wire.jsonl` | JSONL, protocol 1.5 `usage.record` / protocol 1 `StatusUpdate.token_usage` |
| Muse Code | `${TOKEI_MUSE_DIR:-~/.local/share/muse}/sessions/*/*/*/session.jsonl` | JSONL, `model_completed` 事件 `usage` + `model` |
| Command Code | `${TOKEI_CMDCODE_DIR:-~/.commandcode}/projects/*/*.jsonl` | JSONL, assistant message 顶层 `usage` + `costUsd` |
| Kimi Code(额度) | `${KIMI_CODE_HOME:-~/.kimi-code}/credentials/kimi-code.json` → `api.kimi.com/coding/v1/usages` | 本机登录态只读查询，见 §5 |
| ZCode | `~/.zcode/cli/db/db.sqlite` | SQLite, `model_usage` Token 明细 |
| MiMoCode | `$XDG_DATA_HOME/mimocode/mimocode*.db`，macOS 使用 `~/Library/Application Support/mimocode/` | SQLite, OpenCode-compatible `message` 数据 |

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

新版日志读取 `token_usage_record.payload.usage`，按 `response_id` 去重；旧版
`event_msg/token_count` 仍兼容。双写时抵扣对应的旧快照，跨增量扫描保存待抵扣状态。
压缩上下文调用也计入；压缩后的上下文大小不当作一次调用用量。主卡片、Dashboard、
回顾及额度历史的 token 总量都不重复加缓存或推理字段。

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

**DeepSeek Harness** — 底层字段互斥保存，卡片主口径与 Harness 自身一致:
- 输入 = `inputTokens + cacheReadTokens + cacheWriteTokens`
- 输出 = `outputTokens`（已包含 `reasoningTokens`）
- 缓存读、缓存写、推理作为输入/输出的组成明细展示
- 总量 = 输入 + 输出
- `deepseek-official` 路由固定采用 DeepSeek 官方直连价，不受 OpenRouter 价格更新影响
- 官方直连使用人民币原价，按下文历史切点和峰谷时段计费；第三方保留渠道价格

**Kimi Code** — 官方 wire 日志字段独立:
- protocol 1.5 输入 = `usage.inputOther`
- protocol 1.5 输出 = `usage.output`
- protocol 1.5 缓存读 = `usage.inputCacheRead`
- protocol 1.5 缓存写 = `usage.inputCacheCreation`
- protocol 1 使用对应的 `token_usage.input_other`、`output`、`input_cache_read`、`input_cache_creation`

protocol 1.5 为每个 Agent 单独保存 `agents/<agent>/wire.jsonl`。Tokei 扫描全部 Agent wire，
但使用 `state.json.id` 将它们归并为同一会话，并从 `state.json.cwd` 获取项目。旧 protocol 1
仍递归展开主 wire 中的 `SubagentEvent`，且不扫描旧 `session/subagents`，避免重复。
新格式提供权威 `model`，可展示模型明细；两种格式都不持久化实际成本，因此 Kimi Code
卡片不展示推测的 API 成本。

**Muse Code** — `model_completed` 事件字段独立，与 Codex 同口径:
- 输入 = `usage.input_tokens - usage.cached_tokens`（`input_tokens` 已包含缓存）
- 输出 = `usage.output_tokens`
- 缓存读 = `usage.cached_tokens`（与 `cache_read_tokens` 一致）
- 缓存写 = `usage.cache_write_tokens`
- 推理 = `usage.reasoning_tokens`（视为输出子集展示）
- 模型 = 事件自带 `model`（如 `muse-spark-1.3-contributor`），`same-as-main` 时回退到
  同 run 的 `run.model.configured`；`muse-*` 按 `meta/muse-*` 查价格表估算成本

只读取 `model_completed` 用量事件，按 `source_run_record_id` 去重；`goal_usage_attribution`
是归因账本，不重复计入。项目取自 `runtime.session.metadata` 的 `workspace_root`，
时刻取自记录的 `recorded_at`（微秒）。

**Command Code** — 各 token 字段是独立桶:
- 输入 = `usage.inputTokens`
- 输出 = `usage.outputTokens`
- 缓存读 = `usage.cacheReadTokens`
- 缓存写 = `usage.cacheWriteTokens`
- 成本 = `usage.costUsd`（仅接受有限非负值，直接采用不估算）

只读取真实会话转录中的 assistant `usage`，跳过 checkpoints、prompts 与 hooks audit
sidecar，并按消息身份与时刻跨文件去重。兼容顶层和嵌套消息结构，项目取自 session
记录的 `cwd`，时刻取自 `timestamp`（ISO 8601，兼容 `Z` 后缀）。

**Prime Agent** — Usage 字段与 Pi Coding Agent 一致:
- 输入 = `usage.input`
- 输出 = `usage.output`
- 缓存读 = `usage.cacheRead`
- 缓存写 = `usage.cacheWrite`
- 推理 = `usage.reasoning`（通常没有，按 0 处理）
- 成本 = `usage.cost.total`，缺失时按价格表估算

只读取 assistant message 的逐次 usage；`child_usage_attributed` 是父会话聚合 bookkeeping，不重复计入。RLM 子代理日志按独立 session 参与统计。

**Qwen Code** — `inputTokens` 已包含缓存,`thoughtsTokens` 独立:
- 输入 = `inputTokens - cachedTokens`
- 输出 = `outputTokens`
- 缓存读 = `cachedTokens`
- 思考 = `thoughtsTokens`
- 总量 = `inputTokens + outputTokens + thoughtsTokens`

Tokei 优先读取逐请求日志以获得进行中会话和小时分布。旧版 `usage_record.jsonl`
按 `sessionId` 取最后一份快照,用于补齐逐请求日志出现前的历史。同一会话同时存在两种来源时,
保留逐请求记录，并按模型补入汇总中尚未覆盖的余额，避免部分逐请求日志遮蔽完整历史。
余额归于汇总日期，不伪造缺失请求的小时；缓存明细不完整时仍保持输入总量不重复。

### 持久账本与日志清理

Codex、Claude、OpenClaw、Pi、Prime Agent、WorkBuddy、DeepSeek Harness、Qwen Code、
Kimi Code 按可识别来源保存日快照。同日旧会话日志消失后，保留旧来源，再累计新来源；
同一来源的重复扫描不重复加总。Codex 无现存日志时仍从账本提供历史，Dashboard 和回顾
同时使用保留的模型及小时明细。来源标识以散列保存，并发保存合并来源，解析口径升级
可替换对应来源的旧快照。

旧版仅有日汇总的账本保留无法归属的余额，不把旧日总量与当前日志直接相加。
旧模型明细与余额不一致时归入 `unknown`；旧小时明细超过余额时不继续使用该小时分布，
保留有可靠时间戳的新记录。因此旧历史的小时合计可能小于总量，而不会伪造归属。
升级前已删除且未留存的调用无法重建；同一来源内部被截断、以及仅有数据库日汇总的
扫描器，仍无法凭日总量推断所有缺失事件。账本保护不是供应商逐请求账单的完整核销。

**Grok Build** — `unified.jsonl` 中每条带 token 字段的 `shell.turn.inference_done` 代表一次模型调用：
- 输入 = `prompt_tokens - cached_prompt_tokens`
- 缓存读 = `cached_prompt_tokens`
- 输出 = `completion_tokens - reasoning_tokens`
- 推理 = `reasoning_tokens`
- 总量 = 输入 + 缓存读 + 输出 + 推理

记录按自身 `ts` 归入日期和小时，并通过 `sid` 关联 `summary.json` 中的模型与项目路径。
旧版 `inference_done` 没有 token 字段，只在卡片中降级展示上下文快照；上下文快照不会计入
Dashboard、Wrapped 或项目 token 总量。

**Grok Bot** — 同一 `requestId` 下可能连续写入多条流式 `send-message` 事件，响应次数按
`requestId` 去重；用户消息按稳定 entry id 去重。多个持久化键保存同一份 transcript 时，
再按首尾 entry 边界去重。当前快照没有 Token、模型或成本字段，这三项保持未知，文本长度
不会参与 Token 估算。

**Qoder** — `inputTokens` / `outputTokens` 目前全为 0,仅 `durationMs` 和 `contextUsageRatio` 有值。

**OpenClaw** — 新版从 `state/openclaw.sqlite` 的 `agent_databases` 动态发现每个 agent 的
`openclaw-agent.sqlite`，只读取 `transcript_events.event_json` 中 role 为 assistant 且带
`message.usage` 的原始事件。输入、输出、缓存读写、推理和成本分别使用
`input` / `output` / `cacheRead` / `cacheWrite` / `reasoningTokens` / `cost`；日期以事件时间为准，
模型依次使用 `message.responseModel`、`message.model` 和 `session_windows.model`。未知模型保留原名且
不套用其他模型价格。

旧版 `agents/*/sessions/*.jsonl` 继续兼容；SQLite 与 JSONL 中相同 session 只保留记录更完整的一份，
`.trajectory.jsonl`、全文索引和非 usage 事件不参与统计。`state/openclaw.sqlite` 的 `task_runs`
仍提供任务状态，旧版 `~/.openclaw/tasks/runs.sqlite` 作为任务统计回退。

**CodeBuddy Code** — `message.usage.input_tokens` 与 `providerData.rawUsage.prompt_tokens` 包含缓存输入:
- 输入 = prompt 总量 - `cache_read_input_tokens` - `prompt_cache_write_tokens`
- 输出 = `output_tokens` / `completion_tokens`（`completion_thinking_tokens` 已包含在输出中）
- 缓存读 = `cache_read_input_tokens` / `prompt_cache_hit_tokens`
- 缓存写 = `cache_creation_input_tokens` / `prompt_cache_write_tokens`
- Credit = `providerData.rawUsage.credit`，按模型调用累计，不换算成美元
- 去重优先使用 `sessionId + providerData.messageId`，回退 entry `id`；`conversationRequestId` 只作轮次关联，不能作为去重键
- 主会话和 `subagents` 都参与统计；`traces`、`logs`、auth 和 transcript 正文不作为数据源

---

## 3. 缓存命中率

两种公式,取决于 `input` 是否包含缓存:

### Claude / Grok Build / Hermes / Pi / WorkBuddy / WorkBuddy Intl. / CodeBuddy / OpenCode / Qwen Code(input 不含缓存)

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

### DeepSeek 官方 API 人民币潮汐价格

DeepSeek Harness 的 `provider=deepseek-official`，以及 OpenCode 明确记录的 `providerID=deepseek` / `deepseek-official`，按请求时间使用官方人民币价格。未知渠道不凭模型名推断为官方；OpenRouter 等第三方继续使用其渠道价格。

下表单位均为 **人民币 / 百万 token**，每格按缓存命中输入 / 缓存未命中输入 / 输出排列：

| 生效时间（北京时间） | Flash 非高峰 | Flash 高峰 | Pro 非高峰 | Pro 高峰 |
|---|---|---|---|---|
| 2026-08-17 00:00 之前 | 0.02 / 1 / 2 | 同左 | 0.025 / 3 / 6 | 同左 |
| 2026-08-17 00:00 起 | 0.05 / 1.5 / 4.5 | 0.10 / 3 / 9 | 0.15 / 4.5 / 13.5 | 0.30 / 9 / 27 |
| 2026-09-10 12:00 起 | 0.02 / 1 / 4 | 0.04 / 2 / 8 | 不变 | 不变 |

- 高峰为北京时间周一至周五 09:00–12:00、14:00–18:00，其余时段为非高峰。
- Flash 兼容 `deepseek-flash`、`deepseek-v4.1-flash`、旧 V4 Flash 和 vision-exp 名称；Pro 不在 9 月 14 日切换为 Flash。
- 价格来自[官方人民币表](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)，新切点依据[9 月 10 日公告](https://www.deepseek.com/en/news/deepseek-v4-1-flash/)。历史表独立保留，不用新价反算旧调用。
- `cost` 始终表示美元，`cost_cny` 表示人民币。官方人民币费用不再重复计入美元字段；汇总、明细、分享图和同步按币种分别累计，没有汇率换算。
- Harness 与 OpenCode 的计费缓存版本升级，仍有原始日志的记录重新核算。仅剩旧账本且无法确认渠道和请求时间的历史费用保留原美元记录，不猜测兑换或重新定价。
- 聚合行可能包含同模型的官方与第三方调用，保留两币种金额，不以聚合 token 重算。此类行不展示可能误导的渠道单价。
- 其他工具仍保留各自日志/渠道计价路径；缺乏官方渠道身份的记录不会强制改为人民币。

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

### CodeBuddy Code 成本

CodeBuddy 的 `Credit` 是产品原生消耗单位，不等同于美元。Tokei 保留并展示 Credit；只有模型命中明确价格表时才计算美元估算，未知模型的美元成本保持为未知/零估算，不解释为免费。

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

### Codex Luna Reserve(第二缸油)

OpenAI 给 Codex 的 fallback 额度:常规高级模型额度见底后,会话切到 `gpt-reserve`,
单独计量、单独重置,不占用主额度。日志特征:

- 用量:`turn_context`/`session_meta` 的 `payload.model` 为 `gpt-reserve`;
  同一文件可先走主额度后切 Reserve,因此事件级以 `token_count` 的
  `rate_limits` 为准(`limit_name=gpt-reserve` 或 `limit_id=base_model_inference`,
  主额度是 `limit_id=codex`)
- 额度:`limit_name=gpt-reserve` 的 `primary`(周窗口)的已用百分比与重置时间,
  与主额度独立展示
- 成本:Reserve 按 Luna 级别计价(`openai/gpt-5.6-luna` $0.20/$1.20),
  不吃 `gpt-5.5` 兜底;展示名为 `Luna Reserve` 而非裸 `GPT`
- 主用量/Daily/回顾/项目足迹均扣除 Reserve 部分,互不重叠

重置卡使用当前 Codex 登录态只读查询
`/backend-api/wham/rate-limit-reset-credits`。本地仅缓存可用数量和到期时间，不保存卡片
ID、邀请信息或个人资料；每天最多自动查询一次，最近一张卡到期后立即更新，失败后
6 小时再试。未登录或仅使用 API Key 时不请求；401/403 静默隐藏或沿用未过期缓存，
Codex 刷新登录 Token 后立即重试。

### Kimi Code(usages)

使用 Kimi Code CLI 已有的本机登录态只读查询 `https://api.kimi.com/coding/v1/usages`:
- `p5` — 5 小时滚动窗口已用百分比,取 `limits[]` 中 `window` 折算为 300 分钟的那条
  (`TIME_UNIT_MINUTE`/`TIME_UNIT_HOUR` 均按同一口径折算,不假设接口固定用哪种单位)
- `pw` — 订阅周期额度已用百分比,取顶层 `usage`
- `r5` / `rw` — 各自的 `resetTime`
- `plan` — `user.membership.level`

接口把额度数字写成字符串(`"limit": "100"`),解析时统一转数值;`used` 缺失时按
`limit - remaining` 推算。顶层 `usage` 不带 `window` 字段,接口没有说明该额度是周还是月,
因此界面只显示"订阅额度剩余"和它给出的重置时刻,不替接口命名周期。

**凭据只读、绝不代刷。** access_token 由 CLI 写在
`${KIMI_CODE_HOME:-~/.kimi-code}/credentials/kimi-code.json`,有效期很短(实测约 30 分钟)。
Tokei 只读 `access_token`,从不使用同一文件中的 `refresh_token`:OAuth 刷新令牌通常带
rotation,由 Tokei 抢先刷新会顶掉 Kimi Code 自己的登录态。因此凭据过期时直接跳过这次
请求(发出去也必然 401),转为使用缓存并标记读数已过期。

额度过期的判定有两条,命中任一即标 `p5_stale` / `pw_stale`,卡片改为显示"额度读数已过期"
并附上读数时间:
- 窗口的 `resetTime` 已经过去 —— 这份读数不再代表当前窗口
- 读数本身超过 30 分钟未更新 —— 通常是 CLI 长时间未使用,登录态已过期

Codex 在窗口翻篇后若本机零消耗会判定"确实回满",Kimi 不套用这条:Kimi 额度按调用次数
计量,本机 token 日志无法反推它的真实消耗,谎报满额比承认不知道危险得多。

成功查询缓存 5 分钟;网络失败后 5 分钟内不再重试,避免每轮 30 秒刷新都白等超时。
可用 `TOKEI_KIMI_LIVE_QUOTA=0` 完全关闭该查询,关闭后 token 用量统计不受影响。

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

### Grok Bot

本地活动采集不访问网络。官方用量查询默认关闭；开启并明确授权后，Tokei 优先通过
macOS Keychain 读取 Grok Bot 的 Electron Safe Storage 密钥，在内存中解密当前账号的
短期 access token，再请求固定的官方 Sand usage status 与 usage-events 地址。用量请求固定
`clientType=sand`，只统计 Grok Bot 产生的 Token、缓存、模型和成本，避免混入同账号的 Cursor
调用；账号标识、邮箱、会话内容和登录 Token 都不会写入 Tokei 输出。常规刷新使用禁止弹窗的
Keychain 查询，授权失效时静默降级。成功结果缓存 5 分钟，失败时最多沿用 1 小时缓存。首次授权
会由新进程再次验证长期权限，只有系统弹窗选择“始终允许”后才显示授权成功。没有授权时仍可
回退到可复用的 Cursor 登录态，本地会话活动始终正常显示。

开启多设备同步时，官方 Token、模型、费用和额度汇总随快照同步。合并时只采用更新时间最新的
账号快照，不对各设备的账号总量求和；本地会话活动仍按设备正常累加。
额度过期不会删除已采集的用量。Token、模型和费用按日期持久化，新的成功查询按日覆盖更新，历史日期继续保留。

### 千问办公（QwenWork）

千问办公与 Qwen Code 是两个独立产品。本功能只读取额度，不参与 Qwen Code 的 token、成本或模型统计。

查询默认**关闭**，可通过设置开启，也可使用环境变量：

- `~/.tokei/config.json` 中 `qwenwork_quota_enabled: true`
- `TOKEI_QWENWORK_QUOTA=1` 开启；`TOKEI_QWENWORK_QUOTA=0` 强制关闭

开启后，Tokei 读取 `~/.qwenworkcn/mcp-adaptor.config`，并向其中限定为
`http://127.0.0.1:<port>` 的地址发送 JSON-RPC `POST`：工具固定为 `qw_query`，参数固定为
`{"key":"qwenwork.usage"}`。千问办公必须正在运行且已登录；本机 MCP 会由千问办公自行请求
官方额度。Tokei 不读取或解密 `auth-v2.dat`，不读取浏览器 Cookie，也不自动启动客户端。
为防止退出或切换账号后显示旧额度，Tokei 仅把 `.status.json` 的文件 generation 元数据纳入
缓存标识，不读取其中的姓名、邮箱等账号资料；接口明确返回不可用时会删除旧额度缓存。

额度口径：

- `segments` 是套餐积分和加购积分的 canonical 明细；`planCredits`、`addOnCredits` alias
  仅用于个人积分兼容，不能与 `segments` 重复相加；`sharedAddOnCredits` 只作为共享资源包 fallback
- `aggregateRemainingPercent` 表示**剩余百分比**，允许为 `null`；缺失时展示绝对积分，不反推已用百分比
- `total=0` 且 `remaining>0` 是合法的未知总额状态，例如 `total=0, remaining=2100` 应显示
  `2,100` 剩余积分
- `sharedResourcePackage` 单独展示，不并入个人套餐/加购积分余额
- 结果使用短缓存降低查询频率；实时查询失败时可显示标记为缓存来源的最近结果

千问办公首版只有绝对积分时不加入以百分比为口径的菜单栏额度源，额度在独立卡片展示。

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

### Codex 续跑日志分段

同一 thread ID 可对应多个运行时日志分段，不能按记录数只选最大的文件。对含 response ID 的分段保留未覆盖响应，再在同任务分段间按 response ID 去重；冷扫描、增量追加和归档副本使用一致口径。旧日志无响应身份时保留既有副本选择策略。采集器 revision 5 / Codex parser 5 触发旧缓存重建。

### 续跑与历史账本边界修复

- Codex 分段覆盖关系变化（包括多个分段变为单个完整分段）时重建去重结果；旧格式通知先于响应记录时，已计入的事件补齐 response ID。增量扫描与重新扫描使用相同的响应身份。
- DeepSeek Harness 从无来源明细的旧账本迁移时，已完整重建 token 的零余额不再保留旧币种费用；仍有无法重建的历史 token 时保留旧费用，不猜测历史汇率或渠道。
- OpenCode 仅有按日汇总的历史账本且日志不完整时，保留原日快照，避免新计价版本覆盖更大的历史总量。此时费用保持旧口径，直到现存日志恢复完整；无法据此精确分离被删除记录和后续新增调用。
- 项目排行显示人民币费用；活动热图颜色按每日 token 量计算，费用标签仍按美元、人民币分别显示，币种之间不相加。
