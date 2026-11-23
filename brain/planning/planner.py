import logging
from dataclasses import dataclass

from ..errors import (
    LLMError,
    LLMOutputError,
    PlanningError,
    TargetOutOfRangeError,
    TargetUncertainError,
)
from ..llm.base import LLMClient
from ..prompt import SYSTEM_PROMPT, build_retry_message, build_user_message
from ..protocol import Target
from .output_parser import parse_target_from_output

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlanResult:
    target: Target
    attempts: int
    raw_outputs: tuple[str, ...]


class TargetPlanner:
    def __init__(self, llm_client: LLMClient, max_retries: int = 2) -> None:
        if max_retries < 0:
            raise ValueError("max_retries 不能为负数")
        self._llm_client = llm_client
        self._max_retries = max_retries

    @property
    def llm_client(self) -> LLMClient:
        return self._llm_client

    @property
    def max_retries(self) -> int:
        return self._max_retries

    def plan(self, instruction: str) -> PlanResult:
        text = (instruction or "").strip()
        if not text:
            raise PlanningError("指令为空", kind="format", attempts=0)
        raw_outputs: list[str] = []
        last_error: LLMOutputError | None = None
        user_message = build_user_message(text)
        total_attempts = self._max_retries + 1
        for attempt in range(1, total_attempts + 1):
            try:
                raw_output = self._llm_client.complete(SYSTEM_PROMPT, user_message)
            except LLMError as exc:
                raise PlanningError(str(exc), kind="llm", attempts=attempt) from exc
            raw_outputs.append(raw_output)
            logger.debug("第 %d 次大模型输出: %r", attempt, raw_output)
            try:
                target = parse_target_from_output(raw_output)
            except TargetUncertainError as exc:
                raise PlanningError(
                    exc.message,
                    kind="uncertain",
                    attempts=attempt,
                    raw_output=raw_output,
                ) from exc
            except LLMOutputError as exc:
                last_error = exc
                logger.warning("第 %d 次输出不可用: %s", attempt, exc.message)
                if attempt < total_attempts:
                    user_message = build_retry_message(text, exc.message, raw_output)
                continue
            return PlanResult(
                target=target,
                attempts=attempt,
                raw_outputs=tuple(raw_outputs),
            )
        kind = "range" if isinstance(last_error, TargetOutOfRangeError) else "format"
        message = last_error.message if last_error is not None else "输出解析失败"
        raise PlanningError(
            message,
            kind=kind,
            attempts=total_attempts,
            raw_output=raw_outputs[-1] if raw_outputs else "",
        )