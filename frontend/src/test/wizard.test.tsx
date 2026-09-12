import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Wizard } from '../components/Wizard';
import { api } from '../lib/api';
import { readyState } from './fixtures';

vi.mock('../lib/api', () => ({
  api: { credentials: vi.fn(), connect: vi.fn(), config: vi.fn(), wizard: vi.fn() },
  ApiError: class extends Error {},
}));
beforeEach(() => {
  vi.mocked(api.credentials).mockReset().mockResolvedValue({ saved: true });
  vi.mocked(api.connect).mockReset().mockResolvedValue({ status: 'READY' });
  vi.mocked(api.config).mockReset().mockResolvedValue({ config: readyState().config });
  vi.mocked(api.wizard).mockReset().mockResolvedValue({ saved: true });
});

describe('first-run wizard', () => {
  it('completes all ten steps and saves before requesting Demo start', async () => {
    const user = userEvent.setup();
    const start = vi.fn();
    const close = vi.fn();
    render(
      <Wizard
        state={readyState()}
        backendOnline
        socketOnline
        refresh={vi.fn().mockResolvedValue(undefined)}
        onClose={close}
        onStart={start}
      />,
    );
    await user.click(screen.getByRole('button', { name: /Cominciamo/ }));
    expect(screen.getByRole('button', { name: /DEMO/ })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: /Continua/ }));
    expect(screen.getByRole('button', { name: /Continua/ })).toBeDisabled();
    await user.type(screen.getByLabelText('API Key'), 'demo-key123');
    await user.type(screen.getByLabelText('API Secret'), 'demo-secret123');
    await user.click(screen.getByRole('button', { name: 'Salva credenziali' }));
    await waitFor(() => expect(screen.getByRole('button', { name: /Continua/ })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: /Continua/ }));
    await user.click(screen.getByRole('button', { name: 'Test Connessione' }));
    await waitFor(() => expect(screen.getByRole('button', { name: /Continua/ })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: /Continua/ }));
    expect(screen.getByText('Configurazione account compatibile.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Continua/ }));
    expect(screen.getByLabelText('Importo per ordine')).toHaveValue(100);
    await user.click(screen.getByRole('button', { name: /Continua/ }));
    expect(screen.getByRole('switch', { name: 'Recovery automatico' })).not.toBeChecked();
    await user.click(screen.getByRole('button', { name: /Continua/ }));
    expect(screen.getByLabelText('Perdita giornaliera massima')).toHaveValue(100);
    await user.click(screen.getByRole('button', { name: /Continua/ }));
    expect(screen.getByText('Controlla ogni scelta.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Continua/ }));
    expect(screen.getByText('STEP 10 DI 10')).toBeInTheDocument();
    expect(start).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Salva e avvia bot DEMO' }));
    await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
    expect(api.config).toHaveBeenCalledWith(readyState().config);
    expect(api.wizard).toHaveBeenCalledTimes(1);
    expect(close).toHaveBeenCalled();
  });
  it('shows Live warning immediately on selection without any trading call', async () => {
    const user = userEvent.setup();
    const start = vi.fn();
    render(
      <Wizard
        state={readyState()}
        backendOnline
        socketOnline
        refresh={vi.fn()}
        onClose={vi.fn()}
        onStart={start}
      />,
    );
    await user.click(screen.getByRole('button', { name: /Cominciamo/ }));
    await user.click(screen.getByRole('button', { name: /LIVE/ }));
    expect(screen.getByRole('alert')).toHaveTextContent('fondi reali');
    expect(start).not.toHaveBeenCalled();
    expect(api.connect).not.toHaveBeenCalled();
  });
});
