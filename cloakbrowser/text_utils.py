"""Text utilities for CloakBrowser.

Provides helpers for shortening long labels, normalizing text,
and preventing text overlap in UI/logging contexts.
"""

from typing import Dict, Optional


DEFAULT_SHORTHAND_MAP: Dict[str, str] = {
    # Common browser/platform names
    "Google Chrome": "Chrome",
    "Mozilla Firefox": "Firefox",
    "Microsoft Edge": "Edge",
    "Apple Safari": "Safari",
    # Common OS names
    "Windows 11": "Win11",
    "Windows 10": "Win10",
    "macOS Sonoma": "macOS 14",
    "macOS Ventura": "macOS 13",
    # Common long identifiers
    "Chromium": "Chrome",
}


def shorten_label(
    text: str,
    max_length: int = 40,
    shorthand_map: Optional[Dict[str, str]] = None,
    ellipsis: str = "...",
) -> str:
    """Shorten a label to prevent text overlap.

    Args:
        text: Input text to shorten
        max_length: Maximum length (default 40)
        shorthand_map: Custom shorthand replacements (default uses DEFAULT_SHORTHAND_MAP)
        ellipsis: String to append when truncating (default "...")

    Returns:
        Shortened text

    Examples:
        >>> shorten_label("Google Chrome Headless")
        'Chrome Headless'
        >>> shorten_label("Very Long Browser Name That Exceeds Limit", max_length=20)
        'Very Long Browser ...'
    """
    if not text:
        return text

    # Apply shorthand replacements
    mapping = shorthand_map if shorthand_map is not None else DEFAULT_SHORTHAND_MAP
    for long_form, short_form in mapping.items():
        if long_form in text:
            text = text.replace(long_form, short_form)

    # Truncate if still too long
    if len(text) > max_length:
        text = text[: max_length - len(ellipsis)] + ellipsis

    return text


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace in text (collapse multiple spaces, strip).

    Args:
        text: Input text

    Returns:
        Normalized text

    Examples:
        >>> normalize_whitespace("  hello   world  ")
        'hello world'
    """
    return " ".join(text.split())


def truncate_middle(text: str, max_length: int = 50, separator: str = "...") -> str:
    """Truncate text in the middle, preserving start and end.

    Useful for long paths or identifiers where both ends are important.

    Args:
        text: Input text
        max_length: Maximum length
        separator: String to insert in the middle (default "...")

    Returns:
        Truncated text

    Examples:
        >>> truncate_middle("/very/long/path/to/some/file.txt", max_length=30)
        '/very/long/.../file.txt'
    """
    if len(text) <= max_length:
        return text

    # Calculate how much to keep on each side
    side_length = (max_length - len(separator)) // 2
    left_length = side_length + (max_length - len(separator)) % 2  # Give extra char to left

    return text[:left_length] + separator + text[-side_length:]
