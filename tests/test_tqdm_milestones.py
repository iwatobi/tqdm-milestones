from __future__ import annotations

import io
import logging
from collections.abc import Iterator
from itertools import count
from unittest.mock import Mock

import pytest

import tqdm_milestones as module
from tqdm_milestones import ProgressEvent, ProgressReporter, tqdm_iter


class Stream(io.StringIO):
    def __init__(self, is_tty: bool = False) -> None:
        super().__init__()
        self.is_tty = is_tty

    def isatty(self) -> bool:
        return self.is_tty


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"total": -1}, "total must be >= 0"),
        ({"total": 1, "seconds_step": -1}, "seconds_step must be >= 0"),
        ({"total": 1, "percent_step": 0}, "percent_step must be in"),
        ({"total": 1, "percent_step": 101}, "percent_step must be in"),
        ({"total": 1, "count_step": 0}, "count_step must be > 0"),
        ({"total": 1, "bar_width": 0}, "bar_width must be > 0"),
        ({"total": 1, "logger_stacklevel": 0}, "logger_stacklevel must be > 0"),
        (
            {"total": 1, "max_milestones_per_update": 0},
            "max_milestones_per_update must be > 0",
        ),
        ({"total": 1.5}, "total must be >= 0"),
        ({"total": 1, "seconds_step": float("nan")}, "seconds_step must be >= 0"),
        ({"total": 1, "seconds_step": 10**400}, "seconds_step must be >= 0"),
        ({"total": 1, "percent_step": float("inf")}, "percent_step must be in"),
        ({"total": 1, "count_step": 1.5}, "count_step must be > 0"),
        ({"total": 1, "bar_width": True}, "bar_width must be > 0"),
        ({"total": 1, "desc": 1}, "desc must be a string or None"),
        ({"total": 1, "initial": -1}, "initial must be >= 0"),
        ({"total": 1, "initial": 2}, "initial must not exceed total"),
        ({"total": 1, "unit": 1}, "unit must be a string"),
        ({"total": 1, "unit_scale": float("nan")}, "numeric unit_scale must be > 0"),
        ({"total": 1, "unit_scale": 0}, "numeric unit_scale must be > 0"),
        ({"total": 1, "unit_scale": -1}, "numeric unit_scale must be > 0"),
        ({"total": 1, "unit_divisor": 0}, "unit_divisor must be > 0"),
        ({"total": 1, "unit_divisor": True}, "unit_divisor must be > 0"),
        ({"total": 1, "log_level": True}, "log_level must be an integer"),
        ({"total": 1, "log_start": 1}, "log_start must be a boolean"),
        ({"total": 1, "log_complete": 1}, "log_complete must be a boolean"),
        ({"total": 1, "extra_fields": []}, "extra_fields must be a dictionary"),
        (
            {"total": 1, "extra_fields": {"message": "x", "name": "x"}},
            "extra_fields contains reserved logging fields: message, name",
        ),
        ({"total": 1, "callback": 1}, "callback must be callable"),
    ],
)
def test_validation(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ProgressReporter(**kwargs)  # type: ignore[arg-type]


def test_mode_validation_and_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="mode must be one of"):
        module._resolve_mode("bad", Stream())  # type: ignore[arg-type]

    monkeypatch.setenv("TQDM_MILESTONES_MODE", "bad")
    with pytest.raises(ValueError, match="TQDM_MILESTONES_MODE must be"):
        module._resolve_mode("auto", Stream())

    monkeypatch.setenv("TQDM_MILESTONES_MODE", "disabled")
    assert module._resolve_mode("auto", Stream(True)) == "disabled"
    assert module._resolve_mode("log", Stream(True)) == "log"
    monkeypatch.delenv("TQDM_MILESTONES_MODE")
    assert module._resolve_mode("auto", Stream(True)) == "tty"
    assert module._resolve_mode("auto", object()) == "log"  # type: ignore[arg-type]


def test_progress_event_log_fields() -> None:
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


def test_callback_gets_start_all_crossed_milestones_and_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = count(0.0, 1.0)
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock))
    events: list[ProgressEvent] = []
    reporter = ProgressReporter(
        total=10,
        desc="work",
        percent_step=25,
        count_step=2,
        seconds_step=None,
        callback=events.append,
        mode="log",
        log_start=True,
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
    clock = iter([0.0, 2.0, 2.0, 2.0, 2.0])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock))
    stream = Stream()
    reporter = ProgressReporter(
        total=None,
        desc="",
        percent_step=None,
        count_step=None,
        seconds_step=1,
        stream=stream,
        mode="log",
    )
    assert not reporter.has_emitted
    reporter.advance_to(3)
    reporter.advance_to(3)
    reporter.finalize()
    assert stream.getvalue().count("3 it elapsed=00:02 eta=??:??") == 1


def test_unknown_total_milestone_message_shows_observed_progress() -> None:
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


def test_log_complete_overrides_log_start_for_an_empty_job() -> None:
    events: list[ProgressEvent] = []
    with ProgressReporter(
        total=0,
        callback=events.append,
        mode="log",
        log_start=True,
        log_complete=False,
    ):
        pass
    assert events == []


def test_crossed_milestones_distinguish_threshold_from_observed_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = count(0.0, 10.0)
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock))
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
    """Short jobs still leave one useful final status line on successful exit."""
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
    logger = logging.getLogger("tqdm_milestones.test")
    reporter = ProgressReporter(
        total=4,
        percent_step=50,
        seconds_step=None,
        logger=logger,
        extra_fields={"job_id": "abc", "progress_current": "overridden"},
        mode="log",
    )
    with caplog.at_level(logging.INFO, logger=logger.name):
        reporter.advance_to(2)

    record = caplog.records[0]
    assert record.progress_current == 2  # type: ignore[attr-defined]
    assert record.progress_total == 4  # type: ignore[attr-defined]
    assert record.job_id == "abc"  # type: ignore[attr-defined]


def test_callback_failure_can_resume_without_losing_or_repeating_milestones() -> None:
    delivered: list[int] = []
    failed_once = False

    def callback(event: ProgressEvent) -> None:
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
    "reporter",
    [
        ProgressReporter(
            total=100,
            percent_step=0.000001,
            count_step=None,
            seconds_step=None,
            mode="log",
            max_milestones_per_update=5,
        ),
        ProgressReporter(
            total=None,
            percent_step=None,
            count_step=1,
            seconds_step=None,
            mode="log",
            max_milestones_per_update=5,
        ),
    ],
)
def test_milestone_limit_rejects_huge_ranges_before_materializing_them(
    reporter: ProgressReporter,
) -> None:
    with pytest.raises(ValueError, match="crosses .* milestones"):
        reporter.advance_to(10)
    assert reporter.current == 0


def test_milestone_limit_applies_to_combined_deduplicated_events() -> None:
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


def test_subnormal_percentage_step_hits_the_guard_without_corrupting_state() -> None:
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
    callback = Mock()
    reporter = ProgressReporter(total=2, callback=callback, mode="disabled", log_start=True)
    reporter.advance_to(3)
    reporter.finalize()
    assert reporter.current == 2
    callback.assert_not_called()


@pytest.mark.parametrize("disable", [True, None])
def test_tqdm_iter_honors_tqdm_disable_in_log_mode(disable: bool | None) -> None:
    stream = Stream()
    assert list(tqdm_iter([1], file=stream, disable=disable, mode="log")) == [1]
    assert stream.getvalue() == ""


def test_tqdm_iter_rejects_invalid_disable_value() -> None:
    with pytest.raises(ValueError, match="disable must be a boolean or None"):
        list(tqdm_iter([1], disable="yes", mode="log"))


def test_tqdm_iter_rejects_invalid_logger_stacklevel_before_adjustment() -> None:
    with pytest.raises(ValueError, match="logger_stacklevel must be > 0"):
        list(tqdm_iter([1], logger_stacklevel=0, mode="log"))


def test_tqdm_iter_rejects_invalid_initial_before_selecting_output_mode() -> None:
    with pytest.raises(ValueError, match="initial must be >= 0"):
        list(tqdm_iter([1], initial=-1, mode="tty"))


def test_tqdm_iter_validates_reporting_options_before_selecting_output_mode() -> None:
    with pytest.raises(ValueError, match="percent_step must be in"):
        list(tqdm_iter([1], percent_step=0, mode="tty"))

    with pytest.raises(ValueError, match="desc must be a string or None"):
        list(tqdm_iter([1], desc=1, mode="log"))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="max_milestones_per_update must be > 0"):
        list(tqdm_iter([1], max_milestones_per_update=0, mode="tty"))


def test_tqdm_iter_treats_file_none_as_the_configured_stream() -> None:
    stream = Stream()
    assert list(tqdm_iter([1], stream=stream, file=None, mode="log")) == [1]
    assert "1/1 it (100.0%)" in stream.getvalue()


def test_initial_progress_skips_old_milestones_and_honors_unit_formatting() -> None:
    events: list[ProgressEvent] = []
    reporter = ProgressReporter(
        total=2_000,
        initial=1_000,
        count_step=500,
        percent_step=None,
        seconds_step=None,
        callback=events.append,
        mode="log",
        log_start=True,
        unit="row",
        unit_scale=True,
    )
    reporter.advance_to(2_000)

    assert [event.milestone for event in events] == [1_000, 1_500, 2_000]
    assert "1.00k/2.00k row" in events[0].message


def test_eta_excludes_work_completed_before_initial(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = iter([0.0, 1.0, 1.0])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock))
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
    event = ProgressReporter(
        total=1_000,
        initial=500,
        mode="log",
        unit_scale=2.0,
    )._make_event(500)
    assert "1.00k/2.00k it" in event.message


def test_tty_mode_updates_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    bar = Mock()
    tqdm_factory = Mock(return_value=bar)
    monkeypatch.setattr(module, "tqdm", tqdm_factory)
    reporter = ProgressReporter(total=5, desc=None, stream=Stream(True), mode="tty")
    reporter.advance_to(2)
    reporter.finalize()
    tqdm_factory.assert_called_once()
    bar.update.assert_called_once_with(2)
    bar.close.assert_called_once_with()


def test_direct_tty_reporter_forwards_unit_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    tqdm_factory = Mock(return_value=Mock())
    monkeypatch.setattr(module, "tqdm", tqdm_factory)
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


def test_backwards_progress_and_exceptional_context_exit() -> None:
    reporter = ProgressReporter(total=10, mode="disabled")
    reporter.advance_to(5)
    with pytest.raises(ValueError, match="must not go backwards"):
        reporter.advance_to(4)
    with pytest.raises(ValueError, match="current must be an integer"):
        reporter.advance_to(5.5)  # type: ignore[arg-type]

    bar = Mock()
    reporter._bar = bar
    with pytest.raises(RuntimeError), reporter:
        raise RuntimeError("boom")
    bar.close.assert_called_once_with()


def test_closed_reporter_rejects_updates_and_reentry_but_closing_is_idempotent() -> None:
    reporter = ProgressReporter(total=1, mode="disabled")
    reporter.close()
    reporter.close()
    reporter.finalize()
    with pytest.raises(RuntimeError, match="reporter is closed"):
        reporter.advance_to(1)
    with pytest.raises(RuntimeError, match="reporter is closed"):
        reporter.__enter__()


def test_configuration_is_immutable_after_initialization() -> None:
    reporter = ProgressReporter(total=1, mode="disabled")
    with pytest.raises(AttributeError, match="total cannot be changed"):
        reporter.total = 2

    reporter.max_milestones_per_update = 20_000
    assert reporter.max_milestones_per_update == 20_000
    with pytest.raises(ValueError, match="max_milestones_per_update must be > 0"):
        reporter.max_milestones_per_update = 0


def test_mutated_extra_fields_are_revalidated_before_logging() -> None:
    reporter = ProgressReporter(
        total=1,
        mode="log",
        extra_fields={"job_id": "one"},
        percent_step=100,
        seconds_step=None,
    )
    reporter.extra_fields["message"] = "reserved"
    with pytest.raises(ValueError, match="reserved logging fields: message"):
        reporter.advance_to(1)
    assert reporter.current == 0

    with pytest.raises(ValueError, match="reserved logging fields: message"):
        reporter.finalize()


def test_log_complete_false_suppresses_exact_total_for_all_triggers() -> None:
    events: list[ProgressEvent] = []
    with ProgressReporter(
        total=4,
        percent_step=50,
        count_step=2,
        seconds_step=0,
        callback=events.append,
        mode="log",
        log_complete=False,
    ) as reporter:
        reporter.advance_to(2)
        reporter.advance_to(4)
    assert [event.milestone for event in events] == [2]


def test_formatting_edge_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ProgressReporter._format_hms(-1) == "00:00"
    assert ProgressReporter._format_hms(3661) == "01:01:01"

    clock = iter([10.0, 9.0])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock))
    event = ProgressReporter(total=2, mode="log")._make_event(1)
    assert event.elapsed_seconds == 0.0
    assert event.eta_seconds is None
    assert "eta=??:??" in event.message


@pytest.mark.parametrize("unit_scale", [False, True, 2.5])
def test_arbitrarily_large_integer_totals_do_not_overflow(
    unit_scale: bool | float,
) -> None:
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


def test_tqdm_iter_tty_forwards_options(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_tqdm(iterable: Iterator[int] | range, **kwargs: object) -> Iterator[int]:
        calls.append(kwargs)
        return iter(iterable)

    monkeypatch.setattr(module, "tqdm", fake_tqdm)
    stream = Stream(True)
    assert list(tqdm_iter(range(2), stream=stream, desc="explicit", mode="auto", unit="row")) == [
        0,
        1,
    ]
    assert calls == [{"unit": "row", "file": stream, "desc": "explicit"}]


def test_tqdm_iter_tty_does_not_inject_empty_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An omitted label must not overwrite tqdm defaults with an empty string."""
    calls: list[dict[str, object]] = []

    def fake_tqdm(iterable: range, **kwargs: object) -> Iterator[int]:
        calls.append(kwargs)
        return iter(iterable)

    monkeypatch.setattr(module, "tqdm", fake_tqdm)
    stream = Stream(True)
    assert list(tqdm_iter(range(1), file=stream, desc=None, mode="tty", unit="file")) == [0]
    assert calls == [{"file": stream, "unit": "file"}]


def test_tqdm_iter_adds_initial_to_inferred_total_in_tty_and_log_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_tqdm(iterable: list[int], **kwargs: object) -> Iterator[int]:
        calls.append(kwargs)
        return iter(iterable)

    monkeypatch.setattr(module, "tqdm", fake_tqdm)
    tty_stream = Stream(True)
    assert list(tqdm_iter([1, 2], file=tty_stream, mode="tty", initial=1)) == [1, 2]
    assert calls[0]["total"] == 3

    events: list[ProgressEvent] = []
    assert list(
        tqdm_iter(
            [1, 2],
            mode="log",
            initial=1,
            callback=events.append,
            percent_step=None,
            count_step=1,
            seconds_step=None,
        )
    ) == [1, 2]
    assert [(event.current, event.total) for event in events] == [(2, 3), (3, 3)]


def test_real_tqdm_integration_writes_and_closes_a_tty_bar() -> None:
    stream = Stream(True)
    assert list(tqdm_iter(range(2), stream=stream, desc="real", mode="tty")) == [0, 1]
    output = stream.getvalue()
    assert "real:" in output
    assert "2/2" in output


def test_tqdm_iter_uses_file_desc_total_and_callback() -> None:
    events: list[ProgressEvent] = []
    stream = Stream()
    generator = (value for value in range(2))
    assert list(
        tqdm_iter(
            generator,
            file=stream,
            desc="123",
            total=2,
            percent_step=50,
            seconds_step=None,
            callback=events.append,
            mode="log",
            extra_fields={"unused_for_callback": True},
        )
    ) == [0, 1]
    assert [event.current for event in events] == [1, 2]
    assert events[0].description == "123"


def test_tqdm_iter_sized_default_total_and_implicit_description() -> None:
    events: list[ProgressEvent] = []
    assert list(
        tqdm_iter(
            ["a"],
            desc=None,
            percent_step=None,
            seconds_step=None,
            callback=events.append,
            mode="log",
            log_start=True,
        )
    ) == ["a"]
    assert [(event.current, event.total, event.description) for event in events] == [
        (0, 1, None),
        (1, 1, None),
    ]


def test_tqdm_iter_distinguishes_empty_and_unknown_iterables() -> None:
    empty_events: list[ProgressEvent] = []
    unknown_events: list[ProgressEvent] = []

    assert list(tqdm_iter([], callback=empty_events.append, mode="log")) == []
    assert list(
        tqdm_iter(
            (value for value in [1]),
            callback=unknown_events.append,
            mode="log",
            percent_step=None,
            seconds_step=None,
        )
    ) == [1]

    assert [(event.total, event.current_percent) for event in empty_events] == [(0, 100.0)]
    assert [(event.total, event.current_percent) for event in unknown_events] == [
        (None, None)
    ]


def test_logger_stacklevel_points_to_user_code(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("tqdm_milestones.stacklevel")
    with caplog.at_level(logging.INFO, logger=logger.name):
        direct = ProgressReporter(
            total=1,
            logger=logger,
            mode="log",
            percent_step=100,
            seconds_step=None,
        )
        direct.advance_to(1)
        list(
            tqdm_iter(
                [1],
                logger=logger,
                mode="log",
                percent_step=100,
                seconds_step=None,
            )
        )

    assert [record.funcName for record in caplog.records] == [
        "test_logger_stacklevel_points_to_user_code",
        "test_logger_stacklevel_points_to_user_code",
    ]
