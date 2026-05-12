from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

import pytest  # type: ignore[import-not-found]

from qplaywright.agent import _server as server
from qplaywright import QPlaywrightActionError, QPlaywrightAgentError, QPlaywrightLookupError
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


class ErrorConnection(FakeConnection):
    def __init__(self, error: Exception):
        super().__init__()
        self.error = error

    def send(self, method: str, params: dict | None = None, *, timeout: float | None = None) -> object:
        payload = params or {}
        self.calls.append((method, payload, timeout))
        raise self.error


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


def test_locator_cell_raises_lookup_error_when_owner_widget_is_missing():
    conn = SequencedConnection({"find": [None]})
    locator = Locator(cast(Any, conn), "#missing_table", timeout=4.0)

    with pytest.raises(QPlaywrightLookupError, match="Widget not found: #missing_table") as exc_info:
        locator.cell(3, 0)

    assert exc_info.value.code == "widget_not_found"
    assert exc_info.value.context == {"selector": "#missing_table", "has_text": None}


def test_locator_child_locator_raises_lookup_error_when_parent_widget_is_missing():
    conn = SequencedConnection({"find": [None]})
    locator = Locator(cast(Any, conn), "#missing_panel", timeout=4.0)

    with pytest.raises(QPlaywrightLookupError, match="Parent widget not found: #missing_panel") as exc_info:
        locator.locator("role=button")

    assert exc_info.value.code == "widget_not_found"
    assert exc_info.value.context == {"selector": "#missing_panel", "has_text": None}


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


def test_item_locator_is_visible_returns_false_on_agent_error():
    conn = ErrorConnection(QPlaywrightAgentError("Agent error: item no longer visible", code="agent_error"))
    item = ItemLocator(cast(Any, conn), 5, {"kind": "table_cell", "row": 0, "column": 2}, timeout=3.0)

    result = item.is_visible()

    assert result is False
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


def test_item_locator_click_wraps_agent_error_as_action_error():
    conn = ErrorConnection(QPlaywrightAgentError("Agent error: item disabled", code="agent_error"))
    item = ItemLocator(cast(Any, conn), 5, {"kind": "table_cell", "row": 0, "column": 2}, timeout=3.0)

    with pytest.raises(QPlaywrightActionError, match="click failed") as exc_info:
        item.click()

    assert exc_info.value.code == "action_failed"
    assert exc_info.value.context == {
        "action": "click",
        "method": "item_click",
        "owner_wid": 5,
        "item": {
            "kind": "table_cell",
            "row": 0,
            "column": 2,
        },
    }


def test_locator_is_visible_returns_false_on_agent_error():
    conn = ErrorConnection(QPlaywrightAgentError("Agent error: widget disappeared", code="agent_error"))
    locator = Locator(cast(Any, conn), "#login", timeout=2.0)

    result = locator.is_visible()

    assert result is False
    assert conn.calls == [
        (
            "is_visible",
            {"selector": "#login"},
            2.0,
        )
    ]


def test_locator_node_resolves_owner_widget_before_expand():
    conn = SequencedConnection({"find": {"wid": 31}, "item_expand": True})
    locator = Locator(cast(Any, conn), "role=tree", timeout=5.0)

    locator.node(["Settings", 1]).expand()

    assert conn.calls == [
        ("find", {"selector": "role=tree"}, 5.0),
        (
            "item_expand",
            {
                "wid": 31,
                "item": {
                    "kind": "tree_node",
                    "path": ["Settings", 1],
                },
            },
            5.0,
        ),
    ]


def test_locator_root_node_builds_tree_descriptor_for_collapse():
    conn = FakeConnection()
    locator = Locator(cast(Any, conn), "", widget_wid=9, timeout=2.5)

    locator.root_node(0).collapse()

    assert conn.calls == [
        (
            "item_collapse",
            {
                "wid": 9,
                "item": {
                    "kind": "tree_node",
                    "path": [0],
                },
            },
            2.5,
        )
    ]


def test_table_cell_expand_is_rejected_locally():
    conn = FakeConnection()
    item = ItemLocator(cast(Any, conn), 9, {"kind": "table_cell", "row": 1, "column": 2}, timeout=2.5)

    with pytest.raises(ValueError, match=r"expand\(\) is only supported for tree_node items"):
        item.expand()

    assert conn.calls == []


def test_list_item_collapse_is_rejected_locally():
    conn = FakeConnection()
    item = ItemLocator(cast(Any, conn), 9, {"kind": "list_item", "row": 1}, timeout=2.5)

    with pytest.raises(ValueError, match=r"collapse\(\) is only supported for tree_node items"):
        item.collapse()

    assert conn.calls == []


def test_locator_list_item_resolves_owner_widget_before_click():
    conn = SequencedConnection({"find": {"wid": 44}, "item_click": True})
    locator = Locator(cast(Any, conn), "#scroll_list", timeout=7.0)

    locator.list_item("Scrollable item 010").click()

    assert conn.calls == [
        ("find", {"selector": "#scroll_list"}, 7.0),
        (
            "item_click",
            {
                "wid": 44,
                "item": {
                    "kind": "list_item",
                    "text": "Scrollable item 010",
                },
            },
            7.0,
        ),
    ]


def test_locator_list_item_builds_numeric_descriptor_for_properties():
    conn = FakeConnection()
    locator = Locator(cast(Any, conn), "", widget_wid=18, timeout=8.0)

    result = locator.list_item(3).properties()

    assert result == {
        "method": "item_properties",
        "params": {
            "wid": 18,
            "item": {
                "kind": "list_item",
                "row": 3,
            },
        },
    }
    assert conn.calls == [
        (
            "item_properties",
            {
                "wid": 18,
                "item": {
                    "kind": "list_item",
                    "row": 3,
                },
            },
            8.0,
        )
    ]


def test_locator_tab_resolves_owner_widget_before_click():
    conn = SequencedConnection({"find": {"wid": 52}, "item_click": True})
    locator = Locator(cast(Any, conn), "#main_tabs", timeout=6.0)

    locator.tab("Data").click()

    assert conn.calls == [
        ("find", {"selector": "#main_tabs"}, 6.0),
        (
            "item_click",
            {
                "wid": 52,
                "item": {
                    "kind": "tab_item",
                    "label": "Data",
                },
            },
            6.0,
        ),
    ]


def test_item_locator_is_selected_sends_item_selected_request():
    conn = FakeConnection()
    item = ItemLocator(cast(Any, conn), 21, {"kind": "tab_item", "index": 1}, timeout=4.0)

    result = item.is_selected()

    assert result is True
    assert conn.calls == [
        (
            "item_selected",
            {
                "wid": 21,
                "item": {
                    "kind": "tab_item",
                    "index": 1,
                },
            },
            4.0,
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

    def contains(self, point: FakePoint) -> bool:
        return self._x <= point.x_value < self._x + self._width and self._y <= point.y_value < self._y + self._height


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
    def __init__(self, rows: list[list[str]], headers: list[str], edit_rows: list[list[str | None]] | None = None):
        self._rows = rows
        self._headers = headers
        self._edit_rows = edit_rows

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
        if role == 2 and self._edit_rows is not None:
            return self._edit_rows[index.row()][index.column()]
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


class FakeTreeNode:
    def __init__(self, text: str, children: list[FakeTreeNode] | None = None, *, edit_text: str | None = None):
        self.text = text
        self.children = list(children or [])
        self.edit_text = edit_text


class FakeTreeIndex:
    def __init__(self, model, node: FakeTreeNode | None = None, *, row: int = -1, parent=None, valid: bool = False):
        self._model = model
        self._node = node
        self._row = row
        self._parent = parent
        self._valid = valid

    def row(self) -> int:
        return self._row

    def column(self) -> int:
        return 0

    def parent(self):
        return self._parent if self._parent is not None else self._model.invalid_index()

    def isValid(self) -> bool:
        return self._valid

    def data(self, role=None):
        return self._model.data(self, role)


class FakeTreeModel:
    def __init__(self, roots: list[FakeTreeNode]):
        self._roots = roots

    def invalid_index(self):
        return FakeTreeIndex(self)

    def _children(self, parent=None) -> list[FakeTreeNode]:
        if parent is None or not parent.isValid():
            return self._roots
        assert parent._node is not None
        return parent._node.children

    def rowCount(self, parent=None) -> int:
        return len(self._children(parent))

    def index(self, row: int, column: int, parent=None):
        children = self._children(parent)
        if column != 0 or row < 0 or row >= len(children):
            return self.invalid_index()
        parent_index = parent if parent is not None and parent.isValid() else None
        return FakeTreeIndex(self, children[row], row=row, parent=parent_index, valid=True)

    def data(self, index: FakeTreeIndex, role=None):
        if not index.isValid() or index._node is None:
            return None
        if role == 2 and index._node.edit_text is not None:
            return index._node.edit_text
        return index._node.text

    def text_path(self, index: FakeTreeIndex) -> tuple[str, ...]:
        if not index.isValid():
            return ()
        parts: list[str] = []
        current = index
        while current.isValid() and current._node is not None:
            parts.append(current._node.text)
            current = current.parent()
        parts.reverse()
        return tuple(parts)


class FakeTreeSelectionModel:
    def __init__(self, model: FakeTreeModel, selected_paths: set[tuple[str, ...]] | None = None):
        self._model = model
        self._selected_paths = set(selected_paths or set())

    def isSelected(self, index: FakeTreeIndex) -> bool:
        return self._model.text_path(index) in self._selected_paths


class FakeListIndex:
    def __init__(self, model, row: int, *, valid: bool = True):
        self._model = model
        self._row = row
        self._valid = valid

    def row(self) -> int:
        return self._row

    def column(self) -> int:
        return 0

    def isValid(self) -> bool:
        return self._valid

    def data(self, role=None):
        return self._model.data(self, role)


class FakeListModel:
    def __init__(self, items: list[str], edit_items: list[str | None] | None = None):
        self._items = items
        self._edit_items = edit_items

    def rowCount(self) -> int:
        return len(self._items)

    def index(self, row: int, column: int, parent=None):
        valid = column == 0 and 0 <= row < self.rowCount()
        return FakeListIndex(self, row, valid=valid)

    def data(self, index: FakeListIndex, role=None):
        if not index.isValid():
            return None
        if role == 2 and self._edit_items is not None:
            return self._edit_items[index.row()]
        return self._items[index.row()]


class FakeListSelectionModel:
    def __init__(self, selected_rows: set[int] | None = None):
        self._selected_rows = set(selected_rows or set())

    def isSelected(self, index: FakeListIndex) -> bool:
        return index.row() in self._selected_rows


class FakeComboEditor:
    def __init__(self, current_text: str):
        self._current_text = current_text

    def currentText(self) -> str:
        return self._current_text


class FakeTabPage:
    def __init__(self, object_name: str):
        self._object_name = object_name

    def objectName(self) -> str:
        return self._object_name


class FakeTabBar:
    def __init__(
        self,
        labels: list[str],
        *,
        rects: dict[int, FakeRect] | None = None,
        current_index: int = 0,
        hidden_indices: set[int] | None = None,
        enabled_indices: set[int] | None = None,
        class_name: str = "QTabBar",
        global_origin: FakePoint = FakePoint(400, 120),
    ):
        self._meta = FakeMetaObject(class_name)
        self._labels = list(labels)
        self._rects = dict(rects or {})
        self._current_index = current_index
        self._hidden_indices = set(hidden_indices or set())
        self._enabled_indices = set(enabled_indices or range(len(labels)))
        self._global_origin = global_origin
        self.focus_calls: list[tuple[object, ...]] = []

    def metaObject(self):
        return self._meta

    def isVisible(self) -> bool:
        return True

    def isEnabled(self) -> bool:
        return True

    def setFocus(self, *args):
        self.focus_calls.append(args)

    def mapToGlobal(self, point: FakePoint) -> FakePoint:
        return FakePoint(self._global_origin.x_value + point.x_value, self._global_origin.y_value + point.y_value)

    def count(self) -> int:
        return len(self._labels)

    def tabText(self, index: int) -> str:
        return self._labels[index]

    def currentIndex(self) -> int:
        return self._current_index

    def setCurrentIndex(self, index: int):
        self._current_index = index

    def tabRect(self, index: int):
        if index in self._hidden_indices:
            return FakeRect(0, 0, 0, 0)
        return self._rects.get(index, FakeRect(index * 90, 0, 80, 24))

    def isTabVisible(self, index: int) -> bool:
        return index not in self._hidden_indices

    def isTabEnabled(self, index: int) -> bool:
        return index in self._enabled_indices


class FakeTabWidget:
    def __init__(
        self,
        labels: list[str],
        *,
        rects: dict[int, FakeRect] | None = None,
        current_index: int = 0,
        hidden_indices: set[int] | None = None,
        enabled_indices: set[int] | None = None,
        page_object_names: list[str] | None = None,
        class_name: str = "QTabWidget",
    ):
        self._meta = FakeMetaObject(class_name)
        self._tab_bar = FakeTabBar(
            labels,
            rects=rects,
            current_index=current_index,
            hidden_indices=hidden_indices,
            enabled_indices=enabled_indices,
        )
        default_names = page_object_names or [f"tab_page_{index}" for index in range(len(labels))]
        self._pages = [FakeTabPage(name) for name in default_names]

    def metaObject(self):
        return self._meta

    def tabBar(self):
        return self._tab_bar

    def currentIndex(self) -> int:
        return self._tab_bar.currentIndex()

    def setCurrentIndex(self, index: int):
        self._tab_bar.setCurrentIndex(index)

    def widget(self, index: int):
        return self._pages[index]


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
        edit_rows: list[list[str | None]] | None = None,
        editors: dict[tuple[int, int], object] | None = None,
        class_name: str = "QTableView",
    ):
        self._meta = FakeMetaObject(class_name)
        self._model = FakeTableModel(rows, headers, edit_rows=edit_rows)
        self._viewport = FakeViewport()
        self._hidden_columns = set(hidden_columns or set())
        self._rects = dict(rects or {})
        self._selection_model = FakeSelectionModel(selected)
        self._editors = dict(editors or {})
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

    def indexWidget(self, index: FakeTableIndex):
        return self._editors.get((index.row(), index.column()))


class FakeTreeView:
    def __init__(
        self,
        roots: list[FakeTreeNode],
        *,
        rects: dict[tuple[str, ...], FakeRect] | None = None,
        expanded_paths: set[tuple[str, ...]] | None = None,
        selected_paths: set[tuple[str, ...]] | None = None,
        editors: dict[tuple[str, ...], object] | None = None,
        class_name: str = "QTreeView",
    ):
        self._meta = FakeMetaObject(class_name)
        self._model = FakeTreeModel(roots)
        self._viewport = FakeViewport()
        self._rects = dict(rects or {})
        self._expanded_paths = set(expanded_paths or set())
        self._selection_model = FakeTreeSelectionModel(self._model, selected_paths)
        self._editors = dict(editors or {})
        self.scroll_calls: list[tuple[tuple[str, ...], tuple[object, ...]]] = []
        self.expand_calls: list[tuple[str, ...]] = []
        self.collapse_calls: list[tuple[str, ...]] = []

    def metaObject(self):
        return self._meta

    def model(self):
        return self._model

    def viewport(self):
        return self._viewport

    def selectionModel(self):
        return self._selection_model

    def indexWidget(self, index: FakeTreeIndex):
        return self._editors.get(self._path(index))

    def isColumnHidden(self, column: int) -> bool:
        return False

    def _path(self, index: FakeTreeIndex) -> tuple[str, ...]:
        return self._model.text_path(index)

    def _is_visible_path(self, path: tuple[str, ...]) -> bool:
        for depth in range(1, len(path)):
            if path[:depth] not in self._expanded_paths:
                return False
        return True

    def visualRect(self, index: FakeTreeIndex):
        path = self._path(index)
        if not self._is_visible_path(path):
            return FakeRect(0, 0, 0, 0)
        return self._rects.get(path, FakeRect(0, 0, 0, 0))

    def scrollTo(self, index: FakeTreeIndex, *args):
        self.scroll_calls.append((self._path(index), args))

    def isExpanded(self, index: FakeTreeIndex) -> bool:
        return self._path(index) in self._expanded_paths

    def expand(self, index: FakeTreeIndex):
        path = self._path(index)
        self.expand_calls.append(path)
        self._expanded_paths.add(path)

    def collapse(self, index: FakeTreeIndex):
        path = self._path(index)
        self.collapse_calls.append(path)
        self._expanded_paths.discard(path)


class FakeListView:
    def __init__(
        self,
        items: list[str],
        *,
        rects: dict[int, FakeRect] | None = None,
        hidden_rows: set[int] | None = None,
        selected_rows: set[int] | None = None,
        edit_items: list[str | None] | None = None,
        editors: dict[int, object] | None = None,
        class_name: str = "QListView",
    ):
        self._meta = FakeMetaObject(class_name)
        self._model = FakeListModel(items, edit_items=edit_items)
        self._viewport = FakeViewport()
        self._rects = dict(rects or {})
        self._hidden_rows = set(hidden_rows or set())
        self._selection_model = FakeListSelectionModel(selected_rows)
        self._editors = dict(editors or {})
        self.scroll_calls: list[tuple[int, tuple[object, ...]]] = []

    def metaObject(self):
        return self._meta

    def model(self):
        return self._model

    def viewport(self):
        return self._viewport

    def selectionModel(self):
        return self._selection_model

    def indexWidget(self, index: FakeListIndex):
        return self._editors.get(index.row())

    def visualRect(self, index: FakeListIndex):
        if index.row() in self._hidden_rows:
            return FakeRect(0, 0, 0, 0)
        return self._rects.get(index.row(), FakeRect(0, 0, 0, 0))

    def scrollTo(self, index: FakeListIndex, *args):
        self.scroll_calls.append((index.row(), args))


class FakeQTest:
    calls: list[tuple[str, object, object, object, object]] = []

    @staticmethod
    def mouseClick(widget, button, modifier=None, pos=None):
        if isinstance(widget, FakeTabBar) and isinstance(pos, FakePoint):
            for index in range(widget.count()):
                rect = widget.tabRect(index)
                if rect.contains(pos):
                    widget.setCurrentIndex(index)
                    break
        FakeQTest.calls.append(("click", widget, button, modifier, pos))

    @staticmethod
    def mouseDClick(widget, button, modifier=None, pos=None):
        FakeQTest.calls.append(("dblclick", widget, button, modifier, pos))


class FakeApplication:
    process_events_calls = 0

    @staticmethod
    def processEvents():
        FakeApplication.process_events_calls += 1


class FakeQtTableViewBase:
    pass


class FakeQtTreeViewBase:
    pass


class FakeQtListViewBase:
    pass


class FakeQtTabWidgetBase:
    pass


class FakeQtTabBarBase:
    pass


class FakeDerivedTableView(FakeQtTableViewBase, FakeTableView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, class_name="FancyOrdersTable", **kwargs)


class FakeDerivedTreeView(FakeQtTreeViewBase, FakeTreeView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, class_name="FancySettingsTree", **kwargs)


class FakeDerivedListView(FakeQtListViewBase, FakeListView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, class_name="FancyTaskList", **kwargs)


class FakeDerivedTabWidget(FakeQtTabWidgetBase, FakeTabWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, class_name="FancyMainTabs", **kwargs)


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
                EditRole=2,
                LeftButton="left",
                NoModifier="none",
                MouseFocusReason="mouse",
                ItemDataRole=SimpleNamespace(DisplayRole=0, EditRole=2),
            )
        ),
    )
    monkeypatch.setattr(
        server,
        "_QtWidgets",
        SimpleNamespace(
            QAbstractItemView=SimpleNamespace(EnsureVisible="ensure_visible"),
            QTableView=FakeQtTableViewBase,
            QTreeView=FakeQtTreeViewBase,
            QListView=FakeQtListViewBase,
            QTabWidget=FakeQtTabWidgetBase,
            QTabBar=FakeQtTabBarBase,
        ),
    )
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


def test_handle_command_item_text_accepts_qtableview_subclass(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    table = FakeDerivedTableView(
        rows=[["001", "Alice"], ["002", "Bob"]],
        headers=["ID", "Name"],
        rects={(1, 1): FakeRect(10, 20, 40, 18)},
    )
    wid = server._registry.register(table)

    result = server._handle_command(
        Request(method="item_text", params={"wid": wid, "item": {"kind": "table_cell", "row": 1, "column": 1}})
    )

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


def test_handle_command_item_properties_includes_edit_value_when_it_differs(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    table = FakeTableView(
        rows=[["Open", "Alice"]],
        headers=["Status", "Name"],
        edit_rows=[["Pending", None]],
        rects={(0, 0): FakeRect(0, 0, 50, 18)},
    )
    wid = server._registry.register(table)

    result = server._handle_command(
        Request(method="item_properties", params={"wid": wid, "item": {"kind": "table_cell", "row": 0, "column": 0}})
    )

    assert result == {
        "kind": "table_cell",
        "row": 0,
        "column": 0,
        "text": "Open",
        "edit_value": "Pending",
        "selected": False,
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

    assert result == [110, 220, 40, 18]
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


def test_handle_command_item_text_reads_tree_node(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    tree = FakeTreeView(
        [FakeTreeNode("Settings", [FakeTreeNode("General"), FakeTreeNode("Advanced")])],
        rects={
            ("Settings",): FakeRect(4, 6, 60, 16),
            ("Settings", "Advanced"): FakeRect(12, 28, 80, 18),
        },
        expanded_paths={("Settings",)},
    )
    wid = server._registry.register(tree)

    result = server._handle_command(Request(method="item_text", params={"wid": wid, "item": {"kind": "tree_node", "path": ["Settings", "Advanced"]}}))

    assert result == "Advanced"


def test_handle_command_item_properties_reports_tree_state(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    tree = FakeTreeView(
        [FakeTreeNode("Settings", [FakeTreeNode("General"), FakeTreeNode("Advanced")])],
        rects={
            ("Settings",): FakeRect(4, 6, 60, 16),
            ("Settings", "Advanced"): FakeRect(12, 28, 80, 18),
        },
        expanded_paths={("Settings",), ("Settings", "Advanced")},
        selected_paths={("Settings", "Advanced")},
    )
    wid = server._registry.register(tree)

    result = server._handle_command(Request(method="item_properties", params={"wid": wid, "item": {"kind": "tree_node", "path": ["Settings", "Advanced"]}}))

    assert result == {
        "kind": "tree_node",
        "text": "Advanced",
        "path": ["Settings", "Advanced"],
        "expanded": True,
        "selected": True,
    }


def test_handle_command_item_visible_false_when_tree_node_hidden_by_collapsed_ancestor(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    tree = FakeTreeView(
        [FakeTreeNode("Settings", [FakeTreeNode("Advanced")])],
        rects={
            ("Settings",): FakeRect(4, 6, 60, 16),
            ("Settings", "Advanced"): FakeRect(12, 28, 80, 18),
        },
    )
    wid = server._registry.register(tree)

    result = server._handle_command(Request(method="item_visible", params={"wid": wid, "item": {"kind": "tree_node", "path": ["Settings", "Advanced"]}}))

    assert result is False


def test_handle_command_item_click_uses_tree_viewport_local_rect_center(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    tree = FakeTreeView(
        [FakeTreeNode("Settings", [FakeTreeNode("Advanced")])],
        rects={
            ("Settings",): FakeRect(4, 6, 60, 16),
            ("Settings", "Advanced"): FakeRect(12, 28, 80, 18),
        },
        expanded_paths={("Settings",)},
    )
    wid = server._registry.register(tree)

    result = server._handle_command(Request(method="item_click", params={"wid": wid, "item": {"kind": "tree_node", "path": ["Settings", "Advanced"]}}))

    assert result is True
    assert FakeQTest.calls == [
        ("click", tree.viewport(), "left", "none", FakePoint(52, 37))
    ]
    assert tree.scroll_calls == [(("Settings", "Advanced"), ("ensure_visible",))]


def test_handle_command_item_expand_and_collapse_tree_node(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    tree = FakeTreeView(
        [FakeTreeNode("Settings", [FakeTreeNode("Advanced")])],
        rects={("Settings",): FakeRect(4, 6, 60, 16)},
    )
    wid = server._registry.register(tree)

    expand_result = server._handle_command(Request(method="item_expand", params={"wid": wid, "item": {"kind": "tree_node", "path": ["Settings"]}}))
    collapse_result = server._handle_command(Request(method="item_collapse", params={"wid": wid, "item": {"kind": "tree_node", "path": ["Settings"]}}))

    assert expand_result is True
    assert collapse_result is True
    assert tree.expand_calls == [("Settings",)]
    assert tree.collapse_calls == [("Settings",)]


def test_handle_command_item_view_inspect_summarizes_table(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    table = FakeTableView(
        rows=[["001", "Alice"], ["002", "Bob"]],
        headers=["ID", "Name"],
        rects={
            (0, 0): FakeRect(0, 0, 40, 18),
            (0, 1): FakeRect(40, 0, 60, 18),
            (1, 0): FakeRect(0, 18, 40, 18),
            (1, 1): FakeRect(40, 18, 60, 18),
        },
        selected={(1, 1)},
    )
    wid = server._registry.register(table)

    result = server._handle_command(
        Request(method="item_view_inspect", params={"wid": wid, "max_rows": 1, "max_items": 10})
    )

    assert result == {
        "kind": "table",
        "rowCount": 2,
        "columnCount": 2,
        "rowsInspected": 1,
        "columns": [
            {"column": 0, "header": "ID", "hidden": False},
            {"column": 1, "header": "Name", "hidden": False},
        ],
        "items": [
            {"item": {"kind": "table_cell", "row": 0, "column": 0}, "row": 0, "column": 0, "columnHeader": "ID", "text": "001", "visible": True, "selected": False},
            {"item": {"kind": "table_cell", "row": 0, "column": 1}, "row": 0, "column": 1, "columnHeader": "Name", "text": "Alice", "visible": True, "selected": False},
        ],
        "truncated": True,
    }


def test_handle_command_item_view_inspect_includes_table_edit_value(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    table = FakeTableView(
        rows=[["Open", "Alice"]],
        headers=["Status", "Name"],
        edit_rows=[["Pending", None]],
        rects={(0, 0): FakeRect(0, 0, 40, 18), (0, 1): FakeRect(40, 0, 60, 18)},
    )
    wid = server._registry.register(table)

    result = server._handle_command(
        Request(method="item_view_inspect", params={"wid": wid, "max_rows": 1, "max_items": 10})
    )

    assert result["items"][0]["text"] == "Open"
    assert result["items"][0]["edit_value"] == "Pending"
    assert "edit_value" not in result["items"][1]


def test_handle_command_item_view_inspect_prefers_live_editor_value(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    table = FakeTableView(
        rows=[["Active", "Alice"]],
        headers=["Status", "Name"],
        edit_rows=[["Active", None]],
        editors={(0, 0): FakeComboEditor("Pending")},
        rects={(0, 0): FakeRect(0, 0, 40, 18), (0, 1): FakeRect(40, 0, 60, 18)},
    )
    wid = server._registry.register(table)

    properties = server._handle_command(
        Request(method="item_properties", params={"wid": wid, "item": {"kind": "table_cell", "row": 0, "column": 0}})
    )
    inspection = server._handle_command(
        Request(method="item_view_inspect", params={"wid": wid, "max_rows": 1, "max_items": 10})
    )

    assert properties["text"] == "Active"
    assert properties["edit_value"] == "Pending"
    assert inspection["items"][0]["text"] == "Active"
    assert inspection["items"][0]["edit_value"] == "Pending"


def test_handle_command_item_view_inspect_accepts_qtableview_subclass(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    table = FakeDerivedTableView(
        rows=[["001", "Alice"]],
        headers=["ID", "Name"],
        rects={(0, 0): FakeRect(0, 0, 40, 18), (0, 1): FakeRect(40, 0, 60, 18)},
    )
    wid = server._registry.register(table)

    result = server._handle_command(
        Request(method="item_view_inspect", params={"wid": wid, "max_rows": 1, "max_items": 10})
    )

    assert result["kind"] == "table"
    assert result["items"][0]["text"] == "001"


def test_handle_command_item_text_reads_tab_item(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    tabs = FakeTabWidget(["Login", "Data", "Settings"], page_object_names=["tab_login", "tab_data", "tab_settings"])
    wid = server._registry.register(tabs)

    result = server._handle_command(
        Request(method="item_text", params={"wid": wid, "item": {"kind": "tab_item", "label": "Data"}})
    )

    assert result == "Data"


def test_handle_command_item_properties_and_click_support_tab_item(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    tabs = FakeTabWidget(["Login", "Data", "Settings"], current_index=0, page_object_names=["tab_login", "tab_data", "tab_settings"])
    wid = server._registry.register(tabs)

    properties_before = server._handle_command(
        Request(method="item_properties", params={"wid": wid, "item": {"kind": "tab_item", "index": 1}})
    )
    selected_before = server._handle_command(
        Request(method="item_selected", params={"wid": wid, "item": {"kind": "tab_item", "index": 1}})
    )
    click_result = server._handle_command(
        Request(method="item_click", params={"wid": wid, "item": {"kind": "tab_item", "label": "Data"}})
    )
    selected_after = server._handle_command(
        Request(method="item_selected", params={"wid": wid, "item": {"kind": "tab_item", "index": 1}})
    )

    assert properties_before == {
        "kind": "tab_item",
        "index": 1,
        "text": "Data",
        "visible": True,
        "selected": False,
        "enabled": True,
        "pageObjectName": "tab_data",
    }
    assert selected_before is False
    assert click_result is True
    assert selected_after is True
    assert tabs.currentIndex() == 1


def test_handle_command_item_click_clicks_tab_item(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    tabs = FakeTabWidget(["Login", "Data"], rects={1: FakeRect(90, 0, 80, 24)})
    wid = server._registry.register(tabs)

    result = server._handle_command(
        Request(method="item_click", params={"wid": wid, "item": {"kind": "tab_item", "index": 1}})
    )

    assert result is True
    assert FakeQTest.calls == [("click", tabs.tabBar(), "left", "none", FakePoint(130, 12))]


def test_handle_command_item_view_inspect_summarizes_tabs(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    tabs = FakeTabWidget(
        ["Login", "Data", "Settings"],
        current_index=1,
        hidden_indices={2},
        page_object_names=["tab_login", "tab_data", "tab_settings"],
    )
    wid = server._registry.register(tabs)

    result = server._handle_command(
        Request(method="item_view_inspect", params={"wid": wid, "max_items": 10, "include_hidden": False})
    )

    assert result == {
        "kind": "tab",
        "maxItems": 10,
        "items": [
            {
                "item": {"kind": "tab_item", "index": 0},
                "index": 0,
                "text": "Login",
                "visible": True,
                "selected": False,
                "enabled": True,
                "pageObjectName": "tab_login",
            },
            {
                "item": {"kind": "tab_item", "index": 1},
                "index": 1,
                "text": "Data",
                "visible": True,
                "selected": True,
                "enabled": True,
                "pageObjectName": "tab_data",
            },
        ],
        "truncated": False,
    }


def test_handle_command_item_view_inspect_accepts_qtabwidget_subclass(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    tabs = FakeDerivedTabWidget(["Login", "Data"], page_object_names=["tab_login", "tab_data"])
    wid = server._registry.register(tabs)

    result = server._handle_command(
        Request(method="item_view_inspect", params={"wid": wid, "max_items": 10})
    )

    assert result["kind"] == "tab"
    assert result["items"][1]["text"] == "Data"


def test_handle_command_item_view_inspect_summarizes_tree(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    tree = FakeTreeView(
        [FakeTreeNode("Settings", [FakeTreeNode("General"), FakeTreeNode("Advanced")])],
        rects={
            ("Settings",): FakeRect(4, 6, 60, 16),
            ("Settings", "Advanced"): FakeRect(12, 28, 80, 18),
        },
        expanded_paths={("Settings",)},
        selected_paths={("Settings", "Advanced")},
    )
    wid = server._registry.register(tree)

    result = server._handle_command(
        Request(method="item_view_inspect", params={"wid": wid, "max_depth": 2, "max_items": 10})
    )

    assert result == {
        "kind": "tree",
        "maxDepth": 2,
        "items": [
            {"item": {"kind": "tree_node", "path": [0]}, "depth": 0, "text": "Settings", "labelPath": ["Settings"], "visible": True, "selected": False, "expanded": True, "hasChildren": True},
            {"item": {"kind": "tree_node", "path": [0, 1]}, "depth": 1, "text": "Advanced", "labelPath": ["Settings", "Advanced"], "visible": True, "selected": True, "expanded": False, "hasChildren": False},
        ],
        "truncated": False,
    }


def test_handle_command_item_view_inspect_includes_tree_edit_value(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    tree = FakeTreeView(
        [FakeTreeNode("Settings", [FakeTreeNode("Advanced", edit_text="Advanced Draft")])],
        rects={
            ("Settings",): FakeRect(4, 6, 60, 16),
            ("Settings", "Advanced"): FakeRect(12, 28, 80, 18),
        },
        expanded_paths={("Settings",)},
    )
    wid = server._registry.register(tree)

    result = server._handle_command(
        Request(method="item_view_inspect", params={"wid": wid, "max_depth": 2, "max_items": 10})
    )

    assert result["items"][1]["text"] == "Advanced"
    assert result["items"][1]["edit_value"] == "Advanced Draft"


def test_handle_command_item_view_inspect_accepts_qtreeview_subclass(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    tree = FakeDerivedTreeView(
        [FakeTreeNode("Settings", [FakeTreeNode("Advanced")])],
        rects={
            ("Settings",): FakeRect(4, 6, 60, 16),
            ("Settings", "Advanced"): FakeRect(12, 28, 80, 18),
        },
        expanded_paths={("Settings",)},
    )
    wid = server._registry.register(tree)

    result = server._handle_command(
        Request(method="item_view_inspect", params={"wid": wid, "max_depth": 2, "max_items": 10})
    )

    assert result["kind"] == "tree"
    assert result["items"][0]["text"] == "Settings"


def test_handle_command_item_view_inspect_summarizes_list(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    list_view = FakeListView(
        ["Alpha", "Beta", "Gamma"],
        rects={0: FakeRect(0, 0, 50, 18), 1: FakeRect(0, 18, 50, 18)},
        selected_rows={1},
    )
    wid = server._registry.register(list_view)

    result = server._handle_command(
        Request(method="item_view_inspect", params={"wid": wid, "max_rows": 2, "max_items": 10})
    )

    assert result == {
        "kind": "list",
        "rowCount": 3,
        "rowsInspected": 2,
        "items": [
            {"item": {"kind": "list_item", "row": 0}, "row": 0, "text": "Alpha", "visible": True, "selected": False},
            {"item": {"kind": "list_item", "row": 1}, "row": 1, "text": "Beta", "visible": True, "selected": True},
        ],
        "truncated": True,
    }


def test_handle_command_item_view_inspect_includes_list_edit_value(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    list_view = FakeListView(
        ["Alpha", "Beta"],
        edit_items=[None, "Beta (editing)"],
        rects={0: FakeRect(0, 0, 50, 18), 1: FakeRect(0, 18, 50, 18)},
    )
    wid = server._registry.register(list_view)

    result = server._handle_command(
        Request(method="item_view_inspect", params={"wid": wid, "max_rows": 2, "max_items": 10})
    )

    assert "edit_value" not in result["items"][0]
    assert result["items"][1]["text"] == "Beta"
    assert result["items"][1]["edit_value"] == "Beta (editing)"


def test_handle_command_item_text_rejects_ambiguous_tree_path_segment(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    tree = FakeTreeView(
        [FakeTreeNode("Settings", [FakeTreeNode("Advanced"), FakeTreeNode("Advanced")])],
        rects={("Settings",): FakeRect(4, 6, 60, 16)},
        expanded_paths={("Settings",)},
    )
    wid = server._registry.register(tree)

    with pytest.raises(ValueError, match="Ambiguous tree path segment: Advanced"):
        server._handle_command(Request(method="item_text", params={"wid": wid, "item": {"kind": "tree_node", "path": ["Settings", "Advanced"]}}))


def test_handle_command_item_text_accepts_qtreeview_subclass(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    tree = FakeDerivedTreeView(
        [FakeTreeNode("Settings", [FakeTreeNode("Advanced")])],
        rects={
            ("Settings",): FakeRect(4, 6, 60, 16),
            ("Settings", "Advanced"): FakeRect(12, 28, 80, 18),
        },
        expanded_paths={("Settings",)},
    )
    wid = server._registry.register(tree)

    result = server._handle_command(
        Request(method="item_text", params={"wid": wid, "item": {"kind": "tree_node", "path": ["Settings", "Advanced"]}})
    )

    assert result == "Advanced"


def test_handle_command_item_text_reads_list_item(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    list_view = FakeListView(
        ["Alpha", "Beta", "Gamma"],
        rects={1: FakeRect(8, 16, 70, 18)},
    )
    wid = server._registry.register(list_view)

    result = server._handle_command(Request(method="item_text", params={"wid": wid, "item": {"kind": "list_item", "row": 1}}))

    assert result == "Beta"


def test_handle_command_item_text_accepts_qlistview_subclass(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    list_view = FakeDerivedListView(
        ["Alpha", "Beta", "Gamma"],
        rects={1: FakeRect(8, 16, 70, 18)},
    )
    wid = server._registry.register(list_view)

    result = server._handle_command(
        Request(method="item_text", params={"wid": wid, "item": {"kind": "list_item", "row": 1}})
    )

    assert result == "Beta"


def test_handle_command_item_properties_resolves_list_item_by_text(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    list_view = FakeListView(
        ["Alpha", "Beta", "Gamma"],
        rects={1: FakeRect(8, 16, 70, 18)},
        selected_rows={1},
    )
    wid = server._registry.register(list_view)

    result = server._handle_command(Request(method="item_properties", params={"wid": wid, "item": {"kind": "list_item", "text": "Beta"}}))

    assert result == {
        "kind": "list_item",
        "row": 1,
        "text": "Beta",
        "selected": True,
    }


def test_handle_command_item_visible_false_for_hidden_list_row(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    list_view = FakeListView(
        ["Alpha", "Beta"],
        rects={1: FakeRect(8, 16, 70, 18)},
        hidden_rows={1},
    )
    wid = server._registry.register(list_view)

    result = server._handle_command(Request(method="item_visible", params={"wid": wid, "item": {"kind": "list_item", "row": 1}}))

    assert result is False


def test_handle_command_item_text_rejects_ambiguous_list_text(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    list_view = FakeListView(
        ["Alpha", "Beta", "Beta"],
        rects={1: FakeRect(8, 16, 70, 18), 2: FakeRect(8, 40, 70, 18)},
    )
    wid = server._registry.register(list_view)

    with pytest.raises(ValueError, match="Ambiguous list item text: Beta"):
        server._handle_command(Request(method="item_text", params={"wid": wid, "item": {"kind": "list_item", "text": "Beta"}}))


def test_handle_command_item_click_uses_list_viewport_local_rect_center(monkeypatch):
    _install_fake_item_view_qt(monkeypatch)
    server._registry.clear()
    list_view = FakeListView(
        ["Alpha", "Beta", "Gamma"],
        rects={1: FakeRect(8, 16, 70, 18)},
    )
    wid = server._registry.register(list_view)

    result = server._handle_command(Request(method="item_click", params={"wid": wid, "item": {"kind": "list_item", "text": "Beta"}}))

    assert result is True
    assert FakeQTest.calls == [
        ("click", list_view.viewport(), "left", "none", FakePoint(43, 25))
    ]
    assert list_view.scroll_calls == [(1, ("ensure_visible",))]