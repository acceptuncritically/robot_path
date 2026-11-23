import codecs
import select
import socket
import time
from collections import deque

from ..errors import TransportClosedError, TransportError
from .base import Transport
from .json_framer import JsonFramer


class TcpTransport(Transport):
    name = "tcp"

    def __init__(self, host: str, port: int, connect_timeout: float = 3.0) -> None:
        self._host = host
        self._port = port
        self._connect_timeout = connect_timeout
        self._socket: socket.socket | None = None
        self._framer = JsonFramer()
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._pending_messages: deque[str] = deque()

    def describe(self) -> str:
        return f"TCP {self._host}:{self._port}"

    @property
    def is_open(self) -> bool:
        return self._socket is not None

    def open(self) -> None:
        if self._socket is not None:
            return
        try:
            sock = socket.create_connection((self._host, self._port), timeout=self._connect_timeout)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setblocking(True)
        except OSError as exc:
            raise TransportError(f"TCP 连接失败: {exc}") from exc
        self._socket = sock
        self._framer.reset()
        self._decoder.reset()
        self._pending_messages.clear()

    def close(self) -> None:
        sock = self._socket
        self._socket = None
        self._pending_messages.clear()
        self._framer.reset()
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    def send_message(self, message: str) -> None:
        sock = self._require_socket()
        data = message.encode("utf-8")
        if not data.endswith(b"\n"):
            data += b"\n"
        try:
            sock.sendall(data)
        except OSError as exc:
            self._mark_broken()
            raise TransportError(f"TCP 发送失败: {exc}") from exc

    def recv_message(self, timeout: float) -> str | None:
        sock = self._require_socket()
        if self._pending_messages:
            return self._pending_messages.popleft()
        deadline = time.monotonic() + max(timeout, 0.0)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                readable, _, _ = select.select([sock], [], [], remaining)
            except OSError as exc:
                raise TransportError(f"TCP 等待数据失败: {exc}") from exc
            if not readable:
                return None
            try:
                chunk = sock.recv(4096)
            except OSError as exc:
                raise TransportError(f"TCP 接收失败: {exc}") from exc
            if not chunk:
                self._mark_broken()
                raise TransportClosedError("TCP 连接已断开")
            text = self._decoder.decode(chunk)
            self._pending_messages.extend(self._framer.feed(text))
            if self._pending_messages:
                return self._pending_messages.popleft()

    def _require_socket(self) -> socket.socket:
        if self._socket is None:
            raise TransportError("TCP 连接尚未建立")
        return self._socket

    def _mark_broken(self) -> None:
        sock = self._socket
        self._socket = None
        self._pending_messages.clear()
        self._framer.reset()
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass