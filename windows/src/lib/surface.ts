import { call, inTauri } from "./collector";
import type { RangeKey } from "./types";

export const isQuickSurface = new URLSearchParams(window.location.search).get("surface") === "quick";
export type TrayClickAction = "quick" | "window";
export const TRAY_CLICK_KEY = "trayClickAction";

export function normalizeTrayClickAction(action: unknown): TrayClickAction {
  return action === "window" ? "window" : "quick";
}

export function openMainWindow(range: RangeKey) {
  if (inTauri) return call("open_main_window", { range });
  window.location.assign(`/?range=${encodeURIComponent(range)}`);
}

export function hideQuickPanel() {
  return call("hide_quick_panel");
}

export function openQuickPanel() {
  if (inTauri) return call("open_quick_panel");
  window.location.assign("/?surface=quick");
}
