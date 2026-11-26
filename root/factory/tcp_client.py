"""
发出去：{"target_x":5,"target_y":5}   （紧凑单行 JSON，末尾加换行）
收回来：{"path":[{"x":0,"y":0},...],"status":"running"}
          或者 {"path":[],"status":"fail"}
"""
import json
import socket


def check_report(data):
    """检查 C 端回包格式，不对就抛 RuntimeError"""
    status = data.get("status")
    if status not in ("running", "fail"):
        raise RuntimeError(f"路径 JSON 格式不对：status 不合法：{status}")

    path = data.get("path")
    if not isinstance(path, list):
        raise RuntimeError(f"路径 JSON 格式不对：path 不是数组")

    for point in path:
        if not isinstance(point, dict):
            raise RuntimeError(f"路径 JSON 格式不对：path 里的点不是对象")
        x, y = point.get("x"), point.get("y")
        if type(x) is not int or type(y) is not int:
            raise RuntimeError(f"路径 JSON 格式不对：坐标不是整数")
        if not (0 <= x < 6 and 0 <= y < 6):
            raise RuntimeError(f"路径 JSON 格式不对：坐标越界")

    if status == "running" and not path:
        raise RuntimeError(f"路径 JSON 格式不对：running 状态但 path 为空")
    if status == "fail" and path:
        raise RuntimeError(f"路径 JSON 格式不对：fail 状态但 path 不为空")


def send_target(host, port, target_x, target_y, connect_timeout=3.0, response_timeout=8.0, logger=None, socket=None):
    """连接 C 端 -> 发目标 -> 等回包 -> 返回字典；失败抛 RuntimeError """
    if not (0 <= target_x < 6 and 0 <= target_y < 6):
        raise RuntimeError(f"目标坐标越界，不发送：({target_x}, {target_y})")

    # 1. 连接 C 端
    try:
        socket = socket.create_connection((host, port), timeout=connect_timeout)
    except OSError as e:
        raise RuntimeError(f"连不上 C 端寻路服务（{host}:{port}）：{e}") from e

    try:
        # 2. 发送：C 端要求紧凑单行 JSON + 换行
        message = json.dumps(
            {"target_x": target_x, "target_y": target_y}, separators=(",", ":")
        ) + "\n"
        if logger:
            logger.debug(f"发给 C 端：{message.strip()}")
        socket.settimeout(response_timeout)
        socket.sendall(message.encode("utf-8"))

        # 3. 接收：C 端可能分几次把 JSON 发过来，所以循环收
        buffer = ""
        while True:
            try:
                chunk = socket.recv(4096)
            except socket.timeout as e:
                raise RuntimeError(f"等待 C 端寻路结果超时（{response_timeout:.1f} 秒）") from e
            except OSError as e:
                raise RuntimeError(f"和 C 端通信中断：{e}") from e

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
            except ValueError as e:
                raise RuntimeError(f"路径 JSON 格式不对：C 端回包不是合法 JSON") from e

            check_report(data)
            if logger:
                logger.debug(f"收到 C 端回包：{data}")
            return data
    finally:
        socket.close()