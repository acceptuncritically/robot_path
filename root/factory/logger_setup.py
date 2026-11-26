"""
TCP：把每条日志通过 socket 发到日志服务（默认 127.0.0.1:9100）。
  日志服务没启动也没关系，会自动跳过，不影响主程序。
"""
import logging
import socket
import os
from get_path import get_abs_path
import time
from datetime import datetime
from pathlib import Path
#日志保存的根目录
LOG_ROOT =get_abs_path('log')
#确保日志的目录存在,如果不存在则创建在本文件的同级目录下
os.makedirs(LOG_ROOT,exist_ok=True)
DEFAULT_LOG_FORMAT =logging.Formatter(
    '%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')


class TcpHandler(logging.Handler):
    """把日志发给 TCP 日志服务。连不上就跳过，10 秒后再试。"""

    def __init__(self, host, port):
        # 调用父类的构造函数，由于子类重新定义了init，会覆盖父类的init
        super().__init__()
        self.host = host
        self.port = port

        self.socket = None
        self.next_try = 0.0

    def emit(self, record):
        """
        一个带有重连和冷却机制的网络发送流程
        :param record:
        :return:
        """
        try:
            # 检查连接
            if self.socket is None:
                # 冷却期检查，防止网络断开程序卡死
                if time.time() < self.next_try:
                    return
                # 没出问题就去连接远程服务器
                self.socket = socket.create_connection((self.host, self.port), timeout=0.5)
            text = self.format(record) + "\n"
            # 发送日志
            self.socket.sendall(text.encode("utf-8"))
        except Exception:
            self.socket = None
            self.next_try = time.time() + 10  # 10 秒内不再重连，免得每条日志都卡 0.5 秒

    def close(self):
        if self.socket is not None:
            try:
                self.socket.close()
            except OSError:
                pass
            self.socket = None
        # 为self._closed设置为True，防止再次往里写日志并释放内部锁
        super().close()


def setup_logger(log_file=None,name="robot",):
    """
    创建 logger：控制台 + 文件 + TCP，三个 handler 都是 DEBUG
    :param log_file:日志文件名，将日志写在哪里
    :return:
    """

    file_level = logging.DEBUG
    console_level = logging.INFO
    # 获取或创建一个名为 name 的 Logger 对象，当 name 存在时，返回该 Logger 对象，否则创建一个新的 Logger 对象
    logger = logging.getLogger(name)
    # 设置这个 Logger 对象的最低日志门槛级别 保证debug以上的日志都能够记录
    logger.setLevel(logging.DEBUG)
    # 避免重复添加handler
    # 配置一个控制台的handler
    if logger.handlers:
        return logger
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(DEFAULT_LOG_FORMAT)
    logger.addHandler(console_handler)  # 将handler挂到logger上
    # 配置一个文件的handler
    if not log_file:
        log_file = os.path.join(LOG_ROOT, f"{name}_{datetime.now().strftime('%Y-%m-%d')}.log")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(file_level)
    file_handler.setFormatter(DEFAULT_LOG_FORMAT)
    logger.addHandler(file_handler)  # 将handler挂到logger上
    return logger

    #
    # if use_tcp:
    #     tcp_handler = TcpHandler(tcp_host, tcp_port)
    #     tcp_handler.setLevel(logging.DEBUG)
    #     tcp_handler.setFormatter(formatter)
    #     logger.addHandler(tcp_handler)
    #
    # return logger


def run_log_server(host="127.0.0.1", port=9100):
    """最简单的 TCP 日志接收端：收到日志就打印出来。"""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(5)
    server.settimeout(1)
    print(f"TCP 日志服务已启动，监听{host},{port}，按 Ctrl+C 停止")

    clients = []
    try:
        while True:
            try:
                client, address = server.accept()
                print("[日志服务] 客户端已连接", address)
                clients.append(client)
            except socket.timeout:
                pass
            """
            Exception  # 1. 最顶层，兜底所有常规错误
                OSError  # 2. 网络/系统错误（父类）
                    BlockingIOError  # 3. 非阻塞无数据（子类，非真错误）
            """
            # 读一下已连接客户端发来的日志
            # 如果不用try 去包裹会异常穿透到了最外层的 except Exception，随后触发了 client.close() 的未定义错误。
            try:
                """
                和异步的区别      回答的问题
                    阻塞 非阻塞 I/O调用要不要等  套接字/系统调用层
                    同步 异步   操作完成怎么通知和执行  程序控制流/编程模型层
                 """

                client.setblocking(False)
                data = client.recv(4096)
            except BlockingIOError:
                # 非阻塞模式下没读到数据，继续下一个循环即可
                pass
                if not data:
                    # 客户端正常断开
                    clients.remove(client)
                    client.close()
                    continue

                # 正常处理数据
                for line in data.decode("utf-8", "replace").splitlines():
                    print("[TCP日志]", line)

            except OSError as e:
                # 捕获所有的网络/IO错误（包含了除了BlockingIOError之外的所有网络异常）
                print(f"客户端连接异常: {e}")
                clients.remove(client)
                client.close()  # 注意：这里必须加上 close()，防止资源泄漏

            except Exception as e:
                # 最大的兜底异常，捕获所有意料之外的错误
                print(f"\n程序发生未知异常，正在停止: {e}")
    finally:
        server.close()
if __name__ == "__main__":
    run_log_server()