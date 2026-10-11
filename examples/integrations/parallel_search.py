"""Parallel Search MCP + CloakBrowser: discover a URL, then read it in a browser.

Python 3.10+; from the repository root:
    pip install . 'mcp>=1.30,<2'
    python examples/integrations/parallel_search.py 'Python Playwright documentation'

Search is free for light use, runs in Fast mode, and needs no account or API key.
This is a deterministic workflow, with no LLM dependency. CloakBrowser uses its
normal binary selection; without a CloakBrowser key it downloads the older free
binary. On Linux, install system libraries with `playwright install-deps chromium`.

https://docs.parallel.ai/integrations/mcp/search-mcp
"""

import argparse
import asyncio
import json
import uuid
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from cloakbrowser import launch_async


MCP_URL = "https://search.parallel.ai/mcp"
USER_AGENT = "CloakBrowser/parallel-search-example"


async def search(query: str) -> list[dict]:
    """Call the anonymous MCP endpoint using the official Streamable HTTP client."""
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, timeout=60.0,
    ) as client:
        async with streamable_http_client(MCP_URL, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("web_search", {
                    "objective": query,
                    "search_queries": [query],
                    "session_id": uuid.uuid4().hex,
                })
                if result.isError:
                    raise RuntimeError(f"Parallel search failed: {result.content}")
                data = result.structuredContent
                if data is None:
                    # Older MCP servers may return the JSON in a text block.
                    data = json.loads(next(
                        block.text for block in result.content if block.type == "text"
                    ))
                return data["results"]


async def read_page(url: str) -> dict:
    """Read a search result with the maintained CloakBrowser launch API."""
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Search result must be an HTTP or HTTPS URL")
    browser = await launch_async(headless=True)
    try:
        page = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        return {
            "url": page.url,
            "title": await page.title(),
            "text": (await page.locator("body").inner_text(timeout=30_000))[:4000],
        }
    finally:
        await browser.close()


async def main(query: str):
    results = await search(query)
    if not results:
        print("No search results found.")
        return
    # Replace this selection with your own ranking or domain checks as needed.
    print(json.dumps(await read_page(results[0]["url"]), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Search objective and keyword query")
    args = parser.parse_args()
    asyncio.run(main(args.query))
