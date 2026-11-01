import { describe, it, expect, vi, afterEach } from "vitest";
import { sign as cryptoSign, createPrivateKey, createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// Generate a throwaway signing keypair BEFORE the config mock is hoisted, then
// pin its public key so verifySignature accepts signatures we produce here.
const h = vi.hoisted(() => {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const crypto = require("node:crypto");
  const { publicKey, privateKey } = crypto.generateKeyPairSync("ed25519");
  const otherPub = crypto.generateKeyPairSync("ed25519").publicKey;
  const rawB64 = (pk: any) =>
    Buffer.from(pk.export({ format: "jwk" }).x, "base64url").toString("base64");
  return {
    pinnedPubB64: rawB64(publicKey),
    otherPubB64: rawB64(otherPub),
    privPem: privateKey.export({ type: "pkcs8", format: "pem" }) as string,
  };
});

vi.mock("../src/config.js", async (importActual) => {
  const actual = await importActual<typeof import("../src/config.js")>();
  return { ...actual, BINARY_SIGNING_PUBKEYS: [h.pinnedPubB64] };
});

import {
  BinaryVerificationError,
  downloadProBinary,
  parseChecksums,
  parseManifestVersion,
  verifyProDownload,
  verifySignature,
} from "../src/download.js";
import { DOWNLOAD_BASE_URL, getArchiveName } from "../src/config.js";

/** Produce SHA256SUMS.sig content (base64 text bytes) for a manifest. */
function sign(manifest: Uint8Array): Uint8Array {
  const priv = createPrivateKey(h.privPem);
  const sig = cryptoSign(null, manifest, priv); // raw 64-byte Ed25519 signature
  return new TextEncoder().encode(sig.toString("base64"));
}

const enc = (s: string) => new TextEncoder().encode(s);

describe("verifySignature", () => {
  it("accepts a valid signature", () => {
    const manifest = enc("abc  cloakbrowser-linux-x64.tar.gz\n");
    expect(() => verifySignature(manifest, sign(manifest))).not.toThrow();
  });

  it("rejects a tampered manifest", () => {
    const manifest = enc("abc  cloakbrowser-linux-x64.tar.gz\n");
    const sig = sign(manifest);
    const tampered = enc("xyz  cloakbrowser-linux-x64.tar.gz\n");
    expect(() => verifySignature(tampered, sig)).toThrow(/signature verification failed/);
  });

  it("rejects malformed base64 in the .sig", () => {
    expect(() => verifySignature(enc("data\n"), enc("!!!not base64!!!")))
      .toThrow(/Malformed/);
  });

  it("rejects a signature from a non-pinned key", async () => {
    // Re-mock config so ONLY the other key is pinned, then the signature
    // (made with the real key) must fail.
    vi.resetModules();
    vi.doMock("../src/config.js", async (importActual) => {
      const actual = await importActual<typeof import("../src/config.js")>();
      return { ...actual, BINARY_SIGNING_PUBKEYS: [h.otherPubB64] };
    });
    const { verifySignature: vs } = await import("../src/download.js");
    const manifest = enc("data\n");
    expect(() => vs(manifest, sign(manifest))).toThrow(/signature verification failed/);
    vi.doUnmock("../src/config.js");
    vi.resetModules();
  });

  it("accepts a signature under the new key during rotation", async () => {
    // Pin BOTH keys (old + new) and sign with the real (new) key — must pass.
    vi.resetModules();
    vi.doMock("../src/config.js", async (importActual) => {
      const actual = await importActual<typeof import("../src/config.js")>();
      return { ...actual, BINARY_SIGNING_PUBKEYS: [h.otherPubB64, h.pinnedPubB64] };
    });
    const { verifySignature: vs } = await import("../src/download.js");
    const manifest = enc("rotated\n");
    expect(() => vs(manifest, sign(manifest))).not.toThrow();
    vi.doUnmock("../src/config.js");
    vi.resetModules();
  });
});

describe("downloadProBinary (version-pinned URL)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("requests the explicit version, not /latest", async () => {
    let capturedUrl = "";
    // First fetch is the binary download; capture its URL then abort the flow
    // before verify/extract by returning a non-ok response.
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      capturedUrl = typeof input === "string" ? input : (input as URL).toString();
      return { ok: false, status: 500, statusText: "stop" } as Response;
    });

    await downloadProBinary("147.0.1.0", "cb_key").catch(() => {});

    expect(capturedUrl).toBe(`${DOWNLOAD_BASE_URL}/api/download/147.0.1.0`);
    expect(capturedUrl.endsWith("/latest")).toBe(false);
  });
});

describe("verifyProDownload (Pro path, fail-closed parity)", () => {
  const PRO_VERSION = "147.0.1.0";

  afterEach(() => {
    vi.restoreAllMocks();
    delete process.env.CLOAKBROWSER_SKIP_CHECKSUM;
  });

  function tmpFile(bytes: Buffer): string {
    const p = path.join(os.tmpdir(), `cloak-pro-${process.pid}-${bytes.length}-${bytes[0]}`);
    fs.writeFileSync(p, bytes);
    return p;
  }

  /** Mock fetch: serve `manifestBytes` for SHA256SUMS, its signature for *.sig. */
  function mockManifest(manifestBytes: Uint8Array, sigBytes = sign(manifestBytes)) {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as URL).toString();
      const out = url.endsWith(".sig") ? sigBytes : manifestBytes;
      return { ok: true, arrayBuffer: async () => out.buffer } as Response;
    });
  }

  const body = (lines: string, version = PRO_VERSION) =>
    enc(`version=${version}\n${lines}`);

  it("passes when signature is valid and hash matches", async () => {
    const data = Buffer.from("the real pro binary");
    const file = tmpFile(data);
    const hash = createHash("sha256").update(data).digest("hex");
    mockManifest(body(`${hash}  ${getArchiveName()}\n`));
    await expect(verifyProDownload(file, PRO_VERSION)).resolves.toBeUndefined();
  });

  it("CLOAKBROWSER_SKIP_CHECKSUM does NOT bypass Pro verification", async () => {
    const file = tmpFile(Buffer.from("a malicious pro binary"));
    const goodHash = createHash("sha256").update(Buffer.from("the real pro binary")).digest("hex");
    process.env.CLOAKBROWSER_SKIP_CHECKSUM = "true";
    mockManifest(body(`${goodHash}  ${getArchiveName()}\n`));
    const err = await verifyProDownload(file, PRO_VERSION).catch((e) => e);
    // The error TYPE is the contract the ensureBinary router branches on:
    // BinaryVerificationError => re-throw (never downgrade to free).
    expect(err).toBeInstanceOf(BinaryVerificationError);
    expect(err.message).toMatch(/Checksum verification failed/);
  });

  it("treats a failed manifest fetch as transient, not tampering", async () => {
    // A failed manifest FETCH must be a plain Error (router falls back to free),
    // NOT a BinaryVerificationError (which the router re-throws as a hard fail).
    const file = tmpFile(Buffer.from("x"));
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: false, status: 404 } as Response);
    const err = await verifyProDownload(file, PRO_VERSION).catch((e) => e);
    expect(err).toBeInstanceOf(Error);
    expect(err).not.toBeInstanceOf(BinaryVerificationError);
  });

  it("fails on a signed manifest for the wrong version (downgrade)", async () => {
    const data = Buffer.from("the real pro binary");
    const file = tmpFile(data);
    const hash = createHash("sha256").update(data).digest("hex");
    mockManifest(body(`${hash}  ${getArchiveName()}\n`, "1.0.0.0"));
    const err = await verifyProDownload(file, PRO_VERSION).catch((e) => e);
    expect(err).toBeInstanceOf(BinaryVerificationError);
    expect(err.message).toMatch(/Version mismatch/);
  });

  it("rejects a manifest tampered after signing", async () => {
    const data = Buffer.from("the real pro binary");
    const file = tmpFile(data);
    const hash = createHash("sha256").update(data).digest("hex");
    const good = body(`${hash}  ${getArchiveName()}\n`);
    const sig = sign(good);
    const tampered = enc(new TextDecoder().decode(good).replace(getArchiveName(), "evil.tar.gz"));
    mockManifest(tampered, sig);
    const err = await verifyProDownload(file, PRO_VERSION).catch((e) => e);
    expect(err).toBeInstanceOf(BinaryVerificationError);
    expect(err.message).toMatch(/signature verification failed/);
  });
});

describe("version binding", () => {
  it("reads the version= line", () => {
    expect(
      parseManifestVersion("version=146.0.7680.177.5\nabc  file.tar.gz\n")
    ).toBe("146.0.7680.177.5");
  });

  it("returns null when absent", () => {
    expect(parseManifestVersion("abc  file.tar.gz\n")).toBeNull();
  });

  it("old parseChecksums ignores the version line", () => {
    const result = parseChecksums(
      `version=146.0.7680.177.5\n${"a".repeat(64)}  cloakbrowser-linux-x64.tar.gz\n`
    );
    expect(result.size).toBe(1);
    expect(result.has("cloakbrowser-linux-x64.tar.gz")).toBe(true);
  });
});
