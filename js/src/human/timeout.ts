/** Shared timeout-budget helpers for Playwright-style actions. */

export interface TimeoutBudget {
  readonly deadline: number;
}

export type TimeoutInput = number | TimeoutBudget;

/**
 * Resolve a raw Playwright timeout once at the action boundary. Keeping the
 * absolute deadline in an object prevents an exhausted internal budget (`0`)
 * from being mistaken for Playwright's raw `timeout: 0` (disabled timeout).
 */
export function timeoutBudget(timeout: TimeoutInput): TimeoutBudget {
  if (typeof timeout !== 'number') return timeout;
  return {
    deadline: timeout === 0 ? Number.POSITIVE_INFINITY : Date.now() + timeout,
  };
}

/** Return the non-negative time left in a shared action budget. */
export function remainingTimeout(budget: TimeoutBudget): number {
  return budget.deadline === Number.POSITIVE_INFINITY
    ? Number.POSITIVE_INFINITY
    : Math.max(0, budget.deadline - Date.now());
}

/** Cap a finite sub-budget without re-enabling a disabled timeout. */
export function capTimeout(budget: TimeoutBudget, maximum: number): TimeoutBudget {
  if (budget.deadline === Number.POSITIVE_INFINITY) return budget;
  return { deadline: Math.min(budget.deadline, Date.now() + maximum) };
}

/** Convert an internal budget back to Playwright's timeout format. */
export function toPlaywrightTimeout(budget: TimeoutBudget): number {
  const remaining = remainingTimeout(budget);
  return remaining === Number.POSITIVE_INFINITY ? 0 : Math.max(1, remaining);
}
