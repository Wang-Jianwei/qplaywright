"""Locator — Playwright-compatible element locator for Qt widgets."""

from __future__ import annotations

import time
from typing import Any, TYPE_CHECKING

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
    METHOD_CHECK,
    METHOD_UNCHECK,
    METHOD_SELECT_OPTION,
    METHOD_TYPE,
    METHOD_PRESS,
    METHOD_HOVER,
    METHOD_FOCUS,
    METHOD_SCROLL,
    METHOD_SCREENSHOT_WIDGET,
    METHOD_WAIT_FOR,
)

if TYPE_CHECKING:
    from qplaywright.sync_api._connection import Connection


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
        timeout: float = 30.0,
    ):
        self._conn = conn
        self._selector = selector
        self._has_text = has_text
        self._parent_wid = parent_wid
        self._nth_index = nth_index
        self._widget_wid = widget_wid
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
            if self._nth_index is not None:
                p["nth"] = self._nth_index
        p.update(extra)
        return p

    def _send(self, method: str, **extra) -> Any:
        return self._conn.send(method, self._params(**extra), timeout=self._timeout)

    # -- Sub-locators --------------------------------------------------------

    def locator(self, selector: str, *, has_text: str | None = None) -> Locator:
        """Create a child locator scoped to this locator's matched widget."""
        # Resolve current widget to use as parent
        result = self._send(METHOD_FIND)
        if result is None:
            raise ValueError(f"Parent widget not found: {self._selector}")
        return Locator(
            self._conn,
            selector,
            has_text=has_text,
            parent_wid=result["wid"],
            timeout=self._timeout,
        )

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
        """Select the last matching widget — resolved at action time."""
        # We need to know the count first
        count = self.count()
        if count == 0:
            return self.nth(0)  # will raise when used
        return self.nth(count - 1)

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
        except RuntimeError:
            return False

    def is_enabled(self) -> bool:
        """Check if the widget is enabled."""
        try:
            return self._send(METHOD_IS_ENABLED)
        except RuntimeError:
            return False

    def is_checked(self) -> bool:
        """Check if the widget is checked."""
        try:
            return self._send(METHOD_IS_CHECKED)
        except RuntimeError:
            return False

    def is_hidden(self) -> bool:
        """Check if the widget is hidden."""
        return not self.is_visible()

    def is_disabled(self) -> bool:
        """Check if the widget is disabled."""
        return not self.is_enabled()

    def bounding_box(self) -> dict[str, int]:
        """Get the bounding box {x, y, width, height} in screen coordinates."""
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
        self._send(METHOD_CLICK, **kwargs)

    def dblclick(self, **kwargs) -> None:
        """Double-click the widget."""
        self._send(METHOD_DBLCLICK, **kwargs)

    def fill(self, value: str) -> None:
        """Fill the widget with the given value (clears first)."""
        self._send(METHOD_FILL, value=value)

    def invoke(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Invoke a custom widget method declared in qplaywrightClassMetadata.

        Arguments are sent as a named-argument mapping and the agent returns a
        structured invoke result: ``ok``, ``value``, ``errorCode``, and
        ``errorMessage``.
        """
        return self._send(METHOD_INVOKE, request={"method": name, "args": args or {}})

    def clear(self) -> None:
        """Clear the widget's text."""
        self._send(METHOD_CLEAR)

    def type(self, text: str, *, delay: int = 0) -> None:
        """Type text character by character."""
        self._send(METHOD_TYPE, text=text, delay=delay)

    def press(self, key: str) -> None:
        """Press a key (e.g., 'Enter', 'Tab', 'a')."""
        self._send(METHOD_PRESS, key=key)

    def check(self) -> None:
        """Check a checkbox."""
        self._send(METHOD_CHECK)

    def uncheck(self) -> None:
        """Uncheck a checkbox."""
        self._send(METHOD_UNCHECK)

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
        self._send(METHOD_SELECT_OPTION, **params)

    def hover(self) -> None:
        """Hover over the widget."""
        self._send(METHOD_HOVER)

    def focus(self) -> None:
        """Focus the widget."""
        self._send(METHOD_FOCUS)

    def scroll(self, *, delta_x: int = 0, delta_y: int = 0) -> None:
        """Send a mouse wheel scroll event to the widget."""
        self._send(METHOD_SCROLL, delta_x=delta_x, delta_y=delta_y)

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
        if state in ("checked", "unchecked"):
            deadline = time.monotonic() + t
            want_checked = state == "checked"
            while time.monotonic() < deadline:
                if self.count() > 0 and self.first().is_checked() == want_checked:
                    return
                time.sleep(0.05)
            raise TimeoutError(f"Timed out waiting for {self!r} to be {state}")

        params = self._params(state=state, timeout=int(t * 1000))
        self._conn.send(METHOD_WAIT_FOR, params, timeout=t + 5)

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
        if self._nth_index is not None:
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
