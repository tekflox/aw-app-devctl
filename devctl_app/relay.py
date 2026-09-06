"""DevCtl tab relay — remote JS eval into the USER's own browser tab.

Moved verbatim (ADR "Apps Own Their Front + Back Routes" Decision 5) from
the aw-workspace monolith's ``src/api/devctl_relay.py`` — that module lived
in core, which was wrong; this feature (tab registry + eval correlation) now
lives entirely inside this app. The browser-side counterpart is
``ui/src/client.js``; the HTTP/WS surface is wired in ``routes.py``.

Made cross-worker-safe (2026-09-06): ``AW_WORKSPACE_WORKERS`` was flipped
from 1 to 10 (commit 7ff36a9), which forks 10 separate OS processes — 10
separate Python heaps. A tab's WebSocket registers on whichever worker
accepted it, and cannot be handed to another process, so ``self.tabs`` stays
worker-local by necessity (same constraint as this workspace's own
``terminal_manager.py`` PTYs and aw-backend's ``/link`` tunnel). What is
added is:

* a Redis-mirrored, TTL'd registry (``aw:ws:<ws>:devctl:tab:<conn_id>``) so
  ``list_tabs()`` can report every tab connected anywhere, not just this
  worker's own — same STATE-mirror shape as ``src/apps/install_jobs.py``.
* a ``RedisBroadcaster`` relay so ``eval()`` can reach a tab owned by a
  DIFFERENT worker: the command is published for that tab's ``conn_id``,
  and only the worker that actually holds the WebSocket acts on it — the
  same per-message ownership dispatch aw-backend's ``host_link_relay.py``
  uses for the BYOD ``/link`` tunnel. The result is published back on a
  request-id-scoped topic that only the ORIGINATING worker is waiting on.

Both are strictly additive: with ``share=False`` (or Redis unreachable) this
degrades to the original worker-local-only behaviour.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import time
import uuid

log = logging.getLogger("aw_apps.devctl.relay")

#: How long a tab's Redis-mirrored entry survives without a heartbeat
#: refresh — a few missed heartbeats' worth of slack past _HEARTBEAT_INTERVAL_S,
#: so a slow Redis blip doesn't make a live tab flicker out of /tabs.
_TAB_TTL_S = 30
_HEARTBEAT_INTERVAL_S = 10

#: RedisBroadcaster topics for the cross-worker eval relay.
_EVAL_CMD_TOPIC = "devctl:evalcmd"
_EVAL_RESP_TOPIC = "devctl:evalresp"


class DevctlRelay:
    def __init__(self, share: bool = True) -> None:
        self.tabs: dict[str, dict] = {}  # conn_id -> {ws, user, ua, connected_at}
        self._pending: dict[int, asyncio.Future] = {}
        self._remote_pending: dict[str, asyncio.Future] = {}
        self._req_ids = itertools.count(1)
        # Off for unit tests that want purely local, Redis-free behaviour.
        self._share = share
        self._client = None
        self._broadcaster = None
        self._relay_up = False
        self._heartbeats: dict[str, asyncio.Task] = {}

    # ---- lifecycle ----------------------------------------------------

    async def start_relay(self) -> None:
        """Start the cross-worker eval relay. Never raises: with no
        reachable Redis, every method below degrades to this worker's own
        tabs only — the same posture as every other relay in this codebase
        (see ``InstallJobs.start_relay``)."""
        if not self._share:
            return
        try:
            from src.libs.redis_coord import RedisBroadcaster

            self._broadcaster = RedisBroadcaster()
            await self._broadcaster.start_relay(self._on_relay_message)
            self._relay_up = True
        except Exception:
            log.warning(
                "devctl: could not start the tab-relay Redis pub/sub — /tabs "
                "and /eval will only see this worker's own tabs until "
                "restarted (harmless at AW_WORKSPACE_WORKERS=1)", exc_info=True)

    async def aclose(self) -> None:
        for task in list(self._heartbeats.values()):
            task.cancel()
        self._heartbeats.clear()
        if self._broadcaster is not None:
            try:
                await self._broadcaster.stop()
            except Exception:  # noqa: BLE001 — shutdown path
                pass
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # noqa: BLE001 — shutdown path
                pass
            self._client = None

    def _redis(self):
        if not self._share:
            return None
        if self._client is None:
            import redis.asyncio as aioredis

            from src.libs.redis_coord import get_workspace_redis_url

            self._client = aioredis.from_url(get_workspace_redis_url(), decode_responses=True)
        return self._client

    @staticmethod
    def _tab_key_prefix() -> str:
        from src.libs.redis_coord import _key_prefix

        return f"{_key_prefix()}devctl:tab:"

    def _tab_key(self, conn_id: str) -> str:
        return f"{self._tab_key_prefix()}{conn_id}"

    # ---- tab registration (mirrors InstallJobs' W3 STATE-mirror shape) --

    async def register(self, ws, user: str | None, ua: str) -> str:
        """Register a newly-connected tab and return its ``conn_id``.

        Globally unique (``uuid4``, not a per-process counter) — with 10
        worker processes each keeping their own ``itertools.count(1)``,
        two tabs on different workers would otherwise collide on the same
        id in the shared Redis registry.
        """
        conn_id = uuid.uuid4().hex[:12]
        self.tabs[conn_id] = {
            "ws": ws, "user": user or "unknown", "ua": ua, "connected_at": time.time(),
        }
        if self._share:
            # Fire-and-forget: a slow/unreachable Redis must never add
            # latency to a tab's WS handshake.
            self._heartbeats[conn_id] = asyncio.create_task(self._heartbeat_loop(conn_id))
        return conn_id

    async def unregister(self, conn_id: str) -> None:
        self.tabs.pop(conn_id, None)
        task = self._heartbeats.pop(conn_id, None)
        if task is not None:
            task.cancel()
        if self._share:
            asyncio.create_task(self._clear_mirror(conn_id))

    async def _heartbeat_loop(self, conn_id: str) -> None:
        try:
            while conn_id in self.tabs:
                await self._mirror(conn_id)
                await asyncio.sleep(_HEARTBEAT_INTERVAL_S)
        except asyncio.CancelledError:
            pass

    async def _mirror(self, conn_id: str) -> None:
        t = self.tabs.get(conn_id)
        if t is None:
            return
        try:
            client = self._redis()
            if client is not None:
                payload = json.dumps({
                    "user": t["user"], "ua": t.get("ua", ""), "connected_at": t["connected_at"],
                })
                await client.set(self._tab_key(conn_id), payload, ex=_TAB_TTL_S)
        except Exception:
            log.debug("devctl: could not mirror tab %s to Redis — /tabs on "
                      "other workers won't see it until this worker's own "
                      "poll answers", conn_id, exc_info=True)

    async def _clear_mirror(self, conn_id: str) -> None:
        try:
            client = self._redis()
            if client is not None:
                await client.delete(self._tab_key(conn_id))
        except Exception:
            log.debug("devctl: could not clear the shared tab entry for %s",
                      conn_id, exc_info=True)

    async def list_tabs(self) -> list[dict]:
        """This worker's own live tabs (authoritative — they're the ones
        with a real WebSocket behind them) plus any tab another worker has
        mirrored into Redis, deduplicated by ``conn_id``."""
        tabs = {cid: {"conn_id": cid, "user": t["user"], "ua": t.get("ua", "")}
                for cid, t in self.tabs.items()}
        if self._share:
            try:
                client = self._redis()
                if client is not None:
                    prefix = self._tab_key_prefix()
                    async for key in client.scan_iter(match=f"{prefix}*"):
                        cid = key[len(prefix):]
                        if cid in tabs:
                            continue
                        raw = await client.get(key)
                        if not raw:
                            continue
                        try:
                            data = json.loads(raw)
                        except ValueError:
                            continue
                        tabs[cid] = {"conn_id": cid, "user": data.get("user", "unknown"),
                                     "ua": data.get("ua", "")}
            except Exception:
                log.debug("devctl: could not read the shared tab registry — "
                          "falling back to this worker's own tabs only", exc_info=True)
        return list(tabs.values())

    # ---- eval -----------------------------------------------------------

    async def eval(self, code: str, user: str | None = None, timeout: float = 15.0) -> dict:
        """Run ``code`` in the most-recently-connected tab matching ``user``
        (or any tab if ``user`` is None), across EVERY worker.

        A tab owned by THIS worker is reached directly. A tab owned by
        another worker is reached over the Redis relay — see the module
        docstring; if the relay never came up (Redis unreachable), only
        this worker's own tabs are visible.
        """
        target = await self._pick_target(user)
        if target is None:
            raise RuntimeError("no connected tab" + (f" for user {user}" if user else ""))
        conn_id, t = target
        if t is not None:
            return await self._eval_local(conn_id, t, code, timeout)
        return await self._eval_remote(conn_id, code, timeout)

    async def _pick_target(self, user: str | None) -> tuple[str, dict | None] | None:
        candidates: list[tuple[float, str, dict | None]] = [
            (t["connected_at"], cid, t) for cid, t in self.tabs.items()
            if user is None or t["user"] == user
        ]
        if self._share:
            try:
                client = self._redis()
                if client is not None:
                    prefix = self._tab_key_prefix()
                    async for key in client.scan_iter(match=f"{prefix}*"):
                        cid = key[len(prefix):]
                        if cid in self.tabs:
                            continue  # already covered by the local loop above
                        raw = await client.get(key)
                        if not raw:
                            continue
                        try:
                            data = json.loads(raw)
                        except ValueError:
                            continue
                        if user is not None and data.get("user") != user:
                            continue
                        candidates.append((data.get("connected_at", 0), cid, None))
            except Exception:
                log.debug("devctl: could not consult the shared tab registry "
                          "for eval target selection", exc_info=True)
        if not candidates:
            return None
        candidates.sort(key=lambda c: c[0])
        _connected_at, conn_id, t = candidates[-1]
        return conn_id, t

    async def _eval_local(self, conn_id: str, t: dict, code: str, timeout: float) -> dict:
        req_id = next(self._req_ids)
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut
        try:
            await t["ws"].send_text(json.dumps({"cmd": "eval", "id": req_id, "code": code}))
            res = await asyncio.wait_for(fut, timeout)
            return {"conn_id": conn_id, "user": t["user"], **res}
        finally:
            self._pending.pop(req_id, None)

    async def _eval_remote(self, conn_id: str, code: str, timeout: float) -> dict:
        if not self._relay_up:
            raise RuntimeError(
                f"tab {conn_id} is connected on another worker but the "
                f"cross-worker eval relay is not up (Redis unreachable?)")
        req_id = uuid.uuid4().hex
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._remote_pending[req_id] = fut
        try:
            await self._broadcaster.publish(
                _EVAL_CMD_TOPIC, {"conn_id": conn_id, "req_id": req_id, "code": code, "timeout": timeout})
            resp = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"tab {conn_id} did not respond within {timeout}s "
                f"(its owning worker may have died mid-eval)")
        finally:
            self._remote_pending.pop(req_id, None)
        if not resp.pop("ok", True):
            raise RuntimeError(resp.get("error") or "eval failed on the owning worker")
        return resp

    async def _on_relay_message(self, topic: str, payload: dict) -> None:
        """Dispatches by content, not by a dedicated per-worker channel —
        same "every worker gets it, only the owner acts" shape as
        aw-backend's ``host_link_relay.py``."""
        if topic == _EVAL_CMD_TOPIC:
            conn_id = payload.get("conn_id")
            t = self.tabs.get(conn_id)
            if t is None:
                return  # this worker doesn't own that tab — not for us
            try:
                result = await self._eval_local(conn_id, t, payload.get("code", ""),
                                                 float(payload.get("timeout") or 15.0))
                resp = {"ok": True, **result}
            except Exception as exc:
                # Mirrors the ``eval()``-raises path a same-process caller
                # would have hit — ``_eval_remote`` re-raises this rather
                # than letting a relay-level failure masquerade as a
                # successful eval with an "error" field (that field means
                # the tab's OWN JS threw, a different thing).
                resp = {"ok": False, "conn_id": conn_id, "error": str(exc)}
            try:
                await self._broadcaster.publish(_EVAL_RESP_TOPIC, {"req_id": payload.get("req_id"), **resp})
            except Exception:
                log.warning("devctl: could not publish an eval result back "
                            "over the relay", exc_info=True)
        elif topic == _EVAL_RESP_TOPIC:
            fut = self._remote_pending.get(payload.get("req_id"))
            if fut and not fut.done():
                fut.set_result({k: v for k, v in payload.items() if k != "req_id"})

    def _resolve(self, msg: dict) -> None:
        fut = self._pending.get(msg.get("id"))
        if fut and not fut.done():
            fut.set_result({k: msg.get(k) for k in ("result", "error", "ms")})


# Module-level singleton — one per worker process (unavoidable: each of
# AW_WORKSPACE_WORKERS' forked processes imports this module independently).
# Cross-worker visibility is handled explicitly above, not by this shape.
relay = DevctlRelay()
