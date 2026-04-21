"""Selector engine — parses Playwright-style selectors and matches Qt widgets."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from qplaywright.protocol import ROLE_MAP

if TYPE_CHECKING:
    from typing import Sequence


def _widget_text(widget) -> str:
    """Extract the visible text from a widget, trying common Qt accessors."""
    for attr in ("text", "title", "windowTitle", "placeholderText", "toolTip"):
        fn = getattr(widget, attr, None)
        if callable(fn):
            val = fn()
            if val:
                return str(val)
    # QComboBox current text
    if hasattr(widget, "currentText"):
        return str(widget.currentText())
    # QLabel via accessible name
    if hasattr(widget, "accessibleName"):
        name = widget.accessibleName()
        if name:
            return name
    return ""


def _widget_class_name(widget) -> str:
    mo = widget.metaObject()
    return mo.className() if mo else type(widget).__name__


def _class_hierarchy(widget) -> list[str]:
    """Return the full class hierarchy of a widget."""
    classes = []
    mo = widget.metaObject()
    while mo:
        classes.append(mo.className())
        mo = mo.superClass()
    return classes


def _matches_role(widget, role: str) -> bool:
    """Check if widget matches a Playwright-style role."""
    target_classes = ROLE_MAP.get(role.lower(), [])
    if not target_classes:
        return False
    hierarchy = _class_hierarchy(widget)
    return any(cls in target_classes for cls in hierarchy)


def _matches_text_exact(widget, text: str) -> bool:
    return _widget_text(widget) == text


def _matches_text_regex(widget, pattern: str, flags: int = 0) -> bool:
    return bool(re.search(pattern, _widget_text(widget), flags))


def _matches_has_text(widget, text: str) -> bool:
    return text.lower() in _widget_text(widget).lower()


def _matches_class(widget, class_name: str) -> bool:
    return class_name in _class_hierarchy(widget)


def _matches_object_name(widget, name: str) -> bool:
    return widget.objectName() == name


# --------------------------------------------------------------------------- #
#  Selector parser                                                             #
# --------------------------------------------------------------------------- #

_REGEX_SELECTOR = re.compile(
    r"^(?:"
    r"role=(?P<role>\w+)"            # role=button
    r"|text=(?P<text>.+)"            # text=Submit  or  text=/regex/flags
    r"|has-text=(?P<has_text>.+)"    # has-text=Submit
    r"|name=(?P<name>\w+)"           # name=objectName
    r"|#(?P<id>\w+)"                 # #objectName
    r"|\.(?P<cls>\w+)"               # .ClassName
    r")$"
)

_REGEX_TEXT_PATTERN = re.compile(r"^/(.+)/([imsx]*)$")


def parse_selector(selector: str) -> dict:
    """Parse a selector string into a matcher descriptor.

    Returns a dict with keys like ``role``, ``text``, ``has_text``, ``name``,
    ``class_name`` depending on the selector type.
    """
    selector = selector.strip()
    m = _REGEX_SELECTOR.match(selector)
    if m:
        return {k: v for k, v in m.groupdict().items() if v is not None}

    # Fallback: treat bare string as text= selector
    return {"text": selector}


def match_widget(widget, selector_str: str, *, has_text: str | None = None) -> bool:
    """Return True if *widget* matches the selector and optional filters."""
    parsed = parse_selector(selector_str)

    if "role" in parsed and not _matches_role(widget, parsed["role"]):
        return False

    if "text" in parsed:
        text_val = parsed["text"]
        # Check for regex pattern /pattern/flags
        rm = _REGEX_TEXT_PATTERN.match(text_val)
        if rm:
            pattern, flag_str = rm.groups()
            flags = 0
            if "i" in flag_str:
                flags |= re.IGNORECASE
            if not _matches_text_regex(widget, pattern, flags):
                return False
        else:
            if not _matches_text_exact(widget, text_val):
                return False

    if "has_text" in parsed and not _matches_has_text(widget, parsed["has_text"]):
        return False

    if "name" in parsed and not _matches_object_name(widget, parsed["name"]):
        return False

    if "id" in parsed and not _matches_object_name(widget, parsed["id"]):
        return False

    if "cls" in parsed and not _matches_class(widget, parsed["cls"]):
        return False

    # Additional filter from keyword arg
    if has_text is not None and not _matches_has_text(widget, has_text):
        return False

    return True


def find_widgets(
    root_widgets: Sequence,
    selector: str,
    *,
    has_text: str | None = None,
    visible_only: bool = True,
) -> list:
    """Find all widgets under *root_widgets* matching the selector."""
    results = []

    def _walk(widget):
        if visible_only and not widget.isVisible():
            return
        if match_widget(widget, selector, has_text=has_text):
            results.append(widget)
        for child in widget.children():
            if hasattr(child, "isVisible"):  # skip non-widget QObjects
                _walk(child)

    for root in root_widgets:
        _walk(root)

    return results


def widget_to_dict(widget, *, depth: int = 0, max_depth: int = 50) -> dict:
    """Serialize a widget to a JSON-friendly dict."""
    info: dict = {
        "class": _widget_class_name(widget),
        "objectName": widget.objectName() or "",
        "text": _widget_text(widget),
        "visible": widget.isVisible(),
        "enabled": widget.isEnabled(),
        "geometry": {
            "x": widget.x(),
            "y": widget.y(),
            "width": widget.width(),
            "height": widget.height(),
        },
    }

    if hasattr(widget, "isChecked"):
        info["checked"] = widget.isChecked()

    if hasattr(widget, "currentText"):
        info["currentText"] = widget.currentText()
        info["currentIndex"] = widget.currentIndex()

    if hasattr(widget, "value"):
        info["value"] = widget.value()

    if depth < max_depth:
        children = []
        for child in widget.children():
            if hasattr(child, "isVisible"):
                children.append(widget_to_dict(child, depth=depth + 1, max_depth=max_depth))
        if children:
            info["children"] = children

    return info
