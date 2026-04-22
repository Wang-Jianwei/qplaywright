// Raw invoke protocol draft for custom widget automation.
//
// Scope:
// - This metadata describes class methods only.
// - It does not describe Qt event simulation such as click, hover, key press,
//   or wheel events. Those belong to the agent's interaction layer.

#include <QMetaType>
#include <QString>
#include <QStringList>
#include <QVariant>
#include <QVariantMap>
#include <QVector>
#include <QWidget>
#include <QMetaMethod>


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
        _name = name;
        return *this;
    }

    QPlaywrightMethodArg &type(const QString &type)
    {
        _type = type;
        return *this;
    }

    QPlaywrightMethodArg &brief(const QString &brief)
    {
        _brief = brief;
        return *this;
    }

    QPlaywrightMethodArg &required(bool required)
    {
        _required = required;
        return *this;
    }

    QPlaywrightMethodArg &defaultValue(const QVariant &defaultValue)
    {
        _defaultValue = defaultValue;
        return *this;
    }

    QString name() const { return _name; }
    QString type() const { return _type; }
    QString brief() const { return _brief; }
    bool required() const { return _required; }
    QVariant defaultValue() const { return _defaultValue; }

    bool hasDefaultValue() const { return _defaultValue.isValid(); }

    QVariantMap toVariantMap() const
    {
        return {
            {"name", _name},
            {"type", _type},
            {"brief", _brief},
            {"required", _required},
            {"defaultValue", _defaultValue},
        };
    }

private:
    QString _name;
    QString _type;
    QString _brief;
    bool _required = true;
    QVariant _defaultValue;
};


class QPlaywrightClassMethod
{
public:
    QPlaywrightClassMethod() = default;

    QPlaywrightClassMethod &name(const QString &name)
    {
        _name = name;
        return *this;
    }

    QPlaywrightClassMethod &addArg(const QPlaywrightMethodArg &arg)
    {
        _args.append(arg);
        return *this;
    }

    QPlaywrightClassMethod &returnType(const QString &returnType)
    {
        _returnType = returnType;
        return *this;
    }

    QPlaywrightClassMethod &brief(const QString &brief)
    {
        _brief = brief;
        return *this;
    }

    QString name() const { return _name; }
    QVector<QPlaywrightMethodArg> args() const { return _args; }
    QString returnType() const { return _returnType; }
    QString brief() const { return _brief; }

    QString signature() const
    {
        QStringList argTypeNames;
        for (const QPlaywrightMethodArg &arg : _args)
            argTypeNames.append(arg.type());
        return QStringLiteral("%1(%2)").arg(_name, argTypeNames.join(QStringLiteral(", ")));
    }

    bool acceptsArgs(const QVariantMap &providedArgs, QString *error = nullptr) const
    {
        for (auto it = providedArgs.constBegin(); it != providedArgs.constEnd(); ++it) {
            bool known = false;
            for (const QPlaywrightMethodArg &arg : _args) {
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

        for (const QPlaywrightMethodArg &arg : _args) {
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
        for (const QPlaywrightMethodArg &arg : _args)
            argMaps.append(arg.toVariantMap());

        return {
            {"name", _name},
            {"args", argMaps},
            {"returnType", _returnType},
            {"brief", _brief},
        };
    }

private:
    QString _name;
    QVector<QPlaywrightMethodArg> _args;
    QString _returnType;
    QString _brief;
};


class QPlaywrightClassMetadata
{
public:
    QPlaywrightClassMetadata() = default;

    QPlaywrightClassMetadata &role(const QString &role)
    {
        _role = role;
        return *this;
    }

    QString role() const { return _role; }

    QPlaywrightClassMetadata &addMethod(const QPlaywrightClassMethod &method)
    {
        _methods.append(method);
        return *this;
    }

    QVector<QPlaywrightClassMethod> methods() const { return _methods; }

    bool hasMethod(const QString &name) const
    {
        for (const QPlaywrightClassMethod &method : _methods) {
            if (method.name() == name)
                return true;
        }
        return false;
    }

    QPlaywrightClassMethod findMethod(const QString &name) const
    {
        for (const QPlaywrightClassMethod &method : _methods) {
            if (method.name() == name)
                return method;
        }
        return {};
    }

    QVariantMap toVariantMap() const
    {
        QVariantList methodMaps;
        for (const QPlaywrightClassMethod &method : _methods)
            methodMaps.append(method.toVariantMap());

        return {
            {"role", _role},
            {"methods", methodMaps},
        };
    }

private:
    QString _role;
    QVector<QPlaywrightClassMethod> _methods;
};


class QPlaywrightInvokeResult
{
public:
    QPlaywrightInvokeResult() = default;

    static QPlaywrightInvokeResult success(const QVariant &value = {})
    {
        QPlaywrightInvokeResult result;
        result._ok = true;
        result._value = value;
        return result;
    }

    static QPlaywrightInvokeResult failure(QPlaywrightInvokeErrorCode code, const QString &message)
    {
        QPlaywrightInvokeResult result;
        result._ok = false;
        result._errorCode = code;
        result._errorMessage = message;
        return result;
    }

    bool ok() const { return _ok; }
    QVariant value() const { return _value; }
    QPlaywrightInvokeErrorCode errorCode() const { return _errorCode; }
    QString errorMessage() const { return _errorMessage; }

    QVariantMap toVariantMap() const
    {
        return {
            {"ok", _ok},
            {"value", _value},
            {"errorCode", static_cast<int>(_errorCode)},
            {"errorMessage", _errorMessage},
        };
    }

private:
    bool _ok = false;
    QVariant _value;
    QPlaywrightInvokeErrorCode _errorCode = QPlaywrightInvokeErrorCode::None;
    QString _errorMessage;
};


Q_DECLARE_METATYPE(QPlaywrightMethodArg)
Q_DECLARE_METATYPE(QPlaywrightClassMethod)
Q_DECLARE_METATYPE(QPlaywrightClassMetadata)
Q_DECLARE_METATYPE(QPlaywrightInvokeResult)
Q_DECLARE_METATYPE(QPlaywrightInvokeErrorCode)


class QPlaywrightInvokeRequest
{
public:
    QPlaywrightInvokeRequest() = default;

    QPlaywrightInvokeRequest &method(const QString &method)
    {
        _method = method;
        return *this;
    }

    QPlaywrightInvokeRequest &args(const QVariantMap &args)
    {
        _args = args;
        return *this;
    }

    QString method() const { return _method; }
    QVariantMap args() const { return _args; }

    QVariantMap toVariantMap() const
    {
        return {
            {"method", _method},
            {"args", _args},
        };
    }

private:
    QString _method;
    QVariantMap _args;
};


Q_DECLARE_METATYPE(QPlaywrightInvokeRequest)


class QPlaywrightPreparedCall
{
public:
    QPlaywrightPreparedCall() = default;

    QPlaywrightPreparedCall &method(const QPlaywrightClassMethod &method)
    {
        _method = method;
        return *this;
    }

    QPlaywrightPreparedCall &orderedArgs(const QVariantList &orderedArgs)
    {
        _orderedArgs = orderedArgs;
        return *this;
    }

    QPlaywrightClassMethod method() const { return _method; }
    QVariantList orderedArgs() const { return _orderedArgs; }

private:
    QPlaywrightClassMethod _method;
    QVariantList _orderedArgs;
};


class QPlaywrightTypeConverter
{
public:
    static bool convert(const QVariant &input, const QString &targetType, QVariant *output, QString *error = nullptr)
    {
        if (targetType.isEmpty() || targetType == "QVariant") {
            *output = input;
            return true;
        }

        QVariant converted = input;

        if (targetType == "QString") {
            *output = converted.toString();
            return true;
        }
        if (targetType == "int") {
            if (!converted.canConvert<int>()) {
                if (error)
                    *error = QStringLiteral("Cannot convert value to int");
                return false;
            }
            *output = converted.toInt();
            return true;
        }
        if (targetType == "double") {
            if (!converted.canConvert<double>()) {
                if (error)
                    *error = QStringLiteral("Cannot convert value to double");
                return false;
            }
            *output = converted.toDouble();
            return true;
        }
        if (targetType == "bool") {
            if (!converted.canConvert<bool>()) {
                if (error)
                    *error = QStringLiteral("Cannot convert value to bool");
                return false;
            }
            *output = converted.toBool();
            return true;
        }
        if (targetType == "QStringList") {
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
            const QPlaywrightInvokeErrorCode code = argError.startsWith("Missing required")
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

    static QPlaywrightInvokeResult executePreparedCall(
        QObject *target,
        const QPlaywrightPreparedCall &preparedCall)
    {
        const QPlaywrightClassMethod method = preparedCall.method();
        const QVariantList orderedArgs = preparedCall.orderedArgs();

        if (orderedArgs.size() > 2) {
            return QPlaywrightInvokeResult::failure(
                QPlaywrightInvokeErrorCode::MethodInvocationFailed,
                QStringLiteral("First implementation supports at most 2 arguments: %1").arg(method.signature())
            );
        }

        if (method.returnType().isEmpty() || method.returnType() == "void")
            return invokeVoid(target, method, orderedArgs);
        if (method.returnType() == "QString")
            return invokeQString(target, method, orderedArgs);
        if (method.returnType() == "QVariant")
            return invokeQVariant(target, method, orderedArgs);
        if (method.returnType() == "bool")
            return invokeBool(target, method, orderedArgs);
        if (method.returnType() == "int")
            return invokeInt(target, method, orderedArgs);
        if (method.returnType() == "double")
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
        const bool ok = invokeNoReturn(target, method, args);
        if (!ok) {
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
        const bool ok = invokeWithReturn(target, method, args, Q_RETURN_ARG(QString, value));
        return buildReturnResult(ok, method, value);
    }

    static QPlaywrightInvokeResult invokeQVariant(QObject *target, const QPlaywrightClassMethod &method, const QVariantList &args)
    {
        QVariant value;
        const bool ok = invokeWithReturn(target, method, args, Q_RETURN_ARG(QVariant, value));
        return buildReturnResult(ok, method, value);
    }

    static QPlaywrightInvokeResult invokeBool(QObject *target, const QPlaywrightClassMethod &method, const QVariantList &args)
    {
        bool value = false;
        const bool ok = invokeWithReturn(target, method, args, Q_RETURN_ARG(bool, value));
        return buildReturnResult(ok, method, value);
    }

    static QPlaywrightInvokeResult invokeInt(QObject *target, const QPlaywrightClassMethod &method, const QVariantList &args)
    {
        int value = 0;
        const bool ok = invokeWithReturn(target, method, args, Q_RETURN_ARG(int, value));
        return buildReturnResult(ok, method, value);
    }

    static QPlaywrightInvokeResult invokeDouble(QObject *target, const QPlaywrightClassMethod &method, const QVariantList &args)
    {
        double value = 0.0;
        const bool ok = invokeWithReturn(target, method, args, Q_RETURN_ARG(double, value));
        return buildReturnResult(ok, method, value);
    }

    template <typename ReturnArg>
    static bool invokeWithReturn(QObject *target, const QPlaywrightClassMethod &method, const QVariantList &args, ReturnArg returnArg)
    {
        const QByteArray methodName = method.name().toLatin1();
        if (args.isEmpty()) {
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, returnArg);
        }
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

    static bool invokeNoReturnOneArg(
        QObject *target,
        const QByteArray &methodName,
        const QString &declaredType,
        const QVariant &value)
    {
        if (declaredType == "QString") {
            const QString converted = value.toString();
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, Q_ARG(QString, converted));
        }
        if (declaredType == "QVariant") {
            const QVariant converted = value;
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, Q_ARG(QVariant, converted));
        }
        if (declaredType == "int") {
            const int converted = value.toInt();
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, Q_ARG(int, converted));
        }
        if (declaredType == "bool") {
            const bool converted = value.toBool();
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, Q_ARG(bool, converted));
        }
        if (declaredType == "double") {
            const double converted = value.toDouble();
            return QMetaObject::invokeMethod(target, methodName.constData(), Qt::DirectConnection, Q_ARG(double, converted));
        }
        return false;
    }

    static bool invokeNoReturnTwoArgs(
        QObject *target,
        const QByteArray &methodName,
        const QVector<QPlaywrightMethodArg> &declaredArgs,
        const QVariantList &values)
    {
        const QString firstType = declaredArgs.at(0).type();
        const QString secondType = declaredArgs.at(1).type();

        if (firstType == "int" && secondType == "int") {
            const int first = values.at(0).toInt();
            const int second = values.at(1).toInt();
            return QMetaObject::invokeMethod(
                target,
                methodName.constData(),
                Qt::DirectConnection,
                Q_ARG(int, first),
                Q_ARG(int, second)
            );
        }
        if (firstType == "QString" && secondType == "QString") {
            const QString first = values.at(0).toString();
            const QString second = values.at(1).toString();
            return QMetaObject::invokeMethod(
                target,
                methodName.constData(),
                Qt::DirectConnection,
                Q_ARG(QString, first),
                Q_ARG(QString, second)
            );
        }
        if (firstType == "QVariant" && secondType == "QVariant") {
            const QVariant first = values.at(0);
            const QVariant second = values.at(1);
            return QMetaObject::invokeMethod(
                target,
                methodName.constData(),
                Qt::DirectConnection,
                Q_ARG(QVariant, first),
                Q_ARG(QVariant, second)
            );
        }
        return false;
    }

    template <typename ReturnArg>
    static bool invokeWithReturnOneArg(
        QObject *target,
        const QByteArray &methodName,
        ReturnArg returnArg,
        const QString &declaredType,
        const QVariant &value)
    {
        if (declaredType == "QString") {
            const QString converted = value.toString();
            return QMetaObject::invokeMethod(
                target,
                methodName.constData(),
                Qt::DirectConnection,
                returnArg,
                Q_ARG(QString, converted)
            );
        }
        if (declaredType == "QVariant") {
            const QVariant converted = value;
            return QMetaObject::invokeMethod(
                target,
                methodName.constData(),
                Qt::DirectConnection,
                returnArg,
                Q_ARG(QVariant, converted)
            );
        }
        if (declaredType == "int") {
            const int converted = value.toInt();
            return QMetaObject::invokeMethod(
                target,
                methodName.constData(),
                Qt::DirectConnection,
                returnArg,
                Q_ARG(int, converted)
            );
        }
        if (declaredType == "bool") {
            const bool converted = value.toBool();
            return QMetaObject::invokeMethod(
                target,
                methodName.constData(),
                Qt::DirectConnection,
                returnArg,
                Q_ARG(bool, converted)
            );
        }
        if (declaredType == "double") {
            const double converted = value.toDouble();
            return QMetaObject::invokeMethod(
                target,
                methodName.constData(),
                Qt::DirectConnection,
                returnArg,
                Q_ARG(double, converted)
            );
        }
        return false;
    }

    template <typename ReturnArg>
    static bool invokeWithReturnTwoArgs(
        QObject *target,
        const QByteArray &methodName,
        ReturnArg returnArg,
        const QVector<QPlaywrightMethodArg> &declaredArgs,
        const QVariantList &values)
    {
        const QString firstType = declaredArgs.at(0).type();
        const QString secondType = declaredArgs.at(1).type();

        if (firstType == "int" && secondType == "int") {
            const int first = values.at(0).toInt();
            const int second = values.at(1).toInt();
            return QMetaObject::invokeMethod(
                target,
                methodName.constData(),
                Qt::DirectConnection,
                returnArg,
                Q_ARG(int, first),
                Q_ARG(int, second)
            );
        }
        if (firstType == "QString" && secondType == "QString") {
            const QString first = values.at(0).toString();
            const QString second = values.at(1).toString();
            return QMetaObject::invokeMethod(
                target,
                methodName.constData(),
                Qt::DirectConnection,
                returnArg,
                Q_ARG(QString, first),
                Q_ARG(QString, second)
            );
        }
        if (firstType == "QVariant" && secondType == "QVariant") {
            const QVariant first = values.at(0);
            const QVariant second = values.at(1);
            return QMetaObject::invokeMethod(
                target,
                methodName.constData(),
                Qt::DirectConnection,
                returnArg,
                Q_ARG(QVariant, first),
                Q_ARG(QVariant, second)
            );
        }
        return false;
    }

public:
    // First implementation recommendation:
    // - support 0-2 arguments only
    // - support return types QString, QVariant, bool, int, double, void
    // - support exact method name match only
    // - reject overloaded exposed methods until signature matching is added
    // - branch on declared argument type before each invokeMethod call site
    //   instead of trying to build a fully generic QGenericArgument system
    // - begin with these argument combinations only:
    //   * no args
    //   * one of QString/QVariant/int/bool/double
    //   * two of int,int / QString,QString / QVariant,QVariant
};


inline void registerQPlaywrightMethodMetadataTypes()
{
    qRegisterMetaType<QPlaywrightInvokeErrorCode>("QPlaywrightInvokeErrorCode");
    qRegisterMetaType<QPlaywrightMethodArg>("QPlaywrightMethodArg");
    qRegisterMetaType<QPlaywrightClassMethod>("QPlaywrightClassMethod");
    qRegisterMetaType<QPlaywrightClassMetadata>("QPlaywrightClassMetadata");
    qRegisterMetaType<QPlaywrightInvokeRequest>("QPlaywrightInvokeRequest");
    qRegisterMetaType<QPlaywrightInvokeResult>("QPlaywrightInvokeResult");
}


// custom_widget.h
class FancyAmountEdit : public QWidget
{
    Q_OBJECT

public:
    explicit FancyAmountEdit(QWidget *parent = nullptr)
        : QWidget(parent)
    {
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

    Q_INVOKABLE QString amount() const
    {
        return m_amount;
    }

    Q_INVOKABLE void setAmount(const QString &value)
    {
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


// Agent-side intent:
// 1. Read qplaywrightClassMetadata.
// 2. Resolve a method entry by exact exposed method name, for example amount
//    or setAmount.
// 3. For each declared argument:
//    - read it from request.args by parameter name
//    - use defaultValue when present
//    - fail if a required argument is missing
//    - convert it to the declared type
// 4. Invoke the declared method with QMetaObject::invokeMethod.
// 5. Convert the return value according to returnType.
// 6. Return QPlaywrightInvokeResult with either:
//    - ok=true and the converted return value
//    - ok=false with a structured error code and message
// 7. First implementation should deliberately limit complexity:
//    - exact method name only
//    - no overload resolution
//    - 0-2 arguments only
//    - common Qt scalar types only
//    - explicit invokeMethod branches per return type
//    - explicit invokeMethod branches per argument count
//
// Client-side examples:
// - invoke("amount", {})
// - invoke("setAmount", {"value": "123.45"})
//
// Validation rules:
// - Method name must match exactly one exposed method.
// - Extra arguments are rejected by default.
// - Missing required arguments are rejected unless a defaultValue exists.
// - Type conversion happens after argument name resolution.