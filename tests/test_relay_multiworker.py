"""Cross-worker tab-relay regression test.

``AW_WORKSPACE_WORKERS`` was flipped from 1 to 10 (aw-workspace commit
7ff36a9), which forks 10 separate OS processes. ``DevctlRelay.tabs`` is a
plain in-process dict, so a tab registered on one worker used to be
completely invisible to ``/tabs``/``/eval`` requests served by any other
worker — 12/12 polls landed on one worker, 21+ tab registrations landed on
three different ones, and the two never overlapped (root cause on Kanban
card 3d35bf3b-9510-81e3-81ac-d7c16fe98aa4).

Mirrors aw-backend's ``test_f6_tunnel_relay_multiworker.py`` / aw-workspace's
own ``test_w4_ws_registries_redis_relay.py``: "two workers" is two
independent ``DevctlRelay`` instances sharing one real Redis — a tab
registered exclusively on instance A must be visible/reachable from
instance B, since that is exactly the cross-process gap
``AW_WORKSPACE_WORKERS=10`` opened up.

Needs BOTH a reachable Redis (``AW_TEST_REDIS_URL`` / ``AW_WORKSPACE_REDIS_URL``
/ ``AW_REDIS_URL`` — same resolution order ``relay.py`` itself uses) AND
aw-workspace core's own ``src`` package on ``sys.path``: ``relay.py``'s
Redis-backed methods lazy-import ``src.libs.redis_coord``, only importable
when this app is running INSIDE an aw-workspace checkout — not the case in
this repo's own CI (no aw-workspace checkout, no Redis service), so this
test skips cleanly there, same posture as its aw-backend/aw-workspace
precedents skipping without a reachable Redis.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # devctl_app on sys.path

_WORKSPACE_ROOT = Path(os.environ.get("AW_WORKSPACE_CONTAINER_DIR", "/opt/aw-workspace"))
if (_WORKSPACE_ROOT / "src" / "libs" / "redis_coord.py").is_file():
    sys.path.insert(0, str(_WORKSPACE_ROOT))


def _redis_url() -> str:
    for var in ("AW_TEST_REDIS_URL", "AW_WORKSPACE_REDIS_URL", "AW_REDIS_URL"):
        url = os.environ.get(var)
        if url:
            return url
    return "redis://127.0.0.1:6379/0"


def _src_available() -> bool:
    try:
        import src.libs.redis_coord  # noqa: F401
        return True
    except Exception:
        return False


def _redis_available() -> bool:
    if not _src_available():
        return False
    try:
        import redis as sync_redis

        client = sync_redis.Redis.from_url(_redis_url(), socket_connect_timeout=2)
        return bool(client.ping())
    except Exception:
        return False


pytestmark = [
    pytest.mark.skipif(not _src_available(), reason="aw-workspace core's src package is not on sys.path"),
    pytest.mark.skipif(not _redis_available(), reason="Redis not reachable"),
]

# Isolate this run's keys from any real workspace sharing the same Redis.
os.environ["AW_WORKSPACE"] = f"devctl-relay-test-{uuid.uuid4().hex[:8]}"


class _FakeTabWebSocket:
    """Stand-in for the browser tab's WebSocket — records what the relay sent."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, msg: str) -> None:
        self.sent.append(msg)


async def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.05) -> bool:
    """Polls ``predicate()``, awaiting it first if it returns a coroutine —
    ``asyncio`` predicates are as easy to pass here as sync ones, and a
    coroutine object is truthy on its own, so failing to await it here would
    make every check pass without ever running."""
    async def _check():
        result = predicate()
        if asyncio.iscoroutine(result):
            result = await result
        return result

    deadline = time.time() + timeout
    while time.time() < deadline:
        if await _check():
            return True
        await asyncio.sleep(interval)
    return await _check()


class TestTabRegistryRelay:
    def test_tab_registered_on_worker_a_is_visible_from_worker_b(self):
        async def scenario():
            from devctl_app.relay import DevctlRelay

            worker_a = DevctlRelay()
            worker_b = DevctlRelay()
            await worker_a.start_relay()
            await worker_b.start_relay()

            ws = _FakeTabWebSocket()
            cid = await worker_a.register(ws, user="frederico", ua="test-ua")
            try:
                async def seen_on_b():
                    tabs = await worker_b.list_tabs()
                    return any(t["conn_id"] == cid for t in tabs)

                assert await _wait_until(seen_on_b), (
                    "a tab registered exclusively on worker A never showed up "
                    "in worker B's list_tabs() — this is the exact bug the "
                    "WORKERS=10 flip caused")

                # worker A never lost track of its own tab either.
                assert any(t["conn_id"] == cid for t in await worker_a.list_tabs())
            finally:
                await worker_a.unregister(cid)
                await worker_a.aclose()
                await worker_b.aclose()

        asyncio.run(scenario())

    def test_unregister_removes_it_from_the_shared_view(self):
        async def scenario():
            from devctl_app.relay import DevctlRelay

            worker_a = DevctlRelay()
            worker_b = DevctlRelay()
            await worker_a.start_relay()
            await worker_b.start_relay()

            ws = _FakeTabWebSocket()
            cid = await worker_a.register(ws, user="frederico", ua="test-ua")
            try:
                async def seen_on_b():
                    return any(t["conn_id"] == cid for t in await worker_b.list_tabs())

                assert await _wait_until(seen_on_b)
                await worker_a.unregister(cid)

                async def gone_from_b():
                    return not any(t["conn_id"] == cid for t in await worker_b.list_tabs())

                assert await _wait_until(gone_from_b)
            finally:
                await worker_a.aclose()
                await worker_b.aclose()

        asyncio.run(scenario())


class TestEvalRelay:
    def test_eval_reaches_a_tab_owned_by_another_worker(self):
        async def scenario():
            from devctl_app.relay import DevctlRelay

            worker_a = DevctlRelay()  # owns the tab's real WebSocket
            worker_b = DevctlRelay()  # receives the POST /eval
            await worker_a.start_relay()
            await worker_b.start_relay()

            ws = _FakeTabWebSocket()
            cid = await worker_a.register(ws, user="frederico", ua="test-ua")
            try:
                eval_task = asyncio.create_task(
                    worker_b.eval("1+1", user="frederico", timeout=5.0))

                # Only worker A holds the tab's WebSocket — it must be the one
                # that actually sees the eval command land, exactly as the
                # real browser tab would over its own connection.
                assert await _wait_until(lambda: len(ws.sent) >= 1)
                cmd = json.loads(ws.sent[-1])
                assert cmd["cmd"] == "eval"
                assert cmd["code"] == "1+1"
                worker_a._resolve({"id": cmd["id"], "result": 2, "ms": 1})

                result = await asyncio.wait_for(eval_task, timeout=5.0)
                assert result["conn_id"] == cid
                assert result["result"] == 2
            finally:
                await worker_a.unregister(cid)
                await worker_a.aclose()
                await worker_b.aclose()

        asyncio.run(scenario())

    def test_eval_with_conn_id_reaches_a_tab_owned_by_another_worker(self):
        """conn_id's cross-worker lookup goes through the Redis mirror (the
        tab isn't in worker_b's own ``self.tabs``) — the exact path
        ``_pick_target``'s ``client.exists(self._tab_key(conn_id))`` branch
        exists for, distinct from the local-dict lookup test_routes.py's
        same-process tests already cover."""
        async def scenario():
            from devctl_app.relay import DevctlRelay

            worker_a = DevctlRelay()  # owns the tab's real WebSocket
            worker_b = DevctlRelay()  # receives the POST /eval with conn_id
            await worker_a.start_relay()
            await worker_b.start_relay()

            ws = _FakeTabWebSocket()
            cid = await worker_a.register(ws, user="frederico", ua="test-ua")
            try:
                async def mirrored_on_b():
                    return await worker_b._redis().exists(worker_b._tab_key(cid))

                assert await _wait_until(mirrored_on_b), (
                    "worker A's tab never showed up in the shared Redis "
                    "registry — conn_id lookup on another worker has "
                    "nothing to find")

                eval_task = asyncio.create_task(
                    worker_b.eval("1+1", conn_id=cid, timeout=5.0))

                assert await _wait_until(lambda: len(ws.sent) >= 1)
                cmd = json.loads(ws.sent[-1])
                assert cmd["cmd"] == "eval"
                worker_a._resolve({"id": cmd["id"], "result": 2, "ms": 1})

                result = await asyncio.wait_for(eval_task, timeout=5.0)
                assert result["conn_id"] == cid
                assert result["result"] == 2
            finally:
                await worker_a.unregister(cid)
                await worker_a.aclose()
                await worker_b.aclose()

        asyncio.run(scenario())

    def test_eval_relay_timeout_raises_instead_of_a_fake_success(self):
        async def scenario():
            from devctl_app.relay import DevctlRelay

            worker_a = DevctlRelay()
            worker_b = DevctlRelay()
            await worker_a.start_relay()
            await worker_b.start_relay()

            ws = _FakeTabWebSocket()
            cid = await worker_a.register(ws, user="frederico", ua="test-ua")
            try:
                # Nothing ever answers the tab's eval command — the owning
                # worker's own local round trip times out, and that failure
                # must surface as a raise, not an "ok" result with a stale value.
                with pytest.raises(RuntimeError):
                    await worker_b.eval("1+1", user="frederico", timeout=0.3)
            finally:
                await worker_a.unregister(cid)
                await worker_a.aclose()
                await worker_b.aclose()

        asyncio.run(scenario())
