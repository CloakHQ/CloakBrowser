//! Humanize configuration and presets.
//! Direct port of Python `cloakbrowser/human/config.py` / .NET `HumanConfig.cs`.

use serde::{Deserialize, Serialize};

/// Inclusive numeric range `(min, max)`.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Range {
    pub min: f64,
    pub max: f64,
}

impl Range {
    pub const fn new(min: f64, max: f64) -> Self {
        Self { min, max }
    }
}

impl From<(f64, f64)> for Range {
    fn from(t: (f64, f64)) -> Self {
        Self {
            min: t.0,
            max: t.1,
        }
    }
}

/// Humanize behavior preset names.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum HumanPreset {
    #[default]
    Default,
    Careful,
}

impl HumanPreset {
    /// Parse `'default'` / `'careful'` (case-insensitive).
    pub fn parse(s: &str) -> Result<Self, String> {
        match s.trim().to_ascii_lowercase().as_str() {
            "default" => Ok(Self::Default),
            "careful" => Ok(Self::Careful),
            other => Err(format!(
                "Unknown humanize preset '{other}'. Valid presets: careful, default"
            )),
        }
    }
}

/// All tunable parameters for human-like behavior.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HumanConfig {
    // Keyboard
    pub typing_delay: f64,
    pub typing_delay_spread: f64,
    pub typing_pause_chance: f64,
    pub typing_pause_range: Range,
    pub shift_down_delay: Range,
    pub shift_up_delay: Range,
    pub key_hold: Range,
    pub mistype_chance: f64,
    pub mistype_delay_notice: Range,
    pub mistype_delay_correct: Range,
    pub field_switch_delay: Range,

    // Mouse — movement
    pub mouse_steps_divisor: f64,
    pub mouse_min_steps: i32,
    pub mouse_max_steps: i32,
    pub mouse_wobble_max: f64,
    pub mouse_overshoot_chance: f64,
    pub mouse_overshoot_px: Range,
    pub mouse_burst_size: Range,
    pub mouse_burst_pause: Range,

    // Mouse — clicks
    pub click_aim_delay_input: Range,
    pub click_aim_delay_button: Range,
    pub click_hold_input: Range,
    pub click_hold_button: Range,
    pub click_input_x_range: Range,

    // Mouse — idle
    pub idle_drift_px: f64,
    pub idle_pause_range: Range,

    // Scroll
    pub scroll_delta_base: Range,
    pub scroll_delta_variance: f64,
    pub scroll_pause_fast: Range,
    pub scroll_pause_slow: Range,
    pub scroll_accel_steps: Range,
    pub scroll_decel_steps: Range,
    pub scroll_overshoot_chance: f64,
    pub scroll_overshoot_px: Range,
    pub scroll_settle_delay: Range,
    pub scroll_target_zone: Range,
    pub scroll_pre_move_delay: Range,

    // Initial cursor (address-bar area)
    pub initial_cursor_x: Range,
    pub initial_cursor_y: Range,

    // Idle between actions (opt-in)
    pub idle_between_actions: bool,
    pub idle_between_duration: Range,
}

impl Default for HumanConfig {
    fn default() -> Self {
        Self {
            typing_delay: 70.0,
            typing_delay_spread: 40.0,
            typing_pause_chance: 0.1,
            typing_pause_range: Range::new(400.0, 1000.0),
            shift_down_delay: Range::new(30.0, 70.0),
            shift_up_delay: Range::new(20.0, 50.0),
            key_hold: Range::new(15.0, 35.0),
            mistype_chance: 0.02,
            mistype_delay_notice: Range::new(100.0, 300.0),
            mistype_delay_correct: Range::new(50.0, 150.0),
            field_switch_delay: Range::new(800.0, 1500.0),

            mouse_steps_divisor: 8.0,
            mouse_min_steps: 25,
            mouse_max_steps: 80,
            mouse_wobble_max: 1.5,
            mouse_overshoot_chance: 0.15,
            mouse_overshoot_px: Range::new(3.0, 6.0),
            mouse_burst_size: Range::new(3.0, 5.0),
            mouse_burst_pause: Range::new(8.0, 18.0),

            click_aim_delay_input: Range::new(60.0, 140.0),
            click_aim_delay_button: Range::new(80.0, 200.0),
            click_hold_input: Range::new(40.0, 100.0),
            click_hold_button: Range::new(60.0, 150.0),
            click_input_x_range: Range::new(0.05, 0.30),

            idle_drift_px: 3.0,
            idle_pause_range: Range::new(300.0, 1000.0),

            scroll_delta_base: Range::new(80.0, 130.0),
            scroll_delta_variance: 0.2,
            scroll_pause_fast: Range::new(30.0, 80.0),
            scroll_pause_slow: Range::new(80.0, 200.0),
            scroll_accel_steps: Range::new(2.0, 3.0),
            scroll_decel_steps: Range::new(2.0, 3.0),
            scroll_overshoot_chance: 0.1,
            scroll_overshoot_px: Range::new(50.0, 150.0),
            scroll_settle_delay: Range::new(300.0, 600.0),
            scroll_target_zone: Range::new(0.20, 0.80),
            scroll_pre_move_delay: Range::new(100.0, 300.0),

            initial_cursor_x: Range::new(400.0, 700.0),
            initial_cursor_y: Range::new(45.0, 60.0),

            idle_between_actions: false,
            idle_between_duration: Range::new(0.3, 0.8),
        }
    }
}

impl HumanConfig {
    /// Careful preset — slower and more deliberate.
    pub fn careful() -> Self {
        Self {
            typing_delay: 100.0,
            typing_delay_spread: 50.0,
            typing_pause_chance: 0.15,
            typing_pause_range: Range::new(500.0, 1200.0),
            shift_down_delay: Range::new(40.0, 90.0),
            shift_up_delay: Range::new(30.0, 70.0),
            key_hold: Range::new(20.0, 45.0),
            field_switch_delay: Range::new(1000.0, 2000.0),
            mouse_overshoot_chance: 0.10,
            mouse_burst_pause: Range::new(12.0, 25.0),
            click_aim_delay_input: Range::new(80.0, 180.0),
            click_aim_delay_button: Range::new(120.0, 280.0),
            click_hold_input: Range::new(60.0, 140.0),
            click_hold_button: Range::new(80.0, 200.0),
            scroll_pause_fast: Range::new(100.0, 200.0),
            scroll_pause_slow: Range::new(250.0, 600.0),
            scroll_settle_delay: Range::new(400.0, 800.0),
            scroll_pre_move_delay: Range::new(150.0, 400.0),
            idle_between_actions: true,
            idle_between_duration: Range::new(0.4, 1.0),
            ..Self::default()
        }
    }

    /// Resolve a preset into a full config.
    pub fn resolve(preset: HumanPreset) -> Self {
        match preset {
            HumanPreset::Default => Self::default(),
            HumanPreset::Careful => Self::careful(),
        }
    }
}

// ---------------------------------------------------------------------------
// Random / timing helpers (mirror Python human/config.py)
// ---------------------------------------------------------------------------

/// Random float in `[lo, hi]`.
pub fn rand(lo: f64, hi: f64) -> f64 {
    let (lo, hi) = if hi < lo { (hi, lo) } else { (lo, hi) };
    lo + rand::random::<f64>() * (hi - lo)
}

/// Random integer in `[lo, hi]` inclusive.
pub fn rand_int(lo: i32, hi: i32) -> i32 {
    let (lo, hi) = if hi < lo { (hi, lo) } else { (lo, hi) };
    if lo == hi {
        return lo;
    }
    let span = (hi - lo + 1) as u32;
    lo + (rand::random::<u32>() % span) as i32
}

/// Random float from a [`Range`].
pub fn rand_range(r: Range) -> f64 {
    rand(r.min, r.max)
}

/// Random integer from a [`Range`], inclusive.
pub fn rand_int_range(r: Range) -> i32 {
    rand_int(r.min as i32, r.max as i32)
}

/// True with the given probability in `[0, 1]`.
pub fn chance(probability: f64) -> bool {
    rand::random::<f64>() < probability
}

/// Async sleep for `ms` milliseconds (no-op if <= 0).
pub async fn sleep_ms(ms: f64) {
    if ms > 0.0 {
        tokio::time::sleep(std::time::Duration::from_millis(ms.round() as u64)).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn careful_is_slower() {
        let d = HumanConfig::default();
        let c = HumanConfig::careful();
        assert!(c.typing_delay > d.typing_delay);
        assert!(c.idle_between_actions);
    }

    #[test]
    fn parse_preset() {
        assert_eq!(HumanPreset::parse("DEFAULT").unwrap(), HumanPreset::Default);
        assert_eq!(HumanPreset::parse("careful").unwrap(), HumanPreset::Careful);
        assert!(HumanPreset::parse("turbo").is_err());
    }

    #[test]
    fn rand_in_bounds() {
        for _ in 0..50 {
            let v = rand(1.0, 2.0);
            assert!((1.0..=2.0).contains(&v));
            let i = rand_int(3, 5);
            assert!((3..=5).contains(&i));
        }
    }
}
