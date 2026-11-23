import logging
import threading
from dataclasses import dataclass
from enum import Enum

from .errors import (
    PlanningError,
    ProtocolError,
    SessionBusyError,
    SessionClosedError,
    TransportError,
)
from .feedback import FeedbackRenderer
from .planning.planner import TargetPlanner
from .protocol import RobotReport, Target, build_target_message, parse_robot_report
from .transport.base import Transport

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    RUNNING = "running"
    FAIL = "fail"
    INVALID_INSTRUCTION = "invalid_instruction"
    LLM_ERROR = "llm_error"
    TRANSPORT_ERROR = "transport_error"
    PROTOCOL_ERROR = "protocol_error"
    TIMEOUT = "timeout"

    @property
    def is_ok(self) -> bool:
        return self in (TaskStatus.RUNNING, TaskStatus.FAIL)


@dataclass(frozen=True)
class TaskOutcome:
    status: TaskStatus
    user_message: str
    target: Target | None = None
    report: RobotReport | None = None
    raw_report: str | None = None
    attempts: int = 0

    @property
    def is_ok(self) -> bool:
        return self.status.is_ok


class BrainSession:
    def __init__(
        self,
        planner: TargetPlanner,
        transport: Transport,
        feedback: FeedbackRenderer | None = None,
        report_timeout: float = 5.0,
    ) -> None:
        if report_timeout <= 0:
            raise ValueError("report_timeout 必须大于 0")
        self._planner = planner
        self._transport = transport
        self._feedback = feedback or FeedbackRenderer()
        self._report_timeout = report_timeout
        self._lock = threading.Lock()
        self._state = "IDLE"
        self._closed = False
        self._last_outcome: TaskOutcome | None = None
        self._task_count = 0

    @property
    def state(self) -> str:
        return self._state

    @property
    def last_outcome(self) -> TaskOutcome | None:
        return self._last_outcome

    @property
    def task_count(self) -> int:
        return self._task_count

    @property
    def planner(self) -> TargetPlanner:
        return self._planner

    @property
    def transport(self) -> Transport:
        return self._transport

    @property
    def feedback(self) -> FeedbackRenderer:
        return self._feedback

    @property
    def report_timeout(self) -> float:
        return self._report_timeout

    def open(self) -> None:
        if self._closed:
            raise SessionClosedError("会话已关闭")
        self._transport.open()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._transport.close()
        except TransportError as exc:
            logger.warning("关闭传输层失败: %s", exc)

    def handle_instruction(self, instruction: str) -> TaskOutcome:
        if self._closed:
            raise SessionClosedError("会话已关闭")
        if not self._lock.acquire(blocking=False):
            raise SessionBusyError("上一条指令尚未处理完成")
        try:
            self._state = "PLANNING"
            try:
                plan = self._planner.plan(instruction)
            except PlanningError as error:
                status = TaskStatus.LLM_ERROR if error.kind == "llm" else TaskStatus.INVALID_INSTRUCTION
                logger.warning("规划失败 kind=%s attempts=%d message=%s", error.kind, error.attempts, error.message)
                return self._finish(
                    TaskOutcome(
                        status=status,
                        user_message=self._feedback.planning_error(error),
                        attempts=error.attempts,
                    )
                )
            target = plan.target
            logger.info("目标坐标 %s", target)
            self._drain_stale_reports()
            self._state = "SENDING"
            try:
                message = build_target_message(target)
            except (TypeError, ValueError) as exc:
                logger.error("组装下发报文失败: %s", exc)
                return self._finish(
                    TaskOutcome(
                        status=TaskStatus.INVALID_INSTRUCTION,
                        user_message=f"目标坐标非法，未发送：{exc}",
                        target=target,
                        attempts=plan.attempts,
                    )
                )
            try:
                self._transport.send_message(message)
            except TransportError as error:
                logger.error("发送报文失败: %s", error)
                return self._finish(
                    TaskOutcome(
                        status=TaskStatus.TRANSPORT_ERROR,
                        user_message=self._feedback.transport_error(error),
                        target=target,
                        attempts=plan.attempts,
                    )
                )
            logger.info("已发送目标报文: %s", message.strip())
            self._state = "WAITING_REPORT"
            try:
                raw_report = self._transport.recv_message(self._report_timeout)
            except TransportError as error:
                logger.error("接收回包失败: %s", error)
                return self._finish(
                    TaskOutcome(
                        status=TaskStatus.TRANSPORT_ERROR,
                        user_message=self._feedback.transport_error(error),
                        target=target,
                        attempts=plan.attempts,
                    )
                )
            if raw_report is None:
                logger.warning("等待回包超时 %.1f 秒", self._report_timeout)
                return self._finish(
                    TaskOutcome(
                        status=TaskStatus.TIMEOUT,
                        user_message=self._feedback.timeout(self._report_timeout),
                        target=target,
                        attempts=plan.attempts,
                    )
                )
            logger.info("收到回包: %s", raw_report)
            try:
                report = parse_robot_report(raw_report)
            except ProtocolError as error:
                logger.warning("回包协议错误: %s", error.message)
                return self._finish(
                    TaskOutcome(
                        status=TaskStatus.PROTOCOL_ERROR,
                        user_message=self._feedback.protocol_error(error),
                        target=target,
                        raw_report=raw_report,
                        attempts=plan.attempts,
                    )
                )
            if report.is_running:
                outcome = TaskOutcome(
                    status=TaskStatus.RUNNING,
                    user_message=self._feedback.running(report, target),
                    target=target,
                    report=report,
                    raw_report=raw_report,
                    attempts=plan.attempts,
                )
            else:
                outcome = TaskOutcome(
                    status=TaskStatus.FAIL,
                    user_message=self._feedback.fail(),
                    target=target,
                    report=report,
                    raw_report=raw_report,
                    attempts=plan.attempts,
                )
            return self._finish(outcome)
        finally:
            self._state = "IDLE"
            self._lock.release()

    def _drain_stale_reports(self) -> list[str]:
        try:
            discarded = self._transport.drain()
        except TransportError as exc:
            logger.warning("清理残留报文失败: %s", exc)
            return []
        if discarded:
            logger.warning("已丢弃 %d 条残留回包", len(discarded))
        return discarded

    def _finish(self, outcome: TaskOutcome) -> TaskOutcome:
        self._state = "IDLE"
        self._last_outcome = outcome
        self._task_count += 1
        logger.info("任务结束 status=%s", outcome.status.value)
        return outcome