"""Configuration for PerimeterX challenge auto-solving."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Default parameters for PerimeterX "Press & Hold" solving
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_HOLD_MIN = 3.8
DEFAULT_HOLD_MAX = 6.5
DEFAULT_POST_WAIT = 30.0
DEFAULT_MONITOR_INTERVAL = 1.5
PX_UI_WAIT_TIMEOUT = 45.0
PX_BUTTON_WAIT_TIMEOUT = 20.0
PX_POST_INJECT_WAIT = 25.0
PX_APP_READY_TIMEOUT = 60.0


@dataclass
class PxConfig:
    """Configuration for PerimeterX challenge auto-solving.

    Attributes:
        enabled: Set to False to disable auto-solving (useful toggling).
        max_attempts: Maximum number of press-and-hold attempts before giving up.
        hold_min: Minimum hold duration in seconds.
        hold_max: Maximum hold duration in seconds.
        post_wait: Seconds to wait after mouse up for PX to clear.
        ui_wait_timeout: Max seconds to wait for PX UI to appear.
        button_wait_timeout: Max seconds to wait for hold button to render.
        monitor_interval: Seconds between background PX checks (default 1.5).
            The background monitor runs in a daemon thread and polls the page
            at this interval. Lower = faster detection, higher = less CPU.
        reload_if_hidden: Whether to reload page if PX UI doesn't appear.
        debug_capture: Save DOM probe snapshots for debugging.
        checker: Optional callable to verify the page is usable after PX solve.
            Called as checker(page) -> bool. If provided, the solver will
            wait until this returns True (with a timeout).
        webrtc_ip: Optional WebRTC IP to spoof during the solve process.
    """
    enabled: bool = True
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    hold_min: float = DEFAULT_HOLD_MIN
    hold_max: float = DEFAULT_HOLD_MAX
    post_wait: float = DEFAULT_POST_WAIT
    ui_wait_timeout: float = PX_UI_WAIT_TIMEOUT
    button_wait_timeout: float = PX_BUTTON_WAIT_TIMEOUT
    monitor_interval: float = DEFAULT_MONITOR_INTERVAL
    post_inject_wait: float = PX_POST_INJECT_WAIT
    app_ready_timeout: float = PX_APP_READY_TIMEOUT
    reload_if_hidden: bool = True
    debug_capture: bool = False
    checker: Any = None  # Optional callable(page) -> bool


class PXConfigDefaults:
    """Read-only namespace of default PX config values for reference."""
    MAX_ATTEMPTS = DEFAULT_MAX_ATTEMPTS
    HOLD_MIN = DEFAULT_HOLD_MIN
    HOLD_MAX = DEFAULT_HOLD_MAX
    POST_WAIT = DEFAULT_POST_WAIT
    MONITOR_INTERVAL = DEFAULT_MONITOR_INTERVAL
    UI_WAIT_TIMEOUT = PX_UI_WAIT_TIMEOUT
    BUTTON_WAIT_TIMEOUT = PX_BUTTON_WAIT_TIMEOUT
    POST_INJECT_WAIT = PX_POST_INJECT_WAIT
    APP_READY_TIMEOUT = PX_APP_READY_TIMEOUT


# Text markers used to identify PerimeterX challenge pages
PX_TEXT_MARKERS = (
    "pressione e segure",
    "press and hold",
    "press & hold",
    "activate and hold",
    "antes de continuarmos",
    "confirmar que você é um humano",
    "px-captcha",
    "robot or human",
)

# Short button labels (not instruction paragraphs)
PX_HOLD_BUTTON_LABELS = (
    "Pressione e segure",
    "Press and hold",
    "Press & hold",
    "Activate and hold",
)

# Walmart-specific PX iframe selector
PX_IFRAME_SELECTOR = "#px-captcha iframe"
PX_CAPTCHA_CONTAINER = "#px-captcha"
