using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using CloakBrowser;
using Org.BouncyCastle.Crypto.Generators;
using Org.BouncyCastle.Crypto.Parameters;
using Org.BouncyCastle.Crypto.Signers;
using Org.BouncyCastle.Security;
using Xunit;

namespace CloakBrowser.Tests;

/// <summary>
/// Ed25519 binary-signature verification - port of Python <c>tests/test_update.py</c>
/// (TestSignatureVerification, TestVerifyDownloadChecksumSigned, TestVersionBinding)
/// and JS <c>js/tests/signature.test.ts</c>. Closes #308: a compromised download
/// mirror can no longer certify a tampered binary.
/// </summary>
[Collection("env-serial")]
public class SignatureTests
{
    // -----------------------------------------------------------------------
    // Ed25519 key/signature helpers (mirror _make_key / _sign in Python).
    // -----------------------------------------------------------------------

    private static (Ed25519PrivateKeyParameters Priv, string PubB64) MakeKey()
    {
        var gen = new Ed25519KeyPairGenerator();
        gen.Init(new Ed25519KeyGenerationParameters(new SecureRandom()));
        var pair = gen.GenerateKeyPair();
        var priv = (Ed25519PrivateKeyParameters)pair.Private;
        var pub = (Ed25519PublicKeyParameters)pair.Public;
        return (priv, Convert.ToBase64String(pub.GetEncoded()));
    }

    /// <summary>Return SHA256SUMS.sig content (base64 of the raw signature), as served.</summary>
    private static byte[] Sign(Ed25519PrivateKeyParameters priv, byte[] manifest)
    {
        var signer = new Ed25519Signer();
        signer.Init(true, priv);
        signer.BlockUpdate(manifest, 0, manifest.Length);
        var raw = signer.GenerateSignature();
        return Encoding.ASCII.GetBytes(Convert.ToBase64String(raw));
    }

    private static byte[] Utf8(string s) => Encoding.UTF8.GetBytes(s);

    private static string Sha256Hex(byte[] data)
    {
        using var sha = SHA256.Create();
        return Convert.ToHexString(sha.ComputeHash(data)).ToLowerInvariant();
    }

    /// <summary>Run an action with overridden pinned keys / manifest, always restoring afterwards.</summary>
    private static void WithOverrides(
        string[]? pubkeys,
        Func<string?, (byte[], byte[])?>? manifest,
        Action body)
    {
        var prevKeys = Download.SigningPubkeysOverride;
        var prevManifest = Download.SignedManifestOverride;
        var prevCustomUrl = Environment.GetEnvironmentVariable("CLOAKBROWSER_DOWNLOAD_URL");
        try
        {
            Download.SigningPubkeysOverride = pubkeys;
            Download.SignedManifestOverride = manifest;
            // Force the official path (no custom mirror).
            Environment.SetEnvironmentVariable("CLOAKBROWSER_DOWNLOAD_URL", null);
            body();
        }
        finally
        {
            Download.SigningPubkeysOverride = prevKeys;
            Download.SignedManifestOverride = prevManifest;
            Environment.SetEnvironmentVariable("CLOAKBROWSER_DOWNLOAD_URL", prevCustomUrl);
        }
    }

    private static string Tarball() => Config.GetArchiveName();

    private static byte[] Manifest(string body, string? version = null)
    {
        var v = version ?? Config.GetChromiumVersion();
        return Utf8($"version={v}\n{body}");
    }

    // =======================================================================
    // TestSignatureVerification - the cryptographic gate over manifest bytes.
    // =======================================================================

    [Fact]
    public void ValidSignature_passes()
    {
        var (priv, pub) = MakeKey();
        var manifest = Utf8("abc  cloakbrowser-linux-x64.tar.gz\n");
        var sig = Sign(priv, manifest);
        WithOverrides(new[] { pub }, null, () => Download.VerifySignature(manifest, sig));
    }

    [Fact]
    public void TamperedManifest_fails()
    {
        var (priv, pub) = MakeKey();
        var manifest = Utf8("abc  cloakbrowser-linux-x64.tar.gz\n");
        var sig = Sign(priv, manifest);
        var tampered = Utf8("xyz  cloakbrowser-linux-x64.tar.gz\n");
        WithOverrides(new[] { pub }, null, () =>
        {
            var ex = Assert.Throws<InvalidOperationException>(() => Download.VerifySignature(tampered, sig));
            Assert.Contains("signature verification failed", ex.Message);
        });
    }

    [Fact]
    public void WrongKey_fails()
    {
        var (priv, _) = MakeKey();
        var (_, otherPub) = MakeKey();
        var manifest = Utf8("data\n");
        var sig = Sign(priv, manifest);
        WithOverrides(new[] { otherPub }, null, () =>
        {
            var ex = Assert.Throws<InvalidOperationException>(() => Download.VerifySignature(manifest, sig));
            Assert.Contains("signature verification failed", ex.Message);
        });
    }

    [Fact]
    public void MalformedSignature_fails()
    {
        var (_, pub) = MakeKey();
        WithOverrides(new[] { pub }, null, () =>
        {
            var ex = Assert.Throws<InvalidOperationException>(
                () => Download.VerifySignature(Utf8("data\n"), Encoding.ASCII.GetBytes("!!!not base64!!!")));
            Assert.Contains("Malformed", ex.Message);
        });
    }

    [Fact]
    public void PlaceholderKey_is_skipped_not_crashing()
    {
        // An unparseable pinned key (placeholder) must not abort - a real key still validates.
        var (priv, pub) = MakeKey();
        var manifest = Utf8("data\n");
        var sig = Sign(priv, manifest);
        WithOverrides(
            new[] { "REPLACE_WITH_REAL_ED25519_PUBLIC_KEY_BASE64", pub },
            null,
            () => Download.VerifySignature(manifest, sig));
    }

    [Fact]
    public void KeyRotation_second_key_accepts()
    {
        // A manifest signed with the new key validates while the old key stays pinned.
        var (_, oldPub) = MakeKey();
        var (newPriv, newPub) = MakeKey();
        var manifest = Utf8("rotated\n");
        var sig = Sign(newPriv, manifest);
        WithOverrides(new[] { oldPub, newPub }, null, () => Download.VerifySignature(manifest, sig));
    }

    // =======================================================================
    // TestVerifyDownloadChecksumSigned - official path: sig + version + hash, fail-closed.
    // =======================================================================

    private static string WriteTemp(byte[] bytes)
    {
        var path = Path.Combine(Path.GetTempPath(), $"cloak-sig-test-{Guid.NewGuid():N}");
        File.WriteAllBytes(path, bytes);
        return path;
    }

    [Fact]
    public void ValidManifestAndHash_passes()
    {
        var (priv, pub) = MakeKey();
        var binary = Utf8("the real binary");
        var archive = WriteTemp(binary);
        var manifest = Manifest($"{Sha256Hex(binary)}  {Tarball()}\n");
        var sig = Sign(priv, manifest);
        try
        {
            WithOverrides(new[] { pub }, _ => (manifest, sig), () =>
                Download.VerifyDownloadChecksum(archive));
        }
        finally { File.Delete(archive); }
    }

    [Fact]
    public void TamperedBinary_fails_hash()
    {
        var (priv, pub) = MakeKey();
        var archive = WriteTemp(Utf8("a malicious binary"));
        var manifest = Manifest($"{Sha256Hex(Utf8("the real binary"))}  {Tarball()}\n");
        var sig = Sign(priv, manifest);
        try
        {
            WithOverrides(new[] { pub }, _ => (manifest, sig), () =>
            {
                var ex = Assert.Throws<InvalidOperationException>(() =>
                    Download.VerifyDownloadChecksum(archive));
                Assert.Contains("Checksum verification failed", ex.Message);
            });
        }
        finally { File.Delete(archive); }
    }

    [Fact]
    public void WrongVersion_fails_downgrade()
    {
        var (priv, pub) = MakeKey();
        var binary = Utf8("the real binary");
        var archive = WriteTemp(binary);
        // Manifest declares an old version, but we ask for the current one.
        var manifest = Manifest($"{Sha256Hex(binary)}  {Tarball()}\n", version: "1.0.0.0");
        var sig = Sign(priv, manifest);
        try
        {
            WithOverrides(new[] { pub }, _ => (manifest, sig), () =>
            {
                var ex = Assert.Throws<InvalidOperationException>(() =>
                    Download.VerifyDownloadChecksum(archive));
                Assert.Contains("Version mismatch", ex.Message);
            });
        }
        finally { File.Delete(archive); }
    }

    [Fact]
    public void MissingVersionLine_fails()
    {
        var (priv, pub) = MakeKey();
        var binary = Utf8("the real binary");
        var archive = WriteTemp(binary);
        var manifest = Utf8($"{Sha256Hex(binary)}  {Tarball()}\n"); // no version=
        var sig = Sign(priv, manifest);
        try
        {
            WithOverrides(new[] { pub }, _ => (manifest, sig), () =>
            {
                var ex = Assert.Throws<InvalidOperationException>(() =>
                    Download.VerifyDownloadChecksum(archive));
                Assert.Contains("Version mismatch", ex.Message);
            });
        }
        finally { File.Delete(archive); }
    }

    [Fact]
    public void MissingSignedManifest_fails_closed()
    {
        var archive = WriteTemp(Utf8("x"));
        try
        {
            WithOverrides(null, _ => null, () =>
            {
                var ex = Assert.Throws<InvalidOperationException>(() =>
                    Download.VerifyDownloadChecksum(archive));
                Assert.Contains("signed SHA256SUMS", ex.Message);
            });
        }
        finally { File.Delete(archive); }
    }

    [Fact]
    public void ManifestWithoutEntry_fails()
    {
        var (priv, pub) = MakeKey();
        var archive = WriteTemp(Utf8("x"));
        var manifest = Manifest($"{new string('d', 64)}  some-other-file.tar.gz\n"); // no entry for our tarball
        var sig = Sign(priv, manifest);
        try
        {
            WithOverrides(new[] { pub }, _ => (manifest, sig), () =>
            {
                var ex = Assert.Throws<InvalidOperationException>(() =>
                    Download.VerifyDownloadChecksum(archive));
                Assert.Contains("no entry for", ex.Message);
            });
        }
        finally { File.Delete(archive); }
    }

    [Fact]
    public void CustomUrl_uses_plain_checksum_and_skip()
    {
        // Self-hosted CLOAKBROWSER_DOWNLOAD_URL keeps the legacy skippable path,
        // and the signature path must NOT be consulted for a custom mirror.
        var archive = WriteTemp(Utf8("x"));
        var prevDl = Environment.GetEnvironmentVariable("CLOAKBROWSER_DOWNLOAD_URL");
        var prevSkip = Environment.GetEnvironmentVariable("CLOAKBROWSER_SKIP_CHECKSUM");
        var prevManifest = Download.SignedManifestOverride;
        bool manifestConsulted = false;
        try
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_DOWNLOAD_URL", "https://my-mirror.test");
            Environment.SetEnvironmentVariable("CLOAKBROWSER_SKIP_CHECKSUM", "true");
            Download.SignedManifestOverride = _ => { manifestConsulted = true; return null; };

            // Skip honored, no throw.
            Download.VerifyDownloadChecksum(archive);
            Assert.False(manifestConsulted, "signature path must not be consulted for a custom mirror");
        }
        finally
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_DOWNLOAD_URL", prevDl);
            Environment.SetEnvironmentVariable("CLOAKBROWSER_SKIP_CHECKSUM", prevSkip);
            Download.SignedManifestOverride = prevManifest;
            File.Delete(archive);
        }
    }

    // =======================================================================
    // TestVersionBinding - the 'version=<v>' line.
    // =======================================================================

    [Fact]
    public void ParseManifestVersion_reads_line()
    {
        var manifest = "version=146.0.7680.177.5\nabc  cloakbrowser-linux-x64.tar.gz\n";
        Assert.Equal("146.0.7680.177.5", Download.ParseManifestVersion(manifest));
    }

    [Fact]
    public void ParseManifestVersion_absent_returns_null()
    {
        Assert.Null(Download.ParseManifestVersion("abc  cloakbrowser-linux-x64.tar.gz\n"));
    }

    [Fact]
    public void OldChecksumParser_ignores_version_line()
    {
        // Regression: the version line must not pollute the hash map, and a short
        // (non-64-hex) hash like "abc" must be rejected too.
        var h = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
        var manifest = $"version=146.0.7680.177.5\n{h}  cloakbrowser-linux-x64.tar.gz\n";
        var result = Download.ParseChecksums(manifest);
        Assert.Single(result);
        Assert.Equal(h, result["cloakbrowser-linux-x64.tar.gz"]);
    }

    // =======================================================================
    // Pro download verification - VerifyProDownloadAsync uses the SAME pinned
    // Ed25519 signature gate as the free path, but classifies failures:
    //   tampering (bad sig / wrong version / bad hash) -> BinaryVerificationError
    //   transient (manifest fetch failed)              -> InvalidOperationException
    // Port of JS js/tests/signature.test.ts Pro cases + Python TestVerifyProDownload.
    // =======================================================================

    private const string ProVersion = "148.0.7778.215.2";

    private static byte[] ProManifest(string body, string? version = null) =>
        Utf8($"version={version ?? ProVersion}\n{body}");

    private static void WithProOverrides(
        string[]? pubkeys, Func<string, (byte[], byte[])?>? manifest, Action body)
    {
        var prevKeys = Download.SigningPubkeysOverride;
        var prevManifest = Download.ProSignedManifestOverride;
        try
        {
            Download.SigningPubkeysOverride = pubkeys;
            Download.ProSignedManifestOverride = manifest;
            body();
        }
        finally
        {
            Download.SigningPubkeysOverride = prevKeys;
            Download.ProSignedManifestOverride = prevManifest;
        }
    }

    [Fact]
    public void Pro_validManifestAndHash_passes()
    {
        var (priv, pub) = MakeKey();
        var binary = Utf8("the real pro binary");
        var archive = WriteTemp(binary);
        var manifest = ProManifest($"{Sha256Hex(binary)}  {Tarball()}\n");
        var sig = Sign(priv, manifest);
        try
        {
            WithProOverrides(new[] { pub }, _ => (manifest, sig), () =>
                Download.VerifyProDownloadAsync(archive, ProVersion, default).GetAwaiter().GetResult());
        }
        finally { File.Delete(archive); }
    }

    [Fact]
    public void Pro_tamperedBinary_throws_verificationError()
    {
        var (priv, pub) = MakeKey();
        var archive = WriteTemp(Utf8("a malicious pro binary"));
        var manifest = ProManifest($"{Sha256Hex(Utf8("the real pro binary"))}  {Tarball()}\n");
        var sig = Sign(priv, manifest);
        try
        {
            WithProOverrides(new[] { pub }, _ => (manifest, sig), () =>
            {
                var ex = Assert.Throws<BinaryVerificationError>(() =>
                    Download.VerifyProDownloadAsync(archive, ProVersion, default).GetAwaiter().GetResult());
                Assert.Contains("Checksum verification failed", ex.Message);
            });
        }
        finally { File.Delete(archive); }
    }

    [Fact]
    public void Pro_badSignature_throws_verificationError()
    {
        var (priv, _) = MakeKey();
        var (_, otherPub) = MakeKey();
        var binary = Utf8("pro binary");
        var archive = WriteTemp(binary);
        var manifest = ProManifest($"{Sha256Hex(binary)}  {Tarball()}\n");
        var sig = Sign(priv, manifest);
        try
        {
            WithProOverrides(new[] { otherPub }, _ => (manifest, sig), () =>
            {
                var ex = Assert.Throws<BinaryVerificationError>(() =>
                    Download.VerifyProDownloadAsync(archive, ProVersion, default).GetAwaiter().GetResult());
                Assert.Contains("signature verification failed", ex.Message);
            });
        }
        finally { File.Delete(archive); }
    }

    [Fact]
    public void Pro_wrongVersion_throws_verificationError_downgrade()
    {
        var (priv, pub) = MakeKey();
        var binary = Utf8("pro binary");
        var archive = WriteTemp(binary);
        // Manifest declares an older version than the one requested.
        var manifest = ProManifest($"{Sha256Hex(binary)}  {Tarball()}\n", version: "1.0.0.0");
        var sig = Sign(priv, manifest);
        try
        {
            WithProOverrides(new[] { pub }, _ => (manifest, sig), () =>
            {
                var ex = Assert.Throws<BinaryVerificationError>(() =>
                    Download.VerifyProDownloadAsync(archive, ProVersion, default).GetAwaiter().GetResult());
                Assert.Contains("Version mismatch", ex.Message);
            });
        }
        finally { File.Delete(archive); }
    }

    [Fact]
    public void Pro_missingEntry_throws_verificationError()
    {
        var (priv, pub) = MakeKey();
        var archive = WriteTemp(Utf8("x"));
        var manifest = ProManifest($"{new string('d', 64)}  some-other-file.tar.gz\n");
        var sig = Sign(priv, manifest);
        try
        {
            WithProOverrides(new[] { pub }, _ => (manifest, sig), () =>
            {
                var ex = Assert.Throws<BinaryVerificationError>(() =>
                    Download.VerifyProDownloadAsync(archive, ProVersion, default).GetAwaiter().GetResult());
                Assert.Contains("no entry for", ex.Message);
            });
        }
        finally { File.Delete(archive); }
    }

    [Fact]
    public void Pro_manifestFetchFails_is_transient_not_tampering()
    {
        // A failed manifest fetch (null) is transient -> plain InvalidOperationException,
        // NOT a BinaryVerificationError, so the router can surface "unavailable, retry".
        var archive = WriteTemp(Utf8("x"));
        try
        {
            WithProOverrides(null, _ => null, () =>
            {
                var ex = Assert.Throws<InvalidOperationException>(() =>
                    Download.VerifyProDownloadAsync(archive, ProVersion, default).GetAwaiter().GetResult());
                Assert.IsNotType<BinaryVerificationError>(ex);
                Assert.Contains("Could not fetch", ex.Message);
            });
        }
        finally { File.Delete(archive); }
    }
}
