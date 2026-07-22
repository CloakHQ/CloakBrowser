import { describe, it, expect } from "vitest";
import { spawn, type ChildProcess } from "node:child_process";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import fs from "node:fs";

// SLOW TESTS — require a real browser (run with: SLOW=1 vitest run --testTimeout=60000).
// Strategy: start the CloakBrowser binary with a debug port (what cloakserve does
// under the hood), then connect() back to it over CDP — no Pro license, no live sites.
const SLOW = process.env.SLOW === "1";
const describeIfSlow = SLOW ? describe : describe.skip;

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.listen(0, "127.0.0.1", () => {
      const port = (srv.address() as net.AddressInfo).port;
      srv.close(() => resolve(port));
    });
    srv.on("error", reject);
  });
}

async function remoteAlive(port: number): Promise<boolean> {
  try {
    const res = await fetch(`http://127.0.0.1:${port}/json/version`);
    return res.ok;
  } catch {
    return false;
  }
}

async function waitForCdp(port: number, timeoutMs = 30000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await remoteAlive(port)) return;
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`CDP endpoint on :${port} not ready within ${timeoutMs}ms`);
}

async function startBrowser(): Promise<{ endpoint: string; port: number; proc: ChildProcess }> {
  const { ensureBinary } = await import("../src/download.js");
  const binary = await ensureBinary();
  const port = await freePort();
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "cloak-connect-"));
  const proc = spawn(
    binary,
    [
      "--headless=new",
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${dataDir}`,
      "--no-first-run",
      "--no-default-browser-check",
      "--no-sandbox",
    ],
    { stdio: "ignore" }
  );
  await waitForCdp(port);
  return { endpoint: `http://127.0.0.1:${port}`, port, proc };
}

describeIfSlow("connect() — Playwright", () => {
  it("returns a usable browser and honors humanize + no-viewport", async () => {
    const { connect } = await import("../src/index.js");
    const { endpoint, proc } = await startBrowser();
    try {
      const browser = await connect(endpoint, { humanize: true });
      try {
        expect(browser.isConnected()).toBe(true);
        const page = await browser.newPage();
        await page.goto("data:text/html,<title>hi</title>");
        expect(await page.title()).toBe("hi");
        // defaultNoViewport: true → no emulated viewport.
        expect(page.viewportSize()).toBeNull();
      } finally {
        await browser.close();
      }
    } finally {
      proc.kill();
    }
  }, 60000);

  it("close() detaches without killing the remote instance", async () => {
    const { connect } = await import("../src/index.js");
    const { endpoint, port, proc } = await startBrowser();
    try {
      const browser = await connect(endpoint);
      await browser.close();
      expect(browser.isConnected()).toBe(false);
      expect(await remoteAlive(port)).toBe(true);
    } finally {
      proc.kill();
    }
  }, 60000);
});

describeIfSlow("connect() — Puppeteer", () => {
  it("connects over an http endpoint and applies humanize", async () => {
    const { connect } = await import("../src/puppeteer.js");
    const { endpoint, proc } = await startBrowser();
    try {
      const browser = await connect(endpoint, { humanize: true });
      try {
        const page = await browser.newPage();
        await page.goto("data:text/html,<title>hey</title>");
        expect(await page.title()).toBe("hey");
      } finally {
        await browser.disconnect();
      }
    } finally {
      proc.kill();
    }
  }, 60000);
});
