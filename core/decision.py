from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.execution import ExecutionContext
from verification.pipeline import VerificationReport


class Decision(str, Enum):
    RETRY = "RETRY"
    CHANGE_SKILL = "CHANGE_SKILL"
    CHANGE_AGENT = "CHANGE_AGENT"
    ESCALATE = "ESCALATE"
    ABORT = "ABORT"
    COMPLETE = "COMPLETE"


@dataclass(frozen=True, slots=True)
class DecisionResult:
    decision: Decision
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


class DecisionEngine:
    def decide(self, context: ExecutionContext, verification: VerificationReport | None = None) -> DecisionResult:
        if context.cancelled:
            return DecisionResult(Decision.ABORT, "execution was cancelled")
        if verification is not None and verification.passed:
            return DecisionResult(Decision.COMPLETE, "verification passed", verification.metrics)
        if context.retry_count >= context.retry_limit:
            return DecisionResult(
                Decision.ABORT,
                "retry limit reached",
                {"retry_count": context.retry_count, "retry_limit": context.retry_limit},
            )

        failure_count = len(verification.failed_results) if verification is not None else 0
        if failure_count > 0:
            return DecisionResult(
                Decision.RETRY,
                "verification failed and retry budget remains",
                {"failure_count": failure_count, "retry_count": context.retry_count},
            )
        return DecisionResult(Decision.ABORT, "no actionable verification result")

