// 待移植：占位卡片，先不显示（active 恒为 false）。
import { Theme } from "../ui/theme";
import type { CardSpec } from "./spec";

export const cursorCard: CardSpec = {
  id: "cursor",
  name: "Cursor",
  visibleKey: "showCursor",
  visibleDefault: false,
  tint: Theme.cursor,
  active: () => false,
  render: () => null,
};

export const zedCard: CardSpec = {
  id: "zed",
  name: "Zed",
  visibleKey: "showZed",
  visibleDefault: false,
  tint: Theme.zed,
  active: () => false,
  render: () => null,
};

export const sub2apiCard: CardSpec = {
  id: "sub2api",
  name: "Sub2API",
  visibleKey: "showSub2API",
  visibleDefault: false,
  tint: Theme.sub2api,
  active: () => false,
  render: () => null,
};

export const zaiCard: CardSpec = {
  id: "zai",
  name: "z.ai / GLM",
  visibleKey: "showZai",
  visibleDefault: false,
  tint: Theme.zai,
  active: () => false,
  render: () => null,
};

export const devinCard: CardSpec = {
  id: "devin",
  name: "Devin",
  visibleKey: "showDevin",
  visibleDefault: true,
  tint: Theme.devin,
  active: () => false,
  render: () => null,
};

export const minimaxCard: CardSpec = {
  id: "minimax",
  name: "MiniMax Code",
  visibleKey: "showMiniMax",
  visibleDefault: true,
  tint: Theme.minimax,
  active: () => false,
  render: () => null,
};
