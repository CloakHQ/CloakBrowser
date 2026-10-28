/**
 * Error classes kept for API compatibility. The unified engine throws
 * Playwright-style `Error` / `TimeoutError` (with a call log) instead; these
 * classes remain exported so existing `instanceof` imports keep compiling.
 */

export class ActionabilityError extends Error {
  selector: string;
  check: string;

  constructor(selector: string, check: string, message: string) {
    super(`Element ${JSON.stringify(selector)} failed ${check} check: ${message}`);
    this.name = 'ActionabilityError';
    this.selector = selector;
    this.check = check;
  }
}

export class ElementNotAttachedError extends ActionabilityError {
  constructor(selector: string) {
    super(selector, 'attached', 'element not found in DOM');
    this.name = 'ElementNotAttachedError';
  }
}

export class ElementNotVisibleError extends ActionabilityError {
  constructor(selector: string) {
    super(selector, 'visible', 'element is not visible');
    this.name = 'ElementNotVisibleError';
  }
}

export class ElementNotStableError extends ActionabilityError {
  constructor(selector: string) {
    super(selector, 'stable', 'element position is still changing');
    this.name = 'ElementNotStableError';
  }
}

export class ElementNotEnabledError extends ActionabilityError {
  constructor(selector: string) {
    super(selector, 'enabled', 'element is disabled');
    this.name = 'ElementNotEnabledError';
  }
}

export class ElementNotEditableError extends ActionabilityError {
  constructor(selector: string) {
    super(selector, 'editable', 'element is not editable');
    this.name = 'ElementNotEditableError';
  }
}

export class ElementNotReceivingEventsError extends ActionabilityError {
  coveringTag: string;
  constructor(selector: string, coveringTag: string = 'unknown') {
    super(selector, 'pointer_events', `element is covered by <${coveringTag}>`);
    this.name = 'ElementNotReceivingEventsError';
    this.coveringTag = coveringTag;
  }
}

export class ElementTargetChangedError extends ActionabilityError {
  constructor(selector: string) {
    super(selector, 'target_identity', 'selector resolved to a different element before input dispatch');
    this.name = 'ElementTargetChangedError';
  }
}

// Raised by the previous humanize layer; the engine no longer throws them.

export class StealthDomError extends Error {
  constructor(message: string) {
    super(message);
    this.name = new.target.name;
  }
}

export class UnsupportedHumanizeSelectorError extends StealthDomError {
  constructor(selector: string) {
    super(`Humanized selector ${JSON.stringify(selector)} is not supported`);
  }
}

export class StealthWorldUnavailableError extends StealthDomError {
  constructor() {
    super('Humanized DOM read requires an active isolated world');
  }
}

export class StealthEvaluationError extends StealthDomError {
  constructor(selector: string) {
    super(`Isolated-world DOM evaluation failed for ${JSON.stringify(selector)}`);
  }
}
