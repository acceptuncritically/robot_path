from abc import ABC, abstractmethod


class LLMClient(ABC):
    name = "base"

    @abstractmethod
    def complete(self, system_prompt: str, user_message: str) -> str:
        raise NotImplementedError

    def describe(self) -> str:
        return self.name