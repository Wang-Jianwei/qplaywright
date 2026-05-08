"""QPlaywright - Playwright-compatible automation for Qt QWidget applications."""

__version__ = "0.1.1"

from qplaywright.sync_api import sync_qplaywright
from qplaywright.agent import start_agent
from qplaywright.cpp import agent_header_path
from qplaywright.protocol import QPlaywrightClassMetadata, QPlaywrightClassMethod, QPlaywrightMethodArg

__all__ = [
	"sync_qplaywright",
	"start_agent",
	"agent_header_path",
	"QPlaywrightClassMetadata",
	"QPlaywrightClassMethod",
	"QPlaywrightMethodArg",
]
