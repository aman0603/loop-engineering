from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from core.artifacts import BuildArtifact, TestArtifact, VerificationArtifact
from core.events import Event, EventType
from core.execution import ExecutionContext
from core.task_manager.models import Task, VerificationOutcome, VerificationResult, utc_now
from runtime import CommandSpec, LocalRuntime, Runtime
from skills.base import SkillContext


class VerificationCheck(ABC):
    name: str

    @abstractmethod
    def run(self, context: ExecutionContext) -> VerificationResult:
        raise NotImplementedError

    def execute(self, context: ExecutionContext) -> VerificationResult:
        parameter_count = len(inspect.signature(self.run).parameters)
        if parameter_count == 1:
            return self.run(context)
        if parameter_count == 2:
            return self.run(context.task, context)  # type: ignore[misc]
        raise TypeError(f"unsupported run signature for verifier '{self.name}'")


@dataclass(slots=True)
class VerificationReport:
    results: list[VerificationResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.results) and all(result.passed for result in self.results)

    @property
    def failed_results(self) -> list[VerificationResult]:
        return [result for result in self.results if not result.passed]

    @property
    def metrics(self) -> dict[str, float | int]:
        return {
            "checks": len(self.results),
            "failures": len(self.failed_results),
            "duration_ms": sum(result.duration_ms for result in self.results),
        }


class ArtifactExistsCheck(VerificationCheck):
    def __init__(self, artifact_key: str) -> None:
        self.artifact_key = artifact_key
        self.name = f"artifact_exists.{artifact_key}"

    def run(self, context: ExecutionContext) -> VerificationResult:
        started_at = utc_now()
        exists = self.artifact_key in context.artifact_store
        return VerificationResult(
            name=self.name,
            outcome=VerificationOutcome.PASSED if exists else VerificationOutcome.FAILED,
            summary=(
                f"artifact '{self.artifact_key}' exists"
                if exists
                else f"artifact '{self.artifact_key}' is missing"
            ),
            details={"artifact_key": self.artifact_key},
            started_at=started_at,
            finished_at=utc_now(),
        )


class CriteriaCoverageCheck(VerificationCheck):
    name = "criteria_coverage"

    def run(self, context: ExecutionContext) -> VerificationResult:
        started_at = utc_now()
        implementation = context.artifact_store.latest_content("implementation", {})
        covered = set(implementation.get("acceptance_criteria", []))
        required = set(context.task.acceptance_criteria)
        missing = sorted(required - covered)
        passed = not missing
        return VerificationResult(
            name=self.name,
            outcome=VerificationOutcome.PASSED if passed else VerificationOutcome.FAILED,
            summary="all acceptance criteria are covered" if passed else "acceptance criteria are missing",
            details={"missing": missing},
            started_at=started_at,
            finished_at=utc_now(),
        )


class CommandVerificationCheck(VerificationCheck):
    def __init__(
        self,
        name: str,
        command: list[str],
        runtime: Runtime | None = None,
        optional: bool = False,
        timeout_seconds: float | None = None,
    ) -> None:
        self.name = name
        self.command = command
        self.runtime = runtime or LocalRuntime()
        self.optional = optional
        self.timeout_seconds = timeout_seconds

    def run(self, context: ExecutionContext) -> VerificationResult:
        started_at = utc_now()
        result = self.runtime.execute(
            CommandSpec(
                args=self.command,
                cwd=context.working_directory,
                timeout_seconds=self.timeout_seconds,
                name=f"verify.{self.name}",
            ),
            context,
        ).result
        passed = result.success or self.optional
        artifact_content = result.to_dict()
        if "test" in self.name or "pytest" in self.name:
            context.add_artifact(TestArtifact(self.name, artifact_content, optional=self.optional))
        else:
            context.add_artifact(BuildArtifact(self.name, artifact_content, optional=self.optional))
        context.emit(
            Event(
                EventType.TESTS_PASSED if passed else EventType.TESTS_FAILED,
                context.task.id,
                {"check": self.name, "exit_code": result.exit_code, "optional": self.optional},
            )
        )
        return VerificationResult(
            name=self.name,
            outcome=VerificationOutcome.PASSED if passed else VerificationOutcome.FAILED,
            summary=f"{self.name} passed" if passed else f"{self.name} failed",
            details={"command": self.command, "result": result.to_dict(), "optional": self.optional},
            metrics={"duration_ms": result.duration_ms},
            started_at=started_at,
            finished_at=utc_now(),
        )


class VerificationPipeline:
    name = "verification.pipeline"

    def __init__(self, checks: list[VerificationCheck] | None = None) -> None:
        self.checks = checks or [
            ArtifactExistsCheck("plan"),
            ArtifactExistsCheck("implementation"),
            CriteriaCoverageCheck(),
        ]

    def run(
        self,
        context_or_task: ExecutionContext | Task,
        maybe_context: SkillContext | ExecutionContext | None = None,
    ) -> VerificationReport:
        if isinstance(context_or_task, ExecutionContext):
            context = context_or_task
        else:
            context = ExecutionContext(task=context_or_task)
            if isinstance(maybe_context, ExecutionContext):
                context = maybe_context
            elif isinstance(maybe_context, SkillContext):
                context.merge_artifacts(maybe_context.artifacts)
                context.feedback = maybe_context.feedback
                context.execution_metadata.update(maybe_context.metadata)

        context.emit(Event(EventType.VERIFICATION_STARTED, context.task.id, {"checks": len(self.checks)}))
        results = [check.execute(context) for check in self.checks]
        report = VerificationReport(results=results)
        context.verification_results.extend(results)
        context.add_artifact(VerificationArtifact(self.name, [result.to_dict() for result in results]))
        for result in results:
            context.task.record_verification(result)
        for name, value in report.metrics.items():
            context.metrics.set(f"verification.{name}", value)
        context.emit(
            Event(
                EventType.VERIFICATION_PASSED if report.passed else EventType.VERIFICATION_FAILED,
                context.task.id,
                report.metrics,
            )
        )
        context.emit(
            Event(
                EventType.VERIFICATION_EXECUTED,
                context.task.id,
                {"passed": report.passed, **report.metrics},
            )
        )
        return report


class RuntimeVerificationPipeline(VerificationPipeline):
    @classmethod
    def from_context(cls, context: ExecutionContext, runtime: Runtime | None = None) -> "RuntimeVerificationPipeline":
        checks: list[VerificationCheck] = []
        for name, command in context.configuration.verification_commands.items():
            checks.append(
                CommandVerificationCheck(
                    name=name,
                    command=command,
                    runtime=runtime,
                    timeout_seconds=context.configuration.verification_timeout_seconds,
                )
            )
        return cls(checks)
