import unittest

from brain.errors import TargetFormatError, TargetOutOfRangeError, TargetUncertainError
from brain.planning.output_parser import parse_target_from_output
from brain.protocol import Target


class OutputParserTests(unittest.TestCase):
    def test_plain_json(self) -> None:
        self.assertEqual(parse_target_from_output('{"target_x": 3, "target_y": 2}'), Target(3, 2))

    def test_compact_json(self) -> None:
        self.assertEqual(parse_target_from_output('{"target_x":3,"target_y":2}'), Target(3, 2))

    def test_fenced_json(self) -> None:
        raw = '```json\n{"target_x": 3, "target_y": 2}\n```'
        self.assertEqual(parse_target_from_output(raw), Target(3, 2))

    def test_explanation_around_json(self) -> None:
        raw = '好的，目标为：{"target_x": 5, "target_y": 5}，请确认。'
        self.assertEqual(parse_target_from_output(raw), Target(5, 5))

    def test_extra_fields_ignored(self) -> None:
        raw = '{"target_x": 3, "target_y": 2, "reason": "test"}'
        self.assertEqual(parse_target_from_output(raw), Target(3, 2))

    def test_duplicate_same_target(self) -> None:
        raw = '{"target_x": 1, "target_y": 1} 和 {"target_x": 1, "target_y": 1}'
        self.assertEqual(parse_target_from_output(raw), Target(1, 1))

    def test_ambiguous_targets_rejected(self) -> None:
        raw = '{"target_x": 1, "target_y": 1} 和 {"target_x": 2, "target_y": 2}'
        with self.assertRaises(TargetFormatError):
            parse_target_from_output(raw)

    def test_uncertain_sentinel(self) -> None:
        with self.assertRaises(TargetUncertainError):
            parse_target_from_output('{"target_x": -1, "target_y": -1}')

    def test_float_sentinel_rejected_as_format(self) -> None:
        with self.assertRaises(TargetFormatError):
            parse_target_from_output('{"target_x": -1.0, "target_y": -1.0}')

    def test_out_of_range(self) -> None:
        with self.assertRaises(TargetOutOfRangeError):
            parse_target_from_output('{"target_x": 6, "target_y": 2}')

    def test_negative_out_of_range(self) -> None:
        with self.assertRaises(TargetOutOfRangeError):
            parse_target_from_output('{"target_x": -2, "target_y": 3}')

    def test_string_number_rejected(self) -> None:
        with self.assertRaises(TargetFormatError):
            parse_target_from_output('{"target_x": "3", "target_y": 2}')

    def test_bool_rejected(self) -> None:
        with self.assertRaises(TargetFormatError):
            parse_target_from_output('{"target_x": true, "target_y": 2}')

    def test_missing_field_rejected(self) -> None:
        with self.assertRaises(TargetFormatError):
            parse_target_from_output('{"target_x": 3}')

    def test_non_json_rejected(self) -> None:
        with self.assertRaises(TargetFormatError):
            parse_target_from_output("我觉得应该去右下角")

    def test_uncertain_phrase_with_example(self) -> None:
        raw = "我无法确定目标，示例格式 target_x: 3, target_y: 2"
        with self.assertRaises(TargetUncertainError):
            parse_target_from_output(raw)

    def test_prose_example_not_used(self) -> None:
        raw = "示例格式 target_x: 3, target_y: 2，请按此格式输出"
        with self.assertRaises(TargetFormatError):
            parse_target_from_output(raw)

    def test_bare_fields_fallback(self) -> None:
        self.assertEqual(parse_target_from_output("target_x: 4, target_y: 3"), Target(4, 3))

    def test_empty_rejected(self) -> None:
        for raw in ("", "   "):
            with self.subTest(raw=raw), self.assertRaises(TargetFormatError):
                parse_target_from_output(raw)

    def test_non_string_rejected(self) -> None:
        with self.assertRaises(TargetFormatError):
            parse_target_from_output(None)

    def test_deeply_nested_rejected(self) -> None:
        with self.assertRaises(TargetFormatError):
            parse_target_from_output("[" * 3000 + "]" * 3000)


if __name__ == "__main__":
    unittest.main()