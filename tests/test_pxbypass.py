"""Regression tests for issue #448 PerimeterX auto bypass."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cloakbrowser.pxbypass import PxConfig
from cloakbrowser.pxbypass.detect.base import DetectResult
from cloakbrowser.pxbypass.detect.keyword import DetectPxByKeyword
from cloakbrowser.pxbypass.engine import PxEngine
from cloakbrowser.pxbypass.site.ifood import IfoodHandler
from cloakbrowser.pxbypass.solve.base import BaseSolver, HoldTarget, SolveResult
from cloakbrowser.pxbypass.solve.composite import CompositeSolver
from cloakbrowser.pxbypass.solve.press_hold_button import SolveByHoldButton


class AsyncTextPage:
    """Small async Playwright-like page used by detector tests."""

    url = "https://www.ifood.com.br/restaurantes"
    frames: list = []
    main_frame = object()

    def __init__(self, body: str):
        self.body = body

    async def evaluate(self, script, arg=None):
        if "document.body" in script:
            return self.body
        if "querySelectorAll" in script:
            return 0
        return False


@pytest.mark.asyncio
async def test_keyword_detector_supports_async_playwright_page():
    detector = DetectPxByKeyword()
    result = await detector.detect_async(
        AsyncTextPage("Antes de continuarmos, pressione e segure")
    )
    assert result.detected is True
    assert result.confidence >= 0.5


@pytest.mark.asyncio
async def test_ifood_handler_supports_async_detection():
    result = await IfoodHandler().detect_async(
        AsyncTextPage("Pressione e segure para confirmar que você é humano")
    )
    assert result.detected is True


class _AsyncSuccessSolver(BaseSolver):
    def __init__(self, name: str, solved: bool):
        self.name = name
        self.solved = solved
        self.sync_called = False

    def solve(self, page, cfg, detect_result=None):
        self.sync_called = True
        raise AssertionError("async path must not call sync solve()")

    async def async_solve(self, page, cfg, detect_result=None):
        return SolveResult(solved=self.solved, method=self.name)


@pytest.mark.asyncio
async def test_composite_solver_awaits_async_child_solvers():
    first = _AsyncSuccessSolver("first", False)
    second = _AsyncSuccessSolver("second", True)
    result = await CompositeSolver([first, second]).async_solve(
        object(), PxConfig(), DetectResult(detected=True)
    )
    assert result.solved is True
    assert result.method == "second"
    assert first.sync_called is False
    assert second.sync_called is False


def test_sync_page_patch_installs_wait_for_px_solved_immediately(monkeypatch):
    from cloakbrowser import pxbypass

    page = MagicMock()
    page._px_patched = False
    page._px_methods_patched = False
    page.goto = MagicMock(return_value=None)
    engine = MagicMock()
    monkeypatch.setattr(pxbypass, "_get_engine", lambda cfg: engine)

    pxbypass.patch_page(page, PxConfig())

    assert callable(page.wait_for_px_solved)
    engine.install_observer.assert_called_once_with(page)


def test_wait_for_px_solved_does_not_accept_transient_visibility_gap(monkeypatch):
    from cloakbrowser.pxbypass.engine import _patch_methods_for_px_polling

    page = MagicMock()
    page._px_methods_patched = False
    engine = MagicMock()
    visibility = iter([True, False])
    engine._is_px_visible.side_effect = lambda page: next(visibility, False)
    engine.check_and_solve.return_value = True
    engine.detect.return_value = (
        None,
        DetectResult(detected=True, confidence=0.9),
    )
    _patch_methods_for_px_polling(page, engine)

    monkeypatch.setattr("time.sleep", lambda delay: None)
    assert page.wait_for_px_solved(timeout=0.01) is False


class _ObserverPage:
    def __init__(self):
        self.binding = None
        self.handlers = {}

    def expose_binding(self, name, callback):
        assert name == "__pxNotify"
        self.binding = callback

    def on(self, event, callback):
        self.handlers[event] = callback

    def evaluate(self, script):
        return None



def test_sync_observer_binding_accepts_playwright_source_argument():
    page = _ObserverPage()
    engine = PxEngine()
    engine._on_px_detected = MagicMock()
    engine.install_observer(page)

    page.binding({"page": page})

    engine._on_px_detected.assert_called_once_with(page)


class _AsyncObserverPage:
    def __init__(self):
        self.binding = None
        self.handlers = {}

    async def expose_binding(self, name, callback):
        assert name == "__pxNotify"
        self.binding = callback

    def on(self, event, callback):
        self.handlers[event] = callback

    async def evaluate(self, script):
        return None


@pytest.mark.asyncio
async def test_async_observer_binding_accepts_playwright_source_argument():
    page = _AsyncObserverPage()
    engine = PxEngine()
    engine._on_px_detected_async = MagicMock()
    await engine.install_observer_async(page)

    page.binding({"page": page})

    engine._on_px_detected_async.assert_called_once_with(page)


class _ScriptOnlyPage:
    url = "https://example.test/"
    main_frame = object()
    frames = [main_frame]

    def evaluate(self, script, arg=None):
        if "querySelectorAll('script')" in script:
            return ["https://client.px-cloud.net/main.min.js"]
        if arg is not None:
            return 0
        if "document.body" in script:
            return "Normal application content"
        return False



def test_engine_does_not_treat_loaded_px_sdk_as_active_challenge():
    handler, result = PxEngine().detect(_ScriptOnlyPage())
    assert handler is None
    assert result.detected is False


class _Frame:
    url = "https://captcha.px-cloud.net/challenge"

    def evaluate(self, script):
        return True


class _FrameOnlyPage:
    url = "https://example.test/"

    def __init__(self):
        self.main_frame = object()
        self.frames = [self.main_frame, _Frame()]

    def evaluate(self, script, arg=None):
        if arg is not None:
            return 0
        if "querySelectorAll('script')" in script:
            return []
        if "document.body" in script:
            return ""
        return False



def test_engine_detects_challenge_visible_only_in_child_frame():
    handler, result = PxEngine().detect(_FrameOnlyPage())
    assert handler is None
    assert result.detected is True
    assert result.evidence["frame_url"].startswith("https://captcha.px-cloud.net")


class _Mouse:
    def move(self, *args, **kwargs):
        return None

    def down(self, *args, **kwargs):
        return None

    def up(self, *args, **kwargs):
        return None


class _SolvePage:
    viewport_size = {"width": 1280, "height": 720}
    mouse = _Mouse()



def test_solver_does_not_report_success_until_checker_is_ready(monkeypatch):
    solver = SolveByHoldButton()
    target = HoldTarget(x=100, y=100, width=100, height=30)
    monkeypatch.setattr(solver, "find_target", lambda page: target)
    monkeypatch.setattr(solver, "simulate_hold", lambda *args, **kwargs: None)
    visibility = iter([True, False])
    monkeypatch.setattr(solver, "_is_px_visible", lambda page: next(visibility, False))

    cfg = PxConfig(
        max_attempts=1,
        post_wait=0.01,
        app_ready_timeout=0,
        checker=lambda page: False,
    )
    result = solver.solve(_SolvePage(), cfg)

    assert result.solved is False
    assert result.error == "app_not_ready"


@pytest.mark.asyncio
async def test_async_engine_uses_async_detection_and_solving(monkeypatch):
    page = AsyncTextPage("Pressione e segure")
    engine = PxEngine(PxConfig())
    monkeypatch.setattr(engine, "_is_px_visible_async", AsyncMock(return_value=True))
    monkeypatch.setattr(
        engine,
        "solve_async",
        AsyncMock(return_value=SolveResult(solved=True, method="test")),
    )

    ok = await engine.check_and_solve_async(page)

    assert ok is True
    engine.solve_async.assert_awaited_once()



def test_camel_case_px_bypass_alias_is_not_forwarded_to_context(monkeypatch):
    from cloakbrowser import browser as browser_module

    fake_browser = MagicMock()
    fake_context = MagicMock()
    fake_browser.new_context.return_value = fake_context
    launch_mock = MagicMock(return_value=fake_browser)
    monkeypatch.setattr(browser_module, "launch", launch_mock)

    browser_module.launch_context(pxBypass=True)

    assert launch_mock.call_args.kwargs["bypass_px"] is True
    assert "pxBypass" not in fake_browser.new_context.call_args.kwargs
