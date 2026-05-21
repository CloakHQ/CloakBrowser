"""Unit tests for archive extraction — path traversal protection, flattening, permissions."""

import io
import platform
import tarfile
import zipfile
from pathlib import Path

import pytest

from cloakbrowser.download import (
    _extract_tar,
    _extract_zip,
    _flatten_single_subdir,
    _is_executable,
    _make_executable,
)


# ---------------------------------------------------------------------------
# tar.gz extraction
# ---------------------------------------------------------------------------


def _create_tar_gz(tmp_path, members: dict[str, bytes]) -> Path:
    """Create a tar.gz with given {name: content} members."""
    archive = tmp_path / "test.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, content in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return archive


class TestExtractTar:
    def test_basic(self, tmp_path):
        archive = _create_tar_gz(
            tmp_path, {"chrome": b"binary", "lib/libfoo.so": b"lib"}
        )
        dest = tmp_path / "out"
        dest.mkdir()
        _extract_tar(archive, dest)
        assert (dest / "chrome").read_bytes() == b"binary"
        assert (dest / "lib" / "libfoo.so").read_bytes() == b"lib"

    def test_path_traversal_blocked(self, tmp_path):
        archive = tmp_path / "evil.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo(name="../../../etc/passwd")
            info.size = 4
            tar.addfile(info, io.BytesIO(b"evil"))

        dest = tmp_path / "out"
        dest.mkdir()
        with pytest.raises(RuntimeError, match="path traversal"):
            _extract_tar(archive, dest)

    def test_sibling_prefix_traversal_blocked(self, tmp_path):
        """Containment should use path ancestry, not string prefixes."""
        archive = tmp_path / "evil.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo(name="../out_evil/owned.txt")
            content = b"evil"
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))

        dest = tmp_path / "out"
        dest.mkdir()
        with pytest.raises(RuntimeError, match="path traversal"):
            _extract_tar(archive, dest)
        assert not (tmp_path / "out_evil" / "owned.txt").exists()

    def test_symlink_entry_path_traversal_blocked(self, tmp_path):
        archive = tmp_path / "symlink-path.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            sym = tarfile.TarInfo(name="../out_evil/link")
            sym.type = tarfile.SYMTYPE
            sym.linkname = "chrome"
            tar.addfile(sym)

        dest = tmp_path / "out"
        dest.mkdir()
        with pytest.raises(RuntimeError, match="path traversal"):
            _extract_tar(archive, dest)
        assert not (tmp_path / "out_evil" / "link").exists()

    def test_suspicious_symlink_skipped(self, tmp_path):
        """Symlinks with absolute targets are skipped (logged as warning)."""
        archive = tmp_path / "symlink.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            # Normal file
            info = tarfile.TarInfo(name="chrome")
            info.size = 6
            tar.addfile(info, io.BytesIO(b"binary"))
            # Suspicious symlink
            sym = tarfile.TarInfo(name="evil_link")
            sym.type = tarfile.SYMTYPE
            sym.linkname = "/etc/passwd"
            tar.addfile(sym)

        dest = tmp_path / "out"
        dest.mkdir()
        _extract_tar(archive, dest)
        # Normal file extracted
        assert (dest / "chrome").exists()
        # Suspicious symlink was skipped
        assert not (dest / "evil_link").exists()


# ---------------------------------------------------------------------------
# zip extraction
# ---------------------------------------------------------------------------


def _create_zip(tmp_path, members: dict[str, bytes]) -> Path:
    """Create a zip with given {name: content} members."""
    archive = tmp_path / "test.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return archive


class TestExtractZip:
    def test_basic(self, tmp_path):
        archive = _create_zip(
            tmp_path, {"chrome.exe": b"binary", "lib/foo.dll": b"lib"}
        )
        dest = tmp_path / "out"
        dest.mkdir()
        _extract_zip(archive, dest)
        assert (dest / "chrome.exe").read_bytes() == b"binary"
        assert (dest / "lib" / "foo.dll").read_bytes() == b"lib"

    def test_path_traversal_blocked(self, tmp_path):
        archive = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../../../etc/passwd", "evil")

        dest = tmp_path / "out"
        dest.mkdir()
        with pytest.raises(RuntimeError, match="path traversal"):
            _extract_zip(archive, dest)

    def test_sibling_prefix_traversal_blocked(self, tmp_path):
        archive = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../out_evil/owned.txt", "evil")

        dest = tmp_path / "out"
        dest.mkdir()
        with pytest.raises(RuntimeError, match="path traversal"):
            _extract_zip(archive, dest)
        assert not (tmp_path / "out_evil" / "owned.txt").exists()


# ---------------------------------------------------------------------------
# Directory flattening
# ---------------------------------------------------------------------------


class TestFlatten:
    def test_single_subdir_flattened(self, tmp_path):
        """Single subdir contents moved up."""
        dest = tmp_path / "out"
        dest.mkdir()
        subdir = dest / "fingerprint-chromium-custom-v14"
        subdir.mkdir()
        (subdir / "chrome").write_bytes(b"binary")
        (subdir / "lib").mkdir()

        _flatten_single_subdir(dest)

        assert (dest / "chrome").read_bytes() == b"binary"
        assert (dest / "lib").is_dir()
        assert not subdir.exists()

    def test_app_bundle_preserved(self, tmp_path):
        """.app directory NOT flattened (macOS bundle)."""
        dest = tmp_path / "out"
        dest.mkdir()
        app = dest / "Chromium.app"
        app.mkdir()
        (app / "Contents").mkdir()
        (app / "Contents" / "MacOS").mkdir()
        (app / "Contents" / "MacOS" / "Chromium").write_bytes(b"binary")

        _flatten_single_subdir(dest)

        # .app bundle kept intact
        assert app.is_dir()
        assert (app / "Contents" / "MacOS" / "Chromium").exists()

    def test_noop_multiple_entries(self, tmp_path):
        """Multiple entries at top level — no flattening."""
        dest = tmp_path / "out"
        dest.mkdir()
        (dest / "chrome").write_bytes(b"binary")
        (dest / "lib").mkdir()

        _flatten_single_subdir(dest)

        # Nothing moved
        assert (dest / "chrome").exists()
        assert (dest / "lib").is_dir()


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


class TestPermissions:
    @pytest.mark.skipif(
        platform.system() == "Windows", reason="chmod not applicable on Windows"
    )
    def test_make_executable(self, tmp_path):
        binary = tmp_path / "chrome"
        binary.write_bytes(b"binary")
        binary.chmod(0o644)
        assert not _is_executable(binary)

        _make_executable(binary)
        assert _is_executable(binary)

    def test_is_executable_true(self, tmp_path):
        binary = tmp_path / "chrome"
        binary.write_bytes(b"binary")
        binary.chmod(0o755)
        assert _is_executable(binary)

    def test_is_executable_false(self, tmp_path):
        binary = tmp_path / "chrome"
        binary.write_bytes(b"binary")
        binary.chmod(0o644)
        assert not _is_executable(binary)
