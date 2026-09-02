"""Shared support utilities for tqdm_milestones tests."""

from __future__ import annotations

import io


class Stream(io.StringIO):
    """In-memory text stream with configurable TTY detection.

    Attributes:
        is_tty (bool): Whether the stream reports that it is attached to a terminal.
    """

    def __init__(self, is_tty: bool = False) -> None:
        """Initialize the stream with the requested TTY behavior.

        Args:
            is_tty (bool): Whether the stream reports that it is attached to a terminal.
        """
        super().__init__()
        self.is_tty = is_tty

    def isatty(self) -> bool:
        """Return whether the stream should be treated as a TTY.

        Returns:
            bool: Whether the stream should be treated as a TTY.
        """
        return self.is_tty
