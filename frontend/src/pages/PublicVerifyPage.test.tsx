import { describe, it, expect, vi, afterEach } from 'vitest';
import { renderWithProviders, screen } from '../test-utils/render';
import { PublicVerifyPage } from './PublicVerifyPage';

// MagicLinkVerify owns the token-verification flow — stub it so this test
// exercises only PublicVerifyPage's layout shell.
vi.mock('../components/auth/MagicLinkVerify', () => ({
  MagicLinkVerify: () => (
    <div data-testid="magic-link-verify">magic-link-verify</div>
  ),
}));

afterEach(() => {
  vi.restoreAllMocks();
});

describe('PublicVerifyPage', () => {
  it('renders the MagicLinkVerify component inside its layout shell', () => {
    renderWithProviders(<PublicVerifyPage />, {
      route: '/public/verify/abc',
    });
    expect(screen.getByTestId('magic-link-verify')).toBeInTheDocument();
  });
});
