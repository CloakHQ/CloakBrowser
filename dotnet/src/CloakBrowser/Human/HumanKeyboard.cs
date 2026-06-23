using System.Text.Json.Nodes;

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
        ['1'] = "2q", ['2'] = "13qw", ['3'] = "24we", ['4'] = "35er", ['5'] = "46rt",
        ['6'] = "57ty", ['7'] = "68yu", ['8'] = "79ui", ['9'] = "80io", ['0'] = "9p",
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
                await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.KeyHold)).ConfigureAwait(false);
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
                await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.KeyHold)).ConfigureAwait(false);
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
        await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.KeyHold)).ConfigureAwait(false);
        await raw.UpAsync(ch.ToString()).ConfigureAwait(false);
    }

    private static async Task TypeShiftedCharAsync(IRawKeyboard raw, char ch, HumanConfig cfg)
    {
        await raw.DownAsync("Shift").ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.ShiftDownDelay)).ConfigureAwait(false);
        await raw.DownAsync(ch.ToString()).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.KeyHold)).ConfigureAwait(false);
        await raw.UpAsync(ch.ToString()).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.ShiftUpDelay)).ConfigureAwait(false);
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
            await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.ShiftDownDelay)).ConfigureAwait(false);

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
            await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.KeyHold)).ConfigureAwait(false);

            await cdpSession.SendAsync("Input.dispatchKeyEvent", new JsonObject
            {
                ["type"] = "keyUp",
                ["modifiers"] = 8,
                ["key"] = s,
                ["code"] = code,
                ["windowsVirtualKeyCode"] = keyCode,
            }).ConfigureAwait(false);

            await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.ShiftUpDelay)).ConfigureAwait(false);
            await raw.UpAsync("Shift").ConfigureAwait(false);
        }
        else
        {
            // --- Fallback path: page.evaluate (detectable) ---
            await raw.DownAsync("Shift").ConfigureAwait(false);
            await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.ShiftDownDelay)).ConfigureAwait(false);
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
            await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.ShiftUpDelay)).ConfigureAwait(false);
            await raw.UpAsync("Shift").ConfigureAwait(false);
        }
    }

    private static async Task InterCharDelayAsync(HumanConfig cfg)
    {
        if (HumanRandom.NextDouble() < cfg.TypingPauseChance)
        {
            await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.TypingPauseRange)).ConfigureAwait(false);
        }
        else
        {
            double delay = cfg.TypingDelay + (HumanRandom.NextDouble() - 0.5) * 2 * cfg.TypingDelaySpread;
            await HumanRandom.SleepMsAsync(Math.Max(10, delay)).ConfigureAwait(false);
        }
    }
}
