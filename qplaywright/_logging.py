"""Shared logging helpers for qplaywright."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import IO

_PACKAGE_LOGGER_NAME = "qplaywright"
_QPLAYWRIGHT_HANDLER_MARKER = "_qplaywright_configured_handler"
_LOG_LEVEL_ENV = "QPLAYWRIGHT_LOG_LEVEL"
_LOG_FILE_ENV = "QPLAYWRIGHT_LOG_FILE"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def _package_logger() -> logging.Logger:
    logger = logging.getLogger(_PACKAGE_LOGGER_NAME)
    if not any(isinstance(handler, logging.NullHandler) for handler in logger.handlers):
        logger.addHandler(logging.NullHandler())
    return logger


def _normalize_level(level: int | str | None) -> int | None:
    if level is None:
        return None
    if isinstance(level, int):
        return level

    normalized = str(level).strip().upper()
    if not normalized:
        return None
    if normalized.isdigit():
        return int(normalized)

    resolved = logging.getLevelNamesMapping().get(normalized)
    if resolved is None:
        raise ValueError(f"Unsupported qplaywright log level: {level!r}")
    return resolved


def configure_logging(
    *,
    level: int | str = logging.INFO,
    stream: IO[str] | None = None,
    filename: str | Path | None = None,
    force: bool = False,
) -> logging.Logger:
    """Configure the shared qplaywright package logger.

    This only manages handlers previously created by qplaywright itself so it
    can coexist with application-managed logging setups.
    """

    if stream is not None and filename is not None:
        raise ValueError("configure_logging accepts either stream or filename, not both")

    logger = _package_logger()
    normalized_level = _normalize_level(level)
    managed_handlers = [
        handler for handler in logger.handlers if getattr(handler, _QPLAYWRIGHT_HANDLER_MARKER, False)
    ]

    if managed_handlers and not force:
        if normalized_level is not None:
            logger.setLevel(normalized_level)
        return logger

    for handler in managed_handlers:
        logger.removeHandler(handler)
        handler.close()

    if filename is not None:
        handler: logging.Handler = logging.FileHandler(Path(filename), encoding="utf-8")
    else:
        handler = logging.StreamHandler(stream)
    setattr(handler, _QPLAYWRIGHT_HANDLER_MARKER, True)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO if normalized_level is None else normalized_level)
    logger.propagate = False
    return logger


def configure_logging_from_env(*, default_level: int | str | None = None) -> logging.Logger | None:
    """Configure qplaywright logging from environment variables when requested."""

    env_level = os.environ.get(_LOG_LEVEL_ENV, "").strip()
    env_file = os.environ.get(_LOG_FILE_ENV, "").strip()
    effective_level = env_level or default_level
    if effective_level is None and not env_file:
        return None
    return configure_logging(level=effective_level or logging.INFO, filename=env_file or None)


_package_logger()


__all__ = ["configure_logging", "configure_logging_from_env"]