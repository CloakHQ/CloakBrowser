"""The isolated-world resolver JS is hand-copied into three wrappers.

``cloakbrowser/human/stealth_dom.py``, ``js/src/human/stealthDom.ts`` and
``dotnet/src/CloakBrowser/Human/StealthDom.cs`` each embed the same resolver as a
string literal. Nothing generates them, so they can silently drift: a fix landed in
one wrapper and forgotten in another means that wrapper resolves a *different*
element and clicks the wrong coordinates, with no test failing.

These tests assert the three literals stay byte-identical, and that the shared JS
never grows a character that would terminate or corrupt one of the three host
literals (a backtick or ``${`` breaks the TS ``String.raw``; ``\"\"\"`` breaks the
Python and C# raw strings).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

PY_SRC = ROOT / "cloakbrowser" / "human" / "stealth_dom.py"
TS_SRC = ROOT / "js" / "src" / "human" / "stealthDom.ts"
CS_SRC = ROOT / "dotnet" / "src" / "CloakBrowser" / "Human" / "StealthDom.cs"

_TRIPLE = '"' * 3


def _extract(path: Path, pattern: str) -> str:
    m = re.search(pattern, path.read_text(encoding="utf-8"), re.S)
    assert m, f"could not find the resolver literal in {path}"
    return m.group(1)


def _resolvers() -> dict[str, str]:
    return {
        "python": _extract(PY_SRC, r'_RESOLVER_BODY = r"""(.*?)"""'),
        "typescript": _extract(TS_SRC, r"RESOLVER_BODY\s*=\s*String\.raw`(.*?)`"),
        "dotnet": _extract(CS_SRC, r'ResolverBody = """(.*?)"""'),
    }


def test_resolver_bodies_are_byte_identical():
    bodies = _resolvers()
    py = bodies["python"]
    for name, body in bodies.items():
        if body != py:
            # Surface the first differing line rather than dumping 17k chars.
            for i, (a, b) in enumerate(zip(py.splitlines(), body.splitlines()), 1):
                if a != b:
                    pytest.fail(
                        f"{name} resolver diverges from python at line {i}:\n"
                        f"  python: {a!r}\n  {name}: {b!r}"
                    )
            pytest.fail(
                f"{name} resolver differs from python in length only "
                f"({len(body)} vs {len(py)} chars)"
            )


@pytest.mark.parametrize("name", ["python", "typescript", "dotnet"])
def test_resolver_has_no_host_literal_hazards(name):
    body = _resolvers()[name]
    assert "`" not in body, "a backtick terminates the TypeScript String.raw literal"
    assert "${" not in body, "'${' interpolates inside the TypeScript String.raw literal"
    assert _TRIPLE not in body, "a triple quote terminates the Python and C# raw strings"
    assert "\r" not in body, "CR would make the three copies differ by line ending"
    for i, line in enumerate(body.splitlines(), 1):
        assert line == line.rstrip(), f"line {i} has trailing whitespace (invisible drift)"
