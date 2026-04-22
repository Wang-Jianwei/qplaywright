"""QPlaywright - Playwright-compatible automation for Qt QWidget applications."""

__version__ = "0.1.0"

from qplaywright.sync_api import sync_qplaywright
from qplaywright.agent import start_agent
from qplaywright.protocol import QPlaywrightClassMetadata, QPlaywrightClassMethod, QPlaywrightMethodArg

__all__ = [
	"sync_qplaywright",
	"start_agent",
	"QPlaywrightClassMetadata",
	"QPlaywrightClassMethod",
	"QPlaywrightMethodArg",
]
