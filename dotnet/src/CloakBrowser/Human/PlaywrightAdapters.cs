using System.Text.Json.Nodes;
using Microsoft.Playwright;

namespace CloakBrowser.Human;

/// <summary>Adapts Playwright's <see cref="IMouse"/> to <see cref="IRawMouse"/>.</summary>
internal sealed class PlaywrightRawMouse : IRawMouse
{
    private readonly IMouse _mouse;
    public PlaywrightRawMouse(IMouse mouse) => _mouse = mouse;

    public Task MoveAsync(double x, double y) => _mouse.MoveAsync((float)x, (float)y);
    public Task DownAsync() => _mouse.DownAsync();
    public Task UpAsync() => _mouse.UpAsync();
    public Task WheelAsync(double deltaX, double deltaY) => _mouse.WheelAsync((float)deltaX, (float)deltaY);
}

/// <summary>Adapts Playwright's <see cref="IKeyboard"/> to <see cref="IRawKeyboard"/>.</summary>
internal sealed class PlaywrightRawKeyboard : IRawKeyboard
{
    private readonly IKeyboard _keyboard;
    public PlaywrightRawKeyboard(IKeyboard keyboard) => _keyboard = keyboard;

    public Task DownAsync(string key) => _keyboard.DownAsync(key);
    public Task UpAsync(string key) => _keyboard.UpAsync(key);
    public Task TypeAsync(string text) => _keyboard.TypeAsync(text);
    public Task InsertTextAsync(string text) => _keyboard.InsertTextAsync(text);
}

/// <summary>Adapts a Playwright <see cref="ICDPSession"/> to <see cref="IRawCdpSession"/>.</summary>
internal sealed class PlaywrightCdpSession : IRawCdpSession
{
    private readonly ICDPSession _session;
    public PlaywrightCdpSession(ICDPSession session) => _session = session;

    public async Task SendAsync(string method, JsonObject? args = null)
    {
        if (args == null)
        {
            await _session.SendAsync(method).ConfigureAwait(false);
            return;
        }
        var dict = new Dictionary<string, object>();
        foreach (var kv in args)
        {
            if (kv.Value is JsonValue jv)
            {
                if (jv.TryGetValue<int>(out var i)) dict[kv.Key] = i;
                else if (jv.TryGetValue<double>(out var d)) dict[kv.Key] = d;
                else if (jv.TryGetValue<bool>(out var b)) dict[kv.Key] = b;
                else dict[kv.Key] = jv.ToString();
            }
            else if (kv.Value != null)
            {
                dict[kv.Key] = kv.Value;
            }
        }
        await _session.SendAsync(method, dict).ConfigureAwait(false);
    }
}

/// <summary>Adapts a Playwright <see cref="IPage"/> to <see cref="IRawEvaluator"/> (fallback shift-symbol path).</summary>
internal sealed class PlaywrightEvaluator : IRawEvaluator
{
    private readonly IPage _page;
    public PlaywrightEvaluator(IPage page) => _page = page;

    public async Task EvaluateAsync(string expression, object? arg)
    {
        await _page.EvaluateAsync(expression, arg).ConfigureAwait(false);
    }
}

/// <summary>Adapts a Playwright <see cref="IPage"/> to <see cref="IRawScrollPage"/>.</summary>
internal sealed class PlaywrightScrollPage : IRawScrollPage
{
    private readonly IPage _page;
    public PlaywrightScrollPage(IPage page) => _page = page;

    public (int Width, int Height)? ViewportSize
    {
        get
        {
            var vs = _page.ViewportSize;
            return vs == null ? null : (vs.Width, vs.Height);
        }
    }

    public async Task<(int Width, int Height)?> GetLiveWindowSizeAsync()
    {
        try
        {
            var dims = await _page.EvaluateAsync<WindowDims>(
                "() => ({ width: window.innerWidth, height: window.innerHeight })")
                .ConfigureAwait(false);
            if (dims.Width <= 0 || dims.Height <= 0)
                return null;
            return (dims.Width, dims.Height);
        }
        catch (System.Exception)
        {
            return null;
        }
    }

    private struct WindowDims
    {
        public int Width { get; set; }
        public int Height { get; set; }
    }
}
