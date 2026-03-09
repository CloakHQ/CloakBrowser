import { describe, it, expect } from "vitest";
import {
  ProxyRotator,
  maskProxy,
} from "../src/proxy-rotator.js";
import type { ProxyValue } from "../src/proxy-rotator.js";

const PROXIES: ProxyValue[] = [
  "http://user:pass@proxy1:8080",
  "http://user:pass@proxy2:8080",
  "http://user:pass@proxy3:8080",
];

// ---------------------------------------------------------------------------
// Construction
// ---------------------------------------------------------------------------

describe("ProxyRotator construction", () => {
  it("throws on empty list", () => {
    expect(() => new ProxyRotator([])).toThrow("must not be empty");
  });

  it("accepts single proxy", () => {
    const r = new ProxyRotator(["http://proxy:8080"]);
    expect(r.size).toBe(1);
    expect(r.next()).toBe("http://proxy:8080");
  });

  it("accepts dict proxies", () => {
    const r = new ProxyRotator([
      { server: "http://proxy:8080", username: "u", password: "p" },
    ]);
    const p = r.next();
    expect(typeof p).toBe("object");
    if (typeof p === "object") {
      expect(p.server).toBe("http://proxy:8080");
    }
  });

  it("toString includes info", () => {
    const r = new ProxyRotator(PROXIES);
    const s = r.toString();
    expect(s).toContain("proxies=3");
    expect(s).toContain("round_robin");
  });
});

// ---------------------------------------------------------------------------
// Round Robin
// ---------------------------------------------------------------------------

describe("round_robin strategy", () => {
  it("cycles through proxies", () => {
    const r = new ProxyRotator(PROXIES, { strategy: "round_robin" });
    const results = Array.from({ length: 6 }, () => r.next());
    expect(results).toEqual([...PROXIES, ...PROXIES]);
  });

  it("skips cooled-down proxies", () => {
    const r = new ProxyRotator(PROXIES, {
      strategy: "round_robin",
      maxFailures: 1,
      cooldown: 60,
    });
    const p = r.next();
    r.reportFailure(p);
    const results = Array.from({ length: 4 }, () => r.next());
    expect(results).not.toContain(PROXIES[0]);
  });
});

// ---------------------------------------------------------------------------
// Random
// ---------------------------------------------------------------------------

describe("random strategy", () => {
  it("returns valid proxies", () => {
    const r = new ProxyRotator(PROXIES, { strategy: "random" });
    for (let i = 0; i < 20; i++) {
      expect(PROXIES).toContain(r.next());
    }
  });

  it("skips cooled-down proxies", () => {
    const r = new ProxyRotator(PROXIES, {
      strategy: "random",
      maxFailures: 1,
      cooldown: 60,
    });
    r.reportFailure(PROXIES[0]);
    r.reportFailure(PROXIES[1]);
    for (let i = 0; i < 10; i++) {
      expect(r.next()).toBe(PROXIES[2]);
    }
  });
});

// ---------------------------------------------------------------------------
// Least Used
// ---------------------------------------------------------------------------

describe("least_used strategy", () => {
  it("distributes evenly", () => {
    const r = new ProxyRotator(PROXIES, { strategy: "least_used" });
    for (let i = 0; i < 9; i++) r.next();
    const stats = r.stats();
    const counts = stats.map((s) => s.useCount);
    expect(Math.max(...counts) - Math.min(...counts)).toBeLessThanOrEqual(1);
  });
});

// ---------------------------------------------------------------------------
// Least Failures
// ---------------------------------------------------------------------------

describe("least_failures strategy", () => {
  it("avoids failed proxies", () => {
    const r = new ProxyRotator(PROXIES, { strategy: "least_failures" });
    r.reportFailure(PROXIES[0]);
    r.reportFailure(PROXIES[0]);
    const result = r.next();
    expect([PROXIES[1], PROXIES[2]]).toContain(result);
  });
});

// ---------------------------------------------------------------------------
// Health tracking
// ---------------------------------------------------------------------------

describe("health tracking", () => {
  it("success resets consecutive failures", () => {
    const r = new ProxyRotator(PROXIES, { maxFailures: 3, cooldown: 60 });
    r.reportFailure(PROXIES[0]);
    r.reportFailure(PROXIES[0]);
    r.reportSuccess(PROXIES[0]);
    expect(r.stats()[0].consecutiveFails).toBe(0);
    expect(r.stats()[0].available).toBe(true);
  });

  it("triggers cooldown on max failures", () => {
    const r = new ProxyRotator(PROXIES, { maxFailures: 2, cooldown: 60 });
    r.reportFailure(PROXIES[0]);
    r.reportFailure(PROXIES[0]);
    expect(r.stats()[0].available).toBe(false);
  });

  it("throws when all in cooldown", () => {
    const r = new ProxyRotator(
      ["http://p1:80", "http://p2:80"],
      { maxFailures: 1, cooldown: 60 }
    );
    r.reportFailure("http://p1:80");
    r.reportFailure("http://p2:80");
    expect(() => r.next()).toThrow("All");
  });
});

// ---------------------------------------------------------------------------
// Sticky
// ---------------------------------------------------------------------------

describe("sticky count", () => {
  it("reuses proxy for stickyCount requests", () => {
    const r = new ProxyRotator(PROXIES, {
      strategy: "round_robin",
      stickyCount: 3,
    });
    const first = r.next();
    const second = r.next();
    const third = r.next();
    expect(first).toBe(second);
    expect(second).toBe(third);
    const fourth = r.next();
    expect(fourth).not.toBe(first);
  });
});

// ---------------------------------------------------------------------------
// withSession
// ---------------------------------------------------------------------------

describe("withSession", () => {
  it("reports success on normal return", async () => {
    const r = new ProxyRotator(PROXIES);
    await r.withSession(async (proxy) => {
      expect(PROXIES).toContain(proxy);
      return "ok";
    });
    expect(r.stats()[0].consecutiveFails).toBe(0);
  });

  it("reports failure on throw", async () => {
    const r = new ProxyRotator(PROXIES);
    await expect(
      r.withSession(async () => {
        throw new Error("boom");
      })
    ).rejects.toThrow("boom");
    const failedProxy = r.stats().find((s) => s.failCount > 0);
    expect(failedProxy).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// Dynamic pool
// ---------------------------------------------------------------------------

describe("dynamic pool", () => {
  it("adds proxy", () => {
    const r = new ProxyRotator(PROXIES.slice(0, 2));
    expect(r.size).toBe(2);
    r.add("http://new:8080");
    expect(r.size).toBe(3);
  });

  it("removes proxy", () => {
    const r = new ProxyRotator(PROXIES);
    r.remove(PROXIES[0]);
    expect(r.size).toBe(2);
  });

  it("throws on remove nonexistent", () => {
    const r = new ProxyRotator(PROXIES);
    expect(() => r.remove("http://nonexistent:9999")).toThrow("not in pool");
  });

  it("throws on remove last", () => {
    const r = new ProxyRotator(["http://only:8080"]);
    expect(() => r.remove("http://only:8080")).toThrow("pool would be empty");
  });
});

// ---------------------------------------------------------------------------
// Stats and reset
// ---------------------------------------------------------------------------

describe("stats and reset", () => {
  it("returns correct structure", () => {
    const r = new ProxyRotator(PROXIES);
    r.next();
    const stats = r.stats();
    expect(stats).toHaveLength(3);
    for (const s of stats) {
      expect(s).toHaveProperty("proxy");
      expect(s).toHaveProperty("useCount");
      expect(s).toHaveProperty("failCount");
      expect(s).toHaveProperty("available");
    }
  });

  it("masks credentials in stats", () => {
    const r = new ProxyRotator(PROXIES);
    const stats = r.stats();
    for (const s of stats) {
      expect(s.proxy).not.toContain("pass");
    }
  });

  it("reset clears all state", () => {
    const r = new ProxyRotator(PROXIES);
    for (let i = 0; i < 5; i++) r.next();
    r.reportFailure(PROXIES[0]);
    r.reset();
    for (const s of r.stats()) {
      expect(s.useCount).toBe(0);
      expect(s.failCount).toBe(0);
    }
  });
});

// ---------------------------------------------------------------------------
// Available count
// ---------------------------------------------------------------------------

describe("availableCount", () => {
  it("all available initially", () => {
    const r = new ProxyRotator(PROXIES);
    expect(r.availableCount).toBe(3);
  });

  it("decreases with cooldown", () => {
    const r = new ProxyRotator(PROXIES, { maxFailures: 1, cooldown: 60 });
    r.reportFailure(PROXIES[0]);
    expect(r.availableCount).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// current() method
// ---------------------------------------------------------------------------

describe("current()", () => {
  it("returns null initially", () => {
    const r = new ProxyRotator(PROXIES);
    expect(r.current()).toBeNull();
  });

  it("returns last proxy after next()", () => {
    const r = new ProxyRotator(PROXIES, { strategy: "round_robin" });
    const proxy = r.next();
    expect(r.current()).toBe(proxy);
  });

  it("useful for report after launch(proxy=rotator)", () => {
    const r = new ProxyRotator(PROXIES, { strategy: "round_robin" });
    const proxy = r.next();
    const current = r.current()!;
    expect(current).toBe(proxy);
    r.reportSuccess(current);
    expect(r.stats()[0].consecutiveFails).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// remove() edge cases
// ---------------------------------------------------------------------------

describe("remove() edge cases", () => {
  it("preserves state on last proxy error", () => {
    const r = new ProxyRotator(["http://only:8080"]);
    expect(() => r.remove("http://only:8080")).toThrow("pool would be empty");
    expect(r.size).toBe(1);
    expect(r.next()).toBe("http://only:8080");
  });

  it("clears sticky for removed proxy", () => {
    const r = new ProxyRotator(PROXIES, { strategy: "round_robin", stickyCount: 5 });
    const first = r.next();
    r.remove(first);
    const second = r.next();
    expect(second).not.toBe(first);
  });
});

// ---------------------------------------------------------------------------
// maskProxy — dict key format
// ---------------------------------------------------------------------------

describe("maskProxy dict key format", () => {
  it("masks username part of dict keys", () => {
    const masked = maskProxy("http://proxy:8080||admin");
    expect(masked).not.toContain("admin");
    expect(masked).toContain("***");
    expect(masked).toBe("http://proxy:8080||***");
  });

  it("preserves URL without dict key separator", () => {
    expect(maskProxy("http://proxy:8080")).toBe("http://proxy:8080");
  });
});

// ---------------------------------------------------------------------------
// maskProxy utility
// ---------------------------------------------------------------------------

describe("maskProxy", () => {
  it("masks credentials", () => {
    const masked = maskProxy("http://user:pass@host:8080");
    expect(masked).not.toContain("pass");
    expect(masked).toContain("***");
  });

  it("preserves URL without credentials", () => {
    expect(maskProxy("http://host:8080")).toBe("http://host:8080");
  });

  it("handles dict key format", () => {
    const key = ProxyRotator.proxyKey({
      server: "http://p:80",
      username: "u",
    });
    expect(key).toBe("http://p:80||u");
  });
});

// ---------------------------------------------------------------------------
// ProxyRotator.proxyKey static method
// ---------------------------------------------------------------------------

describe("ProxyRotator.proxyKey", () => {
  it("returns string as-is", () => {
    expect(ProxyRotator.proxyKey("http://proxy:8080")).toBe(
      "http://proxy:8080"
    );
  });

  it("builds key from dict with username", () => {
    expect(
      ProxyRotator.proxyKey({ server: "http://p:80", username: "u" })
    ).toBe("http://p:80||u");
  });

  it("builds key from dict without username", () => {
    expect(ProxyRotator.proxyKey({ server: "http://p:80" })).toBe(
      "http://p:80"
    );
  });
});

// ---------------------------------------------------------------------------
// Bare proxy format (user:pass@host:port without scheme)
// ---------------------------------------------------------------------------

describe("bare proxy format", () => {
  it("maskProxy masks bare format credentials", () => {
    const masked = maskProxy("user:pass@proxy1.example.com:5610");
    expect(masked).not.toContain("pass");
    expect(masked).not.toContain("user");
    expect(masked).toContain("***");
    expect(masked).toContain("proxy1.example.com:5610");
  });

  it("maskProxy preserves bare host:port without credentials", () => {
    expect(maskProxy("proxy1.example.com:5610")).toBe("proxy1.example.com:5610");
  });

  it("rotator accepts bare proxy strings", () => {
    const r = new ProxyRotator(["user:pass@proxy1:8080"]);
    const proxy = r.next();
    expect(proxy).toBe("user:pass@proxy1:8080");
  });

  it("stats masks bare proxy credentials", () => {
    const r = new ProxyRotator(["user:secret@proxy1.example.com:5610"]);
    r.next();
    const stats = r.stats();
    expect(stats[0].proxy).not.toContain("secret");
    expect(stats[0].proxy).not.toContain("user");
  });
});

// ---------------------------------------------------------------------------
// SOCKS5 proxy format
// ---------------------------------------------------------------------------

describe("socks5 format", () => {
  it("maskProxy preserves socks5 without credentials", () => {
    const masked = maskProxy("socks5://proxy:15610");
    expect(masked).toBe("socks5://proxy:15610");
  });

  it("rotator accepts socks5 without auth", () => {
    const r = new ProxyRotator(["socks5://proxy:15610"]);
    const proxy = r.next();
    expect(typeof proxy).toBe("string");
    expect((proxy as string).startsWith("socks5://")).toBe(true);
  });

  it("socks5 with auth throws", () => {
    expect(() => new ProxyRotator(["socks5://user:pass@proxy:15610"])).toThrow(
      "SOCKS5 with authentication"
    );
  });
});
