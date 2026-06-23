using CloakBrowser.Human;
using Xunit;

namespace CloakBrowser.Tests.Human;

/// <summary>
/// Ports Python <c>TestNonAsciiKeyboard</c>: non-ASCII characters (Cyrillic, CJK)
/// must be entered via <see cref="IRawKeyboard.InsertTextAsync"/> character-by-character,
/// while ASCII characters go through <see cref="IRawKeyboard.DownAsync"/> /
/// <see cref="IRawKeyboard.UpAsync"/>. Mistyping is disabled (MistypeChance = 0) so the
/// key streams are deterministic.
/// </summary>
public class NonAsciiKeyboardTests
{
    /// <summary>A fake raw keyboard that records the keys pressed and the text inserted.</summary>
    private sealed class RecordingKeyboard : IRawKeyboard
    {
        public List<string> DownKeys { get; } = new();
        public List<string> UpKeys { get; } = new();
        public List<string> Inserted { get; } = new();
        public List<string> Typed { get; } = new();

        public Task DownAsync(string key) { DownKeys.Add(key); return Task.CompletedTask; }
        public Task UpAsync(string key) { UpKeys.Add(key); return Task.CompletedTask; }
        public Task TypeAsync(string text) { Typed.Add(text); return Task.CompletedTask; }
        public Task InsertTextAsync(string text) { Inserted.Add(text); return Task.CompletedTask; }
    }

    // No delays, no typos: deterministic key streams.
    private static HumanConfig FastConfig() => new()
    {
        TypingDelay = 0,
        TypingDelaySpread = 0,
        TypingPauseChance = 0,
        MistypeChance = 0,
        ShiftDownDelay = (0, 0),
        ShiftUpDelay = (0, 0),
        KeyHold = (0, 0),
    };

    private static bool IsAscii(string s) => s.All(c => c <= 0x7F);

    [Fact]
    public async Task Cyrillic_uses_insert_text()
    {
        var kb = new RecordingKeyboard();

        await HumanKeyboard.HumanTypeAsync(evaluator: null, kb, "Привет", FastConfig());

        // Whole word arrives through insertText, one character at a time.
        Assert.Equal("Привет", string.Concat(kb.Inserted));
        // No non-ASCII character was ever pressed as a key.
        Assert.All(kb.DownKeys, k => Assert.True(IsAscii(k), $"unexpected non-ASCII key down: {k}"));
    }

    [Fact]
    public async Task Mixed_ascii_cyrillic_routes_each_char_correctly()
    {
        var kb = new RecordingKeyboard();

        await HumanKeyboard.HumanTypeAsync(evaluator: null, kb, "Hi Мир", FastConfig());

        // ASCII letters are pressed as keys...
        Assert.Contains("H", kb.DownKeys);
        Assert.Contains("i", kb.DownKeys);
        // ...Cyrillic letters are inserted as text.
        Assert.Contains("М", string.Concat(kb.Inserted));
        Assert.Contains("и", string.Concat(kb.Inserted));
        Assert.Contains("р", string.Concat(kb.Inserted));
    }

    [Fact]
    public async Task Cjk_uses_insert_text()
    {
        var kb = new RecordingKeyboard();

        await HumanKeyboard.HumanTypeAsync(evaluator: null, kb, "你好", FastConfig());

        Assert.Equal("你好", string.Concat(kb.Inserted));
        Assert.All(kb.DownKeys, k => Assert.True(IsAscii(k), $"unexpected non-ASCII key down: {k}"));
    }

    [Fact]
    public async Task Ascii_uppercase_goes_through_shifted_key_presses_not_insert()
    {
        var kb = new RecordingKeyboard();

        await HumanKeyboard.HumanTypeAsync(evaluator: null, kb, "Hi", FastConfig());

        // ASCII never uses insertText.
        Assert.Empty(kb.Inserted);
        // Uppercase 'H' is produced by holding Shift.
        Assert.Contains("Shift", kb.DownKeys);
        Assert.Contains("H", kb.DownKeys);
        Assert.Contains("i", kb.DownKeys);
    }
}
