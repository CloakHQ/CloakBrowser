using System.IO;
using System.IO.Compression;
using System.Runtime.InteropServices;
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
/// Tests for <see cref="DownloadHttpError"/>, the typed HTTP-status carrier the
/// v0.4.2 macOS Pro fallback relies on to distinguish a 404 (no Pro binary built
/// for this platform yet) from transient download failures.
/// </summary>
public class DownloadHttpErrorTests
{
    [Fact]
    public void Carries_status_code_and_includes_it_in_message()
    {
        var ex = new DownloadHttpError(System.Net.HttpStatusCode.NotFound, "Not Found");
        Assert.Equal(System.Net.HttpStatusCode.NotFound, ex.Status);
        Assert.Contains("404", ex.Message);
        Assert.Contains("Not Found", ex.Message);
    }

    [Fact]
    public void Distinguishes_404_from_transient_5xx()
    {
        var notFound = new DownloadHttpError(System.Net.HttpStatusCode.NotFound, "Not Found");
        var transient = new DownloadHttpError(System.Net.HttpStatusCode.ServiceUnavailable, "Unavailable");
        // The macOS Pro fallback only triggers on 404; a 5xx stays a hard failure.
        Assert.Equal(System.Net.HttpStatusCode.NotFound, notFound.Status);
        Assert.NotEqual(System.Net.HttpStatusCode.NotFound, transient.Status);
    }
}

/// <summary>
/// Tests for the archive-extraction path-traversal (zip-slip) guard
/// <see cref="Download.ResolveSafeEntryPath(string, string)"/>, shared by
/// <c>ExtractTar</c> and <c>ExtractZip</c>.
/// </summary>
public class PathTraversalTests
{
    private static string DestDir() =>
        Path.Combine(Path.GetTempPath(), "cloak-extract-test");

    [Fact]
    public void Normal_entry_resolves_inside_destination()
    {
        var dest = DestDir();
        var resolved = Download.ResolveSafeEntryPath(dest, "sub/file.txt");

        var destFull = Path.GetFullPath(dest);
        var expected = Path.GetFullPath(Path.Combine(destFull, "sub/file.txt"));

        Assert.Equal(expected, resolved);
        // The resolved path stays under the destination directory.
        Assert.StartsWith(destFull + Path.DirectorySeparatorChar, resolved, System.StringComparison.Ordinal);
    }

    [Fact]
    public void Parent_relative_entry_throws()
    {
        var dest = DestDir();
        var ex = Assert.Throws<System.InvalidOperationException>(
            () => Download.ResolveSafeEntryPath(dest, "../evil.txt"));
        // The message names the offending entry.
        Assert.Contains("../evil.txt", ex.Message);
    }

    [Fact]
    public void Absolute_entry_path_throws()
    {
        var dest = DestDir();
        // An absolute entry path escapes the destination via Path.Combine semantics.
        var absolute = RuntimeInformation.IsOSPlatform(OSPlatform.Windows)
            ? @"C:\Windows\evil.txt"
            : "/etc/evil.txt";

        var ex = Assert.Throws<System.InvalidOperationException>(
            () => Download.ResolveSafeEntryPath(dest, absolute));
        Assert.Contains(absolute, ex.Message);
    }

    [Fact]
    public void Windows_backslash_traversal_throws()
    {
        // "..\..\evil" is only a traversal where backslash is a path separator (Windows).
        // On other platforms backslash is an ordinary filename character, so skip.
        if (!RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
            return;

        var dest = DestDir();
        const string entry = @"..\..\evil";
        var ex = Assert.Throws<System.InvalidOperationException>(
            () => Download.ResolveSafeEntryPath(dest, entry));
        Assert.Contains(entry, ex.Message);
    }
}
