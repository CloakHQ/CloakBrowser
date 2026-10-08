/**
 * Field classification for humanized text input. Port of
 * cloakbrowser/human/fields.py; mirrors Playwright's `InjectedScript.fill`
 * rules (playwright-core 1.63):
 *
 * - text-like inputs are typed into key by key;
 * - value inputs (date, range, ...) are operated through their native widget
 *   the way a person does it (segments + keyboard, slider click + arrows);
 * - everything else (checkbox, file, hidden, radio, ...) cannot be filled.
 *
 * Mistypes are only simulated where a human plausibly makes and corrects them
 * and where the correction is safe: never in number/email/password/tel/url.
 */

export const TYPE_INTO = new Set(['', 'email', 'number', 'password', 'search', 'tel', 'text', 'url']);
export const SET_VALUE = new Set(['color', 'date', 'time', 'datetime-local', 'month', 'range', 'week']);
export const NO_MISTYPE = new Set(['number', 'email', 'password', 'tel', 'url']);

export const TYPE = 'type';
export const SET = 'set';
export const NOT_FILLABLE = 'reject';
export type FieldKind = typeof TYPE | typeof SET | typeof NOT_FILLABLE;

export function classify(tag: string | null, inputType: string | null, editable: boolean): FieldKind {
  const t = (tag ?? '').toLowerCase();
  if (t === 'input') {
    const it = (inputType ?? '').toLowerCase();
    if (TYPE_INTO.has(it)) return TYPE;
    if (SET_VALUE.has(it)) return SET;
    return NOT_FILLABLE;
  }
  if (t === 'textarea' || editable) return TYPE;
  return NOT_FILLABLE;
}

export function allowsMistype(tag: string | null, inputType: string | null): boolean {
  if ((tag ?? '').toLowerCase() !== 'input') return true;
  return !NO_MISTYPE.has((inputType ?? '').toLowerCase());
}

export function normalizeSetValue(inputType: string | null, value: string): string {
  let v = value.trim();
  if ((inputType ?? '').toLowerCase() === 'color') v = v.toLowerCase();
  return v;
}

/** Playwright rejects non-numeric text for input[type=number]; null = invalid. */
export function validateNumber(value: string): string | null {
  const v = value.trim();
  return Number.isNaN(Number(v)) ? null : v; // Playwright's own check
}

export function notFillableMessage(tag: string | null, inputType: string | null): string {
  if ((tag ?? '').toLowerCase() === 'input') return `Input of type "${(inputType ?? '').toLowerCase()}" cannot be filled`;
  return 'Element is not an <input>, <textarea> or [contenteditable] element';
}

// ---------------------------------------------------------------------------
// Native date/time editors
// ---------------------------------------------------------------------------

const DATE = '(?<year>\\d{4,6})-(?<month>\\d{2})-(?<day>\\d{2})';
const TIME = '(?<hour>\\d{2}):(?<minute>\\d{2})(?::(?<second>\\d{2})(?:\\.(?<millisecond>\\d{1,3}))?)?';
const DT_PATTERNS: Record<string, RegExp> = {
  date: new RegExp(`^${DATE}$`),
  month: /^(?<year>\d{4,6})-(?<month>\d{2})$/,
  week: /^(?<year>\d{4,6})-W(?<week>\d{2})$/,
  time: new RegExp(`^${TIME}$`),
  'datetime-local': new RegExp(`^${DATE}T${TIME}$`),
};

const FULL_WIDTH: Record<string, number> = { month: 2, day: 2, week: 2, hour: 2, minute: 2, second: 2, millisecond: 3 };

export interface DateTimeParts { [k: string]: any; hour24?: number; }

/** Split an HTML date/time value into the keystrokes per editor segment
 * (null for a malformed value). `hour` is the 12-hour form shown next to an
 * AM/PM segment; `hour24` keeps the original hour. */
export function datetimeParts(inputType: string, value: string): DateTimeParts | null {
  const re = DT_PATTERNS[inputType];
  const m = re ? re.exec(value) : null;
  if (!m || !m.groups) return null;
  const parts: DateTimeParts = {};
  for (const [k, v] of Object.entries(m.groups)) if (v !== undefined) parts[k] = v;
  if (parts.hour !== undefined) {
    const h = parseInt(parts.hour, 10);
    parts.hour24 = h;
    parts.hour12 = String((h % 12) || 12).padStart(2, '0');
    parts.hour = parts.hour12;
  }
  if (parts.millisecond !== undefined) parts.millisecond = String(parts.millisecond).padEnd(3, '0');
  return parts;
}

/** Pick the hour digits matching the editor (with or without AM/PM). */
export function use24h(parts: DateTimeParts, hasAmpm: boolean): DateTimeParts {
  if (parts.hour24 !== undefined && !hasAmpm) return { ...parts, hour: String(parts.hour24).padStart(2, '0') };
  return parts;
}

/** Whether typing this segment's digits moves focus to the next segment. */
export function segmentAutoAdvances(kind: string, parts: DateTimeParts, inputType = ''): boolean {
  if (inputType === 'month' && kind === 'month') return false; // shown as a month name
  const width = FULL_WIDTH[kind];
  return width !== undefined && String(parts[kind] ?? '').length >= width;
}
