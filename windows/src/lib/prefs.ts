// 界面偏好（Mac 版的 @AppStorage）：存在 WebView 的 localStorage 里，键名与 Mac 版一致，
// 改动广播给所有订阅者，React 组件用 usePref 读写。
import { useCallback, useSyncExternalStore } from "react";

type Listener = () => void;
const listeners = new Set<Listener>();
let version = 0;

function read(key: string): unknown {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? undefined : JSON.parse(raw);
  } catch {
    return undefined;
  }
}

export function getPref<T>(key: string, fallback: T): T {
  const value = read(key);
  return value === undefined ? fallback : (value as T);
}

export function setPref<T>(key: string, value: T) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // 存不下就只在本次会话生效
  }
  version++;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** 任一偏好变化都会让订阅的组件重渲染（换语言、字号时整块界面都要重算）。 */
export function usePrefsVersion(): number {
  return useSyncExternalStore(subscribe, () => version);
}

export function usePref<T>(key: string, fallback: T): [T, (value: T) => void] {
  usePrefsVersion();
  const value = getPref(key, fallback);
  const update = useCallback((next: T) => setPref(key, next), [key]);
  return [value, update];
}

// 其他窗口（例如将来的独立设置窗口）改了偏好，也同步过来。
window.addEventListener("storage", () => {
  version++;
  listeners.forEach((listener) => listener());
});
