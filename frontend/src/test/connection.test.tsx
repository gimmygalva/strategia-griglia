import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ConnectionForm } from '../components/ConnectionForm';
import { api, ApiError } from '../lib/api';
import { readyState } from './fixtures';

vi.mock('../lib/api', () => ({
  api: { credentials: vi.fn(), connect: vi.fn() },
  ApiError: class ApiError extends Error {
    constructor(
      public code: string,
      message: string,
    ) {
      super(message);
    }
  },
}));

beforeEach(() => {
  vi.mocked(api.credentials).mockReset().mockResolvedValue({ saved: true });
  vi.mocked(api.connect).mockReset().mockResolvedValue({ status: 'READY' });
});

describe('Bybit credentials and environment UI', () => {
  it('keeps DEMO and LIVE distinct and clears credentials on environment switch', async () => {
    const user = userEvent.setup();
    render(<ConnectionForm state={readyState()} onConnected={vi.fn()} />);
    await user.type(screen.getByLabelText('API Key'), 'demo-secret-key');
    await user.click(screen.getByRole('button', { name: /LIVE/ }));
    expect(screen.getByLabelText('API Key')).toHaveValue('');
    expect(screen.getByText(/api.bybit.com/)).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('fondi reali');
    await user.click(screen.getByRole('button', { name: /DEMO/ }));
    expect(screen.getByText(/api-demo.bybit.com/)).toBeInTheDocument();
  });
  it('rejects one missing credential without any network mutation', async () => {
    const user = userEvent.setup();
    render(<ConnectionForm state={readyState()} onConnected={vi.fn()} />);
    await user.type(screen.getByLabelText('API Key'), 'demokey123');
    await user.click(screen.getByRole('button', { name: 'Test Connessione' }));
    expect(screen.getByRole('alert')).toHaveTextContent('sia API Key sia API Secret');
    expect(api.credentials).not.toHaveBeenCalled();
    expect(api.connect).not.toHaveBeenCalled();
  });
  it('rejects malformed credentials', async () => {
    const user = userEvent.setup();
    render(<ConnectionForm state={readyState()} onConnected={vi.fn()} />);
    await user.type(screen.getByLabelText('API Key'), 'bad');
    await user.type(screen.getByLabelText('API Secret'), 'bad');
    await user.click(screen.getByRole('button', { name: 'Test Connessione' }));
    expect(screen.getByRole('alert')).toHaveTextContent('non validi');
    expect(api.credentials).not.toHaveBeenCalled();
  });
  it('saves secrets write-only, clears inputs and never writes localStorage', async () => {
    const user = userEvent.setup();
    const saved = vi.spyOn(Storage.prototype, 'setItem');
    render(<ConnectionForm state={readyState()} onConnected={vi.fn()} />);
    const secret = 'only-memory-secret';
    await user.type(screen.getByLabelText('API Key'), 'demo-key1234');
    await user.type(screen.getByLabelText('API Secret'), secret);
    expect(screen.getByLabelText('API Secret')).toHaveAttribute('type', 'password');
    await user.click(screen.getByRole('button', { name: 'Test Connessione' }));
    await waitFor(() => expect(api.connect).toHaveBeenCalledWith('DEMO'));
    expect(api.credentials).toHaveBeenCalledWith('DEMO', 'demo-key1234', secret);
    expect(screen.getByLabelText('API Secret')).toHaveValue('');
    expect(screen.getByLabelText('API Key')).toHaveValue('');
    expect(document.body.textContent).not.toContain(secret);
    expect(saved).not.toHaveBeenCalled();
  });
  it('shows authentication errors and never substitutes a fake balance', async () => {
    vi.mocked(api.connect).mockRejectedValue(
      new ApiError('AUTHENTICATION_FAILED', 'Credenziali rifiutate.'),
    );
    const user = userEvent.setup();
    render(
      <ConnectionForm
        state={readyState({ account: null, connected: false })}
        onConnected={vi.fn()}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Test Connessione' }));
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Authentication Failed'),
    );
    expect(screen.queryByText(/9.500/)).not.toBeInTheDocument();
  });
  it('separates credential storage step from connection and trading', async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    render(
      <ConnectionForm
        state={readyState()}
        onConnected={vi.fn()}
        credentialsOnly
        onSaved={onSaved}
      />,
    );
    await user.type(screen.getByLabelText('API Key'), 'demo-key123');
    await user.type(screen.getByLabelText('API Secret'), 'demo-secret123');
    await user.click(screen.getByRole('button', { name: 'Salva credenziali' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(api.connect).not.toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent('Credenziali salvate');
  });
  it('disables connection changes while the bot is running', () => {
    render(<ConnectionForm state={readyState({ status: 'RUNNING' })} onConnected={vi.fn()} />);
    expect(screen.getByLabelText('API Key')).toBeDisabled();
    expect(screen.getByRole('button', { name: /LIVE/ })).toBeDisabled();
  });
});
