"""CDP (Chrome DevTools Protocol) integration tests for cloakbrowser.

These tests verify that CDP functionality works correctly with the stealth
Chromium binary, including network interception, console capture, and
runtime JavaScript evaluation.
"""

import pytest

from cloakbrowser import launch, binary_info


def is_binary_available():
    """Check if the stealth binary is installed."""
    info = binary_info()
    return info.get("installed", False)


skip_if_no_binary = pytest.mark.skipif(
    not is_binary_available(),
    reason="Stealth binary not installed"
)


@pytest.fixture(scope="module")
def browser():
    """Shared browser instance for CDP tests."""
    b = launch(headless=True)
    yield b
    b.close()


@pytest.fixture
def page(browser):
    """Fresh page for each test."""
    p = browser.new_page()
    yield p
    p.close()


class TestCDPNetworkInterception:
    """Tests for CDP network request interception."""

    @skip_if_no_binary
    def test_cdp_network_enable(self, page):
        """CDP Network domain can be enabled."""
        cdp = page.context().new_cdp_session(page)
        # Enable network tracking
        response = cdp.send("Network.enable")
        assert response is None or isinstance(response, dict)
        cdp.detach()

    @skip_if_no_binary
    def test_cdp_network_request_will_be_sent(self, page):
        """CDP can intercept network request willBeSent events."""
        cdp = page.context().new_cdp_session(page)
        cdp.send("Network.enable")

        requests = []
        cdp.on("Network.requestWillBeSent", lambda params: requests.append(params))

        page.goto("https://example.com", wait_until="networkidle")

        assert len(requests) > 0, "Should capture at least one network request"
        # Verify request has expected structure
        first_request = requests[0]
        assert "request" in first_request
        assert "requestId" in first_request
        cdp.detach()

    @skip_if_no_binary
    def test_cdp_network_response_received(self, page):
        """CDP can intercept network responseReceived events."""
        cdp = page.context().new_cdp_session(page)
        cdp.send("Network.enable")

        responses = []
        cdp.on("Network.responseReceived", lambda params: responses.append(params))

        page.goto("https://example.com", wait_until="networkidle")

        assert len(responses) > 0, "Should capture at least one response"
        first_response = responses[0]
        assert "requestId" in first_response
        assert "response" in first_response
        cdp.detach()

    @skip_if_no_binary
    def test_cdp_network_loading_finished(self, page):
        """CDP can intercept network loadingFinished events."""
        cdp = page.context().new_cdp_session(page)
        cdp.send("Network.enable")

        finished = []
        cdp.on("Network.loadingFinished", lambda params: finished.append(params))

        page.goto("https://example.com", wait_until="networkidle")

        assert len(finished) > 0, "Should capture loading finished events"
        cdp.detach()


class TestCDPConsoleCapture:
    """Tests for CDP console log capture."""

    @skip_if_no_binary
    def test_cdp_log_enable(self, page):
        """CDP Log domain can be enabled."""
        cdp = page.context().new_cdp_session(page)
        response = cdp.send("Log.enable")
        assert response is None or isinstance(response, dict)
        cdp.detach()

    @skip_if_no_binary
    def test_cdp_console_log_capture(self, page):
        """CDP can capture console.log messages."""
        cdp = page.context().new_cdp_session(page)
        cdp.send("Log.enable")

        console_entries = []
        cdp.on("Log.entryAdded", lambda params: console_entries.append(params))

        page.goto("https://example.com")
        # Inject a console.log
        page.evaluate("console.log('test message from cdp')")
        page.wait_for_timeout(500)

        # Check we captured the console log
        messages = [e.get("entry", {}).get("text") for e in console_entries]
        assert any("test message from cdp" in msg for msg in messages), \
            f"Should capture console.log, got: {messages}"
        cdp.detach()

    @skip_if_no_binary
    def test_cdp_console_error_capture(self, page):
        """CDP can capture console.error messages."""
        cdp = page.context().new_cdp_session(page)
        cdp.send("Log.enable")

        console_entries = []
        cdp.on("Log.entryAdded", lambda params: console_entries.append(params))

        page.goto("https://example.com")
        # Inject a console.error
        page.evaluate("console.error('test error from cdp')")
        page.wait_for_timeout(500)

        # Find error entries
        error_entries = [e for e in console_entries 
                         if e.get("entry", {}).get("level") == "error"]
        messages = [e.get("entry", {}).get("text") for e in error_entries]
        assert any("test error from cdp" in msg for msg in messages), \
            f"Should capture console.error, got: {messages}"
        cdp.detach()

    @skip_if_no_binary
    def test_cdp_console_types(self, page):
        """CDP can distinguish different console message types."""
        cdp = page.context().new_cdp_session(page)
        cdp.send("Log.enable")

        console_entries = []
        cdp.on("Log.entryAdded", lambda params: console_entries.append(params))

        page.goto("https://example.com")
        page.evaluate("""
            () => {
                console.log('info msg');
                console.warn('warning msg');
                console.error('error msg');
            }
        """)
        page.wait_for_timeout(500)

        # Group by level
        by_level = {}
        for entry in console_entries:
            level = entry.get("entry", {}).get("level", "unknown")
            by_level[level] = by_level.get(level, 0) + 1

        assert by_level.get("info", 0) >= 1, "Should have info level"
        assert by_level.get("warning", 0) >= 1, "Should have warning level"
        assert by_level.get("error", 0) >= 1, "Should have error level"
        cdp.detach()


class TestCDPRuntimeEvaluation:
    """Tests for CDP runtime JavaScript evaluation."""

    @skip_if_no_binary
    def test_cdp_runtime_enable(self, page):
        """CDP Runtime domain can be enabled."""
        cdp = page.context().new_cdp_session(page)
        response = cdp.send("Runtime.enable")
        assert response is None or isinstance(response, dict)
        cdp.detach()

    @skip_if_no_binary
    def test_cdp_runtime_evaluate_basic(self, page):
        """CDP can evaluate basic JavaScript."""
        cdp = page.context().new_cdp_session(page)
        cdp.send("Runtime.enable")

        result = cdp.send("Runtime.evaluate", {
            "expression": "1 + 1",
            "returnByValue": True
        })

        assert result is not None
        assert "result" in result
        # Result should be 2
        assert result["result"]["value"] == 2
        cdp.detach()

    @skip_if_no_binary
    def test_cdp_runtime_evaluate_object(self, page):
        """CDP can evaluate JavaScript and return objects."""
        cdp = page.context().new_cdp_session(page)
        cdp.send("Runtime.enable")

        result = cdp.send("Runtime.evaluate", {
            "expression": "({ foo: 'bar', num: 42 })",
            "returnByValue": True
        })

        assert result is not None
        assert "result" in result
        # Check the object was returned
        props = result["result"].get("value", {})
        assert props.get("foo") == "bar"
        assert props.get("num") == 42
        cdp.detach()

    @skip_if_no_binary
    def test_cdp_runtime_console_api(self, page):
        """CDP Runtime can use console API."""
        cdp = page.context().new_cdp_session(page)
        cdp.send("Runtime.enable")

        result = cdp.send("Runtime.evaluate", {
            "expression": "console.log('cdp eval test'); 42",
            "returnByValue": True
        })

        assert result is not None
        assert result["result"]["value"] == 42
        cdp.detach()

    @skip_if_no_binary
    def test_cdp_runtime_exception_details(self, page):
        """CDP returns exception details for code errors."""
        cdp = page.context().new_cdp_session(page)
        cdp.send("Runtime.enable")

        result = cdp.send("Runtime.evaluate", {
            "expression": "nonexistent_function()",
            "returnByValue": True
        })

        # Should have an exception
        assert result is not None
        assert "exceptionDetails" in result or result.get("result", {}).get("type") == "error"
        cdp.detach()

    @skip_if_no_binary
    def test_cdp_runtime_dom_access(self, page):
        """CDP Runtime can access the page DOM."""
        page.goto("https://example.com")

        cdp = page.context().new_cdp_session(page)
        cdp.send("Runtime.enable")

        # Get document.title via CDP
        result = cdp.send("Runtime.evaluate", {
            "expression": "document.title",
            "returnByValue": True
        })

        assert result is not None
        assert "Example Domain" in result["result"]["value"]
        cdp.detach()


class TestCDPIntegration:
    """Integration tests combining CDP features."""

    @skip_if_no_binary
    def test_cdp_full_workflow(self, page):
        """Complete workflow: network + console + runtime."""
        cdp = page.context().new_cdp_session(page)

        # Enable all needed domains
        cdp.send("Network.enable")
        cdp.send("Log.enable")
        cdp.send("Runtime.enable")

        # Track events
        requests = []
        logs = []

        cdp.on("Network.requestWillBeSent", lambda p: requests.append(p))
        cdp.on("Log.entryAdded", lambda p: logs.append(p))

        # Navigate and execute
        page.goto("https://example.com")
        page.evaluate("console.log('page loaded')")

        # Evaluate via CDP
        result = cdp.send("Runtime.evaluate", {
            "expression": "document.readyState",
            "returnByValue": True
        })

        # Verify
        assert len(requests) > 0
        assert len(logs) > 0
        assert result["result"]["value"] == "complete"

        cdp.detach()
