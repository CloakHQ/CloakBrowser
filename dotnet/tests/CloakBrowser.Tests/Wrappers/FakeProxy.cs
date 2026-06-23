using System.Reflection;

namespace CloakBrowser.Tests.Wrappers;

/// <summary>
/// A tiny <see cref="DispatchProxy"/>-based fake for any interface. Records every
/// member access and lets a test register handlers for specific members by name;
/// unregistered members return a sensible default (e.g. <c>Task.CompletedTask</c>).
///
/// This is test-only infrastructure - it lets us verify the production wrappers
/// (which use the source generator, not reflection) without spinning up a real
/// browser. The wrappers forward to <c>_inner</c>; here <c>_inner</c> is one of these
/// fakes, so we can assert exactly which inner calls happened.
/// </summary>
public sealed class CallRecord
{
    public string Member { get; init; } = "";
    public object?[] Args { get; init; } = System.Array.Empty<object?>();
}

public class FakeProxy : DispatchProxy
{
    private readonly List<CallRecord> _calls = new();
    private readonly Dictionary<string, System.Func<object?[], object?>> _handlers = new();

    public IReadOnlyList<CallRecord> Calls => _calls;

    public IEnumerable<string> CallNames => _calls.Select(c => c.Member);

    public int CountOf(string member) => _calls.Count(c => c.Member == member);

    public bool WasCalled(string member) => _calls.Any(c => c.Member == member);

    public CallRecord? Last(string member) => _calls.LastOrDefault(c => c.Member == member);

    /// <summary>Register a handler for a member (method or property getter) by name.</summary>
    public void On(string member, System.Func<object?[], object?> handler) => _handlers[member] = handler;

    public void On(string member, object? returnValue) => _handlers[member] = _ => returnValue;

    protected override object? Invoke(MethodInfo? targetMethod, object?[]? args)
    {
        if (targetMethod == null)
            return null;

        string name = NormalizeName(targetMethod.Name);
        args ??= System.Array.Empty<object?>();
        _calls.Add(new CallRecord { Member = name, Args = args });

        if ((_handlers.TryGetValue(targetMethod.Name, out var handler) ||
             _handlers.TryGetValue(name, out handler)) && handler != null)
        {
            return handler(args);
        }

        return DefaultFor(targetMethod.ReturnType);
    }

    private static string NormalizeName(string methodName)
    {
        // Property getters/setters arrive as get_X / set_X.
        if (methodName.StartsWith("get_") || methodName.StartsWith("set_"))
            return methodName.Substring(4);
        return methodName;
    }

    private static object? DefaultFor(System.Type t)
    {
        if (t == typeof(void)) return null;
        if (t == typeof(Task)) return Task.CompletedTask;
        if (t.IsGenericType && t.GetGenericTypeDefinition() == typeof(Task<>))
        {
            var inner = t.GetGenericArguments()[0];
            object? innerDefault = inner.IsValueType ? System.Activator.CreateInstance(inner) : null;
            var fromResult = typeof(Task).GetMethod(nameof(Task.FromResult))!.MakeGenericMethod(inner);
            return fromResult.Invoke(null, new[] { innerDefault });
        }
        return t.IsValueType ? System.Activator.CreateInstance(t) : null;
    }
}

/// <summary>Factory helpers for creating recording fakes.</summary>
public static class Fake
{
    public static (T Proxy, FakeProxy Recorder) Of<T>() where T : class
    {
        var proxy = DispatchProxy.Create<T, FakeProxy>();
        var recorder = (FakeProxy)(object)proxy;
        return ((T)(object)proxy, recorder);
    }
}
