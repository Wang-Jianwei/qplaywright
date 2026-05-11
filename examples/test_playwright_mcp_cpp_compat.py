"""Manual end-to-end test for a stable-handle MCP flow against the C++ demo."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from examples.test_mcp_cpp_demo import _cpp_demo_env, _find_cpp_demo_executable
from examples.test_mcp_demo import (
    _attach_session,
    _call_tool,
    _close_session,
    _discover_widget_handles,
    _list_windows,
    _project_root,
)


async def main() -> None:
    root = _project_root()
    env = _cpp_demo_env(root)
    executable = _find_cpp_demo_executable(root)
    screenshot_path = root / "demo_cpp_playwright_compat_screenshot.png"

    demo_process = subprocess.Popen([str(executable)], cwd=executable.parent, env=env)

    server_params = StdioServerParameters(
        command="d:/workdir/wangjianwei/projects/bot/qt-use/.venv/Scripts/python.exe",
        args=["-m", "qplaywright.mcp_server"],
        env=env,
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                await _attach_session(session, port=19876, timeout=60.0)

                tabs = await _list_windows(session)
                print(f"Tabs: {tabs}")

                snapshot = await _call_tool(session, "snapshot", {"depth": 12})
                print(snapshot["widgets"])

                handles_by_target = await _discover_widget_handles(
                    session,
                    [
                        "#amount_editor",
                        "#username",
                        "#password",
                        "#role",
                        "#login_btn",
                        "#status",
                    ],
                )
                amount_handle = handles_by_target["#amount_editor"]
                username_handle = handles_by_target["#username"]
                password_handle = handles_by_target["#password"]
                role_handle = handles_by_target["#role"]
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
                    "input",
                    {"target": username_handle, "text": "admin"},
                )
                await _call_tool(
                    session,
                    "input",
                    {"target": password_handle, "text": "secret123"},
                )
                username_value = await _call_tool(session, "inspect", {"target": username_handle})
                assert username_value["value"] == "admin"

                await _call_tool(
                    session,
                    "choose",
                    {"target": role_handle, "label": "Admin"},
                )
                login_result = await _call_tool(
                    session,
                    "click",
                    {"target": login_handle, "include_snapshot": True},
                )
                print(f"Login click snapshot: {login_result['snapshot']}")

                await _call_tool(session, "wait", {"target": status_handle, "condition": "text_contains", "expected": "Logged in as admin", "timeout": 5.0})
                status_text = await _call_tool(session, "inspect", {"target": status_handle})
                assert "Logged in as admin" in status_text["text"]
                assert "amount=88.50" in status_text["text"]

                status = await _call_tool(
                    session,
                    "snapshot",
                    {"target": status_handle, "depth": 0},
                )
                print(f"Status snapshot: {status['snapshot']}")

                screenshot = await _call_tool(
                    session,
                    "screenshot",
                    {"path": str(screenshot_path)},
                )
                print(f"Screenshot: {screenshot}")

                await _close_session(session)
                print("C++ stable-handle flow completed")
    finally:
        demo_process.terminate()
        try:
            demo_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            demo_process.kill()
            demo_process.wait(timeout=5)


if __name__ == "__main__":
    asyncio.run(main())