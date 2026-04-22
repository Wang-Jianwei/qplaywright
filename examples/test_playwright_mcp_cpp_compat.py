"""Manual end-to-end test for playwright-mcp style tools against the C++ demo."""

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
from examples.test_mcp_demo import _call_tool, _project_root


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

                await _call_tool(session, "connect", {"name": "cpp-demo", "port": 19876, "timeout": 10.0})

                await _call_tool(
                    session,
                    "invoke_widget_method",
                    {
                        "connection": "cpp-demo",
                        "selector": "#amount_editor",
                        "method_name": "setAmount",
                        "args": {"value": "88.50"},
                    },
                )

                tabs = await _call_tool(session, "browser_tabs", {"action": "list", "connection": "cpp-demo"})
                print(f"Tabs: {tabs['result']}")

                snapshot = await _call_tool(session, "browser_snapshot", {"connection": "cpp-demo", "depth": 3})
                print(snapshot["snapshot"])

                refs_by_target = {
                    entry["target"]: entry["ref"]
                    for entry in snapshot["refs"]
                    if entry.get("target") and entry.get("ref")
                }

                username_ref = refs_by_target["#username"]
                password_ref = refs_by_target["#password"]
                role_ref = refs_by_target["#role"]
                login_ref = refs_by_target["#login_btn"]
                status_ref = refs_by_target["#status"]

                await _call_tool(
                    session,
                    "browser_fill_form",
                    {
                        "connection": "cpp-demo",
                        "fields": [
                            {"target": username_ref, "value": "admin"},
                            {"target": password_ref, "value": "secret123"},
                        ],
                    },
                )
                await _call_tool(
                    session,
                    "browser_verify_value",
                    {
                        "connection": "cpp-demo",
                        "type": "textbox",
                        "element": "Username field",
                        "target": username_ref,
                        "value": "admin",
                    },
                )
                await _call_tool(
                    session,
                    "browser_select_option",
                    {"connection": "cpp-demo", "target": role_ref, "values": ["Admin"]},
                )
                login_result = await _call_tool(
                    session,
                    "browser_click",
                    {"connection": "cpp-demo", "target": login_ref},
                )
                print(f"Login click snapshot: {login_result['snapshot']}")

                await _call_tool(
                    session,
                    "browser_wait_for",
                    {"connection": "cpp-demo", "text": "Logged in as admin", "timeout": 5.0},
                )
                await _call_tool(
                    session,
                    "browser_verify_text_visible",
                    {"connection": "cpp-demo", "text": "amount=88.50"},
                )
                await _call_tool(
                    session,
                    "browser_verify_element_visible",
                    {
                        "connection": "cpp-demo",
                        "role": "button",
                        "accessibleName": "Login",
                    },
                )

                status = await _call_tool(
                    session,
                    "browser_snapshot",
                    {"connection": "cpp-demo", "target": status_ref, "depth": 0},
                )
                print(f"Status snapshot: {status['snapshot']}")

                screenshot = await _call_tool(
                    session,
                    "browser_take_screenshot",
                    {"connection": "cpp-demo", "filename": str(screenshot_path)},
                )
                print(f"Screenshot: {screenshot}")

                await _call_tool(session, "disconnect", {"name": "cpp-demo"})
                print("C++ playwright-style compatibility flow completed")
    finally:
        demo_process.terminate()
        try:
            demo_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            demo_process.kill()
            demo_process.wait(timeout=5)


if __name__ == "__main__":
    asyncio.run(main())