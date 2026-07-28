from __future__ import annotations

import shutil
import sys
from pathlib import Path

from core.scheduler import Scheduler
from loop_cli.config import LoopConfig


def run_doctor(repo: str | None = None) -> dict:
    scheduler = Scheduler.default()
    checks = []
    checks.append(_check("python", True, sys.version.split()[0], "Python is available."))
    git_path = shutil.which("git")
    checks.append(_check("git", git_path is not None, git_path or "missing", "Install Git and ensure it is on PATH."))
    checks.append(_check("runtime", True, "local", "Local runtime is available."))
    checks.append(_check("adapters", bool(scheduler.agent_registry.list_adapters()), scheduler.agent_registry.adapter_names(), "Register at least one agent adapter."))
    checks.append(_check("tools", bool(scheduler.tool_registry.names()), scheduler.tool_registry.names(), "Register runtime tools."))
    config = LoopConfig.load()
    config_detail = str(config.path) if config.path.exists() else f"defaults active; config path {config.path}"
    checks.append(_check("configuration", True, config_detail, ""))
    repo_ok = False
    repo_detail = "not checked"
    if repo:
        repo_path = Path(repo)
        repo_ok = (repo_path / ".git").exists() or (repo_path / ".git").is_file()
        repo_detail = str(repo_path)
    checks.append(_check("worktree", (not repo) or repo_ok, repo_detail, "Pass --repo pointing to a Git repository."))
    return {"ok": all(item["ok"] for item in checks), "checks": checks}


def _check(name: str, ok: bool, detail, action: str) -> dict:
    return {"name": name, "ok": ok, "detail": detail, "action": "" if ok else action}
