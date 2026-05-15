# Custom Widgets

QPlaywright now recognizes custom Qt widgets through a single automation
contract stored in the dynamic property `qplaywrightClassMetadata`.

## Recommended Contract

Public authoring should use the builder objects `QPlaywrightClassMetadata`,
`QPlaywrightClassMethod`, and `QPlaywrightMethodArg`.

Their serialized shape contains two top-level fields:

- `role`: one Playwright-style role such as `textbox`, `button`, or `combobox`
- `methods`: a list of raw invoke method declarations

Each method entry follows this shape:

- `name`
- `args`: list of `{name, type, brief, required, defaultValue}`
- `returnType`
- `brief`

This contract describes methods only. It does not describe pointer events,
keyboard events, hover, or scroll behavior. Those stay in the agent's normal
interaction layer.

The runtime exposes method metadata through `locator.methods()` and executes a
method through `locator.invoke(name, args)`.

## C++ Example

```cpp
class FancyAmountEdit : public QWidget {
    Q_OBJECT

public:
    explicit FancyAmountEdit(QWidget *parent = nullptr) : QWidget(parent) {
        QPlaywrightClassMetadata metadata;
        metadata.role("textbox")
            .addMethod(
                QPlaywrightClassMethod()
                    .name("amount")
                    .returnType("QString")
                    .brief("Return the current amount string")
            )
            .addMethod(
                QPlaywrightClassMethod()
                    .name("setAmount")
                    .addArg(
                        QPlaywrightMethodArg()
                            .name("value")
                            .type("QString")
                            .brief("New amount text")
                            .required(true)
                    )
                    .returnType("void")
                    .brief("Set the current amount string")
            );

        setProperty("qplaywrightClassMetadata", QVariant::fromValue(metadata));
    }

    Q_INVOKABLE QString amount() const {
        return m_amount;
    }

    Q_INVOKABLE void setAmount(const QString &value) {
        if (m_amount == value)
            return;
        m_amount = value;
        emit amountChanged(m_amount);
        update();
    }

signals:
    void amountChanged(const QString &value);

private:
    QString m_amount;
};
```

## Python Example

```python
class FancyAmountEdit(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._amount = ""
        metadata = QPlaywrightClassMetadata()
        metadata.role("textbox").addMethod(
            QPlaywrightClassMethod()
            .name("amount")
            .returnType("QString")
            .brief("Return the current amount string")
        ).addMethod(
            QPlaywrightClassMethod()
            .name("setAmount")
            .addArg(
                QPlaywrightMethodArg()
                .name("value")
                .type("QString")
                .brief("New amount text")
                .required(True)
            )
            .returnType("void")
            .brief("Set the current amount string")
        )
        self.setProperty("qplaywrightClassMetadata", metadata)

    def amount(self):
        return self._amount

    def setAmount(self, value):
        self._amount = str(value)
```

## Client Usage

```python
locator = window.locator("role=textbox")
methods = locator.methods()
result = locator.invoke("setAmount", {"value": "123.45"})

assert result == {
    "ok": True,
    "value": None,
    "errorCode": 0,
    "errorMessage": "",
}
```

When invocation fails, the agent returns the same structure with `ok=False` and
an explicit `errorCode` and `errorMessage`.

## Practical Guidance

- Expose one coherent top-level role for the custom widget.
- Keep method names exact and stable. There is no overload resolution.
- Use named arguments only. `invoke()` now sends `{method, args}` where `args`
  is a mapping keyed by parameter name.
- Keep custom domain behavior behind explicit invokable methods such as
  `setAmount`, `summary`, or `commit`.
- `fill()` on standard editable widgets follows keyboard-style replace
    semantics. It is not a direct value setter.
- Do not use `fill()` as a custom behavior escape hatch. For composite widgets,
  expose a method and call `invoke()` instead.
