"""Demo Qt application with QPlaywright agent embedded.

Run this first, then run test_demo.py in another terminal to automate it.

    python examples/demo_app.py
"""

import os
import sys
import time
from PySide6.QtCore import Qt, Signal, QTimer, QDateTime
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QComboBox,
    QTextEdit,
    QGroupBox,
    QListWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QProgressBar,
    QSlider,
    QSpinBox,
    QDoubleSpinBox,
    QRadioButton,
    QButtonGroup,
    QDateTimeEdit,
    QColorDialog,
    QFontDialog,
    QMenuBar,
    QMenu,
    QStatusBar,
    QToolBar,
    QDialogButtonBox,
    QMessageBox,
    QFileDialog,
    QTreeWidget,
    QTreeWidgetItem,
    QSplitter,
)
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtTest import QTest

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
        self.state_label.setText(f"State: {self._currency} {amount_text} | available={', '.join(self._available_currencies)}")
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


class SettingsDialog(QDialog):
    settingsChanged = Signal(dict)

    def __init__(self, current_settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setObjectName("settings_dialog")
        self.setModal(True)
        self.setMinimumWidth(500)
        self._current_settings = current_settings

        layout = QVBoxLayout(self)

        general_group = QGroupBox("General")
        general_layout = QFormLayout(general_group)

        self.theme_combo = QComboBox()
        self.theme_combo.setObjectName("settings_theme")
        self.theme_combo.addItems(["Light", "Dark", "System"])
        self.theme_combo.setCurrentText(current_settings.get("theme", "Light"))
        general_layout.addRow("Theme:", self.theme_combo)

        self.language_combo = QComboBox()
        self.language_combo.setObjectName("settings_language")
        self.language_combo.addItems(["English", "Chinese", "Japanese", "German"])
        self.language_combo.setCurrentText(current_settings.get("language", "English"))
        general_layout.addRow("Language:", self.language_combo)

        self.auto_save_check = QCheckBox("Auto-save changes")
        self.auto_save_check.setObjectName("settings_auto_save")
        self.auto_save_check.setChecked(current_settings.get("auto_save", True))
        general_layout.addRow("", self.auto_save_check)

        self.refresh_spin = QSpinBox()
        self.refresh_spin.setObjectName("settings_refresh_interval")
        self.refresh_spin.setRange(1, 60)
        self.refresh_spin.setSuffix(" seconds")
        self.refresh_spin.setValue(current_settings.get("refresh_interval", 5))
        general_layout.addRow("Refresh interval:", self.refresh_spin)

        layout.addWidget(general_group)

        notification_group = QGroupBox("Notifications")
        notification_layout = QFormLayout(notification_group)

        self.notify_email_check = QCheckBox("Email notifications")
        self.notify_email_check.setObjectName("notify_email")
        self.notify_email_check.setChecked(current_settings.get("notify_email", False))
        notification_layout.addRow("", self.notify_email_check)

        self.notify_sms_check = QCheckBox("SMS notifications")
        self.notify_sms_check.setObjectName("notify_sms")
        self.notify_sms_check.setChecked(current_settings.get("notify_sms", False))
        notification_layout.addRow("", self.notify_sms_check)

        self.notify_push_check = QCheckBox("Push notifications")
        self.notify_push_check.setObjectName("notify_push")
        self.notify_push_check.setChecked(current_settings.get("notify_push", False))
        notification_layout.addRow("", self.notify_push_check)

        self.notification_level_combo = QComboBox()
        self.notification_level_combo.setObjectName("notification_level")
        self.notification_level_combo.addItems(["All", "Important", "None"])
        self.notification_level_combo.setCurrentText(current_settings.get("notification_level", "All"))
        notification_layout.addRow("Level:", self.notification_level_combo)

        layout.addWidget(notification_group)

        advanced_group = QGroupBox("Advanced")
        advanced_layout = QFormLayout(advanced_group)

        self.max_connections_spin = QSpinBox()
        self.max_connections_spin.setObjectName("max_connections")
        self.max_connections_spin.setRange(1, 100)
        self.max_connections_spin.setValue(current_settings.get("max_connections", 10))
        advanced_layout.addRow("Max connections:", self.max_connections_spin)

        self.cache_size_spin = QSpinBox()
        self.cache_size_spin.setObjectName("cache_size")
        self.cache_size_spin.setRange(0, 1000)
        self.cache_size_spin.setSuffix(" MB")
        self.cache_size_spin.setValue(current_settings.get("cache_size", 100))
        advanced_layout.addRow("Cache size:", self.cache_size_spin)

        self.debug_check = QCheckBox("Enable debug mode")
        self.debug_check.setObjectName("debug_mode")
        self.debug_check.setChecked(current_settings.get("debug_mode", False))
        advanced_layout.addRow("", self.debug_check)

        layout.addWidget(advanced_group)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.setObjectName("settings_button_box")
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _on_accept(self):
        settings = {
            "theme": self.theme_combo.currentText(),
            "language": self.language_combo.currentText(),
            "auto_save": self.auto_save_check.isChecked(),
            "refresh_interval": self.refresh_spin.value(),
            "notify_email": self.notify_email_check.isChecked(),
            "notify_sms": self.notify_sms_check.isChecked(),
            "notify_push": self.notify_push_check.isChecked(),
            "notification_level": self.notification_level_combo.currentText(),
            "max_connections": self.max_connections_spin.value(),
            "cache_size": self.cache_size_spin.value(),
            "debug_mode": self.debug_check.isChecked(),
        }
        self.settingsChanged.emit(settings)
        self.accept()


class DataEntryDialog(QDialog):
    dataSubmitted = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Data Entry")
        self.setObjectName("data_entry_dialog")
        self.setModal(True)
        self.setMinimumWidth(450)

        layout = QVBoxLayout(self)

        form_layout = QFormLayout()

        self.name_input = QLineEdit()
        self.name_input.setObjectName("entry_name")
        self.name_input.setPlaceholderText("Enter name...")
        form_layout.addRow("Name:", self.name_input)

        self.email_input = QLineEdit()
        self.email_input.setObjectName("entry_email")
        self.email_input.setPlaceholderText("user@example.com")
        form_layout.addRow("Email:", self.email_input)

        self.department_combo = QComboBox()
        self.department_combo.setObjectName("entry_department")
        self.department_combo.addItems(["Engineering", "Sales", "Marketing", "HR", "Finance"])
        form_layout.addRow("Department:", self.department_combo)

        self.priority_combo = QComboBox()
        self.priority_combo.setObjectName("entry_priority")
        self.priority_combo.addItems(["Low", "Normal", "High", "Critical"])
        form_layout.addRow("Priority:", self.priority_combo)

        self.urgency_group = QButtonGroup()
        urgency_container = QWidget()
        urgency_layout = QHBoxLayout(urgency_container)
        self.urgency_low = QRadioButton("Low")
        self.urgency_low.setObjectName("entry_urgency_low")
        self.urgency_medium = QRadioButton("Medium")
        self.urgency_medium.setObjectName("entry_urgency_medium")
        self.urgency_medium.setChecked(True)
        self.urgency_high = QRadioButton("High")
        self.urgency_high.setObjectName("entry_urgency_high")
        self.urgency_group.addButton(self.urgency_low, 1)
        self.urgency_group.addButton(self.urgency_medium, 2)
        self.urgency_group.addButton(self.urgency_high, 3)
        urgency_layout.addWidget(self.urgency_low)
        urgency_layout.addWidget(self.urgency_medium)
        urgency_layout.addWidget(self.urgency_high)
        urgency_layout.addStretch()
        form_layout.addRow("Urgency:", urgency_container)

        self.estimated_hours_spin = QDoubleSpinBox()
        self.estimated_hours_spin.setObjectName("entry_estimated_hours")
        self.estimated_hours_spin.setRange(0, 1000)
        self.estimated_hours_spin.setSuffix(" hours")
        self.estimated_hours_spin.setValue(1.0)
        form_layout.addRow("Estimated hours:", self.estimated_hours_spin)

        self.tags_input = QLineEdit()
        self.tags_input.setObjectName("entry_tags")
        self.tags_input.setPlaceholderText("tag1, tag2, tag3...")
        form_layout.addRow("Tags:", self.tags_input)

        self.start_date_edit = QDateTimeEdit()
        self.start_date_edit.setObjectName("entry_start_date")
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDateTime(QDateTime.currentDateTime())
        form_layout.addRow("Start date:", self.start_date_edit)

        self.description_input = QTextEdit()
        self.description_input.setObjectName("entry_description")
        self.description_input.setPlaceholderText("Enter description...")
        self.description_input.setFixedHeight(80)
        form_layout.addRow("Description:", self.description_input)

        layout.addLayout(form_layout)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.setObjectName("data_entry_button_box")
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _on_accept(self):
        urgency_id = self.urgency_group.checkedId()
        urgency_text = {1: "Low", 2: "Medium", 3: "High"}[urgency_id]
        data = {
            "name": self.name_input.text().strip(),
            "email": self.email_input.text().strip(),
            "department": self.department_combo.currentText(),
            "priority": self.priority_combo.currentText(),
            "urgency": urgency_text,
            "estimated_hours": self.estimated_hours_spin.value(),
            "tags": [t.strip() for t in self.tags_input.text().split(",") if t.strip()],
            "start_date": self.start_date_edit.dateTime().toString(),
            "description": self.description_input.toPlainText().strip(),
        }
        self.dataSubmitted.emit(data)
        self.accept()


class DemoWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.review_dialog = None
        self.settings_dialog = None
        self.data_entry_dialog = None
        self.setWindowTitle("QPlaywright Demo App")
        self.setMinimumSize(900, 700)

        self._create_menu_bar()
        self._create_tool_bar()
        self._create_status_bar()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("main_tabs")
        main_layout.addWidget(self.tabs)

        self._create_login_tab()
        self._create_data_tab()
        self._create_settings_tab()
        self._create_progress_tab()

        self._settings_state = {
            "theme": self.settings_theme_combo.currentText(),
            "language": self.settings_language_combo.currentText(),
            "auto_save": self.settings_auto_save_check.isChecked(),
            "refresh_interval": self.settings_refresh_spin.value(),
            "notify_email": self.notify_email_check.isChecked(),
            "notify_sms": self.notify_sms_check.isChecked(),
            "notify_push": self.notify_push_check.isChecked(),
            "notification_level": "All",
            "max_connections": 10,
            "cache_size": 100,
            "debug_mode": False,
        }

        self._update_timer = QTimer()
        self._update_timer.timeout.connect(self._on_timer_update)
        self._update_timer.start(1000)

    def _create_menu_bar(self):
        menubar = self.menuBar()
        menubar.setObjectName("menubar")

        file_menu = menubar.addMenu("File")
        file_menu.setObjectName("menu_file")

        new_action = QAction("New", self)
        new_action.setObjectName("action_new")
        new_action.triggered.connect(lambda: self._log("[ACTION] File > New"))
        file_menu.addAction(new_action)

        open_action = QAction("Open...", self)
        open_action.setObjectName("action_open")
        open_action.triggered.connect(self._on_open_file)
        file_menu.addAction(open_action)

        save_action = QAction("Save", self)
        save_action.setObjectName("action_save")
        save_action.triggered.connect(lambda: self._log("[ACTION] File > Save"))
        file_menu.addAction(save_action)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.setObjectName("action_exit")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        edit_menu = menubar.addMenu("Edit")
        edit_menu.setObjectName("menu_edit")

        copy_action = QAction("Copy", self)
        copy_action.setObjectName("action_copy")
        copy_action.triggered.connect(lambda: self._log("[ACTION] Edit > Copy"))
        edit_menu.addAction(copy_action)

        paste_action = QAction("Paste", self)
        paste_action.setObjectName("action_paste")
        paste_action.triggered.connect(lambda: self._log("[ACTION] Edit > Paste"))
        edit_menu.addAction(paste_action)

        tools_menu = menubar.addMenu("Tools")
        tools_menu.setObjectName("menu_tools")

        settings_action = QAction("Settings...", self)
        settings_action.setObjectName("action_settings")
        settings_action.triggered.connect(self._open_settings)
        tools_menu.addAction(settings_action)

        help_menu = menubar.addMenu("Help")
        help_menu.setObjectName("menu_help")

        about_action = QAction("About", self)
        about_action.setObjectName("action_about")
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _create_tool_bar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setObjectName("main_toolbar")
        self.addToolBar(toolbar)

        self.add_data_btn = QPushButton("Add Entry")
        self.add_data_btn.setObjectName("toolbar_add_entry")
        self.add_data_btn.clicked.connect(self._open_data_entry)
        toolbar.addWidget(self.add_data_btn)

        toolbar.addSeparator()

        self.settings_btn = QPushButton("Settings")
        self.settings_btn.setObjectName("toolbar_settings")
        self.settings_btn.clicked.connect(self._open_settings)
        toolbar.addWidget(self.settings_btn)

        toolbar.addSeparator()

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setObjectName("toolbar_refresh")
        self.refresh_btn.clicked.connect(self._on_refresh)
        toolbar.addWidget(self.refresh_btn)

    def _create_status_bar(self):
        self.statusbar = QStatusBar()
        self.statusbar.setObjectName("statusbar")
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage("Ready")

    def _create_login_tab(self):
        login_tab = QWidget()
        login_tab.setObjectName("tab_login")
        self.tabs.addTab(login_tab, "Login")

        layout = QVBoxLayout(login_tab)

        login_group = QGroupBox("Login Form")
        login_layout = QVBoxLayout(login_group)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Username:"))
        self.username_input = QLineEdit()
        self.username_input.setObjectName("username")
        self.username_input.setPlaceholderText("Enter username")
        row1.addWidget(self.username_input)
        login_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Password:"))
        self.password_input = QLineEdit()
        self.password_input.setObjectName("password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Enter password")
        row2.addWidget(self.password_input)
        login_layout.addLayout(row2)

        self.remember_check = QCheckBox("Remember me")
        self.remember_check.setObjectName("remember")
        login_layout.addWidget(self.remember_check)

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

        self.login_btn = QPushButton("Login")
        self.login_btn.setObjectName("login_btn")
        self.login_btn.clicked.connect(self._on_login)
        login_layout.addWidget(self.login_btn)

        layout.addWidget(login_group)

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

        splitter = QSplitter(Qt.Orientation.Vertical)

        self.scroll_list = QListWidget()
        self.scroll_list.setObjectName("scroll_list")
        self.scroll_list.addItems([f"Scrollable item {index:03d}" for index in range(1, 101)])

        self.scroll_status_label = QLabel("Scroll: top")
        self.scroll_status_label.setObjectName("scroll_status")
        self.scroll_status_label.setWordWrap(True)

        splitter.addWidget(self.scroll_list)
        splitter.addWidget(self.scroll_status_label)
        splitter.setSizes([300, 50])
        layout.addWidget(splitter)

        self.log_area = QTextEdit()
        self.log_area.setObjectName("log")
        self.log_area.setReadOnly(True)
        self.log_area.setPlaceholderText("Logs will appear here...")
        self._seed_scroll_log()
        layout.addWidget(self.log_area)

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

    def _create_data_tab(self):
        data_tab = QWidget()
        data_tab.setObjectName("tab_data")
        self.tabs.addTab(data_tab, "Data")

        layout = QVBoxLayout(data_tab)

        toolbar = QHBoxLayout()
        self.add_entry_btn = QPushButton("Add Entry")
        self.add_entry_btn.setObjectName("add_entry_btn")
        self.add_entry_btn.clicked.connect(self._open_data_entry)
        toolbar.addWidget(self.add_entry_btn)

        self.delete_entry_btn = QPushButton("Delete Selected")
        self.delete_entry_btn.setObjectName("delete_entry_btn")
        self.delete_entry_btn.clicked.connect(self._on_delete_entry)
        toolbar.addWidget(self.delete_entry_btn)

        self.import_btn = QPushButton("Import...")
        self.import_btn.setObjectName("import_btn")
        self.import_btn.clicked.connect(self._on_import)
        toolbar.addWidget(self.import_btn)

        self.export_btn = QPushButton("Export...")
        self.export_btn.setObjectName("export_btn")
        self.export_btn.clicked.connect(self._on_export)
        toolbar.addWidget(self.export_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.data_table = QTableWidget()
        self.data_table.setObjectName("data_table")
        self.data_table.setColumnCount(6)
        self.data_table.setHorizontalHeaderLabels(["ID", "Name", "Department", "Priority", "Status", "Created"])
        self.data_table.setRowCount(5)
        sample_data = [
            ("001", "Alice Johnson", "Engineering", "High", "Active", "2026-01-15"),
            ("002", "Bob Smith", "Sales", "Normal", "Active", "2026-02-20"),
            ("003", "Carol White", "Marketing", "Low", "Inactive", "2026-03-10"),
            ("004", "David Brown", "Finance", "Critical", "Active", "2026-04-05"),
            ("005", "Eve Davis", "HR", "Normal", "Active", "2026-04-18"),
        ]
        for row, (id_, name, dept, priority, status, created) in enumerate(sample_data):
            for col, value in enumerate([id_, name, dept, priority, status, created]):
                item = QTableWidgetItem(value)
                self.data_table.setItem(row, col, item)
        self.data_table.setObjectName("data_table")
        layout.addWidget(self.data_table)

        self.data_status_label = QLabel()
        self.data_status_label.setObjectName("data_status")
        layout.addWidget(self.data_status_label)
        self._refresh_data_status()

    def _create_settings_tab(self):
        settings_tab = QWidget()
        settings_tab.setObjectName("tab_settings")
        self.tabs.addTab(settings_tab, "Settings")

        layout = QVBoxLayout(settings_tab)

        group = QGroupBox("Application Settings")
        group_layout = QFormLayout(group)

        self.settings_theme_combo = QComboBox()
        self.settings_theme_combo.setObjectName("settings_theme")
        self.settings_theme_combo.addItems(["Light", "Dark", "System"])
        group_layout.addRow("Theme:", self.settings_theme_combo)

        self.settings_language_combo = QComboBox()
        self.settings_language_combo.setObjectName("settings_language")
        self.settings_language_combo.addItems(["English", "Chinese", "Japanese", "German"])
        group_layout.addRow("Language:", self.settings_language_combo)

        self.settings_auto_save_check = QCheckBox("Auto-save changes")
        self.settings_auto_save_check.setObjectName("settings_auto_save")
        self.settings_auto_save_check.setChecked(True)
        group_layout.addRow("", self.settings_auto_save_check)

        self.settings_refresh_spin = QSpinBox()
        self.settings_refresh_spin.setObjectName("settings_refresh_interval")
        self.settings_refresh_spin.setRange(1, 60)
        self.settings_refresh_spin.setSuffix(" seconds")
        group_layout.addRow("Refresh interval:", self.settings_refresh_spin)

        layout.addWidget(group)

        notification_group = QGroupBox("Notifications")
        notification_layout = QVBoxLayout(notification_group)

        self.notify_email_check = QCheckBox("Email notifications")
        self.notify_email_check.setObjectName("notify_email")
        notification_layout.addWidget(self.notify_email_check)

        self.notify_sms_check = QCheckBox("SMS notifications")
        self.notify_sms_check.setObjectName("notify_sms")
        notification_layout.addWidget(self.notify_sms_check)

        self.notify_push_check = QCheckBox("Push notifications")
        self.notify_push_check.setObjectName("notify_push")
        notification_layout.addWidget(self.notify_push_check)

        layout.addWidget(notification_group)

        layout.addStretch()

        save_btn = QPushButton("Save Settings")
        save_btn.setObjectName("save_settings_btn")
        save_btn.clicked.connect(self._on_save_settings)
        layout.addWidget(save_btn)

    def _create_progress_tab(self):
        progress_tab = QWidget()
        progress_tab.setObjectName("tab_progress")
        self.tabs.addTab(progress_tab, "Progress")

        layout = QVBoxLayout(progress_tab)

        group = QGroupBox("Task Progress")
        group_layout = QVBoxLayout(group)

        self.task_progress = QProgressBar()
        self.task_progress.setObjectName("task_progress")
        self.task_progress.setRange(0, 100)
        self.task_progress.setValue(0)
        group_layout.addWidget(self.task_progress)

        progress_control = QHBoxLayout()
        self.start_task_btn = QPushButton("Start Task")
        self.start_task_btn.setObjectName("start_task_btn")
        self.start_task_btn.clicked.connect(self._on_start_task)
        progress_control.addWidget(self.start_task_btn)

        self.pause_task_btn = QPushButton("Pause")
        self.pause_task_btn.setObjectName("pause_task_btn")
        self.pause_task_btn.setEnabled(False)
        self.pause_task_btn.clicked.connect(self._on_pause_task)
        progress_control.addWidget(self.pause_task_btn)

        self.cancel_task_btn = QPushButton("Cancel")
        self.cancel_task_btn.setObjectName("cancel_task_btn")
        self.cancel_task_btn.setEnabled(False)
        self.cancel_task_btn.clicked.connect(self._on_cancel_task)
        progress_control.addWidget(self.cancel_task_btn)

        group_layout.addLayout(progress_control)
        layout.addWidget(group)

        slider_group = QGroupBox("Value Adjustment")
        slider_layout = QVBoxLayout(slider_group)

        self.value_slider = QSlider(Qt.Orientation.Horizontal)
        self.value_slider.setObjectName("value_slider")
        self.value_slider.setRange(0, 100)
        self.value_slider.setValue(50)
        self.value_slider.valueChanged.connect(self._on_slider_changed)
        slider_layout.addWidget(self.value_slider)

        self.slider_value_label = QLabel("Value: 50")
        self.slider_value_label.setObjectName("slider_value_label")
        slider_layout.addWidget(self.slider_value_label)

        layout.addWidget(slider_group)

        self.task_log = QTextEdit()
        self.task_log.setObjectName("task_log")
        self.task_log.setReadOnly(True)
        self.task_log.setPlaceholderText("Task log will appear here...")
        layout.addWidget(self.task_log)

        self._task_timer = QTimer()
        self._task_timer.timeout.connect(self._on_task_tick)
        self._task_paused = False

    def _log(self, message):
        self.log_area.append(message)
        self.statusbar.showMessage(message, 3000)

    def _seed_scroll_log(self):
        lines = [f"[TRACE] Scroll entry {index:03d}" for index in range(1, 81)]
        self.log_area.setPlainText("\n".join(lines))

    def _update_scroll_status(self):
        bar = self.scroll_list.verticalScrollBar()
        self.scroll_status_label.setText(f"Scroll: value={bar.value()} max={bar.maximum()} visible={bar.isVisible()}")

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
        self.summary_label.setText(f"Summary: user={username} role={role} env={environment} payment={payment_summary} {flag_state} {note_state}")

    def _refresh_data_status(self):
        total_rows = self.data_table.rowCount()
        self.data_status_label.setText(f"Showing {total_rows} entr{'y' if total_rows == 1 else 'ies'}")

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
            self._log("[ERROR] Missing username or password")
            return

        self.status_label.setText(f"Status: Logged in as {username} ({role}) env={environment} payment={payment_summary}")
        self.summary_label.setText(f"Summary: last-login user={username} role={role} env={environment} payment={payment_summary} notify={notify}")
        self._log(f"[INFO] Login successful: user={username}, role={role}, env={environment}, payment={payment_summary}, remember={remember}, notify={notify}")
        if notes:
            self._log(f"[INFO] Reviewer notes: {notes}")

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
        self._log(f"[INFO] Opened payment review dialog for {self.amount_editor.summary()}")
        self.review_status_label.setText(f"Review: Open for {self.amount_editor.summary()}")

    def _on_review_submitted(self, payload):
        self.review_status_label.setText(f"Review: {payload['decision']} code={payload['approvalCode'] or '<empty>'} risk={payload['risk']} escalate={payload['escalate']}")
        self.status_label.setText(f"Status: Review {payload['decision']} for {payload['paymentSummary']}")
        self._log(f"[INFO] Review {payload['decision']}: code={payload['approvalCode'] or '<empty>'}, risk={payload['risk']}, escalate={payload['escalate']}, notes={payload['notes'] or '<empty>'}")

    def _on_review_cancelled(self):
        self.review_status_label.setText("Review: Cancelled")
        self.status_label.setText("Status: Review cancelled")
        self._log("[INFO] Review dialog cancelled")

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
        self._log("[INFO] Log cleared")

    def _on_open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open File", "", "All Files (*.*)")
        if file_path:
            self._log(f"[ACTION] Opened file: {file_path}")

    def _open_settings(self):
        if self.settings_dialog is not None and self.settings_dialog.isVisible():
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
            return

        dialog = SettingsDialog(dict(self._settings_state), parent=self)
        dialog.settingsChanged.connect(self._on_settings_changed)
        dialog.finished.connect(self._on_settings_finished)
        self.settings_dialog = dialog
        dialog.open()
        self._log("[INFO] Opened settings dialog")

    def _on_settings_changed(self, settings):
        self._settings_state = dict(settings)
        self.settings_theme_combo.setCurrentText(settings["theme"])
        self.settings_language_combo.setCurrentText(settings["language"])
        self.settings_auto_save_check.setChecked(settings["auto_save"])
        self.settings_refresh_spin.setValue(settings["refresh_interval"])
        self.notify_email_check.setChecked(settings["notify_email"])
        self.notify_sms_check.setChecked(settings["notify_sms"])
        self.notify_push_check.setChecked(settings["notify_push"])
        self._log(f"[INFO] Settings changed: theme={settings['theme']}, language={settings['language']}")

    def _on_settings_finished(self, _result):
        self.settings_dialog = None

    def _open_data_entry(self):
        if self.data_entry_dialog is not None and self.data_entry_dialog.isVisible():
            self.data_entry_dialog.raise_()
            self.data_entry_dialog.activateWindow()
            return

        dialog = DataEntryDialog(parent=self)
        dialog.dataSubmitted.connect(self._on_data_submitted)
        dialog.finished.connect(self._on_data_entry_finished)
        self.data_entry_dialog = dialog
        dialog.open()
        self._log("[INFO] Opened data entry dialog")

    def _on_data_submitted(self, data):
        row = self.data_table.rowCount()
        self.data_table.insertRow(row)
        self.data_table.setItem(row, 0, QTableWidgetItem(data["name"][:3].upper() + f"{row+1:03d}"))
        self.data_table.setItem(row, 1, QTableWidgetItem(data["name"]))
        self.data_table.setItem(row, 2, QTableWidgetItem(data["department"]))
        self.data_table.setItem(row, 3, QTableWidgetItem(data["priority"]))
        self.data_table.setItem(row, 4, QTableWidgetItem("Active"))
        self.data_table.setItem(row, 5, QTableWidgetItem(QDateTime.currentDateTime().toString()))
        self._refresh_data_status()
        self._log(f"[INFO] Added entry: {data['name']} ({data['department']})")

    def _on_data_entry_finished(self, _result):
        self.data_entry_dialog = None

    def _on_delete_entry(self):
        current_row = self.data_table.currentRow()
        if current_row >= 0:
            item = self.data_table.item(current_row, 1)
            name = item.text() if item else "Unknown"
            self.data_table.removeRow(current_row)
            self._refresh_data_status()
            self._log(f"[INFO] Deleted entry: {name}")
        else:
            self._log("[WARN] No entry selected for deletion")

    def _on_import(self):
        self._log("[ACTION] Import triggered")

    def _on_export(self):
        self._log("[ACTION] Export triggered")

    def _on_save_settings(self):
        self._log("[INFO] Settings saved")

    def _on_start_task(self):
        self._task_paused = False
        self._task_timer.start(100)
        self.start_task_btn.setEnabled(False)
        self.pause_task_btn.setEnabled(True)
        self.cancel_task_btn.setEnabled(True)
        self.task_log.append("[INFO] Task started")
        self._log("[ACTION] Task started")

    def _on_pause_task(self):
        if self._task_paused:
            self._task_timer.start(100)
            self.pause_task_btn.setText("Pause")
            self._task_paused = False
            self.task_log.append("[INFO] Task resumed")
        else:
            self._task_timer.stop()
            self.pause_task_btn.setText("Resume")
            self._task_paused = True
            self.task_log.append("[INFO] Task paused")

    def _on_cancel_task(self):
        self._task_timer.stop()
        self.task_progress.setValue(0)
        self.start_task_btn.setEnabled(True)
        self.pause_task_btn.setEnabled(False)
        self.pause_task_btn.setText("Pause")
        self.cancel_task_btn.setEnabled(False)
        self._task_paused = False
        self.task_log.append("[INFO] Task cancelled")
        self._log("[ACTION] Task cancelled")

    def _on_task_tick(self):
        if not self._task_paused:
            value = self.task_progress.value()
            if value < 100:
                self.task_progress.setValue(value + 1)
                if value % 10 == 0:
                    self.task_log.append(f"[TRACE] Progress: {value}%")
            else:
                self._task_timer.stop()
                self.start_task_btn.setEnabled(True)
                self.pause_task_btn.setEnabled(False)
                self.cancel_task_btn.setEnabled(False)
                self.task_log.append("[INFO] Task completed!")

    def _on_slider_changed(self, value):
        self.slider_value_label.setText(f"Value: {value}")

    def _on_refresh(self):
        self._log("[ACTION] Refresh triggered")

    def _on_timer_update(self):
        current_time = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        self.statusbar.showMessage(f"Ready | {current_time}", 1000)

    def _show_about(self):
        QMessageBox.about(self, "About", "QPlaywright Demo App v1.0\n\nA demo application for Qt automation testing.")


def main():
    app = QApplication(sys.argv)
    port = int(os.environ.get("QPLAYWRIGHT_PORT", "19876"))

    server = start_agent(app, port=port, visual_feedback=True)
    print(f"QPlaywright agent started on port {port}")

    window = DemoWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
