from collections import deque

from .protocol import GRID_SIZE, PathPoint, Target

START_X = 0
START_Y = 0
OBSTACLES = frozenset({(2, 1), (2, 4), (3, 4), (3, 5), (4, 4)})
DIRECTIONS = ((1, 0), (0, 1), (-1, 0), (0, -1))


def is_inside(x: int, y: int) -> bool:
    return 0 <= x < GRID_SIZE and 0 <= y < GRID_SIZE


def is_blocked(x: int, y: int) -> bool:
    return not is_inside(x, y) or (x, y) in OBSTACLES


def find_path(target: Target, start: tuple[int, int] | None = None) -> list[PathPoint] | None:
    start_x, start_y = start if start is not None else (START_X, START_Y)
    goal_x, goal_y = target.x, target.y
    if is_blocked(start_x, start_y) or is_blocked(goal_x, goal_y):
        return None
    start_node = (start_x, start_y)
    goal_node = (goal_x, goal_y)
    if start_node == goal_node:
        return [PathPoint(x=start_x, y=start_y)]
    parents: dict[tuple[int, int], tuple[int, int] | None] = {start_node: None}
    queue: deque[tuple[int, int]] = deque([start_node])
    while queue:
        current = queue.popleft()
        for delta_x, delta_y in DIRECTIONS:
            neighbor = (current[0] + delta_x, current[1] + delta_y)
            if neighbor in parents or is_blocked(neighbor[0], neighbor[1]):
                continue
            parents[neighbor] = current
            if neighbor == goal_node:
                return _reconstruct(parents, goal_node)
            queue.append(neighbor)
    return None


def _reconstruct(
    parents: dict[tuple[int, int], tuple[int, int] | None],
    node: tuple[int, int],
) -> list[PathPoint]:
    nodes: list[tuple[int, int]] = []
    current: tuple[int, int] | None = node
    while current is not None:
        nodes.append(current)
        current = parents[current]
    nodes.reverse()
    return [PathPoint(x=x, y=y) for x, y in nodes]