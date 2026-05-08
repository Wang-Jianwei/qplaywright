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
import weakref
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
    METHOD_FIND_WIDGETS,
    METHOD_WIDGET_TREE,
    METHOD_GET_PROPERTY,
    METHOD_GET_PROPERTIES,
    METHOD_GET_TEXT,
    METHOD_GET_VALUE,
    METHOD_GET_METHODS,
    METHOD_ITEM_TEXT,
    METHOD_ITEM_PROPERTIES,
    METHOD_ITEM_VISIBLE,
    METHOD_ITEM_SELECTED,
    METHOD_ITEM_BOUNDING_BOX,
    METHOD_ITEM_CLICK,
    METHOD_ITEM_DBLCLICK,
    METHOD_ITEM_HOVER,
    METHOD_ITEM_SELECT,
    METHOD_ITEM_EXPAND,
    METHOD_ITEM_COLLAPSE,
    METHOD_ITEM_VIEW_INSPECT,
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
    _iter_widget_children,
    _matches_accessible_name,
    _matches_class,
    _matches_has_text,
    _matches_object_name,
    _matches_role,
    _matches_text_exact,
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
_QPointF = None
_VISUAL_FEEDBACK_ENABLED = False
_AUTOMATION_OVERLAY_OBJECT_NAME = "_qplaywright_automation_overlay"
_AUTOMATION_OVERLAY_PROPERTY = "qplaywrightAutomationOverlay"
_OVERLAY_EDGE_PADDING = 3
_OVERLAY_FRAME_OUTSET = 3
_OVERLAY_BADGE_GAP = 3
_OVERLAY_BADGE_LEFT_INSET = 6
_OVERLAY_BADGE_TOP_INSET = 6
_OVERLAY_CORNER_RADIUS = 6
_OVERLAY_BADGE_RADIUS = 7
_OVERLAY_MANAGER = None
_OverlayManagerClass = None
_FIND_INFRASTRUCTURE_WIDGET_CLASSES = {
    "QAbstractScrollAreaScrollBarContainer",
}
_SESSION_AGENT_NAMES: dict[str, str] = {}
_ACTIVE_SESSION_ID: str | None = None
# Reentrancy guard: set to True while a CommandEvent is being handled on the Qt
# main thread.  Only ever read/written from the main thread (customEvent is
# always called there), so no lock is needed.
_executing_command: bool = False


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
    global _QtWidgets, _QtCore, _QtGui, _QtTest, _QApplication, _QPointF
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
            _QPointF = getattr(_QtCore, "QPointF", None)
            if _QPointF is None:
                _QPointF = getattr(_QtGui, "QPointF", None)
            if _QPointF is None:
                raise ImportError(f"QPointF not found in {pkg}.QtCore or {pkg}.QtGui")
            logger.info("Using Qt binding: %s", pkg)
            return
        except ImportError:
            continue
    raise ImportError("No Qt binding found. Install PySide6, PyQt6, PySide2, or PyQt5.")


def _qt_core_module() -> Any:
    _import_qt()
    if _QtCore is None:
        raise RuntimeError("QtCore is not available")
    return _QtCore


def _qt_gui_module() -> Any:
    _import_qt()
    if _QtGui is None:
        raise RuntimeError("QtGui is not available")
    return _QtGui


def _qt_application_class() -> Any:
    _import_qt()
    if _QApplication is None:
        raise RuntimeError("QApplication is not available")
    return _QApplication


def _to_qpointf(point):
    _import_qt()
    qpointf_type = _QPointF
    if qpointf_type is None:
        return point
    return qpointf_type(point)


def _coerce_runtime_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an int, got {type(value).__name__}")
    return value


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
    QRect = _QtCore.QRect
    QPainter = _QtGui.QPainter
    QColor = _QtGui.QColor
    QPen = _QtGui.QPen
    QLinearGradient = _QtGui.QLinearGradient
    QFontMetrics = _QtGui.QFontMetrics
    QPolygon = _QtGui.QPolygon
    QBrush = _QtGui.QBrush

    class _AutomationOverlay(QWidget):
        def __init__(self, target_window):
            super().__init__(None)
            self._target_window = target_window
            self._manager_active = False
            self._content_origin = QPoint(0, 0)
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

        def _badge_text(self) -> str:
            if not self._session_agent_name:
                return ""
            return f"正在与 Agent {self._session_agent_name} 共享"

        def _badge_font(self):
            font = self.font()
            if font.pointSizeF() > 0:
                font.setPointSizeF(max(7.5, font.pointSizeF() - 2.0))
            elif font.pixelSize() > 0:
                font.setPixelSize(max(10, font.pixelSize() - 3))
            else:
                font.setPointSizeF(7.5)
            return font

        def _is_maximized_window(self) -> bool:
            if self._target_window is None:
                return False
            if hasattr(self._target_window, "isMaximized") and self._target_window.isMaximized():
                return True
            if hasattr(self._target_window, "windowState") and self._target_window.windowState() & Qt.WindowMaximized:
                return True
            return False

        def _wrapped_global_rect(self):
            if self._target_window is None:
                return QRect()

            content_top_left = self._target_window.mapToGlobal(self._target_window.rect().topLeft())
            content_global_rect = QRect(content_top_left, self._target_window.size())
            if not hasattr(self._target_window, "frameGeometry"):
                return content_global_rect

            frame_global_rect = self._target_window.frameGeometry()
            if (
                frame_global_rect.isValid()
                and frame_global_rect.contains(content_global_rect)
                and (
                    frame_global_rect.topLeft() != content_global_rect.topLeft()
                    or frame_global_rect.size() != content_global_rect.size()
                )
            ):
                return QRect(frame_global_rect)

            return content_global_rect

        def _layout_metrics(self) -> dict[str, Any]:
            badge_text = self._badge_text()
            badge_font = self._badge_font()
            badge_width = 0
            badge_height = 0
            if badge_text:
                metrics = QFontMetrics(badge_font)
                badge_width = metrics.horizontalAdvance(badge_text) + 18
                badge_height = metrics.height() + 8

            wrapped_global_rect = self._wrapped_global_rect()
            content_top_left = self._target_window.mapToGlobal(self._target_window.rect().topLeft()) if self._target_window is not None else QPoint(0, 0)
            content_offset = content_top_left - wrapped_global_rect.topLeft()
            is_maximized = self._is_maximized_window()
            badge_reserve = badge_height + _OVERLAY_BADGE_GAP if badge_text and not is_maximized else 0
            wrapped_rect = QRect(
                _OVERLAY_EDGE_PADDING + _OVERLAY_FRAME_OUTSET,
                _OVERLAY_EDGE_PADDING + _OVERLAY_FRAME_OUTSET + badge_reserve,
                wrapped_global_rect.width(),
                wrapped_global_rect.height(),
            )
            frame_rect = wrapped_rect.adjusted(
                -_OVERLAY_FRAME_OUTSET,
                -_OVERLAY_FRAME_OUTSET,
                _OVERLAY_FRAME_OUTSET,
                _OVERLAY_FRAME_OUTSET,
            )
            target_rect = QRect(
                wrapped_rect.left() + content_offset.x(),
                wrapped_rect.top() + content_offset.y(),
                self._target_window.width() if self._target_window is not None else 0,
                self._target_window.height() if self._target_window is not None else 0,
            )
            badge_rect = QRect()
            overlay_width = frame_rect.right() + _OVERLAY_EDGE_PADDING + 1
            overlay_height = frame_rect.bottom() + _OVERLAY_EDGE_PADDING + 1
            if badge_text:
                if is_maximized:
                    badge_band_top = frame_rect.top() + _OVERLAY_BADGE_TOP_INSET
                    badge_band_bottom = max(
                        badge_band_top,
                        target_rect.top() - _OVERLAY_BADGE_TOP_INSET - badge_height,
                    )
                    centered_badge_top = frame_rect.top() + (target_rect.top() - frame_rect.top() - badge_height) // 2
                    badge_top = min(max(centered_badge_top, badge_band_top), badge_band_bottom)
                    badge_rect = QRect(
                        frame_rect.center().x() - badge_width // 2,
                        badge_top,
                        badge_width,
                        badge_height,
                    )
                else:
                    badge_rect = QRect(
                        frame_rect.left() + _OVERLAY_BADGE_LEFT_INSET,
                        frame_rect.top() - _OVERLAY_BADGE_GAP - badge_height,
                        badge_width,
                        badge_height,
                    )
                overlay_width = max(overlay_width, badge_rect.right() + _OVERLAY_EDGE_PADDING + 1)
                overlay_height = max(overlay_height, badge_rect.bottom() + _OVERLAY_EDGE_PADDING + 1)

            return {
                "target_rect": target_rect,
                "wrapped_rect": wrapped_rect,
                "wrapped_global_rect": wrapped_global_rect,
                "frame_rect": frame_rect,
                "badge_rect": badge_rect,
                "badge_font": badge_font,
                "badge_text": badge_text,
                "is_maximized": is_maximized,
                "overlay_width": overlay_width,
                "overlay_height": overlay_height,
            }

        def _overlay_point_from_target(self, target_point):
            if target_point is None:
                return None
            return QPoint(
                target_point.x() + self._content_origin.x(),
                target_point.y() + self._content_origin.y(),
            )

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

            layout = self._layout_metrics()
            self._content_origin = layout["target_rect"].topLeft()
            rect = self.geometry()
            geometry_x = layout["wrapped_global_rect"].x() - layout["wrapped_rect"].x()
            geometry_y = layout["wrapped_global_rect"].y() - layout["wrapped_rect"].y()
            if rect.x() != geometry_x or rect.y() != geometry_y or rect.width() != layout["overlay_width"] or rect.height() != layout["overlay_height"]:
                self.setGeometry(geometry_x, geometry_y, layout["overlay_width"], layout["overlay_height"])

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
            layout = self._layout_metrics()

            if layout["badge_text"]:
                frame_rect = layout["frame_rect"]
                glow_gradient = QLinearGradient(frame_rect.left(), frame_rect.top(), frame_rect.right(), frame_rect.bottom())
                glow_gradient.setColorAt(0.0, QColor(0, 245, 255, 60))
                glow_gradient.setColorAt(0.34, QColor(20, 132, 255, 65))
                glow_gradient.setColorAt(0.7, QColor(255, 76, 196, 60))
                glow_gradient.setColorAt(1.0, QColor(0, 245, 255, 55))
                painter.setPen(QPen(QBrush(glow_gradient), 6))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(frame_rect, _OVERLAY_CORNER_RADIUS, _OVERLAY_CORNER_RADIUS)

                frame_gradient = QLinearGradient(frame_rect.left(), frame_rect.top(), frame_rect.right(), frame_rect.bottom())
                frame_gradient.setColorAt(0.0, QColor(0, 245, 255, 185))
                frame_gradient.setColorAt(0.34, frame_color)
                frame_gradient.setColorAt(0.7, QColor(255, 76, 196, 175))
                frame_gradient.setColorAt(1.0, QColor(0, 245, 255, 180))
                painter.setPen(QPen(QBrush(frame_gradient), 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(frame_rect, _OVERLAY_CORNER_RADIUS, _OVERLAY_CORNER_RADIUS)

                painter.setFont(layout["badge_font"])
                badge_rect = layout["badge_rect"]

                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(9, 29, 61, 150))
                painter.drawRoundedRect(badge_rect, _OVERLAY_BADGE_RADIUS, _OVERLAY_BADGE_RADIUS)
                painter.setPen(QPen(QColor(140, 228, 255, 135), 1))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(badge_rect, _OVERLAY_BADGE_RADIUS, _OVERLAY_BADGE_RADIUS)
                painter.setPen(QColor(255, 255, 255, 230))
                painter.drawText(badge_rect.adjusted(9, 0, -9, 0), Qt.AlignVCenter | Qt.AlignLeft, layout["badge_text"])

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
                    overlay_center = self._overlay_point_from_target(center)
                    painter.setPen(QPen(ring_color, 2))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawEllipse(overlay_center, int(radius), int(radius))

            if self._cursor_pos is None:
                return

            cursor_pos = self._overlay_point_from_target(self._cursor_pos)

            shadow = QPolygon(
                [
                    cursor_pos + QPoint(2, 2),
                    cursor_pos + QPoint(2, 20),
                    cursor_pos + QPoint(7, 15),
                    cursor_pos + QPoint(10, 23),
                    cursor_pos + QPoint(13, 22),
                    cursor_pos + QPoint(10, 14),
                    cursor_pos + QPoint(17, 14),
                ]
            )
            cursor = QPolygon(
                [
                    cursor_pos,
                    cursor_pos + QPoint(0, 18),
                    cursor_pos + QPoint(5, 13),
                    cursor_pos + QPoint(8, 21),
                    cursor_pos + QPoint(11, 20),
                    cursor_pos + QPoint(8, 12),
                    cursor_pos + QPoint(15, 12),
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
            painter.drawEllipse(cursor_pos, 4, 4)

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
            modal_window = _active_modal_top_level_widget()
            if modal_window is not None:
                self._active_window_id = id(modal_window)
                self._ensure_overlay(modal_window)
                return
            active_window = self._app.activeWindow() if hasattr(self._app, "activeWindow") else None
            if not _is_overlay_target_window_visible(active_window):
                active_window = None
            if active_window is None:
                visible_windows = [window for window in _get_interactable_top_level_widgets() if _is_overlay_target_window_visible(window)]
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

        def overlay_for_window(self, target_window):
            if target_window is None:
                return None
            return self._overlays.get(id(target_window))

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
    _move_visual_cursor(target, _widget_center_point(target), pulse_count=pulse_count)


# --------------------------------------------------------------------------- #
#  Widget ID registry — gives each widget a stable numeric ID                  #
# --------------------------------------------------------------------------- #

class _WidgetRegistry:
    """Maps widgets ↔ integer IDs so the client can reference them.

    Uses weakref to avoid keeping widgets alive and to detect when a widget
    has been garbage-collected.  If a widget is GC'd and a new object reuses
    its memory address, the stale entry is evicted before the new widget is
    registered.
    """

    def __init__(self):
        self._w2id: dict[int, int] = {}
        self._id2w: dict[int, tuple[weakref.ref, int]] = {}
        self._next = 1
        self._lock = threading.Lock()

    def register(self, widget) -> int:
        key = id(widget)
        with self._lock:
            if key in self._w2id:
                wid = self._w2id[key]
                entry = self._id2w.get(wid)
                if entry is not None:
                    ref, _stored_key = entry
                    if ref() is widget:
                        return wid
                    self._remove_entry(wid, _stored_key)
            wid = self._next
            self._next += 1
            ref = weakref.ref(widget, lambda _ref: self._on_ref_cleared(key, wid))
            self._w2id[key] = wid
            self._id2w[wid] = (ref, key)
            return wid

    def get(self, wid: int):
        with self._lock:
            entry = self._id2w.get(wid)
            if entry is None:
                return None
            ref, _key = entry
            widget = ref()
            if widget is None:
                self._remove_entry(wid, _key)
                return None
            return widget

    def _on_ref_cleared(self, key: int, wid: int):
        with self._lock:
            self._w2id.pop(key, None)
            self._id2w.pop(wid, None)

    def _remove_entry(self, wid: int, key: int):
        self._w2id.pop(key, None)
        self._id2w.pop(wid, None)

    def clear(self):
        with self._lock:
            self._w2id.clear()
            self._id2w.clear()
            self._next = 1


_registry = _WidgetRegistry()


def _iter_tree_children(widget, *, topmost_only: bool = False):
    for child in _iter_widget_children(widget):
        if _is_automation_overlay_widget(child):
            continue
        is_window = getattr(child, "isWindow", None)
        is_visible = getattr(child, "isVisible", None)
        if callable(is_window) and callable(is_visible) and is_window() and not is_visible():
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
    qt_core = _qt_core_module()
    q_application = _qt_application_class()
    QEvent = qt_core.QEvent
    QObject = qt_core.QObject

    _CMD_EVENT_TYPE = QEvent.Type(QEvent.registerEventType())
    _CALL_EVENT_TYPE = QEvent.Type(QEvent.registerEventType())

    class CommandEvent(QEvent):
        def __init__(self, request: Request, future: Future):
            super().__init__(_CMD_EVENT_TYPE)
            self.request = request
            self.future = future

    class MainThreadCallEvent(QEvent):
        def __init__(self, callback, future: Future):
            super().__init__(_CALL_EVENT_TYPE)
            self.callback = callback
            self.future = future

    class Dispatcher(QObject):
        def __init__(self):
            super().__init__()
            self._cmd_event_type = _CMD_EVENT_TYPE
            self._call_event_type = _CALL_EVENT_TYPE

        def customEvent(self, event):
            global _executing_command
            if event.type() == self._cmd_event_type:
                req = event.request
                fut = event.future
                if _executing_command:
                    # Re-post the event so it is processed after the current command
                    # finishes, preventing re-entrant command execution during
                    # processEvents() calls inside _handle_command.
                    logger.debug(
                        "Re-entrant CommandEvent detected (method=%r); deferring until current command completes.",
                        req.method,
                    )
                    q_application.postEvent(self, CommandEvent(req, fut))
                    return
                _executing_command = True
                try:
                    result = _handle_command(req)
                    fut.set_result(result)
                except Exception as exc:
                    fut.set_exception(exc)
                finally:
                    _executing_command = False
            elif event.type() == self._call_event_type:
                callback = event.callback
                fut = event.future
                try:
                    fut.set_result(callback())
                except Exception as exc:
                    fut.set_exception(exc)

    return Dispatcher, CommandEvent, MainThreadCallEvent


# --------------------------------------------------------------------------- #
#  Command handler — runs on the main thread                                   #
# --------------------------------------------------------------------------- #

def _get_top_level_widgets():
    q_application = _qt_application_class()
    return [widget for widget in q_application.topLevelWidgets() if not _is_automation_overlay_widget(widget)]


def _active_modal_top_level_widget():
    app = _QApplication.instance() if _QApplication is not None and hasattr(_QApplication, "instance") else None
    active_modal = None
    if app is not None and hasattr(app, "activeModalWidget"):
        active_modal = app.activeModalWidget()
    elif _QApplication is not None and hasattr(_QApplication, "activeModalWidget"):
        active_modal = _QApplication.activeModalWidget()
    if active_modal is None:
        return None
    modal_window = active_modal.window() if hasattr(active_modal, "window") else active_modal
    if not _is_overlay_target_window_visible(modal_window):
        return None
    return modal_window


def _is_window_blocked_by_modal(widget) -> bool:
    modal_window = _active_modal_top_level_widget()
    if modal_window is None or widget is None:
        return False
    widget_window = widget.window() if hasattr(widget, "window") else widget
    return widget_window is not None and widget_window is not modal_window


def _get_interactable_top_level_widgets() -> list:
    modal_window = _active_modal_top_level_widget()
    if modal_window is not None:
        return [modal_window]
    return _get_top_level_widgets()


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
        roots = _get_interactable_top_level_widgets()

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


def _find_lightly_visible(widget) -> bool:
    return _widget_is_visible(widget) and widget.width() > 0 and widget.height() > 0


def _find_interactable(widget) -> bool:
    try:
        _resolve_click_target(widget)
    except Exception:
        return False
    return True


def _is_find_infrastructure_widget(widget) -> bool:
    if _is_automation_overlay_widget(widget):
        return True

    object_name = widget.objectName() if hasattr(widget, "objectName") else ""
    if isinstance(object_name, str) and object_name.startswith("qt_"):
        return True

    return _widget_class_name(widget) in _FIND_INFRASTRUCTURE_WIDGET_CLASSES


def _resolve_find_root_widget(params: dict):
    wid = params.get("wid")
    if wid is not None:
        root = _registry.get(wid)
        if root is None:
            raise ValueError(f"Widget id={wid} not found or was garbage collected")
        return root

    selector = params.get("selector")
    if selector is None:
        raise ValueError("find_widgets requires wid or selector root")

    matches = _resolve_widgets({"selector": selector, "visible_only": False})
    if not matches:
        raise ValueError(f"No widget found for find root: {selector}")
    if len(matches) > 1:
        raise ValueError(f"Find root is ambiguous for selector: {selector}")
    return matches[0]


def _find_match_reasons(params: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if params.get("role") is not None:
        reasons.append(f"role={params['role']}")
    if params.get("text") is not None:
        reasons.append(f"text={params['text']}")
    if params.get("has_text") is not None:
        reasons.append(f"has_text~={params['has_text']}")
    if params.get("class") is not None:
        reasons.append(f"class={params['class']}")
    if params.get("object_name") is not None:
        reasons.append(f"object_name={params['object_name']}")
    if params.get("accessible_name") is not None:
        reasons.append(f"accessible_name={params['accessible_name']}")
    for name in ("visible", "enabled", "interactable"):
        value = params.get(name)
        if value is not None:
            reasons.append(f"{name}={'true' if value else 'false'}")
    return reasons


def _find_widget_matches(widget, params: dict[str, Any], *, visible: bool, enabled: bool, interactable: bool) -> bool:
    role = params.get("role")
    if role is not None and not _matches_role(widget, role):
        return False

    text = params.get("text")
    if text is not None and not _matches_text_exact(widget, text):
        return False

    has_text = params.get("has_text")
    if has_text is not None and not _matches_has_text(widget, has_text):
        return False

    widget_class = params.get("class")
    if widget_class is not None and not _matches_class(widget, widget_class):
        return False

    object_name = params.get("object_name")
    if object_name is not None and not _matches_object_name(widget, object_name):
        return False

    accessible_name = params.get("accessible_name")
    if accessible_name is not None and not _matches_accessible_name(widget, accessible_name):
        return False

    if params.get("visible") is not None and visible is not bool(params["visible"]):
        return False

    if params.get("enabled") is not None and enabled is not bool(params["enabled"]):
        return False

    if params.get("interactable") is not None and interactable is not bool(params["interactable"]):
        return False

    return True


def _find_ancestor_summary(ancestors: list) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for ancestor in ancestors:
        summary.append({"wid": _registry.register(ancestor), **widget_to_dict(ancestor, max_depth=0)})
    return summary


def _find_widgets_payload(params: dict[str, Any]) -> dict[str, Any]:
    root = _resolve_find_root_widget(params)
    root_wid = _registry.register(root)
    include_infrastructure = bool(params.get("include_infrastructure", False))
    limit = int(params.get("limit", 5))
    if limit <= 0:
        raise ValueError("limit must be > 0")

    matches: list[dict[str, Any]] = []
    preorder = 0
    match_reason = _find_match_reasons(params)
    explicit_visible = params.get("visible") is not None
    explicit_interactable = params.get("interactable") is not None

    def _walk(widget, ancestors: list) -> None:
        nonlocal preorder

        current_order = preorder
        preorder += 1
        visible = _find_lightly_visible(widget)
        enabled = _widget_is_enabled(widget)
        interactable = _find_interactable(widget)
        is_infrastructure = _is_find_infrastructure_widget(widget)

        if (include_infrastructure or not is_infrastructure) and _find_widget_matches(
            widget,
            params,
            visible=visible,
            enabled=enabled,
            interactable=interactable,
        ):
            wid = _registry.register(widget)
            entry = {"wid": wid, **widget_to_dict(widget, max_depth=0), "matchReason": list(match_reason)}
            if ancestors:
                entry["ancestorSummary"] = _find_ancestor_summary(ancestors)
            matches.append(
                {
                    "depth": len(ancestors),
                    "interactable": interactable,
                    "visible": visible,
                    "preorder": current_order,
                    "wid": wid,
                    "entry": entry,
                }
            )

        for child in _iter_widget_children(widget):
            _walk(child, [*ancestors, widget])

    _walk(root, [])

    matches.sort(
        key=lambda item: (
            item["depth"],
            0 if explicit_interactable else (0 if item["interactable"] else 1),
            0 if explicit_visible else (0 if item["visible"] else 1),
            item["preorder"],
            item["wid"],
        )
    )
    truncated = len(matches) > limit
    return {
        "rootWid": root_wid,
        "count": min(len(matches), limit),
        "truncated": truncated,
        "results": [item["entry"] for item in matches[:limit]],
    }


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


def _qt_display_role():
    if _QtCore is None:
        return 0
    qt = getattr(_QtCore, "Qt", None)
    if qt is None:
        return 0
    item_data_role = getattr(qt, "ItemDataRole", None)
    if item_data_role is not None and hasattr(item_data_role, "DisplayRole"):
        return item_data_role.DisplayRole
    return getattr(qt, "DisplayRole", 0)


def _qt_horizontal_orientation():
    if _QtCore is None:
        return 1
    qt = getattr(_QtCore, "Qt", None)
    if qt is None:
        return 1
    orientation = getattr(qt, "Orientation", None)
    if orientation is not None and hasattr(orientation, "Horizontal"):
        return orientation.Horizontal
    return getattr(qt, "Horizontal", 1)


def _qt_ensure_visible_hint():
    if _QtWidgets is None:
        return None
    abstract_item_view = getattr(_QtWidgets, "QAbstractItemView", None)
    if abstract_item_view is None:
        return None
    scroll_hint = getattr(abstract_item_view, "ScrollHint", None)
    if scroll_hint is not None and hasattr(scroll_hint, "EnsureVisible"):
        return scroll_hint.EnsureVisible
    return getattr(abstract_item_view, "EnsureVisible", None)


def _resolve_item_owner(params: dict):
    wid = params.get("wid")
    if wid is None:
        raise ValueError("Item operations require wid")

    owner = _registry.get(int(wid))
    if owner is None:
        raise ValueError(f"Widget id={wid} not found or was garbage collected")
    return owner


def _table_view(owner_widget):
    _import_qt()
    table_view_type = getattr(_QtWidgets, "QTableView", None) if _QtWidgets is not None else None
    if table_view_type is not None and isinstance(owner_widget, table_view_type):
        return owner_widget

    class_name = _widget_class_name(owner_widget)
    if class_name not in {"QTableView", "QTableWidget"}:
        raise ValueError(f"Item owner is not a supported table widget: {class_name}")
    return owner_widget


def _tree_view(owner_widget):
    _import_qt()
    tree_view_type = getattr(_QtWidgets, "QTreeView", None) if _QtWidgets is not None else None
    if tree_view_type is not None and isinstance(owner_widget, tree_view_type):
        return owner_widget

    class_name = _widget_class_name(owner_widget)
    if class_name not in {"QTreeView", "QTreeWidget"}:
        raise ValueError(f"Item owner is not a supported tree widget: {class_name}")
    return owner_widget


def _list_view(owner_widget):
    _import_qt()
    list_view_type = getattr(_QtWidgets, "QListView", None) if _QtWidgets is not None else None
    if list_view_type is not None and isinstance(owner_widget, list_view_type):
        return owner_widget

    class_name = _widget_class_name(owner_widget)
    if class_name not in {"QListView", "QListWidget"}:
        raise ValueError(f"Item owner is not a supported list widget: {class_name}")
    return owner_widget


def _tab_widget(owner_widget):
    _import_qt()
    tab_widget_type = getattr(_QtWidgets, "QTabWidget", None) if _QtWidgets is not None else None
    if tab_widget_type is not None and isinstance(owner_widget, tab_widget_type):
        return owner_widget

    class_name = _widget_class_name(owner_widget)
    if class_name != "QTabWidget":
        raise ValueError(f"Item owner is not a supported tab widget: {class_name}")
    return owner_widget


def _tab_bar(owner_widget):
    _import_qt()
    tab_bar_type = getattr(_QtWidgets, "QTabBar", None) if _QtWidgets is not None else None
    if tab_bar_type is not None and isinstance(owner_widget, tab_bar_type):
        return owner_widget

    class_name = _widget_class_name(owner_widget)
    if class_name != "QTabBar":
        raise ValueError(f"Item owner is not a supported tab bar: {class_name}")
    return owner_widget


def _tab_bar_from_owner(owner_widget):
    try:
        return _tab_bar(owner_widget)
    except ValueError:
        pass

    widget = _tab_widget(owner_widget)
    tab_bar_fn = getattr(widget, "tabBar", None)
    if not callable(tab_bar_fn):
        raise ValueError("Tab widget does not expose tabBar()")
    tab_bar = tab_bar_fn()
    if tab_bar is None:
        raise ValueError("Tab widget tabBar() returned None")
    return tab_bar


def _tab_count(tab_bar) -> int:
    count_fn = getattr(tab_bar, "count", None)
    if not callable(count_fn):
        raise ValueError("Tab owner does not expose count()")
    value = count_fn()
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Tab count must be an int, got {type(value).__name__}")
    return value


def _tab_text(tab_bar, index: int) -> str:
    tab_text_fn = getattr(tab_bar, "tabText", None)
    if not callable(tab_text_fn):
        raise ValueError("Tab owner does not expose tabText()")
    return str(tab_text_fn(index))


def _tab_current_index(owner_widget) -> int:
    current_index_fn = getattr(owner_widget, "currentIndex", None)
    if callable(current_index_fn):
        value = current_index_fn()
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"Tab currentIndex() must return an int, got {type(value).__name__}")
        return value
    tab_bar = _tab_bar_from_owner(owner_widget)
    current_index_fn = getattr(tab_bar, "currentIndex", None)
    if callable(current_index_fn):
        value = current_index_fn()
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"Tab currentIndex() must return an int, got {type(value).__name__}")
        return value
    raise ValueError("Tab owner does not expose currentIndex()")


def _rect_top_left(rect):
    top_left_fn = getattr(rect, "topLeft", None)
    if not callable(top_left_fn):
        raise ValueError("Rect does not expose topLeft()")
    return top_left_fn()


def _rect_center(rect):
    center_fn = getattr(rect, "center", None)
    if not callable(center_fn):
        raise ValueError("Rect does not expose center()")
    return center_fn()


def _rect_dimension(rect, name: str) -> int:
    accessor = getattr(rect, name, None)
    value = accessor() if callable(accessor) else accessor
    return _coerce_runtime_int(value, f"Rect {name}")


def _point_coordinate(point, name: str) -> int:
    accessor = getattr(point, name, None)
    value = accessor() if callable(accessor) else accessor
    return _coerce_runtime_int(value, f"Point {name}")


def _widget_rect(widget):
    rect_fn = getattr(widget, "rect", None)
    if not callable(rect_fn):
        raise ValueError(f"Widget does not expose rect(): {_widget_class_name(widget)}")
    return rect_fn()


def _widget_center_point(widget):
    return _rect_center(_widget_rect(widget))


def _widget_dimension(widget, name: str) -> int:
    accessor = getattr(widget, name, None)
    value = accessor() if callable(accessor) else accessor
    return _coerce_runtime_int(value, f"Widget {name}")


def _widget_map_to_global(widget, point):
    map_to_global = getattr(widget, "mapToGlobal", None)
    if not callable(map_to_global):
        raise ValueError(f"Widget does not expose mapToGlobal(): {_widget_class_name(widget)}")
    return map_to_global(point)


def _widget_map_from_global(widget, point):
    map_from_global = getattr(widget, "mapFromGlobal", None)
    if not callable(map_from_global):
        raise ValueError(f"Widget does not expose mapFromGlobal(): {_widget_class_name(widget)}")
    return map_from_global(point)


def _widget_is_visible(widget) -> bool:
    is_visible = getattr(widget, "isVisible", None)
    if not callable(is_visible):
        raise ValueError(f"Widget does not expose isVisible(): {_widget_class_name(widget)}")
    return bool(is_visible())


def _widget_is_enabled(widget) -> bool:
    is_enabled = getattr(widget, "isEnabled", None)
    if not callable(is_enabled):
        raise ValueError(f"Widget does not expose isEnabled(): {_widget_class_name(widget)}")
    return bool(is_enabled())


def _widget_set_focus(widget, reason=None) -> None:
    set_focus = getattr(widget, "setFocus", None)
    if not callable(set_focus):
        raise ValueError(f"Widget does not expose setFocus(): {_widget_class_name(widget)}")
    if reason is None:
        set_focus()
        return
    try:
        set_focus(reason)
    except Exception:
        set_focus()


def _rect_bounding_box(viewport, rect) -> dict[str, int]:
    top_left = _rect_top_left(rect)
    global_pos = _widget_map_to_global(viewport, top_left)
    return {
        "x": _point_coordinate(global_pos, "x"),
        "y": _point_coordinate(global_pos, "y"),
        "width": _rect_dimension(rect, "width"),
        "height": _rect_dimension(rect, "height"),
    }


def _tab_rect(tab_bar, index: int):
    tab_rect_fn = getattr(tab_bar, "tabRect", None)
    if not callable(tab_rect_fn):
        raise ValueError("Tab owner does not expose tabRect()")
    rect = tab_rect_fn(index)
    if _rect_is_empty(rect):
        raise ValueError(f"Tab {index} does not have a visible rect")
    return rect


def _tab_visible(tab_bar, index: int) -> bool:
    is_tab_visible = getattr(tab_bar, "isTabVisible", None)
    if callable(is_tab_visible):
        return bool(is_tab_visible(index))

    tab_rect_fn = getattr(tab_bar, "tabRect", None)
    if not callable(tab_rect_fn):
        raise ValueError("Tab owner does not expose tabRect()")
    return not _rect_is_empty(tab_rect_fn(index))


def _tab_enabled(tab_bar, index: int) -> bool:
    is_tab_enabled = getattr(tab_bar, "isTabEnabled", None)
    if callable(is_tab_enabled):
        return bool(is_tab_enabled(index))
    return True


def _tab_page_object_name(owner_widget, index: int) -> str:
    try:
        tab_widget = _tab_widget(owner_widget)
    except ValueError:
        return ""

    widget_fn = getattr(tab_widget, "widget", None)
    if not callable(widget_fn):
        return ""
    page = widget_fn(index)
    if page is None:
        return ""
    object_name_fn = getattr(page, "objectName", None)
    if not callable(object_name_fn):
        return ""
    name = object_name_fn()
    return "" if name is None else str(name)


def _table_model(owner_widget):
    view = _table_view(owner_widget)
    model_fn = getattr(view, "model", None)
    if not callable(model_fn):
        raise ValueError(f"Table widget does not expose a model: {_widget_class_name(view)}")
    model = model_fn()
    if model is None:
        raise ValueError("Table widget model is not available")
    return model


def _call_with_optional_role(fn, *args, role=None):
    if role is not None:
        try:
            return fn(*args, role)
        except TypeError:
            pass
    return fn(*args)


def _index_display_text(model, index) -> str:
    role = _qt_display_role()

    data_fn = getattr(index, "data", None)
    if callable(data_fn):
        value = _call_with_optional_role(data_fn, role=role)
        return "" if value is None else str(value)

    model_data = getattr(model, "data", None)
    if callable(model_data):
        value = _call_with_optional_role(model_data, index, role=role)
        return "" if value is None else str(value)

    return ""


def _header_display_text(model, section: int) -> str:
    header_data = getattr(model, "headerData", None)
    if not callable(header_data):
        return ""

    orientation = _qt_horizontal_orientation()
    role = _qt_display_role()
    value = _call_with_optional_role(header_data, section, orientation, role=role)
    return "" if value is None else str(value)


def _selection_model(view):
    selection_model = getattr(view, "selectionModel", None)
    if not callable(selection_model):
        return None
    return selection_model()


def _is_valid_model_index(index) -> bool:
    if index is None:
        return False
    is_valid = getattr(index, "isValid", None)
    if callable(is_valid):
        return bool(is_valid())
    return True


def _resolve_table_column(owner_widget, column_or_name):
    model = _table_model(owner_widget)
    column_count_fn = getattr(model, "columnCount", None)
    if not callable(column_count_fn):
        raise ValueError("Table model does not expose columnCount()")
    column_count = _coerce_runtime_int(column_count_fn(), "Table columnCount()")

    if isinstance(column_or_name, bool):
        raise ValueError("Table column must be an int or str")

    if isinstance(column_or_name, int):
        if column_or_name < 0 or column_or_name >= column_count:
            raise ValueError(f"Table column out of range: {column_or_name}")
        return column_or_name

    if not isinstance(column_or_name, str) or not column_or_name:
        raise ValueError("Table column name must be a non-empty string")

    matches = [column for column in range(column_count) if _header_display_text(model, column) == column_or_name]
    if not matches:
        raise ValueError(f"Table header not found: {column_or_name}")
    if len(matches) > 1:
        raise ValueError(f"Ambiguous table header: {column_or_name}")
    return matches[0]


def _resolve_table_item(owner_widget, descriptor: dict):
    if not isinstance(descriptor, dict):
        raise ValueError("Item descriptor must be an object")
    if descriptor.get("kind") != "table_cell":
        raise ValueError(f"Unsupported item kind: {descriptor.get('kind')}")

    row = descriptor.get("row")
    if isinstance(row, bool) or not isinstance(row, int):
        raise ValueError("Table cell row must be an int")

    has_numeric_column = "column" in descriptor
    has_named_column = "columnName" in descriptor
    if has_numeric_column == has_named_column:
        raise ValueError("Table cell descriptor requires exactly one of column or columnName")

    column_value = descriptor.get("column") if has_numeric_column else descriptor.get("columnName")
    column = _resolve_table_column(owner_widget, column_value)

    model = _table_model(owner_widget)
    row_count_fn = getattr(model, "rowCount", None)
    if not callable(row_count_fn):
        raise ValueError("Table model does not expose rowCount()")
    row_count = _coerce_runtime_int(row_count_fn(), "Table rowCount()")
    if row < 0 or row >= row_count:
        raise ValueError(f"Table row out of range: {row}")

    index_fn = getattr(model, "index", None)
    if not callable(index_fn):
        raise ValueError("Table model does not expose index()")
    index = index_fn(row, column)
    if not _is_valid_model_index(index):
        raise ValueError(f"Table cell index is not valid: row={row}, column={column}")

    return {
        "kind": "table_cell",
        "row": row,
        "column": column,
        "index": index,
    }


def _tree_model(owner_widget):
    view = _tree_view(owner_widget)
    model_fn = getattr(view, "model", None)
    if not callable(model_fn):
        raise ValueError(f"Tree widget does not expose a model: {_widget_class_name(view)}")
    model = model_fn()
    if model is None:
        raise ValueError("Tree widget model is not available")
    return model


def _invalid_model_index():
    model_index_type = getattr(_QtCore, "QModelIndex", None) if _QtCore is not None else None
    if callable(model_index_type):
        try:
            return model_index_type()
        except Exception:
            return None
    return None


def _call_with_optional_parent(fn, parent_index):
    if parent_index is not None:
        try:
            return fn(parent_index)
        except TypeError:
            pass
    return fn()


def _model_row_count(model, parent_index):
    row_count_fn = getattr(model, "rowCount", None)
    if not callable(row_count_fn):
        raise ValueError("Tree model does not expose rowCount()")
    return _coerce_runtime_int(_call_with_optional_parent(row_count_fn, parent_index), "Tree rowCount()")


def _model_index(model, row: int, column: int, parent_index):
    index_fn = getattr(model, "index", None)
    if not callable(index_fn):
        raise ValueError("Tree model does not expose index()")
    if parent_index is not None:
        try:
            return index_fn(row, column, parent_index)
        except TypeError:
            pass
    return index_fn(row, column)


def _tree_index_parent(index):
    parent_fn = getattr(index, "parent", None)
    if not callable(parent_fn):
        return None
    parent = parent_fn()
    if not _is_valid_model_index(parent):
        return None
    return parent


def _tree_index_path(model, index) -> list[str]:
    parts: list[str] = []
    current = index
    while _is_valid_model_index(current):
        parts.append(_index_display_text(model, current))
        current = _tree_index_parent(current)
    parts.reverse()
    return parts


def _tree_index_is_expanded(view, index) -> bool:
    is_expanded = getattr(view, "isExpanded", None)
    if callable(is_expanded):
        return bool(is_expanded(index))
    return False


def _tree_index_hidden(view, index) -> bool:
    is_index_hidden = getattr(view, "isIndexHidden", None)
    if callable(is_index_hidden):
        return bool(is_index_hidden(index))

    is_row_hidden = getattr(view, "isRowHidden", None)
    if not callable(is_row_hidden):
        return False

    row_fn = getattr(index, "row", None)
    row = row_fn() if callable(row_fn) else None
    if row is None:
        return False
    row_value = _coerce_runtime_int(row, "Tree row()")

    parent_index = _tree_index_parent(index)
    if parent_index is not None:
        try:
            return bool(is_row_hidden(row_value, parent_index))
        except TypeError:
            pass
    try:
        return bool(is_row_hidden(row_value))
    except TypeError:
        return False


def _tree_index_hidden_by_collapsed_ancestor(view, index) -> bool:
    current = _tree_index_parent(index)
    while current is not None:
        if not _tree_index_is_expanded(view, current):
            return True
        current = _tree_index_parent(current)
    return False


def _resolve_tree_item(owner_widget, descriptor: dict):
    if not isinstance(descriptor, dict):
        raise ValueError("Item descriptor must be an object")
    if descriptor.get("kind") != "tree_node":
        raise ValueError(f"Unsupported item kind: {descriptor.get('kind')}")

    path = descriptor.get("path")
    if not isinstance(path, list) or not path:
        raise ValueError("Tree node descriptor requires a non-empty path list")

    model = _tree_model(owner_widget)
    parent_index = _invalid_model_index()
    current_index = None
    for depth, segment in enumerate(path):
        if isinstance(segment, bool) or not isinstance(segment, (int, str)):
            raise ValueError("Tree path segments must be int or str")

        row_count = _model_row_count(model, parent_index)
        if isinstance(segment, int):
            if segment < 0 or segment >= row_count:
                raise ValueError(f"Tree path index out of range at depth {depth}: {segment}")
            current_index = _model_index(model, segment, 0, parent_index)
        else:
            matches = []
            for row in range(row_count):
                candidate = _model_index(model, row, 0, parent_index)
                if _index_display_text(model, candidate) == segment:
                    matches.append(candidate)
            if not matches:
                raise ValueError(f"Tree path segment not found: {segment}")
            if len(matches) > 1:
                raise ValueError(f"Ambiguous tree path segment: {segment}")
            current_index = matches[0]

        if not _is_valid_model_index(current_index):
            raise ValueError(f"Tree node index is not valid at depth {depth}: {segment}")
        parent_index = current_index

    return {
        "kind": "tree_node",
        "path": list(path),
        "index": current_index,
    }


def _list_model(owner_widget):
    view = _list_view(owner_widget)
    model_fn = getattr(view, "model", None)
    if not callable(model_fn):
        raise ValueError(f"List widget does not expose a model: {_widget_class_name(view)}")
    model = model_fn()
    if model is None:
        raise ValueError("List widget model is not available")
    return model


def _resolve_list_item(owner_widget, descriptor: dict):
    if not isinstance(descriptor, dict):
        raise ValueError("Item descriptor must be an object")
    if descriptor.get("kind") != "list_item":
        raise ValueError(f"Unsupported item kind: {descriptor.get('kind')}")

    has_row = "row" in descriptor
    has_text = "text" in descriptor
    if has_row == has_text:
        raise ValueError("List item descriptor requires exactly one of row or text")

    model = _list_model(owner_widget)
    row_count = _model_row_count(model, None)

    if has_row:
        row = descriptor.get("row")
        if isinstance(row, bool) or not isinstance(row, int):
            raise ValueError("List item row must be an int")
        if row < 0 or row >= row_count:
            raise ValueError(f"List item row out of range: {row}")
        index = _model_index(model, row, 0, None)
        if not _is_valid_model_index(index):
            raise ValueError(f"List item index is not valid: row={row}")
        return {
            "kind": "list_item",
            "row": row,
            "index": index,
        }

    text = descriptor.get("text")
    if not isinstance(text, str) or not text:
        raise ValueError("List item text must be a non-empty string")

    matches = []
    for row in range(row_count):
        candidate = _model_index(model, row, 0, None)
        if _index_display_text(model, candidate) == text:
            matches.append((row, candidate))

    if not matches:
        raise ValueError(f"List item text not found: {text}")
    if len(matches) > 1:
        raise ValueError(f"Ambiguous list item text: {text}")

    row, index = matches[0]
    return {
        "kind": "list_item",
        "row": row,
        "index": index,
    }


def _resolve_tab_item(owner_widget, descriptor: dict):
    if not isinstance(descriptor, dict):
        raise ValueError("Item descriptor must be an object")
    if descriptor.get("kind") != "tab_item":
        raise ValueError(f"Unsupported item kind: {descriptor.get('kind')}")

    has_index = "index" in descriptor
    has_label = "label" in descriptor
    if has_index == has_label:
        raise ValueError("Tab item descriptor requires exactly one of index or label")

    tab_bar = _tab_bar_from_owner(owner_widget)
    count = _tab_count(tab_bar)

    if has_index:
        index = descriptor.get("index")
        if isinstance(index, bool) or not isinstance(index, int):
            raise ValueError("Tab item index must be an int")
        if index < 0 or index >= count:
            raise ValueError(f"Tab index out of range: {index}")
        return {
            "kind": "tab_item",
            "index": index,
            "tabBar": tab_bar,
        }

    label = descriptor.get("label")
    if not isinstance(label, str) or not label:
        raise ValueError("Tab item label must be a non-empty string")

    matches = [index for index in range(count) if _tab_text(tab_bar, index) == label]
    if not matches:
        raise ValueError(f"Tab label not found: {label}")
    if len(matches) > 1:
        raise ValueError(f"Ambiguous tab label: {label}")

    return {
        "kind": "tab_item",
        "index": matches[0],
        "tabBar": tab_bar,
    }


def _resolve_item_target(owner_widget, descriptor: dict):
    if not isinstance(descriptor, dict):
        raise ValueError("Item descriptor must be an object")

    kind = descriptor.get("kind")
    if kind == "table_cell":
        return _resolve_table_item(owner_widget, descriptor)
    if kind == "list_item":
        return _resolve_list_item(owner_widget, descriptor)
    if kind == "tree_node":
        return _resolve_tree_item(owner_widget, descriptor)
    if kind == "tab_item":
        return _resolve_tab_item(owner_widget, descriptor)
    raise ValueError(f"Unsupported item kind: {kind}")


def _tab_item_text(owner_widget, resolved_target) -> str:
    tab_bar = resolved_target.get("tabBar") or _tab_bar_from_owner(owner_widget)
    return _tab_text(tab_bar, int(resolved_target["index"]))


def _tab_item_selected(owner_widget, resolved_target) -> bool:
    return int(resolved_target["index"]) == _tab_current_index(owner_widget)


def _tab_item_properties(owner_widget, resolved_target) -> dict[str, Any]:
    tab_bar = resolved_target.get("tabBar") or _tab_bar_from_owner(owner_widget)
    index = int(resolved_target["index"])
    props = {
        "kind": "tab_item",
        "index": index,
        "text": _tab_text(tab_bar, index),
        "visible": _tab_visible(tab_bar, index),
        "selected": _tab_item_selected(owner_widget, resolved_target),
        "enabled": _tab_enabled(tab_bar, index),
    }
    page_object_name = _tab_page_object_name(owner_widget, index)
    if page_object_name:
        props["pageObjectName"] = page_object_name
    return props


def _tab_item_bounding_box(owner_widget, resolved_target) -> dict[str, int]:
    tab_bar = resolved_target.get("tabBar") or _tab_bar_from_owner(owner_widget)
    rect = _tab_rect(tab_bar, int(resolved_target["index"]))
    map_to_global = getattr(tab_bar, "mapToGlobal", None)
    if not callable(map_to_global):
        raise ValueError("Tab owner does not expose mapToGlobal()")
    global_pos = map_to_global(_rect_top_left(rect))
    return {
        "x": _point_coordinate(global_pos, "x"),
        "y": _point_coordinate(global_pos, "y"),
        "width": _rect_dimension(rect, "width"),
        "height": _rect_dimension(rect, "height"),
    }


def _rect_is_empty(rect) -> bool:
    if rect is None:
        return True
    is_empty = getattr(rect, "isEmpty", None)
    if callable(is_empty):
        return bool(is_empty())
    width_value = _rect_dimension(rect, "width")
    height_value = _rect_dimension(rect, "height")
    return width_value <= 0 or height_value <= 0


def _table_index_visible(owner_widget, resolved_target) -> bool:
    view = _table_view(owner_widget)
    column = int(resolved_target["column"])

    is_column_hidden = getattr(view, "isColumnHidden", None)
    if callable(is_column_hidden) and is_column_hidden(column):
        return False

    rect_fn = getattr(view, "visualRect", None)
    if not callable(rect_fn):
        raise ValueError("Table widget does not expose visualRect()")

    rect = rect_fn(resolved_target["index"])
    return not _rect_is_empty(rect)


def _table_index_rect(owner_widget, resolved_target):
    view = _table_view(owner_widget)
    column = int(resolved_target["column"])

    is_column_hidden = getattr(view, "isColumnHidden", None)
    if callable(is_column_hidden) and is_column_hidden(column):
        raise ValueError(f"Table cell is not visible because column {column} is hidden")

    scroll_to = getattr(view, "scrollTo", None)
    if callable(scroll_to):
        hint = _qt_ensure_visible_hint()
        if hint is None:
            scroll_to(resolved_target["index"])
        else:
            scroll_to(resolved_target["index"], hint)

    rect_fn = getattr(view, "visualRect", None)
    if not callable(rect_fn):
        raise ValueError("Table widget does not expose visualRect()")

    rect = rect_fn(resolved_target["index"])
    if _rect_is_empty(rect):
        raise ValueError("Table cell does not have a usable visible rectangle")
    return rect


def _table_index_text(owner_widget, resolved_target) -> str:
    model = _table_model(owner_widget)
    return _index_display_text(model, resolved_target["index"])


def _table_index_properties(owner_widget, resolved_target) -> dict[str, Any]:
    view = _table_view(owner_widget)
    payload = {
        "kind": "table_cell",
        "row": int(resolved_target["row"]),
        "column": int(resolved_target["column"]),
        "text": _table_index_text(owner_widget, resolved_target),
        "selected": False,
    }

    selection_model = _selection_model(view)
    is_selected = getattr(selection_model, "isSelected", None) if selection_model is not None else None
    if callable(is_selected):
        payload["selected"] = bool(is_selected(resolved_target["index"]))
    return payload


def _table_index_bounding_box(owner_widget, resolved_target) -> dict[str, int]:
    view = _table_view(owner_widget)
    viewport = _primary_event_target(view)
    rect = _table_index_rect(view, resolved_target)
    return _rect_bounding_box(viewport, rect)


def _tree_index_visible(owner_widget, resolved_target) -> bool:
    view = _tree_view(owner_widget)
    index = resolved_target["index"]

    is_column_hidden = getattr(view, "isColumnHidden", None)
    if callable(is_column_hidden) and is_column_hidden(0):
        return False
    if _tree_index_hidden_by_collapsed_ancestor(view, index):
        return False
    if _tree_index_hidden(view, index):
        return False

    rect_fn = getattr(view, "visualRect", None)
    if not callable(rect_fn):
        raise ValueError("Tree widget does not expose visualRect()")

    rect = rect_fn(index)
    return not _rect_is_empty(rect)


def _tree_index_rect(owner_widget, resolved_target):
    view = _tree_view(owner_widget)
    index = resolved_target["index"]

    is_column_hidden = getattr(view, "isColumnHidden", None)
    if callable(is_column_hidden) and is_column_hidden(0):
        raise ValueError("Tree node is not visible because column 0 is hidden")
    if _tree_index_hidden_by_collapsed_ancestor(view, index):
        raise ValueError("Tree node is not visible because an ancestor is collapsed")
    if _tree_index_hidden(view, index):
        raise ValueError("Tree node is hidden in the current view")

    scroll_to = getattr(view, "scrollTo", None)
    if callable(scroll_to):
        hint = _qt_ensure_visible_hint()
        if hint is None:
            scroll_to(index)
        else:
            scroll_to(index, hint)

    rect_fn = getattr(view, "visualRect", None)
    if not callable(rect_fn):
        raise ValueError("Tree widget does not expose visualRect()")

    rect = rect_fn(index)
    if _rect_is_empty(rect):
        raise ValueError("Tree node does not have a usable visible rectangle")
    return rect


def _tree_index_text(owner_widget, resolved_target) -> str:
    model = _tree_model(owner_widget)
    return _index_display_text(model, resolved_target["index"])


def _tree_index_properties(owner_widget, resolved_target) -> dict[str, Any]:
    view = _tree_view(owner_widget)
    model = _tree_model(owner_widget)
    payload = {
        "kind": "tree_node",
        "text": _tree_index_text(owner_widget, resolved_target),
        "path": _tree_index_path(model, resolved_target["index"]),
        "expanded": _tree_index_is_expanded(view, resolved_target["index"]),
        "selected": False,
    }

    selection_model = _selection_model(view)
    is_selected = getattr(selection_model, "isSelected", None) if selection_model is not None else None
    if callable(is_selected):
        payload["selected"] = bool(is_selected(resolved_target["index"]))
    return payload


def _tree_index_bounding_box(owner_widget, resolved_target) -> dict[str, int]:
    view = _tree_view(owner_widget)
    viewport = _primary_event_target(view)
    rect = _tree_index_rect(view, resolved_target)
    return _rect_bounding_box(viewport, rect)


def _list_index_visible(owner_widget, resolved_target) -> bool:
    view = _list_view(owner_widget)
    rect_fn = getattr(view, "visualRect", None)
    if not callable(rect_fn):
        raise ValueError("List widget does not expose visualRect()")

    rect = rect_fn(resolved_target["index"])
    return not _rect_is_empty(rect)


def _list_index_rect(owner_widget, resolved_target):
    view = _list_view(owner_widget)
    scroll_to = getattr(view, "scrollTo", None)
    if callable(scroll_to):
        hint = _qt_ensure_visible_hint()
        if hint is None:
            scroll_to(resolved_target["index"])
        else:
            scroll_to(resolved_target["index"], hint)

    rect_fn = getattr(view, "visualRect", None)
    if not callable(rect_fn):
        raise ValueError("List widget does not expose visualRect()")

    rect = rect_fn(resolved_target["index"])
    if _rect_is_empty(rect):
        raise ValueError("List item does not have a usable visible rectangle")
    return rect


def _list_index_text(owner_widget, resolved_target) -> str:
    model = _list_model(owner_widget)
    return _index_display_text(model, resolved_target["index"])


def _list_index_properties(owner_widget, resolved_target) -> dict[str, Any]:
    view = _list_view(owner_widget)
    payload = {
        "kind": "list_item",
        "row": int(resolved_target["row"]),
        "text": _list_index_text(owner_widget, resolved_target),
        "selected": False,
    }

    selection_model = _selection_model(view)
    is_selected = getattr(selection_model, "isSelected", None) if selection_model is not None else None
    if callable(is_selected):
        payload["selected"] = bool(is_selected(resolved_target["index"]))
    return payload


def _list_index_bounding_box(owner_widget, resolved_target) -> dict[str, int]:
    view = _list_view(owner_widget)
    viewport = _primary_event_target(view)
    rect = _list_index_rect(owner_widget, resolved_target)
    return _rect_bounding_box(viewport, rect)


def _item_text(owner_widget, resolved_target) -> str:
    if resolved_target["kind"] == "table_cell":
        return _table_index_text(owner_widget, resolved_target)
    if resolved_target["kind"] == "list_item":
        return _list_index_text(owner_widget, resolved_target)
    if resolved_target["kind"] == "tree_node":
        return _tree_index_text(owner_widget, resolved_target)
    if resolved_target["kind"] == "tab_item":
        return _tab_item_text(owner_widget, resolved_target)
    raise ValueError(f"Unsupported item kind: {resolved_target['kind']}")


def _item_properties(owner_widget, resolved_target) -> dict[str, Any]:
    if resolved_target["kind"] == "table_cell":
        return _table_index_properties(owner_widget, resolved_target)
    if resolved_target["kind"] == "list_item":
        return _list_index_properties(owner_widget, resolved_target)
    if resolved_target["kind"] == "tree_node":
        return _tree_index_properties(owner_widget, resolved_target)
    if resolved_target["kind"] == "tab_item":
        return _tab_item_properties(owner_widget, resolved_target)
    raise ValueError(f"Unsupported item kind: {resolved_target['kind']}")


def _item_visible(owner_widget, resolved_target) -> bool:
    if resolved_target["kind"] == "table_cell":
        return _table_index_visible(owner_widget, resolved_target)
    if resolved_target["kind"] == "list_item":
        return _list_index_visible(owner_widget, resolved_target)
    if resolved_target["kind"] == "tree_node":
        return _tree_index_visible(owner_widget, resolved_target)
    if resolved_target["kind"] == "tab_item":
        tab_bar = resolved_target.get("tabBar") or _tab_bar_from_owner(owner_widget)
        return _tab_visible(tab_bar, int(resolved_target["index"]))
    raise ValueError(f"Unsupported item kind: {resolved_target['kind']}")


def _item_selected(owner_widget, resolved_target) -> bool:
    selected = _item_properties(owner_widget, resolved_target).get("selected")
    return bool(selected)


def _item_bounding_box(owner_widget, resolved_target) -> dict[str, int]:
    if resolved_target["kind"] == "table_cell":
        return _table_index_bounding_box(owner_widget, resolved_target)
    if resolved_target["kind"] == "list_item":
        return _list_index_bounding_box(owner_widget, resolved_target)
    if resolved_target["kind"] == "tree_node":
        return _tree_index_bounding_box(owner_widget, resolved_target)
    if resolved_target["kind"] == "tab_item":
        return _tab_item_bounding_box(owner_widget, resolved_target)
    raise ValueError(f"Unsupported item kind: {resolved_target['kind']}")


def _click_widget_at(widget, pos, *, double: bool = False):
    _import_qt()
    QTest = _QtTest
    qt_core = _qt_core_module()
    Qt = qt_core.Qt

    if not _widget_is_visible(widget):
        raise ValueError(f"Cannot click widget of type {_widget_class_name(widget)}: event target is not visible")
    if not _widget_is_enabled(widget):
        raise ValueError(f"Cannot click widget of type {_widget_class_name(widget)}: event target is disabled")

    if QTest and hasattr(QTest, "QTest"):
        QTest = QTest.QTest

    try:
        widget.setFocus(Qt.MouseFocusReason)
    except Exception:
        widget.setFocus()
    _process_events()

    _update_visual_feedback(widget, pos, double=double)

    if QTest and hasattr(QTest, "mouseClick"):
        try:
            if double:
                QTest.mouseDClick(widget, Qt.LeftButton, Qt.NoModifier, pos)
            else:
                QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, pos)
        except TypeError:
            if double:
                QTest.mouseDClick(widget, Qt.LeftButton)
            else:
                QTest.mouseClick(widget, Qt.LeftButton)
    else:
        _post_mouse_event(widget, pos, double=double)

    _process_events()


def _coerce_non_negative_int(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{name} must be >= 0")
    return value


def _resolve_pointer_action_target(params: dict):
    qt_core = _qt_core_module()

    if ("x" in params) != ("y" in params):
        raise ValueError("Coordinate pointer actions require x and y together")

    x = _coerce_non_negative_int(params.get("x"), "x")
    y = _coerce_non_negative_int(params.get("y"), "y")

    window = _resolve_pointer_action_window(params)
    width = _widget_dimension(window, "width")
    height = _widget_dimension(window, "height")
    if x >= width or y >= height:
        raise ValueError("Coordinate pointer action is outside the target window bounds")

    local_pos = qt_core.QPoint(x, y)
    if not _point_within_widget_mask(window, local_pos):
        raise ValueError("Coordinate pointer action resolves to a masked-out point")

    global_pos = _widget_map_to_global(window, local_pos)
    hit = _topmost_hit_at_point(window, local_pos)
    if hit is None:
        raise ValueError("Coordinate pointer action does not resolve to an event target")
    if not _is_same_or_descendant_widget(hit, window):
        raise ValueError(f"Coordinate pointer action is covered by {_widget_class_name(hit)}")
    if not _widget_is_visible(hit):
        raise ValueError(f"Cannot click widget of type {_widget_class_name(hit)}: event target is not visible")
    if not _widget_is_enabled(hit):
        raise ValueError(f"Cannot click widget of type {_widget_class_name(hit)}: event target is disabled")
    return hit, _widget_map_from_global(hit, global_pos)


def _click_table_index(owner_widget, resolved_target, *, double: bool = False):
    view = _table_view(owner_widget)
    viewport = _primary_event_target(view)
    rect = _table_index_rect(view, resolved_target)
    local_pos = _rect_center(rect)
    _click_widget_at(viewport, local_pos, double=double)


def _hover_table_index(owner_widget, resolved_target):
    view = _table_view(owner_widget)
    viewport = _primary_event_target(view)
    rect = _table_index_rect(view, resolved_target)
    local_pos = _rect_center(rect)
    _move_visual_cursor(viewport, local_pos)
    _hover_widget(viewport, local_pos)


def _click_tree_index(owner_widget, resolved_target, *, double: bool = False):
    view = _tree_view(owner_widget)
    viewport = _primary_event_target(view)
    rect = _tree_index_rect(view, resolved_target)
    local_pos = _rect_center(rect)
    _click_widget_at(viewport, local_pos, double=double)


def _hover_tree_index(owner_widget, resolved_target):
    view = _tree_view(owner_widget)
    viewport = _primary_event_target(view)
    rect = _tree_index_rect(view, resolved_target)
    local_pos = _rect_center(rect)
    _move_visual_cursor(viewport, local_pos)
    _hover_widget(viewport, local_pos)


def _click_list_index(owner_widget, resolved_target, *, double: bool = False):
    view = _list_view(owner_widget)
    viewport = _primary_event_target(view)
    rect = _list_index_rect(owner_widget, resolved_target)
    local_pos = _rect_center(rect)
    _click_widget_at(viewport, local_pos, double=double)


def _hover_list_index(owner_widget, resolved_target):
    view = _list_view(owner_widget)
    viewport = _primary_event_target(view)
    rect = _list_index_rect(owner_widget, resolved_target)
    local_pos = _rect_center(rect)
    _move_visual_cursor(viewport, local_pos)
    _hover_widget(viewport, local_pos)


def _click_tab_item(owner_widget, resolved_target, *, double: bool = False):
    tab_bar = resolved_target.get("tabBar") or _tab_bar_from_owner(owner_widget)
    rect = _tab_rect(tab_bar, int(resolved_target["index"]))
    _click_widget_at(tab_bar, _rect_center(rect), double=double)


def _hover_tab_item(owner_widget, resolved_target):
    tab_bar = resolved_target.get("tabBar") or _tab_bar_from_owner(owner_widget)
    rect = _tab_rect(tab_bar, int(resolved_target["index"]))
    local_pos = _rect_center(rect)
    _move_visual_cursor(tab_bar, local_pos)
    _hover_widget(tab_bar, local_pos)


def _select_tab_item(owner_widget, resolved_target):
    index = int(resolved_target["index"])
    set_current_index = getattr(owner_widget, "setCurrentIndex", None)
    if callable(set_current_index):
        set_current_index(index)
        _process_events()
        return

    tab_bar = resolved_target.get("tabBar") or _tab_bar_from_owner(owner_widget)
    set_current_index = getattr(tab_bar, "setCurrentIndex", None)
    if callable(set_current_index):
        set_current_index(index)
        _process_events()
        return

    raise ValueError("Tab owner does not expose setCurrentIndex()")


def _click_item(owner_widget, resolved_target, *, double: bool = False):
    if resolved_target["kind"] == "table_cell":
        _click_table_index(owner_widget, resolved_target, double=double)
        return
    if resolved_target["kind"] == "list_item":
        _click_list_index(owner_widget, resolved_target, double=double)
        return
    if resolved_target["kind"] == "tree_node":
        _click_tree_index(owner_widget, resolved_target, double=double)
        return
    if resolved_target["kind"] == "tab_item":
        _click_tab_item(owner_widget, resolved_target, double=double)
        return
    raise ValueError(f"Unsupported item kind: {resolved_target['kind']}")


def _hover_item(owner_widget, resolved_target):
    if resolved_target["kind"] == "table_cell":
        _hover_table_index(owner_widget, resolved_target)
        return
    if resolved_target["kind"] == "list_item":
        _hover_list_index(owner_widget, resolved_target)
        return
    if resolved_target["kind"] == "tree_node":
        _hover_tree_index(owner_widget, resolved_target)
        return
    if resolved_target["kind"] == "tab_item":
        _hover_tab_item(owner_widget, resolved_target)
        return
    raise ValueError(f"Unsupported item kind: {resolved_target['kind']}")


def _expand_tree_index(owner_widget, resolved_target):
    view = _tree_view(owner_widget)
    index = resolved_target["index"]
    expand_fn = getattr(view, "expand", None)
    if callable(expand_fn):
        expand_fn(index)
        _process_events()
        return

    set_expanded = getattr(view, "setExpanded", None)
    if callable(set_expanded):
        set_expanded(index, True)
        _process_events()
        return

    raise ValueError("Tree widget does not support expand()")


def _collapse_tree_index(owner_widget, resolved_target):
    view = _tree_view(owner_widget)
    index = resolved_target["index"]
    collapse_fn = getattr(view, "collapse", None)
    if callable(collapse_fn):
        collapse_fn(index)
        _process_events()
        return

    set_expanded = getattr(view, "setExpanded", None)
    if callable(set_expanded):
        set_expanded(index, False)
        _process_events()
        return

    raise ValueError("Tree widget does not support collapse()")


def _table_item_inspection(owner_widget, *, max_rows: int, max_items: int, include_hidden: bool) -> dict[str, Any]:
    model = _table_model(owner_widget)
    row_count = _model_row_count(model, None)
    column_count_fn = getattr(model, "columnCount", None)
    if not callable(column_count_fn):
        raise ValueError("Table model does not expose columnCount()")
    column_count = _coerce_runtime_int(column_count_fn(), "Table columnCount()")
    rows_inspected = min(row_count, max_rows)
    view = _table_view(owner_widget)

    columns = []
    is_column_hidden = getattr(view, "isColumnHidden", None)
    for column in range(column_count):
        hidden = bool(is_column_hidden(column)) if callable(is_column_hidden) else False
        columns.append({
            "column": column,
            "header": _header_display_text(model, column),
            "hidden": hidden,
        })

    items = []
    truncated = row_count > rows_inspected
    for row in range(rows_inspected):
        for column in range(column_count):
            index = _model_index(model, row, column, None)
            if not _is_valid_model_index(index):
                continue
            target = {"kind": "table_cell", "row": row, "column": column, "index": index}
            visible = _table_index_visible(owner_widget, target)
            if not include_hidden and not visible:
                continue
            properties = _table_index_properties(owner_widget, target)
            items.append({
                "item": {"kind": "table_cell", "row": row, "column": column},
                "row": row,
                "column": column,
                "columnHeader": _header_display_text(model, column),
                "text": properties.get("text", ""),
                "visible": visible,
                "selected": bool(properties.get("selected", False)),
            })
            if len(items) >= max_items:
                truncated = True
                return {
                    "kind": "table",
                    "rowCount": row_count,
                    "columnCount": column_count,
                    "rowsInspected": rows_inspected,
                    "columns": columns,
                    "items": items,
                    "truncated": truncated,
                }

    return {
        "kind": "table",
        "rowCount": row_count,
        "columnCount": column_count,
        "rowsInspected": rows_inspected,
        "columns": columns,
        "items": items,
        "truncated": truncated,
    }


def _list_item_inspection(owner_widget, *, max_rows: int, max_items: int, include_hidden: bool) -> dict[str, Any]:
    model = _list_model(owner_widget)
    row_count = _model_row_count(model, None)
    rows_inspected = min(row_count, max_rows)
    items = []
    truncated = row_count > rows_inspected

    for row in range(rows_inspected):
        index = _model_index(model, row, 0, None)
        if not _is_valid_model_index(index):
            continue
        target = {"kind": "list_item", "row": row, "index": index}
        visible = _list_index_visible(owner_widget, target)
        if not include_hidden and not visible:
            continue
        properties = _list_index_properties(owner_widget, target)
        items.append({
            "item": {"kind": "list_item", "row": row},
            "row": row,
            "text": properties.get("text", ""),
            "visible": visible,
            "selected": bool(properties.get("selected", False)),
        })
        if len(items) >= max_items:
            truncated = True
            break

    return {
        "kind": "list",
        "rowCount": row_count,
        "rowsInspected": rows_inspected,
        "items": items,
        "truncated": truncated,
    }


def _tree_item_inspection(
    owner_widget,
    *,
    max_depth: int,
    max_items: int,
    include_hidden: bool,
) -> dict[str, Any]:
    view = _tree_view(owner_widget)
    model = _tree_model(owner_widget)
    items: list[dict[str, Any]] = []
    truncated = False

    def visit(parent_index, path: list[int], depth: int) -> None:
        nonlocal truncated
        if truncated:
            return

        row_count = _model_row_count(model, parent_index)
        for row in range(row_count):
            index = _model_index(model, row, 0, parent_index)
            if not _is_valid_model_index(index):
                continue

            item_path = [*path, row]
            target = {"kind": "tree_node", "path": item_path, "index": index}
            visible = _tree_index_visible(owner_widget, target)
            if include_hidden or visible:
                properties = _tree_index_properties(owner_widget, target)
                child_count = _model_row_count(model, index)
                items.append({
                    "item": {"kind": "tree_node", "path": item_path},
                    "depth": depth,
                    "text": properties.get("text", ""),
                    "labelPath": list(properties.get("path") or []),
                    "visible": visible,
                    "selected": bool(properties.get("selected", False)),
                    "expanded": bool(properties.get("expanded", False)),
                    "hasChildren": child_count > 0,
                })
                if len(items) >= max_items:
                    truncated = True
                    return

            child_count = _model_row_count(model, index)
            if child_count <= 0:
                continue
            if depth >= max_depth:
                if include_hidden or _tree_index_is_expanded(view, index):
                    truncated = True
                continue
            if include_hidden or _tree_index_is_expanded(view, index):
                visit(index, item_path, depth + 1)
                if truncated:
                    return

    visit(_invalid_model_index(), [], 0)
    return {
        "kind": "tree",
        "maxDepth": max_depth,
        "items": items,
        "truncated": truncated,
    }


def _inspect_item_view(
    owner_widget,
    *,
    max_rows: int,
    max_depth: int,
    max_items: int,
    include_hidden: bool,
) -> dict[str, Any]:
    max_rows = max(0, int(max_rows))
    max_depth = max(0, int(max_depth))
    max_items = max(0, int(max_items))

    try:
        _table_view(owner_widget)
        return _table_item_inspection(owner_widget, max_rows=max_rows, max_items=max_items, include_hidden=include_hidden)
    except ValueError:
        pass

    try:
        _list_view(owner_widget)
        return _list_item_inspection(owner_widget, max_rows=max_rows, max_items=max_items, include_hidden=include_hidden)
    except ValueError:
        pass

    try:
        _tree_view(owner_widget)
        return _tree_item_inspection(owner_widget, max_depth=max_depth, max_items=max_items, include_hidden=include_hidden)
    except ValueError:
        pass

    try:
        return _tab_item_inspection(owner_widget, max_items=max_items, include_hidden=include_hidden)
    except ValueError:
        pass

    class_name = _widget_class_name(owner_widget)
    raise ValueError(f"Widget does not expose supported item-view descendants: {class_name}")


def _tab_item_inspection(owner_widget, *, max_items: int, include_hidden: bool) -> dict[str, Any]:
    tab_bar = _tab_bar_from_owner(owner_widget)
    indices = [index for index in range(_tab_count(tab_bar)) if include_hidden or _tab_visible(tab_bar, index)]
    truncated = len(indices) > max_items
    items = []
    for index in indices[:max_items]:
        entry = {
            "item": {"kind": "tab_item", "index": index},
            "index": index,
            "text": _tab_text(tab_bar, index),
            "visible": _tab_visible(tab_bar, index),
            "selected": index == _tab_current_index(owner_widget),
            "enabled": _tab_enabled(tab_bar, index),
        }
        page_object_name = _tab_page_object_name(owner_widget, index)
        if page_object_name:
            entry["pageObjectName"] = page_object_name
        items.append(entry)

    return {
        "kind": "tab",
        "maxItems": max_items,
        "items": items,
        "truncated": truncated,
    }


def _key_to_qt(key_str: str):
    """Convert a Playwright-style key name to Qt key enum."""
    Qt = _qt_core_module().Qt
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
    qt_core = _qt_core_module()
    Qt = qt_core.Qt

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

    if method == METHOD_FIND_WIDGETS:
        return _find_widgets_payload(params)

    if method == METHOD_WIDGET_TREE:
        wid = params.get("wid")
        topmost_only = bool(params.get("topmost_only", False))
        if wid is not None:
            root = _registry.get(wid)
            if root is None:
                raise ValueError(f"Widget id={wid} not found or was garbage collected")
            roots = [root]
        else:
            roots = _get_interactable_top_level_widgets()
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

    if method == METHOD_ITEM_TEXT:
        owner = _resolve_item_owner(params)
        target = _resolve_item_target(owner, params.get("item") or {})
        return _item_text(owner, target)

    if method == METHOD_ITEM_PROPERTIES:
        owner = _resolve_item_owner(params)
        target = _resolve_item_target(owner, params.get("item") or {})
        return _item_properties(owner, target)

    if method == METHOD_ITEM_VISIBLE:
        owner = _resolve_item_owner(params)
        target = _resolve_item_target(owner, params.get("item") or {})
        return _item_visible(owner, target)

    if method == METHOD_ITEM_SELECTED:
        owner = _resolve_item_owner(params)
        target = _resolve_item_target(owner, params.get("item") or {})
        return _item_selected(owner, target)

    if method == METHOD_ITEM_BOUNDING_BOX:
        owner = _resolve_item_owner(params)
        target = _resolve_item_target(owner, params.get("item") or {})
        return _item_bounding_box(owner, target)

    if method == METHOD_ITEM_VIEW_INSPECT:
        owner = _resolve_item_owner(params)
        return _inspect_item_view(
            owner,
            max_rows=int(params.get("max_rows", 20)),
            max_depth=int(params.get("max_depth", 4)),
            max_items=int(params.get("max_items", 200)),
            include_hidden=bool(params.get("include_hidden", False)),
        )

    # -- Actions -------------------------------------------------------------
    if method == METHOD_CLICK:
        if "wid" in params or "selector" in params:
            w = _resolve_one(params)
            _click_widget(w, double=False)
        else:
            target, local_pos = _resolve_pointer_action_target(params)
            _click_widget_at(target, local_pos, double=False)
        return True

    if method == METHOD_DBLCLICK:
        if "wid" in params or "selector" in params:
            w = _resolve_one(params)
            _click_widget(w, double=True)
        else:
            target, local_pos = _resolve_pointer_action_target(params)
            _click_widget_at(target, local_pos, double=True)
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
        if "wid" in params or "selector" in params:
            w = _resolve_one(params)
            target = _primary_event_target(w)
            local_pos = _widget_center_point(target)
        else:
            target, local_pos = _resolve_pointer_action_target(params)
        _move_visual_cursor(target, local_pos)
        _hover_widget(target, local_pos)
        return True

    if method == METHOD_ITEM_CLICK:
        owner = _resolve_item_owner(params)
        target = _resolve_item_target(owner, params.get("item") or {})
        _click_item(owner, target, double=False)
        return True

    if method == METHOD_ITEM_DBLCLICK:
        owner = _resolve_item_owner(params)
        target = _resolve_item_target(owner, params.get("item") or {})
        _click_item(owner, target, double=True)
        return True

    if method == METHOD_ITEM_HOVER:
        owner = _resolve_item_owner(params)
        target = _resolve_item_target(owner, params.get("item") or {})
        _hover_item(owner, target)
        return True

    if method == METHOD_ITEM_SELECT:
        owner = _resolve_item_owner(params)
        target = _resolve_item_target(owner, params.get("item") or {})
        _select_tab_item(owner, target)
        return True

    if method == METHOD_ITEM_EXPAND:
        owner = _resolve_item_owner(params)
        target = _resolve_item_target(owner, params.get("item") or {})
        if target["kind"] != "tree_node":
            raise ValueError("expand() is only supported for tree nodes")
        _expand_tree_index(owner, target)
        return True

    if method == METHOD_ITEM_COLLAPSE:
        owner = _resolve_item_owner(params)
        target = _resolve_item_target(owner, params.get("item") or {})
        if target["kind"] != "tree_node":
            raise ValueError("collapse() is only supported for tree nodes")
        _collapse_tree_index(owner, target)
        return True

    if method == METHOD_FOCUS:
        w = _resolve_one(params)
        target = _primary_event_target(w)
        _move_visual_cursor(target, _widget_center_point(target))
        _widget_set_focus(w)
        _process_events()
        return True

    if method == METHOD_SCROLL:
        w = _resolve_one(params)
        target = _primary_event_target(w)
        _move_visual_cursor(target, _widget_center_point(target), pulse_count=1)
        _scroll_widget(w, params.get("delta_x", 0), params.get("delta_y", 0))
        return True

    # -- Screenshot ----------------------------------------------------------
    if method in (METHOD_SCREENSHOT, METHOD_SCREENSHOT_WIDGET):
        q_application = _qt_application_class()
        if method == METHOD_SCREENSHOT_WIDGET:
            w = _resolve_one(params)
        else:
            # Full window screenshot
            windows = _get_interactable_top_level_widgets()
            visible = [w for w in windows if w.isVisible()]
            if not visible:
                raise ValueError("No visible window found")
            w = visible[0]

        overlay = _OVERLAY_MANAGER.overlay_for_window(w.window() if hasattr(w, "window") else w) if _OVERLAY_MANAGER is not None else None
        hide_overlay_for_capture = bool(
            overlay is not None
            and getattr(overlay, "_manager_active", False)
            and overlay.isVisible()
        )
        if hide_overlay_for_capture:
            hidden_overlay: Any = overlay
            hidden_overlay.hide()
            q_application.processEvents()

        clip_keys = ("x", "y", "width", "height")
        has_clip = any(params.get(key) is not None for key in clip_keys)
        try:
            if has_clip:
                if any(params.get(key) is None for key in clip_keys):
                    raise ValueError("Screenshot clipping requires x, y, width, and height together")
                clip_x = int(params["x"])
                clip_y = int(params["y"])
                clip_width = int(params["width"])
                clip_height = int(params["height"])
                if clip_x < 0 or clip_y < 0 or clip_width <= 0 or clip_height <= 0:
                    raise ValueError("Screenshot clipping requires non-negative x/y and positive width/height")
                pixmap = w.grab(qt_core.QRect(clip_x, clip_y, clip_width, clip_height))
            else:
                pixmap = w.grab()
        finally:
            if hide_overlay_for_capture:
                shown_overlay: Any = overlay
                shown_overlay.sync_to_window()
                q_application.processEvents()
        buf = qt_core.QBuffer()
        io_device = qt_core.QIODevice
        buf.open(io_device.WriteOnly if hasattr(io_device, "WriteOnly") else io_device.OpenModeFlag.WriteOnly)
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
                    "blocked_by_modal": _is_window_blocked_by_modal(w),
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

def _process_events():
    """Process pending Qt events."""
    _qt_application_class().processEvents()


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
    return _point_coordinate(point, "x"), _point_coordinate(point, "y")


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
    center = _widget_center_point(widget)
    width = _widget_dimension(widget, "width")
    height = _widget_dimension(widget, "height")

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

    global_pos = _widget_map_to_global(target, local_point)

    hit = None
    widget_at = getattr(_qt_application_class(), "widgetAt", None)
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
    if not _widget_is_visible(target):
        return False

    for sample_point in _sample_local_points(target):
        hit = _topmost_hit_at_point(target, sample_point)
        if hit is None:
            continue
        if not _widget_is_visible(hit):
            continue
        if _is_same_or_descendant_widget(hit, target):
            return True
    return False


def _resolve_click_target(widget):
    """Return the concrete event receiver and local click position."""
    _import_qt()

    target = _primary_event_target(widget)
    if not _widget_is_visible(target):
        raise ValueError(
            f"Cannot click widget of type {_widget_class_name(widget)}: event target is not visible"
        )
    if not _widget_is_enabled(target):
        raise ValueError(
            f"Cannot click widget of type {_widget_class_name(widget)}: event target is disabled"
        )

    center = _widget_center_point(target)
    if not _point_within_widget_mask(target, center):
        raise ValueError(
            f"Cannot click widget of type {_widget_class_name(widget)}: center point is masked out"
        )
    global_pos = _widget_map_to_global(target, center)

    hit = _topmost_hit_at_point(target, center)
    if hit is None:
        raise ValueError(
            f"Cannot click widget of type {_widget_class_name(widget)}: center point does not resolve to an event target"
        )

    if not _is_same_or_descendant_widget(hit, target):
        raise ValueError(
            f"Cannot click widget of type {_widget_class_name(widget)}: center point is covered by {_widget_class_name(hit)}"
        )
    if not _widget_is_visible(hit):
        raise ValueError(
            f"Cannot click widget of type {_widget_class_name(widget)}: resolved click target is not visible"
        )
    if not _widget_is_enabled(hit):
        raise ValueError(
            f"Cannot click widget of type {_widget_class_name(widget)}: resolved click target is disabled"
        )

    local_pos = _widget_map_from_global(hit, global_pos)
    return hit, local_pos


def _click_widget(widget, *, double: bool = False):
    """Simulate a mouse click on the concrete event target under the widget center."""
    _import_qt()
    QTest = _QtTest
    qt_core = _qt_core_module()
    Qt = qt_core.Qt

    if QTest and hasattr(QTest, "QTest"):
        QTest = QTest.QTest

    event_target, local_pos = _resolve_click_target(widget)

    _widget_set_focus(event_target, Qt.MouseFocusReason)
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
    qt_gui = _qt_gui_module()
    qt_core = _qt_core_module()
    q_application = _qt_application_class()
    QMouseEvent = qt_gui.QMouseEvent
    QEvent = qt_core.QEvent
    Qt = qt_core.Qt
    global_pos = _widget_map_to_global(widget, pos)

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
        pos_f = _to_qpointf(pos)
        global_f = _to_qpointf(global_pos)
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress, pos_f, global_f,
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        )
        release = QMouseEvent(
            QEvent.Type.MouseButtonRelease, pos_f, global_f,
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        )

    q_application.postEvent(widget, press)
    q_application.postEvent(widget, release)

    if double:
        try:
            dbl = QMouseEvent(
                QEvent.Type.MouseButtonDblClick, pos, global_pos,
                Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
            )
        except TypeError:
            dbl = QMouseEvent(
                QEvent.Type.MouseButtonDblClick, _to_qpointf(pos), _to_qpointf(global_pos),
                Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
            )
        q_application.postEvent(widget, dbl)
        q_application.postEvent(widget, release)


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

    _widget_set_focus(widget)
    _process_events()

    if QTest and hasattr(QTest, "keyClicks"):
        QTest.keyClicks(widget, text, delay=delay)
    else:
        # Fallback: use QKeyEvent
        qt_gui = _qt_gui_module()
        qt_core = _qt_core_module()
        q_application = _qt_application_class()
        QKeyEvent = qt_gui.QKeyEvent
        QEvent = qt_core.QEvent
        Qt = qt_core.Qt

        for ch in text:
            press = QKeyEvent(QEvent.Type.KeyPress, 0, Qt.NoModifier, ch)
            release = QKeyEvent(QEvent.Type.KeyRelease, 0, Qt.NoModifier, ch)
            q_application.postEvent(widget, press)
            q_application.postEvent(widget, release)
            if delay:
                _process_events()
                time.sleep(delay / 1000.0)

    _process_events()


def _hover_widget(widget, pos):
    """Dispatch a synthetic hover event without warping the real cursor."""
    qt_core = _qt_core_module()
    qt_gui = _qt_gui_module()
    q_application = _qt_application_class()
    Qt = qt_core.Qt
    QEvent = qt_core.QEvent

    QMouseEvent = qt_gui.QMouseEvent
    global_pos = _widget_map_to_global(widget, pos)

    try:
        move = QMouseEvent(
            QEvent.Type.MouseMove, pos, global_pos,
            Qt.NoButton, Qt.NoButton, Qt.NoModifier,
        )
    except TypeError:
        move = QMouseEvent(
            QEvent.Type.MouseMove, _to_qpointf(pos), _to_qpointf(global_pos),
            Qt.NoButton, Qt.NoButton, Qt.NoModifier,
        )

    q_application.postEvent(widget, move)
    _process_events()


def _press_key(widget, key_str: str):
    """Press a named key (Enter, Tab, etc.)."""
    qt_core = _qt_core_module()
    Qt = qt_core.Qt

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

    _widget_set_focus(widget)
    _process_events()

    if QTest and hasattr(QTest, "keyClick"):
        QTest.keyClick(widget, qt_key)
    else:
        qt_gui = _qt_gui_module()
        q_application = _qt_application_class()
        QKeyEvent = qt_gui.QKeyEvent
        QEvent = qt_core.QEvent
        press = QKeyEvent(QEvent.Type.KeyPress, qt_key, Qt.NoModifier)
        release = QKeyEvent(QEvent.Type.KeyRelease, qt_key, Qt.NoModifier)
        q_application.postEvent(widget, press)
        q_application.postEvent(widget, release)

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
    qt_gui = _qt_gui_module()
    qt_core = _qt_core_module()
    q_application = _qt_application_class()
    QWheelEvent = qt_gui.QWheelEvent
    Qt = qt_core.Qt
    target = _primary_event_target(widget)

    center = _widget_center_point(target)
    global_pos = _widget_map_to_global(target, center)

    try:
        QPoint = qt_core.QPoint
        event = QWheelEvent(
            _to_qpointf(center), _to_qpointf(global_pos),
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

    q_application.postEvent(target, event)
    _process_events()


def _wait_for(params: dict) -> bool:
    """Wait for a widget condition to be met."""
    selector = params.get("selector")
    if not isinstance(selector, str) or not selector:
        raise ValueError("wait_for requires a non-empty selector")
    state = params.get("state", "visible")  # visible, hidden, enabled, disabled
    timeout = params.get("timeout", 30000)  # ms
    poll_interval = params.get("poll_interval", 100)  # ms

    start = time.monotonic()
    deadline = start + timeout / 1000.0

    while time.monotonic() < deadline:
        _process_events()

        roots = _get_interactable_top_level_widgets()
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

    visible = [window for window in _get_interactable_top_level_widgets() if window.isVisible()]
    if visible:
        return visible[0]

    raise ValueError("No visible window found for targetless key press")


def _resolve_pointer_action_window(params: dict):
    window_wid = params.get("window_wid")
    if window_wid is not None:
        window = _registry.get(window_wid)
        if window is None:
            raise ValueError(f"No window found for window_wid={window_wid}")
        return window.window() if hasattr(window, "window") else window

    modal_window = _active_modal_top_level_widget()
    if modal_window is not None:
        return modal_window

    app = _QApplication.instance() if _QApplication is not None and hasattr(_QApplication, "instance") else None
    active_window = None
    if app is not None and hasattr(app, "activeWindow"):
        active_window = app.activeWindow()
    elif _QApplication is not None and hasattr(_QApplication, "activeWindow"):
        active_window = _QApplication.activeWindow()
    if active_window is not None:
        active_window = active_window.window() if hasattr(active_window, "window") else active_window
        if _is_overlay_target_window_visible(active_window) and not _is_window_blocked_by_modal(active_window):
            return active_window

    if app is not None and hasattr(app, "focusWidget"):
        focused = app.focusWidget()
        if focused is not None:
            focused_window = focused.window() if hasattr(focused, "window") else focused
            if _is_overlay_target_window_visible(focused_window) and not _is_window_blocked_by_modal(focused_window):
                return focused_window

    visible = [window for window in _get_interactable_top_level_widgets() if window.isVisible()]
    if visible:
        return visible[0]

    raise ValueError("No visible window found for coordinate pointer action")


# --------------------------------------------------------------------------- #
#  TCP Server                                                                  #
# --------------------------------------------------------------------------- #

class _ClientHandler(threading.Thread):
    """Handle a single client connection."""

    def __init__(self, conn: socket.socket, addr, dispatcher, command_event_cls, main_thread_call_event_cls):
        super().__init__(daemon=True)
        self.conn = conn
        self.addr = addr
        self.dispatcher = dispatcher
        self.command_event_cls = command_event_cls
        self.main_thread_call_event_cls = main_thread_call_event_cls
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
            self._run_on_main_thread(lambda: _remove_session_agent_name(self._session_id), timeout=5.0)
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
        _qt_application_class().postEvent(self.dispatcher, event)

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

    def _run_on_main_thread(self, callback, *, timeout: float) -> None:
        future = Future()
        event = self.main_thread_call_event_cls(callback, future)
        _qt_application_class().postEvent(self.dispatcher, event)
        try:
            future.result(timeout=timeout)
        except Exception:
            logger.exception("Main-thread cleanup failed for client %s", self.addr)

    def stop(self):
        self._running = False
        try:
            self.conn.close()
        except OSError:
            pass


class _AgentServer(threading.Thread):
    """TCP server that accepts client connections."""

    def __init__(self, host: str, port: int, dispatcher, command_event_cls, main_thread_call_event_cls):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.dispatcher = dispatcher
        self.command_event_cls = command_event_cls
        self.main_thread_call_event_cls = main_thread_call_event_cls
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
                handler = _ClientHandler(conn, addr, self.dispatcher, self.command_event_cls, self.main_thread_call_event_cls)
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
        app = _qt_application_class().instance()
    if app is None:
        raise RuntimeError("No QApplication instance found. Create one first.")

    if _VISUAL_FEEDBACK_ENABLED:
        _ensure_overlay_manager()
    elif _OVERLAY_MANAGER is not None:
        _OVERLAY_MANAGER.close_all()
        _OVERLAY_MANAGER = None

    Dispatcher, CommandEvent, MainThreadCallEvent = _create_dispatcher()
    dispatcher = Dispatcher()
    # Keep reference alive
    dispatcher.setObjectName("_qplaywright_dispatcher")

    server = _AgentServer(host, port, dispatcher, CommandEvent, MainThreadCallEvent)
    server.start()

    _agent_server = server
    return server
