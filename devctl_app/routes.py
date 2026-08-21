"""DevCtl's mode-agnostic FastAPI sub-app (ADR "Apps Own Their Front + Back
Routes — Self-Contained, Dual-Mode" Decision 2/5:
docs/knowledge_base/docs/architecture/adr-app-front-back-routes-dual-mode.md).

``build_routes()`` returns the SAME sub-app used in both modes:

* **integrated** — ``plugin.py`` hands it to ``ctx.routes.register(...)``,
  mounted at ``/api/apps/devctl`` behind the runtime's ``IdentityGuard``
  (aw-workspace ``src/apps/runtime.py``). ``/eval`` and ``/tabs`` are
  additionally declared as ``local_paths`` (``aw-app.json``) — a workspace-
  local caller (the agent, from 127.0.0.1) skips the JWT check on those two;
  every other route, and every OTHER caller, still needs it.
* **standalone** — ``__main__.py`` mounts it at the same prefix, no guard.

Two independent capabilities live in this one sub-app:

1. **Piloted browser** (ported from the monolith's whiteboard piloted-
   browser) — drives the existing ``aw-app-browser`` container over CDP
   (:9223) instead of launching its own chromium, so the browser the user
   sees (noVNC) is the one the agent controls.
   - GET  /browser/screenshot          → live PNG of the browser
   - POST /browser/navigate {url}      → go to a URL
   - POST /browser/eval {js}           → run JS in the page, return its value
   - POST /browser/inject {js}         → inject a script (now + every load)
   - POST /browser/click {x,y,double}  → click at CSS-pixel coords
   - POST /browser/type {text,submit}  → type into the focused field
   - POST /browser/key {key}           → press a named key (Enter, Tab, ...)
   - POST /browser/scroll {dy}         → wheel-scroll
   - GET  /browser/current             → {title, url}
   - WS   /ws                          → live screencast (base64 JPEG frames)

2. **Tab relay** (moved from the aw-workspace monolith's
   ``src/api/devctl_relay.py`` — ADR Decision 5) — remote JS eval into the
   USER's own live browser tab, driven by ``ui/src/client.js``.
   - WS   /ws/tab   → a browser tab registers here (identity from
     ``websocket.scope["aw_identity"]``, populated by IdentityGuard)
   - GET  /tabs     → list currently-connected tabs (local_paths)
   - POST /eval     → {code, user?, timeout?} → run JS in a connected tab,
     return its result (local_paths)

3. **Render** (``render.py``) — a THIRD, independent capability: no side
   container, no shared browser, just a throwaway Playwright chromium that
   renders one URL and closes. For any caller (``mini-browser`` today) that
   wants a screenshot of an arbitrary URL without depending on
   ``aw-app-browser`` being up at all.
   - POST /render/screenshot {url, width?, height?, scale?, full_page?,
     wait_ms?} → PNG bytes
"""

from __future__ import annotations

import json

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from .cdp import client
from .relay import relay
from .render import screenshot_url


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

    # ---- Tab relay (Decision 5) ------------------------------------------

    @app.websocket("/ws/tab")
    async def tab_ws(websocket: WebSocket):
        """A user browser tab connects here to become an eval target.

        Integrated mode: IdentityGuard already verified the JWT before this
        handler runs and stashed the claims at ``scope["aw_identity"]`` — we
        just read them (never re-verify). Standalone mode has no guard, so
        claims are absent and the tab registers as "unknown".
        """
        claims = websocket.scope.get("aw_identity") or {}
        user = claims.get("sub") or claims.get("email") or "unknown"
        await websocket.accept()
        ua = websocket.headers.get("user-agent", "")
        cid = next(relay._conn_ids)
        relay.tabs[cid] = {"ws": websocket, "user": user, "ua": ua}
        try:
            await websocket.send_text(json.dumps({"cmd": "hello"}))
            while True:
                raw = await websocket.receive_text()
                try:
                    relay._resolve(json.loads(raw))
                except Exception:
                    continue
        except WebSocketDisconnect:
            pass
        finally:
            relay.tabs.pop(cid, None)

    @app.get("/tabs")
    async def list_tabs():
        return {"tabs": relay.list_tabs()}

    @app.post("/eval")
    async def eval_in_tab(body: dict = Body(...)):
        code = body.get("code")
        if not code:
            return JSONResponse(status_code=400, content={"ok": False, "error": "code is required"})
        try:
            res = await relay.eval(code, user=body.get("user"),
                                    timeout=float(body.get("timeout") or 15.0))
            return {"ok": True, **res}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/render/screenshot")
    async def render_screenshot(body: dict = Body(...)):
        url = body.get("url")
        if not url or not url.lower().startswith(("http://", "https://")):
            raise HTTPException(400, "url must be an absolute http(s) URL")
        try:
            png = await run_in_threadpool(
                screenshot_url,
                url,
                int(body.get("width") or 1280),
                int(body.get("height") or 800),
                float(body.get("scale") or 1.0),
                bool(body.get("full_page") or False),
                int(body.get("wait_ms") or 0),
            )
        except Exception as exc:
            return JSONResponse(status_code=502, content={"error": "render", "detail": str(exc)})
        return Response(content=png, media_type="image/png")

    return app
