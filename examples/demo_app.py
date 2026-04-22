"""Demo Qt application with QPlaywright agent embedded.

Run this first, then run test_demo.py in another terminal to automate it.

    python examples/demo_app.py
"""

import os
import sys
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
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
    QListWidget,
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


class PaymentReviewDialog(QDialog):
    reviewSubmitted = Signal(dict)
    reviewCancelled = Signal()

    def __init__(self, *, payment_snapshot, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Payment Review")
        self.setObjectName("payment_review_dialog")
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumWidth(460)
        self._payment_snapshot = dict(payment_snapshot)

        layout = QVBoxLayout(self)

        summary_group = QGroupBox("Payment Summary")
        summary_layout = QVBoxLayout(summary_group)
        self.summary_label = QLabel(self._payment_snapshot["summary"])
        self.summary_label.setObjectName("dialog_payment_summary")
        self.summary_label.setWordWrap(True)
        self.snapshot_label = QLabel(
            f"currency={self._payment_snapshot['currency']} amount={self._payment_snapshot['amount']} precision={self._payment_snapshot['precision']}"
        )
        self.snapshot_label.setObjectName("dialog_payment_snapshot")
        self.snapshot_label.setWordWrap(True)
        summary_layout.addWidget(self.summary_label)
        summary_layout.addWidget(self.snapshot_label)
        layout.addWidget(summary_group)

        form_group = QGroupBox("Review Decision")
        form_layout = QVBoxLayout(form_group)

        code_row = QHBoxLayout()
        code_row.addWidget(QLabel("Approval code:"))
        self.approval_code_input = QLineEdit()
        self.approval_code_input.setObjectName("approval_code")
        self.approval_code_input.setPlaceholderText("APR-2026-001")
        code_row.addWidget(self.approval_code_input)
        form_layout.addLayout(code_row)

        risk_row = QHBoxLayout()
        risk_row.addWidget(QLabel("Risk level:"))
        self.risk_combo = QComboBox()
        self.risk_combo.setObjectName("review_risk")
        self.risk_combo.addItems(["Low", "Medium", "High"])
        risk_row.addWidget(self.risk_combo)
        form_layout.addLayout(risk_row)

        self.escalate_check = QCheckBox("Escalate to finance control")
        self.escalate_check.setObjectName("review_escalate")
        form_layout.addWidget(self.escalate_check)

        self.review_notes_input = QTextEdit()
        self.review_notes_input.setObjectName("review_notes_dialog")
        self.review_notes_input.setPlaceholderText("Explain why this payment should be approved or rejected...")
        self.review_notes_input.setFixedHeight(90)
        form_layout.addWidget(self.review_notes_input)

        layout.addWidget(form_group)

        self.result_label = QLabel("Decision: waiting")
        self.result_label.setObjectName("dialog_result")
        layout.addWidget(self.result_label)

        button_row = QHBoxLayout()
        self.approve_btn = QPushButton("Approve")
        self.approve_btn.setObjectName("approve_review_btn")
        self.approve_btn.clicked.connect(lambda: self._submit("approved"))
        button_row.addWidget(self.approve_btn)

        self.reject_btn = QPushButton("Reject")
        self.reject_btn.setObjectName("reject_review_btn")
        self.reject_btn.clicked.connect(lambda: self._submit("rejected"))
        button_row.addWidget(self.reject_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("cancel_review_btn")
        self.cancel_btn.clicked.connect(self._cancel)
        button_row.addWidget(self.cancel_btn)

        layout.addLayout(button_row)

    def _payload(self, decision):
        return {
            "decision": decision,
            "approvalCode": self.approval_code_input.text().strip(),
            "risk": self.risk_combo.currentText(),
            "escalate": self.escalate_check.isChecked(),
            "notes": self.review_notes_input.toPlainText().strip(),
            "paymentSummary": self._payment_snapshot["summary"],
        }

    def _submit(self, decision):
        payload = self._payload(decision)
        self.result_label.setText(
            f"Decision: {decision} code={payload['approvalCode'] or '<empty>'} risk={payload['risk']} escalate={payload['escalate']}"
        )
        self.reviewSubmitted.emit(payload)
        self.close()

    def _cancel(self):
        self.result_label.setText("Decision: cancelled")
        self.reviewCancelled.emit()
        self.close()


class DemoWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.review_dialog = None
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

        self.review_status_label = QLabel("Review: Not started")
        self.review_status_label.setObjectName("review_status")
        self.review_status_label.setWordWrap(True)
        layout.addWidget(self.review_status_label)

        self.scroll_status_label = QLabel("Scroll: top")
        self.scroll_status_label.setObjectName("scroll_status")
        self.scroll_status_label.setWordWrap(True)
        layout.addWidget(self.scroll_status_label)

        self.scroll_list = QListWidget()
        self.scroll_list.setObjectName("scroll_list")
        self.scroll_list.setFixedHeight(120)
        self.scroll_list.addItems([f"Scrollable item {index:03d}" for index in range(1, 101)])
        layout.addWidget(self.scroll_list)

        # --- Log area ---
        self.log_area = QTextEdit()
        self.log_area.setObjectName("log")
        self.log_area.setReadOnly(True)
        self.log_area.setPlaceholderText("Logs will appear here...")
        self._seed_scroll_log()
        layout.addWidget(self.log_area)

        # --- Action buttons ---
        btn_row = QHBoxLayout()
        self.clear_btn = QPushButton("Clear Log")
        self.clear_btn.setObjectName("clear_btn")
        self.clear_btn.clicked.connect(self._on_clear_log)
        btn_row.addWidget(self.clear_btn)

        self.review_btn = QPushButton("Review Payment")
        self.review_btn.setObjectName("review_btn")
        self.review_btn.clicked.connect(self._open_review_dialog)
        btn_row.addWidget(self.review_btn)

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
        self.scroll_list.verticalScrollBar().valueChanged.connect(self._update_scroll_status)
        self._update_scroll_status()
        QTimer.singleShot(0, self._update_scroll_status)
        self._update_summary()

    def _seed_scroll_log(self):
        lines = [f"[TRACE] Scroll entry {index:03d}" for index in range(1, 81)]
        self.log_area.setPlainText("\n".join(lines))

    def _update_scroll_status(self):
        bar = self.scroll_list.verticalScrollBar()
        self.scroll_status_label.setText(
            f"Scroll: value={bar.value()} max={bar.maximum()} visible={bar.isVisible()}"
        )

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

    def _open_review_dialog(self):
        if self.review_dialog is not None and self.review_dialog.isVisible():
            self.review_dialog.raise_()
            self.review_dialog.activateWindow()
            return

        dialog = PaymentReviewDialog(payment_snapshot=self.amount_editor.snapshot(), parent=self)
        dialog.reviewSubmitted.connect(self._on_review_submitted)
        dialog.reviewCancelled.connect(self._on_review_cancelled)
        dialog.finished.connect(self._on_review_finished)
        self.review_dialog = dialog
        dialog.open()
        self.log_area.append(f"[INFO] Opened payment review dialog for {self.amount_editor.summary()}")
        self.review_status_label.setText(f"Review: Open for {self.amount_editor.summary()}")

    def _on_review_submitted(self, payload):
        self.review_status_label.setText(
            f"Review: {payload['decision']} code={payload['approvalCode'] or '<empty>'} risk={payload['risk']} escalate={payload['escalate']}"
        )
        self.status_label.setText(
            f"Status: Review {payload['decision']} for {payload['paymentSummary']}"
        )
        self.log_area.append(
            f"[INFO] Review {payload['decision']}: code={payload['approvalCode'] or '<empty>'}, risk={payload['risk']}, escalate={payload['escalate']}, notes={payload['notes'] or '<empty>'}"
        )

    def _on_review_cancelled(self):
        self.review_status_label.setText("Review: Cancelled")
        self.status_label.setText("Status: Review cancelled")
        self.log_area.append("[INFO] Review dialog cancelled")

    def _on_review_finished(self, _result):
        self.review_dialog = None

    def _on_clear_log(self):
        self._seed_scroll_log()
        self.amount_editor.clearAmount()
        self.notes_input.clear()
        self.status_label.setText("Status: Log cleared")
        self.review_status_label.setText("Review: Not started")
        self._update_scroll_status()
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
