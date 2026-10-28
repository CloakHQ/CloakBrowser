using System.Reflection;
using System.Runtime.ExceptionServices;
using CloakBrowser.Human;
using CloakBrowser.Wrappers;
using Microsoft.Playwright;

namespace CloakBrowser;

/// <summary>
/// A launched stealth browser. Owns the underlying Playwright instance and disposes
/// it on <see cref="CloseAsync"/>. Use <see cref="Browser"/> for the raw Playwright API.
/// </summary>
public sealed class CloakBrowserHandle : IAsyncDisposable
{
    private readonly IPlaywright _playwright;
    private readonly bool _humanize;
    private readonly HumanConfig? _humanCfg;
    private readonly IBrowser _rawBrowser;
    private readonly bool _headless;
    private readonly bool _headlessNoViewport;
    private readonly string? _denialPath;

    /// <summary>
    /// The Playwright browser. When humanize is enabled this is a transparent
    /// humanizing wrapper: every page/context it produces uses human-like mouse,
    /// keyboard, and scrolling automatically while exposing the full standard
    /// <see cref="IBrowser"/> API. Use <see cref="RawBrowser"/> for the un-wrapped
    /// browser.
    /// </summary>
    public IBrowser Browser { get; }

    /// <summary>The original, un-humanized Playwright browser (escape hatch).</summary>
    public IBrowser RawBrowser => _rawBrowser;

    /// <summary>The owning Playwright instance (used internally to transfer ownership to a context handle).</summary>
    internal IPlaywright PlaywrightInstance => _playwright;

    /// <summary>The per-launch denial-file path (used internally to guard a context handle's pages too).</summary>
    internal string? DenialPath => _denialPath;

    internal CloakBrowserHandle(IPlaywright playwright, IBrowser browser, bool humanize, HumanConfig? humanCfg,
        bool headless = true, bool headlessNoViewport = false, string? denialPath = null)
    {
        _playwright = playwright;
        _rawBrowser = browser;
        _humanize = humanize;
        _humanCfg = humanCfg;
        _headless = headless;
        _headlessNoViewport = headlessNoViewport;
        _denialPath = denialPath;
        // Wrap the whole browser so the entire object graph (contexts, pages, mice,
        // keyboards, locators, frames) is humanized transparently. The wrapper is
        // headless-aware so the headed no-viewport default also applies when pages are
        // created through the humanized browser (parity with Python's _default_no_viewport,
        // which patches the raw browser so the default holds on every path).
        var visible = humanize
            ? Wrappers.Humanize.Browser(browser, humanCfg ?? new HumanConfig(), headless, headlessNoViewport)
            : browser;
        // Then wrap in the license guard so a post-handshake denial surfaces on the first
        // call through any page/context this browser produces (see LicenseGuard).
        Browser = (IBrowser)LicenseGuard.Wrap(visible, denialPath);
    }

    /// <summary>
    /// On headed launches, default a page/context that the caller didn't give an explicit
    /// viewport to <c>NoViewport</c> so it tracks the real OS window. Delegates to the
    /// shared <see cref="ViewportDefaults"/> (the single source of truth shared with the
    /// humanize wrapper). Port of Python <c>_default_no_viewport</c>.
    /// </summary>
    private BrowserNewPageOptions ApplyDefaultNoViewport(BrowserNewPageOptions? options) =>
        ViewportDefaults.ApplyHeadedNoViewport(options, _headless, _headlessNoViewport);

    private BrowserNewContextOptions ApplyDefaultNoViewport(BrowserNewContextOptions? options) =>
        ViewportDefaults.ApplyHeadedNoViewport(options, _headless, _headlessNoViewport);

    /// <summary>
    /// Create a new browser context. On headed launches without an explicit viewport,
    /// defaults to <c>NoViewport</c> so the page tracks the real window (see
    /// <see cref="NewPageAsync"/>).
    /// </summary>
    public Task<IBrowserContext> NewContextAsync(BrowserNewContextOptions? options = null) =>
        Browser.NewContextAsync(ApplyDefaultNoViewport(options)); // Browser is license-guarded

    /// <summary>
    /// Create a new page. When humanize is enabled the returned <see cref="IPage"/> is a
    /// transparent humanizing wrapper - your standard Playwright calls
    /// (<c>page.ClickAsync</c>, <c>page.FillAsync</c>, <c>page.Mouse.MoveAsync</c>, ...)
    /// are automatically humanized.
    /// </summary>
    public Task<IPage> NewPageAsync(BrowserNewPageOptions? options = null) =>
        Browser.NewPageAsync(ApplyDefaultNoViewport(options)); // Browser is license-guarded

    /// <summary>
    /// Create a new page wrapped in an explicit <see cref="HumanPage"/> with this
    /// browser's humanize config. Prefer <see cref="NewPageAsync"/> for transparent
    /// humanization; this is the explicit-wrapper API kept for advanced control.
    /// </summary>
    public async Task<HumanPage> NewHumanPageAsync(BrowserNewPageOptions? options = null)
    {
        // Use the raw browser so we don't build a HumanPage over an already-wrapped page.
        var page = await _rawBrowser.NewPageAsync(ApplyDefaultNoViewport(options)).ConfigureAwait(false);
        return await HumanPage.CreateAsync(page, _humanCfg ?? new HumanConfig()).ConfigureAwait(false);
    }

    /// <summary>Whether the humanize layer is enabled for this browser.</summary>
    public bool HumanizeEnabled => _humanize;

    /// <summary>Close the browser and stop the underlying Playwright instance.</summary>
    public async Task CloseAsync()
    {
        try { await _rawBrowser.CloseAsync().ConfigureAwait(false); }
        finally { _playwright.Dispose(); }
    }

    /// <inheritdoc/>
    public async ValueTask DisposeAsync() => await CloseAsync().ConfigureAwait(false);
}

/// <summary>
/// Converts a post-handshake license denial into a clear <see cref="CloakBrowserLicenseError"/>.
/// A denial that lands after Playwright connected kills the browser without a launch
/// failure; the user's next call would throw a bare TargetClosedError. We check the denial
/// file the binary wrote — on error AND on success (the binary writes the file the instant
/// it's over cap but keeps serving blank responses for ~1s before it exits, so a fast flow
/// that never throws must still surface it) — and re-throw as a license error when a code is
/// present; otherwise the original result/exception passes through, so a genuine crash is
/// never mislabelled. A page/context handed back is wrapped so its own later calls are
/// guarded too. Mirrors Python _install_license_guard / JS installLicenseGuard.
/// </summary>
internal static class LicenseGuard
{
    /// <summary>Read the denial file and map it to a license error, or null.</summary>
    internal static CloakBrowserLicenseError? DenialError(string denialPath)
    {
        var code = License.ReadDenialFile(denialPath);
        return code.HasValue ? License.LicenseErrorForCode(code.Value) : null;
    }

    /// <summary>
    /// Run a factory op, surface a denial (whether it threw or succeeded), and wrap the
    /// returned page/context so its later calls are guarded too. When there is no denial
    /// path (keyless), it is a pass-through.
    /// </summary>
    public static async Task<T> GuardAsync<T>(Func<Task<T>> op, string? denialPath) where T : class
    {
        if (denialPath == null) return await op().ConfigureAwait(false);
        T result;
        try
        {
            result = await op().ConfigureAwait(false);
        }
        catch (Exception)
        {
            var lic = DenialError(denialPath);
            if (lic != null) throw lic;
            throw;
        }
        var licSuccess = DenialError(denialPath);
        if (licSuccess != null) throw licSuccess;
        return (T)Wrap(result, denialPath);
    }

    /// <summary>
    /// Wrap a page/context in a transparent proxy that surfaces a post-handshake denial on
    /// the first failing OR succeeding call, and deep-wraps any page/context it returns.
    /// Only <see cref="IPage"/> and <see cref="IBrowserContext"/> are wrapped (the handles
    /// the user drives); anything else is returned unchanged. Null denial path = no-op.
    /// </summary>
    public static object Wrap(object target, string? denialPath)
    {
        if (denialPath == null) return target;
        if (target is IGuardedProxy) return target; // already guarded — don't nest proxies
        return target switch
        {
            IPage p => WrapAs<IPage>(p, denialPath),
            IBrowserContext c => WrapAs<IBrowserContext>(c, denialPath),
            IBrowser b => WrapAs<IBrowser>(b, denialPath),
            _ => target,
        };
    }

    /// <summary>
    /// Peel every CloakBrowser wrapper — the license-guard <see cref="DispatchProxy"/> first,
    /// then the humanize decorator — off a page/frame/element handle to recover the raw
    /// Playwright object. A few Playwright methods (notably
    /// <see cref="IBrowserContext.NewCDPSessionAsync(IPage)"/>) internally down-cast the
    /// handle they are given to Playwright's concrete type, which throws on any wrapper; those
    /// must receive the unwrapped handle. Non-wrapped objects are returned unchanged.
    /// </summary>
    public static object Unwrap(object handle)
    {
        var current = handle;
        while (true)
        {
            switch (current)
            {
                case IGuardedProxy g: current = g.GuardTarget; break;
                case HumanizedPage p: current = p.Original; break;
                case HumanizedFrame f: current = f.Original; break;
                case HumanizedLocator l: current = l.Original; break;
                case HumanizedElementHandle e: current = e.Original; break;
                case HumanizedBrowserContext c: current = c.Original; break;
                case HumanizedBrowser b: current = b.Original; break;
                default: return current;
            }
        }
    }

    private static T WrapAs<T>(T target, string denialPath) where T : class
    {
        var proxy = DispatchProxy.Create<T, LicenseGuardProxy<T>>();
        ((LicenseGuardProxy<T>)(object)proxy!).Init(target, denialPath);
        return proxy;
    }
}

/// <summary>
/// A <see cref="DispatchProxy"/> that guards every method of a wrapped page/context/browser.
/// C# cannot monkey-patch methods like the Python/JS wrappers, so a runtime proxy is how the
/// returned handle's own methods (e.g. <c>page.GotoAsync</c>) get guarded. Property and event
/// accessors are forwarded untouched — they are driven internally by Playwright and don't
/// represent a user browser op that needs license surfacing (mirrors the Python/JS skip of
/// getters + the EventEmitter surface). <c>get_Pages</c> is special-cased so a persistent
/// context's already-open pages are guarded too.
/// </summary>
internal interface IGuardedProxy
{
    /// <summary>The object this proxy forwards to (see <see cref="LicenseGuard.Unwrap"/>).</summary>
    object GuardTarget { get; }
}

internal class LicenseGuardProxy<T> : DispatchProxy, IGuardedProxy where T : class
{
    private T _target = null!;
    private string _denialPath = null!;

    // One guard wrapper per underlying context, so page.Context is a stable instance.
    private readonly System.Runtime.CompilerServices.ConditionalWeakTable<IBrowserContext, object> _contextGuardCache = new();

    object IGuardedProxy.GuardTarget => _target;

    internal void Init(T target, string denialPath)
    {
        _target = target;
        _denialPath = denialPath;
    }

    protected override object? Invoke(MethodInfo? targetMethod, object?[]? args)
    {
        if (targetMethod == null) return null;

        if (targetMethod.IsSpecialName)
        {
            var value = Forward(targetMethod, args);
            // Guard the pages a persistent context hands back (context.Pages[0]).
            if (targetMethod.Name == "get_Pages" && value is IReadOnlyList<IPage> pages)
                return pages.Select(p => (IPage)LicenseGuard.Wrap(p, _denialPath)).ToList();
            // Guard the context a page hands back (page.Context) so calls made through it —
            // notably NewCDPSessionAsync, which unwraps its page/frame argument — stay guarded.
            // Memoized per underlying context so repeated page.Context accesses return the
            // same instance (reference identity parity with raw Playwright).
            if (targetMethod.Name == "get_Context" && value is IBrowserContext ctx)
                return _contextGuardCache.GetValue(ctx, c => LicenseGuard.Wrap((IBrowserContext)c, _denialPath));
            return value;
        }

        var returnType = targetMethod.ReturnType;

        if (returnType == typeof(Task))
            return GuardTask(targetMethod, args);

        if (returnType.IsGenericType && returnType.GetGenericTypeDefinition() == typeof(Task<>))
        {
            var m = typeof(LicenseGuardProxy<T>)
                .GetMethod(nameof(GuardTaskResult), BindingFlags.NonPublic | BindingFlags.Instance)!
                .MakeGenericMethod(returnType.GetGenericArguments()[0]);
            return m.Invoke(this, new object?[] { targetMethod, args });
        }

        // Synchronous method.
        object? result;
        try { result = Forward(targetMethod, args); }
        catch (Exception)
        {
            var lic = LicenseGuard.DenialError(_denialPath);
            if (lic != null) throw lic;
            throw;
        }
        var licSuccess = LicenseGuard.DenialError(_denialPath);
        if (licSuccess != null) throw licSuccess;
        return LicenseGuard.Wrap(result!, _denialPath);
    }

    /// <summary>Invoke the real method, unwrapping the reflection exception wrapper so the
    /// caller sees the genuine Playwright exception.</summary>
    private object? Forward(MethodInfo method, object?[]? args)
    {
        try { return method.Invoke(_target, UnwrapArgs(args)); }
        catch (TargetInvocationException tie) when (tie.InnerException != null)
        {
            ExceptionDispatchInfo.Capture(tie.InnerException).Throw();
            throw; // unreachable
        }
    }

    /// <summary>
    /// Unwrap any page/frame/element-handle arguments back to their raw Playwright objects
    /// before the real method runs. Playwright methods that take a handle (e.g.
    /// NewCDPSessionAsync) down-cast it to a concrete type and throw on a wrapper. Returns the
    /// original array untouched when nothing needs unwrapping (the common case).
    /// </summary>
    private static object?[]? UnwrapArgs(object?[]? args)
    {
        if (args == null) return null;
        object?[]? copy = null;
        for (int i = 0; i < args.Length; i++)
        {
            if (args[i] is IPage or IFrame or IElementHandle)
            {
                var unwrapped = LicenseGuard.Unwrap(args[i]!);
                if (!ReferenceEquals(unwrapped, args[i]))
                    (copy ??= (object?[])args.Clone())[i] = unwrapped;
            }
        }
        return copy ?? args;
    }

    private async Task GuardTask(MethodInfo method, object?[]? args)
    {
        try { await ((Task)Forward(method, args)!).ConfigureAwait(false); }
        catch (Exception)
        {
            var lic = LicenseGuard.DenialError(_denialPath);
            if (lic != null) throw lic;
            throw;
        }
        var licSuccess = LicenseGuard.DenialError(_denialPath);
        if (licSuccess != null) throw licSuccess;
    }

    private async Task<TResult> GuardTaskResult<TResult>(MethodInfo method, object?[]? args)
    {
        TResult result;
        try { result = await ((Task<TResult>)Forward(method, args)!).ConfigureAwait(false); }
        catch (Exception)
        {
            var lic = LicenseGuard.DenialError(_denialPath);
            if (lic != null) throw lic;
            throw;
        }
        var licSuccess = LicenseGuard.DenialError(_denialPath);
        if (licSuccess != null) throw licSuccess;
        return result is not null ? (TResult)LicenseGuard.Wrap(result, _denialPath) : result;
    }
}

/// <summary>
/// A launched stealth browser context. Owns the underlying Playwright instance (and,
/// for non-persistent contexts, the browser) and cleans them up on <see cref="CloseAsync"/>.
/// </summary>
public sealed class CloakContextHandle : IAsyncDisposable
{
    private readonly IPlaywright _playwright;
    private readonly IBrowser? _browser; // null for persistent contexts
    private readonly bool _humanize;
    private readonly HumanConfig? _humanCfg;
    private readonly IBrowserContext _rawContext;
    private readonly string? _denialPath;

    /// <summary>
    /// The Playwright browser context. When humanize is enabled this is a transparent
    /// humanizing wrapper: every page it produces uses human-like input automatically
    /// while exposing the full standard <see cref="IBrowserContext"/> API. Use
    /// <see cref="RawContext"/> for the un-wrapped context.
    /// </summary>
    public IBrowserContext Context { get; }

    /// <summary>The original, un-humanized Playwright context (escape hatch).</summary>
    public IBrowserContext RawContext => _rawContext;

    internal CloakContextHandle(IPlaywright playwright, IBrowser? browser, IBrowserContext context,
        bool humanize, HumanConfig? humanCfg, string? denialPath = null)
    {
        _playwright = playwright;
        _browser = browser;
        _rawContext = context;
        _humanize = humanize;
        _humanCfg = humanCfg;
        _denialPath = denialPath;
        var visible = humanize ? Wrappers.Humanize.Context(context, humanCfg ?? new HumanConfig()) : context;
        // License-guard the context so a post-handshake denial surfaces on the first call
        // through NewPageAsync OR an already-open page (Context.Pages[0]) — see LicenseGuard.
        Context = (IBrowserContext)LicenseGuard.Wrap(visible, denialPath);
    }

    /// <summary>
    /// Create a new page. When humanize is enabled the returned <see cref="IPage"/> is a
    /// transparent humanizing wrapper - standard Playwright calls are auto-humanized.
    /// </summary>
    public Task<IPage> NewPageAsync() =>
        Context.NewPageAsync(); // Context is license-guarded

    /// <summary>
    /// Create a new page wrapped in an explicit <see cref="HumanPage"/> with this
    /// context's humanize config. Prefer <see cref="NewPageAsync"/> for transparent
    /// humanization.
    /// </summary>
    public async Task<HumanPage> NewHumanPageAsync()
    {
        var page = await _rawContext.NewPageAsync().ConfigureAwait(false);
        return await HumanPage.CreateAsync(page, _humanCfg ?? new HumanConfig()).ConfigureAwait(false);
    }

    /// <summary>Whether the humanize layer is enabled for this context.</summary>
    public bool HumanizeEnabled => _humanize;

    /// <summary>Close the context (and browser, if owned) and stop Playwright.</summary>
    public async Task CloseAsync()
    {
        try
        {
            await _rawContext.CloseAsync().ConfigureAwait(false);
            if (_browser != null)
                await _browser.CloseAsync().ConfigureAwait(false);
        }
        finally
        {
            _playwright.Dispose();
        }
    }

    /// <inheritdoc/>
    public async ValueTask DisposeAsync() => await CloseAsync().ConfigureAwait(false);
}
