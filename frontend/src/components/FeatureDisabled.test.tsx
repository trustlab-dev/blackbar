import { describe, it, expect } from 'vitest';
import { renderWithProviders, screen } from '../test-utils/render';
import FeatureDisabled from './FeatureDisabled';

describe('FeatureDisabled', () => {
  it('renders the feature name in the body copy', () => {
    renderWithProviders(<FeatureDisabled featureName="Public Portal" />);
    expect(
      screen.getByText(/public portal has been disabled by the administrator/i),
    ).toBeInTheDocument();
  });

  it('renders the static heading and login link', () => {
    renderWithProviders(<FeatureDisabled featureName="Anything" />);
    expect(
      screen.getByRole('heading', { name: /feature not available/i }),
    ).toBeInTheDocument();
    const loginLink = screen.getByRole('link', { name: /go to login/i });
    expect(loginLink).toHaveAttribute('href', '/login');
  });

  it('updates body copy when featureName prop changes', () => {
    const { rerender } = renderWithProviders(
      <FeatureDisabled featureName="Reports" />,
    );
    expect(screen.getByText(/reports has been disabled/i)).toBeInTheDocument();
    rerender(<FeatureDisabled featureName="Templates" />);
    expect(
      screen.getByText(/templates has been disabled/i),
    ).toBeInTheDocument();
  });
});
