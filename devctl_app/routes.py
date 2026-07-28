"""DevCtl's own FastAPI sub-app, mounted at ``/api/apps/devctl`` via
``ctx.routes.register`` (``routes:register``).

Scaffold only — the sole route is a documented stub for the app's first
planned capability (see repo README): observing/controlling the user's
browser by talking CDP to the aw-app-browser container, reachable
in-workspace as ``aw-app-browser:9223``. Not implemented; returns 501.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse


def build_routes() -> FastAPI:
    app = FastAPI(title="devctl")

    @app.get("/browser/screenshot")
    async def browser_screenshot() -> JSONResponse:
        # TODO: connect to the aw-app-browser CDP endpoint
        # (aw-app-browser:9223 in-workspace) and return a live screenshot.
        return JSONResponse(
            status_code=501,
            content={
                "error": "not_implemented",
                "detail": (
                    "DevCtl's browser-observe capability is a stub. Planned: "
                    "connect to aw-app-browser:9223 over CDP and return a "
                    "screenshot of the user's browser."
                ),
            },
        )

    return app
