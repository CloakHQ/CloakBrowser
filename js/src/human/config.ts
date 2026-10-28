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
  mouse_min_steps: number;
  mouse_max_steps: number;
  mouse_wobble_max: number;
  mouse_overshoot_chance: number;
  mouse_overshoot_px: [number, number];
  mouse_time_base: number;
  mouse_time_per_bit: number;
  mouse_time_spread: number;

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
  scroll_notch_px: number;
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

export type HumanActionOptions = Partial<HumanConfig> & {
  timeout?: number;
  force?: boolean;
  delay?: number;
  human_config?: Partial<HumanConfig>;
};

// ---------------------------------------------------------------------------
// Default preset
// ---------------------------------------------------------------------------

const DEFAULT_CONFIG: HumanConfig = {
  // Keyboard. Defaults follow the 136M Keystrokes study (Dhakal et al.,
  // CHI 2018): keys are held ~100 ms, ~150 ms pass between key presses, and
  // the next key is often pressed before the previous one is released.
  //
  // typing_delay: median time from one key press to the next (ms); the gap is
  // log-normal and depends on the letters (other hand: faster, same finger:
  // slower, after a space: slower).
  typing_delay: 150,
  // How much the gap varies (ms); 0 = always exactly typing_delay.
  typing_delay_spread: 70,
  // Chance of a thinking pause before a word (a tenth of it inside a word).
  typing_pause_chance: 0.15,
  typing_pause_range: [300, 1000],
  // Shift press -> letter press (ms, log-normal: ~5th..95th percentile).
  shift_down_delay: [60, 220],
  // Shift release relative to the letter release (ms). Negative = Shift goes
  // up first, which is what people usually do.
  shift_up_delay: [-60, 30],
  // How long a key is held down (ms, log-normal: ~5th..95th percentile).
  key_hold: [60, 175],
  field_switch_delay: [800, 1500],
  // Mistype (typo simulation): chance per letter / digit.
  mistype_chance: 0.04,
  mistype_delay_notice: [100, 300],
  mistype_delay_correct: [50, 150],

  // Mouse — movement. A move lasts (Fitts' law, log-normal spread)
  //   median = mouse_time_base + mouse_time_per_bit * log2(1 + distance / 8) ms;
  // the speed peaks early (a fast main stroke, then a slow approach) and
  // pointer events go out at ~60 Hz.
  mouse_time_base: 160,
  mouse_time_per_bit: 75,
  mouse_time_spread: 0.3,
  mouse_min_steps: 2,       // fewest pointer events per stroke
  mouse_max_steps: 200,     // most pointer events per stroke
  mouse_wobble_max: 1.5,    // smooth sideways drift (px)
  // Chance that the main stroke lands a little off and a short corrective
  // stroke finishes the move (the miss is a few % of the distance plus
  // mouse_overshoot_px).
  mouse_overshoot_chance: 0.35,
  mouse_overshoot_px: [2, 6],

  // Mouse — clicks
  click_aim_delay_input: [60, 140],
  click_aim_delay_button: [80, 200],
  click_hold_input: [40, 100],
  click_hold_button: [60, 150],
  click_input_x_range: [0.05, 0.30],

  // Mouse — idle
  idle_drift_px: 3,
  idle_pause_range: [300, 1000],

  // Scroll. The wheel turns in whole notches: one wheel event per notch of
  // scroll_notch_px CSS pixels, so deltaY and wheelDeltaY agree the way they
  // do for a real mouse wheel. 0 = what Chrome uses on the persona's platform
  // (100 on Windows, 40 on macOS, 120 on Linux).
  scroll_notch_px: 0,
  // Pause between notches inside one flick / at the start and end of it.
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
  typing_delay: 210,
  typing_delay_spread: 100,
  typing_pause_chance: 0.25,
  typing_pause_range: [500, 1200],
  shift_down_delay: [80, 260],
  shift_up_delay: [-50, 40],
  key_hold: [70, 190],
  field_switch_delay: [1000, 2000],
  mistype_chance: 0.05,
  mistype_delay_notice: [150, 400],
  mistype_delay_correct: [80, 200],

  // Mouse — slower, more precise
  mouse_time_base: 220,
  mouse_time_per_bit: 95,
  mouse_overshoot_chance: 0.45,
  mouse_overshoot_px: [2, 5],

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

/**
 * Merge a partial overrides object on top of an existing HumanConfig.
 * Returns a new object — the original ``cfg`` is never mutated.
 *
 * Used by per-call overrides such as ``page.type(sel, text, { human_config: { typing_delay: 30 } })``
 * so the same patched page can type different fields at different speeds
 * without re-patching.
 */
export function mergeConfig(
  cfg: HumanConfig,
  overrides?: Partial<HumanConfig> | null,
): HumanConfig {
  if (!overrides) return cfg;
  return { ...cfg, ...overrides };
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

const Z95 = 1.6449; // standard normal 95th percentile

/** Standard normal sample (Box-Muller). */
export function gauss(): number {
  let u = 0;
  while (u === 0) u = Math.random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * Math.random());
}

/**
 * Log-normal sample with `range` as its ~5th / 95th percentiles, clipped to
 * [low / 2, high * 2]. Human timings (key holds, gaps) are right-skewed like
 * this, not uniform. Falls back to uniform when a bound is not positive.
 */
export function randLog(range: [number, number]): number {
  let lo = range[0], hi = range[1];
  if (hi < lo) [lo, hi] = [hi, lo];
  if (lo <= 0) return rand(lo, hi);
  if (hi === lo) return lo;
  const mu = (Math.log(lo) + Math.log(hi)) / 2;
  const sigma = (Math.log(hi) - Math.log(lo)) / (2 * Z95);
  return Math.min(hi * 2, Math.max(lo / 2, Math.exp(mu + sigma * gauss())));
}

/** Log-normal sample with the given median and log-space sigma. */
export function randLognormal(median: number, sigma: number): number {
  if (median <= 0) return 0;
  if (sigma <= 0) return median;
  return median * Math.exp(sigma * gauss());
}

/** Sleep for `ms` milliseconds. */
export function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
