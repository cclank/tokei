import { call, inTauri } from "./collector";
import type { RangeKey } from "./types";

export const DOUBAO_QUOTA_PREF = "doubaoWorkQuotaEnabled";
export const DOUBAO_QUOTA_CONFIG = "doubaowork_quota_enabled";
export interface DoubaoQuotaConnection {
  enabled: boolean;
  status: "connected" | "login_required" | "unavailable" | "refreshing";
}

export async function doubaoQuotaConnection(): Promise<DoubaoQuotaConnection> {
  return (await call<DoubaoQuotaConnection>("doubaowork_quota_state")) ?? { enabled: false, status: "unavailable" };
}

async function action(command: string, args?: Record<string, unknown>): Promise<DoubaoQuotaConnection> {
  if (!inTauri) throw new Error("Doubao account connection requires the Windows app");
  const state = await call<DoubaoQuotaConnection>(command, args);
  if (!state) throw new Error("Doubao account window unavailable");
  return state;
}

export const setDoubaoQuotaEnabled = (enabled: boolean) => action("set_doubaowork_quota_enabled", { enabled });
export const connectDoubaoQuota = () => action("connect_doubaowork_quota");
export const refreshDoubaoQuota = () => action("refresh_doubaowork_quota");

/** Quick cards ask the local main panel to connect; backend commands stay main-only. */
export async function requestDoubaoQuotaConnection(range: RangeKey): Promise<DoubaoQuotaConnection | undefined> {
  if (!inTauri) throw new Error("Doubao account connection requires the Windows app");
  const { isQuickSurface, openMainWindow } = await import("./surface");
  if (!isQuickSurface) return connectDoubaoQuota();
  await openMainWindow(range);
  const { emitTo } = await import("@tauri-apps/api/event");
  await emitTo("panel", "tokei://connect-doubaowork-quota");
  return undefined;
}
