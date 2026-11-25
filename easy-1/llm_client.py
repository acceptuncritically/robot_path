"""
两种模式：
- DeepSeek：真实大模型，需要环境变量 DEEPSEEK_API_KEY；
- Mock：不联网，用关键词和正则猜目标，方便没有 Key 时演示。

不管哪种模式，最后都返回同样格式的字典：
    {"action": "intent", "target_x": 5, "target_y": 5, "reply": "好的，去右下角。"}

action 只有三种：
- intent：去某个格子，target_x/target_y 是 0~5 的整数；
- unclear：没听清，需要向用户追问，坐标是 None；
- stop：停止/取消当前任务，坐标是 None。
"""
import json
import os
import re
import time

# 现在只是保证了运行，提示词模板等配置文件直接放在代码中
SYSTEM_PROMPT = """你是小车大脑，负责把用户的中文指令解析成 6x6 栅格里的目标坐标。
坐标规则：左上角是 (0,0)，x 向下表示行，y 向右表示列，x 和 y 都在 0~5 之间，右下角是 (5,5)。
只输出一个 JSON 对象，不要输出别的文字。格式如下：
{"action": "intent", "target_x": 5, "target_y": 5, "reply": "好的，去右下角。"}
action 的取值：
- intent：去某个格子，target_x/target_y 必须是 0~5 的整数；
- unclear：没听清或目标不明确，需要追问，坐标写 null；
- stop：停止或取消任务，坐标写 null。
要结合历史对话理解“再往右一格”“回到刚才那里”这类相对指令。
目标越界或者和移动无关时，用 unclear 追问，不要乱编坐标。"""

# few-shot 示例：写成用户说一句 + 模型答一句，让模型照样子输出 JSON
FEW_SHOT = [
    ("先到x轴为5的坐标点，再到y为3的坐标",'{"action":"intent","target_x":5,"target_y":3,"reply":"好的去(5,3)"}'),
    ("去迷宫右下角", '{"action":"intent","target_x":5,"target_y":5,"reply":"好的，去右下角。"}'),
    ("回到起点", '{"action":"intent","target_x":0,"target_y":0,"reply":"好的，回起点。"}'),
    ("走到坐标(3,2)", '{"action":"intent","target_x":3,"target_y":2,"reply":"好的，去(3,2)。"}'),
    ("去那边", '{"action":"unclear","target_x":null,"target_y":null,"reply":"你说的那边是哪个方向？可以说右下角或坐标(3,2)。"}'),
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



from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
def make_messages(history, instruction, task_state):
    """拼消息：系统提示 + few-shot 示例 + 历史对话 + 本次指令。"""
    # 通过将few-shot提示词模板加入messaegs中和大模型回复的json的格式保持一致
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
    """
    调用一次 DeepSeek返回模型输出的文字。
    :param history: 历史会话内容，列表
    :param instruction: 命令让他怎么走，字符串
    :param task_state: 当前任务状态，字符串
    :return: 模型输出的文字，字符串
    """

    try:
        from langchain_deepseek import ChatDeepSeek
    except ImportError as e:
        raise RuntimeError(
            "没有安装 langchain-deepseek，请先执行：pip install langchain-deepseek"
        ) from e

    model = ChatDeepSeek(
        model=MODEL_NAME,
        api_key=os.environ.get("DEEPSEEK_API_KEY"),
        temperature=0,
        timeout=30.0
    )
    # 不再进行切片获得最后的消息，保留历史内容
    response = model.invoke(make_messages(history, instruction, task_state))
    content = response.content
    return content


def parse_json(text):
    """从模型输出里截出 JSON，并检查字段。格式不对就抛 ValueError。"""
    start = text.find("{")
    end = text.rfind("}")
    # 保证json格式正确，防止大模型输出json格式错误
    if start == -1 or end <= start:
        raise ValueError("模型输出里JSON格式错误")

    data = json.loads(text[start:end + 1])
    action = data.get("action", "intent")
    if action not in ("intent", "unclear", "stop"):
        raise ValueError(f"action 不合法：{action}")

    target_x = data.get("target_x")
    target_y = data.get("target_y")
    reply = data.get("reply") or ""

    if action == "intent":
        if type(target_x) is not int or type(target_y) is not int:
            raise ValueError("target_x/target_y 不是整数")
        if not (0 <= target_x < 6 and 0 <= target_y < 6):
            raise ValueError(f"坐标越界：({target_x},{target_y})")
    else:
        target_x, target_y = None, None

    return {
        "action": action,
        "target_x": target_x,
        "target_y": target_y,
        "reply": reply,
    }


def _intent(x, y, reply):
    """拼一个“去目标”的结果。"""
    return {"action": "intent", "target_x": x, "target_y": y, "reply": reply}


NUMBER_WORDS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5}
MOVE_STEP = {"右": (0, 1), "左": (0, -1), "上": (-1, 0), "下": (1, 0)}
def mock_decision(instruction, last_target):
    """Mock 模式：不用大模型，靠关键词和正则猜一个目标。
    由于使用正则和关键词搜索，只能适用于特殊，简单的命令
    """
    text = instruction.strip()

    # 1. 用户直接说坐标，比如 (3,2) 或 （3，2）
    match = re.search(r"[（(]\s*(\d+)\s*[，,]\s*(\d+)\s*[)）]", text)
    if match:
        # 从正则中获取第一个数字给x，第二个数字给y
        x, y = int(match.group(1)), int(match.group(2))
        if 0 <= x < 6 and 0 <= y < 6:
            return _intent(x, y, f"好的，去坐标({x},{y})。")
        return {
            "action": "unclear",
            "target_x": None,
            "target_y": None,
            "reply": f"坐标 ({x},{y}) 超出 0~5 的范围。",
        }

    # 2. 相对移动，比如往左一格，要基于上一轮的目标
    match = re.search(r"往(右|左|上|下)\s*([一二两三四五])?\s*格", text)
    if match:
        if last_target is None:
            return {
                "action": "unclear",
                "target_x": None,
                "target_y": None,
                "reply": "我还没有上一轮目标，请先告诉我要去哪个位置。",
            }
        # 将移动默认值设置为1
        steps = NUMBER_WORDS.get(match.group(2), 1) if match.group(2) else 1
        dx, dy = MOVE_STEP[match.group(1)]
        x = last_target[0] + dx * steps
        y = last_target[1] + dy * steps
        if 0 <= x < 6 and 0 <= y < 6:
            return _intent(x, y, f"好的，从上一轮目标往{(match.group(1))}移动{steps}格。")
        return {
            "action": "unclear",
            "target_x": None,
            "target_y": None,
            "reply": f"再往{match.group(1)}移动 {steps} 格会超出边界，请直接说要去的格子。",
        }

    # 3. 停止/取消
    if "停" in text or "取消" in text:
        return {"action": "stop", "target_x": None, "target_y": None, "reply": "好的，已停止。"}

    # 4. 常见位置关键词
    for word, (x, y) in MOCK_WORDS:
        if word in text:
            return _intent(x, y, f"好的，去。{word}{x},{y}")

    # 5. 实在没听懂，就追问
    return {
        "action": "unclear",
        "target_x": None,
        "target_y": None,
        "reply": "我没听清具体位置，可以说“右下角”或“坐标(3,2)”。",
    }


def get_decision(instruction, history, last_target, task_state, use_mock, logger, retries=5):
    """
    调用 DeepSeek 模型，返回解析好的指令字典；失败时抛 RuntimeError。
    :param instruction: 命令
    :param history: 历史会话内容，列表
    :param last_target: 上一轮目标
    :param task_state: 当前任务状态
    :param use_mock: 是否使用 Mock 模式
    :param logger: 日志记录器，填入日志的实例对象
    :param retries: 重试次数
    :return: 解析好的指令字典
    """
    if use_mock:
        decision = mock_decision(instruction, last_target)
        logger.debug(f"Mock 模型结果: {json.dumps(decision, ensure_ascii=False)}")
        return decision

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            logger.debug(f"第{attempt}次调用 DeepSeek（历史{len(history)}轮）")
            raw = call_deepseek(history, instruction, task_state)
            logger.debug(f"DeepSeek 原始输出：{raw}")
            return parse_json(raw)
        except ValueError as e:
            # 返回格式不对：加一句提醒再问一次
            last_error = e
            logger.warning(f"模型输出格式不对：{e}")
            instruction = instruction + "\n（上次输出不是合法 JSON，请只输出 JSON。）"
        except Exception as e:
            # 网络错误、超时、Key 错误等
            last_error = e
            logger.warning(f"调用 DeepSeek 出错：{e}")
            time.sleep(1)

    raise RuntimeError(str(last_error))
if __name__ == "__main__":
    from logger_setup import setup_logger
    print(get_decision("去右下角", [], None, "task_state", False, logger=setup_logger()))
