import { test, expect } from "vitest";
import path from "path";
import { _buildArgsForTest } from "../src/playwright.js";

test("extension paths inject chrome flags", () => {
  const args = _buildArgsForTest({
    extensionPaths: ["./ext"],
  });

  const abs = path.resolve("./ext");

  expect(args).toContain(`--load-extension=${abs}`);

  expect(args).toContain(
    `--disable-extensions-except=${abs}`
  );
});

test("--load-extension in args auto-adds companion flag", () => {
  const args = _buildArgsForTest({
    args: ["--load-extension=/path/to/ext"],
  });

  expect(args).toContain("--load-extension=/path/to/ext");
  expect(args).toContain("--disable-extensions-except=/path/to/ext");
});

test("--load-extension with comma-separated paths auto-adds companion", () => {
  const args = _buildArgsForTest({
    args: ["--load-extension=/path/a,/path/b"],
  });

  expect(args).toContain("--load-extension=/path/a,/path/b");
  expect(args).toContain("--disable-extensions-except=/path/a,/path/b");
});

test("no duplicate companion when both flags already present", () => {
  const args = _buildArgsForTest({
    args: [
      "--load-extension=/path/to/ext",
      "--disable-extensions-except=/path/to/ext",
    ],
  });

  const extFlags = args.filter((a) =>
    a.startsWith("--disable-extensions-except=")
  );
  expect(extFlags).toHaveLength(1);
  expect(extFlags[0]).toBe("--disable-extensions-except=/path/to/ext");
});

test("no companion flag without --load-extension", () => {
  const args = _buildArgsForTest({
    args: ["--disable-gpu"],
  });

  expect(
    args.some((a) => a.startsWith("--disable-extensions-except"))
  ).toBe(false);
});
