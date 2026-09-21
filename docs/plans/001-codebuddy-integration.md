# CodeBuddy 本地用量接入

## 目标

为 Tokei 增加独立的 CodeBuddy Code 本地用量来源，读取本机 `~/.codebuddy/projects/**/*.jsonl` 中已经落盘的模型调用数据，在不读取会话正文或账号凭据的前提下展示 Token、缓存拆分、会话数、模型明细和 CodeBuddy Credits，并让数据进入现有账本、日报、项目排行、同步和 macOS 卡片。

## 范围

- 新增 `codebuddy` provider，默认读取 `~/.codebuddy/projects`，支持环境变量覆盖。
- 复用 WorkBuddy 的 JSONL 解析、按文件签名缓存、按日账本和项目归属逻辑。
- 解析 `message.usage` 与 `providerData.rawUsage` 的输入、输出、缓存读写和 `credit`；同一模型调用只计一次。
- 纳入主会话和 `subagents`，使用 `sessionId` 与模型消息 ID 做去重，不使用会跨多次调用复用的 conversation ID 去重。
- 在 Python JSON 输出、ledger、日报、项目排行和 Swift 数据模型/同步/UI 中增加独立 CodeBuddy 字段；回顾继续沿用全局 Token/估算成本口径，原生 Credit 在卡片、复制摘要和日报中单独展示。
- 新增脱敏合成 fixture 与现有本机真实样本的只读验证，不把真实 transcript、模型私有别名、凭据或机器绝对路径写入仓库。

## 不在范围内

- 不读取 CodeBuddy auth、OAuth、local storage、运行日志或 trace 作为主数据源。
- 不请求 CodeBuddy 官方网络额度接口，不实现账户剩余 Credit/套餐余额。
- 不把 CodeBuddy Credit 换算成美元；美元字段若无法命中明确价格，只标记为估算/未知，不显示为免费。
- 不改动 WorkBuddy、其他 provider 的业务口径，不顺手重构无关 UI。

## 关键决策

1. `~/.codebuddy/projects/**/*.jsonl` 是主源。它包含逐次模型调用以及稳定的 `messageId`/entry ID；`traces` 只有聚合数据，`logs` 可能重复且包含敏感正文。
2. 以 `providerData.messageId` 为模型 generation 去重主键，回退到 entry `id`，并与 `sessionId`、时间戳组成复合键。`conversationRequestId` 只作为关联信息，不能作为去重键。
3. `message.usage.input_tokens`/`rawUsage.prompt_tokens` 是含缓存的 prompt 总量；`cache_read_input_tokens`/`prompt_cache_hit_tokens` 是其子集，展示输入时拆成非缓存输入与缓存读。`completion_thinking_tokens` 已包含在输出中，不再额外累加推理。
4. `rawUsage.credit` 进入独立 `credits` 字段，沿用现有 Qoder CLI 对 Credits 的格式化方式，但不复用美元 `cost` 字段。
5. CodeBuddy 使用独立 provider key 和 UI 卡片，避免与 WorkBuddy 的缓存/账本/项目统计混合。

## 实施步骤

1. 为通用 Token 日桶、模型桶和 `TokenUsageRange` 增加可选 Credits 累加能力，并使旧缓存/旧同步快照向后兼容。
2. 将 WorkBuddy 记录解析补充为可选 Credit 字段和 parser 版本；新增 `scan_codebuddy()`，把 CodeBuddy root 接到 `compute()`。
3. 补齐 Python 的 ledger reconcile、daily costs、wrapped、projects 和诊断输出，确保 Token/成本/Credit 不重复累计。
4. 补齐 Swift `Usage`、`TokenModelStat`、`TokenUsageRange`、`SyncManager`、面板卡片、设置开关、日报、回顾、分享图和项目颜色/标签。
5. 增加合成测试：snake/camel/raw usage 对齐、缓存拆分、Credit 保留、重复 message ID、主会话与 subagent、未知价格不冒充美元。
6. 在 worktree 中运行 Python 测试、Swift 同步检查、`swift build` 和本机 CodeBuddy live-only scanner；确认不读取凭据、不保存 transcript，检查 PR diff 无真实本机数据。

## 验证

- `python3 -m py_compile usage.30s.py`
- `PYTHONPATH=tests python3 -m unittest ...`
- `bash Tokei/Tests/run-sync-integration-checks.sh`
- `swift build --package-path Tokei`
- 对本机 `~/.codebuddy/projects` 做禁写扫描，核对记录数、Token、缓存、Credit、重复键和二次扫描缓存命中。
- 构建完成后再在合并后的 `dev` 上生成并覆盖安装本地 macOS App。

## 假设与延期

- 当前安装的 CodeBuddy Code CLI 为 2.151.0；未来字段变化由 parser 的字段回退和版本化缓存处理。
- 现有本机样本的未映射模型不产生可验证的美元成本；第一版以 CodeBuddy Credits 为准确消费指标。
- OpenClaw PR #75 保持原始分支和提交不改写，最终在 `dev` 上与 CodeBuddy 分支一起合并并解决主线冲突。
