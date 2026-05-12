from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from qplaywright.agent import _server as server
from qplaywright.protocol import Request


@dataclass(eq=True)
class FakePoint:
    x: int
    y: int


class FakeRect:
    def __init__(self, center: FakePoint, width: int = 1, height: int = 1):
        self._center = center
        self._width = width
        self._height = height

    def center(self) -> FakePoint:
        return self._center

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height

    def isEmpty(self) -> bool:
        return self._width <= 0 or self._height <= 0


class FakeStyleOptionButton:
    def __init__(self):
        self.widget = None
        self.text = ""
        self.icon = None
        self.iconSize = None

    def initFrom(self, widget) -> None:
        self.widget = widget


class FakeStyle:
    def __init__(self, rects: dict[object, FakeRect]):
        self._rects = rects

    def subElementRect(self, sub_element, _option, _widget):
        return self._rects.get(sub_element, FakeRect(FakePoint(0, 0), width=0, height=0))


class FakeMetaObject:
    def __init__(self, class_name: str):
        self._class_name = class_name

    def className(self) -> str:
        return self._class_name


class FakeMaskRegion:
    def __init__(self, *, empty: bool = True, contains=None):
        self._empty = empty
        self._contains = contains

    def isEmpty(self) -> bool:
        return self._empty

    def contains(self, point: FakePoint) -> bool:
        if self._contains is None:
            return True
        return bool(self._contains(point))


class FakeClickWidget:
    def __init__(
        self,
        class_name: str,
        *,
        parent: FakeClickWidget | None = None,
        visible: bool = True,
        enabled: bool = True,
        global_origin: FakePoint = FakePoint(100, 200),
        center: FakePoint = FakePoint(10, 12),
        size: tuple[int, int] = (40, 40),
        mask_region: FakeMaskRegion | None = None,
        mouse_transparent: bool = False,
        text: str = "",
        style_rects: dict[object, FakeRect] | None = None,
    ):
        self._class_name = class_name
        self._parent = parent
        self._visible = visible
        self._enabled = enabled
        self._global_origin = global_origin
        self._center = center
        self._size = size
        self._mask_region = mask_region or FakeMaskRegion()
        self._mouse_transparent = mouse_transparent
        self._text = text
        self._style = FakeStyle(style_rects or {}) if style_rects is not None else None
        self._child = None
        self._viewport = None
        self.focus_calls: list[tuple[object, ...]] = []

    def metaObject(self):
        return FakeMetaObject(self._class_name)

    def isVisible(self) -> bool:
        return self._visible

    def isEnabled(self) -> bool:
        return self._enabled

    def rect(self) -> FakeRect:
        return FakeRect(self._center)

    def width(self) -> int:
        return self._size[0]

    def height(self) -> int:
        return self._size[1]

    def mask(self):
        return self._mask_region

    def style(self):
        return self._style

    def text(self) -> str:
        return self._text

    def icon(self):
        return None

    def iconSize(self):
        return None

    def testAttribute(self, attribute) -> bool:
        return attribute == "transparent" and self._mouse_transparent

    def mapToGlobal(self, point: FakePoint) -> FakePoint:
        return FakePoint(self._global_origin.x + point.x, self._global_origin.y + point.y)

    def mapFromGlobal(self, point: FakePoint) -> FakePoint:
        return FakePoint(point.x - self._global_origin.x, point.y - self._global_origin.y)

    def parentWidget(self):
        return self._parent

    def childAt(self, point: FakePoint):
        return self._child

    def setChildAt(self, child: FakeClickWidget | None) -> None:
        self._child = child
        if child is not None:
            child._parent = self

    def setViewport(self, viewport: FakeClickWidget) -> None:
        self._viewport = viewport
        viewport._parent = self

    def viewport(self):
        return self._viewport

    def setFocus(self, *args):
        self.focus_calls.append(args)


class FakeApplication:
    widget_at_result = None
    process_events_calls = 0

    @staticmethod
    def widgetAt(point: FakePoint):
        if callable(FakeApplication.widget_at_result):
            return FakeApplication.widget_at_result(point)
        return FakeApplication.widget_at_result

    @staticmethod
    def processEvents():
        FakeApplication.process_events_calls += 1


class FakeQTest:
    calls: list[tuple[str, object, object, object, object]] = []

    @staticmethod
    def mouseClick(widget, button, modifier=None, pos=None):
        FakeQTest.calls.append(("click", widget, button, modifier, pos))

    @staticmethod
    def mouseDClick(widget, button, modifier=None, pos=None):
        FakeQTest.calls.append(("dblclick", widget, button, modifier, pos))


class FakeQMouseEvent:
    def __init__(self, *_args):
        self.args = _args


class FakeQWheelEvent:
    def __init__(self, *_args):
        self.args = _args


def _install_fake_qt(monkeypatch, *, widget_at=None):
    FakeApplication.widget_at_result = widget_at
    FakeApplication.process_events_calls = 0
    FakeQTest.calls = []

    monkeypatch.setattr(server, "_import_qt", lambda: None)
    monkeypatch.setattr(
        server,
        "_QtWidgets",
        SimpleNamespace(
            QStyleOptionButton=FakeStyleOptionButton,
            QStyle=SimpleNamespace(
                SE_CheckBoxIndicator="checkbox-indicator",
                SE_CheckBoxContents="checkbox-contents",
                SE_RadioButtonIndicator="radio-indicator",
                SE_RadioButtonContents="radio-contents",
            ),
        ),
    )
    monkeypatch.setattr(server, "_QApplication", FakeApplication)
    monkeypatch.setattr(server, "_QtGui", SimpleNamespace(QCursor=object, QMouseEvent=FakeQMouseEvent, QWheelEvent=FakeQWheelEvent))
    monkeypatch.setattr(server, "_QtTest", SimpleNamespace(QTest=FakeQTest))
    monkeypatch.setattr(
        server,
        "_QtCore",
        SimpleNamespace(
            QEvent=SimpleNamespace(
                Type=SimpleNamespace(
                    MouseMove="mousemove",
                    MouseButtonPress="mousepress",
                    MouseButtonRelease="mouserelease",
                    MouseButtonDblClick="mousedblclick",
                )
            ),
            Qt=SimpleNamespace(
                LeftButton="left",
                NoButton="none",
                NoModifier="none",
                MouseFocusReason="mouse",
                WA_TransparentForMouseEvents="transparent",
                ScrollBegin="scrollbegin",
                Key_Return="return",
                Key_Tab="tab",
                Key_Escape="escape",
                Key_Backspace="backspace",
                Key_Delete="delete",
                Key_Insert="insert",
                Key_Up="up",
                Key_Down="down",
                Key_Left="left-key",
                Key_Right="right-key",
                Key_Home="home",
                Key_End="end",
                Key_PageUp="pageup",
                Key_PageDown="pagedown",
                Key_Space="space",
                Key_Pause="pause",
                Key_Print="print",
                Key_Menu="menu",
                Key_CapsLock="capslock",
                Key_NumLock="numlock",
                Key_ScrollLock="scrolllock",
                Key_Clear="clear",
                Key_F1="f1",
                Key_F2="f2",
                Key_F3="f3",
                Key_F4="f4",
                Key_F5="f5",
                Key_F6="f6",
                Key_F7="f7",
                Key_F8="f8",
                Key_F9="f9",
                Key_F10="f10",
                Key_F11="f11",
                Key_F12="f12",
                Key_Control="control",
                Key_Shift="shift",
                Key_Alt="alt",
                Key_Meta="meta",
            ),
            QPoint=FakePoint,
        ),
    )


def test_resolve_click_target_prefers_viewport_hit_widget(monkeypatch):
    viewport = FakeClickWidget("QViewport", global_origin=FakePoint(100, 200))
    hit = FakeClickWidget("QLabel", parent=viewport, global_origin=FakePoint(108, 205))
    widget = FakeClickWidget("QListWidget")
    widget.setViewport(viewport)

    _install_fake_qt(monkeypatch, widget_at=hit)

    target, pos = server._resolve_click_target(widget)

    assert target is hit
    assert pos == FakePoint(2, 7)


def test_resolve_click_target_rejects_when_all_click_samples_are_covered(monkeypatch):
    widget = FakeClickWidget("QPushButton")
    overlay = FakeClickWidget("OverlayWidget", global_origin=FakePoint(100, 200))

    _install_fake_qt(monkeypatch, widget_at=overlay)

    with pytest.raises(ValueError, match="no clickable sample point"):
        server._resolve_click_target(widget)


def test_click_widget_uses_hit_target_and_local_position(monkeypatch):
    viewport = FakeClickWidget("QViewport", global_origin=FakePoint(100, 200))
    hit = FakeClickWidget("InnerButton", parent=viewport, global_origin=FakePoint(108, 205))
    widget = FakeClickWidget("QListWidget")
    widget.setViewport(viewport)

    _install_fake_qt(monkeypatch, widget_at=hit)

    server._click_widget(widget)

    assert FakeQTest.calls == [("click", hit, "left", "none", FakePoint(2, 7))]
    assert hit.focus_calls == [("mouse",)]
    assert FakeApplication.process_events_calls >= 2


def test_resolve_click_target_uses_style_reported_checkable_hit_area(monkeypatch):
    widget = FakeClickWidget(
        "QCheckBox",
        global_origin=FakePoint(100, 200),
        center=FakePoint(200, 8),
        size=(400, 16),
        text="Remember me",
        style_rects={
            "checkbox-indicator": FakeRect(FakePoint(320, 8), width=16, height=16),
            "checkbox-contents": FakeRect(FakePoint(260, 8), width=120, height=16),
        },
    )

    _install_fake_qt(
        monkeypatch,
        widget_at=lambda point: widget if point == FakePoint(420, 208) else None,
    )

    target, pos = server._resolve_click_target(widget)

    assert target is widget
    assert pos == FakePoint(320, 8)


def test_handle_command_click_accepts_window_relative_coordinates(monkeypatch):
    window = FakeClickWidget("QMainWindow", global_origin=FakePoint(100, 200), size=(80, 60))
    hit = FakeClickWidget("InnerButton", parent=window, global_origin=FakePoint(120, 230))
    window.setChildAt(hit)

    _install_fake_qt(monkeypatch, widget_at=hit)
    monkeypatch.setattr(server, "_registry", SimpleNamespace(get=lambda wid: window if wid == 7 else None))

    result = server._handle_command(Request(method="click", params={"window_wid": 7, "x": 25, "y": 35}))

    assert result is True
    assert FakeQTest.calls == [("click", hit, "left", "none", FakePoint(5, 5))]


def test_resolve_pointer_action_target_rejects_out_of_bounds_coordinates(monkeypatch):
    window = FakeClickWidget("QMainWindow", global_origin=FakePoint(100, 200), size=(40, 30))

    _install_fake_qt(monkeypatch, widget_at=window)
    monkeypatch.setattr(server, "_registry", SimpleNamespace(get=lambda wid: window if wid == 7 else None))

    with pytest.raises(ValueError, match="outside the target window bounds"):
        server._resolve_pointer_action_target({"window_wid": 7, "x": 40, "y": 12})


def test_handle_command_hover_accepts_window_relative_coordinates(monkeypatch):
    window = FakeClickWidget("QMainWindow", global_origin=FakePoint(100, 200), size=(80, 60))
    hit = FakeClickWidget("InnerButton", parent=window, global_origin=FakePoint(120, 230))
    window.setChildAt(hit)

    posted_events = []

    def post_event(widget, event):
        posted_events.append((widget, event))

    _install_fake_qt(monkeypatch, widget_at=hit)
    monkeypatch.setattr(server, "_registry", SimpleNamespace(get=lambda wid: window if wid == 7 else None))
    monkeypatch.setattr(server, "_QApplication", SimpleNamespace(widgetAt=FakeApplication.widgetAt, processEvents=FakeApplication.processEvents, postEvent=post_event))

    result = server._handle_command(Request(method="hover", params={"window_wid": 7, "x": 25, "y": 35}))

    assert result is True
    assert posted_events
    assert posted_events[-1][0] is hit


def test_is_topmost_visible_widget_accepts_descendant_hit(monkeypatch):
    viewport = FakeClickWidget("QViewport", global_origin=FakePoint(100, 200))
    hit = FakeClickWidget("InnerButton", parent=viewport, global_origin=FakePoint(108, 205))
    widget = FakeClickWidget("QListWidget")
    widget.setViewport(viewport)

    _install_fake_qt(monkeypatch, widget_at=hit)

    assert server._is_topmost_visible_widget(widget) is True


def test_is_topmost_visible_widget_rejects_covered_center(monkeypatch):
    widget = FakeClickWidget("QPushButton")
    overlay = FakeClickWidget("OverlayWidget", global_origin=FakePoint(100, 200))

    _install_fake_qt(monkeypatch, widget_at=overlay)

    assert server._is_topmost_visible_widget(widget) is False


def test_is_topmost_visible_widget_accepts_partial_visibility_when_non_center_sample_is_visible(monkeypatch):
    widget = FakeClickWidget("QPushButton", global_origin=FakePoint(100, 200), center=FakePoint(20, 20), size=(40, 40))
    overlay = FakeClickWidget("OverlayWidget", global_origin=FakePoint(100, 200))

    def widget_at(point: FakePoint):
        if point == FakePoint(120, 220):
            return overlay
        return widget

    _install_fake_qt(monkeypatch, widget_at=widget_at)

    assert server._is_topmost_visible_widget(widget) is True


def test_is_topmost_visible_widget_ignores_samples_outside_mask(monkeypatch):
    masked_hole = FakeMaskRegion(empty=False, contains=lambda point: point == FakePoint(0, 0))
    widget = FakeClickWidget(
        "QPushButton",
        global_origin=FakePoint(100, 200),
        center=FakePoint(20, 20),
        size=(40, 40),
        mask_region=masked_hole,
    )

    _install_fake_qt(monkeypatch, widget_at=None)

    assert server._is_topmost_visible_widget(widget) is False


def test_resolve_click_target_rejects_when_all_click_samples_are_masked(monkeypatch):
    masked_hole = FakeMaskRegion(empty=False, contains=lambda point: False)
    widget = FakeClickWidget("QPushButton", mask_region=masked_hole)

    _install_fake_qt(monkeypatch, widget_at=None)

    with pytest.raises(ValueError, match="no clickable sample point"):
        server._resolve_click_target(widget)


def test_resolve_click_target_skips_mouse_transparent_hit(monkeypatch):
    transparent_overlay = FakeClickWidget("DecorationOverlay", mouse_transparent=True)
    widget = FakeClickWidget("QPushButton")
    widget.setChildAt(transparent_overlay)

    _install_fake_qt(monkeypatch, widget_at=transparent_overlay)

    target, pos = server._resolve_click_target(widget)

    assert target is widget
    assert pos == FakePoint(10, 12)


def test_is_topmost_visible_widget_ignores_mouse_transparent_hit(monkeypatch):
    transparent_overlay = FakeClickWidget("DecorationOverlay", mouse_transparent=True)
    widget = FakeClickWidget("QPushButton")
    widget.setChildAt(transparent_overlay)

    _install_fake_qt(monkeypatch, widget_at=transparent_overlay)

    assert server._is_topmost_visible_widget(widget) is True


def test_post_mouse_event_double_click_posts_second_press(monkeypatch):
    widget = FakeClickWidget("QPushButton")
    posted_events = []

    _install_fake_qt(monkeypatch, widget_at=widget)
    monkeypatch.setattr(
        server,
        "_QApplication",
        SimpleNamespace(
            widgetAt=FakeApplication.widgetAt,
            processEvents=FakeApplication.processEvents,
            postEvent=lambda target, event: posted_events.append((target, event)),
        ),
    )

    server._post_mouse_event(widget, FakePoint(4, 5), double=True)

    assert [event.args[0] for _, event in posted_events] == [
        "mousepress",
        "mouserelease",
        "mousepress",
        "mousedblclick",
        "mouserelease",
    ]


def test_scroll_widget_uses_wheel_angle_steps(monkeypatch):
    widget = FakeClickWidget("QPushButton")
    posted_events = []

    _install_fake_qt(monkeypatch, widget_at=widget)
    monkeypatch.setattr(
        server,
        "_QApplication",
        SimpleNamespace(
            widgetAt=FakeApplication.widgetAt,
            processEvents=FakeApplication.processEvents,
            postEvent=lambda target, event: posted_events.append((target, event)),
        ),
    )

    server._scroll_widget(widget, delta_x=5, delta_y=-10)

    assert posted_events
    wheel_event = posted_events[-1][1]
    assert wheel_event.args[2] == FakePoint(5, -10)
    assert wheel_event.args[3] == FakePoint(120, -120)


@pytest.mark.parametrize(
    ("key_name", "expected"),
    [
        ("Insert", "insert"),
        ("Pause", "pause"),
        ("PrintScreen", "print"),
        ("Menu", "menu"),
        ("CapsLock", "capslock"),
        ("NumLock", "numlock"),
        ("ScrollLock", "scrolllock"),
        ("Clear", "clear"),
    ],
)
def test_key_to_qt_supports_extended_named_keys(monkeypatch, key_name, expected):
    _install_fake_qt(monkeypatch)

    assert server._key_to_qt(key_name) == expected


def test_overlay_badge_text_uses_configured_template(monkeypatch):
    monkeypatch.setenv("QPLAYWRIGHT_OVERLAY_BADGE_TEMPLATE", "Sharing with {agent}")

    assert server._overlay_badge_text("Inspector") == "Sharing with Inspector"