# aw-app-devctl

Decoupled app for aw-workspace, per the
[Decoupled Apps Framework ADR](../../docs/knowledge_base/docs/architecture/decoupled-apps-framework.md)
(`aw-app.json` manifest schema v1). **Scaffold only** — see Status below.

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

- `aw-app.json` — manifest, `id: devctl`, `tier: inprocess`. Contributes a
  `windows` entry only (**no `nav` entry, deliberately** — see "Why no
  Workspace nav" below), so the app shows up as a card in the Apps grid with
  a default window, the same shape as `aw-app-browser`'s manifest.
- `devctl_app/plugin.py` — `DevctlAppPlugin.activate(ctx)` registers the
  routes sub-app via `ctx.routes` (`routes:register`). That's the only
  capability wired up.
- `devctl_app/routes.py` — **one stub route**,
  `GET /api/apps/devctl/browser/screenshot`, returns `501 not_implemented`
  with a message pointing at the CDP plan. This is the extension point for
  the real feature — TODO comment in the code marks exactly where the CDP
  client call goes.
- `windows/main.json` — a single markdown widget explaining the scaffold
  state and the stub endpoint; no real UI yet.
- `schemas/aw-app.schema.json` — local structural validator (same schema
  used by `aw-app-browser`/`aw-app-node`/`aw-app-git`).
- `tests/validate_manifest.py` — validates `aw-app.json` against the schema
  and checks the window spec file exists. Does not claim the app runs.

## Not implemented (out of scope for this scaffold)

- Actually connecting to `aw-app-browser:9223` over CDP.
- Screenshot capture / streaming.
- Browser navigation (URL bar, back/forward, click-through).
- Any UI beyond the stub markdown window.
- Any `nav`/`config_schema` beyond the empty placeholder.

## Why no Workspace nav

`aw-app-browser`'s own history flagged that a decoupled app should NOT
register itself into `core.nav.workspace` — it belongs in the Apps grid,
not the Workspace menu. This manifest follows that: `contributes` has
`windows` but no `nav` entry, matching `aw-app-browser`'s manifest shape
exactly (compare `repos/aw-app-browser/aw-app.json`).

## Layout

```
aw-app.json              manifest (tier: inprocess, no nav contribution)
README.md                this file
schemas/aw-app.schema.json   structural validator (same as other apps)
devctl_app/
  plugin.py               DevctlAppPlugin entrypoint (registers routes only)
  routes.py                build_routes() — one stub endpoint
windows/main.json         declarative window (markdown stub)
tests/validate_manifest.py  manifest + window-spec existence check
```
