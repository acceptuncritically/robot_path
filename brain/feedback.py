from .errors import PlanningError, ProtocolError, TransportError, UnknownStatusError
from .protocol import RobotReport, Target


class FeedbackRenderer:
    def running(self, report: RobotReport, target: Target | None = None) -> str:
        if report.step_count == 0 and len(report.points) == 1:
            point = report.points[0]
            return f"小车当前已在目标点 ({point.x},{point.y})，无需移动。"
        target_text = f"目标点 {target.human_text()}；" if target is not None else ""
        return (
            f"目标解析完成，{target_text}已规划路线，小车准备出发，"
            f"路径：{report.formatted_path()}（共 {report.step_count} 步）"
        )

    def planning_error(self, error: PlanningError) -> str:
        if error.kind == "uncertain":
            return "无法确定目标位置，请给出具体坐标或方位。"
        if error.kind == "range":
            return f"坐标超出迷宫范围，有效范围 0 到 5：{error.message}。请重新输入。"
        if error.kind == "llm":
            return f"大模型调用失败：{error.message}。请检查网络或 API 配置后重试。"
        return f"无法理解这条指令：{error.message}。请直接给出坐标或方位。"

    def fail(self) -> str:
        return "目标点被障碍物阻挡，无法规划可行路线，请更换目标。"

    def protocol_error(self, error: ProtocolError) -> str:
        if isinstance(error, UnknownStatusError):
            return f"小车回传了未知状态：{error.status!r}，请检查小车程序。"
        return f"小车回传数据格式异常：{error.message}。已记录原始报文。"

    def transport_error(self, error: TransportError) -> str:
        return f"串口或网络通信异常：{error.message}。请检查连接后重试。"

    def timeout(self, seconds: float) -> str:
        return f"小车未在 {seconds:g} 秒内响应，请检查串口或网络连接后重试。"

    def goodbye(self) -> str:
        return "已退出，再见。"

    def help_text(self) -> str:
        return (
            "可用指令：\n"
            "q 或 quit 或 exit 或 退出：退出程序\n"
            "help 或 帮助：查看帮助\n"
            "其他任意中文指令，例如：\n"
            "去迷宫右下角\n"
            "小车走到坐标(5,5)\n"
            "回到(0,0)起点\n"
            "坐标约定：6×6 栅格，左上角 (0,0)，x 向下，y 向右，范围 0 到 5。"
        )