# Codex 重置卡 PR 截图

离屏渲染（与 `Tokei --shot` 一致），不依赖真实 Codex 登录态。

```bash
cd Tokei && TOKEI_ARCHS=arm64 TOKEI_LOCAL_BUILD=1 ./package.sh
./Tokei.app/Contents/MacOS/Tokei \
  --usage ../docs/pr-codex-reset/usage-reset-cards.json \
  --shot ../docs/pr-codex-reset/codex-reset-collapsed.png
./Tokei.app/Contents/MacOS/Tokei \
  --usage ../docs/pr-codex-reset/usage-reset-cards.json \
  --expand-codex-reset-cards \
  --shot ../docs/pr-codex-reset/codex-reset-expanded.png
```

`usage-reset-cards.json` 里的 `expires` 为生成时的相对时间戳；重跑截图前可重新执行仓库根目录下的 fixture 生成脚本（见 PR 说明）或手改 epoch。
