# Codex 额外重置动态

macOS 版默认开启，可在「设置 → 隐私与额度 → Codex 额外重置动态」关闭；已保存的关闭选择会保留。
开启后，Codex 卡片底部展示 [AIHOT 的 Tibo 重置监控](https://aihot.news/codex-reset)。
即使当前时间范围没有本机用量，启用的公告区也可见。

## 时间和状态

这项功能跟踪公开宣布的额外额度重置与重置卡发放，独立于个人 5 小时 / 周额度。
预计时间由 AIHOT 整理，Tokei 不根据历史间隔推算尚未公布的下一次事件。

| 来源状态 / 时间 | 显示 |
| --- | --- |
| 无待生效公告 | 最近记录；下一次尚未公布 |
| 已宣布、无时间 | 具体时间待定 |
| 预计时段未开始 | 本地时区的起止时间、距预计开始的倒计时 |
| 处于预计时段 | 等待确认 |
| 预计结束时间已过 | 已过预计时间，等待确认 |
| 正在进行 | 等待完成确认 |
| 来源认为应已生效 | 明确标注尚未确认 |
| 来源确认完成 | 已确认；确认帖时间不等于精确到账时间 |

发放重置卡不等于额度已恢复；卡片是否到账、何时使用以及个人额度以 Codex 显示为准。
Tokei 不会代用户兑换重置卡。AIHOT 是第三方来源，界面保留其页面与公开原帖链接。

## 请求和缓存

- 启用且显示 Codex 卡片时，约每 10 分钟 GET `https://aihot.news/api/site/codex-reset`。
- 使用临时 URLSession，无 Cookie、凭据存储、Authorization 请求头或用量上传；关闭开关取消进行中的请求。
- 使用响应中的 `schemaVersion: 1`、`current`、`lastLanded`、`monitor` 和 ISO 8601 时间戳，不解析公告正文来猜测时间。
- 缓存：`~/.tokei/codex_reset_announcements.json`，独立于个人额度与 Git 同步快照。
- 失败后从 1 分钟开始自动重试，连续失败按 2、4、8 分钟退避，最多 10 分钟；成功后恢复每 10 分钟刷新。有缓存时也可手动重试（最短间隔 30 秒），并显示网络错误码 / HTTP 状态或数据异常原因。
- 网络或解析失败保留上次记录；来源检查 / 本地缓存超过 30 分钟、来源报告异常或时钟明显偏移时显示延迟提示并停止实时倒计时。
- 时间流逝不会把未确认事件自动标为已确认，未知状态不会被推断为重置完成。

## 验证

在 macOS 上运行：

```bash
python3 -m unittest discover -s tests -p test_codex_reset_announcements.py
python3 -m unittest discover -s tests -p test_localization.py
swift build --package-path Tokei -c release --product Tokei
```

测试使用本地 URLProtocol 模拟请求，覆盖时间窗、时区、确认优先级、发卡、空态、无效数据、过期缓存、断网恢复、刷新节流、禁用和取消，不依赖外网。

离屏预览可以注入公开接口格式的 JSON；不会改偏好设置、缓存或访问网络：

```bash
Tokei --shot /tmp/reset-preview.png --usage /path/to/usage-fixture.json --reset-feed /path/to/reset-feed.json --lang zh
```
