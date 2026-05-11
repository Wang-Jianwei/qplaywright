"""Manual end-to-end test for a stable-handle driven MCP flow."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from examples.test_mcp_demo import (
    _attach_session,
    _call_tool,
    _close_session,
    _discover_widget_handles,
    _list_windows,
    _project_root,
    _python_path_env,
)


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

                await _attach_session(session, port=DEMO_PORT, timeout=60.0)

                snapshot = await _call_tool(session, "snapshot", {"depth": 12})
                print(snapshot["snapshot"])

                handles_by_target = await _discover_widget_handles(
                    session,
                    [
                        "#amount_editor",
                        "#username",
                        "#password",
                        "#remember",
                        "#role",
                        "#environment",
                        "#notify",
                        "#notes",
                        "#login_btn",
                        "#status",
                    ],
                )
                amount_handle = handles_by_target["#amount_editor"]
                username_handle = handles_by_target["#username"]
                password_handle = handles_by_target["#password"]
                remember_handle = handles_by_target["#remember"]
                role_handle = handles_by_target["#role"]
                environment_handle = handles_by_target["#environment"]
                notify_handle = handles_by_target["#notify"]
                notes_handle = handles_by_target["#notes"]
                login_handle = handles_by_target["#login_btn"]
                status_handle = handles_by_target["#status"]

                await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": amount_handle,
                        "method": "setAmount",
                        "args": {"value": "88.50"},
                    },
                )
                await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": amount_handle,
                        "method": "setCurrency",
                        "args": {"code": "JPY"},
                    },
                )
                await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": amount_handle,
                        "method": "setPrecision",
                        "args": {"digits": 1},
                    },
                )
                await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": amount_handle,
                        "method": "applyDelta",
                        "args": {"delta": 2.4},
                    },
                )

                tabs = await _list_windows(session)
                print(f"Tabs: {tabs}")

                await _call_tool(
                    session,
                    "input",
                    {"target": username_handle, "text": "admin"},
                )
                await _call_tool(
                    session,
                    "input",
                    {"target": password_handle, "text": "secret123"},
                )
                await _call_tool(
                    session,
                    "input",
                    {"target": notes_handle, "text": "Reviewed by stable handle flow"},
                )
                username_value = await _call_tool(session, "inspect", {"target": username_handle})
                assert username_value["value"] == "admin"

                await _call_tool(
                    session,
                    "choose",
                    {"target": role_handle, "label": "Admin"},
                )
                await _call_tool(
                    session,
                    "choose",
                    {"target": environment_handle, "label": "Production"},
                )
                await _call_tool(
                    session,
                    "press_key",
                    {"target": remember_handle, "key": "Space"},
                )
                await _call_tool(session, "press_key", {"target": notify_handle, "key": "Space"})
                login_result = await _call_tool(
                    session,
                    "click",
                    {"target": login_handle, "include_snapshot": True},
                )
                print(f"Login click snapshot: {login_result['snapshot']}")

                status_text = await _call_tool(session, "inspect", {"target": status_handle})
                assert "Logged in as admin" in status_text["text"]
                assert "payment=JPY 90.9 precision=1 adjustments=on" in status_text["text"]

                login_button = await _call_tool(session, "inspect", {"target": login_handle})
                assert login_button["exists"] is True

                status = await _call_tool(session, "snapshot", {"target": status_handle, "depth": 0})
                print(f"Status snapshot: {status['snapshot']}")
                assert "payment=JPY 90.9 precision=1 adjustments=on" in status["snapshot"]

                screenshot = await _call_tool(
                    session,
                    "screenshot",
                    {"path": str(screenshot_path)},
                )
                print(f"Screenshot: {screenshot}")

                await _close_session(session)
                print("Stable-handle flow completed")
    finally:
        demo_process.terminate()
        try:
            demo_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            demo_process.kill()
            demo_process.wait(timeout=5)


if __name__ == "__main__":
    asyncio.run(main())