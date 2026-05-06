"""Protocol definitions shared between agent and client.

Uses JSON Lines over TCP. Each message is a single JSON object followed by a newline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# Default port for the agent server
DEFAULT_PORT = 19876
DEFAULT_HOST = "127.0.0.1"

# Sentinel for missing values (distinct from None)
MISSING = object()


# --------------------------------------------------------------------------- #
#  Messages                                                                    #
# --------------------------------------------------------------------------- #

@dataclass
class Request:
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    id: int = 0

    def to_bytes(self) -> bytes:
        return json.dumps({"id": self.id, "method": self.method, "params": self.params}).encode() + b"\n"

    @classmethod
    def from_dict(cls, d: dict) -> Request:
        return cls(method=d["method"], params=d.get("params", {}), id=d.get("id", 0))


@dataclass
class Response:
    id: int
    result: Any = None
    error: str | None = None

    def to_bytes(self) -> bytes:
        d: dict[str, Any] = {"id": self.id}
        if self.error is not None:
            d["error"] = {"message": self.error}
        else:
            d["result"] = self.result
        return json.dumps(d).encode() + b"\n"

    @classmethod
    def from_dict(cls, d: dict) -> Response:
        err = d.get("error")
        return cls(
            id=d["id"],
            result=d.get("result"),
            error=err["message"] if isinstance(err, dict) else err,
        )


@dataclass
class QPlaywrightMethodArg:
    name: str = ""
    type: str = "QVariant"
    brief: str = ""
    required: bool = True
    default_value: Any = field(default=MISSING)

    def has_default_value(self) -> bool:
        return self.default_value is not MISSING

    def to_variant_map(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "brief": self.brief,
            "required": self.required,
            "defaultValue": None if self.default_value is MISSING else self.default_value,
        }


@dataclass
class QPlaywrightClassMethod:
    name: str = ""
    return_type: str = "QVariant"
    brief: str = ""
    args: list[QPlaywrightMethodArg] = field(default_factory=list)

    def add_arg(self, arg: QPlaywrightMethodArg) -> QPlaywrightClassMethod:
        self.args.append(arg)
        return self

    def signature(self) -> str:
        return f"{self.name}({', '.join(arg.type for arg in self.args)})"

    def to_variant_map(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "args": [arg.to_variant_map() for arg in self.args],
            "returnType": self.return_type,
            "brief": self.brief,
        }


@dataclass
class QPlaywrightClassMetadata:
    role: str = ""
    methods: list[QPlaywrightClassMethod] = field(default_factory=list)

    def add_method(self, method: QPlaywrightClassMethod) -> QPlaywrightClassMetadata:
        self.methods.append(method)
        return self

    def has_method(self, name: str) -> bool:
        return any(method.name == name for method in self.methods)

    def find_method(self, name: str) -> QPlaywrightClassMethod | None:
        for method in self.methods:
            if method.name == name:
                return method
        return None

    def to_variant_map(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "methods": [method.to_variant_map() for method in self.methods],
        }


def decode_line(line: bytes) -> dict:
    """Decode a single JSON line."""
    return json.loads(line.strip())


# --------------------------------------------------------------------------- #
#  Method constants                                                            #
# --------------------------------------------------------------------------- #

# Widget discovery
METHOD_FIND = "find"
METHOD_FIND_ALL = "find_all"
METHOD_WIDGET_TREE = "widget_tree"
METHOD_GET_PROPERTY = "get_property"
METHOD_GET_PROPERTIES = "get_properties"
METHOD_GET_TEXT = "get_text"
METHOD_GET_VALUE = "get_value"
METHOD_GET_METHODS = "get_methods"
METHOD_IS_VISIBLE = "is_visible"
METHOD_IS_ENABLED = "is_enabled"
METHOD_IS_CHECKED = "is_checked"
METHOD_COUNT = "count"
METHOD_BOUNDING_BOX = "bounding_box"

# Actions
METHOD_CLICK = "click"
METHOD_DBLCLICK = "dblclick"
METHOD_FILL = "fill"
METHOD_INVOKE = "invoke"
METHOD_CLEAR = "clear"
METHOD_CHECK = "check"
METHOD_UNCHECK = "uncheck"
METHOD_SELECT_OPTION = "select_option"
METHOD_TYPE = "type"
METHOD_PRESS = "press"
METHOD_HOVER = "hover"
METHOD_FOCUS = "focus"
METHOD_SCROLL = "scroll"

# Screenshot
METHOD_SCREENSHOT = "screenshot"
METHOD_SCREENSHOT_WIDGET = "screenshot_widget"

# Window
METHOD_LIST_WINDOWS = "list_windows"
METHOD_WINDOW_TITLE = "window_title"
METHOD_WINDOW_SIZE = "window_size"
METHOD_WINDOW_RESIZE = "window_resize"
METHOD_WINDOW_CLOSE = "window_close"

# Utility
METHOD_WAIT_FOR = "wait_for"
METHOD_PING = "ping"
METHOD_SET_SESSION_INFO = "set_session_info"


# --------------------------------------------------------------------------- #
#  Selector format                                                             #
# --------------------------------------------------------------------------- #
# Selectors follow a Playwright-inspired syntax adapted for Qt widgets:
#
#   role=button          →  match by widget role (QPushButton, QToolButton → button)
#   text=Submit          →  match by visible text (exact)
#   text=/sub/i          →  match by text (regex, case-insensitive)
#   a11y-name=Submit     →  match by accessibleName (exact)
#   a11y-desc=Help text  →  match by accessibleDescription (exact)
#   #objectName          →  match by QObject.objectName()
#   .ClassName           →  match by metaObject()->className()
#   name=objectName      →  alias for #objectName
#   has-text=partial     →  contains text (case-insensitive)
#
# Custom widgets declare automation metadata through the Qt dynamic property
# qplaywrightClassMetadata. Public authoring should use the builder objects
# QPlaywrightClassMetadata / QPlaywrightClassMethod / QPlaywrightMethodArg.
# Their serialized shape is:
#
#   role     → one Playwright-style role such as textbox or button
#   methods  → list of method declarations used by methods() and invoke()
#
# Each method declaration follows this shape:
#
#   {name, args, returnType, brief}
#
# where each args entry is:
#
#   {name, type, brief, required, defaultValue}
#
# Filters (keyword args to locator()):
#   has_text="..."       →  same as has-text=
#   has=locator          →  must contain descendant matching another locator
#   nth(n)               →  select the nth match (0-based)

# Qt class → role mapping
ROLE_MAP: dict[str, list[str]] = {
    "button": ["QPushButton", "QToolButton", "QCommandLinkButton"],
    "checkbox": ["QCheckBox"],
    "radio": ["QRadioButton"],
    "textbox": ["QLineEdit"],
    "textarea": ["QTextEdit", "QPlainTextEdit"],
    "input": ["QLineEdit", "QTextEdit", "QPlainTextEdit"],
    "combobox": ["QComboBox"],
    "slider": ["QSlider"],
    "spinbox": ["QSpinBox", "QDoubleSpinBox"],
    "tab": ["QTabBar"],
    "tabwidget": ["QTabWidget"],
    "table": ["QTableWidget", "QTableView"],
    "tree": ["QTreeWidget", "QTreeView"],
    "list": ["QListWidget", "QListView"],
    "menu": ["QMenu"],
    "menubar": ["QMenuBar"],
    "menuitem": ["QAction"],
    "dialog": ["QDialog"],
    "label": ["QLabel"],
    "progressbar": ["QProgressBar"],
    "scrollbar": ["QScrollBar"],
    "toolbar": ["QToolBar"],
    "statusbar": ["QStatusBar"],
    "groupbox": ["QGroupBox"],
    "splitter": ["QSplitter"],
    "stackedwidget": ["QStackedWidget"],
    "dockwidget": ["QDockWidget"],
}

# Reverse mapping: class name → role
CLASS_TO_ROLE: dict[str, str] = {}
for _role, _classes in ROLE_MAP.items():
    for _cls in _classes:
        CLASS_TO_ROLE[_cls] = _role
