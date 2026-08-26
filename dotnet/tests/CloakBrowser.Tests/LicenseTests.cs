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
    private readonly string? _prevReleaseChannel;

    public LicenseTests()
    {
        _tmp = Path.Combine(Path.GetTempPath(), $"cloak-lic-test-{Guid.NewGuid():N}");
        Directory.CreateDirectory(_tmp);
        _prevCacheDir = Environment.GetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR");
        _prevLicenseEnv = Environment.GetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY");
        _prevDownloadUrl = Environment.GetEnvironmentVariable("CLOAKBROWSER_DOWNLOAD_URL");
        _prevReleaseChannel = Environment.GetEnvironmentVariable("CLOAKBROWSER_RELEASE_CHANNEL");
        Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", _tmp);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", null);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_DOWNLOAD_URL", null);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_RELEASE_CHANNEL", null);
    }

    public void Dispose()
    {
        Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", _prevCacheDir);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", _prevLicenseEnv);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_DOWNLOAD_URL", _prevDownloadUrl);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_RELEASE_CHANNEL", _prevReleaseChannel);
        License.ValidateLicenseOverride = null;
        License.ProLatestVersionOverride = null;
        License.ProLatestReleaseOverride = null;
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
    // EnsureBinary Pro routing - a supplied key that isn't valid aborts,
    // never silently downgrades to the free binary.
    // =======================================================================

    [Fact]
    public async Task InvalidKey_aborts_not_free()
    {
        License.ValidateLicenseOverride = key => new LicenseInfo(false, "solo", null);
        var ex = await Assert.ThrowsAsync<InvalidOperationException>(
            () => Download.EnsureBinaryAsync("cb_bad"));
        Assert.Contains("invalid or expired", ex.Message);
    }

    [Fact]
    public async Task UnvalidatableKey_aborts_not_free()
    {
        // validate returns null (server unreachable, no cache) -> abort.
        License.ValidateLicenseOverride = key => null;
        var ex = await Assert.ThrowsAsync<InvalidOperationException>(
            () => Download.EnsureBinaryAsync("cb_x"));
        Assert.Contains("could not be validated", ex.Message);
    }

    // =======================================================================
    // GetProLatestVersion - rate limiting + marker
    // =======================================================================

    [Fact]
    public void ProLatestVersion_rate_limited_reads_marker()
    {
        var platform = Config.GetPlatformTag();
        var marker = Path.Combine(_tmp, $".last_pro_version_check_{platform}");
        File.WriteAllText(marker, "148.0.7778.215.2");
        File.WriteAllText(
            Path.Combine(_tmp, $".last_pro_version_resolution_{platform}"),
            "{\"version\":\"148.0.7778.215.2\",\"requested_channel\":\"stable\","
            + "\"resolved_channel\":\"stable\",\"fallback\":false}");
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
    public void ProLatestVersion_preview_uses_isolated_endpoint_and_marker()
    {
        var recorder = new RecordingHandler(
            "{\"version\":\"150.0.7871.114.3\",\"requested_channel\":\"preview\","
            + "\"resolved_channel\":\"stable\",\"fallback\":true}");
        var original = License.Http;
        License.Http = new HttpClient(recorder);
        try
        {
            var release = License.GetProLatestRelease("preview");
            Assert.NotNull(release);
            Assert.Equal("150.0.7871.114.3", release.Version);
            Assert.Equal("stable", release.ResolvedChannel);
            Assert.True(release.Fallback);
            Assert.EndsWith("?channel=preview", recorder.LastUri);
            Assert.Equal(
                "150.0.7871.114.3",
                File.ReadAllText(Path.Combine(
                    _tmp, $".last_pro_version_check_preview_{Config.GetPlatformTag()}")));
            Assert.False(File.Exists(Path.Combine(
                _tmp, $".last_pro_version_check_{Config.GetPlatformTag()}")));
        }
        finally
        {
            License.Http.Dispose();
            License.Http = original;
        }
    }

    [Fact]
    public void ProLatestVersion_old_server_preview_is_stable_fallback()
    {
        var recorder = new RecordingHandler("{\"version\":\"150.0.7871.114.3\"}");
        var original = License.Http;
        License.Http = new HttpClient(recorder);
        try
        {
            var release = License.GetProLatestRelease("preview");
            Assert.NotNull(release);
            Assert.Equal("stable", release.ResolvedChannel);
            Assert.True(release.Fallback);
        }
        finally
        {
            License.Http.Dispose();
            License.Http = original;
        }
    }

    [Fact]
    public void ProLatestVersion_reads_legacy_javascript_sidecar()
    {
        var platform = Config.GetPlatformTag();
        File.WriteAllText(
            Path.Combine(_tmp, $".last_pro_version_check_preview_{platform}"),
            "150.0.7871.114.3");
        File.WriteAllText(
            Path.Combine(_tmp, $".last_pro_version_resolution_preview_{platform}"),
            "{\"version\":\"150.0.7871.114.3\",\"requestedChannel\":\"preview\","
            + "\"resolvedChannel\":\"stable\",\"fallback\":true}");

        var release = License.GetProLatestRelease("preview");

        Assert.NotNull(release);
        Assert.Equal("stable", release.ResolvedChannel);
        Assert.True(release.Fallback);
    }

    [Fact]
    public void ProLatestVersion_offline_preview_preserves_sidecar_channel()
    {
        // Stale marker (rate-limit expired) forces the network path; the server is
        // unreachable, so the offline branch must reuse the resolution sidecar
        // instead of mislabeling a genuine preview build as a stable fallback.
        var platform = Config.GetPlatformTag();
        var marker = Path.Combine(_tmp, $".last_pro_version_check_preview_{platform}");
        File.WriteAllText(marker, "151.0.7900.10.1");
        File.WriteAllText(
            Path.Combine(_tmp, $".last_pro_version_resolution_preview_{platform}"),
            "{\"version\":\"151.0.7900.10.1\",\"requested_channel\":\"preview\","
            + "\"resolved_channel\":\"preview\",\"fallback\":false}");
        File.SetLastWriteTimeUtc(marker, DateTime.UtcNow.AddHours(-2));

        var original = License.Http;
        License.Http = new HttpClient(new ThrowingHandler());
        try
        {
            var release = License.GetProLatestRelease("preview");
            Assert.NotNull(release);
            Assert.Equal("151.0.7900.10.1", release.Version);
            Assert.Equal("preview", release.ResolvedChannel);
            Assert.False(release.Fallback);
        }
        finally
        {
            License.Http.Dispose();
            License.Http = original;
        }
    }

    [Fact]
    public void ProLatestVersion_offline_preview_without_sidecar_is_stable_fallback()
    {
        var platform = Config.GetPlatformTag();
        var marker = Path.Combine(_tmp, $".last_pro_version_check_preview_{platform}");
        File.WriteAllText(marker, "151.0.7900.10.1");
        File.SetLastWriteTimeUtc(marker, DateTime.UtcNow.AddHours(-2));

        var original = License.Http;
        License.Http = new HttpClient(new ThrowingHandler());
        try
        {
            var release = License.GetProLatestRelease("preview");
            Assert.NotNull(release);
            Assert.Equal("stable", release.ResolvedChannel);
            Assert.True(release.Fallback);
        }
        finally
        {
            License.Http.Dispose();
            License.Http = original;
        }
    }

    [Fact]
    public void ProLatestVersion_environment_selects_preview()
    {
        Environment.SetEnvironmentVariable("CLOAKBROWSER_RELEASE_CHANNEL", "preview");
        var recorder = new RecordingHandler("{\"version\":\"151.0.1234.5\"}");
        var original = License.Http;
        License.Http = new HttpClient(recorder);
        try
        {
            License.GetProLatestVersion();
            Assert.EndsWith("?channel=preview", recorder.LastUri);
        }
        finally
        {
            License.Http.Dispose();
            License.Http = original;
        }
    }

    [Fact]
    public void ProLatestVersion_explicit_stable_overrides_preview_environment()
    {
        Environment.SetEnvironmentVariable("CLOAKBROWSER_RELEASE_CHANNEL", "preview");
        var recorder = new RecordingHandler("{\"version\":\"150.0.1234.5\"}");
        var original = License.Http;
        License.Http = new HttpClient(recorder);
        try
        {
            License.GetProLatestVersion("stable");
            Assert.Equal(License.ProVersionUrl, recorder.LastUri);
        }
        finally
        {
            License.Http.Dispose();
            License.Http = original;
        }
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
        public string? LastUri { get; private set; }

        public RecordingHandler(string body) => _body = body;

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            // Read the header value here — `request` is disposed by the caller after the call.
            LastPlatform = request.Headers.TryGetValues("X-Platform", out var values)
                ? values.FirstOrDefault()
                : null;
            LastUri = request.RequestUri?.ToString();
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(_body),
            });
        }
    }

    /// <summary>Simulates an unreachable server by throwing on every request.</summary>
    private sealed class ThrowingHandler : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
            => throw new HttpRequestException("network");
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
    // GetSessionSeats — the six failure paths that used to collapse into one
    // bare null (count, cap, and the reason either is missing)
    // =======================================================================

    [Fact]
    public void SessionSeats_reports_count_and_limit()
    {
        WithSessionCountHttp(
            new SessionCountHandler("{\"valid\":true,\"active\":8,\"limit\":2000}"),
            () =>
            {
                var seats = License.GetSessionSeats("cb_key");
                Assert.Equal("ok", seats.State);
                Assert.Equal(8, seats.Active);
                Assert.Equal(2000, seats.Limit);
            });
    }

    [Fact]
    public void SessionSeats_missing_limit_is_null_not_an_error()
    {
        // A server predating the field still yields a usable count.
        WithSessionCountHttp(
            new SessionCountHandler("{\"valid\":true,\"active\":8}"),
            () =>
            {
                var seats = License.GetSessionSeats("cb_key");
                Assert.Equal("ok", seats.State);
                Assert.Equal(8, seats.Active);
                Assert.Null(seats.Limit);
            });
    }

    [Fact]
    public void SessionSeats_null_limit_is_null()
    {
        // Unlimited licence or unrecognised plan — the server says so explicitly.
        WithSessionCountHttp(
            new SessionCountHandler("{\"valid\":true,\"active\":3,\"limit\":null}"),
            () => Assert.Null(License.GetSessionSeats("cb_key").Limit));
    }

    [Fact]
    public void SessionSeats_zero_is_a_real_answer()
    {
        WithSessionCountHttp(
            new SessionCountHandler("{\"valid\":true,\"active\":0,\"limit\":5}"),
            () =>
            {
                var seats = License.GetSessionSeats("cb_key");
                Assert.Equal("ok", seats.State);
                Assert.Equal(0, seats.Active);
            });
    }

    [Fact]
    public void SessionSeats_network_failure_is_unreachable()
    {
        // info is a diagnostic — it degrades, it never throws out of the command.
        var original = License.Http;
        License.Http = new HttpClient(new ThrowingHandler());
        try
        {
            var seats = License.GetSessionSeats("cb_key");
            Assert.Equal("unreachable", seats.State);
            Assert.Null(seats.Active);
        }
        finally
        {
            License.Http.Dispose();
            License.Http = original;
        }
    }

    [Theory]
    [InlineData("license_inactive", HttpStatusCode.Forbidden)]
    [InlineData("invalid_key", HttpStatusCode.Forbidden)]
    [InlineData("rate_limited", HttpStatusCode.TooManyRequests)]
    public void SessionSeats_denial_carries_the_server_reason(string code, HttpStatusCode status)
    {
        WithSessionCountHttp(
            new SessionCountHandler($"{{\"valid\":false,\"error\":\"{code}\"}}", status),
            () =>
            {
                var seats = License.GetSessionSeats("cb_key");
                Assert.Equal("denied", seats.State);
                Assert.Equal(code, seats.Reason);
            });
    }

    [Fact]
    public void SessionSeats_denial_without_a_body_falls_back_to_the_status()
    {
        WithSessionCountHttp(
            new SessionCountHandler("not json", HttpStatusCode.InternalServerError),
            () => Assert.Equal("HTTP 500", License.GetSessionSeats("cb_key").Reason));
    }

    [Fact]
    public void SessionSeats_server_reported_unavailable_is_unknown_not_denied()
    {
        // Leaseless mode: 200, key is fine, the server just cannot count. This is
        // the distinction the old single null destroyed.
        WithSessionCountHttp(
            new SessionCountHandler("{\"valid\":true,\"active\":null,\"limit\":null}"),
            () =>
            {
                var seats = License.GetSessionSeats("cb_key");
                Assert.Equal("unknown", seats.State);
                Assert.Null(seats.Active);
            });
    }

    [Fact]
    public void SessionSeats_unparseable_body_is_unknown()
    {
        WithSessionCountHttp(
            new SessionCountHandler("not json"),
            () => Assert.Equal("unknown", License.GetSessionSeats("cb_key").State));
    }

    [Fact]
    public void SessionSeats_old_helper_still_returns_the_bare_count()
    {
        // GetActiveSessionCount is shipped public API — it must keep behaving.
        WithSessionCountHttp(
            new SessionCountHandler("{\"valid\":true,\"active\":4,\"limit\":20}"),
            () => Assert.Equal(4, License.GetActiveSessionCount("cb_key")));
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
    public void Preview_and_stable_effective_versions_are_isolated()
    {
        const string stable = "145.0.1000.1";
        const string preview = "148.0.7778.215.4";
        MakeProBinary(stable);
        MakeProBinary(preview);
        File.WriteAllText(
            Path.Combine(_tmp, $"latest_pro_version_{Config.GetPlatformTag()}"), stable);
        File.WriteAllText(
            Path.Combine(_tmp, $"latest_pro_version_preview_{Config.GetPlatformTag()}"), preview);

        Assert.Equal(stable, Config.GetEffectiveVersion(pro: true, releaseChannel: "stable"));
        Assert.Equal(preview, Config.GetEffectiveVersion(pro: true, releaseChannel: "preview"));
        Assert.False(Config.BinarySupportsHeadlessNoViewport("cb_key", releaseChannel: "stable"));
        Assert.True(Config.BinarySupportsHeadlessNoViewport("cb_key", releaseChannel: "preview"));
        Assert.True(Config.BinarySupportsMaximizedWindow("cb_key", releaseChannel: "preview"));
        Assert.False(Config.BinarySupportsHttpProxyInlineAuth("cb_key", releaseChannel: "stable"));
        Assert.True(Config.BinarySupportsHttpProxyInlineAuth("cb_key", releaseChannel: "preview"));
        Assert.Equal(preview, Download.BinaryInfo(releaseChannel: "preview").Version);

        var stableProxy = ProxyResolver.Resolve(
            "http://user:pass@host:8080", licenseKey: "cb_key", releaseChannel: "stable");
        var previewProxy = ProxyResolver.Resolve(
            "http://user:pass@host:8080", licenseKey: "cb_key", releaseChannel: "preview");
        Assert.NotNull(stableProxy.PlaywrightProxy);
        Assert.Empty(stableProxy.ExtraArgs);
        Assert.Null(previewProxy.PlaywrightProxy);
        Assert.Single(previewProxy.ExtraArgs);

        var viewport = CloakLauncher.ResolveContextViewport(new LaunchContextOptions
        {
            Headless = true,
            LicenseKey = "cb_key",
            ReleaseChannel = "preview",
        });
        Assert.Equal(-1, viewport!.Width);
        Assert.Equal(-1, viewport.Height);
    }

    [Fact]
    public void BinaryInfo_threads_channel_into_pro_download_url()
    {
        const string version = "151.0.7900.10.1";
        MakeProBinary(version); // same cached binary satisfies both channels
        File.WriteAllText(
            Path.Combine(_tmp, $"latest_pro_version_preview_{Config.GetPlatformTag()}"), version);
        File.WriteAllText(
            Path.Combine(_tmp, $"latest_pro_version_{Config.GetPlatformTag()}"), version);

        Assert.EndsWith(
            "/api/download/latest?channel=preview",
            Download.BinaryInfo(releaseChannel: "preview").DownloadUrl);
        var stableUrl = Download.BinaryInfo(releaseChannel: "stable").DownloadUrl;
        Assert.EndsWith("/api/download/latest", stableUrl);
        Assert.DoesNotContain("channel=preview", stableUrl);
    }

    [Fact]
    public void Pinned_preview_launch_bypasses_latest_lookup_and_markers()
    {
        const string pinned = "151.0.1000.1";
        MakeProBinary(pinned);
        License.ValidateLicenseOverride = _ => new LicenseInfo(true, "solo", null);
        License.ProLatestVersionOverride = () => throw new InvalidOperationException("latest lookup must not run");

        Assert.Equal(
            Config.GetBinaryPath(pinned, pro: true),
            Download.EnsureBinary("cb_key", pinned, "preview"));
        Assert.False(File.Exists(Path.Combine(
            _tmp, $"latest_pro_version_preview_{Config.GetPlatformTag()}")));
        Assert.False(File.Exists(Path.Combine(
            _tmp, $"latest_pro_version_{Config.GetPlatformTag()}")));
    }

    [Fact]
    public void Preview_without_preview_build_warns_stable_fallback()
    {
        const string stable = "150.0.1000.1";
        MakeProBinary(stable); // stable-fallback build already cached → no download
        License.ValidateLicenseOverride = _ => new LicenseInfo(true, "solo", null);
        License.ProLatestReleaseOverride =
            () => new ProReleaseInfo(stable, "preview", "stable", true);
        Download.ResetPreviewFallbackWarned();

        var sw = new StringWriter();
        var orig = Console.Error;
        Console.SetError(sw);
        try
        {
            Download.EnsureBinary("cb_key", null, "preview");
        }
        finally
        {
            Console.SetError(orig);
        }
        Assert.Contains("no preview build is available", sw.ToString());
    }

    [Fact]
    public void Genuine_preview_build_does_not_warn()
    {
        const string preview = "151.0.1000.1";
        MakeProBinary(preview);
        License.ValidateLicenseOverride = _ => new LicenseInfo(true, "solo", null);
        License.ProLatestReleaseOverride =
            () => new ProReleaseInfo(preview, "preview", "preview", false);
        Download.ResetPreviewFallbackWarned();

        var sw = new StringWriter();
        var orig = Console.Error;
        Console.SetError(sw);
        try
        {
            Download.EnsureBinary("cb_key", null, "preview");
        }
        finally
        {
            Console.SetError(orig);
        }
        Assert.DoesNotContain("no preview build is available", sw.ToString());
    }

    [Fact]
    public void CheckForProUpdate_preview_advances_only_preview_marker()
    {
        const string stable = "150.0.1000.1";
        const string preview = "151.0.1000.1";
        MakeProBinary(stable);
        MakeProBinary(preview);
        var stableMarker = Path.Combine(_tmp, $"latest_pro_version_{Config.GetPlatformTag()}");
        File.WriteAllText(stableMarker, stable);
        License.ProLatestVersionOverride = () => preview;

        Assert.Equal(preview, Download.CheckForProUpdate("cb_key", "preview"));
        Assert.Equal(stable, File.ReadAllText(stableMarker));
        Assert.Equal(
            preview,
            File.ReadAllText(Path.Combine(
                _tmp, $"latest_pro_version_preview_{Config.GetPlatformTag()}")));
    }

    [Fact]
    public void ReleaseChannel_api_shape_preserves_cancellation_token_positions()
    {
        Assert.Null(new LaunchOptions().ReleaseChannel);

        var ensureParams = typeof(Download).GetMethod(nameof(Download.EnsureBinaryAsync))!.GetParameters();
        Assert.Equal(typeof(CancellationToken), ensureParams[2].ParameterType);
        Assert.Equal("releaseChannel", ensureParams[3].Name);

        var updateParams = typeof(Download).GetMethod(nameof(Download.CheckForProUpdateAsync))!.GetParameters();
        Assert.Equal(typeof(CancellationToken), updateParams[1].ParameterType);
        Assert.Equal("releaseChannel", updateParams[2].Name);
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

    // ── post-handshake denial: helpers + guard ────────────

    [Theory]
    [InlineData(76, "session limit")]
    [InlineData(77, "invalid, expired, or missing")]
    [InlineData(78, "couldn't verify")]
    [InlineData(79, "not writable")]
    public void LicenseErrorForCode_MapsKnownCodes(int code, string fragment)
    {
        var err = License.LicenseErrorForCode(code);
        Assert.NotNull(err);
        Assert.Contains(fragment, err!.Message);
    }

    [Fact]
    public void LicenseErrorForCode_UnknownReturnsNull()
    {
        Assert.Null(License.LicenseErrorForCode(1));
        Assert.Null(License.LicenseErrorForCode(0));
    }

    [Fact]
    public void ReadDenialFile_ReturnsCodeAndConsumes()
    {
        var f = Path.Combine(_tmp, "d.json");
        File.WriteAllText(f, "76");
        Assert.Equal(76, License.ReadDenialFile(f));
        Assert.False(File.Exists(f)); // consumed so a later launch sees no stale code
    }

    [Fact]
    public void ReadDenialFile_SecondReadStillReturnsCodeAfterConsumed()
    {
        var f = Path.Combine(_tmp, "cached.json");
        File.WriteAllText(f, "76");
        Assert.Equal(76, License.ReadDenialFile(f));
        Assert.False(File.Exists(f));            // consumed
        Assert.Equal(76, License.ReadDenialFile(f)); // file gone, cached in-process
    }

    [Fact]
    public void ReadDenialFile_MissingOrGarbageReturnsNull()
    {
        Assert.Null(License.ReadDenialFile(Path.Combine(_tmp, "nope.json")));
        var bad = Path.Combine(_tmp, "bad.json");
        File.WriteAllText(bad, "not-json");
        Assert.Null(License.ReadDenialFile(bad));
        Assert.False(File.Exists(bad)); // garbage is still cleaned up
    }

    [Theory]
    [InlineData("76")]        // bare int
    [InlineData("\"76\"")]    // quoted (Python/JS accept it -> .NET must too)
    [InlineData(" 76 ")]      // whitespace-padded
    [InlineData("76\n")]      // trailing newline
    public void ReadDenialFile_ParsesTolerantlyLikePythonAndJs(string content)
    {
        var f = Path.Combine(_tmp, "d.json");
        File.WriteAllText(f, content);
        Assert.Equal(76, License.ReadDenialFile(f));
    }

    [Fact]
    public void MintDenialFile_ReturnsPathUnderDenialsDir()
    {
        License.HomeDirOverride = () => _tmp;
        try
        {
            var path = License.MintDenialFile();
            Assert.NotNull(path);
            Assert.EndsWith(".json", path);
            Assert.Contains("denials", path);
            Assert.True(Directory.Exists(Path.Combine(_tmp, ".cloakbrowser", "denials")));
        }
        finally { License.HomeDirOverride = null; }
    }

    [Fact]
    public void MintDenialFile_SweepsStaleFilesKeepsFresh()
    {
        License.HomeDirOverride = () => _tmp;
        try
        {
            var denials = Path.Combine(_tmp, ".cloakbrowser", "denials");
            Directory.CreateDirectory(denials);
            var stale = Path.Combine(denials, "stale.json");
            File.WriteAllText(stale, "76");
            File.SetLastWriteTimeUtc(stale, DateTime.UtcNow - TimeSpan.FromHours(2));
            var fresh = Path.Combine(denials, "fresh.json"); // a concurrent live denial
            File.WriteAllText(fresh, "76");

            License.MintDenialFile();

            Assert.False(File.Exists(stale)); // orphan swept
            Assert.True(File.Exists(fresh));  // in-flight denial untouched
        }
        finally { License.HomeDirOverride = null; }
    }

    [Fact]
    public void BuildLaunchEnv_StatusFileCarriedOnInheritPath()
    {
        var prev = Environment.GetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY");
        try
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", "cb_env");
            var result = License.BuildLaunchEnv(statusFile: "/tmp/denials/x.json");
            Assert.NotNull(result);
            Assert.Equal("/tmp/denials/x.json", result![License.LicenseStatusFileEnv]);
            Assert.Equal("cb_env", result["CLOAKBROWSER_LICENSE_KEY"]);
        }
        finally { Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", prev); }
    }

    [Fact]
    public async Task LicenseGuard_RaisesLicenseErrorWhenDenialFilePresent()
    {
        var f = Path.Combine(_tmp, "d.json");
        File.WriteAllText(f, "76");
        await Assert.ThrowsAsync<CloakBrowserLicenseError>(() =>
            LicenseGuard.GuardAsync<object>(
                () => throw new Exception("Target page, context or browser has been closed"), f));
    }

    [Fact]
    public async Task LicenseGuard_PassesThroughWhenNoFile()
    {
        var original = new InvalidOperationException("real crash");
        var thrown = await Assert.ThrowsAsync<InvalidOperationException>(() =>
            LicenseGuard.GuardAsync<object>(() => throw original, Path.Combine(_tmp, "absent.json")));
        Assert.Same(original, thrown);
    }

    [Fact]
    public async Task LicenseGuard_NullPathPassesThrough()
    {
        var original = new InvalidOperationException("real crash");
        var thrown = await Assert.ThrowsAsync<InvalidOperationException>(() =>
            LicenseGuard.GuardAsync<object>(() => throw original, null));
        Assert.Same(original, thrown);
    }

    // The binary writes the denial file the instant it's over cap but keeps serving
    // (blank) responses for ~1s before it exits, so a fast op that SUCCEEDS must still
    // surface the denial. GuardAsync checks the file after a successful call too.
    [Fact]
    public async Task LicenseGuard_RaisesLicenseErrorOnSuccessfulCall()
    {
        var f = Path.Combine(_tmp, "d.json");
        File.WriteAllText(f, "76");
        await Assert.ThrowsAsync<CloakBrowserLicenseError>(() =>
            LicenseGuard.GuardAsync<object>(() => Task.FromResult<object>("ok"), f));
    }

    [Fact]
    public async Task LicenseGuard_SuccessPassesThroughWhenNoFile()
    {
        var result = await LicenseGuard.GuardAsync<object>(
            () => Task.FromResult<object>("ok"), Path.Combine(_tmp, "absent.json"));
        Assert.Equal("ok", result);
    }
}
