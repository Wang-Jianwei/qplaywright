"""Manual end-to-end test for qplaywright MCP support.

This script starts the Python demo app, launches the qplaywright MCP server as a
stdio subprocess, then drives the UI through MCP tool calls.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _python_path_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(root) if not existing else str(root) + os.pathsep + existing
    return env


def _structured(tool_result: Any) -> Any:
    structured = getattr(tool_result, "structuredContent", None)
    if structured is not None:
        return structured

    parsed_blocks: list[Any] = []
    for content in getattr(tool_result, "content", []):
        text = getattr(content, "text", None)
        if text is None:
            continue
        try:
            parsed_blocks.append(json.loads(text))
        except json.JSONDecodeError:
            parsed_blocks.append({"text": text})

    if len(parsed_blocks) == 1:
        return parsed_blocks[0]
    if parsed_blocks:
        return parsed_blocks

    raise RuntimeError(f"Tool did not return structured content: {tool_result!r}")


async def _call_tool(session: ClientSession, name: str, arguments: dict[str, Any]) -> Any:
    result = await session.call_tool(name, arguments=arguments)
    if result.isError:
        raise RuntimeError(f"Tool {name!r} failed: {result}")
    return _structured(result)


async def main() -> None:
    root = _project_root()
    env = _python_path_env(root)
    screenshot_path = root / "demo_mcp_screenshot.png"

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

                connect_result = await _call_tool(
                    session,
                    "connect",
                    {"name": "demo", "port": 19876, "timeout": 10.0},
                )
                print(f"Connected: {connect_result['windows']}")

                windows = await _call_tool(session, "list_windows", {"connection": "demo"})
                print(f"Windows: {windows}")

                tree = await _call_tool(
                    session,
                    "widget_tree",
                    {"connection": "demo", "max_depth": 3},
                )
                print(f"Widget tree roots: {len(tree)}")

                methods = await _call_tool(
                    session,
                    "get_widget_methods",
                    {"connection": "demo", "selector": "#amount_editor"},
                )
                method_names = [entry["name"] for entry in methods["methods"]]
                print(f"Custom methods: {method_names}")
                assert method_names == ["amount", "setAmount", "clearAmount"]

                await _call_tool(
                    session,
                    "invoke_widget_method",
                    {
                        "connection": "demo",
                        "selector": "#amount_editor",
                        "method_name": "setAmount",
                        "args": {"value": "123.45"},
                    },
                )

                amount_result = await _call_tool(
                    session,
                    "invoke_widget_method",
                    {
                        "connection": "demo",
                        "selector": "#amount_editor",
                        "method_name": "amount",
                        "args": {},
                    },
                )
                print(f"Amount result: {amount_result['result']}")
                assert amount_result["result"]["value"] == "123.45"

                await _call_tool(
                    session,
                    "fill",
                    {"connection": "demo", "selector": "#username", "value": "admin"},
                )
                await _call_tool(
                    session,
                    "fill",
                    {"connection": "demo", "selector": "#password", "value": "secret123"},
                )
                await _call_tool(
                    session,
                    "set_checked",
                    {"connection": "demo", "selector": "#remember", "checked": True},
                )
                await _call_tool(
                    session,
                    "select_option",
                    {"connection": "demo", "selector": "#role", "label": "Admin"},
                )
                await _call_tool(
                    session,
                    "select_option",
                    {"connection": "demo", "selector": "#environment", "label": "Production"},
                )
                await _call_tool(
                    session,
                    "set_checked",
                    {"connection": "demo", "selector": "#notify", "checked": True},
                )
                await _call_tool(
                    session,
                    "fill",
                    {
                        "connection": "demo",
                        "selector": "#notes",
                        "value": "Escalate to finance reviewer",
                    },
                )
                await _call_tool(
                    session,
                    "click",
                    {
                        "connection": "demo",
                        "selector": "role=button",
                        "has_text": "Login",
                    },
                )

                status = await _call_tool(
                    session,
                    "inspect_widget",
                    {"connection": "demo", "selector": "#status"},
                )
                print(f"Status after login: {status['text']}")
                assert "Logged in as admin" in status["text"]
                assert "amount=123.45" in status["text"]

                summary = await _call_tool(
                    session,
                    "inspect_widget",
                    {"connection": "demo", "selector": "#summary"},
                )
                print(f"Summary after login: {summary['text']}")
                assert "last-login" in summary["text"]
                assert "amount=123.45" in summary["text"]

                await _call_tool(
                    session,
                    "click",
                    {
                        "connection": "demo",
                        "selector": "role=button",
                        "has_text": "Clear Log",
                    },
                )
                cleared = await _call_tool(
                    session,
                    "inspect_widget",
                    {"connection": "demo", "selector": "#status"},
                )
                print(f"Status after clear: {cleared['text']}")
                assert "cleared" in cleared["text"].lower()

                cleared_amount = await _call_tool(
                    session,
                    "invoke_widget_method",
                    {
                        "connection": "demo",
                        "selector": "#amount_editor",
                        "method_name": "amount",
                        "args": {},
                    },
                )
                print(f"Amount after clear: {cleared_amount['result']}")
                assert cleared_amount["result"]["value"] == "0.00"

                screenshot = await _call_tool(
                    session,
                    "screenshot",
                    {"connection": "demo", "path": str(screenshot_path)},
                )
                print(f"Screenshot: {screenshot}")

                await _call_tool(session, "disconnect", {"name": "demo"})
                print("MCP demo flow completed")
    finally:
        demo_process.terminate()
        try:
            demo_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            demo_process.kill()
            demo_process.wait(timeout=5)


if __name__ == "__main__":
    asyncio.run(main())