# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

QPlaywright — a Playwright-compatible automation library for Qt QWidget applications. It has two sides:

- **Agent**: embeds in the target Qt app (C++ header or Python module), runs a TCP server
- **Client**: Python library with Playwright-style API (locator, click, fill, expect, etc.)

They communicate via JSON Lines over TCP (default `127.0.0.1:19876`).

## Build & Run

### C++ Agent (primary use case)

```bash
# Configure (supports Qt5 or Qt6)
cd agent_cpp && mkdir build && cd build
cmake .. -G "MinGW Makefiles" \
  -DCMAKE_PREFIX_PATH="D:/Qt/Qt5.14.2/5.14.2/mingw73_64" \
  -DCMAKE_CXX_COMPILER="D:/Qt/Qt5.14.2/Tools/mingw730_64/bin/g++.exe"

# Build
cmake --build .

# Deploy Qt DLLs (Windows)
windeployqt demo_app.exe

# Run demo
./demo_app.exe
```

### Python Client

```bash
# Install (zero runtime deps — Qt binding is lazy-imported by agent only)
pip install -e .

# Run test against a running demo app
python examples/test_demo.py
```

### MCP Server (optional northbound adapter)

```bash
# Install MCP support
pip install -e ".[mcp]"

# Start a stdio MCP server for Claude Desktop / VS Code / other MCP hosts
python -m qplaywright.mcp_server

# Or expose Streamable HTTP instead
python -m qplaywright.mcp_server --transport streamable-http

# Manual end-to-end MCP demo against the Python Qt sample app
python examples/test_mcp_demo.py
```

### Python Agent (alternative, for Python Qt apps)

```bash
pip install -e ".[dev]"   # installs PySide6 + pytest
python examples/demo_app.py
```

## Architecture

```
Client (Python)                    Agent (C++ or Python, in Qt app)
┌─────────────────┐    TCP/JSON   ┌──────────────────────┐
│ sync_qplaywright │───Lines────►│ QPlaywrightAgent      │
│ Application      │              │ (QTcpServer)          │
│ Window           │              │   ↓ per client        │
│ Locator          │◄────────────│ ClientConnection      │
│ _LocatorExpect   │              │   ↓ BlockingQueued    │
└─────────────────┘              │ Handler (main thread) │
                                  └──────────────────────┘
```

**Critical constraint**: All widget operations must run on the Qt main thread. Both agents solve this differently:

- **C++ agent**: `QMetaObject::invokeMethod(..., Qt::BlockingQueuedConnection)`
- **Python agent**: `QApplication.postEvent()` + `concurrent.futures.Future`

### Protocol (`qplaywright/protocol.py`)

Single source of truth for method names, selector syntax, and the role→Qt class mapping (`ROLE_MAP`). The C++ agent (`agent_cpp/qplaywright_agent.h`) duplicates the role map and method dispatch independently — keep them in sync when adding new methods or roles.

### Selector Syntax

- `role=button` — by widget role (mapped to Qt classes via `ROLE_MAP`)
- `text=Submit` — exact text match
- `has-text=partial` — case-insensitive substring
- `#objectName` or `name=objectName` — by `QObject::objectName()`
- `.ClassName` — by `metaObject()->className()` hierarchy

### Widget ID Registry

Both agents maintain a `wid` registry (widget pointer → stable integer). The client can cache `wid` values to skip repeated selector resolution.

### Key Files

| File | Purpose |
|---|---|
| `qplaywright/protocol.py` | Method constants, `Request`/`Response`, `ROLE_MAP`, selector docs |
| `agent_cpp/qplaywright_agent.h` | Single-header C++ agent (Q_OBJECT classes, needs AUTOMOC) |
| `qplaywright/agent/_server.py` | Python agent: TCP server + command handler |
| `qplaywright/agent/_selector.py` | Python selector engine + widget serialization |
| `qplaywright/sync_api/_api.py` | Client entry: `sync_qplaywright()`, `Application`, `Window` |
| `qplaywright/sync_api/_locator.py` | `Locator` (lazy, chainable) + `_LocatorExpect` (polling assertions) |
| `qplaywright/sync_api/_connection.py` | Synchronous TCP client with request/response matching |

## Important Notes

- The C++ header is header-only but contains `Q_OBJECT` macros — it **must** be listed in CMake sources for AUTOMOC to process it.
- The Python package has zero runtime dependencies. Qt bindings are lazy-imported at agent startup (tries PySide6 → PyQt6 → PySide2 → PyQt5).
- MCP support is implemented as an optional Python-side adapter over the existing sync client. It does not replace the Qt-side TCP protocol.
- No formal test suite exists yet. `examples/test_demo.py` is a manual integration test requiring the demo app to be running.
- When adding a new method: update `protocol.py` constants, the Python agent dispatch in `_server.py`, the C++ dispatch in `qplaywright_agent.h`, and the client `Locator`/`Window` in `sync_api/`.
