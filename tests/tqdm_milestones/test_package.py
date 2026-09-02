"""Tests for the package-level public API."""

from __future__ import annotations

import inspect

import pytest

import tqdm_milestones as package
from tqdm_milestones import (
    ProgressReporter,
    _events as events_module,
    _iterator as iterator_module,
    _reporter as reporter_module,
    tqdm_iter,
)


def test_public_call_signatures_require_keywords_after_primary_inputs() -> None:
    """Verify only primary inputs can be passed positionally in public APIs."""
    reporter_signature = inspect.signature(ProgressReporter)
    assert reporter_signature.parameters["total"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert reporter_signature.parameters["desc"].kind is inspect.Parameter.KEYWORD_ONLY
    assert inspect.signature(tqdm_iter).parameters["iterable"].kind is (
        inspect.Parameter.POSITIONAL_OR_KEYWORD
    )
    assert inspect.signature(tqdm_iter).parameters["total"].kind is (
        inspect.Parameter.KEYWORD_ONLY
    )

    ProgressReporter(1, mode="disabled")
    with pytest.raises(TypeError, match="positional argument"):
        ProgressReporter(1, "work")  # ty: ignore[too-many-positional-arguments]


def test_package_reexports_the_supported_public_api() -> None:
    """Verify the package root exposes exactly the supported public API."""
    assert package.__all__ == [
        "FinalEventPolicy",
        "ProgressEvent",
        "ProgressMode",
        "ProgressReporter",
        "tqdm_iter",
    ]
    assert package.FinalEventPolicy is events_module.FinalEventPolicy
    assert package.ProgressEvent is events_module.ProgressEvent
    assert package.ProgressMode is events_module.ProgressMode
    assert package.ProgressReporter is reporter_module.ProgressReporter
    assert package.tqdm_iter is iterator_module.tqdm_iter
