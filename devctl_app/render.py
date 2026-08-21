"""Self-contained URL screenshot — no side container.

Unlike ``cdp.py`` (which pilots the SEPARATE ``aw-app-browser`` container
over CDP, the instance a human watches over noVNC), this launches its own
throwaway headless Chromium via Playwright, renders one URL, and closes.
Ported behaviorally from ``aw-app-whiteboard``'s ``browser.py::screenshot_url``
— same one-shot pattern, minus the workspace-own-origin auth header dance
(whiteboard needs that because it screenshots ITS OWN identity-gated pages;
this fetches an arbitrary external URL directly, so there is no key to leak
and nothing to authenticate).
"""

from __future__ import annotations


def screenshot_url(url: str, width: int = 1280, height: int = 800,
                    scale: float = 1.0, full_page: bool = False,
                    wait_ms: int = 0) -> bytes:
    """Synchronous headless-chromium screenshot of ``url``. Run in a worker
    thread by the caller (``page.screenshot()`` blocks the event loop
    otherwise) — see ``routes.py``'s use of ``run_in_threadpool``.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        try:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=scale,
            )
            page = context.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=20000)
            except Exception:
                page.goto(url, wait_until="load", timeout=20000)
            if wait_ms:
                page.wait_for_timeout(wait_ms)
            return page.screenshot(full_page=full_page)
        finally:
            browser.close()
