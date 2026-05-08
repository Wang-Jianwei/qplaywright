# MCP API Usability Improvements Plan

## Context

This document turns the observations in [2026-04-25-mcp-usability-improvements.md](2026-04-25-mcp-usability-improvements.md) into an implementation plan.

The goal is to improve MCP usability without introducing parallel tool sets, compatibility aliases, or transitional contracts. If a contract changes, the MCP surface, tests, and docs should move to the new contract directly.

## Triage Summary

| Issue | Status | Plan |
| --- | --- | --- |
| `choose` strict selector validation | Needs reproduction | Do not schedule a behavior change yet. First reproduce the reported failure with the exact MCP payload. If it is not reproducible, close this item as a usage or documentation issue. |
| `screenshot` returns base64 by default | Accepted | Change the MCP-facing result so screenshot capture is file-oriented instead of embedding large base64 payloads in tool responses. |
| `snapshot` / `inspect` include too much Qt infrastructure | Accepted with scope change | Treat this as an infrastructure-filtering problem, not a hidden-widget problem. Add semantic filtering for internal Qt support widgets. |
| Missing wait / polling utility | Reframed | Do not add a second wait tool. Extend the existing `wait` tool with a separate condition model beyond the current state-based wait contract. |
| Inconsistent window response shapes | Accepted with scope change | Normalize the window summary schema, but do not force every `window` action to return the full `windows` list. |
| Action responses lack widget-level post-state | Accepted with scope change | Add optional post-action widget state observation. Do not report speculative “state changed” flags. Report only observed state. |

## Design Decisions

### 1. No compatibility layer

This work should not introduce deprecated aliases, alternate tool names, or dual response schemas. The MCP interface should move to the cleaner contract in one step.

### 2. Prefer MCP-layer fixes when possible

If a usability problem can be solved in [qplaywright/mcp_server.py](../qplaywright/mcp_server.py) without weakening the underlying sync API or Qt agent protocol, do it there.

### 3. Keep raw automation capabilities intact

Filtering and post-processing should improve MCP ergonomics, but should not remove the ability to inspect real widget structure when debugging. If a full raw view is still needed, expose it with an explicit flag rather than keeping noisy output as the default.

## Workstreams

### A. Make `screenshot` MCP responses file-oriented

#### Objective

Stop returning large base64 blobs as the default MCP result when no explicit path is supplied.

#### Planned behavior

- When `path` is provided, keep returning `path`, `width`, and `height`.
- When `path` is omitted, the MCP layer writes the capture to a dedicated screenshot temp directory and still returns a file path.
- The MCP contract should return a small structured payload such as `path`, `width`, `height`, `target`, and `active_window`.
- Base64 image data should not be part of the normal MCP tool response.

#### Temp file lifecycle

- Default output directory: the system temp directory under a dedicated `qplaywright_screenshots` subdirectory.
- Default filename: timestamp plus a random suffix to avoid collisions across repeated or concurrent captures.
- The MCP server owns this directory and cleans it up on server shutdown.
- The server should not delete screenshot files eagerly during normal runtime, because MCP hosts may read the returned path asynchronously.
- Do not reuse one fixed filename for all captures. Overwriting the same path is fragile when hosts read files after the tool call returns.

#### Likely files

- [qplaywright/mcp_server.py](../qplaywright/mcp_server.py)
- [tests/test_mcp_server.py](../tests/test_mcp_server.py)
- [docs/mcp.md](../docs/mcp.md)

#### Notes

This can likely be implemented entirely in the MCP layer by converting the existing raw screenshot result into a saved file before returning to the MCP host.

### B. Add semantic filtering for `snapshot` and `inspect`

#### Objective

Reduce noise from internal Qt infrastructure widgets such as scroll area viewports and internal containers.

#### Planned behavior

- Add an explicit filtering concept for infrastructure widgets instead of a vague `include_hidden` switch.
- Default `snapshot` output to the filtered semantic view.
- Default `inspect` to the filtered view for normal MCP use, with an explicit opt-in flag for raw infrastructure when debugging.
- Keep `topmost_only` orthogonal. It remains a visibility approximation, not an infrastructure filter.

#### Implementation shape

- Build filtering in the MCP presentation layer after the raw widget tree is fetched.
- Classify infrastructure widgets by explicit heuristics instead of ad hoc inspection.
- Initial strong signals:
  - `objectName` starts with `qt_`
  - class name is in an explicit Qt internal support-widget allowlist
- Initial support-widget allowlist should include the first batch observed in real snapshots, such as scroll-area viewports and scrollbar containers.
- `WA_TransparentForMouseEvents` may be used only as a secondary hint, not as a standalone filter rule, to avoid hiding business wrappers that are intentionally mouse-transparent.
- Preserve the original tree shape for nodes that remain visible in the filtered output.

#### Initial classification baseline

- Filter nodes with `objectName` values such as `qt_scrollarea_viewport`, `qt_scrollarea_hcontainer`, and similar `qt_` internal support names.
- Filter known internal support classes, starting with classes in the `QAbstractScrollArea` support stack.
- Keep the initial class-name list explicit in code and tests so future additions are deliberate instead of heuristic drift.

#### Likely files

- [qplaywright/mcp_server.py](../qplaywright/mcp_server.py)
- [tests/test_mcp_server.py](../tests/test_mcp_server.py)
- [docs/mcp.md](../docs/mcp.md)

### C. Extend the existing `wait` tool instead of adding a new one

#### Objective

Support common verification flows without requiring repeated `snapshot` or `inspect` polling by the MCP caller.

#### Planned behavior

- Keep the existing `wait(target, state=...)` contract for state-based waits.
- Extend `wait` with a separate `condition` model for common UI assertions such as:
  - text equals or contains
  - currentText equals or contains
  - value equals
  - checked equals true or false
  - count equals an expected number
- Do not add a general expression language in the first slice.
- Do not overload the existing `state` field with text, value, or count assertions.
- `state` and `condition` should be mutually exclusive in one request.

#### Implementation shape

- This is an explicit post-end-state extension. [docs/mcp_end_state.md](../docs/mcp_end_state.md) and [docs/mcp_end_state_schema.md](../docs/mcp_end_state_schema.md) must be updated if this workstream lands.
- Reuse existing locator polling where possible.
- For richer property-based waits, implement polling in the MCP layer using current inspection/property access paths.
- Keep timeout handling and result shape aligned with the current `wait` response.

#### Likely files

- [qplaywright/mcp_server.py](../qplaywright/mcp_server.py)
- [tests/test_mcp_server.py](../tests/test_mcp_server.py)
- [docs/mcp.md](../docs/mcp.md)

### D. Normalize `window` response structures

#### Objective

Make `window` responses predictable without forcing heavyweight payloads on non-list actions.

#### Planned behavior

- All `window` summaries use one shared schema:
  - `wid`
  - `title`
  - `class`
  - `geometry`
  - `is_active`
  - `is_modal`
- `window list` returns `ok`, `action`, `windows`, and `active_window`.
- `window select`, `window resize`, and `window close` return `ok`, `action`, and `active_window`.
- Do not force non-list actions to return the full `windows` array. Callers that need a refreshed full list can call `window list` explicitly.

#### Likely files

- [qplaywright/mcp_server.py](../qplaywright/mcp_server.py)
- [tests/test_mcp_server.py](../tests/test_mcp_server.py)
- [docs/mcp.md](../docs/mcp.md)

### E. Add optional post-action widget state observation

#### Objective

Let callers request a small verified widget-state payload after actions without forcing a full snapshot.

#### Planned behavior

- Add an explicit option such as `include_state` for action tools.
- When enabled, return a compact `state` object with only directly observed values relevant to the target, for example:
  - `exists`
  - `visible`
  - `enabled`
  - `checked`
  - `text`
  - `currentText`
  - `value`
- `include_state` and `include_snapshot` are independent flags and may both be `true` in the same request.
- `include_state` returns target-level post-action widget state.
- `include_snapshot` continues to return the heavier window-level text snapshot together with stable-handle snapshot metadata.
- Do not claim that a state changed unless the server actually compared before and after values.
- Keep click failure behavior unchanged: disabled or obstructed widgets should still fail before returning `ok=true`.

#### Likely files

- [qplaywright/mcp_server.py](../qplaywright/mcp_server.py)
- [tests/test_mcp_server.py](../tests/test_mcp_server.py)
- [docs/mcp.md](../docs/mcp.md)

### F. Investigate the reported `choose` failure before changing API semantics

#### Objective

Avoid making the `choose` API more permissive without proof that the current behavior is actually wrong.

#### Planned behavior

- Reproduce the exact failing MCP request that triggered the issue report.
- Confirm whether the problem is:
  - multiple selector fields being sent accidentally
  - empty-string values being serialized unexpectedly
  - a host-side tool wrapper issue
  - a real server-side validation bug
- Only schedule code changes after one of those causes is verified.

#### Likely files if a real bug exists

- [qplaywright/mcp_server.py](../qplaywright/mcp_server.py)
- [tests/test_mcp_server.py](../tests/test_mcp_server.py)
- Possibly [qplaywright/sync_api/_locator.py](../qplaywright/sync_api/_locator.py) if the bug is lower than the MCP layer

## Delivery Order

### Phase 1

- Workstream A: screenshot result cleanup

This change is the clearest, most self-contained MCP usability win.

### Phase 2

- Workstream D: window response normalization
- Workstream E: optional post-action widget state

These two changes both affect action and window response contracts, so they should be designed together and landed in one slice.

### Phase 3

- Workstream B: semantic filtering for snapshot and inspect

This change improves observation quality, but needs a concrete baseline for infrastructure classification to avoid hiding useful widgets.

### Phase 4

- Workstream C: richer wait conditions
- Workstream F: choose failure investigation

These items need tighter API design or reproduction data before implementation should start.

## Validation Plan

For each implemented workstream:

- Add focused unit tests in [tests/test_mcp_server.py](../tests/test_mcp_server.py).
- Update [docs/mcp.md](../docs/mcp.md) so the documented MCP interface matches the shipped tool behavior.
- Run the narrow MCP server test slice first.
- If behavior affects demo flows, run one manual end-to-end MCP scenario against the demo app after unit tests pass.

## Completion Criteria

This issue should be considered complete only when all accepted workstreams are closed end-to-end:

- MCP tool behavior updated
- tests updated and passing
- docs updated
- old response assumptions removed from docs and tests

The issue should not be considered complete while any superseded response shape or half-migrated tool contract remains in place.