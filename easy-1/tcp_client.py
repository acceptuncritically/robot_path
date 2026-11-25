"""TCP 通信模块（简化版）：把目标坐标发给 C 端寻路程序，再把路径收回来。

协议和 C 端 tcp_server2.py 完全一致：
- 发出去：{"target_x":5,"target_y":5}   （紧凑单行 JSON，末尾加换行）
- 收回来：{"path":[{"x":0,"y":0},...],"status":"running"}
          或者 {"path":[],"status":"fail"}

坐标是 6x6 栅格：左上角 (0,0)，x 向下（行），y 向右（列），范围 0~5。
"""
import json
import socket


def check_report(data):
    """检查 C 端回包格式，不对就抛 RuntimeError（main.py 会把原因打印出来）。"""
    status = data.get("status")
    if status not in ("running", "fail"):
        raise RuntimeError("路径 JSON 格式不对：status 不合法：%r" % (status,))

    path = data.get("path")
    if not isinstance(path, list):
        raise RuntimeError("路径 JSON 格式不对：path 不是数组")

    for point in path:
        if not isinstance(point, dict):
            raise RuntimeError("路径 JSON 格式不对：path 里的点不是对象")
        x, y = point.get("x"), point.get("y")
        if type(x) is not int or type(y) is not int:
            raise RuntimeError("路径 JSON 格式不对：坐标不是整数")
        if not (0 <= x < 6 and 0 <= y < 6):
            raise RuntimeError("路径 JSON 格式不对：坐标越界")

    if status == "running" and not path:
        raise RuntimeError("路径 JSON 格式不对：running 状态但 path 为空")
    if status == "fail" and path:
        raise RuntimeError("路径 JSON 格式不对：fail 状态但 path 不为空")


def send_target(host, port, target_x, target_y, connect_timeout=3.0, response_timeout=8.0, logger=None):
    """连接 C 端 -> 发目标 -> 等回包 -> 返回字典；失败抛 RuntimeError。"""
    if not (0 <= target_x < 6 and 0 <= target_y < 6):
        raise RuntimeError("目标坐标越界，不发送：(%d, %d)" % (target_x, target_y))

    # 1. 连接 C 端
    try:
        sock = socket.create_connection((host, port), timeout=connect_timeout)
    except OSError as exc:
        raise RuntimeError("连不上 C 端寻路服务（%s:%d）：%s" % (host, port, exc)) from exc

    try:
        # 2. 发送：C 端要求紧凑单行 JSON + 换行
        message = json.dumps(
            {"target_x": target_x, "target_y": target_y}, separators=(",", ":")
        ) + "\n"
        if logger:
            logger.debug("发给 C 端：%s", message.strip())
        sock.settimeout(response_timeout)
        sock.sendall(message.encode("utf-8"))

        # 3. 接收：C 端可能分几次把 JSON 发过来，所以循环收
        buffer = ""
        while True:
            try:
                chunk = sock.recv(4096)
            except socket.timeout as exc:
                raise RuntimeError("等待 C 端寻路结果超时（%.1f 秒）" % response_timeout) from exc
            except OSError as exc:
                raise RuntimeError("和 C 端通信中断：%s" % exc) from exc

            if not chunk:
                raise RuntimeError("C 端没有返回结果就断开连接")

            buffer += chunk.decode("utf-8", "replace")

            # JSON 还没收完整：大括号数量不相等就继续收
            if buffer.count("{") == 0 or buffer.count("{") != buffer.count("}"):
                continue

            start = buffer.find("{")
            end = buffer.rfind("}")
            try:
                data = json.loads(buffer[start:end + 1])
            except ValueError as exc:
                raise RuntimeError("路径 JSON 格式不对：C 端回包不是合法 JSON") from exc

            check_report(data)
            if logger:
                logger.debug("收到 C 端回包：%s", data)
            return data
    finally:
        sock.close()