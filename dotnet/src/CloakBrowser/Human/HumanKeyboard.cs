using System.Text.Json.Nodes;
using Microsoft.Playwright;

namespace CloakBrowser.Human;

/// <summary>
/// Minimal keyboard abstraction the humanize layer drives. Mirrors the Python
/// <c>RawKeyboard</c> Protocol. Implemented over Playwright's <c>IKeyboard</c>.
/// </summary>
public interface IRawKeyboard
{
    Task DownAsync(string key);
    Task UpAsync(string key);
    Task TypeAsync(string text);
    Task InsertTextAsync(string text);
}

/// <summary>
/// A tiny abstraction over a CDP session so the keyboard can dispatch trusted
/// key events. Implemented over Playwright's <c>ICDPSession</c>.
/// </summary>
public interface IRawCdpSession
{
    Task SendAsync(string method, JsonObject? args = null);
}

/// <summary>
/// A tiny abstraction over <c>page.evaluate</c> used by the fallback shift-symbol path.
/// </summary>
public interface IRawEvaluator
{
    Task EvaluateAsync(string expression, object? arg);
}

/// <summary>
/// Human-like keyboard input. Direct port of Python
/// <c>cloakbrowser/human/keyboard.py</c>.
///
/// Stealth-aware: when a CDP session is provided, shift symbols are typed via
/// CDP <c>Input.dispatchKeyEvent</c> (isTrusted=true, no evaluate stack trace).
/// Falls back to <c>page.evaluate</c> when no CDP session is available.
/// </summary>
public static class HumanKeyboard
{
    /// <summary>Press a key while preserving the caller's keydown-to-keyup delay.</summary>
    internal static Task PressAsync(IKeyboard keyboard, string key, float? delay = null) =>
        keyboard.PressAsync(
            key,
            delay.HasValue ? new KeyboardPressOptions { Delay = delay.Value } : null);

    /// <summary>Characters that require holding Shift to produce.</summary>
    public static readonly IReadOnlySet<char> ShiftSymbols =
        new HashSet<char>("@#!$%^&*()_+{}|:\"<>?~");

    /// <summary>QWERTY-adjacent keys used to simulate fat-finger mistypes.</summary>
    public static readonly IReadOnlyDictionary<char, string> NearbyKeys = new Dictionary<char, string>
    {
        ['a'] = "sqwz", ['b'] = "vghn", ['c'] = "xdfv", ['d'] = "sfecx", ['e'] = "wrsdf",
        ['f'] = "dgrtcv", ['g'] = "fhtyb", ['h'] = "gjybn", ['i'] = "ujko", ['j'] = "hkunm",
        ['k'] = "jloi", ['l'] = "kop", ['m'] = "njk", ['n'] = "bhjm", ['o'] = "iklp",
        ['p'] = "ol", ['q'] = "wa", ['r'] = "edft", ['s'] = "awedxz", ['t'] = "rfgy",
        ['u'] = "yhji", ['v'] = "cfgb", ['w'] = "qase", ['x'] = "zsdc", ['y'] = "tghu",
        ['z'] = "asx",
        // Digits stay digits: a letter typo is rejected by <input type=number>,
        // so the correcting Backspace would delete the previous real digit (#573).
        ['1'] = "2", ['2'] = "13", ['3'] = "24", ['4'] = "35", ['5'] = "46",
        ['6'] = "57", ['7'] = "68", ['8'] = "79", ['9'] = "80", ['0'] = "9",
    };

    /// <summary>CDP key <c>code</c> for each shift symbol's physical key.</summary>
    private static readonly IReadOnlyDictionary<char, string> ShiftSymbolCodes = new Dictionary<char, string>
    {
        ['!'] = "Digit1", ['@'] = "Digit2", ['#'] = "Digit3", ['$'] = "Digit4",
        ['%'] = "Digit5", ['^'] = "Digit6", ['&'] = "Digit7", ['*'] = "Digit8",
        ['('] = "Digit9", [')'] = "Digit0", ['_'] = "Minus", ['+'] = "Equal",
        ['{'] = "BracketLeft", ['}'] = "BracketRight", ['|'] = "Backslash",
        [':'] = "Semicolon", ['"'] = "Quote", ['<'] = "Comma", ['>'] = "Period",
        ['?'] = "Slash", ['~'] = "Backquote",
    };

    /// <summary>Windows virtual key codes for <c>Input.dispatchKeyEvent</c>.</summary>
    private static readonly IReadOnlyDictionary<char, int> ShiftSymbolKeyCodes = new Dictionary<char, int>
    {
        ['!'] = 49, ['@'] = 50, ['#'] = 51, ['$'] = 52, ['%'] = 53,
        ['^'] = 54, ['&'] = 55, ['*'] = 56, ['('] = 57, [')'] = 48,
        ['_'] = 189, ['+'] = 187, ['{'] = 219, ['}'] = 221, ['|'] = 220,
        [':'] = 186, ['"'] = 222, ['<'] = 188, ['>'] = 190, ['?'] = 191,
        ['~'] = 192,
    };

    /// <summary>Physical key of each unshifted digit / punctuation character, so a shift
    /// symbol and its base character ("1" and "!") count as the same key.</summary>
    private static readonly IReadOnlyDictionary<char, string> BaseKeyCodes = new Dictionary<char, string>
    {
        ['1'] = "Digit1", ['2'] = "Digit2", ['3'] = "Digit3", ['4'] = "Digit4", ['5'] = "Digit5",
        ['6'] = "Digit6", ['7'] = "Digit7", ['8'] = "Digit8", ['9'] = "Digit9", ['0'] = "Digit0",
        ['-'] = "Minus", ['='] = "Equal", ['['] = "BracketLeft", [']'] = "BracketRight",
        ['\\'] = "Backslash", [';'] = "Semicolon", ['\''] = "Quote", [','] = "Comma",
        ['.'] = "Period", ['/'] = "Slash", ['`'] = "Backquote",
    };

    /// <summary>The physical key that types <paramref name="ch"/>: "x" and "X" are one key,
    /// so are "1" and "!". Used so a key never goes down while it is still held.</summary>
    internal static string PhysicalKey(string ch)
    {
        if (ch.Length == 1)
        {
            if (ShiftSymbolCodes.TryGetValue(ch[0], out var s)) return s;
            if (BaseKeyCodes.TryGetValue(ch[0], out var b)) return b;
        }
        return ch.ToLowerInvariant();
    }

    /// <summary>CDP <c>code</c> and Windows virtual key code of a shift symbol's physical key.</summary>
    internal static (string Code, int KeyCode) ShiftSymbolKey(char ch) =>
        (ShiftSymbolCodes.TryGetValue(ch, out var c) ? c : "", ShiftSymbolKeyCodes.TryGetValue(ch, out var k) ? k : 0);

    private static bool IsAscii(char c) => c <= 0x7F;
    private static bool IsAlnum(char c) => char.IsLetterOrDigit(c) && IsAscii(c);

    /// <summary>Return a random adjacent key for the given character.</summary>
    private static char GetNearbyKey(char ch)
    {
        char lower = char.ToLowerInvariant(ch);
        if (NearbyKeys.TryGetValue(lower, out var neighbors) && neighbors.Length > 0)
        {
            char wrong = HumanRandom.Choice(neighbors);
            return char.IsUpper(ch) ? char.ToUpperInvariant(wrong) : wrong;
        }
        return ch;
    }

    /// <summary>
    /// Type <paramref name="text"/> with human-like per-character timing.
    /// </summary>
    /// <param name="evaluator">Used by the fallback shift-symbol path (page.evaluate).</param>
    /// <param name="raw">The raw keyboard to drive.</param>
    /// <param name="text">The text to type.</param>
    /// <param name="cfg">Behavior configuration.</param>
    /// <param name="cdpSession">
    /// If provided, shift symbols use CDP <c>Input.dispatchKeyEvent</c> producing
    /// isTrusted=true events with no evaluate stack trace. If null, falls back to
    /// <paramref name="evaluator"/> (detectable).
    /// </param>
    public static async Task HumanTypeAsync(
        IRawEvaluator? evaluator,
        IRawKeyboard raw,
        string text,
        HumanConfig cfg,
        IRawCdpSession? cdpSession = null)
    {
        for (int i = 0; i < text.Length; i++)
        {
            char ch = text[i];

            // Non-ASCII characters (Cyrillic, CJK, emoji) - use insertText.
            if (!IsAscii(ch))
            {
                await HumanRandom.SleepMsAsync(KeyTiming.KeyHold(cfg)).ConfigureAwait(false);
                await raw.InsertTextAsync(ch.ToString()).ConfigureAwait(false);
                if (i < text.Length - 1)
                    await InterCharDelayAsync(cfg).ConfigureAwait(false);
                continue;
            }

            // Mistype chance - only for ASCII alphanumeric.
            if (HumanRandom.NextDouble() < cfg.MistypeChance && IsAlnum(ch))
            {
                char wrong = GetNearbyKey(ch);
                await TypeNormalCharAsync(raw, wrong, cfg).ConfigureAwait(false);
                await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.MistypeDelayNotice)).ConfigureAwait(false);
                await raw.DownAsync("Backspace").ConfigureAwait(false);
                await HumanRandom.SleepMsAsync(KeyTiming.KeyHold(cfg)).ConfigureAwait(false);
                await raw.UpAsync("Backspace").ConfigureAwait(false);
                await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.MistypeDelayCorrect)).ConfigureAwait(false);
            }

            if (char.IsUpper(ch) && char.IsLetter(ch))
                await TypeShiftedCharAsync(raw, ch, cfg).ConfigureAwait(false);
            else if (ShiftSymbols.Contains(ch))
                await TypeShiftSymbolAsync(evaluator, raw, ch, cfg, cdpSession).ConfigureAwait(false);
            else
                await TypeNormalCharAsync(raw, ch, cfg).ConfigureAwait(false);

            if (i < text.Length - 1)
                await InterCharDelayAsync(cfg).ConfigureAwait(false);
        }
    }

    private static async Task TypeNormalCharAsync(IRawKeyboard raw, char ch, HumanConfig cfg)
    {
        await raw.DownAsync(ch.ToString()).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(KeyTiming.KeyHold(cfg)).ConfigureAwait(false);
        await raw.UpAsync(ch.ToString()).ConfigureAwait(false);
    }

    private static async Task TypeShiftedCharAsync(IRawKeyboard raw, char ch, HumanConfig cfg)
    {
        await raw.DownAsync("Shift").ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.RandLog(cfg.ShiftDownDelay)).ConfigureAwait(false);
        await raw.DownAsync(ch.ToString()).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(KeyTiming.KeyHold(cfg)).ConfigureAwait(false);
        await raw.UpAsync(ch.ToString()).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(Math.Max(0, HumanRandom.RandRange(cfg.ShiftUpDelay))).ConfigureAwait(false);
        await raw.UpAsync("Shift").ConfigureAwait(false);
    }

    private static async Task TypeShiftSymbolAsync(
        IRawEvaluator? evaluator,
        IRawKeyboard raw,
        char ch,
        HumanConfig cfg,
        IRawCdpSession? cdpSession)
    {
        if (cdpSession != null)
        {
            // --- Stealth path: CDP Input.dispatchKeyEvent ---
            string code = ShiftSymbolCodes.TryGetValue(ch, out var c) ? c : "";
            int keyCode = ShiftSymbolKeyCodes.TryGetValue(ch, out var kc) ? kc : 0;
            string s = ch.ToString();

            await raw.DownAsync("Shift").ConfigureAwait(false);
            await HumanRandom.SleepMsAsync(HumanRandom.RandLog(cfg.ShiftDownDelay)).ConfigureAwait(false);

            await cdpSession.SendAsync("Input.dispatchKeyEvent", new JsonObject
            {
                ["type"] = "keyDown",
                ["modifiers"] = 8, // Shift modifier flag
                ["key"] = s,
                ["code"] = code,
                ["windowsVirtualKeyCode"] = keyCode,
                ["text"] = s,
                ["unmodifiedText"] = s,
            }).ConfigureAwait(false);
            await HumanRandom.SleepMsAsync(KeyTiming.KeyHold(cfg)).ConfigureAwait(false);

            await cdpSession.SendAsync("Input.dispatchKeyEvent", new JsonObject
            {
                ["type"] = "keyUp",
                ["modifiers"] = 8,
                ["key"] = s,
                ["code"] = code,
                ["windowsVirtualKeyCode"] = keyCode,
            }).ConfigureAwait(false);

            await HumanRandom.SleepMsAsync(Math.Max(0, HumanRandom.RandRange(cfg.ShiftUpDelay))).ConfigureAwait(false);
            await raw.UpAsync("Shift").ConfigureAwait(false);
        }
        else
        {
            // --- Fallback path: page.evaluate (detectable) ---
            await raw.DownAsync("Shift").ConfigureAwait(false);
            await HumanRandom.SleepMsAsync(HumanRandom.RandLog(cfg.ShiftDownDelay)).ConfigureAwait(false);
            await raw.InsertTextAsync(ch.ToString()).ConfigureAwait(false);
            if (evaluator != null)
            {
                await evaluator.EvaluateAsync(
                    @"(key) => {
                        const el = document.activeElement;
                        if (el) {
                            el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
                            el.dispatchEvent(new KeyboardEvent('keyup', { key, bubbles: true }));
                        }
                    }",
                    ch.ToString()).ConfigureAwait(false);
            }
            await HumanRandom.SleepMsAsync(Math.Max(0, HumanRandom.RandRange(cfg.ShiftUpDelay))).ConfigureAwait(false);
            await raw.UpAsync("Shift").ConfigureAwait(false);
        }
    }

    private static Task InterCharDelayAsync(HumanConfig cfg) =>
        HumanRandom.SleepMsAsync(Math.Max(10, KeyTiming.KeyGap(cfg, "a", "b") - HumanRandom.RandLog(cfg.KeyHold)));
}

/// <summary>
/// Key timing shared by the humanize engine. Numbers come from the 136M Keystrokes data
/// (Dhakal et al., CHI 2018): letters typed with the other hand follow ~20% faster than
/// letters of the same hand, a repeated letter (same finger) is slower, and the first letter
/// of a word (after a space) is the slowest. People commonly press the next key before
/// letting go of the previous one (rollover).
/// </summary>
internal static class KeyTiming
{
    private static readonly HashSet<char> LeftHand = new("qwertasdfgzxcvb`12345~!@#$%");

    private static char? Hand(string ch)
    {
        if (ch.Length != 1) return null;
        char c = char.ToLowerInvariant(ch[0]);
        if (c > 0x7F || char.IsWhiteSpace(c)) return null;
        return LeftHand.Contains(c) ? 'L' : 'R';
    }

    /// <summary>How much slower / faster than average the press of <paramref name="ch"/> follows <paramref name="prev"/>.</summary>
    public static double GapFactor(string prev, string ch)
    {
        if (prev.Length == 0) return 1;
        if (prev == " ") return 1.3;
        if (ch == " ") return 0.9;
        if (string.Equals(prev, ch, StringComparison.OrdinalIgnoreCase)) return 1.05;
        var hp = Hand(prev);
        var hc = Hand(ch);
        if (hp != null && hc != null) return hp != hc ? 0.85 : 1.1;
        return 1;
    }

    /// <summary>Milliseconds from the press of <paramref name="prev"/> to the press of
    /// <paramref name="ch"/> (log-normal around TypingDelay, plus occasional thinking pauses
    /// before words).</summary>
    public static double KeyGap(HumanConfig cfg, string prev, string ch)
    {
        double median = Math.Max(1, cfg.TypingDelay * GapFactor(prev, ch));
        double spread = Math.Max(0, cfg.TypingDelaySpread);
        double sigma = cfg.TypingDelay > 0 ? Math.Log(1 + spread / cfg.TypingDelay) : 0;
        double gap = HumanRandom.RandLognormal(median, sigma);
        bool wordStart = prev == " " || prev.Length == 0;
        double chance = cfg.TypingPauseChance * (wordStart ? 1 : 0.1);
        if (chance > 0 && HumanRandom.NextDouble() < chance) gap += HumanRandom.RandRange(cfg.TypingPauseRange);
        return Math.Max(15, gap);
    }

    /// <summary>How long one key stays down (ms).</summary>
    public static double KeyHold(HumanConfig cfg) => Math.Max(1, HumanRandom.RandLog(cfg.KeyHold));
}

/// <summary>
/// Presses keys on a timeline the way a person does: each press follows the previous
/// <em>press</em> after a letter-dependent gap, and each key is held for its own time, so the
/// next key often goes down before the previous one comes up (rollover). Shift goes down
/// before the letter and is usually let go just before the letter key. Releases are queued
/// and sent when due.
/// </summary>
internal sealed class Typist
{
    private sealed record KeyUp(double Due, string Key, Dictionary<string, object>? Cdp);

    private readonly Func<string, Task> _down;
    private readonly Func<string, Task> _up;
    private readonly Func<string, Task> _insertText;
    private readonly Func<Dictionary<string, object>, Task> _cdp;
    private readonly HumanConfig _cfg;
    private readonly double? _delay;
    private readonly System.Diagnostics.Stopwatch _clock = System.Diagnostics.Stopwatch.StartNew();
    private readonly List<KeyUp> _ups = new();
    private string _prev = "";
    private double? _lastPress;
    private double? _shiftUpDue;
    private bool _shiftDown;

    public Typist(Func<string, Task> down, Func<string, Task> up, Func<string, Task> insertText,
        Func<Dictionary<string, object>, Task> cdp, HumanConfig cfg, double? delay = null)
    {
        _down = down; _up = up; _insertText = insertText; _cdp = cdp; _cfg = cfg; _delay = delay;
    }

    private double Now => _clock.Elapsed.TotalMilliseconds;

    private Task WaitAsync(double until) => HumanRandom.SleepMsAsync(until - Now);

    private async Task ShiftAsync(bool down)
    {
        _shiftDown = down;
        await (down ? _down("Shift") : _up("Shift")).ConfigureAwait(false);
    }

    private async Task UpAsync(KeyUp u)
    {
        if (u.Cdp != null) await _cdp(u.Cdp).ConfigureAwait(false);
        else if (u.Key.Length == 1 && u.Key[0] is >= 'A' and <= 'Z' && !_shiftDown)
            await _up(u.Key.ToLowerInvariant()).ConfigureAwait(false); // Shift already came up: the OS reports the bare key
        else await _up(u.Key).ConfigureAwait(false);
    }

    /// <summary>Send every release due before <paramref name="until"/> (in time order).</summary>
    private async Task FlushAsync(double until)
    {
        while (true)
        {
            KeyUp? next = null;
            foreach (var u in _ups)
                if (u.Due <= until && (next == null || u.Due < next.Due)) next = u;
            bool shiftFirst = _shiftUpDue is double sd && sd <= until && (next == null || sd <= next.Due);
            if (shiftFirst)
            {
                await WaitAsync(_shiftUpDue!.Value).ConfigureAwait(false);
                _shiftUpDue = null;
                await ShiftAsync(false).ConfigureAwait(false);
                continue;
            }
            if (next == null) return;
            await WaitAsync(next.Due).ConfigureAwait(false);
            _ups.Remove(next);
            await UpAsync(next).ConfigureAwait(false);
        }
    }

    public async Task KeyAsync(string ch)
    {
        var cfg = _cfg;
        double at = _lastPress == null ? Now
            : _delay != null ? _lastPress.Value + _delay.Value
            : _lastPress.Value + KeyTiming.KeyGap(cfg, _prev, ch);
        bool single = ch.Length == 1;
        bool isSymbol = single && HumanKeyboard.ShiftSymbols.Contains(ch[0]);
        bool shifted = single && (ch[0] is >= 'A' and <= 'Z' || isSymbol);
        // Text without a key (non-ASCII, emoji / combined graphemes, a "\r\n" pair) is
        // inserted as one input; multi-letter ASCII names ("Backspace") are real keys.
        bool textOnly = single ? ch[0] > 0x7F : ch.Any(c => c > 0x7F || char.IsControl(c));
        // A key cannot go down twice: let the earlier press of the same physical key
        // ("x" before "X", "1" before "!") come up first.
        string key = HumanKeyboard.PhysicalKey(ch);
        var same = _ups.Where(u => HumanKeyboard.PhysicalKey(u.Key) == key).ToList();
        if (same.Count > 0) at = Math.Max(at, same.Min(u => u.Due) + 5);
        if (shifted)
        {
            if (_shiftUpDue != null)
            {
                _shiftUpDue = null; // still down from the previous capital
                await FlushAsync(at).ConfigureAwait(false);
            }
            else
            {
                double lead = HumanRandom.RandLog(cfg.ShiftDownDelay);
                // Shift goes down after the previous key comes up.
                await FlushAsync(at - lead).ConfigureAwait(false);
                await WaitAsync(at - lead).ConfigureAwait(false);
                await ShiftAsync(true).ConfigureAwait(false);
                // Keys due to come up while Shift is going down (e.g. the "x" of "xX")
                // are released before the capital is pressed.
                await FlushAsync(at).ConfigureAwait(false);
            }
        }
        else
        {
            await FlushAsync(at).ConfigureAwait(false);
            if (_shiftUpDue != null && ch != "Backspace")
            {
                // A lower-case key while Shift is still down: let it go first.
                _shiftUpDue = null;
                await ShiftAsync(false).ConfigureAwait(false);
            }
        }
        await WaitAsync(at).ConfigureAwait(false);
        double pressed = Math.Max(at, Now);
        _lastPress = pressed;
        double hold0 = KeyTiming.KeyHold(cfg);
        double hold = _delay != null && _delay.Value < hold0 ? _delay.Value : hold0;
        double upAt = pressed + hold;
        if (textOnly)
        {
            // Non-ASCII text has no key: it arrives as one input, like an IME.
            await _insertText(ch).ConfigureAwait(false);
        }
        else if (isSymbol)
        {
            var (code, vk) = HumanKeyboard.ShiftSymbolKey(ch[0]);
            await _cdp(new()
            {
                ["type"] = "keyDown", ["modifiers"] = 8, ["key"] = ch, ["code"] = code,
                ["windowsVirtualKeyCode"] = vk, ["text"] = ch, ["unmodifiedText"] = ch,
            }).ConfigureAwait(false);
            _ups.Add(new KeyUp(upAt, ch, new()
            {
                ["type"] = "keyUp", ["modifiers"] = 8, ["key"] = ch, ["code"] = code, ["windowsVirtualKeyCode"] = vk,
            }));
        }
        else
        {
            await _down(ch).ConfigureAwait(false);
            _ups.Add(new KeyUp(upAt, ch, null));
        }
        if (shifted)
        {
            // Usually let go of Shift around the letter's release, most often just before it.
            _shiftUpDue = Math.Max(pressed + 10, upAt + HumanRandom.RandRange(cfg.ShiftUpDelay));
            // The CDP keyUp of a shift symbol carries the Shift modifier.
            if (isSymbol) _shiftUpDue = Math.Max(_shiftUpDue.Value, upAt + 5);
        }
        _prev = ch;
    }

    /// <summary>Release everything still held, on schedule.</summary>
    public Task FinishAsync() => FlushAsync(double.PositiveInfinity);

    /// <summary>Hands off the keys (before a pause): release, and start the next key without
    /// a gap carried over from the last one.</summary>
    public async Task RestAsync()
    {
        await FinishAsync().ConfigureAwait(false);
        _lastPress = null;
    }

    /// <summary>Error path: never leave a key stuck down.</summary>
    public async Task ReleaseAllAsync()
    {
        var ups = _ups.ToList();
        _ups.Clear();
        foreach (var u in ups)
        {
            try { await UpAsync(u).ConfigureAwait(false); } catch { /* best effort */ }
        }
        _shiftUpDue = null;
        if (_shiftDown)
        {
            try { await ShiftAsync(false).ConfigureAwait(false); } catch { /* best effort */ }
        }
    }
}
