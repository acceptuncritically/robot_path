import codecs
import time
from collections import deque

from ..errors import TransportError
from .base import Transport
from .json_framer import JsonFramer


class SerialTransport(Transport):
    name = "serial"

    def __init__(self, port: str, baudrate: int = 115200, read_timeout: float = 0.05) -> None:
        self._port = port
        self._baudrate = baudrate
        self._read_timeout = read_timeout
        self._serial = None
        self._framer = JsonFramer()
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._pending_messages: deque[str] = deque()

    def describe(self) -> str:
        return f"串口 {self._port} {self._baudrate}bps"

    @property
    def is_open(self) -> bool:
        return self._serial is not None

    def open(self) -> None:
        if self._serial is not None:
            return
        try:
            import serial
        except ImportError as exc:
            raise TransportError("串口功能需要先安装 pyserial") from exc
        try:
            self._serial = serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self._read_timeout,
                write_timeout=1.0,
            )
        except Exception as exc:
            raise TransportError(f"串口打开失败: {exc}") from exc
        self._framer.reset()
        self._decoder.reset()
        self._pending_messages.clear()

    def close(self) -> None:
        serial_port = self._serial
        self._serial = None
        self._pending_messages.clear()
        self._framer.reset()
        if serial_port is None:
            return
        try:
            serial_port.close()
        except Exception:
            pass

    def send_message(self, message: str) -> None:
        serial_port = self._require_serial()
        data = message.encode("utf-8")
        if not data.endswith(b"\n"):
            data += b"\n"
        try:
            serial_port.write(data)
            serial_port.flush()
        except Exception as exc:
            self._mark_broken()
            raise TransportError(f"串口发送失败: {exc}") from exc

    def recv_message(self, timeout: float) -> str | None:
        serial_port = self._require_serial()
        if self._pending_messages:
            return self._pending_messages.popleft()
        deadline = time.monotonic() + max(timeout, 0.0)
        while True:
            try:
                chunk = serial_port.read(1)
            except Exception as exc:
                self._mark_broken()
                raise TransportError(f"串口接收失败: {exc}") from exc
            if chunk:
                text = self._decoder.decode(chunk)
                self._pending_messages.extend(self._framer.feed(text))
                if self._pending_messages:
                    return self._pending_messages.popleft()
                continue
            if time.monotonic() >= deadline:
                return None

    def _require_serial(self):
        if self._serial is None:
            raise TransportError("串口尚未打开")
        return self._serial

    def _mark_broken(self) -> None:
        serial_port = self._serial
        self._serial = None
        self._pending_messages.clear()
        self._framer.reset()
        if serial_port is not None:
            try:
                serial_port.close()
            except Exception:
                pass