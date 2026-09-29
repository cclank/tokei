"""界面多语言的护栏。

中文是源语言：Swift 里写 `L("中文原文")`，原文就是 key；英、法、日、韩的
`Tokei/Localization/<lang>.lproj/Localizable.strings` 把原文映射成译文。采集器输出的
中文标签（额度窗口名、成就等）同样是 key，界面显示时用 `L10n.data()` 翻译。

这里卡住四件事：
1. 代码里用到的每一句（含采集器吐出来的）英文词表都有；
2. 各语言占位符与原文一致（只用 %@ / %N$@）；
3. 不许新增没包 L() 的中文字面量（数据标识等刻意保留的写 `// l10n-ignore`）；
4. 词表里没有已经不用的旧词条。
法、日、韩允许缺词，缺了界面回退英文。
"""
import io
import re
import subprocess
import tempfile
import tokenize
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "Tokei" / "Sources" / "Tokei"
RESOURCES = ROOT / "Tokei" / "Localization"
LANGUAGES = ("en", "fr", "ja", "ko")
CJK = re.compile(r"[一-鿿]")

# 通过变量传给 L() 的 key：源码里看不到字面量，在这里登记。
DYNAMIC_KEYS = {
    # SyncManager.PeerLoadStage 的原始值，显示时 L(stage.rawValue)
    "配置", "读取", "时间戳", "用量结构", "面板数据", "时间范围",
    # 额度轨迹里的窗口标识，显示时 L(window)
    "5 小时", "周 · 全部", "周 · Fable", "周",
    # UsageSummaryBuilder.formatUpdatedLine 按模板认前缀
    "更新于 %@", "更新 %@",
    # Wrapped 成就里带原始数的描述模板（采集器 tokens_template）
    "%@ token", "单日 %@ token",
    # Dashboard 模型名：采集器的「合成 / 未知」拼上工具后缀
    "合成 (%@)", "未知 (%@)",
}

# 采集器里不进 App 界面的中文：SwiftBar 文本输出、命令行提示、内部异常。
COLLECTOR_IGNORE = re.compile(
    r"\{F\}|font=|refresh=|^更新失败|^已更新 |^，保留 |^所有模型价格已匹配|^varint")


def _swift_literal_end(src, i):
    """src[i] 是 '"'，返回单行字符串字面量结束后的位置（跳过插值里的嵌套字符串）。"""
    j = i + 1
    while j < len(src):
        c = src[j]
        if c == "\\" and src[j + 1:j + 2] == "(":
            depth, k = 1, j + 2
            while k < len(src) and depth:
                if src[k] == '"':
                    k = _swift_literal_end(src, k)
                    continue
                depth += {"(": 1, ")": -1}.get(src[k], 0)
                k += 1
            j = k
            continue
        if c == "\\":
            j += 2
            continue
        if c == '"':
            return j + 1
        if c == "\n":
            raise ValueError("unterminated literal")
        j += 1
    raise ValueError("unterminated literal")


def _swift_unescape(text):
    return (text.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')
            .replace("\\'", "'").replace("\\\\", "\\"))


def _swift_literals(src):
    """(起始位置, 字面量源码) —— 跳过注释与多行字符串。"""
    i = 0
    while i < len(src):
        if src.startswith('"""', i):
            end = src.find('"""', i + 3)
            i = len(src) if end < 0 else end + 3
        elif src.startswith("//", i):
            end = src.find("\n", i)
            i = len(src) if end < 0 else end
        elif src.startswith("/*", i):
            end = src.find("*/", i)
            i = len(src) if end < 0 else end + 2
        elif src[i] == '"':
            try:
                end = _swift_literal_end(src, i)
            except ValueError:
                i += 1
                continue
            yield i, src[i:end]
            i = end
        else:
            i += 1


def swift_keys():
    """所有 L("...") 的 key（运行时的字符串形态）及出处。"""
    keys = {}
    for path in sorted(SRC.glob("*.swift")):
        src = path.read_text(encoding="utf-8")
        for start, literal in _swift_literals(src):
            if not re.search(r"\bL\(\s*$", src[max(0, start - 8):start]):
                continue
            body = literal[1:-1]
            assert "\\(" not in body, f"{path.name}: L() 的 key 里不能有插值：{literal}"
            keys.setdefault(_swift_unescape(body), set()).add(path.name)
    return keys


def unwrapped_swift_chinese():
    """没包 L()、也没标 l10n-ignore 的中文字面量。"""
    found = []
    for path in sorted(SRC.glob("*.swift")):
        src = path.read_text(encoding="utf-8")
        for start, literal in _swift_literals(src):
            text = re.sub(r"\\\((?:[^()]|\([^()]*\))*\)", "", literal)
            if not CJK.search(text) or re.search(r"\bL\(\s*$", src[max(0, start - 8):start]):
                continue
            line_start = src.rfind("\n", 0, start) + 1
            line_end = src.find("\n", start)
            line = src[line_start:line_end if line_end >= 0 else len(src)]
            if "l10n-ignore" in line:
                continue
            found.append(f"{path.name}:{src.count(chr(10), 0, start) + 1}: {line.strip()}")
    return found


def _python_string_template(token):
    """Python 字符串 token → 界面 key。f-string 的 {…} 换成 %@，此时字面 % 写成 %%。"""
    prefix = re.match(r"[rRbBfFuU]*", token).group(0).lower()
    body = token[len(prefix):]
    quote = body[:3] if body[:3] in ('"""', "'''") else body[0]
    body = body[len(quote):-len(quote)]
    if "f" not in prefix:
        return body
    pieces = re.split(r"(\{\{|\}\}|\{[^{}]*\})", body)
    has_args = any(p.startswith("{") and p not in ("{{",) and p != "}}" for p in pieces)
    out = []
    for piece in pieces:
        if piece == "{{":
            out.append("{")
        elif piece == "}}":
            out.append("}")
        elif piece.startswith("{"):
            out.append("%@")
        else:
            out.append(piece.replace("%", "%%") if has_args else piece)
    return "".join(out)


def collector_keys():
    """采集器输出、会进 App 界面的中文。"""
    source = (ROOT / "usage.30s.py").read_text(encoding="utf-8")
    keys = {}
    previous = None
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.STRING and CJK.search(token.string):
            docstring = previous is None or previous.type in (
                tokenize.INDENT, tokenize.DEDENT, tokenize.NEWLINE, tokenize.NL)
            triple = re.match(r"[rRbBfFuU]*('''|\"\"\")", token.string)
            if not (docstring and triple):
                key = _python_string_template(token.string)
                if not COLLECTOR_IGNORE.search(token.string) and not COLLECTOR_IGNORE.search(key):
                    keys.setdefault(key, set()).add(f"usage.30s.py:{token.start[0]}")
        if token.type not in (tokenize.COMMENT, tokenize.NL):
            previous = token
    return keys


def load_strings(language):
    """解析 .strings（与 NSDictionary 同一规则的子集：一行一条 "k" = "v";）。"""
    path = RESOURCES / f"{language}.lproj" / "Localizable.strings"
    table = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("/*") or line.startswith("//"):
            continue
        m = re.fullmatch(r'"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)";', line)
        assert m, f"{path.name} 第 {line_no} 行格式不对：{line}"
        key, value = (_swift_unescape(x) for x in m.groups())
        assert key not in table, f"{language}: 重复的 key：{key}"
        table[key] = value
    return table


def placeholders(text):
    """占位符签名。%@ 按顺序编号，%N$@ 按位置；%% 不算。"""
    text = text.replace("%%", "")
    positional = re.findall(r"%(\d+)\$@", text)
    sequential = len(re.findall(r"%@", text))
    return sorted(int(n) for n in positional) + list(range(1, sequential + 1))


def all_keys():
    keys = set(swift_keys()) | set(collector_keys()) | DYNAMIC_KEYS
    return keys


class LocalizationTests(unittest.TestCase):
    def test_every_interface_string_has_an_english_translation(self):
        english = load_strings("en")
        missing = sorted(all_keys() - set(english))
        self.assertEqual(missing, [], "英文词表缺这些句子：\n" + "\n".join(missing))

    def test_every_translation_keeps_the_placeholders_of_the_original(self):
        for language in LANGUAGES:
            for key, value in load_strings(language).items():
                with self.subTest(language=language, key=key):
                    self.assertEqual(sorted(placeholders(value)), sorted(set(placeholders(key))),
                                     f"{language}: {key!r} → {value!r}")
                    if placeholders(key):
                        # 带参数的句子才解析 %：字面百分号写 %%，其余只许 %@ / %N$@
                        self.assertNotRegex(value.replace("%%", ""), r"%(?!@|\d+\$@)",
                                            "只用 %@ / %N$@；数字请先格式化成字符串")

    def test_no_new_chinese_literal_bypasses_l(self):
        self.assertEqual(unwrapped_swift_chinese(), [],
                         "包进 L()；数据标识等刻意保留的中文在行尾写 // l10n-ignore")

    def test_tables_hold_no_stale_entries(self):
        keys = all_keys()
        for language in LANGUAGES:
            stale = sorted(set(load_strings(language)) - keys)
            self.assertEqual(stale, [], f"{language} 词表里有已经不用的词条")

    def test_keys_without_arguments_never_contain_placeholders(self):
        """不带参数的 L("…") 原样返回，写了 %@ 会直接露在界面上。"""
        for path in sorted(SRC.glob("*.swift")):
            src = path.read_text(encoding="utf-8")
            for m in re.finditer(r'\bL\("((?:[^"\\]|\\.)*)"\)', src):
                self.assertNotIn("%@", m.group(1), f"{path.name}: {m.group(0)}")

    def test_the_swift_lookup_behaves(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "l10n-check"
            result = subprocess.run(
                ["swiftc", "-parse-as-library", str(SRC / "L10n.swift"), str(SRC / "Model.swift"),
                 str(ROOT / "tests/swift/LocalizationCheck.swift"), "-o", str(binary)],
                capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("localization checks passed", result.stdout)


class PackagingTests(unittest.TestCase):
    def test_the_app_bundle_ships_every_language(self):
        script = (ROOT / "Tokei" / "package.sh").read_text(encoding="utf-8")
        self.assertIn("Localization/*.lproj", script)
        self.assertIn("CFBundleLocalizations", script)


if __name__ == "__main__":
    unittest.main()
