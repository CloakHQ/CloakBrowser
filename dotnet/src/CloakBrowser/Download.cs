using System.Diagnostics;
using System.Formats.Tar;
using System.IO.Compression;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Security.Cryptography;

namespace CloakBrowser;

/// <summary>Info about the current binary installation (returned by <see cref="Download.BinaryInfo"/>).</summary>
public sealed record CloakBinaryInfo(
    string Version,
    string Tier,
    string BundledVersion,
    string Platform,
    string BinaryPath,
    bool Installed,
    string CacheDir,
    string DownloadUrl);

/// <summary>
/// A downloaded binary could not be authenticated (bad/missing signature, version
/// mismatch, or checksum failure).
///
/// Distinct from transient download/network errors: a verification failure is a
/// tampering signal and MUST surface, never silently fall back to another binary.
/// The Pro routing in <see cref="Download.EnsureBinaryAsync"/> re-raises this rather
/// than downgrading to the free tier.
/// </summary>
public sealed class BinaryVerificationError : Exception
{
    public BinaryVerificationError(string message) : base(message) { }
    public BinaryVerificationError(string message, Exception inner) : base(message, inner) { }
}

/// <summary>
/// A non-2xx HTTP response during a binary download. Carries the status code so
/// callers can distinguish a 404 (binary not built for this platform - e.g. the
/// macOS Pro build hasn't shipped yet) from transient failures. Mirrors the JS
/// <c>DownloadHttpError</c> introduced in v0.4.2.
/// </summary>
public sealed class DownloadHttpError : Exception
{
    public System.Net.HttpStatusCode Status { get; }
    public DownloadHttpError(System.Net.HttpStatusCode status, string? reason)
        : base($"Download failed: HTTP {(int)status} {reason}")
        => Status = status;
}

/// <summary>
/// Binary download and cache management for CloakBrowser.
/// Downloads the patched Chromium binary on first use, caches it locally.
/// Direct port of Python <c>cloakbrowser/download.py</c>.
/// </summary>
public static class Download
{
    // Auto-update check interval (1 hour).
    private const int UpdateCheckInterval = 3600;

    private static readonly HttpClient Http = CreateHttpClient();

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

    /// <summary>Overrides the fetched (manifest, sig) pair for tests. Null -> fetch over HTTP.</summary>
    internal static Func<string?, (byte[] Manifest, byte[] Sig)?>? SignedManifestOverride;

    /// <summary>Overrides the fetched Pro (manifest, sig) pair for tests. Null -> fetch over HTTP.</summary>
    internal static Func<string, (byte[] Manifest, byte[] Sig)?>? ProSignedManifestOverride;

    private static IReadOnlyList<string> EffectiveSigningPubkeys =>
        SigningPubkeysOverride ?? Config.BinarySigningPubkeys;

    // -----------------------------------------------------------------------

    // Pro Chromium major shown in the free-tier welcome banner. Bump at each Pro
    // major release (there is no local constant to derive it from - the live Pro
    // version comes from the network, which we don't call just to print a banner).
    private const string ProMajor = "148";

    /// <summary>
    /// Show the first-launch welcome banner once (gated by a marker file). The
    /// Pro-upsell line is shown to free-tier users only; Pro users get a plain
    /// banner (no "running free tier" message, which would be false for them).
    /// Mirrors Python <c>_show_welcome(pro=...)</c>.
    /// </summary>
    private static void ShowWelcome(bool pro = false)
    {
        var marker = Path.Combine(Config.GetCacheDir(), ".welcome_shown");
        if (File.Exists(marker)) return;

        var sb = new System.Text.StringBuilder();
        sb.Append('\n');
        sb.Append("  CloakBrowser - stealth Chromium for automation\n");
        sb.Append("  https://github.com/CloakHQ/CloakBrowser\n");
        sb.Append('\n');
        if (pro)
        {
            sb.Append($"  CloakBrowser Pro active (v{ProMajor}) - latest binary, newest patches.\n");
            sb.Append("  Pro support -> support@cloakbrowser.dev\n");
        }
        else
        {
            var freeMajor = Config.GetChromiumVersion().Split('.')[0];
            sb.Append($"  Running free tier (v{freeMajor}). " +
                      $"Pro = latest binary (v{ProMajor}) + newest anti-bot patches.\n");
            sb.Append("  Stay ahead of detection -> https://cloakbrowser.dev\n");
        }
        sb.Append("  Star us if CloakBrowser helps your project!\n");
        sb.Append('\n');
        Console.Error.Write(sb.ToString());

        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(marker)!);
            File.WriteAllText(marker, "");
        }
        catch (IOException) { }
    }

    /// <summary>
    /// Ensure the stealth Chromium binary is available. Download if needed.
    /// Returns the path to the chrome executable. Set <c>CLOAKBROWSER_BINARY_PATH</c>
    /// to skip download and use a local build.
    /// </summary>
    /// <param name="licenseKey">
    /// CloakBrowser Pro license key. Also read from the <c>CLOAKBROWSER_LICENSE_KEY</c>
    /// env var or <c>~/.cloakbrowser/license.key</c>. With a valid key the latest Pro
    /// binary is downloaded from cloakbrowser.dev; without one, the free binary
    /// downloads from GitHub Releases exactly as before.
    /// </param>
    /// <param name="ct">Cancellation token.</param>
    public static async Task<string> EnsureBinaryAsync(string? licenseKey = null, CancellationToken ct = default)
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

        // Pro license key check (a custom CLOAKBROWSER_DOWNLOAD_URL overrides the Pro path).
        var key = License.ResolveLicenseKey(licenseKey);
        if (Environment.GetEnvironmentVariable("CLOAKBROWSER_DOWNLOAD_URL") != null)
            key = null;

        if (!string.IsNullOrEmpty(key))
        {
            var info = License.ValidateLicense(key);
            if (info != null && info.Valid)
            {
                // A valid license is entitled to Pro, so Pro failures surface loudly
                // rather than silently substituting the older free binary. (A blip
                // during a routine update never reaches here: EnsureProBinaryAsync
                // returns the cached Pro binary and updates in the background.)
                try
                {
                    return await EnsureProBinaryAsync(key, ct).ConfigureAwait(false);
                }
                catch (BinaryVerificationError)
                {
                    // Authenticity could not be confirmed - surface verbatim.
                    throw;
                }
                catch (Exception e)
                {
                    // macOS has no Pro binary yet. Rather than hard-failing a paying
                    // customer, fall back to the free binary with a clear notice.
                    // Scoped to the 404 (binary-not-found) case so that (a) transient
                    // and verification failures still hard-fail - no silent downgrade -
                    // and (b) the moment the macOS Pro build ships, the 404 disappears
                    // and Pro is served automatically with no wrapper change. (v0.4.2)
                    if (Config.GetPlatformTag().StartsWith("darwin", StringComparison.Ordinal)
                        && e is DownloadHttpError he
                        && he.Status == System.Net.HttpStatusCode.NotFound)
                    {
                        CloakLog.Warning(
                            "macOS Pro binary is not available yet - using the free binary " +
                            "for now. Your license stays valid and you'll get the Pro binary " +
                            "on macOS automatically once the build ships.");
                        // fall through to the free-tier download below
                    }
                    else
                    {
                        // Transient failure with no cached Pro binary to use - surface a
                        // clear error rather than silently downloading the free binary.
                        throw new InvalidOperationException(
                            $"Pro binary unavailable: {e.Message}. Your license is valid but the " +
                            "Pro binary could not be downloaded right now. Retry in a moment. " +
                            "To use the free binary instead, unset CLOAKBROWSER_LICENSE_KEY.", e);
                    }
                }
            }
            else if (info != null)
            {
                CloakLog.Warning("License validation failed (plan={0}), using free tier", info.Plan);
            }
            else
            {
                CloakLog.Warning("License validation unavailable, using free tier");
            }
        }

        // Fail fast if no binary available for this platform.
        Config.CheckPlatformAvailable();

        // Check for auto-updated version first, then fall back to hardcoded.
        var effective = Config.GetEffectiveVersion();
        var binaryPath = Config.GetBinaryPath(effective);

        if (File.Exists(binaryPath) && IsExecutable(binaryPath))
        {
            CloakLog.Debug("Binary found in cache: {0} (version {1})", binaryPath, effective);
            ShowWelcome();
            MaybeTriggerUpdateCheck();
            return binaryPath;
        }

        // Fall back to platform's hardcoded version if effective version binary doesn't exist.
        var platformVersion = Config.GetChromiumVersion();
        if (effective != platformVersion)
        {
            var fallbackPath = Config.GetBinaryPath();
            if (File.Exists(fallbackPath) && IsExecutable(fallbackPath))
            {
                CloakLog.Debug("Binary found in cache: {0}", fallbackPath);
                MaybeTriggerUpdateCheck();
                return fallbackPath;
            }
        }

        // Download platform's hardcoded version.
        CloakLog.Info("Stealth Chromium {0} not found. Downloading for {1}...",
            platformVersion, Config.GetPlatformTag());
        await DownloadAndExtractAsync(null, ct).ConfigureAwait(false);

        binaryPath = Config.GetBinaryPath();
        if (!File.Exists(binaryPath))
            throw new InvalidOperationException(
                $"Download completed but binary not found at expected path: {binaryPath}. " +
                "This may indicate a packaging issue. Please report at " +
                "https://github.com/CloakHQ/cloakbrowser/issues");

        MaybeTriggerUpdateCheck();
        return binaryPath;
    }

    /// <summary>Synchronous convenience wrapper around <see cref="EnsureBinaryAsync"/>.</summary>
    public static string EnsureBinary(string? licenseKey = null) =>
        EnsureBinaryAsync(licenseKey).GetAwaiter().GetResult();

    private static async Task DownloadAndExtractAsync(string? version, CancellationToken ct)
    {
        var primaryUrl = Config.GetDownloadUrl(version);
        var fallbackUrl = Config.GetFallbackDownloadUrl(version);
        var binaryDir = Config.GetBinaryDir(version);
        var binaryPath = Config.GetBinaryPath(version);

        Directory.CreateDirectory(Path.GetDirectoryName(binaryDir)!);

        var tmpPath = Path.Combine(Path.GetTempPath(),
            $"cloakbrowser-{Guid.NewGuid():N}{Config.GetArchiveExt()}");

        try
        {
            // Try primary, fall back to GitHub Releases (skip fallback if custom URL).
            try
            {
                await DownloadFileAsync(primaryUrl, tmpPath, ct).ConfigureAwait(false);
            }
            catch (Exception primaryErr)
            {
                if (Environment.GetEnvironmentVariable("CLOAKBROWSER_DOWNLOAD_URL") != null)
                    throw;
                CloakLog.Warning("Primary download failed ({0}), trying GitHub Releases...", primaryErr.Message);
                await DownloadFileAsync(fallbackUrl, tmpPath, ct).ConfigureAwait(false);
            }

            // Verify the download before extraction. On the official path this is a
            // mandatory, non-bypassable Ed25519 signature check (see
            // VerifyDownloadChecksumAsync); the skip flag only applies to custom
            // self-hosted CLOAKBROWSER_DOWNLOAD_URL setups.
            await VerifyDownloadChecksumAsync(tmpPath, version, ct).ConfigureAwait(false);

            ExtractArchive(tmpPath, binaryDir, binaryPath);
            ShowWelcome();
        }
        finally
        {
            try { if (File.Exists(tmpPath)) File.Delete(tmpPath); } catch (IOException) { }
        }
    }

    // -----------------------------------------------------------------------
    // CloakBrowser Pro download path
    // -----------------------------------------------------------------------

    /// <summary>Ensure the Pro binary is downloaded and cached. Returns the binary path.</summary>
    private static async Task<string> EnsureProBinaryAsync(string licenseKey, CancellationToken ct)
    {
        var effective = Config.GetEffectiveVersion(pro: true);
        var binaryPath = Config.GetBinaryPath(effective, pro: true);

        if (File.Exists(binaryPath) && IsExecutable(binaryPath))
        {
            CloakLog.Debug("Pro binary found in cache: {0} (version {1})", binaryPath, effective);
            ShowWelcome(pro: true);
            MaybeTriggerProUpdateCheck(licenseKey);
            return binaryPath;
        }

        var version = License.GetProLatestVersion();
        if (string.IsNullOrEmpty(version))
            throw new InvalidOperationException("Could not determine latest Pro version from server");

        binaryPath = Config.GetBinaryPath(version, pro: true);
        if (File.Exists(binaryPath) && IsExecutable(binaryPath))
        {
            CloakLog.Debug("Pro binary found in cache: {0} (version {1})", binaryPath, version);
            ShowWelcome(pro: true);
            return binaryPath;
        }

        CloakLog.Info("Downloading Pro Chromium {0} for {1}...", version, Config.GetPlatformTag());
        await DownloadProBinaryAsync(version, licenseKey, ct).ConfigureAwait(false);

        binaryPath = Config.GetBinaryPath(version, pro: true);
        if (!File.Exists(binaryPath))
            throw new InvalidOperationException(
                $"Pro download completed but binary not found at: {binaryPath}");

        WriteProVersionMarker(version);
        ShowWelcome(pro: true);
        return binaryPath;
    }

    /// <summary>
    /// Download a Pro binary from cloakbrowser.dev with license-key auth. Requests the
    /// explicit version so the served archive matches the signed manifest verified in
    /// <see cref="VerifyProDownloadAsync"/>.
    /// </summary>
    private static async Task DownloadProBinaryAsync(string version, string licenseKey, CancellationToken ct)
    {
        var downloadUrl = Config.GetProDownloadUrl(version);
        var binaryDir = Config.GetBinaryDir(version, pro: true);
        var binaryPath = Config.GetBinaryPath(version, pro: true);
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

            // Pro binaries come from cloakbrowser.dev - the same origin as free
            // downloads - so the same attack the Ed25519 signature defends against
            // applies equally. Verify with the same non-bypassable signature check;
            // CLOAKBROWSER_SKIP_CHECKSUM does NOT bypass it (parity with the free path).
            await VerifyProDownloadAsync(tmpPath, version, ct).ConfigureAwait(false);

            ExtractArchive(tmpPath, binaryDir, binaryPath);
        }
        finally
        {
            try { if (File.Exists(tmpPath)) File.Delete(tmpPath); } catch (IOException) { }
        }
    }

    /// <summary>
    /// Verify a Pro archive with the same non-bypassable Ed25519 signature check as
    /// official free downloads.
    ///
    /// Pro binaries are served from cloakbrowser.dev (same origin as the free tier), so
    /// a tampered same-origin SHA256SUMS could otherwise certify a tampered binary
    /// (#308). Fetch the Pro SHA256SUMS + detached SHA256SUMS.sig, verify the signature
    /// against the pinned keys FIRST, bind the manifest to the requested version, then
    /// verify the archive's SHA-256. An invalid signature, checksum, or version mismatch
    /// throws <see cref="BinaryVerificationError"/> (a tampering signal the router surfaces
    /// verbatim); a failed manifest FETCH is transient and throws a plain
    /// <see cref="InvalidOperationException"/>, never silently downgrading a valid-license user.
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
        // BinaryVerificationError so the Pro router treats them as tampering signals
        // (re-raise) rather than transient failures (fall back to free).
        try
        {
            VerifySignature(manifestData, sigData);
        }
        catch (InvalidOperationException exc)
        {
            throw new BinaryVerificationError(exc.Message, exc);
        }

        var manifestText = System.Text.Encoding.UTF8.GetString(manifestData);

        // Version binding: same forced-downgrade defense as the official free path.
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

    private static void WriteProVersionMarker(string version)
    {
        var marker = Path.Combine(Config.GetCacheDir(), $"latest_pro_version_{Config.GetPlatformTag()}");
        try
        {
            Directory.CreateDirectory(Config.GetCacheDir());
            var tmp = marker + ".tmp";
            File.WriteAllText(tmp, version);
            if (File.Exists(marker)) File.Delete(marker);
            File.Move(tmp, marker);
        }
        catch (IOException) { }
    }

    /// <summary>
    /// Verify the downloaded archive's integrity and authenticity.
    ///
    /// Official path (cloakbrowser.dev / GitHub Releases): fetch SHA256SUMS plus
    /// its detached Ed25519 signature SHA256SUMS.sig, verify the signature against
    /// the pinned public keys FIRST, then verify the archive's SHA-256 against the
    /// now-authenticated manifest. Mandatory and non-bypassable - a same-origin
    /// manifest can no longer certify a tampered binary (#308).
    ///
    /// Custom self-hosted path (CLOAKBROWSER_DOWNLOAD_URL set): the pinned keys do
    /// not apply to a third-party server, so fall back to the plain same-origin
    /// SHA256SUMS check, which CLOAKBROWSER_SKIP_CHECKSUM may bypass.
    /// </summary>
    /// <summary>Synchronous wrapper around <see cref="VerifyDownloadChecksumAsync"/> for tests.</summary>
    internal static void VerifyDownloadChecksum(string filePath, string? version = null) =>
        VerifyDownloadChecksumAsync(filePath, version, default).GetAwaiter().GetResult();

    internal static async Task VerifyDownloadChecksumAsync(string filePath, string? version, CancellationToken ct)
    {
        var tarballName = Config.GetArchiveName();

        if (Environment.GetEnvironmentVariable("CLOAKBROWSER_DOWNLOAD_URL") != null)
        {
            // Self-hosted mirror: signature scheme does not apply. Preserve the
            // legacy same-origin checksum behavior, skippable as before.
            if ((Environment.GetEnvironmentVariable("CLOAKBROWSER_SKIP_CHECKSUM") ?? "")
                .ToLowerInvariant() == "true")
            {
                CloakLog.Warning(
                    "CLOAKBROWSER_SKIP_CHECKSUM set - skipping verification for custom download URL");
                return;
            }
            var checksums = await FetchChecksumsAsync(version, ct).ConfigureAwait(false);
            if (checksums == null)
            {
                CloakLog.Warning(
                    "SHA256SUMS not available from custom URL - skipping checksum verification");
                return;
            }
            if (!checksums.TryGetValue(tarballName, out var exp))
            {
                CloakLog.Warning(
                    "SHA256SUMS found but no entry for {0} - skipping verification", tarballName);
                return;
            }
            VerifyChecksum(filePath, exp);
            return;
        }

        // Official path: signature is the trust root and is non-bypassable.
        var manifest = SignedManifestOverride != null
            ? SignedManifestOverride(version)
            : await FetchSignedManifestAsync(version, ct).ConfigureAwait(false);
        if (manifest == null)
            throw new InvalidOperationException(
                "Could not fetch a signed SHA256SUMS (SHA256SUMS + SHA256SUMS.sig) " +
                "for this release - refusing to use an unverified binary. " +
                "Retry, or report at https://github.com/CloakHQ/cloakbrowser/issues");

        var (manifestBytes, sigBytes) = manifest.Value;
        VerifySignature(manifestBytes, sigBytes);
        var manifestText = System.Text.Encoding.UTF8.GetString(manifestBytes);

        // Version binding: the signed manifest must declare the version we asked for.
        // The signature proves "we made this manifest", not "this is the version you
        // requested" - without this check a mirror could serve a genuinely-signed
        // older release in place of the requested one (forced downgrade).
        var requested = version ?? Config.GetChromiumVersion();
        var declared = ParseManifestVersion(manifestText);
        if (declared != requested)
            throw new InvalidOperationException(
                $"Version mismatch in signed SHA256SUMS: requested {requested}, " +
                $"manifest declares {declared ?? "none"}. Refusing (possible downgrade).");

        var manifestChecksums = ParseChecksums(manifestText);
        if (!manifestChecksums.TryGetValue(tarballName, out var expected))
            throw new InvalidOperationException(
                $"Signature-verified SHA256SUMS has no entry for {tarballName} - " +
                "cannot confirm binary integrity.");
        VerifyChecksum(filePath, expected);
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
    /// Fetch (SHA256SUMS, SHA256SUMS.sig) raw bytes for a version, or null.
    /// Both files are fetched from the SAME origin so the signature always matches
    /// the exact manifest bytes it certifies. The primary origin is tried first,
    /// then the GitHub Releases mirror.
    /// </summary>
    internal static async Task<(byte[] Manifest, byte[] Sig)?> FetchSignedManifestAsync(
        string? version, CancellationToken ct)
    {
        var v = version ?? Config.GetChromiumVersion();
        var bases = new[]
        {
            $"{Config.DownloadBaseUrl}/chromium-v{v}",
            $"{Config.GitHubDownloadBaseUrl}/chromium-v{v}",
        };
        foreach (var b in bases)
        {
            try
            {
                using var manifestResp = await Http.GetAsync($"{b}/SHA256SUMS", ct).ConfigureAwait(false);
                manifestResp.EnsureSuccessStatusCode();
                var manifestBytes = await manifestResp.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);

                using var sigResp = await Http.GetAsync($"{b}/SHA256SUMS.sig", ct).ConfigureAwait(false);
                sigResp.EnsureSuccessStatusCode();
                var sigBytes = await sigResp.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);

                return (manifestBytes, sigBytes);
            }
            catch (Exception) { /* try next origin */ }
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

    private static async Task<Dictionary<string, string>?> FetchChecksumsAsync(string? version, CancellationToken ct)
    {
        var v = version ?? Config.GetChromiumVersion();
        var hasCustomUrl = Environment.GetEnvironmentVariable("CLOAKBROWSER_DOWNLOAD_URL") != null;

        var urls = new List<string> { $"{Config.DownloadBaseUrl}/chromium-v{v}/SHA256SUMS" };
        if (!hasCustomUrl)
            urls.Add($"{Config.GitHubDownloadBaseUrl}/chromium-v{v}/SHA256SUMS");

        foreach (var url in urls)
        {
            try
            {
                using var resp = await Http.GetAsync(url, ct).ConfigureAwait(false);
                resp.EnsureSuccessStatusCode();
                var text = await resp.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
                return ParseChecksums(text);
            }
            catch (Exception) { /* try next */ }
        }
        return null;
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
            throw new DownloadHttpError(resp.StatusCode, resp.ReasonPhrase);

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

    private static void ExtractArchive(string archivePath, string destDir, string? binaryPath)
    {
        CloakLog.Info("Extracting to {0}", destDir);

        // Clean existing dir if partial download existed.
        if (Directory.Exists(destDir))
            Directory.Delete(destDir, recursive: true);

        Directory.CreateDirectory(destDir);

        if (archivePath.EndsWith(".zip", StringComparison.OrdinalIgnoreCase))
            ExtractZip(archivePath, destDir);
        else
            ExtractTar(archivePath, destDir);

        // If extracted into a single subdirectory, flatten it (but never .app bundles).
        FlattenSingleSubdir(destDir);

        var bp = binaryPath ?? Config.GetBinaryPath();
        if (File.Exists(bp))
            MakeExecutable(bp);

        // macOS: remove quarantine/provenance xattrs to prevent Gatekeeper prompts.
        if (RuntimeInformation.IsOSPlatform(OSPlatform.OSX))
            RemoveQuarantine(destDir);

        if (File.Exists(bp))
            CloakLog.Info("Binary ready: {0}", bp);
    }

    /// <summary>
    /// Resolves an archive entry to an absolute path under <paramref name="destinationDir"/>,
    /// guarding against path-traversal / zip-slip. The combined path is normalized via
    /// <see cref="Path.GetFullPath(string)"/> and must stay within the (also normalized)
    /// destination directory - comparison accounts for a trailing directory separator and
    /// uses <see cref="StringComparison.Ordinal"/>. Throws <see cref="InvalidOperationException"/>
    /// (naming the offending entry) when the entry escapes the destination.
    /// </summary>
    internal static string ResolveSafeEntryPath(string destinationDir, string entryName)
    {
        var destFull = Path.GetFullPath(destinationDir);
        // Ensure a trailing separator so a sibling like "<dest>foo" can't masquerade as
        // being inside "<dest>".
        var destPrefix = destFull.EndsWith(Path.DirectorySeparatorChar)
            ? destFull
            : destFull + Path.DirectorySeparatorChar;

        var memberPath = Path.GetFullPath(Path.Combine(destFull, entryName));

        if (!string.Equals(memberPath, destFull, StringComparison.Ordinal) &&
            !memberPath.StartsWith(destPrefix, StringComparison.Ordinal))
        {
            throw new InvalidOperationException($"Archive contains path traversal: {entryName}");
        }

        return memberPath;
    }

    private static void ExtractTar(string archivePath, string destDir)
    {
        using var fileStream = File.OpenRead(archivePath);
        using var gzip = new GZipStream(fileStream, CompressionMode.Decompress);
        using var reader = new TarReader(gzip);

        TarEntry? entry;
        while ((entry = reader.GetNextEntry()) != null)
        {
            // Allow symlinks - macOS .app bundles require them (Framework layout).
            if (entry.EntryType is TarEntryType.SymbolicLink or TarEntryType.HardLink)
            {
                var linkTarget = entry.LinkName;
                if (Path.IsPathRooted(linkTarget) || linkTarget.Split('/').Contains(".."))
                {
                    CloakLog.Warning("Skipping suspicious symlink: {0} -> {1}", entry.Name, linkTarget);
                    continue;
                }
                var linkPath = Path.Combine(destDir, entry.Name);
                Directory.CreateDirectory(Path.GetDirectoryName(linkPath)!);
                entry.ExtractToFile(linkPath, overwrite: true);
                continue;
            }

            var memberPath = ResolveSafeEntryPath(destDir, entry.Name);

            if (entry.EntryType == TarEntryType.Directory)
            {
                Directory.CreateDirectory(memberPath);
                continue;
            }

            Directory.CreateDirectory(Path.GetDirectoryName(memberPath)!);
            entry.ExtractToFile(memberPath, overwrite: true);
        }
    }

    private static void ExtractZip(string archivePath, string destDir)
    {
        using var zf = ZipFile.OpenRead(archivePath);
        foreach (var info in zf.Entries)
        {
            // Validate every entry up-front; throws on any zip-slip attempt.
            ResolveSafeEntryPath(destDir, info.FullName);
        }
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

    private static bool IsExecutable(string path)
    {
        if (!File.Exists(path)) return false;
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows)) return true;
        var mode = File.GetUnixFileMode(path);
        return (mode & (UnixFileMode.UserExecute | UnixFileMode.GroupExecute | UnixFileMode.OtherExecute)) != 0;
    }

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
    /// Return info about the current binary installation.
    ///
    /// <c>Tier</c> reflects what is actually installed on disk, not merely whether a
    /// license is cached - a cached license with no Pro binary downloaded yet is still
    /// effectively running the free binary, and the active key may differ from the
    /// cached one.
    /// </summary>
    public static CloakBinaryInfo BinaryInfo()
    {
        // Prefer Pro only if a Pro binary actually exists on disk.
        var proVersion = Config.GetEffectiveVersion(pro: true);
        var proPath = Config.GetBinaryPath(proVersion, pro: true);
        var pro = File.Exists(proPath) && IsExecutable(proPath);

        string effective;
        string binaryPath;
        if (pro)
        {
            effective = proVersion;
            binaryPath = proPath;
        }
        else
        {
            effective = Config.GetEffectiveVersion();
            binaryPath = Config.GetBinaryPath(effective);
        }

        return new CloakBinaryInfo(
            Version: effective,
            Tier: pro ? "pro" : "free",
            BundledVersion: Config.ChromiumVersion,
            Platform: Config.GetPlatformTag(),
            BinaryPath: binaryPath,
            Installed: File.Exists(binaryPath),
            CacheDir: Config.GetBinaryDir(effective, pro: pro),
            DownloadUrl: pro ? Config.GetProLatestDownloadUrl() : Config.GetDownloadUrl(effective));
    }

    // -----------------------------------------------------------------------
    // Auto-update
    // -----------------------------------------------------------------------

    /// <summary>
    /// Manually check for a newer Chromium version. Returns new version or null.
    /// Unlike the background check in EnsureBinary, this blocks until complete.
    /// </summary>
    public static async Task<string?> CheckForUpdateAsync(CancellationToken ct = default)
    {
        var latest = await GetLatestChromiumVersionAsync(ct).ConfigureAwait(false);
        if (latest == null) return null;
        if (!Config.VersionNewer(latest, Config.GetChromiumVersion())) return null;

        var binaryDir = Config.GetBinaryDir(latest);
        if (Directory.Exists(binaryDir))
        {
            WriteVersionMarker(latest);
            return latest;
        }

        CloakLog.Info("Downloading Chromium {0}...", latest);
        await DownloadAndExtractAsync(latest, ct).ConfigureAwait(false);
        WriteVersionMarker(latest);
        return latest;
    }

    /// <summary>Synchronous convenience wrapper around <see cref="CheckForUpdateAsync"/>.</summary>
    public static string? CheckForUpdate() => CheckForUpdateAsync().GetAwaiter().GetResult();

    private static bool ShouldCheckForUpdate()
    {
        if ((Environment.GetEnvironmentVariable("CLOAKBROWSER_AUTO_UPDATE") ?? "").ToLowerInvariant() == "false")
            return false;
        if (Config.GetLocalBinaryOverride() != null) return false;
        if (Environment.GetEnvironmentVariable("CLOAKBROWSER_DOWNLOAD_URL") != null) return false;

        var checkFile = Path.Combine(Config.GetCacheDir(), ".last_update_check");
        if (File.Exists(checkFile))
        {
            try
            {
                var lastCheck = double.Parse(File.ReadAllText(checkFile).Trim(),
                    System.Globalization.CultureInfo.InvariantCulture);
                var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
                if (now - lastCheck < UpdateCheckInterval)
                    return false;
            }
            catch (Exception ex) when (ex is FormatException or IOException) { }
        }
        return true;
    }

    private static async Task<string?> GetLatestChromiumVersionAsync(CancellationToken ct)
    {
        try
        {
            var url = $"{Config.GitHubApiUrl}?per_page=10";
            using var resp = await Http.GetAsync(url, ct).ConfigureAwait(false);
            resp.EnsureSuccessStatusCode();
            var json = await resp.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            using var doc = System.Text.Json.JsonDocument.Parse(json);
            var platformTarball = Config.GetArchiveName();
            foreach (var release in doc.RootElement.EnumerateArray())
            {
                var tag = release.TryGetProperty("tag_name", out var t) ? t.GetString() ?? "" : "";
                var draft = release.TryGetProperty("draft", out var d) && d.GetBoolean();
                if (tag.StartsWith("chromium-v", StringComparison.Ordinal) && !draft)
                {
                    if (release.TryGetProperty("assets", out var assets))
                    {
                        foreach (var asset in assets.EnumerateArray())
                        {
                            if (asset.TryGetProperty("name", out var n) && n.GetString() == platformTarball)
                                return tag["chromium-v".Length..];
                        }
                    }
                }
            }
            return null;
        }
        catch (Exception)
        {
            CloakLog.Debug("Auto-update check failed");
            return null;
        }
    }

    private static void WriteVersionMarker(string version)
    {
        var cacheDir = Config.GetCacheDir();
        Directory.CreateDirectory(cacheDir);
        var marker = Path.Combine(cacheDir, $"latest_version_{Config.GetPlatformTag()}");
        var tmp = marker + ".tmp";
        File.WriteAllText(tmp, version);
        if (File.Exists(marker)) File.Delete(marker);
        File.Move(tmp, marker);
    }

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
        if (Environment.GetEnvironmentVariable("CLOAKBROWSER_DOWNLOAD_URL") != null)
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

    private static async Task CheckAndDownloadUpdateAsync()
    {
        try
        {
            var checkFile = Path.Combine(Config.GetCacheDir(), ".last_update_check");
            Directory.CreateDirectory(Path.GetDirectoryName(checkFile)!);
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
            File.WriteAllText(checkFile, now.ToString(System.Globalization.CultureInfo.InvariantCulture));

            var platformVersion = Config.GetChromiumVersion();
            var latest = await GetLatestChromiumVersionAsync(CancellationToken.None).ConfigureAwait(false);
            if (latest == null) return;
            if (!Config.VersionNewer(latest, platformVersion)) return;

            if (Directory.Exists(Config.GetBinaryDir(latest)))
            {
                WriteVersionMarker(latest);
                return;
            }

            CloakLog.Info("Newer Chromium available: {0} (current: {1}). Downloading in background...",
                latest, platformVersion);
            await DownloadAndExtractAsync(latest, CancellationToken.None).ConfigureAwait(false);
            WriteVersionMarker(latest);
            CloakLog.Info("Background update complete: Chromium {0} ready. Will use on next launch.", latest);
        }
        catch (Exception)
        {
            CloakLog.Debug("Background update failed");
        }
    }

    private static void MaybeTriggerUpdateCheck()
    {
        // Wrapper update: once per process, not rate-limited.
        if (!_wrapperUpdateChecked)
        {
            _wrapperUpdateChecked = true;
            _ = Task.Run(CheckWrapperUpdateAsync);
        }

        // Binary update: rate-limited to once per hour.
        if (!ShouldCheckForUpdate()) return;
        _ = Task.Run(CheckAndDownloadUpdateAsync);
    }

    /// <summary>Fire-and-forget Pro binary update check in a background task (rate-limited to once/hour).</summary>
    private static void MaybeTriggerProUpdateCheck(string licenseKey)
    {
        var checkFile = Path.Combine(Config.GetCacheDir(), ".last_pro_update_check");
        if (File.Exists(checkFile))
        {
            try
            {
                var lastCheck = double.Parse(File.ReadAllText(checkFile).Trim(),
                    System.Globalization.CultureInfo.InvariantCulture);
                var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
                if (now - lastCheck < UpdateCheckInterval)
                    return;
            }
            catch (Exception ex) when (ex is FormatException or IOException) { }
        }

        _ = Task.Run(async () =>
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(checkFile)!);
                var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
                File.WriteAllText(checkFile, now.ToString(System.Globalization.CultureInfo.InvariantCulture));

                var latest = License.GetProLatestVersion();
                if (string.IsNullOrEmpty(latest)) return;
                if (File.Exists(Config.GetBinaryPath(latest, pro: true))) return;

                CloakLog.Info("Newer Pro binary available: {0}. Downloading in background...", latest);
                await DownloadProBinaryAsync(latest, licenseKey, CancellationToken.None).ConfigureAwait(false);
                WriteProVersionMarker(latest);
                CloakLog.Info("Pro background update complete: {0} ready. Will use on next launch.", latest);
            }
            catch (Exception)
            {
                CloakLog.Debug("Pro background update failed");
            }
        });
    }
}
