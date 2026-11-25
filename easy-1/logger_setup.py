"""日志模块（简化版）：DEBUG 级别，同时输出到控制台、文件和 TCP。

- 控制台：运行程序时直接看到；
- 文件：easy-1/logs/brain.log；
- TCP：把每条日志通过 socket 发到日志服务（默认 127.0.0.1:9100）。
  日志服务没启动也没关系，会自动跳过，不影响主程序。

单独运行本文件可以起一个最简单的 TCP 日志接收端：
    python logger_setup.py
"""
import logging
import socket
import sys
import time
from pathlib import Path

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"


class TcpHandler(logging.Handler):
    """把日志发给 TCP 日志服务。连不上就跳过，10 秒后再试。"""

    def __init__(self, host, port):
        super().__init__()
        self.host = host
        self.port = port
        self.sock = None
        self.next_try = 0.0

    def emit(self, record):
        try:
            if self.sock is None:
                if time.time() < self.next_try:
                    return
                self.sock = socket.create_connection((self.host, self.port), timeout=0.5)
            text = self.format(record) + "\n"
            self.sock.sendall(text.encode("utf-8"))
        except OSError:
            self.sock = None
            self.next_try = time.time() + 10  # 10 秒内不再重连，免得每条日志都卡 0.5 秒

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
        super().close()


def setup_logger(log_dir=None, use_tcp=True, tcp_host="127.0.0.1", tcp_port=9100):
    """创建 logger：控制台 + 文件 + TCP，三个 handler 都是 DEBUG（最低级别）。"""
    if log_dir is None:
        log_dir = Path(__file__).resolve().parent / "logs"
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("simple_brain")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT)

    # 1. 控制台
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # 2. 文件
    file_handler = logging.FileHandler(log_dir / "brain.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 3. TCP（可以关掉）
    if use_tcp:
        tcp_handler = TcpHandler(tcp_host, tcp_port)
        tcp_handler.setLevel(logging.DEBUG)
        tcp_handler.setFormatter(formatter)
        logger.addHandler(tcp_handler)

    return logger


def run_log_server(host="127.0.0.1", port=9100):
    """最简单的 TCP 日志接收端：收到日志就打印出来。"""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(5)
    server.settimeout(0.5)
    print("TCP 日志服务已启动，监听 %s:%d，按 Ctrl+C 停止" % (host, port))

    clients = []
    try:
        while True:
            try:
                client, address = server.accept()
                print("[日志服务] 客户端已连接", address)
                clients.append(client)
            except socket.timeout:
                pass

            # 读一下已连接客户端发来的日志
            for client in list(clients):
                try:
                    client.setblocking(False)
                    data = client.recv(4096)
                    if not data:
                        clients.remove(client)
                        client.close()
                        continue
                    for line in data.decode("utf-8", "replace").splitlines():
                        print("[TCP日志]", line)
                except BlockingIOError:
                    pass
                except OSError:
                    clients.remove(client)
    except KeyboardInterrupt:
        print("\n正在停止")
    finally:
        server.close()
        for client in clients:
            client.close()


if __name__ == "__main__":
    run_log_server()