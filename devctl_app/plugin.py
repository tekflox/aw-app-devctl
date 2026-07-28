"""Entrypoint referenced by aw-app.json's runtime.entrypoint
("devctl_app.plugin:DevctlAppPlugin").

Scaffold plugin: registers the app's (currently stub-only) routes sub-app.
No other capability is wired up yet — see repo README for the intended
first capability (browser observe/control via aw-app-browser's CDP :9223).
"""

from __future__ import annotations

import logging

from . import routes as routes_mod

log = logging.getLogger("aw_apps.devctl")


class DevctlAppPlugin:
    async def activate(self, ctx) -> None:
        self.ctx = ctx
        subapp = routes_mod.build_routes()
        ctx.routes.register(subapp)
        log.info("aw-app-devctl activated (scaffold)")

    async def deactivate(self) -> None:
        log.info("aw-app-devctl deactivated")
