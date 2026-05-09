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

from examples.test_mcp_demo import (
    _attach_session,
    _call_tool,
    _close_session,
    _discover_widget_handles,
    _list_windows,
    _project_root,
    _python_path_env,
    _select_window,
)


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

                await _attach_session(session, port=DEMO_PORT, timeout=60.0)

                main_handles = await _discover_widget_handles(
                    session,
                    ["#amount_editor", "#review_btn", "#review_status", "#status"],
                )
                amount_handle = main_handles["#amount_editor"]
                review_handle = main_handles["#review_btn"]
                review_status_handle = main_handles["#review_status"]
                status_handle = main_handles["#status"]

                await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": amount_handle,
                        "method": "setCurrency",
                        "args": {"code": "CNY"},
                    },
                )
                await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": amount_handle,
                        "method": "setAmount",
                        "args": {"value": "66.50"},
                    },
                )

                before_windows = await _list_windows(session)
                assert len(before_windows) == 1

                await _call_tool(session, "click", {"target": review_handle})

                dialog_windows = await _list_windows(session)
                print(f"Windows after dialog open: {dialog_windows}")
                assert len(dialog_windows) == 2
                assert any("Payment Review" in window["title"] for window in dialog_windows)

                await _select_window(session, index=1)

                dialog_snapshot = await _call_tool(session, "snapshot", {"depth": 12})
                print(f"Dialog scoped snapshot: {dialog_snapshot['snapshot']}")
                assert "Payment Review" in dialog_snapshot["snapshot"]
                assert "QPlaywright Demo App" not in dialog_snapshot["snapshot"]

                dialog_handles = await _discover_widget_handles(
                    session,
                    [
                        "#approval_code",
                        "#review_risk",
                        "#review_escalate",
                        "#review_notes_dialog",
                        "#approve_review_btn",
                    ],
                )
                approval_code_handle = dialog_handles["#approval_code"]
                review_risk_handle = dialog_handles["#review_risk"]
                review_escalate_handle = dialog_handles["#review_escalate"]
                review_notes_handle = dialog_handles["#review_notes_dialog"]
                approve_handle = dialog_handles["#approve_review_btn"]

                dialog_root = await _call_tool(session, "inspect", {"target": "role=dialog"})
                print(f"Dialog root: {dialog_root}")
                assert dialog_root["exists"] is True

                dialog_summary = await _call_tool(session, "inspect", {"target": "#dialog_payment_summary"})
                print(f"Dialog summary: {dialog_summary['text']}")
                assert "CNY 66.50 precision=2 adjustments=on" in dialog_summary["text"]

                await _call_tool(
                    session,
                    "input",
                    {
                        "target": approval_code_handle,
                        "text": "APR-CNY-001",
                    },
                )
                await _call_tool(
                    session,
                    "choose",
                    {
                        "target": review_risk_handle,
                        "label": "High",
                    },
                )
                await _call_tool(
                    session,
                    "set_checked",
                    {
                        "target": review_escalate_handle,
                        "checked": True,
                    },
                )
                await _call_tool(
                    session,
                    "input",
                    {
                        "target": review_notes_handle,
                        "text": "Escalated because amount exceeds manual threshold.",
                    },
                )
                await _call_tool(
                    session,
                    "click",
                    {"target": approve_handle},
                )

                after_windows = await _list_windows(session)
                print(f"Windows after dialog close: {after_windows}")
                assert len(after_windows) == 1

                await _select_window(session, index=0)

                review_status = await _call_tool(session, "inspect", {"target": review_status_handle})
                print(f"Review status: {review_status['text']}")
                assert "approved" in review_status["text"]
                assert "APR-CNY-001" in review_status["text"]
                assert "High" in review_status["text"]

                status = await _call_tool(session, "inspect", {"target": status_handle})
                print(f"Main status: {status['text']}")
                assert "Review approved" in status["text"]
                assert "CNY 66.50 precision=2 adjustments=on" in status["text"]

                await _close_session(session)
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