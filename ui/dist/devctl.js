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
      attrs: Array.from(e.attributes || []).reduce((t, o) => (t[o.name] = o.value, t), {}),
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
    const t = {}, o = Object.keys(e).slice(0, 100);
    for (const c of o)
      try {
        t[c] = f(e[c], n + 1);
      } catch (s) {
        t[c] = "[err:" + s.message + "]";
      }
    return t;
  } catch {
    return String(e);
  }
}
async function b(e) {
  const n = performance && performance.now ? performance.now() : Date.now();
  try {
    const t = await new Function("return (async () => { " + e + " })()")(), o = Math.round((performance && performance.now ? performance.now() : Date.now()) - n);
    return { result: f(t), ms: o };
  } catch (r) {
    const t = Math.round((performance && performance.now ? performance.now() : Date.now()) - n);
    return { error: String(r && r.stack || r && r.message || r), ms: t };
  }
}
function E({ wsUrl: e }) {
  let n = !1, r = null, t = 1e3, o = null, c = "closed";
  const s = /* @__PURE__ */ new Set();
  function l() {
    for (const a of s)
      try {
        a({ enabled: p(), state: c });
      } catch {
      }
  }
  function i(a) {
    c = a === "hello" ? "open" : a, l();
  }
  function d() {
    i("connecting");
    try {
      r = new WebSocket(e("/ws/tab"));
    } catch {
      i("error"), m();
      return;
    }
    r.addEventListener("open", () => {
      i("open"), t = 1e3;
    }), r.addEventListener("message", async (a) => {
      let u;
      try {
        u = JSON.parse(a.data);
      } catch {
        return;
      }
      if (u.cmd === "hello") {
        i("hello");
        return;
      }
      if (u.cmd === "eval") {
        const S = await b(u.code || "");
        try {
          r.send(JSON.stringify({ id: u.id, ...S }));
        } catch {
        }
      }
    }), r.addEventListener("close", (a) => {
      if (a.code === 4401 || a.code === 4403 || a.code === 4426) {
        i("unauthorized");
        try {
          window.dispatchEvent(new Event("aw-auth-failed"));
        } catch {
        }
        return;
      }
      i("closed"), m();
    }), r.addEventListener("error", () => {
      i("error");
    });
  }
  function m() {
    o && clearTimeout(o), o = setTimeout(() => {
      n && d();
    }, t), t = Math.min(t * 2, 3e4);
  }
  function g() {
    if (n) return;
    n = !0;
    const a = () => d();
    typeof document < "u" && document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", a, { once: !0 }) : a();
  }
  function y() {
    if (o && (clearTimeout(o), o = null), r)
      try {
        r.onclose = null, r.close();
      } catch {
      }
    r = null, n = !1, c = "closed", l();
  }
  function w() {
    try {
      localStorage.setItem("aw_devctl", "1");
    } catch {
    }
    n = !1, g(), l();
  }
  function h() {
    try {
      localStorage.removeItem("aw_devctl");
    } catch {
    }
    y();
  }
  return {
    start: g,
    stop: y,
    enable: w,
    disable: h,
    isEnabled: p,
    getState: () => c,
    onStateChange(a) {
      return s.add(a), () => s.delete(a);
    }
  };
}
function k(e) {
  const n = E({ wsUrl: e.app.wsUrl });
  n.isEnabled() && n.start(), e.onDispose(() => n.stop());
  function r() {
    const [t, o] = e.React.useState(n.isEnabled()), [c, s] = e.React.useState(n.getState());
    e.React.useEffect(() => n.onStateChange((i) => {
      o(i.enabled), s(i.state);
    }), []);
    const l = t ? c === "open" ? "#22c55e" : c === "connecting" ? "#eab308" : "#ef4444" : "inherit";
    return e.h(
      "button",
      {
        type: "button",
        onClick: () => t ? n.disable() : n.enable(),
        title: t ? `Remote dev channel — enabled, ${c}. Turn it off to stop.` : "Turn it on and ask the agent to interact with your UI",
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
