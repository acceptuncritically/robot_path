"""主程序（简化版）：输入中文指令 -> 大模型解析目标坐标 -> 通过 TCP 发给 C 端 -> 打印路径。

四个文件的分工：
- main.py         主流程：交互对话、调用大模型、调用 TCP、打印结果
- llm_client.py   大模型：DeepSeek / Mock，few-shot 示例，JSON 解析
- tcp_client.py   和 C 端寻路程序通信
- logger_setup.py 日志：DEBUG 级别，控制台 + 文件 + TCP

运行方法：
    python main.py                          # 交互对话（没有 Key 自动用 Mock）
    python main.py --mock                   # 强制用 Mock 大模型
    python main.py --once "去迷宫右下角"     # 只执行一条指令
    python main.py --selftest               # 离线自检
    python main.py --host 127.0.0.1 --port 9000
"""
import argparse
import json
import os

from llm_client import get_decision
from logger_setup import setup_logger
from tcp_client import send_target

HELP_TEXT = """可用指令示例：
  1.去迷宫右下角      2.走到坐标(3,2)
  3.回到起点          4.再往左一格(基于上一轮目标做相对移动)
  5.停一下
命令：
  help   查看帮助       state  查看当前状态
  reset  清空对话和状态    q      退出
坐标约定：6x6 栅格，左上角 (0,0)，x 向下，y 向右，范围 0~5。"""


def format_path(path):
    """把 [{"x":0,"y":0}, ...] 变成 (0,0)->(1,0) 这样的文字。"""
    if not path:
        return "C 端返回了空路径。"
    points = ["(%d,%d)" % (point["x"], point["y"]) for point in path]
    if len(points) == 1:
        return "已经在目标点 %s 了。" % points[0]
    return "已规划路线：%s，共 %d 步。" % ("->".join(points), len(points) - 1)


def new_state():
    """新建一个状态：历史对话、上一轮目标、当前任务状态。"""
    return {"history": [], "last_target": None, "task_state": "空闲"}


def handle_instruction(text, state, args, logger, use_mock):
    """处理一条用户指令。"""
    logger.info("用户指令：%s", text)
    state["task_state"] = "解析指令中"

    try:
        decision = get_decision(
            instruction=text,
            history=state["history"],
            last_target=state["last_target"],
            task_state=state["task_state"],
            use_mock=use_mock,
            logger=logger,
        )
    except Exception as exc:
        logger.error("解析指令失败：%s", exc)
        print("调用大模型失败：%s" % exc)
        state["task_state"] = "失败"
        return

    logger.debug("模型解析结果：%s", json.dumps(decision, ensure_ascii=False))
    # 把这一轮对话记到历史里，下一轮模型就能看到
    state["history"].append((text, json.dumps(decision, ensure_ascii=False)))

    action = decision["action"]
    reply = decision["reply"]

    if action == "clarify":
        print(reply or "我没听清，请再说一下具体位置。")
        state["task_state"] = "等待补充"
        return

    if action == "stop":
        print(reply or "好的，已停止。")
        state["task_state"] = "已停止"
        return

    # action == "navigate"：请求 C 端寻路
    target_x = decision["target_x"]
    target_y = decision["target_y"]
    state["task_state"] = "请求 C 端寻路"

    try:
        report = send_target(
            host=args.host,
            port=args.port,
            target_x=target_x,
            target_y=target_y,
            connect_timeout=args.connect_timeout,
            response_timeout=args.response_timeout,
            logger=logger,
        )
    except Exception as exc:
        logger.error("和 C 端通信失败：%s", exc)
        print(str(exc))  # 异常消息里已经写了中文原因
        state["task_state"] = "失败"
        return

    if report["status"] == "fail":
        print("C 端寻路失败：目标 (%d,%d) 可能越界、是障碍物，或者没有路。" % (target_x, target_y))
        state["task_state"] = "失败"
        return

    print(format_path(report["path"]))
    state["last_target"] = (target_x, target_y)
    state["task_state"] = "成功"


def run_selftest():
    """不连 C 端、不调 DeepSeek 的小自检。"""
    from llm_client import mock_decision, parse_json

    checks = []

    def check(name, ok):
        checks.append(ok)
        print(("通过 " if ok else "失败 ") + name)

    check("Mock：右下角", mock_decision("去迷宫右下角", None)["target_x"] == 5)
    check("Mock：坐标", mock_decision("走到坐标(3,2)", None)["target_y"] == 2)
    check("Mock：停止", mock_decision("停一下", None)["action"] == "stop")
    check("Mock：相对移动", mock_decision("再往左一格", (5, 5))["target_y"] == 4)
    check(
        "JSON 解析",
        parse_json('```json\n{"action":"navigate","target_x":3,"target_y":2}\n```')["target_x"] == 3,
    )
    check(
        "路径格式化",
        format_path([{"x": 0, "y": 0}, {"x": 1, "y": 1}]) == "已规划路线：(0,0)->(1,1)，共 1 步。",
    )
    print("自检结果：%d/%d 通过" % (sum(checks), len(checks)))
    return 0 if all(checks) else 1


def build_parser():
    parser = argparse.ArgumentParser(description="简化版小车大脑端")
    parser.add_argument("--host", default=os.environ.get("EASY_C_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("EASY_C_PORT", "9000")))
    parser.add_argument("--mock", action="store_true", help="强制使用 Mock 大模型")
    parser.add_argument("--once", default=None, help="只执行一条指令后退出")
    parser.add_argument("--selftest", action="store_true", help="离线自检")
    parser.add_argument("--connect-timeout", type=float, default=3.0)
    parser.add_argument("--response-timeout", type=float, default=8.0)
    parser.add_argument("--connect-retries", type=int, default=1, help="简化版保留参数，暂不重试")
    parser.add_argument("--log-dir", default=None, help="日志目录")
    parser.add_argument("--log-tcp-port", type=int, default=9100, help="TCP 日志服务端口，默认 9100")
    parser.add_argument("--no-log-tcp", action="store_true", help="不通过 TCP 发日志")
    return parser


def main():
    args = build_parser().parse_args()
    logger = setup_logger(
        log_dir=args.log_dir, use_tcp=not args.no_log_tcp, tcp_port=args.log_tcp_port
    )
    logger.info("程序启动：host=%s port=%d mock=%s", args.host, args.port, args.mock)

    if args.selftest:
        return run_selftest()

    use_mock = args.mock or not os.environ.get("DEEPSEEK_API_KEY")
    logger.info("大模型模式：%s", "Mock" if use_mock else "DeepSeek")

    state = new_state()

    if args.once is not None:
        handle_instruction(args.once, state, args, logger, use_mock)
        return 0

    print(HELP_TEXT)
    while True:
        try:
            text = input("指令> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text.lower() in ("q", "quit", "exit") or text == "退出":
            break
        if text in ("help", "帮助", "?"):
            print(HELP_TEXT)
            continue
        if text in ("state", "状态"):
            print(
                "当前状态：%s；上一目标：%s；历史对话：%d 轮"
                % (state["task_state"], state["last_target"], len(state["history"]))
            )
            continue
        if text in ("reset", "重置"):
            state = new_state()
            print("已清空对话和状态。")
            continue
        handle_instruction(text, state, args, logger, use_mock)

    logger.info("程序退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())