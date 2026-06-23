using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using CloakBrowser;
using Xunit;

namespace CloakBrowser.Tests;

/// <summary>
/// Port-parity tests for <see cref="Widevine"/> (mirrors Python tests/test_widevine.py
/// and js/tests/widevine.test.ts). Seeding is Linux-only, so the write-path
/// assertions are gated on Linux; the platform-independent behaviour (no-op
/// gates, CDM resolution, kill switch) is exercised everywhere.
///
/// Mutates CLOAKBROWSER_WIDEVINE* env vars, so it joins the env-serial
/// collection to avoid racing other env-mutating suites.
/// </summary>
[Collection("env-serial")]
public sealed class WidevineTests : IDisposable
{
    private const string HintFilename = "latest-component-updated-widevine-cdm";

    private readonly string? _prevWidevine;
    private readonly string? _prevCdm;
    private readonly string _tmp;

    public WidevineTests()
    {
        _prevWidevine = Environment.GetEnvironmentVariable("CLOAKBROWSER_WIDEVINE");
        _prevCdm = Environment.GetEnvironmentVariable("CLOAKBROWSER_WIDEVINE_CDM");
        Environment.SetEnvironmentVariable("CLOAKBROWSER_WIDEVINE", null);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_WIDEVINE_CDM", null);
        _tmp = Path.Combine(Path.GetTempPath(), "cb-widevine-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_tmp);
    }

    public void Dispose()
    {
        Environment.SetEnvironmentVariable("CLOAKBROWSER_WIDEVINE", _prevWidevine);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_WIDEVINE_CDM", _prevCdm);
        try { if (Directory.Exists(_tmp)) Directory.Delete(_tmp, recursive: true); } catch (IOException) { }
    }

    private static bool OnLinux => RuntimeInformation.IsOSPlatform(OSPlatform.Linux);

    /// <summary>Create a fake chrome binary with a sideloaded WidevineCdm/manifest.json next to it.</summary>
    private string MakeBinaryWithCdm()
    {
        var binDir = Path.Combine(_tmp, "bin");
        Directory.CreateDirectory(binDir);
        var binaryPath = Path.Combine(binDir, "chrome");
        File.WriteAllText(binaryPath, "#!/bin/sh\n");
        var cdmDir = Path.Combine(binDir, "WidevineCdm");
        Directory.CreateDirectory(cdmDir);
        File.WriteAllText(Path.Combine(cdmDir, "manifest.json"), "{\"version\":\"1.0\"}");
        return binaryPath;
    }

    // ---- ResolveWidevineCdmDir ------------------------------------------------

    [Fact]
    public void Resolve_FindsCdmNextToBinary()
    {
        var binaryPath = MakeBinaryWithCdm();
        var resolved = Widevine.ResolveWidevineCdmDir(binaryPath);
        Assert.NotNull(resolved);
        Assert.Equal(Path.GetFullPath(Path.Combine(Path.GetDirectoryName(binaryPath)!, "WidevineCdm")),
            resolved);
    }

    [Fact]
    public void Resolve_NoManifest_ReturnsNull()
    {
        var binDir = Path.Combine(_tmp, "nomanifest");
        Directory.CreateDirectory(binDir);
        var binaryPath = Path.Combine(binDir, "chrome");
        File.WriteAllText(binaryPath, "x");
        Directory.CreateDirectory(Path.Combine(binDir, "WidevineCdm")); // dir but no manifest.json
        Assert.Null(Widevine.ResolveWidevineCdmDir(binaryPath));
    }

    [Fact]
    public void Resolve_EnvVar_OverridesAutoDetect()
    {
        // Auto-detect would find the binary-adjacent CDM, but the env var wins exclusively.
        var binaryPath = MakeBinaryWithCdm();
        var customDir = Path.Combine(_tmp, "custom");
        Directory.CreateDirectory(customDir);
        File.WriteAllText(Path.Combine(customDir, "manifest.json"), "{}");
        Environment.SetEnvironmentVariable("CLOAKBROWSER_WIDEVINE_CDM", customDir);

        var resolved = Widevine.ResolveWidevineCdmDir(binaryPath);
        Assert.Equal(Path.GetFullPath(customDir), resolved);
    }

    [Fact]
    public void Resolve_EnvVar_InvalidPath_SkipsSeeding()
    {
        // A present-but-bogus env var is used exclusively => null (does NOT fall back).
        var binaryPath = MakeBinaryWithCdm();
        Environment.SetEnvironmentVariable("CLOAKBROWSER_WIDEVINE_CDM",
            Path.Combine(_tmp, "does-not-exist"));
        Assert.Null(Widevine.ResolveWidevineCdmDir(binaryPath));
    }

    [Fact]
    public void Resolve_EnvVar_Whitespace_SkipsSeeding()
    {
        // A present-but-blank value must be treated as an unusable path and skip
        // seeding (rather than probing the CWD via Path.Combine). Note: .NET's
        // SetEnvironmentVariable("") *unsets* the variable, so a truly-empty value
        // is unreachable through the managed API and only happens via the shell
        // (export X=); whitespace is the testable proxy for that "set-but-blank"
        // case and exercises the same guard in ResolveWidevineCdmDir.
        var binaryPath = MakeBinaryWithCdm();
        Environment.SetEnvironmentVariable("CLOAKBROWSER_WIDEVINE_CDM", "   ");
        Assert.Null(Widevine.ResolveWidevineCdmDir(binaryPath));
    }

    // ---- SeedWidevineHint (write path, Linux only) ---------------------------

    [Fact]
    public void Seed_WritesHintFile_WithCompactJson()
    {
        if (!OnLinux) return;
        var binaryPath = MakeBinaryWithCdm();
        var profile = Path.Combine(_tmp, "profile");
        Directory.CreateDirectory(profile);

        Widevine.SeedWidevineHint(profile, binaryPath);

        var hintFile = Path.Combine(profile, "WidevineCdm", HintFilename);
        Assert.True(File.Exists(hintFile));

        var cdmDir = Path.GetFullPath(Path.Combine(Path.GetDirectoryName(binaryPath)!, "WidevineCdm"));
        // Byte-match the JS wrapper's JSON.stringify({ Path }) output: compact, no BOM.
        var expected = "{\"Path\":\"" + cdmDir + "\"}";
        var actual = File.ReadAllText(hintFile);
        Assert.Equal(expected, actual);
        // No UTF-8 BOM (the JS/Python wrappers write raw UTF-8).
        var bytes = File.ReadAllBytes(hintFile);
        Assert.False(bytes.Length >= 3 && bytes[0] == 0xEF && bytes[1] == 0xBB && bytes[2] == 0xBF);
    }

    [Fact]
    public void Seed_Idempotent_DoesNotRewriteIdenticalHint()
    {
        if (!OnLinux) return;
        var binaryPath = MakeBinaryWithCdm();
        var profile = Path.Combine(_tmp, "profile");
        Directory.CreateDirectory(profile);

        Widevine.SeedWidevineHint(profile, binaryPath);
        var hintFile = Path.Combine(profile, "WidevineCdm", HintFilename);
        var firstWrite = File.GetLastWriteTimeUtc(hintFile);

        System.Threading.Thread.Sleep(20);
        Widevine.SeedWidevineHint(profile, binaryPath); // second seed, identical content
        var secondWrite = File.GetLastWriteTimeUtc(hintFile);

        Assert.Equal(firstWrite, secondWrite); // untouched
    }

    [Fact]
    public void Seed_NoCdm_NoHintWritten()
    {
        if (!OnLinux) return;
        var binDir = Path.Combine(_tmp, "bare");
        Directory.CreateDirectory(binDir);
        var binaryPath = Path.Combine(binDir, "chrome");
        File.WriteAllText(binaryPath, "x");
        var profile = Path.Combine(_tmp, "profile2");
        Directory.CreateDirectory(profile);

        Widevine.SeedWidevineHint(profile, binaryPath);

        Assert.False(File.Exists(Path.Combine(profile, "WidevineCdm", HintFilename)));
    }

    [Fact]
    public void Seed_KillSwitch_NoHintWritten()
    {
        if (!OnLinux) return;
        Environment.SetEnvironmentVariable("CLOAKBROWSER_WIDEVINE", "0");
        var binaryPath = MakeBinaryWithCdm();
        var profile = Path.Combine(_tmp, "profile3");
        Directory.CreateDirectory(profile);

        Widevine.SeedWidevineHint(profile, binaryPath);

        Assert.False(File.Exists(Path.Combine(profile, "WidevineCdm", HintFilename)));
    }

    [Theory]
    [InlineData("0")]
    [InlineData("false")]
    [InlineData("off")]
    [InlineData("no")]
    [InlineData("FALSE")]
    [InlineData(" Off ")]
    public void Seed_KillSwitch_AcceptsFalseyVariants(string value)
    {
        if (!OnLinux) return;
        Environment.SetEnvironmentVariable("CLOAKBROWSER_WIDEVINE", value);
        var binaryPath = MakeBinaryWithCdm();
        var profile = Path.Combine(_tmp, "profile-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(profile);

        Widevine.SeedWidevineHint(profile, binaryPath);

        Assert.False(File.Exists(Path.Combine(profile, "WidevineCdm", HintFilename)));
    }

    [Fact]
    public void Seed_EmptyUserDataDir_NoOp()
    {
        // No exception, no write — ephemeral profile path.
        var binaryPath = MakeBinaryWithCdm();
        Widevine.SeedWidevineHint("", binaryPath);
        Widevine.SeedWidevineHint(null, binaryPath);
        // Nothing to assert beyond "did not throw"; the binary-adjacent CDM must
        // not have been touched.
        Assert.True(File.Exists(binaryPath));
    }
}
