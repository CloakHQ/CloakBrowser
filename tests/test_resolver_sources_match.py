"""The isolated-world helper library (``__cloakH``) is hand-copied into three ports.

``cloakbrowser/human/world.py``, ``js/src/human/worldHelpers.ts`` and
``dotnet/src/CloakBrowser/Human/WorldHelpers.cs`` each embed the same JS as a
string literal. Nothing generates them, so they can silently drift; these tests
assert the copies stay byte-identical and never grow a character that would
terminate one of the host literals (a backtick or ``${`` breaks the TS
``String.raw``; a triple quote breaks the Python and C# raw strings).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_TRIPLE = '"' * 3


def _extract(path: Path, pattern: str) -> str:
    m = re.search(pattern, path.read_text(encoding="utf-8"), re.S)
    assert m, f"could not find the helper literal in {path}"
    return m.group(1)


def test_world_helpers_are_byte_identical():
    """The isolated-world helper library (``__cloakH``) is shared by the
    Python and JS humanize engines; the copies must not drift."""
    py = _extract(ROOT / "cloakbrowser" / "human" / "world.py", r'_HELPERS_JS = r"""(.*?)"""')
    ts = _extract(ROOT / "js" / "src" / "human" / "worldHelpers.ts", r"HELPERS_JS = String\.raw`(.*?)`;")
    assert ts == py, "js/src/human/worldHelpers.ts diverges from cloakbrowser/human/world.py"
    cs = _extract(ROOT / "dotnet" / "src" / "CloakBrowser" / "Human" / "WorldHelpers.cs",
                  r'public const string Js = """\n(.*?)\n""";')
    assert cs == py, "dotnet/src/CloakBrowser/Human/WorldHelpers.cs diverges from cloakbrowser/human/world.py"
    assert _TRIPLE not in py, "a triple quote terminates the C# raw string"
    assert "`" not in py and "${" not in py, "would break the TypeScript String.raw literal"
    assert "\r" not in py, "CR would make the three copies differ by line ending"
    for i, line in enumerate(py.splitlines(), 1):
        assert line == line.rstrip(), f"line {i} has trailing whitespace (invisible drift)"
