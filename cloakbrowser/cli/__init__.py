"""Agent-friendly CLI utilities for cloakbrowser."""

from __future__ import annotations

import json
import sys
from typing import Any


def output(data: Any, as_json: bool = False) -> None:
    """Print data as JSON or human-readable text."""
    if as_json:
        json.dump(data, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        if isinstance(data, str):
            print(data)
        elif isinstance(data, dict):
            for k, v in data.items():
                print(f"{k}: {v}")
        elif isinstance(data, list):
            for item in data:
                print(item)
        else:
            print(data)


def fail(msg: str, exit_code: int = 1) -> None:
    """Print error to stderr and exit."""
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(exit_code)
