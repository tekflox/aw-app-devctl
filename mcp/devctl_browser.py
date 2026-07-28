"""DevCtl browser MCP — the agent-facing tool surface for the piloted browser.

Wraps `devctl_app.cdp` (CDP control of the aw-app-browser container) as MCP
tools so an agent can take action: navigate, click, type, press keys, scroll,
evaluate/inject JS (DOM control), and screenshot. No dependency on the browser
being active — every call goes through `ensure_browser()`, which starts the
container and opens a page if needed.

Registration: this is meant to run under the **aw-workspace mcp-gateway**
(same python env, so `devctl_app.cdp` imports cleanly). That gateway isn't
wired inside aw-workspace yet — until then, drive the browser via the HTTP API
(`/api/apps/devctl/browser/*`). Ships here so it's ready to register.

Run: `python -m mcp.devctl_browser` (stdio).
"""

from __future__ import annotations

import base64
import os
import sys
import time

# Allow running from the app root so `devctl_app` is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from devctl_app.cdp import client  # noqa: E402

mcp = FastMCP("devctl-browser")

_SHOT_DIR = os.environ.get("DEVCTL_SHOT_DIR", "/tmp/devctl")


def _save_png(png: bytes) -> str:
    os.makedirs(_SHOT_DIR, exist_ok=True)
    path = os.path.join(_SHOT_DIR, f"shot-{int(time.time()*1000)}.png")
    with open(path, "wb") as f:
        f.write(png)
    return path


@mcp.tool()
async def browser_screenshot() -> str:
    """Capture the live browser screen. Returns a PNG file path."""
    return _save_png(await client.screenshot())


@mcp.tool()
async def browser_current() -> dict:
    """Current page title + URL."""
    return await client.current()


@mcp.tool()
async def browser_navigate(url: str) -> dict:
    """Navigate the browser to a URL (starts the browser if it's off)."""
    await client.navigate(url)
    return {"ok": True, "url": url}


@mcp.tool()
async def browser_eval(js: str):
    """Run JS in the page and return its value — read/modify the DOM."""
    return await client.evaluate(js)


@mcp.tool()
async def browser_inject(js: str) -> dict:
    """Inject a script that runs now and on every future document load."""
    await client.inject(js)
    return {"ok": True}


@mcp.tool()
async def browser_click(x: float, y: float, double: bool = False) -> str:
    """Click at CSS-pixel coordinates. Returns a screenshot path."""
    await client.click(x, y, double)
    return _save_png(await client.screenshot())


@mcp.tool()
async def browser_type(text: str, submit: bool = False) -> str:
    """Type into the focused field (click it first). Returns a screenshot path."""
    await client.type_text(text)
    if submit:
        await client.key("Enter")
    return _save_png(await client.screenshot())


@mcp.tool()
async def browser_key(key: str) -> str:
    """Press a named key (Enter, Tab, Escape, ArrowDown, ...). Returns a screenshot path."""
    await client.key(key)
    return _save_png(await client.screenshot())


@mcp.tool()
async def browser_scroll(dy: int = 300) -> str:
    """Wheel-scroll by dy pixels. Returns a screenshot path."""
    await client.scroll(dy)
    return _save_png(await client.screenshot())


if __name__ == "__main__":
    mcp.run()
