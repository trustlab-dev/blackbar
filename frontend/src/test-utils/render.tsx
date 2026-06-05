import { ReactElement } from 'react';
import { render, RenderOptions } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import { AuthProvider } from '../contexts/AuthContext';

const theme = createTheme();

type ProviderOptions = Omit<RenderOptions, 'wrapper'> & {
  withAuth?: boolean;
  route?: string;
};

export function renderWithProviders(
  ui: ReactElement,
  options?: ProviderOptions,
) {
  const { withAuth = false, route = '/', ...rest } = options ?? {};

  function Wrapper({ children }: { children: React.ReactNode }) {
    const tree = (
      <ThemeProvider theme={theme}>
        <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
      </ThemeProvider>
    );
    return withAuth ? <AuthProvider>{tree}</AuthProvider> : tree;
  }

  return render(ui, { wrapper: Wrapper, ...rest });
}

export * from '@testing-library/react';
