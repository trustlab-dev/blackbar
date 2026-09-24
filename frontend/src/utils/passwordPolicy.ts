/**
 * Client-side mirror of the backend password policy
 * (backend/src/auth/security.py `password_policy_error`, AUTH-25/27): at least
 * 12 characters, at most 72 bytes when UTF-8 encoded (bcrypt's input limit).
 * The backend is authoritative and answers 422 on create, update and
 * activation; this only saves a round trip and keeps the hint text in sync.
 */
export const MIN_PASSWORD_LENGTH = 12;
export const MAX_PASSWORD_BYTES = 72;

export const PASSWORD_REQUIREMENTS_TEXT = `At least ${MIN_PASSWORD_LENGTH} characters (at most ${MAX_PASSWORD_BYTES} bytes)`;

export function passwordByteLength(password: string): number {
  return new TextEncoder().encode(password).length;
}

/** Why `password` would be refused as a new password, or null if it is fine. */
export function passwordPolicyError(password: string): string | null {
  // Count code points, as Python's len() does, so an emoji counts once.
  if ([...password].length < MIN_PASSWORD_LENGTH) {
    return `Password must be at least ${MIN_PASSWORD_LENGTH} characters`;
  }
  if (passwordByteLength(password) > MAX_PASSWORD_BYTES) {
    return `Password must be at most ${MAX_PASSWORD_BYTES} bytes (fewer characters if it uses accents, symbols or emoji)`;
  }
  return null;
}
