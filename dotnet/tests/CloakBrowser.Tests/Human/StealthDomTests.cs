using System;
using System.Diagnostics;
using System.Text.Json;
using CloakBrowser.Human;
using Xunit;

namespace CloakBrowser.Tests.Human;

public class StealthDomTests
{
    [Fact]
    public void BuildBoxJs_EscapesSelector_AndReadsGeometry()
    {
        var js = StealthDom.BuildBoxJs("a\"b");
        // IsolatedWorld.JsonEncode uses System.Text.Json, which escapes '"' as ".
        Assert.Contains("a\\u0022b", js);
        Assert.Contains("getBoundingClientRect", js);
    }

    [Fact]
    public void BuildPointerJs_InlinesCoordinates()
    {
        Assert.Contains("__deepElementFromPoint(1.5, 2.5)", StealthDom.BuildPointerJs("#x", 1.5, 2.5));
    }

    [Fact]
    public void ParseResult_strictly_validates_protocol_and_target_identity()
    {
        Assert.Equal(StealthStatus.Ok, StealthDom.ParseResult(
            JsonSerializer.SerializeToElement(new { v = 1, r = "ok", targetId = 7 })).Status);
        Assert.Equal(StealthStatus.Stale, StealthDom.ParseResult(
            JsonSerializer.SerializeToElement(new { v = 1, r = "stale", targetId = 8 })).Status);
        Assert.Equal(StealthStatus.NotFound, StealthDom.ParseResult(
            JsonSerializer.SerializeToElement(new { v = 1, r = "not_found" })).Status);
        Assert.Equal(StealthStatus.Unsupported, StealthDom.ParseResult(
            JsonSerializer.SerializeToElement(new { v = 1, r = "unsupported" })).Status);

        JsonElement?[] malformed =
        {
            null,
            JsonSerializer.SerializeToElement(new { }),
            JsonSerializer.SerializeToElement(new { v = 2, r = "ok", targetId = 1 }),
            JsonSerializer.SerializeToElement(new { v = 1, r = "ok" }),
            JsonSerializer.SerializeToElement(new { v = 1, r = "ok", targetId = 1.5 }),
            JsonSerializer.SerializeToElement(new { v = 1, r = "stale" }),
            JsonSerializer.SerializeToElement(new { v = 1, r = "unknown", targetId = 1 }),
        };
        foreach (var value in malformed)
            Assert.Equal(StealthStatus.EvaluationFailed, StealthDom.ParseResult(value).Status);
    }

    // Runs the SHIPPED resolver JS (as produced by the C# builders) under Node against
    // DOM stubs. Validates the verbatim-string transcription is byte-correct and the
    // selector semantics (:has-text / unsupported / not-found) match the other wrappers.
    // Skipped when node is not on PATH.
    [Fact]
    public void ResolverSemantics_RunUnderNode()
    {
        var node = FindNode();
        if (node == null) return; // skip: node unavailable

        string boxHasText = StealthDom.BuildBoxJs("button:has-text('Submit') >> nth=0");
        string boxUnsupported = StealthDom.BuildBoxJs("internal:role=button");
        string boxNotFound = StealthDom.BuildBoxJs("button");
        string ptrHit = StealthDom.BuildPointerJs("button", 5, 5);

        string script = @"
function el(tag, text){
  const e = { tagName: tag, textContent: text || '', children: [] };
  e.contains = o => o === e;
  e.getBoundingClientRect = () => ({ x: 5, y: 6, width: 20, height: 10 });
  e.getAttribute = () => null; e.hasAttribute = () => false; e.closest = () => null;
  e.disabled = false; e.readOnly = false; e.isContentEditable = false; e.isConnected = true;
  return e;
}
function run(js, matches, point){
  const document = {
    querySelectorAll: () => matches.slice(),
    evaluate: () => ({ snapshotLength: matches.length, snapshotItem: i => matches[i] }),
    elementFromPoint: () => point || null,
  };
  return new Function('document','XPathResult','getComputedStyle','return ' + js)(
    document, { ORDERED_NODE_SNAPSHOT_TYPE: 7 }, () => ({ visibility: 'visible', display: 'block' }));
}
const b = " + JsStr(boxHasText) + @";
const u = " + JsStr(boxUnsupported) + @";
const nf = " + JsStr(boxNotFound) + @";
const p = " + JsStr(ptrHit) + @";
const btn = el('BUTTON','Submit');
console.log('HASTEXT', run(b, [btn, el('BUTTON','x')]).r);
console.log('UNSUPPORTED', run(u, []).r);
console.log('NOTFOUND', run(nf, []).r);
const t = el('BUTTON','x');
console.log('POINTER', JSON.stringify(run(p, [t], t)));
";

        string outp = RunNode(node, script);
        Assert.Contains("HASTEXT ok", outp);
        Assert.Contains("UNSUPPORTED unsupported", outp);
        Assert.Contains("NOTFOUND not_found", outp);
        Assert.Contains("POINTER", outp);
        Assert.Contains("\"r\":\"ok\"", outp);
        Assert.Contains("\"hit\":true", outp);
    }

    private static string JsStr(string s) => JsonSerializer.Serialize(s);

    private static string? FindNode()
    {
        foreach (var p in new[] { "node", "/usr/local/bin/node", "/opt/homebrew/bin/node", "/usr/bin/node" })
        {
            try
            {
                var psi = new ProcessStartInfo(p, "--version") { RedirectStandardOutput = true, UseShellExecute = false };
                using var proc = Process.Start(psi);
                if (proc == null) continue;
                proc.WaitForExit(5000);
                if (proc.ExitCode == 0) return p;
            }
            catch { /* try next */ }
        }
        return null;
    }

    private static string RunNode(string node, string script)
    {
        var psi = new ProcessStartInfo(node)
        {
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
        };
        // ArgumentList passes each arg verbatim (no shell/quote parsing to corrupt the script).
        psi.ArgumentList.Add("-e");
        psi.ArgumentList.Add(script);
        using var proc = Process.Start(psi)!;
        string outp = proc.StandardOutput.ReadToEnd();
        string err = proc.StandardError.ReadToEnd();
        proc.WaitForExit(30000);
        Assert.True(proc.ExitCode == 0, $"node failed:\n{outp}\n{err}");
        return outp;
    }
}
