from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ExecutionConfig:
    retry_limit: int = 3
    workflow_name: str = "default_engineering"
    scheduler_policy: str = "priority"
    verification_timeout_seconds: float | None = None
    workflow_timeout_seconds: float | None = None
    logging: dict[str, Any] = field(default_factory=dict)
    agents: dict[str, str] = field(default_factory=dict)
    skills: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

