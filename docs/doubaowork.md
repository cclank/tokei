# Doubao Work 数据采集边界

核验日期：2026-10-29。实测客户端：macOS Doubao Work 2.34.4，Browser helper 同为 2.34.4。以下结论只覆盖这份客户端及本机现存数据，不能据此断言其他版本或服务端完全没有用量数据。

## 已实现的统计

`usage.30s.py` 只读 Doubao Work 的 Chromium IndexedDB，会话类型和 Agent 标记同时匹配才计数。时间范围按会话创建日期划分，不按最后更新日期反复计数。当前卡片显示已缓存的 Agent 新建会话数。

会话标识由账号和原始会话 ID 共同哈希。Tokei 仅保存哈希和时间信息，不保存会话标题或正文。历史账本保留已经采集的记录，多设备按哈希标识取并集。

## Token 与速率的追加核验

本轮对源文件先制作本地只读分析副本，报告只保留字段结构和汇总信息。原始数据不进入仓库或测试夹具。

| 数据来源 | 核验结果 | 能支持的结论 |
| --- | --- | --- |
| 当前 chat / launcher IndexedDB | 解码当前有效 KV，检查会话缓存、嵌套 extra 和配置；未发现请求级输入／输出 Token 或生成计时 | 可以计会话，尚不能据此累计 Token |
| background IndexedDB | 主要是功能配置和通用客户端设置 | 配置中的 Token 上限、动画时长等均不计为实际消耗 |
| Local Storage | 当前 201 个逻辑键；相关数据主要是词表、输入选项、设备与功能配置 | 词表里存在 Token 文案不能证明存在用量记录 |
| 本地 Agent trajectory | 当前 6 条记录包含 role、content、tool_calls 等，没有 usage 或有效生成计时 | 不按文本长度、工具次数估算 Token |
| 16 份原生／前端／Agent 日志副本 | 共 286,352,333 字节；未发现检查的请求级 Token 和生成计时字段 | 日志中的 sandbox SSE 连接事件不能当模型生成事件 |
| 官方客户端单轮“消耗”明细 | 展示套餐消耗百分比和模型名，没有 Token 数 | 套餐额度百分比保持其原单位，不换算为 Token |
| 任务“共用时”明细 | 展示任务耗时及任务过程 | 未确认逐次模型生成区间，不能直接计算 tok/s |
| 已运行 Browser 的本机监听 | 没有 remote-debugging 启动参数；两个监听端口的标准 `/json/version` 探测分别连接重置、HTTP 404 | 未取得可供后台采集器使用的标准 CDP 入口；后续通过浏览器正常 DevTools Network 面板读到了真实查询响应，见下文 |

检查字段包括 `prompt_tokens`、`completion_tokens`、`input_tokens`、`output_tokens`、`total_tokens`、`token_usage`、`usage_metadata`、`input_token_count`、`output_token_count`、`first_packet_cost_time`、`decode_duration`、`generation_time`、`tokens_per_second` 和 `ttft`。字段匹配只是定位线索；即使命中，也需要核对生产者、单位、时间范围和调用身份。

## 精度要求

- 累计用量需要请求或消息的稳定身份、实际 Token 计数及对应时间，排除重复快照和重试记录。
- 纯生成速率需要同一次模型调用的输出 Token 与生成耗时；若只有请求总耗时，必须注明“含等待”。任务工具执行、排队、用户交互和暂停时间不能算进纯生成耗时。
- 上下文窗口占用描述当前上下文状态，不能直接累计成历史调用消耗。套餐额度百分比也无法直接转换为 Token。
- 缺少 Token 计数时，字符数、可见回复长度、额度比例以及任务总耗时均不足以补齐精确速率。隐藏推理、工具上下文和缓存还会进一步影响估算。

## 打包客户端协议的交叉核验

进一步解包核对了 2.34.4 的 `biz.pak`（8,441 个文本资源，解压后约 428 MB）和 `doubao_office.pak`（8,034 个文本资源，约 264 MB）。下列偏移为解压后 JS 的 0 起始字节偏移，不能直接用于压缩包文件定位：

| 包内资源 | 位置／字段 | 已确认含义 |
| --- | --- | --- |
| `static/js/async/s2-context-window-indicator.e824cebd2a.js` | 9465：`ext.context_window_usage`；10009：`system_prompt`；10266：`total_window_size` | 消费代码将 system_prompt、tools、messages、skills 相加，与窗口容量比较。对应 used_token／total_token 埋点描述上下文占用 |
| `static/js/async/21914.0115510397.js` | 53481：`ext.perf_mark`；18802：`perf_mark_samples`；18951：`query_send_timestamp` | 客户端处理 SSE 性能标记，增加发送／接收时刻；没有由此确认模型实际生成区间 |
| `static/js/async/s2-message-tea-trace.6c7049eac0.js` | 28451 | `receiveTimestamp - querySendTimestamp` 上报为 SSE 接收耗时，属于客户端观测的耗时 |
| `static/js/async/64850.4012811d1d.js` | 19359 | 渲染时刻减请求时刻，上报 render_duration，不能作为模型生成耗时 |

消息协议中还有可选 checkpoint 键 `default-chat-im-protocol-store`，其具体存储适配器由外部注入，默认可退化为无操作。本轮在当前 chat IndexedDB、Local Storage、shell KV 副本中继续检查 `perf_mark_samples`、`query_send_timestamp`、`perf_mark` 和该默认键，未发现可供采集器读取的已保存样本。其他适配器或版本的保存行为仍未知。

资源中存在 POST `/alice/message/list/v2` 历史消息封装，但未由其响应 schema 确认真正的 Token counters。本轮没有调用这一云端接口。资源中发现的 `usageCount`／`cumulativeUsageCount` 属于知识与生产力次数统计，也没有逐次模型 Token 的证据。

局部上下文资源还经过 REA 分析，证据标识为 `ev_1a7f698896f04f0420189d114b531018fff58740471ff74f867d6c4fd881d8f8`；孤立 webpack 模块的部分关系未解析，不能将静态分析视作真实请求响应的运行证明。

当前仍待取得并验证真实模型请求的 usage 和计时响应；本轮未获得这类完整响应，因此尚未实现 Token／速率采集。

## 已确认的查询接口

同日进一步从 2.34.4 打包客户端的 API 封装中核实了以下 POST 请求。这张表记录静态封装；实际登录会话的运行核验另列在下文，二者不能混用。

| 路径 | 封装参数 | 查询对象／限制 |
| --- | --- | --- |
| `/alice/commerce/sale/subscription/quota/summary/` | `product_line` | 会员额度窗口汇总；客户端消费 used_amount、total_amount、used_percent、end_time 等字段，不应预设所有账号窗口相同 |
| `/alice/commerce/sale/subscription/overview/` | `product_line` | 订阅权益总览；后续已读到 HTTP 200、code 0 的完整真实响应 |
| `/alice/commerce/sale/entitlement/usage_detail/` | 权益 `id` | 权益消耗明细；接口名称不能证明返回输入／输出 Token，计量单位待实测 |
| `/alice/commerce/usage/timeline/` | `category`、`cursor`、`page_size` | 官方额度消耗明细页实际使用的接口；后续已读取真实首批响应 |
| `/alice/message/list/v2` | `conversation_id`、`start_index`、`batch_size`、`is_reverse`、`end_index` | 历史消息；尚未确认响应含逐请求 Token 和模型生成计时 |

前三个接口的封装位于 `static/js/async/46597.a56f3638d6.js`，解压后字节偏移分别约 16928、12141、13382。`AGWGetUsageTimeline` 位于 `static/js/async/78691.db948bcf9d.js` 的 41358 附近，同文件 35417 附近也有订阅总览封装；消息接口位于 `static/js/async/25688.71b3ac371f.js` 的 25996 附近。其他 bundle 中有重复封装，不能因此重复计用量。

### 使用现有登录会话的真实响应核验

在官方 Doubao Work Browser 的普通标签页打开 `https://www.doubao.com/member/quota-management?platform=desktop&is_work=1&is_setting_iframe=1&locale=zh`，复用客户端现有登录状态。通过正常 DevTools Network 面板查看页面自己发出的查询，没有读取或导出 Cookie、修改远程调试设置或触发模型任务。

1. **订阅总览已查询成功。** `/alice/commerce/sale/subscription/overview/` 返回 HTTP 200、`code: 0`。完整响应中的 `data.window_limit_section.window_limit_groups[].window_limits[]` 含 `window_type`、`start_time`、`end_time`、`used_percent`、`less_than_one_percent`、`item_type`。本机账号的当前时段为未消耗，7 天窗口为已用 20%，与官方页面一致。时间戳单位为毫秒；该 7 天窗口的起止差为 604,800,000 毫秒。`entitlement_count` 是权益数量，不能计为请求数或 Token。
2. **逐任务消耗时间线已查询成功。** 从官方页面点击“额度消耗明细”，实际调用 `/alice/commerce/usage/timeline/`，首批请求体为 `{"category":6,"page_size":20}`。完整首批响应含 20 条 `usage` 和 1 条额度重置事件，`code: 0`、`has_more: true`；本次没有据此声称读完所有历史分页。
3. `usage` 的全部字段为 `display_name`、`item_id`、`model_display_name`、`occurred_at_ms`、`quota_source`。其中 `quota_source` 的全部字段为 `display_name`、`display_text`、`quota_source_code`；实测计量内容是 `display_text: "0.43%"` 这类百分比文案，响应列标题为“占 7 天额度”。`item_id` 标识消耗记录，尚未验证其与会话 ID、单次模型调用的对应关系。
4. 时间线顶层业务字段为 `categories`、`category_tabs`、`consumption_column_title`、`entries`、`has_more`、`next_cursor`、`window_end_time_ms`、`window_start_time_ms`。重置事件需要与消耗记录分开处理，分页需要使用返回的 cursor；不能把整页或重复快照再次累计。

本次两个真实响应均未包含输入／输出 Token、缓存 Token 或模型生成耗时。窗口百分比、任务百分比和发生时间不足以计算 Token 总量或 tok/s。这里的核验边界是当前版本、当前账号和上述实际响应，其他账号、分页或服务端模型调用协议仍需各自验证。原始响应包含任务标题与账号标识，不进入仓库或测试夹具。

官方页面可以查询，不代表采集器能直接后台复用其他应用的登录。已检查的扩展消息、原生请求和本机插件桥没有足够的外部调用证据；最小控制台请求验证遇到 DevTools 自身的粘贴安全警告后停止，没有绕过警告。Network 响应读取不受影响。

### 新增可选的网站会话接入

为避免依赖上述外部认证桥，新增 Tokei 自有的持久网站会话。默认关闭，用户主动点击“连接豆包账号查看额度”才显示官方登录页；登录状态由本应用 WebView 保留，关闭查询不会清除登录，后台失败不会自行弹窗。后续每 5 分钟加载官方额度页，只观察页面自己发出的订阅总览响应，不改变请求参数或导入其他应用的 Cookie。

共享的 `doubaowork-quota.js` 仅在 HTTPS 豆包主页面运行，从 `general` 额度组投影已验证的两个窗口；未知组、重复窗口、非法百分比、缺失计数均不生成读数。Mac 通过受来源限制的 WKScriptMessage 接收，Windows 通过携带一次性 nonce 的原生导航回调接收；远程网页不获通用本机命令权限。接收端仅保存版本、状态、读取时间、窗口类型、消耗百分比、起止时间和小于 1% 标志到 `~/.tokei/doubaowork_quota_cache.json`。

Python 采集器在 `doubaowork_quota_enabled: true` 时才读取这份有长度上限的投影缓存，附到 `doubaowork.quota`。卡片展示当前账号的当前时段／7 天剩余额度和重置时间，不随“今日／昨日”等会话统计范围重新累计；跨设备只合并会话，不替换本机账号额度。超过 30 分钟的读数标为待刷新，重置后不继续显示旧窗口的进度条；小于 1% 保留原始语义，不能展示成精确的 0%。

字段投影、来源过滤、缓存校验、旧数据兼容及页面展示分别验证。原有 Browser 会话下的真实接口查询已核实；本地更新后的 Tokei 已实际打开自有 WebView 的官方登录界面，页面包含豆包／飞书登录及用户协议确认，需要用户本人完成。登录后的真实额度读取与重启后登录保留仍待完成验证，不能由构建或合成夹具代替。Token 和生成速率继续保持缺失。

本次追加实现的验证：Python 会话／额度缓存 23 项、共享网页响应脚本 6 项、Swift 模型／同步／原生分享图回归、8 项本地化及 8 项弹窗位置回归通过；Mac release 构建和中英文卡片预览通过。Windows 前端构建、本地化和启动体积检查及 27 项前端测试通过；Rust `cargo check --offline --lib`、4 项额度回调／缓存测试在 macOS 运行通过，尚未在真实 Windows WebView2 中验证登录、回调、重启保留及文件权限。

火山方舟另有公开的 [`GetUsageDetails`](https://docs.volcengine.com/docs/ark/get-usage-details-api?lang=zh)，需要 Access Key 签名，返回个人 Agent Plan 按天／小时聚合的 Usage 与 Unit。Unit 可以为 Tokens 或 Images，但文档没有逐次生成耗时；是否覆盖当前豆包工作内置订阅的计费数据尚未证实，不能直接替换上述客户端数据源。

## 交叉参考

- [Token Monitor #586 的客户端实测记录](https://github.com/Javis603/token-monitor/issues/586)：另一项目报告了额度、上下文窗口与普通聊天 Token 的区别，以及正常启动的标准 CDP 接入限制。其结论仅作交叉参考，本轮本地核验结果见上表。
- [Token Monitor #524](https://github.com/Javis603/token-monitor/pull/524)：尝试通过已有 CDP 会话读取套餐额度；这类额度数据不能作为请求级 Token 或生成速率的证据。
- [火山方舟 Responses API 的 usage 字段](https://docs.volcengine.com/docs/ark/list-model-responses-api?lang=en)：这是 API 返回的用量结构，不能据此认定 Doubao Work 内置 Agent 已把同样字段持久化到本地。
