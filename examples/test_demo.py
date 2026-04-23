"""Test script that automates the demo app using QPlaywright.

1. First run:   python examples/demo_app.py
2. Then run:    python examples/test_demo.py
"""

import sys
import os
sys.path.insert(0, ".")

from qplaywright.sync_api import sync_qplaywright


def main():
    port = int(os.environ.get("QPLAYWRIGHT_PORT", "19876"))
    with sync_qplaywright() as qp:
        # Connect to the running demo app
        app = qp.connect(port=port, timeout=5)
        print("Connected to demo app!")

        # Get the main window
        window = app.main_window()
        print(f"Window: {window.title()}")

        # --- Print widget tree (for debugging) ---
        print("\n--- Widget Tree ---")
        tree = window.widget_tree(max_depth=3)
        _print_tree(tree, indent=0)
        print("-------------------\n")

        # --- Test 1: Fill the login form ---
        print("Test 1: Filling login form...")
        window.locator("#username").fill("admin")
        window.locator("#password").fill("secret123")
        window.locator("#remember").check()
        window.locator("#role").select_option(label="Admin")
        print("  Form filled!")

        # Verify values
        assert window.locator("#username").input_value() == "admin"
        assert window.locator("#remember").is_checked()
        print("  Values verified!")

        # --- Test 2: Click login ---
        print("Test 2: Clicking login button...")
        window.locator("role=button", has_text="Login").click()

        # Check status changed
        status = window.locator("#status").text_content()
        assert "Logged in" in status, f"Unexpected status: {status}"
        print(f"  Status: {status}")

        # --- Test 3: Using expect assertions ---
        print("Test 3: Using expect assertions...")
        window.locator("#status").expect.to_contain_text("admin")
        window.locator("#login_btn").expect.to_be_visible()
        window.locator("#login_btn").expect.to_be_enabled()
        print("  All assertions passed!")

        # --- Test 4: Clear log ---
        print("Test 4: Clearing log...")
        window.locator("role=button", has_text="Clear Log").click()
        window.locator("#status").expect.to_contain_text("cleared")
        print("  Log cleared!")

        # --- Test 5: Screenshot ---
        print("Test 5: Taking screenshot...")
        result = window.screenshot(path="demo_screenshot.png")
        print(f"  Screenshot saved: {result}")

        # --- Test 6: Playwright-style getByRole ---
        print("Test 6: Using getByRole...")
        buttons = window.get_by_role("button").all()
        print(f"  Found {len(buttons)} buttons")
        for i, btn in enumerate(buttons):
            print(f"    [{i}] {btn.text_content()}")

        print("\n All tests passed!")


def _print_tree(nodes, indent=0):
    """Pretty-print widget tree."""
    for node in nodes:
        prefix = "  " * indent
        name = node.get("objectName", "")
        cls = node.get("class", "?")
        text = node.get("text", "")
        label = f"{prefix}{cls}"
        if name:
            label += f" #{name}"
        if text:
            label += f' "{text[:30]}"'
        print(label)
        for child in node.get("children", []):
            _print_tree([child], indent + 1)


if __name__ == "__main__":
    main()
