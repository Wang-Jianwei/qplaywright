"""Manual end-to-end test for wheel scrolling through qplaywright MCP."""

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


DEMO_PORT = 29878


def _scroll_value(text: str) -> int:
    prefix = "value="
    start = text.index(prefix) + len(prefix)
    end = text.index(" ", start)
    return int(text[start:end])


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

                before = await _call_tool(
                    session,
                    "inspect_widget",
                    {"connection": "demo", "selector": "#scroll_status"},
                )
                print(f"Before scroll: {before['text']}")
                before_value = _scroll_value(before["text"])

                await _call_tool(
                    session,
                    "scroll",
                    {
                        "connection": "demo",
                        "selector": "#scroll_list",
                        "delta_x": 0,
                        "delta_y": -240,
                    },
                )

                after_down = await _call_tool(
                    session,
                    "inspect_widget",
                    {"connection": "demo", "selector": "#scroll_status"},
                )
                print(f"After downward scroll: {after_down['text']}")
                down_value = _scroll_value(after_down["text"])
                assert down_value > before_value

                await _call_tool(
                    session,
                    "scroll",
                    {
                        "connection": "demo",
                        "selector": "#scroll_list",
                        "delta_x": 0,
                        "delta_y": 240,
                    },
                )

                after_up = await _call_tool(
                    session,
                    "inspect_widget",
                    {"connection": "demo", "selector": "#scroll_status"},
                )
                print(f"After upward scroll: {after_up['text']}")
                up_value = _scroll_value(after_up["text"])
                assert up_value < down_value

                await _call_tool(session, "disconnect", {"name": "demo"})
                print("Scroll MCP demo flow completed")
    finally:
        demo_process.terminate()
        try:
            demo_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            demo_process.kill()
            demo_process.wait(timeout=5)


if __name__ == "__main__":
    asyncio.run(main())