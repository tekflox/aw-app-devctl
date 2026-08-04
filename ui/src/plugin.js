// Integrated-mode entrypoint (ADR "Apps Own Their Front + Back Routes"
// Decision 3/5) — dynamic-imported by aw-frontend's loadComponentPlugin()
// when this app is installed SIGNED with "ui:code" granted (effectiveMode()
// downgrades any other install to iframe mode, and this file never runs).
// Built by `npm run build:plugin` -> ui/dist/devctl.js, referenced from
// aw-app.json's contributes.frontend.bundle.
//
// register(host) is the ONE required export, and here it's a HEADLESS
// registration by default (pluginHost.js's sanctioned pattern): the tab
// client starts iff the user already opted in (localStorage.aw_devctl —
// no more force-enable, Decision 5), independent of whether the [dev] pill
// below is even rendered. Every teardown goes through host.onDispose(fn).

import { createDevctlClient } from './client.js';

export function register(host) {
  const client = createDevctlClient({ wsUrl: host.app.wsUrl });

  if (client.isEnabled()) client.start();
  host.onDispose(() => client.stop());

  // [dev] pill in the top-right nav (core.nav.right, next to the mic) —
  // toggles the relay on/off, shows connection state (green=open,
  // yellow=connecting, red/gray=closed|error). Fixed width + the state dot
  // as its own always-present span (opacity toggled, not conditionally
  // appended text) so state changes never shift neighboring icons.
  function DevTogglePill() {
    const [enabled, setEnabled] = host.React.useState(client.isEnabled());
    const [state, setState] = host.React.useState(client.getState());
    host.React.useEffect(() => client.onStateChange((next) => {
      setEnabled(next.enabled);
      setState(next.state);
    }), []);
    const color = !enabled ? 'inherit' : state === 'open' ? '#22c55e' : state === 'connecting' ? '#eab308' : '#ef4444';
    return host.h(
      'button',
      {
        type: 'button',
        onClick: () => (enabled ? client.disable() : client.enable()),
        title: enabled
          ? `Remote dev channel — enabled, ${state}. Turn it off to stop.`
          : 'Turn it on and ask the agent to interact with your UI',
        style: {
          color, background: 'transparent', border: 'none', cursor: 'pointer',
          fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.05em',
          width: '32px', flexShrink: 0, textAlign: 'left',
        },
      },
      'dev',
      host.h('span', { style: { opacity: enabled ? 1 : 0 } }, '•'),
    );
  }
  host.registerSlot('core.nav.right', DevTogglePill, { id: `${host.slug}:nav-toggle` });
}

export default register;
