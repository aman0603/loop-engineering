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
    RETRY_COMMAND = "RETRY_COMMAND"
    ROLLBACK_WORKTREE = "ROLLBACK_WORKTREE"
    RECREATE_RUNTIME = "RECREATE_RUNTIME"
    SKIP_OPTIONAL_STEP = "SKIP_OPTIONAL_STEP"


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

    def decide_recovery(self, context: ExecutionContext, failure: dict[str, Any]) -> DecisionResult:
        if context.cancelled:
            return DecisionResult(Decision.ABORT, "execution was cancelled")
        if failure.get("optional"):
            return DecisionResult(Decision.SKIP_OPTIONAL_STEP, "optional failure can be skipped", failure)
        if failure.get("kind") == "command" and int(failure.get("attempts", 1)) <= context.configuration.command_retries:
            return DecisionResult(Decision.RETRY_COMMAND, "command retry budget remains", failure)
        if failure.get("kind") == "worktree":
            return DecisionResult(Decision.ROLLBACK_WORKTREE, "worktree failure requires rollback", failure)
        if failure.get("kind") == "runtime":
            return DecisionResult(Decision.RECREATE_RUNTIME, "runtime should be recreated", failure)
        return DecisionResult(Decision.ABORT, "failure is not recoverable", failure)
