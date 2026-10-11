using CloakBrowser;
using CloakBrowser.Human;
using CloakBrowser.Wrappers;
using Microsoft.Playwright;
using Xunit;

namespace CloakBrowser.Tests.Wrappers;

/// <summary>
/// The license guard and humanize must compose in this order: humanize wraps the raw
/// Playwright object first, the license-guard proxy wraps the humanized object. The
/// guard forwards to whatever it was handed, so guarding the raw object instead would
/// put Playwright's own methods back in front of the humanized ones for every call on
/// that handle — clicks would teleport and Playwright's action path would run instead
/// of the human engine (the Python and JS wrappers had exactly that bug).
/// </summary>
public class LicenseGuardCompositionTests
{
    private static IPage MakeFakePage()
    {
        var (mouse, _) = Fake.Of<IMouse>();
        var (keyboard, _) = Fake.Of<IKeyboard>();
        var (page, pageRec) = Fake.Of<IPage>();
        pageRec.On("Mouse", mouse);
        pageRec.On("Keyboard", keyboard);
        pageRec.On("ViewportSize", new PageViewportSizeResult { Width = 800, Height = 600 });
        return page;
    }

    [Fact]
    public void Guarded_context_wraps_the_humanized_context()
    {
        var (playwright, _) = Fake.Of<IPlaywright>();
        var (ctx, _) = Fake.Of<IBrowserContext>();

        var handle = new CloakContextHandle(
            playwright, null, ctx, humanize: true, new HumanConfig(), "/tmp/denial-compose");

        var guarded = Assert.IsAssignableFrom<IGuardedProxy>(handle.Context);
        Assert.IsType<HumanizedBrowserContext>(guarded.GuardTarget);
        Assert.Same(ctx, LicenseGuard.Unwrap(handle.Context));
    }

    [Fact]
    public void Keyless_context_is_humanized_and_not_guarded()
    {
        var (playwright, _) = Fake.Of<IPlaywright>();
        var (ctx, _) = Fake.Of<IBrowserContext>();

        var handle = new CloakContextHandle(
            playwright, null, ctx, humanize: true, new HumanConfig(), denialPath: null);

        Assert.IsNotAssignableFrom<IGuardedProxy>(handle.Context);
        Assert.IsType<HumanizedBrowserContext>(handle.Context);
    }

    [Fact]
    public async Task Guarded_context_hands_back_a_guarded_humanized_page()
    {
        var (playwright, _) = Fake.Of<IPlaywright>();
        var (ctx, ctxRec) = Fake.Of<IBrowserContext>();
        ctxRec.On("NewPageAsync", Task.FromResult(MakeFakePage()));

        var handle = new CloakContextHandle(
            playwright, null, ctx, humanize: true, new HumanConfig(), "/tmp/denial-compose");

        var page = await handle.NewPageAsync();

        var guarded = Assert.IsAssignableFrom<IGuardedProxy>(page);
        Assert.IsType<HumanizedPage>(guarded.GuardTarget);
    }

    [Fact]
    public async Task Existing_pages_of_a_guarded_context_are_guarded_humanized_pages()
    {
        var (playwright, _) = Fake.Of<IPlaywright>();
        var (ctx, ctxRec) = Fake.Of<IBrowserContext>();
        var page = MakeFakePage();
        ctxRec.On("Pages", new List<IPage> { page });

        var handle = new CloakContextHandle(
            playwright, null, ctx, humanize: true, new HumanConfig(), "/tmp/denial-compose");

        var pages = handle.Context.Pages;

        Assert.Single(pages);
        var guarded = Assert.IsAssignableFrom<IGuardedProxy>(pages[0]);
        Assert.IsType<HumanizedPage>(guarded.GuardTarget);
    }
}
