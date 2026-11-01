/**
 * Free-key claim flow: claim code, key save, the no-key launch path and the
 * shared menu. Mirrors Python tests/test_free_claim.py.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import readline from "node:readline";

// The menu's "open in browser" must never launch a real browser from a test.
vi.mock("node:child_process", async (importOriginal) => ({
  ...(await importOriginal<typeof import("node:child_process")>()),
  spawn: vi.fn(() => ({ on: vi.fn(), unref: vi.fn() })),
}));

import {
  CLAIM_URL,
  FREE_CLAIM_LINK,
  FreeKeyAlreadyHeld,
  checkClaim,
  getClaimCode,
  saveLicenseKey,
} from "../src/license.js";
import {
  ensureBinary,
  promptLicenseKey,
  resetClaimPollStarted,
} from "../src/download.js";

let cacheDir: string;
const saved: Record<string, string | undefined> = {};
const ttyDesc = {
  stdin: Object.getOwnPropertyDescriptor(process.stdin, "isTTY"),
  stderr: Object.getOwnPropertyDescriptor(process.stderr, "isTTY"),
};

function setTTY(on: boolean): void {
  Object.defineProperty(process.stdin, "isTTY", { value: on, configurable: true });
  Object.defineProperty(process.stderr, "isTTY", { value: on, configurable: true });
}

beforeEach(() => {
  for (const k of ["CLOAKBROWSER_CACHE_DIR", "CLOAKBROWSER_LICENSE_KEY", "CLOAKBROWSER_BINARY_PATH"]) {
    saved[k] = process.env[k];
  }
  cacheDir = fs.mkdtempSync(path.join(os.tmpdir(), "cb-claim-"));
  process.env.CLOAKBROWSER_CACHE_DIR = cacheDir;
  delete process.env.CLOAKBROWSER_LICENSE_KEY;
  delete process.env.CLOAKBROWSER_BINARY_PATH;
  resetClaimPollStarted();
  setTTY(false);
});

afterEach(() => {
  vi.restoreAllMocks();
  for (const [k, v] of Object.entries(saved)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  for (const [name, desc] of Object.entries(ttyDesc)) {
    const stream = name === "stdin" ? process.stdin : process.stderr;
    if (desc) Object.defineProperty(stream, "isTTY", desc);
    else delete (stream as { isTTY?: boolean }).isTTY;
  }
  fs.rmSync(cacheDir, { recursive: true, force: true });
});

const mode = (p: string) => fs.statSync(p).mode & 0o777;

/** Route fetch by URL: claim answers come from `claims` in order. */
function mockServer(claims: Array<Record<string, unknown>>, validPlan: string | null = "free") {
  const calls: Array<{ url: string; body: string }> = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    calls.push({ url, body: String(init?.body ?? "") });
    if (url === CLAIM_URL) return Response.json(claims.shift() ?? { status: "pending" });
    if (url.includes("/api/license/validate")) {
      if (validPlan === null) throw new Error("server down");
      return Response.json({ valid: true, plan: validPlan, expires: null });
    }
    return new Response("not found", { status: 404 });
  });
  return calls;
}

const CTRL_C = "\x03";

/** Answer the menu's readline questions in order; no answers left = EOF; CTRL_C = SIGINT. */
function answer(...answers: string[]) {
  return vi.spyOn(readline, "createInterface").mockImplementation((() => {
    const handlers: Record<string, () => void> = {};
    return {
      question: (_q: string, cb: (a: string) => void) => {
        const next = answers.shift();
        if (next === undefined) setTimeout(() => handlers.close?.(), 0);
        else if (next === CTRL_C) handlers.SIGINT?.();
        else cb(next);
      },
      on: (event: string, handler: () => void) => {
        handlers[event] = handler;
      },
      close: () => { },
    };
  }) as unknown as typeof readline.createInterface);
}

/** process.exit that throws instead of ending the test run. */
function mockExit() {
  return vi.spyOn(process, "exit").mockImplementation(((code: number) => {
    throw new Error(`exit ${code}`);
  }) as never);
}

describe("claim code", () => {
  it("is reused and owner-only", () => {
    const code = getClaimCode();
    expect(code).toMatch(/^[A-Za-z0-9_-]{20,128}$/);
    expect(getClaimCode()).toBe(code);
    expect(mode(path.join(cacheDir, ".free_claim"))).toBe(0o600);
  });

  it("rotates after seven days", () => {
    const old = getClaimCode();
    const stale = new Date(Date.now() - 8 * 86_400_000);
    fs.utimesSync(path.join(cacheDir, ".free_claim"), stale, stale);
    expect(getClaimCode()).not.toBe(old);
  });

  it("a second caller reads the first caller's code", () => {
    // What a parallel worker that lost the hard-link race sees.
    fs.writeFileSync(path.join(cacheDir, ".free_claim"), "a".repeat(43), { mode: 0o600 });
    expect(getClaimCode()).toBe("a".repeat(43));
  });

  it("the link uses the fragment form (never reaches server logs)", () => {
    expect(FREE_CLAIM_LINK).toBe("https://cloakbrowser.dev/#claim=");
  });
});

describe("saveLicenseKey", () => {
  it("writes the key owner-only and retires the claim code", () => {
    getClaimCode();
    expect(saveLicenseKey("cb_abc")).toBe(true);
    const keyFile = path.join(cacheDir, "license.key");
    expect(fs.readFileSync(keyFile, "utf-8")).toBe("cb_abc\n");
    expect(mode(keyFile)).toBe(0o600);
    expect(fs.existsSync(path.join(cacheDir, ".free_claim"))).toBe(false);
  });

  it("rejects anything that is not a key", () => {
    expect(() => saveLicenseKey("<script>")).toThrow();
    expect(fs.existsSync(path.join(cacheDir, "license.key"))).toBe(false);
  });

  it("the background poll never overwrites an existing key, but retires the claim", () => {
    saveLicenseKey("cb_mine");
    getClaimCode();
    expect(saveLicenseKey("cb_claimed", { overwrite: false })).toBe(false);
    expect(fs.readFileSync(path.join(cacheDir, "license.key"), "utf-8")).toBe("cb_mine\n");
    // A kept claim would reinstall the key on a launch after `logout`.
    expect(fs.existsSync(path.join(cacheDir, ".free_claim"))).toBe(false);
  });

  it("pollClaim reports nothing saved when a key already exists", async () => {
    saveLicenseKey("cb_mine");
    mockServer([{ status: "ready", license_key: "cb_claimed" }]);
    const { pollClaim } = await import("../src/license.js");
    // undefined = the background poller prints no "free key saved"
    expect(await pollClaim(getClaimCode(), { deadline: Date.now() + 60_000 })).toBeUndefined();
    expect(fs.readFileSync(path.join(cacheDir, "license.key"), "utf-8")).toBe("cb_mine\n");
  });
});

describe("checkClaim", () => {
  it.each([
    [{ status: "pending" }, undefined],
    [{ status: "ready", license_key: "cb_ok" }, "cb_ok"],
    [{ status: "ready", license_key: "bad key" }, undefined], // trust boundary
  ])("%j -> %s", async (reply, expected) => {
    const calls = mockServer([reply]);
    expect(await checkClaim("c".repeat(32))).toBe(expected);
    // The code is a bearer secret: body, never the URL.
    expect(calls[0]!.url).toBe(CLAIM_URL);
    expect(JSON.parse(calls[0]!.body)).toEqual({ code: "c".repeat(32) });
  });

  it.each([[null], [[1, 2]], ["ready"]])("non-object JSON %j reads as pending", async (reply) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json(reply));
    expect(await checkClaim("c".repeat(32))).toBeUndefined();
  });

  it("a network error reads as pending", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("down"));
    expect(await checkClaim("c".repeat(32))).toBeUndefined();
  });

  it("has_key throws and retires the code", async () => {
    getClaimCode();
    mockServer([{ status: "has_key" }]);
    await expect(checkClaim("c".repeat(32))).rejects.toBeInstanceOf(FreeKeyAlreadyHeld);
    expect(fs.existsSync(path.join(cacheDir, ".free_claim"))).toBe(false);
  });
});

describe("ensureBinary with no key", () => {
  it("without a terminal throws with the link (stderr only)", async () => {
    mockServer([]);
    const err = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    const out = vi.spyOn(process.stdout, "write");
    await expect(ensureBinary()).rejects.toThrow(/cloakbrowser\.dev\/#claim=/);
    expect(err.mock.calls.join("")).toContain("#claim=");
    expect(out).not.toHaveBeenCalled(); // MCP servers own stdout
  });

  it("without a terminal, an email that already has a key says so", async () => {
    mockServer([{ status: "has_key" }]);
    vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    await expect(ensureBinary()).rejects.toThrow(/already has a free key/);
  });

  it("picks up a key confirmed since an earlier launch, without the menu", async () => {
    // validate fails afterwards: enough to prove the claimed key was used.
    const calls = mockServer([{ status: "ready", license_key: "cb_ready" }], null);
    const rl = answer();
    await expect(ensureBinary()).rejects.toThrow(/could not be validated/);
    expect(rl).not.toHaveBeenCalled();
    expect(fs.readFileSync(path.join(cacheDir, "license.key"), "utf-8")).toBe("cb_ready\n");
    expect(calls.some((c) => c.body.includes("cb_ready"))).toBe(true);
  });

  it("any key source skips the claim", async () => {
    process.env.CLOAKBROWSER_LICENSE_KEY = "cb_env";
    const calls = mockServer([], null);
    await expect(ensureBinary()).rejects.toThrow(/could not be validated/);
    expect(calls.some((c) => c.url === CLAIM_URL)).toBe(false);
  });

  it("in a terminal, Enter gets a free key by email and launches with it", async () => {
    setTTY(true);
    // first check, then the menu's poll answers ready right away
    const calls = mockServer([{ status: "pending" }, { status: "ready", license_key: "cb_claimed" }], null);
    vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    answer("");
    await expect(ensureBinary()).rejects.toThrow(/could not be validated/);
    expect(fs.readFileSync(path.join(cacheDir, "license.key"), "utf-8")).toBe("cb_claimed\n");
    expect(calls.some((c) => c.body.includes("cb_claimed"))).toBe(true);
  });
});

describe("promptLicenseKey (the menu)", () => {
  it("default option gets a free key and counts as this launch's welcome", async () => {
    mockServer([{ status: "ready", license_key: "cb_claimed" }]);
    const err = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    answer("");
    expect(await promptLicenseKey()).toBe("cb_claimed");
    const text = err.mock.calls.join("");
    expect(text).toContain("Welcome to CloakBrowser");
    expect(text).toContain("1) Get a free key");
    expect(fs.existsSync(path.join(cacheDir, ".welcome_shown"))).toBe(true);
  });

  it("option 2 pastes a key, asking again on a non-key", async () => {
    mockServer([]);
    vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    answer("2", "hello", "cb_mine");
    expect(await promptLicenseKey()).toBe("cb_mine");
    expect(fs.readFileSync(path.join(cacheDir, "license.key"), "utf-8")).toBe("cb_mine\n");
  });

  it("rejects an invalid pasted key and an unknown choice", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) =>
      Response.json({ valid: String(init?.body).includes("cb_good"), plan: "free", expires: null }),
    );
    vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    answer("7", "2", "cb_bad", "cb_good");
    expect(await promptLicenseKey()).toBe("cb_good");
  });

  it("an email that already has a key switches to the paste prompt", async () => {
    mockServer([{ status: "has_key" }]);
    const err = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    answer("1", "cb_old");
    expect(await promptLicenseKey()).toBe("cb_old");
    expect(err.mock.calls.join("")).toContain("already has a free key");
  });

  it("stdin closing rejects instead of hanging", async () => {
    vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    answer();
    await expect(promptLicenseKey()).rejects.toThrow(/stdin closed/);
  });

  it("Ctrl+C at the menu exits 130 with no link and no second welcome", async () => {
    setTTY(true);
    mockServer([]);
    const err = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    const exit = mockExit();
    answer(CTRL_C);
    await expect(ensureBinary()).rejects.toThrow("exit 130");
    expect(exit).toHaveBeenCalledWith(130);
    const text = err.mock.calls.join("");
    expect(text).not.toContain("#claim=");
    expect(text.split("Welcome to CloakBrowser").length - 1).toBe(1);
  });
});

describe("cloakbrowser login", () => {
  it("saves a pasted key owner-only", async () => {
    mockServer([]);
    vi.spyOn(console, "log").mockImplementation(() => { });
    const { cmdLogin } = await import("../src/cli.js");
    await cmdLogin(["cb_free"]);
    const keyFile = path.join(cacheDir, "license.key");
    expect(fs.readFileSync(keyFile, "utf-8")).toBe("cb_free\n");
    expect(mode(keyFile)).toBe(0o600);
  });

  it("refuses text that is not a key", async () => {
    mockServer([]);
    vi.spyOn(console, "error").mockImplementation(() => { });
    vi.spyOn(process, "exit").mockImplementation(((code: number) => {
      throw new Error(`exit ${code}`);
    }) as never);
    const { cmdLogin } = await import("../src/cli.js");
    await expect(cmdLogin(["not a key"])).rejects.toThrow("exit 1");
    expect(fs.existsSync(path.join(cacheDir, "license.key"))).toBe(false);
  });

  it("with stderr redirected, no menu (it would be invisible): usage + exit 2", async () => {
    Object.defineProperty(process.stdin, "isTTY", { value: true, configurable: true });
    vi.spyOn(console, "error").mockImplementation(() => { });
    mockExit();
    const rl = answer();
    const { cmdLogin } = await import("../src/cli.js");
    await expect(cmdLogin([])).rejects.toThrow("exit 2");
    expect(rl).not.toHaveBeenCalled();
  });

  it("logout also retires a pending claim", async () => {
    vi.spyOn(console, "log").mockImplementation(() => { });
    saveLicenseKey("cb_mine");
    getClaimCode();
    const { cmdLogout } = await import("../src/cli.js");
    cmdLogout();
    expect(fs.existsSync(path.join(cacheDir, ".free_claim"))).toBe(false);
    expect(fs.existsSync(path.join(cacheDir, "license.key"))).toBe(false);
  });
});
