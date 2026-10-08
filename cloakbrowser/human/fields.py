"""Field classification for humanized text input.

Mirrors Playwright's ``InjectedScript.fill`` rules (playwright-core 1.63) so
the humanize layer accepts and rejects the same targets Playwright does:

* text-like inputs are *typed into* key by key;
* value inputs (date, range, color, ...) get their value *set*, like
  Playwright, because a human does not type into a date picker either;
* everything else (checkbox, file, hidden, radio, ...) cannot be filled.

Mistypes are only simulated where a human plausibly makes and corrects them
and where the correction is safe: never in number/email/password/tel/url.
"""

from __future__ import annotations

from typing import Optional

# Playwright: kInputTypesToTypeInto
TYPE_INTO = frozenset({"", "email", "number", "password", "search", "tel", "text", "url"})
# Playwright: kInputTypesToSetValue
SET_VALUE = frozenset({"color", "date", "time", "datetime-local", "month", "range", "week"})
# Fields where a simulated typo is either unsafe (rejected chars, #573) or
# unrealistic (people type passwords, phones and addresses carefully).
NO_MISTYPE = frozenset({"number", "email", "password", "tel", "url"})

TYPE = "type"            # type key by key
SET = "set"              # set value directly
NOT_FILLABLE = "reject"  # raise like Playwright


class FieldKindError(RuntimeError):
    """Raised for targets Playwright refuses to fill."""


def classify(tag: str, input_type: Optional[str], editable_content: bool) -> str:
    """Return ``TYPE``, ``SET`` or ``NOT_FILLABLE`` for a fill target.

    ``tag`` is the lower-case tag name, ``input_type`` the lower-case
    ``input.type`` (``None`` for non-inputs), ``editable_content`` whether the
    element is contenteditable.
    """
    tag = (tag or "").lower()
    if tag == "input":
        t = (input_type or "").lower()
        if t in TYPE_INTO:
            return TYPE
        if t in SET_VALUE:
            return SET
        return NOT_FILLABLE
    if tag == "textarea" or editable_content:
        return TYPE
    return NOT_FILLABLE


def allows_mistype(tag: str, input_type: Optional[str]) -> bool:
    """Whether simulated typos are allowed for this field."""
    if (tag or "").lower() != "input":
        return True
    return (input_type or "").lower() not in NO_MISTYPE


def normalize_set_value(input_type: str, value: str) -> str:
    """Playwright's value normalization for ``SET_VALUE`` inputs."""
    value = value.strip()
    if (input_type or "").lower() == "color":
        value = value.lower()
    return value


def validate_number(value: str) -> str:
    """Playwright rejects non-numeric text for ``input[type=number]``."""
    v = value.strip()
    try:
        float(v)
    except ValueError:
        if v not in ("",):
            raise FieldKindError("Cannot type text into input[type=number]") from None
    return v


def not_fillable_message(tag: str, input_type: Optional[str]) -> str:
    if (tag or "").lower() == "input":
        return f'Input of type "{(input_type or "").lower()}" cannot be filled'
    return "Element is not an <input>, <textarea> or [contenteditable] element"


# ---------------------------------------------------------------------------
# Native date/time editors
# ---------------------------------------------------------------------------

import re as _re

_DT_PATTERNS = {
    "date": r"(?P<year>\d{4,6})-(?P<month>\d{2})-(?P<day>\d{2})",
    "month": r"(?P<year>\d{4,6})-(?P<month>\d{2})",
    "week": r"(?P<year>\d{4,6})-W(?P<week>\d{2})",
    "time": r"(?P<hour>\d{2}):(?P<minute>\d{2})(?::(?P<second>\d{2})(?:\.(?P<millisecond>\d{1,3}))?)?",
}
_DT_PATTERNS["datetime-local"] = _DT_PATTERNS["date"] + "T" + _DT_PATTERNS["time"]

# Digits after which Chromium's editor moves to the next segment by itself.
_FULL_WIDTH = {"month": 2, "day": 2, "week": 2, "hour": 2, "minute": 2, "second": 2, "millisecond": 3}


def datetime_parts(input_type: str, value: str) -> "dict | None":
    """Split an HTML date/time value into the keystrokes per editor segment.

    Returns ``None`` for a malformed value. ``hour`` is given in the 12-hour
    form the editor shows next to an AM/PM segment; ``hour24`` keeps the
    original hour. Callers that see no ``ampm`` segment use ``hour24``.
    """
    m = _re.fullmatch(_DT_PATTERNS.get(input_type, "$^"), value)
    if not m:
        return None
    g = {k: v for k, v in m.groupdict().items() if v is not None}
    parts: dict = dict(g)
    if "hour" in g:
        h = int(g["hour"])
        parts["hour24"] = h
        parts["hour12"] = f"{(h % 12) or 12:02d}"
        parts["hour"] = parts["hour12"]
    if "millisecond" in g:
        parts["millisecond"] = g["millisecond"].ljust(3, "0")
    return parts


def use_24h(parts: dict, has_ampm: bool) -> dict:
    """Pick the hour digits matching the editor (with or without AM/PM)."""
    if "hour24" in parts and not has_ampm:
        parts = dict(parts)
        parts["hour"] = f"{parts['hour24']:02d}"
    return parts


def segment_auto_advances(kind: str, parts: dict, input_type: str = "") -> bool:
    """Whether typing this segment's digits moves focus to the next segment.

    Two-digit segments advance after two digits. The year segment never
    does (it accepts up to six digits), so an ArrowRight follows it.
    """
    if input_type == "month" and kind == "month":
        return False  # shown as a month *name* ("January"): digits select it but do not advance
    width = _FULL_WIDTH.get(kind)
    return width is not None and len(parts.get(kind, "")) >= width
