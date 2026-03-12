/**
 * cloakbrowser-human — Configuration and presets.
 *
 * All numeric parameters for human-like behavior are centralized here.
 * Two built-in presets: 'default' (normal human speed) and 'careful' (slower, more cautious).
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface HumanConfig {
  // Keyboard
  typing_delay: number;
  typing_delay_spread: number;
  typing_pause_chance: number;
  typing_pause_range: [number, number];
  shift_down_delay: [number, number];
  shift_up_delay: [number, number];
  key_hold: [number, number];
  field_switch_delay: [number, number];
  mistype_chance: number;
  mistype_delay_notice: [number, number];
  mistype_delay_correct: [number, number];


  // Mouse — movement
  mouse_steps_divisor: number;
  mouse_min_steps: number;
  mouse_max_steps: number;
  mouse_wobble_max: number;
  mouse_overshoot_chance: number;
  mouse_overshoot_px: [number, number];
  mouse_burst_size: [number, number];
  mouse_burst_pause: [number, number];

  // Mouse — clicks
  click_aim_delay_input: [number, number];
  click_aim_delay_button: [number, number];
  click_hold_input: [number, number];
  click_hold_button: [number, number];
  click_input_x_range: [number, number];

  // Mouse — idle
  idle_drift_px: number;
  idle_pause_range: [number, number];

  // Scroll
  scroll_delta_base: [number, number];
  scroll_delta_variance: number;
  scroll_pause_fast: [number, number];
  scroll_pause_slow: [number, number];
  scroll_accel_steps: [number, number];
  scroll_decel_steps: [number, number];
  scroll_overshoot_chance: number;
  scroll_overshoot_px: [number, number];
  scroll_settle_delay: [number, number];
  scroll_target_zone: [number, number];
  scroll_pre_move_delay: [number, number];

  // Initial cursor position
  initial_cursor_x: [number, number];
  initial_cursor_y: [number, number];


  // Idle micro-movements between actions (opt-in, adds latency)
  idle_between_actions: boolean;
  idle_between_duration: [number, number];
}

export type HumanPreset = 'default' | 'careful';

// ---------------------------------------------------------------------------
// Default preset
// ---------------------------------------------------------------------------

const DEFAULT_CONFIG: HumanConfig = {
  // Keyboard
  typing_delay: 70,
  typing_delay_spread: 40,
  typing_pause_chance: 0.1,
  typing_pause_range: [400, 1000],
  shift_down_delay: [30, 70],
  shift_up_delay: [20, 50],
  key_hold: [15, 35],
  field_switch_delay: [800, 1500],
  // Mistype (typo simulation)
  mistype_chance: 0.02,
  mistype_delay_notice: [100, 300],
  mistype_delay_correct: [50, 150],

  // Mouse — movement
  mouse_steps_divisor: 8,
  mouse_min_steps: 25,
  mouse_max_steps: 80,
  mouse_wobble_max: 1.5,
  mouse_overshoot_chance: 0.15,
  mouse_overshoot_px: [3, 6],
  mouse_burst_size: [3, 5],
  mouse_burst_pause: [8, 18],

  // Mouse — clicks
  click_aim_delay_input: [60, 140],
  click_aim_delay_button: [80, 200],
  click_hold_input: [40, 100],
  click_hold_button: [60, 150],
  click_input_x_range: [0.05, 0.30],

  // Mouse — idle
  idle_drift_px: 3,
  idle_pause_range: [300, 1000],

  // Scroll
  scroll_delta_base: [80, 130],
  scroll_delta_variance: 0.2,
  scroll_pause_fast: [30, 80],
  scroll_pause_slow: [80, 200],
  scroll_accel_steps: [2, 3],
  scroll_decel_steps: [2, 3],
  scroll_overshoot_chance: 0.1,
  scroll_overshoot_px: [50, 150],
  scroll_settle_delay: [300, 600],
  scroll_target_zone: [0.20, 0.80],
  scroll_pre_move_delay: [100, 300],

  // Initial cursor position (as if coming from the address bar area)
  initial_cursor_x: [400, 700],
  initial_cursor_y: [45, 60],

  // Idle micro-movements between actions (off by default)
  idle_between_actions: false,
  idle_between_duration: [0.3, 0.8],
};

// ---------------------------------------------------------------------------
// Careful preset — everything slower and more deliberate
// ---------------------------------------------------------------------------

const CAREFUL_CONFIG: HumanConfig = {
  ...DEFAULT_CONFIG,

  // Keyboard — slower typing
  typing_delay: 100,
  typing_delay_spread: 50,
  typing_pause_chance: 0.15,
  typing_pause_range: [500, 1200],
  shift_down_delay: [40, 90],
  shift_up_delay: [30, 70],
  key_hold: [20, 45],
  field_switch_delay: [1000, 2000],
  mistype_chance: 0.03,
  mistype_delay_notice: [150, 400],
  mistype_delay_correct: [80, 200],

  // Mouse — slower, more precise
  mouse_overshoot_chance: 0.10,
  mouse_burst_pause: [12, 25],

  // Mouse — clicks (longer aiming and holding)
  click_aim_delay_input: [80, 180],
  click_aim_delay_button: [120, 280],
  click_hold_input: [60, 140],
  click_hold_button: [80, 200],

  // Scroll — slower
  scroll_pause_fast: [100, 200],
  scroll_pause_slow: [250, 600],
  scroll_settle_delay: [400, 800],
  scroll_pre_move_delay: [150, 400],

  // Idle between actions enabled for careful preset
  idle_between_actions: true,
  idle_between_duration: [0.4, 1.0],
};

// ---------------------------------------------------------------------------
// Preset map
// ---------------------------------------------------------------------------

const PRESETS: Record<HumanPreset, HumanConfig> = {
  default: DEFAULT_CONFIG,
  careful: CAREFUL_CONFIG,
};

/**
 * Resolve a preset name or partial config into a full HumanConfig.
 * If `preset` is a string, returns the corresponding built-in config.
 * Any keys in `overrides` replace the preset values.
 */
export function resolveConfig(
  preset: HumanPreset = 'default',
  overrides?: Partial<HumanConfig>,
): HumanConfig {
  const base = PRESETS[preset];
  if (!base) {
    throw new Error(
      `Unknown humanize preset "${preset}". Valid presets: ${Object.keys(PRESETS).join(', ')}`
    );
  }
  if (!overrides) return { ...base };
  return { ...base, ...overrides };
}


// ---------------------------------------------------------------------------
// Utility: random number in range
// ---------------------------------------------------------------------------

/** Random float in [min, max]. */
export function rand(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

/** Random integer in [min, max] (inclusive). */
export function randInt(min: number, max: number): number {
  return Math.floor(rand(min, max + 1));
}

/** Random value from a [min, max] tuple. */
export function randRange(range: [number, number]): number {
  return rand(range[0], range[1]);
}

/** Random integer from a [min, max] tuple. */
export function randIntRange(range: [number, number]): number {
  return randInt(range[0], range[1]);
}

/** Sleep for `ms` milliseconds. */
export function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
