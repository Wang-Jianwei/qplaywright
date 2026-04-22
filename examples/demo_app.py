"""Demo Qt application with QPlaywright agent embedded.

Run this first, then run test_demo.py in another terminal to automate it.

    python examples/demo_app.py
"""

import sys
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
    def __init__(self, parent=None):
        super().__init__(parent)
        self._amount = "0.00"
        self.setAccessibleName("Amount editor")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        caption = QLabel("Amount:")
        self.value_label = QLabel(self._amount)
        self.value_label.setObjectName("amount_value")
        self.value_label.setMinimumWidth(90)
        self.hint_label = QLabel("Use invoke(setAmount) to update")

        layout.addWidget(caption)
        layout.addWidget(self.value_label, 1)
        layout.addWidget(self.hint_label)

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
        )
        self.setProperty("qplaywrightClassMetadata", metadata)

    def amount(self):
        return self._amount

    def setAmount(self, value):
        text = str(value).strip()
        self._amount = text or "0.00"
        self.value_label.setText(self._amount)

    def clearAmount(self):
        self.setAmount("0.00")


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
        self._update_summary()

    def _update_summary(self):
        username = self.username_input.text().strip() or "<empty>"
        role = self.role_combo.currentText()
        environment = self.environment_combo.currentText()
        amount = self.amount_editor.amount()
        flags = []
        if self.remember_check.isChecked():
            flags.append("remember")
        if self.notify_check.isChecked():
            flags.append("notify")
        notes = self.notes_input.toPlainText().strip()
        note_state = f"notes={len(notes)} chars" if notes else "notes=empty"
        flag_state = ", ".join(flags) if flags else "no-flags"
        self.summary_label.setText(
            f"Summary: user={username} role={role} env={environment} amount={amount} {flag_state} {note_state}"
        )

    def _on_login(self):
        username = self.username_input.text()
        password = self.password_input.text()
        role = self.role_combo.currentText()
        environment = self.environment_combo.currentText()
        remember = self.remember_check.isChecked()
        notify = self.notify_check.isChecked()
        amount = self.amount_editor.amount()
        notes = self.notes_input.toPlainText().strip()

        if not username or not password:
            self.status_label.setText("Status: Please fill all fields")
            self.log_area.append("[ERROR] Missing username or password")
            return

        self.status_label.setText(
            f"Status: Logged in as {username} ({role}) env={environment} amount={amount}"
        )
        self.summary_label.setText(
            f"Summary: last-login user={username} role={role} env={environment} amount={amount} notify={notify}"
        )
        self.log_area.append(
            f"[INFO] Login successful: user={username}, role={role}, env={environment}, amount={amount}, remember={remember}, notify={notify}"
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

    # Start QPlaywright agent on port 19876
    server = start_agent(app, port=19876)
    print("QPlaywright agent started on port 19876")

    window = DemoWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
