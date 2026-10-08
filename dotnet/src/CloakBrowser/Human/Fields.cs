using System.Text.RegularExpressions;

namespace CloakBrowser.Human;

/// <summary>
/// Field classification for humanized text input. Port of
/// <c>cloakbrowser/human/fields.py</c>; mirrors Playwright's <c>InjectedScript.fill</c>
/// rules so the humanize layer accepts and rejects the same targets Playwright does:
/// text-like inputs are typed into key by key, value inputs (date, range, ...) are
/// operated through their native widget the way a person does it, everything else
/// (checkbox, file, hidden, radio, ...) cannot be filled.
/// Mistypes are only simulated where a correction is safe: never in
/// number/email/password/tel/url fields.
/// </summary>
internal static class Fields
{
    public static readonly IReadOnlySet<string> TypeInto =
        new HashSet<string> { "", "email", "number", "password", "search", "tel", "text", "url" };
    public static readonly IReadOnlySet<string> SetValue =
        new HashSet<string> { "color", "date", "time", "datetime-local", "month", "range", "week" };
    public static readonly IReadOnlySet<string> NoMistype =
        new HashSet<string> { "number", "email", "password", "tel", "url" };

    public enum Kind { Type, Set, NotFillable }

    public static Kind Classify(string? tag, string? inputType, bool editable)
    {
        var t = (tag ?? "").ToLowerInvariant();
        if (t == "input")
        {
            var it = (inputType ?? "").ToLowerInvariant();
            if (TypeInto.Contains(it)) return Kind.Type;
            if (SetValue.Contains(it)) return Kind.Set;
            return Kind.NotFillable;
        }
        return t == "textarea" || editable ? Kind.Type : Kind.NotFillable;
    }

    public static bool AllowsMistype(string? tag, string? inputType) =>
        (tag ?? "").ToLowerInvariant() != "input" || !NoMistype.Contains((inputType ?? "").ToLowerInvariant());

    public static string NormalizeSetValue(string? inputType, string value)
    {
        var v = value.Trim();
        return (inputType ?? "").ToLowerInvariant() == "color" ? v.ToLowerInvariant() : v;
    }

    /// <summary>Playwright rejects non-numeric text for input[type=number]; null = invalid.</summary>
    public static string? ValidateNumber(string value)
    {
        var v = value.Trim();
        if (v.Length == 0) return v;
        return double.TryParse(v, System.Globalization.NumberStyles.Float,
            System.Globalization.CultureInfo.InvariantCulture, out _) ? v : null;
    }

    public static string NotFillableMessage(string? tag, string? inputType) =>
        (tag ?? "").ToLowerInvariant() == "input"
            ? $"Input of type \"{(inputType ?? "").ToLowerInvariant()}\" cannot be filled"
            : "Element is not an <input>, <textarea> or [contenteditable] element";

    // -----------------------------------------------------------------------
    // Native date/time editors
    // -----------------------------------------------------------------------

    private const string Date = @"(?<year>\d{4,6})-(?<month>\d{2})-(?<day>\d{2})";
    private const string Time = @"(?<hour>\d{2}):(?<minute>\d{2})(?::(?<second>\d{2})(?:\.(?<millisecond>\d{1,3}))?)?";

    private static readonly Dictionary<string, Regex> DtPatterns = new()
    {
        ["date"] = new Regex("^" + Date + "$"),
        ["month"] = new Regex(@"^(?<year>\d{4,6})-(?<month>\d{2})$"),
        ["week"] = new Regex(@"^(?<year>\d{4,6})-W(?<week>\d{2})$"),
        ["time"] = new Regex("^" + Time + "$"),
        ["datetime-local"] = new Regex("^" + Date + "T" + Time + "$"),
    };

    private static readonly Dictionary<string, int> FullWidth = new()
    {
        ["month"] = 2, ["day"] = 2, ["week"] = 2, ["hour"] = 2, ["minute"] = 2, ["second"] = 2, ["millisecond"] = 3,
    };

    private static readonly string[] Groups = { "year", "month", "day", "week", "hour", "minute", "second", "millisecond" };

    /// <summary>Editor segment keystrokes of an HTML date/time value (null when malformed).
    /// <c>hour</c> is the 12-hour form shown next to an AM/PM segment; <see cref="DateTimeParts.Hour24"/>
    /// keeps the original hour.</summary>
    public static DateTimeParts? ParseDateTime(string inputType, string value)
    {
        if (!DtPatterns.TryGetValue(inputType, out var re)) return null;
        var m = re.Match(value);
        if (!m.Success) return null;
        var parts = new Dictionary<string, string>();
        foreach (var g in Groups)
            if (m.Groups[g].Success) parts[g] = m.Groups[g].Value;
        int? hour24 = null;
        if (parts.TryGetValue("hour", out var h))
        {
            hour24 = int.Parse(h);
            parts["hour"] = (hour24.Value % 12 == 0 ? 12 : hour24.Value % 12).ToString("00");
        }
        if (parts.TryGetValue("millisecond", out var ms)) parts["millisecond"] = ms.PadRight(3, '0');
        return new DateTimeParts(parts, hour24);
    }

    /// <summary>Pick the hour digits matching the editor (with or without AM/PM).</summary>
    public static DateTimeParts Use24h(DateTimeParts p, bool hasAmpm)
    {
        if (p.Hour24 == null || hasAmpm) return p;
        var d = new Dictionary<string, string>(p.Values) { ["hour"] = p.Hour24.Value.ToString("00") };
        return new DateTimeParts(d, p.Hour24);
    }

    /// <summary>Whether typing this segment's digits moves focus to the next segment.
    /// Two-digit segments advance; the year segment never does (up to six digits).</summary>
    public static bool SegmentAutoAdvances(string kind, DateTimeParts p, string inputType = "")
    {
        if (inputType == "month" && kind == "month") return false; // shown as a month name
        return FullWidth.TryGetValue(kind, out var w) && p.Values.TryGetValue(kind, out var v) && v.Length >= w;
    }
}

internal sealed record DateTimeParts(IReadOnlyDictionary<string, string> Values, int? Hour24)
{
    public bool Has(string kind) => Values.ContainsKey(kind);
    public string this[string kind] => Values[kind];
}
