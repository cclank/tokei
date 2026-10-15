# 本机总输出速率（macOS）

首页卡片区顶部显示「本机总输出」。它将本机所有已采集任务的新增输出相加，再除以实际经过的时间，观察窗口最多 60 秒。

例如两个任务各以 50 tok/s 并发输出 10 秒，总共产生 1,000 token，则本机总输出约为 100 tok/s。原有卡片上的「平均输出速度」仍是输出总数除以各请求耗时之和，同一例子为 50 tok/s，两者分别用于观察本机吞吐量和请求生成速度。

- 只使用成功完成的本机采集结果。启动时的磁盘缓存不参与采样；首个新结果仅建立基线，下一次采集完成后显示数值。
- 不足 60 秒时按实际观测时长计算，并显示「近 N 秒」；持续空闲后回到 0。超过 60 秒没有新采样显示「等待采样」。长时间睡眠、计数回退、时钟倒退或来源集合变化后重新建立基线。
- 不受「今天 / 本周」等时间范围、卡片显隐或「本机 / 全部设备」切换影响。不会将同步设备的历史补入本机速率。
- 包括本机采集的 25 种工具以及 Codex Luna Reserve。输出包含可获取的推理 token；Codex、OpenClaw、Muse Code 的输出已含推理，不重复相加。单独记录推理的来源只相加一次。
- 排除输入和缓存 token，以及 Cursor、Zed、Sub2API、z.ai、Grok Bot 等云端账号用量，避免把其他机器的活动算进本机。
- 数值是**日志采样估算**，不是对网络 token 流的逐秒测量。日志写入延迟、批量落盘和导入历史会影响观察值；跨窗口边界的采集区间按时间比例分摊。它不代表所选历史时间范围的平均吞吐量。
- 不新增网络请求、常驻日志扫描或持久化文件，沿用现有采集调度；界面可见时每秒更新窗口显示。

验证：

```bash
python3 -m unittest discover -s tests -p test_local_output_throughput.py
python3 -m unittest discover -s tests -p test_perf.py
python3 -m unittest discover -s tests -p test_localization.py
swift build --package-path Tokei -c release --product Tokei
```
