# aw-app-devctl

AW workspace app for development control panels. **Scaffold only** — see
Status below.

## Vision

DevCtl = a dev-control panel for the workspace: a place for the agent (and
Frederico) to observe and act on tools running around the workspace that
aren't first-class apps yet.

**First planned capability (not implemented in this scaffold):** observe and
control the user's own browser by reusing the CDP (Chrome DevTools Protocol)
endpoint the `aw-app-browser` container already exposes in-workspace at
`aw-app-browser:9223` — live screenshot + navigation, so the agent can
"see" what's happening in the user's browser and drive it. `aw-app-browser`
already runs Chromium with CDP on 9223 for automation (see
`repos/aw-app-browser/aw-app.json`); DevCtl's job is to be a thin client
against that same CDP endpoint, not to run its own browser.

## Status: scaffold

- `aw-app.json` — manifest, `id: devctl`, `tier: inprocess`. No `windows`
  entry (removed 2026-08-05 — it was a single static-markdown "about" page
  with no real interactivity, which made the app show up as a dead-end
  clickable tile in the Apps grid's "visual" section like `aw-app-browser`,
  instead of the compact command-only list `has_windows: false` apps like
  MCP Tools get). The app's real UI is the `[dev]` toggle pill registered
  imperatively into `core.nav.right` by `ui/src/plugin.js` — see below.
- `devctl_app/plugin.py` — `DevctlAppPlugin.activate(ctx)` registers the
  routes sub-app via `ctx.routes` (`routes:register`). That's the only
  capability wired up.
- `devctl_app/routes.py` — **one stub route**,
  `GET /api/apps/devctl/browser/screenshot`, returns `501 not_implemented`
  with a message pointing at the CDP plan. This is the extension point for
  the real feature — TODO comment in the code marks exactly where the CDP
  client call goes.
- `schemas/aw-app.schema.json` — local structural validator (same schema
  used by `aw-app-browser`/`aw-app-node`/`aw-app-git`).
- `tests/validate_manifest.py` — validates `aw-app.json` against the schema
  (and any window spec file it references, if `contributes.windows` is ever
  reintroduced). Does not claim the app runs.

## Not implemented (out of scope for this scaffold)

- Actually connecting to `aw-app-browser:9223` over CDP.
- Screenshot capture / streaming.
- Browser navigation (URL bar, back/forward, click-through).
- Any UI beyond the stub markdown window.
- Any `nav`/`config_schema` beyond the empty placeholder.

## Why no Workspace nav

`aw-app-browser`'s own history flagged that this kind of app should not
register itself into `core.nav.workspace` — it belongs in the Apps grid's
command-only list (no `windows`, no `nav` entry — see above), not the
Workspace menu. Its real UI (the `[dev]` toggle) lives in `core.nav.right`
instead, registered by the component bundle.

## Layout

```
aw-app.json              manifest (tier: inprocess, no windows/nav contribution)
README.md                this file
schemas/aw-app.schema.json   structural validator (same as other apps)
devctl_app/
  plugin.py               DevctlAppPlugin entrypoint (registers routes only)
  routes.py                build_routes() — one stub endpoint
ui/src/plugin.js          component-mode entrypoint — registers the [dev] pill
tests/validate_manifest.py  manifest validation
```
