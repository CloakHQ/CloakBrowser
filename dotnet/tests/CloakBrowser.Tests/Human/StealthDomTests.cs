using System;
using System.Diagnostics;
using System.IO;
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
            JsonSerializer.SerializeToElement(new { v = 2, r = "ok", targetId = 7, gen = 3 })).Status);
        Assert.Equal(StealthStatus.Stale, StealthDom.ParseResult(
            JsonSerializer.SerializeToElement(new { v = 2, r = "stale", targetId = 8, gen = 3 })).Status);
        Assert.Equal(StealthStatus.NotFound, StealthDom.ParseResult(
            JsonSerializer.SerializeToElement(new { v = 2, r = "not_found" })).Status);
        Assert.Equal(StealthStatus.Unsupported, StealthDom.ParseResult(
            JsonSerializer.SerializeToElement(new { v = 2, r = "unsupported" })).Status);

        JsonElement?[] malformed =
        {
            null,
            JsonSerializer.SerializeToElement(new { }),
            JsonSerializer.SerializeToElement(new { v = 1, r = "ok", targetId = 1, gen = 3 }),
            JsonSerializer.SerializeToElement(new { v = 2, r = "ok" }),
            JsonSerializer.SerializeToElement(new { v = 2, r = "ok", targetId = 1.5, gen = 3 }),
            JsonSerializer.SerializeToElement(new { v = 2, r = "stale", gen = 3 }),
            JsonSerializer.SerializeToElement(new { v = 2, r = "unknown", targetId = 1, gen = 3 }),
            // identity without the world generation is not trustworthy
            JsonSerializer.SerializeToElement(new { v = 2, r = "ok", targetId = 1 }),
            JsonSerializer.SerializeToElement(new { v = 2, r = "stale", targetId = 1 }),
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

    [Fact]
    public void DisplayContentsGeometry_RunUnderNode()
    {
        var node = FindNode();
        if (node == null) return;

        string targetJs = StealthDom.BuildSnapshotJs(".target");
        string unionJs = StealthDom.BuildSnapshotJs(".union");
        string hiddenJs = StealthDom.BuildSnapshotJs(".hidden-text");
        string script = @"
function rect(x,y,width,height){ return {x,y,width,height}; }
function el(tag,text,box,display,visibility){
  const e={tagName:tag,nodeType:1,textContent:text||'',childNodes:[],children:[],firstChild:null,
    parentElement:null,previousElementSibling:null,nextSibling:null,isConnected:true,disabled:false,
    readOnly:false,isContentEditable:false,type:'text',value:'',checked:false,attrs:{},
    style:{display:display||'block',visibility:visibility||'visible'},box:box};
  if(text){const t={nodeType:3,nodeValue:text,textContent:text,nextSibling:null,box:box};e.childNodes.push(t);e.firstChild=t;}
  e.getBoundingClientRect=()=>e.box;e.getAttribute=n=>e.attrs[n]||null;e.hasAttribute=n=>n in e.attrs;
  e.closest=()=>null;e.contains=o=>o===e||e.children.some(c=>c.contains(o));e.getRootNode=()=>document;
  return e;
}
function append(parent,child){const prev=parent.childNodes[parent.childNodes.length-1];if(prev)prev.nextSibling=child;
  child.parentElement=parent;child.previousElementSibling=parent.children[parent.children.length-1]||null;
  parent.children.push(child);parent.childNodes.push(child);parent.firstChild=parent.childNodes[0];}
function run(js,target){let selected=null;const document={children:[target],head:{contains:()=>false},activeElement:null,
  querySelectorAll:()=>[target],evaluate:()=>({snapshotLength:0,snapshotItem:()=>null}),elementFromPoint:()=>null,
  createRange:()=>({selectNode:n=>{selected=n;},getBoundingClientRect:()=>selected.box})};
  function wire(n){n.ownerDocument=document;for(const child of n.childNodes||[])wire(child);}wire(target);
  return new Function('document','XPathResult','getComputedStyle','globalThis','return '+js)(
    document,{ORDERED_NODE_SNAPSHOT_TYPE:7},n=>n.style,{});
}
const target=el('LI','Hoy',rect(0,0,0,0),'contents');target.childNodes[0].box=rect(5,6,25,10);
const union=el('DIV','',rect(0,0,0,0),'contents');
const left=el('SPAN','left',rect(10,20,20,10));const right=el('SPAN','right',rect(40,20,30,10));
const nested=el('SPAN','',rect(0,0,0,0),'contents');append(nested,el('SPAN','nested',rect(75,20,25,10)));
const hidden=el('SPAN','hidden',rect(1000,1000,100,100),'block','hidden');
append(union,left);append(union,right);append(union,nested);append(union,hidden);
const hiddenText=el('DIV','hidden text',rect(0,0,0,0),'contents','hidden');hiddenText.childNodes[0].box=rect(5,6,50,10);
const t=run(" + JsStr(targetJs) + @",target);const u=run(" + JsStr(unionJs) + @",union);const h=run(" + JsStr(hiddenJs) + @",hiddenText);
console.log('TARGET',JSON.stringify({visible:t.visible,box:t.box}));
console.log('UNION',JSON.stringify({visible:u.visible,box:u.box}));
console.log('HIDDEN',JSON.stringify({visible:h.visible,box:h.box}));
";

        string outp = RunNode(node, script);
        Assert.Contains("TARGET {\"visible\":true,\"box\":{\"x\":5,\"y\":6,\"width\":25,\"height\":10}}", outp);
        Assert.Contains("UNION {\"visible\":true,\"box\":{\"x\":10,\"y\":20,\"width\":90,\"height\":10}}", outp);
        Assert.Contains("HIDDEN {\"visible\":false,\"box\":null}", outp);
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
        // The script inlines the resolver once per builder call, so it is well over
        // 100 KB. Linux caps a single argv entry at MAX_ARG_STRLEN (128 KB) and
        // "node -e <script>" hits E2BIG there, so hand node a file instead.
        string scriptPath = Path.Combine(Path.GetTempPath(),
            "cloakbrowser-resolver-" + Guid.NewGuid().ToString("N") + ".js");
        File.WriteAllText(scriptPath, script);
        try
        {
            var psi = new ProcessStartInfo(node)
            {
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
            };
            psi.ArgumentList.Add(scriptPath);
            using var proc = Process.Start(psi)!;
            string outp = proc.StandardOutput.ReadToEnd();
            string err = proc.StandardError.ReadToEnd();
            proc.WaitForExit(30000);
            Assert.True(proc.ExitCode == 0, $"node failed:\n{outp}\n{err}");
            return outp;
        }
        finally
        {
            try { File.Delete(scriptPath); } catch (IOException) { }
        }
    }
}
