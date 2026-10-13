"""cloakbrowser-human — Configuration and presets.

All numeric parameters for human-like behavior are centralized here.
Two built-in presets: 'default' (normal human speed) and 'careful' (slower, more cautious).
"""

from __future__ import annotations

import math
import os
import random
import sys
import time
import warnings
from dataclasses import dataclass, field
from typing import Literal, Tuple, TypedDict

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

Range = Tuple[float, float]
HumanPreset = Literal["default", "careful"]


class HumanConfigOverrides(TypedDict, total=False):
    typing_delay: float
    typing_delay_spread: float
    typing_pause_chance: float
    typing_pause_range: Range
    shift_down_delay: Range
    shift_up_delay: Range
    key_hold: Range
    field_switch_delay: Range
    mistype_chance: float
    mistype_delay_notice: Range
    mistype_delay_correct: Range
    mouse_min_steps: int
    mouse_max_steps: int
    mouse_wobble_max: float
    mouse_overshoot_chance: float
    mouse_overshoot_px: Range
    mouse_time_base: float
    mouse_time_per_bit: float
    mouse_time_spread: float
    click_aim_delay_input: Range
    click_aim_delay_button: Range
    click_hold_input: Range
    click_hold_button: Range
    click_input_x_range: Range
    idle_drift_px: float
    idle_pause_range: Range
    scroll_notch_px: float
    scroll_pause_fast: Range
    scroll_pause_slow: Range
    scroll_accel_steps: Range
    scroll_decel_steps: Range
    scroll_overshoot_chance: float
    scroll_overshoot_px: Range
    scroll_settle_delay: Range
    scroll_target_zone: Range
    scroll_pre_move_delay: Range
    initial_cursor_x: Range
    initial_cursor_y: Range
    idle_between_actions: bool
    idle_between_duration: Range


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------

@dataclass
class HumanConfig:
    """All tunable parameters for human-like behavior."""

    # Keyboard. Defaults follow the 136M Keystrokes study (Dhakal et al.,
    # CHI 2018): keys are held ~100 ms, ~150 ms pass between key presses, and
    # the next key is often pressed before the previous one is released.
    #
    # typing_delay: median time from one key press to the next (ms); the gap
    # is log-normal and depends on the letters (other hand: faster, same
    # finger: slower, after a space: slower).
    typing_delay: float = 150
    # How much the gap varies (ms); 0 = always exactly typing_delay.
    typing_delay_spread: float = 70
    # Chance of a thinking pause before a word (a tenth of it inside a word).
    typing_pause_chance: float = 0.15
    typing_pause_range: Range = (300, 1000)
    # Shift press -> letter press (ms, log-normal: ~5th..95th percentile).
    shift_down_delay: Range = (60, 220)
    # Shift release relative to the letter release (ms). Negative = Shift goes
    # up first, which is what people usually do.
    shift_up_delay: Range = (-60, 30)
    # How long a key is held down (ms, log-normal: ~5th..95th percentile).
    key_hold: Range = (60, 175)

    # Mistype (typo simulation): chance per letter / digit.
    mistype_chance: float = 0.04
    mistype_delay_notice: Range = (100, 300)
    mistype_delay_correct: Range = (50, 150)

    field_switch_delay: Range = (800, 1500)

    # Mouse — movement. A move lasts (Fitts' law, log-normal spread)
    #   median = mouse_time_base + mouse_time_per_bit * log2(1 + distance / 8) ms;
    # the speed peaks early (a fast main stroke, then a slow approach) and
    # pointer events go out at ~60 Hz.
    mouse_time_base: float = 160
    mouse_time_per_bit: float = 75
    mouse_time_spread: float = 0.3
    mouse_min_steps: int = 2       # fewest pointer events per stroke
    mouse_max_steps: int = 200     # most pointer events per stroke
    mouse_wobble_max: float = 1.5  # smooth sideways drift (px)
    # Chance that the main stroke lands a little off and a short corrective
    # stroke finishes the move (the miss is a few % of the distance plus
    # mouse_overshoot_px).
    mouse_overshoot_chance: float = 0.35
    mouse_overshoot_px: Range = (2, 6)

    # Mouse — clicks
    click_aim_delay_input: Range = (60, 140)
    click_aim_delay_button: Range = (80, 200)
    click_hold_input: Range = (40, 100)
    click_hold_button: Range = (60, 150)
    click_input_x_range: Range = (0.05, 0.30)

    # Mouse — idle
    idle_drift_px: float = 3
    idle_pause_range: Range = (300, 1000)

    # Scroll. The wheel turns in whole notches: one wheel event per notch of
    # scroll_notch_px CSS pixels, so deltaY and wheelDeltaY agree the way they
    # do for a real mouse wheel. 0 = what Chrome uses on the persona's
    # platform (100 on Windows, 40 on macOS, 120 on Linux).
    scroll_notch_px: float = 0
    # Pause between notches inside one flick / at the start and end of it.
    scroll_pause_fast: Range = (30, 80)
    scroll_pause_slow: Range = (80, 200)
    scroll_accel_steps: Range = (2, 3)
    scroll_decel_steps: Range = (2, 3)
    scroll_overshoot_chance: float = 0.1
    scroll_overshoot_px: Range = (50, 150)
    scroll_settle_delay: Range = (300, 600)
    scroll_target_zone: Range = (0.20, 0.80)
    scroll_pre_move_delay: Range = (100, 300)

    # Initial cursor position (as if coming from the address bar area)
    initial_cursor_x: Range = (400, 700)
    initial_cursor_y: Range = (45, 60)

    # Idle micro-movements between actions (opt-in, adds latency)
    idle_between_actions: bool = False
    idle_between_duration: Range = (0.3, 0.8)


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

def _careful_config() -> HumanConfig:
    """Careful preset — everything slower and more deliberate."""
    return HumanConfig(
        # Keyboard — slower typing
        typing_delay=210,
        typing_delay_spread=100,
        typing_pause_chance=0.25,
        typing_pause_range=(500, 1200),
        shift_down_delay=(80, 260),
        shift_up_delay=(-50, 40),
        key_hold=(70, 190),
        field_switch_delay=(1000, 2000),
        mistype_chance=0.05,
        # Mouse — slower, more precise
        mouse_time_base=220,
        mouse_time_per_bit=95,
        mouse_overshoot_chance=0.45,
        mouse_overshoot_px=(2, 5),
        # Mouse — clicks (longer aiming and holding)
        click_aim_delay_input=(80, 180),
        click_aim_delay_button=(120, 280),
        click_hold_input=(60, 140),
        click_hold_button=(80, 200),
        # Scroll — slower
        scroll_pause_fast=(100, 200),
        scroll_pause_slow=(250, 600),
        scroll_settle_delay=(400, 800),
        scroll_pre_move_delay=(150, 400),
        # Idle between actions enabled for careful preset
        idle_between_actions=True,
        idle_between_duration=(0.4, 1.0),
    )


# Settings removed when moves switched to Fitts-law timing and scrolling to
# whole wheel notches. Old configs that still pass them keep loading: the key
# is dropped with a warning instead of failing in HumanConfig(**...).
_REMOVED_KEYS = frozenset({
    "mouse_steps_divisor", "mouse_burst_size", "mouse_burst_pause",
    "scroll_delta_base", "scroll_delta_variance",
})


def _drop_removed(overrides: dict) -> dict:
    removed = sorted(k for k in overrides if k in _REMOVED_KEYS)
    if not removed:
        return overrides
    # Point the warning at the caller's own code (launch(), resolve_config()
    # and the wrappers sit at different depths inside this package).
    pkg = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # stacklevel 1 is this function; climb until the first frame outside it.
    level, frame = 1, sys._getframe(0)
    while frame is not None and os.path.abspath(frame.f_code.co_filename).startswith(pkg + os.sep):
        level, frame = level + 1, frame.f_back
    # FutureWarning, not DeprecationWarning: Python hides the latter outside __main__.
    warnings.warn(
        f"human_config: {', '.join(removed)} no longer exist and are ignored "
        "(mouse moves use mouse_time_*, scrolling uses scroll_notch_px)",
        FutureWarning, stacklevel=level,
    )
    return {k: v for k, v in overrides.items() if k not in _REMOVED_KEYS}


_PRESETS: dict[str, HumanConfig] = {
    "default": HumanConfig(),
    "careful": _careful_config(),
}


def resolve_config(
    preset: HumanPreset = "default",
    overrides: HumanConfigOverrides | None = None,
) -> HumanConfig:
    """Resolve a preset name + optional overrides into a full HumanConfig.

    Args:
        preset: 'default' or 'careful'.
        overrides: Typed mapping of HumanConfig field names to override values.

    Returns:
        A new HumanConfig instance.

    Raises:
        ValueError: If preset is not a recognized name.
    """
    if preset not in _PRESETS:
        raise ValueError(
            f"Unknown humanize preset {preset!r}. "
            f"Valid presets: {', '.join(sorted(_PRESETS.keys()))}"
        )
    base = _PRESETS[preset]
    if not overrides:
        return HumanConfig(**{k: getattr(base, k) for k in base.__dataclass_fields__})
    merged = {k: getattr(base, k) for k in base.__dataclass_fields__}
    merged.update(_drop_removed(dict(overrides)))
    return HumanConfig(**merged)


def merge_config(base: HumanConfig, overrides: dict | None) -> HumanConfig:
    """Merge ``overrides`` (a dict of HumanConfig field names → values) on top of
    ``base``. Returns a new HumanConfig — ``base`` is never mutated.

    Used by per-call overrides like ``page.type(sel, text, human_config={...})``
    so the same page can use different timings for different inputs without
    re-patching.

    Unknown keys are ignored silently to keep this forgiving for callers.
    """
    if not overrides:
        return base
    merged = {k: getattr(base, k) for k in base.__dataclass_fields__}
    for k, v in overrides.items():
        if k in base.__dataclass_fields__:
            merged[k] = v
    return HumanConfig(**merged)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def rand(lo: float, hi: float) -> float:
    """Random float in [lo, hi]."""
    return random.uniform(lo, hi)


def rand_int(lo: int, hi: int) -> int:
    """Random integer in [lo, hi] inclusive."""
    return random.randint(lo, hi)


def rand_range(r: Range) -> float:
    """Random float from a (min, max) tuple."""
    return random.uniform(r[0], r[1])


def rand_int_range(r: Range) -> int:
    """Random integer from a (min, max) tuple, inclusive."""
    return random.randint(int(r[0]), int(r[1]))


_Z95 = 1.6449  # standard normal 95th percentile


def rand_log(r: Range) -> float:
    """Log-normal sample with ``r`` as its ~5th / 95th percentiles, clipped to
    [low / 2, high * 2]. Human timings (key holds, gaps) are right-skewed like
    this, not uniform. Falls back to uniform when a bound is not positive."""
    lo, hi = float(r[0]), float(r[1])
    if hi < lo:
        lo, hi = hi, lo
    if lo <= 0:
        return random.uniform(lo, hi)
    if hi == lo:
        return lo
    mu = (math.log(lo) + math.log(hi)) / 2
    sigma = (math.log(hi) - math.log(lo)) / (2 * _Z95)
    return min(hi * 2, max(lo / 2, math.exp(random.gauss(mu, sigma))))


def rand_lognormal(median: float, sigma: float) -> float:
    """Log-normal sample with the given median and log-space sigma."""
    if median <= 0:
        return 0.0
    if sigma <= 0:
        return float(median)
    return median * math.exp(random.gauss(0.0, sigma))


def sleep_ms(ms: float) -> None:
    """Sleep for `ms` milliseconds."""
    if ms > 0:
        time.sleep(ms / 1000.0)
