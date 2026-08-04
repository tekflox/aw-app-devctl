function p() {
  try {
    return localStorage.getItem("aw_devctl") === "1";
  } catch {
    return !1;
  }
}
function f(e, n) {
  if (n = n || 0, n > 4) return "[deep]";
  if (e == null) return e;
  const r = typeof e;
  if (r === "function") return "[Function " + (e.name || "") + "]";
  if (r === "symbol") return e.toString();
  if (r !== "object") return e;
  if (e instanceof Error) return { _error: e.name, message: e.message, stack: (e.stack || "").slice(0, 1200) };
  if (typeof Element < "u" && e instanceof Element)
    return {
      _element: e.tagName,
      id: e.id || void 0,
      class: e.className || void 0,
      attrs: Array.from(e.attributes || []).reduce((t, a) => (t[a.name] = a.value, t), {}),
      rect: (() => {
        try {
          const t = e.getBoundingClientRect();
          return { x: t.x, y: t.y, w: t.width, h: t.height };
        } catch {
          return null;
        }
      })(),
      text: (e.textContent || "").slice(0, 200)
    };
  if (Array.isArray(e)) return e.slice(0, 100).map((t) => f(t, n + 1));
  try {
    const t = {}, a = Object.keys(e).slice(0, 100);
    for (const o of a)
      try {
        t[o] = f(e[o], n + 1);
      } catch (i) {
        t[o] = "[err:" + i.message + "]";
      }
    return t;
  } catch {
    return String(e);
  }
}
async function h(e) {
  const n = performance && performance.now ? performance.now() : Date.now();
  try {
    const t = await new Function("return (async () => { " + e + " })()")(), a = Math.round((performance && performance.now ? performance.now() : Date.now()) - n);
    return { result: f(t), ms: a };
  } catch (r) {
    const t = Math.round((performance && performance.now ? performance.now() : Date.now()) - n);
    return { error: String(r && r.stack || r && r.message || r), ms: t };
  }
}
function E({ wsUrl: e }) {
  let n = !1, r = null, t = 1e3, a = null, o = "closed";
  const i = /* @__PURE__ */ new Set();
  function l() {
    for (const c of i)
      try {
        c({ enabled: p(), state: o });
      } catch {
      }
  }
  function s(c) {
    o = c === "hello" ? "open" : c, l();
  }
  function d() {
    s("connecting");
    try {
      r = new WebSocket(e("/ws/tab"));
    } catch {
      s("error"), m();
      return;
    }
    r.addEventListener("open", () => {
      s("open"), t = 1e3;
    }), r.addEventListener("message", async (c) => {
      let u;
      try {
        u = JSON.parse(c.data);
      } catch {
        return;
      }
      if (u.cmd === "hello") {
        s("hello");
        return;
      }
      if (u.cmd === "eval") {
        const w = await h(u.code || "");
        try {
          r.send(JSON.stringify({ id: u.id, ...w }));
        } catch {
        }
      }
    }), r.addEventListener("close", () => {
      s("closed"), m();
    }), r.addEventListener("error", () => {
      s("error");
    });
  }
  function m() {
    a && clearTimeout(a), a = setTimeout(() => {
      n && d();
    }, t), t = Math.min(t * 2, 3e4);
  }
  function g() {
    if (n) return;
    n = !0;
    const c = () => d();
    typeof document < "u" && document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", c, { once: !0 }) : c();
  }
  function y() {
    if (a && (clearTimeout(a), a = null), r)
      try {
        r.onclose = null, r.close();
      } catch {
      }
    r = null, n = !1, o = "closed", l();
  }
  function b() {
    try {
      localStorage.setItem("aw_devctl", "1");
    } catch {
    }
    n = !1, g(), l();
  }
  function S() {
    try {
      localStorage.removeItem("aw_devctl");
    } catch {
    }
    y();
  }
  return {
    start: g,
    stop: y,
    enable: b,
    disable: S,
    isEnabled: p,
    getState: () => o,
    onStateChange(c) {
      return i.add(c), () => i.delete(c);
    }
  };
}
function k(e) {
  const n = E({ wsUrl: e.app.wsUrl });
  n.isEnabled() && n.start(), e.onDispose(() => n.stop());
  function r() {
    const [t, a] = e.React.useState(n.isEnabled()), [o, i] = e.React.useState(n.getState());
    e.React.useEffect(() => n.onStateChange((s) => {
      a(s.enabled), i(s.state);
    }), []);
    const l = t ? o === "open" ? "#22c55e" : o === "connecting" ? "#eab308" : "#ef4444" : "inherit";
    return e.h(
      "button",
      {
        type: "button",
        onClick: () => t ? n.disable() : n.enable(),
        title: `Remote dev channel — ${t ? "enabled, " + o : "disabled"}`,
        style: {
          color: l,
          background: "transparent",
          border: "none",
          cursor: "pointer",
          fontSize: "10px",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          width: "32px",
          flexShrink: 0,
          textAlign: "left"
        }
      },
      "dev",
      e.h("span", { style: { opacity: t ? 1 : 0 } }, "•")
    );
  }
  e.registerSlot("core.nav.right", r, { id: `${e.slug}:nav-toggle` });
}
export {
  k as default,
  k as register
};
