import { describe, it, expect } from 'vitest';
import { AxiosError, AxiosHeaders } from 'axios';
import {
  getApiErrorMessage,
  withParsedBlobErrorBody,
  DEFAULT_ERROR_MESSAGE,
  PUBLIC_TOKEN_FORBIDDEN_MESSAGE,
} from './errors';

function axiosError(status: number, data: unknown): AxiosError {
  const config = { headers: new AxiosHeaders() };
  return new AxiosError('Request failed', 'ERR_BAD_RESPONSE', config, null, {
    status,
    statusText: '',
    headers: {},
    config,
    data,
  });
}

describe('getApiErrorMessage', () => {
  it('reads the standard backend envelope {error: {message}}', () => {
    const err = axiosError(404, {
      error: { code: 'HTTP_404', message: 'Case not found', details: {}, correlation_id: 'x' },
    });
    expect(getApiErrorMessage(err, 'fallback')).toBe('Case not found');
  });

  it('reads a {error: code, message} body (e.g. magic-link invalid_token)', () => {
    const err = axiosError(400, {
      error: 'invalid_token',
      message: 'Magic link is invalid or has expired.',
    });
    expect(getApiErrorMessage(err, 'fallback')).toBe('Magic link is invalid or has expired.');
  });

  it('reads a legacy FastAPI {detail: string} body', () => {
    expect(getApiErrorMessage(axiosError(400, { detail: 'Bad thing' }), 'fb')).toBe('Bad thing');
  });

  it('reads the first message of a FastAPI validation {detail: [...]} array', () => {
    const err = axiosError(422, { detail: [{ loc: ['body', 'email'], msg: 'field required' }] });
    expect(getApiErrorMessage(err, 'fb')).toBe('email: field required');
    const noLoc = axiosError(422, { detail: [{ msg: 'field required' }] });
    expect(getApiErrorMessage(noLoc, 'fb')).toBe('field required');
  });

  it('adds the first validation error to the envelope message', () => {
    const err = axiosError(422, {
      error: {
        code: 'VALIDATION_ERROR',
        message: 'Invalid request data',
        details: { errors: [{ loc: ['body', 'password'], msg: 'String too short' }] },
      },
    });
    expect(getApiErrorMessage(err, 'fb')).toBe(
      'Invalid request data: password: String too short',
    );
  });

  it('drops the Pydantic "Value error, " prefix from custom validator messages', () => {
    // Shape of the backend 422 for a short password (auth/security.py
    // password_policy_error via a field_validator).
    const err = axiosError(422, {
      error: {
        code: 'VALIDATION_ERROR',
        message: 'Invalid request data',
        details: {
          errors: [
            {
              loc: ['body', 'password'],
              msg: 'Value error, Password must be at least 12 characters',
            },
          ],
        },
      },
    });
    expect(getApiErrorMessage(err, 'fb')).toBe(
      'Invalid request data: password: Password must be at least 12 characters',
    );
  });

  it('explains PUBLIC_TOKEN_FORBIDDEN in requester terms', () => {
    const err = axiosError(403, {
      error: {
        code: 'PUBLIC_TOKEN_FORBIDDEN',
        message: 'Public accounts cannot access this endpoint',
        correlation_id: 'x',
      },
    });
    expect(getApiErrorMessage(err, 'fb')).toBe(PUBLIC_TOKEN_FORBIDDEN_MESSAGE);
  });

  it('never returns a non-string (objects would crash React rendering)', () => {
    expect(getApiErrorMessage(axiosError(400, { detail: { nested: true } }), 'fb')).toBe('fb');
    expect(getApiErrorMessage(axiosError(400, { error: { message: 42 } }), 'fb')).toBe('fb');
    expect(getApiErrorMessage(axiosError(400, { detail: [] }), 'fb')).toBe('fb');
  });

  it('uses the fallback for 5xx responses so internal messages stay generic', () => {
    const err = axiosError(500, { error: { message: 'Internal server error' } });
    expect(getApiErrorMessage(err, 'Failed to save')).toBe('Failed to save');
  });

  it('uses the fallback for non-JSON bodies (e.g. blob downloads)', () => {
    expect(getApiErrorMessage(axiosError(400, new Blob(['x'])), 'fb')).toBe('fb');
    expect(getApiErrorMessage(axiosError(400, 'plain text'), 'fb')).toBe('fb');
    expect(getApiErrorMessage(axiosError(400, null), 'fb')).toBe('fb');
  });

  it('reports timeouts explicitly', () => {
    const err = new AxiosError('timeout of 30000ms exceeded', 'ECONNABORTED');
    expect(getApiErrorMessage(err, 'fb')).toMatch(/timed out/i);
  });

  it('uses the fallback for network errors and non-axios values', () => {
    expect(getApiErrorMessage(new AxiosError('Network Error', 'ERR_NETWORK'), 'fb')).toBe('fb');
    expect(getApiErrorMessage(new Error('boom'), 'fb')).toBe('fb');
    expect(getApiErrorMessage(undefined, 'fb')).toBe('fb');
    expect(getApiErrorMessage('oops')).toBe(DEFAULT_ERROR_MESSAGE);
  });
});

describe('getApiErrorMessage — dict detail', () => {
  it('reads {detail: {message}} (HTTPException raised with a dict detail)', () => {
    const err = axiosError(409, {
      detail: { message: 'Documents that failed conversion cannot be approved.', document_ids: ['d1'] },
    });
    expect(getApiErrorMessage(err, 'fb')).toBe('Documents that failed conversion cannot be approved.');
  });
});

describe('withParsedBlobErrorBody', () => {
  it('parses a JSON error body returned for a blob request so the message is readable', async () => {
    const body = new Blob(
      [JSON.stringify({ error: { code: 'HTTP_409', message: '2 redaction(s) are awaiting review' } })],
      { type: 'application/json' },
    );
    const err = await withParsedBlobErrorBody(axiosError(409, body));
    expect(getApiErrorMessage(err, 'fb')).toBe('2 redaction(s) are awaiting review');
  });

  it('leaves non-JSON blobs and non-axios values alone', async () => {
    const raw = axiosError(409, new Blob(['%PDF'], { type: 'application/pdf' }));
    expect(getApiErrorMessage(await withParsedBlobErrorBody(raw), 'fb')).toBe('fb');
    const bad = axiosError(409, new Blob(['not json'], { type: 'application/json' }));
    expect(getApiErrorMessage(await withParsedBlobErrorBody(bad), 'fb')).toBe('fb');
    expect(await withParsedBlobErrorBody(undefined)).toBeUndefined();
  });
});
