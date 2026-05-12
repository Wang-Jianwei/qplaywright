"""Public exception types for QPlaywright."""

from __future__ import annotations

from typing import Any


class QPlaywrightError(RuntimeError):
    """Base exception for QPlaywright errors that are not socket-level failures."""

    def __init__(self, message: str, *, code: str | None = None, context: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.context = dict(context or {})


class QPlaywrightConnectionError(ConnectionError):
    """Raised when the client cannot establish or maintain the agent connection."""

    def __init__(self, message: str, *, code: str | None = None, context: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.context = dict(context or {})


class QPlaywrightProtocolError(QPlaywrightConnectionError):
    """Raised when the agent is reachable but the protocol handshake/setup fails."""


class QPlaywrightLookupError(QPlaywrightError):
    """Raised when a requested window, widget, or item cannot be resolved."""


class QPlaywrightActionError(QPlaywrightError):
    """Raised when a widget or item action fails after the target is resolved."""


class QPlaywrightAgentError(QPlaywrightError):
    """Raised when the agent returns an application-level error response."""


__all__ = [
    "QPlaywrightError",
    "QPlaywrightConnectionError",
    "QPlaywrightProtocolError",
    "QPlaywrightLookupError",
    "QPlaywrightActionError",
    "QPlaywrightAgentError",
]