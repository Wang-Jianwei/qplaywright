# Issue #26: Table and Tree Support

## Summary

Issue #26 currently exists only as a title: "缺乏对 table、tree 的支持".

The repository already recognizes `role=table` and `role=tree`, but that support stops at the widget container level. A caller can locate a `QTableWidget`, `QTableView`, `QTreeWidget`, or `QTreeView` as a widget, yet cannot address rows, cells, or tree nodes as first-class automation targets.

This document defines a concrete design for adding table and tree support without faking non-widget model items as ordinary widgets and without introducing compatibility aliases.

## Current State

### What already exists

- `role=table` and `role=tree` are already mapped in [qplaywright/protocol.py](../qplaywright/protocol.py).
- Generic widget discovery, widget tree capture, and `Locator` actions already work for the container widget itself.
- The demo application already includes a real `QTableWidget` named `data_table` in [examples/demo_app.py](../examples/demo_app.py).

### What is missing

- No public client API can resolve a table cell or tree node.
- No protocol method operates on model indexes or item-view structure.
- The widget tree contains only actual `QWidget` descendants, so table cells and tree items never appear as locatable nodes.
- There is no tree demo coverage and no table/tree-specific tests.

### Root cause

The current architecture is widget-centric. Discovery walks `QWidget` children only, and serialization reflects only widget properties. That is correct for real widgets, but table cells and tree nodes are usually model items, not widgets:

- `QTableWidgetItem` is not a `QWidget`
- `QTreeWidgetItem` is not a `QWidget`
- `QTableView` and `QTreeView` expose content through `QAbstractItemModel` and `QModelIndex`

As a result, the current locator model has no truthful representation for item-view descendants.

## Design Goals

1. Add first-class automation for table cells and tree nodes.
2. Support both convenience widgets and model-based views:
   - `QTableWidget` and `QTreeWidget`
   - `QTableView` and `QTreeView`
3. Keep widget automation and item-view automation clearly separated.
4. Resolve item targets from explicit structure on every request instead of introducing a long-lived remote item registry.
5. Preserve parity between the Python agent and the C++ agent.

## Non-Goals

- Do not inject fake `cell`, `row`, or `treeitem` nodes into `widget_tree()`.
- Do not rewrite cell text or node labels into the parent widget's `text` field.
- Do not overload `fill()` as a generic model-editing API.
- Do not add compatibility aliases or alternate legacy contracts.
- Do not attempt generalized support for every `QAbstractItemView` subtype in the first slice. The initial scope is table and tree only.

## Design Principles

### 1. No fake widget hierarchy

The accessibility and serialization guidance in [docs/accessibility_semantics.md](../docs/accessibility_semantics.md) is explicit: QPlaywright should serialize real widget structure, not invent a uniform hierarchy. Table rows, cells, and tree nodes must therefore not be exposed as if they were child widgets.

### 2. Introduce structured item locators, not selector hacks

The existing selector grammar is intentionally widget-oriented. Extending it with synthetic child-selector syntax for non-widget descendants would blur two different automation layers and make selector semantics harder to reason about.

Instead, table/tree support should use explicit structured APIs.

### 3. No remote item-id registry

Model indexes are invalidated by sorting, filtering, insertions, removals, and model resets. The repository already has one widget-lifetime issue around remote identity; item-view support should not repeat that mistake.

Each item operation should carry an explicit descriptor, and the agent should resolve that descriptor fresh against the current model each time.

## Proposed Public API

### Client surface

Add a new client-side type `ItemLocator` for non-widget item-view targets.

The existing `Locator` remains the widget locator. A widget locator for a table or tree can derive an `ItemLocator`.

### Table API

```python
table = window.locator("#data_table")

cell = table.cell(2, 1)
assert cell.text_content() == "Carol White"

status = table.cell(row=3, column="Status")
status.click()
```

Proposed methods on `Locator`:

- `cell(row: int, column: int | str) -> ItemLocator`

Notes:

- Row indices are resolved in the current view order after sorting and filtering, not against the source model.
- Integer `column` is zero-based.
- Integer `column` refers to the logical column index, not the current visual header position.
- String `column` resolves by horizontal header text to one logical column.
- Duplicate header text must fail instead of silently picking one column.
- Hidden columns may still support read-only access such as `text_content()` and `properties()`, but pointer actions and `bounding_box()` must fail when there is no visible target rectangle.

### Tree API

```python
tree = window.locator("role=tree")

node = tree.node(["Settings", "Advanced"])
node.expand()
assert node.text_content() == "Advanced"

child = tree.node(["Settings", 1])
child.click()
```

Proposed methods on `Locator`:

- `node(path: list[str | int]) -> ItemLocator`
- `root_node(index: int) -> ItemLocator`

Notes:

- Each path segment is either:
  - `str`: resolve by display text among siblings
  - `int`: resolve by zero-based sibling row index
- Path resolution uses the current view/model ordering after sorting and filtering.
- Path resolution is deterministic and scoped level by level.
- Ambiguous text among siblings should fail instead of silently picking the first match.
- Text segments are a convenience contract, not a stable non-localized identity contract. A richer key-based node identity scheme is deferred to a later slice.

### ItemLocator API

`ItemLocator` should support only operations that are meaningful on item-view descendants.

The first slice should support only two concrete target kinds:

- table cells
- tree nodes

Row locators are intentionally deferred. A row-level API sounds convenient, but it is underspecified across multi-column tables, hidden sections, row spans, and row-level text serialization. That should be designed separately if it is still needed after cell support lands.

Initial read API:

- `text_content() -> str`
- `bounding_box() -> dict[str, int]`
- `is_visible() -> bool`
- `properties() -> dict[str, object]`

Visibility semantics:

- `is_visible()` means the item both exists and currently maps to a non-empty visible rectangle in the owning view.
- A tree descendant under a collapsed ancestor is not visible.
- A cell in a hidden column is not visible.
- Read-only operations may still succeed for existing but non-visible items when the underlying model/index can still be resolved.

Initial action API:

- `click() -> None`
- `dblclick() -> None`
- `hover() -> None`

Tree-only API:

- `expand() -> None`
- `collapse() -> None`

Optional row-level convenience for later evaluation:

- `cells() -> list[ItemLocator]`
- `children() -> list[ItemLocator]`

These should not be part of the first implementation unless they are needed by tests or docs.

## Item descriptor model

Every item request should include the parent widget id plus a structured descriptor.

### Table descriptors

Cell descriptor:

```json
{
  "kind": "table_cell",
  "row": 2,
  "column": 1
}
```

Column-by-header descriptor before server-side normalization:

```json
{
  "kind": "table_cell",
  "row": 3,
  "columnName": "Status"
}
```

Row descriptors are intentionally not part of the first slice.

### Tree descriptors

```json
{
  "kind": "tree_node",
  "path": ["Settings", "Advanced"]
}
```

The client may store these descriptors, but the agent must resolve them fresh on each request.

## Protocol Changes

Add a dedicated item-view operation family in [qplaywright/protocol.py](../qplaywright/protocol.py).

### New method constants

- `METHOD_ITEM_TEXT = "item_text"`
- `METHOD_ITEM_PROPERTIES = "item_properties"`
- `METHOD_ITEM_VISIBLE = "item_visible"`
- `METHOD_ITEM_BOUNDING_BOX = "item_bounding_box"`
- `METHOD_ITEM_CLICK = "item_click"`
- `METHOD_ITEM_DBLCLICK = "item_dblclick"`
- `METHOD_ITEM_HOVER = "item_hover"`
- `METHOD_ITEM_EXPAND = "item_expand"`
- `METHOD_ITEM_COLLAPSE = "item_collapse"`

Each request carries:

- `wid`: the owning table/tree widget id
- `item`: the explicit structured descriptor

Example:

```json
{
  "method": "item_click",
  "params": {
    "wid": 14,
    "item": {
      "kind": "table_cell",
      "row": 3,
      "columnName": "Status"
    }
  }
}
```

## Agent Design

### Shared internal model: resolve to current item-view index

Both agents should introduce a shared conceptual helper layer:

- validate the owner widget type
- resolve the item descriptor to the current model position
- materialize a display payload from the resolved position
- map the model position to view geometry for pointer actions

All item resolution must be defined in terms of the current view state, not the source model state. That means sorting, filtering, header reordering, hidden sections, and tree expansion state must be handled as view-layer concerns.

The core abstraction should be the current cell/node position, not `QTableWidgetItem` or `QTreeWidgetItem` directly.

That keeps `QTableWidget` and `QTableView` on one path, and `QTreeWidget` and `QTreeView` on one path.

### Python agent changes

Likely files:

- [qplaywright/agent/_server.py](../qplaywright/agent/_server.py)

If helper extraction is needed, add a dedicated item-view helper module instead of extending the selector engine. The selector engine should remain widget-oriented.

Planned internal helpers:

- `_resolve_item_target(owner_widget, item_descriptor)`
- `_resolve_table_column(owner_widget, column_or_name)`
- `_resolve_tree_path(owner_widget, path_segments)`
- `_item_text(owner_widget, resolved_target)`
- `_item_properties(owner_widget, resolved_target)`
- `_item_bounding_box(owner_widget, resolved_target)`
- `_click_item(owner_widget, resolved_target, double=False)`
- `_hover_item(owner_widget, resolved_target)`
- `_expand_item(owner_widget, resolved_target)`
- `_collapse_item(owner_widget, resolved_target)`

Implementation notes:

- Use the view's model APIs for row, column, parent, and data resolution.
- Use current view coordinates after sorting/filtering rather than source-model coordinates.
- For geometry and pointer actions, call the view's scroll-to-item behavior first, then compute the visual rectangle and convert it to global coordinates.
- If scrolling still does not produce a valid visible rectangle, fail instead of clicking the owner widget blindly.
- Pointer actions must target the item-view viewport coordinates, not the outer view widget coordinates.
- Pointer actions do not auto-expand collapsed tree ancestors. If the target index exists but is not visually reachable because an ancestor is collapsed, `click()`, `hover()`, and `bounding_box()` must fail until the caller expands the path explicitly.
- Fail with explicit errors when:
  - the owner widget is not a supported table/tree widget
  - the row or column is out of range
  - a header name does not exist
  - a header name is ambiguous
  - a tree path segment is ambiguous or missing
  - the item is not currently visible enough to map to a usable rectangle

### C++ agent changes

Likely file:

- [qplaywright/cpp/qplaywright_agent.h](../qplaywright/cpp/qplaywright_agent.h)

The C++ agent must mirror the same contract and failure behavior. Do not land Python-only item-view semantics.

### Why selector changes stay minimal

No selector grammar change is required for the first slice.

Widget selection remains:

- `window.locator("role=table")`
- `window.locator("#data_table")`
- `window.locator("role=tree")`

Structure selection begins only after the owner widget is resolved through the explicit typed API.

## Returned Item Properties

`ItemLocator.properties()` should surface a truthful item payload, not a fake widget payload.

Initial property set:

- `kind`: `table_cell` or `tree_node`
- `row`
- `column` when applicable
- `text`
- `displayText` if the implementation later needs a separate display role field
- `selected`
- `checkState` when the item is checkable
- `expanded` for tree nodes
- `path` for tree nodes

Do not claim widget-only properties such as `enabled`, `objectName`, or `accessibleName` unless they are truly properties of the item target rather than the owner widget.

## Failure Model

All item-view failures should be explicit and deterministic.

Required failure cases:

- owner widget is not `QTableWidget`, `QTableView`, `QTreeWidget`, or `QTreeView`
- item descriptor shape is invalid
- row or column is out of range
- table header text is missing or ambiguous
- tree path segment is missing or ambiguous
- expand/collapse requested on a non-tree target
- pointer action or bounding box requested on a hidden column item
- pointer action or bounding box requested on a tree item hidden by a collapsed ancestor
- bounding box or pointer action requested for an item with no usable visual rectangle

The API should fail immediately instead of silently degrading to a widget click on the owner view.

## Widget Tree and Snapshot Policy

`widget_tree()` should remain widget-only.

This issue should not change the meaning of widget tree snapshots. Table/tree structure is a separate layer and may be exposed later through explicit structured inspection, but it must not be mixed into the plain widget tree.

If a future MCP or debug workflow needs structured table/tree dumps, that should be an explicit table/tree inspection feature, not a silent change to `widget_tree()`.

## Tests

Add focused tests before any broad manual validation.

### Unit tests

Likely files:

- [tests/test_click_api.py](../tests/test_click_api.py)
- [tests/test_custom_widget_support.py](../tests/test_custom_widget_support.py)
- a new focused file such as `tests/test_item_view_api.py`

Required Python test coverage:

- resolve a table cell by numeric row and column
- resolve a table cell by header name
- resolve rows in current view order after sorting, not source-model order
- click and read text from a table cell
- reject out-of-range row and column
- reject ambiguous header text
- scroll an off-screen item into view before pointer actions
- resolve a tree node by text path
- resolve a tree node by index path
- reject ambiguous or missing tree path segments
- expand and collapse a tree node
- fail pointer actions for descendants hidden by collapsed ancestors until the path is expanded
- ensure `widget_tree()` still does not invent synthetic item nodes

### C++ parity validation

Required C++ coverage:

- at least one end-to-end demo or targeted validation path proving the same API works through the C++ agent

If automated C++ coverage is not added in the same slice, the issue must remain open with that gap called out explicitly.

### Demo coverage

Update [examples/demo_app.py](../examples/demo_app.py) to include:

- an actual visible tree widget with stable node labels
- the existing table kept as the canonical table example

Add one usage example script once the implementation lands.

## Documentation Updates

If the implementation lands, update all of the following in the same slice:

- [README.md](../README.md) with one short table/tree automation example
- [qplaywright/protocol.py](../qplaywright/protocol.py) selector and method comments
- client API docstrings in [qplaywright/sync_api/_locator.py](../qplaywright/sync_api/_locator.py)
- MCP docs only if MCP chooses to expose the new item-view operations directly

## Delivery Plan

### Phase 1: Table support

- add `ItemLocator`
- add `Locator.cell()`
- add item-view protocol methods
- implement Python agent table resolution
- implement C++ agent table resolution
- add table tests

### Phase 2: Tree support

- add `Locator.node()` and `Locator.root_node()`
- implement path resolution and expand/collapse
- add Python and C++ parity tests
- add visible tree demo coverage

### Phase 3: Optional structured inspection

- only if needed after the first two phases
- design explicit inspection APIs for table/tree structure
- keep this separate from `widget_tree()`

## Concrete Implementation Breakdown

This section turns the design into an edit checklist that is concrete enough to drive implementation without re-opening the API discussion.

### Cross-cutting scope control

Do not widen the first implementation slice unnecessarily.

For Phase 1:

- implement table cells only
- keep tree support out of the first patch series except for neutral protocol shape decisions
- keep MCP unchanged unless a real direct dependency appears during implementation
- do not modify the selector grammar
- do not modify `Window` or `Application` in [qplaywright/sync_api/_api.py](../qplaywright/sync_api/_api.py)

The first slice should be able to ship with changes concentrated in protocol constants, the sync locator layer, the Python agent dispatch/helpers, the C++ agent dispatch/helpers, and focused tests.

### Phase 1 file-by-file plan

#### 1. Protocol surface

File:

- [qplaywright/protocol.py](../qplaywright/protocol.py)

Required edits:

- add item-view method constants in the method-constant block
- add a short protocol comment stating that item-view methods target non-widget descendants owned by a table/tree widget
- keep selector syntax comments widget-only; do not document item-view traversal as selector syntax

Do not add:

- role-map changes
- selector grammar changes
- compatibility aliases

#### 2. Sync client public API

Primary file:

- [qplaywright/sync_api/_locator.py](../qplaywright/sync_api/_locator.py)

No-change files for Phase 1 unless the public export decision changes later:

- [qplaywright/sync_api/__init__.py](../qplaywright/sync_api/__init__.py)
- [qplaywright/__init__.py](../qplaywright/__init__.py)

Required edits in `_locator.py`:

- add an `ItemLocator` class next to `Locator`
- add a helper on `Locator` that resolves the owner widget id once and builds item-view request params
- add `Locator.cell(row, column)`
- do not add `Locator.row()` in Phase 1
- implement `ItemLocator.text_content()`
- implement `ItemLocator.bounding_box()`
- implement `ItemLocator.is_visible()`
- implement `ItemLocator.properties()`
- implement `ItemLocator.click()`
- implement `ItemLocator.dblclick()`
- implement `ItemLocator.hover()`
- add a minimal `ItemLocator.__repr__()` for debuggability

Recommended internal method split in `_locator.py`:

- `Locator._resolve_owner_wid()`
- `Locator._item_params(item: dict[str, Any], **extra) -> dict[str, Any]`
- `ItemLocator._send(method: str, **extra) -> Any`

Design note:

- Keep `ItemLocator` derived from an already-resolved owner widget id plus a pure item descriptor.
- Do not make `ItemLocator` pretend to be a widget `Locator`; its method set should remain intentionally smaller.

#### 3. Python agent implementation

Primary file:

- [qplaywright/agent/_server.py](../qplaywright/agent/_server.py)

Keep unchanged in Phase 1:

- [qplaywright/agent/_selector.py](../qplaywright/agent/_selector.py)

Required edits in `_server.py`:

- extend `_handle_command()` with the new `item_*` dispatch cases
- add a dedicated table/item-view helper block near the existing widget action helpers rather than scattering logic inside `_handle_command()`
- reuse existing click-target and hover infrastructure where practical after resolving an item rectangle into viewport-local coordinates

Recommended helper set for Phase 1:

- `_resolve_item_owner(params)`
- `_resolve_table_item(owner_widget, descriptor)`
- `_resolve_table_column(owner_widget, column_or_name)`
- `_table_model(owner_widget)`
- `_table_view(owner_widget)`
- `_table_index_text(owner_widget, resolved_target)`
- `_table_index_properties(owner_widget, resolved_target)`
- `_table_index_visible(owner_widget, resolved_target)`
- `_table_index_rect(owner_widget, resolved_target)`
- `_click_table_index(owner_widget, resolved_target, double=False)`
- `_hover_table_index(owner_widget, resolved_target)`

Recommended resolved-target shape for internal Python code:

```python
{
  "kind": "table_cell",
  "row": 3,
  "column": 4,
  "index": ...,  # agent-local only, never serialized back to the client
}
```

Important guardrails:

- resolve the logical column first, then derive the current view index/rectangle from the view
- use current view row ordering after sorting/filtering
- scroll before pointer actions
- fail explicitly when no usable visual rectangle exists
- never degrade to clicking the owner widget center

#### 4. Python unit tests

Recommended new file:

- `tests/test_item_view_api.py`

Why a new file:

- item-view resolution is a new abstraction and should not overload the current custom-widget or click-only test files
- the tests will need dedicated fake model/view objects that would otherwise pollute unrelated test modules

Recommended test groups in `tests/test_item_view_api.py`:

- `test_locator_cell_builds_item_locator_from_owner_widget()`
- `test_item_locator_text_content_reads_table_cell_by_numeric_column()`
- `test_item_locator_text_content_reads_table_cell_by_header_name()`
- `test_item_locator_rejects_ambiguous_header_name()`
- `test_item_locator_rejects_out_of_range_row()`
- `test_item_locator_rejects_out_of_range_column()`
- `test_item_locator_properties_report_table_cell_payload()`
- `test_item_locator_is_visible_false_for_hidden_column()`
- `test_item_locator_bounding_box_requires_visible_rect()`
- `test_item_click_scrolls_before_resolving_visual_rect()`

Keep [tests/test_click_api.py](../tests/test_click_api.py) for only one narrow follow-up if needed:

- add a single regression test only if item-view clicking ends up reusing and changing shared click-target code

Keep [tests/test_custom_widget_support.py](../tests/test_custom_widget_support.py) unchanged for Phase 1 unless a widget-tree regression appears.

#### 5. C++ agent implementation

Primary file:

- [qplaywright/cpp/qplaywright_agent.h](../qplaywright/cpp/qplaywright_agent.h)

Required edits:

- add `item_*` method handling in `dispatch(const QString &method, const QJsonObject &params)`
- add a dedicated helper cluster near the existing widget action helpers rather than embedding the logic in the dispatch chain
- mirror the Python failure behavior and request/response shapes exactly

Recommended helper names for the C++ side:

- `resolveItemOwner(const QJsonObject &params)`
- `resolveTableItem(QWidget *owner, const QJsonObject &descriptor)`
- `resolveTableColumn(QWidget *owner, const QJsonValue &columnValue)`
- `tableIndexText(QWidget *owner, const ResolvedTableItem &target)`
- `tableIndexProperties(QWidget *owner, const ResolvedTableItem &target)`
- `tableIndexVisible(QWidget *owner, const ResolvedTableItem &target)`
- `tableIndexRect(QWidget *owner, const ResolvedTableItem &target)`
- `clickTableIndex(QWidget *owner, const ResolvedTableItem &target, bool dblClick)`
- `hoverTableIndex(QWidget *owner, const ResolvedTableItem &target)`

Recommended C++ internal struct:

```cpp
struct ResolvedTableItem {
  int row;
  int column;
  QModelIndex index;
};
```

Do not accept a Python-only intermediate contract such as different error text, missing visibility checks, or implicit fallback clicks.

#### 6. Demo and docs impact in Phase 1

Files:

- [examples/demo_app.py](../examples/demo_app.py)
- [README.md](../README.md)

Phase 1 expectation:

- no structural demo change is required for table support because the demo already contains `data_table`
- add README examples only after the implementation and tests are green
- defer tree-demo UI additions to Phase 2

#### 7. MCP impact in Phase 1

Primary file to leave unchanged by default:

- [qplaywright/mcp_server.py](../qplaywright/mcp_server.py)

Phase 1 rule:

- do not thread item-view operations into MCP unless the implementation reveals an unavoidable dependency
- if MCP follow-up is desired later, design it as an explicit target expansion rather than leaking `ItemLocator` internals into current generic locator tooling

### Phase 2 file-by-file plan

Phase 2 should build on the Phase 1 item-view scaffolding instead of inventing a second parallel stack.

#### 1. Sync client additions

File:

- [qplaywright/sync_api/_locator.py](../qplaywright/sync_api/_locator.py)

Required Phase 2 edits:

- add `Locator.node(path)`
- add `Locator.root_node(index)`
- add `ItemLocator.expand()`
- add `ItemLocator.collapse()`
- keep tree-only methods guarded by target kind checks

#### 2. Python agent additions

File:

- [qplaywright/agent/_server.py](../qplaywright/agent/_server.py)

Required Phase 2 edits:

- add tree-node descriptor resolution helpers
- add path walking by sibling text or sibling row index
- add explicit ancestor-expansion checks for visibility-sensitive operations
- add expand/collapse implementations against the owning tree view/widget

Recommended helper additions:

- `_resolve_tree_item(owner_widget, descriptor)`
- `_resolve_tree_path(owner_widget, path_segments)`
- `_tree_index_text(owner_widget, resolved_target)`
- `_tree_index_properties(owner_widget, resolved_target)`
- `_tree_index_visible(owner_widget, resolved_target)`
- `_tree_index_rect(owner_widget, resolved_target)`
- `_expand_tree_index(owner_widget, resolved_target)`
- `_collapse_tree_index(owner_widget, resolved_target)`

#### 3. C++ agent additions

File:

- [qplaywright/cpp/qplaywright_agent.h](../qplaywright/cpp/qplaywright_agent.h)

Required Phase 2 edits:

- mirror the Python tree helper layer
- mirror the same path-ambiguity and collapsed-ancestor failure behavior

#### 4. Demo and tests in Phase 2

Files:

- [examples/demo_app.py](../examples/demo_app.py)
- `tests/test_item_view_api.py`

Required Phase 2 tests:

- `test_locator_node_resolves_text_path()`
- `test_locator_node_resolves_index_path()`
- `test_locator_node_rejects_ambiguous_sibling_text()`
- `test_tree_item_expand_and_collapse()`
- `test_tree_item_click_fails_when_hidden_by_collapsed_ancestor()`

Required Phase 2 demo change:

- add one visible tree widget with stable text labels specifically for automated tests and examples

### Validation order

When implementing this design, validate in the narrowest possible order:

1. add sync-layer unit tests for `ItemLocator` request shaping
2. add Python agent resolution tests with fake views/models
3. implement Python table support until those tests pass
4. add matching C++ dispatch/helper implementation
5. run the focused Python test slice first
6. run any available C++ demo-level validation second
7. update README examples only after executable validation is green

### Suggested patch series

To keep reviewable change slices small, implement this issue as a patch series instead of one large mixed change.

Recommended sequence:

1. protocol constants + sync `ItemLocator` request shaping + Python unit tests for request payloads
2. Python agent table-cell resolution + Python item-view tests
3. C++ agent parity for table-cell methods
4. README example updates for table cells
5. tree support as a separate follow-up slice

This issue can stay open across that series, but each patch should leave the repository in a validated state.

### Suggested validation commands

The repository already declares `pytest` in the `dev` extra in [pyproject.toml](../pyproject.toml), so the Python-side validation path should stay pytest-first.

Recommended narrow commands during implementation:

```bash
python -m pytest tests/test_item_view_api.py
python -m pytest tests/test_click_api.py tests/test_custom_widget_support.py
```

Recommended broader Python confirmation once Phase 1 is green:

```bash
python -m pytest tests
```

Recommended manual demo smoke path for Phase 1:

1. run `python examples/demo_app.py`
2. attach with the sync client
3. resolve `#data_table`
4. read one numeric cell
5. read one header-name cell
6. click one visible cell and verify the action targets the cell rectangle, not the table center

Recommended C++ parity confirmation after the C++ slice lands:

1. build the C++ demo
2. run the demo executable
3. attach with the same sync client flow used for the Python demo
4. repeat the same table-cell smoke actions

### Deferred questions

The following questions are intentionally deferred and should not block Phase 1 unless a concrete implementation problem forces them open.

#### 1. Row-level API

Deferred because row serialization and pointer targeting are still underspecified.

Do not reopen this during the first cell implementation unless a hard requirement appears.

#### 2. Stable tree node identity beyond text/index paths

Deferred because the current issue is about first-class support, not about long-term localization-stable identity.

If future consumers need stable node identity, design that as an explicit follow-up contract instead of quietly overloading text-path behavior.

#### 3. Rich item editing

Deferred because the first slice is about read operations, visibility, and pointer actions.

Do not add `fill()`-like behavior for table cells or model items in this issue unless a specific widget class demands it and the contract is clearly designed.

#### 4. MCP exposure

Deferred because MCP currently works in terms of generic locators and explicit tool contracts.

If table/tree item support is exposed through MCP later, design the target syntax and result shape explicitly instead of tunneling raw item descriptors through generic locator strings.

### What should not move in the first implementation

Leave these surfaces alone unless a concrete blocker proves otherwise:

- selector parsing in [qplaywright/agent/_selector.py](../qplaywright/agent/_selector.py)
- window/application APIs in [qplaywright/sync_api/_api.py](../qplaywright/sync_api/_api.py)
- package exports in [qplaywright/sync_api/__init__.py](../qplaywright/sync_api/__init__.py) and [qplaywright/__init__.py](../qplaywright/__init__.py)
- MCP tool contracts in [qplaywright/mcp_server.py](../qplaywright/mcp_server.py)

If any of those files end up needing changes, document the reason explicitly in the implementation PR or follow-up design note rather than letting scope drift silently.

## Acceptance Criteria

This issue is complete only when all of the following are true:

1. A user can resolve a table cell from a table locator by row and column.
2. A user can resolve a table cell by header name.
3. Table row resolution is defined against current view order after sorting and filtering.
4. A user can resolve a tree node from a tree locator by structured path.
5. Table cells and tree nodes support `text_content()`, `bounding_box()`, and pointer actions.
6. Pointer actions scroll items into view when possible and fail explicitly when no usable visual rectangle exists.
7. Tree nodes support `expand()` and `collapse()`.
8. Both Python and C++ agents implement the same protocol contract.
9. Focused tests cover success and failure cases for both table and tree flows.
10. The demo application includes both a visible table and a visible tree example.
11. `widget_tree()` remains widget-only and does not expose fake item nodes.
12. Docs and examples are updated in the same slice as the implementation.

## Recommendation

Do not treat issue #26 as a selector-mapping problem. The role mapping already exists.

Treat it as a missing structured item-view automation layer. The right fix is to add explicit item locators and protocol support over current model resolution, not to stretch the widget locator model until it also pretends to own non-widget descendants.
