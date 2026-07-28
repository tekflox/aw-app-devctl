// Two build targets, both writing into the SAME ui/dist/ (ADR "Apps Own
// Their Front + Back Routes" Decision 4/5). Selected via `--mode`:
//
//   vite build --mode plugin      -> dist/devctl.js     (lib mode; the bundle
//                                     contributes.frontend.bundle points at)
//   vite build --mode standalone  -> dist/index.html + assets (a normal app
//                                     build; what __main__.py serves as GET /)
//
// `npm run build` (package.json) runs both, in that order, with
// `emptyOutDir: false` so the second build doesn't wipe the first's output.
import { defineConfig } from 'vite';

export default defineConfig(({ mode }) => {
  if (mode === 'plugin') {
    return {
      build: {
        outDir: 'dist',
        emptyOutDir: false,
        lib: {
          entry: 'src/plugin.js',
          formats: ['es'],
          fileName: () => 'devctl.js',
        },
        rollupOptions: {
          // plugin.js never imports react/react-dom directly — it uses
          // host.React / host.h from window.__AW_PLUGIN_HOST__ — but
          // externalize anyway so no second React copy sneaks in if that
          // changes later.
          external: ['react', 'react-dom'],
        },
      },
    };
  }
  // mode === 'standalone' (also the default `vite build`/`vite`): a normal
  // app build — index.html + src/standalone.js bundled together.
  return {
    build: {
      outDir: 'dist',
      emptyOutDir: false,
    },
  };
});
