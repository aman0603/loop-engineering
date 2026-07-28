from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = {
    "default_adapter": "mock",
    "default_runtime": "local",
    "verification_policy": "standard",
    "retry_limits": 3,
    "logging": {"level": "info"},
    "worktree": {"enabled": False, "root": None},
}


def config_dir() -> Path:
    override = os.environ.get("LOOP_CONFIG_HOME")
    if override:
        return Path(override)
    return Path.home() / ".config" / "loop-engineering"


def config_path() -> Path:
    return config_dir() / "config.json"


@dataclass(slots=True)
class LoopConfig:
    data: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_CONFIG))
    path: Path = field(default_factory=config_path)

    @classmethod
    def load(cls) -> "LoopConfig":
        path = config_path()
        if not path.exists():
            return cls(path=path)
        return cls(data={**DEFAULT_CONFIG, **json.loads(path.read_text(encoding="utf-8"))}, path=path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")

    def init(self, force: bool = False) -> None:
        if self.path.exists() and not force:
            return
        self.data = dict(DEFAULT_CONFIG)
        self.save()

    def set_value(self, key: str, value: Any) -> None:
        parts = key.split(".")
        target = self.data
        for part in parts[:-1]:
            current = target.setdefault(part, {})
            if not isinstance(current, dict):
                raise ValueError(f"cannot set nested value under non-object key '{part}'")
            target = current
        target[parts[-1]] = self._coerce(value)
        self.save()

    def _coerce(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        lowered = value.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered == "null":
            return None
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            return value

