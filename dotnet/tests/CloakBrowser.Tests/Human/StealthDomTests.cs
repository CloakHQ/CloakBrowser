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
        Assert.Contains("elementFromPoint(1.5, 2.5)", StealthDom.BuildPointerJs("#x", 1.5, 2.5));
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
  e.getAttribute = () => null; e.disabled = false; e.readOnly = false; e.isContentEditable = false;
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
        Assert.Contains("POINTER {\"r\":\"ok\",\"hit\":true}", outp);
    }

    private static string JsStr(string s) => JsonSerializer.Serialize(s);

    // Regression #560: a display:contents element (e.g. a reset "li { display: contents }"
    // used by custom dropdown/menu widgets) has no box of its own, but its children/text
    // still render. Verifies the shipped resolver JS recurses into children instead of
    // reporting a false "not visible"/not_found, mirroring Playwright's own actionability
    // engine (packages/injected/src/domUtils.ts::computeBox).
    [Fact]
    public void ResolverSemantics_DisplayContents_RunUnderNode()
    {
        var node = FindNode();
        if (node == null) return; // skip: node unavailable

        string actionableJs = StealthDom.BuildActionableJs("li");
        string boxJs = StealthDom.BuildBoxJs("li");

        string script = @"
function contentsEl(tag, display){
  const e = { tagName: tag, nodeType: 1, disabled: false, readOnly: false, isContentEditable: false,
              firstChild: null, nextSibling: null, __display: display || 'block', __rect: { x: 0, y: 0, width: 0, height: 0 } };
  e.getAttribute = () => null;
  e.getBoundingClientRect = () => e.__rect;
  return e;
}
function textNode(text, rect){ return { nodeType: 3, textContent: text, nextSibling: null, __rect: rect }; }
function append(parent, child){
  if (!parent.firstChild) { parent.firstChild = child; return; }
  let last = parent.firstChild;
  while (last.nextSibling) last = last.nextSibling;
  last.nextSibling = child;
}
function run(js, root){
  const document = {
    querySelectorAll: () => [root],
    createRange: () => ({ _n: null, selectNode(n){ this._n = n; }, getBoundingClientRect(){ return this._n.__rect; } }),
  };
  const getComputedStyle = (el) => ({ visibility: 'visible', display: el.__display || 'block' });
  return new Function('document', 'getComputedStyle', 'return ' + js)(document, getComputedStyle);
}
const li = contentsEl('LI', 'contents');
append(li, textNode('Hoy', { x: 10, y: 20, width: 30, height: 12 }));
const actionableJs = " + JsStr(actionableJs) + @";
const boxJs = " + JsStr(boxJs) + @";
console.log('ACTIONABLE', JSON.stringify(run(actionableJs, li)));
console.log('BOX', JSON.stringify(run(boxJs, li)));
";

        string outp = RunNode(node, script);
        Assert.Contains("ACTIONABLE {\"r\":\"ok\",\"visible\":true,\"enabled\":true,\"editable\":false,\"box\":{\"x\":10,\"y\":20,\"width\":30,\"height\":12}}", outp);
        Assert.Contains("BOX {\"r\":\"ok\",\"box\":{\"x\":10,\"y\":20,\"width\":30,\"height\":12}}", outp);
    }

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
