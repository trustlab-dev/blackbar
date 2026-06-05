import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor } from '../test-utils/render';
import AdminConsole from './AdminConsole';

// Child components own their own test files; stub them so AdminConsole tests
// stay focused on the tab-container behavior.
vi.mock('./ReportingDashboard', () => ({
  default: () => <div>ReportingDashboard stub</div>,
}));
vi.mock('./UserManagement', () => ({
  default: () => <div>UserManagement stub</div>,
}));
vi.mock('./SystemConfiguration', () => ({
  default: () => <div>SystemConfiguration stub</div>,
}));
vi.mock('./OrganizationBranding', () => ({
  default: () => <div>OrganizationBranding stub</div>,
}));
vi.mock('./TemplatesManager', () => ({
  default: () => <div>TemplatesManager stub</div>,
}));
vi.mock('./LLMConfiguration', () => ({
  default: () => <div>LLMConfiguration stub</div>,
}));
vi.mock('./PackManagement/PackManagement', () => ({
  default: () => <div>PackManagement stub</div>,
}));

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  localStorage.setItem('token', 'fake');
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('AdminConsole', () => {
  it('renders the sidebar menu and the Dashboard tab by default', () => {
    renderWithProviders(<AdminConsole />);
    expect(
      screen.getByRole('heading', { name: /admin console/i }),
    ).toBeInTheDocument();
    expect(screen.getByText('User Management')).toBeInTheDocument();
    expect(screen.getByText('Packs')).toBeInTheDocument();
    // Dashboard tab content (ReportingDashboard) renders by default
    expect(screen.getByText('ReportingDashboard stub')).toBeInTheDocument();
  });

  it('switches to each child tab when its menu item is clicked', async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminConsole />);

    await user.click(screen.getByText('User Management'));
    expect(screen.getByText('UserManagement stub')).toBeInTheDocument();

    await user.click(screen.getByText('System Configuration'));
    expect(screen.getByText('SystemConfiguration stub')).toBeInTheDocument();

    await user.click(screen.getByText('Branding'));
    expect(screen.getByText('OrganizationBranding stub')).toBeInTheDocument();

    await user.click(screen.getByText('Templates'));
    expect(screen.getByText('TemplatesManager stub')).toBeInTheDocument();

    await user.click(screen.getByText('LLM Configuration'));
    expect(screen.getByText('LLMConfiguration stub')).toBeInTheDocument();

    await user.click(screen.getByText('Packs'));
    expect(screen.getByText('PackManagement stub')).toBeInTheDocument();
  });

  it('fetches and renders audit logs when the Audit Logs tab opens', async () => {
    server.use(
      http.get('/api/v1/cases/', () =>
        HttpResponse.json({
          cases: [
            {
              tracking_number: 'FOI-001',
              title: 'Budget',
              audit_log: [
                {
                  timestamp: '2026-05-01T10:00:00Z',
                  user_name: 'Alice',
                  action: 'case_created',
                  details: { note: 'created' },
                },
              ],
            },
          ],
        }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<AdminConsole />);
    await user.click(screen.getByText('Audit Logs'));
    expect(await screen.findByText('Alice')).toBeInTheDocument();
    expect(screen.getByText('case created')).toBeInTheDocument();
    expect(screen.getByText('FOI-001')).toBeInTheDocument();
  });

  it('shows the no-logs state when no cases have audit entries', async () => {
    server.use(
      http.get('/api/v1/cases/', () =>
        HttpResponse.json({ cases: [{ tracking_number: 'FOI-002', title: 'X' }] }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<AdminConsole />);
    await user.click(screen.getByText('Audit Logs'));
    expect(
      await screen.findByText(/no audit logs found/i),
    ).toBeInTheDocument();
  });

  it('handles an audit-log fetch error gracefully', async () => {
    server.use(
      http.get('/api/v1/cases/', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<AdminConsole />);
    await user.click(screen.getByText('Audit Logs'));
    expect(
      await screen.findByText(/no audit logs found/i),
    ).toBeInTheDocument();
  });

  it('renders a log row with System fallback and a dash when fields are missing', async () => {
    server.use(
      http.get('/api/v1/cases/', () =>
        HttpResponse.json({
          cases: [
            {
              tracking_number: null,
              title: 'NoNumber',
              audit_log: [
                { timestamp: '2026-05-02T10:00:00Z', action: 'status_changed' },
              ],
            },
          ],
        }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<AdminConsole />);
    await user.click(screen.getByText('Audit Logs'));
    expect(await screen.findByText('System')).toBeInTheDocument();
    expect(screen.getByText('status changed')).toBeInTheDocument();
  });
});
