# QAction causes agent crash when traversing widget tree

## Summary

When the demo application uses QMenuBar with QAction items, the qplaywright agent crashes with `'PySide6.QtGui.QAction' object has no attribute 'x'` when attempting to take snapshots or inspect widgets.

## Environment

- Platform: Windows (win32)
- Python + PySide6
- qplaywright from source

## Steps to Reproduce

1. Run the demo app with menu bar:
   ```bash
   python examples/demo_app.py
   ```

2. Connect via MCP:
   ```python
   qplaywright_session(action="attach", host="127.0.0.1", port=19876)
   ```

3. Attempt to take a snapshot:
   ```
   qplaywright_snapshot(topmost_only=False)
   ```

## Expected Behavior

Snapshot should return a valid widget tree without crashing.

## Actual Behavior

```
Error executing tool snapshot: Agent error: 'PySide6.QtGui.QAction' object has no attribute 'x'
```

## Root Cause Analysis

In `qplaywright/agent/_selector.py`, the `widget_to_dict()` function serializes widgets but assumes all children returned by `widget.children()` are `QWidget` instances with geometry methods.

However, `QMenuBar.children()` includes `QAction` objects (from `QtGui`), not `QWidget` objects (from `QtWidgets`). `QAction` has `isVisible()` method (inherited from `QObject`) but does NOT have `.x()`, `.y()`, `.width()`, or `.height()` geometry methods.

The problematic code at line 583-586:

```python
if depth < max_depth:
    children = []
    for child in widget.children():
        if isinstance(child, QWidget):  # <-- This check was added but...
            children.append(widget_to_dict(child, depth=depth + 1, max_depth=max_depth))
```

Wait, actually the fix was applied but the server wasn't restarted. However, there may still be other locations that need fixing.

## Affected Code Locations

1. **`qplaywright/agent/_selector.py`** line 583-586:
   - The `widget_to_dict()` function recurses into `widget.children()` without verifying each child is a `QWidget` before calling geometry methods on it.

2. **Other potential locations** - There may be similar issues in `_server.py` where widgets are traversed.

## Attempted Fix

In `_selector.py`, tried adding `isinstance(child, QWidget)` check:

```python
for child in widget.children():
    if isinstance(child, QWidget):  # skip non-widget QObjects
        children.append(widget_to_dict(child, depth=depth + 1, max_depth=max_depth))
```

But the agent still crashed, suggesting either:
1. The server needs a full restart to load the updated code
2. There are other locations in the codebase with the same issue

## Demo App Code That Triggers the Bug

The demo app creates a menu bar like this:

```python
def _create_menu_bar(self):
    menubar = self.menuBar()
    menubar.setObjectName("menubar")

    file_menu = menubar.addMenu("File")
    file_menu.setObjectName("menu_file")

    new_action = QAction("New", self)
    new_action.setObjectName("action_new")
    file_menu.addAction(new_action)
```

When `menuBar()` is called, Qt creates internal `QAction` objects that appear in the widget children tree, but they are `QtGui.QAction`, not `QtWidgets.QWidget`.

## Impact

- Cannot use `snapshot` or `inspect` tools on applications with menu bars
- The demo app becomes difficult to automate after the menu bar is created

## Suggested Fixes

1. **Quick fix**: Add `isinstance(child, QWidget)` checks in all recursion points that call geometry methods on widget children.

2. **Robust fix**: Check for geometry methods availability before calling them:
   ```python
   if hasattr(child, 'x') and hasattr(child, 'width'):  # Verify it's a widget with geometry
   ```

3. **Defensive fix**: Filter out `QAction` and other non-widget `QObject` subclasses explicitly:
   ```python
   from PySide6.QtWidgets import QWidget
   from PySide6.QtGui import QAction

   if isinstance(child, QWidget) and not isinstance(child, QAction):
   ```

## Verification Steps

After fixing, run:
```bash
python examples/demo_app.py
```

Then connect via MCP and verify:
1. `snapshot` returns valid tree without QAction objects
2. `inspect` works at any depth
3. Menu bar actions are still accessible via click/input

## Additional Context

The same `QAction` issue may also affect:
- `QToolBar` (which also contains actions)
- `QMenu` (which contains actions)
- Any widget that mixes `QWidget` children with `QAction` children
