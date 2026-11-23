import re
from typing import Sequence

from .base import LLMClient

COORDINATE_PATTERNS = (
    re.compile(r"[（(]\s*(\d+)\s*[，,]\s*(\d+)\s*[)）]"),
    re.compile(r"坐标\s*[（(]?\s*(\d+)\s*[，,]\s*(\d+)"),
    re.compile(r"(\d+)\s*[，,]\s*(\d+)"),
)
ROW_COLUMN_PATTERN = re.compile(r"第\s*(\d+)\s*行\s*第\s*(\d+)\s*列")
KEYWORD_TARGETS = (
    ("右下角", (5, 5)),
    ("右上角", (0, 5)),
    ("左下角", (5, 0)),
    ("左上角", (0, 0)),
    ("起点对面", (5, 5)),
    ("回到起点", (0, 0)),
    ("回起点", (0, 0)),
    ("原点", (0, 0)),
    ("起点", (0, 0)),
    ("正中央", (2, 2)),
    ("中心", (2, 2)),
    ("中间", (2, 2)),
)
UNCERTAIN_WORDS = ("随便", "不知道", "不确定", "无所谓")
INSTRUCTION_PATTERN = re.compile(r"用户指令[:：]\s*(.+)")


class MockLLMClient(LLMClient):
    name = "mock"

    def __init__(self, scripted_outputs: Sequence[str] | None = None) -> None:
        self._scripted_outputs = list(scripted_outputs or [])
        self.calls: list[str] = []

    def complete(self, system_prompt: str, user_message: str) -> str:
        self.calls.append(user_message)
        if self._scripted_outputs:
            return self._scripted_outputs.pop(0)
        return self._build_response(user_message)

    @staticmethod
    def _extract_instruction(user_message: str) -> str:
        match = INSTRUCTION_PATTERN.search(user_message)
        if match is None:
            return user_message.strip()
        instruction = match.group(1).strip()
        return instruction.splitlines()[0].strip() if instruction else ""

    def _build_response(self, user_message: str) -> str:
        instruction = self._extract_instruction(user_message)
        row_column = ROW_COLUMN_PATTERN.search(instruction)
        if row_column is not None:
            return self._to_json(int(row_column.group(1)) - 1, int(row_column.group(2)) - 1)
        for pattern in COORDINATE_PATTERNS:
            match = pattern.search(instruction)
            if match is not None:
                return self._to_json(int(match.group(1)), int(match.group(2)))
        for keyword, (x, y) in KEYWORD_TARGETS:
            if keyword in instruction:
                return self._to_json(x, y)
        if any(word in instruction for word in UNCERTAIN_WORDS):
            return '{"target_x": -1, "target_y": -1}'
        return "我不确定目标位置，请告诉我具体坐标或方位。"

    @staticmethod
    def _to_json(x: int, y: int) -> str:
        return f'{{"target_x": {x}, "target_y": {y}}}'