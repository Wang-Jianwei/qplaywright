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


DEMO_PORT = 29876


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


async def _attach_session(
    session: ClientSession,
    *,
    port: int,
    timeout: float = 10.0,
    host: str = "127.0.0.1",
) -> dict[str, Any]:
    return await _call_tool(
        session,
        "session",
        {"action": "attach", "host": host, "port": port, "timeout": timeout},
    )


async def _close_session(session: ClientSession) -> dict[str, Any]:
    return await _call_tool(session, "session", {"action": "close"})


async def _list_windows(session: ClientSession) -> list[dict[str, Any]]:
    result = await _call_tool(session, "window", {"action": "list"})
    return result["windows"]


async def _select_window(
    session: ClientSession,
    *,
    index: int | None = None,
    wid: int | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    arguments: dict[str, Any] = {"action": "select"}
    if index is not None:
        arguments["index"] = index
    if wid is not None:
        arguments["wid"] = wid
    if title is not None:
        arguments["title"] = title
    return await _call_tool(session, "window", arguments)


def _refs_by_target(snapshot: dict[str, Any]) -> dict[str, str]:
    return {
        entry["target"]: entry["ref"]
        for entry in snapshot.get("refs", [])
        if entry.get("target") and entry.get("ref")
    }


async def main() -> None:
    root = _project_root()
    env = _python_path_env(root)
    env["QPLAYWRIGHT_PORT"] = str(DEMO_PORT)
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

                connect_result = await _attach_session(session, port=DEMO_PORT, timeout=10.0)
                print(f"Connected: {connect_result['active_window']}")

                windows = await _list_windows(session)
                print(f"Windows: {windows}")

                tree = await _call_tool(session, "inspect", {"depth": 3})
                print(f"Widget tree roots: {len(tree['tree'])}")

                methods = await _call_tool(session, "inspect", {"target": "#amount_editor", "include_methods": True})
                method_names = [entry["name"] for entry in methods["methods"]]
                print(f"Custom methods: {method_names}")
                assert method_names == [
                    "amount",
                    "setAmount",
                    "clearAmount",
                    "currency",
                    "setCurrency",
                    "availableCurrencies",
                    "precision",
                    "setPrecision",
                    "adjustmentsEnabled",
                    "setAdjustmentsEnabled",
                    "applyDelta",
                    "summary",
                    "snapshot",
                ]

                await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": "#amount_editor",
                        "method": "setAmount",
                        "args": {"value": "123.45"},
                    },
                )
                await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": "#amount_editor",
                        "method": "setCurrency",
                        "args": {"code": "EUR"},
                    },
                )
                await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": "#amount_editor",
                        "method": "setPrecision",
                        "args": {"digits": 3},
                    },
                )
                await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": "#amount_editor",
                        "method": "applyDelta",
                        "args": {"delta": 1.425},
                    },
                )

                amount_result = await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": "#amount_editor",
                        "method": "amount",
                        "args": {},
                    },
                )
                print(f"Amount result: {amount_result['result']}")
                assert amount_result["result"]["value"] == "124.875"

                currency_result = await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": "#amount_editor",
                        "method": "currency",
                        "args": {},
                    },
                )
                print(f"Currency result: {currency_result['result']}")
                assert currency_result["result"]["value"] == "EUR"

                available_result = await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": "#amount_editor",
                        "method": "availableCurrencies",
                        "args": {},
                    },
                )
                print(f"Available currencies: {available_result['result']}")
                assert available_result["result"]["value"] == ["USD", "EUR", "CNY", "JPY"]

                summary_result = await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": "#amount_editor",
                        "method": "summary",
                        "args": {},
                    },
                )
                print(f"Summary result: {summary_result['result']}")
                assert summary_result["result"]["value"] == "EUR 124.875 precision=3 adjustments=on"

                snapshot_result = await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": "#amount_editor",
                        "method": "snapshot",
                        "args": {},
                    },
                )
                print(f"Snapshot result: {snapshot_result['result']}")
                assert snapshot_result["result"]["value"] == {
                    "amount": "124.875",
                    "currency": "EUR",
                    "precision": 3,
                    "adjustmentsEnabled": True,
                    "summary": "EUR 124.875 precision=3 adjustments=on",
                }

                await _call_tool(
                    session,
                    "input",
                    {"target": "#username", "text": "admin"},
                )
                await _call_tool(
                    session,
                    "input",
                    {"target": "#password", "text": "secret123"},
                )
                await _call_tool(
                    session,
                    "set_checked",
                    {"target": "#remember", "checked": True},
                )
                await _call_tool(
                    session,
                    "choose",
                    {"target": "#role", "label": "Admin"},
                )
                await _call_tool(
                    session,
                    "choose",
                    {"target": "#environment", "label": "Production"},
                )
                await _call_tool(
                    session,
                    "set_checked",
                    {"target": "#notify", "checked": True},
                )
                await _call_tool(
                    session,
                    "input",
                    {
                        "target": "#notes",
                        "text": "Escalate to finance reviewer",
                    },
                )
                await _call_tool(
                    session,
                    "click",
                    {"target": "#login_btn"},
                )

                status = await _call_tool(session, "inspect", {"target": "#status"})
                print(f"Status after login: {status['text']}")
                assert "Logged in as admin" in status["text"]
                assert "payment=EUR 124.875 precision=3 adjustments=on" in status["text"]

                summary = await _call_tool(session, "inspect", {"target": "#summary"})
                print(f"Summary after login: {summary['text']}")
                assert "last-login" in summary["text"]
                assert "payment=EUR 124.875 precision=3 adjustments=on" in summary["text"]

                await _call_tool(
                    session,
                    "click",
                    {"target": "#clear_btn"},
                )
                cleared = await _call_tool(session, "inspect", {"target": "#status"})
                print(f"Status after clear: {cleared['text']}")
                assert "cleared" in cleared["text"].lower()

                cleared_amount = await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": "#amount_editor",
                        "method": "amount",
                        "args": {},
                    },
                )
                print(f"Amount after clear: {cleared_amount['result']}")
                assert cleared_amount["result"]["value"] == "0.000"

                screenshot = await _call_tool(
                    session,
                    "screenshot",
                    {"path": str(screenshot_path)},
                )
                print(f"Screenshot: {screenshot}")

                await _close_session(session)
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