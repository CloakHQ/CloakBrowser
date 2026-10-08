using System.Reflection;
using System.Text.Json;
using Microsoft.Playwright;

namespace CloakBrowser.Human;

/// <summary>What an action is aimed at: a selector in a frame, or an element handle.</summary>
internal sealed class Target
{
    public Target(IFrame frame, string? selector, bool strict = false, IElementHandle? handle = null)
    {
        Frame = frame; Selector = selector; Strict = strict; Handle = handle;
        Description = selector != null ? $"locator({JsonSerializer.Serialize(selector)})" : "element handle";
    }

    public IFrame Frame { get; }
    public string? Selector { get; }
    public bool Strict { get; }
    public IElementHandle? Handle { get; }
    public string Description { get; set; }
}

internal readonly record struct Resolved(IFrame Frame, int Id);

internal sealed class Deadline
{
    private readonly long? _end;
    public Deadline(double timeoutMs)
    {
        Timeout = timeoutMs;
        _end = timeoutMs > 0 ? Environment.TickCount64 + (long)timeoutMs : null;
    }
    public double Timeout { get; }
    public double Remaining => _end == null ? double.PositiveInfinity : Math.Max(0, _end.Value - Environment.TickCount64);
    public bool Expired => _end != null && Environment.TickCount64 >= _end.Value;
}

/// <summary>Internal: the current attempt failed for a reason; retry until timeout.</summary>
internal sealed class RetryException : Exception
{
    public RetryException(string reason) : base(reason) { }
}

/// <summary>Options every humanized action understands (Playwright names + ours).</summary>
internal sealed class ActOpts
{
    public float? Timeout { get; set; }
    public bool Force { get; set; }
    public bool Trial { get; set; }
    public bool Strict { get; set; }
    public (double X, double Y)? Position { get; set; }
    public MouseButton? Button { get; set; }
    public int? ClickCount { get; set; }
    public float? Delay { get; set; }
    public IReadOnlyList<string>? Modifiers { get; set; }
    public (double X, double Y)? SourcePosition { get; set; }
    public (double X, double Y)? TargetPosition { get; set; }
    public IReadOnlyDictionary<string, object>? HumanConfig { get; set; }
    // internal
    public Deadline? Deadline { get; set; }
    public bool Nested { get; set; }
    public object[]? Aim { get; set; }

    public ActOpts With(Action<ActOpts> change)
    {
        var c = (ActOpts)MemberwiseClone();
        change(c);
        return c;
    }

    /// <summary>Read the Playwright options object of any action (they share property
    /// names but no base type).</summary>
    public static ActOpts From(object? o, IReadOnlyDictionary<string, object>? humanConfig = null)
    {
        var a = new ActOpts { HumanConfig = humanConfig };
        if (o == null) return a;
        object? P(string n) => o.GetType().GetProperty(n)?.GetValue(o);
        a.Timeout = P("Timeout") as float?;
        a.Force = P("Force") as bool? ?? false;
        a.Trial = P("Trial") as bool? ?? false;
        a.Strict = P("Strict") as bool? ?? false;
        a.Button = P("Button") as MouseButton?;
        a.ClickCount = P("ClickCount") as int?;
        a.Delay = P("Delay") as float?;
        if (P("Modifiers") is IEnumerable<KeyboardModifier> mods) a.Modifiers = mods.Select(m => m.ToString()).ToList();
        if (P("Position") is Position pos) a.Position = (pos.X, pos.Y);
        if (P("SourcePosition") is SourcePosition sp) a.SourcePosition = (sp.X, sp.Y);
        if (P("TargetPosition") is TargetPosition tp) a.TargetPosition = (tp.X, tp.Y);
        return a;
    }
}

internal sealed class Box
{
    public Rect Rect;
    public double Bl, Bt;
    public Rect Clip;
    public Rect Visible;
    public Rect? Scroller;
    public double X => Rect.X; public double Y => Rect.Y; public double Width => Rect.Width; public double Height => Rect.Height;
}

/// <summary>Original (un-humanized) input primitives of one page.</summary>
internal interface IRawInput
{
    Task MoveAsync(double x, double y, int? steps = null);
    Task DownAsync(MouseButton button = MouseButton.Left, int clickCount = 1);
    Task UpAsync(MouseButton button = MouseButton.Left, int clickCount = 1);
    Task WheelAsync(double dx, double dy);
    Task KeyDownAsync(string key);
    Task KeyUpAsync(string key);
    Task KeyPressAsync(string key, float? delay = null);
    Task InsertTextAsync(string text);
}

internal sealed class PlaywrightRawInput : IRawInput
{
    private readonly IMouse _m;
    private readonly IKeyboard _k;
    public PlaywrightRawInput(IMouse mouse, IKeyboard keyboard) { _m = mouse; _k = keyboard; }
    public Task MoveAsync(double x, double y, int? steps = null) =>
        _m.MoveAsync((float)x, (float)y, steps == null ? null : new MouseMoveOptions { Steps = steps });
    public Task DownAsync(MouseButton button = MouseButton.Left, int clickCount = 1) =>
        _m.DownAsync(new MouseDownOptions { Button = button, ClickCount = clickCount });
    public Task UpAsync(MouseButton button = MouseButton.Left, int clickCount = 1) =>
        _m.UpAsync(new MouseUpOptions { Button = button, ClickCount = clickCount });
    public Task WheelAsync(double dx, double dy) => _m.WheelAsync((float)dx, (float)dy);
    public Task KeyDownAsync(string key) => _k.DownAsync(key);
    public Task KeyUpAsync(string key) => _k.UpAsync(key);
    public Task KeyPressAsync(string key, float? delay = null) =>
        _k.PressAsync(key, delay == null ? null : new KeyboardPressOptions { Delay = delay });
    public Task InsertTextAsync(string text) => _k.InsertTextAsync(text);
}

/// <summary>Reads client-side Playwright .NET internals:
/// a locator's frame and selector string, and the page's default-timeout settings.</summary>
internal static class PlaywrightInternals
{
    private const BindingFlags Inst = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

    public static (IFrame Frame, string Selector) LocatorParts(ILocator locator)
    {
        var t = locator.GetType();
        var frame = t.GetField("_frame", Inst)?.GetValue(locator) as IFrame;
        var selector = t.GetField("_selector", Inst)?.GetValue(locator) as string;
        if (frame == null || selector == null)
            throw new PlaywrightException(
                $"cloakbrowser humanize: unsupported locator implementation {t.FullName}; Microsoft.Playwright layout changed");
        return (frame, selector);
    }

    /// <summary>Playwright's effective timeout for an action: the explicit option, else
    /// the page / context default, else 30 s. 0 means no limit.</summary>
    public static double Timeout(IFrame frame, float? explicitTimeout)
    {
        if (explicitTimeout != null) return explicitTimeout.Value;
        var page = frame.Page;
        var ts = page.GetType().GetField("_timeoutSettings", Inst)?.GetValue(page);
        var m = ts?.GetType().GetMethod("Timeout", Inst, null, new[] { typeof(float?) }, null);
        if (m != null) return Convert.ToDouble(m.Invoke(ts, new object?[] { null }));
        return 30000;
    }

    public static IFrame HandleFrame(IElementHandle handle)
    {
        // An ElementHandle's parent object is its frame.
        var parent = handle.GetType().GetProperty("Parent", Inst)?.GetValue(handle);
        return parent as IFrame
            ?? throw new PlaywrightException("cloakbrowser humanize: cannot determine the frame of this element handle");
    }

    public static string HandleGuid(IElementHandle handle) =>
        handle.GetType().GetProperty("Guid", Inst)?.GetValue(handle) as string ?? handle.GetHashCode().ToString();
}

/// <summary>
/// Unified humanized action pipeline. Port of <c>cloakbrowser/human/engine.py</c>
/// (and <c>js/src/human/engine.ts</c>).
///
/// One implementation drives page / frame / locator / element-handle actions:
/// resolve (isolated world, Playwright selector engine, strict mode) -> wait for element
/// states -> scroll into view with mouse-wheel bursts (page, iframes, containers) ->
/// Bezier move to a point inside the visible part of the element -> hit-target check
/// (element and every ancestor iframe) -> press / type. Nothing falls back to
/// Playwright's stock actions, and failures throw
/// <see cref="PlaywrightException"/> / <see cref="System.TimeoutException"/>.
/// </summary>
internal sealed partial class HumanEngine
{
    // Microsoft.Playwright .NET joins FrameLocator parts with an extra space
    // ("enter-frame  >> "), so split on the marker with any surrounding whitespace.
    private static readonly System.Text.RegularExpressions.Regex EnterFrameSplit =
        new(@"\s*>>\s*internal:control=enter-frame\s*>>\s*", System.Text.RegularExpressions.RegexOptions.Compiled);
    private static readonly string[] ClickStates = { "visible", "enabled", "stable" };
    private static readonly string[] HoverStates = { "visible", "stable" };
    private static readonly string[] InputStates = { "visible", "enabled", "editable" };
    private static readonly string[] FocusStates = { "visible", "enabled" };
    private static readonly int[] RetryMs = { 0, 20, 100, 100, 500 };

    private readonly IPage _page;
    private readonly IRawInput _raw;
    private string? _platform;
    private readonly Dictionary<string, (IFrame Frame, int Ctx, int Id)> _handleIds = new();

    public HumanEngine(IPage page, HumanConfig cfg, CursorPosition cursor, IRawInput? raw = null)
    {
        _page = page;
        Config = cfg;
        Cursor = cursor;
        _raw = raw ?? new PlaywrightRawInput(page.Mouse, page.Keyboard);
        World = new HumanWorld(page);
    }

    public HumanConfig Config { get; }
    public CursorPosition Cursor { get; }
    public HumanWorld World { get; }
    public IPage Page => _page;

    private static Task Sleep(double ms) => ms > 0 ? Task.Delay(TimeSpan.FromMilliseconds(ms)) : Task.CompletedTask;
    private static double R(double lo, double hi) => HumanRandom.Rand(lo, hi);
    private static double RR(Range r) => HumanRandom.RandRange(r);

    public HumanConfig CallCfg(IReadOnlyDictionary<string, object>? overrides) =>
        overrides == null || overrides.Count == 0 ? Config : Config.With(overrides);

    public Deadline DeadlineFor(Target t, ActOpts o) =>
        o.Deadline ?? new Deadline(PlaywrightInternals.Timeout(t.Frame, o.Timeout));

    private static PlaywrightException Err(string msg) => new(msg);

    // -- persona ------------------------------------------------------------

    public async Task<string> PlatformAsync()
    {
        if (_platform == null)
        {
            try { _platform = (await World.CallAsync(_page.MainFrame, "platform").ConfigureAwait(false))?.GetString() ?? ""; }
            catch (PlaywrightException) { _platform = ""; }
        }
        return _platform;
    }

    public async Task<bool> IsMacAsync() => (await PlatformAsync().ConfigureAwait(false)).StartsWith("mac", StringComparison.OrdinalIgnoreCase);
    public async Task<string> SelectAllKeyAsync() => await IsMacAsync().ConfigureAwait(false) ? "Meta+a" : "Control+a";

    private async Task<string> ModifierAsync(string key) =>
        key == "ControlOrMeta" ? (await IsMacAsync().ConfigureAwait(false) ? "Meta" : "Control") : key;

    private async Task<string> KeysAsync(string key) =>
        key.Contains("ControlOrMeta") ? key.Replace("ControlOrMeta", await ModifierAsync("ControlOrMeta").ConfigureAwait(false)) : key;

    // -- cursor -------------------------------------------------------------

    public async Task EnsureCursorAsync(HumanConfig? cfg = null)
    {
        if (Cursor.Initialized) return;
        var c = cfg ?? Config;
        Cursor.X = RR(c.InitialCursorX);
        Cursor.Y = RR(c.InitialCursorY);
        await _raw.MoveAsync(Cursor.X, Cursor.Y).ConfigureAwait(false);
        Cursor.Initialized = true;
    }

    /// <summary>Bezier move from the current cursor position to (x, y), ending exactly there.</summary>
    public async Task MoveToAsync(double x, double y, HumanConfig cfg)
    {
        await EnsureCursorAsync(cfg).ConfigureAwait(false);
        double sx = Cursor.X, sy = Cursor.Y;
        double dist = Math.Sqrt((x - sx) * (x - sx) + (y - sy) * (y - sy));
        if (dist >= 1)
        {
            int steps = (int)Math.Max(cfg.MouseMinSteps, Math.Min(cfg.MouseMaxSteps, Math.Round(dist / cfg.MouseStepsDivisor)));
            var (cp1, cp2) = HumanMouse.RandomControlPoints(new Point(sx, sy), new Point(x, y));
            int burst = 0, burstSize = HumanRandom.RandIntRange(cfg.MouseBurstSize);
            for (int i = 1; i <= steps; i++)
            {
                double progress = (double)i / steps;
                if (i == steps) { await _raw.MoveAsync(x, y).ConfigureAwait(false); continue; }
                var pt = HumanMouse.Bezier(new Point(sx, sy), cp1, cp2, new Point(x, y), HumanMouse.EaseInOut(progress));
                double wobble = Math.Sin(Math.PI * progress) * cfg.MouseWobbleMax;
                await _raw.MoveAsync(Math.Round(pt.X + (HumanRandom.NextDouble() - 0.5) * 2 * wobble),
                    Math.Round(pt.Y + (HumanRandom.NextDouble() - 0.5) * 2 * wobble)).ConfigureAwait(false);
                if (++burst >= burstSize) { await Sleep(RR(cfg.MouseBurstPause)).ConfigureAwait(false); burst = 0; }
            }
            if (HumanRandom.NextDouble() < cfg.MouseOvershootChance)
            {
                double angle = Math.Atan2(y - sy, x - sx), over = RR(cfg.MouseOvershootPx);
                await _raw.MoveAsync(Math.Round(x + Math.Cos(angle) * over), Math.Round(y + Math.Sin(angle) * over)).ConfigureAwait(false);
                await Sleep(R(30, 70)).ConfigureAwait(false);
                await _raw.MoveAsync(x, y).ConfigureAwait(false);
            }
        }
        Cursor.X = x; Cursor.Y = y;
    }

    public async Task IdleAsync(HumanConfig cfg)
    {
        if (!cfg.IdleBetweenActions) return;
        await EnsureCursorAsync(cfg).ConfigureAwait(false);
        long end = Environment.TickCount64 + (long)(R(cfg.IdleBetweenDuration.Min, cfg.IdleBetweenDuration.Max) * 1000);
        double x = Cursor.X, y = Cursor.Y;
        while (Environment.TickCount64 < end)
        {
            x += (HumanRandom.NextDouble() - 0.5) * 2 * cfg.IdleDriftPx;
            y += (HumanRandom.NextDouble() - 0.5) * 2 * cfg.IdleDriftPx;
            await _raw.MoveAsync(Math.Round(x), Math.Round(y)).ConfigureAwait(false);
            await Sleep(Math.Min(RR(cfg.IdlePauseRange), Math.Max(0, end - Environment.TickCount64))).ConfigureAwait(false);
        }
        await _raw.MoveAsync(Cursor.X, Cursor.Y).ConfigureAwait(false); // drift is noise, not a new position
    }

    // -- resolution ---------------------------------------------------------

    /// <summary>Resolve once. Throws <see cref="RetryException"/> (not yet there) or a final error.</summary>
    public async Task<Resolved> ResolveAsync(Target t)
    {
        if (t.Handle != null) return await ResolveHandleAsync(t.Handle).ConfigureAwait(false);
        var frame = t.Frame;
        var parts = EnterFrameSplit.Split(t.Selector!);
        for (int i = 0; i < parts.Length; i++)
        {
            var res = (await World.CallAsync(frame, "resolve", parts[i], t.Strict, 0).ConfigureAwait(false))!.Value;
            var status = res.GetProperty("status").GetString();
            if (status == "none") throw new RetryException($"waiting for {t.Description}");
            if (status is "strict" or "error") throw Err(res.GetProperty("message").GetString() ?? status);
            int id = res.GetProperty("id").GetInt32();
            if (i == parts.Length - 1) return new Resolved(frame, id);
            frame = await World.ContentFrameAsync(frame, id).ConfigureAwait(false)
                ?? throw new RetryException($"waiting for the frame of {t.Description}");
        }
        throw Err("unreachable");
    }

    public async Task<Resolved> ResolveHandleAsync(IElementHandle handle)
    {
        var frame = PlaywrightInternals.HandleFrame(handle);
        var guid = PlaywrightInternals.HandleGuid(handle);
        // Element ids are local to one isolated world, and a new document gets a new
        // world: an id cached before a navigation may now name a different element.
        int ctx = await World.ContextIdAsync(frame).ConfigureAwait(false);
        if (_handleIds.TryGetValue(guid, out var cached) && cached.Frame == frame && cached.Ctx == ctx &&
            await World.CallAsync(frame, "connected", cached.Id).ConfigureAwait(false) is { ValueKind: JsonValueKind.True })
            return new Resolved(frame, cached.Id);
        // An ElementHandle carries no identity our context can read, so find the element
        // with exactly its border box.
        var box = await handle.BoundingBoxAsync().ConfigureAwait(false);
        if (box == null)
        {
            // Resolved in an earlier document of this frame and gone now
            // (a same-document navigation keeps the element, and its box).
            if (_handleIds.TryGetValue(guid, out var old) && old.Frame == frame) throw Err("Element is not attached to the DOM");
            throw new RetryException("element is not visible");
        }
        var (ox, oy, _) = await World.FrameGeometryAsync(frame).ConfigureAwait(false);
        var res = (await World.CallAsync(frame, "matchRect", box.X - ox, box.Y - oy, box.Width, box.Height).ConfigureAwait(false))!.Value;
        if (res.GetProperty("count").GetInt32() != 1)
            throw Err("cloakbrowser humanize: cannot identify the element behind this ElementHandle inside the isolated " +
                      "world (it shares its box with another element); use a Locator instead");
        int id = res.GetProperty("id").GetInt32();
        _handleIds[guid] = (frame, ctx, id);
        return new Resolved(frame, id);
    }

    public Task<Resolved> WaitForAsync(Target t, string[] states, Deadline d, string api, bool force = false) =>
        RetryAsync(api, t, d, () => AttemptStatesAsync(t, states, force));

    public async Task<Resolved> AttemptStatesAsync(Target t, string[] states, bool force)
    {
        var r = await ResolveAsync(t).ConfigureAwait(false);
        if (force) return r;
        var res = await World.CallAsync(r.Frame, "states", r.Id, states).ConfigureAwait(false);
        if (res == null || res.Value.ValueKind == JsonValueKind.Null) return r;
        if (res.Value.TryGetProperty("error", out var e)) throw Err(e.GetString() ?? "state check failed");
        var missing = res.Value.GetProperty("missing").GetString();
        if (missing == "attached")
        {
            if (t.Handle != null) throw Err("Element is not attached to the DOM");
            throw new RetryException("element was detached from the DOM, retrying");
        }
        throw new RetryException($"element is not {missing}");
    }

    public async Task<T> RetryAsync<T>(string api, Target t, Deadline d, Func<Task<T>> attempt)
    {
        var reasons = new List<string>();
        void Note(string r) { if (reasons.Count == 0 || reasons[^1] != r) reasons.Add(r); }
        for (int n = 0; ; n++)
        {
            try
            {
                return await attempt().ConfigureAwait(false);
            }
            catch (StaleElementException)
            {
                if (t.Handle != null) throw Err($"{api}: Element is not attached to the DOM");
                Note("element was detached from the DOM, retrying");
            }
            catch (RetryException r)
            {
                Note(r.Message);
            }
            catch (PlaywrightException e) when (!e.Message.StartsWith(api, StringComparison.Ordinal))
            {
                throw new PlaywrightException($"{api}: {e.Message}", e);
            }
            if (d.Expired)
            {
                var log = string.Join("\n", new[] { $"waiting for {t.Description}" }.Concat(reasons.TakeLast(5)).Select(r => $"  - {r}"));
                throw new System.TimeoutException($"{api}: Timeout {Math.Round(d.Timeout)}ms exceeded.\nCall log:\n{log}");
            }
            await Sleep(Math.Min(RetryMs[Math.Min(n, RetryMs.Length - 1)], d.Remaining)).ConfigureAwait(false);
        }
    }

    public Task RetryAsync(string api, Target t, Deadline d, Func<Task> attempt) =>
        RetryAsync<bool>(api, t, d, async () => { await attempt().ConfigureAwait(false); return true; });

    // -- geometry -----------------------------------------------------------

    private static double D(JsonElement e, string p) => e.GetProperty(p).GetDouble();

    /// <summary>Element border box in viewport coordinates plus its visible clip.</summary>
    public async Task<Box> ElementBoxAsync(Resolved r)
    {
        var g = await World.CallAsync(r.Frame, "geometry", r.Id).ConfigureAwait(false);
        if (g == null || g.Value.ValueKind == JsonValueKind.Null) throw new StaleElementException();
        var (ox, oy, clip) = await World.FrameGeometryAsync(r.Frame).ConfigureAwait(false);
        var gv = g.Value;
        var box = new Box
        {
            Rect = new Rect(D(gv, "x") + ox, D(gv, "y") + oy, D(gv, "width"), D(gv, "height")),
            Bl = D(gv, "bl"), Bt = D(gv, "bt"),
        };
        var sc = await World.CallAsync(r.Frame, "scroller", r.Id).ConfigureAwait(false);
        if (sc is JsonElement s && s.ValueKind == JsonValueKind.Object)
        {
            var srect = new Rect(D(s, "x") + ox, D(s, "y") + oy, D(s, "width"), D(s, "height"));
            clip = Rect.Intersect(clip, srect);
            box.Scroller = srect;
        }
        box.Clip = clip;
        box.Visible = Rect.Intersect(clip, box.Rect);
        return box;
    }

    // -- scrolling ----------------------------------------------------------

    /// <summary>Wheel-scroll until the element sits inside its visible clip (and, for the
    /// main document, inside <c>ScrollTargetZone</c> when the page can still scroll that way).</summary>
    public async Task<Box> ScrollIntoViewAsync(Resolved r, HumanConfig cfg, Deadline d)
    {
        var box = await ElementBoxAsync(r).ConfigureAwait(false);
        var (vw, vh) = await World.ViewportAsync().ConfigureAwait(false);
        int stalled = 0, rounds = 0;
        bool overshot = false;
        while (stalled < 2 && rounds < 40 && !d.Expired)
        {
            var (dx, dy) = await NeededScrollAsync(r, box, vw, vh, cfg).ConfigureAwait(false);
            if (Math.Abs(dx) < 1 && Math.Abs(dy) < 1) break;
            rounds++;
            var area = box.Clip.Width > 4 && box.Clip.Height > 4 ? box.Clip : new Rect(0, 0, vw, vh);
            if (!area.Contains(Cursor.X, Cursor.Y))
            {
                await MoveToAsync(area.X + area.Width * R(0.3, 0.7), area.Y + area.Height * R(0.3, 0.7), cfg).ConfigureAwait(false);
                await Sleep(RR(cfg.ScrollPreMoveDelay)).ConfigureAwait(false);
            }
            double bx = box.X, by = box.Y;
            if (Math.Abs(dy) >= 1)
            {
                await WheelBurstAsync(0, dy, cfg, d).ConfigureAwait(false);
                if (!overshot)
                {
                    overshot = true;
                    await OvershootAsync(dy, cfg, d).ConfigureAwait(false);
                }
            }
            if (Math.Abs(dx) >= 1) await WheelBurstAsync(dx, 0, cfg, d).ConfigureAwait(false);
            await Sleep(Math.Min(RR(cfg.ScrollSettleDelay), d.Remaining)).ConfigureAwait(false);
            box = await ElementBoxAsync(r).ConfigureAwait(false);
            stalled = Math.Abs(box.X - bx) + Math.Abs(box.Y - by) < 1 ? stalled + 1 : 0;
        }
        return box;
    }

    private async Task<(double Dx, double Dy)> NeededScrollAsync(Resolved r, Box box, double vw, double vh, HumanConfig cfg)
    {
        var clip = box.Clip;
        if (clip.Width <= 0 || clip.Height <= 0)
            return (0, box.Y + box.Height / 2 - vh / 2); // the frame/container itself is out of view
        double dx = 0, dy = 0, top = box.Y, bottom = box.Y + box.Height;
        var zone = cfg.ScrollTargetZone;
        bool mainDoc = r.Frame.ParentFrame == null && box.Scroller == null;
        if (mainDoc && box.Height <= vh * (zone.Max - zone.Min))
        {
            if (top < vh * zone.Min || bottom > vh * zone.Max)
            {
                dy = top + box.Height / 2 - vh * R(zone.Min, zone.Max);
                if (top >= clip.Y - 1 && bottom <= clip.Y + clip.Height + 1)
                {
                    // Fully visible but off-centre: only if the page can scroll that way.
                    var doc = (await World.CallAsync(_page.MainFrame, "doc").ConfigureAwait(false))!.Value;
                    if ((dy < 0 && D(doc, "y") <= 0) || (dy > 0 && D(doc, "y") >= D(doc, "maxY"))) dy = 0;
                }
            }
        }
        else if (box.Height <= clip.Height)
        {
            if (top < clip.Y - 1 || bottom > clip.Y + clip.Height + 1) dy = top + box.Height / 2 - (clip.Y + clip.Height / 2);
        }
        else if (box.Visible.Height < clip.Height * 0.5)
        {
            dy = top - clip.Y - clip.Height * 0.1;
        }
        // Horizontal (#521): containment only.
        double left = box.X, right = box.X + box.Width;
        if (box.Width <= clip.Width)
        {
            if (left < clip.X - 1 || right > clip.X + clip.Width + 1) dx = left + box.Width / 2 - (clip.X + clip.Width / 2);
        }
        else if (box.Visible.Width <= 0)
        {
            dx = left - clip.X;
        }
        return (dx, dy);
    }

    /// <summary>Sometimes scroll a little past the target, pause, and wheel back
    /// (<c>ScrollOvershootChance</c> / <c>ScrollOvershootPx</c>). The next round of
    /// <see cref="ScrollIntoViewAsync"/> fixes whatever is left.</summary>
    private async Task OvershootAsync(double dy, HumanConfig cfg, Deadline d)
    {
        if (HumanRandom.NextDouble() >= cfg.ScrollOvershootChance || d.Expired) return;
        int sign = dy > 0 ? 1 : -1;
        await WheelBurstAsync(0, Math.Round(RR(cfg.ScrollOvershootPx)) * sign, cfg, d).ConfigureAwait(false);
        await Sleep(Math.Min(RR(cfg.ScrollSettleDelay), d.Remaining)).ConfigureAwait(false);
        int corrections = HumanRandom.RandInt(1, 2);
        for (int i = 0; i < corrections && !d.Expired; i++)
        {
            await WheelBurstAsync(0, Math.Round(R(40, 80)) * -sign, cfg, d).ConfigureAwait(false);
            await Sleep(Math.Min(R(100, 250), d.Remaining)).ConfigureAwait(false);
        }
    }

    /// <summary>One logical scroll: accelerate -> cruise -> decelerate in wheel ticks.</summary>
    public async Task WheelBurstAsync(double dx, double dy, HumanConfig cfg, Deadline? d = null)
    {
        double total = dy != 0 ? Math.Abs(dy) : Math.Abs(dx);
        int sign = (dy != 0 ? dy : dx) > 0 ? 1 : -1;
        int accel = HumanRandom.RandIntRange(cfg.ScrollAccelSteps), decel = HumanRandom.RandIntRange(cfg.ScrollDecelSteps);
        double avg = (cfg.ScrollDeltaBase.Min + cfg.ScrollDeltaBase.Max) / 2;
        int ticks = Math.Max(1, (int)Math.Ceiling(total / avg));
        double sent = 0;
        for (int i = 0; i < ticks; i++)
        {
            if (sent >= total || (d?.Expired ?? false)) break;
            double pause = i < accel || i >= ticks - decel ? RR(cfg.ScrollPauseSlow) : RR(cfg.ScrollPauseFast);
            double tick = Math.Min(total - sent, RR(cfg.ScrollDeltaBase) * (1 + (HumanRandom.NextDouble() - 0.5) * 2 * cfg.ScrollDeltaVariance));
            double left = tick;
            while (left > 0.5)
            {
                double chunk = Math.Min(left, R(20, 40));
                double step = Math.Round(chunk) * sign;
                if (step != 0) await _raw.WheelAsync(dx != 0 ? step : 0, dy != 0 ? step : 0).ConfigureAwait(false);
                left -= chunk;
                await Sleep(R(8, 20)).ConfigureAwait(false);
            }
            sent += tick;
            await Sleep(pause).ConfigureAwait(false);
        }
    }

    // -- pointer ------------------------------------------------------------

    private static (double X, double Y) PointIn(Box box, (double X, double Y)? position, bool isInput, HumanConfig cfg)
    {
        if (position is { } p) return (box.X + box.Bl + p.X, box.Y + box.Bt + p.Y);
        var vis = box.Visible;
        if (vis.Width <= 0 || vis.Height <= 0) throw new RetryException("element is outside of the viewport");
        var full = HumanMouse.ClickTarget(new BoundingBox(box.X, box.Y, box.Width, box.Height), isInput, cfg);
        return (Math.Min(Math.Max(full.X, vis.X + 1), vis.X + vis.Width - 1),
                Math.Min(Math.Max(full.Y, vis.Y + 1), vis.Y + vis.Height - 1));
    }

    /// <summary>Exact aim points: a date-editor segment, or a fraction along a slider.</summary>
    private static (double X, double Y) AimPoint(Box box, object[] aim)
    {
        double x, y;
        if ((string)aim[0] == "segment")
        {
            var seg = (EditorField)aim[1];
            x = box.X + seg.Dx + R(-2, 2); y = box.Y + seg.Dy + R(-2, 2);
        }
        else
        {
            double frac = (double)aim[1]; bool vertical = (bool)aim[2];
            if (vertical)
            {
                double inset = Math.Min(8, box.Height / 4);
                y = box.Y + box.Height - inset - frac * (box.Height - 2 * inset); x = box.X + box.Width / 2;
            }
            else
            {
                double inset = Math.Min(8, box.Width / 4);
                x = box.X + inset + frac * (box.Width - 2 * inset); y = box.Y + box.Height / 2 + R(-1.5, 1.5);
            }
        }
        if (!box.Visible.Contains(x, y)) throw new RetryException("element is outside of the viewport");
        return (x, y);
    }

    internal async Task HitAsync(Resolved r, double x, double y)
    {
        var (ox, oy, clip) = await World.FrameGeometryAsync(r.Frame).ConfigureAwait(false);
        if (!clip.Contains(x, y)) throw new RetryException("element is outside of the viewport");
        var desc = await World.CallAsync(r.Frame, "hit", r.Id, x - ox, y - oy).ConfigureAwait(false);
        string? d = desc is { ValueKind: JsonValueKind.String } s ? s.GetString() : null;
        if (d == null && r.Frame.ParentFrame != null) d = await World.OwnersHitAsync(r.Frame, x, y).ConfigureAwait(false);
        if (d != null) throw new RetryException($"{d} intercepts pointer events");
    }

    private async Task<bool> IsInputAsync(Resolved r)
    {
        var info = (await World.CallAsync(r.Frame, "info", r.Id).ConfigureAwait(false))!.Value;
        var tag = info.GetProperty("tag").GetString();
        return tag is "input" or "textarea" || info.GetProperty("editable").GetBoolean();
    }

    public delegate Task PointerAct(Resolved r, double x, double y, HumanConfig cfg);

    /// <summary>Shared scroll -> move -> hit-check -> action sequence. <paramref name="hold"/>:
    /// modifier names held down while the cursor travels to the target (Playwright's hover
    /// modifiers).</summary>
    public async Task<Resolved> PointerActionAsync(string api, Target t, ActOpts o, string[] states,
        bool? isInputHint = null, PointerAct? action = null, IReadOnlyList<string>? hold = null)
    {
        var cfg = CallCfg(o.HumanConfig);
        var d = DeadlineFor(t, o);
        await EnsureCursorAsync(cfg).ConfigureAwait(false);
        if (!(o.Nested || o.Deadline != null)) await IdleAsync(cfg).ConfigureAwait(false);
        return await RetryAsync(api, t, d, async () =>
        {
            var r = await AttemptStatesAsync(t, states, o.Force).ConfigureAwait(false);
            var box = await ScrollIntoViewAsync(r, cfg, d).ConfigureAwait(false);
            bool isInput = isInputHint ?? await IsInputAsync(r).ConfigureAwait(false);
            var (x, y) = o.Aim != null ? AimPoint(box, o.Aim) : PointIn(box, o.Position, isInput, cfg);
            if (!o.Force) await HitAsync(r, x, y).ConfigureAwait(false);
            if (o.Trial) return r;
            var keys = new List<string>();
            foreach (var m in hold ?? Array.Empty<string>()) keys.Add(await ModifierAsync(m).ConfigureAwait(false));
            foreach (var k in keys) await _raw.KeyDownAsync(k).ConfigureAwait(false);
            try
            {
                await MoveToAsync(x, y, cfg).ConfigureAwait(false);
            }
            finally
            {
                for (int i = keys.Count - 1; i >= 0; i--) await _raw.KeyUpAsync(keys[i]).ConfigureAwait(false);
            }
            // The page may replace or remove the target while the cursor travels; never
            // press on whatever is under it now (even with force). Locators re-resolve.
            if (await World.CallAsync(r.Frame, "connected", r.Id).ConfigureAwait(false) is not { ValueKind: JsonValueKind.True })
                throw new StaleElementException();
            if (!o.Force) await HitAsync(r, Cursor.X, Cursor.Y).ConfigureAwait(false);
            if (action != null) await action(r, Cursor.X, Cursor.Y, cfg).ConfigureAwait(false);
            return r;
        }).ConfigureAwait(false);
    }

    public async Task PressMouseAsync(HumanConfig cfg, bool isInput, MouseButton button = MouseButton.Left,
        int clickCount = 1, float? delay = null, IReadOnlyList<string>? modifiers = null)
    {
        var mods = new List<string>();
        foreach (var m in modifiers ?? Array.Empty<string>()) mods.Add(await ModifierAsync(m).ConfigureAwait(false));
        await Sleep(RR(isInput ? cfg.ClickAimDelayInput : cfg.ClickAimDelayButton)).ConfigureAwait(false);
        foreach (var m in mods) await _raw.KeyDownAsync(m).ConfigureAwait(false);
        try
        {
            int count = Math.Max(1, clickCount);
            for (int n = 1; n <= count; n++)
            {
                double hold = delay ?? RR(isInput ? cfg.ClickHoldInput : cfg.ClickHoldButton);
                await _raw.DownAsync(button, n).ConfigureAwait(false);
                await Sleep(hold).ConfigureAwait(false);
                await _raw.UpAsync(button, n).ConfigureAwait(false);
                if (n < count) await Sleep(delay ?? R(60, 140)).ConfigureAwait(false);
            }
        }
        finally
        {
            for (int i = mods.Count - 1; i >= 0; i--) await _raw.KeyUpAsync(mods[i]).ConfigureAwait(false);
        }
    }
}

/// <summary>Shared virtual cursor position of one page.</summary>
internal sealed class CursorPosition
{
    public double X;
    public double Y;
    public bool Initialized;
}
