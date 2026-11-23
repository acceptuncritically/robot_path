import json
import unittest

from brain.errors import (
    InvalidReportPathError,
    InvalidTargetCommandError,
    MalformedReportError,
    UnknownStatusError,
)
from brain.protocol import (
    PathPoint,
    RobotReport,
    Target,
    build_report_message,
    build_target_message,
    parse_robot_report,
    parse_target_message,
)

C_RUNNING_OUTPUT = """===== 上报JSON =====
{
    "path": [
        {
            "x": 0,
            "y": 0
        },
        {
            "x": 1,
            "y": 0
        }
    ],
    "status": "running"
}
"""

C_FAIL_OUTPUT = """===== 上报JSON =====
{
    "path": [],
    "status": "fail"
}
"""

C_TAB_OUTPUT = '===== 上报JSON =====\n{\n\t"path": [\n\t\t{\n\t\t\t"x": 0,\n\t\t\t"y": 0\n\t\t}\n\t],\n\t"status": "running"\n}\n'


class TargetTests(unittest.TestCase):
    def test_valid_target(self) -> None:
        target = Target(5, 5)
        self.assertEqual(target.to_dict(), {"target_x": 5, "target_y": 5})
        self.assertEqual(str(target), "(5,5)")
        self.assertIn("第 6 行第 6 列", target.human_text())

    def test_reject_bool(self) -> None:
        with self.assertRaises(ValueError):
            Target(True, 1)
        with self.assertRaises(ValueError):
            Target(1, False)

    def test_reject_non_integer(self) -> None:
        for value in ("3", 3.0, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Target(value, 1)

    def test_reject_out_of_range(self) -> None:
        for value in (-1, 6):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Target(value, 0)


class TargetMessageTests(unittest.TestCase):
    def test_build_exact_format(self) -> None:
        self.assertEqual(build_target_message(Target(5, 5)), '{"target_x":5,"target_y":5}\n')

    def test_build_is_single_line_json(self) -> None:
        message = build_target_message(Target(0, 0))
        self.assertEqual(message.count("\n"), 1)
        self.assertEqual(json.loads(message), {"target_x": 0, "target_y": 0})

    def test_parse_valid(self) -> None:
        self.assertEqual(parse_target_message('{"target_x": 3, "target_y": 2}'), Target(3, 2))

    def test_parse_noisy_text(self) -> None:
        self.assertEqual(parse_target_message('收到指令\n{"target_x": 4, "target_y": 5}\n'), Target(4, 5))

    def test_parse_invalid_json(self) -> None:
        with self.assertRaises(MalformedReportError):
            parse_target_message("不是 JSON")

    def test_parse_missing_field(self) -> None:
        with self.assertRaises(InvalidTargetCommandError):
            parse_target_message('{"target_x": 3}')

    def test_parse_string_number(self) -> None:
        with self.assertRaises(InvalidTargetCommandError):
            parse_target_message('{"target_x": "3", "target_y": 2}')

    def test_parse_out_of_range(self) -> None:
        with self.assertRaises(InvalidTargetCommandError):
            parse_target_message('{"target_x": 6, "target_y": 2}')


class ReportMessageTests(unittest.TestCase):
    def test_parse_c_pretty_running(self) -> None:
        report = parse_robot_report(C_RUNNING_OUTPUT)
        self.assertIsInstance(report, RobotReport)
        self.assertEqual(report.status, "running")
        self.assertTrue(report.is_running)
        self.assertEqual(report.points, (PathPoint(0, 0), PathPoint(1, 0)))
        self.assertEqual(report.step_count, 1)
        self.assertEqual(report.formatted_path(), "[(0,0),(1,0)]")

    def test_parse_c_tab_format(self) -> None:
        report = parse_robot_report(C_TAB_OUTPUT)
        self.assertEqual(report.status, "running")
        self.assertEqual(report.step_count, 0)

    def test_parse_c_fail(self) -> None:
        report = parse_robot_report(C_FAIL_OUTPUT)
        self.assertEqual(report.status, "fail")
        self.assertFalse(report.is_running)
        self.assertEqual(report.points, ())

    def test_key_order_does_not_matter(self) -> None:
        report = parse_robot_report('{"status": "running", "path": [{"x": 1, "y": 2}]}')
        self.assertEqual(report.points, (PathPoint(1, 2),))

    def test_extra_fields_ignored(self) -> None:
        report = parse_robot_report(
            '{"status": "running", "path": [{"x": 1, "y": 2}], "timestamp": 123}'
        )
        self.assertEqual(report.status, "running")

    def test_malformed_json(self) -> None:
        for raw in ("", "这不是 JSON", "{"):
            with self.subTest(raw=raw), self.assertRaises(MalformedReportError):
                parse_robot_report(raw)

    def test_missing_status(self) -> None:
        with self.assertRaises(UnknownStatusError):
            parse_robot_report('{"path": []}')

    def test_unknown_status(self) -> None:
        with self.assertRaises(UnknownStatusError) as context:
            parse_robot_report('{"status": "paused", "path": []}')
        self.assertEqual(context.exception.status, "paused")

    def test_missing_path(self) -> None:
        with self.assertRaises(InvalidReportPathError):
            parse_robot_report('{"status": "running"}')

    def test_path_not_list(self) -> None:
        with self.assertRaises(InvalidReportPathError):
            parse_robot_report('{"status": "running", "path": "bad"}')

    def test_path_item_not_object(self) -> None:
        with self.assertRaises(InvalidReportPathError):
            parse_robot_report('{"status": "running", "path": [[0, 0]]}')

    def test_path_item_missing_field(self) -> None:
        with self.assertRaises(InvalidReportPathError):
            parse_robot_report('{"status": "running", "path": [{"x": 0}]}')

    def test_path_item_wrong_type(self) -> None:
        payloads = (
            '{"status": "running", "path": [{"x": true, "y": 0}]}',
            '{"status": "running", "path": [{"x": "0", "y": 0}]}',
            '{"status": "running", "path": [{"x": 0.0, "y": 0}]}',
        )
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(InvalidReportPathError):
                parse_robot_report(payload)

    def test_path_item_out_of_range(self) -> None:
        with self.assertRaises(InvalidReportPathError):
            parse_robot_report('{"status": "running", "path": [{"x": 0, "y": 6}]}')

    def test_running_requires_path(self) -> None:
        with self.assertRaises(InvalidReportPathError):
            parse_robot_report('{"status": "running", "path": []}')

    def test_fail_requires_empty_path(self) -> None:
        with self.assertRaises(InvalidReportPathError):
            parse_robot_report('{"status": "fail", "path": [{"x": 0, "y": 0}]}')

    def test_build_running(self) -> None:
        message = build_report_message("running", [(0, 0), (1, 0)])
        self.assertEqual(
            message,
            '{"path":[{"x":0,"y":0},{"x":1,"y":0}],"status":"running"}',
        )

    def test_build_fail(self) -> None:
        self.assertEqual(build_report_message("fail"), '{"path":[],"status":"fail"}')

    def test_build_invalid_status(self) -> None:
        with self.assertRaises(ValueError):
            build_report_message("paused")

    def test_build_running_without_path(self) -> None:
        with self.assertRaises(ValueError):
            build_report_message("running")

    def test_build_fail_with_path(self) -> None:
        with self.assertRaises(ValueError):
            build_report_message("fail", [(0, 0)])


if __name__ == "__main__":
    unittest.main()