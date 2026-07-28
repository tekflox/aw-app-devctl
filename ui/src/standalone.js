// Standalone-mode entrypoint (ADR Decision 4) — loaded by ui/index.html when
// this app runs as its own page (`python -m devctl_app`): no aw-frontend
// plugin host, no IdentityGuard. Same client core as plugin.js, but with
// same-origin relative/ws(s) URLs instead of the app-scoped host helpers.

import { createDevctlClient } from './client.js';

const SLUG = 'devctl';

const client = createDevctlClient({
  wsUrl: (sub) => {
    const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${scheme}//${location.host}/api/apps/${SLUG}${sub}`;
  },
});

function render() {
  const status = document.getElementById('status');
  const toggle = document.getElementById('toggle');
  status.textContent = `${client.isEnabled() ? 'enabled' : 'disabled'} — ${client.getState()}`;
  toggle.textContent = client.isEnabled() ? 'Disable' : 'Enable';
}

client.onStateChange(render);
document.getElementById('toggle').addEventListener('click', () => {
  if (client.isEnabled()) client.disable(); else client.enable();
  render();
});

if (client.isEnabled()) client.start();
render();
