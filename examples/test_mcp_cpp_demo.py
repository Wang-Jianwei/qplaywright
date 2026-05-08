"""Manual end-to-end test for the C++ demo through qplaywright MCP tools.

This script expects the C++ demo to have been built already. It launches the
demo executable, connects through qplaywright MCP, then exercises the custom
widget method metadata and invoke flow.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from examples.test_mcp_demo import _attach_session, _call_tool, _close_session, _project_root, _python_path_env


def _find_snapshot_node(tree: Any, *, object_name: str) -> dict[str, Any] | None:
    if isinstance(tree, dict):
        if tree.get("objectName") == object_name:
            return tree
        for child in tree.get("children", []):
            match = _find_snapshot_node(child, object_name=object_name)
            if match is not None:
                return match
        return None

    if isinstance(tree, list):
        for entry in tree:
            match = _find_snapshot_node(entry, object_name=object_name)
            if match is not None:
                return match
    return None


def _find_cpp_demo_executable(root: Path) -> Path:
    candidates = [
        root / "examples" / "cpp_demo" / "build_verify" / "demo_app.exe",
        root / "examples" / "cpp_demo" / "build" / "demo_app.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Could not find demo_app.exe. Build the C++ demo first in examples/cpp_demo/build or examples/cpp_demo/build_verify."
    )


def _cpp_demo_env(root: Path, runtime_dir: Path | None = None) -> dict[str, str]:
    env = _python_path_env(root)
    runtime_candidates = []
    if runtime_dir is not None:
        runtime_candidates.append(runtime_dir)
    runtime_candidates.extend(
        [
            root / "examples" / "cpp_demo" / "build_verify",
            root / "examples" / "cpp_demo" / "build",
        ]
    )

    for candidate in runtime_candidates:
        if not candidate.exists():
            continue
        env["PATH"] = str(candidate) + os.pathsep + env.get("PATH", "")
        platforms_dir = candidate / "platforms"
        if platforms_dir.exists():
            env["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platforms_dir)
        break
    return env


async def main() -> None:
    root = _project_root()
    executable = _find_cpp_demo_executable(root)
    env = _cpp_demo_env(root, executable.parent)

    demo_process = subprocess.Popen([str(executable)], cwd=executable.parent, env=env)

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "qplaywright.mcp_server"],
        env=env,
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                await _attach_session(session, port=19876, timeout=60.0)

                tree = await _call_tool(session, "inspect", {"depth": 3})
                tabs_node = _find_snapshot_node(tree.get("tree", []), object_name="main_tabs")
                assert tabs_node is not None
                print(f"Tabs snapshot node: {tabs_node}")
                assert tabs_node["itemView"] == {"kind": "tab", "discoverableBy": "inspect_items"}

                tab_items = await _call_tool(session, "inspect_items", {"owner": "#main_tabs", "max_items": 10})
                print(f"Tab items: {tab_items['items']}")
                assert tab_items["kind"] == "tab"
                assert [entry["text"] for entry in tab_items["items"]] == ["Login", "Data", "Settings"]
                assert tab_items["items"][0]["selected"] is True

                await _call_tool(
                    session,
                    "click",
                    {"target": {"owner": "#main_tabs", "item": {"kind": "tab_item", "label": "Data"}}},
                )

                data_button = await _call_tool(session, "inspect", {"target": "#data_refresh_btn"})
                print(f"Data button after tab switch: {data_button}")
                assert data_button["exists"] is True
                assert data_button["is_visible"] is True

                await _call_tool(session, "click", {"target": "#data_refresh_btn"})

                data_label = await _call_tool(session, "inspect", {"target": "#data_panel_label"})
                print(f"Data label after refresh: {data_label.get('text')}")
                assert data_label["text"] == "Data tab refreshed"

                status_after_tab = await _call_tool(session, "inspect", {"target": "#status"})
                assert status_after_tab["text"] == "Status: Data tab refreshed"

                updated_tab_items = await _call_tool(session, "inspect_items", {"owner": "#main_tabs", "max_items": 10})
                assert updated_tab_items["items"][1]["selected"] is True

                await _call_tool(
                    session,
                    "click",
                    {"target": {"owner": "#main_tabs", "item": {"kind": "tab_item", "label": "Login"}}},
                )

                methods = await _call_tool(session, "inspect", {"target": "#amount_editor", "include_methods": True})
                method_names = [entry["name"] for entry in methods["methods"]]
                print(f"Custom methods: {method_names}")
                assert method_names == ["amount", "setAmount", "clearAmount"]

                properties = await _call_tool(
                    session,
                    "inspect",
                    {"target": "#amount_editor", "include_properties": True},
                )
                print(f"Initial properties: {properties['properties']}")
                assert properties["properties"]["semanticRole"] == "amount-input"
                assert properties["properties"]["amountValue"] == "0.00"
                assert properties["properties"]["myText"] == "Requested amount editor: 0.00"

                set_result = await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": "#amount_editor",
                        "method": "setAmount",
                        "args": {"value": "123.45"},
                    },
                )
                print(f"setAmount result: {set_result['result']}")
                assert set_result["result"]["ok"] is True

                amount_result = await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": "#amount_editor",
                        "method": "amount",
                        "args": {},
                    },
                )
                print(f"amount result: {amount_result['result']}")
                assert amount_result["result"] == {
                    "ok": True,
                    "value": "123.45",
                    "errorCode": 0,
                    "errorMessage": "",
                }

                updated_properties = await _call_tool(
                    session,
                    "inspect",
                    {"target": "#amount_editor", "include_properties": True},
                )
                print(f"Updated properties: {updated_properties['properties']}")
                assert updated_properties["properties"]["amountValue"] == "123.45"
                assert updated_properties["properties"]["myText"] == "Requested amount editor: 123.45"

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
                    "choose",
                    {"target": "#role", "label": "Admin"},
                )
                await _call_tool(
                    session,
                    "click",
                    {"target": "#login_btn"},
                )

                status = await _call_tool(session, "inspect", {"target": "#status"})
                print(f"Status after login: {status['text']}")
                assert "amount=123.45" in status["text"]

                clear_result = await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": "#amount_editor",
                        "method": "clearAmount",
                        "args": {},
                    },
                )
                print(f"clearAmount result: {clear_result['result']}")
                assert clear_result["result"]["ok"] is True

                reset_amount = await _call_tool(
                    session,
                    "invoke",
                    {
                        "target": "#amount_editor",
                        "method": "amount",
                        "args": {},
                    },
                )
                assert reset_amount["result"]["value"] == "0.00"

                await _close_session(session)
                print("C++ MCP demo flow completed")
    finally:
        demo_process.terminate()
        try:
            demo_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            demo_process.kill()
            demo_process.wait(timeout=5)


if __name__ == "__main__":
    asyncio.run(main())