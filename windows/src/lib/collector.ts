// 调采集脚本。Tauri 里走 Rust 命令 run_collector；单独用浏览器开 vite 调界面时，
// 走 vite.config.ts 里的开发中间件（同样是跑一遍 usage.30s.py）。
import { invoke } from "@tauri-apps/api/core";

export const inTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export async function runCollector(args: string[]): Promise<string> {
  if (inTauri) return invoke<string>("run_collector", { args });
  const response = await fetch(`/__tokei/collect?${new URLSearchParams(args.map((a) => ["arg", a]))}`);
  if (!response.ok) throw new Error(await response.text());
  return response.text();
}

export async function collectJSON<T>(args: string[]): Promise<T> {
  return JSON.parse(await runCollector(args)) as T;
}

/** Rust 侧的其他命令；浏览器调试时没有，就什么都不做。 */
export async function call<T>(command: string, args?: Record<string, unknown>): Promise<T | undefined> {
  if (!inTauri) return undefined;
  return invoke<T>(command, args);
}
