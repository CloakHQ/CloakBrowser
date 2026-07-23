"""Unit tests for launch_context() — context kwargs, viewport defaults, close cleanup."""

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from cloakbrowser.config import DEFAULT_VIEWPORT


# All tests mock launch() to avoid needing a binary.
# launch_context() calls launch() internally, then browser.new_context().


def _make_mock_browser():
    """Create a mock browser with new_context() returning a mock context."""
    browser = MagicMock()
    context = MagicMock()
    browser.new_context.return_value = context
    return browser, context


@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch")
def test_default_viewport(mock_launch, _mock_bin):
    """DEFAULT_VIEWPORT applied when no viewport given."""
    browser, context = _make_mock_browser()
    mock_launch.return_value = browser

    from cloakbrowser.browser import launch_context
    launch_context()

    ctx_kwargs = browser.new_context.call_args
    assert ctx_kwargs[1]["viewport"] == DEFAULT_VIEWPORT


@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch")
def test_headed_no_viewport(mock_launch, _mock_bin):
    """Headed (headless=False): no emulated viewport — no_viewport=True so the page
    tracks the real window (CDP viewport emulation would force outerWidth < innerWidth)."""
    browser, context = _make_mock_browser()
    mock_launch.return_value = browser

    from cloakbrowser.browser import launch_context
    launch_context(headless=False)

    ctx_kwargs = browser.new_context.call_args[1]
    assert ctx_kwargs.get("no_viewport") is True
    assert "viewport" not in ctx_kwargs


def test_default_no_viewport_helper():
    """_default_no_viewport defaults new_page()/new_context() to no_viewport=True,
    but never overrides an explicit viewport (Playwright rejects passing both)."""
    from cloakbrowser.browser import _default_no_viewport

    browser = MagicMock()
    orig_new_page = browser.new_page
    orig_new_context = browser.new_context
    _default_no_viewport(browser)

    browser.new_page()
    orig_new_page.assert_called_once_with(no_viewport=True)
    browser.new_context()
    orig_new_context.assert_called_once_with(no_viewport=True)

    # Explicit viewport respected — no_viewport NOT injected.
    orig_new_page.reset_mock()
    browser.new_page(viewport={"width": 800, "height": 600})
    orig_new_page.assert_called_once_with(viewport={"width": 800, "height": 600})


@pytest.mark.asyncio
async def test_default_no_viewport_helper_async():
    """_default_no_viewport_async mirrors the sync helper for async new_page/new_context."""
    from cloakbrowser.browser import _default_no_viewport_async

    browser = MagicMock()
    browser.new_page = AsyncMock()
    browser.new_context = AsyncMock()
    orig_new_page = browser.new_page
    orig_new_context = browser.new_context
    _default_no_viewport_async(browser)

    await browser.new_page()
    orig_new_page.assert_awaited_once_with(no_viewport=True)
    await browser.new_context()
    orig_new_context.assert_awaited_once_with(no_viewport=True)

    # Explicit viewport respected — no_viewport NOT injected.
    orig_new_page.reset_mock()
    await browser.new_page(viewport={"width": 800, "height": 600})
    orig_new_page.assert_awaited_once_with(viewport={"width": 800, "height": 600})


@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch")
def test_conflicting_viewport_kwargs_deduped(mock_launch, _mock_bin):
    """If a caller forces no_viewport via **kwargs alongside viewport=, only one
    reaches Playwright (which rejects both). The explicit kwargs value wins."""
    browser, context = _make_mock_browser()
    mock_launch.return_value = browser

    from cloakbrowser.browser import launch_context
    launch_context(viewport={"width": 1280, "height": 800}, no_viewport=True)

    ctx_kwargs = browser.new_context.call_args[1]
    assert ctx_kwargs.get("no_viewport") is True
    assert "viewport" not in ctx_kwargs


@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch")
def test_custom_viewport(mock_launch, _mock_bin):
    """Custom viewport overrides DEFAULT_VIEWPORT."""
    browser, context = _make_mock_browser()
    mock_launch.return_value = browser

    from cloakbrowser.browser import launch_context
    custom = {"width": 1280, "height": 720}
    launch_context(viewport=custom)

    ctx_kwargs = browser.new_context.call_args
    assert ctx_kwargs[1]["viewport"] == custom


@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch")
def test_default_does_not_suppress_maximize(mock_launch, _mock_bin):
    """No explicit viewport → let launch() auto-maximize (parity with JS/.NET)."""
    browser, _ = _make_mock_browser()
    mock_launch.return_value = browser

    from cloakbrowser.browser import launch_context
    launch_context()

    assert mock_launch.call_args.kwargs["_suppress_maximize"] is False


@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch")
def test_explicit_viewport_suppresses_maximize(mock_launch, _mock_bin):
    """Caller chose a viewport → suppress auto --start-maximized (parity with JS/.NET)."""
    browser, _ = _make_mock_browser()
    mock_launch.return_value = browser

    from cloakbrowser.browser import launch_context
    launch_context(viewport={"width": 800, "height": 600})

    assert mock_launch.call_args.kwargs["_suppress_maximize"] is True


@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch")
def test_no_viewport_kwarg_suppresses_maximize(mock_launch, _mock_bin):
    """Explicit no_viewport also counts as a chosen geometry → suppress."""
    browser, _ = _make_mock_browser()
    mock_launch.return_value = browser

    from cloakbrowser.browser import launch_context
    launch_context(no_viewport=True)

    assert mock_launch.call_args.kwargs["_suppress_maximize"] is True


@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch")
def test_user_agent(mock_launch, _mock_bin):
    """user_agent forwarded to new_context()."""
    browser, context = _make_mock_browser()
    mock_launch.return_value = browser

    from cloakbrowser.browser import launch_context
    launch_context(user_agent="Mozilla/5.0 Custom")

    ctx_kwargs = browser.new_context.call_args
    assert ctx_kwargs[1]["user_agent"] == "Mozilla/5.0 Custom"


@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch")
def test_locale_forwarded(mock_launch, _mock_bin):
    """locale flows to launch() for --lang binary flag, NOT to new_context() CDP."""
    browser, context = _make_mock_browser()
    mock_launch.return_value = browser

    from cloakbrowser.browser import launch_context
    launch_context(locale="de-DE")

    # Locale in launch() call (for --lang binary flag)
    assert mock_launch.call_args[1]["locale"] == "de-DE"
    # NOT in new_context() — would trigger detectable CDP emulation
    ctx_kwargs = browser.new_context.call_args
    assert "locale" not in ctx_kwargs[1]


@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch")
def test_timezone_via_binary_not_cdp(mock_launch, _mock_bin):
    """timezone passed to launch() for binary flag, NOT to new_context() CDP.

    --fingerprint-timezone is process-wide (reads CommandLine in renderer),
    so it applies to ALL contexts, not just the default one.
    """
    browser, context = _make_mock_browser()
    mock_launch.return_value = browser

    from cloakbrowser.browser import launch_context
    launch_context(timezone="America/New_York")

    # timezone in launch() — binary flag set
    assert mock_launch.call_args[1]["timezone"] == "America/New_York"
    # NOT in new_context() — no CDP emulation
    ctx_kwargs = browser.new_context.call_args
    assert "timezone_id" not in ctx_kwargs[1]


@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch")
def test_color_scheme(mock_launch, _mock_bin):
    """color_scheme forwarded to new_context()."""
    browser, context = _make_mock_browser()
    mock_launch.return_value = browser

    from cloakbrowser.browser import launch_context
    launch_context(color_scheme="dark")

    ctx_kwargs = browser.new_context.call_args
    assert ctx_kwargs[1]["color_scheme"] == "dark"


@patch("cloakbrowser.browser.maybe_resolve_geoip", return_value=("Europe/Berlin", "de-DE", "5.6.7.8"))
@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch")
def test_geoip_resolution(mock_launch, _mock_bin, _mock_geoip):
    """geoip fills timezone+locale, both flow to binary args only."""
    browser, context = _make_mock_browser()
    mock_launch.return_value = browser

    from cloakbrowser.browser import launch_context
    launch_context(proxy="http://proxy:8080", geoip=True)

    # Both go to launch() for binary flags
    assert mock_launch.call_args[1]["locale"] == "de-DE"
    assert mock_launch.call_args[1]["timezone"] == "Europe/Berlin"
    # Neither in context — no CDP emulation
    ctx_kwargs = browser.new_context.call_args
    assert "timezone_id" not in ctx_kwargs[1]
    assert "locale" not in ctx_kwargs[1]


@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch")
def test_timezone_id_alias(mock_launch, _mock_bin):
    """timezone_id kwarg accepted as alias for timezone."""
    browser, context = _make_mock_browser()
    mock_launch.return_value = browser

    from cloakbrowser.browser import launch_context
    launch_context(timezone_id="Europe/Paris")

    # Resolved value flows to launch() for binary flag
    assert mock_launch.call_args[1]["timezone"] == "Europe/Paris"
    # NOT in context — no CDP emulation
    ctx_kwargs = browser.new_context.call_args
    assert "timezone_id" not in ctx_kwargs[1]


@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch")
def test_close_closes_browser(mock_launch, _mock_bin):
    """context.close() also calls browser.close()."""
    browser, context = _make_mock_browser()
    # Save reference before launch_context() monkey-patches context.close
    original_ctx_close = context.close
    mock_launch.return_value = browser

    from cloakbrowser.browser import launch_context
    ctx = launch_context()

    # The returned context has a patched close()
    ctx.close()
    # Original context close was called
    original_ctx_close.assert_called_once()
    # Browser close was also called
    browser.close.assert_called_once()


@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch")
def test_error_closes_browser(mock_launch, _mock_bin):
    """If new_context() raises, browser is still closed."""
    browser = MagicMock()
    browser.new_context.side_effect = RuntimeError("context creation failed")
    mock_launch.return_value = browser

    from cloakbrowser.browser import launch_context
    with pytest.raises(RuntimeError, match="context creation failed"):
        launch_context()

    browser.close.assert_called_once()


@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch")
def test_kwargs_passthrough(mock_launch, _mock_bin):
    """Extra kwargs forwarded to new_context(), NOT to launch().

    Important contract: kwargs like record_video_dir go to context creation,
    not browser launch.
    """
    browser, context = _make_mock_browser()
    mock_launch.return_value = browser

    from cloakbrowser.browser import launch_context
    launch_context(record_video_dir="/tmp/videos")

    # Verify kwarg reached new_context()
    ctx_kwargs = browser.new_context.call_args
    assert ctx_kwargs[1]["record_video_dir"] == "/tmp/videos"

    # Verify kwarg did NOT leak to launch()
    launch_kwargs = mock_launch.call_args[1]
    assert "record_video_dir" not in launch_kwargs


# ---------------------------------------------------------------------------
# Async: launch_context_async()
# ---------------------------------------------------------------------------


def _make_mock_async_browser():
    """Create a mock async browser whose new_context() returns a mock context."""
    browser = AsyncMock()
    context = AsyncMock()
    browser.new_context.return_value = context
    return browser, context


@pytest.mark.asyncio
@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch_async")
async def test_async_storage_state_forwarded(mock_launch_async, _mock_bin):
    """storage_state kwarg forwarded to browser.new_context() in async path.

    This is the motivating use case from issue #141.
    """
    browser, context = _make_mock_async_browser()
    mock_launch_async.return_value = browser

    from cloakbrowser.browser import launch_context_async
    await launch_context_async(storage_state="state.json")

    ctx_kwargs = browser.new_context.call_args
    assert ctx_kwargs[1]["storage_state"] == "state.json"


@pytest.mark.asyncio
@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch_async")
async def test_async_default_viewport(mock_launch_async, _mock_bin):
    """DEFAULT_VIEWPORT applied when no viewport given (async)."""
    browser, context = _make_mock_async_browser()
    mock_launch_async.return_value = browser

    from cloakbrowser.browser import launch_context_async
    await launch_context_async()

    ctx_kwargs = browser.new_context.call_args
    assert ctx_kwargs[1]["viewport"] == DEFAULT_VIEWPORT


@pytest.mark.asyncio
@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch_async")
async def test_async_locale_flows_to_binary_not_cdp(mock_launch_async, _mock_bin):
    """locale flows to launch_async() for --lang flag, NOT to new_context() CDP."""
    browser, context = _make_mock_async_browser()
    mock_launch_async.return_value = browser

    from cloakbrowser.browser import launch_context_async
    await launch_context_async(locale="de-DE", timezone="Europe/Berlin")

    # Binary flags
    assert mock_launch_async.call_args[1]["locale"] == "de-DE"
    assert mock_launch_async.call_args[1]["timezone"] == "Europe/Berlin"
    # Not in context — would trigger detectable CDP emulation
    ctx_kwargs = browser.new_context.call_args
    assert "locale" not in ctx_kwargs[1]
    assert "timezone_id" not in ctx_kwargs[1]


@pytest.mark.asyncio
@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch_async")
async def test_async_close_closes_browser(mock_launch_async, _mock_bin):
    """await ctx.close() also closes the underlying browser."""
    browser, context = _make_mock_async_browser()
    original_ctx_close = context.close
    mock_launch_async.return_value = browser

    from cloakbrowser.browser import launch_context_async
    ctx = await launch_context_async()

    await ctx.close()
    original_ctx_close.assert_called_once()
    browser.close.assert_called_once()


@pytest.mark.asyncio
@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch_async")
async def test_async_error_closes_browser(mock_launch_async, _mock_bin):
    """If new_context() raises in async path, browser is still closed."""
    browser = AsyncMock()
    browser.new_context.side_effect = RuntimeError("context creation failed")
    mock_launch_async.return_value = browser

    from cloakbrowser.browser import launch_context_async
    with pytest.raises(RuntimeError, match="context creation failed"):
        await launch_context_async()

    browser.close.assert_called_once()


@pytest.mark.asyncio
@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch_async")
async def test_async_cancellation_closes_browser(mock_launch_async, _mock_bin):
    """asyncio.CancelledError during new_context() still closes browser.

    CancelledError derives from BaseException (not Exception) in Python 3.8+,
    so the cleanup must catch BaseException to prevent browser process leaks
    when the awaiting task is cancelled.
    """
    import asyncio

    browser = AsyncMock()
    browser.new_context.side_effect = asyncio.CancelledError()
    mock_launch_async.return_value = browser

    from cloakbrowser.browser import launch_context_async
    with pytest.raises(asyncio.CancelledError):
        await launch_context_async()

    browser.close.assert_called_once()


@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch")
def test_gpu_accel_forwarded_to_launch(mock_launch, _mock_bin):
    """launch_context(gpu_accel=True) propagates gpu_accel to launch()."""
    browser, _ = _make_mock_browser()
    mock_launch.return_value = browser

    from cloakbrowser.browser import launch_context
    launch_context(gpu_accel=True)

    assert mock_launch.call_args.kwargs.get("gpu_accel") is True
    assert "gpu_accel" not in browser.new_context.call_args.kwargs


@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch")
def test_gpu_accel_default_false(mock_launch, _mock_bin):
    """launch_context() without gpu_accel passes gpu_accel=False."""
    browser, _ = _make_mock_browser()
    mock_launch.return_value = browser

    from cloakbrowser.browser import launch_context
    launch_context()

    assert mock_launch.call_args.kwargs.get("gpu_accel") is False
    assert "gpu_accel" not in browser.new_context.call_args.kwargs


@pytest.mark.asyncio
@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch_async")
async def test_async_gpu_accel_forwarded_to_launch_async(mock_launch_async, _mock_bin):
    """launch_context_async(gpu_accel=True) propagates gpu_accel to launch_async()."""
    browser, _ = _make_mock_async_browser()
    mock_launch_async.return_value = browser

    from cloakbrowser.browser import launch_context_async
    await launch_context_async(gpu_accel=True)

    assert mock_launch_async.call_args.kwargs.get("gpu_accel") is True
    assert "gpu_accel" not in browser.new_context.call_args.kwargs


@pytest.mark.asyncio
@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.launch_async")
async def test_async_gpu_accel_default_false(mock_launch_async, _mock_bin):
    """launch_context_async() without gpu_accel passes gpu_accel=False."""
    browser, _ = _make_mock_async_browser()
    mock_launch_async.return_value = browser

    from cloakbrowser.browser import launch_context_async
    await launch_context_async()

    assert mock_launch_async.call_args.kwargs.get("gpu_accel") is False
    assert "gpu_accel" not in browser.new_context.call_args.kwargs
