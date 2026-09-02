"""Shared validation and output-mode resolution."""

from __future__ import annotations

import logging
import math
import os
from collections.abc import Mapping
from numbers import Real
from types import MappingProxyType
from typing import Any, TextIO, cast

from ._events import ProgressMode

_VALID_FINAL_EVENT_POLICIES = frozenset({"always", "after_milestone", "never"})
_VALID_MODES = frozenset({"auto", "tty", "log", "disabled"})
_MODE_ENV_VAR = "TQDM_MILESTONES_MODE"
_LOG_RECORD_RESERVED_KEYS = frozenset(logging.makeLogRecord({}).__dict__) | {
    "asctime",
    "message",
}
_LOG_EXTRA_PREFIX = "progress_"


def _is_int(value: object) -> bool:
    """Return whether a value is an integer but not a boolean.

    Args:
        value (object): Value to inspect.

    Returns:
        bool: ``True`` for a non-boolean integer.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite_real(value: Real) -> bool:
    """Return whether a real number is finite.

    Args:
        value (Real): Value to inspect.

    Returns:
        bool: ``True`` for a finite real number.
    """
    try:
        return math.isfinite(float(value))
    except (OverflowError, TypeError, ValueError):
        return False


def _validate_extra_fields(extra_fields: Mapping[object, Any]) -> None:
    """Validate structured logging field names.

    Args:
        extra_fields (Mapping[object, Any]): Structured logging fields whose names are validated.

    Raises:
        TypeError: If a field name is not a string.
        ValueError: If a key collides with logging or package fields.
    """
    field_names: list[str] = []
    for key in extra_fields:
        if not isinstance(key, str):
            raise TypeError("extra_fields keys must be strings")
        field_names.append(key)
    reserved_extra_fields = _LOG_RECORD_RESERVED_KEYS.intersection(field_names)
    if reserved_extra_fields:
        names = ", ".join(sorted(reserved_extra_fields))
        raise ValueError(f"extra_fields contains reserved logging fields: {names}")
    namespaced_extra_fields = sorted(
        key for key in field_names if key.startswith(_LOG_EXTRA_PREFIX)
    )
    if namespaced_extra_fields:
        names = ", ".join(namespaced_extra_fields)
        raise ValueError(f"extra_fields contains reserved progress fields: {names}")


def _snapshot_extra_fields(extra_fields: object) -> Mapping[str, Any]:
    """Copy and validate structured logging fields.

    Args:
        extra_fields (object): Structured logging fields to copy.

    Returns:
        Mapping[str, Any]: Immutable validated field snapshot.

    Raises:
        TypeError: If the value is not a string-keyed mapping.
        ValueError: If a key collides with logging or package fields.
    """
    if not isinstance(extra_fields, Mapping):
        raise TypeError("extra_fields must be a mapping")
    copied_fields: dict[Any, Any] = dict(extra_fields)
    _validate_extra_fields(copied_fields)
    return MappingProxyType(cast(dict[str, Any], copied_fields))


def _validate_progress_values(
    *,
    total: object,
    initial: object,
    unit: object,
    unit_scale: object,
    unit_divisor: object,
) -> None:
    """Validate values shared by TTY and log progress implementations.

    Args:
        total (object): Expected item count or ``None``.
        initial (object): Initial completed-item count.
        unit (object): Item label.
        unit_scale (object): Unit scaling setting.
        unit_divisor (object): Unit scaling divisor.

    Raises:
        TypeError: If a value has an invalid type.
        ValueError: If a value is outside its valid range.
    """
    if total is not None and not _is_int(total):
        raise TypeError("total must be an integer or None")
    if total is not None and cast(int, total) < 0:
        raise ValueError("total must be >= 0")
    if not _is_int(initial):
        raise TypeError("initial must be an integer")
    if cast(int, initial) < 0:
        raise ValueError("initial must be >= 0")
    if total is not None and cast(int, initial) > cast(int, total):
        raise ValueError("initial must not exceed total")
    if not isinstance(unit, str):
        raise TypeError("unit must be a string")
    if not isinstance(unit_scale, bool):
        if not isinstance(unit_scale, Real):
            raise TypeError("unit_scale must be a boolean or real number")
        if not _is_finite_real(unit_scale) or float(unit_scale) <= 0:
            raise ValueError("numeric unit_scale must be finite and > 0")
    if not isinstance(unit_divisor, Real) or isinstance(unit_divisor, bool):
        raise TypeError("unit_divisor must be a real number")
    if not _is_finite_real(unit_divisor) or float(unit_divisor) <= 0:
        raise ValueError("unit_divisor must be finite and > 0")


def _validate_reporting_options(
    *,
    desc: object,
    seconds_step: object,
    percent_step: object,
    count_step: object,
    bar_width: object,
    file: object,
    logger: object,
    log_level: object,
    logger_stacklevel: object,
    callback: object,
    emit_start: object,
    final_event: object,
    max_milestones_per_update: object,
) -> None:
    """Validate reporting options shared across output modes.

    Args:
        desc (object): Optional progress label.
        seconds_step (object): Time-trigger interval.
        percent_step (object): Percentage-trigger interval.
        count_step (object): Count-trigger interval.
        bar_width (object): Plain progress bar width.
        file (object): TTY bar or fallback plain text destination.
        logger (object): Optional logging destination.
        log_level (object): Python logging level.
        logger_stacklevel (object): Python logger stack level.
        callback (object): Structured event callback.
        emit_start (object): Start-event control.
        final_event (object): Final-event policy.
        max_milestones_per_update (object): Per-update safety limit for raw
            trigger crossings and deduplicated events.

    Raises:
        TypeError: If an option has an invalid type.
        ValueError: If an option is outside its valid range or conflicts with
            another option.
    """
    if desc is not None and not isinstance(desc, str):
        raise TypeError("desc must be a string or None")
    if seconds_step is not None:
        if not isinstance(seconds_step, Real) or isinstance(seconds_step, bool):
            raise TypeError("seconds_step must be a real number or None")
        if not _is_finite_real(seconds_step) or seconds_step < 0:
            raise ValueError("seconds_step must be finite and >= 0")
    if percent_step is not None:
        if not isinstance(percent_step, Real) or isinstance(percent_step, bool):
            raise TypeError("percent_step must be a real number or None")
        if not _is_finite_real(percent_step) or not (0.0 < float(percent_step) <= 100.0):
            raise ValueError("percent_step must be finite and in (0, 100]")
    if count_step is not None and not _is_int(count_step):
        raise TypeError("count_step must be an integer or None")
    if count_step is not None and cast(int, count_step) <= 0:
        raise ValueError("count_step must be > 0")
    if not _is_int(bar_width):
        raise TypeError("bar_width must be an integer")
    if cast(int, bar_width) <= 0:
        raise ValueError("bar_width must be > 0")
    if not callable(getattr(file, "write", None)):
        raise TypeError("file must be a writable text stream")
    if logger is not None and not isinstance(logger, logging.Logger):
        raise TypeError("logger must be a Logger or None")
    if not _is_int(log_level):
        raise TypeError("log_level must be an integer")
    if not _is_int(logger_stacklevel):
        raise TypeError("logger_stacklevel must be an integer")
    if cast(int, logger_stacklevel) <= 0:
        raise ValueError("logger_stacklevel must be > 0")
    if callback is not None and not callable(callback):
        raise TypeError("callback must be callable or None")
    if callback is not None and logger is not None:
        raise ValueError("callback and logger are mutually exclusive")
    if not isinstance(emit_start, bool):
        raise TypeError("emit_start must be a boolean")
    if not isinstance(final_event, str):
        raise TypeError("final_event must be a string")
    if final_event not in _VALID_FINAL_EVENT_POLICIES:
        raise ValueError(f"final_event must be one of {sorted(_VALID_FINAL_EVENT_POLICIES)}")
    if not _is_int(max_milestones_per_update):
        raise TypeError("max_milestones_per_update must be an integer")
    if cast(int, max_milestones_per_update) <= 0:
        raise ValueError("max_milestones_per_update must be > 0")


def _resolve_mode(mode: ProgressMode, file: TextIO) -> ProgressMode:
    """Resolve explicit and environment-driven output modes.

    Args:
        mode (ProgressMode): Requested output mode.
        file (TextIO): Stream whose TTY status is inspected in automatic mode.

    Returns:
        ProgressMode: A concrete ``tty``, ``log``, or ``disabled`` mode.

    Raises:
        TypeError: If ``mode`` is not a string.
        ValueError: If ``mode`` or ``TQDM_MILESTONES_MODE`` has an unsupported
            value.
    """
    if not isinstance(mode, str):
        raise TypeError("mode must be a string")
    if mode not in _VALID_MODES:
        raise ValueError(f"mode must be one of {sorted(_VALID_MODES)}")

    selected_mode = os.getenv(_MODE_ENV_VAR, "auto") if mode == "auto" else mode
    if selected_mode not in _VALID_MODES:
        raise ValueError(f"{_MODE_ENV_VAR} must be one of {sorted(_VALID_MODES)}")
    if selected_mode != "auto":
        return cast(ProgressMode, selected_mode)
    return "tty" if bool(getattr(file, "isatty", lambda: False)()) else "log"
