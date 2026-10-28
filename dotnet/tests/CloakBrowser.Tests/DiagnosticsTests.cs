using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using CloakBrowser;
using Xunit;

namespace CloakBrowser.Tests;

/// <summary>
/// Diagnostics.Collect drives the `info` / `doctor` CLI. In quick mode it never
/// spawns the binary, so an isolated temp cache dir yields a deterministic
/// "free / not installed" result with no network. Env-serial because it pins
/// CLOAKBROWSER_CACHE_DIR / CLOAKBROWSER_LICENSE_KEY for the duration.
/// </summary>
[Collection("env-serial")]
public class DiagnosticsTests
{
    [Fact]
    public void Quick_skips_launch_and_reports_free_license()
    {
        var tmp = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
        Directory.CreateDirectory(tmp);
        string? prevCache = Environment.GetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR");
        string? prevKey = Environment.GetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY");
        try
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", tmp);
            Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", null);

            var diag = Diagnostics.Collect(quick: true);

            var env = Assert.IsType<Dictionary<string, object?>>(diag["environment"]);
            Assert.NotNull(env["dotnet"]);

            var launch = Assert.IsType<Dictionary<string, object?>>(diag["launch"]);
            Assert.Equal(false, launch["tested"]);
            Assert.Contains("--quick", (string)launch["reason"]!);

            var license = Assert.IsType<Dictionary<string, object?>>(diag["license"]);
            Assert.Equal("free", license["tier"]);

            Assert.True(diag.ContainsKey("binary"));
            Assert.True(diag.ContainsKey("geoip"));
            // modules section mirrors Python/JS for cross-language parity
            var modules = Assert.IsType<Dictionary<string, object?>>(diag["modules"]);
            Assert.True((bool)modules["playwright"]!);
            // fonts section is Linux-only
            Assert.Equal(RuntimeInformation.IsOSPlatform(OSPlatform.Linux), diag.ContainsKey("fonts"));
        }
        finally
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", prevCache);
            Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", prevKey);
            try { Directory.Delete(tmp, recursive: true); } catch { /* best-effort */ }
        }
    }

    [Fact]
    public void No_proxy_never_resolves_geoip_and_stays_network_free()
    {
        var tmp = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
        Directory.CreateDirectory(tmp);
        string? prevCache = Environment.GetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR");
        string? prevKey = Environment.GetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY");
        try
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", tmp);
            Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", null);

            // Default `info` (no proxy) must not resolve — no exit-IP lookup, no
            // GeoIP DB download. The "resolved" key is only added when a proxy is given.
            var diag = Diagnostics.Collect(quick: true);
            var geoip = Assert.IsType<Dictionary<string, object?>>(diag["geoip"]);
            Assert.False(geoip.ContainsKey("resolved"));
        }
        finally
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", prevCache);
            Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", prevKey);
            try { Directory.Delete(tmp, recursive: true); } catch { /* best-effort */ }
        }
    }

    [Fact]
    public void Preview_reports_stable_fallback_and_next_launch_version()
    {
        var tmp = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
        Directory.CreateDirectory(tmp);
        string? prevCache = Environment.GetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR");
        string? prevKey = Environment.GetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY");
        string? prevChannel = Environment.GetEnvironmentVariable("CLOAKBROWSER_RELEASE_CHANNEL");
        try
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", tmp);
            Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", "cb_test");
            Environment.SetEnvironmentVariable("CLOAKBROWSER_RELEASE_CHANNEL", "preview");
            License.ValidateLicenseOverride = _ => new LicenseInfo(true, "business", null);
            License.ProLatestReleaseOverride = () =>
                new ProReleaseInfo("150.0.7871.114.3", "preview", "stable", true);
            License.ActiveSessionCountOverride = _ => null;

            var diag = Diagnostics.Collect(quick: false);
            var binary = Assert.IsType<Dictionary<string, object?>>(diag["binary"]);

            Assert.Equal("preview", binary["requested_channel"]);
            Assert.Equal("stable", binary["resolved_channel"]);
            Assert.Equal(true, binary["channel_fallback"]);
            Assert.Equal("150.0.7871.114.3", binary["version"]);
        }
        finally
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", prevCache);
            Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", prevKey);
            Environment.SetEnvironmentVariable("CLOAKBROWSER_RELEASE_CHANNEL", prevChannel);
            License.ValidateLicenseOverride = null;
            License.ProLatestReleaseOverride = null;
            License.ActiveSessionCountOverride = null;
            try { Directory.Delete(tmp, recursive: true); } catch { /* best-effort */ }
        }
    }

    // =======================================================================
    // FormatSeats — the CLI's "Sessions:" line
    //
    // Kept byte-identical to the Python (_format_seats) and JS (formatSeats)
    // renderers: the three wrappers must print the same line for the same state.
    // =======================================================================

    private static Dictionary<string, object?> Seats(
        int? active = null, int? limit = null, string state = "ok", string? reason = null)
    {
        var d = new Dictionary<string, object?> { ["state"] = state, ["reason"] = reason };
        if (active is not null) d["active"] = active.Value;
        if (limit is not null) d["limit"] = limit.Value;
        return d;
    }

    [Fact]
    public void FormatSeats_shows_used_over_limit()
    {
        // The point of the change: a scale-plan customer can see they are nowhere
        // near the ceiling (or right on it) instead of reading a bare number.
        Assert.Equal("8/2000 in use", Diagnostics.FormatSeats(Seats(active: 8, limit: 2000)));
    }

    [Fact]
    public void FormatSeats_falls_back_when_the_server_sends_no_limit()
    {
        // Older server, unlimited licence, or an unrecognised plan. Never "8/unknown".
        Assert.Equal("8 seats in use", Diagnostics.FormatSeats(Seats(active: 8)));
    }

    [Fact]
    public void FormatSeats_uses_the_singular_in_the_fallback()
    {
        Assert.Equal("1 seat in use", Diagnostics.FormatSeats(Seats(active: 1)));
    }

    [Fact]
    public void FormatSeats_shows_the_limit_for_a_single_seat()
    {
        // A free key holds exactly one seat - the cohort most likely to hit its cap.
        Assert.Equal("1/1 in use", Diagnostics.FormatSeats(Seats(active: 1, limit: 1)));
    }

    [Fact]
    public void FormatSeats_keeps_zero_as_a_real_answer()
    {
        Assert.Equal("0/5 in use", Diagnostics.FormatSeats(Seats(active: 0, limit: 5)));
    }

    [Fact]
    public void FormatSeats_says_so_when_the_server_is_unreachable()
    {
        Assert.Equal("unavailable (cannot reach cloakbrowser.dev)",
            Diagnostics.FormatSeats(Seats(state: "unreachable")));
    }

    [Theory]
    [InlineData("license_inactive", "license inactive")]
    [InlineData("invalid_key", "invalid key")]
    [InlineData("rate_limited", "rate limited")]
    public void FormatSeats_spells_out_the_denial(string code, string shown)
    {
        // These used to be one string. A dead key and a healthy key behind a
        // degraded backend must not read identically.
        Assert.Equal($"unavailable ({shown})",
            Diagnostics.FormatSeats(Seats(state: "denied", reason: code)));
    }

    [Fact]
    public void FormatSeats_passes_an_unrecognised_denial_reason_through()
    {
        Assert.Equal("unavailable (some_new_code)",
            Diagnostics.FormatSeats(Seats(state: "denied", reason: "some_new_code")));
    }

    [Fact]
    public void FormatSeats_degraded_backend_does_not_read_like_a_licence_problem()
    {
        // Leaseless mode / seat store down: the key is fine, nothing for them to do.
        Assert.Equal("unavailable (server cannot report seats right now)",
            Diagnostics.FormatSeats(Seats(state: "unknown")));
    }
}
