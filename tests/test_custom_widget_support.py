from __future__ import annotations

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


class FakeWidget:
    def __init__(
        self,
        *,
        class_name: str = "FancyWidget",
        object_name: str = "",
        properties: dict[str, object] | None = None,
        qt_properties: list[str] | None = None,
        super_class=None,
    ):
        self._meta = FakeMetaObject(class_name, super_class=super_class, properties=qt_properties)
        self._properties = dict(properties or {})
        self._object_name = object_name

    def metaObject(self):
        return self._meta

    def property(self, name):
        if isinstance(name, bytes):
            name = name.decode()
        return self._properties.get(name)

    def objectName(self) -> str:
        return self._object_name

    def isVisible(self) -> bool:
        return True

    def isEnabled(self) -> bool:
        return True

    def children(self) -> list[FakeWidget]:
        return []

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


class FakeTextWidget(FakeWidget):
    def text(self) -> str:
        return str(self._properties.get("text", ""))


class FakeValueWidget(FakeWidget):
    def value(self):
        return self._properties["value"]


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


def test_widget_text_still_uses_standard_accessors():
    widget = FakeTextWidget(properties={"text": "Fancy Value"})

    assert selector._widget_text(widget) == "Fancy Value"