#!/usr/bin/env python3
"""Vendor the `vulnagent` package into each function folder before deploying.

Appwrite builds every function from its own directory, so it cannot see the uv
workspace. This copies the shared package in and writes the merged
requirements. Run it before `appwrite push functions`.

    uv run python scripts/build_functions.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "backend" / "src" / "vulnagent"
FUNCTIONS = ROOT / "backend" / "functions"

IGNORED = shutil.ignore_patterns("__pycache__", "*.pyc", ".mypy_cache", ".ruff_cache")


def vendor(function_dir: Path) -> None:
    destination = function_dir / "src" / "vulnagent"
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(PACKAGE, destination, ignore=IGNORED)
    print(f"  vendored vulnagent -> {destination.relative_to(ROOT)}")


def main() -> int:
    if not PACKAGE.is_dir():
        print(f"cannot find the package at {PACKAGE}", file=sys.stderr)
        return 1

    functions = sorted(path for path in FUNCTIONS.iterdir() if (path / "src").is_dir())
    if not functions:
        print(f"no functions found under {FUNCTIONS}", file=sys.stderr)
        return 1

    for function_dir in functions:
        print(f"{function_dir.name}:")
        vendor(function_dir)

    print(f"\nbuilt {len(functions)} functions. Deploy with: appwrite push functions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
