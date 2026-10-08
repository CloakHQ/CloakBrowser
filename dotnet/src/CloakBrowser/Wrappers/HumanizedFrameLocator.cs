using System.Text.RegularExpressions;
using CloakBrowser.Human;
using Microsoft.Playwright;

namespace CloakBrowser.Wrappers;

/// <summary>
/// Humanizing decorator over Playwright's <see cref="IFrameLocator"/>. A frame locator
/// performs no actions itself; every member returns a locator (or another frame locator),
/// which is re-wrapped so actions inside the frame stay humanized.
/// </summary>
public sealed class HumanizedFrameLocator : IFrameLocator
{
    private readonly IFrameLocator _inner;
    private readonly HumanCursor _cursor;
    private readonly HumanConfig _cfg;

    internal HumanizedFrameLocator(IFrameLocator inner, HumanCursor cursor, HumanConfig cfg)
    {
        _inner = inner;
        _cursor = cursor;
        _cfg = cfg;
    }

    /// <summary>The original, un-humanized Playwright frame locator.</summary>
    public IFrameLocator Original => _inner;

    private ILocator L(ILocator l) => Humanize.WrapLocator(l, _cursor, _cfg);
    private IFrameLocator F(IFrameLocator f) => Humanize.WrapFrameLocator(f, _cursor, _cfg);
    private static ILocator Raw(ILocator l) => l is HumanizedLocator h ? h.Original : l;

    // Obsolete in Playwright but still part of IFrameLocator.
#pragma warning disable CS0612, CS0618
    public IFrameLocator First => F(_inner.First);
    public IFrameLocator Last => F(_inner.Last);
    public IFrameLocator Nth(int index) => F(_inner.Nth(index));
#pragma warning restore CS0612, CS0618
    public IFrameLocator FrameLocator(string selector) => F(_inner.FrameLocator(selector));
    public ILocator Owner => L(_inner.Owner);

    public ILocator Locator(string selectorOrLocator, FrameLocatorLocatorOptions? options = null) =>
        L(_inner.Locator(selectorOrLocator, options));
    public ILocator Locator(ILocator selectorOrLocator, FrameLocatorLocatorOptions? options = null) =>
        L(_inner.Locator(Raw(selectorOrLocator), options));

    public ILocator GetByAltText(string text, FrameLocatorGetByAltTextOptions? options = null) => L(_inner.GetByAltText(text, options));
    public ILocator GetByAltText(Regex text, FrameLocatorGetByAltTextOptions? options = null) => L(_inner.GetByAltText(text, options));
    public ILocator GetByLabel(string text, FrameLocatorGetByLabelOptions? options = null) => L(_inner.GetByLabel(text, options));
    public ILocator GetByLabel(Regex text, FrameLocatorGetByLabelOptions? options = null) => L(_inner.GetByLabel(text, options));
    public ILocator GetByPlaceholder(string text, FrameLocatorGetByPlaceholderOptions? options = null) => L(_inner.GetByPlaceholder(text, options));
    public ILocator GetByPlaceholder(Regex text, FrameLocatorGetByPlaceholderOptions? options = null) => L(_inner.GetByPlaceholder(text, options));
    public ILocator GetByRole(AriaRole role, FrameLocatorGetByRoleOptions? options = null) => L(_inner.GetByRole(role, options));
    public ILocator GetByTestId(string testId) => L(_inner.GetByTestId(testId));
    public ILocator GetByTestId(Regex testId) => L(_inner.GetByTestId(testId));
    public ILocator GetByText(string text, FrameLocatorGetByTextOptions? options = null) => L(_inner.GetByText(text, options));
    public ILocator GetByText(Regex text, FrameLocatorGetByTextOptions? options = null) => L(_inner.GetByText(text, options));
    public ILocator GetByTitle(string text, FrameLocatorGetByTitleOptions? options = null) => L(_inner.GetByTitle(text, options));
    public ILocator GetByTitle(Regex text, FrameLocatorGetByTitleOptions? options = null) => L(_inner.GetByTitle(text, options));

    public override string? ToString() => _inner.ToString();
}
