import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../test-utils/msw-handlers';
import { renderWithProviders, screen } from '../test-utils/render';

// Smallest reproducible component import — pick something cheap
import OrganizationBranding from '../components/OrganizationBranding';

describe('frontend test infrastructure smoke', () => {
  it('Vitest + jsdom + RTL roundtrip works', async () => {
    // OrganizationBranding loads its config on mount. Mock it and wait for the
    // form so the request settles inside this test instead of reaching MSW
    // after the handlers are reset (an unhandled request).
    server.use(
      http.get('/api/v1/admin/config/', () => HttpResponse.json({})),
    );
    renderWithProviders(<OrganizationBranding />);
    // The infrastructure is the test subject: render, fetch via MSW, re-render.
    expect(
      await screen.findByLabelText(/organization name/i),
    ).toBeInTheDocument();
  });

  it('MSW intercepts /api/v1/auth/roles', async () => {
    const response = await fetch('/api/v1/auth/roles');
    const data = await response.json();
    expect(data.roles).toBeDefined();
    expect(data.roles.length).toBeGreaterThan(0);
  });
});
