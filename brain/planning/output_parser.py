import json
import re

from ..errors import TargetFormatError, TargetOutOfRangeError, TargetUncertainError
from ..protocol import MAX_COORDINATE, MIN_COORDINATE, Target
from ..text_json import iter_json_objects

FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
FIELD_PATTERN = re.compile(r'"?target_([xy])"?\s*[:：]\s*(-?\d+)', re.IGNORECASE)
UNCERTAIN_PATTERN = re.compile(r"无法确定|不能确定|不确定|不知道|无法识别|无法判断|没有找到")
BARE_ALLOWED_PATTERN = re.compile(r"[\s,，;；:：{}\[\]()（）\"'`。.!！?？、]")


def parse_target_from_output(raw: str) -> Target:
    if not isinstance(raw, str):
        raise TargetFormatError("输出必须是字符串", "")
    text = raw.strip()
    if not text:
        raise TargetFormatError("输出为空", raw)

    targets: list[Target] = []
    errors: list[Exception] = []
    for value in iter_json_objects(text):
        if not isinstance(value, dict):
            continue
        if "target_x" not in value and "target_y" not in value:
            continue
        try:
            target = _validate_target_object(value)
        except (TargetFormatError, TargetOutOfRangeError, TargetUncertainError) as exc:
            errors.append(exc)
            continue
        if target not in targets:
            targets.append(target)

    if len(targets) > 1:
        raise TargetFormatError("输出中出现多个不同的目标坐标", raw)
    if len(targets) == 1:
        return targets[0]

    if errors:
        for exc in errors:
            if isinstance(exc, TargetOutOfRangeError):
                raise exc
        first_error = errors[0]
        if isinstance(first_error, TargetUncertainError):
            raise first_error
        raise TargetFormatError(first_error.message, raw)

    fenced_text = _extract_fenced_json(text)
    if fenced_text is not None:
        for value in iter_json_objects(fenced_text):
            if not isinstance(value, dict):
                continue
            if "target_x" not in value and "target_y" not in value:
                continue
            target = _validate_target_object(value)
            if target is not None:
                return target

    if UNCERTAIN_PATTERN.search(text):
        raise TargetUncertainError("模型表示无法确定目标坐标", raw)

    fallback = _parse_bare_fields(text)
    if fallback is not None:
        return fallback

    raise TargetFormatError("输出中找不到合法目标 JSON", raw)


def _extract_fenced_json(text: str) -> str | None:
    match = FENCE_PATTERN.search(text)
    if match is None:
        return None
    return match.group(1).strip()


def _validate_target_object(value: dict) -> Target:
    if "target_x" not in value or "target_y" not in value:
        raise TargetFormatError("目标 JSON 缺字段", json.dumps(value, ensure_ascii=False))
    x = value["target_x"]
    y = value["target_y"]
    if type(x) is not int or type(y) is not int:
        raise TargetFormatError("target_x 和 target_y 必须是整数", json.dumps(value, ensure_ascii=False))
    if x == -1 and y == -1:
        raise TargetUncertainError("模型表示无法确定目标坐标", json.dumps(value, ensure_ascii=False))
    if not (MIN_COORDINATE <= x <= MAX_COORDINATE and MIN_COORDINATE <= y <= MAX_COORDINATE):
        raise TargetOutOfRangeError(f"坐标超出范围: x={x}, y={y}", json.dumps(value, ensure_ascii=False))
    return Target(x=x, y=y)


def _parse_bare_fields(text: str) -> Target | None:
    if not FIELD_PATTERN.search(text):
        return None
    remainder = FIELD_PATTERN.sub("", text)
    remainder = BARE_ALLOWED_PATTERN.sub("", remainder)
    if remainder:
        return None
    values: dict[str, int] = {}
    for match in FIELD_PATTERN.finditer(text):
        values[match.group(1).lower()] = int(match.group(2))
    if "x" not in values or "y" not in values:
        return None
    x = values["x"]
    y = values["y"]
    if x == -1 and y == -1:
        raise TargetUncertainError("模型表示无法确定目标坐标", text)
    if not (MIN_COORDINATE <= x <= MAX_COORDINATE and MIN_COORDINATE <= y <= MAX_COORDINATE):
        raise TargetOutOfRangeError(f"坐标超出范围: x={x}, y={y}", text)
    return Target(x=x, y=y)