/**
 * Proxy rotation for cloakbrowser.
 *
 * Provides ProxyRotator — a proxy pool with multiple rotation strategies,
 * health tracking, and automatic failover.
 *
 * @example
 * ```ts
 * import { ProxyRotator, launch } from 'cloakbrowser';
 *
 * const rotator = new ProxyRotator([
 *   'http://user:pass@proxy1:8080',
 *   'http://user:pass@proxy2:8080',
 *   'http://user:pass@proxy3:8080',
 * ]);
 *
 * // Each call picks the next proxy
 * const browser = await launch({ proxy: rotator.next() });
 * const page = await browser.newPage();
 * await page.goto('https://example.com');
 * rotator.reportSuccess(rotator.current()!);
 * await browser.close();
 * ```
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Proxy rotation strategies. */
export type ProxyRotationStrategy =
  | "round_robin"
  | "random"
  | "least_used"
  | "least_failures";

/** A proxy value — either a URL string or a Playwright-style proxy object. */
export type ProxyValue =
  | string
  | { server: string; bypass?: string; username?: string; password?: string };

/** Configuration options for ProxyRotator. */
export interface ProxyRotatorOptions {
  /** Rotation strategy (default: "round_robin"). */
  strategy?: ProxyRotationStrategy;
  /** Seconds to sideline a proxy after max consecutive failures (default: 300). */
  cooldown?: number;
  /** Number of consecutive failures before cooldown (default: 3). */
  maxFailures?: number;
  /** Number of requests to stick with the same proxy before rotating (default: 1). */
  stickyCount?: number;
}

/** Usage statistics for a single proxy. */
export interface ProxyStats {
  proxy: string;
  useCount: number;
  failCount: number;
  consecutiveFails: number;
  available: boolean;
}

// ---------------------------------------------------------------------------
// Internal state
// ---------------------------------------------------------------------------

interface ProxyState {
  url: string;
  useCount: number;
  failCount: number;
  consecutiveFails: number;
  lastUsed: number;
  lastFailed: number;
  cooldownUntil: number;
}

function createState(url: string): ProxyState {
  return {
    url,
    useCount: 0,
    failCount: 0,
    consecutiveFails: 0,
    lastUsed: 0,
    lastFailed: 0,
    cooldownUntil: 0,
  };
}

function isAvailable(state: ProxyState): boolean {
  return performance.now() >= state.cooldownUntil;
}

// ---------------------------------------------------------------------------
// ProxyRotator
// ---------------------------------------------------------------------------

/**
 * Proxy rotator with health tracking.
 *
 * Supports four strategies:
 * - `round_robin`: Cycle through proxies in order (default).
 * - `random`: Pick a random proxy each time.
 * - `least_used`: Pick the proxy with the fewest uses.
 * - `least_failures`: Pick the proxy with the fewest failures.
 *
 * Proxies that fail consecutively are put on cooldown and automatically
 * excluded from selection until the cooldown period expires.
 */
export class ProxyRotator {
  private readonly proxies: ProxyValue[];
  private readonly states: Map<string, ProxyState>;
  private readonly strategy: ProxyRotationStrategy;
  private readonly cooldownMs: number;
  private readonly maxFailures: number;
  private readonly stickyCount: number;

  private rrIndex = 0;
  private stickyCounter = 0;
  private stickyCurrent: ProxyValue | null = null;

  constructor(proxies: ProxyValue[], options: ProxyRotatorOptions = {}) {
    if (!proxies.length) {
      throw new Error("proxies list must not be empty");
    }

    this.proxies = [...proxies];
    this.strategy = options.strategy ?? "round_robin";
    this.cooldownMs = (options.cooldown ?? 300) * 1000; // seconds → ms
    this.maxFailures = options.maxFailures ?? 3;
    this.stickyCount = Math.max(1, options.stickyCount ?? 1);

    this.states = new Map();
    for (const p of this.proxies) {
      ProxyRotator.validateProxy(p);
      const key = ProxyRotator.proxyKey(p);
      if (!this.states.has(key)) {
        this.states.set(key, createState(key));
      }
    }
  }

  // ------------------------------------------------------------------
  // Validation
  // ------------------------------------------------------------------

  /**
   * Validate that a proxy does not use an unsupported configuration.
   * Chromium does not support SOCKS5 proxy authentication.
   */
  private static validateProxy(proxy: ProxyValue): void {
    if (typeof proxy === "object") {
      const server = proxy.server ?? "";
      const hasAuth = !!(proxy.username || proxy.password);
      if (server.startsWith("socks5://") && hasAuth) {
        throw new Error(
          "SOCKS5 with authentication is not supported by Chromium. " +
            "Use the HTTP port of the same proxy, or a local SOCKS5 relay."
        );
      }
    } else {
      if (proxy.startsWith("socks5://") && proxy.includes("@")) {
        throw new Error(
          "SOCKS5 with authentication is not supported by Chromium. " +
            "Use the HTTP port of the same proxy, or a local SOCKS5 relay."
        );
      }
    }
  }

  // ------------------------------------------------------------------
  // Public API
  // ------------------------------------------------------------------

  /**
   * Return the next proxy according to the rotation strategy.
   *
   * @throws {Error} If all proxies are in cooldown.
   */
  next(): ProxyValue {
    // Sticky: keep returning the same proxy for `stickyCount` requests
    if (this.stickyCurrent !== null && this.stickyCounter < this.stickyCount) {
      const key = ProxyRotator.proxyKey(this.stickyCurrent);
      const state = this.states.get(key);
      if (state && isAvailable(state)) {
        this.stickyCounter++;
        state.useCount++;
        state.lastUsed = performance.now();
        return this.stickyCurrent;
      }
    }

    // Select next proxy
    const proxy = this.select();
    const key = ProxyRotator.proxyKey(proxy);
    const state = this.states.get(key)!;
    state.useCount++;
    state.lastUsed = performance.now();

    // Reset sticky tracking
    this.stickyCurrent = proxy;
    this.stickyCounter = 1;

    return proxy;
  }

  /** Return the currently sticky proxy, or null. */
  current(): ProxyValue | null {
    return this.stickyCurrent;
  }

  /** Report that a proxy request succeeded. Resets failure counters. */
  reportSuccess(proxy: ProxyValue): void {
    const key = ProxyRotator.proxyKey(proxy);
    const state = this.states.get(key);
    if (state) {
      state.consecutiveFails = 0;
      state.cooldownUntil = 0;
    }
  }

  /** Report that a proxy request failed. May trigger cooldown. */
  reportFailure(proxy: ProxyValue): void {
    const key = ProxyRotator.proxyKey(proxy);
    const state = this.states.get(key);
    if (state) {
      state.failCount++;
      state.consecutiveFails++;
      state.lastFailed = performance.now();
      if (state.consecutiveFails >= this.maxFailures) {
        state.cooldownUntil = performance.now() + this.cooldownMs;
      }
      // If current sticky proxy failed, force rotation
      if (
        this.stickyCurrent !== null &&
        ProxyRotator.proxyKey(this.stickyCurrent) === key
      ) {
        this.stickyCurrent = null;
        this.stickyCounter = 0;
      }
    }
  }

  /**
   * Execute a callback with an auto-selected proxy.
   * Reports success on return, failure on throw.
   */
  async withSession<T>(fn: (proxy: ProxyValue) => Promise<T>): Promise<T> {
    const proxy = this.next();
    try {
      const result = await fn(proxy);
      this.reportSuccess(proxy);
      return result;
    } catch (err) {
      this.reportFailure(proxy);
      throw err;
    }
  }

  /** Return usage statistics for all proxies. */
  stats(): ProxyStats[] {
    const seen = new Set<string>();
    const result: ProxyStats[] = [];
    for (const p of this.proxies) {
      const key = ProxyRotator.proxyKey(p);
      if (seen.has(key)) continue;
      seen.add(key);
      const state = this.states.get(key)!;
      result.push({
        proxy: maskProxy(key),
        useCount: state.useCount,
        failCount: state.failCount,
        consecutiveFails: state.consecutiveFails,
        available: isAvailable(state),
      });
    }
    return result;
  }

  /** Reset all proxy states (counters, cooldowns). */
  reset(): void {
    for (const state of this.states.values()) {
      state.useCount = 0;
      state.failCount = 0;
      state.consecutiveFails = 0;
      state.lastUsed = 0;
      state.lastFailed = 0;
      state.cooldownUntil = 0;
    }
    this.rrIndex = 0;
    this.stickyCounter = 0;
    this.stickyCurrent = null;
  }

  /** Add a proxy to the pool at runtime. */
  add(proxy: ProxyValue): void {
    ProxyRotator.validateProxy(proxy);
    this.proxies.push(proxy);
    const key = ProxyRotator.proxyKey(proxy);
    if (!this.states.has(key)) {
      this.states.set(key, createState(key));
    }
  }

  /**
   * Remove a proxy from the pool at runtime.
   * @throws {Error} If the proxy is not in the pool or would leave it empty.
   */
  remove(proxy: ProxyValue): void {
    const key = ProxyRotator.proxyKey(proxy);
    const filtered = this.proxies.filter(
      (p) => ProxyRotator.proxyKey(p) !== key
    );
    if (filtered.length === this.proxies.length) {
      throw new Error(`Proxy not in pool: ${maskProxy(key)}`);
    }
    if (filtered.length === 0) {
      throw new Error("Cannot remove last proxy — pool would be empty");
    }
    // Safe to apply — both checks passed
    this.proxies.length = 0;
    this.proxies.push(...filtered);
    this.states.delete(key);
    // Clamp round-robin index to new pool size
    if (this.rrIndex >= this.proxies.length) {
      this.rrIndex = 0;
    }
    // Clear sticky if it was the removed proxy
    if (
      this.stickyCurrent !== null &&
      ProxyRotator.proxyKey(this.stickyCurrent) === key
    ) {
      this.stickyCurrent = null;
      this.stickyCounter = 0;
    }
  }

  /** Number of proxies currently available (not in cooldown). */
  get availableCount(): number {
    let count = 0;
    for (const state of this.states.values()) {
      if (isAvailable(state)) count++;
    }
    return count;
  }

  /** Total number of proxies in the pool. */
  get size(): number {
    return this.proxies.length;
  }

  toString(): string {
    return `ProxyRotator(proxies=${this.proxies.length}, strategy=${this.strategy}, available=${this.availableCount})`;
  }

  // ------------------------------------------------------------------
  // Internal selection logic
  // ------------------------------------------------------------------

  private getAvailable(): Array<{ index: number; proxy: ProxyValue }> {
    const available: Array<{ index: number; proxy: ProxyValue }> = [];
    for (let i = 0; i < this.proxies.length; i++) {
      const key = ProxyRotator.proxyKey(this.proxies[i]);
      const state = this.states.get(key)!;
      if (isAvailable(state)) {
        available.push({ index: i, proxy: this.proxies[i] });
      }
    }
    return available;
  }

  private select(): ProxyValue {
    const available = this.getAvailable();
    if (!available.length) {
      throw new Error(
        `All ${this.proxies.length} proxies are in cooldown. ` +
          `Wait ${this.cooldownMs / 1000}s or call reset().`
      );
    }

    switch (this.strategy) {
      case "round_robin":
        return this.selectRoundRobin(available);
      case "random":
        return this.selectRandom(available);
      case "least_used":
        return this.selectLeastUsed(available);
      case "least_failures":
        return this.selectLeastFailures(available);
      default:
        throw new Error(`Unknown strategy: ${this.strategy}`);
    }
  }

  private selectRoundRobin(
    available: Array<{ index: number; proxy: ProxyValue }>
  ): ProxyValue {
    const n = this.proxies.length;
    for (let i = 0; i < n; i++) {
      const idx = this.rrIndex % n;
      this.rrIndex = (this.rrIndex + 1) % n;
      const proxy = this.proxies[idx];
      const key = ProxyRotator.proxyKey(proxy);
      const state = this.states.get(key)!;
      if (isAvailable(state)) {
        return proxy;
      }
    }
    return available[0].proxy;
  }

  private selectRandom(
    available: Array<{ index: number; proxy: ProxyValue }>
  ): ProxyValue {
    const idx = Math.floor(Math.random() * available.length);
    return available[idx].proxy;
  }

  private selectLeastUsed(
    available: Array<{ index: number; proxy: ProxyValue }>
  ): ProxyValue {
    let best = available[0];
    let bestCount = this.states.get(ProxyRotator.proxyKey(best.proxy))!.useCount;
    for (let i = 1; i < available.length; i++) {
      const count = this.states.get(
        ProxyRotator.proxyKey(available[i].proxy)
      )!.useCount;
      if (count < bestCount) {
        best = available[i];
        bestCount = count;
      }
    }
    return best.proxy;
  }

  private selectLeastFailures(
    available: Array<{ index: number; proxy: ProxyValue }>
  ): ProxyValue {
    let best = available[0];
    let bestCount = this.states.get(ProxyRotator.proxyKey(best.proxy))!
      .failCount;
    for (let i = 1; i < available.length; i++) {
      const count = this.states.get(
        ProxyRotator.proxyKey(available[i].proxy)
      )!.failCount;
      if (count < bestCount) {
        best = available[i];
        bestCount = count;
      }
    }
    return best.proxy;
  }

  // ------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------

  /**
   * Canonical string key for a proxy (for dedup/tracking).
   *
   * Uses '||' separator for dict proxies to avoid ambiguity with URL '@' characters.
   */
  static proxyKey(proxy: ProxyValue): string {
    if (typeof proxy === "object") {
      const username = proxy.username ?? "";
      return username ? `${proxy.server}||${username}` : proxy.server;
    }
    return proxy;
  }
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

/**
 * If the proxy is a ProxyRotator, call .next() to get the actual proxy.
 * Otherwise return it unchanged. Used internally by launch wrappers.
 */
export function resolveProxyRotator(
  proxy: ProxyValue | ProxyRotator | undefined | null
): string | { server: string; bypass?: string; username?: string; password?: string } | undefined {
  if (proxy instanceof ProxyRotator) {
    const next = proxy.next();
    // Ensure we return a plain string or object, never a ProxyRotator
    return typeof next === "string" ? next : next;
  }
  return proxy ?? undefined;
}

/**
 * Mask credentials in a proxy URL for logging/stats.
 *
 * Handles both plain proxy URLs and internal dict-key format ('server||username').
 * Also handles bare proxy strings without a scheme (e.g. 'user:pass@host:port').
 */
export function maskProxy(url: string): string {
  // Internal dict-key format: "http://server:port||username"
  if (url.includes("||")) {
    const sep = url.indexOf("||");
    return `${url.slice(0, sep)}||***`;
  }
  try {
    // Bare format: "user:pass@host:port" — no scheme.
    let normalized = url;
    const hadScheme = url.includes("://");
    if (!hadScheme && url.includes("@")) {
      normalized = `http://${url}`;
    }
    const parsed = new URL(normalized);
    if (parsed.username) {
      const hostPort = `${parsed.hostname}${parsed.port ? `:${parsed.port}` : ""}`;
      if (hadScheme) {
        return `${parsed.protocol}//***:***@${hostPort}`;
      }
      // Bare format — return without scheme to match original style
      return `***:***@${hostPort}`;
    }
    return url;
  } catch {
    return url;
  }
}
