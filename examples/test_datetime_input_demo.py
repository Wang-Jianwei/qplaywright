"""Manual regression for keyboard-style QDateTimeEdit input in the data entry dialog.

1. Run a demo app with the embedded agent.
2. Then run: python examples/test_datetime_input_demo.py
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, ".")

from qplaywright.sync_api import sync_qplaywright


def main() -> None:
    port = int(os.environ.get("QPLAYWRIGHT_PORT", "19876"))
    with sync_qplaywright() as qp:
        app = qp.connect(port=port, timeout=5.0)
        window = app.main_window()

        window.locator("#main_tabs").tab("Data").click()
        before_status = window.locator("#data_status").text_content()
        match = re.search(r"Showing (\d+) entr(?:y|ies)", before_status)
        assert match is not None, before_status
        before_count = int(match.group(1))

        window.locator("#add_entry_btn").click()

        window.locator("#entry_name").fill("Date Input User")
        window.locator("#entry_email").fill("date.input@example.com")
        window.locator("#entry_tags").fill("date, regression")
        window.locator("#entry_description").fill("Keyboard date input regression")

        start_date = window.locator("#entry_start_date")
        target_text = "2026/5/20 09:30"
        start_date.fill(target_text)
        assert start_date.input_value() == target_text

        window.locator("role=button", has_text="OK").click()

        after_status = window.locator("#data_status").text_content()
        match = re.search(r"Showing (\d+) entr(?:y|ies)", after_status)
        assert match is not None, after_status
        after_count = int(match.group(1))
        assert after_count == before_count + 1, after_status

        window.locator("#main_tabs").tab("Login").click()
        log_text = window.locator("#log").text_content()
        assert "Added entry: Date Input User" in log_text, log_text

        print("datetime-input-regression=ok")


if __name__ == "__main__":
    main()