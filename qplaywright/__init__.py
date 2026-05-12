"""QPlaywright - Playwright-compatible automation for Qt QWidget applications."""

__version__ = "0.1.1"

from qplaywright._logging import configure_logging
from qplaywright.sync_api import sync_qplaywright
from qplaywright.agent import start_agent
from qplaywright.cpp import agent_header_path
from qplaywright.errors import (
	QPlaywrightActionError,
    QPlaywrightAgentError,
    QPlaywrightConnectionError,
    QPlaywrightError,
	QPlaywrightLookupError,
    QPlaywrightProtocolError,
)
from qplaywright.protocol import QPlaywrightClassMetadata, QPlaywrightClassMethod, QPlaywrightMethodArg

__all__ = [
    "sync_qplaywright",
    "start_agent",
    "agent_header_path",
    "configure_logging",
    "QPlaywrightError",
    "QPlaywrightConnectionError",
    "QPlaywrightProtocolError",
    "QPlaywrightLookupError",
    "QPlaywrightActionError",
    "QPlaywrightAgentError",
    "QPlaywrightClassMetadata",
    "QPlaywrightClassMethod",
    "QPlaywrightMethodArg",
]
