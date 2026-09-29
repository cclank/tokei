import unittest

from test_codex_limits import USAGE


class ProjectSourceRegistryTests(unittest.TestCase):
    """项目维度的统一数据源。

    项目足迹页与 Wrapped 的每日项目必须来自同一个流——历史上两边各写各的，
    结果 pi 只出现在项目足迹、WorkBuddy 的回顾页项目名还是会话时间戳目录。
    """

    def test_both_dimensions_read_the_same_source(self):
        source = USAGE.projects.__doc__ or ""
        self.assertIn("_project_contributions", source,
                      "项目足迹必须走统一数据源")
        # Wrapped 的每日项目同样由它派生
        import inspect
        wrapped = inspect.getsource(USAGE.build_wrapped)
        self.assertIn("_project_day_names(cache)", wrapped,
                      "回顾页的每日项目必须与项目足迹同源")

    def test_registry_covers_every_shape_of_harness(self):
        entry_tools = {tool for tool, *_ in USAGE._PROJECT_SOURCES}
        day_tools = {tool for tool, _ in USAGE._PROJECT_DAY_SOURCES}
        record_tools = {tool for tool, *_ in USAGE._PROJECT_RECORD_SOURCES}
        # 一文件一会话 / 单库多项目 / 记录流，三种形状都要有代表
        self.assertTrue(entry_tools and day_tools and record_tools)
        self.assertEqual(entry_tools & day_tools, set(), "一个工具只能属于一种形状")
        self.assertEqual(entry_tools & record_tools, set())
        self.assertEqual(day_tools & record_tools, set())

    def test_每个_harness_都被某个维度覆盖(self):
        registered = ({tool for tool, *_ in USAGE._PROJECT_SOURCES}
                      | {tool for tool, _ in USAGE._PROJECT_DAY_SOURCES}
                      | {tool for tool, *_ in USAGE._PROJECT_RECORD_SOURCES})
        # 有项目路径可取的工具都应在册；没有 cwd 的工具（gemini/qwencode/zcode 等）
        # 不在此列，是因为它们的日志里根本不记工作目录。
        for tool in ("claude", "codex", "devin", "minimax", "hermes", "opencode",
                     "kimicode", "pi", "prime_agent", "workbuddy",
                     "workbuddy_ai", "deepseek_harness", "mimocode",
                     "musecode", "cmdcode", "codebuddy"):
            self.assertIn(tool, registered, f"{tool} 应参与项目维度")


class ProjectAggregationTests(unittest.TestCase):
    def _cache(self):
        return {
            # 一文件一会话：会话数按条目算
            "claude": {
                "/a.jsonl": {"proj": "/work/alpha", "days": {
                    "2026-09-20": {"in": 10, "out": 5, "cr": 0, "cw": 0, "reason": 0,
                                   "cost": 1.0, "models": {"opus": {"in": 10, "out": 5}}}}},
                "/b.jsonl": {"proj": "/work/alpha", "days": {
                    "2026-09-21": {"in": 20, "out": 0, "cr": 0, "cw": 0, "reason": 0,
                                   "cost": 2.0, "models": {}}}},
            },
            # 单库多项目：项目挂在天上
            "devin": {
                "db:/x": {"days": {"2026-09-21": {"projects": {
                    "/work/beta": {"tokens": 100, "cost": 0.5,
                                   "models": {"swe-1": 100}, "sessions": ["s1"]}}}}},
            },
        }

    def test_entry_shape_counts_one_session_per_entry(self):
        hits = list(USAGE._project_contributions(self._cache()))
        alpha = [h for h in hits if h["path"] == "/work/alpha"]
        self.assertEqual(len({h["session"] for h in alpha}), 2, "两个文件=两次会话")
        self.assertEqual(sum(h["tokens"] for h in alpha), 35)
        self.assertEqual(sum(h["cost"] for h in alpha), 3.0)

    def test_day_shape_carries_project_level_usage(self):
        hits = [h for h in USAGE._project_contributions(self._cache())
                if h["path"] == "/work/beta"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["tokens"], 100)
        self.assertEqual(hits[0]["tool"], "devin")
        self.assertIn("Swe 1 (Devin)", hits[0]["models"])

    def test_model_labels_always_name_their_tool(self):
        """Claude 曾是唯一不带后缀的，项目卡片上只显示裸模型名，看不出是哪个工具。"""
        for hit in USAGE._project_contributions(self._cache()):
            for name in hit["models"]:
                self.assertTrue(name.endswith(f"({hit['label']})"), name)

    def test_wrapped_day_names_use_the_same_projects(self):
        names = USAGE._project_day_names(self._cache())
        self.assertEqual(names.get("2026-09-20"), {"alpha"})
        self.assertEqual(names.get("2026-09-21"), {"alpha", "beta"})

    def test_a_missing_or_placeholder_path_contributes_nothing(self):
        cache = {"claude": {
            "/a": {"proj": "", "days": {"2026-09-21": {"in": 9}}},
            "/b": {"proj": "?", "days": {"2026-09-21": {"in": 9}}},
            "/c": {"days": {"2026-09-21": {"in": 9}}},
        }}
        self.assertEqual(list(USAGE._project_contributions(cache)), [])


class CodexProjectBackfillTests(unittest.TestCase):
    """Codex 的 cwd 要按需回填：为一个字段重解析几千个会话文件不可接受。"""

    def test_backfill_is_capped_and_newest_first(self):
        import inspect
        source = inspect.getsource(USAGE.scan_codex)
        self.assertIn("_CODEX_PROJECT_BACKFILL_PER_SCAN", source, "必须有每轮上限")
        self.assertIn("pending.sort(reverse=True)", source, "必须最近活跃优先")
        self.assertLessEqual(USAGE._CODEX_PROJECT_BACKFILL_PER_SCAN, 400)

    def test_cwd_reader_only_touches_the_head_of_the_file(self):
        import inspect
        source = inspect.getsource(USAGE._codex_session_cwd)
        # 只认 session_meta 那一行：按 cwd 匹配会一路扫到后面的大事件行
        self.assertIn('"session_meta"', source)
        self.assertIn("max_lines", source)


if __name__ == "__main__":
    unittest.main()
