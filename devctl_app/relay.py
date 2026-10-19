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

Both are strictly additive: with ``share=False`` (or no ``ctx`` — see
``set_context``) this degrades to the original worker-local-only behaviour.

**Migrated off a direct ``src.libs.redis_coord`` import onto
``ctx.state`` (2026-10-19, Kanban 3fe5bf3b-9510-81d6-bab5-f69e1580ba40,
``docs/standards/app-shared-state.md``).** The tab registry is
``ctx.state.kv`` (a TTL'd put/get/scan — exactly the mirror shape above);
the eval relay is ``ctx.state.broadcast`` for both topics, via
``_CtxBroadcastAdapter``. Standalone mode (ADR Decision 4,
``devctl_app/__main__.py``) never calls ``set_context`` — a single process
has no cross-worker gap to close, so that mode's existing degrade-to-local
posture needs no raw Redis fallback at all.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import time
import uuid

log = logging.getLogger("aw_apps.devctl.relay")

#: How long a tab's kv entry survives without a heartbeat refresh — a few
#: missed heartbeats' worth of slack past _HEARTBEAT_INTERVAL_S, so a slow
#: Redis blip doesn't make a live tab flicker out of /tabs.
_TAB_TTL_S = 30
_HEARTBEAT_INTERVAL_S = 10

#: Bare local topic names ``ctx.state.broadcast`` namespaces under this
#: app's own id, and the full topic labels threaded through
#: ``_on_relay_message`` (unchanged — it dispatches by content, same as
#: before migration).
_EVAL_CMD_TOPIC = "devctl:evalcmd"
_EVAL_RESP_TOPIC = "devctl:evalresp"
_EVAL_CMD_BARE = "evalcmd"
_EVAL_RESP_BARE = "evalresp"


class _CtxBroadcastAdapter:
    """Adapts ``ctx.state.broadcast`` (per-topic publish/subscribe,
    ``state:own``) to the single ``start_relay(handler)`` /
    ``publish(topic, payload)`` / ``stop()`` interface this module's
    ``_on_relay_message(topic, payload)`` already speaks — it dispatches
    by content across BOTH eval topics, same as the raw
    ``RedisBroadcaster`` (one PSUBSCRIBE-everything relay) it replaces.
    """

    #: full topic label -> bare local name ``ctx.state.broadcast`` uses.
    _TOPICS = {_EVAL_CMD_TOPIC: _EVAL_CMD_BARE, _EVAL_RESP_TOPIC: _EVAL_RESP_BARE}

    def __init__(self, ctx) -> None:
        self._ctx = ctx

    async def start_relay(self, handler) -> None:
        for full_topic, bare in self._TOPICS.items():
            async def _dispatch(payload: dict, _t=full_topic) -> None:
                await handler(_t, payload)
            await self._ctx.state.broadcast.subscribe(bare, _dispatch)

    async def publish(self, topic: str, payload: dict) -> None:
        await self._ctx.state.broadcast.publish(self._TOPICS[topic], payload)

    async def stop(self) -> None:
        await self._ctx.state.broadcast.aclose()


class DevctlRelay:
    def __init__(self, share: bool = True) -> None:
        self.tabs: dict[str, dict] = {}  # conn_id -> {ws, user, ua, connected_at}
        self._pending: dict[int, asyncio.Future] = {}
        self._remote_pending: dict[str, asyncio.Future] = {}
        self._req_ids = itertools.count(1)
        # Off for unit tests that want purely local, Redis-free behaviour.
        self._share = share
        self._ctx = None
        self._broadcaster = None
        self._relay_up = False
        self._heartbeats: dict[str, asyncio.Task] = {}

    # ---- lifecycle ----------------------------------------------------

    def set_context(self, ctx) -> None:
        """Wire this relay to the app's real ``ctx`` (``state:own``) —
        called once from ``plugin.activate`` before ``start_relay``.
        Standalone mode (ADR Decision 4) never calls this; ``self._ctx``
        stays ``None`` and sharing degrades to this worker's own tabs."""
        self._ctx = ctx

    async def start_relay(self) -> None:
        """Start the cross-worker eval relay. Never raises: with no
        ``ctx`` (``set_context`` never called, or ``state:own`` not
        granted), every method below degrades to this worker's own tabs
        only — the same posture as every other relay in this codebase
        (see ``InstallJobs.start_relay``)."""
        if not self._share or self._ctx is None:
            return
        try:
            self._broadcaster = _CtxBroadcastAdapter(self._ctx)
            await self._broadcaster.start_relay(self._on_relay_message)
            self._relay_up = True
        except Exception:
            log.warning(
                "devctl: could not start the tab-relay over ctx.state.broadcast — "
                "/tabs and /eval will only see this worker's own tabs until "
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

    # ---- tab registration (mirrors InstallJobs' W3 STATE-mirror shape,
    # now via ctx.state.kv — conn_id is already a bare lowercase-hex
    # identifier, valid as a kv name with no further encoding) ------------

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
        if self._ctx is None:
            return
        try:
            await self._ctx.state.kv.put(conn_id, {
                "user": t["user"], "ua": t.get("ua", ""), "connected_at": t["connected_at"],
            }, ttl=_TAB_TTL_S)
        except Exception:
            log.debug("devctl: could not mirror tab %s via ctx.state.kv — /tabs "
                      "on other workers won't see it until this worker's own "
                      "poll answers", conn_id, exc_info=True)

    async def _clear_mirror(self, conn_id: str) -> None:
        if self._ctx is None:
            return
        try:
            await self._ctx.state.kv.delete(conn_id)
        except Exception:
            log.debug("devctl: could not clear the shared tab entry for %s",
                      conn_id, exc_info=True)

    async def list_tabs(self) -> list[dict]:
        """This worker's own live tabs (authoritative — they're the ones
        with a real WebSocket behind them) plus any tab another worker has
        mirrored via ``ctx.state.kv``, deduplicated by ``conn_id``."""
        tabs = {cid: {"conn_id": cid, "user": t["user"], "ua": t.get("ua", "")}
                for cid, t in self.tabs.items()}
        if self._share and self._ctx is not None:
            try:
                for cid in await self._ctx.state.kv.scan():
                    if cid in tabs:
                        continue
                    data = await self._ctx.state.kv.get(cid)
                    if not data:
                        continue
                    tabs[cid] = {"conn_id": cid, "user": data.get("user", "unknown"),
                                 "ua": data.get("ua", "")}
            except Exception:
                log.debug("devctl: could not read the shared tab registry — "
                          "falling back to this worker's own tabs only", exc_info=True)
        return list(tabs.values())

    # ---- eval -----------------------------------------------------------

    async def eval(self, code: str, user: str | None = None, conn_id: str | None = None,
                    timeout: float = 15.0) -> dict:
        """Run ``code`` in a connected tab, across EVERY worker.

        ``conn_id`` (from ``GET /tabs``) targets exactly that tab — required
        whenever more than one tab matches ``user`` (see ``_pick_target``);
        with exactly one match, ``conn_id`` is optional and that one tab is
        used. A tab owned by THIS worker is reached directly. A tab owned by
        another worker is reached over the Redis relay — see the module
        docstring; if the relay never came up (Redis unreachable), only
        this worker's own tabs are visible.
        """
        target = await self._pick_target(user, conn_id)
        if target is None:
            raise RuntimeError("no connected tab" + (f" for user {user}" if user else ""))
        conn_id, t = target
        if t is not None:
            return await self._eval_local(conn_id, t, code, timeout)
        return await self._eval_remote(conn_id, code, timeout)

    async def _pick_target(self, user: str | None,
                            conn_id: str | None = None) -> tuple[str, dict | None] | None:
        """Resolve which tab an eval targets.

        ``conn_id`` given: look it up directly (local dict, then the Redis
        mirror) and error if it is not currently connected — the caller
        asked for a specific tab, so silently falling back to a different
        one would repeat the exact incident (2026-09-09, Kanban card
        3d65bf3b-9510-81ca-bfec-ed8e5f1eaa89) this parameter exists to fix.

        ``conn_id`` omitted: auto-pick only when there is exactly ONE tab
        matching ``user`` — the previous "most recently connected wins"
        behaviour silently hit a stale tab whenever a second one was
        connected. With 2+ candidates we now raise, listing them, instead
        of guessing.
        """
        if conn_id is not None:
            t = self.tabs.get(conn_id)
            if t is not None:
                return conn_id, t
            if self._share and self._ctx is not None:
                try:
                    if (await self._ctx.state.kv.get(conn_id)) is not None:
                        return conn_id, None
                except Exception:
                    log.debug("devctl: could not consult the shared tab registry "
                              "for conn_id %s", conn_id, exc_info=True)
            raise RuntimeError(
                f"tab {conn_id} is not connected — call GET /tabs for the current list")

        candidates: list[dict] = [
            {"conn_id": cid, "user": t["user"], "ua": t.get("ua", ""), "t": t}
            for cid, t in self.tabs.items()
            if user is None or t["user"] == user
        ]
        if self._share and self._ctx is not None:
            try:
                known = {c["conn_id"] for c in candidates}
                for cid in await self._ctx.state.kv.scan():
                    if cid in known:
                        continue  # already covered by the local loop above
                    data = await self._ctx.state.kv.get(cid)
                    if not data:
                        continue
                    if user is not None and data.get("user") != user:
                        continue
                    candidates.append({"conn_id": cid, "user": data.get("user", "unknown"),
                                        "ua": data.get("ua", ""), "t": None})
            except Exception:
                log.debug("devctl: could not consult the shared tab registry "
                          "for eval target selection", exc_info=True)
        if not candidates:
            return None
        if len(candidates) > 1:
            listing = ", ".join(f"{c['conn_id']} ({c['user']}, {c['ua'] or 'unknown ua'})"
                                 for c in candidates)
            raise RuntimeError(
                f"{len(candidates)} tabs connected" + (f" for user {user}" if user else "") +
                f" — pass conn_id to pick one: {listing}")
        c = candidates[0]
        return c["conn_id"], c["t"]

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
