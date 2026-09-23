using System.Formats.Tar;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using CloakBrowser;
using Xunit;

namespace CloakBrowser.Tests;

public class ConfigVersionTests
{
    [Theory]
    [InlineData("146.0.7680.177.5", new[] { 146, 0, 7680, 177, 5 })]
    [InlineData("131.0.6778.33", new[] { 131, 0, 6778, 33 })]
    [InlineData("1.2", new[] { 1, 2 })]
    public void VersionTuple_parses_segments(string v, int[] expected)
        => Assert.Equal(expected, Config.VersionTuple(v));

    [Theory]
    [InlineData("146.0.7680.178", "146.0.7680.177", true)]   // higher patch
    [InlineData("147.0.0.0",      "146.0.7680.177", true)]   // higher major
    [InlineData("146.0.7680.177", "146.0.7680.177", false)]  // equal
    [InlineData("146.0.7680.176", "146.0.7680.177", false)]  // lower
    [InlineData("146.0.7680",     "146.0.7680.177", false)]  // shorter == older on the tail
    [InlineData("146.0.7680.177.5", "146.0.7680.177", true)] // longer == newer
    public void VersionNewer_compares_correctly(string a, string b, bool expected)
        => Assert.Equal(expected, Config.VersionNewer(a, b));

    [Fact]
    public void PlatformTag_is_known_value()
        => Assert.Contains(Config.GetPlatformTag(), Config.AvailablePlatforms);

    [Fact]
    public void ArchiveName_uses_tag_and_ext()
    {
        var name = Config.GetArchiveName("linux-x64");
        Assert.StartsWith("cloakbrowser-linux-x64", name);
        Assert.EndsWith(Config.GetArchiveExt(), name);
    }

    [Fact]
    public void DownloadUrl_contains_base_and_archive()
    {
        var url = Config.GetDownloadUrl();
        Assert.StartsWith(Config.DownloadBaseUrl, url);
        Assert.Contains("cloakbrowser-", url);
    }
}

public class ChecksumParseTests
{
    // Real 64-char hex digests (the parser now requires exactly 64 hex chars,
    // matching the Python/JS parser, so short placeholders are rejected).
    private const string H1 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
    private const string H2 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

    [Fact]
    public void ParseChecksums_reads_sha256sums_format()
    {
        // Standard format: "<64-hex hash>  <filename>" (two spaces).
        var text =
            $"{H1}  cloakbrowser-linux-x64.tar.gz\n" +
            $"{H2}  cloakbrowser-win-x64.zip\n";
        var map = Download.ParseChecksums(text);
        Assert.Equal(H1, map["cloakbrowser-linux-x64.tar.gz"]);
        Assert.Equal(H2, map["cloakbrowser-win-x64.zip"]);
    }

    [Fact]
    public void ParseChecksums_uppercase_hash_is_lowercased()
    {
        var text = $"{H1.ToUpperInvariant()}  file.zip\n";
        var map = Download.ParseChecksums(text);
        Assert.Equal(H1, map["file.zip"]);
    }

    [Fact]
    public void ParseChecksums_ignores_blank_malformed_and_non_64hex_lines()
    {
        // Blank lines, junk, short hashes ("abc") and the version= line are all dropped;
        // only a genuine 64-hex digest line survives.
        var text = $"\n   \nnotavalidline\nabc  short.zip\nversion=146.0.7680.177.5\n{H1}  file.zip\n";
        var map = Download.ParseChecksums(text);
        Assert.Single(map);
        Assert.Equal(H1, map["file.zip"]);
        Assert.False(map.ContainsKey("short.zip"));
    }
}

/// <summary>
/// Tests for <see cref="Download.WrapperVersionNewer(string, string)"/>, the dotted
/// SemVer-ish comparison used by the NuGet wrapper-update check (faithful analog of
/// Python's <c>_check_wrapper_update</c> version compare).
/// </summary>
public class WrapperVersionNewerTests
{
    [Theory]
    [InlineData("0.4.0", "0.3.32", true)]    // higher minor beats higher patch on older minor
    [InlineData("0.4.1", "0.4.0", true)]     // higher patch
    [InlineData("1.0.0", "0.9.9", true)]     // higher major
    [InlineData("0.4.0", "0.4.0", false)]    // equal
    [InlineData("0.3.32", "0.4.0", false)]   // lower minor
    [InlineData("0.4.0", "0.4.1", false)]    // lower patch
    [InlineData("0.4", "0.4.0", false)]      // shorter == equal on the zero-padded tail
    [InlineData("0.4.0.1", "0.4.0", true)]   // longer == newer when tail is non-zero
    public void WrapperVersionNewer_compares_correctly(string a, string b, bool expected)
        => Assert.Equal(expected, Download.WrapperVersionNewer(a, b));

    [Fact]
    public void WrapperVersionNewer_tolerates_non_numeric_segments()
    {
        // Non-numeric segments parse to 0 rather than throwing.
        Assert.False(Download.WrapperVersionNewer("0.x.0", "0.4.0"));
        Assert.True(Download.WrapperVersionNewer("0.4.0", "0.x.0"));
    }
}

/// <summary>
/// Concurrent first-run callers of <see cref="Download.EnsureBinaryAsync"/> against one
/// empty cache, with the archive served by a local HttpListener acting as a custom
/// mirror. In env-serial because it sets CLOAKBROWSER_CACHE_DIR and
/// CLOAKBROWSER_DOWNLOAD_URL.
/// </summary>
[Collection("env-serial")]
public class ConcurrentFirstRunTests
{
    private const int Callers = 4;
    private const int FillerFiles = 300;
    private static readonly byte[] BinaryBytes = Encoding.ASCII.GetBytes("#!/bin/sh\necho fake-chrome\n");

    private static readonly string[] IsolatedEnvNames =
    {
        "CLOAKBROWSER_CACHE_DIR", "CLOAKBROWSER_DOWNLOAD_URL", "CLOAKBROWSER_SKIP_CHECKSUM",
        "CLOAKBROWSER_LICENSE_KEY", "CLOAKBROWSER_BINARY_PATH", "CLOAKBROWSER_VERSION",
    };

    /// <summary>
    /// An archive with this platform's binary layout plus enough filler files that an
    /// extraction takes a measurable time.
    /// </summary>
    private static byte[] CreatePlatformArchive()
    {
        var binaryRelPath = Path.GetRelativePath(Config.GetBinaryDir(), Config.GetBinaryPath());
        using var archive = new MemoryStream();
        using (var gzip = new GZipStream(archive, CompressionLevel.Fastest, leaveOpen: true))
        using (var tar = new TarWriter(gzip))
        {
            AddTarFile(tar, binaryRelPath, BinaryBytes);
            for (var i = 0; i < FillerFiles; i++)
            {
                var filler = new byte[16 * 1024];
                Array.Fill(filler, (byte)i);
                AddTarFile(tar, $"lib/part-{i}.bin", filler);
            }
        }
        return archive.ToArray();
    }

    private static void AddTarFile(TarWriter tar, string name, byte[] content) =>
        tar.WriteEntry(new PaxTarEntry(TarEntryType.RegularFile, name)
        {
            DataStream = new MemoryStream(content),
            Mode = UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute
                | UnixFileMode.GroupRead | UnixFileMode.GroupExecute
                | UnixFileMode.OtherRead | UnixFileMode.OtherExecute,
        });

    /// <summary>Reads the install the way a launch would. Returns what is wrong with it, or "complete".</summary>
    private static string InspectInstall()
    {
        try
        {
            var binaryPath = Config.GetBinaryPath();
            if (!File.ReadAllBytes(binaryPath).AsSpan().SequenceEqual(BinaryBytes)) return "binary content differs";
            if (!Config.IsExecutableFile(binaryPath)) return "binary not executable";
            var fillerCount = Directory.GetFiles(Path.Combine(Config.GetBinaryDir(), "lib")).Length;
            return fillerCount == FillerFiles ? "complete" : $"lib has {fillerCount} files";
        }
        catch (IOException err)
        {
            return err.GetType().Name;
        }
    }

    private static int FindFreeTcpPort()
    {
        var probe = new TcpListener(IPAddress.Loopback, 0);
        probe.Start();
        var port = ((IPEndPoint)probe.LocalEndpoint).Port;
        probe.Stop();
        return port;
    }

    [Fact]
    public async Task Install_stays_complete_while_other_callers_finish()
    {
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows)) return;

        var previousEnv = IsolatedEnvNames.ToDictionary(name => name, Environment.GetEnvironmentVariable);
        var cacheDir = Directory.CreateTempSubdirectory("cloakbrowser-concurrent-").FullName;
        var mirrorPort = FindFreeTcpPort();
        using var mirror = new HttpListener();
        mirror.Prefixes.Add($"http://127.0.0.1:{mirrorPort}/");
        mirror.Start();
        try
        {
            UseLocalMirror(cacheDir, mirrorPort);
            var archiveBytes = CreatePlatformArchive();

            // One caller downloads at once. The others have already seen an empty
            // cache but their downloads are held until the first has returned,
            // which is the state a batch of simultaneous cold launches ends up in.
            var releaseHeldDownloads = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            var requestCount = 0;
            async Task ServeArchiveAsync(HttpListenerContext request)
            {
                if (Interlocked.Increment(ref requestCount) > 1) await releaseHeldDownloads.Task;
                await RespondWithArchiveAsync(request, archiveBytes);
            }
            _ = Task.Run(async () =>
            {
                for (var i = 0; i < Callers; i++)
                    _ = ServeArchiveAsync(await mirror.GetContextAsync());
            });

            var callers = Enumerable.Range(0, Callers).Select(_ => Download.EnsureBinaryAsync()).ToArray();
            Assert.Equal(Config.GetBinaryPath(), await await Task.WhenAny(callers));

            // The first caller would now exec its binary. Keep reading the install
            // while the held callers download and extract.
            releaseHeldDownloads.SetResult();
            var observedStates = new HashSet<string> { InspectInstall() };
            var allCallers = Task.WhenAll(callers);
            while (!allCallers.IsCompleted) observedStates.Add(InspectInstall());
            observedStates.Add(InspectInstall());

            foreach (var caller in callers)
                Assert.Equal(Config.GetBinaryPath(), await caller);
            Assert.Equal(new[] { "complete" }, observedStates);
            Assert.Equal(
                new[] { Path.GetFileName(Config.GetBinaryDir()) },
                Directory.GetFileSystemEntries(cacheDir).Select(Path.GetFileName).Where(name => !name!.StartsWith('.')));
        }
        finally
        {
            mirror.Stop();
            foreach (var (name, value) in previousEnv) Environment.SetEnvironmentVariable(name, value);
            Directory.Delete(cacheDir, recursive: true);
        }
    }

    [Fact]
    public async Task Replaces_partial_install_left_by_interrupted_extraction()
    {
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows)) return;

        var previousEnv = IsolatedEnvNames.ToDictionary(name => name, Environment.GetEnvironmentVariable);
        var cacheDir = Directory.CreateTempSubdirectory("cloakbrowser-concurrent-").FullName;
        var mirrorPort = FindFreeTcpPort();
        using var mirror = new HttpListener();
        mirror.Prefixes.Add($"http://127.0.0.1:{mirrorPort}/");
        mirror.Start();
        try
        {
            UseLocalMirror(cacheDir, mirrorPort);
            var archiveBytes = CreatePlatformArchive();
            _ = Task.Run(async () => await RespondWithArchiveAsync(await mirror.GetContextAsync(), archiveBytes));
            Directory.CreateDirectory(Path.Combine(Config.GetBinaryDir(), "lib"));
            File.WriteAllText(Path.Combine(Config.GetBinaryDir(), "lib", "part-0.bin"), "truncated");

            Assert.Equal(Config.GetBinaryPath(), await Download.EnsureBinaryAsync());
            Assert.Equal("complete", InspectInstall());
        }
        finally
        {
            mirror.Stop();
            foreach (var (name, value) in previousEnv) Environment.SetEnvironmentVariable(name, value);
            Directory.Delete(cacheDir, recursive: true);
        }
    }

    private static void UseLocalMirror(string cacheDir, int mirrorPort)
    {
        foreach (var name in IsolatedEnvNames) Environment.SetEnvironmentVariable(name, null);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", cacheDir);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_DOWNLOAD_URL", $"http://127.0.0.1:{mirrorPort}");
        Environment.SetEnvironmentVariable("CLOAKBROWSER_SKIP_CHECKSUM", "true");
    }

    private static async Task RespondWithArchiveAsync(HttpListenerContext request, byte[] archiveBytes)
    {
        request.Response.ContentLength64 = archiveBytes.Length;
        await request.Response.OutputStream.WriteAsync(archiveBytes);
        request.Response.Close();
    }
}
