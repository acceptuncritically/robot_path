import unittest

from brain.errors import (
    MalformedReportError,
    PlanningError,
    TransportError,
    UnknownStatusError,
)
from brain.feedback import FeedbackRenderer
from brain.protocol import PathPoint, RobotReport, Target


def make_report(*points: tuple[int, int]) -> RobotReport:
    return RobotReport(status="running", points=tuple(PathPoint(x=x, y=y) for x, y in points))


class FeedbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.feedback = FeedbackRenderer()

    def test_running_message(self) -> None:
        message = self.feedback.running(make_report((0, 0), (1, 0), (1, 1)), Target(1, 1))
        self.assertIn("已规划路线", message)
        self.assertIn("[(0,0),(1,0),(1,1)]", message)
        self.assertIn("共 2 步", message)

    def test_running_single_point(self) -> None:
        message = self.feedback.running(make_report((3, 2)))
        self.assertIn("无需移动", message)

    def test_fail_message(self) -> None:
        self.assertIn("阻挡", self.feedback.fail())

    def test_planning_uncertain(self) -> None:
        message = self.feedback.planning_error(PlanningError("无法确定", kind="uncertain", attempts=1))
        self.assertIn("无法确定目标", message)

    def test_planning_range(self) -> None:
        message = self.feedback.planning_error(PlanningError("坐标超出", kind="range", attempts=3))
        self.assertIn("超出迷宫范围", message)

    def test_planning_llm(self) -> None:
        message = self.feedback.planning_error(PlanningError("网络错误", kind="llm", attempts=1))
        self.assertIn("大模型调用失败", message)

    def test_planning_format(self) -> None:
        message = self.feedback.planning_error(PlanningError("无法解析", kind="format", attempts=3))
        self.assertIn("无法理解", message)

    def test_protocol_unknown_status(self) -> None:
        message = self.feedback.protocol_error(UnknownStatusError("paused"))
        self.assertIn("未知状态", message)
        self.assertIn("paused", message)

    def test_protocol_generic(self) -> None:
        message = self.feedback.protocol_error(MalformedReportError("不是 JSON"))
        self.assertIn("格式异常", message)

    def test_transport_error(self) -> None:
        message = self.feedback.transport_error(TransportError("连接失败"))
        self.assertIn("通信异常", message)
        self.assertIn("连接失败", message)

    def test_timeout(self) -> None:
        self.assertIn("5 秒", self.feedback.timeout(5))
        self.assertIn("1.5 秒", self.feedback.timeout(1.5))

    def test_goodbye_and_help(self) -> None:
        self.assertIn("再见", self.feedback.goodbye())
        self.assertIn("右下角", self.feedback.help_text())


if __name__ == "__main__":
    unittest.main()