import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../test-utils/msw-handlers';
import * as userService from './userService';

// ---------------------------------------------------------------------------
// getUsers
// ---------------------------------------------------------------------------
describe('userService.getUsers', () => {
  it('returns the list of users on 200', async () => {
    server.use(
      http.get('/api/v1/auth/users', () =>
        HttpResponse.json([
          { id: 'u-1', email: 'a@example.com', role: 'admin' },
          { id: 'u-2', email: 'b@example.com', role: 'analyst' },
        ]),
      ),
    );
    const users = await userService.getUsers();
    expect(users).toHaveLength(2);
    expect(users[0].email).toBe('a@example.com');
  });

  it('throws on 500', async () => {
    server.use(
      http.get(
        '/api/v1/auth/users',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    await expect(userService.getUsers()).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// getUserById
// ---------------------------------------------------------------------------
describe('userService.getUserById', () => {
  it('returns a single user on 200', async () => {
    server.use(
      http.get('/api/v1/auth/users/u-1', () =>
        HttpResponse.json({
          id: 'u-1',
          email: 'a@example.com',
          role: 'admin',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-02T00:00:00Z',
        }),
      ),
    );
    const user = await userService.getUserById('u-1');
    expect(user.id).toBe('u-1');
    expect(user.email).toBe('a@example.com');
    expect(user.role).toBe('admin');
  });

  it('throws on 404', async () => {
    server.use(
      http.get(
        '/api/v1/auth/users/missing',
        () => new HttpResponse(null, { status: 404 }),
      ),
    );
    await expect(userService.getUserById('missing')).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// createUser
// ---------------------------------------------------------------------------
describe('userService.createUser', () => {
  it('POSTs the payload and returns the created user', async () => {
    let receivedBody: any = null;
    server.use(
      http.post('/api/v1/auth/users', async ({ request }) => {
        receivedBody = await request.json();
        return HttpResponse.json({ id: 'u-new', email: 'new@example.com' });
      }),
    );
    const result = await userService.createUser({
      email: 'new@example.com',
      password: 'secret',
      role: 'analyst',
    });
    expect(receivedBody).toEqual({
      email: 'new@example.com',
      password: 'secret',
      role: 'analyst',
    });
    expect(result.id).toBe('u-new');
  });

  it('throws on 422', async () => {
    server.use(
      http.post(
        '/api/v1/auth/users',
        () => new HttpResponse(null, { status: 422 }),
      ),
    );
    await expect(
      userService.createUser({ email: 'bad' }),
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// updateUser
// ---------------------------------------------------------------------------
describe('userService.updateUser', () => {
  it('PUTs the payload and returns the updated user', async () => {
    let receivedBody: any = null;
    server.use(
      http.put('/api/v1/auth/users/u-1', async ({ request }) => {
        receivedBody = await request.json();
        return HttpResponse.json({ id: 'u-1', role: 'admin' });
      }),
    );
    const result = await userService.updateUser('u-1', { role: 'admin' });
    expect(receivedBody).toEqual({ role: 'admin' });
    expect(result.role).toBe('admin');
  });

  it('throws on 500', async () => {
    server.use(
      http.put(
        '/api/v1/auth/users/u-1',
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    await expect(
      userService.updateUser('u-1', { role: 'admin' }),
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// deleteUser
// ---------------------------------------------------------------------------
describe('userService.deleteUser', () => {
  it('DELETEs the user and returns the response data', async () => {
    server.use(
      http.delete('/api/v1/auth/users/u-1', () =>
        HttpResponse.json({ deleted: 'u-1' }),
      ),
    );
    const result = await userService.deleteUser('u-1');
    expect(result).toEqual({ deleted: 'u-1' });
  });

  it('throws on 404', async () => {
    server.use(
      http.delete(
        '/api/v1/auth/users/u-1',
        () => new HttpResponse(null, { status: 404 }),
      ),
    );
    await expect(userService.deleteUser('u-1')).rejects.toThrow();
  });
});
