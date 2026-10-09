// 界面语言，与 Mac 版 L10n.swift 同一套规则：
// 中文是源语言，代码里写的中文原文就是 key；其他语言查 Tokei/Localization/<lang>.lproj 的词表
// （直接读 Mac 版那份，不另存一份）。法、日、韩缺词先回退英文，再回退中文原文。
import enStrings from "../../../Tokei/Localization/en.lproj/Localizable.strings?raw";
import frStrings from "../../../Tokei/Localization/fr.lproj/Localizable.strings?raw";
import jaStrings from "../../../Tokei/Localization/ja.lproj/Localizable.strings?raw";
import koStrings from "../../../Tokei/Localization/ko.lproj/Localizable.strings?raw";
import { getPref, setPref } from "./prefs";

export type Lang = "zh" | "en" | "fr" | "ja" | "ko";
export type LangSetting = "system" | Lang;

export const LANGUAGE_KEY = "appLanguage";

/** 解析 .strings：`"键" = "值";`，支持 \" \\ \n 转义与注释。 */
export function parseStrings(source: string): Record<string, string> {
  const table: Record<string, string> = {};
  let i = 0;
  const n = source.length;
  const readString = (): string | null => {
    if (source[i] !== '"') return null;
    i++;
    let out = "";
    while (i < n && source[i] !== '"') {
      if (source[i] === "\\" && i + 1 < n) {
        const next = source[i + 1];
        out += next === "n" ? "\n" : next === "t" ? "\t" : next;
        i += 2;
      } else {
        out += source[i++];
      }
    }
    i++;
    return out;
  };
  const skip = () => {
    for (;;) {
      while (i < n && /\s/.test(source[i])) i++;
      if (source.startsWith("/*", i)) {
        const end = source.indexOf("*/", i + 2);
        i = end < 0 ? n : end + 2;
      } else if (source.startsWith("//", i)) {
        const end = source.indexOf("\n", i);
        i = end < 0 ? n : end + 1;
      } else return;
    }
  };
  while (i < n) {
    skip();
    const key = readString();
    if (key === null) {
      i++;
      continue;
    }
    skip();
    if (source[i] !== "=") continue;
    i++;
    skip();
    const value = readString();
    if (value !== null) table[key] = value;
    skip();
    if (source[i] === ";") i++;
  }
  return table;
}

const tables: Record<Exclude<Lang, "zh">, Record<string, string>> = {
  en: parseStrings(enStrings),
  fr: parseStrings(frStrings),
  ja: parseStrings(jaStrings),
  ko: parseStrings(koStrings),
};

/** 跟随系统时取浏览器 / WebView 的首选语言，不支持的回退英文。 */
function resolveSystem(): Lang {
  const preferred = (navigator.languages?.[0] ?? navigator.language ?? "en").toLowerCase();
  for (const lang of ["zh", "fr", "ja", "ko"] as const) {
    if (preferred.startsWith(lang)) return lang;
  }
  return "en";
}

/** 用户没选过时：系统语言列表里只要有中文就用中文（与 Mac 版一致）。 */
export function selectedLanguage(): LangSetting {
  const raw = getPref<string | null>(LANGUAGE_KEY, null);
  if (raw && ["system", "zh", "en", "fr", "ja", "ko"].includes(raw)) return raw as LangSetting;
  const all = (navigator.languages ?? [navigator.language]).map((l) => l.toLowerCase());
  return all.some((l) => l.startsWith("zh")) ? "zh" : "system";
}

export function currentLanguage(): Lang {
  const selected = selectedLanguage();
  return selected === "system" ? resolveSystem() : selected;
}

export function setLanguage(value: LangSetting) {
  setPref(LANGUAGE_KEY, value);
}

export function isChinese(): boolean {
  return currentLanguage() === "zh";
}

function lookup(key: string): string {
  const lang = currentLanguage();
  if (lang === "zh") return key;
  const own = tables[lang][key];
  if (own !== undefined) return own;
  if (lang !== "en" && tables.en[key] !== undefined) return tables.en[key];
  return key;
}

/** `%@` 按顺序、`%1$@` 按位置取参数，`%%` 是百分号本身。 */
export function format(template: string, args: unknown[]): string {
  const values = args.map((value) => String(value));
  let next = 0;
  return template.replace(/%(%|@|(\d+)\$@)/g, (_match, token: string, position?: string) => {
    if (token === "%") return "%";
    if (token === "@") return values[next++] ?? "";
    const index = Number(position) - 1;
    return values[index] ?? "";
  });
}

/** 界面文案：L("防休眠")、L("额度来源 %@ · %@", source, updated)。 */
export function L(key: string, ...args: unknown[]): string {
  const value = lookup(key);
  return args.length ? format(value, args) : value;
}

let dataPatterns: { key: string; regex: RegExp }[] | null = null;

function patterns() {
  if (dataPatterns) return dataPatterns;
  const result: { key: string; regex: RegExp }[] = [];
  for (const key of Object.keys(tables.en)) {
    if (!key.includes("%@")) continue;
    const pieces = key.split("%@");
    if (!/[一-鿿]/.test(pieces.join(""))) continue;
    const body = pieces
      .map((piece) => piece.replace(/%%/g, "%").replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
      .join("(.+?)");
    result.push({ key, regex: new RegExp(`^${body}$`) });
  }
  result.sort((a, b) => b.key.length - a.key.length);
  dataPatterns = result;
  return result;
}

/** 翻译采集器给的中文文案（额度窗口名、成就描述……），查不到时套带 %@ 的模板。 */
export function data(text: string): string {
  if (!text || currentLanguage() === "zh") return text;
  const exact = lookup(text);
  if (exact !== text) return exact;
  for (const { key, regex } of patterns()) {
    const match = regex.exec(text);
    if (!match) continue;
    const translated = lookup(key);
    if (translated === key) return text;
    return format(translated, match.slice(1).map((arg) => data(arg)));
  }
  return text;
}
