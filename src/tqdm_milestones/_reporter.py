"""Progress reporter implementation."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import TracebackType
from typing import Any, ClassVar, TextIO

from tqdm import tqdm

from ._events import FinalEventPolicy, ProgressEvent, ProgressMode
from ._validation import (
    _is_int,
    _resolve_mode,
    _snapshot_extra_fields,
    _validate_progress_values,
    _validate_reporting_options,
)


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


@dataclass(slots=True, eq=False, kw_only=True)
class ProgressReporter:
    """Report progress as a live tqdm bar or deterministic milestone events.

    Percentage, count, and elapsed-time triggers are combined with OR semantics.
    Large updates emit every distinct integer milestone produced by crossed
    percentage and count thresholds. Log mode uses ``callback``, ``logger``, or
    ``file`` as its event destination; ``callback`` and ``logger`` cannot be
    combined.
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
        file (TextIO | None): TTY bar or fallback plain text destination.
            ``None`` uses ``sys.stderr`` at initialization time.
        logger (logging.Logger | None): Optional logging destination.
        log_level (int): Level used for logger output.
        logger_stacklevel (int): Stack level passed to the logger.
        extra_fields (Mapping[str, Any]): Read-only top-level snapshot of user
            fields added to logger records.
        callback (Callable[[ProgressEvent], None] | None): Structured event destination.
        mode (ProgressMode): ``auto``, ``tty``, ``log``, or ``disabled``.
        emit_start (bool): Whether to emit an initial event in log mode.
        final_event (FinalEventPolicy): When final progress is emitted in log mode.
        max_milestones_per_update (int): Safety limit applied separately to raw
            percentage crossings, raw count crossings, and deduplicated events
            in one update.
        initial (int): Completed-item count at reporter initialization.
        unit (str): Item label used in human-readable output.
        unit_scale (bool | float): Whether or how much to scale item counts.
        unit_divisor (float): Divisor used when abbreviating item counts.
        current (int): Latest completed-item count, capped at a known ``total``.
        has_emitted (bool): Whether at least one log-mode milestone event has
            been emitted. TTY bar rendering does not set this property.

    Raises:
        TypeError: If a configuration option has an invalid type.
        ValueError: If a configuration option is outside its valid range,
            conflicts with another option, or selects an unsupported output
            mode.
    """

    total: int | None = field(kw_only=False)
    desc: str | None = None
    seconds_step: float | None = 60 * 60
    percent_step: float | None = 10.0
    count_step: int | None = None
    bar_width: int = 20
    file: TextIO | None = None
    logger: logging.Logger | None = None
    log_level: int = logging.INFO
    logger_stacklevel: int = 3
    extra_fields: Mapping[str, Any] = field(default_factory=dict)
    callback: Callable[[ProgressEvent], None] | None = None
    mode: ProgressMode = "auto"
    emit_start: bool = False
    final_event: FinalEventPolicy = "always"
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
            "file",
            "logger",
            "log_level",
            "logger_stacklevel",
            "extra_fields",
            "callback",
            "mode",
            "emit_start",
            "final_event",
            "initial",
            "unit",
            "unit_scale",
            "unit_divisor",
        }
    )

    _resolved_mode: ProgressMode = field(init=False, repr=False)
    _output_file: TextIO = field(init=False, repr=False)
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
            TypeError: If ``max_milestones_per_update`` has an invalid type.
            ValueError: If ``max_milestones_per_update`` is outside its valid
                range or is decreased after initialization.
        """
        if name in self._IMMUTABLE_CONFIG_FIELDS and hasattr(self, "_current"):
            raise AttributeError(f"{name} cannot be changed after initialization")
        if name == "max_milestones_per_update":
            if not _is_int(value):
                raise TypeError("max_milestones_per_update must be an integer")
            if value <= 0:
                raise ValueError("max_milestones_per_update must be > 0")
            if hasattr(self, "_current") and value < self.max_milestones_per_update:
                raise ValueError("max_milestones_per_update must not be decreased")
        object.__setattr__(self, name, value)

    def __post_init__(self) -> None:
        """Validate configuration and initialize progress state."""
        output_file = sys.stderr if self.file is None else self.file
        frozen_extra_fields = _snapshot_extra_fields(self.extra_fields)
        _validate_progress_values(
            total=self.total,
            initial=self.initial,
            unit=self.unit,
            unit_scale=self.unit_scale,
            unit_divisor=self.unit_divisor,
        )
        _validate_reporting_options(
            desc=self.desc,
            seconds_step=self.seconds_step,
            percent_step=self.percent_step,
            count_step=self.count_step,
            bar_width=self.bar_width,
            file=output_file,
            logger=self.logger,
            log_level=self.log_level,
            logger_stacklevel=self.logger_stacklevel,
            callback=self.callback,
            emit_start=self.emit_start,
            final_event=self.final_event,
            max_milestones_per_update=self.max_milestones_per_update,
        )
        self.extra_fields = frozen_extra_fields
        self._output_file = output_file

        self._resolved_mode = _resolve_mode(self.mode, self._output_file)
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
                file=self._output_file,
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
            and self.emit_start
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
        """Return whether at least one log-mode milestone event has been emitted.

        Rendering or updating a TTY progress bar does not set this property.

        Returns:
            bool: ``True`` after the first emitted log-mode event.
        """
        return self._last_emitted_milestone >= 0

    def advance_to(self, current: int) -> None:
        """Advance to an absolute completed-item count.

        Args:
            current (int): New completed-item count.

        Raises:
            TypeError: If ``current`` is not an integer.
            ValueError: If ``current`` moves backwards or the update exceeds
                ``max_milestones_per_update``.
            RuntimeError: If the reporter is already closed.
        """
        if self._closed:
            raise RuntimeError("reporter is closed")
        if not _is_int(current):
            raise TypeError("current must be an integer")
        if current < self._current:
            raise ValueError("current must not go backwards")

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

        time_is_due = not due_milestones and self._should_emit_seconds(now)
        completion_is_suppressed = self._completion_is_suppressed(has_due_milestone=time_is_due)
        emitted_by_time = False
        if time_is_due and not completion_is_suppressed:
            self._emit(self._current)
            emitted_by_time = True

        self._last_percent_bucket = percent_bucket
        self._last_count_bucket = count_bucket
        if due_milestones or emitted_by_time:
            self._last_emit_time = now

    def finalize(self) -> None:
        """Apply the final-event policy after successful completion, then close."""
        if self._closed:
            return
        should_emit = (
            self._resolved_mode == "log"
            and self._current != self._last_emitted_milestone
            and not self._completion_is_suppressed()
            and self._final_event_is_enabled()
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

    def _completion_is_suppressed(self, *, has_due_milestone: bool = False) -> bool:
        """Return whether the current value is a suppressed completion event.

        Args:
            has_due_milestone (bool): Whether the current update reaches a
                configured time, percentage, or count milestone.

        Returns:
            bool: ``True`` when completion output is disabled at ``total``.
        """
        return (
            self.total is not None
            and self._current == self.total
            and not self._final_event_is_enabled(has_due_milestone=has_due_milestone)
        )

    def _final_event_is_enabled(self, *, has_due_milestone: bool = False) -> bool:
        """Return whether the configured policy permits a final event.

        Args:
            has_due_milestone (bool): Whether the current update reaches a
                configured time, percentage, or count milestone.

        Returns:
            bool: ``True`` when final progress may be emitted.
        """
        if self.final_event == "always":
            return True
        if self.final_event == "never":
            return False
        return self.has_emitted or has_due_milestone

    def _should_emit_seconds(self, now: float) -> bool:
        """Check whether the elapsed-time trigger is due.

        Args:
            now (float): Current monotonic timestamp.

        Returns:
            bool: ``True`` when a time-triggered event should be emitted.
        """
        return self.seconds_step is not None and now - self._last_emit_time >= self.seconds_step

    def _collect_due_milestones(self) -> tuple[list[int], int, int]:
        """Collect distinct integer milestones produced by crossed thresholds.

        Returns:
            tuple[list[int], int, int]: Sorted, deduplicated milestones and the
            latest percentage and count buckets.

        Raises:
            ValueError: If a raw trigger range exceeds
                ``max_milestones_per_update``.
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
            if self._current >= self.total:
                if self._final_event_is_enabled(has_due_milestone=bool(due_milestones)):
                    due_milestones.add(self.total)
                else:
                    due_milestones.discard(self.total)

        milestones = sorted(
            value for value in due_milestones if value > self._last_emitted_milestone
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
                observed_text = f" observed={self._format_count(observed)}{unit_suffix}"
            message = (
                f"{prefix}{self._format_count(milestone)}{unit_suffix}{observed_text} "
                f"elapsed={self._format_hms(elapsed)} eta=??:??"
            )
            return ProgressEvent(
                current=observed,
                milestone=milestone,
                total=self.total,
                current_percent=None,
                milestone_percent=None,
                elapsed_seconds=elapsed,
                eta_seconds=None,
                description=self.desc,
                message=message,
            )

        if self.total == 0:
            bar = "#" * self.bar_width
            message = (
                f"{prefix}[{bar}] 0/0{unit_suffix} (100.0%) "
                f"elapsed={self._format_hms(elapsed)} eta=00:00"
            )
            return ProgressEvent(
                current=0,
                milestone=0,
                total=0,
                current_percent=100.0,
                milestone_percent=100.0,
                elapsed_seconds=elapsed,
                eta_seconds=0.0,
                description=self.desc,
                message=message,
            )

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
                f" observed={self._format_count(observed)}/{total_text} ({current_percent:.1f}%)"
            )
        message = (
            f"{prefix}[{bar}] {milestone_text}/{total_text}{unit_suffix} "
            f"({milestone_percent:.1f}%){observed_text} "
            f"elapsed={self._format_hms(elapsed)} eta={eta_text}"
        )
        return ProgressEvent(
            current=observed,
            milestone=milestone,
            total=self.total,
            current_percent=current_percent,
            milestone_percent=milestone_percent,
            elapsed_seconds=elapsed,
            eta_seconds=eta,
            description=self.desc,
            message=message,
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
            tqdm.write(event.message, file=self._output_file)
        self._last_emitted_milestone = milestone

    def __enter__(self) -> ProgressReporter:
        """Enter the reporter context.

        Returns:
            ProgressReporter: This reporter instance.

        Raises:
            RuntimeError: If the reporter is already closed.
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
