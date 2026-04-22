"""Agent server — TCP server that runs inside the Qt application.

Usage in your Qt app::

    from qplaywright.agent import start_agent

    app = QApplication(sys.argv)
    start_agent(app, port=19876)
    # ... setup your UI ...
    app.exec()
"""

from __future__ import annotations

import base64
import io
import json
import logging
import socket
import struct
import threading
import time
from concurrent.futures import Future
from typing import Any

from qplaywright.protocol import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    Request,
    Response,
    decode_line,
    METHOD_FIND,
    METHOD_FIND_ALL,
    METHOD_WIDGET_TREE,
    METHOD_GET_PROPERTY,
    METHOD_GET_TEXT,
    METHOD_GET_VALUE,
    METHOD_GET_METHODS,
    METHOD_IS_VISIBLE,
    METHOD_IS_ENABLED,
    METHOD_IS_CHECKED,
    METHOD_COUNT,
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
    METHOD_SCREENSHOT,
    METHOD_SCREENSHOT_WIDGET,
    METHOD_LIST_WINDOWS,
    METHOD_WINDOW_TITLE,
    METHOD_WINDOW_SIZE,
    METHOD_WINDOW_RESIZE,
    METHOD_WINDOW_CLOSE,
    METHOD_WAIT_FOR,
    METHOD_PING,
)
from qplaywright.agent._selector import (
    find_widgets,
    widget_to_dict,
    _widget_text,
    _widget_class_name,
    _widget_value,
    _declared_method_schema,
    _invoke_method,
)

logger = logging.getLogger("qplaywright.agent")

_INVOKE_ERROR_NONE = 0
_INVOKE_ERROR_METHOD_NOT_EXPOSED = 1
_INVOKE_ERROR_MISSING_REQUIRED_ARGUMENT = 2
_INVOKE_ERROR_UNEXPECTED_ARGUMENT = 3
_INVOKE_ERROR_ARGUMENT_TYPE_MISMATCH = 4
_INVOKE_ERROR_METHOD_INVOCATION_FAILED = 5

# We import Qt lazily to avoid hard dependency at module level.
_QtWidgets = None
_QtCore = None
_QtGui = None
_QtTest = None
_QApplication = None


def _import_qt():
    global _QtWidgets, _QtCore, _QtGui, _QtTest, _QApplication
    if _QtWidgets is not None:
        return

    # Try PySide6 first, then PyQt6, then PySide2, then PyQt5
    for pkg in ("PySide6", "PyQt6", "PySide2", "PyQt5"):
        try:
            _QtWidgets = __import__(f"{pkg}.QtWidgets", fromlist=["QtWidgets"])
            _QtCore = __import__(f"{pkg}.QtCore", fromlist=["QtCore"])
            _QtGui = __import__(f"{pkg}.QtGui", fromlist=["QtGui"])
            try:
                _QtTest = __import__(f"{pkg}.QtTest", fromlist=["QtTest"])
            except ImportError:
                _QtTest = None
            _QApplication = _QtWidgets.QApplication
            logger.info("Using Qt binding: %s", pkg)
            return
        except ImportError:
            continue
    raise ImportError("No Qt binding found. Install PySide6, PyQt6, PySide2, or PyQt5.")


# --------------------------------------------------------------------------- #
#  Widget ID registry — gives each widget a stable numeric ID                  #
# --------------------------------------------------------------------------- #

class _WidgetRegistry:
    """Maps widgets ↔ integer IDs so the client can reference them."""

    def __init__(self):
        self._w2id: dict[int, int] = {}   # id(widget) → wid
        self._id2w: dict[int, Any] = {}   # wid → widget (weak-ish via id)
        self._next = 1
        self._lock = threading.Lock()

    def register(self, widget) -> int:
        key = id(widget)
        with self._lock:
            if key in self._w2id:
                return self._w2id[key]
            wid = self._next
            self._next += 1
            self._w2id[key] = wid
            self._id2w[wid] = widget
            return wid

    def get(self, wid: int):
        with self._lock:
            return self._id2w.get(wid)

    def clear(self):
        with self._lock:
            self._w2id.clear()
            self._id2w.clear()
            self._next = 1


_registry = _WidgetRegistry()


def _widget_tree_to_dict(widget, *, depth: int = 0, max_depth: int = 50) -> dict:
    """Serialize a widget tree and include stable widget ids for each node."""

    info = widget_to_dict(widget, depth=depth, max_depth=depth)
    info["wid"] = _registry.register(widget)

    if depth < max_depth:
        children = []
        for child in widget.children():
            if hasattr(child, "isVisible"):
                children.append(_widget_tree_to_dict(child, depth=depth + 1, max_depth=max_depth))
        if children:
            info["children"] = children

    return info


# --------------------------------------------------------------------------- #
#  Main-thread command dispatcher                                              #
# --------------------------------------------------------------------------- #

class _Dispatcher(_QtCore.QObject if False else object):
    """Receives commands via custom events and executes them on the main thread.

    We can't subclass QObject at import time because Qt may not be loaded yet,
    so ``_create_dispatcher()`` builds the real class dynamically.
    """
    pass


def _create_dispatcher():
    _import_qt()
    QEvent = _QtCore.QEvent
    QObject = _QtCore.QObject

    _CMD_EVENT_TYPE = QEvent.Type(QEvent.registerEventType())

    class CommandEvent(QEvent):
        def __init__(self, request: Request, future: Future):
            super().__init__(_CMD_EVENT_TYPE)
            self.request = request
            self.future = future

    class Dispatcher(QObject):
        def __init__(self):
            super().__init__()
            self._cmd_event_type = _CMD_EVENT_TYPE

        def customEvent(self, event):
            if event.type() == self._cmd_event_type:
                req = event.request
                fut = event.future
                try:
                    result = _handle_command(req)
                    fut.set_result(result)
                except Exception as exc:
                    fut.set_exception(exc)

    return Dispatcher, CommandEvent


# --------------------------------------------------------------------------- #
#  Command handler — runs on the main thread                                   #
# --------------------------------------------------------------------------- #

def _get_top_level_widgets():
    return _QApplication.topLevelWidgets()


def _resolve_widgets(params: dict) -> list:
    """Resolve widgets from params — either by wid or by selector."""
    wid = params.get("wid")
    if wid is not None:
        w = _registry.get(wid)
        if w is None:
            raise ValueError(f"Widget id={wid} not found or was garbage collected")
        return [w]

    selector = params.get("selector")
    if selector is None:
        raise ValueError("Either 'wid' or 'selector' is required")

    parent_wid = params.get("parent_wid")
    if parent_wid is not None:
        parent = _registry.get(parent_wid)
        if parent is None:
            raise ValueError(f"Parent widget id={parent_wid} not found")
        roots = [parent]
    else:
        roots = _get_top_level_widgets()

    has_text = params.get("has_text")
    visible_only = params.get("visible_only", True)
    nth = params.get("nth")

    widgets = find_widgets(roots, selector, has_text=has_text, visible_only=visible_only)

    if nth is not None:
        if 0 <= nth < len(widgets):
            widgets = [widgets[nth]]
        else:
            widgets = []

    return widgets


def _resolve_one(params: dict):
    widgets = _resolve_widgets(params)
    if not widgets:
        selector = params.get("selector", params.get("wid", "?"))
        raise ValueError(f"No widget found for: {selector}")
    return widgets[0]


def _normalize_invoke_result(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return value.decode(errors="replace")
    if isinstance(value, dict):
        return {str(key): _normalize_invoke_result(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_invoke_result(item) for item in value]
    raise TypeError(f"Invoke result is not JSON-serializable: {type(value).__name__}")


def _invoke_result_success(value=None):
    return {
        "ok": True,
        "value": _normalize_invoke_result(value),
        "errorCode": _INVOKE_ERROR_NONE,
        "errorMessage": "",
    }


def _invoke_result_failure(code: int, message: str):
    return {
        "ok": False,
        "value": None,
        "errorCode": code,
        "errorMessage": message,
    }


def _invoke_error_code(exc: Exception) -> int:
    message = str(exc)
    if message.startswith("Method is not exposed:"):
        return _INVOKE_ERROR_METHOD_NOT_EXPOSED
    if message.startswith("Missing required argument:"):
        return _INVOKE_ERROR_MISSING_REQUIRED_ARGUMENT
    if message.startswith("Unexpected argument:"):
        return _INVOKE_ERROR_UNEXPECTED_ARGUMENT
    if message.startswith("Argument "):
        return _INVOKE_ERROR_ARGUMENT_TYPE_MISMATCH
    return _INVOKE_ERROR_METHOD_INVOCATION_FAILED


def _invoke_widget_method(widget, request: dict):
    try:
        result = _invoke_method(widget, request)
        _process_events()
        return _invoke_result_success(result)
    except Exception as exc:
        return _invoke_result_failure(_invoke_error_code(exc), str(exc))


def _key_to_qt(key_str: str):
    """Convert a Playwright-style key name to Qt key enum."""
    _import_qt()
    Qt = _QtCore.Qt
    KEY_MAP = {
        "Enter": Qt.Key_Return,
        "Return": Qt.Key_Return,
        "Tab": Qt.Key_Tab,
        "Escape": Qt.Key_Escape,
        "Backspace": Qt.Key_Backspace,
        "Delete": Qt.Key_Delete,
        "ArrowUp": Qt.Key_Up,
        "ArrowDown": Qt.Key_Down,
        "ArrowLeft": Qt.Key_Left,
        "ArrowRight": Qt.Key_Right,
        "Home": Qt.Key_Home,
        "End": Qt.Key_End,
        "PageUp": Qt.Key_PageUp,
        "PageDown": Qt.Key_PageDown,
        "Space": Qt.Key_Space,
        "F1": Qt.Key_F1, "F2": Qt.Key_F2, "F3": Qt.Key_F3, "F4": Qt.Key_F4,
        "F5": Qt.Key_F5, "F6": Qt.Key_F6, "F7": Qt.Key_F7, "F8": Qt.Key_F8,
        "F9": Qt.Key_F9, "F10": Qt.Key_F10, "F11": Qt.Key_F11, "F12": Qt.Key_F12,
        "Control": Qt.Key_Control,
        "Shift": Qt.Key_Shift,
        "Alt": Qt.Key_Alt,
        "Meta": Qt.Key_Meta,
    }
    return KEY_MAP.get(key_str)


def _handle_command(req: Request) -> Any:
    """Execute a command on the Qt main thread. Returns JSON-serializable result."""
    _import_qt()
    method = req.method
    params = req.params
    Qt = _QtCore.Qt
    QCursor = _QtGui.QCursor

    # -- Ping ----------------------------------------------------------------
    if method == METHOD_PING:
        return {"pong": True}

    # -- Widget discovery ----------------------------------------------------
    if method == METHOD_FIND:
        widgets = _resolve_widgets(params)
        if not widgets:
            return None
        w = widgets[0]
        wid = _registry.register(w)
        return {"wid": wid, **widget_to_dict(w, max_depth=0)}

    if method == METHOD_FIND_ALL:
        widgets = _resolve_widgets(params)
        result = []
        for w in widgets:
            wid = _registry.register(w)
            result.append({"wid": wid, **widget_to_dict(w, max_depth=0)})
        return result

    if method == METHOD_WIDGET_TREE:
        roots = _get_top_level_widgets()
        return [_widget_tree_to_dict(r, max_depth=params.get("max_depth", 10)) for r in roots if r.isVisible()]

    if method == METHOD_COUNT:
        return len(_resolve_widgets(params))

    # -- Property access -----------------------------------------------------
    if method == METHOD_GET_TEXT:
        w = _resolve_one(params)
        return _widget_text(w)

    if method == METHOD_GET_VALUE:
        w = _resolve_one(params)
        return _widget_value(w)

    if method == METHOD_GET_METHODS:
        w = _resolve_one(params)
        return _normalize_invoke_result(_declared_method_schema(w))

    if method == METHOD_GET_PROPERTY:
        w = _resolve_one(params)
        prop_name = params["property"]
        fn = getattr(w, prop_name, None)
        if callable(fn):
            return fn()
        return None

    if method == METHOD_IS_VISIBLE:
        w = _resolve_one(params)
        return w.isVisible()

    if method == METHOD_IS_ENABLED:
        w = _resolve_one(params)
        return w.isEnabled()

    if method == METHOD_IS_CHECKED:
        w = _resolve_one(params)
        return w.isChecked() if hasattr(w, "isChecked") else False

    if method == METHOD_BOUNDING_BOX:
        w = _resolve_one(params)
        g = w.geometry()
        global_pos = w.mapToGlobal(w.rect().topLeft())
        return {
            "x": global_pos.x(),
            "y": global_pos.y(),
            "width": g.width(),
            "height": g.height(),
        }

    # -- Actions -------------------------------------------------------------
    if method == METHOD_CLICK:
        w = _resolve_one(params)
        _click_widget(w, double=False)
        return True

    if method == METHOD_DBLCLICK:
        w = _resolve_one(params)
        _click_widget(w, double=True)
        return True

    if method == METHOD_FILL:
        w = _resolve_one(params)
        value = params["value"]
        _fill_widget(w, value)
        return True

    if method == METHOD_INVOKE:
        w = _resolve_one(params)
        return _invoke_widget_method(w, params.get("request") or {})

    if method == METHOD_CLEAR:
        w = _resolve_one(params)
        _fill_widget(w, "")
        return True

    if method == METHOD_CHECK:
        w = _resolve_one(params)
        if hasattr(w, "setChecked"):
            w.setChecked(True)
        return True

    if method == METHOD_UNCHECK:
        w = _resolve_one(params)
        if hasattr(w, "setChecked"):
            w.setChecked(False)
        return True

    if method == METHOD_SELECT_OPTION:
        w = _resolve_one(params)
        _select_option(w, params)
        return True

    if method == METHOD_TYPE:
        w = _resolve_one(params)
        text = params["text"]
        delay = params.get("delay", 0)
        _type_text(w, text, delay)
        return True

    if method == METHOD_PRESS:
        w = _resolve_one(params)
        key = params["key"]
        _press_key(w, key)
        return True

    if method == METHOD_HOVER:
        w = _resolve_one(params)
        center = w.mapToGlobal(w.rect().center())
        QCursor.setPos(center)
        _process_events()
        return True

    if method == METHOD_FOCUS:
        w = _resolve_one(params)
        w.setFocus()
        _process_events()
        return True

    if method == METHOD_SCROLL:
        w = _resolve_one(params)
        _scroll_widget(w, params.get("delta_x", 0), params.get("delta_y", 0))
        return True

    # -- Screenshot ----------------------------------------------------------
    if method in (METHOD_SCREENSHOT, METHOD_SCREENSHOT_WIDGET):
        if method == METHOD_SCREENSHOT_WIDGET:
            w = _resolve_one(params)
        else:
            # Full window screenshot
            windows = _get_top_level_widgets()
            visible = [w for w in windows if w.isVisible()]
            if not visible:
                raise ValueError("No visible window found")
            w = visible[0]

        pixmap = w.grab()
        buf = _QtCore.QBuffer()
        buf.open(_QtCore.QIODevice.WriteOnly if hasattr(_QtCore.QIODevice, 'WriteOnly') else _QtCore.QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(buf, "PNG")
        data = bytes(buf.data())
        buf.close()

        path = params.get("path")
        if path:
            pixmap.save(path, "PNG")
            return {"path": path, "width": pixmap.width(), "height": pixmap.height()}

        return {
            "data": base64.b64encode(data).decode(),
            "width": pixmap.width(),
            "height": pixmap.height(),
        }

    # -- Window management ---------------------------------------------------
    if method == METHOD_LIST_WINDOWS:
        windows = _get_top_level_widgets()
        result = []
        for w in windows:
            if w.isVisible():
                wid = _registry.register(w)
                result.append({
                    "wid": wid,
                    "title": w.windowTitle() if hasattr(w, "windowTitle") else "",
                    "class": _widget_class_name(w),
                    "width": w.width(),
                    "height": w.height(),
                })
        return result

    if method == METHOD_WINDOW_TITLE:
        w = _resolve_one(params)
        return w.windowTitle() if hasattr(w, "windowTitle") else ""

    if method == METHOD_WINDOW_SIZE:
        w = _resolve_one(params)
        return {"width": w.width(), "height": w.height()}

    if method == METHOD_WINDOW_RESIZE:
        w = _resolve_one(params)
        w.resize(params["width"], params["height"])
        _process_events()
        return True

    if method == METHOD_WINDOW_CLOSE:
        w = _resolve_one(params)
        w.close()
        _process_events()
        return True

    # -- Wait ----------------------------------------------------------------
    if method == METHOD_WAIT_FOR:
        return _wait_for(params)

    raise ValueError(f"Unknown method: {method}")


# --------------------------------------------------------------------------- #
#  Action helpers                                                              #
# --------------------------------------------------------------------------- #

def _process_events(ms: int = 10):
    """Process pending Qt events."""
    _QApplication.processEvents()
    if ms > 0:
        # Give the event loop a moment
        _QApplication.processEvents()


def _click_widget(widget, *, double: bool = False):
    """Simulate a mouse click on the center of a widget."""
    _import_qt()
    QTest = _QtTest
    Qt = _QtCore.Qt

    if QTest and hasattr(QTest, "QTest"):
        QTest = QTest.QTest

    widget.setFocus()
    _process_events()

    if QTest and hasattr(QTest, "mouseClick"):
        if double:
            QTest.mouseDClick(widget, Qt.LeftButton)
        else:
            QTest.mouseClick(widget, Qt.LeftButton)
    else:
        # Fallback: use QApplication.postEvent
        center = widget.rect().center()
        _post_mouse_event(widget, center, double=double)

    _process_events()


def _post_mouse_event(widget, pos, *, double: bool = False):
    """Post mouse press/release events directly."""
    QMouseEvent = _QtGui.QMouseEvent
    QEvent = _QtCore.QEvent
    Qt = _QtCore.Qt

    global_pos = widget.mapToGlobal(pos)

    # Try Qt6 API first, then Qt5
    try:
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress, pos, global_pos,
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        )
        release = QMouseEvent(
            QEvent.Type.MouseButtonRelease, pos, global_pos,
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        )
    except TypeError:
        from PySide6.QtCore import QPointF
        pos_f = QPointF(pos)
        global_f = QPointF(global_pos)
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress, pos_f, global_f,
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        )
        release = QMouseEvent(
            QEvent.Type.MouseButtonRelease, pos_f, global_f,
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        )

    _QApplication.postEvent(widget, press)
    _QApplication.postEvent(widget, release)

    if double:
        try:
            dbl = QMouseEvent(
                QEvent.Type.MouseButtonDblClick, pos, global_pos,
                Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
            )
        except TypeError:
            dbl = QMouseEvent(
                QEvent.Type.MouseButtonDblClick, QPointF(pos), QPointF(global_pos),
                Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
            )
        _QApplication.postEvent(widget, dbl)
        _QApplication.postEvent(widget, release)


def _fill_widget(widget, value: str):
    """Fill a text input widget."""
    _import_qt()

    class_name = _widget_class_name(widget)

    if hasattr(widget, "clear") and hasattr(widget, "setText"):
        widget.clear()
        widget.setText(value)
    elif hasattr(widget, "setPlainText"):
        widget.setPlainText(value)
    elif hasattr(widget, "setCurrentText"):
        widget.setCurrentText(value)
    else:
        raise ValueError(f"Cannot fill widget of type {class_name}")

    _process_events()


def _type_text(widget, text: str, delay: int = 0):
    """Type text character by character using key events."""
    _import_qt()
    QTest = _QtTest
    if QTest and hasattr(QTest, "QTest"):
        QTest = QTest.QTest

    widget.setFocus()
    _process_events()

    if QTest and hasattr(QTest, "keyClicks"):
        QTest.keyClicks(widget, text, delay=delay)
    else:
        # Fallback: use QKeyEvent
        QKeyEvent = _QtGui.QKeyEvent
        QEvent = _QtCore.QEvent
        Qt = _QtCore.Qt

        for ch in text:
            press = QKeyEvent(QEvent.Type.KeyPress, 0, Qt.NoModifier, ch)
            release = QKeyEvent(QEvent.Type.KeyRelease, 0, Qt.NoModifier, ch)
            _QApplication.postEvent(widget, press)
            _QApplication.postEvent(widget, release)
            if delay:
                _process_events()
                time.sleep(delay / 1000.0)

    _process_events()


def _press_key(widget, key_str: str):
    """Press a named key (Enter, Tab, etc.)."""
    _import_qt()
    Qt = _QtCore.Qt

    qt_key = _key_to_qt(key_str)
    if qt_key is None:
        # Try single character
        if len(key_str) == 1:
            qt_key = ord(key_str.upper())
        else:
            raise ValueError(f"Unknown key: {key_str}")

    QTest = _QtTest
    if QTest and hasattr(QTest, "QTest"):
        QTest = QTest.QTest

    widget.setFocus()
    _process_events()

    if QTest and hasattr(QTest, "keyClick"):
        QTest.keyClick(widget, qt_key)
    else:
        QKeyEvent = _QtGui.QKeyEvent
        QEvent = _QtCore.QEvent
        press = QKeyEvent(QEvent.Type.KeyPress, qt_key, Qt.NoModifier)
        release = QKeyEvent(QEvent.Type.KeyRelease, qt_key, Qt.NoModifier)
        _QApplication.postEvent(widget, press)
        _QApplication.postEvent(widget, release)

    _process_events()


def _select_option(widget, params: dict):
    """Select an option in a QComboBox."""
    if hasattr(widget, "setCurrentIndex") and hasattr(widget, "findText"):
        if "value" in params:
            widget.setCurrentText(str(params["value"]))
        elif "index" in params:
            widget.setCurrentIndex(params["index"])
        elif "label" in params:
            idx = widget.findText(params["label"])
            if idx >= 0:
                widget.setCurrentIndex(idx)
        _process_events()
    else:
        raise ValueError(f"Widget is not a combobox: {_widget_class_name(widget)}")


def _scroll_widget(widget, delta_x: int = 0, delta_y: int = 0):
    """Scroll a widget."""
    _import_qt()
    QWheelEvent = _QtGui.QWheelEvent
    QEvent = _QtCore.QEvent
    Qt = _QtCore.Qt

    center = widget.rect().center()
    global_pos = widget.mapToGlobal(center)

    try:
        from PySide6.QtCore import QPointF, QPoint
        event = QWheelEvent(
            QPointF(center), QPointF(global_pos),
            QPoint(delta_x, delta_y),   # pixelDelta
            QPoint(delta_x, delta_y),   # angleDelta
            Qt.NoButton, Qt.NoModifier,
            Qt.ScrollBegin, False,
        )
    except Exception:
        # Fallback for different Qt API
        event = QWheelEvent(
            center, global_pos,
            delta_y, Qt.NoButton, Qt.NoModifier,
        )

    _QApplication.postEvent(widget, event)
    _process_events()


def _wait_for(params: dict) -> bool:
    """Wait for a widget condition to be met."""
    selector = params.get("selector")
    state = params.get("state", "visible")  # visible, hidden, enabled, disabled
    timeout = params.get("timeout", 30000)  # ms
    poll_interval = params.get("poll_interval", 100)  # ms

    start = time.monotonic()
    deadline = start + timeout / 1000.0

    while time.monotonic() < deadline:
        _process_events()

        roots = _get_top_level_widgets()
        widgets = find_widgets(roots, selector, visible_only=False)

        if state == "visible":
            if any(w.isVisible() for w in widgets):
                return True
        elif state == "hidden":
            if not widgets or all(not w.isVisible() for w in widgets):
                return True
        elif state == "enabled":
            if any(w.isEnabled() for w in widgets):
                return True
        elif state == "disabled":
            if not widgets or all(not w.isEnabled() for w in widgets):
                return True
        elif state == "attached":
            if widgets:
                return True
        elif state == "detached":
            if not widgets:
                return True

        time.sleep(poll_interval / 1000.0)

    raise TimeoutError(f"Timed out waiting for {selector!r} to be {state}")


# --------------------------------------------------------------------------- #
#  TCP Server                                                                  #
# --------------------------------------------------------------------------- #

class _ClientHandler(threading.Thread):
    """Handle a single client connection."""

    def __init__(self, conn: socket.socket, addr, dispatcher, command_event_cls):
        super().__init__(daemon=True)
        self.conn = conn
        self.addr = addr
        self.dispatcher = dispatcher
        self.command_event_cls = command_event_cls
        self._running = True

    def run(self):
        logger.info("Client connected: %s", self.addr)
        buf = b""
        try:
            while self._running:
                data = self.conn.recv(4096)
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    self._process_line(line)
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            logger.info("Client disconnected: %s", self.addr)
            self.conn.close()

    def _process_line(self, line: bytes):
        try:
            d = decode_line(line)
            req = Request.from_dict(d)
        except Exception as e:
            resp = Response(id=0, error=f"Invalid request: {e}")
            self._send(resp)
            return

        # Dispatch to Qt main thread via event
        future = Future()
        event = self.command_event_cls(req, future)
        _QApplication.postEvent(self.dispatcher, event)

        try:
            result = future.result(timeout=60)
            resp = Response(id=req.id, result=result)
        except TimeoutError:
            resp = Response(id=req.id, error="Command timed out (60s)")
        except Exception as e:
            resp = Response(id=req.id, error=str(e))

        self._send(resp)

    def _send(self, resp: Response):
        try:
            self.conn.sendall(resp.to_bytes())
        except (BrokenPipeError, OSError):
            self._running = False

    def stop(self):
        self._running = False
        try:
            self.conn.close()
        except OSError:
            pass


class _AgentServer(threading.Thread):
    """TCP server that accepts client connections."""

    def __init__(self, host: str, port: int, dispatcher, command_event_cls):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.dispatcher = dispatcher
        self.command_event_cls = command_event_cls
        self._running = True
        self._server_socket: socket.socket | None = None
        self._clients: list[_ClientHandler] = []

    def run(self):
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.settimeout(1.0)
        self._server_socket.bind((self.host, self.port))
        self._server_socket.listen(5)
        logger.info("QPlaywright agent listening on %s:%d", self.host, self.port)

        while self._running:
            try:
                conn, addr = self._server_socket.accept()
                handler = _ClientHandler(conn, addr, self.dispatcher, self.command_event_cls)
                handler.start()
                self._clients.append(handler)
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    logger.exception("Server error")
                break

    def stop(self):
        self._running = False
        for client in self._clients:
            client.stop()
        if self._server_socket:
            self._server_socket.close()


# --------------------------------------------------------------------------- #
#  Public API                                                                  #
# --------------------------------------------------------------------------- #

_agent_server: _AgentServer | None = None


def start_agent(
    app=None,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> _AgentServer:
    """Start the QPlaywright agent inside a running Qt application.

    Call this after creating your ``QApplication`` but before ``app.exec()``.

    Args:
        app:  The QApplication instance (auto-detected if None).
        host: Host to bind the TCP server to.
        port: Port to bind the TCP server to.

    Returns:
        The server thread (call ``server.stop()`` to shut down).
    """
    global _agent_server
    _import_qt()

    if app is None:
        app = _QApplication.instance()
    if app is None:
        raise RuntimeError("No QApplication instance found. Create one first.")

    Dispatcher, CommandEvent = _create_dispatcher()
    dispatcher = Dispatcher()
    # Keep reference alive
    dispatcher.setObjectName("_qplaywright_dispatcher")

    server = _AgentServer(host, port, dispatcher, CommandEvent)
    server.start()

    _agent_server = server
    return server
