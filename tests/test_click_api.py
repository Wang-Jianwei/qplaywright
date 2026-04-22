from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from qplaywright.agent import _server as server


@dataclass(eq=True)
class FakePoint:
    x: int
    y: int


class FakeRect:
    def __init__(self, center: FakePoint):
        self._center = center

    def center(self) -> FakePoint:
        return self._center


class FakeMetaObject:
    def __init__(self, class_name: str):
        self._class_name = class_name

    def className(self) -> str:
        return self._class_name


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
    ):
        self._class_name = class_name
        self._parent = parent
        self._visible = visible
        self._enabled = enabled
        self._global_origin = global_origin
        self._center = center
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


def _install_fake_qt(monkeypatch, *, widget_at=None):
    FakeApplication.widget_at_result = widget_at
    FakeApplication.process_events_calls = 0
    FakeQTest.calls = []

    monkeypatch.setattr(server, "_import_qt", lambda: None)
    monkeypatch.setattr(server, "_QApplication", FakeApplication)
    monkeypatch.setattr(server, "_QtTest", SimpleNamespace(QTest=FakeQTest))
    monkeypatch.setattr(
        server,
        "_QtCore",
        SimpleNamespace(Qt=SimpleNamespace(LeftButton="left", NoModifier="none", MouseFocusReason="mouse")),
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


def test_resolve_click_target_rejects_covered_center(monkeypatch):
    widget = FakeClickWidget("QPushButton")
    overlay = FakeClickWidget("OverlayWidget", global_origin=FakePoint(100, 200))

    _install_fake_qt(monkeypatch, widget_at=overlay)

    with pytest.raises(ValueError, match="covered by OverlayWidget"):
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