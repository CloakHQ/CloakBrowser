using System.Text.Json;
using Microsoft.Playwright;

namespace CloakBrowser.Human;

/// <summary>An isolated-world evaluation failed (never falls back to the page).</summary>
public sealed class StealthWorldException : PlaywrightException
{
    public StealthWorldException(string message) : base(message) { }
}

/// <summary>The element behind an id is no longer in the isolated-world registry.</summary>
internal sealed class StaleElementException : PlaywrightException
{
    public StaleElementException() : base("element is not attached to the DOM") { }
}

internal readonly record struct Rect(double X, double Y, double Width, double Height)
{
    public static Rect Intersect(Rect a, Rect b)
    {
        double x0 = Math.Max(a.X, b.X), y0 = Math.Max(a.Y, b.Y);
        double x1 = Math.Min(a.X + a.Width, b.X + b.Width), y1 = Math.Min(a.Y + a.Height, b.Y + b.Height);
        return new Rect(x0, y0, Math.Max(0, x1 - x0), Math.Max(0, y1 - y0));
    }

    public bool Contains(double x, double y) => X <= x && x <= X + Width && Y <= y && y <= Y + Height;
}

internal readonly record struct EditorField(string Kind, double Dx, double Dy);

/// <summary>
/// CDP isolated worlds for every frame of a page (main, same-process, OOPIF).
/// Port of <c>cloakbrowser/human/world.py</c>.
///
/// Each frame gets one isolated world per document, created through
/// <c>Page.createIsolatedWorld</c> on the CDP session that owns the frame. Into that
/// world we install Playwright's InjectedScript and a small helper object. Nothing
/// runs in, or is observable from, the page's main world: frame mapping uses
/// <c>Page.getFrameTree</c>, iframe owners are reached via <c>DOM.getFrameOwner</c>
/// + <c>DOM.resolveNode</c>, elements live in a world-local registry of integer ids.
/// </summary>
internal sealed class HumanWorld
{
    private sealed class FrameRec
    {
        public FrameRec(ICDPSession session, string cdpId) { Session = session; CdpId = cdpId; }
        public ICDPSession Session { get; }
        public string CdpId { get; }
        public int? Ctx { get; set; }
    }

    private static string? _decodedSource;
    private static readonly string[] StaleMarkers =
    {
        "Cannot find context", "Execution context was destroyed", "Inspected target navigated",
        "cloak:stale-world", "Cannot find default execution context",
    };

    private readonly IPage _page;
    private ICDPSession? _session;
    private readonly Dictionary<IFrame, FrameRec> _frames = new();
    private readonly SemaphoreSlim _lock = new(1, 1);

    public HumanWorld(IPage page)
    {
        _page = page;
        try
        {
            page.FrameNavigated += (_, f) => Invalidate(f);
            page.FrameDetached += (_, f) => Invalidate(f);
        }
        catch (Exception) { /* fakes without events */ }
    }

    public IPage Page => _page;

    // -- sessions / frame mapping -------------------------------------------

    public async Task<ICDPSession> SessionAsync()
    {
        _session ??= await _page.Context.NewCDPSessionAsync(_page).ConfigureAwait(false);
        return _session;
    }

    /// <summary>Forget worlds of <paramref name="frame"/> and its descendants (all when null).</summary>
    public void Invalidate(IFrame? frame = null)
    {
        lock (_frames)
        {
            if (frame == null) { _frames.Clear(); return; }
            foreach (var f in _frames.Keys.Where(f => f == frame || IsDescendant(f, frame)).ToList())
                _frames.Remove(f);
        }
    }

    private static bool IsDescendant(IFrame frame, IFrame ancestor)
    {
        for (var p = frame.ParentFrame; p != null; p = p.ParentFrame)
            if (p == ancestor) return true;
        return false;
    }

    private async Task<FrameRec> LocateAsync(IFrame frame)
    {
        lock (_frames) { if (_frames.TryGetValue(frame, out var r)) return r; }
        if (frame.IsDetached) throw new PlaywrightException("Frame was detached");
        FrameRec rec;
        var parent = frame.ParentFrame;
        if (parent == null)
        {
            var session = await SessionAsync().ConfigureAwait(false);
            var tree = await session.SendAsync("Page.getFrameTree").ConfigureAwait(false);
            rec = new FrameRec(session, tree!.Value.GetProperty("frameTree").GetProperty("frame").GetProperty("id").GetString()!);
        }
        else
        {
            rec = await LocateChildAsync(frame, parent).ConfigureAwait(false);
        }
        lock (_frames)
        {
            if (_frames.TryGetValue(frame, out var existing)) return existing;
            _frames[frame] = rec;
        }
        return rec;
    }

    private async Task<FrameRec> LocateChildAsync(IFrame frame, IFrame parent)
    {
        ICDPSession? own = null;
        try { own = await _page.Context.NewCDPSessionAsync(frame).ConfigureAwait(false); } // OOPIF: own target
        catch (Exception) { own = null; }
        if (own != null)
        {
            var t = await own.SendAsync("Page.getFrameTree").ConfigureAwait(false);
            return new FrameRec(own, t!.Value.GetProperty("frameTree").GetProperty("frame").GetProperty("id").GetString()!);
        }
        var prec = await LocateAsync(parent).ConfigureAwait(false);
        var tree = await prec.Session.SendAsync("Page.getFrameTree").ConfigureAwait(false);
        var node = FindNode(tree!.Value.GetProperty("frameTree"), prec.CdpId);
        var kids = new List<JsonElement>();
        if (node is JsonElement n && n.TryGetProperty("childFrames", out var cf))
            foreach (var k in cf.EnumerateArray()) kids.Add(k.GetProperty("frame"));
        var cdpId = MatchChild(frame, parent, kids)
            ?? throw new PlaywrightException("cloakbrowser humanize: could not map the frame to a CDP frame");
        return new FrameRec(prec.Session, cdpId);
    }

    private static JsonElement? FindNode(JsonElement tree, string cdpId)
    {
        if (tree.GetProperty("frame").GetProperty("id").GetString() == cdpId) return tree;
        if (tree.TryGetProperty("childFrames", out var kids))
            foreach (var c in kids.EnumerateArray())
                if (FindNode(c, cdpId) is JsonElement found) return found;
        return null;
    }

    /// <summary>Playwright and CDP list child frames in attach order; frames sharing the
    /// same (name, url) are matched by their position within that group.</summary>
    internal static string? MatchChild(IFrame frame, IFrame parent, IReadOnlyList<JsonElement> kids)
    {
        static string KeyPw(IFrame f) => f.Name + "\u0000" + f.Url;
        static string KeyCdp(JsonElement k) =>
            (k.TryGetProperty("name", out var n) ? n.GetString() : "") + "\u0000" +
            (k.TryGetProperty("url", out var u) ? u.GetString() : "") +
            (k.TryGetProperty("urlFragment", out var uf) ? uf.GetString() : "");
        var want = KeyPw(frame);
        var cands = kids.Where(k => KeyCdp(k) == want).ToList();
        var siblings = parent.ChildFrames.ToList();
        var peers = siblings.Where(f => KeyPw(f) == want).ToList();
        int pi = peers.IndexOf(frame);
        if (cands.Count > 0 && pi >= 0 && cands.Count == peers.Count) return cands[pi].GetProperty("id").GetString();
        if (cands.Count == 1) return cands[0].GetProperty("id").GetString();
        int si = siblings.IndexOf(frame);
        if (kids.Count == siblings.Count && si >= 0) return kids[si].GetProperty("id").GetString();
        return null;
    }

    public async Task<IFrame?> FrameForCdpIdAsync(IFrame parent, string cdpId)
    {
        foreach (var child in parent.ChildFrames)
        {
            try { if ((await LocateAsync(child).ConfigureAwait(false)).CdpId == cdpId) return child; }
            catch (PlaywrightException) { }
        }
        return null;
    }

    // -- world lifecycle ----------------------------------------------------

    /// <summary>Execution context of the frame's isolated world (created if needed). It
    /// changes on every new document, so element ids cached against it go stale with it.</summary>
    public async Task<int> ContextIdAsync(IFrame frame) => (await ReadyAsync(frame).ConfigureAwait(false)).Ctx!.Value;

    private async Task<FrameRec> ReadyAsync(IFrame frame)
    {
        var rec = await LocateAsync(frame).ConfigureAwait(false);
        if (rec.Ctx != null) return rec;
        await _lock.WaitAsync().ConfigureAwait(false);
        try
        {
            if (rec.Ctx != null) return rec;
            var res = await rec.Session.SendAsync("Page.createIsolatedWorld", new Dictionary<string, object>
            {
                ["frameId"] = rec.CdpId, ["worldName"] = "", ["grantUniveralAccess"] = true,
            }).ConfigureAwait(false);
            int ctx = res!.Value.GetProperty("executionContextId").GetInt32();
            await InstallAsync(rec.Session, ctx).ConfigureAwait(false);
            rec.Ctx = ctx;
        }
        finally { _lock.Release(); }
        return rec;
    }

    private static async Task InstallAsync(ICDPSession session, int ctx)
    {
        if (_decodedSource == null)
        {
            var v = await RawEvalAsync(session, ctx, InjectedSource.FindLiteral()).ConfigureAwait(false);
            _decodedSource = v!.Value.GetString();
        }
        await RawEvalAsync(session, ctx, InjectedSource.BuildInstallJs(_decodedSource!)).ConfigureAwait(false);
        await RawEvalAsync(session, ctx, WorldHelpers.Js).ConfigureAwait(false);
    }

    private static async Task<JsonElement?> RawEvalAsync(ICDPSession session, int ctx, string expression, bool byValue = true)
    {
        var res = (await session.SendAsync("Runtime.evaluate", new Dictionary<string, object>
        {
            ["expression"] = expression, ["contextId"] = ctx, ["returnByValue"] = byValue, ["awaitPromise"] = true,
        }).ConfigureAwait(false))!.Value;
        if (res.TryGetProperty("exceptionDetails", out var det))
        {
            string desc = det.TryGetProperty("exception", out var ex) && ex.TryGetProperty("description", out var d)
                ? d.GetString() ?? "" : det.TryGetProperty("text", out var t) ? t.GetString() ?? "" : "";
            if (desc.Contains("cloak:stale-element")) throw new StaleElementException();
            throw new StealthWorldException($"cloakbrowser humanize: isolated-world script failed: {desc.Split('\n')[0]}");
        }
        var result = res.GetProperty("result");
        if (!byValue) return result.Clone();
        return result.TryGetProperty("value", out var value) ? value.Clone() : null;
    }

    // -- evaluation ---------------------------------------------------------

    /// <summary>Evaluate in the frame's isolated world; recreate the world once if stale.</summary>
    public async Task<JsonElement?> EvaluateAsync(IFrame frame, string expression, bool byValue = true)
    {
        for (int attempt = 0; ; attempt++)
        {
            var rec = await ReadyAsync(frame).ConfigureAwait(false);
            try
            {
                return await RawEvalAsync(rec.Session, rec.Ctx!.Value, expression, byValue).ConfigureAwait(false);
            }
            catch (StaleElementException) { throw; }
            catch (Exception e) when (attempt == 0 && StaleMarkers.Any(m => e.Message.Contains(m)))
            {
                rec.Ctx = null;
            }
        }
    }

    public static string Arg(object? a) => JsonSerializer.Serialize(a);

    public Task<JsonElement?> CallAsync(IFrame frame, string method, params object?[] args) =>
        EvaluateAsync(frame, $"{WorldHelpers.Name}.{method}({string.Join(", ", args.Select(Arg))})");

    public async Task<(ICDPSession Session, string ObjectId)> ElementObjectIdAsync(IFrame frame, int id)
    {
        var rec = await ReadyAsync(frame).ConfigureAwait(false);
        var obj = await RawEvalAsync(rec.Session, rec.Ctx!.Value, $"{WorldHelpers.Name}.el({id})", byValue: false).ConfigureAwait(false);
        return (rec.Session, obj!.Value.GetProperty("objectId").GetString()!);
    }

    private static async Task ReleaseAsync(ICDPSession session, string objectId)
    {
        try { await session.SendAsync("Runtime.releaseObject", new() { ["objectId"] = objectId }).ConfigureAwait(false); }
        catch (Exception) { }
    }

    /// <summary>Segments of a native date/time editor in visual order, with centres relative
    /// to the input's border box. They live in the input's closed user-agent shadow root;
    /// CDP's DOM domain (<c>pierce</c>) reads them without running any script in the page.</summary>
    public async Task<List<EditorField>> EditorFieldsAsync(IFrame frame, int id)
    {
        var (session, objectId) = await ElementObjectIdAsync(frame, id).ConfigureAwait(false);
        JsonElement node, own;
        try
        {
            node = (await session.SendAsync("DOM.describeNode", new() { ["objectId"] = objectId, ["depth"] = -1, ["pierce"] = true }).ConfigureAwait(false))!.Value.GetProperty("node").Clone();
            own = (await session.SendAsync("DOM.getBoxModel", new() { ["objectId"] = objectId }).ConfigureAwait(false))!.Value.GetProperty("model").GetProperty("border").Clone();
        }
        finally { await ReleaseAsync(session, objectId).ConfigureAwait(false); }
        double ox = own[0].GetDouble(), oy = own[1].GetDouble();
        var output = new List<EditorField>();

        async Task Walk(JsonElement n)
        {
            string pseudo = "";
            if (n.TryGetProperty("attributes", out var attrs))
                for (int i = 0; i + 1 < attrs.GetArrayLength(); i += 2)
                    if (attrs[i].GetString() == "pseudo") pseudo = attrs[i + 1].GetString() ?? "";
            if (pseudo.StartsWith("-webkit-datetime-edit-") && pseudo.EndsWith("-field") && !pseudo.Contains("wrapper"))
            {
                var q = (await session.SendAsync("DOM.getBoxModel", new() { ["backendNodeId"] = n.GetProperty("backendNodeId").GetInt32() }).ConfigureAwait(false))!
                    .Value.GetProperty("model").GetProperty("border");
                output.Add(new EditorField(
                    pseudo["-webkit-datetime-edit-".Length..^"-field".Length],
                    (q[0].GetDouble() + q[2].GetDouble()) / 2 - ox, (q[1].GetDouble() + q[5].GetDouble()) / 2 - oy));
            }
            foreach (var key in new[] { "children", "shadowRoots" })
                if (n.TryGetProperty(key, out var kids))
                    foreach (var c in kids.EnumerateArray()) await Walk(c).ConfigureAwait(false);
        }

        await Walk(node).ConfigureAwait(false);
        return output.OrderBy(f => Math.Round(f.Dy / 4)).ThenBy(f => f.Dx).ToList();
    }

    /// <summary>Child frame owned by the &lt;iframe&gt; element <paramref name="id"/> in <paramref name="frame"/>.</summary>
    public async Task<IFrame?> ContentFrameAsync(IFrame frame, int id)
    {
        var (session, objectId) = await ElementObjectIdAsync(frame, id).ConfigureAwait(false);
        JsonElement node;
        try { node = (await session.SendAsync("DOM.describeNode", new() { ["objectId"] = objectId }).ConfigureAwait(false))!.Value.GetProperty("node").Clone(); }
        finally { await ReleaseAsync(session, objectId).ConfigureAwait(false); }
        if (!node.TryGetProperty("frameId", out var fid) || string.IsNullOrEmpty(fid.GetString())) return null;
        return await FrameForCdpIdAsync(frame, fid.GetString()!).ConfigureAwait(false);
    }

    // -- geometry across frames ---------------------------------------------

    /// <summary>Call <paramref name="declaration"/> with <c>this</c> = the frame's
    /// &lt;iframe&gt; element, inside the parent frame's isolated world.</summary>
    private async Task<JsonElement?> OwnerCallAsync(IFrame frame, string declaration, params object[] args)
    {
        var parent = frame.ParentFrame!;
        var rec = await LocateAsync(frame).ConfigureAwait(false);
        var prec = await ReadyAsync(parent).ConfigureAwait(false);
        var owner = await prec.Session.SendAsync("DOM.getFrameOwner", new() { ["frameId"] = rec.CdpId }).ConfigureAwait(false);
        var obj = (await prec.Session.SendAsync("DOM.resolveNode", new()
        {
            ["backendNodeId"] = owner!.Value.GetProperty("backendNodeId").GetInt32(), ["executionContextId"] = prec.Ctx!.Value,
        }).ConfigureAwait(false))!.Value.GetProperty("object");
        var objectId = obj.GetProperty("objectId").GetString()!;
        JsonElement res;
        try
        {
            res = (await prec.Session.SendAsync("Runtime.callFunctionOn", new()
            {
                ["objectId"] = objectId, ["functionDeclaration"] = declaration,
                ["arguments"] = args.Select(a => new Dictionary<string, object> { ["value"] = a }).ToArray(),
                ["returnByValue"] = true,
            }).ConfigureAwait(false))!.Value.Clone();
        }
        finally { await ReleaseAsync(prec.Session, objectId).ConfigureAwait(false); }
        if (res.TryGetProperty("exceptionDetails", out _))
            throw new StealthWorldException("cloakbrowser humanize: frame owner evaluation failed");
        return res.GetProperty("result").TryGetProperty("value", out var v) ? v.Clone() : null;
    }

    public async Task<(double Width, double Height)> ViewportAsync()
    {
        var size = _page.ViewportSize;
        if (size != null && size.Width > 0) return (size.Width, size.Height);
        var doc = (await CallAsync(_page.MainFrame, "doc").ConfigureAwait(false))!.Value;
        return (doc.GetProperty("width").GetDouble(), doc.GetProperty("height").GetDouble());
    }

    /// <summary>The frame's origin in viewport coordinates and its visible clip (intersection
    /// of all ancestor iframe content boxes and the viewport).</summary>
    public async Task<(double Ox, double Oy, Rect Clip)> FrameGeometryAsync(IFrame frame)
    {
        var parent = frame.ParentFrame;
        if (parent == null)
        {
            var (w, h) = await ViewportAsync().ConfigureAwait(false);
            return (0, 0, new Rect(0, 0, w, h));
        }
        var (px, py, pclip) = await FrameGeometryAsync(parent).ConfigureAwait(false);
        var box = (await OwnerCallAsync(frame, $"function () {{ return {WorldHelpers.Name}.ownerContent.call(this); }}").ConfigureAwait(false))!.Value;
        double ox = px + box.GetProperty("x").GetDouble(), oy = py + box.GetProperty("y").GetDouble();
        return (ox, oy, Rect.Intersect(pclip, new Rect(ox, oy, box.GetProperty("width").GetDouble(), box.GetProperty("height").GetDouble())));
    }

    /// <summary>Check that the viewport point hits each ancestor &lt;iframe&gt; owner.</summary>
    public async Task<string?> OwnersHitAsync(IFrame frame, double vx, double vy)
    {
        var child = frame;
        while (child.ParentFrame != null)
        {
            var (px, py, _) = await FrameGeometryAsync(child.ParentFrame).ConfigureAwait(false);
            var desc = await OwnerCallAsync(child,
                $"function (x, y) {{ const r = globalThis.{InjectedSource.Global}.expectHitTarget({{ x, y }}, this);" +
                " return r === 'done' ? null : r.hitTargetDescription; }", vx - px, vy - py).ConfigureAwait(false);
            if (desc is JsonElement d && d.ValueKind == JsonValueKind.String) return d.GetString();
            child = child.ParentFrame;
        }
        return null;
    }
}
