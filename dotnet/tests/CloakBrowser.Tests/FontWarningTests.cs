using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using CloakBrowser;
using Xunit;

namespace CloakBrowser.Tests;

/// <summary>
/// Welcome-banner cadence (Download.WelcomeDue): free re-shows every day,
/// Pro shows once ever. Pure function over a marker file — fully deterministic.
/// </summary>
public class WelcomeCadenceTests
{
    private static string TempMarker() => Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());

    [Fact]
    public void Pro_shows_once_then_never()
    {
        var marker = TempMarker();
        try
        {
            Assert.True(Download.WelcomeDue(marker, pro: true)); // absent -> show
            File.WriteAllText(marker, DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString());
            Assert.False(Download.WelcomeDue(marker, pro: true)); // exists -> never again
        }
        finally { if (File.Exists(marker)) File.Delete(marker); }
    }

    [Fact]
    public void Free_reshows_after_interval()
    {
        var marker = TempMarker();
        try
        {
            Assert.True(Download.WelcomeDue(marker, pro: false)); // absent -> show
            var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
            File.WriteAllText(marker, now.ToString());
            Assert.False(Download.WelcomeDue(marker, pro: false)); // fresh -> skip
            File.WriteAllText(marker, (now - Download.WelcomeFreeInterval - 10).ToString());
            Assert.True(Download.WelcomeDue(marker, pro: false)); // stale -> show again
        }
        finally { if (File.Exists(marker)) File.Delete(marker); }
    }

    [Fact]
    public void Legacy_empty_marker_free_reshows_pro_silent()
    {
        var marker = TempMarker();
        try
        {
            File.WriteAllText(marker, ""); // pre-cadence empty marker
            Assert.True(Download.WelcomeDue(marker, pro: false)); // unparseable -> free re-shows
            Assert.False(Download.WelcomeDue(marker, pro: true)); // pro: existence = already shown
        }
        finally { if (File.Exists(marker)) File.Delete(marker); }
    }
}

/// <summary>
/// The welcome banner runs on the binary-download path. On a legacy Windows
/// console a non-ASCII glyph can crash or mojibake the write (ticket 2354), so
/// the banner must be pure ASCII. Mirrors the Python/JS welcome tests.
/// Serialized: mutates CLOAKBROWSER_CACHE_DIR and Console.Error.
/// </summary>
[Collection("env-serial")]
public class WelcomeBannerAsciiTests
{
    [Theory]
    [InlineData("keyless")]
    [InlineData("free")]
    [InlineData("pro")]
    public void Banner_is_ascii_only(string tier)
    {
        var prev = Environment.GetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR");
        var tmp = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
        Directory.CreateDirectory(tmp);
        var origErr = Console.Error;
        var buf = new StringWriter();
        try
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", tmp);
            Console.SetError(buf);
            Download.ShowWelcome(tier); // marker absent -> shows
            var outText = buf.ToString();
            Assert.NotEqual("", outText);
            foreach (var c in outText)
                Assert.True(c <= 0x7F, $"non-ASCII U+{(int)c:X4} in {tier} banner");
        }
        finally
        {
            Console.SetError(origErr);
            Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", prev);
            try { Directory.Delete(tmp, recursive: true); } catch { /* best-effort */ }
        }
    }
}

/// <summary>
/// Linux Windows-font mismatch warning. Platform detection and fc-list aren't
/// mockable without a DI refactor, so these cover the deterministic paths: the
/// non-windows short-circuit (returns before any probe on every OS) and the
/// once-per-process guard. Serialized: mutates a static flag + CLOAKBROWSER_CACHE_DIR.
/// </summary>
[Collection("env-serial")]
public class FontWarningTests
{
    [Fact]
    public void No_warn_no_marker_when_platform_overridden()
    {
        var prev = Environment.GetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR");
        var tmp = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
        Directory.CreateDirectory(tmp);
        try
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", tmp);
            CloakLauncher._fontWarningChecked = false;

            var ex = Record.Exception(() =>
                CloakLauncher.MaybeWarnWindowsFonts(new[] { "--fingerprint-platform=linux", "--no-sandbox" }));

            Assert.Null(ex); // never throws
            Assert.False(File.Exists(Path.Combine(tmp, ".font_warning_shown")));
        }
        finally
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", prev);
            CloakLauncher._fontWarningChecked = false;
            try { Directory.Delete(tmp, recursive: true); } catch { /* best-effort */ }
        }
    }

    [Fact]
    public void WindowsFontsPresent_returns_within_timeout_when_fc_list_hangs()
    {
        // Issue 1 regression guard: a hanging fc-list must not stall the probe past
        // the 5s ceiling. Shim a sleeping "fc-list" on PATH (POSIX hosts only).
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows)) return;

        var dir = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
        Directory.CreateDirectory(dir);
        var shim = Path.Combine(dir, "fc-list");
        File.WriteAllText(shim, "#!/bin/sh\nsleep 30\n");
        using (var chmod = Process.Start(new ProcessStartInfo("chmod", $"+x \"{shim}\"") { UseShellExecute = false }))
        {
            chmod!.WaitForExit();
        }

        var prevPath = Environment.GetEnvironmentVariable("PATH");
        var sw = Stopwatch.StartNew();
        try
        {
            Environment.SetEnvironmentVariable("PATH", dir + Path.PathSeparator + prevPath);
            var result = CloakLauncher.WindowsFontsPresent();
            sw.Stop();
            Assert.Null(result); // timed out -> undeterminable, never "no fonts"
            Assert.True(sw.Elapsed.TotalSeconds < 8,
                $"probe took {sw.Elapsed.TotalSeconds:F1}s; the 5s timeout did not bound it");
        }
        finally
        {
            Environment.SetEnvironmentVariable("PATH", prevPath);
            try { Directory.Delete(dir, recursive: true); } catch { /* best-effort */ }
        }
    }

    [Fact]
    public void Probes_at_most_once_per_process()
    {
        var prev = Environment.GetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR");
        var tmp = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
        Directory.CreateDirectory(tmp);
        try
        {
            // Redirect the cache dir so a Linux host without Windows fonts writes
            // its marker here, not into the real ~/.cloakbrowser.
            Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", tmp);
            CloakLauncher._fontWarningChecked = false;
            var ex = Record.Exception(() =>
            {
                CloakLauncher.MaybeWarnWindowsFonts(new[] { "--fingerprint-platform=windows" });
                CloakLauncher.MaybeWarnWindowsFonts(new[] { "--fingerprint-platform=windows" });
            });
            Assert.Null(ex);
            Assert.True(CloakLauncher._fontWarningChecked); // guard set after first call
        }
        finally
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", prev);
            CloakLauncher._fontWarningChecked = false;
            try { Directory.Delete(tmp, recursive: true); } catch { /* best-effort */ }
        }
    }
}
