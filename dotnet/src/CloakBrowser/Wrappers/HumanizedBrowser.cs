using CloakBrowser.Human;
using Microsoft.Playwright;

namespace CloakBrowser.Wrappers;

/// <summary>
/// Transparent humanizing decorator over Playwright's <see cref="IBrowser"/>.
///
/// Intercepted: <c>NewPageAsync</c> / <c>NewContextAsync</c> / <c>Contexts</c> return
/// humanized pages and contexts so the entire object graph reachable from the browser
/// is humanized. Everything else is delegated to the inner browser by the generator.
/// </summary>
[GenerateInterfaceDelegation(typeof(IBrowser))]
public sealed partial class HumanizedBrowser : IBrowser
{
    private readonly IBrowser _inner;
    private readonly HumanConfig _cfg;
    private readonly bool _defaultNoViewport;

    internal HumanizedBrowser(IBrowser inner, HumanConfig cfg, bool defaultNoViewport = false)
    {
        _inner = inner;
        _cfg = cfg;
        _defaultNoViewport = defaultNoViewport;
    }

    private BrowserNewPageOptions? Viewport(BrowserNewPageOptions? o) =>
        _defaultNoViewport ? ViewportDefaults.ApplyNoViewport(o) : o;

    private BrowserNewContextOptions? Viewport(BrowserNewContextOptions? o) =>
        _defaultNoViewport ? ViewportDefaults.ApplyNoViewport(o) : o;

    /// <summary>The original, un-humanized Playwright browser (escape hatch).</summary>
    public IBrowser Original => _inner;

    /// <summary>Alias of <see cref="Original"/>.</summary>
    public IBrowser Inner => _inner;

    public async Task<IPage> NewPageAsync(BrowserNewPageOptions? options = null) =>
        await Humanize.WrapPageAsync(
            await _inner.NewPageAsync(Viewport(options)).ConfigureAwait(false),
            _cfg).ConfigureAwait(false);

    public async Task<IBrowserContext> NewContextAsync(BrowserNewContextOptions? options = null) =>
        Humanize.Context(
            await _inner.NewContextAsync(Viewport(options)).ConfigureAwait(false),
            _cfg);

    public IReadOnlyList<IBrowserContext> Contexts =>
        _inner.Contexts.Select(c => Humanize.Context(c, _cfg)).ToList();
}
