using CloakBrowser.Human;
using Microsoft.Playwright;

namespace CloakBrowser.Wrappers;

/// <summary>
/// Transparent humanizing decorator over Playwright's <see cref="IBrowserContext"/>.
///
/// Intercepted: page-producing members (<c>NewPageAsync</c>, <c>Pages</c>,
/// <c>WaitForPageAsync</c>, <c>RunAndWaitForPageAsync</c>) return humanized pages.
/// Everything else is delegated to the inner context by the source generator.
/// </summary>
[GenerateInterfaceDelegation(typeof(IBrowserContext))]
public sealed partial class HumanizedBrowserContext : IBrowserContext
{
    private readonly IBrowserContext _inner;
    private readonly HumanConfig _cfg;

    internal HumanizedBrowserContext(IBrowserContext inner, HumanConfig cfg)
    {
        _inner = inner;
        _cfg = cfg;
    }

    /// <summary>The original, un-humanized Playwright context (escape hatch).</summary>
    public IBrowserContext Original => _inner;

    /// <summary>Alias of <see cref="Original"/>.</summary>
    public IBrowserContext Inner => _inner;

    public async Task<IPage> NewPageAsync() =>
        await Humanize.WrapPageAsync(await _inner.NewPageAsync().ConfigureAwait(false), _cfg).ConfigureAwait(false);

    public IReadOnlyList<IPage> Pages => Humanize.WrapPages(_inner.Pages, _cfg);

    public async Task<IPage> WaitForPageAsync(BrowserContextWaitForPageOptions? options = null) =>
        await Humanize.WrapPageAsync(await _inner.WaitForPageAsync(options).ConfigureAwait(false), _cfg).ConfigureAwait(false);

    public async Task<IPage> RunAndWaitForPageAsync(System.Func<Task> action, BrowserContextRunAndWaitForPageOptions? options = null) =>
        await Humanize.WrapPageAsync(await _inner.RunAndWaitForPageAsync(action, options).ConfigureAwait(false), _cfg).ConfigureAwait(false);
}
