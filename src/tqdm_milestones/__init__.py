"""Deterministic progress milestones for terminals, logs, and monitoring systems."""

from __future__ import annotations

import logging
import math
import os
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Sized
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from numbers import Real
from types import TracebackType
from typing import Any, ClassVar, Literal, TextIO, TypeVar, cast

from tqdm import tqdm

__all__ = ["ProgressEvent", "ProgressMode", "ProgressReporter", "tqdm_iter"]

T = TypeVar("T")
ProgressMode = Literal["auto", "tty", "log", "disabled"]
_VALID_MODES = frozenset({"auto", "tty", "log", "disabled"})
_MODE_ENV_VAR = "TQDM_MILESTONES_MODE"
_LOG_RECORD_RESERVED_KEYS = frozenset(logging.makeLogRecord({}).__dict__) | {
    "asctime",
    "message",
}


def _is_int(value: object) -> bool:
    """Return whether a value is an integer but not a boolean.

    Args:
        value (object): Value to inspect.

    Returns:
        bool: ``True`` for a non-boolean integer.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite_real(value: object) -> bool:
    """Return whether a value is a finite real number but not a boolean.

    Args:
        value (object): Value to inspect.

    Returns:
        bool: ``True`` for a finite, non-boolean real number.
    """
    if not isinstance(value, Real) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, TypeError, ValueError):
        return False


def _percentage_bucket(current: int, total: int, step: float) -> int:
    """Return the percentage-step bucket reached by a count.

    Args:
        current (int): Completed-item count.
        total (int): Expected item count.
        step (float): Percentage interval.

    Returns:
        int: Number of percentage intervals reached.
    """
    numerator, denominator = float(step).as_integer_ratio()
    return current * 100 * denominator // (total * numerator)


def _percentage_target(total: int, bucket: int, step: float) -> int:
    """Return the first integer count that reaches a percentage bucket.

    The calculation uses the exact integer ratio of ``step`` so arbitrarily
    large Python integers and tiny percentage intervals are not converted to
    intermediate floating-point values.

    Args:
        total (int): Expected item count.
        bucket (int): One-based percentage-step bucket.
        step (float): Percentage interval.

    Returns:
        int: Smallest count whose percentage reaches the bucket.
    """
    numerator, denominator = float(step).as_integer_ratio()
    scaled_denominator = 100 * denominator
    scaled_numerator = total * bucket * numerator
    return (scaled_numerator + scaled_denominator - 1) // scaled_denominator


def _validate_progress_values(
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
        ValueError: If a value has an invalid type or range.
    """
    if total is not None and (not _is_int(total) or cast(int, total) < 0):
        raise ValueError("total must be >= 0")
    if not _is_int(initial) or cast(int, initial) < 0:
        raise ValueError("initial must be >= 0")
    if total is not None and cast(int, initial) > cast(int, total):
        raise ValueError("initial must not exceed total")
    if not isinstance(unit, str):
        raise ValueError("unit must be a string")
    if not isinstance(unit_scale, bool) and (
        not _is_finite_real(unit_scale) or float(cast(Real, unit_scale)) <= 0
    ):
        raise ValueError("numeric unit_scale must be > 0")
    if not _is_finite_real(unit_divisor) or float(cast(Real, unit_divisor)) <= 0:
        raise ValueError("unit_divisor must be > 0")


def _validate_reporting_options(
    desc: object,
    seconds_step: object,
    percent_step: object,
    count_step: object,
    bar_width: object,
    log_level: object,
    logger_stacklevel: object,
    extra_fields: object,
    callback: object,
    log_start: object,
    log_complete: object,
    max_milestones_per_update: object,
) -> None:
    """Validate reporting options shared across output modes.

    Args:
        desc (object): Optional progress label.
        seconds_step (object): Time-trigger interval.
        percent_step (object): Percentage-trigger interval.
        count_step (object): Count-trigger interval.
        bar_width (object): Plain progress bar width.
        log_level (object): Python logging level.
        logger_stacklevel (object): Python logger stack level.
        extra_fields (object): Structured logging fields.
        callback (object): Structured event callback.
        log_start (object): Start-event control.
        log_complete (object): Completion-event control.
        max_milestones_per_update (object): Per-update event limit.

    Raises:
        ValueError: If an option has an invalid type or range.
    """
    if desc is not None and not isinstance(desc, str):
        raise ValueError("desc must be a string or None")
    if seconds_step is not None and (
        not _is_finite_real(seconds_step) or cast(Real, seconds_step) < 0
    ):
        raise ValueError("seconds_step must be >= 0")
    if percent_step is not None and (
        not _is_finite_real(percent_step)
        or not (0.0 < float(cast(Real, percent_step)) <= 100.0)
    ):
        raise ValueError("percent_step must be in (0, 100]")
    if count_step is not None and (
        not _is_int(count_step) or cast(int, count_step) <= 0
    ):
        raise ValueError("count_step must be > 0")
    if not _is_int(bar_width) or cast(int, bar_width) <= 0:
        raise ValueError("bar_width must be > 0")
    if not _is_int(log_level):
        raise ValueError("log_level must be an integer")
    if not _is_int(logger_stacklevel) or cast(int, logger_stacklevel) <= 0:
        raise ValueError("logger_stacklevel must be > 0")
    if not isinstance(extra_fields, dict):
        raise ValueError("extra_fields must be a dictionary")
    reserved_extra_fields = _LOG_RECORD_RESERVED_KEYS.intersection(extra_fields)
    if reserved_extra_fields:
        names = ", ".join(sorted(reserved_extra_fields))
        raise ValueError(f"extra_fields contains reserved logging fields: {names}")
    if callback is not None and not callable(callback):
        raise ValueError("callback must be callable")
    if not isinstance(log_start, bool):
        raise ValueError("log_start must be a boolean")
    if not isinstance(log_complete, bool):
        raise ValueError("log_complete must be a boolean")
    if (
        not _is_int(max_milestones_per_update)
        or cast(int, max_milestones_per_update) <= 0
    ):
        raise ValueError("max_milestones_per_update must be > 0")


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """Structured data produced for one progress milestone.

    Attributes:
        current (int): Actual completed-item count observed when the event was emitted.
        milestone (int): Threshold represented by the event.
        total (int | None): Expected item count. ``None`` means unknown; zero means empty.
        current_percent (float | None): Actual observed percentage, or ``None`` when unknown.
        milestone_percent (float | None): Threshold percentage, or ``None`` when unknown.
        elapsed_seconds (float): Seconds elapsed since reporter initialization.
        eta_seconds (float | None): Estimated seconds remaining, or ``None``.
        description (str | None): Optional progress label.
        message (str): Human-readable progress line.
    """

    current: int
    milestone: int
    total: int | None
    current_percent: float | None
    milestone_percent: float | None
    elapsed_seconds: float
    eta_seconds: float | None
    description: str | None
    message: str

    def as_log_extra(self) -> dict[str, Any]:
        """Return fields suitable for ``logging.Logger.log(extra=...)``.

        Returns:
            dict[str, Any]: Event fields with names prefixed by ``progress_``.
        """
        return {f"progress_{key}": value for key, value in asdict(self).items()}


def _resolve_mode(mode: ProgressMode, stream: TextIO) -> ProgressMode:
    """Resolve explicit and environment-driven output modes.

    Args:
        mode (ProgressMode): Requested output mode.
        stream (TextIO): Stream whose TTY status is inspected in automatic mode.

    Returns:
        ProgressMode: A concrete ``tty``, ``log``, or ``disabled`` mode.

    Raises:
        ValueError: If ``mode`` or ``TQDM_MILESTONES_MODE`` is invalid.
    """
    if mode not in _VALID_MODES:
        raise ValueError(f"mode must be one of {sorted(_VALID_MODES)}")

    selected_mode = os.getenv(_MODE_ENV_VAR, "auto") if mode == "auto" else mode
    if selected_mode not in _VALID_MODES:
        raise ValueError(f"{_MODE_ENV_VAR} must be one of {sorted(_VALID_MODES)}")
    if selected_mode != "auto":
        return selected_mode  # type: ignore[return-value]
    return "tty" if bool(getattr(stream, "isatty", lambda: False)()) else "log"


@dataclass(slots=True)
class ProgressReporter:
    """Report progress as a live tqdm bar or deterministic milestone events.

    Percentage, count, and elapsed-time triggers are combined with OR semantics.
    Large updates emit every crossed percentage and count milestone. In log mode,
    output uses ``callback`` when supplied, then ``logger``, then ``stream``.
    Instances are not thread-safe; call ``advance_to()`` from one thread only.
    Configuration attributes cannot be reassigned after initialization, except
    for ``max_milestones_per_update``, which may be raised before retrying a
    rejected update.

    Attributes:
        total (int | None): Expected item count. ``None`` means unknown; zero means empty.
        desc (str | None): Optional progress label.
        seconds_step (float | None): Seconds between time-triggered events, or ``None``.
        percent_step (float | None): Percentage interval, or ``None``.
        count_step (int | None): Completed-item interval, or ``None``.
        bar_width (int): Character width of the plain text bar.
        stream (TextIO): TTY bar or fallback plain text destination.
        logger (logging.Logger | None): Optional logging destination.
        log_level (int): Level used for logger output.
        logger_stacklevel (int): Stack level passed to the logger.
        extra_fields (dict[str, Any]): User fields added to logger records.
        callback (Callable[[ProgressEvent], None] | None): Structured event destination.
        mode (ProgressMode): ``auto``, ``tty``, ``log``, or ``disabled``.
        log_start (bool): Whether to emit an initial event in log mode.
        log_complete (bool): Whether to emit an event at exactly ``total``.
        max_milestones_per_update (int): Maximum events emitted by one update.
        initial (int): Completed-item count at reporter initialization.
        unit (str): Item label used in human-readable output.
        unit_scale (bool | float): Whether or how much to scale item counts.
        unit_divisor (float): Divisor used when abbreviating item counts.
    """

    total: int | None
    desc: str | None = None
    seconds_step: float | None = 60 * 60
    percent_step: float | None = 10.0
    count_step: int | None = None
    bar_width: int = 20
    stream: TextIO = sys.stderr
    logger: logging.Logger | None = None
    log_level: int = logging.INFO
    logger_stacklevel: int = 3
    extra_fields: dict[str, Any] = field(default_factory=dict)
    callback: Callable[[ProgressEvent], None] | None = None
    mode: ProgressMode = "auto"
    log_start: bool = False
    log_complete: bool = True
    max_milestones_per_update: int = 10_000
    initial: int = 0
    unit: str = "it"
    unit_scale: bool | float = False
    unit_divisor: float = 1000

    _IMMUTABLE_CONFIG_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "total",
            "desc",
            "seconds_step",
            "percent_step",
            "count_step",
            "bar_width",
            "stream",
            "logger",
            "log_level",
            "logger_stacklevel",
            "extra_fields",
            "callback",
            "mode",
            "log_start",
            "log_complete",
            "initial",
            "unit",
            "unit_scale",
            "unit_divisor",
        }
    )

    _resolved_mode: ProgressMode = field(init=False, repr=False)
    _current: int = field(init=False, repr=False)
    _start_time: float = field(init=False, repr=False)
    _last_emit_time: float = field(init=False, repr=False)
    _last_emitted_milestone: int = field(init=False, repr=False, default=-1)
    _last_percent_bucket: int = field(init=False, repr=False, default=0)
    _last_count_bucket: int = field(init=False, repr=False, default=0)
    _bar: tqdm | None = field(init=False, repr=False, default=None)
    _closed: bool = field(init=False, repr=False, default=False)

    def __setattr__(self, name: str, value: Any) -> None:
        """Set state while preventing configuration changes after initialization.

        Args:
            name (str): Attribute name.
            value (Any): New attribute value.

        Raises:
            AttributeError: If an initialized configuration field is reassigned.
            ValueError: If ``max_milestones_per_update`` is invalid.
        """
        if name in self._IMMUTABLE_CONFIG_FIELDS and hasattr(self, "_current"):
            raise AttributeError(f"{name} cannot be changed after initialization")
        if name == "max_milestones_per_update" and (
            not _is_int(value) or value <= 0
        ):
            raise ValueError("max_milestones_per_update must be > 0")
        object.__setattr__(self, name, value)

    def __post_init__(self) -> None:
        """Validate configuration and initialize progress state."""
        _validate_progress_values(
            self.total,
            self.initial,
            self.unit,
            self.unit_scale,
            self.unit_divisor,
        )
        _validate_reporting_options(
            self.desc,
            self.seconds_step,
            self.percent_step,
            self.count_step,
            self.bar_width,
            self.log_level,
            self.logger_stacklevel,
            self.extra_fields,
            self.callback,
            self.log_start,
            self.log_complete,
            self.max_milestones_per_update,
        )

        self._resolved_mode = _resolve_mode(self.mode, self.stream)
        self._current = self.initial
        if self.total is not None and self.total > 0 and self.percent_step is not None:
            self._last_percent_bucket = _percentage_bucket(
                self.initial,
                self.total,
                self.percent_step,
            )
        if self.count_step is not None:
            self._last_count_bucket = self.initial // self.count_step
        now = time.monotonic()
        self._start_time = now
        self._last_emit_time = now

        if self._resolved_mode == "tty":
            self._bar = tqdm(
                total=self.total,
                desc=self.desc or "",
                file=self.stream,
                dynamic_ncols=True,
                leave=True,
                position=0,
                initial=self.initial,
                unit=self.unit,
                unit_scale=self.unit_scale,
                unit_divisor=self.unit_divisor,
            )
        elif (
            self._resolved_mode == "log"
            and self.log_start
            and not self._completion_is_suppressed()
        ):
            self._emit(self.initial)

    @property
    def current(self) -> int:
        """Return the latest absolute progress value.

        Returns:
            int: Completed-item count, capped at a known ``total``.
        """
        return self._current

    @property
    def has_emitted(self) -> bool:
        """Return whether at least one milestone event has been emitted.

        Returns:
            bool: ``True`` after the first emitted event.
        """
        return self._last_emitted_milestone >= 0

    def advance_to(self, current: int) -> None:
        """Advance to an absolute completed-item count.

        Args:
            current (int): New completed-item count.

        Raises:
            ValueError: If ``current`` is not an integer or moves backwards.
            RuntimeError: If the reporter is already closed.
        """
        if self._closed:
            raise RuntimeError("reporter is closed")
        if not _is_int(current):
            raise ValueError("current must be an integer")
        if current < self._current:
            raise ValueError("current must not go backwards")
        reserved_extra_fields = _LOG_RECORD_RESERVED_KEYS.intersection(self.extra_fields)
        if reserved_extra_fields:
            names = ", ".join(sorted(reserved_extra_fields))
            raise ValueError(f"extra_fields contains reserved logging fields: {names}")

        previous = self._current
        self._current = min(current, self.total) if self.total is not None else current
        increment = self._current - previous

        if self._resolved_mode == "disabled":
            return
        if self._resolved_mode == "tty":
            assert self._bar is not None
            self._bar.update(increment)
            return

        now = time.monotonic()
        try:
            due_milestones, percent_bucket, count_bucket = self._collect_due_milestones()
            if len(due_milestones) > self.max_milestones_per_update:
                raise ValueError(
                    f"update would emit {len(due_milestones)} milestones; "
                    "increase max_milestones_per_update to allow it"
                )
        except ValueError:
            self._current = previous
            raise
        for due_milestone in due_milestones:
            self._emit(due_milestone)

        completion_is_suppressed = self._completion_is_suppressed()
        emitted_by_time = False
        if (
            not due_milestones
            and self._should_emit_seconds(now)
            and not completion_is_suppressed
        ):
            self._emit(self._current)
            emitted_by_time = True

        self._last_percent_bucket = percent_bucket
        self._last_count_bucket = count_bucket
        if due_milestones or emitted_by_time:
            self._last_emit_time = now

    def finalize(self) -> None:
        """Emit pending progress after successful completion, then close."""
        if self._closed:
            return
        reserved_extra_fields = _LOG_RECORD_RESERVED_KEYS.intersection(self.extra_fields)
        if reserved_extra_fields:
            names = ", ".join(sorted(reserved_extra_fields))
            raise ValueError(f"extra_fields contains reserved logging fields: {names}")
        should_emit = (
            self._resolved_mode == "log"
            and self._current != self._last_emitted_milestone
            and not self._completion_is_suppressed()
        )
        if should_emit:
            self._emit(self._current)
        self.close()

    def close(self) -> None:
        """Release resources without emitting a final event."""
        if self._closed:
            return
        if self._bar is not None:
            self._bar.close()
        self._closed = True

    def _completion_is_suppressed(self) -> bool:
        """Return whether the current value is a suppressed completion event.

        Returns:
            bool: ``True`` when completion output is disabled at ``total``.
        """
        return (
            self.total is not None
            and self._current == self.total
            and not self.log_complete
        )

    def _should_emit_seconds(self, now: float) -> bool:
        """Check whether the elapsed-time trigger is due.

        Args:
            now (float): Current monotonic timestamp.

        Returns:
            bool: ``True`` when a time-triggered event should be emitted.
        """
        return self.seconds_step is not None and now - self._last_emit_time >= self.seconds_step

    def _collect_due_milestones(self) -> tuple[list[int], int, int]:
        """Collect every crossed percentage and count milestone.

        Returns:
            tuple[list[int], int, int]: Sorted, deduplicated milestones and the
            latest percentage and count buckets.
        """
        due_milestones: set[int] = set()

        percent_bucket = self._last_percent_bucket
        count_bucket = self._last_count_bucket

        if self.total is not None and self.total > 0 and self.percent_step is not None:
            current_bucket = _percentage_bucket(
                self._current,
                self.total,
                self.percent_step,
            )
            bucket_count = current_bucket - self._last_percent_bucket
            if bucket_count > self.max_milestones_per_update:
                raise ValueError(
                    "update crosses too many percentage milestones; "
                    "increase max_milestones_per_update to allow it"
                )
            for bucket in range(self._last_percent_bucket + 1, current_bucket + 1):
                due_milestones.add(
                    min(_percentage_target(self.total, bucket, self.percent_step), self.total)
                )
            percent_bucket = max(self._last_percent_bucket, current_bucket)

        if self.count_step is not None:
            current_bucket = self._current // self.count_step
            bucket_count = current_bucket - self._last_count_bucket
            if bucket_count > self.max_milestones_per_update:
                raise ValueError(
                    "update crosses too many count milestones; "
                    "increase max_milestones_per_update to allow it"
                )
            for bucket in range(self._last_count_bucket + 1, current_bucket + 1):
                due_milestones.add(bucket * self.count_step)
            count_bucket = max(self._last_count_bucket, current_bucket)

        if self.total is not None:
            due_milestones = {min(value, self.total) for value in due_milestones}
            if self._current >= self.total and self.log_complete:
                due_milestones.add(self.total)
            if not self.log_complete:
                due_milestones.discard(self.total)

        milestones = sorted(
            value
            for value in due_milestones
            if value > self._last_emitted_milestone
        )
        return milestones, percent_bucket, count_bucket

    @staticmethod
    def _format_hms(seconds: float) -> str:
        """Format a duration for human-readable output.

        Args:
            seconds (float): Duration in seconds.

        Returns:
            str: ``MM:SS`` below one hour, otherwise ``HH:MM:SS``.
        """
        total_seconds = max(0, int(seconds + 0.5))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"

    def _format_count(self, value: int) -> str:
        """Format an item count according to unit scaling settings.

        Args:
            value (int): Item count to format.

        Returns:
            str: Raw or abbreviated item count.
        """
        if not self.unit_scale:
            try:
                return str(value)
            except ValueError:
                return format(Decimal(value), "f")
        scale = 1 if isinstance(self.unit_scale, bool) else float(self.unit_scale)
        try:
            return tqdm.format_sizeof(value * scale, "", self.unit_divisor)
        except OverflowError:
            return f"{Decimal(value) * Decimal(str(scale)):.3E}"

    def _make_event(self, milestone: int) -> ProgressEvent:
        """Build a structured event and its human-readable message.

        Args:
            milestone (int): Milestone represented by the event.

        Returns:
            ProgressEvent: A structured progress event.
        """
        elapsed = max(0.0, time.monotonic() - self._start_time)
        prefix = f"{self.desc}: " if self.desc else ""

        observed = self._current
        unit_suffix = f" {self.unit}" if self.unit else ""

        if self.total is None:
            observed_text = ""
            if observed != milestone:
                observed_text = (
                    f" observed={self._format_count(observed)}{unit_suffix}"
                )
            message = (
                f"{prefix}{self._format_count(milestone)}{unit_suffix}{observed_text} "
                f"elapsed={self._format_hms(elapsed)} eta=??:??"
            )
            return ProgressEvent(
                observed,
                milestone,
                self.total,
                None,
                None,
                elapsed,
                None,
                self.desc,
                message,
            )

        if self.total == 0:
            bar = "#" * self.bar_width
            message = (
                f"{prefix}[{bar}] 0/0{unit_suffix} (100.0%) "
                f"elapsed={self._format_hms(elapsed)} eta=00:00"
            )
            return ProgressEvent(0, 0, 0, 100.0, 100.0, elapsed, 0.0, self.desc, message)

        milestone_percent = milestone / self.total * 100.0
        current_percent = observed / self.total * 100.0
        filled = min(max(int(self.bar_width * milestone / self.total), 0), self.bar_width)
        bar = "#" * filled + "-" * (self.bar_width - filled)
        observed_since_start = observed - self.initial
        if observed == self.total:
            eta = 0.0
        else:
            try:
                rate = observed_since_start / elapsed if elapsed > 0 else 0.0
                eta = (self.total - observed) / rate if rate > 0 else None
            except OverflowError:
                eta = None
        eta_text = self._format_hms(eta) if eta is not None else "??:??"
        milestone_text = self._format_count(milestone)
        total_text = self._format_count(self.total)
        observed_text = ""
        if observed != milestone:
            observed_text = (
                f" observed={self._format_count(observed)}/{total_text} "
                f"({current_percent:.1f}%)"
            )
        message = (
            f"{prefix}[{bar}] {milestone_text}/{total_text}{unit_suffix} "
            f"({milestone_percent:.1f}%){observed_text} "
            f"elapsed={self._format_hms(elapsed)} eta={eta_text}"
        )
        return ProgressEvent(
            observed,
            milestone,
            self.total,
            current_percent,
            milestone_percent,
            elapsed,
            eta,
            self.desc,
            message,
        )

    def _emit(self, milestone: int) -> None:
        """Send one event to the configured destination.

        Args:
            milestone (int): Milestone represented by the event.
        """
        event = self._make_event(milestone)
        if self.callback is not None:
            self.callback(event)
        elif self.logger is not None:
            extra = {**self.extra_fields, **event.as_log_extra()}
            self.logger.log(
                self.log_level,
                event.message,
                stacklevel=self.logger_stacklevel,
                extra=extra,
            )
        else:
            tqdm.write(event.message, file=self.stream)
        self._last_emitted_milestone = milestone

    def __enter__(self) -> ProgressReporter:
        """Enter the reporter context.

        Returns:
            ProgressReporter: This reporter instance.
        """
        if self._closed:
            raise RuntimeError("reporter is closed")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Finalize normal exits and silently close exceptional exits.

        Args:
            exc_type (type[BaseException] | None): Raised exception type, if any.
            exc (BaseException | None): Raised exception instance, if any.
            tb (TracebackType | None): Raised exception traceback, if any.
        """
        if exc_type is None:
            self.finalize()
        else:
            self.close()


def tqdm_iter(
    iterable: Iterable[T],
    *,
    seconds_step: float | None = 60 * 60,
    percent_step: float | None = 10.0,
    count_step: int | None = None,
    desc: str | None = None,
    bar_width: int = 20,
    stream: TextIO = sys.stderr,
    logger: logging.Logger | None = None,
    log_level: int = logging.INFO,
    logger_stacklevel: int = 3,
    extra_fields: dict[str, Any] | None = None,
    callback: Callable[[ProgressEvent], None] | None = None,
    mode: ProgressMode = "auto",
    log_start: bool = False,
    log_complete: bool = True,
    max_milestones_per_update: int = 10_000,
    **tqdm_kwargs: Any,
) -> Iterator[T]:
    """Wrap an iterable with TTY-aware deterministic progress reporting.

    Args:
        iterable (Iterable[T]): Iterable whose progress is reported.
        seconds_step (float | None): Seconds between time-triggered log events.
        percent_step (float | None): Percentage interval for log milestones.
        count_step (int | None): Completed-item interval for log milestones.
        desc (str | None): Optional progress label.
        bar_width (int): Character width of the plain text bar.
        stream (TextIO): TTY bar or fallback plain text destination.
        logger (logging.Logger | None): Optional logging destination.
        log_level (int): Level used for logger output.
        logger_stacklevel (int): Stack level passed to the logger.
        extra_fields (dict[str, Any] | None): User fields added to logger records.
        callback (Callable[[ProgressEvent], None] | None): Event destination.
        mode (ProgressMode): ``auto``, ``tty``, ``log``, or ``disabled``.
        log_start (bool): Whether to emit an initial event in log mode.
        log_complete (bool): Whether to emit an event at exactly ``total``.
        max_milestones_per_update (int): Maximum events emitted by one update.
        **tqdm_kwargs (Any): Additional arguments forwarded to tqdm in TTY mode.
            ``total``, ``desc``, ``file``, ``disable``, ``initial``, ``unit``,
            ``unit_scale``, and ``unit_divisor`` are also used in log mode.

    Yields:
        T: Items from ``iterable`` without modification.

    Raises:
        ValueError: If the output mode or reporter configuration is invalid.
    """
    options = dict(tqdm_kwargs)
    configured_file = options.get("file", stream)
    effective_stream = stream if configured_file is None else configured_file
    if configured_file is None:
        options["file"] = effective_stream
    initial = options.get("initial", 0)
    if not _is_int(initial) or initial < 0:
        raise ValueError("initial must be >= 0")
    if initial > 0 and options.get("total") is None and isinstance(iterable, Sized):
        options["total"] = initial + len(iterable)
    resolved_total = options.get("total")
    if resolved_total is None and isinstance(iterable, Sized):
        resolved_total = len(iterable)
    unit = options.get("unit", "it")
    unit_scale = options.get("unit_scale", False)
    unit_divisor = options.get("unit_divisor", 1000)
    _validate_progress_values(resolved_total, initial, unit, unit_scale, unit_divisor)
    resolved_desc = desc if desc is not None else options.get("desc")
    resolved_extra_fields = {} if extra_fields is None else extra_fields
    _validate_reporting_options(
        resolved_desc,
        seconds_step,
        percent_step,
        count_step,
        bar_width,
        log_level,
        logger_stacklevel,
        resolved_extra_fields,
        callback,
        log_start,
        log_complete,
        max_milestones_per_update,
    )
    disable = options.get("disable", False)
    if disable is not None and not isinstance(disable, bool):
        raise ValueError("disable must be a boolean or None")
    resolved_mode = _resolve_mode(mode, effective_stream)

    if resolved_mode == "tty":
        options.setdefault("file", stream)
        if desc is not None:
            options["desc"] = desc
        yield from tqdm(iterable, **options)
        return

    if disable is True or disable is None:
        resolved_mode = "disabled"

    with ProgressReporter(
        total=resolved_total,
        desc=resolved_desc,
        seconds_step=seconds_step,
        percent_step=percent_step,
        count_step=count_step,
        bar_width=bar_width,
        stream=effective_stream,
        logger=logger,
        log_level=log_level,
        logger_stacklevel=logger_stacklevel + 1,
        extra_fields=resolved_extra_fields,
        callback=callback,
        mode=resolved_mode,
        log_start=log_start,
        log_complete=log_complete,
        max_milestones_per_update=max_milestones_per_update,
        initial=initial,
        unit=unit,
        unit_scale=unit_scale,
        unit_divisor=unit_divisor,
    ) as reporter:
        for index, item in enumerate(iterable, start=initial + 1):
            yield item
            reporter.advance_to(index)
