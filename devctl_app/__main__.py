"""
Standalone entrypoint (ADR "Apps Own Their Front + Back Routes" Decision 4)
— run this app WITHOUT the aw-workspace runtime:

    python -m devctl_app                # binds 127.0.0.1:9300 (default)
    PORT=9301 python -m devctl_app

Mounts the SAME ``build_routes()`` sub-app at the SAME prefix used in
integrated mode (``/api/apps/devctl``) so client code and docs never need a
mode-specific path — see ``routes.py``. Then serves ``ui/dist/`` (built via
``npm run build`` in ``ui/``) as static files, with ``html=True`` so
``GET /`` (and any unknown path) falls back to ``ui/dist/index.html`` — the
standalone page loaded by ``ui/src/standalone.js``.

Auth: standalone has **no** ``IdentityGuard`` — that is aw-workspace runtime
machinery, not app code (Decision 4). Default posture here is to bind
``127.0.0.1`` only; the tab relay's ``/eval`` endpoint can run arbitrary JS
in a connected tab, so exposing this beyond loopback without a token gate is
the operator's responsibility, not the framework's.
"""
from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routes import build_routes

SLUG = "devctl"
DEFAULT_PORT = 9300  # matches aw-app.json's runtime.standalone.default_port

APP_ROOT = Path(__file__).resolve().parent.parent
UI_DIST = APP_ROOT / "ui" / "dist"


def build_standalone_app() -> FastAPI:
    app = FastAPI(title="devctl (standalone)")
    app.mount(f"/api/apps/{SLUG}", build_routes())

    if UI_DIST.is_dir():
        app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")

    return app


app = build_standalone_app()


def main() -> None:
    if not UI_DIST.is_dir():
        print(f"NOTE: {UI_DIST} not built yet — run `npm run build` in ui/ first "
              f"(API routes still work without it).")
    port = int(os.environ.get("PORT", str(DEFAULT_PORT)))
    host = os.environ.get("AW_APP_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
