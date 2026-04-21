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
    QMessageBox,
)

# Import QPlaywright agent
sys.path.insert(0, ".")
from qplaywright.agent import start_agent


class DemoWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QPlaywright Demo App")
        self.setMinimumSize(500, 400)

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

    def _on_login(self):
        username = self.username_input.text()
        password = self.password_input.text()
        role = self.role_combo.currentText()
        remember = self.remember_check.isChecked()

        if not username or not password:
            self.status_label.setText("Status: Please fill all fields")
            self.log_area.append("[ERROR] Missing username or password")
            return

        self.status_label.setText(f"Status: Logged in as {username} ({role})")
        self.log_area.append(
            f"[INFO] Login successful: user={username}, role={role}, remember={remember}"
        )

    def _on_clear_log(self):
        self.log_area.clear()
        self.status_label.setText("Status: Log cleared")


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
