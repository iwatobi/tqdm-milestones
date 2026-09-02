"""Tests for progress reporting behavior."""

from __future__ import annotations

import logging
from itertools import count
from unittest.mock import Mock

import pytest

from tqdm_milestones import ProgressEvent, ProgressReporter, _reporter as reporter_module

from ._support import Stream


def test_reporters_use_identity_equality() -> None:
    """Verify reporter instances compare by identity rather than configuration."""
    first = ProgressReporter(1, mode="disabled")
    second = ProgressReporter(1, mode="disabled")
    assert first == first
    assert first != second


def test_callback_gets_start_all_crossed_milestones_and_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify callbacks receive start, crossed-milestone, and completion events.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest fixture used to replace process state or
            dependencies.
    """
    clock = count(0.0, 1.0)
    monkeypatch.setattr(reporter_module.time, "monotonic", lambda: next(clock))
    events: list[ProgressEvent] = []
    reporter = ProgressReporter(
        total=10,
        desc="work",
        percent_step=25,
        count_step=2,
        seconds_step=None,
        callback=events.append,
        mode="log",
        emit_start=True,
        bar_width=10,
    )

    assert reporter.current == 0
    assert reporter.has_emitted
    reporter.advance_to(7)
    reporter.advance_to(99)
    reporter.finalize()

    assert [event.milestone for event in events] == [0, 2, 3, 4, 5, 6, 8, 10]
    assert [event.current for event in events[1:6]] == [7, 7, 7, 7, 7]
    assert events[0].eta_seconds is None
    assert events[-1].current_percent == 100.0
    assert events[-1].eta_seconds == 0.0
    assert "work: [##########] 10/10 it (100.0%)" in events[-1].message


def test_time_trigger_unknown_total_and_finalization(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify time-triggered unknown progress is not duplicated at finalization.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest fixture used to replace process state or
            dependencies.
    """
    clock = iter([0.0, 2.0, 2.0, 2.0, 2.0])
    monkeypatch.setattr(reporter_module.time, "monotonic", lambda: next(clock))
    stream = Stream()
    reporter = ProgressReporter(
        total=None,
        desc="",
        percent_step=None,
        count_step=None,
        seconds_step=1,
        file=stream,
        mode="log",
    )
    assert not reporter.has_emitted
    reporter.advance_to(3)
    reporter.advance_to(3)
    reporter.finalize()
    assert stream.getvalue().count("3 it elapsed=00:02 eta=??:??") == 1


def test_default_final_event_reports_zero_progress() -> None:
    """Verify normal finalization reports an unchanged initial value by default."""
    events: list[ProgressEvent] = []

    with ProgressReporter(100, callback=events.append, mode="log"):
        pass

    assert [(event.current, event.milestone, event.total) for event in events] == [(0, 0, 100)]
    assert "0/100 it (0.0%)" in events[0].message


def test_after_milestone_suppresses_small_completion_without_a_milestone() -> None:
    """Verify after-milestone policy keeps a milestone-free short job silent."""
    events: list[ProgressEvent] = []
    reporter = ProgressReporter(
        total=4,
        percent_step=None,
        count_step=10,
        seconds_step=None,
        callback=events.append,
        mode="log",
        final_event="after_milestone",
    )

    reporter.advance_to(4)
    reporter.finalize()

    assert events == []
    with pytest.raises(RuntimeError, match="reporter is closed"):
        reporter.advance_to(4)


def test_after_milestone_emits_pending_progress_after_a_prior_milestone() -> None:
    """Verify after-milestone policy emits pending progress after an earlier event."""
    events: list[ProgressEvent] = []
    reporter = ProgressReporter(
        total=None,
        percent_step=None,
        count_step=5,
        seconds_step=None,
        callback=events.append,
        mode="log",
        final_event="after_milestone",
    )

    reporter.advance_to(7)
    reporter.finalize()

    assert [event.milestone for event in events] == [5, 7]


def test_after_milestone_keeps_a_configured_milestone_at_completion() -> None:
    """Verify after-milestone policy preserves a completion milestone."""
    events: list[ProgressEvent] = []
    reporter = ProgressReporter(
        total=5,
        percent_step=None,
        count_step=5,
        seconds_step=None,
        callback=events.append,
        mode="log",
        final_event="after_milestone",
    )

    reporter.advance_to(5)
    reporter.finalize()

    assert [event.milestone for event in events] == [5]


def test_after_milestone_keeps_a_due_time_event_at_completion() -> None:
    """Verify after-milestone policy preserves a due completion-time event."""
    events: list[ProgressEvent] = []
    reporter = ProgressReporter(
        total=1,
        percent_step=None,
        count_step=None,
        seconds_step=0,
        callback=events.append,
        mode="log",
        final_event="after_milestone",
    )

    reporter.advance_to(1)
    reporter.finalize()

    assert [event.milestone for event in events] == [1]


def test_never_suppresses_final_progress_but_keeps_earlier_milestones() -> None:
    """Verify never policy suppresses completion without removing earlier milestones."""
    events: list[ProgressEvent] = []
    reporter = ProgressReporter(
        total=10,
        percent_step=None,
        count_step=5,
        seconds_step=None,
        callback=events.append,
        mode="log",
        final_event="never",
    )

    reporter.advance_to(10)
    reporter.finalize()

    assert [event.milestone for event in events] == [5]


def test_unknown_total_milestone_message_shows_observed_progress() -> None:
    """Verify unknown-total messages distinguish milestones from observed progress."""
    events: list[ProgressEvent] = []
    reporter = ProgressReporter(
        total=None,
        count_step=10,
        percent_step=None,
        seconds_step=None,
        callback=events.append,
        mode="log",
    )
    reporter.advance_to(25)
    assert [event.milestone for event in events] == [10, 20]
    assert "10 it observed=25 it" in events[0].message


def test_empty_total_is_distinct_from_unknown_total() -> None:
    """Verify a known empty job reports completion rather than unknown progress."""
    events: list[ProgressEvent] = []
    with ProgressReporter(
        total=0,
        callback=events.append,
        mode="log",
        percent_step=None,
        seconds_step=None,
    ):
        pass

    assert len(events) == 1
    assert events[0].total == 0
    assert events[0].current_percent == 100.0
    assert events[0].eta_seconds == 0.0
    assert "0/0 it (100.0%)" in events[0].message


def test_final_event_never_overrides_emit_start_for_an_empty_job() -> None:
    """Verify never policy suppresses an empty job even when start emission is enabled."""
    events: list[ProgressEvent] = []
    with ProgressReporter(
        total=0,
        callback=events.append,
        mode="log",
        emit_start=True,
        final_event="never",
    ):
        pass
    assert events == []


def test_crossed_milestones_distinguish_threshold_from_observed_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify events separate crossed thresholds from the observed current value.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest fixture used to replace process state or
            dependencies.
    """
    clock = count(0.0, 10.0)
    monkeypatch.setattr(reporter_module.time, "monotonic", lambda: next(clock))
    events: list[ProgressEvent] = []
    reporter = ProgressReporter(
        total=100,
        percent_step=10,
        seconds_step=None,
        callback=events.append,
        mode="log",
    )
    reporter.advance_to(100)

    first = events[0]
    assert first.milestone == 10
    assert first.milestone_percent == 10.0
    assert first.current == 100
    assert first.current_percent == 100.0
    assert first.eta_seconds == 0.0
    assert "observed=100/100 (100.0%)" in first.message


def test_normal_exit_emits_progress_when_no_milestone_was_reached() -> None:
    """Verify successful short jobs emit one useful final progress event."""
    events: list[ProgressEvent] = []
    with ProgressReporter(
        total=100,
        percent_step=50,
        seconds_step=None,
        callback=events.append,
        mode="log",
    ) as reporter:
        reporter.advance_to(3)

    assert [event.milestone for event in events] == [3]
    assert events[0].current_percent == 3.0


def test_logger_receives_automatic_and_custom_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify logger records contain generated progress fields and custom fields.

    Args:
        caplog (pytest.LogCaptureFixture): Pytest fixture used to capture emitted logging records.
    """
    logger = logging.getLogger("tqdm_milestones.test")
    reporter = ProgressReporter(
        total=4,
        percent_step=50,
        seconds_step=None,
        logger=logger,
        extra_fields={"job_id": "abc"},
        mode="log",
    )
    with caplog.at_level(logging.INFO, logger=logger.name):
        reporter.advance_to(2)

    record = caplog.records[0]
    assert record.progress_current == 2  # ty: ignore[unresolved-attribute]
    assert record.progress_total == 4  # ty: ignore[unresolved-attribute]
    assert record.job_id == "abc"  # ty: ignore[unresolved-attribute]


def test_callback_failure_can_resume_without_losing_or_repeating_milestones() -> None:
    """Verify a failed callback can resume without lost or duplicate milestones."""
    delivered: list[int] = []
    failed_once = False

    def callback(event: ProgressEvent) -> None:
        """Fail once at a selected milestone and record successful deliveries.

        Args:
            event (ProgressEvent): Progress event delivered to the callback.
        """
        nonlocal failed_once
        if event.milestone == 4 and not failed_once:
            failed_once = True
            raise RuntimeError("temporary backend failure")
        delivered.append(event.milestone)

    reporter = ProgressReporter(
        total=10,
        percent_step=25,
        count_step=2,
        seconds_step=None,
        callback=callback,
        mode="log",
    )
    with pytest.raises(RuntimeError, match="temporary backend failure"):
        reporter.advance_to(7)

    reporter.advance_to(7)
    assert delivered == [2, 3, 4, 5, 6]


@pytest.mark.parametrize(
    ("total", "percent_step", "count_step"),
    [
        (100, 0.000001, None),
        (None, None, 1),
    ],
)
def test_milestone_limit_rejects_huge_ranges_before_materializing_them(
    total: int | None,
    percent_step: float | None,
    count_step: int | None,
) -> None:
    """Verify oversized milestone ranges fail before event materialization.

    Args:
        total (int | None): Expected item count under test.
        percent_step (float | None): Percentage interval under test.
        count_step (int | None): Completed-item interval under test.
    """
    reporter = ProgressReporter(
        total=total,
        percent_step=percent_step,
        count_step=count_step,
        seconds_step=None,
        mode="log",
        max_milestones_per_update=5,
    )
    with pytest.raises(ValueError, match="crosses .* milestones"):
        reporter.advance_to(10)
    assert reporter.current == 0


def test_milestone_limit_applies_to_combined_deduplicated_events() -> None:
    """Verify the event limit counts the deduplicated union of milestone types."""
    reporter = ProgressReporter(
        total=100,
        percent_step=20,
        count_step=15,
        seconds_step=None,
        callback=lambda event: None,
        mode="log",
        max_milestones_per_update=5,
    )
    with pytest.raises(ValueError, match="would emit 6 milestones"):
        reporter.advance_to(60)
    assert reporter.current == 0

    reporter.max_milestones_per_update = 6
    reporter.advance_to(60)
    assert reporter.current == 60


def test_milestone_limit_applies_before_percentage_targets_are_deduplicated() -> None:
    """Verify raw percentage crossings are limited before target deduplication."""
    reporter = ProgressReporter(
        total=1,
        percent_step=10,
        count_step=None,
        seconds_step=None,
        mode="log",
        max_milestones_per_update=5,
    )

    with pytest.raises(ValueError, match="percentage milestones"):
        reporter.advance_to(1)
    assert reporter.current == 0

    reporter.max_milestones_per_update = 10
    reporter.advance_to(1)
    assert reporter.current == 1


def test_subnormal_percentage_step_hits_the_guard_without_corrupting_state() -> None:
    """Verify subnormal percentage steps trigger the limit without changing state."""
    reporter = ProgressReporter(
        total=2,
        initial=1,
        percent_step=5e-324,
        count_step=None,
        seconds_step=None,
        mode="log",
        max_milestones_per_update=5,
    )
    with pytest.raises(ValueError, match="percentage milestones"):
        reporter.advance_to(2)
    assert reporter.current == 1


def test_disabled_mode_tracks_and_caps_without_output() -> None:
    """Verify disabled mode tracks capped progress without invoking output callbacks."""
    callback = Mock()
    reporter = ProgressReporter(total=2, callback=callback, mode="disabled", emit_start=True)
    reporter.advance_to(3)
    reporter.finalize()
    assert reporter.current == 2
    callback.assert_not_called()


def test_progress_reporter_resolves_file_none_at_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify reporters resolve a missing file to standard error at initialization.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest fixture used to replace process state or
            dependencies.
    """
    stream = Stream()
    monkeypatch.setattr(reporter_module.sys, "stderr", stream)

    with ProgressReporter(1, file=None, mode="log") as reporter:
        reporter.advance_to(1)

    assert "1/1 it (100.0%)" in stream.getvalue()


def test_initial_progress_skips_old_milestones_and_honors_unit_formatting() -> None:
    """Verify initial progress skips past milestones and retains unit formatting."""
    events: list[ProgressEvent] = []
    reporter = ProgressReporter(
        total=2_000,
        initial=1_000,
        count_step=500,
        percent_step=None,
        seconds_step=None,
        callback=events.append,
        mode="log",
        emit_start=True,
        unit="row",
        unit_scale=True,
    )
    reporter.advance_to(2_000)

    assert [event.milestone for event in events] == [1_000, 1_500, 2_000]
    assert "1.00k/2.00k row" in events[0].message


def test_eta_excludes_work_completed_before_initial(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ETA uses only work completed after reporter initialization.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest fixture used to replace process state or
            dependencies.
    """
    clock = iter([0.0, 1.0, 1.0])
    monkeypatch.setattr(reporter_module.time, "monotonic", lambda: next(clock))
    events: list[ProgressEvent] = []
    reporter = ProgressReporter(
        total=1_000,
        initial=900,
        percent_step=None,
        seconds_step=0,
        callback=events.append,
        mode="log",
    )
    reporter.advance_to(901)
    assert events[0].eta_seconds == pytest.approx(99.0)


def test_numeric_unit_scale_is_applied() -> None:
    """Verify numeric unit scaling affects displayed current and total counts."""
    event = ProgressReporter(
        total=1_000,
        initial=500,
        mode="log",
        unit_scale=2.0,
    )._make_event(500)
    assert "1.00k/2.00k it" in event.message


def test_tty_mode_updates_and_closes_without_emitting_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify TTY reporting updates and closes without marking an event emitted.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest fixture used to replace process state or
            dependencies.
    """
    bar = Mock()
    tqdm_factory = Mock(return_value=bar)
    monkeypatch.setattr(reporter_module, "tqdm", tqdm_factory)
    reporter = ProgressReporter(total=5, desc=None, file=Stream(True), mode="tty")
    reporter.advance_to(2)
    assert not reporter.has_emitted
    reporter.finalize()
    tqdm_factory.assert_called_once()
    bar.update.assert_called_once_with(2)
    bar.close.assert_called_once_with()


def test_direct_tty_reporter_forwards_unit_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify direct TTY reporting forwards all unit-formatting settings.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest fixture used to replace process state or
            dependencies.
    """
    tqdm_factory = Mock(return_value=Mock())
    monkeypatch.setattr(reporter_module, "tqdm", tqdm_factory)
    ProgressReporter(
        total=5,
        mode="tty",
        unit="row",
        unit_scale=True,
        unit_divisor=1024,
    )
    assert tqdm_factory.call_args.kwargs["unit"] == "row"
    assert tqdm_factory.call_args.kwargs["unit_scale"] is True
    assert tqdm_factory.call_args.kwargs["unit_divisor"] == 1024


def test_backwards_progress_and_exceptional_context_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify invalid progress is rejected and exceptional exits only close the bar.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest fixture used to replace process state or
            dependencies.
    """
    bar = Mock()
    monkeypatch.setattr(reporter_module, "tqdm", Mock(return_value=bar))
    reporter = ProgressReporter(total=10, file=Stream(True), mode="tty")
    reporter.advance_to(5)
    with pytest.raises(ValueError, match="must not go backwards"):
        reporter.advance_to(4)
    with pytest.raises(TypeError, match="current must be an integer"):
        reporter.advance_to(5.5)  # ty: ignore[invalid-argument-type]

    with pytest.raises(RuntimeError), reporter:
        raise RuntimeError("boom")
    bar.close.assert_called_once_with()


def test_closed_reporter_rejects_updates_and_reentry_but_closing_is_idempotent() -> None:
    """Verify closed reporters reject reuse while repeated closing remains safe."""
    reporter = ProgressReporter(total=1, mode="disabled")
    reporter.close()
    reporter.close()
    reporter.finalize()
    with pytest.raises(RuntimeError, match="reporter is closed"):
        reporter.advance_to(1)
    with pytest.raises(RuntimeError, match="reporter is closed"):
        reporter.__enter__()


def test_configuration_is_immutable_after_initialization() -> None:
    """Verify configuration is immutable except for the validated milestone limit."""
    reporter = ProgressReporter(total=1, mode="disabled")
    with pytest.raises(AttributeError, match="total cannot be changed"):
        reporter.total = 2
    with pytest.raises(AttributeError, match="final_event cannot be changed"):
        reporter.final_event = "never"

    reporter.max_milestones_per_update = 20_000
    assert reporter.max_milestones_per_update == 20_000
    with pytest.raises(TypeError, match="max_milestones_per_update must be an integer"):
        reporter.max_milestones_per_update = 1.5  # ty: ignore[invalid-assignment]
    with pytest.raises(ValueError, match="max_milestones_per_update must be > 0"):
        reporter.max_milestones_per_update = 0
    with pytest.raises(ValueError, match="max_milestones_per_update must not be decreased"):
        reporter.max_milestones_per_update = 10_000


def test_extra_fields_are_copied_and_exposed_as_an_immutable_mapping() -> None:
    """Verify extra logging fields are copied into a read-only top-level mapping."""
    fields = {"job_id": "one"}
    reporter = ProgressReporter(
        total=1,
        mode="log",
        extra_fields=fields,
        percent_step=100,
        seconds_step=None,
    )
    fields["job_id"] = "two"

    assert reporter.extra_fields == {"job_id": "one"}
    with pytest.raises(TypeError, match="does not support item assignment"):
        reporter.extra_fields["job_id"] = "three"  # ty: ignore[invalid-assignment]


def test_final_event_never_suppresses_exact_total_for_all_triggers() -> None:
    """Verify never policy suppresses exact completion from every trigger type."""
    events: list[ProgressEvent] = []
    with ProgressReporter(
        total=4,
        percent_step=50,
        count_step=2,
        seconds_step=0,
        callback=events.append,
        mode="log",
        final_event="never",
    ) as reporter:
        reporter.advance_to(2)
        reporter.advance_to(4)
    assert [event.milestone for event in events] == [2]


def test_formatting_edge_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify duration formatting and backward clocks produce safe event values.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest fixture used to replace process state or
            dependencies.
    """
    assert ProgressReporter._format_hms(-1) == "00:00"
    assert ProgressReporter._format_hms(3661) == "01:01:01"

    clock = iter([10.0, 9.0])
    monkeypatch.setattr(reporter_module.time, "monotonic", lambda: next(clock))
    event = ProgressReporter(total=2, mode="log")._make_event(1)
    assert event.elapsed_seconds == 0.0
    assert event.eta_seconds is None
    assert "eta=??:??" in event.message


@pytest.mark.parametrize("unit_scale", [False, True, 2.5])
def test_arbitrarily_large_integer_totals_do_not_overflow(
    unit_scale: bool | float,
) -> None:
    """Verify extremely large totals work with every supported unit-scaling mode.

    Args:
        unit_scale (bool | float): Unit-scaling setting under test.
    """
    total = 10**400
    events: list[ProgressEvent] = []
    reporter = ProgressReporter(
        total=total,
        percent_step=50,
        count_step=None,
        seconds_step=None,
        callback=events.append,
        mode="log",
        unit_scale=unit_scale,
    )
    reporter.advance_to(total)

    assert [event.milestone for event in events] == [total // 2, total]
    assert events[0].current == total
    assert events[0].current_percent == 100.0
    assert events[0].eta_seconds == 0.0

    partial_events: list[ProgressEvent] = []
    partial = ProgressReporter(
        total=total,
        percent_step=None,
        count_step=1,
        seconds_step=None,
        callback=partial_events.append,
        mode="log",
        unit_scale=unit_scale,
    )
    partial.advance_to(1)
    assert partial_events[0].eta_seconds is None


def test_integer_string_conversion_limit_does_not_break_reporting() -> None:
    """Verify huge integer counts remain reportable beyond Python string limits."""
    current = 10**5_000
    events: list[ProgressEvent] = []
    reporter = ProgressReporter(
        total=None,
        percent_step=None,
        count_step=None,
        seconds_step=None,
        callback=events.append,
        mode="log",
    )
    reporter.advance_to(current)
    reporter.finalize()

    assert events[0].current == current
    assert events[0].message.startswith("1000000000")
