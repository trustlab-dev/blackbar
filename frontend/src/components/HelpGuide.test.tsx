import { describe, it, expect } from 'vitest';
import userEvent from '@testing-library/user-event';
import { renderWithProviders, screen } from '../test-utils/render';
import HelpGuide from './HelpGuide';

describe('HelpGuide — initial render', () => {
  it('renders the heading and all section navigation buttons', () => {
    renderWithProviders(<HelpGuide />);
    expect(
      screen.getByRole('heading', { name: /blackbar help guide/i, level: 1 }),
    ).toBeInTheDocument();
    // Nav buttons present for each of the current sections. Names match
    // the 2026-05-16 content review; if a section is renamed or
    // restructured, update this list alongside the section title.
    expect(screen.getByRole('button', { name: /getting started/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /cases & workflow/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /documents & upload/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /redaction tools/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /ai suggestions/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /llm configuration/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /public portal/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /release packages/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /admin & system config/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /troubleshooting/i })).toBeInTheDocument();
  });

  it('renders Getting Started questions by default', () => {
    renderWithProviders(<HelpGuide />);
    expect(
      screen.getByRole('heading', { name: /what is blackbar\?/i }),
    ).toBeInTheDocument();
  });

  it('renders the search input and footer', () => {
    renderWithProviders(<HelpGuide />);
    expect(screen.getByPlaceholderText(/search help articles/i)).toBeInTheDocument();
    expect(screen.getByText(/need more detail\?/i)).toBeInTheDocument();
  });
});

describe('HelpGuide — section switching', () => {
  it('switches to Cases & Workflow when its nav button is clicked', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HelpGuide />);
    await user.click(screen.getByRole('button', { name: /cases & workflow/i }));
    expect(
      screen.getByRole('heading', { name: /how do i create a new case\?/i }),
    ).toBeInTheDocument();
  });

  it('switches to Troubleshooting when its nav button is clicked', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HelpGuide />);
    await user.click(screen.getByRole('button', { name: /troubleshooting/i }));
    // Use a partial match on a distinctive troubleshooting question
    // so the test isn't brittle to copy edits.
    expect(
      screen.getByRole('heading', { name: /no default llm is set/i }),
    ).toBeInTheDocument();
  });

  it('switches to AI Suggestions and surfaces the Why expander documentation', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HelpGuide />);
    await user.click(screen.getByRole('button', { name: /ai suggestions/i }));
    expect(
      screen.getByRole('heading', { name: /reading a suggestion/i }),
    ).toBeInTheDocument();
  });
});

describe('HelpGuide — search', () => {
  it('filters questions by question text', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HelpGuide />);
    const search = screen.getByPlaceholderText(/search help articles/i);
    await user.type(search, 'create a new case');
    await user.click(screen.getByRole('button', { name: /cases & workflow/i }));
    expect(
      screen.getByRole('heading', { name: /how do i create a new case\?/i }),
    ).toBeInTheDocument();
  });

  it('shows "No results found" when search matches nothing', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HelpGuide />);
    const search = screen.getByPlaceholderText(/search help articles/i);
    await user.type(search, 'zzzzz-no-such-thing');
    expect(screen.getByRole('heading', { name: /no results found/i })).toBeInTheDocument();
  });

  it('filters by tag matches — case-team tag surfaces the team Q', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HelpGuide />);
    const search = screen.getByPlaceholderText(/search help articles/i);
    // The "case-team" tag is on the "Adding people to a case team" Q
    // in Cases & Workflow.
    await user.type(search, 'case-team');
    await user.click(screen.getByRole('button', { name: /cases & workflow/i }));
    expect(
      screen.getByRole('heading', { name: /adding people to a case team/i }),
    ).toBeInTheDocument();
  });
});
