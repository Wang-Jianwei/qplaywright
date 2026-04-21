/**
 * @file qplaywright_agent.h
 * @brief QPlaywright Agent — embed in your C++ Qt application to enable automation.
 *
 * Usage:
 *   #include "qplaywright_agent.h"
 *
 *   int main(int argc, char *argv[]) {
 *       QApplication app(argc, argv);
 *       QPlaywrightAgent::start(19876);  // one line to enable
 *       // ... your UI setup ...
 *       return app.exec();
 *   }
 */

#ifndef QPLAYWRIGHT_AGENT_H
#define QPLAYWRIGHT_AGENT_H

#include <QObject>
#include <QTcpServer>
#include <QTcpSocket>
#include <QThread>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <QApplication>
#include <QWidget>
#include <QMetaObject>
#include <QBuffer>
#include <QPixmap>
#include <QScreen>
#include <QTimer>
#include <QElapsedTimer>
#include <QMutex>
#include <QWaitCondition>
#include <QMouseEvent>
#include <QKeyEvent>
#include <QWheelEvent>
#include <QTest>
#include <QAbstractButton>
#include <QLineEdit>
#include <QTextEdit>
#include <QPlainTextEdit>
#include <QComboBox>
#include <QCheckBox>
#include <QRadioButton>
#include <QSpinBox>
#include <QDoubleSpinBox>
#include <QSlider>
#include <QLabel>
#include <QGroupBox>
#include <QTabWidget>
#include <QTabBar>
#include <QTreeView>
#include <QTreeWidget>
#include <QTableView>
#include <QTableWidget>
#include <QListView>
#include <QListWidget>
#include <QProgressBar>
#include <QMenu>
#include <QMenuBar>
#include <QToolBar>
#include <QStatusBar>
#include <QDialog>
#include <QScrollBar>

#include <functional>

// -------------------------------------------------------------------------- //
//  Forward declarations                                                       //
// -------------------------------------------------------------------------- //

class QPlaywrightAgent;
class QPlaywrightHandler;
class QPlaywrightClientConnection;

// -------------------------------------------------------------------------- //
//  Role mapping                                                               //
// -------------------------------------------------------------------------- //

namespace QPlaywrightRoles {

inline bool matchesRole(const QWidget *widget, const QString &role)
{
    static const QHash<QString, QStringList> roleMap = {
        {"button",      {"QPushButton", "QToolButton", "QCommandLinkButton"}},
        {"checkbox",    {"QCheckBox"}},
        {"radio",       {"QRadioButton"}},
        {"textbox",     {"QLineEdit"}},
        {"textarea",    {"QTextEdit", "QPlainTextEdit"}},
        {"input",       {"QLineEdit", "QTextEdit", "QPlainTextEdit"}},
        {"combobox",    {"QComboBox"}},
        {"slider",      {"QSlider"}},
        {"spinbox",     {"QSpinBox", "QDoubleSpinBox"}},
        {"tab",         {"QTabBar"}},
        {"tabwidget",   {"QTabWidget"}},
        {"table",       {"QTableWidget", "QTableView"}},
        {"tree",        {"QTreeWidget", "QTreeView"}},
        {"list",        {"QListWidget", "QListView"}},
        {"menu",        {"QMenu"}},
        {"menubar",     {"QMenuBar"}},
        {"dialog",      {"QDialog"}},
        {"label",       {"QLabel"}},
        {"progressbar", {"QProgressBar"}},
        {"scrollbar",   {"QScrollBar"}},
        {"toolbar",     {"QToolBar"}},
        {"statusbar",   {"QStatusBar"}},
        {"groupbox",    {"QGroupBox"}},
    };

    const auto it = roleMap.find(role.toLower());
    if (it == roleMap.end()) return false;

    // Walk class hierarchy
    const QMetaObject *mo = widget->metaObject();
    while (mo) {
        if (it->contains(QString::fromLatin1(mo->className())))
            return true;
        mo = mo->superClass();
    }
    return false;
}

inline QString widgetText(const QWidget *widget)
{
    // Try common accessors
    if (auto *btn = qobject_cast<const QAbstractButton *>(widget))
        return btn->text();
    if (auto *label = qobject_cast<const QLabel *>(widget))
        return label->text();
    if (auto *edit = qobject_cast<const QLineEdit *>(widget))
        return edit->text();
    if (auto *te = qobject_cast<const QTextEdit *>(widget))
        return te->toPlainText();
    if (auto *pte = qobject_cast<const QPlainTextEdit *>(widget))
        return pte->toPlainText();
    if (auto *cb = qobject_cast<const QComboBox *>(widget))
        return cb->currentText();
    if (auto *gb = qobject_cast<const QGroupBox *>(widget))
        return gb->title();
    if (auto *tw = qobject_cast<const QTabWidget *>(widget))
        return tw->tabText(tw->currentIndex());
    if (auto *spin = qobject_cast<const QSpinBox *>(widget))
        return QString::number(spin->value());
    if (auto *dspin = qobject_cast<const QDoubleSpinBox *>(widget))
        return QString::number(dspin->value());
    // Fallback: window title
    QString title = widget->windowTitle();
    if (!title.isEmpty()) return title;
    return widget->accessibleName();
}

} // namespace QPlaywrightRoles

// -------------------------------------------------------------------------- //
//  Selector matching                                                          //
// -------------------------------------------------------------------------- //

namespace QPlaywrightSelector {

struct Selector {
    QString type;   // "role", "text", "has_text", "name", "id", "cls"
    QString value;
};

inline Selector parse(const QString &sel)
{
    if (sel.startsWith("role="))
        return {"role", sel.mid(5)};
    if (sel.startsWith("text="))
        return {"text", sel.mid(5)};
    if (sel.startsWith("has-text="))
        return {"has_text", sel.mid(9)};
    if (sel.startsWith("name="))
        return {"name", sel.mid(5)};
    if (sel.startsWith('#'))
        return {"id", sel.mid(1)};
    if (sel.startsWith('.'))
        return {"cls", sel.mid(1)};
    // Bare string → text match
    return {"text", sel};
}

inline bool matches(const QWidget *widget, const Selector &sel)
{
    if (sel.type == "role")
        return QPlaywrightRoles::matchesRole(widget, sel.value);
    if (sel.type == "text")
        return QPlaywrightRoles::widgetText(widget) == sel.value;
    if (sel.type == "has_text")
        return QPlaywrightRoles::widgetText(widget).contains(sel.value, Qt::CaseInsensitive);
    if (sel.type == "name" || sel.type == "id")
        return widget->objectName() == sel.value;
    if (sel.type == "cls") {
        const QMetaObject *mo = widget->metaObject();
        while (mo) {
            if (QString::fromLatin1(mo->className()) == sel.value)
                return true;
            mo = mo->superClass();
        }
        return false;
    }
    return false;
}

inline bool matchesFull(const QWidget *widget, const QString &selectorStr,
                        const QString &hasText = {})
{
    Selector sel = parse(selectorStr);
    if (!matches(widget, sel))
        return false;
    if (!hasText.isEmpty()) {
        if (!QPlaywrightRoles::widgetText(widget).contains(hasText, Qt::CaseInsensitive))
            return false;
    }
    return true;
}

inline void findWidgets(QWidget *root, const QString &selectorStr,
                        const QString &hasText, bool visibleOnly,
                        QList<QWidget *> &results)
{
    if (visibleOnly && !root->isVisible())
        return;
    if (matchesFull(root, selectorStr, hasText))
        results.append(root);
    for (QObject *child : root->children()) {
        QWidget *w = qobject_cast<QWidget *>(child);
        if (w) findWidgets(w, selectorStr, hasText, visibleOnly, results);
    }
}

} // namespace QPlaywrightSelector

// -------------------------------------------------------------------------- //
//  Widget serialization                                                       //
// -------------------------------------------------------------------------- //

namespace QPlaywrightSerializer {

inline QJsonObject widgetToJson(const QWidget *w, int depth = 0, int maxDepth = 10)
{
    QJsonObject obj;
    obj["class"] = QString::fromLatin1(w->metaObject()->className());
    obj["objectName"] = w->objectName();
    obj["text"] = QPlaywrightRoles::widgetText(w);
    obj["visible"] = w->isVisible();
    obj["enabled"] = w->isEnabled();

    QJsonObject geo;
    geo["x"] = w->x();
    geo["y"] = w->y();
    geo["width"] = w->width();
    geo["height"] = w->height();
    obj["geometry"] = geo;

    if (auto *cb = qobject_cast<const QCheckBox *>(w))
        obj["checked"] = cb->isChecked();
    if (auto *rb = qobject_cast<const QRadioButton *>(w))
        obj["checked"] = rb->isChecked();
    if (auto *combo = qobject_cast<const QComboBox *>(w)) {
        obj["currentText"] = combo->currentText();
        obj["currentIndex"] = combo->currentIndex();
    }

    if (depth < maxDepth) {
        QJsonArray children;
        for (QObject *child : w->children()) {
            QWidget *cw = qobject_cast<QWidget *>(child);
            if (cw)
                children.append(widgetToJson(cw, depth + 1, maxDepth));
        }
        if (!children.isEmpty())
            obj["children"] = children;
    }

    return obj;
}

} // namespace QPlaywrightSerializer

// -------------------------------------------------------------------------- //
//  Widget ID registry                                                         //
// -------------------------------------------------------------------------- //

class QPlaywrightRegistry
{
public:
    static QPlaywrightRegistry &instance() {
        static QPlaywrightRegistry reg;
        return reg;
    }

    int registerWidget(QWidget *w) {
        quintptr key = reinterpret_cast<quintptr>(w);
        if (m_w2id.contains(key))
            return m_w2id[key];
        int wid = m_next++;
        m_w2id[key] = wid;
        m_id2w[wid] = w;
        return wid;
    }

    QWidget *get(int wid) const {
        return m_id2w.value(wid, nullptr);
    }

private:
    QHash<quintptr, int> m_w2id;
    QHash<int, QWidget *> m_id2w;
    int m_next = 1;
};

// -------------------------------------------------------------------------- //
//  Command handler — runs on the main thread                                  //
// -------------------------------------------------------------------------- //

class QPlaywrightHandler : public QObject
{
    Q_OBJECT
public:
    explicit QPlaywrightHandler(QObject *parent = nullptr) : QObject(parent) {}

public slots:
    /**
     * @brief Handle a JSON command and return a JSON result.
     * Called via QMetaObject::invokeMethod from the network thread.
     */
    QJsonObject handleCommand(const QJsonObject &request)
    {
        QString method = request["method"].toString();
        QJsonObject params = request["params"].toObject();
        int id = request["id"].toInt();

        QJsonObject response;
        response["id"] = id;

        try {
            QJsonValue result = dispatch(method, params);
            response["result"] = result;
        } catch (const std::exception &e) {
            QJsonObject error;
            error["message"] = QString::fromStdString(e.what());
            response["error"] = error;
        }

        return response;
    }

private:
    QJsonObject serializeWidgetTree(QWidget *w, int depth = 0, int maxDepth = 10)
    {
        auto &reg = QPlaywrightRegistry::instance();

        QJsonObject obj;
        obj["wid"] = reg.registerWidget(w);
        obj["class"] = QString::fromLatin1(w->metaObject()->className());
        obj["objectName"] = w->objectName();
        obj["text"] = QPlaywrightRoles::widgetText(w);
        obj["visible"] = w->isVisible();
        obj["enabled"] = w->isEnabled();

        QJsonObject geo;
        geo["x"] = w->x();
        geo["y"] = w->y();
        geo["width"] = w->width();
        geo["height"] = w->height();
        obj["geometry"] = geo;

        if (auto *cb = qobject_cast<const QCheckBox *>(w))
            obj["checked"] = cb->isChecked();
        if (auto *rb = qobject_cast<const QRadioButton *>(w))
            obj["checked"] = rb->isChecked();
        if (auto *combo = qobject_cast<const QComboBox *>(w)) {
            obj["currentText"] = combo->currentText();
            obj["currentIndex"] = combo->currentIndex();
        }

        if (depth < maxDepth) {
            QJsonArray children;
            for (QObject *child : w->children()) {
                QWidget *cw = qobject_cast<QWidget *>(child);
                if (cw)
                    children.append(serializeWidgetTree(cw, depth + 1, maxDepth));
            }
            if (!children.isEmpty())
                obj["children"] = children;
        }

        return obj;
    }

    QJsonValue dispatch(const QString &method, const QJsonObject &params)
    {
        auto &reg = QPlaywrightRegistry::instance();

        // -- Ping --
        if (method == "ping") {
            QJsonObject r; r["pong"] = true; return r;
        }

        // -- Find --
        if (method == "find") {
            auto widgets = resolveWidgets(params);
            if (widgets.isEmpty()) return QJsonValue::Null;
            QWidget *w = widgets.first();
            int wid = reg.registerWidget(w);
            QJsonObject r = QPlaywrightSerializer::widgetToJson(w, 0, 0);
            r["wid"] = wid;
            return r;
        }

        if (method == "find_all") {
            auto widgets = resolveWidgets(params);
            QJsonArray arr;
            for (QWidget *w : widgets) {
                int wid = reg.registerWidget(w);
                QJsonObject r = QPlaywrightSerializer::widgetToJson(w, 0, 0);
                r["wid"] = wid;
                arr.append(r);
            }
            return arr;
        }

        if (method == "widget_tree") {
            int maxDepth = params["max_depth"].toInt(10);
            QJsonArray arr;
            for (QWidget *w : QApplication::topLevelWidgets()) {
                if (w->isVisible())
                    arr.append(serializeWidgetTree(w, 0, maxDepth));
            }
            return arr;
        }

        if (method == "count") {
            return resolveWidgets(params).size();
        }

        // -- Property access --
        if (method == "get_text") {
            QWidget *w = resolveOne(params);
            return QPlaywrightRoles::widgetText(w);
        }

        if (method == "get_value") {
            QWidget *w = resolveOne(params);
            if (auto *spin = qobject_cast<QSpinBox *>(w)) return spin->value();
            if (auto *dspin = qobject_cast<QDoubleSpinBox *>(w)) return dspin->value();
            if (auto *slider = qobject_cast<QSlider *>(w)) return slider->value();
            if (auto *combo = qobject_cast<QComboBox *>(w)) return combo->currentText();
            return QPlaywrightRoles::widgetText(w);
        }

        if (method == "get_property") {
            QWidget *w = resolveOne(params);
            QString prop = params["property"].toString();
            QVariant val = w->property(prop.toLatin1().constData());
            return QJsonValue::fromVariant(val);
        }

        if (method == "is_visible") {
            return resolveOne(params)->isVisible();
        }
        if (method == "is_enabled") {
            return resolveOne(params)->isEnabled();
        }
        if (method == "is_checked") {
            QWidget *w = resolveOne(params);
            if (auto *cb = qobject_cast<QAbstractButton *>(w)) return cb->isChecked();
            return false;
        }

        if (method == "bounding_box") {
            QWidget *w = resolveOne(params);
            QPoint global = w->mapToGlobal(QPoint(0, 0));
            QJsonObject r;
            r["x"] = global.x();
            r["y"] = global.y();
            r["width"] = w->width();
            r["height"] = w->height();
            return r;
        }

        // -- Actions --
        if (method == "click") {
            QWidget *w = resolveOne(params);
            clickWidget(w, false);
            return true;
        }
        if (method == "dblclick") {
            QWidget *w = resolveOne(params);
            clickWidget(w, true);
            return true;
        }

        if (method == "fill") {
            QWidget *w = resolveOne(params);
            QString value = params["value"].toString();
            fillWidget(w, value);
            return true;
        }
        if (method == "clear") {
            QWidget *w = resolveOne(params);
            fillWidget(w, "");
            return true;
        }

        if (method == "check") {
            QWidget *w = resolveOne(params);
            if (auto *btn = qobject_cast<QAbstractButton *>(w)) btn->setChecked(true);
            return true;
        }
        if (method == "uncheck") {
            QWidget *w = resolveOne(params);
            if (auto *btn = qobject_cast<QAbstractButton *>(w)) btn->setChecked(false);
            return true;
        }

        if (method == "select_option") {
            QWidget *w = resolveOne(params);
            selectOption(w, params);
            return true;
        }

        if (method == "type") {
            QWidget *w = resolveOne(params);
            QString text = params["text"].toString();
            int delay = params["delay"].toInt(0);
            typeText(w, text, delay);
            return true;
        }

        if (method == "press") {
            QWidget *w = resolveOne(params);
            QString key = params["key"].toString();
            pressKey(w, key);
            return true;
        }

        if (method == "hover") {
            QWidget *w = resolveOne(params);
            QCursor::setPos(w->mapToGlobal(w->rect().center()));
            QApplication::processEvents();
            return true;
        }

        if (method == "focus") {
            QWidget *w = resolveOne(params);
            w->setFocus();
            QApplication::processEvents();
            return true;
        }

        if (method == "scroll") {
            QWidget *w = resolveOne(params);
            int dx = params["delta_x"].toInt(0);
            int dy = params["delta_y"].toInt(0);
            scrollWidget(w, dx, dy);
            return true;
        }

        // -- Screenshot --
        if (method == "screenshot" || method == "screenshot_widget") {
            QWidget *w;
            if (method == "screenshot_widget") {
                w = resolveOne(params);
            } else {
                auto windows = QApplication::topLevelWidgets();
                w = nullptr;
                if (params.contains("wid")) {
                    w = reg.get(params["wid"].toInt());
                } else {
                    for (auto *win : windows) {
                        if (win->isVisible()) { w = win; break; }
                    }
                }
                if (!w) throw std::runtime_error("No visible window found");
            }

            QPixmap pixmap = w->grab();
            QString path = params["path"].toString();

            QJsonObject r;
            r["width"] = pixmap.width();
            r["height"] = pixmap.height();

            if (!path.isEmpty()) {
                pixmap.save(path, "PNG");
                r["path"] = path;
            } else {
                QByteArray ba;
                QBuffer buf(&ba);
                buf.open(QIODevice::WriteOnly);
                pixmap.save(&buf, "PNG");
                r["data"] = QString::fromLatin1(ba.toBase64());
            }
            return r;
        }

        // -- Window management --
        if (method == "list_windows") {
            QJsonArray arr;
            for (QWidget *w : QApplication::topLevelWidgets()) {
                if (!w->isVisible()) continue;
                int wid = reg.registerWidget(w);
                QJsonObject r;
                r["wid"] = wid;
                r["title"] = w->windowTitle();
                r["class"] = QString::fromLatin1(w->metaObject()->className());
                r["width"] = w->width();
                r["height"] = w->height();
                arr.append(r);
            }
            return arr;
        }
        if (method == "window_title") {
            return resolveOne(params)->windowTitle();
        }
        if (method == "window_size") {
            QWidget *w = resolveOne(params);
            QJsonObject r;
            r["width"] = w->width();
            r["height"] = w->height();
            return r;
        }
        if (method == "window_resize") {
            QWidget *w = resolveOne(params);
            w->resize(params["width"].toInt(), params["height"].toInt());
            QApplication::processEvents();
            return true;
        }
        if (method == "window_close") {
            QWidget *w = resolveOne(params);
            w->close();
            QApplication::processEvents();
            return true;
        }

        // -- Wait --
        if (method == "wait_for") {
            return waitFor(params);
        }

        throw std::runtime_error(("Unknown method: " + method).toStdString());
    }

    // ----- Widget resolution -----

    QList<QWidget *> resolveWidgets(const QJsonObject &params)
    {
        auto &reg = QPlaywrightRegistry::instance();

        if (params.contains("wid")) {
            QWidget *w = reg.get(params["wid"].toInt());
            if (!w) throw std::runtime_error("Widget not found by wid");
            return {w};
        }

        QString selector = params["selector"].toString();
        if (selector.isEmpty())
            throw std::runtime_error("Either 'wid' or 'selector' is required");

        QList<QWidget *> roots;
        if (params.contains("parent_wid")) {
            QWidget *parent = reg.get(params["parent_wid"].toInt());
            if (!parent) throw std::runtime_error("Parent widget not found");
            roots.append(parent);
        } else {
            roots = QApplication::topLevelWidgets();
        }

        QString hasText = params["has_text"].toString();
        bool visibleOnly = params["visible_only"].toBool(true);

        QList<QWidget *> results;
        for (QWidget *root : roots) {
            QPlaywrightSelector::findWidgets(root, selector, hasText, visibleOnly, results);
        }

        if (params.contains("nth")) {
            int nth = params["nth"].toInt();
            if (nth >= 0 && nth < results.size())
                return {results[nth]};
            return {};
        }

        return results;
    }

    QWidget *resolveOne(const QJsonObject &params)
    {
        auto widgets = resolveWidgets(params);
        if (widgets.isEmpty()) {
            QString sel = params.contains("selector") ? params["selector"].toString() : QString::number(params["wid"].toInt());
            throw std::runtime_error(("No widget found for: " + sel).toStdString());
        }
        return widgets.first();
    }

    // ----- Action helpers -----

    void clickWidget(QWidget *w, bool doubleClick)
    {
        w->setFocus();
        QApplication::processEvents();
        QTest::mouseClick(w, Qt::LeftButton);
        if (doubleClick) {
            QTest::mouseDClick(w, Qt::LeftButton);
        }
        QApplication::processEvents();
    }

    void fillWidget(QWidget *w, const QString &value)
    {
        if (auto *edit = qobject_cast<QLineEdit *>(w)) {
            edit->clear();
            edit->setText(value);
        } else if (auto *te = qobject_cast<QTextEdit *>(w)) {
            te->setPlainText(value);
        } else if (auto *pte = qobject_cast<QPlainTextEdit *>(w)) {
            pte->setPlainText(value);
        } else if (auto *combo = qobject_cast<QComboBox *>(w)) {
            combo->setCurrentText(value);
        } else {
            throw std::runtime_error("Cannot fill widget of type: " +
                std::string(w->metaObject()->className()));
        }
        QApplication::processEvents();
    }

    void typeText(QWidget *w, const QString &text, int delay)
    {
        w->setFocus();
        QApplication::processEvents();
        QTest::keyClicks(w, text, Qt::NoModifier, delay);
        QApplication::processEvents();
    }

    void pressKey(QWidget *w, const QString &keyStr)
    {
        static const QHash<QString, Qt::Key> keyMap = {
            {"Enter", Qt::Key_Return}, {"Return", Qt::Key_Return},
            {"Tab", Qt::Key_Tab}, {"Escape", Qt::Key_Escape},
            {"Backspace", Qt::Key_Backspace}, {"Delete", Qt::Key_Delete},
            {"ArrowUp", Qt::Key_Up}, {"ArrowDown", Qt::Key_Down},
            {"ArrowLeft", Qt::Key_Left}, {"ArrowRight", Qt::Key_Right},
            {"Home", Qt::Key_Home}, {"End", Qt::Key_End},
            {"PageUp", Qt::Key_PageUp}, {"PageDown", Qt::Key_PageDown},
            {"Space", Qt::Key_Space},
            {"F1", Qt::Key_F1}, {"F2", Qt::Key_F2}, {"F3", Qt::Key_F3},
            {"F4", Qt::Key_F4}, {"F5", Qt::Key_F5}, {"F6", Qt::Key_F6},
            {"F7", Qt::Key_F7}, {"F8", Qt::Key_F8}, {"F9", Qt::Key_F9},
            {"F10", Qt::Key_F10}, {"F11", Qt::Key_F11}, {"F12", Qt::Key_F12},
            {"Control", Qt::Key_Control}, {"Shift", Qt::Key_Shift},
            {"Alt", Qt::Key_Alt}, {"Meta", Qt::Key_Meta},
        };

        w->setFocus();
        QApplication::processEvents();

        auto it = keyMap.find(keyStr);
        if (it != keyMap.end()) {
            QTest::keyClick(w, it.value());
        } else if (keyStr.length() == 1) {
            QTest::keyClick(w, keyStr.at(0).toLatin1());
        } else {
            throw std::runtime_error(("Unknown key: " + keyStr).toStdString());
        }
        QApplication::processEvents();
    }

    void selectOption(QWidget *w, const QJsonObject &params)
    {
        auto *combo = qobject_cast<QComboBox *>(w);
        if (!combo)
            throw std::runtime_error("Widget is not a QComboBox");

        if (params.contains("value"))
            combo->setCurrentText(params["value"].toString());
        else if (params.contains("index"))
            combo->setCurrentIndex(params["index"].toInt());
        else if (params.contains("label")) {
            int idx = combo->findText(params["label"].toString());
            if (idx >= 0) combo->setCurrentIndex(idx);
        }
        QApplication::processEvents();
    }

    void scrollWidget(QWidget *w, int dx, int dy)
    {
        QPoint center = w->rect().center();
        QPoint globalPos = w->mapToGlobal(center);
#if QT_VERSION >= QT_VERSION_CHECK(5, 12, 0)
        QWheelEvent event(
            QPointF(center), QPointF(globalPos),
            QPoint(dx, dy), QPoint(dx, dy),
            Qt::NoButton, Qt::NoModifier,
            Qt::ScrollBegin, false
        );
#else
        QWheelEvent event(
            QPointF(center), QPointF(globalPos),
            QPoint(dx, dy), QPoint(dx, dy),
            0, Qt::Vertical,
            Qt::NoButton, Qt::NoModifier
        );
#endif
        QApplication::sendEvent(w, &event);
        QApplication::processEvents();
    }

    bool waitFor(const QJsonObject &params)
    {
        QString selector = params["selector"].toString();
        QString state = params["state"].toString("visible");
        int timeout = params["timeout"].toInt(30000);
        int pollInterval = params["poll_interval"].toInt(100);

        QElapsedTimer timer;
        timer.start();

        while (timer.elapsed() < timeout) {
            QApplication::processEvents();

            QList<QWidget *> roots = QApplication::topLevelWidgets();
            QList<QWidget *> widgets;
            for (QWidget *root : roots) {
                QPlaywrightSelector::findWidgets(root, selector, {}, false, widgets);
            }

            if (state == "visible") {
                for (QWidget *w : widgets)
                    if (w->isVisible()) return true;
            } else if (state == "hidden") {
                if (widgets.isEmpty()) return true;
                bool allHidden = true;
                for (QWidget *w : widgets)
                    if (w->isVisible()) { allHidden = false; break; }
                if (allHidden) return true;
            } else if (state == "enabled") {
                for (QWidget *w : widgets)
                    if (w->isEnabled()) return true;
            } else if (state == "disabled") {
                if (widgets.isEmpty()) return true;
                bool allDisabled = true;
                for (QWidget *w : widgets)
                    if (w->isEnabled()) { allDisabled = false; break; }
                if (allDisabled) return true;
            } else if (state == "attached") {
                if (!widgets.isEmpty()) return true;
            } else if (state == "detached") {
                if (widgets.isEmpty()) return true;
            }

            QThread::msleep(pollInterval);
        }

        throw std::runtime_error(("Timed out waiting for " + selector + " to be " + state).toStdString());
    }
};

// -------------------------------------------------------------------------- //
//  Client connection                                                          //
// -------------------------------------------------------------------------- //

class QPlaywrightClientConnection : public QObject
{
    Q_OBJECT
public:
    QPlaywrightClientConnection(QTcpSocket *socket, QPlaywrightHandler *handler, QObject *parent = nullptr)
        : QObject(parent), m_socket(socket), m_handler(handler)
    {
        connect(m_socket, &QTcpSocket::readyRead, this, &QPlaywrightClientConnection::onReadyRead);
        connect(m_socket, &QTcpSocket::disconnected, this, &QPlaywrightClientConnection::onDisconnected);
    }

private slots:
    void onReadyRead()
    {
        m_buffer += m_socket->readAll();
        while (m_buffer.contains('\n')) {
            int idx = m_buffer.indexOf('\n');
            QByteArray line = m_buffer.left(idx).trimmed();
            m_buffer = m_buffer.mid(idx + 1);
            if (line.isEmpty()) continue;
            processLine(line);
        }
    }

    void onDisconnected()
    {
        qDebug() << "[QPlaywright] Client disconnected";
        deleteLater();
    }

private:
    void processLine(const QByteArray &line)
    {
        QJsonParseError err;
        QJsonDocument doc = QJsonDocument::fromJson(line, &err);
        if (err.error != QJsonParseError::NoError) {
            sendError(0, "Invalid JSON: " + err.errorString());
            return;
        }

        QJsonObject request = doc.object();

        // Invoke handler on the main thread (BlockingQueuedConnection ensures
        // we wait for the result while the handler runs on the GUI thread)
        QJsonObject response;
        bool ok = QMetaObject::invokeMethod(
            m_handler,
            "handleCommand",
            Qt::BlockingQueuedConnection,  // ← 关键: 阻塞等待主线程执行
            Q_RETURN_ARG(QJsonObject, response),
            Q_ARG(QJsonObject, request)
        );

        if (!ok) {
            sendError(request["id"].toInt(), "Failed to invoke handler on main thread");
            return;
        }

        QByteArray data = QJsonDocument(response).toJson(QJsonDocument::Compact) + "\n";
        m_socket->write(data);
        m_socket->flush();
    }

    void sendError(int id, const QString &message)
    {
        QJsonObject resp;
        resp["id"] = id;
        QJsonObject err;
        err["message"] = message;
        resp["error"] = err;
        QByteArray data = QJsonDocument(resp).toJson(QJsonDocument::Compact) + "\n";
        m_socket->write(data);
        m_socket->flush();
    }

    QTcpSocket *m_socket;
    QPlaywrightHandler *m_handler;
    QByteArray m_buffer;
};

// -------------------------------------------------------------------------- //
//  QPlaywrightAgent — the main public class                                   //
// -------------------------------------------------------------------------- //

/**
 * @brief QPlaywright Agent — one-line integration for Qt applications.
 *
 * Usage:
 * @code
 *   QPlaywrightAgent::start(19876);
 * @endcode
 *
 * The agent runs a TCP server on the specified port. Each client connection
 * is handled in a dedicated QThread, with commands dispatched to the main
 * thread via BlockingQueuedConnection for thread-safe widget access.
 */
class QPlaywrightAgent : public QObject
{
    Q_OBJECT
public:
    /**
     * @brief Start the agent on the given port.
     * @param port TCP port to listen on (default: 19876)
     * @param host Host to bind to (default: 127.0.0.1)
     * @return Pointer to the agent instance (owned by QApplication)
     */
    static QPlaywrightAgent *start(int port = 19876, const QString &host = "127.0.0.1")
    {
        auto *app = QApplication::instance();
        Q_ASSERT(app && "QApplication must be created before calling QPlaywrightAgent::start()");

        auto *agent = new QPlaywrightAgent(app);
        agent->m_handler = new QPlaywrightHandler(agent);

        agent->m_server = new QTcpServer(agent);
        QObject::connect(agent->m_server, &QTcpServer::newConnection, agent, &QPlaywrightAgent::onNewConnection);

        QHostAddress addr(host);
        if (!agent->m_server->listen(addr, port)) {
            qCritical() << "[QPlaywright] Failed to listen on" << host << ":" << port
                        << agent->m_server->errorString();
            delete agent;
            return nullptr;
        }

        qDebug() << "[QPlaywright] Agent listening on" << host << ":" << port;
        return agent;
    }

    /**
     * @brief Stop the agent and close all connections.
     */
    void stop()
    {
        if (m_server) {
            m_server->close();
        }
        deleteLater();
    }

private:
    explicit QPlaywrightAgent(QObject *parent) : QObject(parent) {}

private slots:
    void onNewConnection()
    {
        while (m_server->hasPendingConnections()) {
            QTcpSocket *socket = m_server->nextPendingConnection();
            qDebug() << "[QPlaywright] Client connected:" << socket->peerAddress().toString();

            // Each client gets handled in its own thread for concurrent access
            QThread *thread = new QThread(this);
            socket->setParent(nullptr);
            socket->moveToThread(thread);

            auto *conn = new QPlaywrightClientConnection(socket, m_handler);
            conn->moveToThread(thread);

            connect(thread, &QThread::started, []{});
            connect(socket, &QTcpSocket::disconnected, thread, &QThread::quit);
            connect(thread, &QThread::finished, thread, &QThread::deleteLater);
            connect(thread, &QThread::finished, conn, &QObject::deleteLater);

            thread->start();
        }
    }

private:
    QTcpServer *m_server = nullptr;
    QPlaywrightHandler *m_handler = nullptr;
};

#endif // QPLAYWRIGHT_AGENT_H
