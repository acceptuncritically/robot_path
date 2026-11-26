"""主程序（简化版）：输入中文指令 -> 大模型解析目标坐标 -> 通过 TCP 发给 C 端 -> 打印路径 

四个文件 + 一个配置文件的分工：
- main.py         主流程：交互对话、调用大模型、调用 TCP、打印结果
- llm_client.py   大模型：DeepSeek / Mock，few-shot 示例，JSON 解析
- tcp_client.py   和 C 端寻路程序通信
- logger_setup.py 日志：DEBUG 级别，控制台 + 文件 + TCP
- config.yml      配置文件：以前写在命令行参数里的设置（host、port、mock、超时、日志等）都放这里
"""
import json
import os
from pathlib import Path

import yaml

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
坐标约定：6x6 栅格，左上角 (0,0)，x 向下，y 向右，范围 0~5 """


def format_path(path):
    """把 [{"x":0,"y":0}, ...] 变成 (0,0)->(1,0) 这样的文字 """
    if not path:
        return "C 端返回了空路径 "
    points = [f"({point['x']},{point['y']})" for point in path]
    if len(points) == 1:
        return f"已经在目标点{points[0]}了"
    return f"已规划路线：{'->'.join(points)}，共 {len(points) - 1} 步 "


def new_state():
    """新建一个状态：历史对话、上一轮目标、当前任务状态 """
    return {"history": [], "last_target": None, "task_state": "空闲"}


def handle_instruction(text, state, config, logger, use_mock):
    """处理一条用户指令（config 就是从 config.yml 读出来的字典） """
    logger.info(f"用户指令：{text}")
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
    except Exception as e:
        logger.error(f"解析指令失败：{e}")
        print(f"调用大模型失败：{e}")
        state["task_state"] = "失败"
        return

    logger.debug(f"模型解析结果：{json.dumps(decision, ensure_ascii=False)}")
    # 把这一轮对话记到历史里，下一轮模型就能看到
    state["history"].append((text, json.dumps(decision, ensure_ascii=False)))

    action = decision["action"]
    reply = decision["reply"]

    if action == "unclear":
        print(reply or "我没听清，请再说一下具体位置 ")
        state["task_state"] = "等待补充"
        return

    if action == "stop":
        print(reply or "好的，已停止 ")
        state["task_state"] = "已停止"
        return

    target_x = decision["target_x"]
    target_y = decision["target_y"]
    state["task_state"] = "请求 C 端寻路"

    try:
        # 以前这里是 args.host / args.port，现在改成从 config.yml 里读
        report = send_target(
            host=config["host"],
            port=config["port"],
            target_x=target_x,
            target_y=target_y,
            connect_timeout=config["connect_timeout"],
            response_timeout=config["response_timeout"],
            logger=logger,
        )
    except Exception as e:
        logger.error(f"和 C 端通信失败:{e}")
        print(str(e))  # 异常消息里已经写了中文原因
        state["task_state"] = "失败"
        return

    if report["status"] == "fail":
        print(f"C 端寻路失败：目标{target_x},{target_y}可能越界、是障碍物，或者没有路 ")
        state["task_state"] = "失败"
        return

    print(format_path(report["path"]))
    state["last_target"] = (target_x, target_y)
    state["task_state"] = "成功"


def run_selftest():
    """不连 C 端、不调 DeepSeek 的小自检 """
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
        parse_json('```json\n{"action":"intent","target_x":3,"target_y":2}\n```')["target_x"] == 3,
    )
    check(
        "路径格式化",
        format_path([{"x": 0, "y": 0}, {"x": 1, "y": 1}]) == "已规划路线：(0,0)->(1,1)，共 1 步 ",
    )
    print(f"自检结果：{sum(checks)}/{len(checks)} 通过")
    return 0 if all(checks) else 1


# 现在这些参数都改成从同目录的 config.yml 里读，这段代码保留下来当参考，
# 方便对照：以前的命令行参数分别对应 config.yml 里的哪一项。
# def build_parser():
#     parser = argparse.ArgumentParser(description="简化版小车大脑端")
#     parser.add_argument("--host", default=os.environ.get("EASY_C_HOST", "127.0.0.1"))
#     parser.add_argument("--port", type=int, default=int(os.environ.get("EASY_C_PORT", "9000")))
#     parser.add_argument("--mock", action="store_true", help="强制使用 Mock 大模型")
#     parser.add_argument("--once", default=None, help="只执行一条指令后退出")
#     parser.add_argument("--selftest", action="store_true", help="离线自检")
#     parser.add_argument("--connect-timeout", type=float, default=3.0)
#     parser.add_argument("--response-timeout", type=float, default=8.0)
#     parser.add_argument("--connect-retries", type=int, default=1, help="简化版保留参数，暂不重试")
#     parser.add_argument("--log-file", default=None, help="日志目录")
#     parser.add_argument("--log-tcp-port", type=int, default=9100, help="TCP 日志服务端口，默认 9100")
#     parser.add_argument("--no-log-tcp", action="store_true", help="不通过 TCP 发日志")
#     return parser


# 默认配置：如果 config.yml 里漏写了某一项，就用这里的值补上，程序不会因为少一行就报错
DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 9000,
    "connect_timeout": 3.0,
    "response_timeout": 8.0,
    "mock": False,
    "once": None,
    "selftest": False,
    "log_file": None,
}


def load_config():
    """读取和本文件同目录的 config.yml，返回一个字典 """
    # 获取当前代码文件所在目录
    current_dir = Path(__file__).resolve().parent
    # 假设 config.yml 和当前代码在同一个目录
    yml_path = current_dir / "config.yml"

    with open(yml_path, "r", encoding="utf-8") as f:
        file_config = yaml.safe_load(f)  # 推荐使用 safe_load 替代 load(f, Loader=...)

    # config.yml 是空文件时，safe_load 会返回 None，这里先当成空字典，避免后面报错
    if file_config is None:
        file_config = {}

    config = DEFAULT_CONFIG.copy()  # 先复制一份默认配置
    config.update(file_config)      # 再用 config.yml 里的值覆盖默认值
    return config


# 程序一启动就把配置读进来，下面的函数直接用 config["host"] 这样取值
config = load_config()


def main():
    # args = build_parser().parse_args()  # 旧版：解析命令行参数；现在改成读 config.yml
    logger = setup_logger(
        log_file=config["log_file"],
    )
    logger.info(f"程序启动：host={config['host']} port={config['port']} mock={config['mock']}")

    if config["selftest"]:
        return run_selftest()

    # 配置文件里 mock 为 true，或者电脑没设置 DEEPSEEK_API_KEY，都使用 Mock 模式
    use_mock = config["mock"] or not os.environ.get("DEEPSEEK_API_KEY")
    logger.info(f"大模型模式：{'Mock' if use_mock else 'DeepSeek'}")

    state = new_state()

    # once 不为空：只执行这一条指令（来自 config.yml），执行完就退出
    if config["once"] is not None:
        handle_instruction(config["once"], state, config, logger, use_mock)
        return 0

    print(HELP_TEXT)
    while True:
        try:
            text = input("指令>\n ").strip()
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
                f"当前状态：{state['task_state']}；上一目标：{state['last_target']}；历史对话：{len(state['history'])} 轮"
                f"{state['task_state']}, {state['last_target']}, {len(state['history'])}"
            )
            continue
        if text in ("reset", "重置"):
            state = new_state()
            print("已清空对话和状态 ")
            continue
        handle_instruction(text, state, config, logger, use_mock)

    logger.info("程序退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())