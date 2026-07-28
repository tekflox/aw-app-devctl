"""DevCtl tab relay — remote JS eval into the USER's own browser tab.

Moved verbatim (ADR "Apps Own Their Front + Back Routes" Decision 5) from
the aw-workspace monolith's ``src/api/devctl_relay.py`` — that module lived
in core, which was wrong; this feature (tab registry + eval correlation) now
lives entirely inside this app. The browser-side counterpart is
``ui/src/client.js``; the HTTP/WS surface is wired in ``routes.py``.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging

log = logging.getLogger("aw_apps.devctl.relay")


class DevctlRelay:
    def __init__(self) -> None:
        self.tabs: dict[int, dict] = {}      # conn_id -> {ws, user, ua}
        self._pending: dict[int, asyncio.Future] = {}
        self._req_ids = itertools.count(1)
        self._conn_ids = itertools.count(1)

    def list_tabs(self) -> list[dict]:
        return [{"conn_id": cid, "user": t["user"], "ua": t.get("ua", "")}
                for cid, t in self.tabs.items()]

    async def eval(self, code: str, user: str | None = None, timeout: float = 15.0) -> dict:
        targets = [(cid, t) for cid, t in self.tabs.items()
                   if user is None or t["user"] == user]
        if not targets:
            raise RuntimeError(f"no connected tab" + (f" for user {user}" if user else ""))
        cid, t = targets[-1]  # most recently connected
        req_id = next(self._req_ids)
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut
        await t["ws"].send_text(json.dumps({"cmd": "eval", "id": req_id, "code": code}))
        try:
            res = await asyncio.wait_for(fut, timeout)
            return {"conn_id": cid, "user": t["user"], **res}
        finally:
            self._pending.pop(req_id, None)

    def _resolve(self, msg: dict) -> None:
        fut = self._pending.get(msg.get("id"))
        if fut and not fut.done():
            fut.set_result({k: msg.get(k) for k in ("result", "error", "ms")})


# Module-level singleton — mirrors the core's shape. One relay per process
# (both integrated in-process mode and standalone mode run one process).
relay = DevctlRelay()
