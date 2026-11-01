using System.Formats.Tar;
using System.IO;
using System.IO.Compression;
using System.Net;
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
        => Assert.Contains(Config.GetPlatformTag(),
            new[] { "linux-x64", "linux-arm64", "darwin-arm64", "darwin-x64", "windows-x64" });

    [Fact]
    public void ArchiveName_uses_tag_and_ext()
    {
        var name = Config.GetArchiveName("linux-x64");
        Assert.StartsWith("cloakbrowser-linux-x64", name);
        Assert.EndsWith(Config.GetArchiveExt(), name);
    }

    [Fact]
    public void ProDownloadUrl_pins_version_on_base()
        => Assert.Equal($"{Config.DownloadBaseUrl}/api/download/155.0.1.1", Config.GetProDownloadUrl("155.0.1.1"));
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
/// empty cache, on the keyed download path: the license and latest version are mocked
/// and the archive is served by a fake <see cref="Download.Http"/> handler, verified
/// against a test-signed manifest. In env-serial because it sets CLOAKBROWSER_CACHE_DIR.
/// </summary>
[Collection("env-serial")]
public class ConcurrentFirstRunTests
{
    private const int Callers = 4;
    private const int FillerFiles = 300;
    private const string Version = "155.0.8059.39.2";
    private static readonly byte[] BinaryBytes = Encoding.ASCII.GetBytes("#!/bin/sh\necho fake-chrome\n");

    private static readonly string[] IsolatedEnvNames =
    {
        "CLOAKBROWSER_CACHE_DIR", "CLOAKBROWSER_LICENSE_KEY", "CLOAKBROWSER_BINARY_PATH",
        "CLOAKBROWSER_VERSION", "CLOAKBROWSER_RELEASE_CHANNEL", "CLOAKBROWSER_AUTO_UPDATE",
    };

    private sealed class FakeHandler(Func<HttpRequestMessage, Task<HttpResponseMessage>> serve) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
            => serve(request);
    }

    private static Task<HttpResponseMessage> Archive(byte[] bytes) =>
        Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(bytes) });

    /// <summary>
    /// Run <paramref name="body"/> with an isolated cache, a valid license, a fixed latest
    /// version and archive downloads answered by <paramref name="serveArchive"/>.
    /// </summary>
    private static async Task WithKeyedDownloads(
        byte[] archiveBytes, Func<HttpRequestMessage, Task<HttpResponseMessage>> serveArchive, Func<string, Task> body)
    {
        var previousEnv = IsolatedEnvNames.ToDictionary(name => name, Environment.GetEnvironmentVariable);
        var cacheDir = Directory.CreateTempSubdirectory("cloakbrowser-concurrent-").FullName;
        var previousHttp = Download.Http;
        var gen = new Org.BouncyCastle.Crypto.Generators.Ed25519KeyPairGenerator();
        gen.Init(new Org.BouncyCastle.Crypto.Parameters.Ed25519KeyGenerationParameters(
            new Org.BouncyCastle.Security.SecureRandom()));
        var pair = gen.GenerateKeyPair();
        var manifest = Encoding.UTF8.GetBytes(
            $"version={Version}\n{Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(archiveBytes)).ToLowerInvariant()}  {Config.GetArchiveName()}\n");
        var signer = new Org.BouncyCastle.Crypto.Signers.Ed25519Signer();
        signer.Init(true, pair.Private);
        signer.BlockUpdate(manifest, 0, manifest.Length);
        var sig = Encoding.ASCII.GetBytes(Convert.ToBase64String(signer.GenerateSignature()));
        try
        {
            foreach (var name in IsolatedEnvNames) Environment.SetEnvironmentVariable(name, null);
            Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", cacheDir);
            License.ValidateLicenseOverride = _ => new LicenseInfo(true, "business", null);
            License.ProLatestVersionOverride = () => Version;
            Download.SigningPubkeysOverride = new[]
            {
                Convert.ToBase64String(((Org.BouncyCastle.Crypto.Parameters.Ed25519PublicKeyParameters)pair.Public).GetEncoded()),
            };
            Download.ProSignedManifestOverride = _ => (manifest, sig);
            // Only the archive route is served; anything else (the NuGet update check) is a 404.
            Download.Http = new HttpClient(new FakeHandler(request =>
                request.RequestUri!.AbsolutePath.StartsWith("/api/download/", StringComparison.Ordinal)
                    ? serveArchive(request)
                    : Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound))));
            await body(cacheDir);
        }
        finally
        {
            Download.Http = previousHttp;
            License.ValidateLicenseOverride = null;
            License.ProLatestVersionOverride = null;
            Download.SigningPubkeysOverride = null;
            Download.ProSignedManifestOverride = null;
            foreach (var (name, value) in previousEnv) Environment.SetEnvironmentVariable(name, value);
            Directory.Delete(cacheDir, recursive: true);
        }
    }

    /// <summary>
    /// An archive with this platform's binary layout plus enough filler files that an
    /// extraction takes a measurable time.
    /// </summary>
    private static byte[] CreatePlatformArchive()
    {
        var binaryRelPath = Path.GetRelativePath(Config.GetBinaryDir(Version), Config.GetBinaryPath(Version));
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
            var binaryPath = Config.GetBinaryPath(Version);
            if (!File.ReadAllBytes(binaryPath).AsSpan().SequenceEqual(BinaryBytes)) return "binary content differs";
            if (!Config.IsExecutableFile(binaryPath)) return "binary not executable";
            var fillerCount = Directory.GetFiles(Path.Combine(Config.GetBinaryDir(Version), "lib")).Length;
            return fillerCount == FillerFiles ? "complete" : $"lib has {fillerCount} files";
        }
        catch (IOException err)
        {
            return err.GetType().Name;
        }
    }

    /// <summary>What a keyed first install leaves in the cache (besides dot files).</summary>
    private static string[] ExpectedCacheEntries() =>
        new[] { Path.GetFileName(Config.GetBinaryDir(Version)), $"latest_pro_version_{Config.GetPlatformTag()}" };

    private static IEnumerable<string?> CacheEntries(string cacheDir) =>
        Directory.GetFileSystemEntries(cacheDir).Select(Path.GetFileName)
            .Where(name => !name!.StartsWith('.')).OrderBy(n => n, StringComparer.Ordinal);

    [Fact]
    public async Task Install_stays_complete_while_other_callers_finish()
    {
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows)) return;
        var archiveBytes = CreatePlatformArchive();

        // One caller downloads at once. The others have already seen an empty
        // cache but their downloads are held until the first has returned,
        // which is the state a batch of simultaneous cold launches ends up in.
        var releaseHeldDownloads = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var requestCount = 0;
        async Task<HttpResponseMessage> ServeArchiveAsync(HttpRequestMessage _)
        {
            if (Interlocked.Increment(ref requestCount) > 1) await releaseHeldDownloads.Task;
            return await Archive(archiveBytes);
        }

        await WithKeyedDownloads(archiveBytes, ServeArchiveAsync, async cacheDir =>
        {
            var callers = Enumerable.Range(0, Callers).Select(_ => Download.EnsureBinaryAsync("cb_test")).ToArray();
            Assert.Equal(Config.GetBinaryPath(Version), await await Task.WhenAny(callers));

            // The first caller would now exec its binary. Keep reading the install
            // while the held callers download and extract.
            releaseHeldDownloads.SetResult();
            var observedStates = new HashSet<string> { InspectInstall() };
            var allCallers = Task.WhenAll(callers);
            while (!allCallers.IsCompleted) observedStates.Add(InspectInstall());
            observedStates.Add(InspectInstall());

            foreach (var caller in callers)
                Assert.Equal(Config.GetBinaryPath(Version), await caller);
            Assert.Equal(new[] { "complete" }, observedStates);
            Assert.Equal(ExpectedCacheEntries().OrderBy(n => n, StringComparer.Ordinal), CacheEntries(cacheDir));
        });
    }

    [Fact]
    public async Task Replaces_partial_install_left_by_interrupted_extraction()
    {
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows)) return;
        var archiveBytes = CreatePlatformArchive();

        await WithKeyedDownloads(archiveBytes, _ => Archive(archiveBytes), async _ =>
        {
            Directory.CreateDirectory(Path.Combine(Config.GetBinaryDir(Version), "lib"));
            File.WriteAllText(Path.Combine(Config.GetBinaryDir(Version), "lib", "part-0.bin"), "truncated");

            Assert.Equal(Config.GetBinaryPath(Version), await Download.EnsureBinaryAsync("cb_test"));
            Assert.Equal("complete", InspectInstall());
        });
    }

    [Fact]
    public async Task Concurrent_callers_replace_partial_install()
    {
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows)) return;
        var archiveBytes = CreatePlatformArchive();

        // Answer only once every caller is downloading, so all of them find the
        // partial install in the way when they move their extraction into place.
        var allDownloading = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var requestCount = 0;
        async Task<HttpResponseMessage> ServeArchiveAsync(HttpRequestMessage _)
        {
            if (Interlocked.Increment(ref requestCount) == Callers) allDownloading.SetResult();
            await allDownloading.Task;
            return await Archive(archiveBytes);
        }

        await WithKeyedDownloads(archiveBytes, ServeArchiveAsync, async cacheDir =>
        {
            Directory.CreateDirectory(Path.Combine(Config.GetBinaryDir(Version), "lib"));
            for (var i = 0; i < FillerFiles; i++)
                File.WriteAllText(Path.Combine(Config.GetBinaryDir(Version), "lib", $"part-{i}.bin"), "truncated");

            var callers = Enumerable.Range(0, Callers).Select(_ => Download.EnsureBinaryAsync("cb_test")).ToArray();
            var outcomes = new List<string>();
            foreach (var caller in callers)
            {
                try { outcomes.Add(await caller); }
                catch (Exception err) { outcomes.Add($"{err.GetType().Name}: {err.Message}"); }
            }

            Assert.Equal(Enumerable.Repeat(Config.GetBinaryPath(Version), Callers), outcomes);
            Assert.Equal("complete", InspectInstall());
            Assert.Equal(ExpectedCacheEntries().OrderBy(n => n, StringComparer.Ordinal), CacheEntries(cacheDir));
        });
    }
}
