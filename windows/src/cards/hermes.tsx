// 待移植：占位卡片，先不显示（active 恒为 false）。
import { Theme } from "../ui/theme";
import type { CardSpec } from "./spec";

export const hermesCard: CardSpec = {
  id: "hermes",
  name: "Hermes",
  visibleKey: "showHermes",
  visibleDefault: true,
  tint: Theme.hermes,
  active: () => false,
  render: () => null,
};
