"""Tests for the iterable progress wrapper."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest

from tqdm_milestones import (
    ProgressEvent,
    ProgressReporter,
    _iterator as iterator_module,
    tqdm_iter,
)

from ._support import Stream


@pytest.mark.parametrize("disable", [True, None])
def test_tqdm_iter_honors_tqdm_disable_in_log_mode(disable: bool | None) -> None:
    """Verify log output is suppressed for explicit or automatic disabling.

    Args:
        disable (bool | None): Disable setting under test.
    """
    stream = Stream()
    assert list(tqdm_iter([1], file=stream, disable=disable, mode="log")) == [1]
    assert stream.getvalue() == ""


def test_tqdm_iter_can_keep_a_short_unknown_iterable_silent() -> None:
    """Verify short unknown-length iteration can finish without emitting an event."""
    events: list[ProgressEvent] = []
    iterable = (value for value in range(2))

    assert list(
        tqdm_iter(
            iterable,
            percent_step=None,
            count_step=10,
            seconds_step=None,
            callback=events.append,
            mode="log",
            final_event="after_milestone",
        )
    ) == [0, 1]
    assert events == []


def test_tqdm_iter_rejects_invalid_disable_value() -> None:
    """Verify the iterable wrapper rejects an invalid disable setting."""
    with pytest.raises(TypeError, match="disable must be a boolean or None"):
        tqdm_iter([1], disable="yes", mode="log")  # ty: ignore[invalid-argument-type]


@pytest.mark.parametrize(
    ("removed_name", "replacement"),
    [
        ("log_complete", "final_event"),
        ("log_start", "emit_start"),
        ("stream", "file"),
    ],
)
def test_tqdm_iter_rejects_removed_options_with_migration_guidance(
    removed_name: str,
    replacement: str,
) -> None:
    """Verify removed options fail with guidance to their replacements.

    Args:
        removed_name (str): Removed option name under test.
        replacement (str): Supported replacement option name.
    """
    options: Any = {removed_name: True}
    with pytest.raises(
        TypeError,
        match=rf"{removed_name} is no longer supported; use {replacement}",
    ):
        tqdm_iter([1], mode="log", **options)


def test_tqdm_iter_rejects_invalid_logger_stacklevel_before_adjustment() -> None:
    """Verify logger stack depth is validated before wrapper adjustment."""
    with pytest.raises(ValueError, match="logger_stacklevel must be > 0"):
        tqdm_iter([1], logger_stacklevel=0, mode="log")


def test_tqdm_iter_rejects_invalid_initial_before_selecting_output_mode() -> None:
    """Verify initial progress is validated before output mode selection."""
    with pytest.raises(ValueError, match="initial must be >= 0"):
        tqdm_iter([1], initial=-1, mode="tty")


def test_tqdm_iter_validates_reporting_options_before_selecting_output_mode() -> None:
    """Verify reporting options are validated consistently across output modes."""
    with pytest.raises(ValueError, match="percent_step must be finite and in"):
        tqdm_iter([1], percent_step=0, mode="tty")

    with pytest.raises(TypeError, match="desc must be a string or None"):
        tqdm_iter([1], desc=1, mode="log")  # ty: ignore[invalid-argument-type]

    with pytest.raises(ValueError, match="max_milestones_per_update must be > 0"):
        tqdm_iter([1], max_milestones_per_update=0, mode="tty")

    with pytest.raises(TypeError, match="max_milestones_per_update must be an integer"):
        tqdm_iter(
            [1],
            max_milestones_per_update=1.5,  # ty: ignore[invalid-argument-type]
            mode="tty",
        )

    with pytest.raises(TypeError, match="extra_fields must be a mapping"):
        tqdm_iter(
            [1],
            extra_fields=[],  # ty: ignore[invalid-argument-type]
            mode="log",
        )


def test_tqdm_iter_resolves_file_none_when_called(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a missing output file resolves to the current standard error stream.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest fixture used to replace process state or
            dependencies.
    """
    stream = Stream()
    monkeypatch.setattr(iterator_module.sys, "stderr", stream)

    assert list(tqdm_iter([1], file=None, mode="log")) == [1]
    assert "1/1 it (100.0%)" in stream.getvalue()


def test_tqdm_iter_tty_forwards_options(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify TTY mode forwards normalized progress options to tqdm.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest fixture used to replace process state or
            dependencies.
    """
    calls: list[dict[str, object]] = []

    def fake_tqdm(iterable: Iterator[int] | range, **kwargs: object) -> Iterator[int]:
        """Capture tqdm options and return an iterator over the supplied values.

        Args:
            iterable (Iterator[int] | range): Values that the fake tqdm implementation should
                yield.
            **kwargs (object): Options forwarded to the fake tqdm implementation.

        Returns:
            Iterator[int]: Iterator over the supplied values.
        """
        calls.append(kwargs)
        return iter(iterable)

    monkeypatch.setattr(iterator_module, "tqdm", fake_tqdm)
    stream = Stream(True)
    assert list(
        tqdm_iter(
            range(2),
            file=stream,
            desc="explicit",
            mode="auto",
            final_event="never",
            unit="row",
        )
    ) == [
        0,
        1,
    ]
    assert calls == [
        {
            "total": 2,
            "initial": 0,
            "unit": "row",
            "unit_scale": False,
            "unit_divisor": 1000,
            "disable": False,
            "file": stream,
            "desc": "explicit",
        }
    ]


def test_tqdm_iter_tty_does_not_inject_empty_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify an omitted label does not overwrite tqdm defaults with an empty string.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest fixture used to replace process state or
            dependencies.
    """
    calls: list[dict[str, object]] = []

    def fake_tqdm(iterable: range, **kwargs: object) -> Iterator[int]:
        """Capture tqdm options and return an iterator over the supplied values.

        Args:
            iterable (range): Values that the fake tqdm implementation should yield.
            **kwargs (object): Options forwarded to the fake tqdm implementation.

        Returns:
            Iterator[int]: Iterator over the supplied values.
        """
        calls.append(kwargs)
        return iter(iterable)

    monkeypatch.setattr(iterator_module, "tqdm", fake_tqdm)
    stream = Stream(True)
    assert list(tqdm_iter(range(1), file=stream, desc=None, mode="tty", unit="file")) == [0]
    assert calls == [
        {
            "total": 1,
            "initial": 0,
            "unit": "file",
            "unit_scale": False,
            "unit_divisor": 1000,
            "disable": False,
            "file": stream,
        }
    ]


def test_tqdm_iter_adds_initial_to_inferred_total_in_tty_and_log_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify inferred totals include initial progress in TTY and log modes.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest fixture used to replace process state or
            dependencies.
    """
    calls: list[dict[str, object]] = []

    def fake_tqdm(iterable: list[int], **kwargs: object) -> Iterator[int]:
        """Capture tqdm options and return an iterator over the supplied values.

        Args:
            iterable (list[int]): Values that the fake tqdm implementation should yield.
            **kwargs (object): Options forwarded to the fake tqdm implementation.

        Returns:
            Iterator[int]: Iterator over the supplied values.
        """
        calls.append(kwargs)
        return iter(iterable)

    monkeypatch.setattr(iterator_module, "tqdm", fake_tqdm)
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
    """Verify real tqdm integration renders completed TTY output."""
    stream = Stream(True)
    assert list(tqdm_iter(range(2), file=stream, desc="real", mode="tty")) == [0, 1]
    output = stream.getvalue()
    assert "real:" in output
    assert "2/2" in output


def test_tqdm_iter_uses_file_desc_total_and_callback() -> None:
    """Verify explicit output, label, total, and callback settings work together."""
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
    """Verify sized iterables infer totals without inventing a description."""
    events: list[ProgressEvent] = []
    assert list(
        tqdm_iter(
            ["a"],
            desc=None,
            percent_step=None,
            seconds_step=None,
            callback=events.append,
            mode="log",
            emit_start=True,
        )
    ) == ["a"]
    assert [(event.current, event.total, event.description) for event in events] == [
        (0, 1, None),
        (1, 1, None),
    ]


def test_tqdm_iter_distinguishes_empty_and_unknown_iterables() -> None:
    """Verify empty known totals differ from unknown iterable totals."""
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
    assert [(event.total, event.current_percent) for event in unknown_events] == [(None, None)]


def test_tqdm_iter_reports_empty_unknown_iterable_by_default() -> None:
    """Verify an empty unknown-length iterable emits its zero state by default."""
    events: list[ProgressEvent] = []

    assert list(tqdm_iter(iter(()), callback=events.append, mode="log")) == []

    assert [(event.current, event.milestone, event.total) for event in events] == [(0, 0, None)]
    assert events[0].message.startswith("0 it elapsed=")


def test_logger_stacklevel_points_to_user_code(caplog: pytest.LogCaptureFixture) -> None:
    """Verify direct and wrapped logging records identify the user call site.

    Args:
        caplog (pytest.LogCaptureFixture): Pytest fixture used to capture emitted logging records.
    """
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
