from __future__ import annotations

from typing import Any, cast

import qplaywright.agent._server as server
import qplaywright.agent._selector as selector
from qplaywright.protocol import QPlaywrightClassMetadata, QPlaywrightClassMethod, QPlaywrightMethodArg


class FakeMetaObject:
    def __init__(self, class_name: str, *, super_class=None, properties: list[str] | None = None):
        self._class_name = class_name
        self._super_class = super_class
        self._properties = list(properties or [])

    def className(self) -> str:
        return self._class_name

    def superClass(self):
        return self._super_class

    def indexOfProperty(self, name) -> int:
        if isinstance(name, bytes):
            name = name.decode()
        try:
            return self._properties.index(name)
        except ValueError:
            return -1

    def propertyCount(self) -> int:
        return len(self._properties)

    def property(self, index: int):
        return FakeMetaProperty(self._properties[index])


class FakeMetaProperty:
    def __init__(self, name: str):
        self._name = name

    def name(self) -> str:
        return self._name


class FakeWidget:
    def __init__(
        self,
        *,
        class_name: str = "FancyWidget",
        object_name: str = "",
        properties: dict[str, object] | None = None,
        qt_properties: list[str] | None = None,
        dynamic_properties: list[str] | None = None,
        children: list[object] | None = None,
        super_class=None,
    ):
        self._meta = FakeMetaObject(class_name, super_class=super_class, properties=qt_properties)
        self._properties: dict[str, Any] = dict(properties or {})
        self._dynamic_properties = list(dynamic_properties or [])
        self._object_name = object_name
        self._children = list(children or [])

    def metaObject(self):
        return self._meta

    def property(self, name):
        if isinstance(name, bytes):
            name = name.decode()
        return self._properties.get(name)

    def dynamicPropertyNames(self):
        return [name.encode() for name in self._dynamic_properties]

    def objectName(self) -> str:
        return self._object_name

    def isVisible(self) -> bool:
        return True

    def isEnabled(self) -> bool:
        return True

    def children(self) -> list[object]:
        return list(self._children)

    def x(self) -> int:
        return 0

    def y(self) -> int:
        return 0

    def width(self) -> int:
        return 100

    def height(self) -> int:
        return 30

    def accessibleName(self) -> str:
        return str(self._properties.get("accessibleName", ""))

    def accessibleDescription(self) -> str:
        return str(self._properties.get("accessibleDescription", ""))

    def windowTitle(self) -> str:
        return str(self._properties.get("windowTitle", ""))

    def placeholderText(self) -> str:
        return str(self._properties.get("placeholderText", ""))

    def toolTip(self) -> str:
        return str(self._properties.get("toolTip", ""))

    def rect(self):
        return self

    def topLeft(self):
        return self

    def mapToGlobal(self, point):
        return point

    def parentWidget(self):
        return None


class FakeTextWidget(FakeWidget):
    def text(self) -> str:
        return str(self._properties.get("text", ""))


class FakeValueWidget(FakeWidget):
    def value(self):
        return self._properties["value"]


class FakeComboWidget(FakeWidget):
    def currentText(self) -> str:
        return str(self._properties.get("currentText", ""))

    def currentIndex(self) -> int:
        return int(cast(int, self._properties.get("currentIndex", -1)))


class FakeActionLike:
    def isVisible(self) -> bool:
        return True

    def children(self):
        raise AssertionError("non-widget children should not be traversed")


class FakeScreenWidget(FakeWidget):
    def __init__(self, *, parent=None, visible: bool = True, screen_visible: bool = True, **kwargs):
        super().__init__(**kwargs)
        self._parent = parent
        self._visible = visible
        self._screen_visible = screen_visible

    def isVisible(self) -> bool:
        return self._visible

    def parentWidget(self):
        return self._parent


def _metadata(*, role: str = "", methods: list[dict] | None = None) -> QPlaywrightClassMetadata:
    metadata = QPlaywrightClassMetadata().role(role)
    for method in methods or []:
        builder = QPlaywrightClassMethod()
        builder.name(method.get("name", ""))
        builder.returnType(method.get("returnType", "QVariant"))
        builder.brief(method.get("brief", ""))
        for arg in method.get("args", []):
            arg_builder = (
                QPlaywrightMethodArg()
                .name(arg.get("name", ""))
                .type(arg.get("type", "QVariant"))
                .brief(arg.get("brief", ""))
                .required(arg.get("required", True))
            )
            if "defaultValue" in arg:
                arg_builder.defaultValue(arg["defaultValue"])
            builder.addArg(arg_builder)
        metadata.addMethod(builder)
    return metadata


def test_custom_role_metadata_matches_selector():
    widget = FakeWidget(properties={"qplaywrightClassMetadata": _metadata(role="textbox")})

    assert selector.match_widget(widget, "role=textbox") is True
    assert selector.match_widget(widget, "role=input") is False


def test_declared_method_schema_reads_custom_widget_metadata():
    widget = FakeWidget(
        properties={
            "qplaywrightClassMetadata": _metadata(
                role="textbox",
                methods=[
                    {
                        "name": "setAmount",
                        "returnType": "void",
                        "brief": "Set amount",
                        "args": [
                            {
                                "name": "value",
                                "type": "QString",
                                "required": True,
                            }
                        ],
                    }
                ],
            )
        }
    )

    payload = selector._declared_method_schema(widget)

    assert payload == [
        {
            "name": "setAmount",
            "returnType": "void",
            "brief": "Set amount",
            "args": [
                {
                    "name": "value",
                    "type": "QString",
                    "brief": "",
                    "required": True,
                    "defaultValue": None,
                }
            ],
        }
    ]


def test_widget_to_dict_includes_custom_role_from_class_metadata():
    widget = FakeValueWidget(
        properties={
            "qplaywrightClassMetadata": _metadata(role="combobox"),
            "value": "Admin",
        }
    )

    payload = selector.widget_to_dict(widget, max_depth=0)

    assert payload["roles"] == ["combobox"]
    assert payload["value"] == "Admin"


def test_widget_to_dict_marks_item_view_owner_for_discovery():
    qt_widget = FakeMetaObject("QWidget")
    abstract_scroll_area = FakeMetaObject("QAbstractScrollArea", super_class=qt_widget)
    abstract_item_view = FakeMetaObject("QAbstractItemView", super_class=abstract_scroll_area)
    table_view = FakeMetaObject("QTableView", super_class=abstract_item_view)
    widget = FakeWidget(class_name="FancyOrdersTable", super_class=table_view)

    payload = selector.widget_to_dict(widget, max_depth=0)

    assert payload["itemView"] == {"kind": "table", "discoverableBy": "inspect_items"}


def test_widget_text_still_uses_standard_accessors():
    widget = FakeTextWidget(properties={"text": "Fancy Value"})

    assert selector._widget_text(widget) == "Fancy Value"


def test_text_and_a11y_selectors_stay_separate():
    a11y_only = FakeWidget(properties={"accessibleName": "Power Sweep", "accessibleDescription": "切换测量类型"})
    visible_text = FakeTextWidget(properties={"text": "Power Sweep"})

    assert selector.match_widget(a11y_only, "text=Power Sweep") is False
    assert selector.match_widget(a11y_only, "a11y-name=Power Sweep") is True
    assert selector.match_widget(a11y_only, "a11y-desc=切换测量类型") is True
    assert selector.match_widget(visible_text, "a11y-name=Power Sweep") is False


def test_widget_to_dict_keeps_a11y_and_title_fields_distinct_from_text():
    widget = FakeWidget(
        object_name="scan_btn",
        properties={
            "accessibleName": "功率扫描",
            "accessibleDescription": "切换测量类型为功率扫描",
            "windowTitle": "ignored-title",
            "toolTip": "tooltip",
        },
    )

    payload = selector.widget_to_dict(widget, max_depth=0)

    assert "text" not in payload
    assert payload["objectName"] == "scan_btn"
    assert payload["accessibleName"] == "功率扫描"
    assert payload["accessibleDescription"] == "切换测量类型为功率扫描"
    assert payload["windowTitle"] == "ignored-title"
    assert payload["toolTip"] == "tooltip"


def test_widget_to_dict_preserves_current_index_without_rewriting_current_text_as_text():
    widget = FakeComboWidget(properties={"currentText": "Admin", "currentIndex": 0})

    payload = selector.widget_to_dict(widget, max_depth=0)

    assert "text" not in payload
    assert payload["currentText"] == "Admin"
    assert payload["currentIndex"] == 0


def test_find_widgets_skips_non_widget_children():
    widget = FakeWidget(object_name="root", children=[FakeActionLike()])

    results = selector.find_widgets([widget], "name=root", visible_only=False)

    assert results == [widget]


def test_find_widgets_payload_returns_match_reason_and_ancestor_summary():
    server._registry.clear()
    submit = FakeTextWidget(class_name="QPushButton", object_name="submit_btn", properties={"text": "Submit"})
    panel = FakeWidget(class_name="QGroupBox", object_name="payment_panel", children=[submit])
    root = FakeWidget(class_name="DemoWindow", object_name="main_window", children=[panel])
    root_wid = server._registry.register(root)

    payload = server._find_widgets_payload(
        {
            "wid": root_wid,
            "role": "button",
            "keyword": "submt",
            "limit": 5,
        }
    )

    assert payload["rootWid"] == root_wid
    assert payload["count"] == 1
    assert payload["truncated"] is False
    assert payload["results"] == [
        {
            "wid": server._registry.register(submit),
            "class": "QPushButton",
            "objectName": "submit_btn",
            "text": "Submit",
            "visible": True,
            "enabled": True,
            "geometry": [0, 0, 100, 30],
            "interactable": False,
            "matchReason": ["role=button", "keyword~=submt via text:fuzzy"],
            "ancestorSummary": [
                {
                    "wid": root_wid,
                    "class": "DemoWindow",
                    "visible": True,
                    "enabled": True,
                    "geometry": [0, 0, 100, 30],
                    "objectName": "main_window",
                },
                {
                    "wid": server._registry.register(panel),
                    "class": "QGroupBox",
                    "visible": True,
                    "enabled": True,
                    "geometry": [0, 0, 100, 30],
                    "objectName": "payment_panel",
                },
            ],
        }
    ]


def test_find_widgets_payload_applies_limit_and_truncated_flag():
    server._registry.clear()
    root = FakeWidget(
        class_name="DemoWindow",
        object_name="main_window",
        children=[
            FakeTextWidget(class_name="QPushButton", object_name="submit_btn", properties={"text": "Submit"}),
            FakeTextWidget(class_name="QPushButton", object_name="confirm_btn", properties={"text": "Submit"}),
        ],
    )
    root_wid = server._registry.register(root)

    payload = server._find_widgets_payload(
        {
            "wid": root_wid,
            "role": "button",
            "keyword": "submit",
            "limit": 1,
        }
    )

    assert payload["count"] == 1
    assert payload["truncated"] is True
    assert len(payload["results"]) == 1


def test_widget_to_dict_skips_non_widget_children():
    child = FakeTextWidget(object_name="child", properties={"text": "Save"})
    widget = FakeWidget(object_name="root", children=[child, FakeActionLike()])

    payload = selector.widget_to_dict(widget, max_depth=1)

    assert [entry["objectName"] for entry in payload["children"]] == ["child"]


def test_widget_tree_snapshot_skips_non_widget_children():
    server._registry.clear()
    child = FakeTextWidget(object_name="child", properties={"text": "Save"})
    widget = FakeWidget(object_name="root", children=[child, FakeActionLike()])

    payload = server._widget_tree_to_dict(widget, max_depth=1)

    assert [entry["objectName"] for entry in payload["children"]] == ["child"]


def test_widget_tree_snapshot_captures_live_delegate_editor_widget():
    server._registry.clear()
    viewport = FakeWidget(class_name="QWidget", object_name="table_viewport")
    table = FakeWidget(class_name="QTableView", object_name="orders_table", children=[viewport])

    before = server._widget_tree_to_dict(table, max_depth=2)

    assert before["objectName"] == "orders_table"
    assert before["children"][0]["objectName"] == "table_viewport"
    assert before["children"][0].get("children") is None

    editor = FakeComboWidget(
        class_name="QComboBox",
        object_name="status_editor",
        properties={"currentText": "Ready", "accessibleName": "Status editor"},
    )
    viewport._children.append(editor)

    after = server._widget_tree_to_dict(table, max_depth=2)

    editor_payload = after["children"][0]["children"][0]
    assert editor_payload["class"] == "QComboBox"
    assert editor_payload["objectName"] == "status_editor"
    assert editor_payload["currentText"] == "Ready"
    assert editor_payload["accessibleName"] == "Status editor"


def test_widget_tree_snapshot_screen_visible_only_filters_hidden_descendants(monkeypatch):
    server._registry.clear()
    root = FakeScreenWidget(class_name="QWidget", object_name="root")
    visible_child = FakeScreenWidget(class_name="QPushButton", object_name="visible_child", parent=root)
    hidden_child = FakeScreenWidget(class_name="QPushButton", object_name="hidden_child", parent=root, screen_visible=False)
    root._children = [visible_child, hidden_child]

    monkeypatch.setattr(server, "_is_topmost_visible_widget", lambda widget: getattr(widget, "_screen_visible", True))

    payload = server._widget_tree_to_dict(root, max_depth=1, screen_visible_only=True)

    assert [entry["objectName"] for entry in payload["children"]] == ["visible_child"]


def test_widget_properties_include_qt_and_dynamic_properties():
    widget = FakeWidget(
        properties={
            "text": "Painter label",
            "myText": "pressme",
            "qplaywrightClassMetadata": _metadata(role="button"),
        },
        qt_properties=["text", "qplaywrightClassMetadata"],
        dynamic_properties=["myText"],
    )

    payload = selector._widget_properties(widget)

    assert payload["text"] == "Painter label"
    assert payload["myText"] == "pressme"
    metadata = cast(dict[str, object], payload["qplaywrightClassMetadata"])
    assert metadata["role"] == "button"