import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from ..errors import LLMError
from .base import LLMClient


@dataclass(frozen=True)
class OpenAIClientConfig:
    base_url: str
    model: str
    api_key: str = ""
    timeout: float = 30.0
    max_retries: int = 2
    temperature: float = 0.0
    max_tokens: int = 128


class _NonRetryableError(LLMError):
    pass


class OpenAICompatibleClient(LLMClient):
    name = "openai"

    def __init__(self, config: OpenAIClientConfig) -> None:
        self._config = config
        self._endpoint = config.base_url.rstrip("/") + "/chat/completions"

    def describe(self) -> str:
        return f"OpenAI 兼容接口 {self._config.base_url} 模型 {self._config.model}"

    def complete(self, system_prompt: str, user_message: str) -> str:
        payload = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        last_error: LLMError | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                return self._request(data, headers)
            except _NonRetryableError as exc:
                raise LLMError(exc.message) from exc
            except LLMError as exc:
                last_error = exc
                if attempt < self._config.max_retries:
                    time.sleep(min(2 ** attempt, 4))
        raise last_error or LLMError("调用大模型失败")

    def _request(self, data: bytes, headers: dict[str, str]) -> str:
        request = urllib.request.Request(self._endpoint, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self._config.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
            except OSError:
                detail = ""
            message = f"HTTP {exc.code}: {detail or exc.reason}"
            if exc.code in (400, 401, 403, 404, 422):
                raise _NonRetryableError(message) from exc
            raise LLMError(message) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LLMError(f"请求失败: {exc}") from exc
        return self._extract_content(body)

    @staticmethod
    def _extract_content(body: str) -> str:
        try:
            payload = json.loads(body)
            content = payload["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("大模型响应结构异常") from exc
        if not isinstance(content, str):
            raise LLMError("大模型响应内容类型异常")
        return content