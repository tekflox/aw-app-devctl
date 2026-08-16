---
repo: architecture
path: docs/architecture/aw-app-devctl.md
source: generated
edited: false
checksum: sha256:4691df8f36fa0fb2830a989742d2eaba250a4750cb9fb9fd33fa625838e99d3f
---
# DevCtl

- **repo**: aw-app-devctl
- **layer**: app
- **technologies**: python, react
- **health** (derived): planned

Dev-control panel for the workspace: (1) a piloted browser — observes and controls the aw-app-browser container over CDP (aw-app-browser:9223), live screenshot, screencast over a WebSocket, navigate, click/type/key/scroll, evaluate/inject JS; (2) a tab relay — remote JS eval into the USER's OWN live browser tab (moved from the aw-workspace monolith, ADR "Apps Own Their Front + Back Routes" Decision 5), with a [dev] top-nav toggle and an agent-driven local /eval + /tabs escape hatch. Runs standalone too (Decision 4). Backend routes under /api/apps/devctl; a devctl-browser MCP tool wrapper (piloted-browser navigate/click/type/eval/screenshot) is contributed for agents via mcp.json.

## Connections
- `http` → **aw-workspace** — routes mounted at /api/apps/devctl

## MCP tools
_none exposed_

## Requirements
_none documented_
