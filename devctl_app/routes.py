"""DevCtl's FastAPI sub-app, mounted at ``/api/apps/devctl`` via
``ctx.routes.register`` (capability ``routes:register``).

Ported from the monolith's whiteboard "piloted browser" (src/api/routes/
whiteboard.py + whiteboard_browser.py), but drives the **existing
aw-app-browser container over CDP** (:9223) instead of launching its own
chromium — so the browser the user sees (noVNC) is the one the agent controls.

Surface (use via API for now; an MCP-gateway wrapper comes later):
- GET  /browser/screenshot          → live PNG of the browser
- POST /browser/navigate {url}      → go to a URL
- POST /browser/eval {js}           → run JS in the page, return its value (DOM control)
- POST /browser/inject {js}         → inject a script (runs now + on every load)
- POST /browser/click {x,y,double}  → click at CSS-pixel coords
- POST /browser/type {text,submit}  → type into the focused field
- POST /browser/key {key}           → press a named key (Enter, Tab, ...)
- POST /browser/scroll {dy}         → wheel-scroll
- GET  /browser/current             → {title, url}
- WS   /ws                          → live screencast (base64 JPEG frames)
"""

from __future__ import annotations

import json

from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

from .cdp import client


def build_routes() -> FastAPI:
    app = FastAPI(title="devctl")

    async def _guard(fn):
        try:
            return await fn()
        except Exception as exc:  # surface CDP/browser errors as 502, not 500
            return JSONResponse(status_code=502, content={"error": "browser", "detail": str(exc)})

    @app.get("/browser/screenshot")
    async def screenshot():
        try:
            png = await client.screenshot()
        except Exception as exc:
            return JSONResponse(status_code=502, content={"error": "browser", "detail": str(exc)})
        return Response(content=png, media_type="image/png")

    @app.get("/browser/current")
    async def current():
        return await _guard(lambda: client.current())

    @app.post("/browser/navigate")
    async def navigate(body: dict = Body(...)):
        async def go():
            await client.navigate(body["url"])
            return {"ok": True, "url": body["url"]}
        return await _guard(go)

    @app.post("/browser/eval")
    async def eval_js(body: dict = Body(...)):
        async def go():
            return {"ok": True, "result": await client.evaluate(body["js"])}
        return await _guard(go)

    @app.post("/browser/inject")
    async def inject(body: dict = Body(...)):
        async def go():
            await client.inject(body["js"])
            return {"ok": True}
        return await _guard(go)

    @app.post("/browser/click")
    async def click(body: dict = Body(...)):
        async def go():
            await client.click(float(body["x"]), float(body["y"]), bool(body.get("double", False)))
            return {"ok": True}
        return await _guard(go)

    @app.post("/browser/type")
    async def type_text(body: dict = Body(...)):
        async def go():
            await client.type_text(body["text"])
            if body.get("submit"):
                await client.key("Enter")
            return {"ok": True}
        return await _guard(go)

    @app.post("/browser/key")
    async def key(body: dict = Body(...)):
        async def go():
            await client.key(body["key"])
            return {"ok": True}
        return await _guard(go)

    @app.post("/browser/scroll")
    async def scroll(body: dict = Body(...)):
        async def go():
            await client.scroll(int(body.get("dy", 300)))
            return {"ok": True}
        return await _guard(go)

    @app.websocket("/ws")
    async def live(ws: WebSocket):
        """Stream the browser screen as base64 JPEG frames (CDP screencast)."""
        await ws.accept()
        try:
            await client.start_screencast()
        except Exception as exc:
            await ws.send_text(json.dumps({"type": "error", "detail": str(exc)}))
            await ws.close()
            return
        try:
            while True:
                ev = await client.events.get()
                if ev.get("method") == "Page.screencastFrame":
                    p = ev["params"]
                    try:
                        await client.ack(p["sessionId"])
                    except Exception:
                        pass
                    await ws.send_text(json.dumps({"type": "frame", "data": p["data"]}))
        except WebSocketDisconnect:
            pass
        finally:
            await client.stop_screencast()

    return app
