/**
 * Stealth evaluate — run JS in a CDP isolated world.
 *
 * Provides page.stealthEvaluate(expression) on every page returned by
 * cloakbrowser launch functions.  Produces clean Error.stack traces (no
 * `eval at evaluate :302:` leak) and full variable isolation from main
 * world JS.  Context auto-recreates after navigation.
 *
 * The same StealthEval instances are reused by the humanize layer
 * (human/index.ts) for stealth DOM queries.
 */

import type { Browser, BrowserContext, Page, CDPSession } from 'playwright-core';


// ============================================================================
// Isolated world class
// ============================================================================

/**
 * Manages a CDP isolated execution context for DOM reads.
 * Produces clean Error.stack traces (no 'eval at evaluate :302:')
 * and is invisible to querySelector monkey-patches in the main world.
 *
 * Context ID is invalidated on navigation and auto-recreated on next call.
 */
export class StealthEval {
  private cdp: CDPSession | null = null;
  private contextId: number | null = null;
  private page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  private async ensureCdp(): Promise<CDPSession> {
    if (!this.cdp) {
      this.cdp = await this.page.context().newCDPSession(this.page);
    }
    return this.cdp;
  }

  private async createWorld(): Promise<number> {
    const cdp = await this.ensureCdp();
    const tree = await cdp.send('Page.getFrameTree');
    const frameId = tree.frameTree.frame.id;
    const result = await cdp.send('Page.createIsolatedWorld', {
      frameId,
      worldName: '',
      grantUniveralAccess: true,
    });
    const ctxId = result.executionContextId;
    this.contextId = ctxId;
    return ctxId;
  }

  /**
   * Evaluate a JS expression in the isolated world.
   * Auto-recreates the world if the context was invalidated (navigation).
   * Returns the result value, or undefined on failure.
   */
  async evaluate(expression: string): Promise<any> {
    if (this.contextId === null) {
      try {
        await this.createWorld();
      } catch {
        return undefined;
      }
    }

    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const cdp = await this.ensureCdp();
        const result = await cdp.send('Runtime.evaluate', {
          expression,
          contextId: this.contextId!,
          returnByValue: true,
        });

        if (result.exceptionDetails) {
          if (attempt === 0) {
            await this.createWorld();
            continue;
          }
          return undefined;
        }

        return result.result?.value;
      } catch {
        if (attempt === 0) {
          this.contextId = null;
          try {
            await this.createWorld();
          } catch {
            return undefined;
          }
          continue;
        }
        return undefined;
      }
    }
    return undefined;
  }

  /** Mark context as stale — call after navigation. */
  invalidate(): void {
    this.contextId = null;
  }

  /** Get the underlying CDP session (reused for Input.dispatchKeyEvent etc.). */
  async getCdpSession(): Promise<CDPSession> {
    return this.ensureCdp();
  }
}


// ============================================================================
// Page / context / browser patching
// ============================================================================

function patchPage(page: Page): void {
  if ((page as any).stealthEvaluate) return;
  const existing = (page as any)._stealthWorld;
  const stealth = existing instanceof StealthEval ? existing : new StealthEval(page);
  (page as any)._stealthWorld = stealth;
  (page as any).stealthEvaluate = stealth.evaluate.bind(stealth);
}

export function patchContext(context: BrowserContext): void {
  if ((context as any)._stealthEvalPatched) return;
  (context as any)._stealthEvalPatched = true;
  for (const p of context.pages()) {
    patchPage(p);
  }

  const origNewPage = context.newPage.bind(context);
  context.newPage = async (...args: Parameters<BrowserContext['newPage']>) => {
    const page = await origNewPage(...args);
    patchPage(page);
    return page;
  };

  context.on('page', (page: Page) => patchPage(page));
}

export function patchBrowser(browser: Browser): void {
  const origNewContext = browser.newContext.bind(browser);
  browser.newContext = async (...args: Parameters<Browser['newContext']>) => {
    const ctx = await origNewContext(...args);
    patchContext(ctx);
    return ctx;
  };

  const origNewPage = browser.newPage.bind(browser);
  browser.newPage = async (...args: Parameters<Browser['newPage']>) => {
    const page = await origNewPage(...args);
    patchContext(page.context());
    patchPage(page);
    return page;
  };
}
