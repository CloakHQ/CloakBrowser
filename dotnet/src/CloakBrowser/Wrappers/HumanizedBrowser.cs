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
    private readonly bool _headless;

    internal HumanizedBrowser(IBrowser inner, HumanConfig cfg, bool headless = true)
    {
        _inner = inner;
        _cfg = cfg;
        _headless = headless;
    }

    /// <summary>The original, un-humanized Playwright browser (escape hatch).</summary>
    public IBrowser Original => _inner;

    /// <summary>Alias of <see cref="Original"/>.</summary>
    public IBrowser Inner => _inner;

    public async Task<IPage> NewPageAsync(BrowserNewPageOptions? options = null) =>
        await Humanize.WrapPageAsync(
            await _inner.NewPageAsync(ViewportDefaults.ApplyHeadedNoViewport(options, _headless)).ConfigureAwait(false),
            _cfg).ConfigureAwait(false);

    public async Task<IBrowserContext> NewContextAsync(BrowserNewContextOptions? options = null) =>
        Humanize.Context(
            await _inner.NewContextAsync(ViewportDefaults.ApplyHeadedNoViewport(options, _headless)).ConfigureAwait(false),
            _cfg);

    public IReadOnlyList<IBrowserContext> Contexts =>
        _inner.Contexts.Select(c => Humanize.Context(c, _cfg)).ToList();
}
