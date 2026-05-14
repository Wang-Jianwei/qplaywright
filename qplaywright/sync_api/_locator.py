"""Locator — Playwright-compatible element locator for Qt widgets."""

from __future__ import annotations

import time
from typing import Any, TYPE_CHECKING

from qplaywright.errors import QPlaywrightActionError, QPlaywrightAgentError, QPlaywrightLookupError
from qplaywright.protocol import (
    METHOD_FIND,
    METHOD_FIND_ALL,
    METHOD_COUNT,
    METHOD_GET_TEXT,
    METHOD_GET_VALUE,
    METHOD_GET_METHODS,
    METHOD_GET_PROPERTY,
    METHOD_GET_PROPERTIES,
    METHOD_IS_VISIBLE,
    METHOD_IS_ENABLED,
    METHOD_IS_CHECKED,
    METHOD_BOUNDING_BOX,
    METHOD_CLICK,
    METHOD_DBLCLICK,
    METHOD_FILL,
    METHOD_INVOKE,
    METHOD_CLEAR,
    METHOD_SELECT_OPTION,
    METHOD_TYPE,
    METHOD_PRESS,
    METHOD_HOVER,
    METHOD_FOCUS,
    METHOD_SCROLL,
    METHOD_SCREENSHOT_WIDGET,
    METHOD_WAIT_FOR,
    METHOD_ITEM_TEXT,
    METHOD_ITEM_PROPERTIES,
    METHOD_ITEM_VISIBLE,
    METHOD_ITEM_SELECTED,
    METHOD_ITEM_BOUNDING_BOX,
    METHOD_ITEM_CLICK,
    METHOD_ITEM_DBLCLICK,
    METHOD_ITEM_HOVER,
    METHOD_ITEM_EXPAND,
    METHOD_ITEM_COLLAPSE,
)

if TYPE_CHECKING:
    from qplaywright.sync_api._connection import Connection


def _normalize_tree_path(path: list[str | int]) -> list[str | int]:
    if not isinstance(path, list):
        raise TypeError("path must be a list")
    if not path:
        raise ValueError("path must not be empty")

    normalized: list[str | int] = []
    for segment in path:
        if isinstance(segment, bool):
            raise TypeError("tree path segments must be int or str")
        if isinstance(segment, int):
            if segment < 0:
                raise ValueError("tree path indices must be >= 0")
            normalized.append(segment)
            continue
        if isinstance(segment, str):
            if not segment:
                raise ValueError("tree path text segments must not be empty")
            normalized.append(segment)
            continue
        raise TypeError("tree path segments must be int or str")
    return normalized


class ItemLocator:
    """Locator for non-widget descendants owned by a table/tree/list/tab widget."""

    def __init__(self, conn: Connection, owner_wid: int, item: dict[str, Any], *, timeout: float = 30.0):
        self._conn = conn
        self._owner_wid = owner_wid
        self._item = dict(item)
        self._timeout = timeout

    def _params(self, **extra) -> dict[str, Any]:
        params: dict[str, Any] = {"wid": self._owner_wid, "item": dict(self._item)}
        params.update(extra)
        return params

    def _send(self, method: str, **extra) -> Any:
        return self._conn.send(method, self._params(**extra), timeout=self._timeout)

    def _send_action(self, action: str, method: str, **extra) -> Any:
        try:
            return self._send(method, **extra)
        except QPlaywrightAgentError as exc:
            raise QPlaywrightActionError(
                f"{action} failed for item target {self._item!r}: {exc}",
                code="action_failed",
                context={
                    "action": action,
                    "method": method,
                    "owner_wid": self._owner_wid,
                    "item": dict(self._item),
                },
            ) from exc

    def _kind(self) -> str:
        kind = self._item.get("kind")
        return str(kind) if isinstance(kind, str) else ""

    def _require_kind(self, *allowed: str, action: str) -> None:
        kind = self._kind()
        if kind in allowed:
            return
        allowed_text = ", ".join(sorted(allowed))
        raise ValueError(f"{action}() is only supported for {allowed_text} items; got {kind or 'unknown'}")

    def text_content(self) -> str:
        return self._send(METHOD_ITEM_TEXT)

    def inner_text(self) -> str:
        return self.text_content()

    def properties(self) -> dict[str, Any]:
        return self._send(METHOD_ITEM_PROPERTIES)

    def is_visible(self) -> bool:
        try:
            return self._send(METHOD_ITEM_VISIBLE)
        except QPlaywrightAgentError:
            return False

    def is_selected(self) -> bool:
        return bool(self._send(METHOD_ITEM_SELECTED))

    def bounding_box(self) -> list[int]:
        return self._send(METHOD_ITEM_BOUNDING_BOX)

    def click(self) -> None:
        self._send_action("click", METHOD_ITEM_CLICK)

    def dblclick(self) -> None:
        self._send_action("dblclick", METHOD_ITEM_DBLCLICK)

    def hover(self) -> None:
        self._send_action("hover", METHOD_ITEM_HOVER)

    def expand(self) -> None:
        self._require_kind("tree_node", action="expand")
        self._send_action("expand", METHOD_ITEM_EXPAND)

    def collapse(self) -> None:
        self._require_kind("tree_node", action="collapse")
        self._send_action("collapse", METHOD_ITEM_COLLAPSE)

    def __repr__(self) -> str:
        return f"ItemLocator(owner_wid={self._owner_wid}, item={self._item!r})"


class Locator:
    """Playwright-compatible locator for Qt widgets.

    Locators are lazy — they don't resolve widgets until an action is performed.
    This enables auto-waiting: if a widget isn't found immediately, the locator
    will retry until a timeout is reached.

    Usage::

        window.locator("role=button", has_text="OK").click()
        window.locator("#username").fill("admin")
        window.locator(".QLabel", has_text="Status").text_content()
    """

    def __init__(
        self,
        conn: Connection,
        selector: str,
        *,
        has_text: str | None = None,
        parent_wid: int | None = None,
        nth_index: int | None = None,
        widget_wid: int | None = None,
        is_last: bool = False,
        timeout: float = 30.0,
    ):
        self._conn = conn
        self._selector = selector
        self._has_text = has_text
        self._parent_wid = parent_wid
        self._nth_index = nth_index
        self._widget_wid = widget_wid
        self._is_last = is_last
        self._timeout = timeout

    def _params(self, **extra) -> dict:
        if self._widget_wid is not None:
            p: dict[str, Any] = {"wid": self._widget_wid}
        else:
            p = {"selector": self._selector}
            if self._has_text is not None:
                p["has_text"] = self._has_text
            if self._parent_wid is not None:
                p["parent_wid"] = self._parent_wid
            if self._is_last:
                # Call _conn.send directly (not _send) to avoid recursion:
                # _send → _params → _send.  We need the bare selector params
                # without nth to count all matches, then pick the last index.
                count = self._conn.send(METHOD_COUNT, p, timeout=self._timeout)
                p["nth"] = max(0, count - 1)
            elif self._nth_index is not None:
                p["nth"] = self._nth_index
        p.update(extra)
        return p

    def _send(self, method: str, **extra) -> Any:
        return self._conn.send(method, self._params(**extra), timeout=self._timeout)

    def _action_context(self) -> dict[str, Any]:
        return {
            "selector": self._selector,
            "has_text": self._has_text,
            "parent_wid": self._parent_wid,
            "widget_wid": self._widget_wid,
        }

    def _send_action(self, action: str, method: str, **extra) -> Any:
        try:
            return self._send(method, **extra)
        except QPlaywrightAgentError as exc:
            raise QPlaywrightActionError(
                f"{action} failed for locator {self!r}: {exc}",
                code="action_failed",
                context={
                    "action": action,
                    "method": method,
                    **self._action_context(),
                },
            ) from exc

    def _resolve_owner_wid(self) -> int:
        if self._widget_wid is not None:
            return self._widget_wid

        result = self._send(METHOD_FIND)
        if result is None:
            raise QPlaywrightLookupError(
                f"Widget not found: {self._selector}",
                code="widget_not_found",
                context={"selector": self._selector, "has_text": self._has_text},
            )
        return int(result["wid"])

    def _item_params(self, item: dict[str, Any], **extra) -> dict[str, Any]:
        params: dict[str, Any] = {"wid": self._resolve_owner_wid(), "item": dict(item)}
        params.update(extra)
        return params

    # -- Sub-locators --------------------------------------------------------

    def locator(self, selector: str, *, has_text: str | None = None) -> Locator:
        """Create a child locator scoped to this locator's matched widget."""
        # Resolve current widget to use as parent
        result = self._send(METHOD_FIND)
        if result is None:
            raise QPlaywrightLookupError(
                f"Parent widget not found: {self._selector}",
                code="widget_not_found",
                context={"selector": self._selector, "has_text": self._has_text},
            )
        return Locator(
            self._conn,
            selector,
            has_text=has_text,
            parent_wid=result["wid"],
            timeout=self._timeout,
        )

    def cell(self, row: int, column: int | str) -> ItemLocator:
        """Create an item locator for one table cell owned by this widget locator."""
        if isinstance(row, bool) or not isinstance(row, int):
            raise TypeError("row must be an int")

        item: dict[str, Any] = {"kind": "table_cell", "row": row}
        if isinstance(column, bool):
            raise TypeError("column must be an int or str")
        if isinstance(column, int):
            item["column"] = column
        elif isinstance(column, str):
            if not column:
                raise ValueError("column name must not be empty")
            item["columnName"] = column
        else:
            raise TypeError("column must be an int or str")

        return ItemLocator(self._conn, self._resolve_owner_wid(), item, timeout=self._timeout)

    def list_item(self, item: int | str) -> ItemLocator:
        descriptor: dict[str, Any] = {"kind": "list_item"}
        if isinstance(item, bool):
            raise TypeError("item must be an int or str")
        if isinstance(item, int):
            if item < 0:
                raise ValueError("list item index must be >= 0")
            descriptor["row"] = item
        elif isinstance(item, str):
            if not item:
                raise ValueError("list item text must not be empty")
            descriptor["text"] = item
        else:
            raise TypeError("item must be an int or str")

        return ItemLocator(self._conn, self._resolve_owner_wid(), descriptor, timeout=self._timeout)

    def node(self, path: list[str | int]) -> ItemLocator:
        item = {
            "kind": "tree_node",
            "path": _normalize_tree_path(path),
        }
        return ItemLocator(self._conn, self._resolve_owner_wid(), item, timeout=self._timeout)

    def root_node(self, index: int) -> ItemLocator:
        if isinstance(index, bool) or not isinstance(index, int):
            raise TypeError("index must be an int")
        if index < 0:
            raise ValueError("index must be >= 0")
        return self.node([index])

    def tab(self, tab: int | str) -> ItemLocator:
        descriptor: dict[str, Any] = {"kind": "tab_item"}
        if isinstance(tab, bool):
            raise TypeError("tab must be an int or str")
        if isinstance(tab, int):
            if tab < 0:
                raise ValueError("tab index must be >= 0")
            descriptor["index"] = tab
        elif isinstance(tab, str):
            if not tab:
                raise ValueError("tab label must not be empty")
            descriptor["label"] = tab
        else:
            raise TypeError("tab must be an int or str")

        return ItemLocator(self._conn, self._resolve_owner_wid(), descriptor, timeout=self._timeout)

    def nth(self, index: int) -> Locator:
        """Select the nth matching widget (0-based)."""
        return Locator(
            self._conn,
            self._selector,
            has_text=self._has_text,
            parent_wid=self._parent_wid,
            nth_index=index,
            widget_wid=self._widget_wid,
            timeout=self._timeout,
        )

    def first(self) -> Locator:
        """Select the first matching widget."""
        return self.nth(0)

    def last(self) -> Locator:
        """Select the last matching widget — resolved lazily at action time."""
        return Locator(
            self._conn,
            self._selector,
            has_text=self._has_text,
            parent_wid=self._parent_wid,
            is_last=True,
            timeout=self._timeout,
        )

    # -- Queries (read-only) -------------------------------------------------

    def count(self) -> int:
        """Return the number of matching widgets."""
        return self._send(METHOD_COUNT)

    def text_content(self) -> str:
        """Get the text content of the widget."""
        return self._send(METHOD_GET_TEXT)

    def inner_text(self) -> str:
        """Alias for text_content (Qt widgets don't distinguish)."""
        return self.text_content()

    def input_value(self) -> str:
        """Get the current value of an input widget."""
        return self._send(METHOD_GET_VALUE)

    def methods(self) -> list[dict[str, Any]]:
        """Return exposed custom methods and any declared argument metadata."""
        return self._send(METHOD_GET_METHODS)

    def get_attribute(self, name: str) -> Any:
        """Get a Qt property value."""
        return self._send(METHOD_GET_PROPERTY, property=name)

    def properties(self) -> dict[str, Any]:
        """Return all readable Qt properties exposed by the widget."""
        return self._send(METHOD_GET_PROPERTIES)

    def is_visible(self) -> bool:
        """Check if the widget is visible."""
        try:
            return self._send(METHOD_IS_VISIBLE)
        except QPlaywrightAgentError:
            return False

    def is_enabled(self) -> bool:
        """Check if the widget is enabled."""
        try:
            return self._send(METHOD_IS_ENABLED)
        except QPlaywrightAgentError:
            return False

    def is_checked(self) -> bool:
        """Check if the widget is checked."""
        try:
            return self._send(METHOD_IS_CHECKED)
        except QPlaywrightAgentError:
            return False

    def is_hidden(self) -> bool:
        """Check if the widget is hidden."""
        return not self.is_visible()

    def is_disabled(self) -> bool:
        """Check if the widget is disabled."""
        return not self.is_enabled()

    def bounding_box(self) -> list[int]:
        """Get the bounding box as [x, y, width, height] in screen coordinates."""
        return self._send(METHOD_BOUNDING_BOX)

    def all(self) -> list[Locator]:
        """Return a list of Locators, one per matching widget."""
        results = self._send(METHOD_FIND_ALL)
        return [
            Locator(self._conn, self._selector, has_text=self._has_text,
                    parent_wid=self._parent_wid, widget_wid=r["wid"], timeout=self._timeout)
            for r in results
        ]

    def all_text_contents(self) -> list[str]:
        """Return the text content of all matching widgets."""
        results = self._send(METHOD_FIND_ALL)
        return [r.get("text", "") for r in results]

    # -- Actions -------------------------------------------------------------

    def click(self, **kwargs) -> None:
        """Click the widget."""
        self._send_action("click", METHOD_CLICK, **kwargs)

    def dblclick(self, **kwargs) -> None:
        """Double-click the widget."""
        self._send_action("dblclick", METHOD_DBLCLICK, **kwargs)

    def fill(self, value: str) -> None:
        """Fill the widget with the given value (clears first)."""
        self._send_action("fill", METHOD_FILL, value=value)

    def invoke(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Invoke a custom widget method declared in qplaywrightClassMetadata.

        Arguments are sent as a named-argument mapping and the agent returns a
        structured invoke result: ``ok``, ``value``, ``errorCode``, and
        ``errorMessage``.
        """
        try:
            return self._send(METHOD_INVOKE, request={"method": name, "args": args or {}})
        except QPlaywrightAgentError as exc:
            raise QPlaywrightActionError(
                f"invoke failed for locator {self!r}: {exc}",
                code="action_failed",
                context={
                    "action": "invoke",
                    "method": METHOD_INVOKE,
                    "invoke_name": name,
                    **self._action_context(),
                },
            ) from exc

    def clear(self) -> None:
        """Clear the widget's text."""
        self._send_action("clear", METHOD_CLEAR)

    def type(self, text: str, *, delay: int = 0) -> None:
        """Type text character by character."""
        self._send_action("type", METHOD_TYPE, text=text, delay=delay)

    def press(self, key: str) -> None:
        """Press a key (e.g., 'Enter', 'Tab', 'a')."""
        self._send_action("press", METHOD_PRESS, key=key)

    def select_option(
        self,
        value: str | None = None,
        *,
        index: int | None = None,
        label: str | None = None,
    ) -> None:
        """Select an option in a combobox."""
        params: dict[str, Any] = {}
        if value is not None:
            params["value"] = value
        if index is not None:
            params["index"] = index
        if label is not None:
            params["label"] = label
        self._send_action("select_option", METHOD_SELECT_OPTION, **params)

    def hover(self) -> None:
        """Hover over the widget."""
        self._send_action("hover", METHOD_HOVER)

    def focus(self) -> None:
        """Focus the widget."""
        self._send_action("focus", METHOD_FOCUS)

    def scroll(self, *, delta_x: int = 0, delta_y: int = 0) -> None:
        """Send a mouse wheel scroll event to the widget."""
        self._send_action("scroll", METHOD_SCROLL, delta_x=delta_x, delta_y=delta_y)

    def scroll_into_view_if_needed(self) -> None:
        """No-op for Qt (widgets are always in view if visible)."""
        pass

    def screenshot(
        self,
        *,
        path: str | None = None,
        x: int | None = None,
        y: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | dict:
        """Take a screenshot of this specific widget or a clipped region inside it."""
        params = self._params()
        if path:
            params["path"] = path
        if x is not None:
            params["x"] = x
        if y is not None:
            params["y"] = y
        if width is not None:
            params["width"] = width
        if height is not None:
            params["height"] = height
        return self._conn.send(METHOD_SCREENSHOT_WIDGET, params, timeout=self._timeout)

    # -- Waiting -------------------------------------------------------------

    def wait_for(self, *, state: str = "visible", timeout: float | None = None) -> None:
        """Wait for the widget to reach a state: visible, hidden, enabled, disabled."""
        t = timeout or self._timeout
        if self._widget_wid is not None and state in ("visible", "hidden", "enabled", "disabled"):
            deadline = time.monotonic() + t
            while time.monotonic() < deadline:
                if state == "visible" and self.is_visible():
                    return
                if state == "hidden" and not self.is_visible():
                    return
                if state == "enabled" and self.is_enabled():
                    return
                if state == "disabled" and not self.is_enabled():
                    return
                time.sleep(0.05)
            raise TimeoutError(f"Timed out waiting for {self!r} to be {state}")

        if state in ("checked", "unchecked"):
            deadline = time.monotonic() + t
            want_checked = state == "checked"
            while time.monotonic() < deadline:
                if self.count() > 0 and self.first().is_checked() == want_checked:
                    return
                time.sleep(0.05)
            raise TimeoutError(f"Timed out waiting for {self!r} to be {state}")

        params = self._params(state=state, timeout=int(t * 1000))
        try:
            self._conn.send(METHOD_WAIT_FOR, params, timeout=t + 5)
        except QPlaywrightAgentError as exc:
            raise QPlaywrightActionError(
                f"wait_for failed for locator {self!r}: {exc}",
                code="action_failed",
                context={
                    "action": "wait_for",
                    "method": METHOD_WAIT_FOR,
                    "state": state,
                    **self._action_context(),
                },
            ) from exc

    # -- Expect (convenience) ------------------------------------------------

    @property
    def expect(self) -> _LocatorExpect:
        return _LocatorExpect(self)

    # -- Repr ----------------------------------------------------------------

    def __repr__(self) -> str:
        if self._widget_wid is not None:
            parts = [f"Locator(wid={self._widget_wid}"]
        else:
            parts = [f"Locator({self._selector!r}"]
        if self._has_text:
            parts.append(f", has_text={self._has_text!r}")
        if self._is_last:
            parts.append(", last")
        elif self._nth_index is not None:
            parts.append(f", nth={self._nth_index}")
        parts.append(")")
        return "".join(parts)


# --------------------------------------------------------------------------- #
#  Expect — assertion helpers attached to Locator                              #
# --------------------------------------------------------------------------- #

class _LocatorExpect:
    """Playwright-style expect assertions for a Locator."""

    def __init__(self, locator: Locator, *, timeout: float = 5.0):
        self._locator = locator
        self._timeout = timeout

    def _poll(self, check, message: str, timeout: float | None = None):
        t = timeout or self._timeout
        deadline = time.monotonic() + t
        last_error = None
        while time.monotonic() < deadline:
            try:
                if check():
                    return
            except Exception as e:
                last_error = e
            time.sleep(0.1)
        raise AssertionError(f"{message} (timed out after {t}s, last error: {last_error})")

    def to_be_visible(self, *, timeout: float | None = None) -> None:
        self._poll(lambda: self._locator.is_visible(), "Expected widget to be visible", timeout)

    def to_be_hidden(self, *, timeout: float | None = None) -> None:
        self._poll(lambda: self._locator.is_hidden(), "Expected widget to be hidden", timeout)

    def to_be_enabled(self, *, timeout: float | None = None) -> None:
        self._poll(lambda: self._locator.is_enabled(), "Expected widget to be enabled", timeout)

    def to_be_disabled(self, *, timeout: float | None = None) -> None:
        self._poll(lambda: self._locator.is_disabled(), "Expected widget to be disabled", timeout)

    def to_be_checked(self, *, timeout: float | None = None) -> None:
        self._poll(lambda: self._locator.is_checked(), "Expected widget to be checked", timeout)

    def to_have_text(self, text: str, *, timeout: float | None = None) -> None:
        self._poll(
            lambda: self._locator.text_content() == text,
            f"Expected text to be {text!r}",
            timeout,
        )

    def to_contain_text(self, text: str, *, timeout: float | None = None) -> None:
        self._poll(
            lambda: text.lower() in self._locator.text_content().lower(),
            f"Expected text to contain {text!r}",
            timeout,
        )

    def to_have_value(self, value: str, *, timeout: float | None = None) -> None:
        self._poll(
            lambda: str(self._locator.input_value()) == value,
            f"Expected value to be {value!r}",
            timeout,
        )

    def to_have_count(self, count: int, *, timeout: float | None = None) -> None:
        self._poll(
            lambda: self._locator.count() == count,
            f"Expected count to be {count}",
            timeout,
        )

    def not_to_be_visible(self, *, timeout: float | None = None) -> None:
        self.to_be_hidden(timeout=timeout)

    def not_to_be_checked(self, *, timeout: float | None = None) -> None:
        self._poll(lambda: not self._locator.is_checked(), "Expected widget not to be checked", timeout)
