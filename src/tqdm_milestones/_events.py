"""Event data and public type aliases."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

FinalEventPolicy = Literal["always", "after_milestone", "never"]
ProgressMode = Literal["auto", "tty", "log", "disabled"]


@dataclass(frozen=True, slots=True, kw_only=True)
class ProgressEvent:
    """Structured data produced for one progress milestone.

    Attributes:
        current (int): Actual completed-item count observed when the event was emitted.
        milestone (int): Threshold represented by the event.
        total (int | None): Expected item count. ``None`` means unknown; zero means empty.
        current_percent (float | None): Actual observed percentage, or ``None`` when unknown.
        milestone_percent (float | None): Percentage represented by ``milestone``, or
            ``None`` when unknown.
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
