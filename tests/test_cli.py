"""Tests for the agent-friendly CLI subcommands."""

import json
import subprocess
import sys
from pathlib import Path


def run_cli(*args: str) -> subprocess.CompletedProcess:
    """Run cloakbrowser CLI and return completed process."""
    return subprocess.run(
        [sys.executable, "-m", "cloakbrowser", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestDoctor:
    def test_doctor_json(self):
        result = run_cli("doctor", "--json")
        data = json.loads(result.stdout)
        assert isinstance(data, dict)
        assert "ready" in data
        assert "version" in data
        assert "platform" in data
        assert "binary_path" in data
        assert "installed" in data
        assert "cache_dir" in data

    def test_doctor_text(self):
        result = run_cli("doctor")
        assert result.returncode == 0
        assert "ready" in result.stdout.lower() or "true" in result.stdout.lower()


class TestProfile:
    def test_profile_list_json(self):
        result = run_cli("profile", "list", "--json")
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_profile_list_text(self):
        result = run_cli("profile", "list")
        assert result.returncode == 0

    def test_profile_path_json(self, tmp_path):
        profile_dir = tmp_path / "test-profile"
        profile_dir.mkdir()
        result = run_cli("profile", "path", "test-profile", "--json", "--dir", str(tmp_path))
        data = json.loads(result.stdout)
        assert data["name"] == "test-profile"
        assert data["exists"] is True

    def test_profile_path_nonexistent(self, tmp_path):
        result = run_cli("profile", "path", "nonexistent", "--json", "--dir", str(tmp_path))
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert data["exists"] is False


class TestDumpJS:
    """Test the dump JavaScript function independently (no browser needed)."""

    def test_dump_js_imports(self):
        """Verify the dump JS is valid and doesn't throw on load."""
        from cloakbrowser.cli.dump import _DUMP_JS
        assert "mode" in _DUMP_JS
        assert "inputs" in _DUMP_JS
        assert "buttons" in _DUMP_JS
        assert "text" in _DUMP_JS
        assert "links" in _DUMP_JS


class TestHelp:
    def test_help_shows_new_commands(self):
        result = run_cli("--help")
        assert "doctor" in result.stdout
        assert "profile" in result.stdout
        assert "screenshot" in result.stdout
        assert "dump" in result.stdout
        assert "eval" in result.stdout
        assert "open" in result.stdout

    def test_doctor_help(self):
        result = run_cli("doctor", "--help")
        assert "--json" in result.stdout

    def test_dump_help(self):
        result = run_cli("dump", "--help")
        assert "inputs" in result.stdout
        assert "buttons" in result.stdout
        assert "text" in result.stdout
