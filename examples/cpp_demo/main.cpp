/**
 * Demo Qt application with QPlaywright agent embedded.
 *
 * Build:
 *   cd agent_cpp && mkdir build && cd build
 *   cmake .. -DCMAKE_PREFIX_PATH=<your-qt-path>
 *   cmake --build .
 *
 * Run:
 *   ./demo_app
 *
 * Then in another terminal:
 *   python examples/test_demo.py
 */

#include <QApplication>
#include <QMainWindow>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QPushButton>
#include <QCheckBox>
#include <QComboBox>
#include <QTextEdit>
#include <QGroupBox>

#include "qplaywright_agent.h"

class DemoWindow : public QMainWindow
{
    Q_OBJECT
public:
    DemoWindow(QWidget *parent = nullptr) : QMainWindow(parent)
    {
        setWindowTitle("QPlaywright C++ Demo");
        setMinimumSize(500, 400);

        auto *central = new QWidget;
        setCentralWidget(central);
        auto *layout = new QVBoxLayout(central);

        // --- Login form ---
        auto *loginGroup = new QGroupBox("Login Form");
        auto *loginLayout = new QVBoxLayout(loginGroup);

        // Username
        auto *row1 = new QHBoxLayout;
        row1->addWidget(new QLabel("Username:"));
        m_username = new QLineEdit;
        m_username->setObjectName("username");
        m_username->setPlaceholderText("Enter username");
        row1->addWidget(m_username);
        loginLayout->addLayout(row1);

        // Password
        auto *row2 = new QHBoxLayout;
        row2->addWidget(new QLabel("Password:"));
        m_password = new QLineEdit;
        m_password->setObjectName("password");
        m_password->setEchoMode(QLineEdit::Password);
        m_password->setPlaceholderText("Enter password");
        row2->addWidget(m_password);
        loginLayout->addLayout(row2);

        // Remember me
        m_remember = new QCheckBox("Remember me");
        m_remember->setObjectName("remember");
        loginLayout->addWidget(m_remember);

        // Role
        auto *row3 = new QHBoxLayout;
        row3->addWidget(new QLabel("Role:"));
        m_role = new QComboBox;
        m_role->setObjectName("role");
        m_role->addItems({"User", "Admin", "Moderator"});
        row3->addWidget(m_role);
        loginLayout->addLayout(row3);

        // Login button
        m_loginBtn = new QPushButton("Login");
        m_loginBtn->setObjectName("login_btn");
        connect(m_loginBtn, &QPushButton::clicked, this, &DemoWindow::onLogin);
        loginLayout->addWidget(m_loginBtn);

        layout->addWidget(loginGroup);

        // Status
        m_status = new QLabel("Status: Ready");
        m_status->setObjectName("status");
        layout->addWidget(m_status);

        // Log area
        m_log = new QTextEdit;
        m_log->setObjectName("log");
        m_log->setReadOnly(true);
        m_log->setPlaceholderText("Logs will appear here...");
        layout->addWidget(m_log);

        // Buttons
        auto *btnRow = new QHBoxLayout;
        auto *clearBtn = new QPushButton("Clear Log");
        clearBtn->setObjectName("clear_btn");
        connect(clearBtn, &QPushButton::clicked, this, &DemoWindow::onClearLog);
        btnRow->addWidget(clearBtn);

        auto *quitBtn = new QPushButton("Quit");
        quitBtn->setObjectName("quit_btn");
        connect(quitBtn, &QPushButton::clicked, this, &QWidget::close);
        btnRow->addWidget(quitBtn);
        layout->addLayout(btnRow);
    }

private slots:
    void onLogin()
    {
        QString username = m_username->text();
        QString password = m_password->text();
        QString role = m_role->currentText();

        if (username.isEmpty() || password.isEmpty()) {
            m_status->setText("Status: Please fill all fields");
            m_log->append("[ERROR] Missing username or password");
            return;
        }

        m_status->setText(QString("Status: Logged in as %1 (%2)").arg(username, role));
        m_log->append(QString("[INFO] Login successful: user=%1, role=%2, remember=%3")
            .arg(username, role, m_remember->isChecked() ? "true" : "false"));
    }

    void onClearLog()
    {
        m_log->clear();
        m_status->setText("Status: Log cleared");
    }

private:
    QLineEdit *m_username;
    QLineEdit *m_password;
    QCheckBox *m_remember;
    QComboBox *m_role;
    QPushButton *m_loginBtn;
    QLabel *m_status;
    QTextEdit *m_log;
};

int main(int argc, char *argv[])
{
    QApplication app(argc, argv);

    // ★ One line to enable QPlaywright automation ★
    QPlaywrightAgent::start(19876);

    DemoWindow window;
    window.show();

    return app.exec();
}

#include "main.moc"
