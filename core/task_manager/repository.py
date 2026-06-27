from __future__ import annotations

import json
import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

from core.task_manager.models import Task


class TaskRepository(ABC):
    @abstractmethod
    def save(self, task: Task) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, task_id: str) -> Task | None:
        raise NotImplementedError

    @abstractmethod
    def list(self) -> list[Task]:
        raise NotImplementedError

    @abstractmethod
    def delete(self, task_id: str) -> None:
        raise NotImplementedError


class InMemoryTaskRepository(TaskRepository):
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def save(self, task: Task) -> None:
        self._tasks[task.id] = task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list(self) -> list[Task]:
        return list(self._tasks.values())

    def delete(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)


class JsonTaskRepository(TaskRepository):
    """Small durable repository for Phase 1 local execution state."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({})

    def save(self, task: Task) -> None:
        tasks = self._read()
        tasks[task.id] = task.to_dict()
        self._write(tasks)

    def get(self, task_id: str) -> Task | None:
        data = self._read().get(task_id)
        return Task.from_dict(data) if data else None

    def list(self) -> list[Task]:
        return [Task.from_dict(data) for data in self._read().values()]

    def delete(self, task_id: str) -> None:
        tasks = self._read()
        tasks.pop(task_id, None)
        self._write(tasks)

    def _read(self) -> dict[str, dict]:
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write(self, data: dict[str, dict]) -> None:
        fd, tmp_name = tempfile.mkstemp(prefix=f"{self.path.name}.", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

