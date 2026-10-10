import { describe, it, expect } from 'vitest';
import {
  MIN_PASSWORD_LENGTH,
  MAX_PASSWORD_BYTES,
  passwordByteLength,
  passwordPolicyError,
} from './passwordPolicy';

describe('passwordPolicy (mirrors backend auth/security.py)', () => {
  it('matches the backend limits', () => {
    expect(MIN_PASSWORD_LENGTH).toBe(12);
    expect(MAX_PASSWORD_BYTES).toBe(72);
  });

  it('refuses fewer than 12 characters', () => {
    expect(passwordPolicyError('elevenchars')).toMatch(/at least 12 characters/);
    expect(passwordPolicyError('twelve-chars')).toBeNull();
  });

  it('counts characters by code point like Python len()', () => {
    // 11 ASCII + 1 emoji = 12 code points (but 13 UTF-16 units).
    expect(passwordPolicyError('abcdefghijk\u{1F600}')).toBeNull();
    expect(passwordPolicyError('abcdefghij\u{1F600}')).toMatch(/at least 12/);
  });

  it('refuses more than 72 UTF-8 bytes, not 72 characters', () => {
    expect(passwordPolicyError('a'.repeat(72))).toBeNull();
    expect(passwordPolicyError('a'.repeat(73))).toMatch(/at most 72 bytes/);
    // 37 x "é" is 37 characters but 74 bytes.
    const accented = 'é'.repeat(37);
    expect(passwordByteLength(accented)).toBe(74);
    expect(passwordPolicyError(accented)).toMatch(/at most 72 bytes/);
  });
});
