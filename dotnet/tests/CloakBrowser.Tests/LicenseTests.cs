using System;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
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
        License.ActiveSessionCountOverride = null;
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
        var marker = Path.Combine(_tmp, $".last_pro_version_check_{Config.GetPlatformTag()}");
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

    [Fact]
    public void ProLatestVersion_sends_platform_header()
    {
        // Exercise the real SendAsync path (no override) via a recording handler.
        var recorder = new RecordingHandler("{\"version\":\"147.0.1234.5\"}");
        var original = License.Http;
        License.Http = new HttpClient(recorder);
        try
        {
            var version = License.GetProLatestVersion();
            Assert.Equal("147.0.1234.5", version);
            Assert.Equal(Config.GetPlatformTag(), recorder.LastPlatform);
        }
        finally
        {
            License.Http.Dispose();
            License.Http = original;
        }
    }

    /// <summary>Captures the X-Platform header off the outgoing request and returns a canned body.</summary>
    private sealed class RecordingHandler : HttpMessageHandler
    {
        private readonly string _body;
        public string? LastPlatform { get; private set; }

        public RecordingHandler(string body) => _body = body;

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            // Read the header value here — `request` is disposed by the caller after the call.
            LastPlatform = request.Headers.TryGetValues("X-Platform", out var values)
                ? values.FirstOrDefault()
                : null;
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(_body),
            });
        }
    }

    // =======================================================================
    // GetActiveSessionCount — live seat count
    // =======================================================================

    /// <summary>Captures the request URI + body and returns a canned response.</summary>
    private sealed class SessionCountHandler : HttpMessageHandler
    {
        private readonly string _body;
        private readonly HttpStatusCode _status;
        public string? LastUri { get; private set; }
        public string? LastMethod { get; private set; }
        public string? LastBody { get; private set; }
        public int Calls { get; private set; }

        public SessionCountHandler(string body, HttpStatusCode status = HttpStatusCode.OK)
        {
            _body = body;
            _status = status;
        }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls++;
            LastUri = request.RequestUri?.ToString();
            LastMethod = request.Method.Method;
            LastBody = request.Content?.ReadAsStringAsync(cancellationToken).GetAwaiter().GetResult();
            return Task.FromResult(new HttpResponseMessage(_status)
            {
                Content = new StringContent(_body),
            });
        }
    }

    private void WithSessionCountHttp(SessionCountHandler handler, Action body)
    {
        var original = License.Http;
        License.Http = new HttpClient(handler);
        try { body(); }
        finally
        {
            License.Http.Dispose();
            License.Http = original;
        }
    }

    [Fact]
    public void ActiveSessionCount_override_used()
    {
        License.ActiveSessionCountOverride = _ => 7;
        Assert.Equal(7, License.GetActiveSessionCount("cb_key"));
    }

    [Fact]
    public void ActiveSessionCount_returns_live_count()
    {
        var handler = new SessionCountHandler("{\"valid\":true,\"active\":3}");
        WithSessionCountHttp(handler, () =>
            Assert.Equal(3, License.GetActiveSessionCount("cb_key")));
    }

    [Fact]
    public void ActiveSessionCount_posts_the_key_in_the_body()
    {
        // POST, not GET: the key is a live credential and a query string would
        // land in the server's access log.
        var handler = new SessionCountHandler("{\"valid\":true,\"active\":0}");
        WithSessionCountHttp(handler, () => License.GetActiveSessionCount("cb_key"));

        Assert.Equal(License.SessionCountUrl, handler.LastUri);
        Assert.Equal("POST", handler.LastMethod);
        Assert.Contains("cb_key", handler.LastBody!);
    }

    [Fact]
    public void ActiveSessionCount_zero_is_not_confused_with_unknown()
    {
        // 0 is a real answer ("nothing running"); null means "couldn't tell".
        // They print differently, so 0 must not collapse to null.
        var handler = new SessionCountHandler("{\"valid\":true,\"active\":0}");
        WithSessionCountHttp(handler, () =>
            Assert.Equal(0, License.GetActiveSessionCount("cb_key")));
    }

    [Fact]
    public void ActiveSessionCount_null_when_server_reports_unavailable()
    {
        // Leaseless mode on the server → {"active": null}, never a false 0.
        var handler = new SessionCountHandler("{\"valid\":true,\"active\":null}");
        WithSessionCountHttp(handler, () =>
            Assert.Null(License.GetActiveSessionCount("cb_key")));
    }

    [Fact]
    public void ActiveSessionCount_null_on_denial()
    {
        var handler = new SessionCountHandler(
            "{\"valid\":false,\"error\":\"invalid_key\"}", HttpStatusCode.Forbidden);
        WithSessionCountHttp(handler, () =>
            Assert.Null(License.GetActiveSessionCount("cb_bad")));
    }

    [Fact]
    public void ActiveSessionCount_is_never_cached()
    {
        // ValidateLicense caches 24h; a cached seat count would be a wrong seat
        // count, so every call must hit the network.
        var handler = new SessionCountHandler("{\"valid\":true,\"active\":2}");
        WithSessionCountHttp(handler, () =>
        {
            License.GetActiveSessionCount("cb_key");
            License.GetActiveSessionCount("cb_key");
        });
        Assert.Equal(2, handler.Calls);
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
    public void EffectiveVersion_pro_marker_without_binary_returns_null()
    {
        var marker = Path.Combine(_tmp, $"latest_pro_version_{Config.GetPlatformTag()}");
        File.WriteAllText(marker, "148.0.7778.215.2");
        // Ticket 431 Fix 4: marker present but no Pro binary on disk -> null, NOT the
        // free base. A valid Pro license must never fall back to the free binary.
        Assert.Null(Config.GetEffectiveVersion(pro: true));
    }

    [Fact]
    public void EffectiveVersion_pro_no_marker_returns_null_free_returns_base()
    {
        // No Pro marker at all -> null for Pro; free tier still resolves to a version.
        Assert.Null(Config.GetEffectiveVersion(pro: true));
        Assert.Equal(Config.GetChromiumVersion(), Config.GetEffectiveVersion(pro: false));
    }

    // Create a fake cached, executable Pro binary for `version`.
    private static void MakeProBinary(string version)
    {
        var p = Config.GetBinaryPath(version, pro: true);
        Directory.CreateDirectory(Path.GetDirectoryName(p)!);
        File.WriteAllText(p, "binary");
        if (!RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
            File.SetUnixFileMode(p,
                UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
    }

    [Fact]
    public void CheckForProUpdate_already_latest_returns_null()
    {
        // Ticket 431 Fix 1: `update` on a Pro install already at latest is a no-op.
        File.WriteAllText(
            Path.Combine(_tmp, $"latest_pro_version_{Config.GetPlatformTag()}"),
            "148.0.7778.215.5");
        MakeProBinary("148.0.7778.215.5");
        License.ProLatestVersionOverride = () => "148.0.7778.215.5";
        try
        {
            Assert.Null(Download.CheckForProUpdate("cb_key"));
        }
        finally { License.ProLatestVersionOverride = null; }
    }

    [Fact]
    public void CheckForProUpdate_server_down_returns_null()
    {
        License.ProLatestVersionOverride = () => null;
        try
        {
            Assert.Null(Download.CheckForProUpdate("cb_key"));
        }
        finally { License.ProLatestVersionOverride = null; }
    }

    // =======================================================================
    // BuildLaunchEnv
    // =======================================================================

    [Fact]
    public void BuildLaunchEnv_no_key_returns_null()
    {
        Assert.Null(License.BuildLaunchEnv());
    }

    [Fact]
    public void BuildLaunchEnv_explicit_param_injects_env()
    {
        var result = License.BuildLaunchEnv("cb_test_key");
        Assert.NotNull(result);
        Assert.Equal("cb_test_key", result["CLOAKBROWSER_LICENSE_KEY"]);
        // Parent env vars should be present
        Assert.Contains("PATH", result.Keys);
    }

    [Fact]
    public void BuildLaunchEnv_env_source_no_user_env_returns_null()
    {
        var prev = Environment.GetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY");
        try
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", "cb_env");
            Assert.Null(License.BuildLaunchEnv());
        }
        finally
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", prev);
        }
    }

    [Fact]
    public void BuildLaunchEnv_env_source_with_user_env_preserves_key()
    {
        var prev = Environment.GetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY");
        try
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", "cb_env");
            var result = License.BuildLaunchEnv(null, new Dictionary<string, string> { ["MY_VAR"] = "1" });
            Assert.NotNull(result);
            Assert.Equal("cb_env", result["CLOAKBROWSER_LICENSE_KEY"]);
            Assert.Equal("1", result["MY_VAR"]);
        }
        finally
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", prev);
        }
    }

    [Fact]
    public void BuildLaunchEnv_default_file_skips_injection()
    {
        // Place license.key in the default ~/.cloakbrowser path
        var homeDir = Path.Combine(_tmp, "home");
        var defaultCache = Path.Combine(homeDir, ".cloakbrowser");
        Directory.CreateDirectory(defaultCache);
        File.WriteAllText(Path.Combine(defaultCache, "license.key"), "cb_file");

        var prevCacheDir = Environment.GetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR");
        try
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", defaultCache);
            // Mock the OS home path via the test seam so the cache dir is
            // recognized as the default ~/.cloakbrowser path.
            License.HomeDirOverride = () => homeDir;
            Assert.Null(License.BuildLaunchEnv());

            // With a custom userEnv, Playwright replaces the child env (which
            // could drop HOME and hide the file), so the key IS injected.
            var withUser = License.BuildLaunchEnv(null, new Dictionary<string, string> { ["KEEP"] = "me" });
            Assert.NotNull(withUser);
            Assert.Equal("me", withUser["KEEP"]);
            Assert.Equal("cb_file", withUser["CLOAKBROWSER_LICENSE_KEY"]);
        }
        finally
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", prevCacheDir);
            License.HomeDirOverride = null;
        }
    }

    [Fact]
    public void BuildLaunchEnv_user_env_preserved()
    {
        var result = License.BuildLaunchEnv("cb_mine", new Dictionary<string, string> { ["PATH"] = "/custom/bin" });
        Assert.NotNull(result);
        Assert.Equal("cb_mine", result["CLOAKBROWSER_LICENSE_KEY"]);
        Assert.Equal("/custom/bin", result["PATH"]);
        // Only the user env + injected key — NOT the full parent environment.
        Assert.Equal(2, result.Count);
    }

    // ── license exit-code surfacing ───────────────────────

    private static string LaunchText(int code) =>
        "BrowserType.LaunchAsync: Target page, context or browser has been closed\n" +
        $"Browser logs:\n- [pid=123] <process did exit: exitCode={code}, signal=null>";

    [Theory]
    [InlineData(76, "session limit")]
    [InlineData(77, "invalid, expired, or missing")]
    [InlineData(78, "couldn't verify")]
    [InlineData(79, "not writable")]
    public void LicenseErrorMessage_MapsKnownCodes(int code, string fragment)
    {
        var msg = License.LicenseErrorMessage(LaunchText(code));
        Assert.NotNull(msg);
        Assert.StartsWith("CloakBrowser Pro:", msg);
        Assert.Contains(fragment, msg);
    }

    [Theory]
    [InlineData(1)]
    [InlineData(139)]
    public void LicenseErrorMessage_NonLicenseCode_ReturnsNull(int code)
    {
        Assert.Null(License.LicenseErrorMessage(LaunchText(code)));
    }

    [Fact]
    public void LicenseErrorMessage_LargeSehCode_DoesNotThrowOrMatch()
    {
        // Windows access violation 0xC0000005 = 3221225477, > int.MaxValue.
        // Must not overflow int.Parse (which would mask the original launch error).
        Assert.Null(License.LicenseErrorMessage("<process did exit: exitCode=3221225477, signal=null>"));
    }

    [Fact]
    public void LicenseErrorMessage_NoCode_ReturnsNull()
    {
        Assert.Null(License.LicenseErrorMessage("Target page, context or browser has been closed"));
        Assert.Null(License.LicenseErrorMessage(""));
        Assert.Null(License.LicenseErrorMessage(null));
    }

    [Fact]
    public void LicenseErrorFrom_ReturnsTypedErrorOrNull()
    {
        var lic = License.LicenseErrorFrom(new Exception(LaunchText(77)));
        Assert.NotNull(lic);
        Assert.IsType<CloakBrowserLicenseError>(lic);
        Assert.Contains("invalid", lic!.Message);
        Assert.Null(License.LicenseErrorFrom(new Exception("some unrelated crash")));
    }
}
