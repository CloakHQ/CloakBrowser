/**
 * Human-like behavioral layer for cloakbrowser (JS/TS, Playwright).
 *
 * Activated via `humanize: true` in launch() / launchContext().
 *
 * Every humanized action (page, frame, frameLocator, locator, element handle,
 * mouse, keyboard) runs through one engine (engine.ts):
 *
 * - elements are resolved by Playwright's own selector engine running in a
 *   CDP isolated world per frame (world.ts / injected.ts) -- full selector
 *   syntax (role, label, text, `>>` chains, filters, frame locators) and
 *   strict mode, with no page-observable trace;
 * - scrolling uses mouse-wheel bursts, pointer movement uses Bezier curves,
 *   every press is preceded by a hit-target check (also through iframes);
 * - Playwright's options and timeouts are honoured; failures throw
 *   Playwright `Error` / `TimeoutError` instead of falling back to
 *   Playwright's own page-visible actions.
 */

export { HumanConfig, resolveConfig, mergeConfig } from './config.js';
export { humanMove, humanClick, clickTarget, humanIdle } from './mouse.js';
export { humanType } from './keyboard.js';
export { CursorState, Human } from './engine.js';
export { patchPage, patchContext, patchBrowser } from './patch.js';
export { StealthWorldError } from './world.js';
export {
  ActionabilityError, ElementNotAttachedError, ElementNotVisibleError,
  ElementNotStableError, ElementNotEnabledError, ElementNotEditableError,
  ElementNotReceivingEventsError, ElementTargetChangedError,
  StealthDomError, UnsupportedHumanizeSelectorError,
  StealthWorldUnavailableError, StealthEvaluationError,
} from './errors.js';
