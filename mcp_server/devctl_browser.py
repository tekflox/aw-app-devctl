"""DevCtl browser MCP — the agent-facing tool surface for the piloted browser
and the tab relay.

Wraps `devctl_app.cdp` (CDP control of the aw-app-browser container) as MCP
tools so an agent can take action: navigate, click, type, press keys, scroll,
evaluate/inject JS (DOM control), and screenshot. No dependency on the browser
being active — every call goes through `ensure_browser()`, which starts the
container and opens a page if needed.

`tab_list`/`tab_eval` are a separate, unrelated capability: devctl_app's tab
relay (a registry of the USER's own live browser tabs, see routes.py's
module docstring) reached over HTTP rather than CDP — see the comment above
those two tools for why.

Registration: wired into the aw-workspace mcp-gateway via this app's
``mcp.json`` (``contributes.mcp`` in ``aw-app.json`` signals it). The gateway
spawns this with ``cwd`` set to the app root so `devctl_app.cdp` imports
cleanly.

Note: this package is named ``mcp_server`` (not ``mcp``) specifically to
avoid shadowing the installed ``mcp`` SDK package (FastMCP) — a directory
named ``mcp`` next to this file would resolve first on ``sys.path`` and
break the `from mcp.server.fastmcp import FastMCP` import below.

Run: `python -m mcp_server.devctl_browser` (stdio).
"""

from __future__ import annotations

import base64
import os
import sys
import time

import httpx

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


# ---- Tab relay (a DIFFERENT capability from the piloted browser above:
# devctl_app/relay.py's cross-worker registry of the USER's own live
# browser tabs, driven by ui/src/client.js's [dev] toggle — see
# devctl_app/routes.py's module docstring). Reached over HTTP, not by
# importing devctl_app.relay.relay directly: this MCP tool runs as its own
# OS process (spawned per mcp.json), so that singleton would be a fresh,
# empty one with no visibility into tabs registered on the real server.
#
# GET /tabs and POST /eval are declared `local_paths` in aw-app.json (skip
# identity for a caller at 127.0.0.1) — but confirmed live 2026-09-09 that
# this MCP subprocess does NOT share loopback with the workspace server (a
# bare 127.0.0.1:AW_PORT call fails with a connection error, reproduced by
# QA on Kanban card 3d65bf3b-9510-81ca-bfec-ed8e5f1eaa89 3x for tab_list, 1x
# for tab_eval). So the external published URL + a real X-Api-Key is the
# path that actually works here, not a "just in case" fallback — mirrors
# src/cli/local_client.py's own base_url()/_read_env_value(), which exists
# for exactly this "off-loopback caller" case. ---------------------------

def _read_workspace_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    home = os.environ.get("AW_WORKSPACE_HOME") or os.path.join(
        os.environ.get("AW_WORKSPACE_CONTAINER_DIR", "/opt/aw-workspace"), ".aw-workspace")
    prefix = f"{name}="
    try:
        with open(os.path.join(home, ".env"), "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith(prefix):
                    return line[len(prefix):].strip()
    except OSError:
        pass
    return None


def _devctl_api_url(path: str) -> str:
    base = _read_workspace_env("AW_WORKSPACE_API_URL") or \
        f"http://127.0.0.1:{os.environ.get('AW_PORT', '9030')}"
    return f"{base.rstrip('/')}/api/apps/devctl{path}"


def _devctl_api_key() -> str | None:
    return _read_workspace_env("AW_WORKSPACE_API_KEY")


def _devctl_headers() -> dict:
    key = _devctl_api_key()
    return {"X-Api-Key": key} if key else {}


@mcp.tool()
async def tab_list() -> dict:
    """List every browser tab currently connected to devctl's tab relay —
    conn_id, user, ua — across every worker. Call this BEFORE tab_eval
    whenever more than one tab might be connected for the same user:
    tab_eval requires an explicit conn_id in that case instead of guessing
    which tab you meant (a stale tab silently receiving eval commands meant
    for a different one is exactly the failure this is for)."""
    async with httpx.AsyncClient(timeout=10.0) as c:
        resp = await c.get(_devctl_api_url("/tabs"), headers=_devctl_headers())
    return resp.json()


@mcp.tool()
async def tab_eval(code: str, conn_id: str | None = None, user: str | None = None,
                    timeout: float = 15.0) -> dict:
    """Run JS in a connected browser tab via devctl's tab relay — the
    USER's own live tab (opted in via the [dev] toggle), NOT the piloted
    CDP browser (`browser_eval` above is that). Pass `conn_id` (from
    `tab_list`) to target a specific tab; it is required whenever more than
    one tab is connected for `user` (or at all, if `user` is omitted) — the
    call errors with the candidate list instead of guessing which one you
    meant."""
    body = {"code": code, "conn_id": conn_id, "user": user, "timeout": timeout}
    async with httpx.AsyncClient(timeout=timeout + 5.0) as c:
        resp = await c.post(_devctl_api_url("/eval"), json=body, headers=_devctl_headers())
    return resp.json()


if __name__ == "__main__":
    mcp.run()
