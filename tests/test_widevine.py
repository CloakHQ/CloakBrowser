"""Unit tests for Widevine CDM hint-file seeding (cloakbrowser/widevine.py)."""

import json

import pytest

from cloakbrowser import widevine
from cloakbrowser.widevine import resolve_widevine_cdm_dir, seed_widevine_hint

_HINT = "WidevineCdm/latest-component-updated-widevine-cdm"


@pytest.fixture(autouse=True)
def _force_linux(monkeypatch):
    """Run as if on Linux unless a test overrides it (seeding is Linux-only)."""
    monkeypatch.setattr(widevine.platform, "system", lambda: "Linux")
    monkeypatch.delenv("CLOAKBROWSER_WIDEVINE", raising=False)
    monkeypatch.delenv("CLOAKBROWSER_WIDEVINE_CDM", raising=False)


def _make_cdm(dirpath):
    """Create a fake WidevineCdm dir with a manifest.json."""
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / "manifest.json").write_text('{"version": "4.10.3050.0"}')
    return dirpath


def _binary(tmp_path):
    """Return a fake chrome binary path inside its own dir."""
    bdir = tmp_path / "bin"
    bdir.mkdir(parents=True, exist_ok=True)
    return bdir / "chrome"


def test_seeds_hint_next_to_binary(tmp_path):
    """CDM in <binary dir>/WidevineCdm -> hint file written with abs Path."""
    binary = _binary(tmp_path)
    cdm = _make_cdm(binary.parent / "WidevineCdm")

    profile = tmp_path / "profile"
    seed_widevine_hint(profile, binary)

    hint = profile / _HINT
    assert hint.is_file()
    assert json.loads(hint.read_text())["Path"] == str(cdm.resolve())


def test_seeds_hint_from_env_var(tmp_path, monkeypatch):
    """CLOAKBROWSER_WIDEVINE_CDM takes priority and is used as the Path."""
    cdm = _make_cdm(tmp_path / "custom_cdm")
    monkeypatch.setenv("CLOAKBROWSER_WIDEVINE_CDM", str(cdm))

    profile = tmp_path / "profile"
    seed_widevine_hint(profile, _binary(tmp_path))

    assert json.loads((profile / _HINT).read_text())["Path"] == str(cdm.resolve())


def test_no_cdm_no_file(tmp_path):
    """No CDM present -> nothing written, no exception."""
    profile = tmp_path / "profile"
    seed_widevine_hint(profile, _binary(tmp_path))
    assert not (profile / _HINT).exists()


def test_kill_switch_disables(tmp_path, monkeypatch):
    """CLOAKBROWSER_WIDEVINE=0 disables seeding even when a CDM exists."""
    monkeypatch.setenv("CLOAKBROWSER_WIDEVINE_CDM", str(_make_cdm(tmp_path / "custom_cdm")))
    monkeypatch.setenv("CLOAKBROWSER_WIDEVINE", "0")

    profile = tmp_path / "profile"
    seed_widevine_hint(profile, _binary(tmp_path))
    assert not (profile / _HINT).exists()


def test_idempotent(tmp_path, monkeypatch):
    """Seeding twice leaves the same correct content and doesn't error."""
    cdm = _make_cdm(tmp_path / "custom_cdm")
    monkeypatch.setenv("CLOAKBROWSER_WIDEVINE_CDM", str(cdm))

    profile = tmp_path / "profile"
    binary = _binary(tmp_path)
    seed_widevine_hint(profile, binary)
    seed_widevine_hint(profile, binary)
    assert json.loads((profile / _HINT).read_text())["Path"] == str(cdm.resolve())


def test_noop_on_non_linux(tmp_path, monkeypatch):
    """On non-Linux, seeding is a no-op even with a CDM present."""
    monkeypatch.setattr(widevine.platform, "system", lambda: "Windows")
    monkeypatch.setenv("CLOAKBROWSER_WIDEVINE_CDM", str(_make_cdm(tmp_path / "cdm")))

    profile = tmp_path / "profile"
    seed_widevine_hint(profile, _binary(tmp_path))
    assert not (profile / _HINT).exists()


def test_resolve_requires_manifest(tmp_path, monkeypatch):
    """A WidevineCdm dir without manifest.json is not treated as a CDM."""
    bogus = tmp_path / "custom_cdm"
    bogus.mkdir()
    monkeypatch.setenv("CLOAKBROWSER_WIDEVINE_CDM", str(bogus))
    assert resolve_widevine_cdm_dir(_binary(tmp_path)) is None


def test_env_var_is_exclusive(tmp_path, monkeypatch):
    """An invalid CLOAKBROWSER_WIDEVINE_CDM skips seeding — no fallback to binary dir."""
    binary = _binary(tmp_path)
    _make_cdm(binary.parent / "WidevineCdm")  # valid CDM next to binary
    bogus = tmp_path / "bogus"
    bogus.mkdir()  # set but no manifest.json
    monkeypatch.setenv("CLOAKBROWSER_WIDEVINE_CDM", str(bogus))
    assert resolve_widevine_cdm_dir(binary) is None


def test_empty_env_var_is_exclusive(tmp_path, monkeypatch):
    """An empty (but set) CLOAKBROWSER_WIDEVINE_CDM is exclusive — no binary-dir fallback."""
    binary = _binary(tmp_path)
    _make_cdm(binary.parent / "WidevineCdm")  # valid CDM next to binary
    monkeypatch.setenv("CLOAKBROWSER_WIDEVINE_CDM", "")
    monkeypatch.chdir(tmp_path)  # so a stray ./manifest.json can't match
    assert resolve_widevine_cdm_dir(binary) is None


def test_empty_user_data_dir_skips(tmp_path, monkeypatch):
    """Empty user_data_dir (ephemeral profile) -> no CWD pollution, no seeding."""
    cdm = _make_cdm(tmp_path / "custom_cdm")
    monkeypatch.setenv("CLOAKBROWSER_WIDEVINE_CDM", str(cdm))
    monkeypatch.chdir(tmp_path)
    seed_widevine_hint("", _binary(tmp_path))
    assert not (tmp_path / "WidevineCdm").exists()


def test_never_raises_on_write_failure(tmp_path, monkeypatch):
    """A write failure (hint dir path is a file) must not raise — launch must not break."""
    cdm = _make_cdm(tmp_path / "custom_cdm")
    monkeypatch.setenv("CLOAKBROWSER_WIDEVINE_CDM", str(cdm))
    profile = tmp_path / "profile"
    profile.mkdir()
    # Block mkdir of <profile>/WidevineCdm by occupying that path with a file.
    (profile / "WidevineCdm").write_text("not a dir")

    seed_widevine_hint(profile, _binary(tmp_path))  # must not raise


def test_rewrites_corrupt_existing_hint(tmp_path, monkeypatch):
    """A non-UTF8 / mismatched existing hint is overwritten, without raising."""
    cdm = _make_cdm(tmp_path / "custom_cdm")
    monkeypatch.setenv("CLOAKBROWSER_WIDEVINE_CDM", str(cdm))
    profile = tmp_path / "profile"
    hint = profile / "WidevineCdm" / _HINT.split("/")[-1]
    hint.parent.mkdir(parents=True)
    hint.write_bytes(b"\xff\xfe not valid utf-8")

    seed_widevine_hint(profile, _binary(tmp_path))  # must not raise

    # corrupt content replaced with a valid hint pointing at the CDM
    assert json.loads(hint.read_text())["Path"] == str(cdm.resolve())
