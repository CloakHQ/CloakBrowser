using System;
using System.Collections.Concurrent;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using CloakBrowser;
using Xunit;

namespace CloakBrowser.Tests;

/// <summary>
/// Fingerprint seed persistence for persistent profiles (mirrors Python
/// tests/test_profile_seed.py and js/tests/profile-seed.test.ts). Playwright launch
/// isn't mocked in this suite, so these drive <see cref="Config.PersistentSeedArgs"/>
/// and <see cref="CloakLauncher.BuildArgs"/>, the two calls LaunchPersistentContextAsync chains.
/// </summary>
[Collection("env-serial")] // swaps the global CloakLog.Sink
public sealed class ProfileSeedTests : IDisposable
{
    private readonly string _tmp =
        Path.Combine(Path.GetTempPath(), "cb-seed-" + Guid.NewGuid().ToString("N"));

    private string SeedFile => Path.Combine(_tmp, Config.ProfileSeedFile);

    public ProfileSeedTests() => Directory.CreateDirectory(_tmp);

    public void Dispose()
    {
        CloakLog.Sink = null;
        Directory.Delete(_tmp, recursive: true);
    }

    private static List<string> ChromeArgs(string dir, bool stealth, List<string>? args) =>
        CloakLauncher.BuildArgs(stealth, Config.PersistentSeedArgs(dir, stealth, args), headless: true);

    private static List<string> Seeds(List<string> args) =>
        args.Where(a => a.StartsWith("--fingerprint=")).ToList();

    [Fact]
    public void FirstLaunch_WritesSeed_SecondReuses()
    {
        var profile = Path.Combine(_tmp, "missing", "profile"); // created on demand
        var first = Seeds(ChromeArgs(profile, true, null));
        var stored = File.ReadAllText(Path.Combine(profile, Config.ProfileSeedFile));
        Assert.Matches(@"^\d{5}\n$", stored);
        Assert.Equal(new[] { $"--fingerprint={stored.Trim()}" }, first);
        Assert.Equal(first, Seeds(ChromeArgs(profile, true, null)));
    }

    /// <summary>
    /// Call-site check through the real launcher: a fake "chrome" records its argv and
    /// exits, so the launch fails but the args Playwright passed are on disk.
    /// </summary>
    [Fact]
    public async Task LaunchPersistentContextAsync_WritesAndPassesSeed()
    {
        if (OperatingSystem.IsWindows()) return; // the fake binary is a shell script
        var argvFile = Path.Combine(_tmp, "argv.txt");
        var fake = Path.Combine(_tmp, "fake-chrome");
        File.WriteAllText(fake, $"#!/bin/sh\nprintf '%s\\n' \"$@\" > '{argvFile}'\nexit 1\n");
        File.SetUnixFileMode(fake, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        var profile = Path.Combine(_tmp, "profile");

        var saved = new[] { "CLOAKBROWSER_BINARY_PATH", "CLOAKBROWSER_LICENSE_KEY", "CLOAKBROWSER_VERSION" }
            .ToDictionary(k => k, Environment.GetEnvironmentVariable);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_BINARY_PATH", fake);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", null);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_VERSION", null);
        try
        {
            await Assert.ThrowsAnyAsync<Exception>(() => CloakLauncher.LaunchPersistentContextAsync(profile));
        }
        finally
        {
            foreach (var (k, v) in saved) Environment.SetEnvironmentVariable(k, v);
        }

        var stored = File.ReadAllText(Path.Combine(profile, Config.ProfileSeedFile));
        Assert.Equal(new[] { $"--fingerprint={stored.Trim()}" }, Seeds(File.ReadAllLines(argvFile).ToList()));
    }

    [Fact]
    public void Reads_PythonWritten_File()
    {
        File.WriteAllText(SeedFile, "12345\n"); // exact Python output
        Assert.Equal(new[] { "--fingerprint=12345" }, Seeds(ChromeArgs(_tmp, true, null)));
    }

    [Theory]
    [InlineData("--fingerprint=4242")]
    [InlineData("--fingerprint=off")]
    public void ExplicitFingerprint_Wins_FileUntouched(string flag)
    {
        Assert.Equal(new[] { flag }, Seeds(ChromeArgs(_tmp, true, new List<string> { flag })));
        Assert.False(File.Exists(SeedFile));
        File.WriteAllText(SeedFile, "12345\n");
        Assert.Equal(new[] { flag }, Seeds(ChromeArgs(_tmp, true, new List<string> { flag })));
        Assert.Equal("12345\n", File.ReadAllText(SeedFile));
    }

    [Fact]
    public void StealthArgsFalse_WritesNothing()
    {
        Assert.Empty(Seeds(ChromeArgs(_tmp, false, null)));
        Assert.Empty(Directory.GetFileSystemEntries(_tmp));
    }

    [Fact]
    public void EmptyUserDataDir_Ignored()
    {
        var args = new List<string> { "--x" };
        Assert.Same(args, Config.PersistentSeedArgs("", true, args));
    }

    [Fact]
    public void NonPersistent_StaysRandom()
    {
        var seeds = Enumerable.Range(0, 5)
            .Select(_ => Seeds(CloakLauncher.BuildArgs(true, null, headless: true))[0])
            .ToHashSet();
        Assert.True(seeds.Count > 1);
    }

    [Theory]
    [InlineData("")]
    [InlineData("abc\n")]
    [InlineData("5\n")]
    [InlineData("123456\n")]
    [InlineData("-12345\n")]
    public void CorruptFile_Logs_And_Regenerates(string content)
    {
        File.WriteAllText(SeedFile, content);
        var warnings = new ConcurrentQueue<string>();
        CloakLog.Sink = (level, msg) => { if (level == CloakLogLevel.Warning) warnings.Enqueue(msg); };

        var args = Config.PersistentSeedArgs(_tmp, true, null)!;

        Assert.Contains(warnings, w => w.Contains(SeedFile));
        var stored = File.ReadAllText(SeedFile);
        Assert.Matches(@"^\d{5}\n$", stored);
        Assert.Equal(new[] { $"--fingerprint={stored.Trim()}" }, args);
    }

    [Fact]
    public async Task ConcurrentFirstLaunches_Agree()
    {
        using var start = new ManualResetEventSlim();
        var tasks = Enumerable.Range(0, 16).Select(_ => Task.Run(() =>
        {
            start.Wait();
            return Config.PersistentSeedArgs(_tmp, true, null)![0];
        })).ToArray();
        start.Set();
        var seeds = await Task.WhenAll(tasks);

        Assert.Single(seeds.Distinct());
        // macOS adds ._ AppleDouble files on FAT volumes, where these tests also run.
        Assert.Equal(new[] { SeedFile },
            Directory.GetFileSystemEntries(_tmp).Where(p => !Path.GetFileName(p).StartsWith("._")));
    }
}
