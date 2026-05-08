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
#include <QLinearGradient>
#include <QMutex>
#include <QPainter>
#include <QPen>
#include <QPointer>
#include <QBrush>
#include <QPolygon>
#include <QWindow>
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
#include <QHash>

#include <algorithm>
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
    // Typed storage for converting QVariant arguments before passing to invokeMethod.
    // Each supported type gets its own fixed-size array (up to Qt's 9-arg limit) so that
    // QGenericArgument pointers remain stable across multiple convert() calls.
    struct ArgStorage {
        static const int MAX_ARGS = 9;
        QString  strStore[MAX_ARGS];
        QVariant varStore[MAX_ARGS];
        int      intStore[MAX_ARGS];
        bool     boolStore[MAX_ARGS];
        double   dblStore[MAX_ARGS];
        int stringIndex, variantIndex, intIndex, boolIndex, doubleIndex;

        ArgStorage() : stringIndex(0), variantIndex(0), intIndex(0), boolIndex(0), doubleIndex(0) {}

        // Convert one (typeName, value) pair and return a stable QGenericArgument.
        // Unknown type names fall back to QVariant so the invokeMethod call can
        // still succeed when the method is declared with QVariant parameters.
        QGenericArgument convert(const QString &typeName, const QVariant &value)
        {
            if (typeName == QStringLiteral("QString"))  { strStore[stringIndex]    = value.toString();  return Q_ARG(QString,  strStore[stringIndex++]);  }
            if (typeName == QStringLiteral("int"))      { intStore[intIndex]       = value.toInt();     return Q_ARG(int,      intStore[intIndex++]);     }
            if (typeName == QStringLiteral("bool"))     { boolStore[boolIndex]     = value.toBool();    return Q_ARG(bool,     boolStore[boolIndex++]);   }
            if (typeName == QStringLiteral("double"))   { dblStore[doubleIndex]    = value.toDouble();  return Q_ARG(double,   dblStore[doubleIndex++]);  }
            /* QVariant or any other declared type */    varStore[variantIndex]    = value;             return Q_ARG(QVariant, varStore[variantIndex++]);
        }
    };

    // Build generic args from declared types + runtime values, then call invokeMethod.
    // Supports 0–9 arguments (Qt's hard limit). Returns false for >9 args.
    static bool invokeNoReturn(QObject *target, const QPlaywrightClassMethod &method, const QVariantList &args)
    {
        const QByteArray methodName = method.name().toLatin1();
        const QVector<QPlaywrightMethodArg> &decl = method.args();
        const int n = args.size();

        if (n == 0)
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection);

        ArgStorage s;
        QGenericArgument g[9];
        const int bounded = qMin(n, qMin(static_cast<int>(decl.size()), 9));
        for (int i = 0; i < bounded; ++i)
            g[i] = s.convert(decl.at(i).type(), args.at(i));

        switch (bounded) {
        case 1: return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, g[0]);
        case 2: return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, g[0], g[1]);
        case 3: return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, g[0], g[1], g[2]);
        case 4: return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, g[0], g[1], g[2], g[3]);
        case 5: return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, g[0], g[1], g[2], g[3], g[4]);
        case 6: return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, g[0], g[1], g[2], g[3], g[4], g[5]);
        case 7: return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, g[0], g[1], g[2], g[3], g[4], g[5], g[6]);
        case 8: return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, g[0], g[1], g[2], g[3], g[4], g[5], g[6], g[7]);
        case 9: return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, g[0], g[1], g[2], g[3], g[4], g[5], g[6], g[7], g[8]);
        default: return false;
        }
    }

    template <typename ReturnArg>
    static bool invokeWithReturn(QObject *target, const QPlaywrightClassMethod &method, const QVariantList &args, ReturnArg returnArg)
    {
        const QByteArray methodName = method.name().toLatin1();
        const QVector<QPlaywrightMethodArg> &decl = method.args();
        const int n = args.size();

        if (n == 0)
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, returnArg);

        ArgStorage s;
        QGenericArgument g[9];
        const int bounded = qMin(n, qMin(static_cast<int>(decl.size()), 9));
        for (int i = 0; i < bounded; ++i)
            g[i] = s.convert(decl.at(i).type(), args.at(i));

        switch (bounded) {
        case 1: return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, returnArg, g[0]);
        case 2: return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, returnArg, g[0], g[1]);
        case 3: return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, returnArg, g[0], g[1], g[2]);
        case 4: return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, returnArg, g[0], g[1], g[2], g[3]);
        case 5: return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, returnArg, g[0], g[1], g[2], g[3], g[4]);
        case 6: return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, returnArg, g[0], g[1], g[2], g[3], g[4], g[5]);
        case 7: return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, returnArg, g[0], g[1], g[2], g[3], g[4], g[5], g[6]);
        case 8: return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, returnArg, g[0], g[1], g[2], g[3], g[4], g[5], g[6], g[7]);
        case 9: return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, returnArg, g[0], g[1], g[2], g[3], g[4], g[5], g[6], g[7], g[8]);
        default: return false;
        }
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
    // Only real visible text belongs to the text channel.
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
    if (auto *gb = qobject_cast<const QGroupBox *>(widget))
        return gb->title();
    if (auto *tw = qobject_cast<const QTabWidget *>(widget))
        return tw->tabText(tw->currentIndex());
    return QString();
}

inline QString widgetAccessibleName(const QWidget *widget)
{
    return widget->accessibleName();
}

inline QString widgetAccessibleDescription(const QWidget *widget)
{
    return widget->accessibleDescription();
}

inline QString widgetCurrentText(const QWidget *widget)
{
    if (auto *combo = qobject_cast<const QComboBox *>(widget))
        return combo->currentText();
    return QString();
}

inline QVariant widgetValue(const QWidget *widget)
{
    if (auto *spin = qobject_cast<const QSpinBox *>(widget))
        return spin->value();
    if (auto *dspin = qobject_cast<const QDoubleSpinBox *>(widget))
        return dspin->value();
    if (auto *slider = qobject_cast<const QSlider *>(widget))
        return slider->value();
    return QVariant();
}

inline QString widgetInputValue(const QWidget *widget)
{
    if (auto *combo = qobject_cast<const QComboBox *>(widget))
        return combo->currentText();
    if (auto *edit = qobject_cast<const QLineEdit *>(widget))
        return edit->text();
    if (auto *te = qobject_cast<const QTextEdit *>(widget))
        return te->toPlainText();
    if (auto *pte = qobject_cast<const QPlainTextEdit *>(widget))
        return pte->toPlainText();
    return widgetText(widget);
}

inline QString widgetPlaceholderText(const QWidget *widget)
{
    if (auto *edit = qobject_cast<const QLineEdit *>(widget))
        return edit->placeholderText();
    return QString();
}

inline QString widgetToolTip(const QWidget *widget)
{
    return widget->toolTip();
}

inline QString widgetWindowTitle(const QWidget *widget)
{
    return widget->windowTitle();
}

} // namespace QPlaywrightRoles

// -------------------------------------------------------------------------- //
//  Selector matching                                                          //
// -------------------------------------------------------------------------- //

namespace QPlaywrightSelector {

struct Selector {
    QString type;   // "role", "text", "has_text", "a11y_name", "a11y_desc", "name", "id", "cls"
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
    if (sel.startsWith("a11y-name="))
        return {"a11y_name", sel.mid(10)};
    if (sel.startsWith("a11y-desc="))
        return {"a11y_desc", sel.mid(10)};
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
    if (sel.type == "a11y_name")
        return QPlaywrightRoles::widgetAccessibleName(widget) == sel.value;
    if (sel.type == "a11y_desc")
        return QPlaywrightRoles::widgetAccessibleDescription(widget) == sel.value;
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

inline void setJsonStringIfNotEmpty(QJsonObject &obj, const char *key, const QString &value)
{
    if (!value.isEmpty())
        obj[key] = value;
}

inline void setJsonVariantIfValid(QJsonObject &obj, const char *key, const QVariant &value)
{
    if (value.isValid())
        obj[key] = QJsonValue::fromVariant(value);
}

inline QJsonObject widgetToJson(const QWidget *w, int depth = 0, int maxDepth = 10)
{
    QJsonObject obj;
    obj["class"] = QString::fromLatin1(w->metaObject()->className());
    obj["visible"] = w->isVisible();
    obj["enabled"] = w->isEnabled();

    setJsonStringIfNotEmpty(obj, "objectName", w->objectName());
    setJsonStringIfNotEmpty(obj, "text", QPlaywrightRoles::widgetText(w));
    setJsonStringIfNotEmpty(obj, "accessibleName", QPlaywrightRoles::widgetAccessibleName(w));
    setJsonStringIfNotEmpty(obj, "accessibleDescription", QPlaywrightRoles::widgetAccessibleDescription(w));
    setJsonStringIfNotEmpty(obj, "windowTitle", QPlaywrightRoles::widgetWindowTitle(w));
    setJsonStringIfNotEmpty(obj, "placeholderText", QPlaywrightRoles::widgetPlaceholderText(w));
    setJsonStringIfNotEmpty(obj, "toolTip", QPlaywrightRoles::widgetToolTip(w));

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
        setJsonStringIfNotEmpty(obj, "currentText", combo->currentText());
        obj["currentIndex"] = combo->currentIndex();
    }

    setJsonVariantIfValid(obj, "value", QPlaywrightRoles::widgetValue(w));

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
        if (!w)
            return 0;

        quintptr key = reinterpret_cast<quintptr>(w);
        auto existing = m_w2id.constFind(key);
        if (existing != m_w2id.constEnd()) {
            const int wid = existing.value();
            auto current = m_id2w.constFind(wid);
            if (current != m_id2w.constEnd() && !current.value().isNull())
                return wid;
            m_w2id.remove(key);
            m_id2w.remove(wid);
        }

        int wid = m_next++;
        m_w2id[key] = wid;
        m_id2w[wid] = w;
        QObject::connect(w, &QObject::destroyed, [this, key, wid]() {
            m_w2id.remove(key);
            m_id2w.remove(wid);
        });
        return wid;
    }

    QWidget *get(int wid) const {
        auto it = m_id2w.constFind(wid);
        if (it == m_id2w.constEnd() || it.value().isNull())
            return nullptr;
        return it.value().data();
    }

private:
    QHash<quintptr, int> m_w2id;
    QHash<int, QPointer<QWidget>> m_id2w;
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
        if (!enabled) {
            if (m_overlayManager)
                m_overlayManager->setEnabled(false);
            return;
        }

        ensureOverlayManager()->setEnabled(true);
        ensureOverlayManager()->setSharedAgentName(activeSessionAgentName());
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
        const QString sessionId = params.take(QStringLiteral("_sessionId")).toString();
        if (!sessionId.isEmpty())
            markSessionActive(sessionId);
        int id = request["id"].toInt();

        QJsonObject response;
        response["id"] = id;

        try {
            QJsonValue result;
            if (method == "set_session_info") {
                setSessionInfo(sessionId, params["agentName"].toString());
                QJsonObject sessionInfo;
                sessionInfo["agentName"] = activeSessionAgentName();
                result = sessionInfo;
            } else {
                result = dispatch(method, params);
            }
            response["result"] = result;
        } catch (const std::exception &e) {
            QJsonObject error;
            error["message"] = QString::fromStdString(e.what());
            response["error"] = error;
        }

        return response;
    }

public:
    void onClientDisconnected(const QString &sessionId)
    {
        removeSessionInfo(sessionId);
    }

private:
    static constexpr const char *kAutomationOverlayObjectName = "_qplaywright_automation_overlay";
    static constexpr const char *kAutomationOverlayProperty = "qplaywrightAutomationOverlay";
    static constexpr int kOverlayEdgePadding = 3;
    static constexpr int kOverlayFrameOutset = 3;
    static constexpr int kOverlayBadgeGap = 3;
    static constexpr int kOverlayBadgeLeftInset = 6;
    static constexpr int kOverlayBadgeTopInset = 6;
    static constexpr int kOverlayCornerRadius = 6;
    static constexpr int kOverlayBadgeRadius = 7;

    static bool isOverlayTargetWindowVisible(QWidget *widget)
    {
        if (!widget)
            return false;
        if (widget->objectName() == QString::fromLatin1(kAutomationOverlayObjectName))
            return false;
        if (widget->property(kAutomationOverlayProperty).toBool())
            return false;
        if (!widget->isVisible())
            return false;
        if (widget->isMinimized())
            return false;
        if (widget->windowState().testFlag(Qt::WindowMinimized))
            return false;
        QWindow *windowHandle = widget->windowHandle();
        if (windowHandle && !windowHandle->isExposed())
            return false;
        return true;
    }

    static bool isQtApplicationActive()
    {
        if (!qApp)
            return true;
        return qApp->applicationState() == Qt::ApplicationActive;
    }

    static QWidget *activeModalTopLevelWidget()
    {
        QWidget *activeModal = QApplication::activeModalWidget();
        if (!activeModal)
            return nullptr;
        QWidget *modalWindow = activeModal->window();
        if (!isOverlayTargetWindowVisible(modalWindow))
            return nullptr;
        return modalWindow;
    }

    bool isWindowBlockedByModal(QWidget *widget) const
    {
        QWidget *modalWindow = activeModalTopLevelWidget();
        if (!modalWindow || !widget)
            return false;
        QWidget *widgetWindow = widget->window();
        return widgetWindow && widgetWindow != modalWindow;
    }

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
            : QWidget(nullptr), m_targetWindow(targetWindow)
        {
            setWindowFlags(
                Qt::Tool
                | Qt::FramelessWindowHint
                | Qt::WindowStaysOnTopHint
                | Qt::WindowTransparentForInput
            );
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
            if (!m_managerActive) {
                m_timer.stop();
                hide();
                return;
            }

            if (!isOverlayTargetWindowVisible(m_targetWindow.data())) {
                hide();
                return;
            }

            const LayoutMetrics layout = layoutMetrics();
            m_contentOrigin = layout.targetRect.topLeft();
            const QRect targetRect(
                layout.wrappedGlobalRect.x() - layout.wrappedRect.x(),
                layout.wrappedGlobalRect.y() - layout.wrappedRect.y(),
                layout.overlayWidth,
                layout.overlayHeight
            );
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

        void setManagerActive(bool active)
        {
            if (m_managerActive == active)
                return;

            m_managerActive = active;
            if (!m_managerActive) {
                m_pulses.clear();
                m_timer.stop();
                hide();
                return;
            }

            syncToWindow();
        }

        void setSharedAgentName(const QString &agentName)
        {
            const QString normalized = agentName.trimmed();
            if (m_sharedAgentName == normalized)
                return;
            m_sharedAgentName = normalized;
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
            const QColor frameColor(20, 132, 255, 150);
            const LayoutMetrics layout = layoutMetrics();

            if (!layout.badgeText.isEmpty()) {
                const QRect frameRect = layout.frameRect;
                QLinearGradient glowGradient(frameRect.topLeft(), frameRect.bottomRight());
                glowGradient.setColorAt(0.0, QColor(0, 245, 255, 60));
                glowGradient.setColorAt(0.34, QColor(20, 132, 255, 65));
                glowGradient.setColorAt(0.7, QColor(255, 76, 196, 60));
                glowGradient.setColorAt(1.0, QColor(0, 245, 255, 55));
                painter.setPen(QPen(QBrush(glowGradient), 6));
                painter.setBrush(Qt::NoBrush);
                painter.drawRoundedRect(frameRect, kOverlayCornerRadius, kOverlayCornerRadius);

                QLinearGradient frameGradient(frameRect.topLeft(), frameRect.bottomRight());
                frameGradient.setColorAt(0.0, QColor(0, 245, 255, 185));
                frameGradient.setColorAt(0.34, frameColor);
                frameGradient.setColorAt(0.7, QColor(255, 76, 196, 175));
                frameGradient.setColorAt(1.0, QColor(0, 245, 255, 180));
                painter.setPen(QPen(QBrush(frameGradient), 2));
                painter.setBrush(Qt::NoBrush);
                painter.drawRoundedRect(frameRect, kOverlayCornerRadius, kOverlayCornerRadius);

                painter.setFont(layout.badgeFont);
                const QRect badgeRect = layout.badgeRect;

                painter.setPen(Qt::NoPen);
                painter.setBrush(QColor(9, 29, 61, 150));
                painter.drawRoundedRect(badgeRect, kOverlayBadgeRadius, kOverlayBadgeRadius);
                painter.setPen(QPen(QColor(140, 228, 255, 135), 1));
                painter.setBrush(Qt::NoBrush);
                painter.drawRoundedRect(badgeRect, kOverlayBadgeRadius, kOverlayBadgeRadius);
                painter.setPen(QColor(255, 255, 255, 230));
                painter.drawText(badgeRect.adjusted(9, 0, -9, 0), Qt::AlignVCenter | Qt::AlignLeft, layout.badgeText);
            }

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
                    const QPoint pulseCenter = overlayPointFromTarget(pulse.center);

                    painter.setPen(QPen(pulseColor, 2));
                    painter.setBrush(Qt::NoBrush);
                    painter.drawEllipse(pulseCenter, radius, radius);
                }
            }

            if (!m_cursorPosValid)
                return;

            const QPoint cursorPos = overlayPointFromTarget(m_cursorPos);

            const QPolygon shadow({
                cursorPos + QPoint(2, 2),
                cursorPos + QPoint(2, 20),
                cursorPos + QPoint(7, 15),
                cursorPos + QPoint(10, 23),
                cursorPos + QPoint(13, 22),
                cursorPos + QPoint(10, 14),
                cursorPos + QPoint(17, 14),
            });
            const QPolygon cursor({
                cursorPos,
                cursorPos + QPoint(0, 18),
                cursorPos + QPoint(5, 13),
                cursorPos + QPoint(8, 21),
                cursorPos + QPoint(11, 20),
                cursorPos + QPoint(8, 12),
                cursorPos + QPoint(15, 12),
            });

            painter.setPen(Qt::NoPen);
            painter.setBrush(QColor(0, 0, 0, 110));
            painter.drawPolygon(shadow);
            painter.setPen(QPen(QColor(0, 0, 0, 200), 1));
            painter.setBrush(QBrush(QColor(255, 255, 255, 240)));
            painter.drawPolygon(cursor);
            painter.setPen(Qt::NoPen);
            painter.setBrush(coreColor);
            painter.drawEllipse(cursorPos, 4, 4);
        }

    private:
        struct LayoutMetrics
        {
            QRect targetRect;
            QRect wrappedRect;
            QRect wrappedGlobalRect;
            QRect frameRect;
            QRect badgeRect;
            QFont badgeFont;
            QString badgeText;
            bool isMaximized = false;
            int overlayWidth = 0;
            int overlayHeight = 0;
        };

        QString badgeText() const
        {
            if (m_sharedAgentName.isEmpty())
                return QString();
            return QStringLiteral("正在与 Agent %1 共享").arg(m_sharedAgentName);
        }

        QFont badgeFont() const
        {
            QFont font = this->font();
            font.setFamily(qApp->font().family());
            if (font.pointSizeF() > 0.0)
                font.setPointSizeF(qMax(7.5, font.pointSizeF() - 2.0));
            else if (font.pixelSize() > 0)
                font.setPixelSize(qMax(10, font.pixelSize() - 3));
            else
                font.setPointSizeF(7.5);
            return font;
        }

        bool isMaximizedWindow() const
        {
            if (!m_targetWindow)
                return false;
            if (m_targetWindow->isMaximized())
                return true;
            return m_targetWindow->windowState().testFlag(Qt::WindowMaximized);
        }

        QRect wrappedGlobalRect() const
        {
            if (!m_targetWindow)
                return QRect();

            const QPoint contentTopLeft = m_targetWindow->mapToGlobal(m_targetWindow->rect().topLeft());
            const QRect contentGlobalRect(contentTopLeft, m_targetWindow->size());
            const QRect frameGlobalRect = m_targetWindow->frameGeometry();
            if (
                frameGlobalRect.isValid()
                && frameGlobalRect.contains(contentGlobalRect)
                && (
                    frameGlobalRect.topLeft() != contentGlobalRect.topLeft()
                    || frameGlobalRect.size() != contentGlobalRect.size()
                )
            ) {
                return frameGlobalRect;
            }

            return contentGlobalRect;
        }

        LayoutMetrics layoutMetrics() const
        {
            LayoutMetrics layout;
            layout.badgeText = badgeText();
            layout.badgeFont = badgeFont();

            int badgeWidth = 0;
            int badgeHeight = 0;
            if (!layout.badgeText.isEmpty()) {
                const QFontMetrics metrics(layout.badgeFont);
                badgeWidth = metrics.horizontalAdvance(layout.badgeText) + 18;
                badgeHeight = metrics.height() + 8;
            }

            layout.wrappedGlobalRect = wrappedGlobalRect();
            const QPoint contentTopLeft = m_targetWindow ? m_targetWindow->mapToGlobal(m_targetWindow->rect().topLeft()) : QPoint();
            const QPoint contentOffset = contentTopLeft - layout.wrappedGlobalRect.topLeft();
            layout.isMaximized = isMaximizedWindow();
            const int badgeReserve = (!layout.badgeText.isEmpty() && !layout.isMaximized) ? badgeHeight + kOverlayBadgeGap : 0;
            layout.wrappedRect = QRect(
                kOverlayEdgePadding + kOverlayFrameOutset,
                kOverlayEdgePadding + kOverlayFrameOutset + badgeReserve,
                layout.wrappedGlobalRect.width(),
                layout.wrappedGlobalRect.height()
            );
            layout.targetRect = QRect(
                layout.wrappedRect.left() + contentOffset.x(),
                layout.wrappedRect.top() + contentOffset.y(),
                m_targetWindow ? m_targetWindow->width() : 0,
                m_targetWindow ? m_targetWindow->height() : 0
            );
            layout.frameRect = layout.wrappedRect.adjusted(
                -kOverlayFrameOutset,
                -kOverlayFrameOutset,
                kOverlayFrameOutset,
                kOverlayFrameOutset
            );
            layout.overlayWidth = layout.frameRect.right() + kOverlayEdgePadding + 1;
            layout.overlayHeight = layout.frameRect.bottom() + kOverlayEdgePadding + 1;

            if (!layout.badgeText.isEmpty()) {
                if (layout.isMaximized) {
                    const int badgeBandTop = layout.frameRect.top() + kOverlayBadgeTopInset;
                    const int badgeBandBottom = qMax(
                        badgeBandTop,
                        layout.targetRect.top() - kOverlayBadgeTopInset - badgeHeight
                    );
                    const int centeredBadgeTop = layout.frameRect.top() + (layout.targetRect.top() - layout.frameRect.top() - badgeHeight) / 2;
                    const int badgeTop = qMin(qMax(centeredBadgeTop, badgeBandTop), badgeBandBottom);
                    layout.badgeRect = QRect(
                        layout.frameRect.center().x() - badgeWidth / 2,
                        badgeTop,
                        badgeWidth,
                        badgeHeight
                    );
                } else {
                    layout.badgeRect = QRect(
                        layout.frameRect.left() + kOverlayBadgeLeftInset,
                        layout.frameRect.top() - kOverlayBadgeGap - badgeHeight,
                        badgeWidth,
                        badgeHeight
                    );
                }
                layout.overlayWidth = qMax(layout.overlayWidth, layout.badgeRect.right() + kOverlayEdgePadding + 1);
                layout.overlayHeight = qMax(layout.overlayHeight, layout.badgeRect.bottom() + kOverlayEdgePadding + 1);
            }

            return layout;
        }

        QPoint overlayPointFromTarget(const QPoint &targetPoint) const
        {
            return QPoint(targetPoint.x() + m_contentOrigin.x(), targetPoint.y() + m_contentOrigin.y());
        }

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

            if (!m_managerActive || !isOverlayTargetWindowVisible(m_targetWindow.data())) {
                if (!m_managerActive)
                    m_pulses.clear();
                hide();
                if (m_pulses.isEmpty())
                    m_timer.stop();
                return;
            }

            syncToWindow();
            update();
        }

        QPointer<QWidget> m_targetWindow;
        QString m_sharedAgentName;
        QPoint m_cursorPos;
        QPoint m_contentOrigin;
        bool m_managerActive = false;
        bool m_cursorPosValid = false;
        QVector<PulseRecord> m_pulses;
        QTimer m_timer;
        QElapsedTimer m_clock;
    };

    class AutomationOverlayManager : public QObject
    {
    public:
        explicit AutomationOverlayManager(QObject *parent = nullptr)
            : QObject(parent)
        {
            m_timer.setInterval(16);
            QObject::connect(&m_timer, &QTimer::timeout, this, &AutomationOverlayManager::syncVisibility);
            m_timer.start();
        }

        void setEnabled(bool enabled)
        {
            m_enabled = enabled;
            if (!m_enabled) {
                closeAll();
                return;
            }
            syncVisibility();
        }

        void setSharedAgentName(const QString &agentName)
        {
            m_sharedAgentName = agentName.trimmed();
            for (auto it = m_overlays.begin(); it != m_overlays.end(); ++it) {
                if (!it.value().isNull())
                    it.value()->setSharedAgentName(m_sharedAgentName);
            }
            if (m_sharedAgentName.isEmpty()) {
                closeAll();
                return;
            }
            syncVisibility();
        }

        void moveCursor(QWidget *widget, const QPoint &localPos, int pulseCount)
        {
            if (!m_enabled || !widget)
                return;

            QWidget *targetWindow = widget->window();
            if (!isOverlayTargetWindowVisible(targetWindow))
                return;

            m_activeWindow = targetWindow;
            AutomationOverlay *overlay = ensureOverlay(targetWindow);
            if (!overlay)
                return;

            syncVisibility();
            overlay->setManagerActive(true);
            overlay->setCursorFromGlobal(widget->mapToGlobal(localPos), pulseCount);
        }

        AutomationOverlay *overlayForWindow(QWidget *targetWindow) const
        {
            auto it = m_overlays.find(targetWindow);
            if (it == m_overlays.end() || it.value().isNull())
                return nullptr;
            return it.value().data();
        }

        void closeAll()
        {
            const QList<QWidget *> keys = m_overlays.keys();
            for (QWidget *targetWindow : keys)
                dropOverlay(targetWindow);
            m_activeWindow = nullptr;
        }

    protected:
        bool eventFilter(QObject *watched, QEvent *event) override
        {
            QWidget *targetWindow = qobject_cast<QWidget *>(watched);
            if (!targetWindow)
                return QObject::eventFilter(watched, event);

            AutomationOverlay *overlay = overlayForWindow(targetWindow);
            if (!overlay)
                return QObject::eventFilter(watched, event);

            switch (event->type()) {
            case QEvent::Move:
            case QEvent::Resize:
            case QEvent::Show:
            case QEvent::WindowStateChange:
                if (m_enabled && targetWindow == m_activeWindow && isOverlayTargetWindowVisible(targetWindow))
                    overlay->syncToWindow(event->type() == QEvent::Show);
                else
                    overlay->setManagerActive(false);
                break;
            case QEvent::Hide:
            case QEvent::Close:
                overlay->setManagerActive(false);
                if (targetWindow == m_activeWindow)
                    m_activeWindow = nullptr;
                break;
            default:
                break;
            }

            return QObject::eventFilter(watched, event);
        }

    private:
        AutomationOverlay *ensureOverlay(QWidget *targetWindow)
        {
            auto it = m_overlays.find(targetWindow);
            if (it != m_overlays.end() && !it.value().isNull())
            {
                it.value()->setSharedAgentName(m_sharedAgentName);
                it.value()->setManagerActive(targetWindow == m_activeWindow);
                return it.value().data();
            }

            AutomationOverlay *overlay = new AutomationOverlay(targetWindow);
            overlay->setSharedAgentName(m_sharedAgentName);
            overlay->setManagerActive(targetWindow == m_activeWindow);
            m_overlays.insert(targetWindow, overlay);
            targetWindow->removeEventFilter(this);
            targetWindow->installEventFilter(this);
            QObject::connect(targetWindow, &QObject::destroyed, this, [this, targetWindow] {
                dropOverlay(targetWindow, false);
            });
            return overlay;
        }

        void dropOverlay(QWidget *targetWindow, bool removeFilter = true)
        {
            auto it = m_overlays.find(targetWindow);
            if (it == m_overlays.end())
                return;

            if (removeFilter && targetWindow)
                targetWindow->removeEventFilter(this);

            if (!it.value().isNull()) {
                it.value()->closeOverlay();
                it.value()->deleteLater();
            }

            m_overlays.erase(it);
            if (targetWindow == m_activeWindow)
                m_activeWindow = nullptr;
        }

        void syncVisibility()
        {
            if (!isQtApplicationActive())
                m_activeWindow = nullptr;

            if (m_enabled && !m_sharedAgentName.isEmpty() && isQtApplicationActive()) {
                QWidget *modalWindow = QPlaywrightHandler::activeModalTopLevelWidget();
                if (modalWindow) {
                    m_activeWindow = modalWindow;
                } else {
                    QWidget *activeWindow = QApplication::activeWindow();
                    if (isOverlayTargetWindowVisible(activeWindow)) {
                        m_activeWindow = activeWindow;
                    } else if (!isOverlayTargetWindowVisible(m_activeWindow)) {
                        m_activeWindow = nullptr;
                        const auto windows = QApplication::topLevelWidgets();
                        for (QWidget *window : windows) {
                            if (isOverlayTargetWindowVisible(window)) {
                                m_activeWindow = window;
                                break;
                            }
                        }
                    }
                }

                if (m_activeWindow)
                    ensureOverlay(m_activeWindow);
            }

            QList<QWidget *> staleKeys;
            for (auto it = m_overlays.begin(); it != m_overlays.end(); ++it) {
                AutomationOverlay *overlay = it.value().data();
                if (!overlay) {
                    staleKeys.append(it.key());
                    continue;
                }

                QWidget *targetWindow = overlay->targetWindow();
                if (!targetWindow) {
                    staleKeys.append(it.key());
                    continue;
                }

                overlay->setSharedAgentName(m_sharedAgentName);
                const bool isActive = m_enabled && targetWindow == m_activeWindow;
                overlay->setManagerActive(isActive);

                if (!isOverlayTargetWindowVisible(targetWindow)) {
                    if (targetWindow == m_activeWindow)
                        m_activeWindow = nullptr;
                } else if (isActive)
                    overlay->syncToWindow();
            }
            for (QWidget *staleKey : staleKeys)
                dropOverlay(staleKey, false);
        }

        bool m_enabled = false;
        QString m_sharedAgentName;
        QHash<QWidget *, QPointer<AutomationOverlay>> m_overlays;
        QPointer<QWidget> m_activeWindow;
        QTimer m_timer;
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

    QList<QWidget *> interactableTopLevelWidgets() const
    {
        if (QWidget *modalWindow = activeModalTopLevelWidget())
            return {modalWindow};
        return topLevelWidgets();
    }

    AutomationOverlayManager *ensureOverlayManager()
    {
        if (!m_overlayManager)
            m_overlayManager = new AutomationOverlayManager(this);
        return m_overlayManager;
    }

    void syncSessionOverlayState()
    {
        if (!m_visualFeedbackEnabled)
            return;

        ensureOverlayManager()->setEnabled(true);
        ensureOverlayManager()->setSharedAgentName(activeSessionAgentName());
    }

    QString activeSessionAgentName() const
    {
        if (!m_activeSessionId.isEmpty()) {
            auto it = m_sessionAgentNames.constFind(m_activeSessionId);
            if (it != m_sessionAgentNames.constEnd())
                return it.value();
        }
        if (!m_sessionAgentNames.isEmpty())
            return m_sessionAgentNames.constBegin().value();
        return QString();
    }

    void setSessionInfo(const QString &sessionId, const QString &agentName)
    {
        if (sessionId.isEmpty())
            return;

        const QString normalizedAgentName = agentName.trimmed();
        if (normalizedAgentName.isEmpty()) {
            m_sessionAgentNames.remove(sessionId);
            if (m_activeSessionId == sessionId)
                m_activeSessionId.clear();
        } else {
            m_sessionAgentNames.insert(sessionId, normalizedAgentName);
            m_activeSessionId = sessionId;
        }

        if (m_activeSessionId.isEmpty() && !m_sessionAgentNames.isEmpty())
            m_activeSessionId = m_sessionAgentNames.constBegin().key();

        syncSessionOverlayState();
    }

    void markSessionActive(const QString &sessionId)
    {
        if (sessionId.isEmpty() || !m_sessionAgentNames.contains(sessionId) || m_activeSessionId == sessionId)
            return;
        m_activeSessionId = sessionId;
        syncSessionOverlayState();
    }

    void removeSessionInfo(const QString &sessionId)
    {
        if (sessionId.isEmpty())
            return;

        m_sessionAgentNames.remove(sessionId);
        if (m_activeSessionId == sessionId)
            m_activeSessionId.clear();
        if (m_activeSessionId.isEmpty() && !m_sessionAgentNames.isEmpty())
            m_activeSessionId = m_sessionAgentNames.constBegin().key();
        syncSessionOverlayState();
    }

    void updateVisualFeedback(QWidget *target, const QPoint &localPos, int pulseCount = 0)
    {
        if (!m_visualFeedbackEnabled || !target)
            return;

        ensureOverlayManager()->setEnabled(true);
        ensureOverlayManager()->moveCursor(target, localPos, pulseCount);
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

    QJsonObject serializeWidgetTree(QWidget *w, int depth = 0, int maxDepth = 10, bool topmostOnly = false)
    {
        if (isAutomationOverlayWidget(w))
            throw std::runtime_error("Automation overlay widgets are excluded from snapshot capture");

        auto &reg = QPlaywrightRegistry::instance();

        QJsonObject obj;
        obj["wid"] = reg.registerWidget(w);
        obj["class"] = QString::fromLatin1(w->metaObject()->className());
        obj["visible"] = w->isVisible();
        obj["enabled"] = w->isEnabled();

        QPlaywrightSerializer::setJsonStringIfNotEmpty(obj, "objectName", w->objectName());
        QPlaywrightSerializer::setJsonStringIfNotEmpty(obj, "text", QPlaywrightRoles::widgetText(w));
        QPlaywrightSerializer::setJsonStringIfNotEmpty(obj, "accessibleName", QPlaywrightRoles::widgetAccessibleName(w));
        QPlaywrightSerializer::setJsonStringIfNotEmpty(obj, "accessibleDescription", QPlaywrightRoles::widgetAccessibleDescription(w));
        QPlaywrightSerializer::setJsonStringIfNotEmpty(obj, "windowTitle", QPlaywrightRoles::widgetWindowTitle(w));
        QPlaywrightSerializer::setJsonStringIfNotEmpty(obj, "placeholderText", QPlaywrightRoles::widgetPlaceholderText(w));
        QPlaywrightSerializer::setJsonStringIfNotEmpty(obj, "toolTip", QPlaywrightRoles::widgetToolTip(w));

        const QString role = QPlaywrightMetadata::classMetadata(w).role().trimmed().toLower();
        if (!role.isEmpty()) {
            QJsonArray roleArray;
            roleArray.append(role);
            obj["roles"] = roleArray;
        }

        QString itemViewKind;
        if (qobject_cast<QTableView *>(w)) {
            itemViewKind = "table";
        } else if (qobject_cast<QListView *>(w)) {
            itemViewKind = "list";
        } else if (qobject_cast<QTreeView *>(w)) {
            itemViewKind = "tree";
        } else if (qobject_cast<QTabWidget *>(w) || qobject_cast<QTabBar *>(w)) {
            itemViewKind = "tab";
        }

        if (!itemViewKind.isEmpty()) {
            QJsonObject itemView;
            itemView["kind"] = itemViewKind;
            itemView["discoverableBy"] = "inspect_items";
            obj["itemView"] = itemView;
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
            QPlaywrightSerializer::setJsonStringIfNotEmpty(obj, "currentText", combo->currentText());
            obj["currentIndex"] = combo->currentIndex();
        }

        QPlaywrightSerializer::setJsonVariantIfValid(obj, "value", QPlaywrightRoles::widgetValue(w));

        if (depth < maxDepth) {
            QJsonArray children;
            for (QObject *child : w->children()) {
                QWidget *cw = qobject_cast<QWidget *>(child);
                if (!cw || isAutomationOverlayWidget(cw))
                    continue;
                if (cw->isWindow() && !cw->isVisible())
                    continue;
                if (topmostOnly && !isTopmostVisibleWidget(cw))
                    continue;
                children.append(serializeWidgetTree(cw, depth + 1, maxDepth, topmostOnly));
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

        if (method == "find_widgets") {
            return findWidgetsPayload(params);
        }

        if (method == "widget_tree") {
            int maxDepth = params["max_depth"].toInt(10);
            const bool topmostOnly = params["topmost_only"].toBool(false);
            QJsonArray arr;
            QList<QWidget *> roots;
            if (params.contains("wid")) {
                QWidget *root = reg.get(params["wid"].toInt());
                if (!root)
                    throw std::runtime_error("Widget not found by wid");
                roots.append(root);
            } else {
                roots = interactableTopLevelWidgets();
            }
            for (QWidget *w : roots) {
                if (w->isVisible())
                    arr.append(serializeWidgetTree(w, 0, maxDepth, topmostOnly));
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
            QVariant value = QPlaywrightRoles::widgetValue(w);
            if (value.isValid()) return QJsonValue::fromVariant(value);
            return QPlaywrightRoles::widgetInputValue(w);
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

        if (method == "item_text") {
            QWidget *owner = resolveItemOwner(params);
            const QJsonObject item = params.value("item").toObject();
            const QString kind = item.value("kind").toString();
            if (kind == "table_cell") {
                ResolvedTableItem target = resolveTableItem(owner, item);
                return tableIndexText(owner, target);
            }
            if (kind == "list_item") {
                ResolvedListItem target = resolveListItem(owner, item);
                return listIndexText(owner, target);
            }
            if (kind == "tree_node") {
                ResolvedTreeItem target = resolveTreeItem(owner, item);
                return treeIndexText(owner, target);
            }
            if (kind == "tab_item") {
                ResolvedTabItem target = resolveTabItem(owner, item);
                return tabItemText(owner, target);
            }
            throw std::runtime_error(("Unsupported item kind: " + kind).toStdString());
        }

        if (method == "item_properties") {
            QWidget *owner = resolveItemOwner(params);
            const QJsonObject item = params.value("item").toObject();
            const QString kind = item.value("kind").toString();
            if (kind == "table_cell") {
                ResolvedTableItem target = resolveTableItem(owner, item);
                return tableIndexProperties(owner, target);
            }
            if (kind == "list_item") {
                ResolvedListItem target = resolveListItem(owner, item);
                return listIndexProperties(owner, target);
            }
            if (kind == "tree_node") {
                ResolvedTreeItem target = resolveTreeItem(owner, item);
                return treeIndexProperties(owner, target);
            }
            if (kind == "tab_item") {
                ResolvedTabItem target = resolveTabItem(owner, item);
                return tabItemProperties(owner, target);
            }
            throw std::runtime_error(("Unsupported item kind: " + kind).toStdString());
        }

        if (method == "item_selected") {
            QWidget *owner = resolveItemOwner(params);
            const QJsonObject item = params.value("item").toObject();
            const QString kind = item.value("kind").toString();
            if (kind == "table_cell") {
                ResolvedTableItem target = resolveTableItem(owner, item);
                return tableIndexProperties(owner, target).value("selected").toBool(false);
            }
            if (kind == "list_item") {
                ResolvedListItem target = resolveListItem(owner, item);
                return listIndexProperties(owner, target).value("selected").toBool(false);
            }
            if (kind == "tree_node") {
                ResolvedTreeItem target = resolveTreeItem(owner, item);
                return treeIndexProperties(owner, target).value("selected").toBool(false);
            }
            if (kind == "tab_item") {
                ResolvedTabItem target = resolveTabItem(owner, item);
                return tabItemSelected(owner, target);
            }
            throw std::runtime_error(("Unsupported item kind: " + kind).toStdString());
        }

        if (method == "item_visible") {
            QWidget *owner = resolveItemOwner(params);
            const QJsonObject item = params.value("item").toObject();
            const QString kind = item.value("kind").toString();
            if (kind == "table_cell") {
                ResolvedTableItem target = resolveTableItem(owner, item);
                return tableIndexVisible(owner, target);
            }
            if (kind == "list_item") {
                ResolvedListItem target = resolveListItem(owner, item);
                return listIndexVisible(owner, target);
            }
            if (kind == "tree_node") {
                ResolvedTreeItem target = resolveTreeItem(owner, item);
                return treeIndexVisible(owner, target);
            }
            if (kind == "tab_item") {
                ResolvedTabItem target = resolveTabItem(owner, item);
                return tabItemVisible(owner, target);
            }
            throw std::runtime_error(("Unsupported item kind: " + kind).toStdString());
        }

        if (method == "item_bounding_box") {
            QWidget *owner = resolveItemOwner(params);
            const QJsonObject item = params.value("item").toObject();
            const QString kind = item.value("kind").toString();
            if (kind == "table_cell") {
                ResolvedTableItem target = resolveTableItem(owner, item);
                return tableIndexBoundingBox(owner, target);
            }
            if (kind == "list_item") {
                ResolvedListItem target = resolveListItem(owner, item);
                return listIndexBoundingBox(owner, target);
            }
            if (kind == "tree_node") {
                ResolvedTreeItem target = resolveTreeItem(owner, item);
                return treeIndexBoundingBox(owner, target);
            }
            if (kind == "tab_item") {
                ResolvedTabItem target = resolveTabItem(owner, item);
                return tabItemBoundingBox(owner, target);
            }
            throw std::runtime_error(("Unsupported item kind: " + kind).toStdString());
        }

        if (method == "item_view_inspect") {
            QWidget *owner = resolveItemOwner(params);
            const int maxRows = qMax(0, params.value("max_rows").toInt(20));
            const int maxDepth = qMax(0, params.value("max_depth").toInt(4));
            const int maxItems = qMax(0, params.value("max_items").toInt(200));
            const bool includeHidden = params.value("include_hidden").toBool(false);
            return inspectItemView(owner, maxRows, maxDepth, maxItems, includeHidden);
        }

        // -- Actions --
        if (method == "click") {
            if (params.contains("wid") || params.contains("selector")) {
                QWidget *w = resolveOne(params);
                clickWidget(w, false);
            } else {
                clickPointerActionTarget(params, false);
            }
            return true;
        }
        if (method == "dblclick") {
            if (params.contains("wid") || params.contains("selector")) {
                QWidget *w = resolveOne(params);
                clickWidget(w, true);
            } else {
                clickPointerActionTarget(params, true);
            }
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
            moveVisualCursorToWidget(w, 1);
            if (auto *btn = qobject_cast<QAbstractButton *>(w)) btn->setChecked(true);
            return true;
        }
        if (method == "uncheck") {
            QWidget *w = resolveOne(params);
            moveVisualCursorToWidget(w, 1);
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
            if (params.contains("wid") || params.contains("selector")) {
                QWidget *w = resolveOne(params);
                hoverWidget(w);
            } else {
                hoverPointerActionTarget(params);
            }
            return true;
        }

        if (method == "item_click") {
            QWidget *owner = resolveItemOwner(params);
            const QJsonObject item = params.value("item").toObject();
            const QString kind = item.value("kind").toString();
            if (kind == "table_cell") {
                ResolvedTableItem target = resolveTableItem(owner, item);
                clickTableIndex(owner, target, false);
                return true;
            }
            if (kind == "list_item") {
                ResolvedListItem target = resolveListItem(owner, item);
                clickListIndex(owner, target, false);
                return true;
            }
            if (kind == "tree_node") {
                ResolvedTreeItem target = resolveTreeItem(owner, item);
                clickTreeIndex(owner, target, false);
                return true;
            }
            if (kind == "tab_item") {
                ResolvedTabItem target = resolveTabItem(owner, item);
                clickTabItem(owner, target, false);
                return true;
            }
            throw std::runtime_error(("Unsupported item kind: " + kind).toStdString());
        }

        if (method == "item_dblclick") {
            QWidget *owner = resolveItemOwner(params);
            const QJsonObject item = params.value("item").toObject();
            const QString kind = item.value("kind").toString();
            if (kind == "table_cell") {
                ResolvedTableItem target = resolveTableItem(owner, item);
                clickTableIndex(owner, target, true);
                return true;
            }
            if (kind == "list_item") {
                ResolvedListItem target = resolveListItem(owner, item);
                clickListIndex(owner, target, true);
                return true;
            }
            if (kind == "tree_node") {
                ResolvedTreeItem target = resolveTreeItem(owner, item);
                clickTreeIndex(owner, target, true);
                return true;
            }
            if (kind == "tab_item") {
                ResolvedTabItem target = resolveTabItem(owner, item);
                clickTabItem(owner, target, true);
                return true;
            }
            throw std::runtime_error(("Unsupported item kind: " + kind).toStdString());
        }

        if (method == "item_hover") {
            QWidget *owner = resolveItemOwner(params);
            const QJsonObject item = params.value("item").toObject();
            const QString kind = item.value("kind").toString();
            if (kind == "table_cell") {
                ResolvedTableItem target = resolveTableItem(owner, item);
                hoverTableIndex(owner, target);
                return true;
            }
            if (kind == "list_item") {
                ResolvedListItem target = resolveListItem(owner, item);
                hoverListIndex(owner, target);
                return true;
            }
            if (kind == "tree_node") {
                ResolvedTreeItem target = resolveTreeItem(owner, item);
                hoverTreeIndex(owner, target);
                return true;
            }
            if (kind == "tab_item") {
                ResolvedTabItem target = resolveTabItem(owner, item);
                hoverTabItem(owner, target);
                return true;
            }
            throw std::runtime_error(("Unsupported item kind: " + kind).toStdString());
        }

        if (method == "item_select") {
            QWidget *owner = resolveItemOwner(params);
            const QJsonObject item = params.value("item").toObject();
            const QString kind = item.value("kind").toString();
            if (kind != "tab_item")
                throw std::runtime_error("select() is only supported for tab_item items");

            ResolvedTabItem target = resolveTabItem(owner, item);
            selectTabItem(owner, target);
            return true;
        }

        if (method == "item_expand") {
            QWidget *owner = resolveItemOwner(params);
            const QJsonObject item = params.value("item").toObject();
            const QString kind = item.value("kind").toString();
            if (kind != "tree_node")
                throw std::runtime_error("expand() is only supported for tree nodes");
            ResolvedTreeItem target = resolveTreeItem(owner, item);
            expandTreeIndex(owner, target);
            return true;
        }

        if (method == "item_collapse") {
            QWidget *owner = resolveItemOwner(params);
            const QJsonObject item = params.value("item").toObject();
            const QString kind = item.value("kind").toString();
            if (kind != "tree_node")
                throw std::runtime_error("collapse() is only supported for tree nodes");
            ResolvedTreeItem target = resolveTreeItem(owner, item);
            collapseTreeIndex(owner, target);
            return true;
        }

        if (method == "focus") {
            QWidget *w = resolveOne(params);
            QWidget *target = primaryEventTarget(w);
            updateVisualFeedback(target, target->rect().center(), 0);
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
                auto windows = interactableTopLevelWidgets();
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
            AutomationOverlay *overlay = m_overlayManager ? m_overlayManager->overlayForWindow(w->window()) : nullptr;
            const bool hideOverlayForCapture =
                overlay &&
                overlay->isVisible() &&
                overlay->targetWindow() == w->window();
            if (hideOverlayForCapture) {
                overlay->hide();
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
                overlay->syncToWindow(true);
                overlay->update();
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
                QJsonObject geometry;
                r["wid"] = wid;
                r["title"] = w->windowTitle();
                r["class"] = QString::fromLatin1(w->metaObject()->className());
                geometry["x"] = w->x();
                geometry["y"] = w->y();
                geometry["width"] = w->width();
                geometry["height"] = w->height();
                r["geometry"] = geometry;
                r["is_modal"] = w->isModal();
                r["blocked_by_modal"] = isWindowBlockedByModal(w);
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
            roots = interactableTopLevelWidgets();
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

    bool findLightlyVisible(QWidget *widget)
    {
        return widget && widget->isVisible() && widget->width() > 0 && widget->height() > 0;
    }

    bool findInteractable(QWidget *widget)
    {
        if (!widget)
            return false;
        try {
            resolveClickTarget(widget);
        } catch (...) {
            return false;
        }
        return true;
    }

    bool isFindInfrastructureWidget(QWidget *widget)
    {
        if (!widget)
            return false;
        if (isAutomationOverlayWidget(widget))
            return true;
        if (widget->objectName().startsWith(QString::fromLatin1("qt_")))
            return true;

        static const QStringList infrastructureClasses = {
            QString::fromLatin1("QAbstractScrollAreaScrollBarContainer"),
        };
        return infrastructureClasses.contains(QString::fromLatin1(widget->metaObject()->className()));
    }

    QWidget *resolveFindRootWidget(const QJsonObject &params)
    {
        auto &reg = QPlaywrightRegistry::instance();

        if (params.contains("wid")) {
            QWidget *root = reg.get(params["wid"].toInt());
            if (!root)
                throw std::runtime_error("Widget not found by wid");
            return root;
        }

        const QString selector = params.value("selector").toString();
        if (selector.isEmpty())
            throw std::runtime_error("find_widgets requires wid or selector root");

        QJsonObject lookup;
        lookup["selector"] = selector;
        lookup["visible_only"] = false;
        auto matches = resolveWidgets(lookup);
        if (matches.isEmpty())
            throw std::runtime_error(("No widget found for find root: " + selector).toStdString());
        if (matches.size() > 1)
            throw std::runtime_error(("Find root is ambiguous for selector: " + selector).toStdString());
        return matches.first();
    }

    QJsonArray findMatchReasons(const QJsonObject &params)
    {
        QJsonArray reasons;
        if (params.contains("role"))
            reasons.append(QString::fromLatin1("role=") + params.value("role").toString());
        if (params.contains("text"))
            reasons.append(QString::fromLatin1("text=") + params.value("text").toString());
        if (params.contains("has_text"))
            reasons.append(QString::fromLatin1("has_text~=") + params.value("has_text").toString());
        if (params.contains("class"))
            reasons.append(QString::fromLatin1("class=") + params.value("class").toString());
        if (params.contains("object_name"))
            reasons.append(QString::fromLatin1("object_name=") + params.value("object_name").toString());
        if (params.contains("accessible_name"))
            reasons.append(QString::fromLatin1("accessible_name=") + params.value("accessible_name").toString());
        for (const char *name : {"visible", "enabled", "interactable"}) {
            if (!params.contains(name))
                continue;
            reasons.append(QString::fromLatin1(name) + QString::fromLatin1("=") + (params.value(name).toBool() ? QString::fromLatin1("true") : QString::fromLatin1("false")));
        }
        return reasons;
    }

    bool findWidgetMatches(QWidget *widget, const QJsonObject &params, bool visible, bool enabled, bool interactable)
    {
        if (!widget)
            return false;

        if (params.contains("role") && !QPlaywrightRoles::matchesRole(widget, params.value("role").toString()))
            return false;
        if (params.contains("text") && QPlaywrightRoles::widgetText(widget) != params.value("text").toString())
            return false;
        if (params.contains("has_text") && !QPlaywrightRoles::widgetText(widget).contains(params.value("has_text").toString(), Qt::CaseInsensitive))
            return false;

        if (params.contains("class")) {
            const QString className = params.value("class").toString();
            bool classMatch = false;
            const QMetaObject *mo = widget->metaObject();
            while (mo) {
                if (QString::fromLatin1(mo->className()) == className) {
                    classMatch = true;
                    break;
                }
                mo = mo->superClass();
            }
            if (!classMatch)
                return false;
        }

        if (params.contains("object_name") && widget->objectName() != params.value("object_name").toString())
            return false;
        if (params.contains("accessible_name") && widget->accessibleName() != params.value("accessible_name").toString())
            return false;
        if (params.contains("visible") && visible != params.value("visible").toBool())
            return false;
        if (params.contains("enabled") && enabled != params.value("enabled").toBool())
            return false;
        if (params.contains("interactable") && interactable != params.value("interactable").toBool())
            return false;

        return true;
    }

    QJsonArray findAncestorSummary(const QList<QWidget *> &ancestors)
    {
        auto &reg = QPlaywrightRegistry::instance();

        QJsonArray summary;
        for (QWidget *ancestor : ancestors) {
            if (!ancestor)
                continue;
            QJsonObject entry = serializeWidgetTree(ancestor, 0, 0, false);
            entry["wid"] = reg.registerWidget(ancestor);
            summary.append(entry);
        }
        return summary;
    }

    struct FindWidgetCandidate
    {
        int depth = 0;
        bool interactable = false;
        bool visible = false;
        int preorder = 0;
        int wid = 0;
        QJsonObject entry;
    };

    QJsonObject findWidgetsPayload(const QJsonObject &params)
    {
        auto &reg = QPlaywrightRegistry::instance();

        QWidget *root = resolveFindRootWidget(params);
        const int rootWid = reg.registerWidget(root);
        const bool includeInfrastructure = params.value("include_infrastructure").toBool(false);
        const int limit = params.value("limit").toInt(5);
        if (limit <= 0)
            throw std::runtime_error("limit must be > 0");

        const QJsonArray matchReason = findMatchReasons(params);
        const bool explicitVisible = params.contains("visible");
        const bool explicitInteractable = params.contains("interactable");
        QList<FindWidgetCandidate> matches;
        int preorder = 0;

        std::function<void(QWidget *, const QList<QWidget *> &)> walk =
            [&](QWidget *widget, const QList<QWidget *> &ancestors) {
                if (!widget)
                    return;

                const int currentOrder = preorder++;
                const bool visible = findLightlyVisible(widget);
                const bool enabled = widget->isEnabled();
                const bool interactable = findInteractable(widget);
                const bool infrastructure = isFindInfrastructureWidget(widget);

                if ((includeInfrastructure || !infrastructure) &&
                    findWidgetMatches(widget, params, visible, enabled, interactable)) {
                    QJsonObject entry = serializeWidgetTree(widget, 0, 0, false);
                    const int wid = reg.registerWidget(widget);
                    entry["wid"] = wid;
                    entry["interactable"] = interactable;
                    entry["matchReason"] = matchReason;
                    if (!ancestors.isEmpty())
                        entry["ancestorSummary"] = findAncestorSummary(ancestors);

                    FindWidgetCandidate candidate;
                    candidate.depth = ancestors.size();
                    candidate.interactable = interactable;
                    candidate.visible = visible;
                    candidate.preorder = currentOrder;
                    candidate.wid = wid;
                    candidate.entry = entry;
                    matches.append(candidate);
                }

                QList<QWidget *> nextAncestors = ancestors;
                nextAncestors.append(widget);
                for (QObject *child : widget->children()) {
                    QWidget *childWidget = qobject_cast<QWidget *>(child);
                    if (childWidget)
                        walk(childWidget, nextAncestors);
                }
            };

        walk(root, {});

        std::sort(matches.begin(), matches.end(),
                  [&](const FindWidgetCandidate &left, const FindWidgetCandidate &right) {
                      if (left.depth != right.depth)
                          return left.depth < right.depth;
                      if (!explicitInteractable && left.interactable != right.interactable)
                          return left.interactable && !right.interactable;
                      if (!explicitVisible && left.visible != right.visible)
                          return left.visible && !right.visible;
                      if (left.preorder != right.preorder)
                          return left.preorder < right.preorder;
                      return left.wid < right.wid;
                  });

        QJsonArray results;
        const int count = std::min(limit, matches.size());
        for (int index = 0; index < count; ++index)
            results.append(matches[index].entry);

        QJsonObject result;
        result["rootWid"] = rootWid;
        result["count"] = count;
        result["truncated"] = matches.size() > limit;
        result["results"] = results;
        return result;
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

        for (QWidget *window : interactableTopLevelWidgets()) {
            if (window->isVisible())
                return window;
        }

        throw std::runtime_error("No visible window found for targetless key press");
    }

    QWidget *resolvePointerActionWindow(const QJsonObject &params)
    {
        auto &reg = QPlaywrightRegistry::instance();

        if (params.contains("window_wid")) {
            QWidget *window = reg.get(params["window_wid"].toInt());
            if (!window)
                throw std::runtime_error("No window found for the requested window_wid");
            return window->window();
        }

        if (QWidget *activeModal = activeModalTopLevelWidget())
            return activeModal;

        if (QWidget *activeWindow = QApplication::activeWindow()) {
            QWidget *window = activeWindow->window();
            if (window && isOverlayTargetWindowVisible(window) && !isWindowBlockedByModal(window))
                return window;
        }

        if (QWidget *focused = QApplication::focusWidget()) {
            QWidget *window = focused->window();
            if (window && isOverlayTargetWindowVisible(window) && !isWindowBlockedByModal(window))
                return window;
        }

        for (QWidget *window : interactableTopLevelWidgets()) {
            if (window->isVisible())
                return window;
        }

        throw std::runtime_error("No visible window found for coordinate pointer action");
    }
    
    struct ResolvedTableItem
    {
        int row;
        int column;
        QModelIndex index;
    };

    struct ResolvedListItem
    {
        int row;
        QModelIndex index;
    };

    struct ResolvedTreeItem
    {
        QModelIndex index;
    };

    struct ResolvedTabItem
    {
        int index;
        QTabBar *tabBar;
    };
    
    QWidget *resolveItemOwner(const QJsonObject &params)
    {
        if (!params.contains("wid"))
            throw std::runtime_error("Item operations require wid");
        
        auto &reg = QPlaywrightRegistry::instance();
        QWidget *owner = reg.get(params["wid"].toInt());
        if (!owner)
            throw std::runtime_error("Widget not found by wid");
        return owner;
    }
    
    QTableView *tableView(QWidget *owner)
    {
        QTableView *view = qobject_cast<QTableView *>(owner);
        if (!view) {
            throw std::runtime_error(
                ("Item owner is not a supported table widget: " + QString::fromLatin1(owner->metaObject()->className())).toStdString()
            );
        }
        return view;
    }

    QTreeView *treeView(QWidget *owner)
    {
        QTreeView *view = qobject_cast<QTreeView *>(owner);
        if (!view) {
            throw std::runtime_error(
                ("Item owner is not a supported tree widget: " + QString::fromLatin1(owner->metaObject()->className())).toStdString()
            );
        }
        return view;
    }

    QListView *listView(QWidget *owner)
    {
        QListView *view = qobject_cast<QListView *>(owner);
        if (!view) {
            throw std::runtime_error(
                ("Item owner is not a supported list widget: " + QString::fromLatin1(owner->metaObject()->className())).toStdString()
            );
        }
        return view;
    }

    QTabWidget *tabWidget(QWidget *owner)
    {
        QTabWidget *widget = qobject_cast<QTabWidget *>(owner);
        if (!widget) {
            throw std::runtime_error(
                ("Item owner is not a supported tab widget: " + QString::fromLatin1(owner->metaObject()->className())).toStdString()
            );
        }
        return widget;
    }

    QTabBar *tabBarFromOwner(QWidget *owner)
    {
        if (auto *bar = qobject_cast<QTabBar *>(owner))
            return bar;

        QTabWidget *widget = tabWidget(owner);
        QTabBar *bar = widget->tabBar();
        if (!bar)
            throw std::runtime_error("Tab widget tabBar() returned null");
        return bar;
    }

    int tabCount(QTabBar *bar)
    {
        return bar->count();
    }

    QString tabText(QTabBar *bar, int index)
    {
        return bar->tabText(index);
    }

    int tabCurrentIndex(QWidget *owner)
    {
        if (auto *widget = qobject_cast<QTabWidget *>(owner))
            return widget->currentIndex();
        return tabBarFromOwner(owner)->currentIndex();
    }

    bool tabVisible(QTabBar *bar, int index)
    {
        return !bar->tabRect(index).isEmpty();
    }

    bool tabEnabled(QTabBar *bar, int index)
    {
        return bar->isTabEnabled(index);
    }

    QString tabPageObjectName(QWidget *owner, int index)
    {
        auto *widget = qobject_cast<QTabWidget *>(owner);
        if (!widget)
            return QString();

        QWidget *page = widget->widget(index);
        if (!page)
            return QString();
        return page->objectName();
    }
    
    int resolveTableColumn(QWidget *owner, const QJsonValue &columnValue)
    {
        QTableView *view = tableView(owner);
        auto *model = view->model();
        if (!model)
            throw std::runtime_error("Table widget model is not available");
        
        const int columnCount = model->columnCount();
        if (columnValue.isDouble()) {
            const int column = columnValue.toInt();
            if (column < 0 || column >= columnCount)
                throw std::runtime_error(("Table column out of range: " + QString::number(column)).toStdString());
            return column;
        }
        
        const QString columnName = columnValue.toString();
        if (columnName.isEmpty())
            throw std::runtime_error("Table column name must be a non-empty string");
        
        QVector<int> matches;
        for (int column = 0; column < columnCount; ++column) {
            if (model->headerData(column, Qt::Horizontal, Qt::DisplayRole).toString() == columnName)
                matches.append(column);
        }
        
        if (matches.isEmpty())
            throw std::runtime_error(("Table header not found: " + columnName).toStdString());
        if (matches.size() > 1)
            throw std::runtime_error(("Ambiguous table header: " + columnName).toStdString());
        return matches.first();
    }
    
    ResolvedTableItem resolveTableItem(QWidget *owner, const QJsonObject &descriptor)
    {
        if (descriptor.value("kind").toString() != "table_cell")
            throw std::runtime_error(("Unsupported item kind: " + descriptor.value("kind").toString()).toStdString());
        if (!descriptor.contains("row") || !descriptor.value("row").isDouble())
            throw std::runtime_error("Table cell row must be an int");
        
        const bool hasColumn = descriptor.contains("column");
        const bool hasColumnName = descriptor.contains("columnName");
        if (hasColumn == hasColumnName)
            throw std::runtime_error("Table cell descriptor requires exactly one of column or columnName");
        
        QTableView *view = tableView(owner);
        auto *model = view->model();
        if (!model)
            throw std::runtime_error("Table widget model is not available");
        
        const int row = descriptor.value("row").toInt();
        if (row < 0 || row >= model->rowCount())
            throw std::runtime_error(("Table row out of range: " + QString::number(row)).toStdString());
        
        const int column = resolveTableColumn(owner, hasColumn ? descriptor.value("column") : descriptor.value("columnName"));
        const QModelIndex index = model->index(row, column);
        if (!index.isValid()) {
            throw std::runtime_error(
                ("Table cell index is not valid: row=" + QString::number(row) + ", column=" + QString::number(column)).toStdString()
            );
        }
        
        return {row, column, index};
    }

    ResolvedListItem resolveListItem(QWidget *owner, const QJsonObject &descriptor)
    {
        if (descriptor.value("kind").toString() != "list_item")
            throw std::runtime_error(("Unsupported item kind: " + descriptor.value("kind").toString()).toStdString());

        const bool hasRow = descriptor.contains("row");
        const bool hasText = descriptor.contains("text");
        if (hasRow == hasText)
            throw std::runtime_error("List item descriptor requires exactly one of row or text");

        QListView *view = listView(owner);
        auto *model = view->model();
        if (!model)
            throw std::runtime_error("List widget model is not available");

        const int rowCount = model->rowCount();
        if (hasRow) {
            if (!descriptor.value("row").isDouble())
                throw std::runtime_error("List item row must be an int");

            const int row = descriptor.value("row").toInt();
            if (row < 0 || row >= rowCount)
                throw std::runtime_error(("List item row out of range: " + QString::number(row)).toStdString());

            const QModelIndex index = model->index(row, 0);
            if (!index.isValid())
                throw std::runtime_error(("List item index is not valid: row=" + QString::number(row)).toStdString());
            return {row, index};
        }

        const QString text = descriptor.value("text").toString();
        if (text.isEmpty())
            throw std::runtime_error("List item text must be a non-empty string");

        QVector<QPair<int, QModelIndex>> matches;
        for (int row = 0; row < rowCount; ++row) {
            const QModelIndex candidate = model->index(row, 0);
            if (model->data(candidate, Qt::DisplayRole).toString() == text)
                matches.append(qMakePair(row, candidate));
        }

        if (matches.isEmpty())
            throw std::runtime_error(("List item text not found: " + text).toStdString());
        if (matches.size() > 1)
            throw std::runtime_error(("Ambiguous list item text: " + text).toStdString());
        return {matches.first().first, matches.first().second};
    }

    ResolvedTreeItem resolveTreeItem(QWidget *owner, const QJsonObject &descriptor)
    {
        if (descriptor.value("kind").toString() != "tree_node")
            throw std::runtime_error(("Unsupported item kind: " + descriptor.value("kind").toString()).toStdString());
        if (!descriptor.contains("path") || !descriptor.value("path").isArray())
            throw std::runtime_error("Tree node descriptor requires a non-empty path list");

        const QJsonArray path = descriptor.value("path").toArray();
        if (path.isEmpty())
            throw std::runtime_error("Tree node descriptor requires a non-empty path list");

        QTreeView *view = treeView(owner);
        auto *model = view->model();
        if (!model)
            throw std::runtime_error("Tree widget model is not available");

        QModelIndex parentIndex;
        QModelIndex currentIndex;
        for (int depth = 0; depth < path.size(); ++depth) {
            const QJsonValue segment = path.at(depth);
            const int rowCount = model->rowCount(parentIndex);

            if (segment.isDouble()) {
                const int row = segment.toInt();
                if (row < 0 || row >= rowCount) {
                    throw std::runtime_error(
                        ("Tree path index out of range at depth " + QString::number(depth) + ": " + QString::number(row)).toStdString()
                    );
                }
                currentIndex = model->index(row, 0, parentIndex);
            } else {
                const QString label = segment.toString();
                if (label.isEmpty())
                    throw std::runtime_error("Tree path segments must be int or non-empty str");

                QVector<QModelIndex> matches;
                for (int row = 0; row < rowCount; ++row) {
                    const QModelIndex candidate = model->index(row, 0, parentIndex);
                    if (model->data(candidate, Qt::DisplayRole).toString() == label)
                        matches.append(candidate);
                }

                if (matches.isEmpty())
                    throw std::runtime_error(("Tree path segment not found: " + label).toStdString());
                if (matches.size() > 1)
                    throw std::runtime_error(("Ambiguous tree path segment: " + label).toStdString());
                currentIndex = matches.first();
            }

            if (!currentIndex.isValid()) {
                throw std::runtime_error(
                    ("Tree node index is not valid at depth " + QString::number(depth)).toStdString()
                );
            }
            parentIndex = currentIndex;
        }

        return {currentIndex};
    }

    ResolvedTabItem resolveTabItem(QWidget *owner, const QJsonObject &descriptor)
    {
        if (descriptor.value("kind").toString() != "tab_item")
            throw std::runtime_error(("Unsupported item kind: " + descriptor.value("kind").toString()).toStdString());

        const bool hasIndex = descriptor.contains("index");
        const bool hasLabel = descriptor.contains("label");
        if (hasIndex == hasLabel)
            throw std::runtime_error("Tab item descriptor requires exactly one of index or label");

        QTabBar *bar = tabBarFromOwner(owner);
        const int count = tabCount(bar);

        if (hasIndex) {
            if (!descriptor.value("index").isDouble())
                throw std::runtime_error("Tab item index must be an int");

            const int index = descriptor.value("index").toInt();
            if (index < 0 || index >= count)
                throw std::runtime_error(("Tab index out of range: " + QString::number(index)).toStdString());
            return {index, bar};
        }

        const QString label = descriptor.value("label").toString();
        if (label.isEmpty())
            throw std::runtime_error("Tab item label must be a non-empty string");

        QVector<int> matches;
        for (int index = 0; index < count; ++index) {
            if (tabText(bar, index) == label)
                matches.append(index);
        }

        if (matches.isEmpty())
            throw std::runtime_error(("Tab label not found: " + label).toStdString());
        if (matches.size() > 1)
            throw std::runtime_error(("Ambiguous tab label: " + label).toStdString());
        return {matches.first(), bar};
    }
    
    QString tableIndexText(QWidget *owner, const ResolvedTableItem &target)
    {
        QTableView *view = tableView(owner);
        auto *model = view->model();
        if (!model)
            throw std::runtime_error("Table widget model is not available");
        return model->data(target.index, Qt::DisplayRole).toString();
    }

    QString tableIndexEditText(QWidget *owner, const ResolvedTableItem &target, bool *hasEditValue = nullptr)
    {
        QTableView *view = tableView(owner);
        if (QWidget *editor = view->indexWidget(target.index)) {
            if (hasEditValue)
                *hasEditValue = true;
            QVariant editorValue = QPlaywrightRoles::widgetValue(editor);
            if (editorValue.isValid() && !editorValue.isNull())
                return editorValue.toString();
            return QPlaywrightRoles::widgetInputValue(editor);
        }
        auto *model = view->model();
        if (!model)
            throw std::runtime_error("Table widget model is not available");
        const QVariant value = model->data(target.index, Qt::EditRole);
        const bool valid = value.isValid() && !value.isNull();
        if (hasEditValue)
            *hasEditValue = valid;
        return valid ? value.toString() : QString();
    }

    QString listIndexText(QWidget *owner, const ResolvedListItem &target)
    {
        QListView *view = listView(owner);
        auto *model = view->model();
        if (!model)
            throw std::runtime_error("List widget model is not available");
        return model->data(target.index, Qt::DisplayRole).toString();
    }

    QString listIndexEditText(QWidget *owner, const ResolvedListItem &target, bool *hasEditValue = nullptr)
    {
        QListView *view = listView(owner);
        if (QWidget *editor = view->indexWidget(target.index)) {
            if (hasEditValue)
                *hasEditValue = true;
            QVariant editorValue = QPlaywrightRoles::widgetValue(editor);
            if (editorValue.isValid() && !editorValue.isNull())
                return editorValue.toString();
            return QPlaywrightRoles::widgetInputValue(editor);
        }
        auto *model = view->model();
        if (!model)
            throw std::runtime_error("List widget model is not available");
        const QVariant value = model->data(target.index, Qt::EditRole);
        const bool valid = value.isValid() && !value.isNull();
        if (hasEditValue)
            *hasEditValue = valid;
        return valid ? value.toString() : QString();
    }

    QJsonArray treeIndexPath(QAbstractItemModel *model, const QModelIndex &index)
    {
        QStringList reversed;
        QModelIndex current = index;
        while (current.isValid()) {
            reversed.prepend(model->data(current, Qt::DisplayRole).toString());
            current = current.parent();
        }

        QJsonArray path;
        for (const QString &segment : reversed)
            path.append(segment);
        return path;
    }

    QJsonArray treeIndexRowPath(const QModelIndex &index)
    {
        QVector<int> reversed;
        QModelIndex current = index;
        while (current.isValid()) {
            reversed.prepend(current.row());
            current = current.parent();
        }

        QJsonArray path;
        for (int row : reversed)
            path.append(row);
        return path;
    }

    QString treeIndexText(QWidget *owner, const ResolvedTreeItem &target)
    {
        QTreeView *view = treeView(owner);
        auto *model = view->model();
        if (!model)
            throw std::runtime_error("Tree widget model is not available");
        return model->data(target.index, Qt::DisplayRole).toString();
    }

    QString treeIndexEditText(QWidget *owner, const ResolvedTreeItem &target, bool *hasEditValue = nullptr)
    {
        QTreeView *view = treeView(owner);
        if (QWidget *editor = view->indexWidget(target.index)) {
            if (hasEditValue)
                *hasEditValue = true;
            QVariant editorValue = QPlaywrightRoles::widgetValue(editor);
            if (editorValue.isValid() && !editorValue.isNull())
                return editorValue.toString();
            return QPlaywrightRoles::widgetInputValue(editor);
        }
        auto *model = view->model();
        if (!model)
            throw std::runtime_error("Tree widget model is not available");
        const QVariant value = model->data(target.index, Qt::EditRole);
        const bool valid = value.isValid() && !value.isNull();
        if (hasEditValue)
            *hasEditValue = valid;
        return valid ? value.toString() : QString();
    }

    QString tabItemText(QWidget *owner, const ResolvedTabItem &target)
    {
        Q_UNUSED(owner);
        if (!target.tabBar)
            throw std::runtime_error("Tab item is missing tab bar context");
        return tabText(target.tabBar, target.index);
    }
    
    bool tableIndexVisible(QWidget *owner, const ResolvedTableItem &target)
    {
        QTableView *view = tableView(owner);
        if (view->isColumnHidden(target.column))
            return false;
        const QRect rect = view->visualRect(target.index);
        return !rect.isEmpty();
    }

    bool listIndexVisible(QWidget *owner, const ResolvedListItem &target)
    {
        QListView *view = listView(owner);
        const QRect rect = view->visualRect(target.index);
        return !rect.isEmpty();
    }

    bool treeIndexHasCollapsedAncestor(QTreeView *view, const QModelIndex &index)
    {
        QModelIndex current = index.parent();
        while (current.isValid()) {
            if (!view->isExpanded(current))
                return true;
            current = current.parent();
        }
        return false;
    }

    bool treeIndexVisible(QWidget *owner, const ResolvedTreeItem &target)
    {
        QTreeView *view = treeView(owner);
        if (view->isColumnHidden(0))
            return false;
        if (treeIndexHasCollapsedAncestor(view, target.index))
            return false;
        if (view->isRowHidden(target.index.row(), target.index.parent()))
            return false;
        const QRect rect = view->visualRect(target.index);
        return !rect.isEmpty();
    }

    bool tabItemVisible(QWidget *owner, const ResolvedTabItem &target)
    {
        Q_UNUSED(owner);
        if (!target.tabBar)
            throw std::runtime_error("Tab item is missing tab bar context");
        return tabVisible(target.tabBar, target.index);
    }

    bool tabItemSelected(QWidget *owner, const ResolvedTabItem &target)
    {
        return target.index == tabCurrentIndex(owner);
    }
    
    QRect tableIndexRect(QWidget *owner, const ResolvedTableItem &target)
    {
        QTableView *view = tableView(owner);
        if (view->isColumnHidden(target.column)) {
            throw std::runtime_error(
                ("Table cell is not visible because column " + QString::number(target.column) + " is hidden").toStdString()
            );
        }
        
        view->scrollTo(target.index, QAbstractItemView::EnsureVisible);
        const QRect rect = view->visualRect(target.index);
        if (rect.isEmpty())
            throw std::runtime_error("Table cell does not have a usable visible rectangle");
        return rect;
    }

    QRect listIndexRect(QWidget *owner, const ResolvedListItem &target)
    {
        QListView *view = listView(owner);
        view->scrollTo(target.index, QAbstractItemView::EnsureVisible);
        const QRect rect = view->visualRect(target.index);
        if (rect.isEmpty())
            throw std::runtime_error("List item does not have a usable visible rectangle");
        return rect;
    }

    QRect treeIndexRect(QWidget *owner, const ResolvedTreeItem &target)
    {
        QTreeView *view = treeView(owner);
        if (view->isColumnHidden(0))
            throw std::runtime_error("Tree node is not visible because column 0 is hidden");
        if (treeIndexHasCollapsedAncestor(view, target.index))
            throw std::runtime_error("Tree node is not visible because an ancestor is collapsed");
        if (view->isRowHidden(target.index.row(), target.index.parent()))
            throw std::runtime_error("Tree node is hidden in the current view");

        view->scrollTo(target.index, QAbstractItemView::EnsureVisible);
        const QRect rect = view->visualRect(target.index);
        if (rect.isEmpty())
            throw std::runtime_error("Tree node does not have a usable visible rectangle");
        return rect;
    }

    QRect tabItemRect(QWidget *owner, const ResolvedTabItem &target)
    {
        Q_UNUSED(owner);
        if (!target.tabBar)
            throw std::runtime_error("Tab item is missing tab bar context");

        const QRect rect = target.tabBar->tabRect(target.index);
        if (rect.isEmpty())
            throw std::runtime_error(("Tab does not have a usable visible rectangle: " + QString::number(target.index)).toStdString());
        return rect;
    }
    
    QJsonObject tableIndexProperties(QWidget *owner, const ResolvedTableItem &target)
    {
        QTableView *view = tableView(owner);
        QJsonObject payload;
        const QString text = tableIndexText(owner, target);
        payload["kind"] = "table_cell";
        payload["row"] = target.row;
        payload["column"] = target.column;
        payload["text"] = text;
        bool hasEditValue = false;
        const QString editValue = tableIndexEditText(owner, target, &hasEditValue);
        if (hasEditValue && editValue != text)
            payload["edit_value"] = editValue;
        payload["selected"] = view->selectionModel() && view->selectionModel()->isSelected(target.index);
        return payload;
    }

    QJsonObject listIndexProperties(QWidget *owner, const ResolvedListItem &target)
    {
        QListView *view = listView(owner);
        QJsonObject payload;
        const QString text = listIndexText(owner, target);
        payload["kind"] = "list_item";
        payload["row"] = target.row;
        payload["text"] = text;
        bool hasEditValue = false;
        const QString editValue = listIndexEditText(owner, target, &hasEditValue);
        if (hasEditValue && editValue != text)
            payload["edit_value"] = editValue;
        payload["selected"] = view->selectionModel() && view->selectionModel()->isSelected(target.index);
        return payload;
    }

    QJsonObject treeIndexProperties(QWidget *owner, const ResolvedTreeItem &target)
    {
        QTreeView *view = treeView(owner);
        auto *model = view->model();
        if (!model)
            throw std::runtime_error("Tree widget model is not available");

        QJsonObject payload;
        const QString text = treeIndexText(owner, target);
        payload["kind"] = "tree_node";
        payload["text"] = text;
        payload["path"] = treeIndexPath(model, target.index);
        bool hasEditValue = false;
        const QString editValue = treeIndexEditText(owner, target, &hasEditValue);
        if (hasEditValue && editValue != text)
            payload["edit_value"] = editValue;
        payload["expanded"] = view->isExpanded(target.index);
        payload["selected"] = view->selectionModel() && view->selectionModel()->isSelected(target.index);
        return payload;
    }

    QJsonObject tabItemProperties(QWidget *owner, const ResolvedTabItem &target)
    {
        if (!target.tabBar)
            throw std::runtime_error("Tab item is missing tab bar context");

        QJsonObject payload;
        payload["kind"] = "tab_item";
        payload["index"] = target.index;
        payload["text"] = tabItemText(owner, target);
        payload["visible"] = tabItemVisible(owner, target);
        payload["selected"] = tabItemSelected(owner, target);
        payload["enabled"] = tabEnabled(target.tabBar, target.index);

        const QString pageObjectName = tabPageObjectName(owner, target.index);
        if (!pageObjectName.isEmpty())
            payload["pageObjectName"] = pageObjectName;
        return payload;
    }
    
    QJsonObject tableIndexBoundingBox(QWidget *owner, const ResolvedTableItem &target)
    {
        QTableView *view = tableView(owner);
        QWidget *targetWidget = primaryEventTarget(view);
        const QRect rect = tableIndexRect(owner, target);
        const QPoint global = targetWidget->mapToGlobal(rect.topLeft());
        QJsonObject payload;
        payload["x"] = global.x();
        payload["y"] = global.y();
        payload["width"] = rect.width();
        payload["height"] = rect.height();
        return payload;
    }

    QJsonObject listIndexBoundingBox(QWidget *owner, const ResolvedListItem &target)
    {
        QListView *view = listView(owner);
        QWidget *targetWidget = primaryEventTarget(view);
        const QRect rect = listIndexRect(owner, target);
        const QPoint global = targetWidget->mapToGlobal(rect.topLeft());
        QJsonObject payload;
        payload["x"] = global.x();
        payload["y"] = global.y();
        payload["width"] = rect.width();
        payload["height"] = rect.height();
        return payload;
    }

    QJsonObject treeIndexBoundingBox(QWidget *owner, const ResolvedTreeItem &target)
    {
        QTreeView *view = treeView(owner);
        QWidget *targetWidget = primaryEventTarget(view);
        const QRect rect = treeIndexRect(owner, target);
        const QPoint global = targetWidget->mapToGlobal(rect.topLeft());
        QJsonObject payload;
        payload["x"] = global.x();
        payload["y"] = global.y();
        payload["width"] = rect.width();
        payload["height"] = rect.height();
        return payload;
    }

    QJsonObject tabItemBoundingBox(QWidget *owner, const ResolvedTabItem &target)
    {
        Q_UNUSED(owner);
        if (!target.tabBar)
            throw std::runtime_error("Tab item is missing tab bar context");

        const QRect rect = tabItemRect(owner, target);
        const QPoint global = target.tabBar->mapToGlobal(rect.topLeft());
        QJsonObject payload;
        payload["x"] = global.x();
        payload["y"] = global.y();
        payload["width"] = rect.width();
        payload["height"] = rect.height();
        return payload;
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

    bool isMouseTransparentWidget(QWidget *widget)
    {
        return widget && widget->testAttribute(Qt::WA_TransparentForMouseEvents);
    }

    QVector<QPoint> sampleLocalPoints(QWidget *target)
    {
        const QPoint center = target->rect().center();
        const int width = target->width();
        const int height = target->height();
        const int offsetX = width > 1 ? qMax(1, width / 4) : 0;
        const int offsetY = height > 1 ? qMax(1, height / 4) : 0;

        QVector<QPoint> samples;
        samples.append(center);
        if (offsetX || offsetY) {
            samples.append(center + QPoint(-offsetX, -offsetY));
            samples.append(center + QPoint(offsetX, -offsetY));
            samples.append(center + QPoint(-offsetX, offsetY));
            samples.append(center + QPoint(offsetX, offsetY));
        }
        return samples;
    }

    bool pointWithinWidgetMask(QWidget *target, const QPoint &localPoint)
    {
        const QRegion region = target->mask();
        if (region.isEmpty())
            return true;
        return region.contains(localPoint);
    }

    QWidget *topmostHitAtPoint(QWidget *target, const QPoint &localPoint)
    {
        if (!pointWithinWidgetMask(target, localPoint))
            return nullptr;

        const QPoint globalPos = target->mapToGlobal(localPoint);

        QWidget *hit = QApplication::widgetAt(globalPos);
        if (isAutomationOverlayWidget(hit) || isMouseTransparentWidget(hit))
            hit = nullptr;
        if (!hit)
            hit = target->childAt(localPoint);
        if (isMouseTransparentWidget(hit))
            hit = nullptr;
        if (!hit)
            hit = target;
        return hit;
    }

    bool isTopmostVisibleWidget(QWidget *w)
    {
        QWidget *target = primaryEventTarget(w);
        if (!target || !target->isVisible())
            return false;

        const QVector<QPoint> samples = sampleLocalPoints(target);
        for (const QPoint &samplePoint : samples) {
            QWidget *hit = topmostHitAtPoint(target, samplePoint);
            if (!hit)
                continue;
            if (!hit->isVisible())
                continue;
            if (isSameOrDescendantWidget(hit, target))
                return true;
        }
        return false;
    }

    struct ClickTarget
    {
        QWidget *widget;
        QPoint localPos;
    };

    ClickTarget resolvePointerActionTarget(const QJsonObject &params)
    {
        if (params.contains("x") != params.contains("y"))
            throw std::runtime_error("Coordinate pointer actions require x and y together");

        const QJsonValue xValue = params.value("x");
        const QJsonValue yValue = params.value("y");
        if (!xValue.isDouble() || !yValue.isDouble())
            throw std::runtime_error("Coordinate pointer actions require integer x and y values");

        const int x = xValue.toInt();
        const int y = yValue.toInt();
        if (x < 0 || y < 0)
            throw std::runtime_error("Coordinate pointer actions require non-negative x and y");

        QWidget *window = resolvePointerActionWindow(params);
        if (x >= window->width() || y >= window->height())
            throw std::runtime_error("Coordinate pointer action is outside the target window bounds");

        const QPoint windowPos(x, y);
        if (!pointWithinWidgetMask(window, windowPos))
            throw std::runtime_error("Coordinate pointer action resolves to a masked-out point");

        const QPoint globalPos = window->mapToGlobal(windowPos);
        QWidget *hit = topmostHitAtPoint(window, windowPos);
        if (!hit)
            throw std::runtime_error("Coordinate pointer action does not resolve to an event target");
        if (!isSameOrDescendantWidget(hit, window)) {
            throw std::runtime_error(
                std::string("Coordinate pointer action is covered by ") + std::string(hit->metaObject()->className())
            );
        }
        if (!hit->isVisible())
            throw std::runtime_error("Coordinate pointer action resolved to a non-visible widget");
        if (!hit->isEnabled())
            throw std::runtime_error("Coordinate pointer action resolved to a disabled widget");
        return {hit, hit->mapFromGlobal(globalPos)};
    }

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
        if (!pointWithinWidgetMask(target, center)) {
            throw std::runtime_error(
                std::string("Cannot click widget of type: ") + std::string(w->metaObject()->className()) +
                "; center point is masked out"
            );
        }
        QPoint globalPos = target->mapToGlobal(center);
        QWidget *hit = topmostHitAtPoint(target, center);
        if (!hit) {
            throw std::runtime_error(
                std::string("Cannot click widget of type: ") + std::string(w->metaObject()->className()) +
                "; center point does not resolve to an event target"
            );
        }

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
        updateVisualFeedback(target, clickTarget.localPos, doubleClick ? 2 : 1);
        if (doubleClick)
            QTest::mouseDClick(target, Qt::LeftButton, Qt::NoModifier, clickTarget.localPos);
        else
            QTest::mouseClick(target, Qt::LeftButton, Qt::NoModifier, clickTarget.localPos);
        QApplication::processEvents();
    }

    void clickPointerActionTarget(const QJsonObject &params, bool doubleClick)
    {
        auto clickTarget = resolvePointerActionTarget(params);
        clickWidgetAt(clickTarget.widget, clickTarget.localPos, doubleClick);
    }
    
    void clickWidgetAt(QWidget *target, const QPoint &localPos, bool doubleClick)
    {
        if (!target->isVisible())
            throw std::runtime_error("Cannot click item target: event target is not visible");
        if (!target->isEnabled())
            throw std::runtime_error("Cannot click item target: event target is disabled");
        
        target->setFocus(Qt::MouseFocusReason);
        QApplication::processEvents();
        updateVisualFeedback(target, localPos, doubleClick ? 2 : 1);
        if (doubleClick)
            QTest::mouseDClick(target, Qt::LeftButton, Qt::NoModifier, localPos);
        else
            QTest::mouseClick(target, Qt::LeftButton, Qt::NoModifier, localPos);
        QApplication::processEvents();
    }
    
    void clickTableIndex(QWidget *owner, const ResolvedTableItem &target, bool doubleClick)
    {
        QTableView *view = tableView(owner);
        QWidget *targetWidget = primaryEventTarget(view);
        const QRect rect = tableIndexRect(owner, target);
        clickWidgetAt(targetWidget, rect.center(), doubleClick);
    }

    void clickListIndex(QWidget *owner, const ResolvedListItem &target, bool doubleClick)
    {
        QListView *view = listView(owner);
        QWidget *targetWidget = primaryEventTarget(view);
        const QRect rect = listIndexRect(owner, target);
        clickWidgetAt(targetWidget, rect.center(), doubleClick);
    }

    void clickTreeIndex(QWidget *owner, const ResolvedTreeItem &target, bool doubleClick)
    {
        QTreeView *view = treeView(owner);
        QWidget *targetWidget = primaryEventTarget(view);
        const QRect rect = treeIndexRect(owner, target);
        clickWidgetAt(targetWidget, rect.center(), doubleClick);
    }

    void clickTabItem(QWidget *owner, const ResolvedTabItem &target, bool doubleClick)
    {
        Q_UNUSED(owner);
        if (!target.tabBar)
            throw std::runtime_error("Tab item is missing tab bar context");

        const QRect rect = tabItemRect(owner, target);
        clickWidgetAt(target.tabBar, rect.center(), doubleClick);
    }

    void moveVisualCursorToWidget(QWidget *w, int pulseCount = 0)
    {
        QWidget *target = primaryEventTarget(w);
        updateVisualFeedback(target, target->rect().center(), pulseCount);
    }

    void fillWidget(QWidget *w, const QString &value)
    {
        moveVisualCursorToWidget(w);
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
        moveVisualCursorToWidget(w);
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

        moveVisualCursorToWidget(w);
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

    void hoverWidget(QWidget *w)
    {
        QWidget *target = primaryEventTarget(w);
        QPoint center = target->rect().center();
        updateVisualFeedback(target, center, 0);
        QPoint globalPos = target->mapToGlobal(center);
#if QT_VERSION >= QT_VERSION_CHECK(6, 0, 0)
        QMouseEvent event(
            QEvent::MouseMove,
            QPointF(center),
            QPointF(globalPos),
            Qt::NoButton,
            Qt::NoButton,
            Qt::NoModifier
        );
#else
        QMouseEvent event(
            QEvent::MouseMove,
            center,
            globalPos,
            Qt::NoButton,
            Qt::NoButton,
            Qt::NoModifier
        );
#endif
        QApplication::sendEvent(target, &event);
        QApplication::processEvents();
    }

    void hoverPointerActionTarget(const QJsonObject &params)
    {
        auto hoverTarget = resolvePointerActionTarget(params);
        QWidget *target = hoverTarget.widget;
        const QPoint localPos = hoverTarget.localPos;
        updateVisualFeedback(target, localPos, 0);
        const QPoint globalPos = target->mapToGlobal(localPos);
#if QT_VERSION >= QT_VERSION_CHECK(6, 0, 0)
        QMouseEvent event(
            QEvent::MouseMove,
            QPointF(localPos),
            QPointF(globalPos),
            Qt::NoButton,
            Qt::NoButton,
            Qt::NoModifier
        );
#else
        QMouseEvent event(
            QEvent::MouseMove,
            localPos,
            globalPos,
            Qt::NoButton,
            Qt::NoButton,
            Qt::NoModifier
        );
#endif
        QApplication::sendEvent(target, &event);
        QApplication::processEvents();
    }

    void hoverTableIndex(QWidget *owner, const ResolvedTableItem &target)
    {
        QTableView *view = tableView(owner);
        QWidget *targetWidget = primaryEventTarget(view);
        const QRect rect = tableIndexRect(owner, target);
        const QPoint center = rect.center();
        updateVisualFeedback(targetWidget, center, 0);
        const QPoint globalPos = targetWidget->mapToGlobal(center);
#if QT_VERSION >= QT_VERSION_CHECK(6, 0, 0)
        QMouseEvent event(
            QEvent::MouseMove,
            QPointF(center),
            QPointF(globalPos),
            Qt::NoButton,
            Qt::NoButton,
            Qt::NoModifier
        );
#else
        QMouseEvent event(
            QEvent::MouseMove,
            center,
            globalPos,
            Qt::NoButton,
            Qt::NoButton,
            Qt::NoModifier
        );
#endif
        QApplication::sendEvent(targetWidget, &event);
        QApplication::processEvents();
    }

    void hoverListIndex(QWidget *owner, const ResolvedListItem &target)
    {
        QListView *view = listView(owner);
        QWidget *targetWidget = primaryEventTarget(view);
        const QRect rect = listIndexRect(owner, target);
        const QPoint center = rect.center();
        updateVisualFeedback(targetWidget, center, 0);
        const QPoint globalPos = targetWidget->mapToGlobal(center);
#if QT_VERSION >= QT_VERSION_CHECK(6, 0, 0)
        QMouseEvent event(
            QEvent::MouseMove,
            QPointF(center),
            QPointF(globalPos),
            Qt::NoButton,
            Qt::NoButton,
            Qt::NoModifier
        );
#else
        QMouseEvent event(
            QEvent::MouseMove,
            center,
            globalPos,
            Qt::NoButton,
            Qt::NoButton,
            Qt::NoModifier
        );
#endif
        QApplication::sendEvent(targetWidget, &event);
        QApplication::processEvents();
    }

    void hoverTreeIndex(QWidget *owner, const ResolvedTreeItem &target)
    {
        QTreeView *view = treeView(owner);
        QWidget *targetWidget = primaryEventTarget(view);
        const QRect rect = treeIndexRect(owner, target);
        const QPoint center = rect.center();
        updateVisualFeedback(targetWidget, center, 0);
        const QPoint globalPos = targetWidget->mapToGlobal(center);
#if QT_VERSION >= QT_VERSION_CHECK(6, 0, 0)
        QMouseEvent event(
            QEvent::MouseMove,
            QPointF(center),
            QPointF(globalPos),
            Qt::NoButton,
            Qt::NoButton,
            Qt::NoModifier
        );
#else
        QMouseEvent event(
            QEvent::MouseMove,
            center,
            globalPos,
            Qt::NoButton,
            Qt::NoButton,
            Qt::NoModifier
        );
#endif
        QApplication::sendEvent(targetWidget, &event);
        QApplication::processEvents();
    }

    void hoverTabItem(QWidget *owner, const ResolvedTabItem &target)
    {
        Q_UNUSED(owner);
        if (!target.tabBar)
            throw std::runtime_error("Tab item is missing tab bar context");

        const QRect rect = tabItemRect(owner, target);
        const QPoint center = rect.center();
        updateVisualFeedback(target.tabBar, center, 0);
        const QPoint globalPos = target.tabBar->mapToGlobal(center);
#if QT_VERSION >= QT_VERSION_CHECK(6, 0, 0)
        QMouseEvent event(
            QEvent::MouseMove,
            QPointF(center),
            QPointF(globalPos),
            Qt::NoButton,
            Qt::NoButton,
            Qt::NoModifier
        );
#else
        QMouseEvent event(
            QEvent::MouseMove,
            center,
            globalPos,
            Qt::NoButton,
            Qt::NoButton,
            Qt::NoModifier
        );
#endif
        QApplication::sendEvent(target.tabBar, &event);
        QApplication::processEvents();
    }

    void selectTabItem(QWidget *owner, const ResolvedTabItem &target)
    {
        if (auto *widget = qobject_cast<QTabWidget *>(owner)) {
            widget->setCurrentIndex(target.index);
            QApplication::processEvents();
            return;
        }

        QTabBar *bar = target.tabBar ? target.tabBar : tabBarFromOwner(owner);
        bar->setCurrentIndex(target.index);
        QApplication::processEvents();
    }

    void expandTreeIndex(QWidget *owner, const ResolvedTreeItem &target)
    {
        QTreeView *view = treeView(owner);
        view->expand(target.index);
        QApplication::processEvents();
    }

    void collapseTreeIndex(QWidget *owner, const ResolvedTreeItem &target)
    {
        QTreeView *view = treeView(owner);
        view->collapse(target.index);
        QApplication::processEvents();
    }

    QJsonObject inspectTableItems(QWidget *owner, int maxRows, int maxItems, bool includeHidden)
    {
        QTableView *view = tableView(owner);
        auto *model = view->model();
        if (!model)
            throw std::runtime_error("Table widget model is not available");

        const int rowCount = model->rowCount();
        const int columnCount = model->columnCount();
        const int rowsInspected = qMin(rowCount, maxRows);
        bool truncated = rowCount > rowsInspected;

        QJsonArray columns;
        for (int column = 0; column < columnCount; ++column) {
            QJsonObject entry;
            entry["column"] = column;
            entry["header"] = model->headerData(column, Qt::Horizontal, Qt::DisplayRole).toString();
            entry["hidden"] = view->isColumnHidden(column);
            columns.append(entry);
        }

        QJsonArray items;
        for (int row = 0; row < rowsInspected; ++row) {
            for (int column = 0; column < columnCount; ++column) {
                const QModelIndex index = model->index(row, column);
                if (!index.isValid())
                    continue;

                const ResolvedTableItem target{row, column, index};
                const bool visible = tableIndexVisible(owner, target);
                if (!includeHidden && !visible)
                    continue;

                const QJsonObject properties = tableIndexProperties(owner, target);
                QJsonObject descriptor;
                descriptor["kind"] = "table_cell";
                descriptor["row"] = row;
                descriptor["column"] = column;

                QJsonObject entry;
                entry["item"] = descriptor;
                entry["row"] = row;
                entry["column"] = column;
                entry["columnHeader"] = model->headerData(column, Qt::Horizontal, Qt::DisplayRole).toString();
                entry["text"] = properties.value("text").toString();
                entry["visible"] = visible;
                entry["selected"] = properties.value("selected").toBool(false);
                items.append(entry);

                if (items.size() >= maxItems) {
                    truncated = true;
                    QJsonObject payload;
                    payload["kind"] = "table";
                    payload["rowCount"] = rowCount;
                    payload["columnCount"] = columnCount;
                    payload["rowsInspected"] = rowsInspected;
                    payload["columns"] = columns;
                    payload["items"] = items;
                    payload["truncated"] = truncated;
                    return payload;
                }
            }
        }

        QJsonObject payload;
        payload["kind"] = "table";
        payload["rowCount"] = rowCount;
        payload["columnCount"] = columnCount;
        payload["rowsInspected"] = rowsInspected;
        payload["columns"] = columns;
        payload["items"] = items;
        payload["truncated"] = truncated;
        return payload;
    }

    QJsonObject inspectListItems(QWidget *owner, int maxRows, int maxItems, bool includeHidden)
    {
        QListView *view = listView(owner);
        auto *model = view->model();
        if (!model)
            throw std::runtime_error("List widget model is not available");

        const int rowCount = model->rowCount();
        const int rowsInspected = qMin(rowCount, maxRows);
        bool truncated = rowCount > rowsInspected;
        QJsonArray items;

        for (int row = 0; row < rowsInspected; ++row) {
            const QModelIndex index = model->index(row, 0);
            if (!index.isValid())
                continue;

            const ResolvedListItem target{row, index};
            const bool visible = listIndexVisible(owner, target);
            if (!includeHidden && !visible)
                continue;

            const QJsonObject properties = listIndexProperties(owner, target);
            QJsonObject descriptor;
            descriptor["kind"] = "list_item";
            descriptor["row"] = row;

            QJsonObject entry;
            entry["item"] = descriptor;
            entry["row"] = row;
            entry["text"] = properties.value("text").toString();
            entry["visible"] = visible;
            entry["selected"] = properties.value("selected").toBool(false);
            items.append(entry);

            if (items.size() >= maxItems) {
                truncated = true;
                break;
            }
        }

        QJsonObject payload;
        payload["kind"] = "list";
        payload["rowCount"] = rowCount;
        payload["rowsInspected"] = rowsInspected;
        payload["items"] = items;
        payload["truncated"] = truncated;
        return payload;
    }

    QJsonObject inspectTreeItems(QWidget *owner, int maxDepth, int maxItems, bool includeHidden)
    {
        QTreeView *view = treeView(owner);
        auto *model = view->model();
        if (!model)
            throw std::runtime_error("Tree widget model is not available");

        bool truncated = false;
        QJsonArray items;

        std::function<void(const QModelIndex &, int)> visit = [&](const QModelIndex &parent, int depth) {
            if (truncated)
                return;

            const int rowCount = model->rowCount(parent);
            for (int row = 0; row < rowCount; ++row) {
                const QModelIndex index = model->index(row, 0, parent);
                if (!index.isValid())
                    continue;

                const ResolvedTreeItem target{index};
                const bool visible = treeIndexVisible(owner, target);
                if (includeHidden || visible) {
                    const QJsonObject properties = treeIndexProperties(owner, target);
                    QJsonObject descriptor;
                    descriptor["kind"] = "tree_node";
                    descriptor["path"] = treeIndexRowPath(index);

                    QJsonObject entry;
                    entry["item"] = descriptor;
                    entry["depth"] = depth;
                    entry["text"] = properties.value("text").toString();
                    entry["labelPath"] = properties.value("path").toArray();
                    entry["visible"] = visible;
                    entry["selected"] = properties.value("selected").toBool(false);
                    entry["expanded"] = properties.value("expanded").toBool(false);
                    entry["hasChildren"] = model->rowCount(index) > 0;
                    items.append(entry);

                    if (items.size() >= maxItems) {
                        truncated = true;
                        return;
                    }
                }

                const int childCount = model->rowCount(index);
                if (childCount <= 0)
                    continue;
                if (depth >= maxDepth) {
                    if (includeHidden || view->isExpanded(index))
                        truncated = true;
                    continue;
                }
                if (includeHidden || view->isExpanded(index)) {
                    visit(index, depth + 1);
                    if (truncated)
                        return;
                }
            }
        };

        visit(QModelIndex(), 0);

        QJsonObject payload;
        payload["kind"] = "tree";
        payload["maxDepth"] = maxDepth;
        payload["items"] = items;
        payload["truncated"] = truncated;
        return payload;
    }

    QJsonObject inspectTabItems(QWidget *owner, int maxItems, bool includeHidden)
    {
        QTabBar *bar = tabBarFromOwner(owner);
        QVector<int> indices;
        const int count = tabCount(bar);
        for (int index = 0; index < count; ++index) {
            if (includeHidden || tabVisible(bar, index))
                indices.append(index);
        }

        const bool truncated = indices.size() > maxItems;
        QJsonArray items;
        const int inspected = qMin(indices.size(), maxItems);
        for (int offset = 0; offset < inspected; ++offset) {
            const int index = indices.at(offset);

            QJsonObject descriptor;
            descriptor["kind"] = "tab_item";
            descriptor["index"] = index;

            QJsonObject entry;
            entry["item"] = descriptor;
            entry["index"] = index;
            entry["text"] = tabText(bar, index);
            entry["visible"] = tabVisible(bar, index);
            entry["selected"] = index == tabCurrentIndex(owner);
            entry["enabled"] = tabEnabled(bar, index);

            const QString pageObjectName = tabPageObjectName(owner, index);
            if (!pageObjectName.isEmpty())
                entry["pageObjectName"] = pageObjectName;
            items.append(entry);
        }

        QJsonObject payload;
        payload["kind"] = "tab";
        payload["maxItems"] = maxItems;
        payload["items"] = items;
        payload["truncated"] = truncated;
        return payload;
    }

    QJsonObject inspectItemView(QWidget *owner, int maxRows, int maxDepth, int maxItems, bool includeHidden)
    {
        if (qobject_cast<QTableView *>(owner))
            return inspectTableItems(owner, maxRows, maxItems, includeHidden);
        if (qobject_cast<QListView *>(owner))
            return inspectListItems(owner, maxRows, maxItems, includeHidden);
        if (qobject_cast<QTreeView *>(owner))
            return inspectTreeItems(owner, maxDepth, maxItems, includeHidden);
        if (qobject_cast<QTabWidget *>(owner) || qobject_cast<QTabBar *>(owner))
            return inspectTabItems(owner, maxItems, includeHidden);

        throw std::runtime_error(
            ("Widget does not expose supported item-view descendants: " + QString::fromLatin1(owner->metaObject()->className())).toStdString()
        );
    }

    void selectOption(QWidget *w, const QJsonObject &params)
    {
        auto *combo = qobject_cast<QComboBox *>(w);
        if (!combo)
            throw std::runtime_error("Widget is not a QComboBox");

        moveVisualCursorToWidget(w, 1);

        if (params.contains("value"))
            combo->setCurrentText(params["value"].toString());
        else if (params.contains("index"))
            combo->setCurrentIndex(params["index"].toInt());
        else if (params.contains("label")) {
            int idx = combo->findText(params["label"].toString());
            if (idx >= 0)
                combo->setCurrentIndex(idx);
        }
        QApplication::processEvents();
    }

    void scrollWidget(QWidget *w, int dx, int dy)
    {
        QWidget *target = primaryEventTarget(w);
        QPoint center = target->rect().center();
        updateVisualFeedback(target, center, (dx != 0 || dy != 0) ? 1 : 0);
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

            QList<QWidget *> roots = interactableTopLevelWidgets();
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
    QPointer<AutomationOverlayManager> m_overlayManager;
    QHash<QString, QString> m_sessionAgentNames;
    QString m_activeSessionId;
};

// -------------------------------------------------------------------------- //
//  Client connection                                                          //
// -------------------------------------------------------------------------- //

class QPlaywrightClientConnection : public QObject
{
    Q_OBJECT
public:
    QPlaywrightClientConnection(QTcpSocket *socket, QPlaywrightHandler *handler, QObject *parent = nullptr)
        : QObject(parent), m_socket(socket), m_handler(handler), m_sessionId(QString::number(socket->socketDescriptor()))
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
            if (!line.isEmpty())
                processLine(line);
        }
    }

    void onDisconnected()
    {
        qDebug() << "[QPlaywright] Client disconnected";
        QMetaObject::invokeMethod(
            m_handler,
            [this] {
                m_handler->onClientDisconnected(m_sessionId);
            },
            Qt::BlockingQueuedConnection
        );
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
    QJsonObject params = request["params"].toObject();
    params["_sessionId"] = m_sessionId;
    request["params"] = params;

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
    QString m_sessionId;
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
 * is handled in a dedicated QThread, with commands dispatched to the main
 * thread via BlockingQueuedConnection for thread-safe widget access.
 */
class QPlaywrightAgent : public QObject
{
    Q_OBJECT
public:
    /**
     * @brief Start the agent on the given port.
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
