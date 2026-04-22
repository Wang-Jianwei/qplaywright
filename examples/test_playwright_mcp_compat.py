"""Manual end-to-end test for the playwright-mcp style compatibility tools."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from examples.test_mcp_demo import _call_tool, _project_root, _python_path_env


DEMO_PORT = 29876


async def main() -> None:
    root = _project_root()
    env = _python_path_env(root)
    env["QPLAYWRIGHT_PORT"] = str(DEMO_PORT)
    screenshot_path = root / "demo_playwright_compat_screenshot.png"

    demo_process = subprocess.Popen(
        [sys.executable, str(root / "examples" / "demo_app.py")],
        cwd=root,
        env=env,
    )

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "qplaywright.mcp_server"],
        env=env,
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                await _call_tool(session, "connect", {"name": "demo", "port": DEMO_PORT, "timeout": 10.0})

                await _call_tool(
                    session,
                    "invoke_widget_method",
                    {
                        "connection": "demo",
                        "selector": "#amount_editor",
                        "method_name": "setAmount",
                        "args": {"value": "88.50"},
                    },
                )
                await _call_tool(
                    session,
                    "invoke_widget_method",
                    {
                        "connection": "demo",
                        "selector": "#amount_editor",
                        "method_name": "setCurrency",
                        "args": {"code": "JPY"},
                    },
                )
                await _call_tool(
                    session,
                    "invoke_widget_method",
                    {
                        "connection": "demo",
                        "selector": "#amount_editor",
                        "method_name": "setPrecision",
                        "args": {"digits": 1},
                    },
                )
                await _call_tool(
                    session,
                    "invoke_widget_method",
                    {
                        "connection": "demo",
                        "selector": "#amount_editor",
                        "method_name": "applyDelta",
                        "args": {"delta": 2.4},
                    },
                )

                tabs = await _call_tool(session, "browser_tabs", {"action": "list", "connection": "demo"})
                print(f"Tabs: {tabs['result']}")

                snapshot = await _call_tool(session, "browser_snapshot", {"connection": "demo", "depth": 3})
                print(snapshot["snapshot"])

                refs_by_target = {
                    entry["target"]: entry["ref"]
                    for entry in snapshot["refs"]
                    if entry.get("target") and entry.get("ref")
                }
                username_ref = refs_by_target["#username"]
                password_ref = refs_by_target["#password"]
                remember_ref = refs_by_target["#remember"]
                role_ref = refs_by_target["#role"]
                environment_ref = refs_by_target["#environment"]
                notify_ref = refs_by_target["#notify"]
                notes_ref = refs_by_target["#notes"]
                login_ref = refs_by_target["#login_btn"]

                await _call_tool(
                    session,
                    "browser_fill_form",
                    {
                        "connection": "demo",
                        "fields": [
                            {"target": username_ref, "value": "admin"},
                            {"target": password_ref, "value": "secret123"},
                            {"target": notes_ref, "value": "Reviewed by playwright compat flow"},
                        ],
                    },
                )
                await _call_tool(
                    session,
                    "browser_verify_value",
                    {
                        "connection": "demo",
                        "type": "textbox",
                        "element": "Username field",
                        "target": username_ref,
                        "value": "admin",
                    },
                )
                await _call_tool(
                    session,
                    "browser_select_option",
                    {"connection": "demo", "target": role_ref, "values": ["Admin"]},
                )
                await _call_tool(
                    session,
                    "browser_select_option",
                    {"connection": "demo", "target": environment_ref, "values": ["Production"]},
                )
                await _call_tool(
                    session,
                    "browser_click",
                    {"connection": "demo", "target": remember_ref},
                )
                await _call_tool(
                    session,
                    "browser_click",
                    {"connection": "demo", "target": notify_ref},
                )
                login_result = await _call_tool(
                    session,
                    "browser_click",
                    {"connection": "demo", "target": login_ref},
                )
                print(f"Login click snapshot: {login_result['snapshot']}")

                await _call_tool(
                    session,
                    "browser_wait_for",
                    {"connection": "demo", "text": "Logged in as admin", "timeout": 5.0},
                )
                await _call_tool(
                    session,
                    "browser_verify_text_visible",
                    {"connection": "demo", "text": "payment=JPY 90.9 precision=1 adjustments=on"},
                )
                await _call_tool(
                    session,
                    "browser_verify_element_visible",
                    {
                        "connection": "demo",
                        "role": "button",
                        "accessibleName": "Login",
                    },
                )

                status_snapshot = await _call_tool(session, "browser_snapshot", {"connection": "demo", "depth": 3})
                status_ref = {
                    entry["target"]: entry["ref"]
                    for entry in status_snapshot["refs"]
                    if entry.get("target") and entry.get("ref")
                }["#status"]

                status = await _call_tool(
                    session,
                    "browser_snapshot",
                    {"connection": "demo", "target": status_ref, "depth": 0},
                )
                print(f"Status snapshot: {status['snapshot']}")
                assert "payment=JPY 90.9 precision=1 adjustments=on" in status["snapshot"]

                screenshot = await _call_tool(
                    session,
                    "browser_take_screenshot",
                    {"connection": "demo", "filename": str(screenshot_path)},
                )
                print(f"Screenshot: {screenshot}")

                await _call_tool(session, "disconnect", {"name": "demo"})
                print("Playwright-style compatibility flow completed")
    finally:
        demo_process.terminate()
        try:
            demo_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            demo_process.kill()
            demo_process.wait(timeout=5)


if __name__ == "__main__":
    asyncio.run(main())