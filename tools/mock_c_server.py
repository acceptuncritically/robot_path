import argparse
import codecs
import json
import socket
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from brain.errors import ProtocolError
from brain.grid import find_path
from brain.protocol import (
    STATUS_FAIL,
    STATUS_RUNNING,
    PathPoint,
    Target,
    parse_target_message,
)
from brain.transport.json_framer import JsonFramer

MODES = ("normal", "fail", "timeout", "malformed", "unknown_status")
C_OUTPUT_HEADER = "===== 上报JSON ====="


def format_c_output(status: str, points: list[PathPoint]) -> str:
    payload = {"path": [point.to_dict() for point in points], "status": status}
    return C_OUTPUT_HEADER + "\n" + json.dumps(payload, ensure_ascii=False, indent=4) + "\n"


class MockCServer:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9000,
        mode: str = "normal",
        verbose: bool = True,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"不支持的场景: {mode}")
        self.host = host
        self._requested_port = port
        self.mode = mode
        self.verbose = verbose
        self._server_socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._actual_port = port

    @property
    def port(self) -> int:
        return self._actual_port

    def start(self) -> int:
        if self._thread is not None:
            return self._actual_port
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server_socket.bind((self.host, self._requested_port))
        except OSError as exc:
            server_socket.close()
            raise OSError(f"监听失败: {exc}") from exc
        server_socket.listen(1)
        server_socket.settimeout(0.2)
        self._actual_port = server_socket.getsockname()[1]
        self._server_socket = server_socket
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self._actual_port

    def stop(self) -> None:
        self._stop_event.set()
        server_socket = self._server_socket
        self._server_socket = None
        if server_socket is not None:
            try:
                server_socket.close()
            except OSError:
                pass
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def __enter__(self) -> "MockCServer":
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        self.stop()
        return False

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message)

    def _serve(self) -> None:
        server_socket = self._server_socket
        if server_socket is None:
            return
        while not self._stop_event.is_set():
            try:
                connection, address = server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                self._handle_client(connection, address)

    def _handle_client(self, connection: socket.socket, address: tuple[str, int]) -> None:
        self._log(f"[模拟C端] 客户端已连接 {address}")
        connection.settimeout(0.2)
        framer = JsonFramer()
        decoder = codecs.getincrementaldecoder("utf-8")()
        try:
            while not self._stop_event.is_set():
                try:
                    chunk = connection.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                try:
                    text = decoder.decode(chunk)
                except UnicodeDecodeError:
                    break
                for message in framer.feed(text):
                    self._handle_message(connection, message)
        finally:
            self._log(f"[模拟C端] 客户端已断开 {address}")

    def _handle_message(self, connection: socket.socket, message: str) -> None:
        self._log(f"[模拟C端] 收到报文 {message.strip()}")
        if self.mode == "timeout":
            return
        if self.mode == "malformed":
            self._send(connection, '{"status": "running", "path": "bad"}')
            return
        if self.mode == "unknown_status":
            self._send(connection, '{"status":"paused","path":[]}')
            return
        try:
            target = parse_target_message(message)
        except ProtocolError:
            self._send(connection, format_c_output(STATUS_FAIL, []))
            return
        if self.mode == "fail":
            self._send(connection, format_c_output(STATUS_FAIL, []))
            return
        points = find_path(target)
        if points is None:
            self._send(connection, format_c_output(STATUS_FAIL, []))
            return
        self._send(connection, format_c_output(STATUS_RUNNING, points))

    def _send(self, connection: socket.socket, message: str) -> None:
        if not message.endswith("\n"):
            message += "\n"
        try:
            connection.sendall(message.encode("utf-8"))
        except OSError:
            pass


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python tools/mock_c_server.py",
        description="模拟 C 端 TCP 服务器",
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=9000, help="监听端口")
    parser.add_argument("--mode", choices=MODES, default="normal", help="行为模式")
    parser.add_argument("--quiet", action="store_true", help="不输出日志")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    server = MockCServer(host=args.host, port=args.port, mode=args.mode, verbose=not args.quiet)
    try:
        port = server.start()
    except OSError as exc:
        print(f"启动失败: {exc}", file=sys.stderr)
        return 2
    print("=" * 64)
    print("模拟 C 端 TCP 服务器已启动")
    print(f"监听地址: {args.host}:{port}")
    print(f"行为模式: {args.mode}")
    print(f"联调命令: python -m brain --transport tcp --tcp-port {port}")
    print("按 Ctrl+C 停止")
    print("=" * 64)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n正在停止")
    finally:
        server.stop()
    print("已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())