"""Playwright's own selector / actionability engine, run inside OUR isolated world.

Playwright ships its InjectedScript (selector engines for role, label, text,
test-id, ``>>`` chains, ``has`` / ``has-text`` filters, ``nth``, ``visible``,
plus ``checkElementStates`` / ``expectHitTarget`` / ``fill`` rules) as a string
literal inside the driver bundle.  Playwright installs it in the page's main
world or in its utility world -- both leave page-visible traces (capture
listeners named ``addHitTargetInterceptorListeners``, ``__playwright_*``
CustomEvents).

Here the very same source is evaluated in a CDP isolated world that only the
humanize layer uses, with the two constructor hooks that touch ``window``
(hit-target interceptors and global-listener-removal detection) disabled.
The page cannot observe the installation or any query made through it, and
the humanize layer gets exact Playwright selector semantics (#522) and strict
mode for free instead of re-implementing accessible-name computation.

The literal is extracted per installed Playwright version, so selector syntax
always matches the client that produced the selector string.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

_LITERAL_START = re.compile(r"""\bsource\d*\s*[=:]\s*(['"`])""")
_cache: dict[str, str] = {}

# Global name inside the isolated world. Isolated-world globals are invisible
# to page scripts, so the name only has to avoid our own collisions.
GLOBAL = "__cloakInjected"


def _driver_lib_dirs() -> list[Path]:
    import playwright

    root = Path(playwright.__file__).parent / "driver" / "package" / "lib"
    return [root] if root.is_dir() else []


def _read_literal(text: str, start: int) -> str:
    """Return the JS string literal starting at ``text[start]`` (quotes included)."""
    quote = text[start]
    i = start + 1
    while text[i] != quote:
        i += 2 if text[i] == "\\" else 1
    return text[start:i + 1]


def find_injected_literal(lib_dirs: Optional[list[Path]] = None) -> str:
    """Locate the InjectedScript source literal in a Playwright driver.

    Supports the bundled layout (``coreBundle.js``, Playwright >= 1.55) and the
    older per-file layout (``generated/injectedScriptSource.js``).
    """
    dirs = lib_dirs if lib_dirs is not None else _driver_lib_dirs()
    key = "|".join(str(d) for d in dirs)
    if key in _cache:
        return _cache[key]
    for d in dirs:
        bundle = d / "coreBundle.js"
        if bundle.is_file():
            text = bundle.read_text("utf-8")
            pos = text.find("generated/injectedScriptSource.ts")
            if pos >= 0:
                m = _LITERAL_START.search(text, pos)
                if m:
                    _cache[key] = _read_literal(text, m.start(1))
                    return _cache[key]
        for f in sorted(d.rglob("injectedScriptSource.js")):
            text = f.read_text("utf-8")
            m = _LITERAL_START.search(text)
            if m:
                _cache[key] = _read_literal(text, m.start(1))
                return _cache[key]
    raise RuntimeError(
        "cloakbrowser humanize: Playwright's InjectedScript source was not found in "
        f"{[str(d) for d in dirs]}; the installed Playwright layout is not supported"
    )


def build_install_js(source: str, sdk_language: str = "python",
                     test_id_attribute: str = "data-testid") -> str:
    """Expression that installs the engine in the current (isolated) world.

    ``source`` is the *decoded* InjectedScript module text.  Idempotent: a
    second evaluation in the same world is a no-op.  Works with both the
    options-object constructor (>= 1.47) and the older positional one.
    """
    opts = json.dumps({
        "isUnderTest": False,
        "sdkLanguage": sdk_language,
        "testIdAttributeName": test_id_attribute,
        "stableRafCount": 1,
        "browserName": "chromium",
        "isUtilityWorld": True,
        "customEngines": [],
    })
    return (
        "(() => {\n"
        f"if (globalThis.{GLOBAL}) return true;\n"
        "const module = { exports: {} }; const exports = module.exports;\n"
        f"{source}\n"
        ";const exp = module.exports.InjectedScript;\n"
        "const C = (exp && exp.prototype && exp.prototype.querySelectorAll) ? exp : exp();\n"
        # Both hooks register listeners / dispatch events on the shared window.
        "C.prototype._setupGlobalListenersRemovalDetection = function () {};\n"
        "C.prototype._setupHitTargetInterceptors = function () {};\n"
        f"const o = {opts};\n"
        "const inj = C.length > 2\n"
        "  ? new C(globalThis, o.isUnderTest, o.sdkLanguage, o.testIdAttributeName,"
        " o.stableRafCount, o.browserName, o.customEngines)\n"
        "  : new C(globalThis, o);\n"
        f"Object.defineProperty(globalThis, {json.dumps(GLOBAL)}, {{ value: inj }});\n"
        "return true; })()"
    )
