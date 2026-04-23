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

from examples.test_mcp_demo import _attach_session, _call_tool, _close_session, _project_root, _python_path_env


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
        command="d:/workdir/wangjianwei/projects/bot/qt-use/.venv/Scripts/python.exe",
        args=["-m", "qplaywright.mcp_server"],
        env=env,
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                await _attach_session(session, port=19876, timeout=30.0)

                methods = await _call_tool(session, "inspect", {"target": "#amount_editor", "include_methods": True})
                method_names = [entry["name"] for entry in methods["methods"]]
                print(f"Custom methods: {method_names}")
                assert method_names == ["amount", "setAmount", "clearAmount"]

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