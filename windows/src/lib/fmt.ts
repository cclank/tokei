// 数字与时间的显示格式，逐条对应 Mac 版 Model.swift 的 Fmt 与 nativeMoney。
import { currentLanguage, isChinese, L } from "./i18n";

const pad = (n: number) => String(n).padStart(2, "0");

export function human(n: number): string {
  const v = Number(n) || 0;
  // 中文按「亿」进位；其他语言用国际通行的 B（十亿）。
  if (isChinese()) {
    if (v >= 100_000_000) return `${(v / 100_000_000).toFixed(1)}亿`;
  } else if (v >= 1_000_000_000) {
    return `${(v / 1_000_000_000).toFixed(1)}B`;
  }
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
  return v.toFixed(0);
}

/** 千分位精确写法，分隔符固定为逗号。 */
export function grouped(n: number): string {
  return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

export function credits(n: number): string {
  if (Math.abs(Math.round(n) - n) < 0.000_001) return n.toFixed(0);
  return n.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

function date(epoch: number) {
  return new Date(epoch * 1000);
}

/** MM-dd HH:mm（本地时区）。 */
export function reset(epoch?: number | null): string {
  if (epoch == null) return "?";
  const d = date(epoch);
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function day(epoch?: number | null): string {
  if (epoch == null) return "?";
  const d = date(epoch);
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export const localTime = (epoch: number) => reset(epoch);

/** 重置卡到期列表上的时区说明，如「本地 · GMT+8」。 */
export function localTimeZoneCaption(): string {
  let name = "";
  try {
    const parts = new Intl.DateTimeFormat(currentLanguage(), { timeZoneName: "short" }).formatToParts(new Date());
    name = parts.find((p) => p.type === "timeZoneName")?.value ?? "";
  } catch {
    name = "";
  }
  if (!name) {
    const offset = -new Date().getTimezoneOffset() / 60;
    name = `GMT${offset >= 0 ? "+" : ""}${offset}`;
  }
  return L("本地 · %@", name);
}

/** 离到期还有多久：两天以上按天（16d6h），两天以内 3h20m，过了是「已到期」。 */
export function remaining(epoch: number, now = Date.now()): string {
  const seconds = Math.floor(epoch - now / 1000);
  if (seconds <= 0) return L("已到期");
  if (seconds >= 2 * 86400) return `${Math.floor(seconds / 86400)}d${Math.floor((seconds % 86400) / 3600)}h`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h${m}m` : `${Math.max(m, 1)}m`;
}

export function countdown(epoch?: number | null): string {
  if (epoch == null) return "?";
  const s = epoch - Date.now() / 1000;
  if (s <= 0) return L("即将重置");
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}h${m}m` : `${m}m`;
}

/** 输出速度：两位数以上取整（98 tok/s），以下留一位小数（6.2 tok/s）。 */
export function tps(value: number): string {
  return value >= 10 ? `${value.toFixed(0)} tok/s` : `${value.toFixed(1)} tok/s`;
}

/** 首字延迟这类秒级时长：1.4s、12s。 */
export function seconds(value: number): string {
  return value >= 10 ? `${value.toFixed(0)}s` : `${value.toFixed(1)}s`;
}

export function duration(ms: number): string {
  const s = Math.floor(ms / 1000);
  if (s >= 3600) return `${Math.floor(s / 3600)}h${Math.floor((s % 3600) / 60)}m`;
  if (s >= 60) return `${Math.floor(s / 60)}m${s % 60}s`;
  return `${s}s`;
}

/** 等价于 Swift 的 %g：去掉多余的 0。 */
export function price(x: number): string {
  return String(Number(x.toPrecision(6)));
}

/** %.2g：单价徽标用（4/20、0.1/0.5）。 */
export function g2(x: number): string {
  if (x === 0) return "0";
  return String(Number(x.toPrecision(2)));
}

export function weekdayLabels(): string[] {
  if (isChinese()) return ["一", "二", "三", "四", "五", "六", "日"];
  try {
    const formatter = new Intl.DateTimeFormat(currentLanguage(), { weekday: "short" });
    // 2024-01-01 是周一
    return Array.from({ length: 7 }, (_, i) => formatter.format(new Date(2024, 0, 1 + i)));
  } catch {
    return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  }
}

export function relativeDate(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return iso;
  const then = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = Math.round((today.getTime() - then.getTime()) / 86_400_000);
  if (days === 0) return L("今天");
  if (days === 1) return L("昨天");
  if (days <= 7) return L("%@天前", days);
  if (days <= 30) return L("%@周前", Math.floor(days / 7));
  return L("%@月前", Math.floor(days / 30));
}

/** 原币种显示，不换汇不混加；不到 1 分写「<$0.01」。 */
export function nativeMoney(usd: number, cny?: number | null): string {
  const amount = (symbol: string, value: number) =>
    value > 0 && value < 0.005 ? `<${symbol}0.01` : `${symbol}${value.toFixed(2)}`;
  const parts: string[] = [];
  if (usd > 0 || (cny ?? 0) <= 0) parts.push(amount("$", usd));
  if (cny && cny > 0) parts.push(amount("¥", cny));
  return parts.join(" + ");
}

export const dollars = (value: number) => `$${(Number(value) || 0).toFixed(2)}`;

export const percent0 = (value: number) => `${Math.round(value)}%`;
