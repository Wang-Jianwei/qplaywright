"""MCP server adapter for qplaywright.

This module exposes the existing synchronous qplaywright client as an MCP
server. It does not replace the Qt-side agent protocol. Instead, it adds a
northbound MCP tool layer so MCP hosts can connect to a running Qt app,
inspect windows, and interact with widgets via the existing selector model.
"""

import base64
import builtins
import argparse
import atexit
import inspect as pyinspect
import contextlib
import json
import logging
import re
import shlex
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import Field, ValidationError

from qplaywright.protocol import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    METHOD_CLICK,
    METHOD_DBLCLICK,
    METHOD_FIND,
    METHOD_FIND_WIDGETS,
    METHOD_HOVER,
    METHOD_ITEM_VIEW_INSPECT,
    METHOD_LIST_WINDOWS,
    METHOD_PING,
    METHOD_PRESS,
    METHOD_WIDGET_TREE,
)
from qplaywright._logging import configure_logging_from_env
from qplaywright.errors import QPlaywrightActionError, QPlaywrightConnectionError
from qplaywright.sync_api import QPlaywright
from qplaywright.sync_api._locator import ItemLocator, Locator

LOGGER = logging.getLogger(__name__)

_ACTION_POSTPROCESS_TIMEOUT = 2.0
_TOPMOST_ONLY_WARNING = (
    "topmost_only is an approximate frontmost-visible filter and may omit widgets or content. "
    "Rerun with topmost_only=false when you need a complete tree."
)
_SCREENSHOT_TEMP_DIR = Path(tempfile.gettempdir()) / "qplaywright_screenshots" / uuid4().hex
_INFRASTRUCTURE_WIDGET_CLASSES = {
    "QAbstractScrollAreaScrollBarContainer",
}


def _qt_application_instance(*, required: bool) -> Any | None:
    for package_name in ("PySide6", "PyQt6", "PySide2", "PyQt5"):
        with contextlib.suppress(ImportError, AttributeError):
            qt_widgets = __import__(f"{package_name}.QtWidgets", fromlist=["QApplication"])
            application = qt_widgets.QApplication.instance()
            if application is not None:
                return application
    if required:
        raise RuntimeError("Qt application instance is not available")
    return None


def _strip_null_schema_type(schema: dict[str, Any]) -> None:
    any_of = schema.get("anyOf")
    if not isinstance(any_of, list):
        return
    schema["anyOf"] = [entry for entry in any_of if entry.get("type") != "null"]


def _tighten_pointer_tool_schema(tool: Any | None, *, verb: str) -> None:
    if tool is None:
        return

    parameters = tool.parameters
    properties = parameters.get("properties", {})
    target_schema = properties.get("target")
    x_schema = properties.get("x")
    y_schema = properties.get("y")
    if not isinstance(target_schema, dict) or not isinstance(x_schema, dict) or not isinstance(y_schema, dict):
        return

    _strip_null_schema_type(target_schema)
    target_schema.pop("default", None)
    target_schema["description"] = (
        f"Stable widget handle, or a structured item target object {{owner, item}}. "
        f"Use snapshot, find, or inspect to observe the UI and capture handles first. Provide target to {verb} a widget or item. Omit target only when using both x and y to {verb} "
        "a window-relative coordinate in the active window."
    )

    for axis, axis_schema in (("x", x_schema), ("y", y_schema)):
        axis_schema.pop("default", None)
        axis_schema["description"] = (
            f"Window-relative {axis} coordinate in pixels. Provide together with the other axis to {verb} "
            "the active window when target is omitted."
        )

    parameters["oneOf"] = [
        {"required": ["target"]},
        {"required": ["x", "y"]},
    ]
    parameters["allOf"] = [
        {"not": {"required": ["target", "x"]}},
        {"not": {"required": ["target", "y"]}},
    ]

SessionAction = Literal["attach", "launch", "close", "status"]
WindowAction = Literal["list", "select", "resize", "close"]
FindMode = Literal["auto", "exact", "fuzzy"]

_ALLOWED_WAIT_STATES = {"visible", "hidden", "enabled", "disabled", "checked", "unchecked"}
_ALLOWED_WAIT_CONDITIONS = {
    "text_equals",
    "text_contains",
    "current_text_equals",
    "current_text_contains",
    "value_equals",
    "checked_equals",
    "count_equals",
}

SessionActionArg = Annotated[
    SessionAction,
    Field(description="Session action to run: attach, launch, close, or status."),
]
HostArg = Annotated[
    str,
    Field(description="Host where the qplaywright agent is listening."),
]
PortArg = Annotated[
    int,
    Field(description="TCP port where the qplaywright agent is listening."),
]
TimeoutSecondsArg = Annotated[
    float,
    Field(description="Timeout in seconds for the session operation."),
]
ExecutableArg = Annotated[
    str | None,
    Field(description="Executable path to launch when action is launch."),
]
LaunchArgsArg = Annotated[
    list[str] | None,
    Field(description="Optional command-line arguments passed to the launched executable."),
]
AgentNameArg = Annotated[
    str | None,
    Field(description="Agent name reported to the remote qplaywright agent."),
]

WindowActionArg = Annotated[
    WindowAction,
    Field(description="Window action to run: list, select, resize, or close."),
]
WindowIndexArg = Annotated[
    int | None,
    Field(description="Zero-based window index used for selection or targeting."),
]
WindowWidArg = Annotated[
    int | None,
    Field(description="Exact window wid used for selection or targeting."),
]
WindowTitleArg = Annotated[
    str | None,
    Field(description="Case-insensitive window title substring used for selection or targeting."),
]
WindowWidthArg = Annotated[
    int | None,
    Field(description="Target window width in pixels for resize."),
]
WindowHeightArg = Annotated[
    int | None,
    Field(description="Target window height in pixels for resize."),
]

WidgetHandleArg = Annotated[
    str,
    Field(description="Stable widget handle target, such as w12. Get handles from snapshot, find, or inspect before precise widget actions."),
]
WidgetDiscoveryTargetArg = Annotated[
    str,
    Field(description="Stable widget handle or selector target used for observation or search, such as w12, #objectName, role=button, or text=Submit. Use selectors to narrow candidates; reuse returned handles for precise widget actions."),
]
ItemTargetArg = Annotated[
    dict[str, Any],
    Field(description="Structured item target object: {owner: <widget stable handle or selector>, item: <table_cell/tree_node/list_item descriptor>}. Prefer a stable handle for owner when available."),
]
ActionTargetArg = Annotated[
    str | dict[str, Any],
    Field(description="Stable widget handle, or a structured item target object {owner, item}. Widget actions require stable handles; item actions use structured targets returned by inspect_items."),
]
OptionalActionTargetArg = Annotated[
    str | dict[str, Any] | None,
    Field(description="Optional stable widget handle, or a structured item target object {owner, item}. Widget actions require stable handles; item actions use structured targets returned by inspect_items. Omit only when the tool supports targetless operation."),
]
OptionalWidgetHandleArg = Annotated[
    str | None,
    Field(description="Optional stable widget handle target. Get handles from snapshot, find, or inspect before precise widget actions. Omit to use the active window or focused widget when supported."),
]
OptionalWidgetDiscoveryTargetArg = Annotated[
    str | None,
    Field(description="Optional stable widget handle or selector target used for observation or search. Use selectors to narrow candidates; reuse returned handles for precise widget actions. Omit to inspect or snapshot the active window when supported."),
]
OptionalDiscoveryOrItemTargetArg = Annotated[
    str | dict[str, Any] | None,
    Field(description="Optional stable widget handle, selector target used for observation or search, or structured item target object {owner, item}. Omit to inspect the active window when the tool supports it."),
]
FindRootArg = Annotated[
    str | None,
    Field(description="Optional find scope root: stable widget handle or selector. Use selectors to narrow candidate search; reuse returned handles for precise widget actions. Omit to search under the active window."),
]
FindRoleArg = Annotated[
    str | None,
    Field(description="Exact qplaywright role name to match, such as button, table, or tree."),
]
FindModeArg = Annotated[
    FindMode,
    Field(
        description=(
            "Find mode: auto chooses fuzzy when keyword is provided and exact otherwise; "
            "exact uses deterministic constraints such as text, class, object_name, or accessible_name; "
            "fuzzy requires keyword and ranks approximate matches across readable widget fields."
        )
    ),
]
FindTextArg = Annotated[
    str | None,
    Field(description="Exact primary widget text to match, case-sensitive."),
]
FindKeywordArg = Annotated[
    str | None,
    Field(description="Approximate keyword clue for fuzzy discovery across readable widget text, accessible name, current text, window title, and object name fields."),
]
FindClassArg = Annotated[
    str | None,
    Field(
        alias="class",
        validation_alias="class",
        serialization_alias="class",
        description="Exact Qt class name to match against the widget class hierarchy.",
    ),
]
FindObjectNameArg = Annotated[
    str | None,
    Field(description="Exact QObject::objectName() to match."),
]
ResolveObjectNamesArg = Annotated[
    list[str],
    Field(
        description="One or more exact QObject::objectName() values to resolve within one known root scope. Use this only when that subtree exposes deliberate stable objectName values."
    ),
]
FindAccessibleNameArg = Annotated[
    str | None,
    Field(description="Exact accessibleName to match, case-sensitive."),
]
FindVisibleArg = Annotated[
    bool | None,
    Field(description="When true, only return visible widgets with non-empty geometry; when false, only return widgets outside that visible condition."),
]
FindEnabledArg = Annotated[
    bool | None,
    Field(description="When true, only return enabled widgets; when false, only return disabled widgets."),
]
FindInteractableArg = Annotated[
    bool | None,
    Field(description="When true, only return currently interactable widgets; when false, only return non-interactable widgets."),
]
FindLimitArg = Annotated[
    int,
    Field(description="Maximum number of widget candidates to return. Must be a positive integer."),
]
DepthArg = Annotated[
    int,
    Field(description="Maximum widget tree depth to include in the returned snapshot or inspect tree."),
]
TopmostOnlyArg = Annotated[
    bool,
    Field(description="When true, return an approximate frontmost-visible view instead of the full active window tree."),
]
IncludeInfrastructureArg = Annotated[
    bool,
    Field(description="When true, include Qt infrastructure helper widgets that are normally filtered out."),
]
SaveToArg = Annotated[
    str | None,
    Field(description="Optional filesystem path where the text snapshot should be written."),
]
PropertyArg = Annotated[
    str | None,
    Field(description="Optional widget property name to read alongside the standard inspect payload."),
]
IncludeMethodsArg = Annotated[
    bool,
    Field(description="When true, include exposed custom widget methods in inspect output."),
]
IncludePropertiesArg = Annotated[
    bool,
    Field(description="When true, include the raw widget property map in inspect output."),
]

ClickCountArg = Annotated[
    int,
    Field(description="Click count. Use 1 for a single click or 2 for a double click."),
]
InputTextArg = Annotated[
    str,
    Field(description="Text to input into the stable-handle target widget."),
]
InputModeArg = Annotated[
    str,
    Field(description="Input mode. Use replace to overwrite existing content, append to type after it, type to simulate keyboard entry without clearing first, or clear to erase existing content without typing."),
]
InputDelayArg = Annotated[
    int,
    Field(description="Delay in milliseconds between typed characters when keyboard typing is used."),
]
SubmitArg = Annotated[
    bool,
    Field(description="When true, press Enter after the input action."),
]
IncludeStateArg = Annotated[
    bool,
    Field(description="When true, include a compact post-action target state in result.state."),
]
IncludeSnapshotArg = Annotated[
    bool,
    Field(description="When true, include a post-action observation in result.observation. If the action changes windows, the observation falls back to the active window."),
]
MethodArg = Annotated[
    str,
    Field(description="Exact exposed custom widget method name to invoke."),
]
InvokeArgsArg = Annotated[
    dict[str, Any] | None,
    Field(description="Optional keyword argument object passed to the custom widget method."),
]
KeyArg = Annotated[
    str,
    Field(description="Qt or keyboard key name to press, such as Enter, Tab, Escape, or Ctrl+A."),
]
ChooseValueArg = Annotated[
    str | None,
    Field(description="Combobox option value to select. Provide exactly one of value, index, or label."),
]
ChooseIndexArg = Annotated[
    int | None,
    Field(description="Combobox option index to select. Provide exactly one of value, index, or label."),
]
ChooseLabelArg = Annotated[
    str | None,
    Field(description="Combobox option label or current text to select. Provide exactly one of value, index, or label."),
]
WaitStateArg = Annotated[
    str | None,
    Field(description="Built-in wait state to wait for: visible, hidden, enabled, disabled, checked, or unchecked."),
]
WaitConditionArg = Annotated[
    str | None,
    Field(description="Higher-level wait condition such as text_equals, text_contains, current_text_equals, current_text_contains, value_equals, checked_equals, or count_equals."),
]
WaitExpectedArg = Annotated[
    str | int | bool | None,
    Field(description="Expected value used with condition. Its type depends on the selected condition."),
]
OptionalTimeoutArg = Annotated[
    float | None,
    Field(description="Optional timeout in seconds for the operation. When omitted, the active session timeout is used."),
]
ScreenshotPathArg = Annotated[
    str | None,
    Field(description="Optional output file path for the screenshot. When omitted, the server materializes or returns a managed file path."),
]
ClipXArg = Annotated[
    int | None,
    Field(description="Optional left coordinate in pixels for screenshot clipping."),
]
ClipYArg = Annotated[
    int | None,
    Field(description="Optional top coordinate in pixels for screenshot clipping."),
]
ClipWidthArg = Annotated[
    int | None,
    Field(description="Optional clip width in pixels for screenshot clipping."),
]
ClipHeightArg = Annotated[
    int | None,
    Field(description="Optional clip height in pixels for screenshot clipping."),
]
DeltaXArg = Annotated[
    int,
    Field(description="Horizontal mouse wheel delta to send to the stable-handle target widget."),
]
DeltaYArg = Annotated[
    int,
    Field(description="Vertical mouse wheel delta to send to the stable-handle target widget."),
]
ExpandedArg = Annotated[
    bool,
    Field(description="Whether the targeted tree node item should be expanded (true) or collapsed (false)."),
]
InspectItemsMaxRowsArg = Annotated[
    int,
    Field(description="Maximum number of table or list rows to enumerate."),
]
InspectItemsMaxDepthArg = Annotated[
    int,
    Field(description="Maximum tree depth to enumerate when inspecting tree items."),
]
InspectItemsMaxItemsArg = Annotated[
    int,
    Field(description="Maximum number of item entries to return."),
]
IncludeHiddenItemsArg = Annotated[
    bool,
    Field(description="When true, include hidden or collapsed item-view descendants when the backend can resolve them."),
]

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase
    from mcp.shared.session import BaseSession, RequestResponder
    from mcp.types import (
        ClientNotification,
        JSONRPCError,
        JSONRPCMessage,
        JSONRPCNotification,
        JSONRPCRequest,
        JSONRPCResponse,
    )
except ImportError as exc:  # pragma: no cover - exercised only without the extra installed
    FastMCP = None  # type: ignore[assignment]
    ArgModelBase = None  # type: ignore[assignment]
    BaseSession = None  # type: ignore[assignment]
    RequestResponder = None  # type: ignore[assignment]
    ClientNotification = None  # type: ignore[assignment]
    JSONRPCError = None  # type: ignore[assignment]
    JSONRPCMessage = None  # type: ignore[assignment]
    JSONRPCNotification = None  # type: ignore[assignment]
    JSONRPCRequest = None  # type: ignore[assignment]
    JSONRPCResponse = None  # type: ignore[assignment]
    _MCP_IMPORT_ERROR: ImportError | None = exc
else:
    _MCP_IMPORT_ERROR = None


_MCP_MINIMUM_VERSION = (1, 27, 0)
_MCP_MINIMUM_VERSION_TEXT = ".".join(str(part) for part in _MCP_MINIMUM_VERSION)


def _parse_version_tuple(raw_version: str) -> tuple[int, int, int]:
    parts = [int(part) for part in re.findall(r"\d+", raw_version)[:3]]
    while len(parts) < 3:
        parts.append(0)
    return (parts[0], parts[1], parts[2])


_MCP_VERSION_ERROR: str | None = None
if _MCP_IMPORT_ERROR is None:
    try:
        _installed_mcp_version = package_version("mcp")
    except PackageNotFoundError:
        _MCP_VERSION_ERROR = (
            "The qplaywright MCP server requires the optional 'mcp' dependency. "
            "Install it with: pip install -e .[mcp]"
        )
    else:
        if _parse_version_tuple(_installed_mcp_version) < _MCP_MINIMUM_VERSION:
            _MCP_VERSION_ERROR = (
                "The qplaywright MCP server requires mcp "
                f">={_MCP_MINIMUM_VERSION_TEXT}, but found {_installed_mcp_version}. "
                "Upgrade it with: pip install -U \"mcp[cli]>=1.27.0\""
            )


_MCP_CANCEL_NOTIFICATION_METHOD = "notifications/cancelled"
_HANDLE_PATTERN = re.compile(r"^w\d+$")
_SELECTOR_EXAMPLES = "role=button, text=Submit, has-text=partial, a11y-name=Submit, #objectName, name=objectName, .QLabel"


def _patch_fastmcp_argument_dump() -> None:
    if ArgModelBase is None:
        return

    def model_dump_one_level(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        for field_name, field_info in self.__class__.model_fields.items():
            value = getattr(self, field_name)
            output_name = field_name
            # FastMCP renames some fields to avoid BaseModel attribute collisions.
            # Preserve the public alias only for those synthetic field_* names.
            if field_name.startswith("field_") and field_info.alias:
                output_name = field_info.alias
            kwargs[output_name] = value
        return kwargs

    ArgModelBase.model_dump_one_level = model_dump_one_level


_patch_fastmcp_argument_dump()


@dataclass
class ManagedConnection:
    """A live qplaywright connection tracked by the MCP server."""

    name: str
    qplaywright: Any
    app: Any
    host: str
    port: int
    timeout: float
    launched_executable: str | None = None
    active_window_wid: int | None = None
    window_scope_override_wid: int | None = None
    handle_counter: int = 0
    wid_to_handle: dict[int, str] = field(default_factory=dict)
    handle_to_wid: dict[str, int] = field(default_factory=dict)
    stale_handles: set[str] = field(default_factory=set)

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.app.close()
        with contextlib.suppress(Exception):
            self.qplaywright.close()

    def handle_for_wid(self, wid: int | None) -> str | None:
        if wid is None:
            return None
        handle = self.wid_to_handle.get(wid)
        if handle is not None:
            return handle
        self.handle_counter += 1
        handle = f"w{self.handle_counter}"
        self.wid_to_handle[wid] = handle
        self.handle_to_wid[handle] = wid
        return handle

    def wid_for_handle(self, handle: str) -> int:
        wid = self.handle_to_wid.get(handle)
        if wid is not None:
            return wid
        if handle in self.stale_handles:
            raise ValueError(f"Stable handle {handle!r} is stale because its widget no longer exists.")
        raise ValueError(f"Unknown stable handle {handle!r}. Run snapshot, find, or inspect to discover handles.")


@dataclass
class ServerState:
    """In-process state for live qplaywright MCP sessions."""

    connection: ManagedConnection | None = None

    def close_all(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None


_SERVER_STATE = ServerState()
atexit.register(_SERVER_STATE.close_all)


def _cleanup_screenshot_temp_dir() -> None:
    shutil.rmtree(_SCREENSHOT_TEMP_DIR, ignore_errors=True)


atexit.register(_cleanup_screenshot_temp_dir)


def _mcp_client_notification_supports_cancelled() -> bool:
    if ClientNotification is None:
        return True
    try:
        ClientNotification.model_validate(
            {
                "method": _MCP_CANCEL_NOTIFICATION_METHOD,
                "params": {"requestId": 1, "reason": "timeout"},
            }
        )
    except Exception:
        return False
    return True


def _decode_client_notification(session: Any, payload: dict[str, Any]) -> Any | None:
    method = payload.get("method")
    if method == _MCP_CANCEL_NOTIFICATION_METHOD:
        params = payload.get("params") or {}
        LOGGER.info(
            "Ignoring MCP client cancellation notification for requestId=%s",
            params.get("requestId"),
        )
        return None

    try:
        return session._receive_notification_type.model_validate(payload)
    except ValidationError as exc:
        LOGGER.warning("Ignoring invalid MCP client notification %r: %s", method, exc)
        return None


async def _patched_mcp_session_receive_loop(session: Any) -> None:
    assert JSONRPCRequest is not None
    assert JSONRPCNotification is not None
    assert RequestResponder is not None

    async with (
        session._read_stream,
        session._write_stream,
        session._incoming_message_stream_writer,
    ):
        async for message in session._read_stream:
            if isinstance(message, Exception):
                await session._incoming_message_stream_writer.send(message)
            elif isinstance(message.root, JSONRPCRequest):
                validated_request = session._receive_request_type.model_validate(
                    message.root.model_dump(by_alias=True, mode="json", exclude_none=True)
                )
                responder = RequestResponder(
                    request_id=message.root.id,
                    request_meta=validated_request.root.params.meta if validated_request.root.params else None,
                    request=validated_request,
                    session=session,
                    on_complete=lambda r: session._in_flight.pop(r.request_id, None),
                    message_metadata=getattr(message, "metadata", None),
                )
                session._in_flight[responder.request_id] = responder

                await session._received_request(responder)
                if responder.in_flight:
                    await session._incoming_message_stream_writer.send(responder)
            elif isinstance(message.root, JSONRPCNotification):
                payload = message.root.model_dump(by_alias=True, mode="json", exclude_none=True)
                notification = _decode_client_notification(session, payload)
                if notification is None:
                    continue

                await session._received_notification(notification)
                await session._incoming_message_stream_writer.send(notification)
            else:
                stream = session._response_streams.pop(message.root.id, None)
                if stream:
                    await stream.send(message.root)
                else:
                    await session._incoming_message_stream_writer.send(
                        RuntimeError(f"Received response with an unknown request ID: {message}")
                    )


def _install_mcp_stdio_cancel_compat() -> None:
    if BaseSession is None or getattr(BaseSession, "_qplaywright_cancel_compat_installed", False):
        return
    if _mcp_client_notification_supports_cancelled():
        return

    BaseSession._receive_loop = _patched_mcp_session_receive_loop  # type: ignore[method-assign]
    BaseSession._qplaywright_cancel_compat_installed = True  # type: ignore[attr-defined]
    LOGGER.info(
        "Installed qplaywright MCP compatibility patch for unsupported %s notifications",
        _MCP_CANCEL_NOTIFICATION_METHOD,
    )


def _run_mcp_transport(transport: str) -> int:
    assert mcp is not None
    runner: Any = mcp

    try:
        runner.run(transport=transport)
    except BaseExceptionGroup as exc:
        LOGGER.error("qplaywright MCP server exited unexpectedly on %s transport: %s", transport, exc)
        return 1
    except Exception as exc:
        LOGGER.error("qplaywright MCP server exited unexpectedly on %s transport: %s", transport, exc)
        return 1
    return 0


_install_mcp_stdio_cancel_compat()


def _list_windows_raw(connection: ManagedConnection, *, timeout: float | None = None) -> list[dict[str, Any]]:
    client = getattr(connection.app, "_conn", None)
    if client is not None:
        response = client.send(METHOD_LIST_WINDOWS, timeout=timeout)
        if isinstance(response, list):
            return [window for window in response if isinstance(window, dict)]
        if isinstance(response, dict):
            windows = response.get("windows")
            if isinstance(windows, list):
                return [window for window in windows if isinstance(window, dict)]
        return []

    windows = []
    for index, window in enumerate(connection.app.windows()):
        windows.append(
            {
                "wid": window.wid,
                "title": window.title(),
                "class": "",
                "geometry": [None, None, None, None],
                "is_modal": bool(window.isModal()) if hasattr(window, "isModal") else False,
                "index": index,
            }
        )
    return windows


def _window_geometry(window: dict[str, Any]) -> list[Any]:
    geometry = window.get("geometry")
    if isinstance(geometry, list):
        return geometry
    if not isinstance(geometry, dict):
        raise ValueError("Window payload is missing geometry")

    return _compact_geometry(geometry) or [None, None, None, None]


def _compact_geometry(geometry: Any) -> list[Any] | None:
    if isinstance(geometry, list):
        if len(geometry) != 4:
            return None
        if all(value is None for value in geometry):
            return None
        return geometry
    if not isinstance(geometry, dict):
        return None
    compact = [geometry.get("x"), geometry.get("y"), geometry.get("width"), geometry.get("height")]
    if all(value is None for value in compact):
        return None
    return compact


def _attribute_summary(node: dict[str, Any]) -> dict[str, Any] | None:
    attribute: dict[str, Any] = {}
    if _is_mouse_transparent(node):
        attribute["transparent_for_mouse_events"] = True
    return attribute or None


def _is_mouse_transparent(node: dict[str, Any]) -> bool:
    attributes = node.get("attributes")
    return isinstance(attributes, dict) and attributes.get("WA_TransparentForMouseEvents") is True


def _widget_tree_raw(
    connection: ManagedConnection,
    *,
    max_depth: int,
    window_wid: int | None = None,
    topmost_only: bool = False,
    include_interactable: bool = False,
    timeout: float | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "max_depth": max_depth,
        "topmost_only": topmost_only,
        "include_interactable": include_interactable,
    }
    if window_wid is not None:
        params["wid"] = window_wid
    return connection.app._conn.send(METHOD_WIDGET_TREE, params, timeout=timeout)


def _find_widgets_raw(
    connection: ManagedConnection,
    *,
    root_wid: int,
    keyword: str | None = None,
    role: str | None = None,
    text: str | None = None,
    widget_class: str | None = None,
    object_name: str | None = None,
    accessible_name: str | None = None,
    visible: bool | None = None,
    enabled: bool | None = None,
    interactable: bool | None = None,
    include_infrastructure: bool = False,
    limit: int = 5,
    timeout: float | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "wid": root_wid,
        "include_infrastructure": include_infrastructure,
        "limit": limit,
    }
    optional_params = {
        "keyword": keyword,
        "role": role,
        "text": text,
        "class": widget_class,
        "object_name": object_name,
        "accessible_name": accessible_name,
        "visible": visible,
        "enabled": enabled,
        "interactable": interactable,
    }
    for key, value in optional_params.items():
        if value is not None:
            params[key] = value
    return connection.app._conn.send(
        METHOD_FIND_WIDGETS,
        params,
        timeout=timeout if timeout is not None else connection.timeout,
    )


def _window_summary(connection: ManagedConnection) -> list[dict[str, Any]]:
    return _summarize_windows(connection, _list_windows_raw(connection))


def _effective_active_window_wid(
    connection: ManagedConnection,
    windows: list[dict[str, Any]],
) -> int | None:
    if not windows:
        return None

    scoped_window = next(
        (window for window in windows if window.get("wid") == connection.window_scope_override_wid),
        None,
    )
    if scoped_window is not None and isinstance(connection.window_scope_override_wid, int):
        return connection.window_scope_override_wid

    stored_window = next(
        (window for window in windows if window.get("wid") == connection.active_window_wid),
        None,
    )

    explicit_active = next(
        (
            window.get("wid")
            for window in windows
            if window.get("is_active") is True and isinstance(window.get("wid"), int)
        ),
        None,
    )
    if isinstance(explicit_active, int):
        return explicit_active

    if stored_window is not None and not bool(stored_window.get("blocked_by_modal", False)):
        return connection.active_window_wid

    modal_candidate = next(
        (
            window.get("wid")
            for window in windows
            if bool(window.get("is_modal", False))
            and not bool(window.get("blocked_by_modal", False))
            and isinstance(window.get("wid"), int)
        ),
        None,
    )
    if isinstance(modal_candidate, int):
        return modal_candidate

    if stored_window is not None and isinstance(connection.active_window_wid, int):
        return connection.active_window_wid

    first_wid = windows[0].get("wid")
    return first_wid if isinstance(first_wid, int) else None


def _summarize_windows(
    connection: ManagedConnection,
    windows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    effective_active_wid = _effective_active_window_wid(connection, windows)
    summaries: list[dict[str, Any]] = []
    for index, window in enumerate(windows):
        is_active = window["wid"] == effective_active_wid
        summaries.append(
            {
                "index": index,
                "wid": window["wid"],
                "title": window.get("title", ""),
                "class": window.get("class", ""),
                "geometry": _window_geometry(window),
                "is_active": is_active,
                "is_modal": bool(window.get("is_modal", False)),
            }
        )
    return summaries


def _active_window_summary(
    connection: ManagedConnection,
    *,
    windows: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if windows is None:
        windows = _window_summary(connection)
    if not windows:
        return None

    active_window = next((window for window in windows if window.get("is_active") is True), None)
    if active_window is None and connection.active_window_wid is not None:
        active_window = next(
            (window for window in windows if window["wid"] == connection.active_window_wid),
            None,
        )
    if active_window is None:
        active_window = windows[0]

    summary = {
        "wid": active_window["wid"],
        "title": active_window.get("title", ""),
        "class": active_window.get("class", ""),
        "geometry": _window_geometry(active_window),
        "is_active": True,
        "is_modal": bool(active_window.get("is_modal", False)),
    }
    if "index" in active_window:
        summary["index"] = active_window.get("index")
    return summary


def _session_summary(connection: ManagedConnection) -> dict[str, Any]:
    return {
        "connected": True,
        "host": connection.host,
        "port": connection.port,
        "launched_executable": connection.launched_executable,
    }


def _select_active_window(connection: ManagedConnection, window_wid: int | None, *, override_scope: bool = False) -> None:
    connection.active_window_wid = window_wid
    connection.window_scope_override_wid = window_wid if override_scope else None


def _initialize_active_window(connection: ManagedConnection) -> list[dict[str, Any]]:
    windows = _window_summary(connection)
    if windows:
        _select_active_window(connection, windows[0]["wid"])
    else:
        _select_active_window(connection, None)
    return windows


def _ping_connection(connection: ManagedConnection) -> None:
    client = getattr(connection.app, "_conn", None)
    if client is None:
        return
    client.send(METHOD_PING, timeout=min(connection.timeout, 5.0))


def _stale_connection_message(connection: ManagedConnection, exc: Exception) -> str:
    return (
        f"Session to {connection.host}:{connection.port} is no longer alive: {exc}. "
        "The remote qplaywright agent disconnected or restarted. Call session attach again to establish a fresh session."
    )


def _get_connection(state: ServerState) -> ManagedConnection:
    connection = state.connection
    if connection is None:
        raise ValueError("No active session. Call session with action='attach' or action='launch' first")

    try:
        _ping_connection(connection)
    except Exception as exc:
        connection.close()
        state.connection = None
        raise QPlaywrightConnectionError(
            _stale_connection_message(connection, exc),
            code="stale_session",
            context={
                "host": connection.host,
                "port": connection.port,
                "timeout": connection.timeout,
                "connection_name": connection.name,
                "last_error": repr(exc),
            },
        ) from exc

    return connection


def _require_session_transport(connection: ManagedConnection, *, action: str) -> Any:
    client = getattr(connection.app, "_conn", None)
    if client is None:
        raise QPlaywrightConnectionError(
            f"Active session transport is unavailable for {action}. Reattach or relaunch the session before retrying.",
            code="transport_unavailable",
            context={
                "host": connection.host,
                "port": connection.port,
                "timeout": connection.timeout,
                "connection_name": connection.name,
                "action": action,
            },
        )
    return client


def connect_connection(
    state: ServerState,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = 30.0,
    agent_name: str | None = None,
) -> ManagedConnection:
    if state.connection is not None:
        state.connection.close()
        state.connection = None

    qplaywright = QPlaywright()
    connection_name = (agent_name or "default").strip() or "default"
    app = qplaywright.connect(host=host, port=port, timeout=timeout, agent_name=agent_name)
    connection = ManagedConnection(
        name=connection_name,
        qplaywright=qplaywright,
        app=app,
        host=host,
        port=port,
        timeout=timeout,
    )
    state.connection = connection
    _initialize_active_window(connection)
    return connection


def launch_connection(
    state: ServerState,
    *,
    executable: str,
    args: Sequence[str] | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = 30.0,
    agent_name: str | None = None,
) -> ManagedConnection:
    if state.connection is not None:
        state.connection.close()
        state.connection = None

    qplaywright = QPlaywright()
    connection_name = (agent_name or "default").strip() or "default"
    app = qplaywright.launch(
        executable,
        *(args or ()),
        host=host,
        port=port,
        timeout=timeout,
        agent_name=agent_name,
    )
    connection = ManagedConnection(
        name=connection_name,
        qplaywright=qplaywright,
        app=app,
        host=host,
        port=port,
        timeout=timeout,
        launched_executable=executable,
    )
    state.connection = connection
    _initialize_active_window(connection)
    return connection


def disconnect_connection(state: ServerState) -> dict[str, Any]:
    connection = state.connection
    if connection is None:
        raise ValueError("No active session. Call session with action='attach' or action='launch' first")
    connection.close()
    state.connection = None
    return {
        "closed": True,
        "launched_executable": connection.launched_executable,
    }


def _resolve_window(
    connection: ManagedConnection,
    *,
    window_wid: int | None = None,
    window_title: str | None = None,
    window_index: int | None = None,
) -> Any:
    windows = connection.app.windows()
    if not windows:
        raise ValueError(f"No visible windows found for connection {connection.name!r}")

    if window_wid is not None:
        for window in windows:
            if window.wid == window_wid:
                return window
        raise ValueError(f"Window wid={window_wid} was not found for connection {connection.name!r}")

    if window_title:
        title_lower = window_title.lower()
        for window in windows:
            if title_lower in window.title().lower():
                return window
        raise ValueError(
            f"No window title containing {window_title!r} was found for connection {connection.name!r}"
        )

    if window_index is not None:
        if window_index < 0 or window_index >= len(windows):
            raise IndexError(
                f"Window index {window_index} is out of range for connection {connection.name!r}"
            )
        return windows[window_index]

    if connection.active_window_wid is not None:
        for window in windows:
            if window.wid == connection.active_window_wid:
                return window

    return windows[0]


def _require_exactly_one_window_selector(*, index: int | None, wid: int | None, title: str | None) -> None:
    selector_count = sum(candidate is not None for candidate in (index, wid, title))
    if selector_count != 1:
        raise ValueError("window select requires exactly one of index, wid, or title")


def _resolve_locator(
    connection: ManagedConnection,
    *,
    target: str,
) -> Any:
    if not target.strip():
        raise ValueError("target must not be empty")

    if _HANDLE_PATTERN.match(target):
        handle_wid = connection.wid_for_handle(target)
        return Locator(connection.app._conn, "", widget_wid=handle_wid, timeout=connection.timeout)

    window = _resolve_window(connection)
    return window.locator(target)


def _resolve_widget_handle_locator(
    connection: ManagedConnection,
    *,
    target: str,
    action: str,
) -> Any:
    normalized_target = target.strip()
    if not normalized_target:
        raise ValueError("target must not be empty")
    if not _HANDLE_PATTERN.match(normalized_target):
        raise ValueError(
            f"{action} requires a stable widget handle target like w12. Use snapshot, find, or inspect first and reuse the returned handle."
        )

    handle_wid = connection.wid_for_handle(normalized_target)
    return Locator(connection.app._conn, "", widget_wid=handle_wid, timeout=connection.timeout)


def _raise_if_hidden_click_target(locator: Any, *, target: str, action: str, exc: Exception) -> None:
    try:
        exists = locator.count() > 0
    except Exception:
        exists = False

    if not exists:
        return

    try:
        visible = locator.is_visible()
    except Exception:
        visible = False

    if not visible:
        raise ValueError(
            f"{action} target {target!r} still exists but is not visible. "
            "The stable handle is valid, but the widget is currently hidden in the active UI scope. "
            "Use inspect, snapshot, or window select to confirm the current window before retrying."
        ) from exc


def _is_item_target(target: Any) -> bool:
    return isinstance(target, dict) and "owner" in target and "item" in target


def _normalize_item_target(target: Any) -> dict[str, Any]:
    if not _is_item_target(target):
        raise ValueError("item target must be an object with owner and item keys")

    owner = target.get("owner")
    item = target.get("item")
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("item target owner must be a non-empty widget selector or stable handle")
    if not isinstance(item, dict):
        raise ValueError("item target item must be an object descriptor")
    return {"owner": owner, "item": dict(item)}


def _target_owner_target(target: str | dict[str, Any] | None) -> str | None:
    if target is None:
        return None
    if isinstance(target, str):
        return target
    return _normalize_item_target(target)["owner"]


def _resolve_locator_owner_wid(locator: Any, *, context: str) -> int:
    resolve_owner_wid = getattr(locator, "_resolve_owner_wid", None)
    if not callable(resolve_owner_wid):
        raise ValueError(f"{context} could not be resolved to a concrete widget.")
    try:
        owner_wid = resolve_owner_wid()
    except Exception as exc:
        raise ValueError(f"{context} could not be resolved to a concrete widget: {exc}") from exc
    if isinstance(owner_wid, bool) or not isinstance(owner_wid, int):
        raise ValueError(f"{context} did not resolve to a concrete widget id.")
    return int(owner_wid)


def _resolve_item_locator(
    connection: ManagedConnection,
    *,
    target: dict[str, Any],
) -> ItemLocator:
    normalized = _normalize_item_target(target)
    owner_locator = _resolve_locator(connection, target=normalized["owner"])
    owner_wid = _resolve_locator_owner_wid(owner_locator, context=f"Item target owner {normalized['owner']!r}")
    client = _require_session_transport(connection, action="item target operations")
    return ItemLocator(client, owner_wid, normalized["item"], timeout=connection.timeout)


def _inspect_locator(
    locator: Any,
    *,
    connection: ManagedConnection | None = None,
    property_name: str | None = None,
    include_methods: bool = False,
    include_properties: bool = False,
) -> dict[str, Any]:
    count = locator.count()
    result: dict[str, Any] = {
        "exists": count > 0,
        "count": count,
    }
    if count == 0:
        return result

    if connection is not None:
        handle = _widget_handle_from_locator(connection, locator)
        if handle is not None:
            result["handle"] = handle

    first = locator.first()
    properties = first.properties()

    property_key_map = {
        "accessibleName": "accessible_name",
        "accessibleDescription": "accessible_description",
        "currentText": "current_text",
        "currentIndex": "current_index",
        "objectName": "object_name",
        "checked": "checked",
        "value": "value",
        "windowTitle": "window_title",
        "placeholderText": "placeholder_text",
        "toolTip": "tool_tip",
    }
    for key, output_key in property_key_map.items():
        value = properties.get(key)
        if value is None or value == "":
            continue
        result[output_key] = value

    widget_class = properties.get("class")
    if isinstance(widget_class, str) and widget_class:
        result["class"] = widget_class

    geometry = properties.get("geometry")
    compact_geometry = _compact_geometry(geometry)
    if compact_geometry is not None:
        result["geometry"] = compact_geometry

    attribute = _attribute_summary(properties)
    if attribute is not None:
        result["attribute"] = attribute

    text_content = first.text_content()
    if text_content not in (None, ""):
        result["text"] = text_content

    input_value = first.input_value()
    if input_value not in (None, ""):
        result["value"] = input_value

    bounding_box = first.bounding_box()
    compact_bounding_box = _compact_geometry(bounding_box)
    if compact_bounding_box is not None:
        result["global_bounding_box"] = compact_bounding_box

    result.update(
        {
            "all_text_contents": locator.all_text_contents(),
            "visible": first.is_visible(),
            "enabled": first.is_enabled(),
            "checked": first.is_checked(),
            "bounding_box": compact_bounding_box,
        }
    )

    if property_name is not None:
        result["property_name"] = property_name
        result["property_value"] = first.get_attribute(property_name)

    if include_methods:
        result["methods"] = first.methods()

    if include_properties:
        result["properties"] = properties

    return result


def _inspect_item_locator(
    locator: ItemLocator,
    *,
    property_name: str | None = None,
    include_methods: bool = False,
    include_properties: bool = False,
) -> dict[str, Any]:
    try:
        properties = locator.properties()
    except Exception:
        return {"exists": False, "count": 0}

    result: dict[str, Any] = {
        "exists": True,
        "count": 1,
        "kind": properties.get("kind") or locator._item.get("kind"),
    }

    for key in ("text", "edit_value", "row", "column", "path", "selected", "expanded"):
        value = properties.get(key)
        if value is None or value == "":
            continue
        result[key] = value

    try:
        text_content = locator.text_content()
    except Exception:
        text_content = properties.get("text")
    if text_content not in (None, ""):
        result["text"] = text_content
        result["all_text_contents"] = [text_content]

    visible = locator.is_visible()
    result["visible"] = visible

    try:
        bounding_box = locator.bounding_box()
    except Exception:
        bounding_box = None
    compact_bounding_box = _compact_geometry(bounding_box)
    if compact_bounding_box is not None:
        result["bounding_box"] = compact_bounding_box
        result["global_bounding_box"] = compact_bounding_box

    if property_name is not None:
        result["property_name"] = property_name
        result["property_value"] = properties.get(property_name)

    if include_methods:
        result["methods"] = []

    if include_properties:
        result["properties"] = properties

    return result


def _widget_handle_from_locator(connection: ManagedConnection, locator: Any) -> str | None:
    resolve_owner_wid = getattr(locator, "_resolve_owner_wid", None)
    if not callable(resolve_owner_wid):
        return None
    try:
        owner_wid = resolve_owner_wid()
    except Exception:
        return None
    if isinstance(owner_wid, bool) or not isinstance(owner_wid, int):
        return None
    return connection.handle_for_wid(int(owner_wid))


def _compact_action_state(connection: ManagedConnection, locator: Any) -> dict[str, Any]:
    inspected = _inspect_locator(locator)
    state = {
        "exists": inspected["exists"],
        "count": inspected["count"],
    }

    handle = _widget_handle_from_locator(connection, locator)
    if handle is not None:
        state["handle"] = handle

    for source_key, target_key in (
        ("object_name", "object_name"),
        ("accessible_name", "accessible_name"),
        ("accessible_description", "accessible_description"),
        ("attribute", "attribute"),
        ("class", "class"),
        ("geometry", "geometry"),
        ("bounding_box", "bounding_box"),
        ("global_bounding_box", "global_bounding_box"),
        ("visible", "visible"),
        ("enabled", "enabled"),
        ("checked", "checked"),
        ("text", "text"),
        ("current_text", "current_text"),
        ("value", "value"),
    ):
        value = inspected.get(source_key)
        if value is None or value == "":
            continue
        state[target_key] = value

    return state


def _compact_item_state(connection: ManagedConnection, locator: ItemLocator) -> dict[str, Any]:
    inspected = _inspect_item_locator(locator)
    state = {
        "exists": inspected["exists"],
        "count": inspected["count"],
    }

    owner_handle = connection.handle_for_wid(getattr(locator, "_owner_wid", None))
    if owner_handle is not None:
        state["owner_handle"] = owner_handle

    for source_key, target_key in (
        ("kind", "kind"),
        ("row", "row"),
        ("column", "column"),
        ("path", "path"),
        ("edit_value", "edit_value"),
        ("bounding_box", "bounding_box"),
        ("global_bounding_box", "global_bounding_box"),
        ("visible", "visible"),
        ("text", "text"),
        ("expanded", "expanded"),
        ("selected", "selected"),
    ):
        value = inspected.get(source_key)
        if value is None or value == "":
            continue
        state[target_key] = value

    return state


def _wait_item_condition_matches(locator: ItemLocator, *, condition: str, expected: str) -> bool:
    if condition not in {"text_equals", "text_contains"}:
        raise ValueError("item targets only support text_equals and text_contains wait conditions")

    try:
        actual = locator.text_content()
    except Exception:
        return False

    if actual in (None, ""):
        return False

    if condition == "text_contains":
        return str(expected).lower() in str(actual).lower()
    return str(actual) == str(expected)


def _wait_for_item_locator_condition(
    locator: ItemLocator,
    *,
    condition: str,
    expected: str,
    timeout: float,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _wait_item_condition_matches(locator, condition=condition, expected=expected):
            return
        time.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for {condition}={expected!r}")


def _wait_for_item_locator_state(locator: ItemLocator, *, state: str, timeout: float) -> None:
    if state not in {"visible", "hidden"}:
        raise ValueError("item targets only support visible and hidden wait states")

    deadline = time.monotonic() + timeout
    want_visible = state == "visible"
    while time.monotonic() < deadline:
        if locator.is_visible() is want_visible:
            return
        time.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for state={state!r}")


def _item_view_inspect(
    connection: ManagedConnection,
    *,
    target: str,
    max_rows: int,
    max_depth: int,
    max_items: int,
    include_hidden: bool,
) -> dict[str, Any]:
    owner_locator = _resolve_locator(connection, target=target)
    owner_wid = _resolve_locator_owner_wid(owner_locator, context=f"inspect_items target {target!r}")
    client = _require_session_transport(connection, action="inspect_items")

    payload = client.send(
        METHOD_ITEM_VIEW_INSPECT,
        {
            "wid": owner_wid,
            "max_rows": max_rows,
            "max_depth": max_depth,
            "max_items": max_items,
            "include_hidden": include_hidden,
        },
        timeout=connection.timeout,
    )
    if not isinstance(payload, dict):
        raise ValueError("inspect_items received an invalid item_view_inspect payload")

    items = []
    for entry in payload.get("items") or []:
        if not isinstance(entry, dict):
            continue
        enriched = dict(entry)
        descriptor = enriched.get("item")
        if isinstance(descriptor, dict):
            enriched["target"] = {"owner": target, "item": dict(descriptor)}
        items.append(enriched)
    payload["items"] = items
    return payload


def _invoke_locator_method(
    locator: Any,
    *,
    method_name: str,
    args: dict[str, Any] | None = None,
) -> Any:
    count = locator.count()
    if count == 0:
        raise ValueError(
            "No widget found for invoke. Use snapshot, find, or inspect first and reuse the returned stable handle."
        )

    try:
        result = locator.first().invoke(method_name, args or {})
    except QPlaywrightActionError as exc:
        raise ValueError(f"Invoke failed for method {method_name!r}: {exc}") from exc

    if isinstance(result, dict) and "ok" in result and result.get("ok") is False:
        error_code = result.get("errorCode")
        error_message = str(result.get("errorMessage") or "Unknown invoke failure")
        raise ValueError(f"Invoke failed for method {method_name!r} (errorCode={error_code}): {error_message}")
    return result


def _run_widget_tool_action(*, action: str, target: str, callback: Callable[[], Any]) -> Any:
    try:
        return callback()
    except QPlaywrightActionError as exc:
        raise ValueError(f"{action} failed for target {target!r}: {exc}") from exc


def _target_not_found_message(connection: ManagedConnection, target: str | None, *, element: str | None = None) -> str:
    examples = "#objectName, role=button, text=Submit, has-text=partial, a11y-name=Submit, .QLabel"
    candidate = (target or element or "").strip()
    if candidate and _HANDLE_PATTERN.match(candidate):
        return f"No widget found for stable handle {candidate!r}. Run snapshot, find, or inspect to capture fresh handles."
    if candidate:
        return (
            f"No widget found for target {candidate!r}. Run snapshot, find, or inspect to observe the UI, "
            f"prefer a returned stable handle, and fall back to selectors like {examples} when needed."
        )
    return (
        "No widget target was resolved. Run snapshot, find, or inspect first, prefer a returned stable handle, "
        f"and fall back to selectors like {examples} when needed."
    )


def _selector_help_text() -> str:
    return (
        "Selectors follow the qplaywright selector syntax. Use snapshot, find, or inspect first to observe the UI and capture stable handles for repeatable actions.\n\n"
        "Common forms:\n"
        "- role=button\n"
        "- text=Submit\n"
        "- has-text=partial\n"
        "- a11y-name=Submit\n"
        "- a11y-desc=Help text\n"
        "- #objectName\n"
        "- name=objectName\n"
        "- .QLabel\n\n"
        "Structured item targets use the form {owner, item}, for example:\n"
        "- {\"owner\": \"w12\", \"item\": {\"kind\": \"table_cell\", \"row\": 3, \"column\": 1}}\n"
        "- {\"owner\": \"w9\", \"item\": {\"kind\": \"tree_node\", \"path\": [0, 1]}}\n"
        "- {\"owner\": \"w5\", \"item\": {\"kind\": \"list_item\", \"row\": 2}}\n"
        "- {\"owner\": \"w3\", \"item\": {\"kind\": \"tab_item\", \"index\": 1}}\n\n"
        "Geometry help:\n"
        "- Read qplaywright://help/geometry when you need the exact meaning of geometry, bounding_box, and global_bounding_box\n\n"
        "Typical workflow:\n"
        "1. session attach or session launch\n"
        "2. window list and window select when multiple windows are visible\n"
        "3. use snapshot with target+depth when you want one subtree and several child handles; use find when you want a small candidate set for one predicate\n"
        "4. inspect one chosen handle when you need methods, properties, or exact state; inspect_items for table/tree/list/tab descendants\n"
        "5. click, hover, wait, set_expanded, input, press_key, choose, screenshot, or invoke with those handles\n"
        "6. session close when finished"
    )


def _geometry_help_text() -> str:
    return (
        "All geometry-like response fields use Rect4 arrays in the exact form [x, y, width, height].\n\n"
        "Field meanings:\n"
        "- geometry: layout rectangle for a widget or window. For child widgets this is widget-local, usually relative to the parent widget. For top-level windows this is screen-space.\n"
        "- global_bounding_box: screen-space rectangle for the resolved widget or item target.\n"
        "- bounding_box: existing locator-compatible screen-space rectangle. It is currently identical to global_bounding_box and kept as a separate field for compatibility.\n\n"
        "Examples:\n"
        "- geometry [12, 48, 220, 80] means x=12, y=48, width=220, height=80 in the field's coordinate space.\n"
        "- global_bounding_box [300, 220, 220, 80] means the same size positioned at screen coordinate (300, 220).\n\n"
        "Do not reorder Rect4 slots and do not assume geometry uses screen coordinates unless the field description says so."
    )


def _snapshot_state_markers(node: dict[str, Any]) -> list[str]:
    markers: list[str] = []
    if node.get("visible") is False:
        markers.append("[hidden]")
    if node.get("enabled") is False:
        markers.append("[disabled]")
    if node.get("interactable") is False:
        markers.append("[non-interactable]")
    return markers


def _format_widget_snapshot(nodes: list[dict[str, Any]], *, depth: int = 10, level: int = 0) -> str:
    if level > depth:
        return ""

    lines: list[str] = []
    for node in nodes:
        transparent_part = " !transparent" if _is_mouse_transparent(node) else ""

        label, marker = _snapshot_display_label(node)
        item_view_marker = _snapshot_item_view_marker(node)
        text_part = f' "{label}"' if label else ""
        markers = " ".join(part for part in (marker, item_view_marker, *_snapshot_state_markers(node)) if part)
        marker_part = f" {markers}" if markers else ""
        line = f"{'  ' * level}- {node.get('class', '?')}{text_part}{marker_part}{transparent_part}"
        lines.append(line)

        children = node.get("children") or []
        child_text = _format_widget_snapshot(children, depth=depth, level=level + 1)
        if child_text:
            lines.append(child_text)

    return "\n".join(lines)


def _snapshot_handle_for_widget(connection: ManagedConnection, wid: int | None) -> str | None:
    return connection.handle_for_wid(wid if isinstance(wid, int) and not isinstance(wid, bool) else None)


def _snapshot_display_label(node: dict[str, Any]) -> tuple[str, str]:
    text = node.get("text") or ""
    if text:
        return text, ""

    accessible_name = node.get("accessibleName") or ""
    if accessible_name:
        return accessible_name, "[a11y]"

    for key in ("currentText", "windowTitle", "value"):
        value = node.get(key)
        if value is None or value == "":
            continue
        return str(value), ""

    return "", ""


def _snapshot_item_view_marker(node: dict[str, Any]) -> str:
    item_view = node.get("itemView")
    if not isinstance(item_view, dict):
        return ""
    kind = item_view.get("kind")
    if not isinstance(kind, str) or not kind:
        return ""
    discoverable_by = item_view.get("discoverableBy")
    if isinstance(discoverable_by, str) and discoverable_by:
        return f"[item-view={kind}; use {discoverable_by}]"
    return f"[item-view={kind}]"


def _snapshot_entry(node: dict[str, Any], handle: str | None, *, include_geometry: bool = True) -> dict[str, Any]:
    entry = {
        "handle": handle,
        "class": node.get("class", ""),
    }
    if include_geometry:
        compact_geometry = _compact_geometry(node.get("geometry"))
        if compact_geometry is not None:
            entry["geometry"] = compact_geometry
    attribute = _attribute_summary(node)
    if attribute is not None:
        entry["attribute"] = attribute
    key_map = {
        "text": "text",
        "accessibleName": "accessible_name",
        "accessibleDescription": "accessible_description",
        "currentText": "current_text",
        "windowTitle": "window_title",
        "value": "value",
        "objectName": "object_name",
    }
    for key, output_key in key_map.items():
        value = node.get(key)
        if value is None or value == "":
            continue
        entry[output_key] = value
    for key in ("visible", "enabled", "interactable"):
        if node.get(key) is False:
            entry[key] = False
    item_view = node.get("itemView")
    if isinstance(item_view, dict) and item_view:
        entry["item_view"] = dict(item_view)
    return entry


def _is_infrastructure_widget_node(node: dict[str, Any]) -> bool:
    object_name = node.get("objectName")
    if isinstance(object_name, str) and object_name.startswith("qt_"):
        return True

    widget_class = node.get("class")
    if isinstance(widget_class, str) and widget_class in _INFRASTRUCTURE_WIDGET_CLASSES:
        return True

    if _is_mouse_transparent(node):
        return True

    return False


def _filter_infrastructure_nodes(
    nodes: list[dict[str, Any]],
    *,
    preserve_roots: bool = False,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []

    for node in nodes:
        filtered_children = _filter_infrastructure_nodes(node.get("children") or [])
        normalized = dict(node)
        if filtered_children:
            normalized["children"] = filtered_children
        else:
            normalized.pop("children", None)

        if not preserve_roots and _is_infrastructure_widget_node(normalized):
            filtered.extend(filtered_children)
            continue

        filtered.append(normalized)

    return filtered


def _render_snapshot_tree(
    connection: ManagedConnection,
    nodes: list[dict[str, Any]],
    *,
    depth: int = 10,
    level: int = 0,
    seen_wids: set[int] | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    if level > depth:
        return [], []

    if seen_wids is None:
        seen_wids = set()

    lines: list[str] = []
    tree: list[dict[str, Any]] = []

    for node in nodes:
        wid = node.get("wid")
        if wid is not None:
            if wid in seen_wids:
                continue
            seen_wids.add(wid)

        handle = _snapshot_handle_for_widget(connection, wid)
        handle_part = f" @{handle}" if handle else ""
        transparent_part = " !transparent" if _is_mouse_transparent(node) else ""
        label, marker = _snapshot_display_label(node)
        text_part = f' "{label}"' if label else ""
        markers = " ".join(part for part in (marker, *_snapshot_state_markers(node)) if part)
        marker_part = f" {markers}" if markers else ""
        active_part = " [active]" if wid == connection.active_window_wid else ""
        lines.append(f"{'  ' * level}- {node.get('class', '?')}{text_part}{marker_part}{active_part}{handle_part}{transparent_part}")

        child_lines, child_tree = _render_snapshot_tree(
            connection,
            node.get("children") or [],
            depth=depth,
            level=level + 1,
            seen_wids=seen_wids,
        )
        entry = _snapshot_entry(node, handle, include_geometry=False)
        entry["children"] = child_tree
        lines.extend(child_lines)
        tree.append(entry)

    return lines, tree


def _snapshot_window_payload(connection: ManagedConnection) -> dict[str, Any] | None:
    active_window = _active_window_summary(connection)
    if active_window is None:
        return None

    return {
        "handle": connection.handle_for_wid(active_window.get("wid")),
        "title": active_window.get("title", ""),
        "class": active_window.get("class", ""),
        "geometry": _window_geometry(active_window),
    }


def _snapshot_payload(
    connection: ManagedConnection,
    nodes: list[dict[str, Any]],
    *,
    depth: int = 10,
    include_infrastructure: bool = False,
    preserve_roots: bool = False,
) -> dict[str, Any]:
    if not include_infrastructure:
        nodes = _filter_infrastructure_nodes(nodes, preserve_roots=preserve_roots)

    lines, tree = _render_snapshot_tree(connection, nodes, depth=depth)
    root_wid = None
    if nodes:
        candidate = nodes[0].get("wid")
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            root_wid = candidate
    root_handle = connection.handle_for_wid(root_wid if root_wid is not None else connection.active_window_wid)
    return {
        "ok": True,
        "window": _snapshot_window_payload(connection),
        "root_handle": root_handle,
        "snapshot": "\n".join(lines),
        "tree": tree,
    }


def _write_text_file(path: str, content: str) -> str:
    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")
    return str(target_path)


def _next_managed_screenshot_path() -> Path:
    _SCREENSHOT_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return _SCREENSHOT_TEMP_DIR / f"screenshot-{timestamp}-{uuid4().hex[:8]}.png"


def _normalize_screenshot_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise TypeError(f"Unexpected screenshot result type: {type(result)!r}")

    path = result.get("path")
    if isinstance(path, str) and path:
        normalized = dict(result)
        normalized.pop("data", None)
        return normalized

    data = result.get("data")
    if not isinstance(data, str) or not data:
        raise ValueError("Screenshot result did not include a file path or image data")

    target_path = _next_managed_screenshot_path()
    target_path.write_bytes(base64.b64decode(data))

    normalized = {key: value for key, value in result.items() if key != "data"}
    normalized["path"] = str(target_path)
    return normalized


def _target_params(connection: ManagedConnection, target: str, **extra: Any) -> dict[str, Any]:
    if _HANDLE_PATTERN.match(target):
        params: dict[str, Any] = {"wid": connection.wid_for_handle(target)}
    else:
        params = {"selector": target}
    params.update(extra)
    return params


def _normalize_find_string(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    if not value.strip():
        raise ValueError(f"{name} must be a non-empty string when provided")
    return value


def _normalize_object_name_batch(object_names: Sequence[str]) -> list[str]:
    if isinstance(object_names, (str, bytes)):
        raise ValueError("object_names must be a list of non-empty strings")

    normalized: list[str] = []
    seen: set[str] = set()
    for value in object_names:
        if not isinstance(value, str):
            raise ValueError("object_names must contain only strings")
        candidate = value.strip()
        if not candidate:
            raise ValueError("object_names must contain only non-empty strings")
        if candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)

    if not normalized:
        raise ValueError("object_names must contain at least one non-empty string")

    return normalized


def _resolve_find_root_wid(connection: ManagedConnection, root: str | None) -> int:
    if root is None:
        return _resolve_window(connection).wid

    candidate = root.strip()
    if not candidate:
        raise ValueError("root must be a non-empty selector or stable handle")

    if _HANDLE_PATTERN.match(candidate):
        return connection.wid_for_handle(candidate)

    locator = _resolve_window(connection).locator(candidate)
    count = locator.count()
    if count == 0:
        raise ValueError(f"No widget found for find root {candidate!r}. Run snapshot or inspect to discover the UI first.")
    if count > 1:
        raise ValueError(
            f"Find root {candidate!r} is ambiguous ({count} matches). Use find to narrow candidates before using it as a root."
        )

    return _resolve_locator_owner_wid(locator, context=f"Find root {candidate!r}")


def _find_ancestor_summary_entry(connection: ManagedConnection, node: dict[str, Any]) -> dict[str, Any]:
    entry = {
        "handle": connection.handle_for_wid(node.get("wid")),
        "class": node.get("class", ""),
    }
    label, _marker = _snapshot_display_label(node)
    if label:
        entry["label"] = label
    return entry


def _find_result_entry(connection: ManagedConnection, node: dict[str, Any]) -> dict[str, Any]:
    entry = _snapshot_entry(node, connection.handle_for_wid(node.get("wid")))

    for key in ("visible", "enabled", "interactable"):
        value = node.get(key)
        if isinstance(value, bool):
            entry[key] = value

    match_reason = node.get("matchReason")
    if isinstance(match_reason, list) and match_reason:
        entry["match_reason"] = [str(reason) for reason in match_reason]

    ancestor_summary = node.get("ancestorSummary")
    if isinstance(ancestor_summary, list) and ancestor_summary:
        entry["ancestor_summary"] = [
            _find_ancestor_summary_entry(connection, ancestor)
            for ancestor in ancestor_summary
            if isinstance(ancestor, dict)
        ]

    return entry


def _find_result(
    connection: ManagedConnection,
    *,
    mode: FindMode = "auto",
    root: str | None = None,
    keyword: str | None = None,
    role: str | None = None,
    text: str | None = None,
    widget_class: str | None = None,
    object_name: str | None = None,
    accessible_name: str | None = None,
    visible: bool | None = None,
    enabled: bool | None = None,
    interactable: bool | None = None,
    include_infrastructure: bool = False,
    limit: int = 5,
    timeout: float | None = None,
) -> dict[str, Any]:
    resolved_mode = "fuzzy" if mode == "auto" and keyword is not None else ("exact" if mode == "auto" else mode)
    root_wid = _resolve_find_root_wid(connection, root)
    raw = _find_widgets_raw(
        connection,
        root_wid=root_wid,
        keyword=_normalize_find_string("keyword", keyword),
        role=_normalize_find_string("role", role),
        text=_normalize_find_string("text", text),
        widget_class=_normalize_find_string("class", widget_class),
        object_name=_normalize_find_string("object_name", object_name),
        accessible_name=_normalize_find_string("accessible_name", accessible_name),
        visible=visible,
        enabled=enabled,
        interactable=interactable,
        include_infrastructure=include_infrastructure,
        limit=limit,
        timeout=timeout,
    )
    results = raw.get("results") or []
    raw_root_wid = raw.get("rootWid")
    root_handle = connection.handle_for_wid(raw_root_wid if isinstance(raw_root_wid, int) else root_wid)
    return {
        "search_mode": resolved_mode,
        "root_handle": root_handle,
        "count": int(raw.get("count", len(results))),
        "truncated": bool(raw.get("truncated", False)),
        "results": [
            _find_result_entry(connection, entry)
            for entry in results
            if isinstance(entry, dict)
        ],
    }


def _iter_widget_tree_nodes(nodes: Sequence[dict[str, Any]]) -> Any:
    for node in nodes:
        if not isinstance(node, dict):
            continue
        yield node
        children = node.get("children")
        if isinstance(children, list):
            yield from _iter_widget_tree_nodes(children)


def _resolve_object_names_result(
    connection: ManagedConnection,
    *,
    root: str | None = None,
    object_names: Sequence[str],
    depth: int = 10,
    include_infrastructure: bool = False,
    timeout: float | None = None,
) -> dict[str, Any]:
    if depth <= 0:
        raise ValueError("depth must be > 0")

    normalized_names = _normalize_object_name_batch(object_names)
    requested_names = set(normalized_names)
    root_wid = _resolve_find_root_wid(connection, root)
    nodes = _widget_tree_raw(
        connection,
        max_depth=depth,
        window_wid=root_wid,
        topmost_only=False,
        timeout=timeout,
    )
    if not include_infrastructure:
        nodes = _filter_infrastructure_nodes(nodes, preserve_roots=True)

    matched_entries: dict[str, list[dict[str, Any]]] = {name: [] for name in normalized_names}
    seen_wids: set[int] = set()
    for node in _iter_widget_tree_nodes(nodes):
        wid = node.get("wid")
        if isinstance(wid, int):
            if wid in seen_wids:
                continue
            seen_wids.add(wid)

        object_name = node.get("objectName")
        if not isinstance(object_name, str) or object_name not in requested_names:
            continue

        matched_entries[object_name].append(_snapshot_entry(node, connection.handle_for_wid(wid)))

    handles: dict[str, str] = {}
    resolved: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    ambiguous: dict[str, list[dict[str, Any]]] = {}

    for name in normalized_names:
        entries = matched_entries[name]
        if len(entries) == 1:
            resolved[name] = entries[0]
            handle = entries[0].get("handle")
            if isinstance(handle, str) and handle:
                handles[name] = handle
            continue
        if not entries:
            missing.append(name)
            continue
        ambiguous[name] = entries

    return {
        "root_handle": connection.handle_for_wid(root_wid),
        "requested": normalized_names,
        "handles": handles,
        "resolved": resolved,
        "missing": missing,
        "ambiguous": ambiguous,
    }


def _snapshot_result(
    managed_connection: ManagedConnection,
    *,
    target: str | None = None,
    depth: int = 10,
    topmost_only: bool = False,
    include_infrastructure: bool = False,
    timeout: float | None = None,
) -> dict[str, Any]:
    target_params = _target_params(managed_connection, target, max_depth=depth) if target is not None else None

    if target is None:
        return _snapshot_payload(
            managed_connection,
            _widget_tree_raw(
                managed_connection,
                max_depth=depth,
                window_wid=managed_connection.active_window_wid,
                topmost_only=topmost_only,
                include_interactable=True,
                timeout=timeout,
            ),
            depth=depth,
            include_infrastructure=include_infrastructure,
        )

    assert target_params is not None
    find_params = dict(target_params)
    find_params["include_interactable"] = True
    node = managed_connection.app._conn.send(
        METHOD_FIND,
        find_params,
        timeout=timeout if timeout is not None else managed_connection.timeout,
    )
    if node is None:
        raise ValueError(_target_not_found_message(managed_connection, target))
    return _snapshot_payload(
        managed_connection,
        [node],
        depth=depth,
        include_infrastructure=include_infrastructure,
        preserve_roots=True,
    )


def _public_observation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    public_payload = dict(payload)
    public_payload.pop("snapshot", None)
    return public_payload


def _topmost_only_warnings(*, topmost_only: bool, target: str | None = None) -> list[str]:
    if not topmost_only:
        return []
    if target is not None:
        return []
    return [_TOPMOST_ONLY_WARNING]


def _press_key_without_target(connection: ManagedConnection, *, key: str) -> None:
    client = _require_session_transport(connection, action="targetless press_key")

    params: dict[str, Any] = {"key": key}
    if connection.active_window_wid is not None:
        params["window_wid"] = connection.active_window_wid
    client.send(METHOD_PRESS, params, timeout=connection.timeout)


def _pointer_action_coords(*, x: int | None, y: int | None) -> dict[str, int]:
    if (x is None) != (y is None):
        raise ValueError("Coordinate pointer actions require x and y together")
    if x is None:
        return {}
    assert y is not None

    point_x = int(x)
    point_y = int(y)
    if point_x < 0 or point_y < 0:
        raise ValueError("Coordinate pointer actions require non-negative x and y")
    return {"x": point_x, "y": point_y}


def _pointer_action_without_target(connection: ManagedConnection, *, method: str, x: int, y: int) -> None:
    client = _require_session_transport(connection, action=f"targetless {method}")

    params: dict[str, Any] = {"x": x, "y": y}
    if connection.active_window_wid is not None:
        params["window_wid"] = connection.active_window_wid
    client.send(method, params, timeout=connection.timeout)


def _action_result_with_snapshot(
    managed_connection: ManagedConnection,
    *,
    target: str | None = None,
    depth: int = 3,
    timeout: float | None = None,
    **payload: Any,
) -> dict[str, Any]:
    result = dict(payload)
    with contextlib.suppress(Exception):
        q_application = _qt_application_instance(required=False)
        if q_application is not None:
            q_application.processEvents()
    result["observation"] = _public_observation_payload(
        _snapshot_result(managed_connection, target=target, depth=depth, timeout=timeout)
    )
    return result


def _observe_action_window_state(
    managed_connection: ManagedConnection,
    *,
    timeout: float | None = None,
) -> dict[str, Any]:
    previous_active_window_wid = managed_connection.active_window_wid
    windows = _summarize_windows(
        managed_connection,
        _list_windows_raw(managed_connection, timeout=timeout),
    )

    active_window = _active_window_summary(managed_connection, windows=windows)

    next_active_window_wid = active_window["wid"] if active_window is not None else None
    if next_active_window_wid != managed_connection.active_window_wid:
        _select_active_window(managed_connection, next_active_window_wid)

    return {
        "window_changed": next_active_window_wid != previous_active_window_wid,
        "active_window": active_window,
    }


def _observe_action_target_state(
    managed_connection: ManagedConnection,
    *,
    target: str | dict[str, Any],
) -> dict[str, Any]:
    if isinstance(target, str):
        locator = _resolve_widget_handle_locator(managed_connection, target=target, action="state inspection")
        return _compact_action_state(managed_connection, locator)

    locator = _resolve_item_locator(managed_connection, target=target)
    return _compact_item_state(managed_connection, locator)


def _normalize_choose_selectors(
    *,
    value: str | None,
    index: int | None,
    label: str | None,
) -> tuple[str | None, int | None, str | None]:
    has_meaningful_string = any(
        isinstance(candidate, str) and candidate.strip() != ""
        for candidate in (value, label)
    )
    if has_meaningful_string or index is not None:
        if isinstance(value, str) and value.strip() == "":
            value = None
        if isinstance(label, str) and label.strip() == "":
            label = None

    return value, index, label


def _normalize_wait_expected(condition: str, expected: str | int | bool | None) -> str | int | bool:
    if expected is None:
        raise ValueError("expected is required when condition is provided")

    if condition == "count_equals":
        if isinstance(expected, bool):
            raise ValueError("expected for count_equals must be an integer")
        if isinstance(expected, int):
            return expected
        try:
            return int(expected)
        except (TypeError, ValueError) as exc:
            raise ValueError("expected for count_equals must be an integer") from exc

    if condition == "checked_equals":
        if isinstance(expected, bool):
            return expected
        if isinstance(expected, str):
            normalized = expected.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        raise ValueError("expected for checked_equals must be a boolean")

    return str(expected)


def _wait_condition_matches(locator: Any, *, condition: str, expected: str | int | bool) -> bool:
    if condition == "count_equals":
        return locator.count() == expected

    count = locator.count()
    if count == 0:
        return False

    first = locator.first()

    if condition == "checked_equals":
        return first.is_checked() is expected

    if condition in {"text_equals", "text_contains"}:
        actual = first.text_content()
    elif condition in {"current_text_equals", "current_text_contains"}:
        actual = first.properties().get("currentText")
    elif condition == "value_equals":
        actual = first.input_value()
    else:
        raise ValueError(f"Unsupported wait condition: {condition!r}")

    if actual in (None, ""):
        return False

    if condition.endswith("_contains"):
        return str(expected).lower() in str(actual).lower()

    return str(actual) == str(expected)


def _wait_for_locator_condition(
    locator: Any,
    *,
    condition: str,
    expected: str | int | bool,
    timeout: float,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _wait_condition_matches(locator, condition=condition, expected=expected):
            return
        time.sleep(0.05)

    raise TimeoutError(f"Timed out waiting for {condition}={expected!r}")


def _finalize_action_result(
    managed_connection: ManagedConnection,
    *,
    include_state: bool = False,
    include_snapshot: bool = False,
    state_target: str | dict[str, Any] | None = None,
    snapshot_target: str | None = None,
    snapshot_depth: int = 3,
    **payload: Any,
) -> dict[str, Any]:
    result = dict(payload)
    post_action_warnings: list[str] = []
    postprocess_timeout = min(managed_connection.timeout, _ACTION_POSTPROCESS_TIMEOUT)

    try:
        result.update(_observe_action_window_state(managed_connection, timeout=postprocess_timeout))
    except Exception as exc:
        result["window_changed"] = None
        result["active_window"] = None
        post_action_warnings.append(
            f"post-action window state unavailable: {exc}. Window state is unknown; retry snapshot if you need to confirm focus or modal changes."
        )

    if include_state:
        if state_target is None:
            result["state"] = None
        else:
            try:
                result["state"] = _observe_action_target_state(managed_connection, target=state_target)
            except Exception as exc:
                result["state"] = None
                post_action_warnings.append(f"post-action target state unavailable: {exc}")

    if not include_snapshot:
        if post_action_warnings:
            result["warnings"] = post_action_warnings
        return result

    window_changed = result.get("window_changed")
    effective_target = snapshot_target if window_changed is False else None
    try:
        result.update(
            _action_result_with_snapshot(
                managed_connection,
                target=effective_target,
                depth=snapshot_depth,
                timeout=postprocess_timeout,
            )
        )
    except Exception as exc:
        post_action_warnings.append(f"post-action observation unavailable: {exc}")

    if post_action_warnings:
        result["warnings"] = post_action_warnings
    return result


if FastMCP is not None:
    mcp = FastMCP(
        "qplaywright",
        instructions=(
            "Automate Qt QWidget applications through qplaywright. "
            "Use session, window, snapshot, inspect, and inspect_items to observe the UI before "
            "performing destructive UI actions. Geometry fields use Rect4 arrays in the form [x, y, width, height]."
        ),
        json_response=True,
    )


    @mcp.resource("qplaywright://help/selectors")
    def selector_help() -> str:
        """Selector syntax and recommended qplaywright MCP workflow."""

        return _selector_help_text()


    @mcp.resource("qplaywright://help/geometry")
    def geometry_help() -> str:
        """Geometry field semantics for Rect4 response values."""

        return _geometry_help_text()


    @mcp.tool()
    def session(
        action: SessionActionArg,
        host: HostArg = DEFAULT_HOST,
        port: PortArg = DEFAULT_PORT,
        timeout: TimeoutSecondsArg = 30.0,
        executable: ExecutableArg = None,
        args: LaunchArgsArg = None,
        agent_name: AgentNameArg = "GitHub Copilot",
    ) -> dict[str, Any]:
        """Manage the active qplaywright session.

        action must be one of:
        - attach: attach to an already running Qt app
        - launch: launch a Qt app and attach
        - close: close the current session
        - status: report current session and active window
        """

        if action == "attach":
            connection_state = connect_connection(
                _SERVER_STATE,
                host=host,
                port=port,
                timeout=timeout,
                agent_name=agent_name,
            )
            windows = _window_summary(connection_state)
            return {
                "ok": True,
                "action": action,
                "session": _session_summary(connection_state),
                "active_window": _active_window_summary(connection_state, windows=windows),
            }

        if action == "launch":
            if not executable:
                raise ValueError("executable is required when action='launch'")
            connection_state = launch_connection(
                _SERVER_STATE,
                executable=executable,
                args=args,
                host=host,
                port=port,
                timeout=timeout,
                agent_name=agent_name,
            )
            windows = _window_summary(connection_state)
            return {
                "ok": True,
                "action": action,
                "session": _session_summary(connection_state),
                "active_window": _active_window_summary(connection_state, windows=windows),
            }

        if action == "close":
            result = disconnect_connection(_SERVER_STATE)
            return {"ok": True, "action": action, "closed": result["closed"]}

        if action == "status":
            connection_state = _get_connection(_SERVER_STATE)
            windows = _window_summary(connection_state)
            return {
                "ok": True,
                "action": action,
                "session": _session_summary(connection_state),
                "active_window": _active_window_summary(connection_state, windows=windows),
            }

        raise ValueError(f"Unsupported session action: {action!r}")


    @mcp.tool()
    def window(
        action: WindowActionArg,
        index: WindowIndexArg = None,
        wid: WindowWidArg = None,
        title: WindowTitleArg = None,
        width: WindowWidthArg = None,
        height: WindowHeightArg = None,
    ) -> dict[str, Any]:
        """Manage top-level windows in the current session.

        action must be one of:
        - list: list visible top-level windows
        - select: switch active window
        - resize: resize one window or the active window
        - close: close one window or the active window

        Geometry semantics:
        - window.geometry is Rect4: [x, y, width, height]
        - for top-level windows, x and y are screen-space coordinates
        """

        connection_state = _get_connection(_SERVER_STATE)

        if action == "list":
            windows = _window_summary(connection_state)
            return {
                "ok": True,
                "action": action,
                "windows": windows,
                "active_window": _active_window_summary(connection_state, windows=windows),
            }

        if action == "select":
            _require_exactly_one_window_selector(index=index, wid=wid, title=title)
            selected_window = _resolve_window(
                connection_state,
                window_wid=wid,
                window_title=title,
                window_index=index,
            )
            _select_active_window(connection_state, selected_window.wid, override_scope=True)
            return {
                "ok": True,
                "action": action,
                "active_window": _active_window_summary(connection_state),
            }

        if action == "resize":
            if width is None or height is None:
                raise ValueError("width and height are required when action='resize'")
            target_window = _resolve_window(
                connection_state,
                window_wid=wid,
                window_title=title,
                window_index=index,
            )
            target_window.resize(width, height)
            return {
                "ok": True,
                "action": action,
                "active_window": _active_window_summary(connection_state),
            }

        if action == "close":
            target_window = _resolve_window(
                connection_state,
                window_wid=wid,
                window_title=title,
                window_index=index,
            )
            target_window.close()
            remaining_windows = _window_summary(connection_state)
            if not any(window["wid"] == connection_state.active_window_wid for window in remaining_windows):
                _select_active_window(connection_state, remaining_windows[0]["wid"] if remaining_windows else None)
            return {
                "ok": True,
                "action": action,
                "active_window": _active_window_summary(connection_state, windows=remaining_windows),
            }

        raise ValueError(f"Unsupported window action: {action!r}")


    @mcp.tool()
    def snapshot(
        target: OptionalWidgetDiscoveryTargetArg = None,
        depth: DepthArg = 10,
        topmost_only: TopmostOnlyArg = False,
        include_infrastructure: IncludeInfrastructureArg = False,
        save_to: SaveToArg = None,
    ) -> dict[str, Any]:
        """Return a structured snapshot of the current active window or one target.

        Use target plus depth when you want to inspect one subtree and capture
        several child handles in one call.

        The returned payload is JSON-first. Use `tree` and `root_handle` as
        the primary observation surface. `save_to` can still export the internal
        text snapshot for external debugging.

        When topmost_only is true, the window-wide snapshot becomes an approximate
        frontmost-visible view and may be incomplete.

        Snapshot tree semantics:
        - tree nodes expose stable handles, semantic labels, sparse negative state, and children
        - tree nodes omit geometry by default; use inspect when you need geometry or screen-space bounds

        Snapshot state semantics:
        - tree nodes only emit visible, enabled, and interactable when the value is false
        - text snapshot lines add [hidden], [disabled], and [non-interactable] only when those states apply
        """

        connection_state = _get_connection(_SERVER_STATE)
        active_window = _active_window_summary(connection_state)
        payload = _snapshot_result(
            connection_state,
            target=target,
            depth=depth,
            topmost_only=topmost_only,
            include_infrastructure=include_infrastructure,
        )
        text_snapshot = payload.get("snapshot")
        public_payload = _public_observation_payload(payload)
        result = {
            "ok": True,
            "session": _session_summary(connection_state),
            "window": active_window,
            "target": target,
            "topmost_only": topmost_only,
            "include_infrastructure": include_infrastructure,
            **public_payload,
        }
        warnings = _topmost_only_warnings(topmost_only=topmost_only, target=target)
        if warnings:
            result["warnings"] = warnings
        if save_to is not None:
            result["save_to"] = _write_text_file(save_to, text_snapshot if isinstance(text_snapshot, str) else "")
        return result


    @mcp.tool()
    def inspect(
        target: OptionalDiscoveryOrItemTargetArg = None,
        property: PropertyArg = None,
        include_methods: IncludeMethodsArg = False,
        include_properties: IncludePropertiesArg = False,
        depth: DepthArg = 10,
        topmost_only: TopmostOnlyArg = False,
        include_infrastructure: IncludeInfrastructureArg = False,
    ) -> dict[str, Any]:
        """Inspect one target or return the current active window tree in debug mode.

        When topmost_only is true and target is omitted, the returned tree is an
        approximate frontmost-visible view and may be incomplete.

                Geometry semantics for targeted inspect:
                - geometry is Rect4 [x, y, width, height] in widget-local coordinates
                - global_bounding_box is Rect4 in screen coordinates
                - bounding_box is the existing locator-compatible screen-space Rect4 and is
                    currently identical to global_bounding_box
        """

        connection_state = _get_connection(_SERVER_STATE)
        if target is None:
            tree = _widget_tree_raw(
                connection_state,
                max_depth=depth,
                window_wid=connection_state.active_window_wid,
                topmost_only=topmost_only,
            )
            if not include_infrastructure:
                tree = _filter_infrastructure_nodes(tree)
            result = {
                "ok": True,
                "target": None,
                "depth": depth,
                "include_infrastructure": include_infrastructure,
                "tree": tree,
            }
            warnings = _topmost_only_warnings(topmost_only=topmost_only, target=None)
            if warnings:
                result["warnings"] = warnings
            return result

        if isinstance(target, str):
            locator = _resolve_locator(connection_state, target=target)
            result = _inspect_locator(
                locator,
                connection=connection_state,
                property_name=property,
                include_methods=include_methods,
                include_properties=include_properties,
            )
        else:
            locator = _resolve_item_locator(connection_state, target=target)
            result = _inspect_item_locator(
                locator,
                property_name=property,
                include_methods=include_methods,
                include_properties=include_properties,
            )
        return {
            "ok": True,
            "target": target,
            **result,
        }


    @mcp.tool()
    def find(
        mode: FindModeArg = "auto",
        keyword: FindKeywordArg = None,
        root: FindRootArg = None,
        role: FindRoleArg = None,
        text: FindTextArg = None,
        class_: FindClassArg = None,
        object_name: FindObjectNameArg = None,
        accessible_name: FindAccessibleNameArg = None,
        visible: FindVisibleArg = None,
        enabled: FindEnabledArg = None,
        interactable: FindInteractableArg = None,
        include_infrastructure: IncludeInfrastructureArg = False,
        limit: FindLimitArg = 5,
    ) -> dict[str, Any]:
        """Return a small candidate set within one root scope using exact, fuzzy, or auto search.

        Use mode=exact for deterministic constraints such as exact text,
        role, class, or object_name. Use mode=fuzzy with keyword when you only
        know an approximate visible phrase, semantic label, window title, or
        object name clue. mode=auto chooses fuzzy when keyword is provided and
        exact otherwise.
        """

        if limit <= 0:
            raise ValueError("limit must be > 0")
        if mode == "exact" and keyword is not None:
            raise ValueError("find mode='exact' does not accept keyword; use mode='fuzzy' or mode='auto'")
        if mode == "fuzzy" and keyword is None:
            raise ValueError("find mode='fuzzy' requires keyword")

        connection_state = _get_connection(_SERVER_STATE)
        payload = _find_result(
            connection_state,
            mode=mode,
            root=root,
            keyword=keyword,
            role=role,
            text=text,
            widget_class=class_,
            object_name=object_name,
            accessible_name=accessible_name,
            visible=visible,
            enabled=enabled,
            interactable=interactable,
            include_infrastructure=include_infrastructure,
            limit=limit,
        )
        return {
            "ok": True,
            **payload,
        }


    @mcp.tool()
    def resolve_object_names(
        object_names: ResolveObjectNamesArg,
        root: FindRootArg = None,
        depth: DepthArg = 10,
        include_infrastructure: IncludeInfrastructureArg = False,
    ) -> dict[str, Any]:
        """Resolve several exact objectName values to stable handles within one root scope.

        Use this when one known subtree exposes deliberate stable objectName
        values and you want several handles in one call. Missing or duplicated
        names are reported explicitly instead of guessed.
        """

        connection_state = _get_connection(_SERVER_STATE)
        payload = _resolve_object_names_result(
            connection_state,
            object_names=object_names,
            root=root,
            depth=depth,
            include_infrastructure=include_infrastructure,
        )
        return {
            "ok": True,
            **payload,
        }

    @mcp.tool()
    def click(
        target: OptionalActionTargetArg = None,
        count: ClickCountArg = 1,
        x: ClipXArg = None,
        y: ClipYArg = None,
        include_state: IncludeStateArg = False,
        include_snapshot: IncludeSnapshotArg = False,
    ) -> dict[str, Any]:
        """Click or double-click a target, or a window-relative coordinate in the active window."""

        if count not in (1, 2):
            raise ValueError("count must be 1 or 2")

        connection_state = _get_connection(_SERVER_STATE)
        coords = _pointer_action_coords(x=x, y=y)
        if target is None:
            if not coords:
                raise ValueError("click requires either a target or x/y coordinates")
            method = METHOD_DBLCLICK if count == 2 else METHOD_CLICK
            _pointer_action_without_target(connection_state, method=method, x=coords["x"], y=coords["y"])
        else:
            if coords:
                raise ValueError("click does not accept x/y together with target")
            if isinstance(target, str):
                locator = _resolve_widget_handle_locator(connection_state, target=target, action="click")
            else:
                locator = _resolve_item_locator(connection_state, target=target)
            try:
                if count == 2:
                    locator.dblclick()
                else:
                    locator.click()
            except QPlaywrightActionError as exc:
                if isinstance(target, str):
                    _raise_if_hidden_click_target(
                        locator,
                        target=target,
                        action="dblclick" if count == 2 else "click",
                        exc=exc,
                    )
                raise ValueError(
                    f"{'dblclick' if count == 2 else 'click'} failed for target {target!r}: {exc}"
                ) from exc

        snapshot_target = _target_owner_target(target) if target is not None else None
        return _finalize_action_result(
            connection_state,
            include_state=include_state,
            include_snapshot=include_snapshot,
            state_target=target,
            snapshot_target=snapshot_target,
            ok=True,
            count=count,
            target=target,
            **coords,
        )


    @mcp.tool()
    def inspect_items(
        target: WidgetDiscoveryTargetArg,
        max_rows: InspectItemsMaxRowsArg = 20,
        max_depth: InspectItemsMaxDepthArg = 4,
        max_items: InspectItemsMaxItemsArg = 200,
        include_hidden: IncludeHiddenItemsArg = False,
    ) -> dict[str, Any]:
        """Enumerate structured descendants for one table, tree, list, or tab widget."""

        if max_rows < 0:
            raise ValueError("max_rows must be >= 0")
        if max_depth < 0:
            raise ValueError("max_depth must be >= 0")
        if max_items < 0:
            raise ValueError("max_items must be >= 0")

        connection_state = _get_connection(_SERVER_STATE)
        payload = _item_view_inspect(
            connection_state,
            target=target,
            max_rows=max_rows,
            max_depth=max_depth,
            max_items=max_items,
            include_hidden=include_hidden,
        )
        return {
            "ok": True,
            "target": target,
            **payload,
        }


    @mcp.tool()
    def input(
        target: WidgetHandleArg,
        text: InputTextArg = "",
        mode: InputModeArg = "replace",
        delay: InputDelayArg = 0,
        submit: SubmitArg = False,
        include_state: IncludeStateArg = False,
        include_snapshot: IncludeSnapshotArg = False,
    ) -> dict[str, Any]:
        """Input text into one widget resolved by stable handle."""

        if mode not in ("replace", "append", "type", "clear"):
            raise ValueError("mode must be 'replace', 'append', 'type', or 'clear'")
        if delay < 0:
            raise ValueError("delay must be >= 0")
        if mode == "clear" and submit:
            raise ValueError("clear mode does not support submit")
        if mode != "clear" and not text:
            raise ValueError("text must not be empty unless mode='clear'")

        connection_state = _get_connection(_SERVER_STATE)
        locator = _resolve_widget_handle_locator(connection_state, target=target, action="input")
        try:
            if mode == "replace":
                if delay == 0:
                    locator.fill(text)
                else:
                    locator.clear()
                    locator.type(text, delay=delay)
            elif mode == "append":
                locator.type(text, delay=delay)
            elif mode == "type":
                locator.type(text, delay=delay)
            else:
                locator.clear()

            if submit:
                locator.press("Enter")
        except QPlaywrightActionError as exc:
            raise ValueError(f"Input failed for target {target!r}: {exc}") from exc

        return _finalize_action_result(
            connection_state,
            include_state=include_state,
            include_snapshot=include_snapshot,
            state_target=target,
            snapshot_target=target,
            ok=True,
            target=target,
            text=text,
            mode=mode,
            delay=delay,
            submitted=submit,
        )


    @mcp.tool()
    def invoke(
        target: WidgetHandleArg,
        method: MethodArg,
        args: InvokeArgsArg = None,
        include_state: IncludeStateArg = False,
        include_snapshot: IncludeSnapshotArg = False,
    ) -> dict[str, Any]:
        """Invoke one exposed custom widget method by exact name."""

        connection_state = _get_connection(_SERVER_STATE)
        locator = _resolve_widget_handle_locator(connection_state, target=target, action="invoke")
        result = _invoke_locator_method(locator, method_name=method, args=args)
        return _finalize_action_result(
            connection_state,
            include_state=include_state,
            include_snapshot=include_snapshot,
            state_target=target,
            snapshot_target=target,
            ok=True,
            target=target,
            method=method,
            args=dict(args or {}),
            result=result,
        )
    @mcp.tool()
    def press_key(
        key: KeyArg,
        target: OptionalWidgetHandleArg = None,
        include_state: IncludeStateArg = False,
        include_snapshot: IncludeSnapshotArg = False,
    ) -> dict[str, Any]:
        """Send a single key press to one widget resolved by stable handle."""

        connection_state = _get_connection(_SERVER_STATE)
        if target is None:
            _press_key_without_target(connection_state, key=key)
        else:
            locator = _resolve_widget_handle_locator(connection_state, target=target, action="press_key")
            _run_widget_tool_action(action="press_key", target=target, callback=lambda: locator.press(key))
        return _finalize_action_result(
            connection_state,
            include_state=include_state,
            include_snapshot=include_snapshot,
            state_target=target,
            snapshot_target=target,
            ok=True,
            target=target,
            key=key,
        )

    @mcp.tool()
    def focus(
        target: WidgetHandleArg,
        include_state: IncludeStateArg = False,
        include_snapshot: IncludeSnapshotArg = False,
    ) -> dict[str, Any]:
        """Focus one widget resolved by stable handle."""

        connection_state = _get_connection(_SERVER_STATE)
        locator = _resolve_widget_handle_locator(connection_state, target=target, action="focus")
        _run_widget_tool_action(action="focus", target=target, callback=locator.focus)
        return _finalize_action_result(
            connection_state,
            include_state=include_state,
            include_snapshot=include_snapshot,
            state_target=target,
            snapshot_target=target,
            ok=True,
            target=target,
        )

    @mcp.tool()
    def choose(
        target: WidgetHandleArg,
        value: ChooseValueArg = None,
        index: ChooseIndexArg = None,
        label: ChooseLabelArg = None,
        include_state: IncludeStateArg = False,
        include_snapshot: IncludeSnapshotArg = False,
    ) -> dict[str, Any]:
        """Select a combobox option by value, index, or label."""

        value, index, label = _normalize_choose_selectors(value=value, index=index, label=label)

        selector_count = sum(candidate is not None for candidate in (value, index, label))
        if selector_count != 1:
            raise ValueError("Exactly one of value, index, or label must be provided")

        connection_state = _get_connection(_SERVER_STATE)
        locator = _resolve_widget_handle_locator(connection_state, target=target, action="choose")
        _run_widget_tool_action(
            action="choose",
            target=target,
            callback=lambda: locator.select_option(value=value, index=index, label=label),
        )
        return _finalize_action_result(
            connection_state,
            include_state=include_state,
            include_snapshot=include_snapshot,
            state_target=target,
            snapshot_target=target,
            ok=True,
            target=target,
            value=value,
            index=index,
            label=label,
        )


    @mcp.tool()
    def wait(
        target: ActionTargetArg,
        state: WaitStateArg = None,
        condition: WaitConditionArg = None,
        expected: WaitExpectedArg = None,
        timeout: OptionalTimeoutArg = None,
        include_state: IncludeStateArg = False,
        include_snapshot: IncludeSnapshotArg = False,
    ) -> dict[str, Any]:
        """Wait until a widget reaches a supported state."""

        if state is None and condition is None:
            state = "visible"

        if state is not None and condition is not None:
            raise ValueError("state and condition are mutually exclusive")

        if condition is None and state not in _ALLOWED_WAIT_STATES:
            raise ValueError(f"state must be one of {sorted(_ALLOWED_WAIT_STATES)!r}")

        if condition is not None and condition not in _ALLOWED_WAIT_CONDITIONS:
            raise ValueError(f"condition must be one of {sorted(_ALLOWED_WAIT_CONDITIONS)!r}")

        normalized_expected: str | int | bool | None = None
        if condition is not None:
            normalized_expected = _normalize_wait_expected(condition, expected)

        connection_state = _get_connection(_SERVER_STATE)
        effective_timeout = timeout if timeout is not None else connection_state.timeout
        snapshot_target = _target_owner_target(target)

        if isinstance(target, str):
            locator = _resolve_widget_handle_locator(connection_state, target=target, action="wait")

            if condition is None:
                assert state is not None
                try:
                    locator.wait_for(state=state, timeout=timeout)
                except QPlaywrightActionError as exc:
                    raise ValueError(f"wait failed for target {target!r}: {exc}") from exc
                payload = {
                    "ok": True,
                    "target": target,
                    "state": state,
                    "timeout": timeout,
                }
            else:
                assert normalized_expected is not None
                _wait_for_locator_condition(
                    locator,
                    condition=condition,
                    expected=normalized_expected,
                    timeout=effective_timeout,
                )
                payload = {
                    "ok": True,
                    "target": target,
                    "condition": condition,
                    "expected": normalized_expected,
                    "timeout": timeout,
                }
        else:
            locator = _resolve_item_locator(connection_state, target=target)
            if condition is None:
                assert state is not None
                _wait_for_item_locator_state(locator, state=state, timeout=effective_timeout)
                payload = {
                    "ok": True,
                    "target": target,
                    "state": state,
                    "timeout": timeout,
                }
            else:
                if not isinstance(normalized_expected, str):
                    raise ValueError("item target waits require a string expected value")
                _wait_for_item_locator_condition(
                    locator,
                    condition=condition,
                    expected=normalized_expected,
                    timeout=effective_timeout,
                )
                payload = {
                    "ok": True,
                    "target": target,
                    "condition": condition,
                    "expected": normalized_expected,
                    "timeout": timeout,
                }

        return _finalize_action_result(
            connection_state,
            include_state=include_state,
            include_snapshot=include_snapshot,
            state_target=target,
            snapshot_target=snapshot_target,
            **payload,
        )


    @mcp.tool()
    def screenshot(
        target: OptionalWidgetHandleArg = None,
        path: ScreenshotPathArg = None,
        x: ClipXArg = None,
        y: ClipYArg = None,
        width: ClipWidthArg = None,
        height: ClipHeightArg = None,
    ) -> dict[str, Any]:
        """Capture a screenshot of the active window or one widget resolved by stable handle."""

        live_connection = _get_connection(_SERVER_STATE)
        clip_kwargs = _screenshot_clip_kwargs(x=x, y=y, width=width, height=height)
        clip_x = clip_kwargs.get("x")
        clip_y = clip_kwargs.get("y")
        clip_width = clip_kwargs.get("width")
        clip_height = clip_kwargs.get("height")
        if target is None:
            window = _resolve_window(live_connection)
            if clip_kwargs:
                result = window.screenshot(
                    path=path,
                    x=clip_x,
                    y=clip_y,
                    width=clip_width,
                    height=clip_height,
                )
            elif path:
                result = window.screenshot(path=path)
            else:
                result = window.screenshot()
        else:
            locator = _resolve_widget_handle_locator(live_connection, target=target, action="screenshot")
            if clip_kwargs:
                result = locator.screenshot(
                    path=path,
                    x=clip_x,
                    y=clip_y,
                    width=clip_width,
                    height=clip_height,
                )
            elif path:
                result = locator.screenshot(path=path)
            else:
                result = locator.screenshot()
        result = _normalize_screenshot_result(result)
        result["ok"] = True
        result["target"] = target
        result["active_window"] = _active_window_summary(live_connection)
        return result


    @mcp.tool()
    def hover(
        target: OptionalActionTargetArg = None,
        x: ClipXArg = None,
        y: ClipYArg = None,
        include_state: IncludeStateArg = False,
        include_snapshot: IncludeSnapshotArg = False,
    ) -> dict[str, Any]:
        """Hover a target, or a window-relative coordinate in the active window."""

        connection_state = _get_connection(_SERVER_STATE)
        coords = _pointer_action_coords(x=x, y=y)
        if target is None:
            if not coords:
                raise ValueError("hover requires either a target or x/y coordinates")
            _pointer_action_without_target(connection_state, method=METHOD_HOVER, x=coords["x"], y=coords["y"])
        else:
            if coords:
                raise ValueError("hover does not accept x/y together with target")
            if isinstance(target, str):
                locator = _resolve_widget_handle_locator(connection_state, target=target, action="hover")
                _run_widget_tool_action(action="hover", target=target, callback=locator.hover)
            else:
                locator = _resolve_item_locator(connection_state, target=target)
                try:
                    locator.hover()
                except QPlaywrightActionError as exc:
                    raise ValueError(f"hover failed for target {target!r}: {exc}") from exc

        snapshot_target = _target_owner_target(target) if target is not None else None
        return _finalize_action_result(
            connection_state,
            include_state=include_state,
            include_snapshot=include_snapshot,
            state_target=target,
            snapshot_target=snapshot_target,
            ok=True,
            target=target,
            **coords,
        )


    @mcp.tool()
    def set_expanded(
        target: ItemTargetArg,
        expanded: ExpandedArg,
        include_state: IncludeStateArg = False,
        include_snapshot: IncludeSnapshotArg = False,
    ) -> dict[str, Any]:
        """Expand or collapse one structured tree node item target."""

        connection_state = _get_connection(_SERVER_STATE)
        locator = _resolve_item_locator(connection_state, target=target)
        snapshot_target = _target_owner_target(target)

        try:
            if expanded:
                locator.expand()
            else:
                locator.collapse()
        except QPlaywrightActionError as exc:
            raise ValueError(f"set_expanded failed for target {target!r}: {exc}") from exc

        return _finalize_action_result(
            connection_state,
            include_state=include_state,
            include_snapshot=include_snapshot,
            state_target=target,
            snapshot_target=snapshot_target,
            ok=True,
            target=target,
            expanded=expanded,
        )


    @mcp.tool()
    def scroll(
        target: WidgetHandleArg,
        delta_x: DeltaXArg = 0,
        delta_y: DeltaYArg = 0,
        include_state: IncludeStateArg = False,
        include_snapshot: IncludeSnapshotArg = False,
    ) -> dict[str, Any]:
        """Send a mouse wheel scroll event to one widget resolved by stable handle."""

        if delta_x == 0 and delta_y == 0:
            raise ValueError("delta_x and delta_y cannot both be 0")

        connection_state = _get_connection(_SERVER_STATE)
        locator = _resolve_widget_handle_locator(connection_state, target=target, action="scroll")
        _run_widget_tool_action(
            action="scroll",
            target=target,
            callback=lambda: locator.scroll(delta_x=delta_x, delta_y=delta_y),
        )
        return _finalize_action_result(
            connection_state,
            include_state=include_state,
            include_snapshot=include_snapshot,
            state_target=target,
            snapshot_target=target,
            ok=True,
            target=target,
            delta_x=delta_x,
            delta_y=delta_y,
        )


    _tighten_pointer_tool_schema(mcp._tool_manager.get_tool("click"), verb="click")
    _tighten_pointer_tool_schema(mcp._tool_manager.get_tool("hover"), verb="hover over")


else:  # pragma: no cover - exercised only without the extra installed
    mcp = None


_CLI_TOOL_NAMES = (
    "session",
    "window",
    "snapshot",
    "find",
    "resolve_object_names",
    "inspect",
    "inspect_items",
    "click",
    "input",
    "invoke",
    "press_key",
    "focus",
    "set_expanded",
    "choose",
    "wait",
    "screenshot",
    "hover",
    "scroll",
)

_CLI_RESOURCE_NAMES = {
    "qplaywright://help/selectors": "selector_help",
    "qplaywright://help/geometry": "geometry_help",
}


def _cli_tool_registry() -> dict[str, Any]:
    registry: dict[str, Any] = {}
    for name in _CLI_TOOL_NAMES:
        func = globals().get(name)
        if callable(func):
            registry[name] = func
    return registry


def _cli_resource_registry() -> dict[str, Any]:
    registry: dict[str, Any] = {}
    for uri, func_name in _CLI_RESOURCE_NAMES.items():
        func = globals().get(func_name)
        if callable(func):
            registry[uri] = func
    return registry


def _cli_command_registry() -> dict[str, Any]:
    return _cli_tool_registry() | {"resource": resource}


def _cli_usage_text() -> str:
    return (
        "Interactive qplaywright MCP CLI\n\n"
        "Examples:\n"
        "  qplaywright-mcp cli\n"
        "  qplaywright-mcp cli help session\n"
        "  qplaywright-mcp cli resources\n"
        "  qplaywright-mcp cli resource list\n"
        "  qplaywright-mcp cli resource read qplaywright://help/selectors\n"
        "  qplaywright-mcp cli resource read qplaywright://help/geometry\n"
        "  qplaywright-mcp cli session attach --port 19877\n"
        "  qplaywright-mcp cli window select --title Dialog\n"
        "  qplaywright-mcp cli snapshot --depth 4 --topmost-only\n"
        "  qplaywright-mcp cli click w12 --count 2\n"
        "  qplaywright-mcp cli click --x 320 --y 180\n"
        "  qplaywright-mcp cli hover --x 320 --y 180\n"
        "  qplaywright-mcp cli input w7 123.45 --submit\n"
        "  qplaywright-mcp cli session '{\"action\": \"attach\", \"port\": 19877}'\n"
        "  qplaywright-mcp cli resource '{\"uri\": \"qplaywright://help/selectors\"}'\n"
        "  qplaywright-mcp cli resource '{\"uri\": \"qplaywright://help/geometry\"}'\n"
        "  qplaywright-mcp cli snapshot '{\"depth\": 4}'\n\n"
        "REPL commands:\n"
        "  .tools                List available tools\n"
        "  .resources            List available resources\n"
        "  .help                 Show CLI help\n"
        "  .help TOOL            Show one tool signature and docstring\n"
        "\n"
        "One-shot typed subcommands:\n"
        "  resource list|read URI\n"
        "  session attach|launch|status|close\n"
        "  window list|select\n"
        "  snapshot [--target TARGET] [--depth N] [--topmost-only] [--save-to PATH]\n"
        "  find [--mode auto|exact|fuzzy] [--keyword KEYWORD] [--root ROOT] [--role ROLE] [--text TEXT] [--class CLASS] [--object-name NAME] [--accessible-name NAME] [--limit N]\n"
        "  click [TARGET] [--count 1|2] [--x X --y Y] [--include-snapshot]\n"
        "  hover [TARGET] [--x X --y Y] [--include-snapshot]\n"
        "  input TARGET [TEXT] [--mode replace|append|type|clear] [--delay MS] [--submit]\n"
        "  focus TARGET [--include-state] [--include-snapshot]\n"
        "  wait TARGET [--state STATE | --condition CONDITION --expected VALUE] [--timeout SEC]\n"
        "\n"
        "JSON/REPL commands:\n"
        "  resource {JSON}       Read one resource or list resources when JSON is omitted\n"
        "  TOOL {JSON}           Invoke one tool with a JSON object argument\n"
        "  quit / exit           Leave the REPL"
    )


def _prefix_action_lines(tool_name: str, doc: str) -> str:
    lines: list[str] = []
    in_action_block = False
    for raw_line in doc.splitlines():
        stripped = raw_line.strip()
        if stripped == "action must be one of:":
            in_action_block = True
            lines.append(raw_line)
            continue

        if in_action_block and stripped.startswith("- "):
            action_name, separator, description = stripped[2:].partition(":")
            if separator:
                lines.append(f"- {tool_name}.{action_name.strip()}: {description.strip()}")
                continue

        if in_action_block and stripped and not stripped.startswith("- "):
            in_action_block = False

        lines.append(raw_line)

    return "\n".join(lines)


def _mcp_tool_definition(tool_name: str) -> Any | None:
    if mcp is None:
        return None
    tool_manager = getattr(mcp, "_tool_manager", None)
    get_tool = getattr(tool_manager, "get_tool", None)
    if not callable(get_tool):
        return None
    return get_tool(tool_name)


def _schema_required_shape(rule: dict[str, Any]) -> str | None:
    required = rule.get("required")
    if not isinstance(required, list) or not required:
        return None
    return ", ".join(str(item) for item in required)


def _cli_tool_help_from_schema(tool_name: str) -> str | None:
    tool = _mcp_tool_definition(tool_name)
    if tool is None:
        return None

    description = _prefix_action_lines(tool_name, pyinspect.cleandoc(tool.description or "No description available."))
    schema = tool.parameters if isinstance(tool.parameters, dict) else {}
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}

    lines = [tool_name]
    if description:
        lines.extend(["", description])

    if isinstance(schema.get("oneOf"), list):
        shapes = [
            shape
            for entry in schema["oneOf"]
            if isinstance(entry, dict)
            for shape in [_schema_required_shape(entry)]
            if shape is not None
        ]
        if shapes:
            lines.extend(["", "Allowed request shapes:"])
            lines.extend(f"- {shape}" for shape in shapes)

    if isinstance(properties, dict) and properties:
        lines.extend(["", "Parameters:"])
        for name, property_schema in properties.items():
            if not isinstance(property_schema, dict):
                continue
            line = f"- {name}"
            property_description = str(property_schema.get("description") or "").strip()
            if property_description:
                line += f": {property_description}"
            if "default" in property_schema and property_schema["default"] is not None:
                line += f" Default: {property_schema['default']!r}."
            lines.append(line)

    if isinstance(properties, dict) and any(name in properties for name in ("target", "root", "owner")):
        lines.extend([
            "",
            "Target guidance:",
            "- Prefer the stable handle returned by snapshot, find, resolve_object_names, or inspect.",
            f"- Selector fallback examples: {_SELECTOR_EXAMPLES}",
        ])

    return "\n".join(lines)


def _cli_tool_help(tool_name: str, func: Any) -> str:
    schema_help = _cli_tool_help_from_schema(tool_name)
    if schema_help is not None:
        return schema_help

    signature = pyinspect.signature(func)
    doc = _prefix_action_lines(tool_name, (pyinspect.getdoc(func) or "No description available.").strip())
    return f"{tool_name}{signature}\n\n{doc}"


def resource(uri: str | None = None) -> dict[str, Any]:
    """Read one CLI-exposed MCP resource.

    When uri is omitted, returns the list of available resource URIs.
    """

    registry = _cli_resource_registry()
    if uri is None:
        return {
            "ok": True,
            "resources": [
                {
                    "uri": resource_uri,
                    "description": (pyinspect.getdoc(func) or "").strip(),
                }
                for resource_uri, func in sorted(registry.items())
            ],
        }

    try:
        func = registry[uri]
    except KeyError as exc:
        available = ", ".join(sorted(registry)) or "<none>"
        raise ValueError(f"Unknown CLI resource {uri!r}. Available resources: {available}") from exc

    return {
        "ok": True,
        "uri": uri,
        "content": func(),
    }


def _split_cli_invocation(command_line: str) -> tuple[str, str | None]:
    parts = command_line.strip().split(None, 1)
    if not parts:
        raise ValueError("A tool name is required")
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1]


def _parse_cli_arguments(raw_arguments: str | None) -> dict[str, Any]:
    if raw_arguments is None or not raw_arguments.strip():
        return {}
    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "CLI arguments must be a JSON object, for example: '{\"target\": \"#amount_editor\"}'"
        ) from exc
    if not isinstance(parsed, dict):
        raise ValueError("CLI arguments must decode to a JSON object")
    return parsed


def _looks_like_json_object_argument(raw_argument: str | None) -> bool:
    if raw_argument is None:
        return False
    return raw_argument.lstrip().startswith("{")


def _print_cli_result(value: Any) -> None:
    if isinstance(value, str):
        print(value)
        return
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str))


def _invoke_cli_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
    registry = _cli_command_registry()
    try:
        func = registry[tool_name]
    except KeyError as exc:
        available = ", ".join(sorted(registry)) or "<none>"
        raise ValueError(f"Unknown CLI command {tool_name!r}. Available commands: {available}") from exc
    return func(**arguments)


def _handle_cli_meta_command(command_line: str) -> bool:
    normalized = command_line.strip()
    if normalized in {".tools", "tools"}:
        print("Available tools:")
        for name in sorted(_cli_tool_registry()):
            print(f"- {name}")
        return True

    if normalized in {".resources", "resources"}:
        print("Available resources:")
        for uri in sorted(_cli_resource_registry()):
            print(f"- {uri}")
        return True

    if normalized in {".help", "help"}:
        print(_cli_usage_text())
        return True

    if normalized.startswith(".help ") or normalized.startswith("help "):
        _, tool_name = normalized.split(None, 1)
        registry = _cli_command_registry()
        try:
            func = registry[tool_name]
        except KeyError as exc:
            raise ValueError(f"Unknown CLI command {tool_name!r}") from exc
        print(_cli_tool_help(tool_name, func))
        return True

    return False


def _run_cli_command(tool_name: str, raw_arguments: str | None) -> int:
    try:
        result = _invoke_cli_tool(tool_name, _parse_cli_arguments(raw_arguments))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _print_cli_result(result)
    return 0


def _run_cli_invocation(tool_name: str, arguments: dict[str, Any]) -> int:
    try:
        result = _invoke_cli_tool(tool_name, arguments)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _print_cli_result(result)
    return 0


def _build_typed_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run qplaywright MCP tools with typed subcommands.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    resource_parser = subparsers.add_parser("resource", help="List or read CLI-exposed MCP resources.")
    resource_subparsers = resource_parser.add_subparsers(dest="resource_action")
    resource_subparsers.add_parser("list", help="List available resource URIs.")
    read_resource_parser = resource_subparsers.add_parser("read", help="Read one resource by URI.")
    read_resource_parser.add_argument("uri", help="Resource URI to read.")

    session_parser = subparsers.add_parser("session", help="Manage the active qplaywright session.")
    session_subparsers = session_parser.add_subparsers(dest="session_action", required=True)
    session_attach_parser = session_subparsers.add_parser("attach", help="Attach to a running Qt app.")
    session_attach_parser.add_argument("--host", default=DEFAULT_HOST)
    session_attach_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    session_attach_parser.add_argument("--timeout", type=float, default=30.0)
    session_attach_parser.add_argument("--agent-name", default="GitHub Copilot")

    session_launch_parser = session_subparsers.add_parser("launch", help="Launch a Qt app and attach.")
    session_launch_parser.add_argument("executable")
    session_launch_parser.add_argument("args", nargs="*")
    session_launch_parser.add_argument("--host", default=DEFAULT_HOST)
    session_launch_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    session_launch_parser.add_argument("--timeout", type=float, default=30.0)
    session_launch_parser.add_argument("--agent-name", default="GitHub Copilot")

    session_status_parser = session_subparsers.add_parser("status", help="Show session status.")
    session_status_parser.add_argument("--host", default=DEFAULT_HOST)
    session_status_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    session_status_parser.add_argument("--timeout", type=float, default=30.0)
    session_status_parser.add_argument("--agent-name", default="GitHub Copilot")

    session_close_parser = session_subparsers.add_parser("close", help="Close the active session.")
    session_close_parser.add_argument("--host", default=DEFAULT_HOST)
    session_close_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    session_close_parser.add_argument("--timeout", type=float, default=30.0)
    session_close_parser.add_argument("--agent-name", default="GitHub Copilot")

    window_parser = subparsers.add_parser("window", help="Manage top-level windows.")
    window_subparsers = window_parser.add_subparsers(dest="window_action", required=True)
    window_subparsers.add_parser("list", help="List visible top-level windows.")
    window_select_parser = window_subparsers.add_parser("select", help="Select the active window.")
    window_select_group = window_select_parser.add_mutually_exclusive_group(required=True)
    window_select_group.add_argument("--index", type=int)
    window_select_group.add_argument("--wid", type=int)
    window_select_group.add_argument("--title")

    snapshot_parser = subparsers.add_parser("snapshot", help="Capture a text snapshot of the current UI.")
    snapshot_parser.add_argument("--target")
    snapshot_parser.add_argument("--depth", type=int, default=10)
    snapshot_parser.add_argument("--topmost-only", action="store_true")
    snapshot_parser.add_argument("--include-infrastructure", action="store_true")
    snapshot_parser.add_argument("--save-to")

    find_parser = subparsers.add_parser("find", help="Run exact or fuzzy server-side widget search under one scope.")
    find_parser.add_argument("--mode", choices=("auto", "exact", "fuzzy"), default="auto")
    find_parser.add_argument("--keyword")
    find_parser.add_argument("--root")
    find_parser.add_argument("--role")
    find_parser.add_argument("--text")
    find_parser.add_argument("--class")
    find_parser.add_argument("--object-name")
    find_parser.add_argument("--accessible-name")
    find_parser.add_argument("--visible", action="store_true")
    find_parser.add_argument("--not-visible", action="store_true")
    find_parser.add_argument("--enabled", action="store_true")
    find_parser.add_argument("--disabled", action="store_true")
    find_parser.add_argument("--interactable", action="store_true")
    find_parser.add_argument("--not-interactable", action="store_true")
    find_parser.add_argument("--include-infrastructure", action="store_true")
    find_parser.add_argument("--limit", type=int, default=5)

    resolve_object_names_parser = subparsers.add_parser(
        "resolve_object_names",
        help="Resolve several exact objectName values to stable handles under one root.",
    )
    resolve_object_names_parser.add_argument("--root")
    resolve_object_names_parser.add_argument("--object-name", action="append", required=True)
    resolve_object_names_parser.add_argument("--depth", type=int, default=10)
    resolve_object_names_parser.add_argument("--include-infrastructure", action="store_true")

    click_parser = subparsers.add_parser("click", help="Click a target or a window-relative coordinate.")
    click_parser.add_argument("target", nargs="?")
    click_parser.add_argument("--count", type=int, choices=(1, 2), default=1)
    click_parser.add_argument("--x", type=int)
    click_parser.add_argument("--y", type=int)
    click_parser.add_argument("--include-state", action="store_true")
    click_parser.add_argument("--include-snapshot", action="store_true")

    input_parser = subparsers.add_parser("input", help="Input text into one widget resolved by stable handle.")
    input_parser.add_argument("target")
    input_parser.add_argument("text", nargs="?", default="")
    input_parser.add_argument("--mode", choices=("replace", "append", "type", "clear"), default="replace")
    input_parser.add_argument("--delay", type=int, default=0)
    input_parser.add_argument("--submit", action="store_true")
    input_parser.add_argument("--include-state", action="store_true")
    input_parser.add_argument("--include-snapshot", action="store_true")

    inspect_parser = subparsers.add_parser("inspect", help="Inspect one target or return the current window tree.")
    inspect_parser.add_argument("target_arg", nargs="?")
    inspect_parser.add_argument("--target")
    inspect_parser.add_argument("--property")
    inspect_parser.add_argument("--include-methods", action="store_true")
    inspect_parser.add_argument("--include-properties", action="store_true")
    inspect_parser.add_argument("--depth", type=int, default=10)
    inspect_parser.add_argument("--topmost-only", action="store_true")
    inspect_parser.add_argument("--include-infrastructure", action="store_true")

    invoke_parser = subparsers.add_parser("invoke", help="Invoke a custom widget method by exact name.")
    invoke_parser.add_argument("target")
    invoke_parser.add_argument("method")
    invoke_parser.add_argument("--args", default="{}")
    invoke_parser.add_argument("--include-state", action="store_true")
    invoke_parser.add_argument("--include-snapshot", action="store_true")

    press_key_parser = subparsers.add_parser("press_key", help="Send a key press to one widget resolved by stable handle.")
    press_key_parser.add_argument("key")
    press_key_parser.add_argument("--target")
    press_key_parser.add_argument("--include-state", action="store_true")
    press_key_parser.add_argument("--include-snapshot", action="store_true")

    focus_parser = subparsers.add_parser("focus", help="Focus one widget resolved by stable handle.")
    focus_parser.add_argument("target")
    focus_parser.add_argument("--include-state", action="store_true")
    focus_parser.add_argument("--include-snapshot", action="store_true")

    choose_parser = subparsers.add_parser("choose", help="Select a combobox option by value, index, or label.")
    choose_parser.add_argument("target")
    choose_group = choose_parser.add_mutually_exclusive_group()
    choose_group.add_argument("--value")
    choose_group.add_argument("--index", type=int)
    choose_group.add_argument("--label")
    choose_parser.add_argument("--include-state", action="store_true")
    choose_parser.add_argument("--include-snapshot", action="store_true")

    wait_parser = subparsers.add_parser("wait", help="Wait until a widget reaches a supported state.")
    wait_parser.add_argument("target")
    wait_group = wait_parser.add_mutually_exclusive_group()
    wait_group.add_argument("--state", choices=tuple(sorted(_ALLOWED_WAIT_STATES)))
    wait_group.add_argument("--condition", choices=tuple(sorted(_ALLOWED_WAIT_CONDITIONS)))
    wait_parser.add_argument("--expected")
    wait_parser.add_argument("--timeout", type=float)
    wait_parser.add_argument("--include-state", action="store_true")
    wait_parser.add_argument("--include-snapshot", action="store_true")

    screenshot_parser = subparsers.add_parser("screenshot", help="Capture a screenshot of the active window or one widget resolved by stable handle.")
    screenshot_parser.add_argument("--target")
    screenshot_parser.add_argument("--path")
    screenshot_parser.add_argument("--x", type=int)
    screenshot_parser.add_argument("--y", type=int)
    screenshot_parser.add_argument("--width", type=int)
    screenshot_parser.add_argument("--height", type=int)

    hover_parser = subparsers.add_parser("hover", help="Hover a target or a window-relative coordinate.")
    hover_parser.add_argument("target", nargs="?")
    hover_parser.add_argument("--x", type=int)
    hover_parser.add_argument("--y", type=int)
    hover_parser.add_argument("--include-state", action="store_true")
    hover_parser.add_argument("--include-snapshot", action="store_true")

    scroll_parser = subparsers.add_parser("scroll", help="Send a mouse wheel scroll event to one widget resolved by stable handle.")
    scroll_parser.add_argument("target")
    scroll_parser.add_argument("--delta-x", type=int, default=0)
    scroll_parser.add_argument("--delta-y", type=int, default=0)
    scroll_parser.add_argument("--include-state", action="store_true")
    scroll_parser.add_argument("--include-snapshot", action="store_true")

    return parser


def _typed_cli_arguments(namespace: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    command = namespace.command

    if command == "find":
        arguments = {
            "mode": namespace.mode,
            "keyword": namespace.keyword,
            "root": namespace.root,
            "role": namespace.role,
            "text": namespace.text,
            "class_": getattr(namespace, "class"),
            "object_name": getattr(namespace, "object_name"),
            "accessible_name": getattr(namespace, "accessible_name"),
            "include_infrastructure": namespace.include_infrastructure,
            "limit": namespace.limit,
        }
        if namespace.visible:
            arguments["visible"] = True
        elif namespace.not_visible:
            arguments["visible"] = False
        if namespace.enabled:
            arguments["enabled"] = True
        elif namespace.disabled:
            arguments["enabled"] = False
        if namespace.interactable:
            arguments["interactable"] = True
        elif namespace.not_interactable:
            arguments["interactable"] = False
        return "find", arguments

    if command == "resolve_object_names":
        return "resolve_object_names", {
            "root": namespace.root,
            "object_names": getattr(namespace, "object_name"),
            "depth": namespace.depth,
            "include_infrastructure": namespace.include_infrastructure,
        }

    if command == "inspect":
        return "inspect", {
            "target": namespace.target if namespace.target is not None else namespace.target_arg,
            "property": namespace.property,
            "include_methods": namespace.include_methods,
            "include_properties": namespace.include_properties,
            "depth": namespace.depth,
            "topmost_only": namespace.topmost_only,
            "include_infrastructure": namespace.include_infrastructure,
        }

    if command == "invoke":
        return "invoke", {
            "target": namespace.target,
            "method": namespace.method,
            "args": json.loads(namespace.args),
            "include_state": namespace.include_state,
            "include_snapshot": namespace.include_snapshot,
        }

    if command == "press_key":
        return "press_key", {
            "key": namespace.key,
            "target": namespace.target,
            "include_state": namespace.include_state,
            "include_snapshot": namespace.include_snapshot,
        }

    if command == "focus":
        return "focus", {
            "target": namespace.target,
            "include_state": namespace.include_state,
            "include_snapshot": namespace.include_snapshot,
        }

    if command == "choose":
        arguments = {
            "target": namespace.target,
            "include_state": namespace.include_state,
            "include_snapshot": namespace.include_snapshot,
        }
        for field_name in ("value", "index", "label"):
            value = getattr(namespace, field_name, None)
            if value is not None:
                arguments[field_name] = value
        return "choose", arguments

    if command == "wait":
        arguments = {
            "target": namespace.target,
            "timeout": namespace.timeout,
            "include_state": namespace.include_state,
            "include_snapshot": namespace.include_snapshot,
        }
        if namespace.condition is not None:
            arguments["condition"] = namespace.condition
            arguments["expected"] = _normalize_wait_expected(namespace.condition, namespace.expected)
        else:
            arguments["state"] = namespace.state or "visible"
        return "wait", arguments

    if command == "screenshot":
        arguments = {
            "target": namespace.target,
            "path": namespace.path,
        }
        for field_name in ("x", "y", "width", "height"):
            value = getattr(namespace, field_name, None)
            if value is not None:
                arguments[field_name] = value
        return "screenshot", arguments

    if command == "hover":
        arguments = {
            "target": namespace.target,
            "include_state": namespace.include_state,
            "include_snapshot": namespace.include_snapshot,
        }
        if namespace.x is not None:
            arguments["x"] = namespace.x
        if namespace.y is not None:
            arguments["y"] = namespace.y
        return "hover", arguments

    if command == "scroll":
        return "scroll", {
            "target": namespace.target,
            "delta_x": namespace.delta_x,
            "delta_y": namespace.delta_y,
            "include_state": namespace.include_state,
            "include_snapshot": namespace.include_snapshot,
        }

    if command == "resource":
        if namespace.resource_action in (None, "list"):
            return "resource", {}
        return "resource", {"uri": namespace.uri}

    if command == "session":
        arguments = {
            "action": namespace.session_action,
            "host": namespace.host,
            "port": namespace.port,
            "timeout": namespace.timeout,
            "agent_name": namespace.agent_name,
        }
        if namespace.session_action == "launch":
            arguments["executable"] = namespace.executable
            arguments["args"] = list(namespace.args)
        return "session", arguments

    if command == "window":
        arguments = {"action": namespace.window_action}
        for field_name in ("index", "wid", "title"):
            value = getattr(namespace, field_name, None)
            if value is not None:
                arguments[field_name] = value
        return "window", arguments

    if command == "snapshot":
        arguments = {
            "target": namespace.target,
            "depth": namespace.depth,
            "topmost_only": namespace.topmost_only,
            "include_infrastructure": namespace.include_infrastructure,
            "save_to": namespace.save_to,
        }
        return "snapshot", arguments

    if command == "click":
        arguments = {
            "target": namespace.target,
            "count": namespace.count,
            "include_state": namespace.include_state,
            "include_snapshot": namespace.include_snapshot,
        }
        if namespace.x is not None:
            arguments["x"] = namespace.x
        if namespace.y is not None:
            arguments["y"] = namespace.y
        return "click", arguments

    if command == "input":
        return "input", {
            "target": namespace.target,
            "text": namespace.text,
            "mode": namespace.mode,
            "delay": namespace.delay,
            "submit": namespace.submit,
            "include_state": namespace.include_state,
            "include_snapshot": namespace.include_snapshot,
        }

    raise ValueError(f"Unsupported typed CLI command: {command!r}")


def _try_run_typed_cli(argv: Sequence[str]) -> int | None:
    if not argv:
        return None
    if argv[0] not in {
        "resource", "session", "window", "snapshot", "find", "resolve_object_names", "inspect", "click", "input", "invoke",
        "press_key", "focus", "choose", "wait", "screenshot", "hover", "scroll",
    }:
        return None
    if len(argv) > 1 and _looks_like_json_object_argument(argv[1]):
        return None

    parser = _build_typed_cli_parser()
    try:
        namespace = parser.parse_args(list(argv))
    except SystemExit:
        return 2
    tool_name, arguments = _typed_cli_arguments(namespace)
    return _run_cli_invocation(tool_name, arguments)


def _try_run_typed_cli_from_command_line(command_line: str) -> int | None:
    """Try to parse and run a command line as a typed CLI command."""
    try:
        parts = shlex.split(command_line.strip(), posix=True)
    except ValueError as exc:
        raise ValueError(f"Invalid CLI command line: {exc}") from exc
    if not parts:
        return None
    # If the first part is a known tool and the rest looks like flags/args (not JSON)
    if parts[0] in {
        "resource", "session", "window", "snapshot", "find", "resolve_object_names", "inspect", "click", "input", "invoke",
        "press_key", "focus", "choose", "wait", "screenshot", "hover", "scroll",
    }:
        if len(parts) > 1 and parts[1].lstrip().startswith("{"):
            return None
        return _try_run_typed_cli(parts)
    return None


def _run_cli_repl() -> int:
    print("qplaywright MCP CLI. Type .help for usage.")
    while True:
        try:
            command_line = builtins.input("qplaywright> ").strip()
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            return 130

        if not command_line:
            continue
        if command_line in {"quit", "exit", ".quit", ".exit"}:
            return 0

        try:
            if _handle_cli_meta_command(command_line):
                continue
            # Try typed CLI first (for commands like "session attach --port 19876" or "click text=Start")
            typed_result = _try_run_typed_cli_from_command_line(command_line)
            if typed_result is not None:
                continue
            tool_name, raw_arguments = _split_cli_invocation(command_line)
            _run_cli_command(tool_name, raw_arguments)
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)


def _run_cli(argv: Sequence[str]) -> int:
    argv_list = list(argv)
    if not argv_list:
        return _run_cli_repl()

    typed_result = _try_run_typed_cli(argv_list)
    if typed_result is not None:
        return typed_result

    parser = argparse.ArgumentParser(
        description="Run qplaywright MCP tools directly from the command line or in an interactive REPL."
    )
    parser.add_argument(
        "tool",
        nargs="?",
        help="Tool name to call once. Omit to start an interactive CLI session.",
    )
    parser.add_argument(
        "arguments",
        nargs="?",
        help="JSON object with tool arguments, for example '{\"action\": \"attach\", \"port\": 19877}'.",
    )
    args = parser.parse_args(argv_list)

    if args.tool is None:
        return _run_cli_repl()

    if args.tool in {"help", "tools", "resources"}:
        command_line = args.tool if args.arguments is None else f"{args.tool} {args.arguments}"
        try:
            if _handle_cli_meta_command(command_line):
                return 0
            raise ValueError(f"Unsupported CLI meta command: {command_line}")
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    return _run_cli_command(args.tool, args.arguments)


def _configure_stdio_for_mcp(transport: str) -> None:
    """Force UTF-8 stdio for MCP line transport on Windows and other locale-based consoles."""

    if transport != "stdio":
        return

    for stream_name, errors in (("stdin", "strict"), ("stdout", "strict"), ("stderr", "backslashreplace")):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors=errors)


def _screenshot_clip_kwargs(
    x: int | None = None,
    y: int | None = None,
    width: int | None = None,
    height: int | None = None,
) -> dict[str, int]:
    values = {"x": x, "y": y, "width": width, "height": height}
    present = {key: value for key, value in values.items() if value is not None}
    if not present:
        return {}
    if len(present) != 4:
        raise ValueError("Screenshot clipping requires x, y, width, and height together")
    if x is None or y is None or width is None or height is None:
        raise ValueError("Screenshot clipping requires x, y, width, and height together")
    clip_x = int(x)
    clip_y = int(y)
    clip_width = int(width)
    clip_height = int(height)
    if clip_x < 0 or clip_y < 0 or clip_width <= 0 or clip_height <= 0:
        raise ValueError("Screenshot clipping requires non-negative x/y and positive width/height")
    return {"x": clip_x, "y": clip_y, "width": clip_width, "height": clip_height}


def main(argv: Sequence[str] | None = None) -> None:
    """Entry point for running the qplaywright MCP server."""

    if _MCP_IMPORT_ERROR is not None or mcp is None:
        raise SystemExit(
            "The qplaywright MCP server requires the optional 'mcp' dependency. "
            "Install it with: pip install -e .[mcp]"
        )
    if _MCP_VERSION_ERROR is not None:
        raise SystemExit(_MCP_VERSION_ERROR)

    argv_list = list(argv if argv is not None else sys.argv[1:])
    mode = "serve"
    if argv_list and argv_list[0] in {"serve", "cli"}:
        mode = argv_list.pop(0)

    if mode == "cli":
        raise SystemExit(_run_cli(argv_list))

    parser = argparse.ArgumentParser(description="Run the qplaywright MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="MCP transport to expose. stdio is the default and works with most hosts.",
    )
    args = parser.parse_args(argv_list)
    configure_logging_from_env()
    LOGGER.debug("Starting qplaywright MCP server with transport=%s", args.transport)
    _configure_stdio_for_mcp(args.transport)
    raise SystemExit(_run_mcp_transport(args.transport))


if __name__ == "__main__":
    main()