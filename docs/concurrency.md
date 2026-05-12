# Concurrency Model

QPlaywright does not expose a general multi-threaded widget automation model.
The core rule is simple: all QWidget access stays on the Qt GUI thread.

This document records the current concurrency boundaries so future changes do
not accidentally weaken them.

## Core Guarantees

- Widget reads and writes must execute on the Qt main thread.
- Network or helper threads may decode requests and wait for results, but they
  must hand control back to the GUI thread before touching widget state.
- QPlaywright does not implicitly replay arbitrary action requests after a
  connection failure, because many actions are not idempotent.

## Python Agent

The Python agent accepts TCP traffic off the GUI thread, but command execution
is funneled back onto the Qt event loop:

- socket/server work happens outside the widget thread
- requests are wrapped in `CommandEvent` objects and posted with
  `QApplication.postEvent(...)`
- `Dispatcher.customEvent(...)` runs on the Qt main thread and calls
  `_handle_command(...)`
- `_executing_command` is a main-thread-only reentrancy guard that defers nested
  command execution when `_handle_command(...)` temporarily pumps events

Session overlay globals follow the same rule:

- `_SESSION_AGENT_NAMES`
- `_ACTIVE_SESSION_ID`

They are process-global state, but current code only mutates them from main
thread command handling helpers such as `_set_session_agent_name(...)`,
`_mark_session_active(...)`, and `_remove_session_agent_name(...)`.

## C++ Agent

The C++ agent uses a similar boundary with a different transport bridge:

- each client connection reads requests on its own connection thread
- the connection thread invokes `QPlaywrightHandler::handleCommand(...)` with
  `QMetaObject::invokeMethod(..., Qt::BlockingQueuedConnection)`
- the calling thread blocks until the GUI thread finishes the command

This preserves the same invariant as the Python agent: widget access happens on
the GUI thread, not on the socket thread.

## Sync Client

The sync Python client is not a connection pool. One `Application` owns one
`Connection`, and `Connection.send(...)` serializes request/response traffic
with an internal lock.

That lock protects request IDs and socket reads from interleaving, but it does
not make higher-level automation flows transactional or retry-safe.

## What Is Not Guaranteed

- No promise of correctness if internal agent helpers are called from arbitrary
  threads outside the documented dispatch paths.
- No automatic reconnect-and-replay for arbitrary actions.
- No documented support for concurrent mutation of shared session/UI state from
  multiple GUI-thread entry points.

## Rules For Future Changes

- If a new code path touches `QWidget` or other GUI-owned objects, route it back
  to the GUI thread first.
- If a new module introduces process-global session state, document its owner
  thread next to the variable.
- If a future feature truly needs cross-thread mutation, add an explicit guard
  or synchronization primitive and update this document.