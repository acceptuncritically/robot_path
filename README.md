# 具身 Agent 小车 Python 大脑端

自然语言指令进入大模型，解析成 6×6 栅格目标坐标，按固定 JSON 协议发给 C 端寻路程序，再把状态和路径翻译成中文反馈。

## 目录结构

```text
robot_remove/
├── brain/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── errors.py
│   ├── feedback.py
│   ├── grid.py
│   ├── logging_setup.py
│   ├── prompt.py
│   ├── protocol.py
│   ├── session.py
│   ├── text_json.py
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── mock_client.py
│   │   └── openai_client.py
│   ├── planning/
│   │   ├── __init__.py
│   │   ├── output_parser.py
│   │   └── planner.py
│   └── transport/
│       ├── __init__.py
│       ├── base.py
│       ├── json_framer.py
│       ├── mock_transport.py
│       ├── serial_transport.py
│       └── tcp_transport.py
├── tests/
├── tools/
│   └── mock_c_server.py
├── docs/
│   └── c_integration_notes.md
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## 快速开始

环境要求 Python 3.10 以上，核心功能只使用标准库。

```powershell
cd E:\deepseek\robot_remove
$env:PYTHONUTF8='1'

python -m brain
python main.py
python -m brain --selftest
python -m brain --once "去迷宫右下角"
python -m unittest discover -s tests -v
```

离线演示使用 Mock 大模型和 Mock 传输层，不需要 API Key 和硬件。Mock 传输层按 C 端实际 A* 程序的行为返回多行格式化 JSON，并带一行 C 端控制台横幅，用于验证解析兼容性。

## 接入真实大模型

```powershell
$env:BRAIN_LLM_PROVIDER='openai'
$env:BRAIN_LLM_BASE_URL='https://dashscope.aliyuncs.com/compatible-mode/v1'
$env:BRAIN_LLM_API_KEY='sk-你的Key'
$env:BRAIN_LLM_MODEL='qwen-plus'
python -m brain
```

本地 Ollama 示例：

```powershell
$env:BRAIN_LLM_PROVIDER='openai'
$env:BRAIN_LLM_BASE_URL='http://127.0.0.1:11434/v1'
$env:BRAIN_LLM_MODEL='qwen2.5:7b'
$env:BRAIN_LLM_API_KEY='ollama'
python -m brain
```

也可以复制 `.env.example` 为 `.env` 后填写。系统环境变量优先于 `.env` 文件。

## 与 C 端对接

固定协议：

```text
Python 下发:   {"target_x": 5, "target_y": 5}
C 端成功:      {"path":[{"x":0,"y":0},{"x":1,"y":0}],"status":"running"}
C 端失败:      {"path":[],"status":"fail"}
```

坐标约定：6×6 栅格，左上角 (0,0)，x 表示行且向下增大，y 表示列且向右增大，范围 0 到 5。

C 端实际程序输出的是 cJSON 格式化多行 JSON，并带有 `===== 上报JSON =====` 横幅和中文日志。Python 端会从任意文本中提取完整 JSON 对象并严格校验字段、类型、范围和状态，因此两种格式都能解析。

详细分析见 [docs/c_integration_notes.md](docs/c_integration_notes.md)。

## TCP 联调彩排

```powershell
cd E:\deepseek\robot_remove
python tools\mock_c_server.py --port 9000

cd E:\deepseek\robot_remove
python -m brain --transport tcp --tcp-port 9000
```

只跑一条指令验证链路：

```powershell
python -m brain --transport tcp --tcp-port 9000 --once "去迷宫右下角"
```

模拟 C 端支持 normal、fail、timeout、malformed、unknown_status 五种模式。

串口联调优先方案，需要先安装 pyserial：

```powershell
pip install pyserial
python -m brain --transport serial --serial-port COM3 --baudrate 115200
```

## 协议与行为要点

- 下发报文为紧凑单行 JSON，以换行结尾，字段只有 target_x 和 target_y，值为 0 到 5 的整数。
- 不合法目标绝不发送，包括越界、格式错误和无法确定目标。
- 大模型输出出现多个不同目标时按歧义处理并重试，不猜测。
- 回包支持多行格式化 JSON、字段顺序任意、额外字段忽略。
- 等待回包超时、非法回包、未知状态、通信断开都会给出中文反馈且不会崩溃。
- 新任务下发前会清理上一任务迟到或残留的回包，避免任务错配。
- 任务串行处理，带并发保护，可连续对话。

## 配置项

大模型：

- BRAIN_LLM_PROVIDER，mock 或 openai
- BRAIN_LLM_BASE_URL
- BRAIN_LLM_API_KEY，也可使用 DASHSCOPE_API_KEY 或 OPENAI_API_KEY
- BRAIN_LLM_MODEL
- BRAIN_LLM_TIMEOUT
- BRAIN_LLM_MAX_RETRIES
- BRAIN_LLM_TEMPERATURE
- BRAIN_LLM_MAX_TOKENS

通信：

- BRAIN_TRANSPORT，mock、tcp 或 serial
- BRAIN_TCP_HOST
- BRAIN_TCP_PORT
- BRAIN_SERIAL_PORT
- BRAIN_BAUDRATE
- BRAIN_CONNECT_TIMEOUT
- BRAIN_REPORT_TIMEOUT

日志：

- BRAIN_LOG_FILE
- BRAIN_VERBOSE

## 命名规范

- 文件和目录使用小写加下划线的 snake_case，例如 output_parser.py。
- 类和枚举使用 PascalCase，例如 TargetPlanner、TaskStatus。
- 函数、方法、变量和属性使用 snake_case，例如 build_target_message、report_timeout。
- 常量使用大写加下划线，例如 GRID_SIZE、STATUS_RUNNING。
- 代码不写注释和文档字符串，通过命名和结构表达意图。

## 测试

共 149 个标准库 unittest 用例，覆盖协议编解码、JSON 分帧、大模型输出解析、规划重试、会话状态机、Mock 传输层、TCP 真实 socket 通信、GBK 噪声兼容、配置和命令行。运行：

```powershell
python -m unittest discover -s tests -v
```

## 已知限制

- 当前 C 端程序仍处于控制台仿真阶段，目标坐标写死为 (5,5)，未实现从标准输入、串口或 TCP 读取指令，需要按联调说明改造后才能与 Python 端真实互通。
- 串口链路依赖 pyserial 和实际硬件，本机未验证。
- 真实大模型接口需要配置有效 API Key 后验证。
- TCP 或串口断开后不会自动重连，需要重新启动程序。
- path 是否包含起点和终点已经由 C 端 A* 代码确认包含，其余通信层细节仍需联调确认。