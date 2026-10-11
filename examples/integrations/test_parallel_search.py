"""Run with: python -m unittest discover -s examples/integrations -p test_parallel_search.py"""

import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from mcp.types import CallToolResult, TextContent

import parallel_search as example


class SearchExampleTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_dispatch_is_anonymous_and_identifies_project(self):
        requests = []

        def handle(request):
            requests.append(request)
            self.assertEqual(str(request.url), example.MCP_URL)
            self.assertEqual(request.headers['user-agent'], example.USER_AGENT)
            self.assertNotIn('authorization', request.headers)
            body = json.loads(request.content)
            if 'id' not in body:
                return httpx.Response(202)
            if body['method'] == 'initialize':
                result = {'protocolVersion': '2025-11-25', 'capabilities': {},
                          'serverInfo': {'name': 'fixture', 'version': '1'}}
            elif body['method'] == 'tools/list':
                result = {'tools': [{'name': 'web_search', 'inputSchema': {'type': 'object'}}]}
            else:
                self.assertEqual(body['method'], 'tools/call')
                self.assertEqual(body['params']['name'], 'web_search')
                args = body['params']['arguments']
                self.assertEqual(args['objective'], 'Playwright Python docs')
                self.assertEqual(args['search_queries'], ['Playwright Python docs'])
                self.assertEqual(len(args['session_id']), 32)
                result = {'content': [], 'structuredContent': {'results': [
                    {'url': 'https://playwright.dev/python/', 'excerpts': ['docs']}
                ]}}
            return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'], 'result': result})

        real_client = httpx.AsyncClient
        def client(**kwargs):
            return real_client(transport=httpx.MockTransport(handle), **kwargs)

        with patch.object(example.httpx, 'AsyncClient', side_effect=client):
            results = await example.search('Playwright Python docs')
        self.assertEqual(results[0]['url'], 'https://playwright.dev/python/')
        self.assertEqual(len(requests), 4)  # initialize, notification, discovery, call

    async def test_browser_closes_on_navigation_failure(self):
        browser = AsyncMock()
        browser.new_page.return_value.goto.side_effect = RuntimeError('navigation failed')
        with patch.object(example, 'launch_async', return_value=browser):
            with self.assertRaisesRegex(RuntimeError, 'navigation failed'):
                await example.read_page('https://example.com')
        browser.close.assert_awaited_once()

    async def test_invalid_url_does_not_launch_browser(self):
        with patch.object(example, 'launch_async') as launch:
            with self.assertRaises(ValueError):
                await example.read_page('file:///etc/passwd')
        launch.assert_not_called()

    async def test_empty_search_does_not_launch_browser(self):
        with patch.object(example, 'search', return_value=[]), \
                patch.object(example, 'read_page') as read, patch('builtins.print') as output:
            await example.main('missing')
        read.assert_not_called()
        output.assert_called_once_with('No search results found.')

    async def test_search_error_prevents_browsing(self):
        response = CallToolResult(isError=True, content=[TextContent(type='text', text='try later')])
        session = AsyncMock()
        session.call_tool.return_value = response
        with patch.object(example, 'ClientSession') as session_type:
            session_type.return_value.__aenter__.return_value = session
            # Keep the actual transport; replace its context with inert streams.
            with patch.object(example, 'streamable_http_client') as transport:
                transport.return_value.__aenter__.return_value = (None, None, None)
                with self.assertRaisesRegex(RuntimeError, 'Parallel search failed'):
                    await example.search('missing')


if __name__ == '__main__':
    unittest.main()
