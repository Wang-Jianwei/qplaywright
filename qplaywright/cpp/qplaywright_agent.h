/**
 * @file qplaywright_agent.h
 * @brief QPlaywright Agent — embed in your C++ Qt application to enable automation.
 *
 * Usage:
 *   #include "qplaywright_agent.h"
 *
 *   int main(int argc, char *argv[]) {
 *       QApplication app(argc, argv);
 *       QPlaywrightAgent::start(19876, "127.0.0.1", true);  // one line to enable
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
#include <QMetaType>
#include <QMetaProperty>
#include <QBuffer>
#include <QPixmap>
#include <QScreen>
#include <QTimer>
#include <QElapsedTimer>
#include <QMutex>
#include <QPainter>
#include <QPen>
#include <QPointer>
#include <QBrush>
#include <QPolygon>
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
#include <QAbstractScrollArea>
#include <QScrollBar>
#include <QStringList>
#include <QVariant>
#include <QVector>

#include <functional>

// -------------------------------------------------------------------------- //
//  Forward declarations                                                       //
// -------------------------------------------------------------------------- //

class QPlaywrightAgent;
class QPlaywrightHandler;
class QPlaywrightClientConnection;

enum class QPlaywrightInvokeErrorCode {
    None,
    MethodNotExposed,
    MissingRequiredArgument,
    UnexpectedArgument,
    ArgumentTypeMismatch,
    MethodInvocationFailed,
};

class QPlaywrightMethodArg
{
public:
    QPlaywrightMethodArg() = default;

    QPlaywrightMethodArg &name(const QString &name)
    {
        m_name = name;
        return *this;
    }

    QPlaywrightMethodArg &type(const QString &type)
    {
        m_type = type;
        return *this;
    }

    QPlaywrightMethodArg &brief(const QString &brief)
    {
        m_brief = brief;
        return *this;
    }

    QPlaywrightMethodArg &required(bool required)
    {
        m_required = required;
        return *this;
    }

    QPlaywrightMethodArg &defaultValue(const QVariant &defaultValue)
    {
        m_defaultValue = defaultValue;
        return *this;
    }

    QString name() const { return m_name; }
    QString type() const { return m_type; }
    QString brief() const { return m_brief; }
    bool required() const { return m_required; }
    QVariant defaultValue() const { return m_defaultValue; }
    bool hasDefaultValue() const { return m_defaultValue.isValid(); }

    QVariantMap toVariantMap() const
    {
        QVariantMap map;
        map.insert("name", m_name);
        map.insert("type", m_type);
        map.insert("brief", m_brief);
        map.insert("required", m_required);
        map.insert("defaultValue", m_defaultValue);
        return map;
    }

private:
    QString m_name;
    QString m_type = QStringLiteral("QVariant");
    QString m_brief;
    bool m_required = true;
    QVariant m_defaultValue;
};

class QPlaywrightClassMethod
{
public:
    QPlaywrightClassMethod() = default;

    QPlaywrightClassMethod &name(const QString &name)
    {
        m_name = name;
        return *this;
    }

    QPlaywrightClassMethod &addArg(const QPlaywrightMethodArg &arg)
    {
        m_args.append(arg);
        return *this;
    }

    QPlaywrightClassMethod &returnType(const QString &returnType)
    {
        m_returnType = returnType;
        return *this;
    }

    QPlaywrightClassMethod &brief(const QString &brief)
    {
        m_brief = brief;
        return *this;
    }

    QString name() const { return m_name; }
    QVector<QPlaywrightMethodArg> args() const { return m_args; }
    QString returnType() const { return m_returnType; }
    QString brief() const { return m_brief; }

    QString signature() const
    {
        QStringList argTypeNames;
        for (const QPlaywrightMethodArg &arg : m_args)
            argTypeNames.append(arg.type());
        return QStringLiteral("%1(%2)").arg(m_name, argTypeNames.join(QStringLiteral(", ")));
    }

    bool acceptsArgs(const QVariantMap &providedArgs, QString *error = nullptr) const
    {
        for (auto it = providedArgs.constBegin(); it != providedArgs.constEnd(); ++it) {
            bool known = false;
            for (const QPlaywrightMethodArg &arg : m_args) {
                if (arg.name() == it.key()) {
                    known = true;
                    break;
                }
            }
            if (!known) {
                if (error)
                    *error = QStringLiteral("Unexpected argument: %1").arg(it.key());
                return false;
            }
        }

        for (const QPlaywrightMethodArg &arg : m_args) {
            if (!providedArgs.contains(arg.name()) && arg.required() && !arg.hasDefaultValue()) {
                if (error)
                    *error = QStringLiteral("Missing required argument: %1").arg(arg.name());
                return false;
            }
        }

        return true;
    }

    QVariantMap toVariantMap() const
    {
        QVariantList argMaps;
        for (const QPlaywrightMethodArg &arg : m_args)
            argMaps.append(arg.toVariantMap());

        QVariantMap map;
        map.insert("name", m_name);
        map.insert("args", argMaps);
        map.insert("returnType", m_returnType);
        map.insert("brief", m_brief);
        return map;
    }

private:
    QString m_name;
    QVector<QPlaywrightMethodArg> m_args;
    QString m_returnType = QStringLiteral("QVariant");
    QString m_brief;
};

class QPlaywrightClassMetadata
{
public:
    QPlaywrightClassMetadata() = default;

    QPlaywrightClassMetadata &role(const QString &role)
    {
        m_role = role;
        return *this;
    }

    QString role() const { return m_role; }

    QPlaywrightClassMetadata &addMethod(const QPlaywrightClassMethod &method)
    {
        m_methods.append(method);
        return *this;
    }

    QVector<QPlaywrightClassMethod> methods() const { return m_methods; }

    bool hasMethod(const QString &name) const
    {
        for (const QPlaywrightClassMethod &method : m_methods) {
            if (method.name() == name)
                return true;
        }
        return false;
    }

    QPlaywrightClassMethod findMethod(const QString &name) const
    {
        for (const QPlaywrightClassMethod &method : m_methods) {
            if (method.name() == name)
                return method;
        }
        return {};
    }

    QVariantMap toVariantMap() const
    {
        QVariantList methodMaps;
        for (const QPlaywrightClassMethod &method : m_methods)
            methodMaps.append(method.toVariantMap());

        QVariantMap map;
        map.insert("role", m_role);
        map.insert("methods", methodMaps);
        return map;
    }

private:
    QString m_role;
    QVector<QPlaywrightClassMethod> m_methods;
};

class QPlaywrightInvokeRequest
{
public:
    QPlaywrightInvokeRequest() = default;

    static QPlaywrightInvokeRequest fromJsonObject(const QJsonObject &object)
    {
        QPlaywrightInvokeRequest request;
        request.m_method = object.value("method").toString().trimmed();
        request.m_args = object.value("args").toObject().toVariantMap();
        return request;
    }

    QString method() const { return m_method; }
    QVariantMap args() const { return m_args; }

private:
    QString m_method;
    QVariantMap m_args;
};

class QPlaywrightPreparedCall
{
public:
    QPlaywrightPreparedCall() = default;

    QPlaywrightPreparedCall &method(const QPlaywrightClassMethod &method)
    {
        m_method = method;
        return *this;
    }

    QPlaywrightPreparedCall &orderedArgs(const QVariantList &orderedArgs)
    {
        m_orderedArgs = orderedArgs;
        return *this;
    }

    QPlaywrightClassMethod method() const { return m_method; }
    QVariantList orderedArgs() const { return m_orderedArgs; }

private:
    QPlaywrightClassMethod m_method;
    QVariantList m_orderedArgs;
};

class QPlaywrightInvokeResult
{
public:
    QPlaywrightInvokeResult() = default;

    static QPlaywrightInvokeResult success(const QVariant &value = QVariant())
    {
        QPlaywrightInvokeResult result;
        result.m_ok = true;
        result.m_value = value;
        return result;
    }

    static QPlaywrightInvokeResult failure(QPlaywrightInvokeErrorCode code, const QString &message)
    {
        QPlaywrightInvokeResult result;
        result.m_ok = false;
        result.m_errorCode = code;
        result.m_errorMessage = message;
        return result;
    }

    bool ok() const { return m_ok; }

    QJsonObject toJsonObject() const
    {
        QJsonObject object;
        object["ok"] = m_ok;
        object["value"] = QJsonValue::fromVariant(m_value);
        object["errorCode"] = static_cast<int>(m_errorCode);
        object["errorMessage"] = m_errorMessage;
        return object;
    }

private:
    bool m_ok = false;
    QVariant m_value;
    QPlaywrightInvokeErrorCode m_errorCode = QPlaywrightInvokeErrorCode::None;
    QString m_errorMessage;
};

Q_DECLARE_METATYPE(QPlaywrightMethodArg)
Q_DECLARE_METATYPE(QPlaywrightClassMethod)
Q_DECLARE_METATYPE(QPlaywrightClassMetadata)
Q_DECLARE_METATYPE(QPlaywrightInvokeResult)
Q_DECLARE_METATYPE(QPlaywrightInvokeErrorCode)

class QPlaywrightTypeConverter
{
public:
    static bool convert(const QVariant &input, const QString &targetType, QVariant *output, QString *error = nullptr)
    {
        if (targetType.isEmpty() || targetType == QStringLiteral("QVariant")) {
            *output = input;
            return true;
        }

        QVariant converted = input;

        if (targetType == QStringLiteral("QString")) {
            *output = converted.toString();
            return true;
        }
        if (targetType == QStringLiteral("int")) {
            if (!converted.canConvert<int>()) {
                if (error)
                    *error = QStringLiteral("Cannot convert value to int");
                return false;
            }
            *output = converted.toInt();
            return true;
        }
        if (targetType == QStringLiteral("double")) {
            if (!converted.canConvert<double>()) {
                if (error)
                    *error = QStringLiteral("Cannot convert value to double");
                return false;
            }
            *output = converted.toDouble();
            return true;
        }
        if (targetType == QStringLiteral("bool")) {
            if (!converted.canConvert<bool>()) {
                if (error)
                    *error = QStringLiteral("Cannot convert value to bool");
                return false;
            }
            *output = converted.toBool();
            return true;
        }
        if (targetType == QStringLiteral("QStringList")) {
            if (!converted.canConvert<QStringList>()) {
                if (error)
                    *error = QStringLiteral("Cannot convert value to QStringList");
                return false;
            }
            *output = converted.toStringList();
            return true;
        }

        if (error)
            *error = QStringLiteral("Unsupported target type: %1").arg(targetType);
        return false;
    }
};

class QPlaywrightInvoker
{
public:
    static QPlaywrightInvokeResult prepareCall(
        const QPlaywrightClassMetadata &metadata,
        const QPlaywrightInvokeRequest &request,
        QPlaywrightPreparedCall *preparedCall)
    {
        if (!metadata.hasMethod(request.method())) {
            return QPlaywrightInvokeResult::failure(
                QPlaywrightInvokeErrorCode::MethodNotExposed,
                QStringLiteral("Method is not exposed: %1").arg(request.method())
            );
        }

        const QPlaywrightClassMethod method = metadata.findMethod(request.method());
        QString argError;
        if (!method.acceptsArgs(request.args(), &argError)) {
            const QPlaywrightInvokeErrorCode code = argError.startsWith(QStringLiteral("Missing required"))
                ? QPlaywrightInvokeErrorCode::MissingRequiredArgument
                : QPlaywrightInvokeErrorCode::UnexpectedArgument;
            return QPlaywrightInvokeResult::failure(code, argError);
        }

        QVariantList orderedArgs;
        for (const QPlaywrightMethodArg &arg : method.args()) {
            QVariant rawValue;
            if (request.args().contains(arg.name()))
                rawValue = request.args().value(arg.name());
            else
                rawValue = arg.defaultValue();

            QVariant convertedValue;
            QString conversionError;
            if (!QPlaywrightTypeConverter::convert(rawValue, arg.type(), &convertedValue, &conversionError)) {
                return QPlaywrightInvokeResult::failure(
                    QPlaywrightInvokeErrorCode::ArgumentTypeMismatch,
                    QStringLiteral("Argument %1: %2").arg(arg.name(), conversionError)
                );
            }
            orderedArgs.append(convertedValue);
        }

        preparedCall->method(method).orderedArgs(orderedArgs);
        return QPlaywrightInvokeResult::success();
    }

    static QPlaywrightInvokeResult executePreparedCall(QObject *target, const QPlaywrightPreparedCall &preparedCall)
    {
        const QPlaywrightClassMethod method = preparedCall.method();
        const QVariantList orderedArgs = preparedCall.orderedArgs();

        if (orderedArgs.size() > 2) {
            return QPlaywrightInvokeResult::failure(
                QPlaywrightInvokeErrorCode::MethodInvocationFailed,
                QStringLiteral("First implementation supports at most 2 arguments: %1").arg(method.signature())
            );
        }

        if (method.returnType().isEmpty() || method.returnType() == QStringLiteral("void"))
            return invokeVoid(target, method, orderedArgs);
        if (method.returnType() == QStringLiteral("QString"))
            return invokeQString(target, method, orderedArgs);
        if (method.returnType() == QStringLiteral("QVariant"))
            return invokeQVariant(target, method, orderedArgs);
        if (method.returnType() == QStringLiteral("bool"))
            return invokeBool(target, method, orderedArgs);
        if (method.returnType() == QStringLiteral("int"))
            return invokeInt(target, method, orderedArgs);
        if (method.returnType() == QStringLiteral("double"))
            return invokeDouble(target, method, orderedArgs);

        return QPlaywrightInvokeResult::failure(
            QPlaywrightInvokeErrorCode::MethodInvocationFailed,
            QStringLiteral("Unsupported return type: %1").arg(method.returnType())
        );
    }

private:
    static bool invokeNoReturn(QObject *target, const QPlaywrightClassMethod &method, const QVariantList &args)
    {
        const QByteArray methodName = method.name().toLatin1();
        if (args.isEmpty())
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection);
        if (args.size() == 1)
            return invokeNoReturnOneArg(target, methodName, method.args().at(0).type(), args.at(0));
        if (args.size() == 2)
            return invokeNoReturnTwoArgs(target, methodName, method.args(), args);
        return false;
    }

    static QPlaywrightInvokeResult invokeVoid(QObject *target, const QPlaywrightClassMethod &method, const QVariantList &args)
    {
        if (!invokeNoReturn(target, method, args)) {
            return QPlaywrightInvokeResult::failure(
                QPlaywrightInvokeErrorCode::MethodInvocationFailed,
                QStringLiteral("invokeMethod failed: %1").arg(method.signature())
            );
        }
        return QPlaywrightInvokeResult::success();
    }

    static QPlaywrightInvokeResult invokeQString(QObject *target, const QPlaywrightClassMethod &method, const QVariantList &args)
    {
        QString value;
        return buildReturnResult(invokeWithReturn(target, method, args, Q_RETURN_ARG(QString, value)), method, value);
    }

    static QPlaywrightInvokeResult invokeQVariant(QObject *target, const QPlaywrightClassMethod &method, const QVariantList &args)
    {
        QVariant value;
        return buildReturnResult(invokeWithReturn(target, method, args, Q_RETURN_ARG(QVariant, value)), method, value);
    }

    static QPlaywrightInvokeResult invokeBool(QObject *target, const QPlaywrightClassMethod &method, const QVariantList &args)
    {
        bool value = false;
        return buildReturnResult(invokeWithReturn(target, method, args, Q_RETURN_ARG(bool, value)), method, value);
    }

    static QPlaywrightInvokeResult invokeInt(QObject *target, const QPlaywrightClassMethod &method, const QVariantList &args)
    {
        int value = 0;
        return buildReturnResult(invokeWithReturn(target, method, args, Q_RETURN_ARG(int, value)), method, value);
    }

    static QPlaywrightInvokeResult invokeDouble(QObject *target, const QPlaywrightClassMethod &method, const QVariantList &args)
    {
        double value = 0.0;
        return buildReturnResult(invokeWithReturn(target, method, args, Q_RETURN_ARG(double, value)), method, value);
    }

    template <typename ReturnArg>
    static bool invokeWithReturn(QObject *target, const QPlaywrightClassMethod &method, const QVariantList &args, ReturnArg returnArg)
    {
        const QByteArray methodName = method.name().toLatin1();
        if (args.isEmpty())
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, returnArg);
        if (args.size() == 1)
            return invokeWithReturnOneArg(target, methodName, returnArg, method.args().at(0).type(), args.at(0));
        if (args.size() == 2)
            return invokeWithReturnTwoArgs(target, methodName, returnArg, method.args(), args);
        return false;
    }

    template <typename TValue>
    static QPlaywrightInvokeResult buildReturnResult(bool ok, const QPlaywrightClassMethod &method, const TValue &value)
    {
        if (!ok) {
            return QPlaywrightInvokeResult::failure(
                QPlaywrightInvokeErrorCode::MethodInvocationFailed,
                QStringLiteral("invokeMethod failed: %1").arg(method.signature())
            );
        }
        return QPlaywrightInvokeResult::success(QVariant::fromValue(value));
    }

    static bool invokeNoReturnOneArg(QObject *target, const QByteArray &methodName, const QString &declaredType, const QVariant &value)
    {
        if (declaredType == QStringLiteral("QString")) {
            const QString converted = value.toString();
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, Q_ARG(QString, converted));
        }
        if (declaredType == QStringLiteral("QVariant")) {
            const QVariant converted = value;
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, Q_ARG(QVariant, converted));
        }
        if (declaredType == QStringLiteral("int")) {
            const int converted = value.toInt();
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, Q_ARG(int, converted));
        }
        if (declaredType == QStringLiteral("bool")) {
            const bool converted = value.toBool();
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, Q_ARG(bool, converted));
        }
        if (declaredType == QStringLiteral("double")) {
            const double converted = value.toDouble();
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, Q_ARG(double, converted));
        }
        return false;
    }

    static bool invokeNoReturnTwoArgs(QObject *target, const QByteArray &methodName, const QVector<QPlaywrightMethodArg> &declaredArgs, const QVariantList &values)
    {
        const QString firstType = declaredArgs.at(0).type();
        const QString secondType = declaredArgs.at(1).type();

        if (firstType == QStringLiteral("int") && secondType == QStringLiteral("int")) {
            const int first = values.at(0).toInt();
            const int second = values.at(1).toInt();
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, Q_ARG(int, first), Q_ARG(int, second));
        }
        if (firstType == QStringLiteral("QString") && secondType == QStringLiteral("QString")) {
            const QString first = values.at(0).toString();
            const QString second = values.at(1).toString();
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, Q_ARG(QString, first), Q_ARG(QString, second));
        }
        if (firstType == QStringLiteral("QVariant") && secondType == QStringLiteral("QVariant")) {
            const QVariant first = values.at(0);
            const QVariant second = values.at(1);
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, Q_ARG(QVariant, first), Q_ARG(QVariant, second));
        }
        return false;
    }

    template <typename ReturnArg>
    static bool invokeWithReturnOneArg(QObject *target, const QByteArray &methodName, ReturnArg returnArg, const QString &declaredType, const QVariant &value)
    {
        if (declaredType == QStringLiteral("QString")) {
            const QString converted = value.toString();
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, returnArg, Q_ARG(QString, converted));
        }
        if (declaredType == QStringLiteral("QVariant")) {
            const QVariant converted = value;
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, returnArg, Q_ARG(QVariant, converted));
        }
        if (declaredType == QStringLiteral("int")) {
            const int converted = value.toInt();
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, returnArg, Q_ARG(int, converted));
        }
        if (declaredType == QStringLiteral("bool")) {
            const bool converted = value.toBool();
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, returnArg, Q_ARG(bool, converted));
        }
        if (declaredType == QStringLiteral("double")) {
            const double converted = value.toDouble();
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, returnArg, Q_ARG(double, converted));
        }
        return false;
    }

    template <typename ReturnArg>
    static bool invokeWithReturnTwoArgs(QObject *target, const QByteArray &methodName, ReturnArg returnArg, const QVector<QPlaywrightMethodArg> &declaredArgs, const QVariantList &values)
    {
        const QString firstType = declaredArgs.at(0).type();
        const QString secondType = declaredArgs.at(1).type();

        if (firstType == QStringLiteral("int") && secondType == QStringLiteral("int")) {
            const int first = values.at(0).toInt();
            const int second = values.at(1).toInt();
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, returnArg, Q_ARG(int, first), Q_ARG(int, second));
        }
        if (firstType == QStringLiteral("QString") && secondType == QStringLiteral("QString")) {
            const QString first = values.at(0).toString();
            const QString second = values.at(1).toString();
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, returnArg, Q_ARG(QString, first), Q_ARG(QString, second));
        }
        if (firstType == QStringLiteral("QVariant") && secondType == QStringLiteral("QVariant")) {
            const QVariant first = values.at(0);
            const QVariant second = values.at(1);
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, returnArg, Q_ARG(QVariant, first), Q_ARG(QVariant, second));
        }
        return false;
    }
};

namespace QPlaywrightMetadataParsing {

inline QPlaywrightMethodArg parseMethodArg(const QVariantMap &map)
{
    return QPlaywrightMethodArg()
        .name(map.value("name").toString().trimmed())
        .type(map.value("type", QStringLiteral("QVariant")).toString())
        .brief(map.value("brief").toString())
        .required(map.value("required", true).toBool())
        .defaultValue(map.value("defaultValue"));
}

inline QPlaywrightClassMethod parseClassMethod(const QVariantMap &map)
{
    QPlaywrightClassMethod method;
    method.name(map.value("name").toString().trimmed())
        .returnType(map.value("returnType", QStringLiteral("QVariant")).toString())
        .brief(map.value("brief").toString());

    const QVariantList rawArgs = map.value("args").toList();
    for (const QVariant &rawArg : rawArgs)
        method.addArg(parseMethodArg(rawArg.toMap()));
    return method;
}

inline QPlaywrightClassMetadata parseClassMetadata(const QVariantMap &map)
{
    QPlaywrightClassMetadata metadata;
    metadata.role(map.value("role").toString().trimmed());

    const QVariantList rawMethods = map.value("methods").toList();
    for (const QVariant &rawMethod : rawMethods)
        metadata.addMethod(parseClassMethod(rawMethod.toMap()));
    return metadata;
}

} // namespace QPlaywrightMetadataParsing

// -------------------------------------------------------------------------- //
//  Role mapping                                                               //
// -------------------------------------------------------------------------- //

namespace QPlaywrightMetadata {

inline QPlaywrightClassMetadata classMetadata(const QObject *object)
{
    const QVariant value = object->property("qplaywrightClassMetadata");
    if (!value.isValid() || value.isNull())
        return {};

    if (value.userType() == qMetaTypeId<QPlaywrightClassMetadata>())
        return value.value<QPlaywrightClassMetadata>();

    if (value.canConvert<QVariantMap>())
        return QPlaywrightMetadataParsing::parseClassMetadata(value.toMap());

    return {};
}

inline QJsonArray methodSchema(const QWidget *widget)
{
    QJsonArray methods;
    const QVector<QPlaywrightClassMethod> declaredMethods = classMetadata(widget).methods();
    for (const QPlaywrightClassMethod &method : declaredMethods)
        methods.append(QJsonValue::fromVariant(method.toVariantMap()).toObject());
    return methods;
}

} // namespace QPlaywrightMetadata

namespace QPlaywrightRoles {

inline bool matchesRole(const QWidget *widget, const QString &role)
{
    const QString declaredRole = QPlaywrightMetadata::classMetadata(widget).role().trimmed().toLower();
    if (!declaredRole.isEmpty() && declaredRole == role.toLower())
        return true;

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

    const QString role = QPlaywrightMetadata::classMetadata(w).role().trimmed().toLower();
    if (!role.isEmpty()) {
        QJsonArray roleArray;
        roleArray.append(role);
        obj["roles"] = roleArray;
    }

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

    if (auto *spin = qobject_cast<const QSpinBox *>(w))
        obj["value"] = spin->value();
    if (auto *dspin = qobject_cast<const QDoubleSpinBox *>(w))
        obj["value"] = dspin->value();
    if (auto *slider = qobject_cast<const QSlider *>(w))
        obj["value"] = slider->value();

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

    void setVisualFeedbackEnabled(bool enabled)
    {
        m_visualFeedbackEnabled = enabled;
        if (!m_visualFeedbackEnabled) {
            closeAutomationOverlay();
            m_overlaySyncTimer.stop();
            return;
        }

        if (!m_overlaySyncTimer.isActive()) {
            m_overlaySyncTimer.setInterval(16);
            QObject::connect(&m_overlaySyncTimer, &QTimer::timeout, this, &QPlaywrightHandler::syncAutomationOverlay, Qt::UniqueConnection);
            m_overlaySyncTimer.start();
        }
    }

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
    static constexpr const char *kAutomationOverlayObjectName = "_qplaywright_automation_overlay";
    static constexpr const char *kAutomationOverlayProperty = "qplaywrightAutomationOverlay";

    struct PulseRecord
    {
        qint64 startedAtMs;
        QPoint center;
        int pulseCount;
    };

    class AutomationOverlay : public QWidget
    {
    public:
        explicit AutomationOverlay(QWidget *targetWindow)
            : QWidget(targetWindow), m_targetWindow(targetWindow)
        {
            setAttribute(Qt::WA_TransparentForMouseEvents, true);
            setAttribute(Qt::WA_NoSystemBackground, true);
            setAttribute(Qt::WA_TranslucentBackground, true);
            setAttribute(Qt::WA_ShowWithoutActivating, true);
            setFocusPolicy(Qt::NoFocus);
            setObjectName(QString::fromLatin1(kAutomationOverlayObjectName));
            setProperty(kAutomationOverlayProperty, true);
            m_timer.setInterval(16);
            QObject::connect(&m_timer, &QTimer::timeout, this, &AutomationOverlay::tick);
            m_clock.start();
        }

        void syncToWindow(bool forceRaise = false)
        {
            if (!m_targetWindow || !m_targetWindow->isVisible()) {
                hide();
                return;
            }

            const QRect targetRect = m_targetWindow->rect();
            if (geometry() != targetRect) {
                setGeometry(targetRect);
            }

            if (!m_cursorPosValid)
                m_cursorPos = m_targetWindow->rect().center();
            m_cursorPosValid = true;

            if (!isVisible())
                show();
            if (forceRaise)
                raise();
            if (!m_timer.isActive())
                m_timer.start();
            update();
        }

        void setCursorFromGlobal(const QPoint &globalPos, int pulseCount)
        {
            if (!m_targetWindow)
                return;

            m_cursorPos = m_targetWindow->mapFromGlobal(globalPos);
            m_cursorPosValid = true;
            if (pulseCount > 0)
                m_pulses.append({m_clock.elapsed(), m_cursorPos, pulseCount});
            syncToWindow(true);
            update();
        }

        void closeOverlay()
        {
            m_timer.stop();
            hide();
            close();
        }

        QWidget *targetWindow() const
        {
            return m_targetWindow.data();
        }

    protected:
        void paintEvent(QPaintEvent *) override
        {
            QPainter painter(this);
            painter.setRenderHint(QPainter::Antialiasing, true);

            const QColor coreColor(20, 132, 255, 180);
            const QColor ringColor(20, 132, 255, 220);

            const qint64 now = m_clock.elapsed();
            for (const PulseRecord &pulse : m_pulses) {
                for (int pulseIndex = 0; pulseIndex < pulse.pulseCount; ++pulseIndex) {
                    const qint64 localElapsed = now - pulse.startedAtMs - pulseIndex * 80;
                    if (localElapsed < 0 || localElapsed > 220)
                        continue;

                    const qreal progress = qreal(localElapsed) / 220.0;
                    const int radius = int(6 + progress * 20.0);
                    QColor pulseColor = ringColor;
                    pulseColor.setAlpha(qMax(0, int(ringColor.alpha() * (1.0 - progress))));

                    painter.setPen(QPen(pulseColor, 2));
                    painter.setBrush(Qt::NoBrush);
                    painter.drawEllipse(pulse.center, radius, radius);
                }
            }

            if (!m_cursorPosValid)
                return;

            const QPolygon shadow({
                m_cursorPos + QPoint(2, 2),
                m_cursorPos + QPoint(2, 20),
                m_cursorPos + QPoint(7, 15),
                m_cursorPos + QPoint(10, 23),
                m_cursorPos + QPoint(13, 22),
                m_cursorPos + QPoint(10, 14),
                m_cursorPos + QPoint(17, 14),
            });
            const QPolygon cursor({
                m_cursorPos,
                m_cursorPos + QPoint(0, 18),
                m_cursorPos + QPoint(5, 13),
                m_cursorPos + QPoint(8, 21),
                m_cursorPos + QPoint(11, 20),
                m_cursorPos + QPoint(8, 12),
                m_cursorPos + QPoint(15, 12),
            });

            painter.setPen(Qt::NoPen);
            painter.setBrush(QColor(0, 0, 0, 110));
            painter.drawPolygon(shadow);
            painter.setPen(QPen(QColor(0, 0, 0, 200), 1));
            painter.setBrush(QBrush(QColor(255, 255, 255, 240)));
            painter.drawPolygon(cursor);
            painter.setPen(Qt::NoPen);
            painter.setBrush(coreColor);
            painter.drawEllipse(m_cursorPos, 4, 4);
        }

    private:
        void tick()
        {
            const qint64 cutoff = m_clock.elapsed() - 300;
            int writeIndex = 0;
            for (int readIndex = 0; readIndex < m_pulses.size(); ++readIndex) {
                if (m_pulses[readIndex].startedAtMs >= cutoff) {
                    if (writeIndex != readIndex)
                        m_pulses[writeIndex] = m_pulses[readIndex];
                    ++writeIndex;
                }
            }
            if (writeIndex != m_pulses.size())
                m_pulses.resize(writeIndex);

            if (!m_targetWindow || !m_targetWindow->isVisible()) {
                hide();
                if (m_pulses.isEmpty())
                    m_timer.stop();
                return;
            }

            syncToWindow();
            update();
        }

        QPointer<QWidget> m_targetWindow;
        QPoint m_cursorPos;
        bool m_cursorPosValid = false;
        QVector<PulseRecord> m_pulses;
        QTimer m_timer;
        QElapsedTimer m_clock;
    };

    bool isAutomationOverlayWidget(QWidget *widget) const
    {
        if (!widget)
            return false;
        if (widget->objectName() == QString::fromLatin1(kAutomationOverlayObjectName))
            return true;
        return widget->property(kAutomationOverlayProperty).toBool();
    }

    QList<QWidget *> topLevelWidgets() const
    {
        QList<QWidget *> widgets;
        for (QWidget *widget : QApplication::topLevelWidgets()) {
            if (!isAutomationOverlayWidget(widget))
                widgets.append(widget);
        }
        return widgets;
    }

    void closeAutomationOverlay()
    {
        if (m_overlay) {
            m_overlay->closeOverlay();
            m_overlay->deleteLater();
            m_overlay = nullptr;
        }
    }

    void syncAutomationOverlay()
    {
        if (!m_visualFeedbackEnabled) {
            closeAutomationOverlay();
            return;
        }

        if (!m_activeOverlayWindow || !m_activeOverlayWindow->isVisible()) {
            m_activeOverlayWindow = nullptr;
            closeAutomationOverlay();
            return;
        }

        if (!m_overlay || m_overlay->targetWindow() != m_activeOverlayWindow) {
            QWidget *targetWindow = m_activeOverlayWindow;
            closeAutomationOverlay();
            m_activeOverlayWindow = targetWindow;
            m_overlay = new AutomationOverlay(targetWindow);
        }

        m_overlay->syncToWindow();
    }

    void updateVisualFeedback(QWidget *target, const QPoint &localPos, bool doubleClick)
    {
        if (!m_visualFeedbackEnabled || !target)
            return;

        m_activeOverlayWindow = target->window();
        syncAutomationOverlay();
        if (!m_overlay)
            return;

        m_overlay->setCursorFromGlobal(target->mapToGlobal(localPos), doubleClick ? 2 : 1);
        QApplication::processEvents();
    }

    QJsonValue invokeWidgetMethod(QWidget *widget, const QJsonObject &requestObject)
    {
        const QPlaywrightClassMetadata metadata = QPlaywrightMetadata::classMetadata(widget);
        const QPlaywrightInvokeRequest request = QPlaywrightInvokeRequest::fromJsonObject(requestObject);

        QPlaywrightPreparedCall preparedCall;
        const QPlaywrightInvokeResult prepareResult = QPlaywrightInvoker::prepareCall(metadata, request, &preparedCall);
        if (!prepareResult.ok())
            return prepareResult.toJsonObject();

        const QPlaywrightInvokeResult executeResult = QPlaywrightInvoker::executePreparedCall(widget, preparedCall);
        QApplication::processEvents();
        return executeResult.toJsonObject();
    }

    QJsonValue jsonValueFromVariant(const QVariant &value)
    {
        const QJsonValue jsonValue = QJsonValue::fromVariant(value);
        if (!jsonValue.isUndefined())
            return jsonValue;
        if (!value.isValid() || value.isNull())
            return QJsonValue();
        return value.toString();
    }

    QJsonObject serializeWidgetProperties(QWidget *w)
    {
        QJsonObject properties;
        const QMetaObject *meta = w->metaObject();
        if (meta) {
            for (int index = 0; index < meta->propertyCount(); ++index) {
                const QMetaProperty property = meta->property(index);
                const QString name = QString::fromLatin1(property.name());
                properties[name] = jsonValueFromVariant(w->property(property.name()));
            }
        }

        const QList<QByteArray> dynamicNames = w->dynamicPropertyNames();
        for (const QByteArray &name : dynamicNames)
            properties[QString::fromLatin1(name)] = jsonValueFromVariant(w->property(name.constData()));

        return properties;
    }

    QJsonObject serializeWidgetTree(QWidget *w, int depth = 0, int maxDepth = 10)
    {
        if (isAutomationOverlayWidget(w))
            throw std::runtime_error("Automation overlay widgets are excluded from snapshot capture");

        auto &reg = QPlaywrightRegistry::instance();

        QJsonObject obj;
        obj["wid"] = reg.registerWidget(w);
        obj["class"] = QString::fromLatin1(w->metaObject()->className());
        obj["objectName"] = w->objectName();
        obj["text"] = QPlaywrightRoles::widgetText(w);
        obj["visible"] = w->isVisible();
        obj["enabled"] = w->isEnabled();

        const QString role = QPlaywrightMetadata::classMetadata(w).role().trimmed().toLower();
        if (!role.isEmpty()) {
            QJsonArray roleArray;
            roleArray.append(role);
            obj["roles"] = roleArray;
        }

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

        if (auto *spin = qobject_cast<const QSpinBox *>(w))
            obj["value"] = spin->value();
        if (auto *dspin = qobject_cast<const QDoubleSpinBox *>(w))
            obj["value"] = dspin->value();
        if (auto *slider = qobject_cast<const QSlider *>(w))
            obj["value"] = slider->value();

        if (depth < maxDepth) {
            QJsonArray children;
            for (QObject *child : w->children()) {
                QWidget *cw = qobject_cast<QWidget *>(child);
                if (cw && !isAutomationOverlayWidget(cw))
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
            QJsonObject r = serializeWidgetTree(w, 0, params["max_depth"].toInt(0));
            r["wid"] = wid;
            return r;
        }

        if (method == "find_all") {
            auto widgets = resolveWidgets(params);
            QJsonArray arr;
            for (QWidget *w : widgets) {
                int wid = reg.registerWidget(w);
                QJsonObject r = serializeWidgetTree(w, 0, params["max_depth"].toInt(0));
                r["wid"] = wid;
                arr.append(r);
            }
            return arr;
        }

        if (method == "widget_tree") {
            int maxDepth = params["max_depth"].toInt(10);
            QJsonArray arr;
            QList<QWidget *> roots;
            if (params.contains("wid")) {
                QWidget *root = reg.get(params["wid"].toInt());
                if (!root)
                    throw std::runtime_error("Widget not found by wid");
                roots.append(root);
            } else {
                roots = topLevelWidgets();
            }
            for (QWidget *w : roots) {
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

        if (method == "get_methods") {
            QWidget *w = resolveOne(params);
            return QPlaywrightMetadata::methodSchema(w);
        }

        if (method == "get_property") {
            QWidget *w = resolveOne(params);
            QString prop = params["property"].toString();
            QVariant val = w->property(prop.toLatin1().constData());
            return jsonValueFromVariant(val);
        }

        if (method == "get_properties") {
            QWidget *w = resolveOne(params);
            return serializeWidgetProperties(w);
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
        if (method == "invoke") {
            QWidget *w = resolveOne(params);
            return invokeWidgetMethod(w, params["request"].toObject());
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
            QWidget *w = (params.contains("wid") || params.contains("selector"))
                ? resolveOne(params)
                : resolvePressTarget(params);
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
                auto windows = topLevelWidgets();
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

            const bool hasClipX = params.contains("x") && !params.value("x").isNull();
            const bool hasClipY = params.contains("y") && !params.value("y").isNull();
            const bool hasClipWidth = params.contains("width") && !params.value("width").isNull();
            const bool hasClipHeight = params.contains("height") && !params.value("height").isNull();

            QPixmap pixmap;
            const bool hideOverlayForCapture =
                m_overlay &&
                m_overlay->isVisible() &&
                m_overlay->targetWindow() == w->window();
            if (hideOverlayForCapture) {
                m_overlay->hide();
                QApplication::processEvents();
            }
            if (hasClipX || hasClipY || hasClipWidth || hasClipHeight) {
                if (!(hasClipX && hasClipY && hasClipWidth && hasClipHeight)) {
                    throw std::runtime_error("Screenshot clipping requires x, y, width, and height together");
                }
                const int clipX = params.value("x").toInt();
                const int clipY = params.value("y").toInt();
                const int clipWidth = params.value("width").toInt();
                const int clipHeight = params.value("height").toInt();
                if (clipX < 0 || clipY < 0 || clipWidth <= 0 || clipHeight <= 0) {
                    throw std::runtime_error("Screenshot clipping requires non-negative x/y and positive width/height");
                }
                pixmap = w->grab(QRect(clipX, clipY, clipWidth, clipHeight));
            } else {
                pixmap = w->grab();
            }
            if (hideOverlayForCapture) {
                m_overlay->show();
                m_overlay->raise();
                m_overlay->update();
                QApplication::processEvents();
            }
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
            for (QWidget *w : topLevelWidgets()) {
                if (!w->isVisible()) continue;
                int wid = reg.registerWidget(w);
                QJsonObject r;
                r["wid"] = wid;
                r["title"] = w->windowTitle();
                r["class"] = QString::fromLatin1(w->metaObject()->className());
                r["width"] = w->width();
                r["height"] = w->height();
                r["is_modal"] = w->isModal();
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
                roots = topLevelWidgets();
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

    QWidget *resolvePressTarget(const QJsonObject &params)
    {
        auto &reg = QPlaywrightRegistry::instance();

        if (QWidget *focused = QApplication::focusWidget())
            return focused;

        if (params.contains("window_wid")) {
            if (QWidget *window = reg.get(params["window_wid"].toInt()))
                return window;
        }

        for (QWidget *window : topLevelWidgets()) {
            if (window->isVisible())
                return window;
        }

        throw std::runtime_error("No visible window found for targetless key press");
    }

    QWidget *primaryEventTarget(QWidget *w)
    {
        if (auto *scrollArea = qobject_cast<QAbstractScrollArea *>(w)) {
            if (scrollArea->viewport())
                return scrollArea->viewport();
        }
        return w;
    }

    bool isSameOrDescendantWidget(QWidget *candidate, QWidget *ancestor)
    {
        QWidget *current = candidate;
        while (current) {
            if (current == ancestor)
                return true;
            current = current->parentWidget();
        }
        return false;
    }

    struct ClickTarget
    {
        QWidget *widget;
        QPoint localPos;
    };

    ClickTarget resolveClickTarget(QWidget *w)
    {
        QWidget *target = primaryEventTarget(w);
        if (!target->isVisible()) {
            throw std::runtime_error(
                std::string("Cannot click widget of type: ") + std::string(w->metaObject()->className()) +
                "; event target is not visible"
            );
        }
        if (!target->isEnabled()) {
            throw std::runtime_error(
                std::string("Cannot click widget of type: ") + std::string(w->metaObject()->className()) +
                "; event target is disabled"
            );
        }

        QPoint center = target->rect().center();
        QPoint globalPos = target->mapToGlobal(center);
        QWidget *hit = QApplication::widgetAt(globalPos);
        if (isAutomationOverlayWidget(hit))
            hit = nullptr;
        if (!hit)
            hit = target->childAt(center);
        if (!hit)
            hit = target;

        if (!isSameOrDescendantWidget(hit, target)) {
            throw std::runtime_error(
                std::string("Cannot click widget of type: ") + std::string(w->metaObject()->className()) +
                "; center point is covered by " + std::string(hit->metaObject()->className())
            );
        }
        if (!hit->isVisible()) {
            throw std::runtime_error(
                std::string("Cannot click widget of type: ") + std::string(w->metaObject()->className()) +
                "; resolved click target is not visible"
            );
        }
        if (!hit->isEnabled()) {
            throw std::runtime_error(
                std::string("Cannot click widget of type: ") + std::string(w->metaObject()->className()) +
                "; resolved click target is disabled"
            );
        }

        return {hit, hit->mapFromGlobal(globalPos)};
    }

    // ----- Action helpers -----

    void clickWidget(QWidget *w, bool doubleClick)
    {
        auto clickTarget = resolveClickTarget(w);
        QWidget *target = clickTarget.widget;
        target->setFocus(Qt::MouseFocusReason);
        QApplication::processEvents();
        updateVisualFeedback(target, clickTarget.localPos, doubleClick);
        if (doubleClick)
            QTest::mouseDClick(target, Qt::LeftButton, Qt::NoModifier, clickTarget.localPos);
        else
            QTest::mouseClick(target, Qt::LeftButton, Qt::NoModifier, clickTarget.localPos);
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
        QWidget *target = primaryEventTarget(w);
        QPoint center = target->rect().center();
        QPoint globalPos = target->mapToGlobal(center);
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
        QApplication::sendEvent(target, &event);
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

    bool m_visualFeedbackEnabled = false;
    QTimer m_overlaySyncTimer;
    QPointer<QWidget> m_activeOverlayWindow;
    QPointer<AutomationOverlay> m_overlay;
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
 *   QPlaywrightAgent::start(19876, "127.0.0.1", true);
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
     * @param visualFeedback Whether to show click feedback rings in the UI.
     * @return Pointer to the agent instance (owned by QApplication)
     */
    static QPlaywrightAgent *start(int port = 19876, const QString &host = "127.0.0.1", bool visualFeedback = false)
    {
        auto *app = QApplication::instance();
        Q_ASSERT(app && "QApplication must be created before calling QPlaywrightAgent::start()");

        auto *agent = new QPlaywrightAgent(app);
        agent->m_handler = new QPlaywrightHandler(agent);
        agent->m_handler->setVisualFeedbackEnabled(visualFeedback);

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
