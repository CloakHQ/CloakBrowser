"""Tests for auto-update and version management."""

from __future__ import annotations

import base64
import hashlib
import os
from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from cloakbrowser.config import (
    _version_newer,
    _version_tuple,
    get_archive_name,
    get_effective_version,
    get_platform_tag,
)
from cloakbrowser.download import (
    BinaryVerificationError,
    _check_wrapper_update,
    _download_pro_binary,
    _ensure_pro_binary,
    _parse_checksums,
    _parse_manifest_version,
    _verify_checksum,
    _verify_pro_download,
    _verify_signature,
    check_for_pro_update,
    clear_cache,
    ensure_binary,
)


class TestVersionComparison:
    def test_version_tuple_parsing(self):
        assert _version_tuple("145.0.7718.0") == (145, 0, 7718, 0)
        assert _version_tuple("142.0.7444.175") == (142, 0, 7444, 175)

    def test_newer_version(self):
        assert _version_newer("145.0.7718.0", "142.0.7444.175") is True

    def test_older_version(self):
        assert _version_newer("142.0.7444.175", "145.0.7718.0") is False

    def test_same_version(self):
        assert _version_newer("142.0.7444.175", "142.0.7444.175") is False

    def test_patch_bump(self):
        assert _version_newer("142.0.7444.176", "142.0.7444.175") is True

    def test_major_bump(self):
        assert _version_newer("143.0.0.0", "142.9.9999.999") is True

    def test_5th_segment_parsing(self):
        assert _version_tuple("145.0.7632.109.2") == (145, 0, 7632, 109, 2)

    def test_build_bump(self):
        assert _version_newer("145.0.7632.109.3", "145.0.7632.109.2") is True

    def test_build_suffix_newer_than_no_suffix(self):
        assert _version_newer("145.0.7632.109.2", "145.0.7632.109") is True

    def test_no_suffix_older_than_build_suffix(self):
        assert _version_newer("145.0.7632.109", "145.0.7632.109.2") is False

    def test_new_chromium_beats_old_build(self):
        assert _version_newer("146.0.0.0", "145.0.7632.109.2") is True


class TestWrapperUpdateCheck:
    """Tests for _check_wrapper_update (PyPI version check)."""

    def setup_method(self):
        import cloakbrowser.download as dl

        dl._wrapper_update_checked = False

    def test_warns_when_newer_version_available(self, caplog):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"info": {"version": "99.0.0"}}
        mock_resp.raise_for_status = MagicMock()

        with patch("cloakbrowser.download.httpx.get", return_value=mock_resp):
            import logging

            with caplog.at_level(logging.WARNING):
                _check_wrapper_update()
            assert "Update available" in caplog.text
            assert "99.0.0" in caplog.text

    def test_silent_when_current(self, caplog):
        import cloakbrowser.download as dl

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"info": {"version": dl._wrapper_version}}
        mock_resp.raise_for_status = MagicMock()

        with patch("cloakbrowser.download.httpx.get", return_value=mock_resp):
            import logging

            with caplog.at_level(logging.WARNING):
                _check_wrapper_update()
            assert "Update available" not in caplog.text

    def test_disabled_by_auto_update_env(self):
        with patch.dict(os.environ, {"CLOAKBROWSER_AUTO_UPDATE": "false"}):
            with patch("cloakbrowser.download.httpx.get") as mock_get:
                _check_wrapper_update()
                mock_get.assert_not_called()

    def test_network_error_silent(self, caplog):
        with patch("cloakbrowser.download.httpx.get", side_effect=Exception("timeout")):
            import logging

            with caplog.at_level(logging.WARNING):
                _check_wrapper_update()
            assert "Update available" not in caplog.text

    def test_runs_only_once(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"info": {"version": "0.0.1"}}
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "cloakbrowser.download.httpx.get", return_value=mock_resp
        ) as mock_get:
            _check_wrapper_update()
            _check_wrapper_update()
            assert mock_get.call_count == 1


class TestParseChecksums:
    HASH_A = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    HASH_B = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"

    def test_standard_format(self):
        text = (
            f"{self.HASH_A}  cloakbrowser-linux-x64.tar.gz\n"
            f"{self.HASH_B}  cloakbrowser-darwin-arm64.tar.gz\n"
        )
        result = _parse_checksums(text)
        assert result["cloakbrowser-linux-x64.tar.gz"] == self.HASH_A
        assert result["cloakbrowser-darwin-arm64.tar.gz"] == self.HASH_B

    def test_binary_mode_asterisk(self):
        text = f"{self.HASH_A} *cloakbrowser-linux-x64.tar.gz\n"
        result = _parse_checksums(text)
        assert "cloakbrowser-linux-x64.tar.gz" in result

    def test_empty_lines_skipped(self):
        text = f"\n\n{self.HASH_A}  file.tar.gz\n\n"
        result = _parse_checksums(text)
        assert len(result) == 1

    def test_uppercase_lowered(self):
        text = f"{self.HASH_A.upper()}  file.tar.gz\n"
        result = _parse_checksums(text)
        assert result["file.tar.gz"] == self.HASH_A

    def test_empty_input(self):
        assert _parse_checksums("") == {}
        assert _parse_checksums("   \n  \n") == {}


class TestVerifyChecksum:
    def test_matching_checksum(self, tmp_path):
        content = b"test binary content"
        file = tmp_path / "test.tar.gz"
        file.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        # Should not raise
        _verify_checksum(file, expected)

    def test_mismatched_checksum(self, tmp_path):
        file = tmp_path / "test.tar.gz"
        file.write_bytes(b"real content")
        with pytest.raises(RuntimeError, match="Checksum verification failed"):
            _verify_checksum(file, "0" * 64)


class TestClearCache:
    def test_removes_dir(self, tmp_path):
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            # Create some content
            (tmp_path / "chromium-145").mkdir()
            (tmp_path / "chromium-145" / "chrome").write_bytes(b"binary")
            clear_cache()
            assert not tmp_path.exists()

    def test_noop_if_missing(self, tmp_path):
        nonexistent = tmp_path / "nonexistent"
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(nonexistent)}):
            clear_cache()  # Should not raise


class TestEnsureBinary:
    @patch("cloakbrowser.download._maybe_trigger_update_check")
    def test_local_override(self, _mock_update, tmp_path):
        binary = tmp_path / "chrome"
        binary.write_bytes(b"binary")
        with patch.dict(os.environ, {"CLOAKBROWSER_BINARY_PATH": str(binary)}):
            result = ensure_binary()
            assert result == str(binary)

    @patch("cloakbrowser.download._maybe_trigger_update_check")
    def test_local_override_missing_file(self, _mock_update):
        with patch.dict(
            os.environ, {"CLOAKBROWSER_BINARY_PATH": "/nonexistent/chrome"}
        ):
            with pytest.raises(FileNotFoundError, match="does not exist"):
                ensure_binary()

    def test_pinned_pro_version_skips_latest_marker(self, tmp_path):
        # A pinned Pro (rollback) download must NOT write latest_pro_version_*,
        # so an unpinned Pro launch still resolves to the latest build.
        requested = "148.0.7778.215.2"
        fake_binary = tmp_path / "Chromium"
        marker = tmp_path / f"latest_pro_version_{get_platform_tag()}"
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            with patch(
                "cloakbrowser.download.get_binary_path", return_value=fake_binary
            ):

                def fake_pro_download(version, key):
                    assert version == requested
                    fake_binary.write_bytes(b"binary")
                    fake_binary.chmod(0o755)

                with (
                    patch(
                        "cloakbrowser.download._download_pro_binary",
                        side_effect=fake_pro_download,
                    ),
                    patch(
                        "cloakbrowser.license.get_pro_latest_version"
                    ) as mock_latest,
                ):
                    result = _ensure_pro_binary(
                        "cb_key",
                        requested_version=requested,
                        release_channel="preview",
                    )
                    assert result == str(fake_binary)
                    mock_latest.assert_not_called()
                    assert not marker.exists()

    @patch("cloakbrowser.download._maybe_trigger_update_check")
    def test_env_pin_rejects_unsafe_version(self, _mock_update, tmp_path):
        with patch.dict(
            os.environ,
            {
                "CLOAKBROWSER_CACHE_DIR": str(tmp_path),
                "CLOAKBROWSER_BINARY_PATH": "",
                "CLOAKBROWSER_VERSION": "../../146.0.0.0",
            },
        ):
            with pytest.raises(ValueError, match="Invalid browser version pin"):
                ensure_binary()


def _make_pro_binary(version: str):
    """Create a fake cached, executable Pro binary for `version`."""
    from cloakbrowser.config import get_binary_path

    bp = get_binary_path(version)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_bytes(b"binary")
    bp.chmod(0o755)
    return bp


class TestUnpinnedProUpgrade:
    """An unpinned keyed launch must track the server's latest stable and never
    roll down to a stale cached build."""

    OLD = "148.0.7778.215.3"
    NEW = "148.0.7778.215.5"

    def test_upgrades_to_server_latest(self, tmp_path):
        marker = tmp_path / f"latest_pro_version_{get_platform_tag()}"
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            marker.write_text(self.OLD)
            _make_pro_binary(self.OLD)  # stale build cached

            def fake_download(version, key):
                assert version == self.NEW
                _make_pro_binary(self.NEW)

            with (
                patch(
                    "cloakbrowser.license.get_pro_latest_version",
                    return_value=self.NEW,
                ),
                patch(
                    "cloakbrowser.download._download_pro_binary",
                    side_effect=fake_download,
                ) as mock_dl,
            ):
                from cloakbrowser.config import get_binary_path

                result = _ensure_pro_binary("cb_key")
                mock_dl.assert_called_once()
                assert result == str(get_binary_path(self.NEW))
                assert marker.read_text() == self.NEW  # marker advanced, not stuck

    def test_preview_uses_server_version_and_preview_marker(self, tmp_path):
        stable_marker = tmp_path / f"latest_pro_version_{get_platform_tag()}"
        preview_marker = (
            tmp_path / f"latest_pro_version_preview_{get_platform_tag()}"
        )
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            stable_marker.write_text(self.OLD)
            _make_pro_binary(self.OLD)

            with (
                patch(
                    "cloakbrowser.license.get_pro_latest_version",
                    return_value=self.NEW,
                ) as mock_latest,
                patch(
                    "cloakbrowser.download._download_pro_binary",
                    side_effect=lambda version, key: _make_pro_binary(version),
                ) as mock_dl,
            ):
                from cloakbrowser.config import get_binary_path

                result = _ensure_pro_binary(
                    "cb_key", release_channel="preview"
                )
                expected_path = str(get_binary_path(self.NEW))

        mock_latest.assert_called_once_with("preview")
        mock_dl.assert_called_once_with(self.NEW, "cb_key")
        assert result == expected_path
        assert preview_marker.read_text() == self.NEW
        assert stable_marker.read_text() == self.OLD

    def test_preview_with_no_preview_build_warns_stable_fallback(self, tmp_path, capsys):
        """Preview requested but the server has no preview for this platform (fallback
        to stable) → print a one-line notice at launch."""
        import cloakbrowser.download as dl
        from cloakbrowser.license import ProReleaseInfo

        dl._preview_fallback_warned = False  # reset once-per-process guard
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            _make_pro_binary(self.NEW)  # stable-fallback build already cached → no download

            with (
                patch(
                    "cloakbrowser.license.get_pro_latest_version",
                    return_value=self.NEW,
                ),
                patch(
                    "cloakbrowser.license.get_pro_latest_release",
                    return_value=ProReleaseInfo(self.NEW, "preview", "stable", True),
                ),
                patch("cloakbrowser.download._download_pro_binary") as mock_dl,
            ):
                _ensure_pro_binary("cb_key", release_channel="preview")

        mock_dl.assert_not_called()
        assert "no preview build is available" in capsys.readouterr().err

    def test_genuine_preview_does_not_warn(self, tmp_path, capsys):
        """A real preview build (no fallback) prints no fallback notice."""
        import cloakbrowser.download as dl
        from cloakbrowser.license import ProReleaseInfo

        dl._preview_fallback_warned = False
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            _make_pro_binary(self.NEW)

            with (
                patch(
                    "cloakbrowser.license.get_pro_latest_version",
                    return_value=self.NEW,
                ),
                patch(
                    "cloakbrowser.license.get_pro_latest_release",
                    return_value=ProReleaseInfo(self.NEW, "preview", "preview", False),
                ),
                patch("cloakbrowser.download._download_pro_binary"),
            ):
                _ensure_pro_binary("cb_key", release_channel="preview")

        assert "no preview build is available" not in capsys.readouterr().err

    def test_cached_newer_build_advances_marker_no_download(self, tmp_path):
        """Marker names an OLD build but a NEWER build is already cached (the customer's
        multi-version cache): resolve to newest, no download, and advance the marker so
        `info` never diverges from what launches."""
        marker = tmp_path / f"latest_pro_version_{get_platform_tag()}"
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            marker.write_text(self.OLD)
            _make_pro_binary(self.OLD)
            _make_pro_binary(self.NEW)  # newer build already on disk

            with (
                patch(
                    "cloakbrowser.license.get_pro_latest_version",
                    return_value=self.NEW,
                ),
                patch("cloakbrowser.download._download_pro_binary") as mock_dl,
            ):
                from cloakbrowser.config import get_binary_path

                result = _ensure_pro_binary("cb_key")
                mock_dl.assert_not_called()  # already cached, no download
                assert result == str(get_binary_path(self.NEW))
                assert marker.read_text() == self.NEW  # marker advanced, no stale divergence

    def test_steady_state_no_download(self, tmp_path):
        marker = tmp_path / f"latest_pro_version_{get_platform_tag()}"
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            marker.write_text(self.NEW)
            _make_pro_binary(self.NEW)  # already on latest

            with (
                patch(
                    "cloakbrowser.license.get_pro_latest_version",
                    return_value=self.NEW,
                ),
                patch("cloakbrowser.download._download_pro_binary") as mock_dl,
            ):
                from cloakbrowser.config import get_binary_path

                result = _ensure_pro_binary("cb_key")
                mock_dl.assert_not_called()
                assert result == str(get_binary_path(self.NEW))

    def test_server_down_uses_cached_pro(self, tmp_path):
        """Server unreachable → launch the cached Pro build, never fail."""
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            (tmp_path / f"latest_pro_version_{get_platform_tag()}").write_text(self.OLD)
            _make_pro_binary(self.OLD)

            with (
                patch(
                    "cloakbrowser.license.get_pro_latest_version", return_value=None
                ),
                patch("cloakbrowser.download._download_pro_binary") as mock_dl,
            ):
                from cloakbrowser.config import get_binary_path

                result = _ensure_pro_binary("cb_key")
                mock_dl.assert_not_called()
                assert result == str(get_binary_path(self.OLD))

    def test_download_failure_falls_back_to_cached(self, tmp_path):
        """A failed upgrade download falls back to the cached Pro build."""
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            (tmp_path / f"latest_pro_version_{get_platform_tag()}").write_text(self.OLD)
            _make_pro_binary(self.OLD)

            with (
                patch(
                    "cloakbrowser.license.get_pro_latest_version",
                    return_value=self.NEW,
                ),
                patch(
                    "cloakbrowser.download._download_pro_binary",
                    side_effect=RuntimeError("network down"),
                ),
            ):
                from cloakbrowser.config import get_binary_path

                result = _ensure_pro_binary("cb_key")
                assert result == str(get_binary_path(self.OLD))

    def test_verification_error_surfaces_not_cached_fallback(self, tmp_path):
        """A tampering signal (BinaryVerificationError) must propagate verbatim, even
        with a cached Pro build present — never masked by the cached-fallback path."""
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            (tmp_path / f"latest_pro_version_{get_platform_tag()}").write_text(self.OLD)
            _make_pro_binary(self.OLD)

            with (
                patch(
                    "cloakbrowser.license.get_pro_latest_version",
                    return_value=self.NEW,
                ),
                patch(
                    "cloakbrowser.download._download_pro_binary",
                    side_effect=BinaryVerificationError("checksum mismatch"),
                ),
            ):
                with pytest.raises(BinaryVerificationError, match="checksum mismatch"):
                    _ensure_pro_binary("cb_key")

    def test_no_cache_no_server_raises(self, tmp_path):
        """No cached Pro build AND no server → hard error."""
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            with (
                patch(
                    "cloakbrowser.license.get_pro_latest_version", return_value=None
                ),
                patch("cloakbrowser.download._download_pro_binary") as mock_dl,
            ):
                with pytest.raises(RuntimeError, match="latest Pro version"):
                    _ensure_pro_binary("cb_key")
                mock_dl.assert_not_called()

    def test_auto_update_false_keeps_cached_no_server_check(self, tmp_path):
        """CLOAKBROWSER_AUTO_UPDATE=false + a cached Pro build → keep it, no upgrade,
        no server check."""
        with patch.dict(
            os.environ,
            {
                "CLOAKBROWSER_CACHE_DIR": str(tmp_path),
                "CLOAKBROWSER_AUTO_UPDATE": "false",
            },
        ):
            (tmp_path / f"latest_pro_version_{get_platform_tag()}").write_text(self.OLD)
            _make_pro_binary(self.OLD)

            with (
                patch(
                    "cloakbrowser.license.get_pro_latest_version",
                    return_value=self.NEW,
                ) as mock_latest,
                patch("cloakbrowser.download._download_pro_binary") as mock_dl,
            ):
                from cloakbrowser.config import get_binary_path

                result = _ensure_pro_binary("cb_key")
                mock_dl.assert_not_called()
                mock_latest.assert_not_called()  # frozen → no server check at all
                assert result == str(get_binary_path(self.OLD))

    def test_missing_cache_downloads_latest(self, tmp_path):
        """Marker names a build whose binary is gone → fetch latest Pro."""
        marker = tmp_path / f"latest_pro_version_{get_platform_tag()}"
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            marker.write_text(self.OLD)  # marker present, but NO binary on disk

            def fake_download(version, key):
                assert version == self.NEW
                _make_pro_binary(self.NEW)

            with (
                patch(
                    "cloakbrowser.license.get_pro_latest_version",
                    return_value=self.NEW,
                ),
                patch(
                    "cloakbrowser.download._download_pro_binary",
                    side_effect=fake_download,
                ),
            ):
                from cloakbrowser.config import get_binary_path

                result = _ensure_pro_binary("cb_key")
                assert result == str(get_binary_path(self.NEW))


class TestCheckForProUpdate:
    """`cloakbrowser update` for Pro installs."""

    OLD = "148.0.7778.215.3"
    NEW = "148.0.7778.215.5"

    def test_downloads_and_writes_marker(self, tmp_path):
        marker = tmp_path / f"latest_pro_version_{get_platform_tag()}"
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            marker.write_text(self.OLD)
            _make_pro_binary(self.OLD)

            with (
                patch(
                    "cloakbrowser.license.get_pro_latest_version",
                    return_value=self.NEW,
                ),
                patch(
                    "cloakbrowser.download._download_pro_binary",
                    side_effect=lambda v, k: _make_pro_binary(v),
                ) as mock_dl,
            ):
                result = check_for_pro_update("cb_key")
                mock_dl.assert_called_once()
                assert result == self.NEW
                assert marker.read_text() == self.NEW

    def test_already_latest_returns_none(self, tmp_path):
        marker = tmp_path / f"latest_pro_version_{get_platform_tag()}"
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            marker.write_text(self.NEW)
            _make_pro_binary(self.NEW)

            with (
                patch(
                    "cloakbrowser.license.get_pro_latest_version",
                    return_value=self.NEW,
                ),
                patch("cloakbrowser.download._download_pro_binary") as mock_dl,
            ):
                assert check_for_pro_update("cb_key") is None
                mock_dl.assert_not_called()

    def test_server_down_returns_none(self, tmp_path):
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            with patch(
                "cloakbrowser.license.get_pro_latest_version", return_value=None
            ):
                assert check_for_pro_update("cb_key") is None


class TestEffectiveVersion:
    """get_effective_version() returns None when no cached binary matches the marker."""

    def test_none_when_no_cached_binary(self, tmp_path):
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            # Marker points at a version whose binary is not on disk.
            (tmp_path / f"latest_pro_version_{get_platform_tag()}").write_text(
                "148.0.7778.215.5"
            )
            assert get_effective_version() is None

    def test_none_when_no_marker(self, tmp_path):
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            assert get_effective_version() is None

    def test_returns_cached_marker_version(self, tmp_path):
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            (tmp_path / f"latest_pro_version_{get_platform_tag()}").write_text(
                "148.0.7778.215.5"
            )
            _make_pro_binary("148.0.7778.215.5")
            assert get_effective_version() == "148.0.7778.215.5"


# ---------------------------------------------------------------------------
# Signed-manifest verification (Ed25519). Trust root is the pinned public key,
# not the same-origin SHA256SUMS — this is what closes M1 (#308).
# ---------------------------------------------------------------------------
def _make_key():
    priv = Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization

    raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return priv, base64.b64encode(raw).decode()


def _sign(priv, manifest_bytes: bytes) -> bytes:
    """Return SHA256SUMS.sig content (base64 of the raw signature), as served."""
    return base64.b64encode(priv.sign(manifest_bytes))


class TestSignatureVerification:
    """_verify_signature: the cryptographic gate over the raw manifest bytes."""

    def test_valid_signature_passes(self):
        priv, pub_b64 = _make_key()
        manifest = b"abc  cloakbrowser-linux-x64.tar.gz\n"
        sig = _sign(priv, manifest)
        with patch("cloakbrowser.download.BINARY_SIGNING_PUBKEYS", [pub_b64]):
            _verify_signature(manifest, sig)  # no raise

    def test_tampered_manifest_fails(self):
        priv, pub_b64 = _make_key()
        manifest = b"abc  cloakbrowser-linux-x64.tar.gz\n"
        sig = _sign(priv, manifest)
        tampered = manifest.replace(b"abc", b"xyz")
        with patch("cloakbrowser.download.BINARY_SIGNING_PUBKEYS", [pub_b64]):
            with pytest.raises(RuntimeError, match="signature verification failed"):
                _verify_signature(tampered, sig)

    def test_wrong_key_fails(self):
        priv, _ = _make_key()
        _, other_pub = _make_key()
        manifest = b"data\n"
        sig = _sign(priv, manifest)
        with patch("cloakbrowser.download.BINARY_SIGNING_PUBKEYS", [other_pub]):
            with pytest.raises(RuntimeError, match="signature verification failed"):
                _verify_signature(manifest, sig)

    def test_malformed_signature_fails(self):
        _, pub_b64 = _make_key()
        with patch("cloakbrowser.download.BINARY_SIGNING_PUBKEYS", [pub_b64]):
            with pytest.raises(RuntimeError, match="Malformed"):
                _verify_signature(b"data\n", b"!!!not base64!!!")

    def test_placeholder_key_is_skipped_not_crashing(self):
        """An unparseable pinned key (placeholder) must not abort — a real key still validates."""
        priv, pub_b64 = _make_key()
        manifest = b"data\n"
        sig = _sign(priv, manifest)
        with patch(
            "cloakbrowser.download.BINARY_SIGNING_PUBKEYS",
            ["REPLACE_WITH_REAL_ED25519_PUBLIC_KEY_BASE64", pub_b64],
        ):
            _verify_signature(manifest, sig)  # no raise

    def test_key_rotation_second_key_accepts(self):
        """A manifest signed with the new key validates while the old key stays pinned."""
        old_priv, old_pub = _make_key()
        new_priv, new_pub = _make_key()
        manifest = b"rotated\n"
        sig = _sign(new_priv, manifest)
        with patch("cloakbrowser.download.BINARY_SIGNING_PUBKEYS", [old_pub, new_pub]):
            _verify_signature(manifest, sig)  # no raise


class TestVerifyProDownloadSigned:
    """_verify_pro_download: downloads get a non-bypassable signature check
    (closes M1)."""

    PRO_VERSION = "147.0.1.0"

    def _hash(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _tarball(self) -> str:
        return get_archive_name()

    def _mock_fetch(self, manifest: bytes, sig: bytes):
        """httpx.get stub: returns the .sig for *.sig URLs, manifest otherwise."""

        def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.content = sig if url.endswith(".sig") else manifest
            return resp

        return mock_get

    def test_valid_pro_manifest_passes(self, tmp_path):
        priv, pub_b64 = _make_key()
        archive = tmp_path / "binary"
        archive.write_bytes(b"the real pro binary")
        manifest = (
            f"version={self.PRO_VERSION}\n"
            f"{self._hash(b'the real pro binary')}  {self._tarball()}\n"
        ).encode()
        sig = _sign(priv, manifest)
        with (
            patch("cloakbrowser.download.BINARY_SIGNING_PUBKEYS", [pub_b64]),
            patch(
                "cloakbrowser.download.httpx.get",
                side_effect=self._mock_fetch(manifest, sig),
            ),
        ):
            _verify_pro_download(archive, self.PRO_VERSION)  # no raise

    def test_skip_checksum_does_not_bypass(self, tmp_path):
        """CLOAKBROWSER_SKIP_CHECKSUM must NOT weaken Pro verification (the point)."""
        priv, pub_b64 = _make_key()
        archive = tmp_path / "binary"
        archive.write_bytes(b"a malicious pro binary")  # bytes differ from manifest
        manifest = (
            f"version={self.PRO_VERSION}\n"
            f"{self._hash(b'the real pro binary')}  {self._tarball()}\n"
        ).encode()
        sig = _sign(priv, manifest)
        with (
            patch.dict(os.environ, {"CLOAKBROWSER_SKIP_CHECKSUM": "true"}),
            patch("cloakbrowser.download.BINARY_SIGNING_PUBKEYS", [pub_b64]),
            patch(
                "cloakbrowser.download.httpx.get",
                side_effect=self._mock_fetch(manifest, sig),
            ),
        ):
            with pytest.raises(RuntimeError, match="Checksum verification failed"):
                _verify_pro_download(archive, self.PRO_VERSION)

    def test_missing_manifest_is_transient_not_tampering(self, tmp_path):
        """A failed manifest FETCH is transient (router falls back to a cached build), so it
        must be a plain RuntimeError — NOT a BinaryVerificationError, which the
        router re-raises as a hard failure."""
        archive = tmp_path / "binary"
        archive.write_bytes(b"x")
        with patch("cloakbrowser.download.httpx.get", side_effect=Exception("404")):
            with pytest.raises(RuntimeError) as ei:
                _verify_pro_download(archive, self.PRO_VERSION)
        assert not isinstance(ei.value, BinaryVerificationError)

    def test_wrong_version_fails_downgrade(self, tmp_path):
        """A genuinely-signed Pro manifest for a DIFFERENT version is rejected."""
        priv, pub_b64 = _make_key()
        archive = tmp_path / "binary"
        archive.write_bytes(b"the real pro binary")
        manifest = (
            f"version=1.0.0.0\n"  # declares old version, we ask for PRO_VERSION
            f"{self._hash(b'the real pro binary')}  {self._tarball()}\n"
        ).encode()
        sig = _sign(priv, manifest)
        with (
            patch("cloakbrowser.download.BINARY_SIGNING_PUBKEYS", [pub_b64]),
            patch(
                "cloakbrowser.download.httpx.get",
                side_effect=self._mock_fetch(manifest, sig),
            ),
        ):
            with pytest.raises(RuntimeError, match="Version mismatch"):
                _verify_pro_download(archive, self.PRO_VERSION)

    def test_tampered_manifest_fails_signature(self, tmp_path):
        """A manifest tampered after signing fails the signature gate (not the hash)."""
        priv, pub_b64 = _make_key()
        archive = tmp_path / "binary"
        archive.write_bytes(b"the real pro binary")
        manifest = (
            f"version={self.PRO_VERSION}\n"
            f"{self._hash(b'the real pro binary')}  {self._tarball()}\n"
        ).encode()
        sig = _sign(priv, manifest)
        tampered = manifest.replace(self._tarball().encode(), b"evil.tar.gz")
        with (
            patch("cloakbrowser.download.BINARY_SIGNING_PUBKEYS", [pub_b64]),
            patch(
                "cloakbrowser.download.httpx.get",
                side_effect=self._mock_fetch(tampered, sig),
            ),
        ):
            with pytest.raises(RuntimeError, match="signature verification failed"):
                _verify_pro_download(archive, self.PRO_VERSION)


class TestProDownloadVersionPinned:
    """The Pro download must request the explicit version, NOT /latest, so the
    served artifact matches the version-pinned signed manifest it's verified
    against (no latest-advances TOCTOU)."""

    def test_download_url_is_version_pinned(self):
        from cloakbrowser.config import DOWNLOAD_BASE_URL

        captured = {}

        def fake_download_file(url, dest, headers=None):
            captured["url"] = url

        with (
            patch(
                "cloakbrowser.download._download_file", side_effect=fake_download_file
            ),
            patch("cloakbrowser.download._verify_pro_download"),
            patch("cloakbrowser.download._extract_archive"),
        ):
            _download_pro_binary("147.0.1.0", "cb_key")

        assert captured["url"] == f"{DOWNLOAD_BASE_URL}/api/download/147.0.1.0"
        assert not captured["url"].endswith("/latest")


class TestVersionBinding:
    """The 'version=<v>' line: read by new wrappers, ignored by old parsers."""

    def test_parse_manifest_version(self):
        manifest = "version=146.0.7680.177.5\nabc  cloakbrowser-linux-x64.tar.gz\n"
        assert _parse_manifest_version(manifest) == "146.0.7680.177.5"

    def test_parse_manifest_version_absent(self):
        assert _parse_manifest_version("abc  cloakbrowser-linux-x64.tar.gz\n") is None

    def test_old_checksum_parser_ignores_version_line(self):
        """Regression: the version line must not pollute the old hash map."""
        h = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        manifest = f"version=146.0.7680.177.5\n{h}  cloakbrowser-linux-x64.tar.gz\n"
        result = _parse_checksums(manifest)
        assert result == {"cloakbrowser-linux-x64.tar.gz": h}


# ---------------------------------------------------------------------------
# Welcome-banner cadence: a free key re-shows daily, Pro shows once ever.
# ---------------------------------------------------------------------------
class TestWelcomeCadence:
    def test_pro_shows_once_then_never(self, tmp_path):
        import time as _time
        from cloakbrowser.download import _welcome_due

        marker = tmp_path / ".welcome_shown"
        assert _welcome_due(marker, pro=True) is True  # absent -> show
        marker.write_text(str(int(_time.time())))
        assert _welcome_due(marker, pro=True) is False  # exists -> never again

    def test_free_reshows_after_interval(self, tmp_path):
        import time as _time
        from cloakbrowser.download import _welcome_due, WELCOME_FREE_INTERVAL

        marker = tmp_path / ".welcome_shown"
        assert _welcome_due(marker, pro=False) is True  # absent -> show
        marker.write_text(str(int(_time.time())))
        assert _welcome_due(marker, pro=False) is False  # fresh -> skip
        marker.write_text(str(int(_time.time()) - WELCOME_FREE_INTERVAL - 10))
        assert _welcome_due(marker, pro=False) is True  # stale -> show again

    def test_legacy_empty_marker(self, tmp_path):
        from cloakbrowser.download import _welcome_due

        marker = tmp_path / ".welcome_shown"
        marker.write_text("")  # pre-cadence empty marker
        assert _welcome_due(marker, pro=False) is True  # unparseable -> free re-shows
        assert _welcome_due(marker, pro=True) is False  # pro: existence = already shown
