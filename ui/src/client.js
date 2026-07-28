// Framework-free tab-relay client core (ADR "Apps Own Their Front + Back
// Routes" Decision 4/5) — ported from the aw-workspace monolith's
// src/lib/devctlClient.js, unaware of whether it's running integrated
// (behind IdentityGuard, inside the AW SPA) or standalone (its own page, no
// auth). Both plugin.js and standalone.js build the same {wsUrl} shape and
// hand it here.
//
// Opt-in only — the core's force-enable is GONE (Decision 5): this tab does
// NOT connect on load unless the user has already turned it on (persisted
// in localStorage.aw_devctl), matching the [dev] pill's toggle.
//
//   wsUrl: (sub) => string   e.g. sub="/ws/tab" -> "ws(s)://.../api/apps/devctl/ws/tab"

export function isDevctlEnabled() {
  try { return localStorage.getItem('aw_devctl') === '1'; } catch { return false; }
}

function safeSerialize(v, depth) {
  depth = depth || 0;
  if (depth > 4) return '[deep]';
  if (v === null || v === undefined) return v;
  const t = typeof v;
  if (t === 'function') return '[Function ' + (v.name || '') + ']';
  if (t === 'symbol') return v.toString();
  if (t !== 'object') return v;
  if (v instanceof Error) return { _error: v.name, message: v.message, stack: (v.stack || '').slice(0, 1200) };
  if (typeof Element !== 'undefined' && v instanceof Element) {
    return {
      _element: v.tagName,
      id: v.id || undefined,
      class: v.className || undefined,
      attrs: Array.from(v.attributes || []).reduce((m, a) => (m[a.name] = a.value, m), {}),
      rect: (() => { try { const r = v.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; } catch { return null; } })(),
      text: (v.textContent || '').slice(0, 200),
    };
  }
  if (Array.isArray(v)) return v.slice(0, 100).map((x) => safeSerialize(x, depth + 1));
  try {
    const out = {};
    const keys = Object.keys(v).slice(0, 100);
    for (const k of keys) {
      try { out[k] = safeSerialize(v[k], depth + 1); } catch (e) { out[k] = '[err:' + e.message + ']'; }
    }
    return out;
  } catch {
    return String(v);
  }
}

async function evalCode(code) {
  const t0 = (performance && performance.now) ? performance.now() : Date.now();
  try {
    // eslint-disable-next-line no-new-func
    const fn = new Function('return (async () => { ' + code + ' })()');
    const result = await fn();
    const ms = Math.round(((performance && performance.now) ? performance.now() : Date.now()) - t0);
    return { result: safeSerialize(result), ms };
  } catch (e) {
    const ms = Math.round(((performance && performance.now) ? performance.now() : Date.now()) - t0);
    return { error: String((e && e.stack) || (e && e.message) || e), ms };
  }
}

// Creates one client instance bound to a {wsUrl} URL builder. Returns a
// tiny controller: start()/stop() connect/disconnect the tab, enable()/
// disable() additionally flip the localStorage opt-in flag, getState()/
// onStateChange(cb) let a UI (the [dev] pill) react to the connection.
export function createDevctlClient({ wsUrl }) {
  let started = false;
  let ws = null;
  let reconnectDelay = 1000;
  let reconnectTimer = null;
  let connectionState = 'closed'; // 'closed' | 'connecting' | 'open' | 'error'
  const stateListeners = new Set();

  function notify() {
    for (const cb of stateListeners) {
      try { cb({ enabled: isDevctlEnabled(), state: connectionState }); } catch { /* keep notifying the rest */ }
    }
  }

  function setStatus(state) {
    connectionState = state === 'hello' ? 'open' : state;
    notify();
  }

  function connect() {
    setStatus('connecting');
    try {
      ws = new WebSocket(wsUrl('/ws/tab'));
    } catch (e) {
      setStatus('error');
      scheduleReconnect();
      return;
    }
    ws.addEventListener('open', () => {
      setStatus('open');
      reconnectDelay = 1000;
    });
    ws.addEventListener('message', async (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.cmd === 'hello') {
        setStatus('hello');
        return;
      }
      if (msg.cmd === 'eval') {
        const out = await evalCode(msg.code || '');
        try { ws.send(JSON.stringify({ id: msg.id, ...out })); } catch { /* connection dropped mid-eval */ }
      }
    });
    ws.addEventListener('close', () => {
      setStatus('closed');
      scheduleReconnect();
    });
    ws.addEventListener('error', () => {
      setStatus('error');
    });
  }

  function scheduleReconnect() {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(() => {
      if (started) connect();
    }, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 30000);
  }

  function start() {
    if (started) return;
    started = true;
    const go = () => connect();
    if (typeof document !== 'undefined' && document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', go, { once: true });
    } else {
      go();
    }
  }

  function stop() {
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    if (ws) { try { ws.onclose = null; ws.close(); } catch { /* already closing */ } }
    ws = null;
    started = false;
    connectionState = 'closed';
    notify();
  }

  function enable() {
    try { localStorage.setItem('aw_devctl', '1'); } catch { /* private mode, best-effort */ }
    started = false; // allow reconnect even if a prior start() returned early (disabled)
    start();
    notify();
  }

  function disable() {
    try { localStorage.removeItem('aw_devctl'); } catch { /* private mode, best-effort */ }
    stop();
  }

  return {
    start,
    stop,
    enable,
    disable,
    isEnabled: isDevctlEnabled,
    getState: () => connectionState,
    onStateChange(cb) {
      stateListeners.add(cb);
      return () => stateListeners.delete(cb);
    },
  };
}
