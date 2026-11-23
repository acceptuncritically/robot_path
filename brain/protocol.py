import json
from dataclasses import dataclass
from typing import Iterable

from .errors import (
    InvalidReportPathError,
    InvalidTargetCommandError,
    MalformedReportError,
    ProtocolError,
    UnknownStatusError,
)
from .text_json import iter_json_objects

GRID_SIZE = 6
MIN_COORDINATE = 0
MAX_COORDINATE = GRID_SIZE - 1
STATUS_RUNNING = "running"
STATUS_FAIL = "fail"
SUPPORTED_STATUSES = (STATUS_RUNNING, STATUS_FAIL)
MESSAGE_END = "\n"


def validate_coordinate(value: object, name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} 必须是整数")
    if value < MIN_COORDINATE or value > MAX_COORDINATE:
        raise ValueError(f"{name} 必须在 {MIN_COORDINATE} 到 {MAX_COORDINATE} 之间")
    return value


def format_path(points: Iterable["PathPoint"]) -> str:
    return "[" + ",".join(f"({point.x},{point.y})" for point in points) + "]"


@dataclass(frozen=True)
class Target:
    x: int
    y: int

    def __post_init__(self) -> None:
        validate_coordinate(self.x, "target_x")
        validate_coordinate(self.y, "target_y")

    def to_dict(self) -> dict[str, int]:
        return {"target_x": self.x, "target_y": self.y}

    def human_text(self) -> str:
        return f"(x={self.x}, y={self.y})（第 {self.x + 1} 行第 {self.y + 1} 列）"

    def __str__(self) -> str:
        return f"({self.x},{self.y})"


@dataclass(frozen=True)
class PathPoint:
    x: int
    y: int

    def __post_init__(self) -> None:
        validate_coordinate(self.x, "x")
        validate_coordinate(self.y, "y")

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y}

    def __str__(self) -> str:
        return f"({self.x},{self.y})"


@dataclass(frozen=True)
class RobotReport:
    status: str
    points: tuple[PathPoint, ...]
    raw: str = ""

    @property
    def is_running(self) -> bool:
        return self.status == STATUS_RUNNING

    @property
    def step_count(self) -> int:
        return max(len(self.points) - 1, 0)

    def formatted_path(self) -> str:
        return format_path(self.points)


def find_message_object(raw: str, required_keys: tuple[str, ...]) -> dict:
    fallback = None
    for value in iter_json_objects(raw):
        if not isinstance(value, dict):
            continue
        if fallback is None:
            fallback = value
        if all(key in value for key in required_keys):
            return value
    if fallback is not None:
        return fallback
    raise MalformedReportError("未找到 JSON 报文", raw)


def build_target_message(target: Target) -> str:
    return json.dumps(target.to_dict(), separators=(",", ":")) + MESSAGE_END


def parse_target_message(raw: str) -> Target:
    data = find_message_object(raw, ("target_x", "target_y"))
    for key in ("target_x", "target_y"):
        if key not in data:
            raise InvalidTargetCommandError(f"下发报文缺少 {key} 字段", raw)
        value = data[key]
        if type(value) is not int:
            raise InvalidTargetCommandError(f"{key} 必须是整数", raw)
        if value < MIN_COORDINATE or value > MAX_COORDINATE:
            raise InvalidTargetCommandError(f"{key} 超出范围: {value}", raw)
    return Target(x=data["target_x"], y=data["target_y"])


def parse_robot_report(raw: str) -> RobotReport:
    data = find_message_object(raw, ("status", "path"))
    status = data.get("status")
    if not isinstance(status, str) or status not in SUPPORTED_STATUSES:
        raise UnknownStatusError(status, raw)
    path = data.get("path")
    if not isinstance(path, list):
        raise InvalidReportPathError("path 必须是数组", raw)
    points: list[PathPoint] = []
    for index, item in enumerate(path):
        if not isinstance(item, dict):
            raise InvalidReportPathError(f"path[{index}] 必须是对象", raw)
        if "x" not in item or "y" not in item:
            raise InvalidReportPathError(f"path[{index}] 缺少 x 或 y", raw)
        x = item["x"]
        y = item["y"]
        if type(x) is not int or type(y) is not int:
            raise InvalidReportPathError(f"path[{index}] 的 x 和 y 必须是整数", raw)
        if not (MIN_COORDINATE <= x <= MAX_COORDINATE and MIN_COORDINATE <= y <= MAX_COORDINATE):
            raise InvalidReportPathError(f"path[{index}] 坐标越界", raw)
        points.append(PathPoint(x=x, y=y))
    if status == STATUS_FAIL and points:
        raise InvalidReportPathError("status 为 fail 时 path 必须为空", raw)
    if status == STATUS_RUNNING and not points:
        raise InvalidReportPathError("status 为 running 时 path 不能为空", raw)
    return RobotReport(status=status, points=tuple(points), raw=raw)


def build_report_message(status: str, points: Iterable[PathPoint | tuple[int, int]] = ()) -> str:
    if status not in SUPPORTED_STATUSES:
        raise ValueError(f"不支持的 status: {status}")
    normalized: list[PathPoint] = []
    for item in points:
        if isinstance(item, PathPoint):
            normalized.append(item)
        else:
            x, y = item
            normalized.append(PathPoint(x=x, y=y))
    if status == STATUS_FAIL and normalized:
        raise ValueError("fail 状态不能携带路径")
    if status == STATUS_RUNNING and not normalized:
        raise ValueError("running 状态必须携带路径")
    payload = {"path": [point.to_dict() for point in normalized], "status": status}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))