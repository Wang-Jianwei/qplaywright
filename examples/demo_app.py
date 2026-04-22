"""Demo Qt application with QPlaywright agent embedded.

Run this first, then run test_demo.py in another terminal to automate it.

    python examples/demo_app.py
"""

import os
import sys
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QComboBox,
    QTextEdit,
    QGroupBox,
)

# Import QPlaywright agent
sys.path.insert(0, ".")
from qplaywright import QPlaywrightClassMetadata, QPlaywrightClassMethod, QPlaywrightMethodArg, start_agent


class FancyAmountEdit(QWidget):
    stateChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._amount_value = 0.0
        self._currency = "USD"
        self._precision = 2
        self._adjustments_enabled = True
        self._available_currencies = ["USD", "EUR", "CNY", "JPY"]
        self.setAccessibleName("Amount editor")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)

        caption = QLabel("Amount:")
        self.value_label = QLabel()
        self.value_label.setObjectName("amount_value")
        self.value_label.setMinimumWidth(90)
        self.currency_label = QLabel()
        self.currency_label.setObjectName("amount_currency")
        self.precision_label = QLabel()
        self.precision_label.setObjectName("amount_precision")
        self.mode_label = QLabel()
        self.mode_label.setObjectName("amount_mode")

        top_row.addWidget(caption)
        top_row.addWidget(self.value_label, 1)
        top_row.addWidget(self.currency_label)
        top_row.addWidget(self.precision_label)
        top_row.addWidget(self.mode_label)

        self.hint_label = QLabel("invoke(setCurrency/setPrecision/applyDelta/summary/snapshot)")
        self.hint_label.setWordWrap(True)
        self.state_label = QLabel()
        self.state_label.setObjectName("amount_state")
        self.state_label.setWordWrap(True)

        layout.addLayout(top_row)
        layout.addWidget(self.hint_label)
        layout.addWidget(self.state_label)

        metadata = QPlaywrightClassMetadata()
        metadata.role("textbox").addMethod(
            QPlaywrightClassMethod().name("amount").returnType("QString").brief("Return the current amount string")
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
        ).addMethod(
            QPlaywrightClassMethod().name("clearAmount").returnType("void").brief("Reset the amount to 0.00")
        ).addMethod(
            QPlaywrightClassMethod().name("currency").returnType("QString").brief("Return the active currency code")
        ).addMethod(
            QPlaywrightClassMethod()
            .name("setCurrency")
            .addArg(
                QPlaywrightMethodArg()
                .name("code")
                .type("QString")
                .brief("ISO-like currency code")
                .required(True)
            )
            .returnType("void")
            .brief("Set the active currency code")
        ).addMethod(
            QPlaywrightClassMethod()
            .name("availableCurrencies")
            .returnType("QStringList")
            .brief("Return all supported currency codes")
        ).addMethod(
            QPlaywrightClassMethod().name("precision").returnType("int").brief("Return the active precision")
        ).addMethod(
            QPlaywrightClassMethod()
            .name("setPrecision")
            .addArg(
                QPlaywrightMethodArg()
                .name("digits")
                .type("int")
                .brief("Number of fractional digits")
                .required(True)
            )
            .returnType("void")
            .brief("Set the amount precision")
        ).addMethod(
            QPlaywrightClassMethod()
            .name("adjustmentsEnabled")
            .returnType("bool")
            .brief("Return whether delta adjustments are enabled")
        ).addMethod(
            QPlaywrightClassMethod()
            .name("setAdjustmentsEnabled")
            .addArg(
                QPlaywrightMethodArg()
                .name("enabled")
                .type("bool")
                .brief("Whether delta adjustments are enabled")
                .required(True)
            )
            .returnType("void")
            .brief("Enable or disable delta adjustments")
        ).addMethod(
            QPlaywrightClassMethod()
            .name("applyDelta")
            .addArg(
                QPlaywrightMethodArg()
                .name("delta")
                .type("double")
                .brief("Increment or decrement amount by this delta")
                .required(True)
            )
            .returnType("QString")
            .brief("Apply a delta to the current amount and return the formatted amount")
        ).addMethod(
            QPlaywrightClassMethod().name("summary").returnType("QString").brief("Return a human-readable amount summary")
        ).addMethod(
            QPlaywrightClassMethod().name("snapshot").returnType("QVariant").brief("Return a structured snapshot")
        )
        self.setProperty("qplaywrightClassMetadata", metadata)
        self._refresh_view()

    def _format_amount(self):
        return f"{self._amount_value:.{self._precision}f}"

    def _refresh_view(self):
        amount_text = self._format_amount()
        self.value_label.setText(amount_text)
        self.currency_label.setText(self._currency)
        self.precision_label.setText(f"precision={self._precision}")
        self.mode_label.setText("adjustments=on" if self._adjustments_enabled else "adjustments=off")
        self.state_label.setText(
            f"State: {self._currency} {amount_text} | available={', '.join(self._available_currencies)}"
        )
        self.stateChanged.emit()

    def amount(self):
        return self._format_amount()

    def setAmount(self, value):
        text = str(value).strip()
        self._amount_value = 0.0 if not text else float(text)
        self._refresh_view()

    def clearAmount(self):
        self.setAmount("0.00")

    def currency(self):
        return self._currency

    def setCurrency(self, code):
        normalized = str(code).strip().upper()
        if normalized not in self._available_currencies:
            raise ValueError(f"Unsupported currency: {normalized}")
        self._currency = normalized
        self._refresh_view()

    def availableCurrencies(self):
        return list(self._available_currencies)

    def precision(self):
        return self._precision

    def setPrecision(self, digits):
        digits = int(digits)
        if digits < 0 or digits > 4:
            raise ValueError("Precision must be between 0 and 4")
        self._precision = digits
        self._refresh_view()

    def adjustmentsEnabled(self):
        return self._adjustments_enabled

    def setAdjustmentsEnabled(self, enabled):
        self._adjustments_enabled = bool(enabled)
        self._refresh_view()

    def applyDelta(self, delta):
        if not self._adjustments_enabled:
            raise ValueError("Adjustments are disabled")
        self._amount_value += float(delta)
        self._refresh_view()
        return self.amount()

    def summary(self):
        return f"{self._currency} {self.amount()} precision={self._precision} adjustments={'on' if self._adjustments_enabled else 'off'}"

    def snapshot(self):
        return {
            "amount": self.amount(),
            "currency": self._currency,
            "precision": self._precision,
            "adjustmentsEnabled": self._adjustments_enabled,
            "summary": self.summary(),
        }


class DemoWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QPlaywright Demo App")
        self.setMinimumSize(640, 520)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # --- Login form ---
        login_group = QGroupBox("Login Form")
        login_layout = QVBoxLayout(login_group)

        # Username
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Username:"))
        self.username_input = QLineEdit()
        self.username_input.setObjectName("username")
        self.username_input.setPlaceholderText("Enter username")
        row1.addWidget(self.username_input)
        login_layout.addLayout(row1)

        # Password
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Password:"))
        self.password_input = QLineEdit()
        self.password_input.setObjectName("password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Enter password")
        row2.addWidget(self.password_input)
        login_layout.addLayout(row2)

        # Remember me
        self.remember_check = QCheckBox("Remember me")
        self.remember_check.setObjectName("remember")
        login_layout.addWidget(self.remember_check)

        # Role selector
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Role:"))
        self.role_combo = QComboBox()
        self.role_combo.setObjectName("role")
        self.role_combo.addItems(["User", "Admin", "Moderator"])
        row3.addWidget(self.role_combo)
        login_layout.addLayout(row3)

        row4 = QHBoxLayout()
        row4.addWidget(QLabel("Environment:"))
        self.environment_combo = QComboBox()
        self.environment_combo.setObjectName("environment")
        self.environment_combo.addItems(["Development", "Staging", "Production"])
        row4.addWidget(self.environment_combo)
        login_layout.addLayout(row4)

        row5 = QHBoxLayout()
        row5.addWidget(QLabel("Requested amount:"))
        self.amount_editor = FancyAmountEdit()
        self.amount_editor.setObjectName("amount_editor")
        row5.addWidget(self.amount_editor)
        login_layout.addLayout(row5)

        self.notify_check = QCheckBox("Send audit notification")
        self.notify_check.setObjectName("notify")
        self.notify_check.setChecked(True)
        login_layout.addWidget(self.notify_check)

        self.notes_input = QTextEdit()
        self.notes_input.setObjectName("notes")
        self.notes_input.setPlaceholderText("Add reviewer notes for this login flow...")
        self.notes_input.setFixedHeight(72)
        login_layout.addWidget(self.notes_input)

        # Login button
        self.login_btn = QPushButton("Login")
        self.login_btn.setObjectName("login_btn")
        self.login_btn.clicked.connect(self._on_login)
        login_layout.addWidget(self.login_btn)

        layout.addWidget(login_group)

        # --- Status area ---
        self.status_label = QLabel("Status: Ready")
        self.status_label.setObjectName("status")
        layout.addWidget(self.status_label)

        self.summary_label = QLabel("Summary: Waiting for input")
        self.summary_label.setObjectName("summary")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        # --- Log area ---
        self.log_area = QTextEdit()
        self.log_area.setObjectName("log")
        self.log_area.setReadOnly(True)
        self.log_area.setPlaceholderText("Logs will appear here...")
        layout.addWidget(self.log_area)

        # --- Action buttons ---
        btn_row = QHBoxLayout()
        self.clear_btn = QPushButton("Clear Log")
        self.clear_btn.setObjectName("clear_btn")
        self.clear_btn.clicked.connect(self._on_clear_log)
        btn_row.addWidget(self.clear_btn)

        self.quit_btn = QPushButton("Quit")
        self.quit_btn.setObjectName("quit_btn")
        self.quit_btn.clicked.connect(self.close)
        btn_row.addWidget(self.quit_btn)
        layout.addLayout(btn_row)

        self.username_input.textChanged.connect(self._update_summary)
        self.role_combo.currentTextChanged.connect(self._update_summary)
        self.environment_combo.currentTextChanged.connect(self._update_summary)
        self.remember_check.toggled.connect(self._update_summary)
        self.notify_check.toggled.connect(self._update_summary)
        self.notes_input.textChanged.connect(self._update_summary)
        self.amount_editor.stateChanged.connect(self._update_summary)
        self._update_summary()

    def _update_summary(self):
        username = self.username_input.text().strip() or "<empty>"
        role = self.role_combo.currentText()
        environment = self.environment_combo.currentText()
        payment_summary = self.amount_editor.summary()
        flags = []
        if self.remember_check.isChecked():
            flags.append("remember")
        if self.notify_check.isChecked():
            flags.append("notify")
        notes = self.notes_input.toPlainText().strip()
        note_state = f"notes={len(notes)} chars" if notes else "notes=empty"
        flag_state = ", ".join(flags) if flags else "no-flags"
        self.summary_label.setText(
            f"Summary: user={username} role={role} env={environment} payment={payment_summary} {flag_state} {note_state}"
        )

    def _on_login(self):
        username = self.username_input.text()
        password = self.password_input.text()
        role = self.role_combo.currentText()
        environment = self.environment_combo.currentText()
        remember = self.remember_check.isChecked()
        notify = self.notify_check.isChecked()
        payment_summary = self.amount_editor.summary()
        notes = self.notes_input.toPlainText().strip()

        if not username or not password:
            self.status_label.setText("Status: Please fill all fields")
            self.log_area.append("[ERROR] Missing username or password")
            return

        self.status_label.setText(
            f"Status: Logged in as {username} ({role}) env={environment} payment={payment_summary}"
        )
        self.summary_label.setText(
            f"Summary: last-login user={username} role={role} env={environment} payment={payment_summary} notify={notify}"
        )
        self.log_area.append(
            f"[INFO] Login successful: user={username}, role={role}, env={environment}, payment={payment_summary}, remember={remember}, notify={notify}"
        )
        if notes:
            self.log_area.append(f"[INFO] Reviewer notes: {notes}")

    def _on_clear_log(self):
        self.log_area.clear()
        self.amount_editor.clearAmount()
        self.notes_input.clear()
        self.status_label.setText("Status: Log cleared")
        self._update_summary()


def main():
    app = QApplication(sys.argv)
    port = int(os.environ.get("QPLAYWRIGHT_PORT", "19876"))

    # Start QPlaywright agent on a configurable port for isolated MCP demos.
    server = start_agent(app, port=port)
    print(f"QPlaywright agent started on port {port}")

    window = DemoWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
