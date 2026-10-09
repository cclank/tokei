// 待移植：占位卡片，先不显示（active 恒为 false）。
import { Theme } from "../ui/theme";
import type { CardSpec } from "./spec";

export const qwenworkCard: CardSpec = {
  id: "qwenwork",
  name: "千问办公",
  visibleKey: "showQwenWork",
  visibleDefault: true,
  tint: Theme.qwenwork,
  active: () => false,
  render: () => null,
};
