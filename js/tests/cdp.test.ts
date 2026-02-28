import { describe, it, expect } from "vitest";
import { launch } from "../src/playwright.js";

describe.skipIf(!process.env.CLOAKBROWSER_BINARY_PATH)(
  "CDP (integration)",
  () => {
    it("captures console logs via CDP", async () => {
      const browser = await launch({ headless: true });
      const page = await browser.newPage();

      // Create CDP session for console capture
      const cdp = await page.context().newCDPSession(page);
      await cdp.send("Log.enable");

      const consoleLogs: unknown[] = [];
      cdp.on("Log.entryAdded", (entry: { entry: { text: string } }) => {
        consoleLogs.push(entry.entry.text);
      });

      await page.goto("about:blank");

      // Execute JS that logs to console
      await page.evaluate(() => {
        console.log("CDP_TEST_LOG: Hello from CDP");
        console.warn("CDP_TEST_WARN: Warning message");
      });

      // Wait for console events to propagate
      await new Promise((resolve) => setTimeout(resolve, 500));

      expect(consoleLogs.some((log) => String(log).includes("CDP_TEST_LOG"))).toBe(
        true
      );
      expect(consoleLogs.some((log) => String(log).includes("CDP_TEST_WARN"))).toBe(
        true
      );

      await cdp.detach();
      await browser.close();
    }, 30_000);

    it("evaluates JavaScript via CDP", async () => {
      const browser = await launch({ headless: true });
      const page = await browser.newPage();

      // Create CDP session for runtime evaluation
      const cdp = await page.context().newCDPSession(page);

      await page.goto("about:blank");

      // Evaluate JavaScript via CDP
      const result = await cdp.send("Runtime.evaluate", {
        expression: "2 + 2",
        returnByValue: true,
      });

      expect(result.result.value).toBe(4);

      // Test console interaction
      const consoleResult = await cdp.send("Runtime.evaluate", {
        expression: "'Hello ' + 'World'",
        returnByValue: true,
      });

      expect(consoleResult.result.value).toBe("Hello World");

      await cdp.detach();
      await browser.close();
    }, 30_000);

    it("intercepts network requests via CDP", async () => {
      const browser = await launch({ headless: true });
      const page = await browser.newPage();

      // Create CDP session for network interception
      const cdp = await page.context().newCDPSession(page);

      // Enable network tracking
      await cdp.send("Network.enable");

      const requests: string[] = [];
      cdp.on(
        "Network.requestWillBeSent",
        (entry: { params: { request: { url: string } } }) => {
          requests.push(entry.params.request.url);
        }
      );

      // Navigate to a simple page that makes requests
      await page.goto("https://example.com");

      // Wait for network events to propagate
      await new Promise((resolve) => setTimeout(resolve, 1000));

      // Verify we captured some network requests
      expect(requests.length).toBeGreaterThan(0);
      expect(requests.some((url) => url.includes("example.com"))).toBe(true);

      await cdp.detach();
      await browser.close();
    }, 30_000);

    it("captures exceptions via CDP", async () => {
      const browser = await launch({ headless: true });
      const page = await browser.newPage();

      // Create CDP session for exception capture
      const cdp = await page.context().newCDPSession(page);
      await cdp.send("Runtime.enable");

      const exceptions: string[] = [];
      cdp.on(
        "Runtime.exceptionThrown",
        (entry: { params: { exceptionDetails: { text: string } } }) => {
          exceptions.push(entry.params.exceptionDetails.text);
        }
      );

      await page.goto("about:blank");

      // Trigger an exception
      await page.evaluate(() => {
        // eslint-disable-next-line @typescript-eslint/no-throw-literal
        throw new Error("CDP_TEST_EXCEPTION");
      });

      // Wait for exception to propagate
      await new Promise((resolve) => setTimeout(resolve, 500));

      expect(exceptions.some((ex) => ex.includes("CDP_TEST_EXCEPTION"))).toBe(true);

      await cdp.detach();
      await browser.close();
    }, 30_000);

    it("gets DOM document via CDP", async () => {
      const browser = await launch({ headless: true });
      const page = await browser.newPage();

      await page.goto("about:blank");

      // Set some page content
      await page.setContent("<html><body><div id='test'>Hello CDP</div></body></html>");

      // Create CDP session
      const cdp = await page.context().newCDPSession(page);

      // Get document via CDP
      const doc = await cdp.send("DOM.getDocument");

      expect(doc.root.nodeId).toBeDefined();

      // Query for element
      const queryResult = await cdp.send("DOM.querySelector", {
        nodeId: doc.root.nodeId,
        selector: "#test",
      });

      expect(queryResult.nodeId).toBeDefined();

      // Get element content
      const content = await cdp.send("DOM.getAttributes", {
        nodeId: queryResult.nodeId,
      });

      expect(content.attributes).toBeDefined();

      await cdp.detach();
      await browser.close();
    }, 30_000);
  }
);
