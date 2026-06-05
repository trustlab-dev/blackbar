import { describe, it, expect } from 'vitest';
import { renderWithProviders } from '../test-utils/render';

// Smallest reproducible component import — pick something cheap
import OrganizationBranding from '../components/OrganizationBranding';

describe('frontend test infrastructure smoke', () => {
  it('Vitest + jsdom + RTL roundtrip works', () => {
    renderWithProviders(<OrganizationBranding />);
    // Don't assert anything specific — just that render() didn't throw.
    // The infrastructure is the test subject.
    expect(true).toBe(true);
  });

  it('MSW intercepts /api/v1/auth/roles', async () => {
    const response = await fetch('/api/v1/auth/roles');
    const data = await response.json();
    expect(data.roles).toBeDefined();
    expect(data.roles.length).toBeGreaterThan(0);
  });
});
