"""Manual end-to-end test for a real popped QDialog through qplaywright MCP."""

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


DEMO_PORT = 29877


async def main() -> None:
    root = _project_root()
    env = _python_path_env(root)
    env["QPLAYWRIGHT_PORT"] = str(DEMO_PORT)

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
                        "method_name": "setCurrency",
                        "args": {"code": "CNY"},
                    },
                )
                await _call_tool(
                    session,
                    "invoke_widget_method",
                    {
                        "connection": "demo",
                        "selector": "#amount_editor",
                        "method_name": "setAmount",
                        "args": {"value": "66.50"},
                    },
                )

                before_windows = await _call_tool(session, "list_windows", {"connection": "demo"})
                before_windows = before_windows["result"] if isinstance(before_windows, dict) else before_windows
                assert len(before_windows) == 1

                await _call_tool(session, "click", {"connection": "demo", "selector": "#review_btn"})

                dialog_windows = await _call_tool(session, "list_windows", {"connection": "demo"})
                dialog_windows = dialog_windows["result"] if isinstance(dialog_windows, dict) else dialog_windows
                print(f"Windows after dialog open: {dialog_windows}")
                assert len(dialog_windows) == 2
                assert any("Payment Review" in window["title"] for window in dialog_windows)

                dialog_root = await _call_tool(
                    session,
                    "inspect_widget",
                    {
                        "connection": "demo",
                        "selector": "role=dialog",
                        "window_index": 1,
                    },
                )
                print(f"Dialog root: {dialog_root}")
                assert dialog_root["exists"] is True

                dialog_summary = await _call_tool(
                    session,
                    "inspect_widget",
                    {
                        "connection": "demo",
                        "selector": "#dialog_payment_summary",
                        "window_index": 1,
                    },
                )
                print(f"Dialog summary: {dialog_summary['text']}")
                assert "CNY 66.50 precision=2 adjustments=on" in dialog_summary["text"]

                await _call_tool(
                    session,
                    "fill",
                    {
                        "connection": "demo",
                        "selector": "#approval_code",
                        "window_index": 1,
                        "value": "APR-CNY-001",
                    },
                )
                await _call_tool(
                    session,
                    "select_option",
                    {
                        "connection": "demo",
                        "selector": "#review_risk",
                        "window_index": 1,
                        "label": "High",
                    },
                )
                await _call_tool(
                    session,
                    "set_checked",
                    {
                        "connection": "demo",
                        "selector": "#review_escalate",
                        "window_index": 1,
                        "checked": True,
                    },
                )
                await _call_tool(
                    session,
                    "fill",
                    {
                        "connection": "demo",
                        "selector": "#review_notes_dialog",
                        "window_index": 1,
                        "value": "Escalated because amount exceeds manual threshold.",
                    },
                )
                await _call_tool(
                    session,
                    "click",
                    {
                        "connection": "demo",
                        "selector": "#approve_review_btn",
                        "window_index": 1,
                    },
                )

                after_windows = await _call_tool(session, "list_windows", {"connection": "demo"})
                after_windows = after_windows["result"] if isinstance(after_windows, dict) else after_windows
                print(f"Windows after dialog close: {after_windows}")
                assert len(after_windows) == 1

                review_status = await _call_tool(
                    session,
                    "inspect_widget",
                    {"connection": "demo", "selector": "#review_status"},
                )
                print(f"Review status: {review_status['text']}")
                assert "approved" in review_status["text"]
                assert "APR-CNY-001" in review_status["text"]
                assert "High" in review_status["text"]

                status = await _call_tool(
                    session,
                    "inspect_widget",
                    {"connection": "demo", "selector": "#status"},
                )
                print(f"Main status: {status['text']}")
                assert "Review approved" in status["text"]
                assert "CNY 66.50 precision=2 adjustments=on" in status["text"]

                await _call_tool(session, "disconnect", {"name": "demo"})
                print("Dialog MCP demo flow completed")
    finally:
        demo_process.terminate()
        try:
            demo_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            demo_process.kill()
            demo_process.wait(timeout=5)


if __name__ == "__main__":
    asyncio.run(main())