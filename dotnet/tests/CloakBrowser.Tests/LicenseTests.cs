using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using CloakBrowser;
using Xunit;

namespace CloakBrowser.Tests;

/// <summary>
/// CloakBrowser Pro license validation, caching, key resolution, Pro-aware config,
/// and the binary_info tier - port of Python <c>tests/test_license.py</c> and JS
/// <c>js/tests/license.test.ts</c>.
///
/// Tests are serialized (a shared collection) because they manipulate process env
/// vars and a temp cache dir.
/// </summary>
[Collection("env-serial")]
public class LicenseTests : IDisposable
{
    private readonly string _tmp;
    private readonly string? _prevCacheDir;
    private readonly string? _prevLicenseEnv;
    private readonly string? _prevDownloadUrl;

    public LicenseTests()
    {
        _tmp = Path.Combine(Path.GetTempPath(), $"cloak-lic-test-{Guid.NewGuid():N}");
        Directory.CreateDirectory(_tmp);
        _prevCacheDir = Environment.GetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR");
        _prevLicenseEnv = Environment.GetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY");
        _prevDownloadUrl = Environment.GetEnvironmentVariable("CLOAKBROWSER_DOWNLOAD_URL");
        Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", _tmp);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", null);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_DOWNLOAD_URL", null);
    }

    public void Dispose()
    {
        Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", _prevCacheDir);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", _prevLicenseEnv);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_DOWNLOAD_URL", _prevDownloadUrl);
        License.ValidateLicenseOverride = null;
        License.ProLatestVersionOverride = null;
        try { if (Directory.Exists(_tmp)) Directory.Delete(_tmp, recursive: true); } catch (IOException) { }
    }

    private static string Sha256Hex(string s) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(s))).ToLowerInvariant();

    private void WriteCache(string key, bool valid, string plan, string? expires, double validatedAt)
    {
        var payload = JsonSerializer.Serialize(new Dictionary<string, object?>
        {
            ["key_sha256"] = Sha256Hex(key),
            ["valid"] = valid,
            ["plan"] = plan,
            ["expires"] = expires,
            ["validated_at"] = validatedAt,
        });
        File.WriteAllText(Path.Combine(_tmp, ".license_cache"), payload);
    }

    private static double Now() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;

    // =======================================================================
    // ResolveLicenseKey - param > env > file > null
    // =======================================================================

    [Fact]
    public void ExplicitParam_wins()
    {
        Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", "env-key");
        Assert.Equal("param-key", License.ResolveLicenseKey("param-key"));
    }

    [Fact]
    public void EnvVar_fallback()
    {
        Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", "env-key");
        Assert.Equal("env-key", License.ResolveLicenseKey(null));
    }

    [Fact]
    public void Returns_null_when_absent()
    {
        Assert.Null(License.ResolveLicenseKey(null));
    }

    [Fact]
    public void EmptyString_param_uses_env()
    {
        Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", "env-key");
        Assert.Equal("env-key", License.ResolveLicenseKey("   "));
    }

    [Fact]
    public void File_fallback()
    {
        File.WriteAllText(Path.Combine(_tmp, "license.key"), "file-key\n");
        Assert.Equal("file-key", License.ResolveLicenseKey(null));
    }

    [Fact]
    public void Env_takes_precedence_over_file()
    {
        File.WriteAllText(Path.Combine(_tmp, "license.key"), "file-key");
        Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", "env-key");
        Assert.Equal("env-key", License.ResolveLicenseKey(null));
    }

    // =======================================================================
    // ValidateLicense - cache + server + stale fallback
    // =======================================================================

    [Fact]
    public void FreshCache_skips_server()
    {
        WriteCache("k", valid: true, plan: "team", expires: null, validatedAt: Now());
        // No override set, but a fresh cache must short-circuit before any HTTP.
        var info = License.ValidateLicense("k");
        Assert.NotNull(info);
        Assert.True(info!.Valid);
        Assert.Equal("team", info.Plan);
    }

    [Fact]
    public void StaleCache_is_ignored_by_fresh_read()
    {
        // Older than 24h -> not returned from the fresh read; server override supplies a new one.
        WriteCache("k", valid: true, plan: "solo", expires: null, validatedAt: Now() - 90000);
        License.ValidateLicenseOverride = key => new LicenseInfo(true, "team", null);
        var info = License.ValidateLicense("k");
        Assert.Equal("team", info!.Plan);
    }

    [Fact]
    public void Server_rejection_returns_invalid()
    {
        License.ValidateLicenseOverride = key => new LicenseInfo(false, "solo", null);
        var info = License.ValidateLicense("bad");
        Assert.NotNull(info);
        Assert.False(info!.Valid);
    }

    [Fact]
    public void Cache_stores_hash_not_raw_key()
    {
        // The on-disk cache must store a SHA-256 of the key, never the raw secret.
        WriteCache("super-secret-key", valid: true, plan: "team", expires: null, validatedAt: Now());
        var contents = File.ReadAllText(Path.Combine(_tmp, ".license_cache"));
        Assert.DoesNotContain("super-secret-key", contents);
        Assert.Contains(Sha256Hex("super-secret-key"), contents);
        // And a fresh read of that hashed entry round-trips.
        var info = License.ValidateLicense("super-secret-key");
        Assert.True(info!.Valid);
        Assert.Equal("team", info.Plan);
    }

    [Fact]
    public void WrongKey_cache_ignored()
    {
        WriteCache("other-key", valid: true, plan: "team", expires: null, validatedAt: Now());
        License.ValidateLicenseOverride = key => new LicenseInfo(true, "solo", null);
        var info = License.ValidateLicense("my-key");
        // Cache belongs to a different key -> ignored; server override result used.
        Assert.Equal("solo", info!.Plan);
    }

    [Fact]
    public void ExpiredLicense_rejected_from_cache()
    {
        var pastIso = DateTimeOffset.UtcNow.AddDays(-1).ToString("o");
        WriteCache("k", valid: true, plan: "solo", expires: pastIso, validatedAt: Now());
        var info = License.ValidateLicense("k");
        Assert.NotNull(info);
        Assert.False(info!.Valid);
    }

    [Fact]
    public void CorruptedValidatedAt_does_not_crash()
    {
        var payload = JsonSerializer.Serialize(new Dictionary<string, object?>
        {
            ["key_sha256"] = Sha256Hex("k"),
            ["valid"] = true,
            ["plan"] = "solo",
            ["expires"] = null,
            ["validated_at"] = "not-a-number",
        });
        File.WriteAllText(Path.Combine(_tmp, ".license_cache"), payload);
        License.ValidateLicenseOverride = key => new LicenseInfo(true, "team", null);
        // Corrupt cache treated as absent -> server override consulted, no crash.
        var info = License.ValidateLicense("k");
        Assert.Equal("team", info!.Plan);
    }

    // =======================================================================
    // GetProLatestVersion - rate limiting + marker
    // =======================================================================

    [Fact]
    public void ProLatestVersion_rate_limited_reads_marker()
    {
        var marker = Path.Combine(_tmp, ".last_pro_version_check");
        File.WriteAllText(marker, "148.0.7778.215.2");
        // Fresh marker (just written) -> returns cached value without server.
        Assert.Equal("148.0.7778.215.2", License.GetProLatestVersion());
    }

    [Fact]
    public void ProLatestVersion_override_used()
    {
        License.ProLatestVersionOverride = () => "149.0.0.0";
        Assert.Equal("149.0.0.0", License.GetProLatestVersion());
    }

    // =======================================================================
    // Config Pro paths
    // =======================================================================

    [Fact]
    public void BinaryDir_pro_suffix()
    {
        var dir = Config.GetBinaryDir("148.0.7778.215.2", pro: true);
        Assert.EndsWith("chromium-148.0.7778.215.2-pro", dir);
    }

    [Fact]
    public void BinaryDir_default_no_suffix()
    {
        var dir = Config.GetBinaryDir("146.0.7680.177.5", pro: false);
        Assert.EndsWith("chromium-146.0.7680.177.5", dir);
        Assert.DoesNotContain("-pro", Path.GetFileName(dir));
    }

    [Fact]
    public void EffectiveVersion_pro_marker_without_binary_falls_back()
    {
        var marker = Path.Combine(_tmp, $"latest_pro_version_{Config.GetPlatformTag()}");
        File.WriteAllText(marker, "148.0.7778.215.2");
        // Marker present but no Pro binary on disk -> falls back to bundled version.
        Assert.Equal(Config.GetChromiumVersion(), Config.GetEffectiveVersion(pro: true));
    }
}
