using System.Text.RegularExpressions;
using CloakBrowser.Human;
using Microsoft.Playwright;

namespace CloakBrowser.Wrappers;

/// <summary>
/// Transparent humanizing decorator over Playwright's <see cref="IPage"/>.
///
/// Selector-based interaction methods (Click/Fill/Type/Hover/Press/Tap/Check/...) are
/// routed through the unified <see cref="HumanEngine"/>. <c>Mouse</c> and
/// <c>Keyboard</c> return humanized wrappers; <c>Locator</c>/<c>GetBy*</c>/frames return
/// re-wrapped objects so the whole chain stays humanized. Everything else is delegated
/// to the inner page by the source generator.
/// </summary>
[GenerateInterfaceDelegation(typeof(IPage))]
public sealed partial class HumanizedPage : IPage
{
    private readonly IPage _inner;
    private readonly HumanCursor _cursor;
    private readonly HumanConfig _cfg;
    private readonly HumanEngine _engine;
    private readonly HumanizedMouse _mouse;
    private readonly HumanizedKeyboard _keyboard;
    private readonly object _frameEventLock = new();
    private readonly Dictionary<EventHandler<IFrame>, Stack<EventHandler<IFrame>>> _frameAttachedHandlers = new();
    private readonly Dictionary<EventHandler<IFrame>, Stack<EventHandler<IFrame>>> _frameDetachedHandlers = new();
    private readonly Dictionary<EventHandler<IFrame>, Stack<EventHandler<IFrame>>> _frameNavigatedHandlers = new();

    internal HumanizedPage(IPage inner, HumanCursor cursor, HumanConfig cfg)
    {
        _inner = inner;
        _cursor = cursor;
        _cfg = cfg;
        _engine = cursor.EngineFor(cfg);
        _mouse = new HumanizedMouse(inner.Mouse, cursor, cfg);
        _keyboard = new HumanizedKeyboard(inner.Keyboard, cursor, cfg);

        // Isolated worlds are dropped per frame on navigation / detach by HumanWorld
        // itself, so click/form navigations never leave a stale document (#507).
    }

    /// <summary>The original, un-humanized Playwright page (escape hatch for raw speed).</summary>
    public IPage Original => _inner;

    /// <summary>Alias of <see cref="Original"/>.</summary>
    public IPage Inner => _inner;

    private static ActOpts Opt(object? options) => ActOpts.From(options);
    private Target T(string selector, object? options) =>
        new(_inner.MainFrame, selector, ActOpts.From(options).Strict);

    private ILocator Wrap(ILocator l) => Humanize.WrapLocator(l, _cursor, _cfg);
    private ILocator Wrap(ILocator l, string? selector) => Humanize.WrapLocator(l, _cursor, _cfg, selector);
    private IFrame Wrap(IFrame f) => Humanize.WrapFrame(f, _cursor, _cfg);

    private void AddFrameEventHandler(
        Dictionary<EventHandler<IFrame>, Stack<EventHandler<IFrame>>> handlersBySubscriber,
        EventHandler<IFrame> subscriber,
        Action<EventHandler<IFrame>> subscribe)
    {
        EventHandler<IFrame> wrapped = (_, frame) => subscriber(this, Wrap(frame));
        lock (_frameEventLock)
        {
            subscribe(wrapped);
            if (!handlersBySubscriber.TryGetValue(subscriber, out var handlers))
            {
                handlers = new Stack<EventHandler<IFrame>>();
                handlersBySubscriber[subscriber] = handlers;
            }
            handlers.Push(wrapped);
        }
    }

    private void RemoveFrameEventHandler(
        Dictionary<EventHandler<IFrame>, Stack<EventHandler<IFrame>>> handlersBySubscriber,
        EventHandler<IFrame> subscriber,
        Action<EventHandler<IFrame>> unsubscribe)
    {
        lock (_frameEventLock)
        {
            if (!handlersBySubscriber.TryGetValue(subscriber, out var handlers) || handlers.Count == 0)
                return;

            var wrapped = handlers.Peek();
            unsubscribe(wrapped);
            handlers.Pop();
            if (handlers.Count == 0)
                handlersBySubscriber.Remove(subscriber);
        }
    }

    // -----------------------------------------------------------------------
    // Humanized wrappers for nested objects
    // -----------------------------------------------------------------------

    public IMouse Mouse => _mouse;
    public IKeyboard Keyboard => _keyboard;

    // Re-wrap the owning context so pages/CDP sessions obtained via page.Context stay
    // humanized (the generator would otherwise forward the raw Playwright context).
    public IBrowserContext Context => Humanize.Context(_inner.Context, _cfg);

    // -----------------------------------------------------------------------
    // Humanized selector actions
    // -----------------------------------------------------------------------

    public Task ClickAsync(string selector, PageClickOptions? options = null) =>
        _engine.ClickAsync(T(selector, options), Opt(options), "Page.ClickAsync");

    public Task DblClickAsync(string selector, PageDblClickOptions? options = null) =>
        _engine.ClickAsync(T(selector, options), Opt(options), "Page.DblClickAsync", 2);

    public Task HoverAsync(string selector, PageHoverOptions? options = null) =>
        _engine.HoverAsync(T(selector, options), Opt(options), "Page.HoverAsync");

    public Task TapAsync(string selector, PageTapOptions? options = null) =>
        _engine.TapAsync(T(selector, options), Opt(options), "Page.TapAsync");

    public Task FillAsync(string selector, string value, PageFillOptions? options = null) =>
        _engine.FillAsync(T(selector, options), value, Opt(options), "Page.FillAsync");

    public Task TypeAsync(string selector, string text, PageTypeOptions? options = null) =>
        _engine.TypeAsync(T(selector, options), text, Opt(options), "Page.TypeAsync");

    public Task PressAsync(string selector, string key, PagePressOptions? options = null) =>
        _engine.PressAsync(T(selector, options), key, Opt(options), "Page.PressAsync");

    public Task CheckAsync(string selector, PageCheckOptions? options = null) =>
        _engine.SetCheckedAsync(T(selector, options), true, Opt(options), "Page.CheckAsync");

    public Task UncheckAsync(string selector, PageUncheckOptions? options = null) =>
        _engine.SetCheckedAsync(T(selector, options), false, Opt(options), "Page.UncheckAsync");

    public Task SetCheckedAsync(string selector, bool checkedState, PageSetCheckedOptions? options = null) =>
        _engine.SetCheckedAsync(T(selector, options), checkedState, Opt(options), "Page.SetCheckedAsync");

    public Task FocusAsync(string selector, PageFocusOptions? options = null) =>
        _engine.FocusAsync(T(selector, options), Opt(options), "Page.FocusAsync");

    public Task DragAndDropAsync(string source, string target, PageDragAndDropOptions? options = null) =>
        _engine.DragAsync(T(source, options), T(target, options), Opt(options), "Page.DragAndDropAsync");

    private Task<IReadOnlyList<string>> Select(string selector, SelectValues v, PageSelectOptionOptions? options) =>
        _engine.SelectOptionAsync(T(selector, options), v.Options, v.Handles, Opt(options), "Page.SelectOptionAsync");

    public Task<IReadOnlyList<string>> SelectOptionAsync(string selector, string values, PageSelectOptionOptions? options = null) =>
        Select(selector, SelectValues.Of(new[] { values }), options);
    public Task<IReadOnlyList<string>> SelectOptionAsync(string selector, IEnumerable<string> values, PageSelectOptionOptions? options = null) =>
        Select(selector, SelectValues.Of(values), options);
    public Task<IReadOnlyList<string>> SelectOptionAsync(string selector, IElementHandle values, PageSelectOptionOptions? options = null) =>
        Select(selector, SelectValues.Of(new[] { values }), options);
    public Task<IReadOnlyList<string>> SelectOptionAsync(string selector, IEnumerable<IElementHandle> values, PageSelectOptionOptions? options = null) =>
        Select(selector, SelectValues.Of(values), options);
    public Task<IReadOnlyList<string>> SelectOptionAsync(string selector, SelectOptionValue values, PageSelectOptionOptions? options = null) =>
        Select(selector, SelectValues.Of(new[] { values }), options);
    public Task<IReadOnlyList<string>> SelectOptionAsync(string selector, IEnumerable<SelectOptionValue> values, PageSelectOptionOptions? options = null) =>
        Select(selector, SelectValues.Of(values), options);

    private static IElementHandle Unwrap(IElementHandle h) => h is HumanizedElementHandle hh ? hh.Original : h;
    private static ILocator Unwrap(ILocator l) => l is HumanizedLocator hl ? hl.Original : l;

    // #549: Playwright down-casts ILocator args to concrete Locator; unwrap ours first.
    public Task AddLocatorHandlerAsync(ILocator locator, Func<Task> handler, PageAddLocatorHandlerOptions? options = null) =>
        _inner.AddLocatorHandlerAsync(Unwrap(locator), handler, options);

    // Re-wrap the callback locator so the user's handler stays humanized.
    public Task AddLocatorHandlerAsync(ILocator locator, Func<ILocator, Task> handler, PageAddLocatorHandlerOptions? options = null) =>
        _inner.AddLocatorHandlerAsync(Unwrap(locator), l => handler(Wrap(l)), options);

    public Task RemoveLocatorHandlerAsync(ILocator locator) =>
        _inner.RemoveLocatorHandlerAsync(Unwrap(locator));

    // #549: unwrap masked locators in place (rebuilding options would drop future fields).
    public Task<byte[]> ScreenshotAsync(PageScreenshotOptions? options = null)
    {
        if (options?.Mask != null)
            options.Mask = options.Mask.Select(Unwrap).ToList();
        return _inner.ScreenshotAsync(options);
    }

    // -----------------------------------------------------------------------
    // Locator-returning members - re-wrap.
    // -----------------------------------------------------------------------

    // Locator options can change which element Playwright resolves. Preserve raw
    // selector metadata only when it completely describes the locator semantics.
    public IFrameLocator FrameLocator(string selector) => Humanize.WrapFrameLocator(_inner.FrameLocator(selector), _cursor, _cfg);
    public ILocator Locator(string selector, PageLocatorOptions? options = null) =>
        Wrap(_inner.Locator(selector, options), options == null ? selector : null);
    public ILocator GetByAltText(string text, PageGetByAltTextOptions? options = null) => Wrap(_inner.GetByAltText(text, options));
    public ILocator GetByAltText(Regex text, PageGetByAltTextOptions? options = null) => Wrap(_inner.GetByAltText(text, options));
    public ILocator GetByLabel(string text, PageGetByLabelOptions? options = null) => Wrap(_inner.GetByLabel(text, options));
    public ILocator GetByLabel(Regex text, PageGetByLabelOptions? options = null) => Wrap(_inner.GetByLabel(text, options));
    public ILocator GetByPlaceholder(string text, PageGetByPlaceholderOptions? options = null) => Wrap(_inner.GetByPlaceholder(text, options));
    public ILocator GetByPlaceholder(Regex text, PageGetByPlaceholderOptions? options = null) => Wrap(_inner.GetByPlaceholder(text, options));
    public ILocator GetByRole(AriaRole role, PageGetByRoleOptions? options = null) => Wrap(_inner.GetByRole(role, options));
    public ILocator GetByTestId(string testId) => Wrap(_inner.GetByTestId(testId));
    public ILocator GetByTestId(Regex testId) => Wrap(_inner.GetByTestId(testId));
    public ILocator GetByText(string text, PageGetByTextOptions? options = null) => Wrap(_inner.GetByText(text, options));
    public ILocator GetByText(Regex text, PageGetByTextOptions? options = null) => Wrap(_inner.GetByText(text, options));
    public ILocator GetByTitle(string text, PageGetByTitleOptions? options = null) => Wrap(_inner.GetByTitle(text, options));
    public ILocator GetByTitle(Regex text, PageGetByTitleOptions? options = null) => Wrap(_inner.GetByTitle(text, options));

    // -----------------------------------------------------------------------
    // Frame-returning members - re-wrap.
    // -----------------------------------------------------------------------

    public IReadOnlyList<IFrame> Frames => Humanize.WrapFrames(_inner.Frames, _cursor, _cfg);
    public IFrame MainFrame => Wrap(_inner.MainFrame);

    // Generated event delegates would expose Playwright's raw frames. Adapt every
    // frame-event payload so dynamic, detached, and navigated frames stay wrapped.
    public event EventHandler<IFrame> FrameAttached
    {
        add => AddFrameEventHandler(_frameAttachedHandlers, value, handler => _inner.FrameAttached += handler);
        remove => RemoveFrameEventHandler(_frameAttachedHandlers, value, handler => _inner.FrameAttached -= handler);
    }

    public event EventHandler<IFrame> FrameDetached
    {
        add => AddFrameEventHandler(_frameDetachedHandlers, value, handler => _inner.FrameDetached += handler);
        remove => RemoveFrameEventHandler(_frameDetachedHandlers, value, handler => _inner.FrameDetached -= handler);
    }

    public event EventHandler<IFrame> FrameNavigated
    {
        add => AddFrameEventHandler(_frameNavigatedHandlers, value, handler => _inner.FrameNavigated += handler);
        remove => RemoveFrameEventHandler(_frameNavigatedHandlers, value, handler => _inner.FrameNavigated -= handler);
    }

    public IFrame? Frame(string name) { var f = _inner.Frame(name); return f == null ? null : Wrap(f); }
    public IFrame? FrameByUrl(string url) { var f = _inner.FrameByUrl(url); return f == null ? null : Wrap(f); }
    public IFrame? FrameByUrl(Regex url) { var f = _inner.FrameByUrl(url); return f == null ? null : Wrap(f); }
    public IFrame? FrameByUrl(System.Func<string, bool> url) { var f = _inner.FrameByUrl(url); return f == null ? null : Wrap(f); }

    // -----------------------------------------------------------------------
    // Handle-returning members - re-wrap so handle actions stay humanized.
    // -----------------------------------------------------------------------

    private IElementHandle? H(IElementHandle? h) => h == null ? null : Humanize.WrapElementHandle(h, _cursor, _cfg);

    public async Task<IElementHandle?> QuerySelectorAsync(string selector, PageQuerySelectorOptions? options = null) =>
        H(await _inner.QuerySelectorAsync(selector, options).ConfigureAwait(false));

    public async Task<IReadOnlyList<IElementHandle>> QuerySelectorAllAsync(string selector) =>
        Humanize.WrapHandles(await _inner.QuerySelectorAllAsync(selector).ConfigureAwait(false), _cursor, _cfg);

    public async Task<IElementHandle?> WaitForSelectorAsync(string selector, PageWaitForSelectorOptions? options = null) =>
        H(await _inner.WaitForSelectorAsync(selector, options).ConfigureAwait(false));
}
