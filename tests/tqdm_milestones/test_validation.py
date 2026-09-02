"""Tests for shared configuration validation."""

from __future__ import annotations

import logging

import pytest

from tqdm_milestones import _validation as validation_module

from ._support import Stream


def _validate_options(**overrides: object) -> None:
    """Run all validators with valid defaults and selected overrides.

    Args:
        **overrides (object): Option values that replace the valid defaults.
    """
    values: dict[str, object] = {
        "total": 1,
        "initial": 0,
        "unit": "it",
        "unit_scale": False,
        "unit_divisor": 1000,
        "desc": None,
        "seconds_step": 3600,
        "percent_step": 10.0,
        "count_step": None,
        "bar_width": 20,
        "file": Stream(),
        "logger": None,
        "log_level": logging.INFO,
        "logger_stacklevel": 3,
        "extra_fields": {},
        "callback": None,
        "emit_start": False,
        "final_event": "always",
        "max_milestones_per_update": 10_000,
    }
    values.update(overrides)
    validation_module._validate_progress_values(
        total=values["total"],
        initial=values["initial"],
        unit=values["unit"],
        unit_scale=values["unit_scale"],
        unit_divisor=values["unit_divisor"],
    )
    validation_module._snapshot_extra_fields(values["extra_fields"])
    validation_module._validate_reporting_options(
        desc=values["desc"],
        seconds_step=values["seconds_step"],
        percent_step=values["percent_step"],
        count_step=values["count_step"],
        bar_width=values["bar_width"],
        file=values["file"],
        logger=values["logger"],
        log_level=values["log_level"],
        logger_stacklevel=values["logger_stacklevel"],
        callback=values["callback"],
        emit_start=values["emit_start"],
        final_event=values["final_event"],
        max_milestones_per_update=values["max_milestones_per_update"],
    )


def test_progress_value_validation_is_keyword_only() -> None:
    """Verify internal progress validation rejects order-sensitive positional calls."""
    with pytest.raises(TypeError, match="positional argument"):
        validation_module._validate_progress_values(  # ty: ignore[missing-argument]
            1,  # ty: ignore[too-many-positional-arguments]
            0,
            "it",
            False,
            1000,
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"total": 1.5}, "total must be an integer or None"),
        ({"total": 1, "initial": 0.5}, "initial must be an integer"),
        ({"total": 1, "seconds_step": True}, "seconds_step must be a real number"),
        ({"total": 1, "percent_step": "10"}, "percent_step must be a real number"),
        ({"total": 1, "count_step": 1.5}, "count_step must be an integer"),
        ({"total": 1, "bar_width": True}, "bar_width must be an integer"),
        ({"total": 1, "file": object()}, "file must be a writable text stream"),
        ({"total": 1, "logger": object()}, "logger must be a Logger"),
        ({"total": 1, "desc": 1}, "desc must be a string or None"),
        ({"total": 1, "unit": 1}, "unit must be a string"),
        ({"total": 1, "unit_scale": object()}, "unit_scale must be a boolean"),
        ({"total": 1, "unit_divisor": True}, "unit_divisor must be a real number"),
        ({"total": 1, "log_level": True}, "log_level must be an integer"),
        (
            {"total": 1, "logger_stacklevel": True},
            "logger_stacklevel must be an integer",
        ),
        ({"total": 1, "emit_start": 1}, "emit_start must be a boolean"),
        ({"total": 1, "final_event": []}, "final_event must be a string"),
        ({"total": 1, "extra_fields": []}, "extra_fields must be a mapping"),
        ({"total": 1, "extra_fields": {1: "x"}}, "extra_fields keys must be strings"),
        ({"total": 1, "callback": 1}, "callback must be callable or None"),
        (
            {"total": 1, "max_milestones_per_update": 1.5},
            "max_milestones_per_update must be an integer",
        ),
    ],
)
def test_type_validation(kwargs: dict[str, object], message: str) -> None:
    """Verify invalid configuration types raise descriptive errors.

    Args:
        kwargs (dict[str, object]): Invalid configuration overrides under test.
        message (str): Expected fragment of the validation error message.
    """
    with pytest.raises(TypeError, match=message):
        _validate_options(**kwargs)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"total": -1}, "total must be >= 0"),
        ({"total": 1, "seconds_step": -1}, "seconds_step must be finite and >= 0"),
        ({"total": 1, "percent_step": 0}, "percent_step must be finite and in"),
        ({"total": 1, "percent_step": 101}, "percent_step must be finite and in"),
        ({"total": 1, "count_step": 0}, "count_step must be > 0"),
        ({"total": 1, "bar_width": 0}, "bar_width must be > 0"),
        ({"total": 1, "logger_stacklevel": 0}, "logger_stacklevel must be > 0"),
        (
            {"total": 1, "max_milestones_per_update": 0},
            "max_milestones_per_update must be > 0",
        ),
        (
            {"total": 1, "seconds_step": float("nan")},
            "seconds_step must be finite and >= 0",
        ),
        (
            {"total": 1, "seconds_step": 10**400},
            "seconds_step must be finite and >= 0",
        ),
        (
            {"total": 1, "percent_step": float("inf")},
            "percent_step must be finite and in",
        ),
        ({"total": 1, "initial": -1}, "initial must be >= 0"),
        ({"total": 1, "initial": 2}, "initial must not exceed total"),
        (
            {"total": 1, "unit_scale": float("nan")},
            "numeric unit_scale must be finite and > 0",
        ),
        ({"total": 1, "unit_scale": 0}, "numeric unit_scale must be finite and > 0"),
        ({"total": 1, "unit_scale": -1}, "numeric unit_scale must be finite and > 0"),
        ({"total": 1, "unit_divisor": 0}, "unit_divisor must be finite and > 0"),
        (
            {"total": 1, "unit_divisor": float("inf")},
            "unit_divisor must be finite and > 0",
        ),
        ({"total": 1, "final_event": "sometimes"}, "final_event must be one of"),
        (
            {"total": 1, "extra_fields": {"message": "x", "name": "x"}},
            "extra_fields contains reserved logging fields: message, name",
        ),
        (
            {"total": 1, "extra_fields": {"progress_current": "x"}},
            "extra_fields contains reserved progress fields: progress_current",
        ),
        (
            {
                "total": 1,
                "logger": logging.getLogger("exclusive"),
                "callback": lambda event: None,
            },
            "callback and logger are mutually exclusive",
        ),
    ],
)
def test_value_validation(kwargs: dict[str, object], message: str) -> None:
    """Verify invalid configuration values raise descriptive errors.

    Args:
        kwargs (dict[str, object]): Invalid configuration overrides under test.
        message (str): Expected fragment of the validation error message.
    """
    with pytest.raises(ValueError, match=message):
        _validate_options(**kwargs)


def test_validation_accepts_optional_triggers_and_numeric_unit_scaling() -> None:
    """Verify valid disabled triggers and numeric unit scaling pass validation."""
    _validate_options(
        total=None,
        initial=3,
        unit_scale=2.5,
        unit_divisor=1024,
        seconds_step=None,
        percent_step=None,
        count_step=None,
        max_milestones_per_update=1,
    )


def test_extra_field_snapshot_is_detached_validated_and_immutable() -> None:
    """Verify extra-field snapshots cannot change with their input mapping."""
    fields = {"job_id": "one"}
    snapshot = validation_module._snapshot_extra_fields(fields)

    fields["job_id"] = "two"
    assert snapshot == {"job_id": "one"}
    with pytest.raises(TypeError, match="does not support item assignment"):
        snapshot["job_id"] = "three"  # ty: ignore[invalid-assignment]

    with pytest.raises(TypeError, match="extra_fields must be a mapping"):
        validation_module._snapshot_extra_fields([])


def test_mode_validation_and_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify explicit, automatic, and environment-selected output modes.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest fixture used to replace process state or
            dependencies.
    """
    with pytest.raises(TypeError, match="mode must be a string"):
        validation_module._resolve_mode([], Stream())  # ty: ignore[invalid-argument-type]

    with pytest.raises(ValueError, match="mode must be one of"):
        validation_module._resolve_mode("bad", Stream())  # ty: ignore[invalid-argument-type]

    monkeypatch.setenv("TQDM_MILESTONES_MODE", "bad")
    with pytest.raises(ValueError, match="TQDM_MILESTONES_MODE must be"):
        validation_module._resolve_mode("auto", Stream())

    monkeypatch.setenv("TQDM_MILESTONES_MODE", "disabled")
    assert validation_module._resolve_mode("auto", Stream(True)) == "disabled"
    assert validation_module._resolve_mode("log", Stream(True)) == "log"
    monkeypatch.delenv("TQDM_MILESTONES_MODE")
    assert validation_module._resolve_mode("auto", Stream(True)) == "tty"
    assert (
        validation_module._resolve_mode(
            "auto",
            object(),  # ty: ignore[invalid-argument-type]
        )
        == "log"
    )
