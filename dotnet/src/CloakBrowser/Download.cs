using System.Diagnostics;
using System.Diagnostics.CodeAnalysis;
using System.Formats.Tar;
using System.IO.Compression;
using System.Runtime.InteropServices;
using System.Security.Cryptography;

namespace CloakBrowser;

/// <summary>Info about the current binary installation (returned by <see cref="Download.BinaryInfo"/>).</summary>
public sealed record CloakBinaryInfo(
    string? Version,
    string Platform,
    string? BinaryPath,
    bool Installed,
    string? CacheDir,
    string DownloadUrl);

/// <summary>
/// A downloaded binary could not be authenticated (bad/missing signature, version
/// mismatch, or checksum failure).
///
/// Distinct from transient download/network errors: a verification failure is a
/// tampering signal and MUST surface, never silently fall back to another binary.
/// The routing in <see cref="Download.EnsureBinaryAsync"/> re-raises this rather
/// than falling back to a cached build.
/// </summary>
public sealed class BinaryVerificationError : Exception
{
    public BinaryVerificationError(string message) : base(message) { }
    public BinaryVerificationError(string message, Exception inner) : base(message, inner) { }
}

/// <summary>
/// Binary download and cache management for CloakBrowser.
/// Downloads the patched Chromium binary on first use, caches it locally.
/// Direct port of Python <c>cloakbrowser/download.py</c>.
/// </summary>
public static class Download
{
    // Free-key welcome banner re-show interval (1 day, seconds). Free users see
    // the "more sessions" invite again after this gap; Pro users see it only
    // once (see ShowWelcome).
    internal const long WelcomeFreeInterval = 24L * 3600;

    // Attempts to rename an extraction into place while concurrent callers are
    // replacing the same partial install (see ExtractArchive).
    private const int InstallRenameAttempts = 5;

    // Retries for a directory rename that Windows transiently denies (see
    // MoveDirectoryWithRetry): about 2.5 seconds in total.
    private const int TransientRenameAttempts = 10;
    private const int TransientRenameDelayMs = 250;

    // HRESULTs of the IOException Directory.Move throws on Windows for
    // ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION and ERROR_LOCK_VIOLATION.
    private const int AccessDeniedHResult = unchecked((int)0x80070005);
    private const int SharingViolationHResult = unchecked((int)0x80070020);
    private const int LockViolationHResult = unchecked((int)0x80070021);

    // Not readonly so tests can swap in an HttpClient backed by a fake handler.
    internal static HttpClient Http = CreateHttpClient();

    private static HttpClient CreateHttpClient()
    {
        var client = new HttpClient { Timeout = TimeSpan.FromMinutes(10) };
        client.DefaultRequestHeaders.UserAgent.ParseAdd($"cloakbrowser-dotnet/{CloakVersion.Version}");
        return client;
    }

    private static bool _wrapperUpdateChecked;

    // -----------------------------------------------------------------------
    // Testing seams - mirror the monkey-patching the Python/JS tests rely on.
    // These let unit tests inject pinned keys and a signed manifest without
    // touching the network. Null means "use real behavior" in production.
    // -----------------------------------------------------------------------

    /// <summary>Overrides the pinned signing keys for tests. Null -> use <see cref="Config.BinarySigningPubkeys"/>.</summary>
    internal static IReadOnlyList<string>? SigningPubkeysOverride;

    /// <summary>Overrides the fetched Pro (manifest, sig) pair for tests. Null -> fetch over HTTP.</summary>
    internal static Func<string, (byte[] Manifest, byte[] Sig)?>? ProSignedManifestOverride;

    private static IReadOnlyList<string> EffectiveSigningPubkeys =>
        SigningPubkeysOverride ?? Config.BinarySigningPubkeys;

    // -----------------------------------------------------------------------


    /// <summary>
    /// Whether the welcome banner should be shown now. Pro: once ever (only when
    /// the marker is absent). Free: re-show when the marker is absent or its
    /// timestamp is older than <see cref="WelcomeFreeInterval"/>. Unreadable or
    /// legacy empty markers count as stale (due).
    /// </summary>
    internal static bool WelcomeDue(string marker, bool pro)
    {
        if (!File.Exists(marker)) return true;
        if (pro) return false;
        try
        {
            if (!long.TryParse(File.ReadAllText(marker).Trim(), out var last)) return true;
            return DateTimeOffset.UtcNow.ToUnixTimeSeconds() - last >= WelcomeFreeInterval;
        }
        catch
        {
            // Unreadable marker (IO, permissions, etc.) counts as stale — never crash.
            return true;
        }
    }

    private static bool _previewFallbackWarned;

    /// <summary>Reset the once-per-process Preview-fallback notice. Test seam.</summary>
    internal static void ResetPreviewFallbackWarned() => _previewFallbackWarned = false;

    /// <summary>
    /// Tell the user, once per process, that a requested Preview build does not exist
    /// for this platform and the Stable build is being used instead.
    /// </summary>
    private static void WarnPreviewFallback()
    {
        if (_previewFallbackWarned) return;
        _previewFallbackWarned = true;
        Console.Error.WriteLine(
            "[cloakbrowser] Preview channel requested, but no preview build is available for "
            + $"{Config.GetPlatformTag()}; using the stable build.");
    }

    /// <summary>
    /// Show the launch welcome banner. A marker file gates the cadence: a paid
    /// (Pro) key shows once ever; a free key re-shows every
    /// <see cref="WelcomeFreeInterval"/>. Mirrors Python <c>_show_welcome(tier)</c>.
    ///
    /// <paramref name="tier"/>:
    ///   "pro"  — a paid license key (Pro banner + support address)
    ///   "free" — a free key (latest binary, one concurrent session)
    /// </summary>
    internal static void ShowWelcome(string tier)
    {
        var marker = Path.Combine(Config.GetCacheDir(), ".welcome_shown");
        if (!WelcomeDue(marker, tier == "pro")) return;

        // ASCII-only banner: on a legacy Windows console a non-ASCII glyph can
        // crash or mojibake the write, and this runs on the binary-download
        // path. Keep the three wrappers byte-parallel.
        var sb = new System.Text.StringBuilder();
        sb.Append('\n');
        sb.Append("  CloakBrowser - stealth Chromium for automation\n");
        if (tier == "pro")
        {
            sb.Append("  CloakBrowser Pro active.\n\n");
            sb.Append("  Pro support -> support@cloakbrowser.dev\n");
            sb.Append("  Site -> https://cloakbrowser.dev\n");
        }
        else
        {
            sb.Append("  CloakBrowser free: 1 concurrent session.\n\n");
            sb.Append("  For more than one concurrent session -> https://cloakbrowser.dev\n");
        }
        sb.Append("  Docs -> https://github.com/CloakHQ/CloakBrowser\n");
        sb.Append("  Star us if CloakBrowser helps your project!\n");
        sb.Append('\n');
        Emit(sb.ToString());
        MarkWelcomeShown();
    }

    private static void MarkWelcomeShown()
    {
        try
        {
            var marker = Path.Combine(Config.GetCacheDir(), ".welcome_shown");
            Directory.CreateDirectory(Path.GetDirectoryName(marker)!);
            File.WriteAllText(marker, DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString());
        }
        catch { /* marker write is best-effort (IO, permissions, etc.) — never crash */ }
    }

    /// <summary>Write a cosmetic line to stderr, swallowing any error (a banner must never kill a launch).</summary>
    private static void Emit(string text)
    {
        try { Console.Error.Write(text); }
        catch { /* cosmetic */ }
    }

    /// <summary>
    /// Ensure the stealth Chromium binary is available. Download if needed.
    /// Returns the path to the chrome executable. Set <c>CLOAKBROWSER_BINARY_PATH</c>
    /// to skip download and use a local build.
    /// </summary>
    /// <param name="licenseKey">
    /// CloakBrowser license key. Also read from the <c>CLOAKBROWSER_LICENSE_KEY</c>
    /// env var or <c>~/.cloakbrowser/license.key</c>. With no key anywhere, a terminal
    /// gets a menu to get a free key by email or paste one; otherwise this throws
    /// <see cref="CloakBrowserLicenseError"/> with the claim link.
    /// </param>
    /// <param name="browserVersion">
    /// Exact Chromium version pin. Also read from the <c>CLOAKBROWSER_VERSION</c>
    /// env var. When set, downloads (and caches) this specific version instead of
    /// the platform default.
    /// </param>
    /// <param name="ct">Cancellation token.</param>
    /// <param name="releaseChannel">Stable (default) or Preview binary channel.</param>
    public static async Task<string> EnsureBinaryAsync(
        string? licenseKey = null, string? browserVersion = null,
        CancellationToken ct = default, string? releaseChannel = null)
    {
        // Check for local override first.
        var localOverride = Config.GetLocalBinaryOverride();
        if (!string.IsNullOrEmpty(localOverride))
        {
            if (!File.Exists(localOverride))
                throw new FileNotFoundException(
                    $"CLOAKBROWSER_BINARY_PATH set to '{localOverride}' but file does not exist");
            CloakLog.Info("Using local binary override: {0}", localOverride);
            return localOverride;
        }

        var requestedVersion = Config.NormalizeRequestedVersion(browserVersion);

        // No key anywhere (param, env, license.key) -> get a free one first.
        var key = License.ResolveLicenseKey(licenseKey);
        if (string.IsNullOrEmpty(key))
            key = await Task.Run(ClaimFreeKey, ct).ConfigureAwait(false);

        // Sync HTTP on a cache miss: run it off the caller's thread (e.g. a UI thread).
        var info = await Task.Run(() => License.ValidateLicense(key)).ConfigureAwait(false);
        if (info != null && info.Valid)
        {
            MaybeTriggerUpdateCheck();
            // A free key always gets the latest build. Drop any version pin: the
            // server force-serves latest to free keys, so fetching a pinned
            // version's signed manifest would mismatch the served bytes and fail
            // checksum verification. Paid keys keep pinning/rollback.
            var proVersion = info.Plan == "free" ? null : requestedVersion;
            // (A blip during a routine update never reaches the error below:
            // EnsureProBinaryAsync returns the cached build and retries next launch.)
            try
            {
                return await EnsureProBinaryAsync(
                    key, proVersion, info.Plan, ct, releaseChannel).ConfigureAwait(false);
            }
            catch (BinaryVerificationError)
            {
                // Authenticity could not be confirmed - surface verbatim.
                throw;
            }
            catch (Exception e)
            {
                throw new InvalidOperationException(
                    $"CloakBrowser binary unavailable: {e.Message}. Your license is valid but " +
                    "the binary could not be downloaded right now. Retry in a moment.", e);
            }
        }
        if (info != null)
            throw new CloakBrowserLicenseError(
                $"CloakBrowser: license key is invalid or expired (plan={info.Plan}). " +
                "Check CLOAKBROWSER_LICENSE_KEY or ~/.cloakbrowser/license.key, or get " +
                "a free key with: cloakbrowser login");
        throw new CloakBrowserLicenseError(
            "CloakBrowser: license could not be validated (server unreachable and " +
            "no cached validation). Retry in a moment.");
    }

    /// <summary>Synchronous convenience wrapper around <see cref="EnsureBinaryAsync"/>.</summary>
    public static string EnsureBinary(
        string? licenseKey = null, string? browserVersion = null, string? releaseChannel = null) =>
        EnsureBinaryAsync(licenseKey, browserVersion, releaseChannel: releaseChannel).GetAwaiter().GetResult();

    // -----------------------------------------------------------------------
    // No key: free key by email (claim link) or paste one. Mirrors Python
    // download.py prompt_license_key / _claim_free_key.
    // -----------------------------------------------------------------------

    /// <summary>How long a background claim poll keeps checking for the key (not readonly: test seam).</summary>
    internal static TimeSpan ClaimPollWindow = TimeSpan.FromMinutes(10);

    private static int _claimPollStarted;

    /// <summary>The running background claim poll, if any. Test seam (await it instead of leaking it).</summary>
    internal static Task? ClaimPollTask;

    internal const string HasKeyMessage =
        "This email already has a free key. It's in the email we sent when you " +
        "first got it (search your mail for CloakBrowser).";

    // Test seams: null -> real console / browser.
    internal static Func<bool>? CanPromptOverride;
    internal static Func<string?>? ReadLineOverride;
    internal static Func<string, bool>? OpenBrowserOverride;

    /// <summary>Reset the once-per-process background claim poll. Test seam.</summary>
    internal static void ResetClaimPoll() => _claimPollStarted = 0;

    /// <summary>A person is at this terminal: neither stdin nor stderr is redirected.</summary>
    public static bool CanPrompt() =>
        CanPromptOverride?.Invoke() ?? (!Console.IsInputRedirected && !Console.IsErrorRedirected);

    /// <summary>Prompt on stderr (a program's stdout may be its data); EndOfStreamException if stdin closes.</summary>
    private static string Ask(string prompt)
    {
        Emit(prompt);
        var line = ReadLineOverride != null ? ReadLineOverride() : Console.ReadLine();
        return line?.Trim() ?? throw new EndOfStreamException("stdin closed");
    }

    private static void EmitWelcome()
    {
        Emit("\n  Welcome to CloakBrowser - stealth Chromium for automation\n");
        Emit("  https://github.com/CloakHQ/CloakBrowser\n\n");
        Emit("  CloakBrowser needs a license key.\n\n");
    }

    /// <summary>
    /// Terminal menu shared by a no-key launch and <c>cloakbrowser login</c>: get a free
    /// key by email or paste one. Returns a valid key, already saved. Throws
    /// <see cref="EndOfStreamException"/> if stdin closes.
    /// </summary>
    public static string PromptLicenseKey()
    {
        EmitWelcome();
        Emit("    1) Get a free key (by email: the latest build, 1 concurrent session)\n");
        Emit("    2) Paste a key I already have\n\n");
        while (true)
        {
            var choice = Ask("  Choose 1 or 2 [1]: ");
            if (choice is "" or "1")
            {
                var free = GetFreeKey();
                if (free != null) return free;
                Emit($"\n  {HasKeyMessage}\n");
            }
            else if (choice != "2")
            {
                Emit("  Please type 1 or 2.\n");
                continue;
            }
            var pasted = PasteKey();
            if (pasted != null) return pasted;
        }
    }

    /// <summary>Ask until a valid key is pasted (saved, returned) or the answer is empty.</summary>
    private static string? PasteKey()
    {
        while (true)
        {
            var key = Ask("  Paste your key (empty to go back): ");
            if (key.Length == 0) return null;
            if (!License.KeyRe.IsMatch(key))
            {
                Emit("  That is not a CloakBrowser key (they start with cb_).\n");
                continue;
            }
            var info = License.ValidateLicense(key);
            if (info == null)
                Emit("  Could not reach the license server. Check your connection and retry.\n");
            else if (!info.Valid)
                Emit("  That key is invalid or expired.\n");
            else
            {
                License.SaveLicenseKey(key);
                Emit("  Key saved.\n\n");
                if (info.Plan == "free")
                    MarkWelcomeShown(); // the menu was the welcome; a paid key keeps its Pro banner
                return key;
            }
        }
    }

    /// <summary>
    /// Open the claim link and wait for the key (saved, returned). Null if the email
    /// already has a key, which the server never sends to a claim.
    /// </summary>
    private static string? GetFreeKey()
    {
        var code = License.GetClaimCode();
        var link = License.ClaimLink(code);
        Emit($"\n  Open this link and enter your email:\n  {link}\n");
        if (OpenBrowser(link))
            Emit("  (opened in your browser)\n");
        Emit("\n  Waiting for you to confirm your email... (Ctrl+C to stop)\n");
        string? key;
        try
        {
            key = License.PollClaim(code, overwrite: true);
        }
        catch (FreeKeyAlreadyHeldException)
        {
            return null;
        }
        Emit("  Free key saved.\n\n");
        MarkWelcomeShown(); // the menu was the welcome: no second banner this launch
        return key;
    }

    /// <summary>Open <paramref name="url"/> in the default browser. False if that failed.</summary>
    public static bool OpenBrowser(string url)
    {
        if (OpenBrowserOverride != null) return OpenBrowserOverride(url);
        try
        {
            using var p = Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
            return true;
        }
        catch (Exception e) when (e is System.ComponentModel.Win32Exception or InvalidOperationException
                                      or PlatformNotSupportedException)
        {
            CloakLog.Debug("Could not open a browser: {0}", e.Message);
            return false;
        }
    }

    /// <summary>
    /// No key anywhere: get one before launching. A person at a terminal gets the menu
    /// (<see cref="PromptLicenseKey"/>). Anything else (CI, Docker, an MCP server) throws
    /// with the claim link and keeps polling in the background, so a long-lived process
    /// picks the key up and its next launch works.
    /// </summary>
    private static string ClaimFreeKey()
    {
        var code = License.GetClaimCode();
        string? key;
        try
        {
            key = License.CheckClaim(code);
        }
        catch (FreeKeyAlreadyHeldException)
        {
            if (!CanPrompt())
                throw new CloakBrowserLicenseError(
                    $"{HasKeyMessage} Set CLOAKBROWSER_LICENSE_KEY or run: cloakbrowser login");
            key = null; // the menu below starts over with a fresh code
        }
        if (key != null) // confirmed since an earlier launch printed the link
        {
            License.SaveLicenseKey(key, overwrite: false);
            return key;
        }
        if (CanPrompt())
        {
            try
            {
                return PromptLicenseKey();
            }
            catch (EndOfStreamException) { /* stdin closed mid-menu: fall through to the link + error */ }
        }
        code = License.GetClaimCode(); // fresh if the old one was retired
        var link = License.ClaimLink(code);
        EmitWelcome();
        Emit($"  Get one free (the latest build, 1 concurrent session):\n  {link}\n" +
             "  After you confirm, the key is also emailed to you.\n\n");
        StartClaimPoll(code);
        throw new CloakBrowserLicenseError(
            $"No CloakBrowser license key. Get one free: {link} " +
            "(or run: cloakbrowser login), then launch again.");
    }

    /// <summary>Poll for the claimed key in the background, once per process.</summary>
    private static void StartClaimPoll(string code)
    {
        if (Interlocked.Exchange(ref _claimPollStarted, 1) == 1) return;
        ClaimPollTask = Task.Run(() =>
        {
            try
            {
                // Saved, not merely received: an existing key is never overwritten here.
                if (License.PollClaimCore(code, deadline: DateTime.UtcNow + ClaimPollWindow).Saved)
                    Emit("\n  CloakBrowser: free key saved. The next launch uses it.\n");
            }
            catch (FreeKeyAlreadyHeldException)
            {
                Emit($"\n  CloakBrowser: {HasKeyMessage}\n  Set CLOAKBROWSER_LICENSE_KEY or run: cloakbrowser login\n");
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException or ArgumentException)
            {
                CloakLog.Warning("Could not save the claimed free key: {0}", e.Message);
            }
        });
    }

    // -----------------------------------------------------------------------
    // CloakBrowser Pro download path
    // -----------------------------------------------------------------------

    /// <summary>Ensure the Pro binary is downloaded and cached. Returns the binary path.</summary>
    private static async Task<string> EnsureProBinaryAsync(
        string licenseKey, string? requestedVersion, string? plan,
        CancellationToken ct, string? releaseChannel)
    {
        // A validated free key routes here too (it downloads the latest binary),
        // but its welcome banner is the "free" one, not the paid Pro banner.
        var welcomeTier = plan == "free" ? "free" : "pro";

        if (requestedVersion != null)
        {
            var pinnedPath = Config.GetBinaryPath(requestedVersion);
            if (File.Exists(pinnedPath) && IsExecutable(pinnedPath))
            {
                CloakLog.Debug("Pinned Pro binary found in cache: {0} (version {1})", pinnedPath, requestedVersion);
                ShowWelcome(welcomeTier);
                return pinnedPath;
            }

            CloakLog.Info("Downloading Pro Chromium {0} for {1}...", requestedVersion, Config.GetPlatformTag());
            await DownloadProBinaryAsync(requestedVersion, licenseKey, ct).ConfigureAwait(false);

            pinnedPath = Config.GetBinaryPath(requestedVersion);
            if (!File.Exists(pinnedPath) || !IsExecutable(pinnedPath))
                throw new InvalidOperationException(
                    $"Pro download completed but binary not found at: {pinnedPath}");

            // Do NOT write the Pro version marker for a pinned download. A rollback
            // pin must not make future unpinned launches stick to the old build.
            ShowWelcome(welcomeTier);
            return pinnedPath;
        }

        // Unpinned: track the server's latest selected channel.
        var effective = Config.GetEffectiveVersion(releaseChannel);

        // Honor CLOAKBROWSER_AUTO_UPDATE=false: frozen AND a cached build present → keep
        // it, skip the server check. With no cached build we must still fetch one.
        // (The `update` CLI ignores this and always acts.)
        var frozen = string.Equals(
            Environment.GetEnvironmentVariable("CLOAKBROWSER_AUTO_UPDATE"), "false",
            StringComparison.OrdinalIgnoreCase);
        if (frozen && ProBinaryReady(effective))
        {
            ShowWelcome(welcomeTier);
            return Config.GetBinaryPath(effective);
        }

        // GetProLatestVersion() is rate-limited to one network call per hour and returns a
        // cached string in between, so this foreground check stays cheap steady-state.
        var latest = await Task.Run(() => License.GetProLatestVersion(releaseChannel)).ConfigureAwait(false);

        // Tell the user when they asked for Preview but the server has no preview build
        // for this platform, so the Stable build is used instead. The lookup is a cache
        // hit (GetProLatestVersion above already populated it), so this only touches the
        // network on the once-an-hour refresh.
        if (Config.NormalizeReleaseChannel(releaseChannel) == "preview")
        {
            var release = await Task.Run(() => License.GetProLatestRelease(releaseChannel)).ConfigureAwait(false);
            if (release is { Fallback: true })
                WarnPreviewFallback();
        }

        // Prefer the server's latest when it is newer than — or replaces a missing — the
        // cached build. Otherwise stay on the cached Pro binary (fast, offline-ok).
        string? version;
        if (!string.IsNullOrEmpty(latest) &&
            (!ProBinaryReady(effective) || Config.VersionNewer(latest, effective!))) // !ProBinaryReady covers effective == null
        {
            version = latest;
        }
        else
        {
            version = effective;
        }

        if (version == null)
        {
            // Valid Pro license but nothing resolvable (server unreachable AND no cached
            // build) — fail loudly.
            throw new InvalidOperationException("Could not determine latest Pro version from server");
        }

        var readyPath = Config.GetBinaryPath(version);
        if (File.Exists(readyPath) && IsExecutable(readyPath))
        {
            // Advance the marker if this cached build is newer than what the marker names,
            // so `info` (and a later server-outage launch) reflect the build we actually
            // launch — never a stale marker.
            if (version != effective)
                WriteProVersionMarker(version, releaseChannel);
            CloakLog.Debug("Pro binary found in cache: {0} (version {1})", readyPath, version);
            ShowWelcome(welcomeTier);
            return readyPath;
        }

        // `version` (the server latest) needs downloading. On failure, fall back to a
        // cached build if we have one.
        try
        {
            CloakLog.Info("Downloading Pro Chromium {0} for {1}...", version, Config.GetPlatformTag());
            await DownloadProBinaryAsync(version, licenseKey, ct).ConfigureAwait(false);
        }
        catch (BinaryVerificationError)
        {
            // A tampering signal must surface verbatim — never mask it behind the
            // cached-Pro fallback, which is only for transient download failures.
            throw;
        }
        catch (Exception)
        {
            if (ProBinaryReady(effective))
            {
                CloakLog.Warning("Pro update to {0} failed; launching cached Pro binary {1}", version, effective);
                ShowWelcome(welcomeTier);
                return Config.GetBinaryPath(effective);
            }
            throw;
        }

        var downloadedPath = Config.GetBinaryPath(version);
        if (!File.Exists(downloadedPath))
            throw new InvalidOperationException(
                $"Pro download completed but binary not found at: {downloadedPath}");

        WriteProVersionMarker(version, releaseChannel);
        ShowWelcome(welcomeTier);
        return downloadedPath;
    }

    /// <summary>
    /// Download a Pro binary from cloakbrowser.dev with license-key auth. Requests the
    /// explicit version so the served archive matches the signed manifest verified in
    /// <see cref="VerifyProDownloadAsync"/>.
    /// </summary>
    private static async Task DownloadProBinaryAsync(string version, string licenseKey, CancellationToken ct)
    {
        var downloadUrl = Config.GetProDownloadUrl(version);
        var binaryDir = Config.GetBinaryDir(version);
        var binaryPath = Config.GetBinaryPath(version);
        var platformTag = Config.GetPlatformTag();

        Directory.CreateDirectory(Path.GetDirectoryName(binaryDir)!);

        var tmpPath = Path.Combine(Path.GetTempPath(),
            $"cloakbrowser-{Guid.NewGuid():N}{Config.GetArchiveExt()}");

        try
        {
            await DownloadFileAsync(downloadUrl, tmpPath, ct, new Dictionary<string, string>
            {
                ["Authorization"] = $"Bearer {licenseKey}",
                ["X-Platform"] = platformTag,
            }).ConfigureAwait(false);

            // Non-bypassable Ed25519 signature check (M1 defense); no env var skips it.
            await VerifyProDownloadAsync(tmpPath, version, ct).ConfigureAwait(false);

            ExtractArchive(tmpPath, binaryDir, binaryPath);
        }
        finally
        {
            try { if (File.Exists(tmpPath)) File.Delete(tmpPath); } catch (IOException) { }
        }
    }

    /// <summary>
    /// Verify a downloaded archive with a non-bypassable Ed25519 signature check.
    ///
    /// A tampered same-origin SHA256SUMS could otherwise certify a tampered binary
    /// (#308). Fetch the Pro SHA256SUMS + detached SHA256SUMS.sig, verify the signature
    /// against the pinned keys FIRST, bind the manifest to the requested version, then
    /// verify the archive's SHA-256. An invalid signature, checksum, or version mismatch
    /// throws <see cref="BinaryVerificationError"/> (a tampering signal the router surfaces
    /// verbatim); a failed manifest FETCH is transient and throws a plain
    /// <see cref="InvalidOperationException"/>.
    /// </summary>
    internal static async Task VerifyProDownloadAsync(string filePath, string version, CancellationToken ct)
    {
        (byte[] Manifest, byte[] Sig)? manifest;
        if (ProSignedManifestOverride != null)
        {
            manifest = ProSignedManifestOverride(version);
            if (manifest == null)
                throw new InvalidOperationException(
                    $"Could not fetch the signed SHA256SUMS for Pro {version}");
        }
        else
        {
            var baseUrl = Config.GetProManifestBaseUrl(version);
            try
            {
                using var manifestResp = await Http.GetAsync($"{baseUrl}/SHA256SUMS", ct).ConfigureAwait(false);
                manifestResp.EnsureSuccessStatusCode();
                var manifestBytes = await manifestResp.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);

                using var sigResp = await Http.GetAsync($"{baseUrl}/SHA256SUMS.sig", ct).ConfigureAwait(false);
                sigResp.EnsureSuccessStatusCode();
                var sigBytes = await sigResp.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);

                manifest = (manifestBytes, sigBytes);
            }
            catch (Exception exc)
            {
                // Fetch failure is transient, not tampering - raise a plain
                // InvalidOperationException (the router reports it as "unavailable,
                // retry") rather than a BinaryVerificationError (a tampering signal).
                throw new InvalidOperationException(
                    $"Could not fetch the signed SHA256SUMS for Pro {version} ({exc.Message})", exc);
            }
        }

        var (manifestData, sigData) = manifest.Value;

        // VerifySignature / VerifyChecksum throw InvalidOperationException; convert to
        // BinaryVerificationError so the router treats them as tampering signals
        // (re-raise) rather than transient failures (fall back to a cached build).
        try
        {
            VerifySignature(manifestData, sigData);
        }
        catch (InvalidOperationException exc)
        {
            throw new BinaryVerificationError(exc.Message, exc);
        }

        var manifestText = System.Text.Encoding.UTF8.GetString(manifestData);

        // Version binding: the signature proves "we made this manifest", not "this is
        // the version you asked for" — without this a genuinely-signed older release
        // could be served in place of the requested one (forced downgrade).
        var declared = ParseManifestVersion(manifestText);
        if (declared != version)
            throw new BinaryVerificationError(
                $"Version mismatch in signed Pro SHA256SUMS: requested {version}, " +
                $"manifest declares {declared ?? "none"}. Refusing (possible downgrade).");

        var tarballName = Config.GetArchiveName();
        var checksums = ParseChecksums(manifestText);
        if (!checksums.TryGetValue(tarballName, out var expected))
            throw new BinaryVerificationError(
                $"Signature-verified Pro SHA256SUMS has no entry for {tarballName} - " +
                "cannot confirm binary integrity.");
        try
        {
            VerifyChecksum(filePath, expected);
        }
        catch (InvalidOperationException exc)
        {
            throw new BinaryVerificationError(exc.Message, exc);
        }
    }

    private static void WriteProVersionMarker(string version, string? releaseChannel = null)
    {
        var markerPrefix = Config.NormalizeReleaseChannel(releaseChannel) == "preview"
            ? "latest_pro_version_preview"
            : "latest_pro_version";
        var marker = Path.Combine(Config.GetCacheDir(), $"{markerPrefix}_{Config.GetPlatformTag()}");
        try
        {
            Directory.CreateDirectory(Config.GetCacheDir());
            var tmp = marker + ".tmp";
            File.WriteAllText(tmp, version);
            File.Move(tmp, marker, overwrite: true);
        }
        catch (IOException) { }
    }

    /// <summary>
    /// Read the 'version=&lt;v&gt;' line from a signed manifest. Null if absent.
    /// The line has no internal whitespace so older wrappers' SHA256SUMS parsers
    /// ignore it (they only accept '&lt;hash&gt;  &lt;filename&gt;' lines).
    /// </summary>
    internal static string? ParseManifestVersion(string text)
    {
        foreach (var rawLine in text.Replace("\r\n", "\n").Split('\n'))
        {
            var line = rawLine.Trim();
            if (line.StartsWith("version=", StringComparison.Ordinal))
                return line.Substring("version=".Length).Trim();
        }
        return null;
    }

    /// <summary>
    /// Verify a detached Ed25519 signature over the raw manifest bytes.
    /// <paramref name="sigB64"/> is the base64 of the 64-byte raw signature. Tries
    /// each pinned key in <see cref="Config.BinarySigningPubkeys"/>; succeeds if any
    /// validates. Throws <see cref="InvalidOperationException"/> if the signature is
    /// malformed or no pinned key validates it.
    /// </summary>
    internal static void VerifySignature(byte[] manifestBytes, byte[] sigB64)
    {
        byte[] signature;
        try
        {
            var sigText = System.Text.Encoding.ASCII.GetString(sigB64).Trim();
            signature = Convert.FromBase64String(sigText);
        }
        catch (Exception exc)
        {
            throw new InvalidOperationException($"Malformed SHA256SUMS.sig (not valid base64): {exc.Message}");
        }

        foreach (var pubkeyB64 in EffectiveSigningPubkeys)
        {
            byte[] pubBytes;
            try
            {
                pubBytes = Convert.FromBase64String(pubkeyB64);
                if (pubBytes.Length != 32)
                    continue;
            }
            catch (Exception)
            {
                // Skip an unparseable pinned key (e.g. a placeholder) rather than
                // aborting - another pinned key may still validate.
                continue;
            }

            try
            {
                var verifier = new Org.BouncyCastle.Crypto.Signers.Ed25519Signer();
                verifier.Init(false, new Org.BouncyCastle.Crypto.Parameters.Ed25519PublicKeyParameters(pubBytes, 0));
                verifier.BlockUpdate(manifestBytes, 0, manifestBytes.Length);
                if (verifier.VerifySignature(signature))
                {
                    CloakLog.Info("SHA256SUMS signature verified: Ed25519 OK");
                    return;
                }
            }
            catch (Exception)
            {
                // Wrong-length/malformed signature for this key - try the next pinned
                // key (and ultimately fail closed below).
                continue;
            }
        }

        throw new InvalidOperationException(
            "SHA256SUMS signature verification failed - no pinned key validated the " +
            "manifest. The binary's authenticity could not be confirmed. " +
            "Report at https://github.com/CloakHQ/cloakbrowser/issues");
    }

    /// <summary>
    /// Parse SHA256SUMS format: '&lt;64-hex sha256&gt;  filename' per line.
    /// Only lines whose first token is a 64-character hex digest are accepted
    /// (matches the Python/JS parser); blank lines, the version= line, and any
    /// other junk are ignored.
    /// </summary>
    internal static Dictionary<string, string> ParseChecksums(string text)
    {
        var result = new Dictionary<string, string>();
        foreach (var rawLine in text.Trim().Replace("\r\n", "\n").Split('\n'))
        {
            var parts = rawLine.Trim().Split((char[]?)null, 2, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length != 2) continue;
            var hashVal = parts[0].ToLowerInvariant();
            if (hashVal.Length != 64 || hashVal.Any(c => !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))))
                continue;
            result[parts[1].TrimStart('*')] = hashVal;
        }
        return result;
    }

    private static void VerifyChecksum(string filePath, string expectedHash)
    {
        using var sha256 = SHA256.Create();
        using var fs = File.OpenRead(filePath);
        var hashBytes = sha256.ComputeHash(fs);
        var actual = Convert.ToHexString(hashBytes).ToLowerInvariant();
        if (actual != expectedHash.ToLowerInvariant())
            throw new InvalidOperationException(
                "Checksum verification failed!\n" +
                $"  Expected: {expectedHash}\n" +
                $"  Got:      {actual}\n" +
                "  File may be corrupted or tampered with. " +
                "Please retry or report at https://github.com/CloakHQ/cloakbrowser/issues");
        CloakLog.Info("Checksum verified: SHA-256 OK");
    }

    private static async Task DownloadFileAsync(
        string url, string dest, CancellationToken ct, IReadOnlyDictionary<string, string>? headers = null)
    {
        CloakLog.Info("Downloading from {0}", url);

        using var req = new HttpRequestMessage(HttpMethod.Get, url);
        if (headers != null)
        {
            foreach (var kv in headers)
                req.Headers.TryAddWithoutValidation(kv.Key, kv.Value);
        }

        using var resp = await Http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct)
            .ConfigureAwait(false);
        if (!resp.IsSuccessStatusCode)
            throw new InvalidOperationException(
                $"Download failed: HTTP {(int)resp.StatusCode} {resp.ReasonPhrase}");

        long total = resp.Content.Headers.ContentLength ?? 0;
        long downloaded = 0;
        int lastLoggedPct = -1;

        await using var src = await resp.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
        await using var fs = new FileStream(dest, FileMode.Create, FileAccess.Write, FileShare.None);
        var buffer = new byte[8192];
        int read;
        while ((read = await src.ReadAsync(buffer, ct).ConfigureAwait(false)) > 0)
        {
            await fs.WriteAsync(buffer.AsMemory(0, read), ct).ConfigureAwait(false);
            downloaded += read;
            if (total > 0)
            {
                int pct = (int)(downloaded / (double)total * 100);
                if (pct >= lastLoggedPct + 10)
                {
                    lastLoggedPct = pct;
                    CloakLog.Info("Download progress: {0}% ({1}/{2} MB)",
                        pct, downloaded / (1024 * 1024), total / (1024 * 1024));
                }
            }
        }

        CloakLog.Info("Download complete: {0} MB", new FileInfo(dest).Length / (1024 * 1024));
    }

    private static void ExtractArchive(string archivePath, string destDir, string binaryPath)
    {
        CloakLog.Info("Extracting to {0}", destDir);
        var bp = binaryPath;

        // Extract into a private sibling dir, then rename it into place. Concurrent
        // first runs (in this process or others) each get their own staging dir, so
        // none of them can see or delete another's half-written install.
        var stagingDir = $"{destDir}.partial-{Guid.NewGuid():N}";
        Directory.CreateDirectory(stagingDir);
        var staleDirs = new List<string>();
        try
        {
            if (archivePath.EndsWith(".zip", StringComparison.OrdinalIgnoreCase))
                ExtractZip(archivePath, stagingDir);
            else
                ExtractTar(archivePath, stagingDir);

            // If extracted into a single subdirectory, flatten it (but never .app bundles).
            FlattenSingleSubdir(stagingDir);

            var stagedBinaryPath = Path.Combine(stagingDir, Path.GetRelativePath(destDir, bp));
            if (File.Exists(stagedBinaryPath))
                MakeExecutable(stagedBinaryPath);

            // macOS: remove quarantine/provenance xattrs to prevent Gatekeeper prompts.
            if (RuntimeInformation.IsOSPlatform(OSPlatform.OSX))
                RemoveQuarantine(stagingDir);

            for (var attempt = 1; attempt <= InstallRenameAttempts; attempt++)
            {
                try
                {
                    MoveDirectoryWithRetry(stagingDir, destDir);
                    break;
                }
                catch (Exception err) when (err is IOException or UnauthorizedAccessException)
                {
                    // destDir is in the way. Keep it if another caller finished a complete
                    // install; replace it if it is an incomplete leftover, such as an
                    // interrupted in-place extraction from an older release.
                    if (File.Exists(bp) && IsExecutable(bp)) break;
                    if (attempt == InstallRenameAttempts) throw;
                }
                // Rename the leftover aside before deleting it. Deleting it in place races
                // other callers renaming their extraction into destDir.
                var staleDir = $"{destDir}.stale-{Guid.NewGuid():N}";
                try
                {
                    MoveDirectoryWithRetry(destDir, staleDir);
                }
                catch (DirectoryNotFoundException)
                {
                    continue; // another caller moved it aside first
                }
                staleDirs.Add(staleDir);
            }
        }
        finally
        {
            // Best effort, so a cleanup failure never masks the exception being thrown.
            foreach (var leftoverDir in staleDirs.Prepend(stagingDir))
            {
                try { if (Directory.Exists(leftoverDir)) Directory.Delete(leftoverDir, recursive: true); }
                catch (Exception err) when (err is IOException or UnauthorizedAccessException) { }
            }
        }

        if (File.Exists(bp))
            CloakLog.Info("Binary ready: {0}", bp);
    }

    private static void ExtractTar(string archivePath, string destDir)
    {
        // Signature-verified before extraction, so unpack as-is (symlinks included:
        // macOS .app bundles need them for the Framework layout).
        using var fileStream = File.OpenRead(archivePath);
        using var gzip = new GZipStream(fileStream, CompressionMode.Decompress);
        TarFile.ExtractToDirectory(gzip, destDir, overwriteFiles: true);
    }

    /// <summary>Rename a directory, retrying while Windows reports it as in use.</summary>
    private static void MoveDirectoryWithRetry(string source, string destination)
    {
        for (var attempt = 1; attempt <= TransientRenameAttempts; attempt++)
        {
            try
            {
                Directory.Move(source, destination);
                return;
            }
            catch (Exception err) when (err is IOException or UnauthorizedAccessException)
            {
                // Windows antivirus briefly holds freshly written files open, which fails the
                // move with access denied. An existing destination is not transient.
                var accessDenied = err is UnauthorizedAccessException
                    || err.HResult is AccessDeniedHResult or SharingViolationHResult or LockViolationHResult;
                if (!RuntimeInformation.IsOSPlatform(OSPlatform.Windows)
                    || !accessDenied
                    || attempt == TransientRenameAttempts
                    || Directory.Exists(destination))
                    throw;
                Thread.Sleep(TransientRenameDelayMs);
            }
        }
    }

    private static void ExtractZip(string archivePath, string destDir)
    {
        // Signature-verified before extraction, so unpack as-is.
        ZipFile.ExtractToDirectory(archivePath, destDir, overwriteFiles: true);
    }

    private static void FlattenSingleSubdir(string destDir)
    {
        var entries = Directory.GetFileSystemEntries(destDir);
        if (entries.Length == 1 && Directory.Exists(entries[0]))
        {
            var subdir = entries[0];
            var name = Path.GetFileName(subdir);
            // Never flatten .app bundles - macOS needs the bundle structure.
            if (name.EndsWith(".app", StringComparison.Ordinal))
            {
                CloakLog.Debug("Keeping .app bundle intact: {0}", name);
                return;
            }
            CloakLog.Debug("Flattening single subdirectory: {0}", name);
            foreach (var item in Directory.GetFileSystemEntries(subdir))
            {
                var target = Path.Combine(destDir, Path.GetFileName(item));
                if (Directory.Exists(item))
                    Directory.Move(item, target);
                else
                    File.Move(item, target);
            }
            Directory.Delete(subdir, recursive: true);
        }
    }

    /// <summary>True when a cached, executable Pro binary exists for <paramref name="version"/>.</summary>
    private static bool ProBinaryReady([NotNullWhen(true)] string? version)
    {
        if (string.IsNullOrEmpty(version)) return false;
        var p = Config.GetBinaryPath(version);
        return File.Exists(p) && IsExecutable(p);
    }

    private static bool IsExecutable(string path) => Config.IsExecutableFile(path);

    private static void MakeExecutable(string path)
    {
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows)) return;
        var mode = File.GetUnixFileMode(path);
        File.SetUnixFileMode(path,
            mode | UnixFileMode.UserExecute | UnixFileMode.GroupExecute | UnixFileMode.OtherExecute);
    }

    private static void RemoveQuarantine(string path)
    {
        try
        {
            var psi = new ProcessStartInfo("xattr")
            {
                ArgumentList = { "-cr", path },
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            using var proc = Process.Start(psi);
            proc?.WaitForExit(30000);
            CloakLog.Debug("Removed quarantine attributes from {0}", path);
        }
        catch (Exception)
        {
            CloakLog.Debug("Failed to remove quarantine attributes");
        }
    }

    /// <summary>Remove all cached binaries. Forces re-download on next launch.</summary>
    public static void ClearCache()
    {
        var cacheDir = Config.GetCacheDir();
        if (Directory.Exists(cacheDir))
        {
            Directory.Delete(cacheDir, recursive: true);
            CloakLog.Info("Cache cleared: {0}", cacheDir);
        }
    }

    /// <summary>
    /// Return info about the cached binary installation. <paramref name="browserVersion"/>
    /// (or CLOAKBROWSER_VERSION) pins the reported version so the info matches what a
    /// pinned launch actually runs, instead of latest. Version is null until a build
    /// has been downloaded.
    /// </summary>
    public static CloakBinaryInfo BinaryInfo(
        string? browserVersion = null, string? releaseChannel = null)
    {
        var version = Config.NormalizeRequestedVersion(browserVersion)
            ?? Config.GetEffectiveVersion(releaseChannel);
        return new CloakBinaryInfo(
            Version: version,
            Platform: Config.GetPlatformTag(),
            BinaryPath: version != null ? Config.GetBinaryPath(version) : null,
            Installed: ProBinaryReady(version),
            CacheDir: version != null ? Config.GetBinaryDir(version) : null,
            DownloadUrl: Config.GetProLatestDownloadUrl(releaseChannel));
    }

    // -----------------------------------------------------------------------
    // Auto-update
    // -----------------------------------------------------------------------

    /// <summary>
    /// Move a Pro install to the selected channel's latest. Blocks until complete. Returns the
    /// new version when a newer Pro build is downloaded or an already-cached newer build is
    /// activated, else null (already up to date or the server could not be reached).
    /// Requires a valid Pro license key.
    /// </summary>
    public static async Task<string?> CheckForProUpdateAsync(
        string licenseKey, CancellationToken ct = default, string? releaseChannel = null)
    {
        var latest = await Task.Run(() => License.GetProLatestVersion(releaseChannel)).ConfigureAwait(false);
        if (string.IsNullOrEmpty(latest)) return null;

        var effective = Config.GetEffectiveVersion(releaseChannel);
        if (effective != null && !Config.VersionNewer(latest, effective) && ProBinaryReady(effective))
        {
            // Already on the latest cached Pro build.
            return null;
        }

        if (!ProBinaryReady(latest))
        {
            CloakLog.Info("Downloading Pro Chromium {0}...", latest);
            await DownloadProBinaryAsync(latest, licenseKey, ct).ConfigureAwait(false);
            var p = Config.GetBinaryPath(latest);
            if (!File.Exists(p))
                throw new InvalidOperationException($"Pro download completed but binary not found at: {p}");
        }

        WriteProVersionMarker(latest, releaseChannel);
        return latest;
    }

    /// <summary>Synchronous convenience wrapper around <see cref="CheckForProUpdateAsync"/>.</summary>
    public static string? CheckForProUpdate(string licenseKey, string? releaseChannel = null) =>
        CheckForProUpdateAsync(licenseKey, releaseChannel: releaseChannel).GetAwaiter().GetResult();

    /// <summary>
    /// Check NuGet for a newer wrapper version and log an upgrade hint. Runs once per
    /// process (gated by <see cref="_wrapperUpdateChecked"/> in MaybeTriggerUpdateCheck).
    /// Faithful analog of Python's <c>_check_wrapper_update</c> (which queries PyPI):
    /// uses the NuGet flat-container index (<c>.../v3-flatcontainer/{id}/index.json</c>),
    /// takes the newest stable version, and warns if it's newer than the running wrapper.
    /// </summary>
    private static async Task CheckWrapperUpdateAsync()
    {
        if ((Environment.GetEnvironmentVariable("CLOAKBROWSER_AUTO_UPDATE") ?? "").ToLowerInvariant() == "false")
            return;
        try
        {
            using var resp = await Http.GetAsync(
                "https://api.nuget.org/v3-flatcontainer/cloakbrowser/index.json").ConfigureAwait(false);
            resp.EnsureSuccessStatusCode();
            var json = await resp.Content.ReadAsStringAsync().ConfigureAwait(false);
            using var doc = System.Text.Json.JsonDocument.Parse(json);
            if (!doc.RootElement.TryGetProperty("versions", out var versions)
                || versions.ValueKind != System.Text.Json.JsonValueKind.Array)
                return;

            string? latestStable = null;
            foreach (var ve in versions.EnumerateArray())
            {
                var v = ve.GetString();
                if (string.IsNullOrEmpty(v) || v.Contains('-')) // skip prerelease (1.2.3-beta)
                    continue;
                if (latestStable == null || WrapperVersionNewer(v, latestStable))
                    latestStable = v;
            }

            if (latestStable != null && WrapperVersionNewer(latestStable, CloakVersion.Version))
                CloakLog.Warning(
                    "Update available: CloakBrowser {0} -> {1}. Run: dotnet add package CloakBrowser",
                    CloakVersion.Version, latestStable);
        }
        catch (Exception)
        {
            CloakLog.Debug("Wrapper update check failed");
        }
    }

    /// <summary>Compare dotted wrapper (SemVer-ish) versions, e.g. "0.4.0" vs "0.3.32".</summary>
    internal static bool WrapperVersionNewer(string a, string b)
    {
        static int[] Parts(string v) =>
            v.Split('.').Select(p => int.TryParse(p, out var n) ? n : 0).ToArray();
        var pa = Parts(a);
        var pb = Parts(b);
        int len = Math.Max(pa.Length, pb.Length);
        for (int i = 0; i < len; i++)
        {
            int va = i < pa.Length ? pa[i] : 0;
            int vb = i < pb.Length ? pb[i] : 0;
            if (va != vb) return va > vb;
        }
        return false;
    }

    /// <summary>
    /// Fire-and-forget wrapper update check (once per process). The binary itself
    /// updates on the launch path (<see cref="EnsureProBinaryAsync"/>).
    /// </summary>
    private static void MaybeTriggerUpdateCheck()
    {
        if (!_wrapperUpdateChecked)
        {
            _wrapperUpdateChecked = true;
            _ = Task.Run(CheckWrapperUpdateAsync);
        }
    }
}
