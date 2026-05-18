from cloakbrowser.text_utils import (
    normalize_whitespace,
    shorten_label,
    truncate_middle,
)


def test_shorten_label_applies_shorthand_replacements() -> None:
    assert shorten_label("Google Chrome Headless") == "Chrome Headless"
    assert shorten_label("Mozilla Firefox on Windows 11") == "Firefox on Win11"


def test_shorten_label_truncates_when_too_long() -> None:
    text = "This is a very long label that should definitely be truncated"
    result = shorten_label(text, max_length=20)
    assert len(result) == 20
    assert result.endswith("...")


def test_shorten_label_handles_empty_input() -> None:
    assert shorten_label("") == ""


def test_normalize_whitespace() -> None:
    assert normalize_whitespace("  hello   world  ") == "hello world"
    assert normalize_whitespace("a\n\tb\t c") == "a b c"


def test_truncate_middle() -> None:
    text = "/very/long/path/to/some/file.txt"
    result = truncate_middle(text, max_length=20)
    assert len(result) <= 20
    assert "..." in result
    assert result.startswith("/very")
    assert result.endswith(".txt")


def test_truncate_middle_no_change_when_short() -> None:
    text = "short.txt"
    assert truncate_middle(text, max_length=20) == text
