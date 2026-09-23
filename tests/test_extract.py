"""Unit tests for archive extraction — path traversal protection, flattening, permissions."""

import io
import os
import platform
import queue
import shutil
import stat
import tarfile
import threading
import zipfile

import pytest

import cloakbrowser.download as download
from cloakbrowser.config import get_binary_dir, get_binary_path
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


def _create_tar_gz(tmp_path, members: dict[str, bytes]) -> "Path":
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
        archive = _create_tar_gz(tmp_path, {"chrome": b"binary", "lib/libfoo.so": b"lib"})
        dest = tmp_path / "out"
        dest.mkdir()
        _extract_tar(archive, dest)
        assert (dest / "chrome").read_bytes() == b"binary"
        assert (dest / "lib" / "libfoo.so").read_bytes() == b"lib"

    def test_symlink_extracted(self, tmp_path):
        """Symlinks extract as-is — the archive is signature-verified before
        extraction, so no per-member sanitization is applied (macOS .app
        Framework layout depends on symlinks)."""
        archive = tmp_path / "symlink.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo(name="chrome")
            info.size = 6
            tar.addfile(info, io.BytesIO(b"binary"))
            sym = tarfile.TarInfo(name="chrome_link")
            sym.type = tarfile.SYMTYPE
            sym.linkname = "chrome"
            tar.addfile(sym)

        dest = tmp_path / "out"
        dest.mkdir()
        _extract_tar(archive, dest)
        assert (dest / "chrome").exists()
        assert (dest / "chrome_link").is_symlink()


# ---------------------------------------------------------------------------
# zip extraction
# ---------------------------------------------------------------------------


def _create_zip(tmp_path, members: dict[str, bytes]) -> "Path":
    """Create a zip with given {name: content} members."""
    archive = tmp_path / "test.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return archive


class TestExtractZip:
    def test_basic(self, tmp_path):
        archive = _create_zip(tmp_path, {"chrome.exe": b"binary", "lib/foo.dll": b"lib"})
        dest = tmp_path / "out"
        dest.mkdir()
        _extract_zip(archive, dest)
        assert (dest / "chrome.exe").read_bytes() == b"binary"
        assert (dest / "lib" / "foo.dll").read_bytes() == b"lib"


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
    @pytest.mark.skipif(platform.system() == "Windows", reason="chmod not applicable on Windows")
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


# ---------------------------------------------------------------------------
# Concurrent first-run downloads
# ---------------------------------------------------------------------------


class TestConcurrentFirstRun:
    CALLERS = 4
    FILLER_FILES = 300
    BINARY_BYTES = b"#!/bin/sh\necho fake-chrome\n"

    def _create_platform_archive(self, tmp_path):
        """An archive with this platform's binary layout plus enough filler
        files that an extraction spans many thread switches."""
        binary_rel_path = get_binary_path().relative_to(get_binary_dir()).as_posix()
        members = {binary_rel_path: self.BINARY_BYTES}
        for i in range(self.FILLER_FILES):
            members[f"lib/part-{i}.bin"] = bytes([i % 256]) * 16 * 1024
        archive = tmp_path / "platform.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for name, content in members.items():
                info = tarfile.TarInfo(name=name)
                info.size = len(content)
                info.mode = 0o755
                tar.addfile(info, io.BytesIO(content))
        return archive

    def _inspect_install(self) -> str:
        """Reads the install the way a launch would. Returns what is wrong
        with it, or "complete"."""
        try:
            binary_path = get_binary_path()
            if binary_path.read_bytes() != self.BINARY_BYTES:
                return "binary content differs"
            if not _is_executable(binary_path):
                return "binary not executable"
            filler_count = len(os.listdir(get_binary_dir() / "lib"))
            if filler_count != self.FILLER_FILES:
                return f"lib has {filler_count} files"
            return "complete"
        except OSError as err:
            return type(err).__name__

    def _use_local_mirror(self, cache_dir, monkeypatch):
        monkeypatch.setenv("CLOAKBROWSER_CACHE_DIR", str(cache_dir))
        monkeypatch.setenv("CLOAKBROWSER_DOWNLOAD_URL", "https://mirror.invalid")
        monkeypatch.setenv("CLOAKBROWSER_SKIP_CHECKSUM", "true")
        for name in ("CLOAKBROWSER_LICENSE_KEY", "CLOAKBROWSER_BINARY_PATH", "CLOAKBROWSER_VERSION"):
            monkeypatch.delenv(name, raising=False)

    @pytest.mark.skipif(platform.system() == "Windows", reason="POSIX exec semantics")
    def test_install_stays_complete_while_other_callers_finish(self, tmp_path, monkeypatch):
        archive = self._create_platform_archive(tmp_path)
        cache_dir = tmp_path / "cache"
        self._use_local_mirror(cache_dir, monkeypatch)

        # One caller downloads at once. The others have already seen an empty
        # cache but their downloads are held until the first has returned,
        # which is the state a batch of simultaneous cold launches ends up in.
        all_callers_downloading = threading.Barrier(self.CALLERS)
        release_held_downloads = threading.Event()

        def fake_download_file(url, dest, headers=None):
            if all_callers_downloading.wait() != 0:
                release_held_downloads.wait()
            shutil.copyfile(archive, dest)

        monkeypatch.setattr(download, "_download_file", fake_download_file)

        caller_outcomes: queue.Queue = queue.Queue()

        def run_caller():
            try:
                caller_outcomes.put(("returned", download.ensure_binary()))
            except Exception as err:
                caller_outcomes.put(("raised", repr(err)))

        callers = [threading.Thread(target=run_caller) for _ in range(self.CALLERS)]
        for caller in callers:
            caller.start()

        outcomes = [caller_outcomes.get(timeout=60)]
        assert outcomes[0] == ("returned", str(get_binary_path()))

        # The first caller would now exec its binary. Keep reading the install
        # while the held callers download and extract.
        release_held_downloads.set()
        observed_states = {self._inspect_install()}
        while any(caller.is_alive() for caller in callers):
            observed_states.add(self._inspect_install())
        observed_states.add(self._inspect_install())

        while not caller_outcomes.empty():
            outcomes.append(caller_outcomes.get())
        assert outcomes == [("returned", str(get_binary_path()))] * self.CALLERS
        assert observed_states == {"complete"}
        assert [p.name for p in cache_dir.iterdir() if not p.name.startswith(".")] == [
            get_binary_dir().name
        ]

    @pytest.mark.skipif(platform.system() == "Windows", reason="POSIX exec semantics")
    def test_replaces_partial_install_left_by_interrupted_extraction(self, tmp_path, monkeypatch):
        archive = self._create_platform_archive(tmp_path)
        self._use_local_mirror(tmp_path / "cache", monkeypatch)
        monkeypatch.setattr(
            download, "_download_file", lambda url, dest, headers=None: shutil.copyfile(archive, dest)
        )
        (get_binary_dir() / "lib").mkdir(parents=True)
        (get_binary_dir() / "lib" / "part-0.bin").write_bytes(b"truncated")

        assert download.ensure_binary() == str(get_binary_path())
        assert self._inspect_install() == "complete"
