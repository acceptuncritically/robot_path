# C 端代码分析与联调说明

## 代码来源

微信缓存目录中的副本已不可用，实际读取的是本机另一份副本：

```text
E:\下载缓存\project\project
```

主要文件：

- planner/main.c
- planner/astar.c
- planner/astar.h
- planner/cJSON.c
- planner/cJSON.h
- data/grid.txt
- vision/test.py
- vision/M_matrix.txt
- CMakeLists.txt

## C 端当前行为

main.c 当前是一个控制台仿真程序：

1. 从固定绝对路径 C:\Users\Redmi\Desktop\project\data\grid.txt 读取 6×6 栅格。
2. 使用写死的字符串 {"target_x":5,"target_y":5} 模拟收到 Python 指令。
3. cJSON 解析 target_x 和 target_y，要求两者都是数字。
4. 检查目标坐标在 0 到 5 范围内、目标点不是障碍物、起点不是障碍物。
5. 从 (0,0) 调用 A* 寻路，路径包含起点和终点，A* 使用曼哈顿距离启发式。
6. 用 cJSON_Print 将结果格式化打印到标准输出，前面带一行横幅。

成功输出示例：

```text
===== 上报JSON =====
{
    "path": [
        {
            "x": 0,
            "y": 0
        },
        {
            "x": 1,
            "y": 0
        }
    ],
    "status": "running"
}
```

失败输出示例：

```text
===== 上报JSON =====
{
    "path": [],
    "status": "fail"
}
```

失败场景包括目标越界、目标点为障碍物、起点为障碍物、A* 找不到路径。

## 栅格与坐标语义

data/grid.txt 内容：

```text
0 0 0 0 0 0
0 0 0 0 0 0
0 1 0 0 1 0
0 0 0 0 1 1
0 0 0 0 1 0
0 0 0 0 0 0
```

按行读取，即 maze[x][y]，x 是行号向下增大，y 是列号向右增大，与 Python 端坐标约定一致。

障碍物坐标：

```text
(2,1)
(2,4)
(3,4)
(3,5)
(4,4)
```

起点固定为 (0,0)。路径数组包含起点和终点。

vision/test.py 的 IPM 栅格同样使用 grid[r][c] 对应 x=r、y=c，路径绘制时也是 x 作为行、y 作为列，三端坐标定义一致。

## 协议对照

Python 下发：

```json
{"target_x":5,"target_y":5}
```

C 端 cJSON 解析只要求 target_x 和 target_y 是数字，不关心空格、字段顺序和末尾换行，因此 Python 的紧凑单行 JSON 可以直接使用。

C 端回包：

```json
{"path":[{"x":0,"y":0},{"x":1,"y":0}],"status":"running"}
```

字段顺序为 path 在前、status 在后，cJSON_Print 会输出多行格式化文本。Python 端使用 JSON 对象提取器和 JSON 分帧器处理，不依赖单行格式和字段顺序。

## 联调前需要在 C 端完成的改造

1. 将写死的 mock_recv_json 替换为真实输入：从标准输入、串口或 TCP 读取一行或一段 JSON。
2. 将回包发送到同一通信通道：当前只打印到标准输出，串口或 TCP 联调时需要改为写串口或写 socket。
3. 将 grid.txt 绝对路径改为相对路径或由命令行参数传入，避免依赖特定电脑的用户目录。
4. 建议每条报文之间保留换行分隔；Python 端按 JSON 括号配对分帧，不强制单行，但单行更便于人工排查。
5. 确认串口参数，默认按 115200、8N1 处理。
6. 如果后续增加到达终点、避障失败等新状态，需要双方同时更新状态枚举和文档。

## Python 端已做的兼容处理

- 支持单行紧凑 JSON 和多行格式化 JSON。
- 支持 JSON 前后存在横幅、中文日志、空行等噪声。
- 串口和 TCP 解码使用 UTF-8 替换模式，C 端控制台输出中的 GBK 中文横幅或日志不会导致连接报错，只会作为噪声被忽略；建议通信通道上只发送 JSON 本身。
- 严格校验 status 只能是 running 或 fail。
- 严格校验 path 为数组、每个点为对象、x 和 y 为 0 到 5 的整数。
- 支持 running 路径包含起点和终点；running 空路径和 fail 非空路径按协议错误处理。
- 新任务下发前清理上一任务残留或迟到回包，避免错配。
- Mock 传输层和模拟 C 端服务器使用与 C 端相同的 6×6 障碍地图和 A* 可达性语义。

## 当前无法直接互通的原因

C 端 main.c 没有命令行参数，也不读取标准输入，目标坐标被写死，因此 Python 端即使通过进程管道启动它，也无法改变目标点。必须先在 C 端实现指令输入通道，才能进行真实联调。