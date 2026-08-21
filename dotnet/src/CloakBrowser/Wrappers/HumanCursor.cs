using System.Runtime.InteropServices;
using CloakBrowser.Human;
using Microsoft.Playwright;

namespace CloakBrowser.Wrappers;

/// <summary>
/// Per-page shared humanize state: the virtual cursor position, the raw mouse /
/// keyboard adapters, and the CDP typing stealth path. A single instance is shared
/// by a <see cref="HumanizedPage"/>, its <see cref="HumanizedMouse"/>,
/// <see cref="HumanizedKeyboard"/>, and every <see cref="HumanizedLocator"/> it
/// produces, so cursor motion is continuous across them (no jumps).
///
/// This mirrors the cursor/stealth bookkeeping inside <see cref="HumanPage"/>, exposed
/// in a form the wrappers can share.
/// </summary>
internal sealed class HumanCursor
{
    private static readonly bool IsMac = RuntimeInformation.IsOSPlatform(OSPlatform.OSX);
    private static readonly string SelectAll = IsMac ? "Meta+a" : "Control+a";

    private readonly IPage _page;
    private readonly IRawMouse _rawMouse;
    private readonly IRawKeyboard _rawKeyboard;
    private readonly IRawEvaluator _evaluator;

    private IsolatedWorld? _stealth;
    private IRawCdpSession? _cdpSession;
    private bool _stealthInitialized;
    private bool _initialized;

    public double X { get; private set; }
    public double Y { get; private set; }
    public IRawMouse RawMouse => _rawMouse;
    internal IPage Page => _page;

    public HumanCursor(IPage page)
    {
        _page = page;
        _rawMouse = new PlaywrightRawMouse(page.Mouse);
        _rawKeyboard = new PlaywrightRawKeyboard(page.Keyboard);
        _evaluator = new PlaywrightEvaluator(page);
    }

    public void Set(double x, double y) { X = x; Y = y; }

    public async Task InitStealthAsync()
    {
        if (_stealthInitialized) return;
        _stealthInitialized = true;
        try
        {
            _stealth = new IsolatedWorld(_page);
            var session = await _stealth.GetCdpSessionAsync().ConfigureAwait(false);
            _cdpSession = new PlaywrightCdpSession(session);
        }
        catch (System.Exception)
        {
            _stealth = null;
            _cdpSession = null;
            CloakLog.Debug("Could not create CDP session - stealth features disabled");
        }
    }

    public void InvalidateStealth() => _stealth?.Invalidate();

    /// <summary>The isolated world for stealth DOM reads, initializing it on first use.
    /// Returns null when the CDP session could not be created.</summary>
    internal async Task<IsolatedWorld?> GetStealthAsync()
    {
        if (!_stealthInitialized)
            await InitStealthAsync().ConfigureAwait(false);
        return _stealth;
    }

    public async Task EnsureInitializedAsync(HumanConfig cfg)
    {
        if (_initialized) return;
        X = HumanRandom.Rand(cfg.InitialCursorX.Min, cfg.InitialCursorX.Max);
        Y = HumanRandom.Rand(cfg.InitialCursorY.Min, cfg.InitialCursorY.Max);
        try
        {
            await _rawMouse.MoveAsync(X, Y).ConfigureAwait(false);
            _initialized = true;
        }
        catch (System.Exception) { /* viewport may not be ready yet */ }
    }

    public Task RawMouseDownAsync(int clickCount = 1) =>
        _page.Mouse.DownAsync(new MouseDownOptions { ClickCount = clickCount });

    public Task RawMouseUpAsync(int clickCount = 1) =>
        _page.Mouse.UpAsync(new MouseUpOptions { ClickCount = clickCount });

    public Task SelectAllAsync() => _page.Keyboard.PressAsync(SelectAll);

    public Task PressAsync(string key, float? delay = null) =>
        HumanKeyboard.PressAsync(_page.Keyboard, key, delay);

    public Task HumanTypeAsync(string text, HumanConfig cfg) =>
        HumanKeyboard.HumanTypeAsync(_evaluator, _rawKeyboard, text, cfg, _cdpSession);
}
