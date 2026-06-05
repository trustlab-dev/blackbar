import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor, within } from '../../test-utils/render';
import PackManagement from './PackManagement';

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  localStorage.setItem('token', 'fake');
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

const caPack = {
  pack_id: 'ca-bc-fippa',
  name: 'BC FIPPA',
  version: '1.0.0',
  description: 'BC pack',
  jurisdiction: { country: 'CA', region: 'BC', legislation_short: 'FIPPA' },
  author: 'Team',
  category_count: 5,
  status_count: 3,
  has_templates: true,
  has_ai_prompts: false,
  is_active: true,
};

const usPack = {
  pack_id: 'us-fed-foia',
  name: 'US FOIA',
  version: '2.0.0',
  description: 'US federal pack',
  jurisdiction: { country: 'US', region: 'Federal', legislation_short: 'FOIA' },
  author: 'Team',
  category_count: 9,
  status_count: 4,
  has_templates: false,
  has_ai_prompts: true,
  is_active: false,
};

const otherPack = {
  ...usPack,
  pack_id: 'gb-foia',
  name: 'UK FOIA',
  jurisdiction: { country: 'GB', region: 'UK', legislation_short: 'FOIA' },
};

describe('PackManagement', () => {
  it('shows the spinner, then renders packs and the active-pack alert', async () => {
    server.use(
      http.get('/api/v1/packs/', () =>
        HttpResponse.json({ packs: [caPack, usPack] }),
      ),
    );
    renderWithProviders(<PackManagement />);
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
    expect(await screen.findByText('BC FIPPA')).toBeInTheDocument();
    expect(screen.getByText('US FOIA')).toBeInTheDocument();
    expect(screen.getByText(/Active Pack:/)).toBeInTheDocument();
  });

  it('renders the empty state when there are no packs', async () => {
    server.use(
      http.get('/api/v1/packs/', () => HttpResponse.json({ packs: [] })),
    );
    renderWithProviders(<PackManagement />);
    expect(
      await screen.findByText(/no packs available/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /upload your first pack/i }),
    ).toBeInTheDocument();
  });

  it('shows an error alert when the fetch fails', async () => {
    server.use(
      http.get('/api/v1/packs/', () =>
        HttpResponse.json({ detail: 'fetch boom' }, { status: 500 }),
      ),
    );
    renderWithProviders(<PackManagement />);
    expect(await screen.findByText('fetch boom')).toBeInTheDocument();
  });

  it('filters packs by country across the Canada / US tabs', async () => {
    server.use(
      http.get('/api/v1/packs/', () =>
        HttpResponse.json({ packs: [caPack, usPack] }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PackManagement />);
    await screen.findByText('BC FIPPA');
    await user.click(screen.getByRole('tab', { name: /canada/i }));
    expect(screen.getByText('BC FIPPA')).toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: /united states/i }));
    expect(screen.getByText('US FOIA')).toBeInTheDocument();
  });

  it('renders the Other tab only when non-CA/US packs exist', async () => {
    server.use(
      http.get('/api/v1/packs/', () =>
        HttpResponse.json({ packs: [caPack, otherPack] }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PackManagement />);
    await screen.findByText('BC FIPPA');
    await user.click(screen.getByRole('tab', { name: /other/i }));
    expect(screen.getByText('UK FOIA')).toBeInTheDocument();
  });

  it('shows the empty-tab messages for Canada / US when none match', async () => {
    server.use(
      http.get('/api/v1/packs/', () =>
        HttpResponse.json({ packs: [otherPack] }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PackManagement />);
    await screen.findByText('UK FOIA');
    await user.click(screen.getByRole('tab', { name: /canada/i }));
    expect(
      screen.getByText(/no canadian packs available/i),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: /united states/i }));
    expect(screen.getByText(/no us packs available/i)).toBeInTheDocument();
  });

  it('activates a pack and shows the success alert', async () => {
    let activated = false;
    server.use(
      http.get('/api/v1/packs/', () =>
        HttpResponse.json({
          packs: [
            { ...usPack, is_active: activated },
            { ...caPack, is_active: !activated },
          ],
        }),
      ),
      http.post('/api/v1/packs/activate', () => {
        activated = true;
        return HttpResponse.json({ success: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<PackManagement />);
    await screen.findByText('US FOIA');
    await user.click(screen.getByRole('button', { name: /^activate$/i }));
    expect(
      await screen.findByText(/pack activated successfully/i),
    ).toBeInTheDocument();
  });

  it('shows an error when activation fails', async () => {
    server.use(
      http.get('/api/v1/packs/', () =>
        HttpResponse.json({ packs: [usPack] }),
      ),
      http.post('/api/v1/packs/activate', () =>
        HttpResponse.json({ detail: 'activate boom' }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PackManagement />);
    await screen.findByText('US FOIA');
    await user.click(screen.getByRole('button', { name: /^activate$/i }));
    expect(await screen.findByText('activate boom')).toBeInTheDocument();
  });

  it('reloads packs when Reload is clicked', async () => {
    let reloaded = false;
    server.use(
      http.get('/api/v1/packs/', () =>
        HttpResponse.json({ packs: reloaded ? [caPack, usPack] : [caPack] }),
      ),
      http.post('/api/v1/packs/reload', () => {
        reloaded = true;
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<PackManagement />);
    await screen.findByText('BC FIPPA');
    await user.click(screen.getByRole('button', { name: /reload/i }));
    expect(await screen.findByText('US FOIA')).toBeInTheDocument();
    expect(
      screen.getByText(/packs reloaded successfully/i),
    ).toBeInTheDocument();
  });

  it('shows an error when reload fails', async () => {
    server.use(
      http.get('/api/v1/packs/', () =>
        HttpResponse.json({ packs: [caPack] }),
      ),
      http.post('/api/v1/packs/reload', () =>
        HttpResponse.json({ detail: 'reload boom' }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PackManagement />);
    await screen.findByText('BC FIPPA');
    await user.click(screen.getByRole('button', { name: /reload/i }));
    expect(await screen.findByText('reload boom')).toBeInTheDocument();
  });

  it('opens the pack details modal from a card', async () => {
    server.use(
      http.get('/api/v1/packs/', () =>
        HttpResponse.json({ packs: [caPack] }),
      ),
      http.get('/api/v1/packs/ca-bc-fippa/preview', () =>
        HttpResponse.json({
          pack_id: 'ca-bc-fippa',
          name: 'BC FIPPA',
          version: '1.0.0',
          jurisdiction: { country_name: 'Canada', region_name: 'BC' },
          terminology: {},
          timelines: {},
          categories: [],
          statuses: [],
          priorities: [],
          templates: [],
          features: {},
          branding: {},
        }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PackManagement />);
    await screen.findByText('BC FIPPA');
    await user.click(screen.getByRole('button', { name: /details/i }));
    expect(await screen.findByText('Canada')).toBeInTheDocument();
  });

  it('opens the uploader dialog from the Upload Pack button', async () => {
    server.use(
      http.get('/api/v1/packs/', () =>
        HttpResponse.json({ packs: [caPack] }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PackManagement />);
    await screen.findByText('BC FIPPA');
    await user.click(screen.getByRole('button', { name: /upload pack/i }));
    expect(
      await screen.findByText(/upload jurisdiction pack/i),
    ).toBeInTheDocument();
  });

  it('opens the uploader from the empty-state button', async () => {
    server.use(
      http.get('/api/v1/packs/', () => HttpResponse.json({ packs: [] })),
    );
    const user = userEvent.setup();
    renderWithProviders(<PackManagement />);
    await screen.findByText(/no packs available/i);
    await user.click(
      screen.getByRole('button', { name: /upload your first pack/i }),
    );
    expect(
      await screen.findByText(/upload jurisdiction pack/i),
    ).toBeInTheDocument();
  });
});
