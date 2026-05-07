from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

import pytest  # type: ignore[import-not-found]

from qplaywright.agent import _server as server
from qplaywright.protocol import Request
from qplaywright.sync_api._locator import ItemLocator, Locator


class FakeConnection:
    def __init__(self):
        self.calls: list[tuple[str, dict, float | None]] = []

    def send(self, method: str, params: dict | None = None, *, timeout: float | None = None) -> object:
        payload = params or {}
        self.calls.append((method, payload, timeout))
        return {"method": method, "params": payload}


class SequencedConnection(FakeConnection):
    def __init__(self, responses: dict[str, list[object] | object]):
        super().__init__()
        self.responses = responses

    def send(self, method: str, params: dict | None = None, *, timeout: float | None = None) -> object:
        payload = params or {}
        self.calls.append((method, payload, timeout))
        response = self.responses[method]
        if isinstance(response, list):
            if len(response) > 1:
                return response.pop(0)
            return response[0]
        return response


def test_locator_cell_with_widget_id_builds_numeric_item_locator_request():
    conn = FakeConnection()
    locator = Locator(cast(Any, conn), "", widget_wid=42, timeout=9.0)

    item = locator.cell(2, 1)

    assert isinstance(item, ItemLocator)
    result = item.text_content()

    assert result == {
        "method": "item_text",
        "params": {
            "wid": 42,
            "item": {
                "kind": "table_cell",
                "row": 2,
                "column": 1,
            },
        },
    }
    assert conn.calls == [
        (
            "item_text",
            {
                "wid": 42,
                "item": {
                    "kind": "table_cell",
                    "row": 2,
                    "column": 1,
                },
            },
            9.0,
        )
    ]


def test_locator_cell_resolves_owner_widget_before_item_click():
    conn = SequencedConnection({"find": {"wid": 77}, "item_click": True})
    locator = Locator(cast(Any, conn), "#data_table", timeout=4.0)

    locator.cell(3, 0).click()

    assert conn.calls == [
        ("find", {"selector": "#data_table"}, 4.0),
        (
            "item_click",
            {
                "wid": 77,
                "item": {
                    "kind": "table_cell",
                    "row": 3,
                    "column": 0,
                },
            },
            4.0,
        ),
    ]


def test_locator_cell_uses_header_name_descriptor_for_string_column():
    conn = FakeConnection()
    locator = Locator(cast(Any, conn), "", widget_wid=12, timeout=6.0)

    result = locator.cell(1, "Status").properties()

    assert result == {
        "method": "item_properties",
        "params": {
            "wid": 12,
            "item": {
                "kind": "table_cell",
                "row": 1,
                "columnName": "Status",
            },
        },
    }
    assert conn.calls == [
        (
            "item_properties",
            {
                "wid": 12,
                "item": {
                    "kind": "table_cell",
                    "row": 1,
                    "columnName": "Status",
                },
            },
            6.0,
        )
    ]


def test_item_locator_is_visible_sends_item_visible_request():
    conn = FakeConnection()
    item = ItemLocator(cast(Any, conn), 5, {"kind": "table_cell", "row": 0, "column": 2}, timeout=3.0)

    result = item.is_visible()

    assert result == {
        "method": "item_visible",
        "params": {
            "wid": 5,
            "item": {
                "kind": "table_cell",
                "row": 0,
                "column": 2,
            },
        },
    }
    assert conn.calls == [
        (
            "item_visible",
            {
                "wid": 5,
                "item": {
                    "kind": "table_cell",
                    "row": 0,
                    "column": 2,
                },
            },
            3.0,
        )
    ]


@dataclass(eq=True)
class FakePoint:
    x_value: int
    y_value: int

    def x(self) -> int:
        return self.x_value

    def y(self) -> int:
        return self.y_value


class FakeRect:
    def __init__(self, x: int, y: int, width: int, height: int):
        self._x = x
        self._y = y
        self._width = width
        self._height = height

    def topLeft(self) -> FakePoint:
        return FakePoint(self._x, self._y)

    def center(self) -> FakePoint:
        return FakePoint(self._x + self._width // 2, self._y + self._height // 2)

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height

    def isEmpty(self) -> bool:
        return self._width <= 0 or self._height <= 0


class FakeMetaObject:
    def __init__(self, class_name: str):
        self._class_name = class_name

    def className(self) -> str:
        return self._class_name


class FakeTableIndex:
    def __init__(self, model, row: int, column: int, *, valid: bool = True):
        self._model = model
        self._row = row
        self._column = column
        self._valid = valid

    def row(self) -> int:
        return self._row

    def column(self) -> int:
        return self._column

    def isValid(self) -> bool:
        return self._valid

    def data(self, role=None):
        return self._model.data(self, role)


class FakeTableModel:
    def __init__(self, rows: list[list[str]], headers: list[str]):
        self._rows = rows
        self._headers = headers

    def rowCount(self) -> int:
        return len(self._rows)

    def columnCount(self) -> int:
        return len(self._headers)

    def index(self, row: int, column: int):
        valid = 0 <= row < self.rowCount() and 0 <= column < self.columnCount()
        return FakeTableIndex(self, row, column, valid=valid)

    def data(self, index: FakeTableIndex, role=None):
        if not index.isValid():
            return None
        return self._rows[index.row()][index.column()]

    def headerData(self, section: int, orientation, role=None):
        if 0 <= section < len(self._headers):
            return self._headers[section]
        return None


class FakeSelectionModel:
    def __init__(self, selected: set[tuple[int, int]] | None = None):
        self._selected = set(selected or set())

    def isSelected(self, index: FakeTableIndex) -> bool:
        return (index.row(), index.column()) in self._selected


class FakeViewport:
    def __init__(self, *, global_origin: FakePoint = FakePoint(100, 200)):
        self._global_origin = global_origin
        self.focus_calls: list[tuple[object, ...]] = []

    def isVisible(self) -> bool:
        return True

    def isEnabled(self) -> bool:
        return True

    def mapToGlobal(self, point: FakePoint) -> FakePoint:
        return FakePoint(self._global_origin.x_value + point.x_value, self._global_origin.y_value + point.y_value)

    def setFocus(self, *args):
        self.focus_calls.append(args)

    def metaObject(self):
        return FakeMetaObject("QViewport")


class FakeTableView:
    def __init__(
        self,
        rows: list[list[str]],
        headers: list[str],
        *,
        hidden_columns: set[int] | None = None,
        rects: dict[tuple[int, int], FakeRect] | None = None,
        selected: set[tuple[int, int]] | None = None,
        class_name: str = "QTableView",
    ):
        self._meta = FakeMetaObject(class_name)
        self._model = FakeTableModel(rows, headers)
        self._viewport = FakeViewport()
        self._hidden_columns = set(hidden_columns or set())
        self._rects = dict(rects or {})
        self._selection_model = FakeSelectionModel(selected)
        self.scroll_calls: list[tuple[int, int, tuple[object, ...]]] = []

    def metaObject(self):
        return self._meta

    def model(self):
        return self._model

    def viewport(self):
        return self._viewport

    def isColumnHidden(self, column: int) -> bool:
        return column in self._hidden_columns

    def visualRect(self, index: FakeTableIndex):
        return self._rects.get((index.row(), index.column()), FakeRect(0, 0, 0, 0))

    def scrollTo(self, index: FakeTableIndex, *args):
        self.scroll_calls.append((index.row(), index.column(), args))

    def selectionModel(self):
        return self._selection_model


class FakeQTest:
    calls: list[tuple[str, object, object, object, object]] = []

    @staticmethod
    def mouseClick(widget, button, modifier=None, pos=None):
        FakeQTest.calls.append(("click", widget, button, modifier, pos))

    @staticmethod
    def mouseDClick(widget, button, modifier=None, pos=None):
        FakeQTest.calls.append(("dblclick", widget, button, modifier, pos))


class FakeApplication:
    process_events_calls = 0

    @staticmethod
    def processEvents():
        FakeApplication.process_events_calls += 1


def _install_fake_item_view_qt(monkeypatch):
    FakeQTest.calls = []
    FakeApplication.process_events_calls = 0

    monkeypatch.setattr(server, "_import_qt", lambda: None)
    monkeypatch.setattr(server, "_QApplication", FakeApplication)
    monkeypatch.setattr(server, "_QtTest", SimpleNamespace(QTest=FakeQTest))
    monkeypatch.setattr(server, "_QtGui", SimpleNamespace(QCursor=object()))
    monkeypatch.setattr(
        server,
        "_QtCore",
        SimpleNamespace(
            Qt=SimpleNamespace(
                Horizontal=1,
                DisplayRole=0,
                LeftButton="left",
                NoModifier="none",
                MouseFocusReason="mouse",
                ItemDataRole=SimpleNamespace(DisplayRole=0),
            )
        ),
    )
    monkeypatch.setattr(server, "_QtWidgets", SimpleNamespace(QAbstractItemView=SimpleNamespace(EnsureVisible="ensure_visible")))
    monkeypatch.setattr(server, "_update_visual_feedback", lambda *args, **kwargs: None)


def test_handle_command_item_text_reads_table_cell(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    table = FakeTableView(
        rows=[["001", "Alice"], ["002", "Bob"]],
        headers=["ID", "Name"],
        rects={(1, 1): FakeRect(10, 20, 40, 18)},
    )
    wid = server._registry.register(table)

    result = server._handle_command(Request(method="item_text", params={"wid": wid, "item": {"kind": "table_cell", "row": 1, "column": 1}}))

    assert result == "Bob"


def test_handle_command_item_properties_resolves_header_name(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    table = FakeTableView(
        rows=[["001", "Alice"], ["002", "Bob"]],
        headers=["ID", "Name"],
        rects={(1, 1): FakeRect(10, 20, 40, 18)},
        selected={(1, 1)},
    )
    wid = server._registry.register(table)

    result = server._handle_command(Request(method="item_properties", params={"wid": wid, "item": {"kind": "table_cell", "row": 1, "columnName": "Name"}}))

    assert result == {
        "kind": "table_cell",
        "row": 1,
        "column": 1,
        "text": "Bob",
        "selected": True,
    }


def test_handle_command_item_visible_false_for_hidden_column(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    table = FakeTableView(
        rows=[["001", "Alice"]],
        headers=["ID", "Name"],
        hidden_columns={1},
        rects={(0, 1): FakeRect(10, 20, 40, 18)},
    )
    wid = server._registry.register(table)

    result = server._handle_command(Request(method="item_visible", params={"wid": wid, "item": {"kind": "table_cell", "row": 0, "column": 1}}))

    assert result is False


def test_handle_command_item_bounding_box_uses_viewport_global_coordinates(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    table = FakeTableView(
        rows=[["001", "Alice"]],
        headers=["ID", "Name"],
        rects={(0, 1): FakeRect(10, 20, 40, 18)},
    )
    wid = server._registry.register(table)

    result = server._handle_command(Request(method="item_bounding_box", params={"wid": wid, "item": {"kind": "table_cell", "row": 0, "column": 1}}))

    assert result == {"x": 110, "y": 220, "width": 40, "height": 18}
    assert table.scroll_calls == [(0, 1, ("ensure_visible",))]


def test_handle_command_item_text_rejects_ambiguous_header_name(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    table = FakeTableView(
        rows=[["open", "closed"]],
        headers=["Status", "Status"],
        rects={(0, 0): FakeRect(0, 0, 10, 10), (0, 1): FakeRect(12, 0, 10, 10)},
    )
    wid = server._registry.register(table)

    with pytest.raises(ValueError, match="Ambiguous table header: Status"):
        server._handle_command(Request(method="item_text", params={"wid": wid, "item": {"kind": "table_cell", "row": 0, "columnName": "Status"}}))


def test_handle_command_item_click_uses_viewport_local_rect_center(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    table = FakeTableView(
        rows=[["001", "Alice"]],
        headers=["ID", "Name"],
        rects={(0, 1): FakeRect(10, 20, 40, 18)},
    )
    wid = server._registry.register(table)

    result = server._handle_command(Request(method="item_click", params={"wid": wid, "item": {"kind": "table_cell", "row": 0, "column": 1}}))

    assert result is True
    assert FakeQTest.calls == [
        ("click", table.viewport(), "left", "none", FakePoint(30, 29))
    ]
    assert table.scroll_calls == [(0, 1, ("ensure_visible",))]