import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { useBot } from '../lib/useBot';
import { api } from '../lib/api';
import { readyState } from './fixtures';

vi.mock('../lib/useBot', () => ({ useBot: vi.fn() }));
vi.mock('../lib/api', () => ({
  api: {
    candles: vi.fn(),
    start: vi.fn(),
    pause: vi.fn(),
    closeAll: vi.fn(),
    config: vi.fn(),
    credentials: vi.fn(),
    connect: vi.fn(),
  },
  ApiError: class extends Error {},
}));
const botFixture = () => ({
  state: readyState(),
  events: [],
  loading: false,
  error: null,
  backendOnline: true,
  socketOnline: true,
  refresh: vi.fn().mockResolvedValue(undefined),
});
const renderApp = async () => {
  await act(async () => {
    render(<App />);
  });
};
beforeEach(() => {
  vi.mocked(useBot).mockReturnValue(botFixture());
  vi.mocked(api.candles).mockReset().mockResolvedValue([]);
  vi.mocked(api.start).mockReset().mockResolvedValue({ status: 'RUNNING' });
  vi.mocked(api.pause).mockReset().mockResolvedValue({ status: 'PAUSED' });
  vi.mocked(api.closeAll).mockReset().mockResolvedValue({ status: 'PAUSED' });
});

describe('application screens and controls', () => {
  it('navigates Home, Activity and Settings and always displays environment/status/latency', async () => {
    const user = userEvent.setup();
    await renderApp();
    const navigation = screen.getByRole('navigation', { name: 'Navigazione principale' });
    expect(screen.getByRole('contentinfo', { name: 'Stato connessione' })).toHaveTextContent(
      'DEMO',
    );
    expect(screen.getByRole('contentinfo')).toHaveTextContent('Connected');
    expect(screen.getByRole('contentinfo')).toHaveTextContent('91 ms');
    await user.click(within(navigation).getByRole('button', { name: 'Attività' }));
    expect(screen.getByText('Nessuna attività registrata')).toBeInTheDocument();
    await user.click(within(navigation).getByRole('button', { name: 'Impostazioni' }));
    expect(screen.getByRole('button', { name: 'Test Connessione' })).toBeInTheDocument();
    await user.click(within(navigation).getByRole('button', { name: 'Home' }));
    expect(screen.getByRole('button', { name: 'Avvia bot' })).toBeInTheDocument();
  });
  it('starts Demo only from explicit user action', async () => {
    const user = userEvent.setup();
    await renderApp();
    expect(api.start).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Avvia bot' }));
    await waitFor(() => expect(api.start).toHaveBeenCalledWith(false));
  });
  it('blocks all start commands when backend unavailable and shows no account values', async () => {
    vi.mocked(useBot).mockReturnValue({
      ...botFixture(),
      backendOnline: false,
      socketOnline: false,
      error: 'Offline',
    });
    const user = userEvent.setup();
    await renderApp();
    expect(screen.getByText('Backend non raggiungibile')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Avvia bot' })).toBeDisabled();
    expect(screen.queryByText('10.000,00')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Avvia bot' }));
    expect(api.start).not.toHaveBeenCalled();
  });
  it('requires Live dialog before sending any Mainnet start request', async () => {
    vi.mocked(useBot).mockReturnValue({
      ...botFixture(),
      state: readyState({ environment: 'LIVE', mainnet_allowed: true }),
    });
    const user = userEvent.setup();
    await renderApp();
    expect(screen.getByRole('contentinfo')).toHaveTextContent('LIVE');
    await user.click(screen.getByRole('button', { name: 'Avvia bot' }));
    expect(screen.getByRole('dialog', { name: 'Attivare il trading LIVE?' })).toBeInTheDocument();
    expect(api.start).not.toHaveBeenCalled();
    await user.click(screen.getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: 'Continua' }));
    await user.type(screen.getByRole('textbox'), 'AVVIA LIVE');
    await user.click(screen.getByRole('button', { name: 'Avvia con fondi reali' }));
    await waitFor(() => expect(api.start).toHaveBeenCalledWith(true));
  });
  it('emergency Stop pauses and never submits close-all', async () => {
    vi.mocked(useBot).mockReturnValue({
      ...botFixture(),
      state: readyState({ status: 'RUNNING' }),
    });
    const user = userEvent.setup();
    await renderApp();
    await user.click(screen.getByRole('button', { name: 'Stop bot' }));
    await waitFor(() => expect(api.pause).toHaveBeenCalledTimes(1));
    expect(api.closeAll).not.toHaveBeenCalled();
  });
  it('opens first-run wizard without auto-starting the bot', async () => {
    vi.mocked(useBot).mockReturnValue({
      ...botFixture(),
      state: readyState({ wizard_completed: false }),
    });
    await renderApp();
    expect(screen.getByRole('dialog', { name: 'Configurazione guidata' })).toBeInTheDocument();
    expect(api.start).not.toHaveBeenCalled();
  });
});
