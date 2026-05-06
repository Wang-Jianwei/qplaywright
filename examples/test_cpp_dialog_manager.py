"""Manual regression script for C++ overlay manager window switching.

1. Build and run: examples/cpp_demo/build_verify/demo_app.exe
2. Then run:     python examples/test_cpp_dialog_manager.py

The script validates a main-window -> dialog -> main-window interaction chain,
checks that the automation overlay does not leak into window/widget enumeration,
and saves screenshots next to the running demo executable.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, ".")

from qplaywright.sync_api import sync_qplaywright


def _window_titles(app):
    return [window.title() for window in app.windows()]


def _contains_overlay(nodes):
    for node in nodes:
        if node.get("objectName") == "_qplaywright_automation_overlay":
            return True
        if _contains_overlay(node.get("children", [])):
            return True
    return False


def main():
    port = int(os.environ.get("QPLAYWRIGHT_PORT", "19885"))
    with sync_qplaywright() as qp:
        app = qp.connect(port=port, timeout=5.0)
        main_window = app.window(title="C++ Demo")

        titles_before = _window_titles(app)
        assert len(titles_before) == 1, titles_before
        print(f"before={titles_before}")

        main_window.locator("#open_dialog_btn").click()

        titles_open = _window_titles(app)
        assert len(titles_open) == 2, titles_open
        assert any("Dialog Demo" in title for title in titles_open), titles_open
        print(f"opened={titles_open}")

        dialog = app.window(title="Dialog Demo")
        dialog.locator("#dialog_input").hover()
        dialog.locator("#dialog_input").fill("dialog-pass")
        dialog.locator("#dialog_apply_btn").click()

        dialog_status = dialog.locator("#dialog_status").text_content()
        assert "dialog-pass" in dialog_status, dialog_status
        print(f"dialog-status={dialog_status}")

        dialog_tree = dialog.widget_tree(max_depth=4)
        assert not _contains_overlay(dialog_tree), dialog_tree
        print("dialog-tree-ok")

        dialog_shot = "tmp_cpp_dialog_window.png"
        dialog.screenshot(path=dialog_shot)
        print(f"dialog-shot={dialog_shot}")

        dialog.locator("#dialog_close_btn").click()
        main_window.wait_for_timeout(0.2)

        titles_closed = _window_titles(app)
        assert len(titles_closed) == 1, titles_closed
        print(f"closed={titles_closed}")

        main_window.locator("#username").hover()
        main_window.locator("#username").fill("after-dialog")
        main_window.locator("#password").fill("secret")
        main_window.locator("#login_btn").click()

        main_status = main_window.locator("#status").text_content()
        assert "after-dialog" in main_status, main_status
        print(f"main-status={main_status}")

        main_tree = main_window.widget_tree(max_depth=4)
        assert not _contains_overlay(main_tree), main_tree
        print("main-tree-ok")

        main_shot = "tmp_cpp_dialog_main_window.png"
        main_window.screenshot(path=main_shot)
        print(f"main-shot={main_shot}")


if __name__ == "__main__":
    main()