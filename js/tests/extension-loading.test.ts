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
