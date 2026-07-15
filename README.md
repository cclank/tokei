<p align="center">
  <img src="https://img.shields.io/badge/platform-macOS_13+-black?style=flat-square&logo=apple&logoColor=white" alt="macOS 13+">
  <img src="https://img.shields.io/badge/swift-5.9+-F05138?style=flat-square&logo=swift&logoColor=white" alt="Swift 5.9+">
  <img src="https://img.shields.io/badge/python-3.8+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="MIT License">
  <a href="https://github.com/cclank/tokei/stargazers"><img src="https://img.shields.io/github/stars/cclank/tokei?style=flat-square&color=yellow" alt="Stars"></a>
  <a href="https://github.com/cclank/tokei/releases"><img src="https://img.shields.io/github/v/release/cclank/tokei?style=flat-square&color=blue" alt="Release"></a>
</p>

<h1 align="center">⏱ Tokei 知度</h1>

<p align="center">
  <strong>macOS 菜单栏 AI 编程用量监控</strong><br>
  <sub>了然于心，掌控全局。</sub><br><br>
  <a href="https://tokei.lanshuagent.com">🌐 官网</a> · <a href="https://github.com/cclank/tokei/releases/latest">⬇️ 下载</a> · <a href="#english">English</a>
</p>

---

## 什么是 Tokei？

Tokei 是一款 **macOS 菜单栏应用**，实时追踪你在 **12 款 AI 编程工具** 上的用量、成本和性能——全部基于本地日志，零网络流量。

### 支持的工具

| 工具 | 追踪指标 |
|------|----------|
| **Claude Code** | Token（输入/输出/缓存）、成本、配额、模型 |
| **Codex CLI** | Token、成本、配额、会话 |
| **Gemini CLI** | Token、思考量、成本、模型 |
| **Grok CLI** | Token、会话、上下文 |
| **Hermes** | Token、成本、缓存命中率、模型 |
| **OpenClaw** | Token、成本、任务、模型 |
| **Pi Coding Agent CLI** | Token、成本、缓存命中率、模型、项目 |
| **WorkBuddy** | Token、成本、缓存命中率、模型、项目 |
| **OpenCode** | Token、成本、缓存命中率、模型 |
| **Qwen Code** | Token、思考量、成本、模型 |
| **Qoder** | Token、调用次数、配额 |
| **QoderWork** | Token、调用次数、配额 |

## 功能一览

### 实时监控
- 30 秒自动刷新，菜单栏直接显示配额/用量
- 菜单栏支持品牌、单色、刻度、圆点、数字、星轨 6 种样式
- 双额度、单额度、仅图标 3 档信息量，最窄只占一个状态栏槽位
- 按工具展示卡片，一眼掌握所有 AI 工具状态

### 成本估算
- 基于 API 实际定价估算成本（非订阅费用）
- 317 个模型价格表（来源 OpenRouter），支持一键更新
- 本地价格覆盖（`pricing_overrides.json`），更新不丢失
- 未知模型按家族关键词回退，兜底用 Opus 价格（保守上限）

### 数据面板
- 每日成本折线图
- 每周热力图
- 工具用量占比分析

### 时间维度
- 今天 / 昨天 / 本周 / 上周 / 本月 / 今年
- 随时切换，对比不同时段用量趋势

### 项目追踪
- 按项目维度查看 Claude Code / Pi / WorkBuddy / Grok 用量
- 了解每个项目消耗了多少 Token 和成本

### 多设备同步
- 基于 Git 的跨设备同步（Mac + Linux 服务器）
- Mac 端设置里一键开启
- 远程 Linux 服务器支持 crontab 自动采集和同步
- 也可以让 Claude Code 帮你自动完成全部配置

### 年度回顾（Wrapped）
- 回顾你一整年的 AI 编程旅程
- 总用量、总成本、高峰日、工具偏好等统计

### 久坐提醒
- 感知空闲状态，智能提醒休息
- 可自定义间隔时间

### 隐私优先
- 仅读取本地日志文件，从不联网上报
- 唯一的网络操作：手动执行 `--update-prices` 更新价格表

## 快速开始

1. 从 [GitHub Releases](https://github.com/cclank/tokei/releases/latest) 下载最新 DMG
2. 打开 DMG，将 Tokei.app 拖入 Applications 文件夹
3. 首次打开如被 macOS 拦截，在终端运行：`sudo xattr -rd com.apple.quarantine /Applications/Tokei.app`
4. 打开 Tokei 即可

<details>
<summary>从源码构建</summary>

```bash
git clone https://github.com/cclank/tokei.git
cd tokei/Tokei
bash package.sh
open Tokei.app
```
</details>

## 多设备同步配置

Tokei 支持通过私有 Git 仓库在多台机器间同步用量数据。

**Mac 端：** 打开设置 → 多设备同步 → 开启，选择一个 Git 仓库目录。

**远程 Linux 服务器：**

```bash
git clone <你的私有仓库> ~/.tokei/sync
curl -fsSL https://dl.lanshuagent.com/tokei/usage.30s.py -o ~/.tokei/usage.30s.py
echo '{"sync_dir":"~/.tokei/sync","device_id":"'$(hostname -s)'"}' > ~/.tokei/config.json
# 每 5 分钟自动采集并同步
(crontab -l 2>/dev/null; echo '*/5 * * * * cd ~/.tokei/sync && python3 ~/.tokei/usage.30s.py --json >/dev/null && git pull -q && git add -A && git diff --cached --quiet || git commit -qm sync && git push -q') | crontab -
```

## 数据来源

所有数据均来自 **本地日志文件**，无网络请求。

| 工具 | 日志路径 |
|------|----------|
| Claude Code | `~/.claude/projects/<proj>/<session>.jsonl` |
| Codex CLI | `~/.codex/sessions/YYYY/MM/DD/*.jsonl` |
| Gemini CLI | `~/.gemini/gemini-cli/conversations/*.json` |
| Grok CLI | `~/.grok/sessions/YYYY/MM/DD/*.jsonl` |
| Hermes | `~/.hermes/state.db` + `~/.hermes/profiles/*/state.db` |
| OpenClaw | `~/.openclaw/agents/*/sessions/*.jsonl` + `~/.openclaw/state/openclaw.sqlite` |
| Pi Coding Agent CLI | `~/.pi/agent/sessions/<project>/*.jsonl` |
| WorkBuddy | `~/.workbuddy/projects/<project>/*.jsonl` |
| OpenCode | `~/.opencode/sessions/*.json` |
| Qwen Code | `~/.qwen/usage/token-usage-*.jsonl` + `~/.qwen/usage_record.jsonl` |
| Qoder | `~/.qodo-ai/sessions/*.jsonl` |
| QoderWork | `~/Library/Application Support/Qoder/SharedClientCache/cache/db/local.db` |

## 对比 CodexBar

| 功能 | Tokei | [CodexBar](https://github.com/steipete/CodexBar) |
|------|:-----:|:---------:|
| 支持工具 | 12 | 40+ |
| Token 级用量分析 | ✅ | — |
| 成本估算（317 模型） | ✅ | 部分 |
| 数据面板（图表 + 热力图） | ✅ | — |
| 多时间维度 | 6 个 | — |
| 项目级追踪 | ✅ | — |
| 多设备同步 | ✅ | — |
| 年度回顾 | ✅ | — |
| 防休眠 / 久坐提醒 | ✅ | — |
| 需要联网 | 否 | 是 |
| 需要登录 | 否 | 是 |
| 数据来源 | 本地日志 | 远程 API |

> CodexBar 在提供商覆盖和配额可见性上表现出色。Tokei 更深入——Token 级分析、成本趋势、项目维度拆分、跨设备同步——全部无需登录。

## 更新日志

### v1.0.13
- feat: WorkBuddy 本地 JSONL 用量采集（Token、缓存、模型、成本、项目）
- feat: WorkBuddy 数据接入卡片、Dashboard、回顾、项目足迹和多设备同步
- feat: 各工具 token 按小时追踪（hours/day_hours），扩展作息分析维度
- feat: 菜单栏新增 6 种可即时切换并持久保存的图标样式（含自绘星轨）
- feat: 菜单栏新增双额度、单额度和仅图标模式，兼顾信息量与占用宽度
- feat: 自绘 Tokei 菜单栏标记和额度刻度环，移除重复时钟与通用符号
- fix: WorkBuddy 推理 Token 保持包含在输出中，避免总量重复累计
- fix: 恢复合并中误删的 _recalc_costs（本地价格表重算，防 GLM 等价格回退）

### v1.0.12
- feat: 开机自启动（设置页「登录时启动」开关）
- fix: Codex token 快照去重，避免重复累计
- fix: 同步配置只更新同步字段，保留 qoder_ide_enabled 等其他配置
- fix: 启动时落盘 Qoder IDE 开关状态

### v1.0.11
- fix: Codex 跨 rollout 去重，避免子代理和分叉任务重复累计父任务 Token

### v1.0.10
- fix: Codex 实时配额抓取（plan / 周配额 / 重置时间）
- fix: Codex 按时长检测配额窗口，跳过重复 token 快照
- fix: 多设备同步稳定性

### v1.0.9
- fix: 多设备同步按日期边界对齐，修正跨设备采集时差导致的 range 串台

### v1.0.8
- feat: 点击模型行展开详情（输入/输出/缓存读写/命中率/单价）
- feat: 回顾新增「Loop Engineering !!」「Loop滴神」成就（连续 24/7 活跃）
- fix: GLM 5.2 价格映射修复（不再按 Opus 价计算）
- fix: 同步数据成本自动修正（本地价格表重算对端模型成本）

### v1.0.7
- feat: Qoder 拆分为 CLI 和 IDE 两张独立卡片
- feat: Qoder IDE 数据采集（支持 VS Code / JetBrains 插件用量）
- fix: Qoder 分拆后数据模型和同步适配

### v1.0.6
- perf: 脚本性能优化 10 倍（6.5s→0.6s），CPU 占用从 ~22% 降至 ~1%
- fix: 首次加载失败自动重试 3 次，不再直接显示错误
- fix: Python 路径探测，解决 GUI 应用 PATH 缺失问题

### v1.0.5
- fix: 彻底消除外部 zstd 二进制依赖，根治 Gatekeeper 拦截问题
- fix: Swift 内置 CZstd 解压修复（帧边界精确定位）
- feat: 设置关闭工具卡片后菜单栏同步隐藏对应额度
- feat: 设置页手动检查更新按钮
- fix: 移除过时的 zstd 安装提示

### v1.0.4
- feat: 回顾支持时间周期筛选（今日/本周/本月/今年/全部），模型用量联动
- feat: 新增「永动机」成就（24h 全时段活跃）
- fix: 成就命名优化（俱乐部→先生）
- fix: Claude 额度条缺失时显示 zstd 安装提示

### v1.0.3
- feat: 主页顶部动态升级按钮，有新版本自动显示，一键升级
- feat: 24 小时自动检查更新
- feat: 品牌升级「時計」→「知度」(Token + Insight = Tokei)
- fix: Claude Desktop 配额条不显示（zstd 路径发现 + 二进制打包）
- fix: 下载超时保护（5 分钟）+ 失败自动恢复

### v1.0.2
- feat: 久坐提醒语音播报
- feat: 按模型显示 token 总量 + 缓存命中率
- feat: Hermes 多 profile 支持（`~/.hermes/profiles/*/state.db`）
- feat: 设置页 GitHub 链接按钮
- fix: 菜单栏无配额时兜底显示今日总 token 或品牌图标
- fix: 3 处文件句柄泄漏（Claude/Gemini/Pi 扫描）
- fix: Hermes「上周」数据缺失
- fix: OpenCode 成本纳入每日汇总

### v1.0.1
- fix: Claude Code 按 message ID 去重，修复重复计数问题
- fix: Claude Code 扫描 subagent/workflow 日志（之前遗漏）
- fix: Codex 额度过期后自动归零，解决刷新不及时问题
- feat: 设置页增加「检查更新」按钮 + "已是最新"反馈
- fix: 应用内自动更新支持

## Star History

<p align="center">
  <a href="https://star-history.com/#cclank/tokei&Date">
    <img src="https://api.star-history.com/svg?repos=cclank/tokei&type=Date" width="600" alt="Star History Chart">
  </a>
</p>

---

<a id="english"></a>

## English

Tokei is a **macOS menu bar app** that tracks usage, cost, and performance across **12 AI coding tools** in real-time — all from local log files, with zero network traffic.

**Features:** Real-time monitoring (30s refresh, five menu bar styles, three density modes) · Cost estimation (317 models, OpenRouter pricing) · Dashboard (daily chart, weekly heatmap) · Time ranges (today/week/month/year) · Project-level tracking · Multi-device sync (Git-based, Mac + Linux) · Annual Wrapped · Keep awake · Sit reminder · Privacy-first (local logs only) · [Compare with CodexBar](https://tokei.lanshuagent.com#compare)

**Supported tools:** Claude Code, Codex CLI, Gemini CLI, Grok CLI, Hermes, OpenClaw, Pi Coding Agent CLI, WorkBuddy, OpenCode, Qwen Code, Qoder, QoderWork

For full documentation, visit [tokei.lanshuagent.com](https://tokei.lanshuagent.com).

## License

MIT
