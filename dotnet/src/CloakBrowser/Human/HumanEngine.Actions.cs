using System.Text.Json;
using Microsoft.Playwright;

namespace CloakBrowser.Human;

/// <summary>Public actions of the unified engine (port of the action half of
/// <c>cloakbrowser/human/engine.py</c>).</summary>
internal sealed partial class HumanEngine
{
    private static MouseButton Btn(ActOpts o) => o.Button ?? MouseButton.Left;

    public async Task ClickAsync(Target t, ActOpts o, string api, int? clickCount = null)
    {
        int count = clickCount ?? o.ClickCount ?? 1;
        await PointerActionAsync(api, t, o, ClickStates, null, async (r, _, _, cfg) =>
        {
            bool isInput = await IsInputAsync(r).ConfigureAwait(false);
            await PressMouseAsync(cfg, isInput, Btn(o), count, o.Delay, o.Modifiers).ConfigureAwait(false);
        }).ConfigureAwait(false);
    }

    public async Task HoverAsync(Target t, ActOpts o, string api)
    {
        // Playwright holds the modifiers while the mouse moves onto the target.
        await PointerActionAsync(api, t, o, HoverStates, false, hold: o.Modifiers).ConfigureAwait(false);
    }

    public Task TapAsync(Target t, ActOpts o, string api) => ClickAsync(t, o.With(c => c.ClickCount = 1), api);

    private async Task<JsonElement> InfoAsync(Resolved r) =>
        (await World.CallAsync(r.Frame, "info", r.Id).ConfigureAwait(false))!.Value;

    private static string? S(JsonElement e, string p) =>
        e.TryGetProperty(p, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null;

    /// <summary>
    /// Focus by a human click unless already focused. Returns (r, clickedIn): clickedIn is
    /// true when this call clicked and focus landed in the target. With
    /// <paramref name="requireFocus"/> false (press / type) a click that does not move focus
    /// is fine, as in Playwright: the keys go to whatever handles them (a &lt;canvas&gt;,
    /// document-level key handlers).
    /// </summary>
    public async Task<(Resolved R, bool Clicked)> FocusElementAsync(Target t, ActOpts o, string api, Deadline d,
        bool requireFocus = true)
    {
        var r = await WaitForAsync(t, FocusStates, d, api, o.Force).ConfigureAwait(false);
        var info = await InfoAsync(r).ConfigureAwait(false);
        if (info.GetProperty("focused").GetBoolean()) return (r, false);
        // A person focuses a field by clicking it: scroll it into view with the wheel and
        // click. When it cannot be brought on screen at all the click times out with
        // "element is outside of the viewport" -- no silent programmatic focus.
        await ClickAsync(t, new ActOpts { Deadline = d, Force = o.Force, HumanConfig = o.HumanConfig }, api).ConfigureAwait(false);
        info = await InfoAsync(r).ConfigureAwait(false);
        if (info.GetProperty("focused").GetBoolean() || await FocusMovedIntoAsync(r).ConfigureAwait(false))
            return (r, true);
        if (requireFocus)
            throw Err($"{api}: Error: element did not receive focus when clicked (it may not be focusable): {S(info, "preview")}");
        return (r, false);
    }

    private async Task<bool> FocusMovedIntoAsync(Resolved r)
    {
        var act = await World.CallAsync(r.Frame, "activeValue").ConfigureAwait(false);
        if (act is not JsonElement a || S(a, "tag") == null) return false;
        var v = await World.EvaluateAsync(r.Frame,
            $"(() => {{ const e = {WorldHelpers.Name}.el({r.Id}); const a = document.activeElement; return !!a && (e === a || e.contains(a)); }})()").ConfigureAwait(false);
        return v is { ValueKind: JsonValueKind.True };
    }

    public async Task CaretToEndAsync(Resolved r)
    {
        var info = await InfoAsync(r).ConfigureAwait(false);
        if (S(info, "tag") == "input")
        {
            if (await World.CallAsync(r.Frame, "caretAtEnd", r.Id).ConfigureAwait(false) is not { ValueKind: JsonValueKind.True })
                await _raw.KeyPressAsync("End").ConfigureAwait(false);
        }
        else
        {
            await _raw.KeyPressAsync("Control+End").ConfigureAwait(false);
        }
        await Sleep(R(20, 60)).ConfigureAwait(false);
    }

    public async Task PressAsync(Target t, string key, ActOpts o, string api)
    {
        var d = DeadlineFor(t, o);
        await FocusElementAsync(t, o, api, d, requireFocus: false).ConfigureAwait(false);
        await Sleep(R(50, 150)).ConfigureAwait(false);
        await _raw.KeyPressAsync(await KeysAsync(key).ConfigureAwait(false), o.Delay).ConfigureAwait(false);
    }

    public async Task TypeAsync(Target t, string text, ActOpts o, string api)
    {
        var cfg = CallCfg(o.HumanConfig);
        var d = DeadlineFor(t, o);
        await Sleep(RR(cfg.FieldSwitchDelay)).ConfigureAwait(false);
        var (r, clicked) = await FocusElementAsync(t, o, api, d, requireFocus: false).ConfigureAwait(false);
        if (clicked) await CaretToEndAsync(r).ConfigureAwait(false);
        await Sleep(R(100, 250)).ConfigureAwait(false);
        await TypeTextAsync(text, cfg, r.Frame, await InfoAsync(r).ConfigureAwait(false), o.Delay).ConfigureAwait(false);
    }

    public async Task FillAsync(Target t, string value, ActOpts o, string api)
    {
        var cfg = CallCfg(o.HumanConfig);
        var d = DeadlineFor(t, o);
        var r = await WaitForAsync(t, InputStates, d, api, o.Force).ConfigureAwait(false);
        var info = await InfoAsync(r).ConfigureAwait(false);
        string? tag = S(info, "tag"), type = S(info, "type");
        var kind = Fields.Classify(tag, type, info.GetProperty("editable").GetBoolean());
        if (kind == Fields.Kind.NotFillable) throw Err($"{api}: Error: {Fields.NotFillableMessage(tag, type)}");
        if (type == "number")
            value = Fields.ValidateNumber(value) ?? throw Err($"{api}: Error: Cannot type text into input[type=number]");
        if (kind == Fields.Kind.Set)
        {
            value = Fields.NormalizeSetValue(type, value);
            await Sleep(RR(cfg.FieldSwitchDelay)).ConfigureAwait(false);
            if (type == "range") await SetRangeAsync(t, r, value, o, api, d).ConfigureAwait(false);
            else if (type == "color")
                throw Err($"{api}: Error: <input type=color> opens a native colour picker that cannot be operated with " +
                          "human input; set it on the original page (Humanize.Unwrap(page).FillAsync) if a programmatic value is acceptable");
            else await SetDateTimeAsync(t, r, type!, value, o, api, cfg, d).ConfigureAwait(false);
            return;
        }
        await Sleep(RR(cfg.FieldSwitchDelay)).ConfigureAwait(false);
        (r, _) = await FocusElementAsync(t, o, api, d).ConfigureAwait(false);
        await Sleep(R(100, 250)).ConfigureAwait(false);
        info = await InfoAsync(r).ConfigureAwait(false);
        if (!string.IsNullOrEmpty(S(info, "value")))
        {
            await _raw.KeyPressAsync(await SelectAllKeyAsync().ConfigureAwait(false)).ConfigureAwait(false);
            await Sleep(R(30, 80)).ConfigureAwait(false);
            await _raw.KeyPressAsync("Backspace").ConfigureAwait(false);
            await Sleep(R(50, 150)).ConfigureAwait(false);
            info = await InfoAsync(r).ConfigureAwait(false);
            var left = S(info, "value");
            if (!string.IsNullOrEmpty(left))
            {
                // Some widgets ignore select-all; clear what is left by keys.
                await CaretToEndAsync(r).ConfigureAwait(false);
                for (int i = 0; i < left.Length; i++)
                {
                    await _raw.KeyPressAsync("Backspace").ConfigureAwait(false);
                    await Sleep(R(15, 40)).ConfigureAwait(false);
                }
            }
        }
        if (value.Length > 0) await TypeTextAsync(value, cfg, r.Frame, info, null).ConfigureAwait(false);
    }

    public async Task SetCheckedAsync(Target t, bool want, ActOpts o, string api)
    {
        var d = DeadlineFor(t, o);
        var r = await WaitForAsync(t, ClickStates, d, api, o.Force).ConfigureAwait(false);
        var state = (await World.CallAsync(r.Frame, "checked", r.Id).ConfigureAwait(false))!.Value;
        if (state.TryGetProperty("error", out var e)) throw Err($"{api}: Error: {e.GetString()}");
        if (state.GetProperty("checked").GetBoolean() == want) return;
        if (state.GetProperty("radio").GetBoolean() && !want)
            throw Err($"{api}: Error: Cannot uncheck radio button. Radio buttons can only be unchecked by selecting another radio button in the same group.");
        await ClickAsync(t, new ActOpts { Force = o.Force, Position = o.Position, Trial = o.Trial, HumanConfig = o.HumanConfig, Deadline = d }, api).ConfigureAwait(false);
        if (o.Trial) return;
        state = (await World.CallAsync(r.Frame, "checked", r.Id).ConfigureAwait(false))!.Value;
        if (!state.TryGetProperty("checked", out var c) || c.GetBoolean() != want)
            throw Err($"{api}: Error: Clicking the checkbox did not change its state");
    }

    // -- value inputs: what a person does --------------------------------

    private async Task<string?> ValueAsync(Resolved r) =>
        (await World.CallAsync(r.Frame, "value", r.Id).ConfigureAwait(false)) is { ValueKind: JsonValueKind.String } v ? v.GetString() : null;

    /// <summary>date / time / datetime-local / month / week: click the first segment of the
    /// native editor and type each part, in the order the locale shows them.</summary>
    private async Task SetDateTimeAsync(Target t, Resolved r, string inputType, string value, ActOpts o, string api,
        HumanConfig cfg, Deadline d)
    {
        var parts = Fields.ParseDateTime(inputType, value) ?? throw Err($"{api}: Error: Malformed value");
        var segs = await World.EditorFieldsAsync(r.Frame, r.Id).ConfigureAwait(false);
        var kinds = segs.Select(s => s.Kind).ToList();
        parts = Fields.Use24h(parts, kinds.Contains("ampm"));
        if (segs.Count == 0 || kinds.Any(k => k != "ampm" && !parts.Has(k)))
            throw Err($"{api}: Error: unsupported date/time editor layout [{string.Join(", ", kinds)}]");
        await PointerActionAsync(api, t, o.With(c => { c.Deadline = d; c.Position = null; c.Aim = new object[] { "segment", segs[0] }; }),
            InputStates, true, (_, _, _, c) => PressMouseAsync(c, true)).ConfigureAwait(false);
        await Sleep(R(80, 200)).ConfigureAwait(false);
        var current = Fields.ParseDateTime(inputType, await ValueAsync(r).ConfigureAwait(false) ?? "");
        for (int i = 0; i < segs.Count; i++)
        {
            var kind = segs[i].Kind;
            if (inputType == "month" && kind == "month" && current != null)
            {
                // Shown as a month name; over an existing month Chromium's digit matching
                // is unreliable, so step with the arrow keys.
                int diff = int.Parse(parts["month"]) - int.Parse(current["month"]);
                for (int k = 0; k < Math.Abs(diff); k++)
                {
                    await _raw.KeyPressAsync(diff > 0 ? "ArrowUp" : "ArrowDown").ConfigureAwait(false);
                    await Sleep(R(60, 140)).ConfigureAwait(false);
                }
            }
            else if (kind == "ampm")
            {
                await TypeCharAsync((parts.Hour24 ?? 0) >= 12 ? 'P' : 'A', cfg).ConfigureAwait(false);
            }
            else
            {
                var digits = parts[kind];
                for (int j = 0; j < digits.Length; j++)
                {
                    await TypeCharAsync(digits[j], cfg).ConfigureAwait(false);
                    // The editor forgets a partial entry after ~1 s without a key.
                    if (j < digits.Length - 1)
                        await Sleep(Math.Min(450, Math.Max(40, cfg.TypingDelay + (HumanRandom.NextDouble() - 0.5) * 2 * cfg.TypingDelaySpread))).ConfigureAwait(false);
                }
            }
            if (i < segs.Count - 1 && !Fields.SegmentAutoAdvances(kind, parts, inputType))
                await _raw.KeyPressAsync("ArrowRight").ConfigureAwait(false);
            await Sleep(R(60, 160)).ConfigureAwait(false);
        }
        var got = await ValueAsync(r).ConfigureAwait(false);
        if (got != value) throw Err($"{api}: Error: the date/time editor produced '{got}' instead of '{value}'");
    }

    /// <summary>Slider: click on the track near the wanted value, then nudge with arrow keys.</summary>
    private async Task SetRangeAsync(Target t, Resolved r, string value, ActOpts o, string api, Deadline d)
    {
        var info = (await World.CallAsync(r.Frame, "rangeInfo", r.Id).ConfigureAwait(false))!.Value;
        if (!double.TryParse(value, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var want))
            throw Err($"{api}: Error: Malformed value");
        double min = D(info, "min"), max = D(info, "max"), step = D(info, "step");
        bool vertical = info.GetProperty("vertical").GetBoolean(), rtl = info.GetProperty("rtl").GetBoolean();
        double span = max - min;
        double frac = span <= 0 ? 0.5 : Math.Min(1, Math.Max(0, (want - min) / span));
        if (rtl && !vertical) frac = 1 - frac;
        await PointerActionAsync(api, t, o.With(c => { c.Deadline = d; c.Position = null; c.Aim = new object[] { "fraction", frac, vertical }; }),
            InputStates, false, (_, _, _, c) => PressMouseAsync(c, false)).ConfigureAwait(false);
        async Task<double> Read() => double.Parse(await ValueAsync(r).ConfigureAwait(false) ?? "0", System.Globalization.CultureInfo.InvariantCulture);
        for (int k = 0; k < 400; k++)
        {
            double cur = await Read().ConfigureAwait(false);
            if (Math.Abs(cur - want) < 1e-9 || (step > 0 && Math.Abs(cur - want) < step / 2)) break;
            bool up = cur < want;
            await _raw.KeyPressAsync(!rtl ? (up ? "ArrowRight" : "ArrowLeft") : (up ? "ArrowLeft" : "ArrowRight")).ConfigureAwait(false);
            await Sleep(R(40, 110)).ConfigureAwait(false);
            if (await Read().ConfigureAwait(false) == cur) break; // min/max reached
        }
        double snap = Math.Min(max, Math.Max(min, want));
        if (step > 0) snap = Math.Min(max, min + Math.Round((snap - min) / step) * step);
        var got = await Read().ConfigureAwait(false);
        if (got != snap) throw Err($"{api}: Error: slider stopped at {got} instead of {value}");
    }

    /// <summary>Pick options like a person: a dropdown is opened with a click and moved with
    /// arrow keys + Enter; a list box gets clicks on the options (Ctrl/Cmd to add).</summary>
    public async Task<IReadOnlyList<string>> SelectOptionAsync(Target t, IReadOnlyList<object> options,
        IReadOnlyList<IElementHandle> handles, ActOpts o, string api)
    {
        var cfg = CallCfg(o.HumanConfig);
        var d = DeadlineFor(t, o);
        var (r, plan) = await RetryAsync(api, t, d, async () =>
        {
            var rr = await AttemptStatesAsync(t, new[] { "visible", "enabled" }, o.Force).ConfigureAwait(false);
            var ids = new List<int>();
            foreach (var h in handles) ids.Add((await ResolveHandleAsync(h).ConfigureAwait(false)).Id);
            var res = (await World.CallAsync(rr.Frame, "selectPlan", rr.Id, options, ids).ConfigureAwait(false))!.Value;
            if (res.TryGetProperty("error", out var e)) throw Err(e.GetString() ?? "select failed");
            if (res.TryGetProperty("retry", out var re)) throw new RetryException(re.GetString() ?? "retry");
            return (rr, res);
        }).ConfigureAwait(false);
        var targets = plan.GetProperty("targets").EnumerateArray().Select(x => x.GetInt32()).ToList();
        var values = plan.GetProperty("values").EnumerateArray().Select(x => x.GetString()!).ToList();
        if (!plan.GetProperty("listbox").GetBoolean())
            await SelectDropdownAsync(t, r, targets.Count > 0 ? targets[0] : null, plan, o, api, d).ConfigureAwait(false);
        else
            await SelectListboxAsync(t, r, targets, o, api, cfg, d).ConfigureAwait(false);
        var state = (await World.CallAsync(r.Frame, "selectState", r.Id).ConfigureAwait(false))!.Value;
        var selected = state.GetProperty("selected").EnumerateArray().Select(x => x.GetInt32()).OrderBy(x => x).ToList();
        var got = state.GetProperty("values").EnumerateArray().Select(x => x.GetString()!).ToList();
        if (!selected.SequenceEqual(targets.OrderBy(x => x)))
            throw Err($"{api}: Error: selection ended as [{string.Join(", ", got)}] instead of [{string.Join(", ", values)}]");
        return got;
    }

    private async Task SelectDropdownAsync(Target t, Resolved r, int? index, JsonElement plan, ActOpts o, string api, Deadline d)
    {
        if (index == null) throw Err($"{api}: Error: a dropdown always keeps one option selected");
        var state = (await World.CallAsync(r.Frame, "selectState", r.Id).ConfigureAwait(false))!.Value;
        int cur = state.GetProperty("current").GetInt32();
        if (cur == index)
        {
            await HoverAsync(t, new ActOpts { Deadline = d, HumanConfig = o.HumanConfig }, api).ConfigureAwait(false);
            return;
        }
        bool mac = OperatingSystem.IsMacOS(); // a macOS host's native popup ignores arrow keys
        var ta = await World.CallAsync(r.Frame, "typeAheadPlan", r.Id, index.Value, mac ? 0 : 3).ConfigureAwait(false);
        if (ta is not { ValueKind: JsonValueKind.Object } p) throw Err($"{api}: Error: no option of this dropdown can be reached");
        bool viaHome = p.TryGetProperty("home", out var home) && home.GetBoolean();
        if (mac && viaHome && p.GetProperty("label").GetString()!.Any(char.IsSurrogate))
            throw Err($"{api}: Error: this option's label has an emoji or similar character that cannot be typed, and a " +
                      "macOS dropdown ignores arrow keys, so it cannot be picked with human input; select it on the " +
                      "original page (Humanize.Unwrap(page).SelectOptionAsync) if a programmatic selection is acceptable");
        await ClickAsync(t, new ActOpts { Deadline = d, Force = o.Force, HumanConfig = o.HumanConfig }, api).ConfigureAwait(false);
        await Sleep(R(200, 450)).ConfigureAwait(false); // popup opens; eyes find the option
        var cfg = CallCfg(o.HumanConfig);
        int n = p.GetProperty("arrows").GetInt32();
        var walk = Enumerable.Repeat(n > 0 ? "ArrowDown" : "ArrowUp", Math.Abs(n));
        var keys = new List<string>();
        if (viaHome)
        {
            // No name prefix is unique (duplicate labels): Home, then walk; on macOS type the whole label.
            if (mac) keys.AddRange(p.GetProperty("label").GetString()!.Select(c => c.ToString()));
            else { keys.Add("Home"); keys.AddRange(walk); }
        }
        else
        {
            keys.AddRange(p.GetProperty("typed").GetString()!.Select(c => c.ToString()));
            keys.AddRange(walk);
        }
        // The browser joins letters typed within ~1s into one search: let an earlier
        // SelectOption's search lapse before starting a new one.
        if (keys.Count > 0 && keys[0].Length == 1)
        {
            double wait = (_typeAheadUntil - DateTime.UtcNow).TotalMilliseconds;
            if (wait > 0) await Sleep(wait).ConfigureAwait(false);
        }
        bool typed = false;
        foreach (var k in keys)
        {
            if (d.Expired)
            {
                await _raw.KeyPressAsync("Escape").ConfigureAwait(false);
                throw new System.TimeoutException($"{api}: Timeout {Math.Round(d.Timeout)}ms exceeded.\n"
                    + $"Call log:\n  - choosing an option of {t.Description}");
            }
            if (k.Length == 1)
            {
                await TypeAheadCharAsync(k[0], cfg).ConfigureAwait(false);
                typed = true;
                _typeAheadUntil = DateTime.UtcNow.AddMilliseconds(1100);
                await Sleep(R(60, 160)).ConfigureAwait(false);
            }
            else
            {
                await _raw.KeyPressAsync(k).ConfigureAwait(false);
                await Sleep(R(90, 200)).ConfigureAwait(false);
            }
        }
        await Sleep(R(100, 250)).ConfigureAwait(false);
        await _raw.KeyPressAsync("Enter").ConfigureAwait(false);
        if (typed) _typeAheadUntil = DateTime.UtcNow.AddMilliseconds(1100);
        await Sleep(R(80, 160)).ConfigureAwait(false);
    }

    /// <summary>When the browser stops joining typed letters into one type-ahead search.</summary>
    private DateTime _typeAheadUntil = DateTime.MinValue;

    /// <summary>One type-ahead letter (lowercase: a person doesn't hold Shift to search a list);
    /// a character without a US-layout key is sent as itself.</summary>
    private async Task TypeAheadCharAsync(char ch, HumanConfig cfg)
    {
        if (ch < 128)
        {
            await TypeCharAsync(ch, cfg).ConfigureAwait(false);
            return;
        }
        var session = await World.SessionAsync().ConfigureAwait(false);
        await session.SendAsync("Input.dispatchKeyEvent", new()
        {
            ["type"] = "keyDown", ["key"] = ch.ToString(), ["text"] = ch.ToString(), ["unmodifiedText"] = ch.ToString(),
        }).ConfigureAwait(false);
        await Sleep(RR(cfg.KeyHold)).ConfigureAwait(false);
        await session.SendAsync("Input.dispatchKeyEvent", new() { ["type"] = "keyUp", ["key"] = ch.ToString() }).ConfigureAwait(false);
    }

    private async Task SelectListboxAsync(Target t, Resolved r, List<int> want, ActOpts o, string api, HumanConfig cfg, Deadline d)
    {
        var state = (await World.CallAsync(r.Frame, "selectState", r.Id).ConfigureAwait(false))!.Value;
        var selected = state.GetProperty("selected").EnumerateArray().Select(x => x.GetInt32()).OrderBy(x => x);
        if (selected.SequenceEqual(want.OrderBy(x => x)))
        {
            await HoverAsync(t, new ActOpts { Deadline = d, HumanConfig = o.HumanConfig }, api).ConfigureAwait(false);
            return;
        }
        if (want.Count == 0) throw Err($"{api}: Error: deselecting every option is not something a click can do");
        string addKey = await IsMacAsync().ConfigureAwait(false) ? "Meta" : "Control";
        bool first = true;
        foreach (var idx in want)
        {
            int oid = (await World.CallAsync(r.Frame, "optionId", r.Id, idx).ConfigureAwait(false))!.Value.GetInt32();
            var label = new Target(r.Frame, null) { Description = $"option #{idx}" };
            var option = new Resolved(r.Frame, oid);
            var mods = first ? Array.Empty<string>() : new[] { addKey };
            // A plain click on the first option replaces the selection; further options are
            // added with Ctrl/Cmd held, as a person does.
            await RetryAsync(api, label, d, async () =>
            {
                var box = await ScrollIntoViewAsync(option, cfg, d).ConfigureAwait(false);
                var (x, y) = PointIn(box, null, false, cfg);
                await HitAsync(option, x, y).ConfigureAwait(false);
                await MoveToAsync(x, y, cfg).ConfigureAwait(false);
                await HitAsync(option, Cursor.X, Cursor.Y).ConfigureAwait(false);
                await PressMouseAsync(cfg, false, MouseButton.Left, 1, null, mods).ConfigureAwait(false);
            }).ConfigureAwait(false);
            first = false;
            await Sleep(R(120, 300)).ConfigureAwait(false);
        }
    }

    public async Task DragAsync(Target source, Target dest, ActOpts o, string api)
    {
        var sub = new ActOpts { Deadline = DeadlineFor(source, o), Force = o.Force, HumanConfig = o.HumanConfig, Position = o.SourcePosition, Trial = o.Trial };
        await IdleAsync(CallCfg(o.HumanConfig)).ConfigureAwait(false);
        await HoverAsync(source, sub, api).ConfigureAwait(false);
        if (o.Trial)
        {
            await HoverAsync(dest, sub.With(c => { c.Position = o.TargetPosition; c.Nested = true; }), api).ConfigureAwait(false);
            return;
        }
        await Sleep(R(100, 200)).ConfigureAwait(false);
        await _raw.DownAsync().ConfigureAwait(false);
        try
        {
            await Sleep(R(80, 150)).ConfigureAwait(false);
            await HoverAsync(dest, sub.With(c => { c.Position = o.TargetPosition; c.Force = true; c.Nested = true; }), api).ConfigureAwait(false);
            await Sleep(R(80, 150)).ConfigureAwait(false);
        }
        finally { await _raw.UpAsync().ConfigureAwait(false); }
    }

    /// <summary>Focus without a click (Playwright's focus() is itself programmatic); the
    /// ElementHandle variant moves the cursor over the element first.</summary>
    public async Task FocusAsync(Target t, ActOpts o, string api, bool move = false)
    {
        var d = DeadlineFor(t, o);
        if (move) await HoverAsync(t, new ActOpts { Timeout = o.Timeout, HumanConfig = o.HumanConfig }, api).ConfigureAwait(false);
        var r = await RetryAsync(api, t, d, () => ResolveAsync(t)).ConfigureAwait(false);
        await World.CallAsync(r.Frame, "focus", r.Id).ConfigureAwait(false);
    }

    public async Task ScrollIntoViewIfNeededAsync(Target t, ActOpts o, string api)
    {
        var cfg = CallCfg(o.HumanConfig);
        var d = DeadlineFor(t, o);
        await EnsureCursorAsync(cfg).ConfigureAwait(false);
        await RetryAsync(api, t, d, async () =>
        {
            var r = await AttemptStatesAsync(t, new[] { "visible", "stable" }, false).ConfigureAwait(false);
            await ScrollIntoViewAsync(r, cfg, d).ConfigureAwait(false);
        }).ConfigureAwait(false);
    }

    // -- keyboard -----------------------------------------------------------

    private static bool IsAscii(string s) => s.Length > 0 && s.All(c => c <= 0x7F);
    private static bool IsUpper(char c) => c is >= 'A' and <= 'Z';

    /// <summary>Type <paramref name="text"/> key by key into the focused element of the frame.</summary>
    public async Task TypeTextAsync(string text, HumanConfig cfg, IFrame frame, JsonElement? info, float? delay)
    {
        string? tag = info is JsonElement i ? S(i, "tag") : null;
        bool mistypes = cfg.MistypeChance > 0 && tag != null && Fields.AllowsMistype(tag, S(info!.Value, "type"));
        var elements = System.Globalization.StringInfo.GetTextElementEnumerator(text);
        var chars = new List<string>();
        while (elements.MoveNext()) chars.Add((string)elements.Current);
        for (int k = 0; k < chars.Count; k++)
        {
            var ch = chars[k];
            if (!IsAscii(ch) || ch.Length != 1)
            {
                await Sleep(RR(cfg.KeyHold)).ConfigureAwait(false);
                await _raw.InsertTextAsync(ch).ConfigureAwait(false);
            }
            else
            {
                char c = ch[0];
                if (mistypes && char.IsLetterOrDigit(c) && HumanRandom.NextDouble() < cfg.MistypeChance)
                    await TypoAsync(c, cfg, frame).ConfigureAwait(false);
                await TypeCharAsync(c, cfg).ConfigureAwait(false);
            }
            if (k < chars.Count - 1) await BetweenKeysAsync(cfg, delay).ConfigureAwait(false);
        }
    }

    private async Task TypoAsync(char ch, HumanConfig cfg, IFrame frame)
    {
        if (!HumanKeyboard.NearbyKeys.TryGetValue(char.ToLowerInvariant(ch), out var near) || near.Length == 0) return;
        char wrong = HumanRandom.Choice(near);
        if (IsUpper(ch)) wrong = char.ToUpperInvariant(wrong);
        var before = await ActiveValueAsync(frame).ConfigureAwait(false);
        await TypeCharAsync(wrong, cfg).ConfigureAwait(false);
        await Sleep(RR(cfg.MistypeDelayNotice)).ConfigureAwait(false);
        var after = await ActiveValueAsync(frame).ConfigureAwait(false);
        if (before != null && after == before)
        {
            // The page rejected the wrong key (mask / filter): nothing to undo.
            await Sleep(RR(cfg.MistypeDelayCorrect)).ConfigureAwait(false);
            return;
        }
        await _raw.KeyDownAsync("Backspace").ConfigureAwait(false);
        await Sleep(RR(cfg.KeyHold)).ConfigureAwait(false);
        await _raw.KeyUpAsync("Backspace").ConfigureAwait(false);
        await Sleep(RR(cfg.MistypeDelayCorrect)).ConfigureAwait(false);
    }

    private async Task<string?> ActiveValueAsync(IFrame frame)
    {
        try { return (await World.CallAsync(frame, "activeValue").ConfigureAwait(false)) is JsonElement v ? S(v, "value") : null; }
        catch (PlaywrightException) { return null; }
    }

    public async Task TypeCharAsync(char ch, HumanConfig cfg)
    {
        var key = ch.ToString();
        if (IsUpper(ch))
        {
            await _raw.KeyDownAsync("Shift").ConfigureAwait(false);
            await Sleep(RR(cfg.ShiftDownDelay)).ConfigureAwait(false);
            await _raw.KeyDownAsync(key).ConfigureAwait(false);
            await Sleep(RR(cfg.KeyHold)).ConfigureAwait(false);
            await _raw.KeyUpAsync(key).ConfigureAwait(false);
            await Sleep(RR(cfg.ShiftUpDelay)).ConfigureAwait(false);
            await _raw.KeyUpAsync("Shift").ConfigureAwait(false);
        }
        else if (HumanKeyboard.ShiftSymbols.Contains(ch))
        {
            var session = await World.SessionAsync().ConfigureAwait(false);
            var (code, vk) = HumanKeyboard.ShiftSymbolKey(ch);
            await _raw.KeyDownAsync("Shift").ConfigureAwait(false);
            await Sleep(RR(cfg.ShiftDownDelay)).ConfigureAwait(false);
            await session.SendAsync("Input.dispatchKeyEvent", new()
            {
                ["type"] = "keyDown", ["modifiers"] = 8, ["key"] = key, ["code"] = code,
                ["windowsVirtualKeyCode"] = vk, ["text"] = key, ["unmodifiedText"] = key,
            }).ConfigureAwait(false);
            await Sleep(RR(cfg.KeyHold)).ConfigureAwait(false);
            await session.SendAsync("Input.dispatchKeyEvent", new()
            {
                ["type"] = "keyUp", ["modifiers"] = 8, ["key"] = key, ["code"] = code, ["windowsVirtualKeyCode"] = vk,
            }).ConfigureAwait(false);
            await Sleep(RR(cfg.ShiftUpDelay)).ConfigureAwait(false);
            await _raw.KeyUpAsync("Shift").ConfigureAwait(false);
        }
        else
        {
            await _raw.KeyDownAsync(key).ConfigureAwait(false);
            await Sleep(RR(cfg.KeyHold)).ConfigureAwait(false);
            await _raw.KeyUpAsync(key).ConfigureAwait(false);
        }
    }

    private static Task BetweenKeysAsync(HumanConfig cfg, float? delay)
    {
        if (delay != null) return Sleep(delay.Value);
        if (HumanRandom.NextDouble() < cfg.TypingPauseChance) return Sleep(RR(cfg.TypingPauseRange));
        return Sleep(Math.Max(10, cfg.TypingDelay + (HumanRandom.NextDouble() - 0.5) * 2 * cfg.TypingDelaySpread));
    }

    /// <summary><c>page.Keyboard.TypeAsync</c>: no target; mistypes only where safe.</summary>
    public async Task KeyboardTypeAsync(string text, float? delay = null)
    {
        JsonElement? info = null;
        try { info = await World.CallAsync(_page.MainFrame, "activeValue").ConfigureAwait(false); }
        catch (PlaywrightException) { }
        if (info is JsonElement i && (S(i, "tag") == null || S(i, "tag") == "iframe")) info = null;
        await TypeTextAsync(text, Config, _page.MainFrame, info, delay).ConfigureAwait(false);
    }

    // -- raw mouse API ------------------------------------------------------

    public async Task MouseMoveAsync(double x, double y, int? steps = null)
    {
        if (steps != null)
        {
            await EnsureCursorAsync().ConfigureAwait(false);
            await _raw.MoveAsync(x, y, steps).ConfigureAwait(false);
        }
        else
        {
            await MoveToAsync(x, y, Config).ConfigureAwait(false);
        }
        Cursor.X = x; Cursor.Y = y;
    }

    public async Task MouseClickAsync(double x, double y, float? delay = null, MouseButton? button = null, int? clickCount = null)
    {
        await MoveToAsync(x, y, Config).ConfigureAwait(false);
        await PressMouseAsync(Config, false, button ?? MouseButton.Left, clickCount ?? 1, delay).ConfigureAwait(false);
    }
}
