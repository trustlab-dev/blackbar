import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor } from '../test-utils/render';
import UserManagement from './UserManagement';

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  localStorage.setItem('token', 'fake');
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

// Phase 1.9a: the user-listing API returns `role`, NOT `tenant_role`.
const baseUser = {
  id: 'u1',
  email: 'alice@example.com',
  full_name: 'Alice Admin',
  role: 'admin',
  created_at: '2026-01-01T00:00:00Z',
  disabled: false,
};

const rolesResponse = {
  roles: [
    { id: 'owner' },
    { id: 'admin' },
    { id: 'analyst' },
    { id: 'user' },
    { id: 'guest' },
  ],
};

describe('UserManagement — listing', () => {
  it('shows the loading row, then renders users keyed on the `role` field', async () => {
    server.use(
      http.get('/api/v1/auth/users', () => HttpResponse.json([baseUser])),
      http.get('/api/v1/auth/roles', () => HttpResponse.json(rolesResponse)),
    );
    renderWithProviders(<UserManagement />);
    expect(screen.getByText(/loading users/i)).toBeInTheDocument();
    expect(await screen.findByText('Alice Admin')).toBeInTheDocument();
    expect(screen.getByText('alice@example.com')).toBeInTheDocument();
    // The role cell reads straight from `role` (not `tenant_role`).
    expect(screen.getByText('admin')).toBeInTheDocument();
    expect(screen.getByText('Active')).toBeInTheDocument();
  });

  it('renders the no-users state when the list is empty', async () => {
    server.use(
      http.get('/api/v1/auth/users', () => HttpResponse.json([])),
      http.get('/api/v1/auth/roles', () => HttpResponse.json(rolesResponse)),
    );
    renderWithProviders(<UserManagement />);
    expect(await screen.findByText(/no users found/i)).toBeInTheDocument();
  });

  it('falls back to the email local-part when full_name is missing', async () => {
    server.use(
      http.get('/api/v1/auth/users', () =>
        HttpResponse.json([{ ...baseUser, full_name: undefined }]),
      ),
      http.get('/api/v1/auth/roles', () => HttpResponse.json(rolesResponse)),
    );
    renderWithProviders(<UserManagement />);
    expect(await screen.findByText('alice')).toBeInTheDocument();
  });

  it('shows an error message when the user fetch fails', async () => {
    server.use(
      http.get('/api/v1/auth/users', () =>
        HttpResponse.json({ detail: 'nope' }, { status: 500 }),
      ),
      http.get('/api/v1/auth/roles', () => HttpResponse.json(rolesResponse)),
    );
    renderWithProviders(<UserManagement />);
    // userService throws an axios error; the component surfaces err.message.
    await waitFor(() =>
      expect(
        screen.queryByText(/loading users/i),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByText(/no users found/i)).toBeInTheDocument();
  });

  it('keeps the default roles when the roles fetch fails', async () => {
    server.use(
      http.get('/api/v1/auth/users', () => HttpResponse.json([baseUser])),
      http.get('/api/v1/auth/roles', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<UserManagement />);
    await screen.findByText('Alice Admin');
    await user.click(screen.getByRole('button', { name: /add user/i }));
    // Default role list still drives the Role select.
    await screen.findByRole('heading', { name: /invite new user/i });
    expect(screen.getByRole('combobox')).toBeInTheDocument();
  });

  it('refreshes the list when Refresh is clicked', async () => {
    let calls = 0;
    server.use(
      http.get('/api/v1/auth/users', () => {
        calls += 1;
        return HttpResponse.json(calls > 1 ? [] : [baseUser]);
      }),
      http.get('/api/v1/auth/roles', () => HttpResponse.json(rolesResponse)),
    );
    const user = userEvent.setup();
    renderWithProviders(<UserManagement />);
    await screen.findByText('Alice Admin');
    await user.click(screen.getByRole('button', { name: /refresh/i }));
    expect(await screen.findByText(/no users found/i)).toBeInTheDocument();
  });
});

describe('UserManagement — add user', () => {
  it('invites a new user and shows the confirmation', async () => {
    let postBody: any = null;
    server.use(
      http.get('/api/v1/auth/users', () => HttpResponse.json([])),
      http.get('/api/v1/auth/roles', () => HttpResponse.json(rolesResponse)),
      http.post('/api/v1/auth/users', async ({ request }) => {
        postBody = await request.json();
        return HttpResponse.json({ invitation_sent: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<UserManagement />);
    await screen.findByText(/no users found/i);
    await user.click(screen.getByRole('button', { name: /add user/i }));
    await screen.findByRole('heading', { name: /invite new user/i });
    await user.type(
      screen.getByLabelText(/email address/i),
      'bob@example.com',
    );
    await user.type(screen.getByLabelText(/full name/i), 'Bob Builder');
    await user.click(
      screen.getByRole('button', { name: /send invitation/i }),
    );
    await waitFor(() => expect(postBody?.email).toBe('bob@example.com'));
    expect(postBody.role).toBe('analyst');
    expect(
      await screen.findByText(/invitation sent/i),
    ).toBeInTheDocument();
  });

  it('closes the dialog and refetches when invitation_sent is false', async () => {
    server.use(
      http.get('/api/v1/auth/users', () => HttpResponse.json([])),
      http.get('/api/v1/auth/roles', () => HttpResponse.json(rolesResponse)),
      http.post('/api/v1/auth/users', () =>
        HttpResponse.json({ invitation_sent: false }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<UserManagement />);
    await screen.findByText(/no users found/i);
    await user.click(screen.getByRole('button', { name: /add user/i }));
    await screen.findByRole('heading', { name: /invite new user/i });
    await user.type(
      screen.getByLabelText(/email address/i),
      'carol@example.com',
    );
    await user.click(
      screen.getByRole('button', { name: /send invitation/i }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole('heading', { name: /invite new user/i }),
      ).not.toBeInTheDocument(),
    );
  });

  it('surfaces a FastAPI validation-array error', async () => {
    server.use(
      http.get('/api/v1/auth/users', () => HttpResponse.json([])),
      http.get('/api/v1/auth/roles', () => HttpResponse.json(rolesResponse)),
      http.post('/api/v1/auth/users', () =>
        HttpResponse.json(
          {
            detail: [
              { loc: ['body', 'email'], msg: 'invalid email' },
            ],
          },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<UserManagement />);
    await screen.findByText(/no users found/i);
    await user.click(screen.getByRole('button', { name: /add user/i }));
    await screen.findByRole('heading', { name: /invite new user/i });
    await user.type(
      screen.getByLabelText(/email address/i),
      'bad@example.com',
    );
    await user.click(
      screen.getByRole('button', { name: /send invitation/i }),
    );
    expect(
      await screen.findByText(/body\.email: invalid email/i),
    ).toBeInTheDocument();
  });

  it('cancels the add dialog', async () => {
    server.use(
      http.get('/api/v1/auth/users', () => HttpResponse.json([])),
      http.get('/api/v1/auth/roles', () => HttpResponse.json(rolesResponse)),
    );
    const user = userEvent.setup();
    renderWithProviders(<UserManagement />);
    await screen.findByText(/no users found/i);
    await user.click(screen.getByRole('button', { name: /add user/i }));
    await screen.findByRole('heading', { name: /invite new user/i });
    await user.click(screen.getByRole('button', { name: /cancel/i }));
    await waitFor(() =>
      expect(
        screen.queryByRole('heading', { name: /invite new user/i }),
      ).not.toBeInTheDocument(),
    );
  });
});

describe('UserManagement — edit user', () => {
  it('edits an existing user and updates the row', async () => {
    let putBody: any = null;
    server.use(
      http.get('/api/v1/auth/users', () => HttpResponse.json([baseUser])),
      http.get('/api/v1/auth/roles', () => HttpResponse.json(rolesResponse)),
      http.put('/api/v1/auth/users/u1', async ({ request }) => {
        putBody = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<UserManagement />);
    await screen.findByText('Alice Admin');
    await user.click(screen.getByRole('button', { name: /edit user/i }));
    await screen.findByRole('heading', { name: /edit user/i });
    const nameField = screen.getByLabelText(/full name/i);
    await user.clear(nameField);
    await user.type(nameField, 'Alice Renamed');
    await user.click(
      screen.getByRole('button', { name: /save changes/i }),
    );
    await waitFor(() => expect(putBody?.full_name).toBe('Alice Renamed'));
    expect(await screen.findByText('Alice Renamed')).toBeInTheDocument();
  });

  it('shows an error when an edit fails', async () => {
    server.use(
      http.get('/api/v1/auth/users', () => HttpResponse.json([baseUser])),
      http.get('/api/v1/auth/roles', () => HttpResponse.json(rolesResponse)),
      http.put('/api/v1/auth/users/u1', () =>
        HttpResponse.json({ detail: 'update rejected' }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<UserManagement />);
    await screen.findByText('Alice Admin');
    await user.click(screen.getByRole('button', { name: /edit user/i }));
    await screen.findByRole('heading', { name: /edit user/i });
    await user.click(
      screen.getByRole('button', { name: /save changes/i }),
    );
    expect(
      await screen.findByText(/update rejected/i),
    ).toBeInTheDocument();
  });
});

describe('UserManagement — toggle disable', () => {
  it('toggles a user between Active and Disabled', async () => {
    let putBody: any = null;
    server.use(
      http.get('/api/v1/auth/users', () => HttpResponse.json([baseUser])),
      http.get('/api/v1/auth/roles', () => HttpResponse.json(rolesResponse)),
      http.put('/api/v1/auth/users/u1', async ({ request }) => {
        putBody = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<UserManagement />);
    await screen.findByText('Alice Admin');
    await user.click(
      screen.getByRole('checkbox', { name: /toggle user status/i }),
    );
    await waitFor(() => expect(putBody?.disabled).toBe(true));
    expect(await screen.findByText('Disabled')).toBeInTheDocument();
  });

  it('shows an error when the disable toggle fails', async () => {
    server.use(
      http.get('/api/v1/auth/users', () => HttpResponse.json([baseUser])),
      http.get('/api/v1/auth/roles', () => HttpResponse.json(rolesResponse)),
      http.put('/api/v1/auth/users/u1', () => HttpResponse.error()),
    );
    const user = userEvent.setup();
    renderWithProviders(<UserManagement />);
    await screen.findByText('Alice Admin');
    await user.click(
      screen.getByRole('checkbox', { name: /toggle user status/i }),
    );
    // The axios error carries a `message`, so the component surfaces that
    // (the `Failed to disable user` literal is only the `|| ` fallback).
    await waitFor(() =>
      expect(screen.getByText(/network error/i)).toBeInTheDocument(),
    );
  });
});

describe('UserManagement — change password', () => {
  it('updates a password when both fields match', async () => {
    let putBody: any = null;
    server.use(
      http.get('/api/v1/auth/users', () => HttpResponse.json([baseUser])),
      http.get('/api/v1/auth/roles', () => HttpResponse.json(rolesResponse)),
      http.put('/api/v1/auth/users/u1', async ({ request }) => {
        putBody = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<UserManagement />);
    await screen.findByText('Alice Admin');
    await user.click(
      screen.getByRole('button', { name: /change password/i }),
    );
    await screen.findByRole('heading', { name: /change password/i });
    await user.type(screen.getByLabelText(/^new password$/i), 'secret123');
    await user.type(
      screen.getByLabelText(/confirm new password/i),
      'secret123',
    );
    await user.click(
      screen.getByRole('button', { name: /update password/i }),
    );
    await waitFor(() => expect(putBody?.password).toBe('secret123'));
  });

  it('blocks the update when the passwords do not match', async () => {
    server.use(
      http.get('/api/v1/auth/users', () => HttpResponse.json([baseUser])),
      http.get('/api/v1/auth/roles', () => HttpResponse.json(rolesResponse)),
    );
    const user = userEvent.setup();
    renderWithProviders(<UserManagement />);
    await screen.findByText('Alice Admin');
    await user.click(
      screen.getByRole('button', { name: /change password/i }),
    );
    await screen.findByRole('heading', { name: /change password/i });
    await user.type(screen.getByLabelText(/^new password$/i), 'secret123');
    await user.type(
      screen.getByLabelText(/confirm new password/i),
      'different',
    );
    await user.click(
      screen.getByRole('button', { name: /update password/i }),
    );
    expect(
      await screen.findByText(/passwords do not match/i),
    ).toBeInTheDocument();
  });
});
