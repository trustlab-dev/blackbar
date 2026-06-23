import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: '0.0.0.0', // for Docker
    // Vite rejects requests whose Host header isn't allow-listed. A
    // reverse-proxied deployment (or a container reaching this server by its
    // docker service name) must list those hosts here, otherwise the browser
    // gets "Blocked request. This host is not allowed." Set ALLOWED_HOSTS to a
    // comma-separated list of hostnames, or "all" to accept any host (used by
    // the demo, which is only reachable through its trusted reverse proxy).
    allowedHosts:
      process.env.ALLOWED_HOSTS === 'all'
        ? true
        : process.env.ALLOWED_HOSTS
          ? process.env.ALLOWED_HOSTS.split(',').map((h) => h.trim()).filter(Boolean)
          : ['localhost', '127.0.0.1'],
    proxy: {
      '/api': {
        target: 'http://backend:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'build', // match CRA's output dir so Dockerfile doesn't need changes
    sourcemap: true,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/setupTests.ts',
    css: true,
    // Vitest 4 defaults the pool to `forks`, which starts noticeably slower
    // than the `threads` pool this suite was tuned under. Combined with v8
    // coverage instrumentation that was enough to push a couple of
    // userEvent-driven dialog tests past the default 5s timeout. Restore the
    // thread pool and give coverage runs extra headroom.
    pool: 'threads',
    testTimeout: 15000,
    coverage: {
      reporter: ['text', 'html', 'lcov'],
      exclude: [
        'node_modules/',
        'src/setupTests.ts',
        'src/test-utils/**',
        'src/vite-env.d.ts',
        '**/*.d.ts',
        '**/*.config.{ts,js}',
        // Mount point — exercised only by the real browser bootstrap.
        'src/index.tsx',
        // Type-only module — no runtime statements to cover.
        'src/types/user.ts',
        // Barrel re-export files — no executable statements.
        '**/index.ts',
      ],
      // Phase 5 CI enforces these. Overall frontend coverage sits ~98%
      // line / 94% branch / 67.6% function — the function number is low
      // because v8 counts every inline arrow (including never-invoked
      // prop callbacks and test-file helpers) as a function. The gate is
      // set conservatively below current numbers so a future regression
      // that drops a whole module still fails the build.
      thresholds: {
        lines: 70,
        functions: 65,
        branches: 65,
        statements: 70,
      },
    },
  },
});
