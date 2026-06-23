using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Playwright;

namespace CloakBrowser.Human;

/// <summary>
/// Manages a CDP isolated execution context for DOM reads.
/// Direct port of Python <c>_AsyncIsolatedWorld</c> (cloakbrowser/human/__init__.py).
///
/// Produces clean <c>Error.stack</c> traces (no <c>eval at evaluate</c> frames)
/// and is invisible to <c>querySelector</c> monkey-patches in the main world.
/// The context ID is invalidated on navigation and auto-recreated on next call.
/// </summary>
public sealed class IsolatedWorld
{
    private readonly IPage _page;
    private ICDPSession? _cdp;
    private int? _contextId;

    public IsolatedWorld(IPage page)
    {
        _page = page;
    }

    private async Task<ICDPSession> EnsureCdpAsync()
    {
        _cdp ??= await _page.Context.NewCDPSessionAsync(_page).ConfigureAwait(false);
        return _cdp;
    }

    private async Task<int> CreateWorldAsync()
    {
        var cdp = await EnsureCdpAsync().ConfigureAwait(false);
        var tree = await cdp.SendAsync("Page.getFrameTree").ConfigureAwait(false);
        string frameId = tree.Value
            .GetProperty("frameTree")
            .GetProperty("frame")
            .GetProperty("id")
            .GetString()!;
        var result = await cdp.SendAsync("Page.createIsolatedWorld", new Dictionary<string, object>
        {
            ["frameId"] = frameId,
            ["worldName"] = "",
            ["grantUniveralAccess"] = true, // (intentional typo preserved from CDP/source)
        }).ConfigureAwait(false);
        _contextId = result.Value.GetProperty("executionContextId").GetInt32();
        return _contextId.Value;
    }

    /// <summary>Evaluate JS in the isolated world. Auto-recreates on a stale context. Returns null on failure.</summary>
    public async Task<JsonElement?> EvaluateAsync(string expression)
    {
        if (_contextId == null)
            await CreateWorldAsync().ConfigureAwait(false);

        for (int attempt = 0; attempt < 2; attempt++)
        {
            try
            {
                var result = await _cdp!.SendAsync("Runtime.evaluate", new Dictionary<string, object>
                {
                    ["expression"] = expression,
                    ["contextId"] = _contextId!.Value,
                    ["returnByValue"] = true,
                }).ConfigureAwait(false);

                if (result.Value.TryGetProperty("exceptionDetails", out _))
                {
                    if (attempt == 0)
                    {
                        await CreateWorldAsync().ConfigureAwait(false);
                        continue;
                    }
                    return null;
                }

                if (result.Value.TryGetProperty("result", out var r) &&
                    r.TryGetProperty("value", out var v))
                {
                    return v;
                }
                return null;
            }
            catch (Exception)
            {
                if (attempt == 0)
                {
                    _contextId = null;
                    try { await CreateWorldAsync().ConfigureAwait(false); }
                    catch (Exception) { return null; }
                    continue;
                }
                return null;
            }
        }
        return null;
    }

    /// <summary>Evaluate and coerce the result to a bool (false on null/failure).</summary>
    public async Task<bool> EvaluateBoolAsync(string expression)
    {
        var v = await EvaluateAsync(expression).ConfigureAwait(false);
        if (v == null) return false;
        return v.Value.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            JsonValueKind.Number => v.Value.GetDouble() != 0,
            JsonValueKind.String => !string.IsNullOrEmpty(v.Value.GetString()),
            _ => false,
        };
    }

    /// <summary>Mark the context as stale - call after navigation.</summary>
    public void Invalidate() => _contextId = null;

    /// <summary>Get the underlying CDP session (reused for <c>Input.dispatchKeyEvent</c>).</summary>
    public Task<ICDPSession> GetCdpSessionAsync() => EnsureCdpAsync();

    /// <summary>JSON-encode a string for safe embedding in a JS expression (like Python's json.dumps).</summary>
    public static string JsonEncode(string s) => JsonSerializer.Serialize(s);
}
