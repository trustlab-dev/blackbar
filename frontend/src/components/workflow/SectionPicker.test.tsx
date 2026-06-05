import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { server } from '../../test-utils/msw-handlers';
import { renderWithProviders, screen, waitFor } from '../../test-utils/render';
import SectionPicker from './SectionPicker';

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  localStorage.setItem('token', 'fake');
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

const sections = [
  {
    code: 's13',
    name: 'Policy Advice',
    description: 'Advice or recommendations developed by or for a public body',
    category_id: 'cat1',
  },
  {
    code: 's14',
    name: 'Legal Advice',
    description: 'Information subject to solicitor-client privilege',
    category_id: 'cat1',
  },
  {
    code: 's22',
    name: 'Personal Privacy',
    description: 'Unreasonable invasion of personal privacy',
    category_id: 'cat2',
  },
];

function mockSections(list = sections) {
  server.use(
    http.get('/api/v1/packs/active/sections', () =>
      HttpResponse.json({
        sections: list,
        pack_id: 'p',
        pack_name: 'P',
        count: list.length,
      }),
    ),
  );
}

describe('SectionPicker', () => {
  it('loads sections and renders the autocomplete', async () => {
    mockSections();
    renderWithProviders(
      <SectionPicker selectedSections={[]} onChange={vi.fn()} />,
    );
    expect(
      await screen.findByLabelText(/exemption sections/i),
    ).toBeInTheDocument();
  });

  it('uses a custom label and placeholder', async () => {
    mockSections();
    renderWithProviders(
      <SectionPicker
        selectedSections={[]}
        onChange={vi.fn()}
        label="Pick Sections"
        placeholder="Type here..."
      />,
    );
    expect(await screen.findByLabelText('Pick Sections')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Type here...')).toBeInTheDocument();
  });

  it('selects a section from the dropdown and emits onChange', async () => {
    mockSections();
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <SectionPicker selectedSections={[]} onChange={onChange} />,
    );
    const input = await screen.findByLabelText(/exemption sections/i);
    await user.click(input);
    await user.type(input, 's13');
    const option = await screen.findByText('Policy Advice');
    await user.click(option);
    // first selection becomes the primary section
    expect(onChange).toHaveBeenCalledWith(['s13'], 's13');
  });

  it('renders selected sections as chips and the primary hint', async () => {
    mockSections();
    renderWithProviders(
      <SectionPicker
        selectedSections={['s13', 's14']}
        primarySection="s13"
        onChange={vi.fn()}
      />,
    );
    await screen.findByLabelText(/exemption sections/i);
    await waitFor(() =>
      expect(screen.getAllByText('s13').length).toBeGreaterThan(0),
    );
    expect(screen.getAllByText('s14').length).toBeGreaterThan(0);
    expect(
      screen.getByText(/Click a section chip to set it as primary/),
    ).toBeInTheDocument();
  });

  it('sets a chip as primary when clicked', async () => {
    mockSections();
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <SectionPicker
        selectedSections={['s13', 's14']}
        primarySection="s13"
        onChange={onChange}
      />,
    );
    await waitFor(() =>
      expect(screen.getAllByText('s14').length).toBeGreaterThan(0),
    );
    await user.click(screen.getAllByText('s14')[0]);
    expect(onChange).toHaveBeenCalledWith(['s13', 's14'], 's14');
  });

  it('removes a section and reassigns the primary', async () => {
    mockSections();
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <SectionPicker
        selectedSections={['s13', 's14']}
        primarySection="s13"
        onChange={onChange}
      />,
    );
    await waitFor(() =>
      expect(screen.getAllByText('s13').length).toBeGreaterThan(0),
    );
    // each chip has a delete (cancel) icon button
    const cancelIcons = screen.getAllByTestId('CancelIcon');
    await user.click(cancelIcons[0]);
    // s13 removed -> remaining s14 becomes primary
    expect(onChange).toHaveBeenCalledWith(['s14'], 's14');
  });

  it('handles a failed section fetch by rendering an empty list', async () => {
    server.use(
      http.get('/api/v1/packs/active/sections', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    renderWithProviders(
      <SectionPicker selectedSections={[]} onChange={vi.fn()} />,
    );
    // component still renders the input even when the fetch fails
    expect(
      await screen.findByLabelText(/exemption sections/i),
    ).toBeInTheDocument();
  });

  it('respects the disabled prop', async () => {
    mockSections();
    renderWithProviders(
      <SectionPicker selectedSections={[]} onChange={vi.fn()} disabled />,
    );
    const input = await screen.findByLabelText(/exemption sections/i);
    expect(input).toBeDisabled();
  });
});
