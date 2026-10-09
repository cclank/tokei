// Rust 侧命令的前端封装（src-tauri/src/store.rs、lib.rs）。浏览器里单独调界面时都是空操作。
import { call, inTauri } from "./collector";

/** 读 `~/.tokei/<name>`；不存在返回 null。只允许单层文件名。 */
export async function readTokeiFile(name: string): Promise<string | null> {
  return (await call<string | null>("read_tokei_file", { name })) ?? null;
}

export async function writeTokeiFile(name: string, content: string): Promise<void> {
  await call("write_tokei_file", { name, content });
}

/** 采集脚本读的 `~/.tokei/config.json`。 */
export async function readTokeiConfig(): Promise<Record<string, unknown>> {
  return (await call<Record<string, unknown>>("read_tokei_config")) ?? {};
}

/** 按键合并写入 config.json：值为 null 的键删除，没提到的键保留。 */
export async function updateTokeiConfig(patch: Record<string, unknown>): Promise<Record<string, unknown>> {
  return (await call<Record<string, unknown>>("update_tokei_config", { patch })) ?? {};
}

export type SecretProvider = "sub2api" | "zai" | "minimax";

/** 只回答有没有存 Key，不把 Key 本身交给前端。 */
export async function hasSecret(provider: SecretProvider): Promise<boolean> {
  return Boolean(await call<boolean>("has_secret", { provider }));
}

export async function setSecret(provider: SecretProvider, value: string): Promise<void> {
  await call("set_secret", { provider, value });
}

export async function deleteSecret(provider: SecretProvider): Promise<void> {
  await call("delete_secret", { provider });
}

export async function autostartEnabled(): Promise<boolean> {
  if (!inTauri) return false;
  const { isEnabled } = await import("@tauri-apps/plugin-autostart");
  return isEnabled();
}

export async function setAutostart(on: boolean): Promise<void> {
  if (!inTauri) return;
  const { enable, disable } = await import("@tauri-apps/plugin-autostart");
  await (on ? enable() : disable());
}

export async function openExternal(url: string): Promise<void> {
  if (!inTauri) {
    window.open(url, "_blank");
    return;
  }
  const { openUrl } = await import("@tauri-apps/plugin-opener");
  await openUrl(url);
}
