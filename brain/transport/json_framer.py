import json

from ..errors import ProtocolError


class JsonFramer:
    def __init__(self, max_buffer_size: int = 1048576) -> None:
        self._buffer = ""
        self._max_buffer_size = max_buffer_size

    def feed(self, chunk: str) -> list[str]:
        self._buffer += chunk
        messages: list[str] = []
        while True:
            start = self._buffer.find("{")
            if start < 0:
                self._buffer = ""
                break
            if start > 0:
                self._buffer = self._buffer[start:]
            try:
                value, end = json.JSONDecoder().raw_decode(self._buffer)
            except json.JSONDecodeError:
                if len(self._buffer) > self._max_buffer_size:
                    raise ProtocolError("接收缓冲区超过上限")
                break
            if not isinstance(value, dict):
                self._buffer = self._buffer[end:]
                continue
            messages.append(self._buffer[:end])
            self._buffer = self._buffer[end:]
        return messages

    def reset(self) -> None:
        self._buffer = ""