namespace CloakBrowser.Human;

/// <summary>A (min, max) inclusive numeric range, mirroring Python's <c>Range = Tuple[float, float]</c>.</summary>
public readonly record struct Range(double Min, double Max)
{
    public static implicit operator Range((double Min, double Max) t) => new(t.Min, t.Max);
}

/// <summary>Humanize behavior preset names.</summary>
public enum HumanPreset
{
    Default,
    Careful,
}

/// <summary>
/// All tunable parameters for human-like behavior.
/// Direct port of Python <c>cloakbrowser/human/config.py</c> (the <c>HumanConfig</c> dataclass).
/// Property names match the Python field names (snake_case keys are accepted by
/// <see cref="HumanConfigExtensions.With(HumanConfig, IReadOnlyDictionary{string, object})"/>).
/// </summary>
public sealed class HumanConfig
{
    // Keyboard
    public double TypingDelay { get; set; } = 70;
    public double TypingDelaySpread { get; set; } = 40;
    public double TypingPauseChance { get; set; } = 0.1;
    public Range TypingPauseRange { get; set; } = (400, 1000);
    public Range ShiftDownDelay { get; set; } = (30, 70);
    public Range ShiftUpDelay { get; set; } = (20, 50);
    public Range KeyHold { get; set; } = (15, 35);

    // Mistype (typo simulation)
    public double MistypeChance { get; set; } = 0.02;
    public Range MistypeDelayNotice { get; set; } = (100, 300);
    public Range MistypeDelayCorrect { get; set; } = (50, 150);

    public Range FieldSwitchDelay { get; set; } = (800, 1500);

    // Mouse - movement
    public double MouseStepsDivisor { get; set; } = 8;
    public int MouseMinSteps { get; set; } = 25;
    public int MouseMaxSteps { get; set; } = 80;
    public double MouseWobbleMax { get; set; } = 1.5;
    public double MouseOvershootChance { get; set; } = 0.15;
    public Range MouseOvershootPx { get; set; } = (3, 6);
    public Range MouseBurstSize { get; set; } = (3, 5);
    public Range MouseBurstPause { get; set; } = (8, 18);

    // Mouse - clicks
    public Range ClickAimDelayInput { get; set; } = (60, 140);
    public Range ClickAimDelayButton { get; set; } = (80, 200);
    public Range ClickHoldInput { get; set; } = (40, 100);
    public Range ClickHoldButton { get; set; } = (60, 150);
    public Range ClickInputXRange { get; set; } = (0.05, 0.30);

    // Mouse - idle
    public double IdleDriftPx { get; set; } = 3;
    public Range IdlePauseRange { get; set; } = (300, 1000);

    // Scroll
    public Range ScrollDeltaBase { get; set; } = (80, 130);
    public double ScrollDeltaVariance { get; set; } = 0.2;
    public Range ScrollPauseFast { get; set; } = (30, 80);
    public Range ScrollPauseSlow { get; set; } = (80, 200);
    public Range ScrollAccelSteps { get; set; } = (2, 3);
    public Range ScrollDecelSteps { get; set; } = (2, 3);
    public double ScrollOvershootChance { get; set; } = 0.1;
    public Range ScrollOvershootPx { get; set; } = (50, 150);
    public Range ScrollSettleDelay { get; set; } = (300, 600);
    public Range ScrollTargetZone { get; set; } = (0.20, 0.80);
    public Range ScrollPreMoveDelay { get; set; } = (100, 300);

    // Initial cursor position (as if coming from the address bar area)
    public Range InitialCursorX { get; set; } = (400, 700);
    public Range InitialCursorY { get; set; } = (45, 60);

    // Idle micro-movements between actions (opt-in, adds latency)
    public bool IdleBetweenActions { get; set; } = false;
    public Range IdleBetweenDuration { get; set; } = (0.3, 0.8);

    /// <summary>Create a shallow copy of this config.</summary>
    public HumanConfig Clone() => (HumanConfig)MemberwiseClone();
}

/// <summary>Resolution and merging helpers for <see cref="HumanConfig"/>.</summary>
public static class HumanConfigFactory
{
    private static HumanConfig CarefulConfig() => new()
    {
        // Keyboard - slower typing
        TypingDelay = 100,
        TypingDelaySpread = 50,
        TypingPauseChance = 0.15,
        TypingPauseRange = (500, 1200),
        ShiftDownDelay = (40, 90),
        ShiftUpDelay = (30, 70),
        KeyHold = (20, 45),
        FieldSwitchDelay = (1000, 2000),
        // Mouse - slower, more precise
        MouseOvershootChance = 0.10,
        MouseBurstPause = (12, 25),
        // Mouse - clicks (longer aiming and holding)
        ClickAimDelayInput = (80, 180),
        ClickAimDelayButton = (120, 280),
        ClickHoldInput = (60, 140),
        ClickHoldButton = (80, 200),
        // Scroll - slower
        ScrollPauseFast = (100, 200),
        ScrollPauseSlow = (250, 600),
        ScrollSettleDelay = (400, 800),
        ScrollPreMoveDelay = (150, 400),
        // Idle between actions enabled for careful preset
        IdleBetweenActions = true,
        IdleBetweenDuration = (0.4, 1.0),
    };

    /// <summary>
    /// Resolve a preset name + optional overrides into a full <see cref="HumanConfig"/>.
    /// </summary>
    public static HumanConfig Resolve(
        HumanPreset preset = HumanPreset.Default,
        IReadOnlyDictionary<string, object>? overrides = null)
    {
        var baseCfg = preset switch
        {
            HumanPreset.Default => new HumanConfig(),
            HumanPreset.Careful => CarefulConfig(),
            _ => throw new ArgumentException($"Unknown humanize preset {preset}."),
        };
        return overrides == null || overrides.Count == 0
            ? baseCfg
            : baseCfg.With(overrides);
    }

    /// <summary>Parse a preset name string ('default'/'careful'), case-insensitive.</summary>
    public static HumanPreset ParsePreset(string? preset) => (preset ?? "default").ToLowerInvariant() switch
    {
        "default" => HumanPreset.Default,
        "careful" => HumanPreset.Careful,
        _ => throw new ArgumentException(
            $"Unknown humanize preset '{preset}'. Valid presets: careful, default"),
    };
}

/// <summary>Extension helpers for merging override dictionaries onto a <see cref="HumanConfig"/>.</summary>
public static class HumanConfigExtensions
{
    /// <summary>
    /// Merge a dictionary of overrides (keys may be snake_case like the Python API,
    /// or PascalCase property names) on top of <paramref name="baseCfg"/>.
    /// Returns a new config - the base is never mutated. Unknown keys are ignored.
    /// </summary>
    public static HumanConfig With(this HumanConfig baseCfg, IReadOnlyDictionary<string, object>? overrides)
    {
        if (overrides == null || overrides.Count == 0)
            return baseCfg.Clone();

        var result = baseCfg.Clone();
        foreach (var (key, value) in overrides)
        {
            var prop = ResolveProperty(key);
            if (prop == null) continue; // unknown keys ignored silently
            try
            {
                prop.SetValue(result, Coerce(value, prop.PropertyType));
            }
            catch (Exception) { /* ignore bad coercions, matching Python's forgiving merge */ }
        }
        return result;
    }

    private static System.Reflection.PropertyInfo? ResolveProperty(string key)
    {
        var pascal = SnakeToPascal(key);
        return typeof(HumanConfig).GetProperty(pascal,
            System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance);
    }

    private static string SnakeToPascal(string key)
    {
        if (!key.Contains('_'))
            // Already PascalCase (or single word) - normalise first char to upper.
            return key.Length == 0 ? key : char.ToUpperInvariant(key[0]) + key[1..];
        var parts = key.Split('_', StringSplitOptions.RemoveEmptyEntries);
        return string.Concat(parts.Select(p => char.ToUpperInvariant(p[0]) + p[1..]));
    }

    private static object Coerce(object value, Type target)
    {
        if (target == typeof(Range))
        {
            // Accept (double,double) tuple, double[]/object[] of length 2, List, etc.
            switch (value)
            {
                case Range r:
                    return r;
                case ValueTuple<double, double> vt:
                    return new Range(vt.Item1, vt.Item2);
                case IEnumerable<object> seq:
                {
                    var arr = seq.ToArray();
                    if (arr.Length >= 2)
                        return new Range(Convert.ToDouble(arr[0]), Convert.ToDouble(arr[1]));
                    break;
                }
                case System.Collections.IEnumerable en and not string:
                {
                    var list = en.Cast<object>().ToArray();
                    if (list.Length >= 2)
                        return new Range(Convert.ToDouble(list[0]), Convert.ToDouble(list[1]));
                    break;
                }
            }
            throw new InvalidCastException("Cannot convert value to Range");
        }
        if (target == typeof(bool)) return Convert.ToBoolean(value);
        if (target == typeof(int)) return Convert.ToInt32(value);
        if (target == typeof(double)) return Convert.ToDouble(value);
        return value;
    }
}
