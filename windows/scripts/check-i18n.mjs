// 界面文案护栏，规则与 Mac 版 tests/test_localization.py 一致：
// 1. 每个 L("…") 的 key 在英文词表里都有（Windows 版直接用 Mac 的词表，缺词就是没对齐原文）；
// 2. 传的参数个数与 key 里的占位符对得上（没参数的 key 原样显示，写了 %@ 会露在界面上）；
// 3. 不许有没包 L() 的中文字面量或 JSX 文本。数据标识等刻意保留的中文，在那一行写 l10n-ignore。
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const srcDir = path.join(root, "src");
// TOKEI_EN_STRINGS 可指向另一份词表（比如只对照已提交的版本）。
const englishTable =
  process.env.TOKEI_EN_STRINGS || path.join(root, "..", "Tokei", "Localization", "en.lproj", "Localizable.strings");
const CJK = /[一-鿿]/;

function unescape(text) {
  return text.replace(/\\(.)/g, (_m, c) => (c === "n" ? "\n" : c === "t" ? "\t" : c));
}

function loadStrings(file) {
  const table = new Set();
  for (const line of fs.readFileSync(file, "utf8").split("\n")) {
    const m = /^\s*"((?:[^"\\]|\\.)*)"\s*=\s*"(?:[^"\\]|\\.)*";\s*$/.exec(line);
    if (m) table.add(unescape(m[1]));
  }
  return table;
}

/** 占位符个数：%@ 按顺序数，%N$@ 取最大的 N；%% 不算。 */
function placeholderCount(key) {
  const text = key.replaceAll("%%", "");
  const sequential = (text.match(/%@/g) ?? []).length;
  const positional = [...text.matchAll(/%(\d+)\$@/g)].map((m) => Number(m[1]));
  return Math.max(sequential, ...positional, 0);
}

function sourceFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return /\.tsx?$/.test(entry.name) && !entry.name.endsWith(".d.ts") ? [full] : [];
  });
}

const english = loadStrings(englishTable);
const problems = [];
const usedKeys = new Set();

for (const file of sourceFiles(srcDir)) {
  const text = fs.readFileSync(file, "utf8");
  const kind = file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind);
  const lines = text.split("\n");
  const wrapped = new Set();
  const where = (node) => {
    const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf));
    return { label: `${path.relative(root, file)}:${line + 1}`, line };
  };
  const ignored = (node) => {
    const start = sf.getLineAndCharacterOfPosition(node.getStart(sf)).line;
    const end = sf.getLineAndCharacterOfPosition(node.getEnd()).line;
    return lines.slice(start, end + 1).some((line) => line.includes("l10n-ignore"));
  };

  /** L() 的第一个参数：字面量直接是 key；`条件 ? "甲" : "乙"` 两边都算 key。 */
  const literalKeys = (node) => {
    if (ts.isParenthesizedExpression(node)) return literalKeys(node.expression);
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return [node];
    if (ts.isConditionalExpression(node)) {
      const a = literalKeys(node.whenTrue);
      const b = literalKeys(node.whenFalse);
      return a && b ? [...a, ...b] : null;
    }
    return null;
  };

  const visit = (node) => {
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) return;
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === "L") {
      const [first, ...rest] = node.arguments;
      if (first && ts.isTemplateExpression(first)) {
        problems.push(`${where(first).label}: L() 的 key 里不能有插值，用 %@ 传参`);
      }
      const keys = first ? literalKeys(first) : null;
      const spread = rest.some((arg) => ts.isSpreadElement(arg));
      for (const literal of keys ?? []) {
        wrapped.add(literal);
        const key = literal.text;
        usedKeys.add(key);
        if (!english.has(key)) problems.push(`${where(literal).label}: 英文词表里没有「${key}」`);
        if (!spread && placeholderCount(key) !== rest.length) {
          problems.push(
            `${where(literal).label}: 「${key}」有 ${placeholderCount(key)} 个占位符，却传了 ${rest.length} 个参数`,
          );
        }
      }
    }
    const isText =
      ts.isStringLiteral(node) ||
      ts.isNoSubstitutionTemplateLiteral(node) ||
      ts.isTemplateHead(node) ||
      ts.isTemplateMiddle(node) ||
      ts.isTemplateTail(node) ||
      ts.isJsxText(node);
    if (isText && !wrapped.has(node) && CJK.test(node.text ?? node.getText(sf)) && !ignored(node)) {
      const snippet = node.getText(sf).trim().slice(0, 60);
      problems.push(`${where(node).label}: 中文没包 L()：${snippet}`);
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
}

if (problems.length) {
  console.error(`界面文案检查没通过（${problems.length} 处）：\n` + problems.join("\n"));
  process.exit(1);
}
console.log(`i18n ok: ${usedKeys.size} keys`);
