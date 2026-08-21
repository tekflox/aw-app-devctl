"""TestClient smoke test for devctl_app.routes.build_routes()'s tab relay
(ADR "Apps Own Their Front + Back Routes" Decision 5) — GET /tabs, WS
/ws/tab, POST /eval, exercised the same way both modes mount the sub-app
(no IdentityGuard here, matching standalone / __main__.py's posture; the
integrated-mode auth wrapper is aw-workspace runtime machinery and is
covered by that repo's own tests).

Run: .venv/aw/bin/python -m pytest tests/test_routes.py -q
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from devctl_app.routes import build_routes  # noqa: E402


def _client() -> TestClient:
    return TestClient(build_routes())


def test_tabs_starts_empty():
    with _client() as c:
        resp = c.get("/tabs")
        assert resp.status_code == 200
        assert resp.json() == {"tabs": []}


def test_eval_with_no_connected_tab_returns_ok_false():
    with _client() as c:
        resp = c.post("/eval", json={"code": "1+1"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert "no connected tab" in body["error"]


def test_eval_requires_code():
    with _client() as c:
        resp = c.post("/eval", json={})
        assert resp.status_code == 400
        assert resp.json()["ok"] is False


def test_tab_registers_receives_hello_then_answers_eval():
    # POST /eval blocks (TestClient's portal) until the tab replies over the
    # WS, so it has to run on its own thread while the main thread drives
    # the WS side of the same in-flight request — real callers are two
    # independent connections doing exactly this concurrently.
    with _client() as c:
        with c.websocket_connect("/ws/tab") as ws:
            hello = ws.receive_json()
            assert hello == {"cmd": "hello"}

            result = {}

            def do_eval():
                result["resp"] = c.post("/eval", json={"code": "return 41 + 1"})

            t = threading.Thread(target=do_eval)
            t.start()

            eval_msg = ws.receive_json()
            assert eval_msg["cmd"] == "eval"
            assert eval_msg["code"] == "return 41 + 1"
            ws.send_text(json.dumps({"id": eval_msg["id"], "result": 42, "ms": 1}))

            t.join(timeout=5)
            resp = result["resp"]
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["result"] == 42

        resp = c.get("/tabs")
        assert resp.json() == {"tabs": []}


def test_render_screenshot_requires_absolute_http_url():
    with _client() as c:
        resp = c.post("/render/screenshot", json={"url": "not-a-url"})
        assert resp.status_code == 400

        resp = c.post("/render/screenshot", json={})
        assert resp.status_code == 400
