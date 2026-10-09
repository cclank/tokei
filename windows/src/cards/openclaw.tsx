// 待移植：占位卡片，先不显示（active 恒为 false）。
import { Theme } from "../ui/theme";
import type { CardSpec } from "./spec";

export const openclawCard: CardSpec = {
  id: "openclaw",
  name: "OpenClaw",
  visibleKey: "showOpenClaw",
  visibleDefault: true,
  tint: Theme.openclaw,
  active: () => false,
  render: () => null,
};
