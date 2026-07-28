from __future__ import annotations

import json
import sys
from typing import Any


def emit(data: Any, json_output: bool = False, quiet: bool = False) -> None:
    if quiet:
        return
    if json_output:
        print(json.dumps(data, indent=2, sort_keys=True, default=str))
        return
    if isinstance(data, str):
        print(data)
        return
    if isinstance(data, list):
        for item in data:
            print(item if isinstance(item, str) else json.dumps(item, sort_keys=True, default=str))
        return
    if isinstance(data, dict):
        for key, value in data.items():
            print(f"{key}: {value}")
        return
    print(data)


def fail(message: str, code: int = 1, json_output: bool = False) -> int:
    if json_output:
        print(json.dumps({"ok": False, "error": message}, indent=2, sort_keys=True), file=sys.stderr)
    else:
        print(f"error: {message}", file=sys.stderr)
    return code

