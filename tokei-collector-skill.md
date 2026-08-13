# Tokei Collector Skill

采集本机 AI 工具用量数据,同步到共享 Git 仓库,供 Tokei 面板聚合展示。

## 安装

告诉远程 Agent:

```
安装 tokei-collector skill,同步仓库: <your-repo-url>,设备名: <server-name>
```

Agent 执行以下命令即可:

```bash
curl -sL https://raw.githubusercontent.com/<user>/tokei-sync/main/install.sh | bash -s -- \
  --repo git@github.com:<user>/tokei-sync.git \
  --name <server-name>
```

## 工作原理

1. 克隆同步 Git 仓库到 `~/.tokei/sync/`
2. 每 30 分钟执行 `usage.30s.py --json` 采集本机所有 AI 工具用量
3. 写入 `~/.tokei/sync/<device-name>.json`
4. 仅提交本机 JSON，再通过 `git fetch + rebase + push` 重试同步，避免多设备并发分叉
5. 本地 Tokei 从同一仓库读取,自动聚合所有设备数据

## 支持的工具

自动采集以下工具的本地日志(有就采,没有跳过):

- Claude Code (`~/.claude/`)
- Codex (`~/.codex/`)
- Gemini CLI (`~/.gemini/`)
- Grok CLI (`~/.grok/`)
- Qoder / QoderWork
- Hermes (`~/.hermes/`)
- OpenClaw (`~/.openclaw/`)
- Pi Coding Agent CLI (`~/.pi/agent/sessions/`)
- OpenCode (`~/.local/share/opencode/`)
- Qwen Code (`~/.qwen/`)
- DeepSeek Harness (`${DSH_HOME:-~/.dsh}/sessions/`)
- Qoder CLI (`~/.qoder/cli/`)
- ZCode (`~/.zcode/cli/db/db.sqlite`)
- MiMoCode (自动发现本地 SQLite 数据库)

## 卸载

```bash
crontab -l | grep -v "tokei-sync.sh" | crontab -
rm -rf ~/.tokei/
```
