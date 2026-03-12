"""cloakbrowser-human — Configuration and presets.

All numeric parameters for human-like behavior are centralized here.
Two built-in presets: 'default' (normal human speed) and 'careful' (slower, more cautious).
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Literal, Tuple

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

Range = Tuple[float, float]
HumanPreset = Literal["default", "careful"]


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------

@dataclass
class HumanConfig:
    """All tunable parameters for human-like behavior."""

    # Keyboard
    typing_delay: float = 70
    typing_delay_spread: float = 40
    typing_pause_chance: float = 0.1
    typing_pause_range: Range = (400, 1000)
    shift_down_delay: Range = (30, 70)
    shift_up_delay: Range = (20, 50)
    key_hold: Range = (15, 35)
    
    # Mistype (typo simulation)
    mistype_chance: float = 0.02
    mistype_delay_notice: Range = (100, 300)
    mistype_delay_correct: Range = (50, 150)

    field_switch_delay: Range = (800, 1500)

    # Mouse — movement
    mouse_steps_divisor: float = 8
    mouse_min_steps: int = 25
    mouse_max_steps: int = 80
    mouse_wobble_max: float = 1.5
    mouse_overshoot_chance: float = 0.15
    mouse_overshoot_px: Range = (3, 6)
    mouse_burst_size: Range = (3, 5)
    mouse_burst_pause: Range = (8, 18)

    # Mouse — clicks
    click_aim_delay_input: Range = (60, 140)
    click_aim_delay_button: Range = (80, 200)
    click_hold_input: Range = (40, 100)
    click_hold_button: Range = (60, 150)
    click_input_x_range: Range = (0.05, 0.30)

    # Mouse — idle
    idle_drift_px: float = 3
    idle_pause_range: Range = (300, 1000)

    # Scroll
    scroll_delta_base: Range = (80, 130)
    scroll_delta_variance: float = 0.2
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
        typing_delay=100,
        typing_delay_spread=50,
        typing_pause_chance=0.15,
        typing_pause_range=(500, 1200),
        shift_down_delay=(40, 90),
        shift_up_delay=(30, 70),
        key_hold=(20, 45),
        field_switch_delay=(1000, 2000),
        # Mouse — slower, more precise
        mouse_overshoot_chance=0.10,
        mouse_burst_pause=(12, 25),
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


_PRESETS: dict[str, HumanConfig] = {
    "default": HumanConfig(),
    "careful": _careful_config(),
}


def resolve_config(
    preset: HumanPreset = "default",
    overrides: dict | None = None,
) -> HumanConfig:
    """Resolve a preset name + optional overrides into a full HumanConfig.

    Args:
        preset: 'default' or 'careful'.
        overrides: Dict of field names to override values.

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
    merged.update(overrides)
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


def sleep_ms(ms: float) -> None:
    """Sleep for `ms` milliseconds."""
    if ms > 0:
        time.sleep(ms / 1000.0)


async def async_sleep_ms(ms: float) -> None:
    """Async sleep for `ms` milliseconds."""
    if ms > 0:
        import asyncio
        await asyncio.sleep(ms / 1000.0)
