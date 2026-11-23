from abc import ABC, abstractmethod
from typing import Any


class Transport(ABC):
    name = "base"

    @abstractmethod
    def open(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def send_message(self, message: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def recv_message(self, timeout: float) -> str | None:
        raise NotImplementedError

    @property
    def is_open(self) -> bool:
        return False

    def drain(self, timeout: float = 0.05, max_messages: int = 20) -> list[str]:
        messages: list[str] = []
        for _ in range(max_messages):
            message = self.recv_message(timeout)
            if message is None:
                break
            if message.strip():
                messages.append(message)
        return messages

    def describe(self) -> str:
        return self.name

    def __enter__(self) -> "Transport":
        self.open()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        self.close()
        return False