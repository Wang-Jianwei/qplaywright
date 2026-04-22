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

start_agent(port=19876)
```

### C++ Qt application

```cpp
#include "qplaywright_agent.h"

int main(int argc, char *argv[]) {
    QApplication app(argc, argv);
    QPlaywrightAgent::start(19876);
    return app.exec();
}
```

### Python client

```python
from qplaywright import sync_qplaywright

with sync_qplaywright(port=19876) as qp:
    app = qp.application()
    window = app.window()
    window.locator("role=button", has_text="Submit").click()
```

## MCP Server

Run the MCP server over stdio:

```bash
qplaywright-mcp
```

Or:

```bash
python -m qplaywright.mcp_server
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
