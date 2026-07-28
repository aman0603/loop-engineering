from __future__ import annotations

import argparse
import json
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from agents.adapters import CodexCLIAdapter, MockAgentAdapter
from core.scheduler import Scheduler
from core.task_manager import Task
from loop_cli.config import LoopConfig
from loop_cli.diagnostics import run_doctor
from loop_cli.output import emit, fail


WORKFLOW_ALIASES = {
    "feature": "feature-development",
    "feature-development": "feature-development",
    "bug": "bug-fix",
    "bug-fix": "bug-fix",
    "code-review": "code-review",
    "documentation": "documentation",
    "docs": "documentation",
    "refactoring": "refactoring",
    "test-generation": "test-generation",
    "dependency-upgrade": "dependency-upgrade",
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return args.handler(args)
    except KeyError as exc:
        return fail(str(exc), json_output=getattr(args, "json", False))
    except ValueError as exc:
        return fail(str(exc), json_output=getattr(args, "json", False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="loop", description="Loop Engineering workflow runner")
    parser.add_argument("--json", action="store_true", help="emit JSON output")
    parser.add_argument("--quiet", action="store_true", help="suppress human-readable output")
    parser.add_argument("--verbose", action="store_true", help="emit verbose details")
    sub = parser.add_subparsers(dest="command")

    _command(sub, "version", "show version", command_version)
    _command(sub, "workflows", "list workflows", command_workflows)
    _command(sub, "agents", "list agents", command_agents)
    _command(sub, "adapters", "list adapters", command_adapters)
    _command(sub, "doctor", "run diagnostics", command_doctor).add_argument("--repo")
    _command(sub, "init", "initialize loop config", command_init)

    config = _command(sub, "config", "manage configuration", command_config)
    config_sub = config.add_subparsers(dest="config_command")
    _command(config_sub, "init", "initialize config", command_config_init).add_argument("--force", action="store_true")
    _command(config_sub, "show", "show config", command_config_show)
    config_set = _command(config_sub, "set", "set config value", command_config_set)
    config_set.add_argument("key")
    config_set.add_argument("value")

    run = _command(sub, "run", "run workflow", command_run)
    _add_run_args(run)

    new_project = _command(sub, "new-project", "plan and execute a new project workflow", command_new_project)
    new_project.add_argument("--goal", required=True)
    new_project.add_argument("--repo")
    new_project.add_argument("--adapter")
    new_project.add_argument("--model")
    new_project.add_argument("--parameters")
    new_project.add_argument("--dry-run", action="store_true")

    benchmark = _command(sub, "benchmark", "run workflow benchmark", command_benchmark)
    benchmark.add_argument("target", nargs="?", default="all", choices=["bug-fix", "feature", "feature-development", "all"])
    benchmark.add_argument("--repo")

    return parser


def _command(subparsers, name: str, help_text: str, handler):
    parser = subparsers.add_parser(name, help=help_text)
    parser.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--quiet", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", action="store_true", help=argparse.SUPPRESS)
    parser.set_defaults(handler=handler)
    return parser


def _add_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("workflow", nargs="?", help="workflow name")
    parser.add_argument("--workflow", dest="workflow_option", help="workflow name")
    parser.add_argument("--repo")
    parser.add_argument("--goal", required=False)
    parser.add_argument("--issue")
    parser.add_argument("--parameters")
    parser.add_argument("--adapter")
    parser.add_argument("--model")
    parser.add_argument("--dry-run", action="store_true")


def command_version(args) -> int:
    try:
        value = version("loop-engineering")
    except PackageNotFoundError:
        value = "0.1.0"
    emit({"version": value} if args.json else f"loop {value}", args.json, args.quiet)
    return 0


def command_workflows(args) -> int:
    scheduler = Scheduler.default()
    workflows = [
        {"name": workflow.name, "metadata": workflow.metadata, "outputs": workflow.outputs}
        for workflow in scheduler.workflow_registry.list_workflows()
    ]
    emit(workflows if args.json else [item["name"] for item in workflows], args.json, args.quiet)
    return 0


def command_agents(args) -> int:
    scheduler = Scheduler.default()
    agents = [{"name": agent.name} for agent in scheduler.agent_registry.list()]
    emit(agents if args.json else [item["name"] for item in agents], args.json, args.quiet)
    return 0


def command_adapters(args) -> int:
    scheduler = Scheduler.default()
    adapters = [
        {
            "name": adapter.name,
            "provider": adapter.provider,
            "model": adapter.model,
            "capabilities": [cap.name for cap in adapter.capabilities()],
            "healthy": adapter.health().available,
        }
        for adapter in scheduler.agent_registry.list_adapters()
    ]
    emit(adapters if args.json else [f"{item['name']} ({', '.join(item['capabilities'])})" for item in adapters], args.json, args.quiet)
    return 0


def command_doctor(args) -> int:
    result = run_doctor(repo=args.repo)
    if args.json:
        emit(result, True, args.quiet)
    else:
        lines = [f"{'OK' if item['ok'] else 'FAIL'} {item['name']}: {item['detail']}" for item in result["checks"]]
        emit(lines, False, args.quiet)
    return 0 if result["ok"] else 1


def command_init(args) -> int:
    return command_config_init(args)


def command_config(args) -> int:
    if not getattr(args, "config_command", None):
        return command_config_show(args)
    return args.handler(args)


def command_config_init(args) -> int:
    config = LoopConfig.load()
    config.init(force=getattr(args, "force", False))
    emit({"path": str(config.path), "config": config.data} if getattr(args, "json", False) else f"initialized {config.path}", getattr(args, "json", False), getattr(args, "quiet", False))
    return 0


def command_config_show(args) -> int:
    config = LoopConfig.load()
    emit(config.data, getattr(args, "json", False), getattr(args, "quiet", False))
    return 0


def command_config_set(args) -> int:
    config = LoopConfig.load()
    config.set_value(args.key, args.value)
    emit({"key": args.key, "value": config.data} if getattr(args, "json", False) else f"set {args.key}", getattr(args, "json", False), getattr(args, "quiet", False))
    return 0


def command_run(args) -> int:
    workflow = _resolve_workflow(args.workflow_option or args.workflow)
    goal = args.goal or args.issue or f"Run {workflow}"
    parameters = _parse_parameters(args.parameters)
    scheduler = _scheduler_for(args.repo, args.adapter, args.model)
    if args.dry_run:
        definition = scheduler.workflow_registry.load_workflow(workflow)
        task = Task(title=f"Dry run: {workflow}", description=goal, goal=goal, max_attempts=int(parameters.get("max_retries", 3)))
        plan = definition.to_execution_plan(task, parameters=parameters, registry=scheduler.workflow_registry)
        output = {"workflow": workflow, "dry_run": True, "plan": plan.to_dict()}
    else:
        task = scheduler.run_workflow(workflow, goal, parameters)
        output = _task_output(task, verbose=args.verbose)
    emit(output if args.json else _human_run_output(output), args.json, args.quiet)
    return 0


def command_new_project(args) -> int:
    parameters = _parse_parameters(args.parameters)
    parameters.setdefault("description", args.goal)
    workflow = "feature-development"
    scheduler = _scheduler_for(args.repo, args.adapter, args.model)
    if args.dry_run:
        definition = scheduler.workflow_registry.load_workflow(workflow)
        task = Task(title="New project", description=args.goal, goal=args.goal)
        output = {"workflow": workflow, "dry_run": True, "plan": definition.to_execution_plan(task, parameters=parameters, registry=scheduler.workflow_registry).to_dict()}
    else:
        output = _task_output(scheduler.run_workflow(workflow, args.goal, parameters))
    emit(output if getattr(args, "json", False) else _human_run_output(output), getattr(args, "json", False), getattr(args, "quiet", False))
    return 0


def command_benchmark(args) -> int:
    targets = ["bug-fix", "feature-development"] if args.target == "all" else [_resolve_workflow(args.target)]
    scheduler = _scheduler_for(args.repo, None, None)
    results = []
    for workflow in targets:
        started = time.monotonic()
        task = scheduler.run_workflow(workflow, f"Benchmark {workflow}", {"max_retries": 1})
        duration_ms = (time.monotonic() - started) * 1000
        snapshot = task.metadata.get("last_execution", {})
        results.append(
            {
                "workflow": workflow,
                "success": task.status.value == "DONE",
                "execution_time_ms": duration_ms,
                "retry_count": snapshot.get("retries", 0),
                "verification": snapshot.get("verification_results", []),
                "artifacts": len(snapshot.get("artifacts", [])),
            }
        )
    emit({"benchmarks": results} if args.json else [_format_benchmark(item) for item in results], args.json, getattr(args, "quiet", False))
    return 0


def _scheduler_for(repo: str | None, adapter: str | None, model: str | None) -> Scheduler:
    config = LoopConfig.load()
    repo_value = repo or (config.data.get("worktree", {}) or {}).get("repo")
    scheduler = Scheduler.runtime_default(repo_value) if repo_value else Scheduler.default()
    adapter_name = adapter or config.data.get("default_adapter")
    if adapter_name == "codex":
        scheduler.agent_registry.unregister_adapter("mock.agent")
        scheduler.agent_registry.register_adapter(CodexCLIAdapter(model=model or "codex-default"))
    elif adapter_name and adapter_name != "mock":
        # Unknown adapters can still be configured by applications using the registry API.
        pass
    return scheduler


def _parse_parameters(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    if value.startswith("@"):
        return json.loads(Path(value[1:]).read_text(encoding="utf-8"))
    try:
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("--parameters must decode to a JSON object")
        return parsed
    except json.JSONDecodeError:
        result: dict[str, Any] = {}
        for item in value.split(","):
            if not item:
                continue
            key, _, raw = item.partition("=")
            result[key.strip()] = _coerce(raw.strip())
        return result


def _coerce(value: str) -> Any:
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        return int(value)
    except ValueError:
        return value


def _resolve_workflow(value: str | None) -> str:
    if not value:
        raise ValueError("workflow is required")
    return WORKFLOW_ALIASES.get(value, value)


def _task_output(task: Task, verbose: bool = False) -> dict[str, Any]:
    data = {
        "task_id": task.id,
        "status": task.status.value,
        "workflow": task.metadata.get("workflow_library"),
        "plan_id": task.metadata.get("last_plan", {}).get("id"),
        "artifacts": len(task.metadata.get("last_execution", {}).get("artifacts", [])),
        "success": task.status.value == "DONE",
    }
    if verbose:
        data["execution"] = task.metadata.get("last_execution", {})
        data["plan"] = task.metadata.get("last_plan", {})
    return data


def _human_run_output(output: dict[str, Any]) -> str:
    if output.get("dry_run"):
        return f"dry run workflow={output['workflow']} steps={len(output['plan']['steps'])}"
    return f"workflow={output.get('workflow')} status={output.get('status')} artifacts={output.get('artifacts')}"


def _format_benchmark(item: dict[str, Any]) -> str:
    return f"{item['workflow']}: success={item['success']} time_ms={item['execution_time_ms']:.2f} artifacts={item['artifacts']}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
