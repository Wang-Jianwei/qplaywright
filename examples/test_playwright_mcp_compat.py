"""Manual end-to-end test for a snapshot-ref driven MCP flow."""

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
    _list_windows,
    _project_root,
    _python_path_env,
    _refs_by_target,
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

                await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": "#amount_editor",
                        "method": "setAmount",
                        "args": {"value": "88.50"},
                    },
                )
                await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": "#amount_editor",
                        "method": "setCurrency",
                        "args": {"code": "JPY"},
                    },
                )
                await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": "#amount_editor",
                        "method": "setPrecision",
                        "args": {"digits": 1},
                    },
                )
                await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": "#amount_editor",
                        "method": "applyDelta",
                        "args": {"delta": 2.4},
                    },
                )

                tabs = await _list_windows(session)
                print(f"Tabs: {tabs}")

                snapshot = await _call_tool(session, "snapshot", {"depth": 3})
                print(snapshot["snapshot"])

                refs_by_target = _refs_by_target(snapshot)
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
                    "input",
                    {"target": username_ref, "text": "admin"},
                )
                await _call_tool(
                    session,
                    "input",
                    {"target": password_ref, "text": "secret123"},
                )
                await _call_tool(
                    session,
                    "input",
                    {"target": notes_ref, "text": "Reviewed by snapshot ref flow"},
                )

                username_value = await _call_tool(session, "inspect", {"target": username_ref})
                assert username_value["value"] == "admin"

                await _call_tool(
                    session,
                    "choose",
                    {"target": role_ref, "label": "Admin"},
                )
                await _call_tool(
                    session,
                    "choose",
                    {"target": environment_ref, "label": "Production"},
                )
                await _call_tool(
                    session,
                    "click",
                    {"target": remember_ref},
                )
                await _call_tool(session, "click", {"target": notify_ref})
                login_result = await _call_tool(
                    session,
                    "click",
                    {"target": login_ref, "include_snapshot": True},
                )
                print(f"Login click snapshot: {login_result['snapshot']}")

                status_text = await _call_tool(session, "inspect", {"target": "#status"})
                assert "Logged in as admin" in status_text["text"]
                assert "payment=JPY 90.9 precision=1 adjustments=on" in status_text["text"]

                login_button = await _call_tool(session, "inspect", {"target": "#login_btn"})
                assert login_button["exists"] is True

                status_snapshot = await _call_tool(session, "snapshot", {"depth": 3})
                status_ref = _refs_by_target(status_snapshot)["#status"]

                status = await _call_tool(session, "snapshot", {"target": status_ref, "depth": 0})
                print(f"Status snapshot: {status['snapshot']}")
                assert "payment=JPY 90.9 precision=1 adjustments=on" in status["snapshot"]

                screenshot = await _call_tool(
                    session,
                    "screenshot",
                    {"path": str(screenshot_path)},
                )
                print(f"Screenshot: {screenshot}")

                await _close_session(session)
                print("Snapshot-ref flow completed")
    finally:
        demo_process.terminate()
        try:
            demo_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            demo_process.kill()
            demo_process.wait(timeout=5)


if __name__ == "__main__":
    asyncio.run(main())