"""Tests for progress event data."""

from __future__ import annotations

import pytest

from tqdm_milestones import ProgressEvent


def test_progress_event_log_fields() -> None:
    """Verify event fields convert to logging extras and construction is keyword-only."""
    event = ProgressEvent(
        current=2,
        milestone=1,
        total=2,
        current_percent=100.0,
        milestone_percent=50.0,
        elapsed_seconds=3.0,
        eta_seconds=0.0,
        description="work",
        message="message",
    )
    assert event.as_log_extra() == {
        "progress_current": 2,
        "progress_milestone": 1,
        "progress_total": 2,
        "progress_current_percent": 100.0,
        "progress_milestone_percent": 50.0,
        "progress_elapsed_seconds": 3.0,
        "progress_eta_seconds": 0.0,
        "progress_description": "work",
        "progress_message": "message",
    }

    with pytest.raises(TypeError, match="positional argument"):
        ProgressEvent(  # ty: ignore[missing-argument]
            2,  # ty: ignore[too-many-positional-arguments]
            1,
            2,
            100.0,
            50.0,
            3.0,
            0.0,
            "work",
            "message",
        )
