import { describe, it, expect, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import { renderWithProviders, screen } from '../../test-utils/render';
import PackCard from './PackCard';

const basePack = {
  pack_id: 'ca-bc-fippa',
  name: 'BC FIPPA',
  version: '1.2.0',
  description: 'British Columbia jurisdiction pack',
  jurisdiction: {
    country: 'CA',
    region: 'British Columbia',
    legislation_short: 'FIPPA',
  },
  author: 'BlackBar Team',
  category_count: 12,
  status_count: 6,
  has_templates: true,
  has_ai_prompts: true,
  is_active: false,
};

describe('PackCard', () => {
  it('renders pack metadata, chips and the country flag', () => {
    renderWithProviders(
      <PackCard
        pack={basePack}
        onActivate={vi.fn()}
        onViewDetails={vi.fn()}
        activating={false}
      />,
    );
    expect(screen.getByText('BC FIPPA')).toBeInTheDocument();
    expect(screen.getByText('v1.2.0')).toBeInTheDocument();
    expect(
      screen.getByText('British Columbia jurisdiction pack'),
    ).toBeInTheDocument();
    expect(screen.getByText('FIPPA')).toBeInTheDocument();
    expect(screen.getByText('12 categories')).toBeInTheDocument();
    expect(screen.getByText('6 statuses')).toBeInTheDocument();
    expect(screen.getByText('Templates')).toBeInTheDocument();
    expect(screen.getByText('AI Ready')).toBeInTheDocument();
    expect(screen.getByText(/By BlackBar Team/)).toBeInTheDocument();
    expect(screen.getByText('🇨🇦')).toBeInTheDocument();
  });

  it('uses the globe fallback flag for an unknown country', () => {
    renderWithProviders(
      <PackCard
        pack={{
          ...basePack,
          jurisdiction: { ...basePack.jurisdiction, country: 'ZZ' },
        }}
        onActivate={vi.fn()}
        onViewDetails={vi.fn()}
        activating={false}
      />,
    );
    expect(screen.getByText('🌍')).toBeInTheDocument();
  });

  it('calls onViewDetails when the Details button is clicked', async () => {
    const onViewDetails = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <PackCard
        pack={basePack}
        onActivate={vi.fn()}
        onViewDetails={onViewDetails}
        activating={false}
      />,
    );
    await user.click(screen.getByRole('button', { name: /details/i }));
    expect(onViewDetails).toHaveBeenCalledWith(basePack);
  });

  it('calls onActivate when the Activate button is clicked', async () => {
    const onActivate = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <PackCard
        pack={basePack}
        onActivate={onActivate}
        onViewDetails={vi.fn()}
        activating={false}
      />,
    );
    await user.click(screen.getByRole('button', { name: /activate/i }));
    expect(onActivate).toHaveBeenCalledWith('ca-bc-fippa');
  });

  it('shows the Activating state and disables the button', () => {
    renderWithProviders(
      <PackCard
        pack={basePack}
        onActivate={vi.fn()}
        onViewDetails={vi.fn()}
        activating
      />,
    );
    const btn = screen.getByRole('button', { name: /activating/i });
    expect(btn).toBeDisabled();
  });

  it('renders the ACTIVE chip and "In Use" instead of the Activate button when active', () => {
    renderWithProviders(
      <PackCard
        pack={{ ...basePack, is_active: true }}
        onActivate={vi.fn()}
        onViewDetails={vi.fn()}
        activating={false}
      />,
    );
    expect(screen.getByText('ACTIVE')).toBeInTheDocument();
    expect(screen.getByText('In Use')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /activate/i }),
    ).not.toBeInTheDocument();
  });

  it('omits the Templates / AI Ready chips when those capabilities are off', () => {
    renderWithProviders(
      <PackCard
        pack={{ ...basePack, has_templates: false, has_ai_prompts: false }}
        onActivate={vi.fn()}
        onViewDetails={vi.fn()}
        activating={false}
      />,
    );
    expect(screen.queryByText('Templates')).not.toBeInTheDocument();
    expect(screen.queryByText('AI Ready')).not.toBeInTheDocument();
  });
});
