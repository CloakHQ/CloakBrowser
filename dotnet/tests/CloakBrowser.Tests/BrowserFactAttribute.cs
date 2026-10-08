using Xunit;

namespace CloakBrowser.Tests;

/// <summary>A <see cref="FactAttribute"/> for tests that drive a real CloakBrowser binary:
/// reported as skipped (not silently passed) when <c>CLOAKBROWSER_BINARY_PATH</c> is not set.</summary>
public sealed class BrowserFactAttribute : FactAttribute
{
    public static bool Available =>
        !string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("CLOAKBROWSER_BINARY_PATH"));

    public BrowserFactAttribute()
    {
        if (!Available) Skip = "set CLOAKBROWSER_BINARY_PATH to run real-browser tests";
    }
}

/// <summary><see cref="TheoryAttribute"/> counterpart of <see cref="BrowserFactAttribute"/>.</summary>
public sealed class BrowserTheoryAttribute : TheoryAttribute
{
    public BrowserTheoryAttribute()
    {
        if (!BrowserFactAttribute.Available) Skip = "set CLOAKBROWSER_BINARY_PATH to run real-browser tests";
    }
}
