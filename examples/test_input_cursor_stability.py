"""Manual regression for cursor stability during text input.

1. Run a demo app with the embedded agent.
2. Then run: python examples/test_input_cursor_stability.py

The script asserts that keyboard-like input actions do not move the real system
cursor. This protects MCP-style automation from regressing into real pointer
warping during text entry.
"""

from __future__ import annotations

import ctypes
import os
import sys

sys.path.insert(0, ".")

from qplaywright.sync_api import sync_qplaywright


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _cursor_pos() -> tuple[int, int]:
    point = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def _assert_cursor_stable(label: str, before: tuple[int, int], after: tuple[int, int]) -> None:
    assert before == after, f"{label} moved system cursor: {before} -> {after}"
    print(f"{label}={before}->{after}")


def main() -> None:
    if os.name != "nt":
        raise SystemExit("This regression script currently supports Windows only")

    port = int(os.environ.get("QPLAYWRIGHT_PORT", "19876"))
    with sync_qplaywright() as qp:
        app = qp.connect(port=port, timeout=5.0)
        window = app.main_window()

        before_fill = _cursor_pos()
        window.locator("#username").fill("cursor-stable")
        after_fill = _cursor_pos()
        _assert_cursor_stable("fill", before_fill, after_fill)

        before_hover = _cursor_pos()
        window.locator("#username").hover()
        after_hover = _cursor_pos()
        _assert_cursor_stable("hover", before_hover, after_hover)

        before_type = _cursor_pos()
        window.locator("#password").type("secret", delay=0)
        after_type = _cursor_pos()
        _assert_cursor_stable("type", before_type, after_type)

        before_press = _cursor_pos()
        window.locator("#password").press("Enter")
        after_press = _cursor_pos()
        _assert_cursor_stable("press", before_press, after_press)


if __name__ == "__main__":
    main()