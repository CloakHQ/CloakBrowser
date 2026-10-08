using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace CloakBrowser.Human;

/// <summary>
/// Playwright's own selector / actionability engine, run inside OUR isolated world.
/// Port of <c>cloakbrowser/human/injected.py</c>.
///
/// Playwright ships its InjectedScript (selector engines for role, label, text,
/// test-id, <c>&gt;&gt;</c> chains, <c>has</c> / <c>has-text</c> filters, <c>nth</c>,
/// <c>visible</c>, plus <c>checkElementStates</c> / <c>expectHitTarget</c>) as a string
/// literal in its driver package (<c>.playwright/package/lib/generated/injectedScriptSource.js</c>,
/// copied next to the app by the Microsoft.Playwright NuGet package). It is evaluated
/// here in a CDP isolated world that only the humanize layer uses, with the two
/// constructor hooks that touch <c>window</c> disabled, so the page observes nothing.
/// The literal comes from the installed driver, so selector syntax always matches
/// the client that produced the selector string.
/// </summary>
internal static class InjectedSource
{
    /// <summary>Global name inside the isolated world (invisible to page scripts).</summary>
    public const string Global = "__cloakInjected";

    private static readonly Regex LiteralStart = new(@"\bsource\d*\s*[=:]\s*(['""`])", RegexOptions.Compiled);
    private static string? _literal;
    private static readonly object Lock = new();

    /// <summary>Driver lib directories to search (app base dir first, then the NuGet cache).</summary>
    internal static IEnumerable<string> LibDirs()
    {
        var env = Environment.GetEnvironmentVariable("PLAYWRIGHT_DRIVER_SEARCH_PATH");
        if (!string.IsNullOrEmpty(env)) yield return Path.Combine(env, ".playwright", "package", "lib");
        yield return Path.Combine(AppContext.BaseDirectory, ".playwright", "package", "lib");
        var asmDir = Path.GetDirectoryName(typeof(Microsoft.Playwright.IPage).Assembly.Location);
        if (!string.IsNullOrEmpty(asmDir))
        {
            yield return Path.Combine(asmDir, ".playwright", "package", "lib");
            // NuGet cache layout: <pkg>/<ver>/lib/netstandard2.0/Microsoft.Playwright.dll
            yield return Path.GetFullPath(Path.Combine(asmDir, "..", "..", ".playwright", "package", "lib"));
        }
    }

    /// <summary>The JS string literal starting at <paramref name="start"/> (quotes included).</summary>
    internal static string ReadLiteral(string text, int start)
    {
        char quote = text[start];
        int i = start + 1;
        while (text[i] != quote) i += text[i] == '\\' ? 2 : 1;
        return text.Substring(start, i + 1 - start);
    }

    /// <summary>Locate the InjectedScript source literal (bundled or per-file layout).</summary>
    public static string FindLiteral(IEnumerable<string>? dirs = null)
    {
        lock (Lock)
        {
            if (_literal != null && dirs == null) return _literal;
            var searched = new List<string>();
            foreach (var d in dirs ?? LibDirs())
            {
                searched.Add(d);
                if (!Directory.Exists(d)) continue;
                var bundle = Path.Combine(d, "coreBundle.js");
                if (File.Exists(bundle))
                {
                    var text = File.ReadAllText(bundle, Encoding.UTF8);
                    int pos = text.IndexOf("generated/injectedScriptSource.ts", StringComparison.Ordinal);
                    if (pos >= 0)
                    {
                        var m = LiteralStart.Match(text, pos);
                        if (m.Success) return Remember(ReadLiteral(text, m.Groups[1].Index), dirs);
                    }
                }
                foreach (var f in Directory.EnumerateFiles(d, "injectedScriptSource.js", SearchOption.AllDirectories).OrderBy(x => x, StringComparer.Ordinal))
                {
                    var text = File.ReadAllText(f, Encoding.UTF8);
                    var m = LiteralStart.Match(text);
                    if (m.Success) return Remember(ReadLiteral(text, m.Groups[1].Index), dirs);
                }
            }
            throw new InvalidOperationException(
                "cloakbrowser humanize: Playwright's InjectedScript source was not found in " +
                string.Join(", ", searched) + "; the installed Microsoft.Playwright layout is not supported");
        }
    }

    private static string Remember(string lit, IEnumerable<string>? dirs)
    {
        if (dirs == null) _literal = lit;
        return lit;
    }

    /// <summary>Expression that installs the engine in the current (isolated) world.
    /// <paramref name="source"/> is the decoded module text. Idempotent; supports the
    /// positional (&lt; 1.47) and options-object constructors.</summary>
    public static string BuildInstallJs(string source, string sdkLanguage = "csharp", string testIdAttribute = "data-testid")
    {
        var opts = JsonSerializer.Serialize(new Dictionary<string, object>
        {
            ["isUnderTest"] = false,
            ["sdkLanguage"] = sdkLanguage,
            ["testIdAttributeName"] = testIdAttribute,
            ["stableRafCount"] = 1,
            ["browserName"] = "chromium",
            ["isUtilityWorld"] = true,
            ["customEngines"] = Array.Empty<object>(),
        });
        return "(() => {\n" +
            $"if (globalThis.{Global}) return true;\n" +
            "const module = { exports: {} }; const exports = module.exports;\n" +
            source + "\n" +
            ";const exp = module.exports.InjectedScript;\n" +
            "const C = (exp && exp.prototype && exp.prototype.querySelectorAll) ? exp : exp();\n" +
            "C.prototype._setupGlobalListenersRemovalDetection = function () {};\n" +
            "C.prototype._setupHitTargetInterceptors = function () {};\n" +
            $"const o = {opts};\n" +
            "const inj = C.length > 2\n" +
            "  ? new C(globalThis, o.isUnderTest, o.sdkLanguage, o.testIdAttributeName, o.stableRafCount, o.browserName, o.customEngines)\n" +
            "  : new C(globalThis, o);\n" +
            $"Object.defineProperty(globalThis, {JsonSerializer.Serialize(Global)}, {{ value: inj }});\n" +
            "return true; })()";
    }
}
