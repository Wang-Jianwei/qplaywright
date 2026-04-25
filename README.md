# QPlaywright

QPlaywright is a Playwright-compatible automation library for Qt QWidget applications.

It has two sides:

- A Qt-side agent embedded in the target application.
- A Python client with Playwright-style APIs such as locator, click, fill, invoke, expect, and MCP integration.

The Python client and the embedded agent communicate over JSON Lines on TCP.

## Install

Basic client install:

```bash
pip install qplaywright
```

Install with MCP support:

```bash
pip install "qplaywright[mcp]"
```

From source:

```bash
pip install .
pip install ".[mcp]"
```

## What Gets Installed

The Python package includes:

- The sync client API.
- The Python Qt agent.
- The MCP server entrypoint.
- The C++ header-only Qt agent.

In the source tree, the C++ agent lives under `qplaywright/cpp`.
The demo application lives separately under `examples/cpp_demo`.

If you need the packaged C++ agent header path at runtime:

```python
import qplaywright

header_path = qplaywright.agent_header_path()
print(header_path)
```

## Quick Start

### Python Qt application

```python
from qplaywright.agent import start_agent

start_agent(port=19876, visual_feedback=True)
```

Call `start_agent()` after creating `QApplication` and before entering `app.exec()`.

### C++ Qt application

```cpp
#include "qplaywright_agent.h"

int main(int argc, char *argv[]) {
    QApplication app(argc, argv);
    QPlaywrightAgent::start(19876);
    return app.exec();
}
```

Build the bundled C++ demo from the source tree:

```bash
cd examples/cpp_demo
cmake -S . -B build -DCMAKE_PREFIX_PATH=<your-qt-path>
cmake --build build
```

### Python client

```python
from qplaywright import sync_qplaywright

with sync_qplaywright() as qp:
    app = qp.connect(port=19876, agent_name="GitHub Copilot")
    window = app.main_window()
    window.get_by_role("button", name="Submit").click()
```

When `visual_feedback` is enabled in the Qt agent and the client provides `agent_name`, the target window shows the current shared-agent overlay marker.

## MCP Server

Run the MCP server over stdio:

```bash
qplaywright-mcp
```

Or:

```bash
python -m qplaywright.mcp_server
```

Run the direct CLI / REPL when you want to keep issuing tool calls from one terminal session:

```bash
qplaywright-mcp cli
qplaywright> session {"action": "attach", "port": 19877}
qplaywright> window {"action": "list"}
qplaywright> snapshot {"depth": 4}
qplaywright> click {"target": "text=Start"}
```

You can also run one tool call without starting the REPL:

```bash
qplaywright-mcp cli snapshot '{"depth": 4}'
```

Expose Streamable HTTP instead of stdio when needed:

```bash
python -m qplaywright.mcp_server --transport streamable-http
```

## Packaging

Build wheel and sdist locally:

```bash
python -m build --no-isolation
```

## Notes

- All widget operations must execute on the Qt main thread.
- The Python package has zero mandatory runtime dependencies.
- Qt bindings are imported lazily by the Python agent.
- The C++ agent is header-only, but because it contains `Q_OBJECT`, it must still be listed in your CMake sources for AUTOMOC.
- MCP uses a single active session and a single active window scope; use the `session` and `window` tools to switch explicitly.

## Additional Docs

- `docs/mcp.md`: current MCP server contract and tool surface
- `docs/custom_widgets.md`: explicit method-based custom widget automation contract
- `docs/accessibility_semantics.md`: recommended use of `accessibleName`, `accessibleDescription`, and future `accessibleIdentifier` for agent-friendly Qt UIs
