"""大模型模块（简化版）：把中文指令解析成 6x6 栅格里的目标坐标。

两种模式：
- DeepSeek：真实大模型，需要环境变量 DEEPSEEK_API_KEY；
- Mock：不联网，用关键词和正则猜目标，方便没有 Key 时演示。

不管哪种模式，最后都返回同样格式的字典：
    {"action": "navigate", "target_x": 5, "target_y": 5, "reply": "好的，去右下角。"}

action 只有三种：
- navigate：去某个格子，target_x/target_y 是 0~5 的整数；
- clarify：没听清，需要向用户追问，坐标是 None；
- stop：停止/取消当前任务，坐标是 None。
"""
import json
import os
import re
import time


SYSTEM_PROMPT = """你是小车大脑，负责把用户的中文指令解析成 6x6 栅格里的目标坐标。
坐标规则：左上角是 (0,0)，x 向下表示行，y 向右表示列，x 和 y 都在 0~5 之间，右下角是 (5,5)。
只输出一个 JSON 对象，不要输出别的文字。格式如下：
{"action": "navigate", "target_x": 5, "target_y": 5, "reply": "好的，去右下角。"}
action 的取值：
- navigate：去某个格子，target_x/target_y 必须是 0~5 的整数；
- clarify：没听清或目标不明确，需要追问，坐标写 null；
- stop：停止或取消任务，坐标写 null。
要结合历史对话理解“再往右一格”“回到刚才那里”这类相对指令。
目标越界或者和移动无关时，用 clarify 追问，不要乱编坐标。"""

# few-shot 示例：写成“用户说一句 + 模型答一句”，让模型照样子输出 JSON
FEW_SHOT = [
    ("去迷宫右下角", '{"action":"navigate","target_x":5,"target_y":5,"reply":"好的，去右下角。"}'),
    ("回到起点", '{"action":"navigate","target_x":0,"target_y":0,"reply":"好的，回起点。"}'),
    ("走到坐标(3,2)", '{"action":"navigate","target_x":3,"target_y":2,"reply":"好的，去(3,2)。"}'),
    ("去那边", '{"action":"clarify","target_x":null,"target_y":null,"reply":"你说的那边是哪个方向？可以说右下角或坐标(3,2)。"}'),
    ("停一下", '{"action":"stop","target_x":null,"target_y":null,"reply":"好的，已停止。"}'),
]

# Mock 模式用的关键词表
MOCK_WORDS = [
    ("右下角", (5, 5)),
    ("右上角", (0, 5)),
    ("左下角", (5, 0)),
    ("左上角", (0, 0)),
    ("中心", (2, 2)),
    ("中间", (2, 2)),
    ("起点", (0, 0)),
    ("终点", (5, 5)),
]
NUMBER_WORDS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5}
MOVE_STEP = {"右": (0, 1), "左": (0, -1), "上": (-1, 0), "下": (1, 0)}


from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
def make_messages(history, instruction, task_state):
    """拼消息：系统提示 + few-shot 示例 + 历史对话 + 本次指令。"""

    messages = [SystemMessage(content=SYSTEM_PROMPT + "\n当前任务状态：" + task_state)]
    for user_text, model_text in FEW_SHOT:
        messages.append(HumanMessage(content=user_text))
        messages.append(AIMessage(content=model_text))
    for user_text, model_text in history:
        messages.append(HumanMessage(content=user_text))
        messages.append(AIMessage(content=model_text))
    messages.append(HumanMessage(content=instruction))
    return messages

MODEL_NAME = "deepseek-chat"

def call_deepseek(history, instruction, task_state):
    """调用一次 DeepSeek，返回模型输出的文字。"""
    try:
        from langchain_deepseek import ChatDeepSeek
    except ImportError as exc:
        raise RuntimeError(
            "没有安装 langchain-deepseek，请先执行：pip install langchain-deepseek"
        ) from exc

    model = ChatDeepSeek(
        model=os.environ.get("DEEPSEEK_API_KEY", MODEL_NAME),
        temperature=0,
        timeout=30.0,
    )
    response = model.invoke(make_messages(history, instruction, task_state))
    content = response.content
    return content if isinstance(content, str) else str(content)


def parse_json(text):
    """从模型输出里截出 JSON，并检查字段。格式不对就抛 ValueError。"""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("模型输出里没有 JSON")

    data = json.loads(text[start:end + 1])
    action = data.get("action", "navigate")
    if action not in ("navigate", "clarify", "stop"):
        raise ValueError("action 不合法：%r" % (action,))

    target_x = data.get("target_x")
    target_y = data.get("target_y")
    reply = data.get("reply") or ""

    if action == "navigate":
        if type(target_x) is not int or type(target_y) is not int:
            raise ValueError("target_x/target_y 不是整数")
        if not (0 <= target_x < 6 and 0 <= target_y < 6):
            raise ValueError("坐标越界：(%s, %s)" % (target_x, target_y))
    else:
        target_x, target_y = None, None

    return {
        "action": action,
        "target_x": target_x,
        "target_y": target_y,
        "reply": reply,
    }


def _navigate(x, y, reply):
    """拼一个“去目标”的结果。"""
    return {"action": "navigate", "target_x": x, "target_y": y, "reply": reply}


def mock_decision(instruction, last_target):
    """Mock 模式：不用大模型，靠关键词和正则猜一个目标。"""
    text = instruction.strip()

    # 1. 用户直接说坐标，比如 (3,2) 或 （3，2）
    match = re.search(r"[（(]\s*(\d+)\s*[，,]\s*(\d+)\s*[)）]", text)
    if match:
        x, y = int(match.group(1)), int(match.group(2))
        if 0 <= x < 6 and 0 <= y < 6:
            return _navigate(x, y, "好的，去坐标(%d,%d)。" % (x, y))
        return {
            "action": "clarify",
            "target_x": None,
            "target_y": None,
            "reply": "坐标 (%d,%d) 超出 0~5 的范围。" % (x, y),
        }

    # 2. 相对移动，比如“再往左一格”，要基于上一轮的目标
    match = re.search(r"往(右|左|上|下)\s*([一二两三四五])?\s*格", text)
    if match:
        if last_target is None:
            return {
                "action": "clarify",
                "target_x": None,
                "target_y": None,
                "reply": "我还没有上一轮目标，请先告诉我要去哪个位置。",
            }
        steps = NUMBER_WORDS.get(match.group(2), 1) if match.group(2) else 1
        dx, dy = MOVE_STEP[match.group(1)]
        x = last_target[0] + dx * steps
        y = last_target[1] + dy * steps
        if 0 <= x < 6 and 0 <= y < 6:
            return _navigate(x, y, "好的，从上一轮目标往%s移动 %d 格。" % (match.group(1), steps))
        return {
            "action": "clarify",
            "target_x": None,
            "target_y": None,
            "reply": "再往%s移动 %d 格会超出边界，请直接说要去的格子。" % (match.group(1), steps),
        }

    # 3. 停止/取消
    if "停" in text or "取消" in text:
        return {"action": "stop", "target_x": None, "target_y": None, "reply": "好的，已停止。"}

    # 4. 常见位置关键词
    for word, (x, y) in MOCK_WORDS:
        if word in text:
            return _navigate(x, y, "好的，去%s(%d,%d)。" % (word, x, y))

    # 5. 实在没听懂，就追问
    return {
        "action": "clarify",
        "target_x": None,
        "target_y": None,
        "reply": "我没听清具体位置，可以说“右下角”或“坐标(3,2)”。",
    }


def get_decision(instruction, history, last_target, task_state, use_mock, logger, timeout=30.0, retries=2):
    """主入口：返回解析好的指令字典；失败时抛 RuntimeError。

    history 是 [(用户说了什么, 模型答了什么), ...]，用来支持多轮对话。
    """
    if use_mock:
        decision = mock_decision(instruction, last_target)
        logger.debug("Mock 模型结果：%s", json.dumps(decision, ensure_ascii=False))
        return decision

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            logger.debug("第 %d 次调用 DeepSeek（历史 %d 轮）", attempt, len(history))
            raw = call_deepseek(history, instruction, task_state, timeout)
            logger.debug("DeepSeek 原始输出：%s", raw)
            return parse_json(raw)
        except ValueError as exc:
            # 返回格式不对：加一句提醒再问一次
            last_error = exc
            logger.warning("模型输出格式不对：%s", exc)
            instruction = instruction + "\n（上次输出不是合法 JSON，请只输出 JSON。）"
        except Exception as exc:
            # 网络错误、超时、Key 错误等
            last_error = exc
            logger.warning("调用 DeepSeek 出错：%s", exc)
            time.sleep(1)

    raise RuntimeError(str(last_error))