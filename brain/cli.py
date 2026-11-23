import argparse
import logging
import sys

from . import __version__
from .config import AppConfig
from .errors import BrainError, ConfigError, SessionBusyError, SessionClosedError
from .feedback import FeedbackRenderer
from .llm.base import LLMClient
from .llm.mock_client import MockLLMClient
from .llm.openai_client import OpenAIClientConfig, OpenAICompatibleClient
from .logging_setup import setup_logging
from .planning.planner import TargetPlanner
from .session import BrainSession, TaskStatus
from .transport.base import Transport
from .transport.mock_transport import MockTransport
from .transport.serial_transport import SerialTransport
from .transport.tcp_transport import TcpTransport

logger = logging.getLogger(__name__)
QUIT_COMMANDS = ("q", "quit", "exit", "退出")
HELP_COMMANDS = ("help", "帮助", "?")
STATUS_LABELS = {
    TaskStatus.RUNNING: "寻路成功",
    TaskStatus.FAIL: "寻路失败",
    TaskStatus.INVALID_INSTRUCTION: "指令无法解析",
    TaskStatus.LLM_ERROR: "大模型调用失败",
    TaskStatus.TRANSPORT_ERROR: "通信异常",
    TaskStatus.PROTOCOL_ERROR: "回包协议异常",
    TaskStatus.TIMEOUT: "等待回包超时",
}


def build_llm_client(config: AppConfig) -> LLMClient:
    llm_config = config.llm
    if llm_config.provider == "mock":
        return MockLLMClient()
    if not llm_config.api_key:
        raise ConfigError("使用真实大模型需要配置 BRAIN_LLM_API_KEY")
    return OpenAICompatibleClient(
        OpenAIClientConfig(
            base_url=llm_config.base_url,
            model=llm_config.model,
            api_key=llm_config.api_key,
            timeout=llm_config.timeout,
            max_retries=llm_config.max_retries,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
        )
    )


def build_transport(config: AppConfig) -> Transport:
    transport_config = config.transport
    if transport_config.kind == "mock":
        return MockTransport()
    if transport_config.kind == "tcp":
        return TcpTransport(
            host=transport_config.host,
            port=transport_config.port,
            connect_timeout=transport_config.connect_timeout,
        )
    if transport_config.kind == "serial":
        return SerialTransport(
            port=transport_config.serial_port,
            baudrate=transport_config.baudrate,
        )
    raise ConfigError(f"不支持的通信方式: {transport_config.kind}")


def build_session(config: AppConfig) -> BrainSession:
    planner = TargetPlanner(build_llm_client(config), max_retries=config.llm.max_retries)
    return BrainSession(
        planner=planner,
        transport=build_transport(config),
        feedback=FeedbackRenderer(),
        report_timeout=config.report_timeout,
    )


def print_banner(config: AppConfig) -> None:
    transport_descriptions = {
        "mock": "Mock 离线模拟",
        "tcp": f"TCP {config.transport.host}:{config.transport.port}",
        "serial": f"串口 {config.transport.serial_port} {config.transport.baudrate}bps",
    }
    transport_text = transport_descriptions.get(config.transport.kind, config.transport.kind)
    print("=" * 64)
    print("具身 Agent 小车 Python 大脑端")
    print(f"大模型: {config.llm.describe()}")
    print(f"通信: {transport_text}")
    print("坐标: 6×6 栅格，左上角 (0,0)，x 向下，y 向右，范围 0 到 5")
    print("输入 help 查看帮助，输入 q 退出")
    print("=" * 64)


def run_interactive(config: AppConfig) -> int:
    feedback = FeedbackRenderer()
    try:
        setup_logging(config.verbose, config.log_file)
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2
    try:
        session = build_session(config)
    except (ConfigError, ValueError) as exc:
        print(f"启动失败: {exc}", file=sys.stderr)
        return 2
    print_banner(config)
    try:
        session.open()
    except BrainError as exc:
        print(f"连接失败: {exc.message}", file=sys.stderr)
        return 2
    try:
        while True:
            try:
                text = input("请输入指令 > ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            text = text.strip()
            if not text:
                print("输入为空，请重新输入。")
                continue
            if text.lower() in QUIT_COMMANDS:
                break
            if text in HELP_COMMANDS:
                print(feedback.help_text())
                continue
            try:
                outcome = session.handle_instruction(text)
            except SessionBusyError as exc:
                print(f"[大脑] {exc.message}")
                continue
            except SessionClosedError as exc:
                print(f"[大脑] {exc.message}")
                break
            except KeyboardInterrupt:
                print()
                break
            except BrainError as exc:
                print(f"[大脑] 处理失败: {exc.message}")
                continue
            except Exception:
                logger.exception("处理指令时发生未预期异常")
                print("[大脑] 内部错误，已记录日志。")
                continue
            print()
            print(f"[大脑] {outcome.user_message}")
            print()
    finally:
        session.close()
    print(feedback.goodbye())
    return 0


def run_once(config: AppConfig, instruction: str) -> int:
    try:
        setup_logging(config.verbose, config.log_file)
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2
    try:
        session = build_session(config)
    except (ConfigError, ValueError) as exc:
        print(f"启动失败: {exc}", file=sys.stderr)
        return 2
    try:
        session.open()
        outcome = session.handle_instruction(instruction)
    except BrainError as exc:
        print(f"执行失败: {exc.message}", file=sys.stderr)
        return 2
    except Exception:
        logger.exception("执行指令时发生未预期异常")
        print("执行失败: 内部错误", file=sys.stderr)
        return 2
    finally:
        session.close()
    print(outcome.user_message)
    return 0 if outcome.is_ok else 1


def run_selftest_case(
    name: str,
    instruction: str,
    llm_client: LLMClient,
    transport: Transport,
    expected_status: TaskStatus,
    expected_keywords: tuple[str, ...],
) -> bool:
    session = BrainSession(
        planner=TargetPlanner(llm_client, max_retries=2),
        transport=transport,
        feedback=FeedbackRenderer(),
        report_timeout=1.0,
    )
    print(f"\n[自检] {name}")
    print(f"用户指令: {instruction}")
    session.open()
    try:
        outcome = session.handle_instruction(instruction)
    finally:
        session.close()
    sent_messages = getattr(transport, "sent_messages", [])
    print(f"下发报文: {[message.strip() for message in sent_messages]}")
    print(f"回包: {outcome.raw_report!r}")
    print(f"反馈: {outcome.user_message}")
    print(f"任务状态: {STATUS_LABELS.get(outcome.status, outcome.status.value)}")
    passed = outcome.status == expected_status
    passed = passed and all(keyword in outcome.user_message for keyword in expected_keywords)
    if expected_status is TaskStatus.INVALID_INSTRUCTION:
        passed = passed and not sent_messages
    print("结果: PASS" if passed else "结果: FAIL")
    return passed


def run_selftest() -> int:
    setup_logging(False, None)
    logging.getLogger("brain").setLevel(logging.CRITICAL)
    cases = [
        ("正常寻路", "去迷宫右下角", MockLLMClient(), MockTransport(), TaskStatus.RUNNING, ("已规划路线",)),
        ("目标点是障碍物", "去(2,1)", MockLLMClient(), MockTransport(), TaskStatus.FAIL, ("阻挡",)),
        ("起点即终点", "回到(0,0)起点", MockLLMClient(), MockTransport(), TaskStatus.RUNNING, ("无需移动",)),
        (
            "坐标越界后重试成功",
            "去(9,9)",
            MockLLMClient(scripted_outputs=['{"target_x": 9, "target_y": 9}', '{"target_x": 3, "target_y": 2}']),
            MockTransport(),
            TaskStatus.RUNNING,
            ("已规划路线",),
        ),
        (
            "输出始终不合法",
            "去(3,2)",
            MockLLMClient(scripted_outputs=["这是一段乱码"] * 3),
            MockTransport(),
            TaskStatus.INVALID_INSTRUCTION,
            ("无法理解",),
        ),
        ("无法确定目标", "随便走走吧", MockLLMClient(), MockTransport(), TaskStatus.INVALID_INSTRUCTION, ("无法确定目标",)),
        ("等待回包超时", "去(5,5)", MockLLMClient(), MockTransport(scenario="timeout"), TaskStatus.TIMEOUT, ("响应",)),
        ("回包格式非法", "去(3,2)", MockLLMClient(), MockTransport(scenario="malformed"), TaskStatus.PROTOCOL_ERROR, ("格式异常",)),
        ("未知状态", "去(3,2)", MockLLMClient(), MockTransport(scenario="unknown_status"), TaskStatus.PROTOCOL_ERROR, ("未知状态",)),
        ("发送异常", "去(3,2)", MockLLMClient(), MockTransport(scenario="send_error"), TaskStatus.TRANSPORT_ERROR, ("通信异常",)),
    ]
    print("=" * 64)
    print("内置自检")
    print("=" * 64)
    passed = 0
    for case in cases:
        if run_selftest_case(*case):
            passed += 1
    print("\n" + "=" * 64)
    print(f"自检结果: {passed}/{len(cases)} 通过")
    print("=" * 64)
    return 0 if passed == len(cases) else 1


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m brain", description="具身 Agent 小车 Python 大脑端")
    parser.add_argument("--selftest", action="store_true", help="运行内置自检")
    parser.add_argument("--once", metavar="指令", help="执行一条指令后退出")
    parser.add_argument("--llm", choices=("mock", "openai"), help="大模型提供方")
    parser.add_argument("--model", help="模型名称")
    parser.add_argument("--base-url", help="OpenAI 兼容接口地址")
    parser.add_argument("--api-key", help="API Key")
    parser.add_argument("--llm-timeout", type=float, help="大模型请求超时秒数")
    parser.add_argument("--transport", choices=("mock", "tcp", "serial"), help="通信方式")
    parser.add_argument("--tcp-host", help="TCP 主机")
    parser.add_argument("--tcp-port", type=int, help="TCP 端口")
    parser.add_argument("--serial-port", help="串口号")
    parser.add_argument("--baudrate", type=int, help="串口波特率")
    parser.add_argument("--report-timeout", type=float, help="等待回包超时秒数")
    parser.add_argument("--log-file", help="日志文件路径")
    parser.add_argument("--env-file", help="环境变量文件路径")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def apply_cli_overrides(config: AppConfig, args: argparse.Namespace) -> AppConfig:
    if args.llm is not None:
        config = config.with_llm(provider=args.llm)
    if args.model is not None:
        config = config.with_llm(model=args.model)
    if args.base_url is not None:
        config = config.with_llm(base_url=args.base_url)
    if args.api_key is not None:
        config = config.with_llm(api_key=args.api_key)
    if args.llm_timeout is not None:
        config = config.with_llm(timeout=args.llm_timeout)
    if args.transport is not None:
        config = config.with_transport(kind=args.transport)
    if args.tcp_host is not None:
        config = config.with_transport(host=args.tcp_host)
    if args.tcp_port is not None:
        config = config.with_transport(port=args.tcp_port)
    if args.serial_port is not None:
        config = config.with_transport(serial_port=args.serial_port)
    if args.baudrate is not None:
        config = config.with_transport(baudrate=args.baudrate)
    if args.report_timeout is not None:
        config = config.with_app(report_timeout=args.report_timeout)
    if args.log_file is not None:
        config = config.with_app(log_file=args.log_file)
    if args.verbose:
        config = config.with_app(verbose=True)
    return config


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    if args.selftest:
        return run_selftest()
    try:
        config = AppConfig.from_env(env_file=args.env_file)
        config = apply_cli_overrides(config, args)
    except (ConfigError, ValueError) as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2
    if args.once is not None:
        return run_once(config, args.once)
    return run_interactive(config)