using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using CloakBrowser;
using Xunit;

namespace CloakBrowser.Tests;

/// <summary>
/// Free key by email: claim code, key save, and the no-key launch path.
/// Port of Python <c>tests/test_free_claim.py</c>. Serialized: mutates env and static seams.
/// </summary>
[Collection("env-serial")]
public sealed class ClaimTests : IDisposable
{
    private readonly string _tmp;
    private readonly string? _prevCache;
    private readonly string? _prevKey;
    private readonly string? _prevBinary;
    private readonly HttpClient _prevHttp = License.Http;
    private readonly TimeSpan _prevInterval = License.ClaimPollInterval;
    private readonly List<string> _claimBodies = new();
    private readonly Queue<string> _claimAnswers = new();
    private readonly StringWriter _err = new();
    private readonly TextWriter _prevErr = Console.Error;

    private const string Version = "155.0.8059.39.2";

    public ClaimTests()
    {
        _tmp = Directory.CreateTempSubdirectory("cloak-claim-").FullName;
        _prevCache = Environment.GetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR");
        _prevKey = Environment.GetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY");
        _prevBinary = Environment.GetEnvironmentVariable("CLOAKBROWSER_BINARY_PATH");
        Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", _tmp);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", null);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_BINARY_PATH", null);
        License.ClaimPollInterval = TimeSpan.Zero;
        // Claim POSTs get the queued answers (pending once empty); record their bodies.
        License.Http = new HttpClient(new FakeHandler(async request =>
        {
            Assert.Equal(License.ClaimUrl, request.RequestUri!.ToString());
            _claimBodies.Add(await request.Content!.ReadAsStringAsync());
            var body = _claimAnswers.Count > 0 ? _claimAnswers.Dequeue() : "{\"status\":\"pending\"}";
            if (body == "network-error") throw new HttpRequestException("down");
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(body) };
        }));
        Download.OpenBrowserOverride = _ => true;
        Download.ResetClaimPoll();
        Console.SetError(_err);
    }

    public void Dispose()
    {
        Console.SetError(_prevErr);
        License.Http = _prevHttp;
        License.ClaimPollInterval = _prevInterval;
        License.ValidateLicenseOverride = null;
        License.ProLatestVersionOverride = null;
        Download.CanPromptOverride = null;
        Download.ReadLineOverride = null;
        Download.OpenBrowserOverride = null;
        Download.ClaimPollTask = null;
        Download.ResetClaimPoll();
        Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", _prevCache);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", _prevKey);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_BINARY_PATH", _prevBinary);
        try { Directory.Delete(_tmp, recursive: true); } catch (IOException) { }
    }

    private sealed class FakeHandler(Func<HttpRequestMessage, Task<HttpResponseMessage>> serve) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
            => serve(request);
    }

    private string ClaimFile => Path.Combine(_tmp, ".free_claim");
    private string KeyFile => Path.Combine(_tmp, "license.key");

    private static void AssertOwnerOnly(string path)
    {
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows)) return;
        Assert.Equal(UnixFileMode.UserRead | UnixFileMode.UserWrite, File.GetUnixFileMode(path));
    }

    private void Answer(params string[] bodies)
    {
        foreach (var b in bodies) _claimAnswers.Enqueue(b);
    }

    /// <summary>Valid license + a cached latest build, so a launch returns without downloading.</summary>
    private Dictionary<string, string> ValidLaunch()
    {
        var seen = new Dictionary<string, string>();
        License.ValidateLicenseOverride = key => { seen["key"] = key; return new LicenseInfo(true, "free", null); };
        License.ProLatestVersionOverride = () => Version;
        var bin = Config.GetBinaryPath(Version);
        Directory.CreateDirectory(Path.GetDirectoryName(bin)!);
        File.WriteAllText(bin, "binary");
        if (!RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
            File.SetUnixFileMode(bin, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        return seen;
    }

    private void Input(params string[] lines)
    {
        var q = new Queue<string>(lines);
        Download.CanPromptOverride = () => true;
        Download.ReadLineOverride = () => q.Count > 0 ? q.Dequeue() : null;
    }

    // ── claim code ─────────────────────────────────────────────────────────

    [Fact]
    public void ClaimCode_is_reused_and_private()
    {
        var code = License.GetClaimCode();
        Assert.Matches(License.ClaimCodeRe, code);
        Assert.Equal(code, License.GetClaimCode());
        AssertOwnerOnly(ClaimFile);
    }

    [Fact]
    public void ClaimCode_rotates_after_seven_days()
    {
        var old = License.GetClaimCode();
        File.SetLastWriteTimeUtc(ClaimFile, DateTime.UtcNow - License.ClaimMaxAge - TimeSpan.FromMinutes(1));
        Assert.NotEqual(old, License.GetClaimCode());
    }

    [Fact]
    public async Task Parallel_workers_share_one_code()
    {
        using var start = new Barrier(8);
        var codes = await Task.WhenAll(Enumerable.Range(0, 8).Select(_ => Task.Run(() =>
        {
            start.SignalAndWait();
            return License.GetClaimCode();
        })));
        Assert.Single(codes.Distinct());
    }

    // ── key save ───────────────────────────────────────────────────────────

    [Fact]
    public void SaveKey_is_private_and_retires_claim()
    {
        License.GetClaimCode();
        Assert.True(License.SaveLicenseKey("cb_abc"));
        Assert.Equal("cb_abc\n", File.ReadAllText(KeyFile));
        AssertOwnerOnly(KeyFile);
        Assert.False(File.Exists(ClaimFile));
    }

    [Fact]
    public void SaveKey_rejects_non_keys()
    {
        Assert.Throws<ArgumentException>(() => License.SaveLicenseKey("<script>"));
        Assert.False(File.Exists(KeyFile));
    }

    [Fact]
    public void Poller_never_overwrites_an_existing_key()
    {
        License.SaveLicenseKey("cb_mine");
        Assert.False(License.SaveLicenseKey("cb_claimed", overwrite: false));
        Assert.Equal("cb_mine\n", File.ReadAllText(KeyFile));
    }

    [Fact]
    public void Ready_claim_with_an_existing_key_is_not_saved_but_is_retired()
    {
        // A login happened while the background poll ran: keep that key, report
        // "not saved" (no false "saved" message), and drop the spent claim so it
        // can't reinstall the key after a later logout.
        License.SaveLicenseKey("cb_mine");
        var code = License.GetClaimCode();
        Answer("{\"status\":\"ready\",\"license_key\":\"cb_claimed\"}");
        var (key, saved) = License.PollClaimCore(code);
        Assert.Equal("cb_claimed", key);
        Assert.False(saved);
        Assert.Equal("cb_mine\n", File.ReadAllText(KeyFile));
        Assert.False(File.Exists(ClaimFile));
    }

    // ── CheckClaim ─────────────────────────────────────────────────────────

    [Theory]
    [InlineData("{\"status\":\"pending\"}", null)]
    [InlineData("{\"status\":\"ready\",\"license_key\":\"cb_ok\"}", "cb_ok")]
    [InlineData("{\"status\":\"ready\",\"license_key\":\"bad key\"}", null)] // trust boundary
    public void CheckClaim_answers(string body, string? expected)
    {
        Answer(body);
        var code = new string('c', 32);
        Assert.Equal(expected, License.CheckClaim(code));
        // The code is a bearer secret: body, never the URL (the handler asserts the URL).
        Assert.Equal($"{{\"code\":\"{code}\"}}", Assert.Single(_claimBodies));
    }

    [Fact]
    public void CheckClaim_network_error_is_pending()
    {
        Answer("network-error");
        Assert.Null(License.CheckClaim(new string('c', 32)));
    }

    [Fact]
    public void CheckClaim_has_key_throws_and_retires_code()
    {
        License.GetClaimCode();
        Answer("{\"status\":\"has_key\"}");
        Assert.Throws<FreeKeyAlreadyHeldException>(() => License.CheckClaim(new string('c', 32)));
        Assert.False(File.Exists(ClaimFile));
    }

    // ── EnsureBinary with no key ───────────────────────────────────────────

    [Fact]
    public async Task No_key_without_terminal_throws_with_link_and_polls_once()
    {
        Download.CanPromptOverride = () => false;
        Download.ClaimPollWindow = TimeSpan.Zero; // one background check, then stop
        try
        {
            var ex = await Assert.ThrowsAsync<CloakBrowserLicenseError>(() => Download.EnsureBinaryAsync());
            Assert.Contains("cloakbrowser.dev/#claim=", ex.Message);
            Assert.NotNull(Download.ClaimPollTask);
            await Download.ClaimPollTask!;
            // A second no-key launch in the same process starts no second poll.
            var first = Download.ClaimPollTask;
            await Assert.ThrowsAsync<CloakBrowserLicenseError>(() => Download.EnsureBinaryAsync());
            Assert.Same(first, Download.ClaimPollTask);
        }
        finally
        {
            Download.ClaimPollWindow = TimeSpan.FromMinutes(10);
        }
        Assert.Contains("#claim=", _err.ToString()); // stderr only: stdout belongs to the app
    }

    [Fact]
    public async Task Menu_default_gets_free_key_then_launches()
    {
        var seen = ValidLaunch();
        Answer("{\"status\":\"pending\"}", "{\"status\":\"pending\"}",
            "{\"status\":\"ready\",\"license_key\":\"cb_claimed\"}"); // first check, then polls
        Input("");
        string? opened = null;
        Download.OpenBrowserOverride = url => { opened = url; return true; };

        Assert.Equal(Config.GetBinaryPath(Version), await Download.EnsureBinaryAsync());
        Assert.StartsWith(License.FreeClaimLink, opened);
        Assert.Equal("cb_claimed", seen["key"]);
        Assert.Equal("cb_claimed\n", File.ReadAllText(KeyFile));
        var err = _err.ToString();
        Assert.Contains("Welcome to CloakBrowser", err);
        Assert.Contains("1) Get a free key", err);
        // The menu was the welcome: the regular banner stays quiet this launch.
        Assert.DoesNotContain("Star us", err);
    }

    [Fact]
    public async Task Menu_paste_key_asks_again_until_valid()
    {
        var seen = ValidLaunch();
        Input("2", "hello", "cb_mine");
        Download.OpenBrowserOverride = _ => throw new InvalidOperationException("must not open a browser");

        Assert.Equal(Config.GetBinaryPath(Version), await Download.EnsureBinaryAsync());
        Assert.Equal("cb_mine", seen["key"]);
        Assert.Equal("cb_mine\n", File.ReadAllText(KeyFile));
    }

    [Fact]
    public void Menu_rejects_invalid_pasted_key()
    {
        License.ValidateLicenseOverride = key => new LicenseInfo(key == "cb_good", "free", null);
        Input("7", "2", "cb_bad", "cb_good");
        Assert.Equal("cb_good", Download.PromptLicenseKey());
        Assert.Equal("cb_good\n", File.ReadAllText(KeyFile));
    }

    [Fact]
    public void Menu_email_already_has_key_switches_to_paste()
    {
        License.ValidateLicenseOverride = _ => new LicenseInfo(true, "free", null);
        Answer("{\"status\":\"has_key\"}");
        Input("1", "cb_old");
        Assert.Equal("cb_old", Download.PromptLicenseKey());
        Assert.Contains("already has a free key", _err.ToString());
        Assert.Equal("cb_old\n", File.ReadAllText(KeyFile));
    }

    [Fact]
    public async Task No_terminal_email_already_has_key_says_so()
    {
        Download.CanPromptOverride = () => false;
        Answer("{\"status\":\"has_key\"}");
        var ex = await Assert.ThrowsAsync<CloakBrowserLicenseError>(() => Download.EnsureBinaryAsync());
        Assert.Contains("already has a free key", ex.Message);
    }

    [Fact]
    public async Task Stdin_closed_mid_menu_falls_back_to_link_error()
    {
        Input(); // EOF on the first read
        Download.ClaimPollWindow = TimeSpan.Zero;
        try
        {
            var ex = await Assert.ThrowsAsync<CloakBrowserLicenseError>(() => Download.EnsureBinaryAsync());
            Assert.Contains("#claim=", ex.Message);
            if (Download.ClaimPollTask != null) await Download.ClaimPollTask;
        }
        finally
        {
            Download.ClaimPollWindow = TimeSpan.FromMinutes(10);
        }
    }

    [Fact]
    public async Task Any_key_source_skips_the_claim()
    {
        var seen = ValidLaunch();
        Environment.SetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY", "cb_env");
        Download.CanPromptOverride = () => throw new InvalidOperationException("must not reach the claim flow");

        await Download.EnsureBinaryAsync();
        Assert.Equal("cb_env", seen["key"]);
        Assert.Empty(_claimBodies);
    }
}
