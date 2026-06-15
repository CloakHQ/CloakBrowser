"""Tests for binary supply-chain hardening.

  * checksum verification fails CLOSED on missing/absent SHA256SUMS
  * _fetch_checksums skips non-checksum (HTML) bodies and falls through mirrors
  * _parse_checksums only accepts valid 64-hex digests
  * version-tag validation (is_safe_version_tag) blocks injection-shaped tags
"""

from unittest.mock import MagicMock, patch

import pytest

import cloakbrowser.download as download
from cloakbrowser.config import get_archive_name, is_safe_version_tag


class TestChecksumFailClosed:
    def test_raises_when_checksums_unavailable(self, tmp_path):
        f = tmp_path / "archive"
        f.write_bytes(b"unverified")
        with patch("cloakbrowser.download._fetch_checksums", return_value=None):
            with pytest.raises(RuntimeError, match="cannot be integrity-verified"):
                download._verify_download_checksum(f)

    def test_raises_when_no_entry_for_platform(self, tmp_path):
        f = tmp_path / "archive"
        f.write_bytes(b"unverified")
        with patch("cloakbrowser.download._fetch_checksums",
                   return_value={"some-other-file.tar.gz": "00" * 32}):
            with pytest.raises(RuntimeError, match="no entry for"):
                download._verify_download_checksum(f)

    def test_passes_when_entry_matches(self, tmp_path):
        import hashlib
        content = b"the real binary bytes"
        f = tmp_path / "archive"
        f.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        with patch("cloakbrowser.download._fetch_checksums",
                   return_value={get_archive_name(): digest}):
            download._verify_download_checksum(f)  # should not raise


class TestFetchChecksumsSkipsJunk:
    def test_html_body_is_skipped_in_favor_of_valid_mirror(self):
        valid = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  file.tar.gz\n"

        def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.text = ("<html><body>404 Not Found</body></html>"
                         if "cloakbrowser.dev" in url else valid)
            return resp

        with patch.dict("os.environ", {"CLOAKBROWSER_DOWNLOAD_URL": ""}):
            with patch("cloakbrowser.download.httpx.get", side_effect=mock_get):
                result = download._fetch_checksums()
        assert result == {"file.tar.gz": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}

    def test_parse_rejects_non_hex_lines(self):
        text = "notahash  evil.tar.gz\nGGGG  also-bad.tar.gz\n"
        assert download._parse_checksums(text) == {}


class TestVersionTagValidation:
    @pytest.mark.parametrize("v", ["146.0.7680.177.5", "145.0.0.0", "1", "1.2.3.4.5"])
    def test_valid_versions(self, v):
        assert is_safe_version_tag(v)

    @pytest.mark.parametrize("v", [
        "", "../../etc", "146.0; calc", "146'+x", "v1.2.3", "1.2.3-beta", "1.2/3",
    ])
    def test_invalid_versions(self, v):
        assert not is_safe_version_tag(v)

    def test_get_latest_skips_unsafe_tag(self):
        releases = [
            {"tag_name": "chromium-v9'; evil", "draft": False,
             "assets": [{"name": get_archive_name()}]},
        ]
        resp = MagicMock()
        resp.json.return_value = releases
        resp.raise_for_status = MagicMock()
        with patch("cloakbrowser.download.httpx.get", return_value=resp):
            assert download._get_latest_chromium_version() is None
