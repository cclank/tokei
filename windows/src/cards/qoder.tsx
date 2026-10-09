// 待移植：占位卡片，先不显示（active 恒为 false）。
import { Theme } from "../ui/theme";
import type { CardSpec } from "./spec";

export const qoderIdeCard: CardSpec = {
  id: "qoder",
  name: "Qoder Desktop",
  visibleKey: "showQoderIde",
  visibleDefault: true,
  tint: Theme.qoder,
  active: () => false,
  render: () => null,
};

export const qoderworkCard: CardSpec = {
  id: "qoderwork",
  name: "QoderWork",
  visibleKey: "showQoderWork",
  visibleDefault: true,
  tint: Theme.qoderwork,
  active: () => false,
  render: () => null,
};

export const qodercliCard: CardSpec = {
  id: "qodercli",
  name: "Qoder CLI",
  visibleKey: "showQoderCli",
  visibleDefault: true,
  tint: Theme.qodercli,
  active: () => false,
  render: () => null,
};

export const qodercliCNCard: CardSpec = {
  id: "qodercli_cn",
  name: "Qoder CN",
  visibleKey: "showQoderCliCN",
  visibleDefault: true,
  tint: Theme.qodercliCN,
  active: () => false,
  render: () => null,
};
