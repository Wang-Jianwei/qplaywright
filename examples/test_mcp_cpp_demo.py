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

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from examples.test_mcp_demo import _call_tool, _project_root, _python_path_env


def _find_cpp_demo_executable(root: Path) -> Path:
    candidates = [
        root / "agent_cpp" / "build_validate" / "demo_app.exe",
        root / "agent_cpp" / "build" / "demo_app.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Could not find demo_app.exe. Build the C++ demo first in agent_cpp/build or agent_cpp/build_validate."
    )


def _cpp_demo_env(root: Path) -> dict[str, str]:
    env = _python_path_env(root)
    runtime_dir = root / "agent_cpp" / "build"
    if runtime_dir.exists():
        env["PATH"] = str(runtime_dir) + os.pathsep + env.get("PATH", "")
        platforms_dir = runtime_dir / "platforms"
        if platforms_dir.exists():
            env["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platforms_dir)
    return env


async def main() -> None:
    root = _project_root()
    env = _cpp_demo_env(root)
    executable = _find_cpp_demo_executable(root)

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

                methods = await _call_tool(
                    session,
                    "get_widget_methods",
                    {"connection": "cpp-demo", "selector": "#amount_editor"},
                )
                method_names = [entry["name"] for entry in methods["methods"]]
                print(f"Custom methods: {method_names}")
                assert method_names == ["amount", "setAmount", "clearAmount"]

                set_result = await _call_tool(
                    session,
                    "invoke_widget_method",
                    {
                        "connection": "cpp-demo",
                        "selector": "#amount_editor",
                        "method_name": "setAmount",
                        "args": {"value": "123.45"},
                    },
                )
                print(f"setAmount result: {set_result['result']}")
                assert set_result["result"]["ok"] is True

                amount_result = await _call_tool(
                    session,
                    "invoke_widget_method",
                    {
                        "connection": "cpp-demo",
                        "selector": "#amount_editor",
                        "method_name": "amount",
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

                await _call_tool(
                    session,
                    "fill",
                    {"connection": "cpp-demo", "selector": "#username", "value": "admin"},
                )
                await _call_tool(
                    session,
                    "fill",
                    {"connection": "cpp-demo", "selector": "#password", "value": "secret123"},
                )
                await _call_tool(
                    session,
                    "select_option",
                    {"connection": "cpp-demo", "selector": "#role", "label": "Admin"},
                )
                await _call_tool(
                    session,
                    "click",
                    {"connection": "cpp-demo", "selector": "#login_btn"},
                )

                status = await _call_tool(
                    session,
                    "inspect_widget",
                    {"connection": "cpp-demo", "selector": "#status"},
                )
                print(f"Status after login: {status['text']}")
                assert "amount=123.45" in status["text"]

                clear_result = await _call_tool(
                    session,
                    "invoke_widget_method",
                    {
                        "connection": "cpp-demo",
                        "selector": "#amount_editor",
                        "method_name": "clearAmount",
                        "args": {},
                    },
                )
                print(f"clearAmount result: {clear_result['result']}")
                assert clear_result["result"]["ok"] is True

                reset_amount = await _call_tool(
                    session,
                    "invoke_widget_method",
                    {
                        "connection": "cpp-demo",
                        "selector": "#amount_editor",
                        "method_name": "amount",
                        "args": {},
                    },
                )
                assert reset_amount["result"]["value"] == "0.00"

                await _call_tool(session, "disconnect", {"name": "cpp-demo"})
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