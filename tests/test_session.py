import threading
import unittest

from brain.errors import (
    LLMError,
    SessionBusyError,
    SessionClosedError,
    TransportError,
)
from brain.feedback import FeedbackRenderer
from brain.llm.base import LLMClient
from brain.llm.mock_client import MockLLMClient
from brain.planning.planner import TargetPlanner
from brain.protocol import PathPoint, Target
from brain.session import BrainSession, TaskStatus
from brain.transport.mock_transport import MockTransport


class FailingLLM(LLMClient):
    name = "failing"

    def complete(self, system_prompt: str, user_message: str) -> str:
        raise LLMError("模拟大模型故障")


class BlockingTransport(MockTransport):
    def __init__(self) -> None:
        super().__init__()
        self.recv_started = threading.Event()
        self.release_recv = threading.Event()

    def drain(self, timeout: float = 0.05, max_messages: int = 20) -> list[str]:
        return []

    def recv_message(self, timeout: float) -> str | None:
        self.recv_started.set()
        self.release_recv.wait(5.0)
        return super().recv_message(timeout)


class LateReplyTransport(MockTransport):
    def __init__(self) -> None:
        super().__init__()
        self._drain_calls = 0
        self._held_report: str | None = None

    def drain(self, timeout: float = 0.05, max_messages: int = 20) -> list[str]:
        self._drain_calls += 1
        if self._held_report is not None:
            held, self._held_report = self._held_report, None
            return [held]
        return []

    def recv_message(self, timeout: float) -> str | None:
        if self._drain_calls == 1 and self._held_report is None:
            self._held_report = super().recv_message(timeout)
            return None
        return super().recv_message(timeout)


class OpenFailingTransport(MockTransport):
    def open(self) -> None:
        raise TransportError("模拟连接失败")


def make_session(
    llm_client: LLMClient | None = None,
    transport: MockTransport | None = None,
    report_timeout: float = 1.0,
) -> BrainSession:
    return BrainSession(
        planner=TargetPlanner(llm_client or MockLLMClient(), max_retries=2),
        transport=transport or MockTransport(),
        feedback=FeedbackRenderer(),
        report_timeout=report_timeout,
    )


class SessionSuccessTests(unittest.TestCase):
    def test_running_outcome(self) -> None:
        transport = MockTransport()
        session = make_session(transport=transport)
        session.open()
        self.addCleanup(session.close)
        outcome = session.handle_instruction("去迷宫右下角")
        self.assertEqual(outcome.status, TaskStatus.RUNNING)
        self.assertTrue(outcome.is_ok)
        self.assertEqual(outcome.target, Target(5, 5))
        self.assertIsNotNone(outcome.report)
        self.assertEqual(outcome.report.points[-1], PathPoint(5, 5))
        self.assertIn("已规划路线", outcome.user_message)
        self.assertEqual(transport.sent_messages, ['{"target_x":5,"target_y":5}\n'])
        self.assertEqual(session.state, "IDLE")
        self.assertEqual(session.task_count, 1)
        self.assertIs(session.last_outcome, outcome)

    def test_fail_outcome(self) -> None:
        session = make_session()
        session.open()
        self.addCleanup(session.close)
        outcome = session.handle_instruction("去(2,1)")
        self.assertEqual(outcome.status, TaskStatus.FAIL)
        self.assertTrue(outcome.is_ok)
        self.assertIn("阻挡", outcome.user_message)

    def test_already_at_target(self) -> None:
        session = make_session()
        session.open()
        self.addCleanup(session.close)
        outcome = session.handle_instruction("回到(0,0)起点")
        self.assertEqual(outcome.status, TaskStatus.RUNNING)
        self.assertIn("无需移动", outcome.user_message)

    def test_retry_then_success(self) -> None:
        client = MockLLMClient(
            scripted_outputs=['{"target_x": 9, "target_y": 9}', '{"target_x": 3, "target_y": 2}']
        )
        transport = MockTransport()
        session = make_session(llm_client=client, transport=transport)
        session.open()
        self.addCleanup(session.close)
        outcome = session.handle_instruction("去(9,9)")
        self.assertEqual(outcome.status, TaskStatus.RUNNING)
        self.assertEqual(outcome.attempts, 2)
        self.assertEqual(transport.sent_messages, ['{"target_x":3,"target_y":2}\n'])


class SessionFailureTests(unittest.TestCase):
    def test_invalid_instruction_never_sends(self) -> None:
        client = MockLLMClient(scripted_outputs=["这是一段乱码"] * 3)
        transport = MockTransport()
        session = make_session(llm_client=client, transport=transport)
        session.open()
        self.addCleanup(session.close)
        outcome = session.handle_instruction("去(3,2)")
        self.assertEqual(outcome.status, TaskStatus.INVALID_INSTRUCTION)
        self.assertEqual(transport.sent_messages, [])
        self.assertIn("无法理解", outcome.user_message)

    def test_uncertain_instruction(self) -> None:
        session = make_session()
        session.open()
        self.addCleanup(session.close)
        outcome = session.handle_instruction("随便走走吧")
        self.assertEqual(outcome.status, TaskStatus.INVALID_INSTRUCTION)
        self.assertIn("无法确定目标", outcome.user_message)

    def test_llm_error(self) -> None:
        session = make_session(llm_client=FailingLLM())
        session.open()
        self.addCleanup(session.close)
        outcome = session.handle_instruction("去右下角")
        self.assertEqual(outcome.status, TaskStatus.LLM_ERROR)
        self.assertIn("大模型调用失败", outcome.user_message)

    def test_timeout(self) -> None:
        transport = MockTransport(scenario="timeout")
        session = make_session(transport=transport)
        session.open()
        self.addCleanup(session.close)
        outcome = session.handle_instruction("去(5,5)")
        self.assertEqual(outcome.status, TaskStatus.TIMEOUT)
        self.assertIn("响应", outcome.user_message)
        self.assertEqual(transport.sent_messages, ['{"target_x":5,"target_y":5}\n'])

    def test_malformed_report(self) -> None:
        session = make_session(transport=MockTransport(scenario="malformed"))
        session.open()
        self.addCleanup(session.close)
        outcome = session.handle_instruction("去(3,2)")
        self.assertEqual(outcome.status, TaskStatus.PROTOCOL_ERROR)
        self.assertIn("格式异常", outcome.user_message)

    def test_unknown_status(self) -> None:
        session = make_session(transport=MockTransport(scenario="unknown_status"))
        session.open()
        self.addCleanup(session.close)
        outcome = session.handle_instruction("去(3,2)")
        self.assertEqual(outcome.status, TaskStatus.PROTOCOL_ERROR)
        self.assertIn("未知状态", outcome.user_message)

    def test_send_error(self) -> None:
        session = make_session(transport=MockTransport(scenario="send_error"))
        session.open()
        self.addCleanup(session.close)
        outcome = session.handle_instruction("去(3,2)")
        self.assertEqual(outcome.status, TaskStatus.TRANSPORT_ERROR)
        self.assertIn("通信异常", outcome.user_message)


class SessionLifecycleTests(unittest.TestCase):
    def test_continuous_dialogue(self) -> None:
        transport = MockTransport()
        session = make_session(transport=transport)
        session.open()
        first = session.handle_instruction("去(2,1)")
        second = session.handle_instruction("去(5,5)")
        self.assertEqual(first.status, TaskStatus.FAIL)
        self.assertEqual(second.status, TaskStatus.RUNNING)
        self.assertEqual(session.task_count, 2)
        self.assertEqual(len(transport.sent_messages), 2)
        session.close()

    def test_closed_session(self) -> None:
        session = make_session()
        session.open()
        session.close()
        session.close()
        with self.assertRaises(SessionClosedError):
            session.handle_instruction("去(3,2)")

    def test_busy_guard(self) -> None:
        transport = BlockingTransport()
        session = make_session(transport=transport)
        session.open()
        self.addCleanup(session.close)
        outcomes: dict[str, TaskStatus] = {}

        def worker() -> None:
            outcome = session.handle_instruction("去(5,5)")
            outcomes["status"] = outcome.status

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        self.assertTrue(transport.recv_started.wait(2.0))
        with self.assertRaises(SessionBusyError):
            session.handle_instruction("去(3,2)")
        transport.release_recv.set()
        thread.join(5.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcomes.get("status"), TaskStatus.RUNNING)
        self.assertEqual(len(transport.sent_messages), 1)

    def test_stale_reply_not_used_for_next_task(self) -> None:
        transport = LateReplyTransport()
        session = make_session(transport=transport)
        session.open()
        self.addCleanup(session.close)
        first = session.handle_instruction("去(5,5)")
        self.assertEqual(first.status, TaskStatus.TIMEOUT)
        second = session.handle_instruction("回到(0,0)起点")
        self.assertEqual(second.status, TaskStatus.RUNNING)
        self.assertIsNotNone(second.report)
        self.assertEqual((second.report.points[-1].x, second.report.points[-1].y), (0, 0))
        self.assertIn("无需移动", second.user_message)
        self.assertEqual(transport.sent_messages[-1], '{"target_x":0,"target_y":0}\n')

    def test_report_timeout_validation(self) -> None:
        with self.assertRaises(ValueError):
            make_session(report_timeout=0)

    def test_open_failure(self) -> None:
        session = make_session(transport=OpenFailingTransport())
        with self.assertRaises(TransportError):
            session.open()


if __name__ == "__main__":
    unittest.main()