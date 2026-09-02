"""Iterable wrapper implementation."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping, Sized
from typing import Any, TextIO, TypeVar

from tqdm import tqdm

from ._events import FinalEventPolicy, ProgressEvent, ProgressMode
from ._reporter import ProgressReporter
from ._validation import (
    _resolve_mode,
    _snapshot_extra_fields,
    _validate_progress_values,
    _validate_reporting_options,
)

T = TypeVar("T")
_REMOVED_OPTIONS = {
    "log_complete": "final_event",
    "log_start": "emit_start",
    "stream": "file",
}


def _iterate_with_reporter(
    iterable: Iterable[T],
    reporter: ProgressReporter,
    initial: int,
) -> Iterator[T]:
    """Yield items while updating a preconfigured reporter.

    Args:
        iterable (Iterable[T]): Iterable whose progress is reported.
        reporter (ProgressReporter): Reporter updated after every yielded item.
        initial (int): Completed-item count before iteration starts.

    Yields:
        T: Items from ``iterable`` without modification.
    """
    with reporter:
        for index, item in enumerate(iterable, start=initial + 1):
            yield item
            reporter.advance_to(index)


def tqdm_iter(
    iterable: Iterable[T],
    *,
    total: int | None = None,
    desc: str | None = None,
    initial: int = 0,
    unit: str = "it",
    unit_scale: bool | float = False,
    unit_divisor: float = 1000,
    disable: bool | None = False,
    file: TextIO | None = None,
    seconds_step: float | None = 60 * 60,
    percent_step: float | None = 10.0,
    count_step: int | None = None,
    bar_width: int = 20,
    logger: logging.Logger | None = None,
    log_level: int = logging.INFO,
    logger_stacklevel: int = 3,
    extra_fields: Mapping[str, Any] | None = None,
    callback: Callable[[ProgressEvent], None] | None = None,
    mode: ProgressMode = "auto",
    emit_start: bool = False,
    final_event: FinalEventPolicy = "always",
    max_milestones_per_update: int = 10_000,
    **tqdm_kwargs: Any,
) -> Iterator[T]:
    """Return an iterator with TTY-aware deterministic progress reporting.

    Configuration is validated before the iterator is returned. Additional
    tqdm display options are forwarded only in TTY mode.

    Args:
        iterable (Iterable[T]): Iterable whose progress is reported.
        total (int | None): Expected item count, or ``None`` to infer it from a
            sized iterable when possible.
        desc (str | None): Optional progress label.
        initial (int): Completed-item count before iteration starts.
        unit (str): Item label used in human-readable output.
        unit_scale (bool | float): Whether or how much to scale item counts.
        unit_divisor (float): Divisor used when abbreviating item counts.
        disable (bool | None): Whether to suppress output. ``None`` follows
            tqdm's non-TTY disabling behavior.
        file (TextIO | None): Output stream, or ``None`` for ``sys.stderr``.
        seconds_step (float | None): Seconds between time-triggered log events.
        percent_step (float | None): Percentage interval for log milestones.
        count_step (int | None): Completed-item interval for log milestones.
        bar_width (int): Character width of the plain text bar.
        logger (logging.Logger | None): Optional logging destination.
        log_level (int): Level used for logger output.
        logger_stacklevel (int): Stack level passed to the logger.
        extra_fields (Mapping[str, Any] | None): User fields copied into logger
            records. Keys beginning with ``progress_`` are reserved.
        callback (Callable[[ProgressEvent], None] | None): Event destination.
            It cannot be combined with ``logger``.
        mode (ProgressMode): ``auto``, ``tty``, ``log``, or ``disabled``.
        emit_start (bool): Whether to emit an initial event in log mode.
        final_event (FinalEventPolicy): ``always`` emits final progress,
            ``after_milestone`` emits it only after another event or a milestone
            reached by the final update, and ``never`` suppresses it.
        max_milestones_per_update (int): Safety limit applied separately to raw
            percentage crossings, raw count crossings, and deduplicated events
            in one update.
        **tqdm_kwargs (Any): Additional arguments forwarded to tqdm in TTY mode.

    Returns:
        Iterator[T]: Iterator yielding the original items without modification.

    Raises:
        TypeError: If an option has an invalid type.
        ValueError: If an option is outside its valid range, conflicts with
            another option, or selects an unsupported output mode.
    """
    for removed_name, replacement in _REMOVED_OPTIONS.items():
        if removed_name in tqdm_kwargs:
            raise TypeError(f"{removed_name} is no longer supported; use {replacement} instead")

    _validate_progress_values(
        total=total,
        initial=initial,
        unit=unit,
        unit_scale=unit_scale,
        unit_divisor=unit_divisor,
    )
    resolved_total = total
    if resolved_total is None and isinstance(iterable, Sized):
        # len() is a non-negative integer, so adding it to the validated initial
        # value produces a valid total without repeating the full validation.
        resolved_total = initial + len(iterable)

    effective_file = sys.stderr if file is None else file
    resolved_extra_fields: Mapping[str, Any] = {} if extra_fields is None else extra_fields
    frozen_extra_fields = _snapshot_extra_fields(resolved_extra_fields)
    _validate_reporting_options(
        desc=desc,
        seconds_step=seconds_step,
        percent_step=percent_step,
        count_step=count_step,
        bar_width=bar_width,
        file=effective_file,
        logger=logger,
        log_level=log_level,
        logger_stacklevel=logger_stacklevel,
        callback=callback,
        emit_start=emit_start,
        final_event=final_event,
        max_milestones_per_update=max_milestones_per_update,
    )
    if disable is not None and not isinstance(disable, bool):
        raise TypeError("disable must be a boolean or None")
    resolved_mode = _resolve_mode(mode, effective_file)

    if resolved_mode == "tty":
        options = dict(tqdm_kwargs)
        options.update(
            total=resolved_total,
            initial=initial,
            unit=unit,
            unit_scale=unit_scale,
            unit_divisor=unit_divisor,
            disable=disable,
            file=effective_file,
        )
        if desc is not None:
            options["desc"] = desc
        return iter(tqdm(iterable, **options))

    if disable is True or disable is None:
        resolved_mode = "disabled"

    reporter = ProgressReporter(
        resolved_total,
        desc=desc,
        seconds_step=seconds_step,
        percent_step=percent_step,
        count_step=count_step,
        bar_width=bar_width,
        file=effective_file,
        logger=logger,
        log_level=log_level,
        logger_stacklevel=logger_stacklevel + 1,
        extra_fields=frozen_extra_fields,
        callback=callback,
        mode=resolved_mode,
        emit_start=emit_start,
        final_event=final_event,
        max_milestones_per_update=max_milestones_per_update,
        initial=initial,
        unit=unit,
        unit_scale=unit_scale,
        unit_divisor=unit_divisor,
    )
    return _iterate_with_reporter(iterable, reporter, initial)
