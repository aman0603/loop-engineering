from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Sequence
from uuid import uuid4

from core.artifacts import CommandArtifact, RuntimeLogArtifact
from core.events import Event, EventType
from core.execution import CancellationToken, ExecutionContext


class CommandStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class CommandSpec:
    args: list[str]
    cwd: Path | None = None
    env: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float | None = None
    retries: int = 0
    stream_output: bool = False
    name: str | None = None


@dataclass(slots=True)
class CommandResult:
    command_id: str
    args: list[str]
    cwd: str | None
    stdout: str
    stderr: str
    exit_code: int | None
    duration_ms: float
    status: CommandStatus
    attempts: int = 1

    @property
    def success(self) -> bool:
        return self.status == CommandStatus.SUCCEEDED and self.exit_code == 0

    def to_dict(self) -> dict:
        return {
            "command_id": self.command_id,
            "args": self.args,
            "cwd": self.cwd,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "status": self.status.value,
            "attempts": self.attempts,
            "success": self.success,
        }


class CommandHandle:
    def __init__(
        self,
        thread: threading.Thread,
        cancel_token: CancellationToken,
        result_holder: dict[str, CommandResult],
    ) -> None:
        self._thread = thread
        self.cancel_token = cancel_token
        self._result_holder = result_holder

    def cancel(self, reason: str | None = None) -> None:
        self.cancel_token.cancel(reason or "command cancelled")

    def result(self, timeout: float | None = None) -> CommandResult:
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise TimeoutError("command is still running")
        return self._result_holder["result"]

    @property
    def done(self) -> bool:
        return not self._thread.is_alive()


StreamCallback = Callable[[str, str], None]


class CommandRunner:
    def run(
        self,
        spec: CommandSpec,
        context: ExecutionContext,
        stream_callback: StreamCallback | None = None,
    ) -> CommandResult:
        command_id = f"cmd_{uuid4().hex}"
        attempts = 0
        last_result: CommandResult | None = None
        total_allowed = max(0, spec.retries) + 1

        while attempts < total_allowed:
            attempts += 1
            result = self._run_once(command_id, spec, context, stream_callback)
            result.attempts = attempts
            last_result = result
            if result.success:
                break
            if result.status in {CommandStatus.CANCELLED, CommandStatus.TIMED_OUT}:
                break

        assert last_result is not None
        context.add_artifact(CommandArtifact("command_runner", last_result.to_dict(), name=spec.name or "command"))
        context.metrics.increment("commands_executed")
        if not last_result.success:
            context.metrics.increment("commands_failed")
        return last_result

    def run_async(
        self,
        spec: CommandSpec,
        context: ExecutionContext,
        stream_callback: StreamCallback | None = None,
    ) -> CommandHandle:
        cancel_token = CancellationToken()
        result_holder: dict[str, CommandResult] = {}
        child_context = context

        def target() -> None:
            if cancel_token.cancelled:
                child_context.cancellation_token.cancel(cancel_token.reason)
            result_holder["result"] = self.run(spec, child_context, stream_callback)

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        return CommandHandle(thread, cancel_token, result_holder)

    def _run_once(
        self,
        command_id: str,
        spec: CommandSpec,
        context: ExecutionContext,
        stream_callback: StreamCallback | None,
    ) -> CommandResult:
        started = time.monotonic()
        cwd = Path(spec.cwd or context.runtime_variables.get("working_directory") or os.getcwd())
        env = {**os.environ, **context.configuration.environment, **spec.env}
        context.emit(
            Event(
                EventType.COMMAND_STARTED,
                context.task.id,
                {"command_id": command_id, "args": spec.args, "cwd": str(cwd), "name": spec.name},
            )
        )
        process = subprocess.Popen(
            spec.args,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        status = CommandStatus.FAILED
        exit_code: int | None = None
        timed_out = False

        try:
            if spec.stream_output:
                exit_code, timed_out = self._communicate_streaming(
                    process,
                    spec.timeout_seconds,
                    context.cancellation_token,
                    stdout_chunks,
                    stderr_chunks,
                    stream_callback,
                )
            else:
                stdout, stderr = process.communicate(timeout=spec.timeout_seconds)
                stdout_chunks.append(stdout)
                stderr_chunks.append(stderr)
                exit_code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            stdout, stderr = process.communicate()
            stdout_chunks.append(stdout)
            stderr_chunks.append(stderr)

        if context.cancelled:
            if process.poll() is None:
                process.kill()
            status = CommandStatus.CANCELLED
        elif timed_out:
            status = CommandStatus.TIMED_OUT
        elif exit_code == 0:
            status = CommandStatus.SUCCEEDED
        else:
            status = CommandStatus.FAILED

        result = CommandResult(
            command_id=command_id,
            args=list(spec.args),
            cwd=str(cwd),
            stdout="".join(stdout_chunks),
            stderr="".join(stderr_chunks),
            exit_code=exit_code,
            duration_ms=(time.monotonic() - started) * 1000,
            status=status,
        )
        context.add_artifact(RuntimeLogArtifact("command_runner", result.to_dict(), command_id=command_id))
        context.emit(
            Event(
                EventType.COMMAND_CANCELLED if status == CommandStatus.CANCELLED else EventType.COMMAND_FINISHED,
                context.task.id,
                {"command_id": command_id, "status": status.value, "exit_code": exit_code},
            )
        )
        return result

    def _communicate_streaming(
        self,
        process: subprocess.Popen[str],
        timeout_seconds: float | None,
        cancellation_token: CancellationToken,
        stdout_chunks: list[str],
        stderr_chunks: list[str],
        stream_callback: StreamCallback | None,
    ) -> tuple[int | None, bool]:
        deadline = time.monotonic() + timeout_seconds if timeout_seconds else None
        while process.poll() is None:
            if cancellation_token.cancelled:
                process.kill()
                return process.returncode, False
            if deadline is not None and time.monotonic() > deadline:
                process.kill()
                return process.returncode, True
            time.sleep(0.01)

        stdout, stderr = process.communicate()
        stdout_chunks.append(stdout)
        stderr_chunks.append(stderr)
        if stream_callback and stdout:
            stream_callback("stdout", stdout)
        if stream_callback and stderr:
            stream_callback("stderr", stderr)
        return process.returncode, False

