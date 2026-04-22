"""Selector engine — parses Playwright-style selectors and matches Qt widgets."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from qplaywright.protocol import ROLE_MAP

if TYPE_CHECKING:
    from typing import Sequence


_MISSING = object()
_QPLAYWRIGHT_CLASS_METADATA_PROP = "qplaywrightClassMetadata"


def _qt_property(widget, name: str):
    prop = getattr(widget, "property", None)
    if not callable(prop):
        return None
    try:
        return prop(name)
    except TypeError:
        return prop(name.encode())


def _qt_property_exists(widget, name: str) -> bool:
    meta_object = getattr(widget, "metaObject", None)
    if not callable(meta_object):
        return False
    meta = meta_object()
    if meta is None or not hasattr(meta, "indexOfProperty"):
        return False
    try:
        return meta.indexOfProperty(name) >= 0
    except TypeError:
        return meta.indexOfProperty(name.encode()) >= 0


def _invoke_named_method(widget, name: str, *args):
    fn = getattr(widget, name, None)
    if callable(fn):
        return fn(*args)
    return _MISSING


def _normalize_string_list(value) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (str, bytes, bytearray)):
        text = value.decode() if isinstance(value, (bytes, bytearray)) else value
        return [item.strip() for item in text.replace(";", ",").split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        try:
            items = list(value)
        except TypeError:
            items = [value]
    return [str(item).strip() for item in items if str(item).strip()]


def _normalize_metadata_map(value) -> dict:
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "items"):
        return {str(key): item for key, item in value.items()}
    raise TypeError(f"qplaywrightClassMetadata must be a mapping, got {type(value).__name__}")


def _declared_class_metadata(widget) -> dict:
    return _normalize_metadata_map(_qt_property(widget, _QPLAYWRIGHT_CLASS_METADATA_PROP))


def _normalize_method_arg_schema(value) -> dict:
    if isinstance(value, str):
        return {
            "name": value,
            "type": "QVariant",
            "brief": "",
            "required": True,
            "defaultValue": None,
        }

    if not isinstance(value, dict):
        raise TypeError(f"Method arg schema must be a dict or string, got {type(value).__name__}")

    return {
        "name": str(value.get("name", "")).strip(),
        "type": str(value.get("type", "QVariant") or "QVariant"),
        "brief": str(value.get("brief", "") or ""),
        "required": bool(value.get("required", True)),
        "defaultValue": value.get("defaultValue"),
    }


def _normalize_method_schema_entry(value) -> dict:
    if isinstance(value, str):
        return {
            "name": value,
            "args": [],
            "returnType": "QVariant",
            "brief": "",
        }

    if not isinstance(value, dict):
        raise TypeError(f"Method schema entry must be a dict or string, got {type(value).__name__}")

    raw_args = value.get("args", [])
    if raw_args is None:
        raw_args = []
    if not isinstance(raw_args, (list, tuple)):
        raise TypeError("Method schema 'args' must be a list")

    normalized = {
        "name": str(value.get("name", "")).strip(),
        "args": [_normalize_method_arg_schema(arg) for arg in raw_args],
        "returnType": str(value.get("returnType", "QVariant") or "QVariant"),
        "brief": str(value.get("brief", "") or ""),
    }
    if not normalized["name"]:
        raise ValueError("Method schema entry is missing a name")
    return normalized


def _declared_method_schema(widget) -> list[dict]:
    metadata = _declared_class_metadata(widget)
    methods = metadata.get("methods", [])
    if methods is None:
        methods = []
    if not isinstance(methods, (list, tuple)):
        raise TypeError("qplaywrightClassMetadata.methods must be a list")
    return [_normalize_method_schema_entry(item) for item in methods]


def _declared_method_schema_entry(widget, name: str) -> dict:
    for entry in _declared_method_schema(widget):
        if entry["name"] == name:
            return entry
    raise ValueError(f"Method is not exposed: {name}")


def _declared_role(widget) -> str:
    metadata = _declared_class_metadata(widget)
    return str(metadata.get("role", "") or "").strip().lower()


def _convert_invoke_argument(value, declared_type: str):
    if not declared_type or declared_type == "QVariant":
        return value
    if declared_type == "QString":
        return "" if value is None else str(value)
    if declared_type == "int":
        if isinstance(value, bool):
            raise TypeError("Cannot convert value to int")
        return int(value)
    if declared_type == "double":
        if isinstance(value, bool):
            raise TypeError("Cannot convert value to double")
        return float(value)
    if declared_type == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True
            if lowered in {"false", "0", "no", "off"}:
                return False
            raise TypeError("Cannot convert value to bool")
        if isinstance(value, (int, float)):
            return bool(value)
        raise TypeError("Cannot convert value to bool")
    if declared_type == "QStringList":
        if isinstance(value, (list, tuple)):
            return ["" if item is None else str(item) for item in value]
        raise TypeError("Cannot convert value to QStringList")
    raise TypeError(f"Unsupported target type: {declared_type}")


def _prepare_invoke_call(widget, request: dict) -> dict:
    if not isinstance(request, dict):
        raise TypeError("Invoke request must be a mapping")

    name = str(request.get("method", "") or "").strip()
    if not name:
        raise ValueError("Method name is required")

    method_schema = _declared_method_schema_entry(widget, name)
    provided_args = request.get("args", {})
    if provided_args is None:
        provided_args = {}
    if not isinstance(provided_args, dict):
        raise TypeError("Invoke request args must be a mapping")

    ordered_args: list = []
    remaining = set(provided_args)
    for arg in method_schema["args"]:
        arg_name = arg["name"]
        if arg_name in provided_args:
            raw_value = provided_args[arg_name]
            remaining.remove(arg_name)
        elif not arg["required"]:
            raw_value = arg.get("defaultValue")
        else:
            raise ValueError(f"Missing required argument: {arg_name}")

        try:
            ordered_args.append(_convert_invoke_argument(raw_value, arg["type"]))
        except (TypeError, ValueError) as exc:
            raise TypeError(f"Argument {arg_name}: {exc}") from exc

    if remaining:
        unexpected = sorted(remaining)[0]
        raise ValueError(f"Unexpected argument: {unexpected}")

    return {
        "method": method_schema,
        "orderedArgs": ordered_args,
    }


def _execute_prepared_call(widget, prepared_call: dict):
    method_schema = prepared_call["method"]
    name = method_schema["name"]
    fn = getattr(widget, name, None)
    if not callable(fn):
        raise ValueError(f"Exposed method is missing or not callable: {name}")
    return fn(*prepared_call.get("orderedArgs", []))


def _invoke_method(widget, request: dict):
    prepared_call = _prepare_invoke_call(widget, request)
    return _execute_prepared_call(widget, prepared_call)


def _widget_value(widget):
    if hasattr(widget, "value"):
        return widget.value()
    if hasattr(widget, "currentText"):
        return widget.currentText()
    return _widget_text(widget)


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
    declared_role = _declared_role(widget)
    if declared_role and role.lower() == declared_role:
        return True
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

    declared_role = _declared_role(widget)
    if declared_role:
        info["roles"] = [declared_role]

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
