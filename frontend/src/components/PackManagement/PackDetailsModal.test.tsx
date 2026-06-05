import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor, within } from '../../test-utils/render';
import PackDetailsModal from './PackDetailsModal';

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  localStorage.setItem('token', 'fake');
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

const pack = {
  pack_id: 'ca-bc-fippa',
  name: 'BC FIPPA',
  version: '1.2.0',
  description: 'BC pack',
  jurisdiction: {
    country: 'CA',
    region: 'British Columbia',
    legislation_short: 'FIPPA',
  },
};

const details = {
  pack_id: 'ca-bc-fippa',
  name: 'BC FIPPA',
  version: '1.2.0',
  jurisdiction: {
    country_name: 'Canada',
    region_name: 'British Columbia',
    legislation: 'Freedom of Information and Protection of Privacy Act',
    legislation_url: 'https://example.gov/fippa',
  },
  terminology: {
    request_type: 'FOI Request',
    requester: 'Applicant',
    tracking_number_prefix: 'FOI',
  },
  timelines: {
    default_response_days: 30,
    extension_max_days: 30,
    business_days: true,
    extension_reasons: ['Third party consultation'],
  },
  categories: [
    {
      code: 's13',
      name: 'Policy Advice',
      color: '#ff0000',
      description: 'Advice or recommendations',
      guidance: 'Use sparingly',
    },
  ],
  statuses: [
    { label: 'Open', color: '#00ff00', description: 'Case is open' },
  ],
  priorities: [{ label: 'High' }],
  templates: ['acknowledgment_letter'],
  features: { ai_suggestions: true, public_portal: false },
  branding: {},
};

describe('PackDetailsModal', () => {
  it('renders nothing when pack is null', () => {
    const { container } = renderWithProviders(
      <PackDetailsModal pack={null} open onClose={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the loading spinner while fetching details', async () => {
    server.use(
      http.get('/api/v1/packs/ca-bc-fippa/preview', async () => {
        await new Promise((r) => setTimeout(r, 50));
        return HttpResponse.json(details);
      }),
    );
    renderWithProviders(<PackDetailsModal pack={pack} open onClose={vi.fn()} />);
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });

  it('renders the Overview tab with jurisdiction, terminology and capabilities', async () => {
    server.use(
      http.get('/api/v1/packs/ca-bc-fippa/preview', () =>
        HttpResponse.json(details),
      ),
    );
    renderWithProviders(<PackDetailsModal pack={pack} open onClose={vi.fn()} />);
    expect(await screen.findByText('Canada')).toBeInTheDocument();
    expect(
      screen.getByText(/Freedom of Information and Protection of Privacy Act/),
    ).toBeInTheDocument();
    expect(screen.getByText('FOI Request')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /view legislation/i })).toHaveAttribute(
      'href',
      'https://example.gov/fippa',
    );
    expect(screen.getByText('1 Redaction Categories')).toBeInTheDocument();
  });

  it('switches to the Categories tab', async () => {
    server.use(
      http.get('/api/v1/packs/ca-bc-fippa/preview', () =>
        HttpResponse.json(details),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PackDetailsModal pack={pack} open onClose={vi.fn()} />);
    await screen.findByText('Canada');
    await user.click(screen.getByRole('tab', { name: /categories/i }));
    expect(screen.getByText('Policy Advice')).toBeInTheDocument();
    expect(screen.getByText(/Advice or recommendations/)).toBeInTheDocument();
    expect(screen.getByText(/Use sparingly/)).toBeInTheDocument();
  });

  it('switches to the Statuses tab', async () => {
    server.use(
      http.get('/api/v1/packs/ca-bc-fippa/preview', () =>
        HttpResponse.json(details),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PackDetailsModal pack={pack} open onClose={vi.fn()} />);
    await screen.findByText('Canada');
    await user.click(screen.getByRole('tab', { name: /statuses/i }));
    expect(screen.getByText('Open')).toBeInTheDocument();
    expect(screen.getByText('Case is open')).toBeInTheDocument();
  });

  it('switches to the Timelines tab', async () => {
    server.use(
      http.get('/api/v1/packs/ca-bc-fippa/preview', () =>
        HttpResponse.json(details),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PackDetailsModal pack={pack} open onClose={vi.fn()} />);
    await screen.findByText('Canada');
    await user.click(screen.getByRole('tab', { name: /timelines/i }));
    expect(screen.getByText(/Default Response Time:/)).toBeInTheDocument();
    expect(screen.getByText('Third party consultation')).toBeInTheDocument();
  });

  it('switches to the Features tab', async () => {
    server.use(
      http.get('/api/v1/packs/ca-bc-fippa/preview', () =>
        HttpResponse.json(details),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<PackDetailsModal pack={pack} open onClose={vi.fn()} />);
    await screen.findByText('Canada');
    await user.click(screen.getByRole('tab', { name: /features/i }));
    expect(screen.getByText('AI SUGGESTIONS')).toBeInTheDocument();
    expect(screen.getByText('ACKNOWLEDGMENT LETTER')).toBeInTheDocument();
  });

  it('shows the no-details state when the fetch fails', async () => {
    server.use(
      http.get('/api/v1/packs/ca-bc-fippa/preview', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    renderWithProviders(<PackDetailsModal pack={pack} open onClose={vi.fn()} />);
    expect(
      await screen.findByText(/no details available/i),
    ).toBeInTheDocument();
  });

  it('calls onClose from the Close button', async () => {
    server.use(
      http.get('/api/v1/packs/ca-bc-fippa/preview', () =>
        HttpResponse.json(details),
      ),
    );
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<PackDetailsModal pack={pack} open onClose={onClose} />);
    await screen.findByText('Canada');
    await user.click(screen.getByRole('button', { name: /^close$/i }));
    expect(onClose).toHaveBeenCalled();
  });
});
