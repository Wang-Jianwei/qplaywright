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
import os
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
    METHOD_GET_PROPERTIES,
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
    METHOD_SET_SESSION_INFO,
)
from qplaywright.agent._selector import (
    find_widgets,
    widget_to_dict,
    _widget_text,
    _widget_class_name,
    _widget_value,
    _qt_property,
    _normalize_property_value,
    _widget_properties,
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
_VISUAL_FEEDBACK_ENABLED = False
_AUTOMATION_OVERLAY_OBJECT_NAME = "_qplaywright_automation_overlay"
_AUTOMATION_OVERLAY_PROPERTY = "qplaywrightAutomationOverlay"
_OVERLAY_MANAGER = None
_OverlayManagerClass = None
_SESSION_AGENT_NAMES: dict[str, str] = {}
_ACTIVE_SESSION_ID: str | None = None


def _active_session_agent_name() -> str:
    if _ACTIVE_SESSION_ID and _ACTIVE_SESSION_ID in _SESSION_AGENT_NAMES:
        return _SESSION_AGENT_NAMES[_ACTIVE_SESSION_ID]
    if _SESSION_AGENT_NAMES:
        fallback_session_id = next(reversed(_SESSION_AGENT_NAMES))
        return _SESSION_AGENT_NAMES[fallback_session_id]
    return ""


def _sync_overlay_session_agent_name() -> None:
    manager = _ensure_overlay_manager() if _VISUAL_FEEDBACK_ENABLED else _OVERLAY_MANAGER
    if manager is not None:
        manager.set_session_agent_name(_active_session_agent_name())


def _set_session_agent_name(session_id: str, agent_name: str) -> None:
    global _ACTIVE_SESSION_ID
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return

    normalized_agent_name = str(agent_name or "").strip()
    if normalized_agent_name:
        _SESSION_AGENT_NAMES[normalized_session_id] = normalized_agent_name
        _ACTIVE_SESSION_ID = normalized_session_id
    else:
        _SESSION_AGENT_NAMES.pop(normalized_session_id, None)
        if _ACTIVE_SESSION_ID == normalized_session_id:
            _ACTIVE_SESSION_ID = next(reversed(_SESSION_AGENT_NAMES), None)

    _sync_overlay_session_agent_name()


def _mark_session_active(session_id: str) -> None:
    global _ACTIVE_SESSION_ID
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id or normalized_session_id not in _SESSION_AGENT_NAMES:
        return
    if _ACTIVE_SESSION_ID == normalized_session_id:
        return
    _ACTIVE_SESSION_ID = normalized_session_id
    _sync_overlay_session_agent_name()


def _remove_session_agent_name(session_id: str) -> None:
    global _ACTIVE_SESSION_ID
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return

    _SESSION_AGENT_NAMES.pop(normalized_session_id, None)
    if _ACTIVE_SESSION_ID == normalized_session_id:
        _ACTIVE_SESSION_ID = next(reversed(_SESSION_AGENT_NAMES), None)
    _sync_overlay_session_agent_name()


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


def _is_automation_overlay_widget(widget) -> bool:
    if widget is None:
        return False

    object_name = getattr(widget, "objectName", None)
    if callable(object_name) and object_name() == _AUTOMATION_OVERLAY_OBJECT_NAME:
        return True

    return bool(_qt_property(widget, _AUTOMATION_OVERLAY_PROPERTY))


def _is_mouse_transparent_widget(widget) -> bool:
    if widget is None or _QtCore is None:
        return False

    qt = getattr(_QtCore, "Qt", None)
    attribute = getattr(qt, "WA_TransparentForMouseEvents", None)
    if attribute is None:
        return False

    test_attribute = getattr(widget, "testAttribute", None)
    if callable(test_attribute):
        try:
            return bool(test_attribute(attribute))
        except Exception:
            return False
    return False


def _create_overlay_manager_class():
    _import_qt()
    assert _QtWidgets is not None
    assert _QtCore is not None
    assert _QtGui is not None
    QObject = _QtCore.QObject
    QWidget = _QtWidgets.QWidget
    Qt = _QtCore.Qt
    QTimer = _QtCore.QTimer
    QPoint = _QtCore.QPoint
    QPainter = _QtGui.QPainter
    QColor = _QtGui.QColor
    QPen = _QtGui.QPen
    QLinearGradient = _QtGui.QLinearGradient
    QPolygon = _QtGui.QPolygon
    QBrush = _QtGui.QBrush

    class _AutomationOverlay(QWidget):
        def __init__(self, target_window):
            super().__init__(None)
            self._target_window = target_window
            self._manager_active = False
            self._cursor_pos = None
            self._session_agent_name = ""
            self._pulse_span = 0.22
            self._pulse_gap = 0.08
            self._pulse_records: list[tuple[float, Any, int]] = []
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)

            flags = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            if hasattr(Qt, "NoDropShadowWindowHint"):
                flags |= Qt.NoDropShadowWindowHint
            self.setWindowFlags(flags)
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self.setAttribute(Qt.WA_NoSystemBackground, True)
            if hasattr(Qt, "WA_TranslucentBackground"):
                self.setAttribute(Qt.WA_TranslucentBackground, True)
            if hasattr(Qt, "WA_ShowWithoutActivating"):
                self.setAttribute(Qt.WA_ShowWithoutActivating, True)
            self.setFocusPolicy(Qt.NoFocus)
            self.setObjectName(_AUTOMATION_OVERLAY_OBJECT_NAME)
            self.setProperty(_AUTOMATION_OVERLAY_PROPERTY, True)

        def sync_to_window(self, *, force_raise: bool = False) -> None:
            if not self._manager_active:
                self._timer.stop()
                self.hide()
                return

            if self._target_window is None:
                self.hide()
                return

            if not _is_overlay_target_window_visible(self._target_window):
                self.hide()
                return

            top_left = self._target_window.mapToGlobal(self._target_window.rect().topLeft())
            rect = self.geometry()
            if rect.x() != top_left.x() or rect.y() != top_left.y() or rect.width() != self._target_window.width() or rect.height() != self._target_window.height():
                self.setGeometry(top_left.x(), top_left.y(), self._target_window.width(), self._target_window.height())

            if self._cursor_pos is None:
                self._cursor_pos = self._target_window.rect().center()

            if not self.isVisible():
                self.show()
            if force_raise:
                self.raise_()
            if not self._timer.isActive():
                self._timer.start(16)

        def set_cursor_from_global(self, global_pos, *, pulse_count: int = 0) -> None:
            self._cursor_pos = self._target_window.mapFromGlobal(global_pos)
            if pulse_count > 0:
                self._pulse_records.append((time.monotonic(), QPoint(self._cursor_pos), pulse_count))
            self.sync_to_window(force_raise=True)
            self.update()

        def set_manager_active(self, active: bool) -> None:
            normalized = bool(active)
            if self._manager_active == normalized:
                return
            self._manager_active = normalized
            if not self._manager_active:
                self._timer.stop()
                self.hide()
                return
            self.sync_to_window()

        def set_session_agent_name(self, agent_name: str) -> None:
            normalized = str(agent_name or "").strip()
            if self._session_agent_name == normalized:
                return
            self._session_agent_name = normalized
            self.sync_to_window(force_raise=True)
            self.update()

        def close_overlay(self) -> None:
            self._timer.stop()
            self.hide()
            self.close()

        def _tick(self) -> None:
            cutoff = time.monotonic() - (self._pulse_span + self._pulse_gap)
            self._pulse_records = [record for record in self._pulse_records if record[0] >= cutoff]
            if not self._manager_active or self._target_window is None or not _is_overlay_target_window_visible(self._target_window):
                self.hide()
                if not self._manager_active and self._pulse_records:
                    self._pulse_records.clear()
            else:
                self.sync_to_window()
            if not self.isVisible() and not self._pulse_records:
                self._timer.stop()
                return
            self.update()

        def paintEvent(self, _event) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)

            core_color = QColor(20, 132, 255, 180)
            ring_base = QColor(20, 132, 255, 220)
            frame_color = QColor(20, 132, 255, 150)

            if self._session_agent_name:
                frame_rect = self.rect().adjusted(1, 1, -1, -1)
                glow_gradient = QLinearGradient(frame_rect.left(), frame_rect.top(), frame_rect.right(), frame_rect.bottom())
                glow_gradient.setColorAt(0.0, QColor(0, 245, 255, 60))
                glow_gradient.setColorAt(0.34, QColor(20, 132, 255, 65))
                glow_gradient.setColorAt(0.7, QColor(255, 76, 196, 60))
                glow_gradient.setColorAt(1.0, QColor(0, 245, 255, 55))
                painter.setPen(QPen(QBrush(glow_gradient), 6))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(frame_rect, 10, 10)

                frame_gradient = QLinearGradient(frame_rect.left(), frame_rect.top(), frame_rect.right(), frame_rect.bottom())
                frame_gradient.setColorAt(0.0, QColor(0, 245, 255, 185))
                frame_gradient.setColorAt(0.34, frame_color)
                frame_gradient.setColorAt(0.7, QColor(255, 76, 196, 175))
                frame_gradient.setColorAt(1.0, QColor(0, 245, 255, 180))
                painter.setPen(QPen(QBrush(frame_gradient), 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(frame_rect, 10, 10)

                label_text = f"正在与 Agent {self._session_agent_name} 共享"
                font = painter.font()
                if font.pointSizeF() > 0:
                    font.setPointSizeF(max(7.5, font.pointSizeF() - 2.0))
                elif font.pixelSize() > 0:
                    font.setPixelSize(max(10, font.pixelSize() - 3))
                else:
                    font.setPointSizeF(7.5)
                painter.setFont(font)
                metrics = painter.fontMetrics()
                badge_width = metrics.horizontalAdvance(label_text) + 18
                badge_height = metrics.height() + 8
                badge_rect = self.rect().adjusted(8, 8, -(self.width() - 8 - badge_width), -(self.height() - 8 - badge_height))

                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(9, 29, 61, 150))
                painter.drawRoundedRect(badge_rect, 8, 8)
                painter.setPen(QPen(QColor(140, 228, 255, 135), 1))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(badge_rect, 8, 8)
                painter.setPen(QColor(255, 255, 255, 230))
                painter.drawText(badge_rect.adjusted(9, 0, -9, 0), Qt.AlignVCenter | Qt.AlignLeft, label_text)

            for started_at, center, pulse_count in self._pulse_records:
                elapsed = time.monotonic() - started_at
                for pulse_index in range(pulse_count):
                    local_elapsed = elapsed - pulse_index * self._pulse_gap
                    if local_elapsed < 0 or local_elapsed > self._pulse_span:
                        continue

                    progress = local_elapsed / self._pulse_span
                    radius = 6 + progress * 20
                    alpha = max(0, int(ring_base.alpha() * (1.0 - progress)))
                    ring_color = QColor(ring_base)
                    ring_color.setAlpha(alpha)
                    painter.setPen(QPen(ring_color, 2))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawEllipse(center, int(radius), int(radius))

            if self._cursor_pos is None:
                return

            shadow = QPolygon(
                [
                    self._cursor_pos + QPoint(2, 2),
                    self._cursor_pos + QPoint(2, 20),
                    self._cursor_pos + QPoint(7, 15),
                    self._cursor_pos + QPoint(10, 23),
                    self._cursor_pos + QPoint(13, 22),
                    self._cursor_pos + QPoint(10, 14),
                    self._cursor_pos + QPoint(17, 14),
                ]
            )
            cursor = QPolygon(
                [
                    self._cursor_pos,
                    self._cursor_pos + QPoint(0, 18),
                    self._cursor_pos + QPoint(5, 13),
                    self._cursor_pos + QPoint(8, 21),
                    self._cursor_pos + QPoint(11, 20),
                    self._cursor_pos + QPoint(8, 12),
                    self._cursor_pos + QPoint(15, 12),
                ]
            )

            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, 110))
            painter.drawPolygon(shadow)
            painter.setPen(QPen(QColor(0, 0, 0, 200), 1))
            painter.setBrush(QBrush(QColor(255, 255, 255, 240)))
            painter.drawPolygon(cursor)
            painter.setPen(Qt.NoPen)
            painter.setBrush(core_color)
            painter.drawEllipse(self._cursor_pos, 4, 4)

    class _OverlayManager(QObject):
        def __init__(self, app):
            super().__init__(app)
            self._app = app
            self._overlays: dict[int, Any] = {}
            self._active_window_id: int | None = None
            self._session_agent_name = ""
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._sync)
            self._timer.start(16)

        def close_all(self) -> None:
            self._clear_overlays()
            self._timer.stop()

        def _clear_overlays(self) -> None:
            for window_id in list(self._overlays):
                self._drop_overlay(window_id)
            self._active_window_id = None

        def move_cursor(self, widget, pos, *, pulse_count: int = 0) -> None:
            target_window = widget.window() if hasattr(widget, "window") else None
            if not _is_overlay_target_window_visible(target_window):
                return
            self._active_window_id = id(target_window)
            overlay = self._ensure_overlay(target_window)
            overlay.set_manager_active(True)
            overlay.set_cursor_from_global(widget.mapToGlobal(pos), pulse_count=pulse_count)

        def set_session_agent_name(self, agent_name: str) -> None:
            normalized = str(agent_name or "").strip()
            self._session_agent_name = normalized
            if not normalized:
                self._clear_overlays()
                return
            for overlay in list(self._overlays.values()):
                overlay.set_session_agent_name(normalized)
            self._ensure_active_overlay()
            self._sync()

        def _ensure_active_overlay(self) -> None:
            if not _is_qt_application_active(self._app):
                self._active_window_id = None
                return
            active_window = self._app.activeWindow() if hasattr(self._app, "activeWindow") else None
            if not _is_overlay_target_window_visible(active_window):
                active_window = None
            if active_window is None:
                visible_windows = [window for window in _get_top_level_widgets() if _is_overlay_target_window_visible(window)]
                if visible_windows:
                    active_window = visible_windows[0]
            if active_window is None:
                return
            self._active_window_id = id(active_window)
            self._ensure_overlay(active_window)

        def _ensure_overlay(self, target_window):
            window_id = id(target_window)
            overlay = self._overlays.get(window_id)
            if overlay is not None:
                overlay.set_session_agent_name(self._session_agent_name)
                overlay.set_manager_active(window_id == self._active_window_id)
                return overlay

            overlay = _AutomationOverlay(target_window)
            overlay.set_session_agent_name(self._session_agent_name)
            overlay.set_manager_active(window_id == self._active_window_id)
            self._overlays[window_id] = overlay
            target_window.destroyed.connect(lambda *_args, wid=window_id: self._drop_overlay(wid))
            return overlay

        def _drop_overlay(self, window_id: int) -> None:
            overlay = self._overlays.pop(window_id, None)
            if overlay is not None:
                overlay.close_overlay()

        def _sync(self) -> None:
            if not _is_qt_application_active(self._app):
                self._active_window_id = None

            if self._active_window_id is not None:
                active_overlay = self._overlays.get(self._active_window_id)
                active_window = getattr(active_overlay, "_target_window", None) if active_overlay is not None else None
                if not _is_overlay_target_window_visible(active_window):
                    self._active_window_id = None

            if self._session_agent_name:
                self._ensure_active_overlay()

            for window_id, overlay in list(self._overlays.items()):
                target_window = getattr(overlay, "_target_window", None)
                if not _is_overlay_target_window_visible(target_window):
                    self._drop_overlay(window_id)
                    continue

                is_active = window_id == self._active_window_id
                overlay.set_manager_active(is_active)
                if not is_active:
                    continue

                overlay.sync_to_window()

            if self._session_agent_name and self._active_window_id is not None and self._active_window_id not in self._overlays:
                for window in _get_top_level_widgets():
                    if id(window) == self._active_window_id:
                        self._ensure_overlay(window)
                        break

    return _OverlayManager


def _ensure_overlay_manager():
    global _OVERLAY_MANAGER, _OverlayManagerClass
    if not _VISUAL_FEEDBACK_ENABLED:
        return None

    if _OverlayManagerClass is None:
        _OverlayManagerClass = _create_overlay_manager_class()
    if _OVERLAY_MANAGER is None:
        assert _QApplication is not None
        _OVERLAY_MANAGER = _OverlayManagerClass(_QApplication.instance())
    return _OVERLAY_MANAGER


def _update_visual_feedback(widget, pos, *, double: bool = False) -> None:
    manager = _ensure_overlay_manager()
    if manager is None:
        return
    manager.move_cursor(widget, pos, pulse_count=2 if double else 1)


def _move_visual_cursor(widget, pos, *, pulse_count: int = 0) -> None:
    manager = _ensure_overlay_manager()
    if manager is None:
        return
    manager.move_cursor(widget, pos, pulse_count=pulse_count)


def _move_visual_cursor_to_widget(widget, *, pulse_count: int = 0) -> None:
    target = _primary_event_target(widget)
    _move_visual_cursor(target, target.rect().center(), pulse_count=pulse_count)


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


def _iter_tree_children(widget, *, topmost_only: bool = False):
    for child in widget.children():
        if not hasattr(child, "isVisible") or _is_automation_overlay_widget(child):
            continue
        if topmost_only and not _is_topmost_visible_widget(child):
            continue
        yield child


def _widget_tree_to_dict(widget, *, depth: int = 0, max_depth: int = 50, topmost_only: bool = False) -> dict:
    """Serialize a widget tree and include stable widget ids for each node."""

    if _is_automation_overlay_widget(widget):
        raise ValueError("Automation overlay widgets are excluded from snapshot capture")

    info = widget_to_dict(widget, depth=depth, max_depth=depth)
    info["wid"] = _registry.register(widget)

    if depth < max_depth:
        children = []
        for child in _iter_tree_children(widget, topmost_only=topmost_only):
            children.append(
                _widget_tree_to_dict(child, depth=depth + 1, max_depth=max_depth, topmost_only=topmost_only)
            )
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
    return [widget for widget in _QApplication.topLevelWidgets() if not _is_automation_overlay_widget(widget)]


def _is_overlay_target_window_visible(widget) -> bool:
    qt_namespace = getattr(_QtCore, "Qt", None) if _QtCore is not None else None
    if widget is None or _is_automation_overlay_widget(widget):
        return False
    if not hasattr(widget, "isVisible") or not widget.isVisible():
        return False
    if hasattr(widget, "isMinimized") and widget.isMinimized():
        return False
    if qt_namespace is not None and hasattr(widget, "windowState") and widget.windowState() & qt_namespace.WindowMinimized:
        return False
    window_handle = widget.windowHandle() if hasattr(widget, "windowHandle") else None
    if window_handle is not None and hasattr(window_handle, "isExposed") and not window_handle.isExposed():
        return False
    return True


def _is_qt_application_active(app) -> bool:
    qt_namespace = getattr(_QtCore, "Qt", None) if _QtCore is not None else None
    if app is None or qt_namespace is None or not hasattr(app, "applicationState"):
        return True
    return app.applicationState() == qt_namespace.ApplicationActive


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
    params = dict(req.params)
    session_id = params.pop("_sessionId", "")
    if session_id:
        _mark_session_active(session_id)
    Qt = _QtCore.Qt
    QCursor = _QtGui.QCursor

    # -- Ping ----------------------------------------------------------------
    if method == METHOD_PING:
        return {"pong": True}

    if method == METHOD_SET_SESSION_INFO:
        _set_session_agent_name(str(session_id), str(params.get("agentName", "") or ""))
        return {"agentName": _active_session_agent_name()}

    # -- Widget discovery ----------------------------------------------------
    if method == METHOD_FIND:
        widgets = _resolve_widgets(params)
        if not widgets:
            return None
        w = widgets[0]
        wid = _registry.register(w)
        return {"wid": wid, **widget_to_dict(w, max_depth=params.get("max_depth", 0))}

    if method == METHOD_FIND_ALL:
        widgets = _resolve_widgets(params)
        result = []
        for w in widgets:
            wid = _registry.register(w)
            result.append({"wid": wid, **widget_to_dict(w, max_depth=params.get("max_depth", 0))})
        return result

    if method == METHOD_WIDGET_TREE:
        wid = params.get("wid")
        topmost_only = bool(params.get("topmost_only", False))
        if wid is not None:
            root = _registry.get(wid)
            if root is None:
                raise ValueError(f"Widget id={wid} not found or was garbage collected")
            roots = [root]
        else:
            roots = _get_top_level_widgets()
        return [
            _widget_tree_to_dict(r, max_depth=params.get("max_depth", 10), topmost_only=topmost_only)
            for r in roots
            if r.isVisible()
        ]

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
        return _normalize_property_value(_qt_property(w, prop_name))

    if method == METHOD_GET_PROPERTIES:
        w = _resolve_one(params)
        return _widget_properties(w)

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
        _move_visual_cursor_to_widget(w)
        _fill_widget(w, value)
        return True

    if method == METHOD_INVOKE:
        w = _resolve_one(params)
        return _invoke_widget_method(w, params.get("request") or {})

    if method == METHOD_CLEAR:
        w = _resolve_one(params)
        _move_visual_cursor_to_widget(w)
        _fill_widget(w, "")
        return True

    if method == METHOD_CHECK:
        w = _resolve_one(params)
        _move_visual_cursor_to_widget(w, pulse_count=1)
        if hasattr(w, "setChecked"):
            w.setChecked(True)
        return True

    if method == METHOD_UNCHECK:
        w = _resolve_one(params)
        _move_visual_cursor_to_widget(w, pulse_count=1)
        if hasattr(w, "setChecked"):
            w.setChecked(False)
        return True

    if method == METHOD_SELECT_OPTION:
        w = _resolve_one(params)
        _move_visual_cursor_to_widget(w, pulse_count=1)
        _select_option(w, params)
        return True

    if method == METHOD_TYPE:
        w = _resolve_one(params)
        text = params["text"]
        delay = params.get("delay", 0)
        _move_visual_cursor_to_widget(w)
        _type_text(w, text, delay)
        return True

    if method == METHOD_PRESS:
        if "wid" in params or "selector" in params:
            w = _resolve_one(params)
        else:
            w = _resolve_press_target(params)
        key = params["key"]
        _move_visual_cursor_to_widget(w)
        _press_key(w, key)
        return True

    if method == METHOD_HOVER:
        w = _resolve_one(params)
        target = _primary_event_target(w)
        local_pos = target.rect().center()
        _move_visual_cursor(target, local_pos)
        _hover_widget(target, local_pos)
        return True

    if method == METHOD_FOCUS:
        w = _resolve_one(params)
        target = _primary_event_target(w)
        _move_visual_cursor(target, target.rect().center())
        w.setFocus()
        _process_events()
        return True

    if method == METHOD_SCROLL:
        w = _resolve_one(params)
        target = _primary_event_target(w)
        _move_visual_cursor(target, target.rect().center(), pulse_count=1)
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

        clip_keys = ("x", "y", "width", "height")
        has_clip = any(params.get(key) is not None for key in clip_keys)
        if has_clip:
            if any(params.get(key) is None for key in clip_keys):
                raise ValueError("Screenshot clipping requires x, y, width, and height together")
            clip_x = int(params["x"])
            clip_y = int(params["y"])
            clip_width = int(params["width"])
            clip_height = int(params["height"])
            if clip_x < 0 or clip_y < 0 or clip_width <= 0 or clip_height <= 0:
                raise ValueError("Screenshot clipping requires non-negative x/y and positive width/height")
            pixmap = w.grab(_QtCore.QRect(clip_x, clip_y, clip_width, clip_height))
        else:
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
                    "geometry": {
                        "x": w.x(),
                        "y": w.y(),
                        "width": w.width(),
                        "height": w.height(),
                    },
                    "is_modal": bool(w.isModal()) if hasattr(w, "isModal") else False,
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


def _primary_event_target(widget):
    viewport = getattr(widget, "viewport", None)
    if callable(viewport):
        target = viewport()
        if target is not None:
            return target
    return widget


def _is_same_or_descendant_widget(candidate, ancestor) -> bool:
    current = candidate
    while current is not None:
        if current is ancestor:
            return True
        parent_widget = getattr(current, "parentWidget", None)
        current = parent_widget() if callable(parent_widget) else None
    return False


def _point_xy(point) -> tuple[int, int]:
    x_attr = getattr(point, "x", None)
    y_attr = getattr(point, "y", None)
    x_value = x_attr() if callable(x_attr) else x_attr
    y_value = y_attr() if callable(y_attr) else y_attr
    return int(x_value), int(y_value)


def _offset_point(point, dx: int, dy: int):
    point_type = type(point)
    x_value, y_value = _point_xy(point)
    return point_type(x_value + dx, y_value + dy)


def _point_within_widget_mask(widget, local_point) -> bool:
    mask_fn = getattr(widget, "mask", None)
    if not callable(mask_fn):
        return True

    region = mask_fn()
    if region is None:
        return True

    is_empty = getattr(region, "isEmpty", None)
    if callable(is_empty) and is_empty():
        return True

    contains = getattr(region, "contains", None)
    if callable(contains):
        return bool(contains(local_point))
    return True


def _sample_local_points(widget) -> list:
    center = widget.rect().center()

    width_fn = getattr(widget, "width", None)
    height_fn = getattr(widget, "height", None)
    width = int(width_fn()) if callable(width_fn) else 0
    height = int(height_fn()) if callable(height_fn) else 0

    offset_x = max(1, width // 4) if width > 1 else 0
    offset_y = max(1, height // 4) if height > 1 else 0

    samples = [center]
    if offset_x or offset_y:
        samples.extend(
            [
                _offset_point(center, -offset_x, -offset_y),
                _offset_point(center, offset_x, -offset_y),
                _offset_point(center, -offset_x, offset_y),
                _offset_point(center, offset_x, offset_y),
            ]
        )
    return samples


def _topmost_hit_at_point(target, local_point):
    if not _point_within_widget_mask(target, local_point):
        return None

    global_pos = target.mapToGlobal(local_point)

    hit = None
    widget_at = getattr(_QApplication, "widgetAt", None)
    if callable(widget_at):
        hit = widget_at(global_pos)
    if _is_automation_overlay_widget(hit) or _is_mouse_transparent_widget(hit):
        hit = None
    if hit is None and hasattr(target, "childAt"):
        hit = target.childAt(local_point)
    if _is_mouse_transparent_widget(hit):
        hit = None
    if hit is None:
        hit = target
    return hit


def _is_topmost_visible_widget(widget) -> bool:
    """Return True when the widget is frontmost at one of several sample points."""
    _import_qt()

    target = _primary_event_target(widget)
    if not hasattr(target, "isVisible") or not target.isVisible():
        return False

    for sample_point in _sample_local_points(target):
        hit = _topmost_hit_at_point(target, sample_point)
        if hit is None:
            continue
        if hasattr(hit, "isVisible") and not hit.isVisible():
            continue
        if _is_same_or_descendant_widget(hit, target):
            return True
    return False


def _resolve_click_target(widget):
    """Return the concrete event receiver and local click position."""
    _import_qt()

    target = _primary_event_target(widget)
    if not target.isVisible():
        raise ValueError(
            f"Cannot click widget of type {_widget_class_name(widget)}: event target is not visible"
        )
    if not target.isEnabled():
        raise ValueError(
            f"Cannot click widget of type {_widget_class_name(widget)}: event target is disabled"
        )

    center = target.rect().center()
    if not _point_within_widget_mask(target, center):
        raise ValueError(
            f"Cannot click widget of type {_widget_class_name(widget)}: center point is masked out"
        )
    global_pos = target.mapToGlobal(center)

    hit = _topmost_hit_at_point(target, center)
    if hit is None:
        raise ValueError(
            f"Cannot click widget of type {_widget_class_name(widget)}: center point does not resolve to an event target"
        )

    if not _is_same_or_descendant_widget(hit, target):
        raise ValueError(
            f"Cannot click widget of type {_widget_class_name(widget)}: center point is covered by {_widget_class_name(hit)}"
        )
    if hasattr(hit, "isVisible") and not hit.isVisible():
        raise ValueError(
            f"Cannot click widget of type {_widget_class_name(widget)}: resolved click target is not visible"
        )
    if hasattr(hit, "isEnabled") and not hit.isEnabled():
        raise ValueError(
            f"Cannot click widget of type {_widget_class_name(widget)}: resolved click target is disabled"
        )

    local_pos = hit.mapFromGlobal(global_pos) if hasattr(hit, "mapFromGlobal") else center
    return hit, local_pos


def _click_widget(widget, *, double: bool = False):
    """Simulate a mouse click on the concrete event target under the widget center."""
    _import_qt()
    QTest = _QtTest
    Qt = _QtCore.Qt

    if QTest and hasattr(QTest, "QTest"):
        QTest = QTest.QTest

    event_target, local_pos = _resolve_click_target(widget)

    try:
        event_target.setFocus(Qt.MouseFocusReason)
    except Exception:
        event_target.setFocus()
    _process_events()

    _update_visual_feedback(event_target, local_pos, double=double)

    if QTest and hasattr(QTest, "mouseClick"):
        try:
            if double:
                QTest.mouseDClick(event_target, Qt.LeftButton, Qt.NoModifier, local_pos)
            else:
                QTest.mouseClick(event_target, Qt.LeftButton, Qt.NoModifier, local_pos)
        except TypeError:
            if double:
                QTest.mouseDClick(event_target, Qt.LeftButton)
            else:
                QTest.mouseClick(event_target, Qt.LeftButton)
    else:
        # Fallback: use QApplication.postEvent
        _post_mouse_event(event_target, local_pos, double=double)

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


def _hover_widget(widget, pos):
    """Dispatch a synthetic hover event without warping the real cursor."""
    _import_qt()
    Qt = _QtCore.Qt
    QEvent = _QtCore.QEvent

    QMouseEvent = _QtGui.QMouseEvent
    global_pos = widget.mapToGlobal(pos)

    try:
        move = QMouseEvent(
            QEvent.Type.MouseMove, pos, global_pos,
            Qt.NoButton, Qt.NoButton, Qt.NoModifier,
        )
    except TypeError:
        from PySide6.QtCore import QPointF
        move = QMouseEvent(
            QEvent.Type.MouseMove, QPointF(pos), QPointF(global_pos),
            Qt.NoButton, Qt.NoButton, Qt.NoModifier,
        )

    _QApplication.postEvent(widget, move)
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
    Qt = _QtCore.Qt

    target = _primary_event_target(widget)

    center = target.rect().center()
    global_pos = target.mapToGlobal(center)

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

    _QApplication.postEvent(target, event)
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


def _resolve_press_target(params: dict):
    app = _QApplication
    if app is not None:
        focused = app.focusWidget()
        if focused is not None:
            return focused

    window_wid = params.get("window_wid")
    if window_wid is not None:
        window = _registry.get(window_wid)
        if window is not None:
            return window

    visible = [window for window in _get_top_level_widgets() if window.isVisible()]
    if visible:
        return visible[0]

    raise ValueError("No visible window found for targetless key press")


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
        self._session_id = f"{addr[0]}:{addr[1]}:{id(self)}"

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
            _remove_session_agent_name(self._session_id)
            self.conn.close()

    def _process_line(self, line: bytes):
        try:
            d = decode_line(line)
            req = Request.from_dict(d)
            req.params["_sessionId"] = self._session_id
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
    visual_feedback: bool | None = None,
) -> _AgentServer:
    """Start the QPlaywright agent inside a running Qt application.

    Call this after creating your ``QApplication`` but before ``app.exec()``.

    Args:
        app:  The QApplication instance (auto-detected if None).
        host: Host to bind the TCP server to.
        port: Port to bind the TCP server to.
        visual_feedback: Whether to show visual click feedback in the UI. Defaults to
            the QPLAYWRIGHT_VISUAL_FEEDBACK environment variable when omitted.

    Returns:
        The server thread (call ``server.stop()`` to shut down).
    """
    global _agent_server, _VISUAL_FEEDBACK_ENABLED, _OVERLAY_MANAGER
    _import_qt()

    if visual_feedback is None:
        env_value = os.environ.get("QPLAYWRIGHT_VISUAL_FEEDBACK", "").strip().lower()
        visual_feedback = env_value in {"1", "true", "yes", "on"}
    _VISUAL_FEEDBACK_ENABLED = bool(visual_feedback)

    if app is None:
        app = _QApplication.instance()
    if app is None:
        raise RuntimeError("No QApplication instance found. Create one first.")

    if _VISUAL_FEEDBACK_ENABLED:
        _ensure_overlay_manager()
    elif _OVERLAY_MANAGER is not None:
        _OVERLAY_MANAGER.close_all()
        _OVERLAY_MANAGER = None

    Dispatcher, CommandEvent = _create_dispatcher()
    dispatcher = Dispatcher()
    # Keep reference alive
    dispatcher.setObjectName("_qplaywright_dispatcher")

    server = _AgentServer(host, port, dispatcher, CommandEvent)
    server.start()

    _agent_server = server
    return server
