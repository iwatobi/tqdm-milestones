"""Enforce direct 100% coverage between implementation and test modules."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRECTORY = PROJECT_ROOT / "src" / "tqdm_milestones"
TEST_DIRECTORY = PROJECT_ROOT / "tests" / "tqdm_milestones"


def _discover_module_pairs() -> tuple[tuple[Path, Path], ...]:
    """Match every implementation module to exactly one test module.

    Returns:
        tuple[tuple[Path, Path], ...]: Test and implementation module pairs.

    Raises:
        RuntimeError: If an implementation lacks a test module, a test module
            lacks an implementation, or two implementations map to one test.
    """
    pairs: list[tuple[Path, Path]] = []
    expected_tests: set[Path] = set()
    for source_path in sorted(SOURCE_DIRECTORY.rglob("*.py")):
        relative_source = source_path.relative_to(SOURCE_DIRECTORY)
        test_name = (
            "test_package.py"
            if source_path.name == "__init__.py"
            else f"test_{source_path.stem.removeprefix('_')}.py"
        )
        test_path = TEST_DIRECTORY / relative_source.parent / test_name
        if test_path in expected_tests:
            raise RuntimeError(f"multiple implementation modules map to {test_path.name}")
        expected_tests.add(test_path)
        if not test_path.is_file():
            raise RuntimeError(f"{source_path.name} has no matching {test_path.name}")
        pairs.append((test_path, source_path))

    unexpected_tests = set(TEST_DIRECTORY.rglob("test_*.py")) - expected_tests
    if unexpected_tests:
        names = ", ".join(path.name for path in sorted(unexpected_tests))
        raise RuntimeError(f"test modules without matching implementations: {names}")
    return tuple(pairs)


def _run(command: tuple[str, ...]) -> None:
    """Run one coverage command from the project root.

    Args:
        command (tuple[str, ...]): Command and arguments to execute.

    Raises:
        subprocess.CalledProcessError: If the command exits unsuccessfully.
    """
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def main() -> None:
    """Verify every test module fully covers its corresponding implementation."""
    coverage = (sys.executable, "-m", "coverage")
    try:
        for test_path, source_path in _discover_module_pairs():
            relative_test = test_path.relative_to(PROJECT_ROOT).as_posix()
            relative_source = source_path.relative_to(PROJECT_ROOT).as_posix()
            print(f"Checking {relative_test} -> {relative_source}", flush=True)
            _run((*coverage, "erase"))
            _run((*coverage, "run", "-m", "pytest", relative_test))
            _run((*coverage, "report", f"--include={relative_source}", "--fail-under=100"))
    finally:
        _run((*coverage, "erase"))


if __name__ == "__main__":
    main()
