import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';

// Baseline handlers shared across the suite. Per-test files add their own
// using `server.use(...)` and reset via afterEach in setupTests.ts.
export const handlers = [
  http.get('/api/v1/auth/roles', () =>
    HttpResponse.json({ roles: [{ id: 'admin' }, { id: 'analyst' }] }),
  ),
  // Public config: default to non-demo so components that read it (e.g.
  // AutoSuggestDrawer) behave normally unless a test overrides it. The
  // `*/` prefix matches regardless of the per-test location origin.
  http.get('*/api/v1/admin/config/public', () =>
    HttpResponse.json({ demo_mode: false }),
  ),
];

export const server = setupServer(...handlers);
