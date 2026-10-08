/**
 * CDP isolated worlds for every frame of a page (main, same-process, OOPIF).
 *
 * Each frame gets one isolated world per document, created through
 * `Page.createIsolatedWorld` on the CDP session that owns the frame. Into that
 * world we install Playwright's InjectedScript (see injected.ts) and a small
 * helper object:
 *
 * - frame <-> CDP frame id mapping uses `Page.getFrameTree` only;
 * - iframe owner elements are reached via `DOM.getFrameOwner` +
 *   `DOM.resolveNode` straight into the parent frame's isolated world;
 * - elements are kept in a world-local registry and addressed by integer ids.
 *
 * Port of cloakbrowser/human/world.py.
 */

import type { CDPSession, Frame, Page } from 'playwright-core';
import { GLOBAL, buildInstallJs, findInjectedLiteral } from './injected.js';
import { HELPERS, HELPERS_JS } from './worldHelpers.js';

export { HELPERS };

let decodedSource: string | null = null;

export class StealthWorldError extends Error {
  constructor(message: string) { super(message); this.name = 'StealthWorldError'; }
}

export class StaleElement extends Error {
  constructor() { super('element is not attached to the DOM'); this.name = 'StaleElement'; }
}

export interface Rect { x: number; y: number; width: number; height: number; }

const STALE_MARKERS = [
  'Cannot find context', 'Execution context was destroyed', 'Inspected target navigated',
  'cloak:stale-world', 'Cannot find default execution context',
];
const isStale = (e: unknown) => STALE_MARKERS.some((s) => String((e as any)?.message ?? e).includes(s));

interface FrameRec { session: CDPSession; cdpId: string; ctx: number | null; }

export function intersect(a: Rect, b: Rect): Rect {
  const x0 = Math.max(a.x, b.x), y0 = Math.max(a.y, b.y);
  const x1 = Math.min(a.x + a.width, b.x + b.width);
  const y1 = Math.min(a.y + a.height, b.y + b.height);
  return { x: x0, y: y0, width: Math.max(0, x1 - x0), height: Math.max(0, y1 - y0) };
}

function isDescendant(frame: Frame, ancestor: Frame): boolean {
  for (let p = frame.parentFrame(); p; p = p.parentFrame()) if (p === ancestor) return true;
  return false;
}

function findNode(tree: any, cdpId: string): any {
  if (tree.frame.id === cdpId) return tree;
  for (const c of tree.childFrames ?? []) {
    const f = findNode(c, cdpId);
    if (f) return f;
  }
  return null;
}

/**
 * Pick the CDP child frame for a Playwright frame. Playwright and CDP list
 * child frames in attach order; frames sharing the same (name, url) are
 * matched by their position within that group.
 */
export function matchChild(frame: Frame, parent: Frame, kids: any[]): string | null {
  const keyPw = (f: Frame) => `${f.name()}\u0000${f.url()}`;
  const keyCdp = (k: any) => `${k.name ?? ''}\u0000${(k.url ?? '') + (k.urlFragment ?? '')}`;
  const want = keyPw(frame);
  const cands = kids.filter((k) => keyCdp(k) === want);
  const siblings = parent.childFrames();
  const peers = siblings.filter((f) => keyPw(f) === want);
  if (cands.length && peers.includes(frame) && cands.length === peers.length) return cands[peers.indexOf(frame)].id;
  if (cands.length === 1) return cands[0].id;
  if (kids.length === siblings.length && siblings.includes(frame)) return kids[siblings.indexOf(frame)].id;
  return null;
}

async function release(session: CDPSession, objectId: string): Promise<void> {
  try { await session.send('Runtime.releaseObject', { objectId }); } catch { /* gone */ }
}

/** Isolated worlds for all frames of one Playwright page. */
export class Worlds {
  readonly page: Page;
  private _session: CDPSession | null = null;
  private _sessionP: Promise<CDPSession> | null = null;
  private frames = new Map<Frame, FrameRec>();
  private locating = new Map<Frame, Promise<FrameRec>>();
  private lock: Promise<unknown> = Promise.resolve();

  constructor(page: Page) {
    this.page = page;
    try {
      page.on('framenavigated', (f) => this.invalidate(f));
      page.on('framedetached', (f) => this.invalidate(f));
    } catch { /* emitter missing in mocks */ }
  }

  // -- sessions / frame mapping -------------------------------------------

  async session(): Promise<CDPSession> {
    if (this._session) return this._session;
    if (!this._sessionP) this._sessionP = this.page.context().newCDPSession(this.page);
    try {
      this._session = await this._sessionP;
    } finally {
      this._sessionP = null;
    }
    return this._session;
  }

  /** Forget worlds of `frame` and its descendants (all when undefined). */
  invalidate(frame?: Frame): void {
    if (!frame) { this.frames.clear(); return; }
    for (const f of [...this.frames.keys()]) if (f === frame || isDescendant(f, frame)) this.frames.delete(f);
  }

  private async locate(frame: Frame): Promise<FrameRec> {
    const rec = this.frames.get(frame);
    if (rec) return rec;
    const pending = this.locating.get(frame);
    if (pending) return pending;
    const p = (async () => {
      if (frame.isDetached()) throw new Error('Frame was detached');
      const parent = frame.parentFrame();
      let r: FrameRec;
      if (!parent) {
        const session = await this.session();
        const tree: any = await session.send('Page.getFrameTree');
        r = { session, cdpId: tree.frameTree.frame.id, ctx: null };
      } else {
        r = await this.locateChild(frame, parent);
      }
      this.frames.set(frame, r);
      return r;
    })();
    this.locating.set(frame, p);
    try { return await p; } finally { this.locating.delete(frame); }
  }

  private async locateChild(frame: Frame, parent: Frame): Promise<FrameRec> {
    let own: CDPSession | null = null;
    try { // out-of-process iframe: it has its own target/session
      own = await this.page.context().newCDPSession(frame);
    } catch { own = null; }
    if (own) {
      const tree: any = await own.send('Page.getFrameTree');
      return { session: own, cdpId: tree.frameTree.frame.id, ctx: null };
    }
    const prec = await this.locate(parent);
    const tree: any = await prec.session.send('Page.getFrameTree');
    const node = findNode(tree.frameTree, prec.cdpId);
    const kids = (node?.childFrames ?? []).map((k: any) => k.frame);
    const cdpId = matchChild(frame, parent, kids);
    if (!cdpId) throw new Error('cloakbrowser humanize: could not map the frame to a CDP frame');
    return { session: prec.session, cdpId, ctx: null };
  }

  async frameForCdpId(parent: Frame, cdpId: string): Promise<Frame | null> {
    for (const child of parent.childFrames()) {
      try { if ((await this.locate(child)).cdpId === cdpId) return child; } catch { /* skip */ }
    }
    return null;
  }

  // -- world lifecycle ----------------------------------------------------

  async ready(frame: Frame): Promise<FrameRec> {
    const rec = await this.locate(frame);
    if (rec.ctx !== null) return rec;
    const run = this.lock.then(async () => {
      if (rec.ctx !== null) return;
      const res: any = await rec.session.send('Page.createIsolatedWorld', {
        frameId: rec.cdpId, worldName: '', grantUniveralAccess: true,
      });
      const ctx = res.executionContextId as number;
      await this.install(rec.session, ctx);
      rec.ctx = ctx;
    });
    this.lock = run.catch(() => undefined);
    await run;
    return rec;
  }

  private async install(session: CDPSession, ctx: number): Promise<void> {
    if (decodedSource === null) decodedSource = await Worlds.rawEval(session, ctx, findInjectedLiteral());
    await Worlds.rawEval(session, ctx, buildInstallJs(decodedSource!));
    await Worlds.rawEval(session, ctx, HELPERS_JS);
  }

  static async rawEval(session: CDPSession, ctx: number, expression: string, byValue = true): Promise<any> {
    const res: any = await session.send('Runtime.evaluate', {
      expression, contextId: ctx, returnByValue: byValue, awaitPromise: true,
    });
    if (res.exceptionDetails) {
      const det = res.exceptionDetails;
      const desc: string = det.exception?.description || det.text || '';
      if (desc.includes('cloak:stale-element')) throw new StaleElement();
      throw new StealthWorldError(`cloakbrowser humanize: isolated-world script failed: ${desc.split('\n')[0]}`);
    }
    return byValue ? res.result?.value : res.result;
  }

  // -- evaluation ---------------------------------------------------------

  /** Evaluate in `frame`'s isolated world; recreate the world once if stale. */
  async evaluate(frame: Frame, expression: string, byValue = true): Promise<any> {
    for (let attempt = 0; attempt < 2; attempt++) {
      const rec = await this.ready(frame);
      try {
        return await Worlds.rawEval(rec.session, rec.ctx!, expression, byValue);
      } catch (e) {
        if (e instanceof StaleElement) throw e;
        if (attempt === 0 && isStale(e)) { rec.ctx = null; continue; }
        throw e;
      }
    }
    throw new StealthWorldError('cloakbrowser humanize: isolated world unavailable');
  }

  call(frame: Frame, method: string, ...args: unknown[]): Promise<any> {
    return this.evaluate(frame, `${HELPERS}.${method}(${args.map((a) => JSON.stringify(a)).join(', ')})`);
  }

  async elementObjectId(frame: Frame, id: number): Promise<[CDPSession, string]> {
    const rec = await this.ready(frame);
    const obj = await Worlds.rawEval(rec.session, rec.ctx!, `${HELPERS}.el(${Math.trunc(id)})`, false);
    return [rec.session, obj.objectId];
  }

  /**
   * Segments of a native date/time editor in visual order, with centres
   * relative to the input's border box. They live in the input's closed
   * user-agent shadow root; CDP's DOM domain (`pierce`) sees them without
   * running any script in the page.
   */
  async editorFields(frame: Frame, id: number): Promise<{ kind: string; dx: number; dy: number }[]> {
    const [session, objectId] = await this.elementObjectId(frame, id);
    let node: any, own: number[];
    try {
      node = (await session.send('DOM.describeNode', { objectId, depth: -1, pierce: true }) as any).node;
      own = (await session.send('DOM.getBoxModel', { objectId }) as any).model.border;
    } finally {
      await release(session, objectId);
    }
    const out: { kind: string; dx: number; dy: number }[] = [];
    const walk = async (n: any): Promise<void> => {
      const attrs: string[] = n.attributes ?? [];
      let pseudo = '';
      for (let i = 0; i + 1 < attrs.length; i += 2) if (attrs[i] === 'pseudo') pseudo = attrs[i + 1];
      if (pseudo.startsWith('-webkit-datetime-edit-') && pseudo.endsWith('-field') && !pseudo.includes('wrapper')) {
        const q = (await session.send('DOM.getBoxModel', { backendNodeId: n.backendNodeId }) as any).model.border;
        out.push({
          kind: pseudo.slice('-webkit-datetime-edit-'.length, -'-field'.length),
          dx: (q[0] + q[2]) / 2 - own[0], dy: (q[1] + q[5]) / 2 - own[1],
        });
      }
      for (const c of [...(n.children ?? []), ...(n.shadowRoots ?? [])]) await walk(c);
    };
    await walk(node);
    out.sort((a, b) => (Math.round(a.dy / 4) - Math.round(b.dy / 4)) || (a.dx - b.dx));
    return out;
  }

  /** Child frame owned by the <iframe> element `id` in `frame`. */
  async contentFrame(frame: Frame, id: number): Promise<Frame | null> {
    const [session, objectId] = await this.elementObjectId(frame, id);
    let node: any;
    try {
      node = (await session.send('DOM.describeNode', { objectId }) as any).node;
    } finally {
      await release(session, objectId);
    }
    if (!node.frameId) return null;
    return this.frameForCdpId(frame, node.frameId);
  }

  // -- geometry across frames ---------------------------------------------

  /** Call `declaration` with `this` = the frame's <iframe> element, inside
   * the parent frame's isolated world. */
  private async ownerCall(frame: Frame, declaration: string, ...args: unknown[]): Promise<any> {
    const parent = frame.parentFrame()!;
    const rec = await this.locate(frame);
    const prec = await this.ready(parent);
    const owner: any = await prec.session.send('DOM.getFrameOwner', { frameId: rec.cdpId });
    const obj: any = (await prec.session.send('DOM.resolveNode', {
      backendNodeId: owner.backendNodeId, executionContextId: prec.ctx!,
    } as any) as any).object;
    let res: any;
    try {
      res = await prec.session.send('Runtime.callFunctionOn', {
        objectId: obj.objectId, functionDeclaration: declaration,
        arguments: args.map((value) => ({ value })), returnByValue: true,
      });
    } finally {
      await release(prec.session, obj.objectId);
    }
    if (res.exceptionDetails) throw new StealthWorldError('cloakbrowser humanize: frame owner evaluation failed');
    return res.result?.value;
  }

  async viewport(): Promise<{ width: number; height: number }> {
    const size = this.page.viewportSize();
    if (size && size.width) return { width: size.width, height: size.height };
    const doc = await this.call(this.page.mainFrame(), 'doc');
    return { width: doc.width, height: doc.height };
  }

  /** `[offsetX, offsetY, clip]`: the frame's origin in viewport coordinates
   * and the visible part of it (intersection of all ancestor iframe content
   * boxes and the viewport). */
  async frameGeometry(frame: Frame): Promise<[number, number, Rect]> {
    const parent = frame.parentFrame();
    if (!parent) {
      const vp = await this.viewport();
      return [0, 0, { x: 0, y: 0, width: vp.width, height: vp.height }];
    }
    const [px, py, pclip] = await this.frameGeometry(parent);
    const box = await this.ownerCall(frame, `function () { return ${HELPERS}.ownerContent.call(this); }`);
    const ox = px + box.x, oy = py + box.y;
    return [ox, oy, intersect(pclip, { x: ox, y: oy, width: box.width, height: box.height })];
  }

  /** Check that the viewport point hits each ancestor <iframe> owner. */
  async ownersHit(frame: Frame, vx: number, vy: number): Promise<string | null> {
    let child = frame;
    while (child.parentFrame()) {
      const [px, py] = await this.frameGeometry(child.parentFrame()!);
      const desc = await this.ownerCall(
        child,
        `function (x, y) { const r = globalThis.${GLOBAL}.expectHitTarget({ x, y }, this);` +
        ` return r === 'done' ? null : r.hitTargetDescription; }`,
        vx - px, vy - py,
      );
      if (desc) return desc;
      child = child.parentFrame()!;
    }
    return null;
  }
}
