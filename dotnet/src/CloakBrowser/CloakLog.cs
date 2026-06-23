namespace CloakBrowser;

/// <summary>
/// Log severity levels for <see cref="CloakLog"/>. By default only Info/Warning/Error are
/// written to stderr; set <c>CloakLog.MinLevel</c> to <see cref="Debug"/> for verbose output,
/// or <see cref="None"/> to silence everything.
/// </summary>
public enum CloakLogLevel
{
    Debug = 0,
    Info = 1,
    Warning = 2,
    Error = 3,
    None = 4,
}

/// <summary>Logging facade used across the library.</summary>
public static class CloakLog
{
    /// <summary>Minimum level that will be emitted. Defaults to <see cref="CloakLogLevel.Info"/>.</summary>
    public static CloakLogLevel MinLevel { get; set; } = CloakLogLevel.Info;

    /// <summary>Optional custom sink. Receives (level, message). Defaults to writing to stderr.</summary>
    public static Action<CloakLogLevel, string>? Sink { get; set; }

    public static void Debug(string message) => Emit(CloakLogLevel.Debug, message);
    public static void Info(string message) => Emit(CloakLogLevel.Info, message);
    public static void Warning(string message) => Emit(CloakLogLevel.Warning, message);
    public static void Error(string message) => Emit(CloakLogLevel.Error, message);

    public static void Debug(string format, params object?[] args) => Emit(CloakLogLevel.Debug, Fmt(format, args));
    public static void Info(string format, params object?[] args) => Emit(CloakLogLevel.Info, Fmt(format, args));
    public static void Warning(string format, params object?[] args) => Emit(CloakLogLevel.Warning, Fmt(format, args));

    private static string Fmt(string format, object?[] args)
    {
        try { return args is { Length: > 0 } ? string.Format(format, args) : format; }
        catch (FormatException) { return format; }
    }

    private static void Emit(CloakLogLevel level, string message)
    {
        if (level < MinLevel) return;
        if (Sink != null) { Sink(level, message); return; }
        Console.Error.WriteLine($"[cloakbrowser:{level.ToString().ToLowerInvariant()}] {message}");
    }
}
