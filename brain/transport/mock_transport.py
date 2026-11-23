import json
from typing import Sequence

from ..errors import ProtocolError, TransportError
from ..grid import find_path
from ..protocol import STATUS_FAIL, STATUS_RUNNING, PathPoint, Target, parse_target_message
from .base import Transport

SCENARIOS = ("normal", "fail", "timeout", "malformed", "unknown_status", "send_error")
C_OUTPUT_HEADER = "===== 上报JSON ====="


def format_c_report(status: str, points: Sequence[PathPoint]) -> str:
    payload = {"path": [point.to_dict() for point in points], "status": status}
    return C_OUTPUT_HEADER + "\n" + json.dumps(payload, ensure_ascii=False, indent=4)


class MockTransport(Transport):
    name = "mock"

    def __init__(self, scenario: str = "normal", scripted_reports: Sequence[str | None] | None = None) -> None:
        if scenario not in SCENARIOS:
            raise ValueError(f"不支持的场景: {scenario}")
        self._scenario = scenario
        self._scripted_reports = list(scripted_reports or [])
        self._opened = False
        self._pending_report: str | None = None
        self.sent_messages: list[str] = []
        self.received_targets: list[Target] = []
        self.invalid_messages: list[str] = []

    def open(self) -> None:
        self._opened = True

    def close(self) -> None:
        self._opened = False
        self._pending_report = None

    @property
    def is_open(self) -> bool:
        return self._opened

    def describe(self) -> str:
        return f"Mock 传输层（场景 {self._scenario}）"

    def send_message(self, message: str) -> None:
        self._ensure_open()
        self.sent_messages.append(message)
        if self._scenario == "send_error":
            raise TransportError("模拟发送失败")
        try:
            target = parse_target_message(message)
        except ProtocolError:
            self.invalid_messages.append(message)
            self._pending_report = None
            return
        self.received_targets.append(target)
        if self._scripted_reports:
            self._pending_report = None
            return
        self._pending_report = self._build_report(target)

    def recv_message(self, timeout: float) -> str | None:
        self._ensure_open()
        if self._scripted_reports:
            return self._scripted_reports.pop(0)
        report = self._pending_report
        self._pending_report = None
        return report

    def drain(self, timeout: float = 0.05, max_messages: int = 20) -> list[str]:
        if self._scripted_reports:
            return []
        return super().drain(timeout=timeout, max_messages=max_messages)

    def _ensure_open(self) -> None:
        if not self._opened:
            raise TransportError("Mock 传输层尚未打开")

    def _build_report(self, target: Target) -> str | None:
        if self._scenario == "timeout":
            return None
        if self._scenario == "malformed":
            return "这不是合法 JSON"
        if self._scenario == "unknown_status":
            return '{"status":"paused","path":[]}'
        if self._scenario == "fail":
            return format_c_report(STATUS_FAIL, [])
        points = find_path(target)
        if points is None:
            return format_c_report(STATUS_FAIL, [])
        return format_c_report(STATUS_RUNNING, points)