import { afterEach, describe, expect, it, vi } from "vitest";
import * as fs from "node:fs";
import * as http from "node:http";
import type { AddressInfo } from "node:net";
import * as os from "node:os";
import * as path from "node:path";
import { DEFAULT_DOWNLOAD_TIMEOUT_MS, downloadFile, downloadTimeoutMs } from "../src/download.js";

afterEach(() => {
  vi.restoreAllMocks();
  delete process.env.CLOAKBROWSER_DOWNLOAD_TIMEOUT_SECONDS;
});

describe("downloadTimeoutMs", () => {
  it("defaults to 10 minutes", () => {
    expect(downloadTimeoutMs()).toBe(DEFAULT_DOWNLOAD_TIMEOUT_MS);
  });

  it("reads seconds from the environment", () => {
    process.env.CLOAKBROWSER_DOWNLOAD_TIMEOUT_SECONDS = "3600";
    expect(downloadTimeoutMs()).toBe(3_600_000);
  });

  it.each(["abc", "0", "-5", "Infinity", "9999999"])("warns and keeps the default for %s", (raw) => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    process.env.CLOAKBROWSER_DOWNLOAD_TIMEOUT_SECONDS = raw;
    expect(downloadTimeoutMs()).toBe(DEFAULT_DOWNLOAD_TIMEOUT_MS);
    expect(warn).toHaveBeenCalledOnce();
  });
});

describe("downloadFile", () => {
  it("gives up after the configured time, and finishes with a longer one", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const server = http.createServer((_req, res) => {
      res.write("first");
      setTimeout(() => res.end("second"), 600);
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}/`;
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cloak-download-"));
    const dest = path.join(dir, "binary");
    try {
      process.env.CLOAKBROWSER_DOWNLOAD_TIMEOUT_SECONDS = "0.2";
      await expect(downloadFile(url, dest)).rejects.toThrow();

      process.env.CLOAKBROWSER_DOWNLOAD_TIMEOUT_SECONDS = "5";
      await downloadFile(url, dest);
      expect(fs.readFileSync(dest, "utf-8")).toBe("firstsecond");
    } finally {
      server.closeAllConnections();
      server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
