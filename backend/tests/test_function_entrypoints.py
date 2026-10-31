"""Every Appwrite function must import and expose a callable `main`.

These entry points are never exercised by the rest of the suite, so without
this a typo in one of them only shows up after a deploy.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

FUNCTIONS = Path(__file__).resolve().parent.parent / "functions"
SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"

EXPECTED = ["hydra"]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve annotations through sys.modules, so register first.
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


@pytest.mark.parametrize("function", EXPECTED)
def test_the_function_imports_and_exposes_a_main(function):
    module = load(FUNCTIONS / function / "src" / "main.py", f"vulnagent_fn_{function}")

    assert callable(module.main)


@pytest.mark.parametrize("function", EXPECTED)
def test_the_function_declares_its_dependencies(function):
    requirements = (FUNCTIONS / function / "requirements.txt").read_text()

    assert "appwrite" in requirements


@pytest.mark.parametrize("function", EXPECTED)
def test_the_function_installs_exactly_the_versions_the_tests_ran_against(function):
    import re
    import tomllib

    lock = tomllib.loads((Path(__file__).resolve().parents[2] / "uv.lock").read_text())
    locked = {package["name"]: package["version"] for package in lock["package"]}
    lines = (FUNCTIONS / function / "requirements.txt").read_text().splitlines()
    requirements = [line for line in lines if line.strip() and not line.startswith("#")]

    pins = {
        re.sub(r"\[.*\]", "", name).lower(): version
        for name, _, version in (line.partition("==") for line in requirements)
    }

    project = tomllib.loads((FUNCTIONS.parent / "pyproject.toml").read_text())
    declared = {
        re.split(r"[\[<>=]", dependency, maxsplit=1)[0].lower()
        for dependency in project["project"]["dependencies"]
    }

    assert pins == {name: locked[name] for name in declared}
    assert all("==" in line for line in requirements)


def test_every_destination_has_a_handler():
    from typing import get_args

    from vulnagent.entrypoints.main import HANDLERS
    from vulnagent.entrypoints.routing import Destination
    from vulnagent.entrypoints.tasks import Task

    routed = {*get_args(Task.__value__), *get_args(get_args(Destination.__value__)[1])}

    assert set(HANDLERS) == routed - {"forbidden"}


def test_every_function_folder_is_accounted_for():
    found = {path.name for path in FUNCTIONS.iterdir() if (path / "src").is_dir()}

    assert found == set(EXPECTED)


@pytest.mark.parametrize(
    "script",
    ["bootstrap_db.py", "bootstrap_vectors.py", "seed_memory.py", "reset_test_rows.py"],
)
def test_the_script_imports(script):
    module = load(SCRIPTS / script, f"vulnagent_script_{script.removesuffix('.py')}")

    assert callable(module.main)


def test_the_packaging_script_imports():
    module = load(SCRIPTS / "build_functions.py", "vulnagent_script_build_functions")

    assert callable(module.main)
