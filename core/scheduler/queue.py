from __future__ import annotations

import heapq
from itertools import count

from core.task_manager.models import Task


class TaskPriorityQueue:
    def __init__(self) -> None:
        self._counter = count()
        self._heap: list[tuple[int, int, str]] = []
        self._queued: set[str] = set()

    def push(self, task: Task) -> None:
        if task.id in self._queued:
            return
        heapq.heappush(self._heap, (task.priority, next(self._counter), task.id))
        self._queued.add(task.id)

    def pop(self) -> str | None:
        while self._heap:
            _, _, task_id = heapq.heappop(self._heap)
            if task_id in self._queued:
                self._queued.remove(task_id)
                return task_id
        return None

    def __len__(self) -> int:
        return len(self._queued)

