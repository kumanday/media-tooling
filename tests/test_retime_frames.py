from __future__ import annotations

import argparse
import importlib.util
import io
import json
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType
from typing import Any

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / ".agents"
    / "skills"
    / "media-motion-graphics"
    / "scripts"
    / "retime_frames.py"
)


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("retime_frames", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rf = load_script()


def voice(frame: int, duration: float, words: list[tuple[str, float, float]]) -> dict[str, Any]:
    return {
        "frame": frame,
        "duration_s": duration,
        "words": [{"text": t, "start": s, "end": e} for t, s, e in words],
    }


# Old take: 12 s; new take: 14 s with every word moved. The warp passes through
# (0,0) (1,2) (2,3) (4,6) (5,7) (9,11) (10,12) (12,14): e.g. 0.7->1.4, 1.5->2.5,
# 3.0->4.5, 4.5->6.5, 7.0->9.0, 8.0->10.0.
OLD = voice(1, 12.0, [("one", 1.0, 2.0), ("two", 4.0, 5.0), ("three", 9.0, 10.0)])
NEW = voice(1, 14.0, [("One", 2.0, 3.0), ("two,", 6.0, 7.0), ("three.", 11.0, 12.0)])
PTS = rf.warp_points(OLD, NEW)


def retime(code: str, **opts: Any) -> Any:
    return rf.retime_code(code, PTS, 12.0, 14.0, rf.Options(**opts))


class WarpTests(unittest.TestCase):
    def test_words_match_ignoring_case_and_punctuation(self) -> None:
        self.assertIsNotNone(PTS)
        self.assertAlmostEqual(rf.warp(PTS, 3.0), 4.5)
        self.assertAlmostEqual(rf.warp(PTS, 13.0), 15.0)  # past the end: shifted

    def test_different_words_are_not_warped(self) -> None:
        other = voice(1, 14.0, [("one", 2.0, 3.0), ("deux", 6.0, 7.0), ("three", 11.0, 12.0)])
        self.assertIsNone(rf.warp_points(OLD, other))


class LegacyRuleTests(unittest.TestCase):
    def test_dur_position_pairs_and_default_helper_rule(self) -> None:
        code = (
            "var DUR = 12;\n"
            'tl.to("#a", { opacity: 1, duration: 0.5 }, 3.0);\n'
            '[["#b", 7.0], ["#c", 8.0]].forEach(function (c) { tl.to(c[0], { x: 1 }, c[1]); });\n'
            'pop("#d", 1.5);\n'
            "tl.set({}, {}, DUR);\n"
        )
        res = retime(code)
        self.assertIn("var DUR = 14.00;", res.text)
        self.assertIn('tl.to("#a", { opacity: 1, duration: 0.5 }, 4.50);', res.text)
        self.assertIn('[["#b", 9.00], ["#c", 10.00]]', res.text)
        self.assertIn('pop("#d", 2.50);', res.text)
        self.assertEqual(res.default_helpers, Counter({"pop": 1}))
        self.assertEqual(
            [(o, n, rule) for o, n, _, rule in res.changes],
            [
                (12.0, 14.0, "DUR"),
                (3.0, 4.5, "position"),
                (7.0, 9.0, "pair"),
                (8.0, 10.0, "pair"),
                (1.5, 2.5, "pop() last arg (default)"),
            ],
        )
        self.assertEqual([ln for _, _, ln, _ in res.changes], [1, 2, 3, 3, 4])

    def test_plain_dur_is_mapped_unconditionally(self) -> None:
        self.assertIn("var DUR = 14.00;", retime("var DUR = 11.5;").text)

    def test_dur_minus_keeps_legacy_mapping(self) -> None:
        self.assertIn("DUR - 1.00", retime('tl.to("#a", {}, DUR - 0.5);').text)

    def test_strings_and_comments_are_untouched(self) -> None:
        code = (
            'var label = "pop(x, 3.0)"; var css = \'}, 3.0)\'; var tpl = `${a}, 3.0)`;\n'
            "// pop(x, 3.0) and }, 3.0)\n"
            "/* }, 7.0) */\n"
            'tl.to("#a", { ease: "back.out(1.7)" }, 3.0);\n'
        )
        res = retime(code)
        expected = code.replace('"back.out(1.7)" }, 3.0)', '"back.out(1.7)" }, 4.50)')
        self.assertEqual(res.text, expected)
        self.assertEqual([(o, n) for o, n, _, _ in res.changes], [(3.0, 4.5)])

    def test_retime_script_wrapper_keeps_return_shape(self) -> None:
        text, changes = rf.retime_script('tl.to("#a", {}, 3.0);', PTS, 12.0, 14.0)
        self.assertEqual(text, 'tl.to("#a", {}, 4.50);')
        self.assertEqual(changes, [(3.0, 4.5)])


class DurationVariableTests(unittest.TestCase):
    def test_dur_prefixed_names_map_when_they_hold_the_old_duration(self) -> None:
        res = retime("var DURATION = 12.0;\nconst DUR_FADE = 0.4;\nvar D = 12;\n")
        self.assertIn("var DURATION = 14.00;", res.text)
        self.assertIn("const DUR_FADE = 0.4;", res.text)
        self.assertIn("var D = 12;", res.text)
        self.assertEqual(len(res.notes), 1)
        self.assertIn("DUR_FADE", res.notes[0])

    def test_extra_duration_variable(self) -> None:
        res = retime("var D = 12;\ntl.set({}, {}, D);\n", duration_vars=frozenset({"D"}))
        self.assertIn("var D = 14.00;", res.text)


class TimeKeyTests(unittest.TestCase):
    CODE = (
        "var cards = [\n"
        "  { n: 1, cue: 3.0, q: 7.0 },\n"
        '  { n: 2, "cue": 1.5, q: 4.5 + 0.1 }\n'
        "];\n"
        "var rows = [{ n: 1, L: 1.5, R: 8.0 }];\n"
    )

    def test_time_keys_are_opt_in(self) -> None:
        self.assertEqual(retime(self.CODE).text, self.CODE)

    def test_time_keys_warp_object_fields(self) -> None:
        res = retime(self.CODE, time_keys=frozenset({"cue", "q", "L", "R"}))
        self.assertIn("{ n: 1, cue: 4.50, q: 9.00 }", res.text)
        self.assertIn('{ n: 2, "cue": 2.50, q: 6.50 + 0.1 }', res.text)
        self.assertIn("{ n: 1, L: 2.50, R: 10.00 }", res.text)
        self.assertEqual(
            sorted({rule for _, _, _, rule in res.changes}), ["key L", "key R", "key cue", "key q"]
        )


class HelperTests(unittest.TestCase):
    def test_default_rule_warps_the_last_argument(self) -> None:
        res = retime('wipe("#r1", 3.0, 0.7);')
        self.assertEqual(res.text, 'wipe("#r1", 3.0, 1.40);')
        self.assertEqual(res.default_helpers, Counter({"wipe": 1}))

    def test_declared_helper_warps_only_its_time_argument(self) -> None:
        res = retime('wipe("#r1", 3.0, 0.7);', helpers={"wipe": frozenset({1})})
        self.assertEqual(res.text, 'wipe("#r1", 4.50, 0.7);')
        self.assertEqual(res.default_helpers, Counter())
        self.assertEqual(res.changes[0][3], "wipe() arg 1")

    def test_nested_calls_and_multiple_indices(self) -> None:
        code = 'draw($("f03-b1"), 3.0, 0.6, "power2.out");\nspan(q("x"), 1.5, 0.3, 7.0 + i * 0.1);\n'
        res = retime(code, helpers={"draw": frozenset({1}), "span": frozenset({1, 3})})
        self.assertIn('draw($("f03-b1"), 4.50, 0.6, "power2.out");', res.text)
        self.assertIn('span(q("x"), 2.50, 0.3, 9.00 + i * 0.1);', res.text)

    def test_helper_definition_is_untouched(self) -> None:
        code = "function wipe(id, t, dur) { tl.fromTo(q(id), { scaleX: 0 }, { scaleX: 1, duration: dur || 0.6 }, t); }"
        self.assertEqual(retime(code, helpers={"wipe": frozenset({1})}).text, code)

    def test_no_helper_default(self) -> None:
        res = retime('pop("#d", 1.5);\ntl.to("#a", {}, 3.0);', helper_default=False)
        self.assertEqual(res.text, 'pop("#d", 1.5);\ntl.to("#a", {}, 4.50);')

    def test_parse_helper(self) -> None:
        self.assertEqual(rf.parse_helper("span:1,3"), ("span", frozenset({1, 3})))
        self.assertEqual(rf.parse_helper("$fade:0"), ("$fade", frozenset({0})))
        with self.assertRaises(argparse.ArgumentTypeError):
            rf.parse_helper("wipe")


class PositionExpressionTests(unittest.TestCase):
    def test_leading_base_time_is_warped(self) -> None:
        code = (
            'tl.to("#a", { x: 1 }, 3.0 + i * 0.1);\n'
            'tl.fromTo("#b", { a: 1 },\n'
            "  { a: 2, duration: 0.3 },\n"
            "  7.0 + (k - 1) * 0.15);\n"
        )
        res = retime(code)
        self.assertIn("}, 4.50 + i * 0.1);", res.text)
        self.assertIn("  9.00 + (k - 1) * 0.15);", res.text)
        self.assertEqual([rule for _, _, _, rule in res.changes], ["position base", "position base"])

    def test_non_literal_or_non_final_expressions_are_untouched(self) -> None:
        code = 'tl.to("#c", {}, c.cue + 0.1);\nfoo({}, 3.0 + i, "x");\n'
        self.assertEqual(retime(code).text, code)


class AuditTests(unittest.TestCase):
    CODE = (
        "var t = 8.0 + i * 0.2;\n"
        'tl.to("#a", { x: 120, scale: 1.2, duration: 0.5 }, [3.0, 7.0][i]);\n'
        'tl.to("#b", { duration: 7.0 - 3.0 }, 3.0);\n'
        'tl.to("#c", { duration: 2.5, "stroke-width": 2.5 }, 1.5);\n'
        'rise("#el", 3.0, 36, 2.5);\n'
        "var speed = dist / 11.0;\n"
        'tl.to("#d", { rot: -4.5 }, 0);\n'
        "// at 9.5 the card lands\n"
    )

    def test_audit_lists_unmapped_time_like_literals(self) -> None:
        res = retime(self.CODE, helpers={"rise": frozenset({1})}, audit=True)
        self.assertEqual(
            [(v, ctx) for _, v, _, ctx, _ in res.leftovers],
            [
                (8.0, "assign t"),
                (3.0, "array"),
                (7.0, "array"),
                (7.0, "field duration (computed)"),
                (3.0, "field duration (computed)"),
                (2.5, "field duration (long)"),
                (11.0, "assign speed"),
            ],
        )
        line, value, warped, _, source = res.leftovers[0]
        self.assertEqual((line, value, warped), (1, 8.0, 10.0))
        self.assertEqual(source, "var t = 8.0 + i * 0.2;")
        self.assertEqual(res.text.count("8.0 + i"), 1)  # a report, not a rewrite

    def test_audit_is_off_by_default(self) -> None:
        self.assertEqual(retime(self.CODE).leftovers, [])


class MainTests(unittest.TestCase):
    FRAME = (
        "<html><body>\n"
        '<script src="gsap.min.js"></script>\n'
        "<script>\n"
        "  var DURATION = 12.0;\n"
        '  wipe("#r", 3.0, 0.7);\n'
        "  var cards = [{ n: 1, cue: 1.5 }];\n"
        "  var t = 8.0 + i;\n"
        "  tl.set({}, {}, DURATION);\n"
        "</script>\n"
        "</body></html>\n"
    )

    def run_main(self, root: Path, *extra: str) -> tuple[int, str]:
        argv = [
            "--old-audio-meta", str(root / "old.json"),
            "--new-audio-meta", str(root / "new.json"),
            "--frames-dir", str(root / "frames"),
            "--time-keys", "cue",
            "--helper", "wipe:1",
            *extra,
        ]
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit) as exit_info:
            rf.main(argv)
        return int(exit_info.exception.code or 0), buf.getvalue()

    def test_dry_run_reports_and_apply_rewrites(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = root / "frames"
            frames.mkdir()
            frame_two_old = voice(2, 5.0, [("hello", 1.0, 2.0)])
            frame_two_new = voice(2, 5.0, [("hola", 1.0, 2.0)])
            (root / "old.json").write_text(json.dumps({"voices": [OLD, frame_two_old]}))
            new_three = voice(3, 4.0, [("x", 1.0, 2.0)])
            (root / "new.json").write_text(json.dumps({"voices": [NEW, frame_two_new, new_three]}))
            frame = frames / "01-test.html"
            frame.write_text(self.FRAME, encoding="utf-8")
            (frames / "02-other.html").write_text("<script>tl.to('#a', {}, 1.5);</script>", encoding="utf-8")

            status, out = self.run_main(root, "--dry-run", "--audit")
            self.assertEqual(status, 1)  # frame 02's words differ
            self.assertEqual(frame.read_text(encoding="utf-8"), self.FRAME)
            self.assertIn("frame 01: 01-test.html · duration 12.0 -> 14.0 · 3 times moved", out)
            self.assertIn("  3.00 ->   4.50  L5 wipe() arg 1", out)
            self.assertIn("  1.50 ->   2.50  L6 key cue", out)
            self.assertIn("audit: 1 time-like literals not mapped:", out)
            self.assertIn("L7", out)
            self.assertIn("frame 02: SKIPPED, words differ between takes", out)
            self.assertIn("frame 03: skipped (no old voice or no frame file)", out)

            status, _ = self.run_main(root)
            self.assertEqual(status, 1)
            text = frame.read_text(encoding="utf-8")
            self.assertIn("var DURATION = 14.00;", text)
            self.assertIn('wipe("#r", 4.50, 0.7);', text)
            self.assertIn("{ n: 1, cue: 2.50 }", text)
            self.assertIn("var t = 8.0 + i;", text)
            self.assertIn('<script src="gsap.min.js"></script>', text)


if __name__ == "__main__":
    unittest.main()
