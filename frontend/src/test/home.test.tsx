import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Home, canStart } from '../components/Home';
import { api } from '../lib/api';
import type { BotState } from '../lib/types';
import { readyState, recoveryFixture } from './fixtures';

vi.mock('../lib/api', () => ({
  api: { candles: vi.fn(), pause: vi.fn(), config: vi.fn(), recovery: vi.fn() },
}));
beforeEach(() => {
  vi.mocked(api.candles).mockReset().mockResolvedValue([]);
  vi.mocked(api.pause).mockReset().mockResolvedValue({ status: 'PAUSED' });
  vi.mocked(api.config).mockReset();
  vi.mocked(api.recovery).mockReset().mockResolvedValue({ status: 'RUNNING' });
});

const home = async (state: BotState, backendOnline = true, socketOnline = true) => {
  await act(async () => {
    render(
      <Home
        state={state}
        backendOnline={backendOnline}
        socketOnline={socketOnline}
        refresh={vi.fn().mockResolvedValue(undefined)}
        onStart={vi.fn()}
        onCloseAll={vi.fn()}
        onOpenSettings={vi.fn()}
        busy={false}
      />,
    );
  });
};

describe('start gating', () => {
  it('permits verified and reconciled Demo only with both feeds and local realtime', () => {
    expect(canStart(readyState(), true, true)).toBe(true);
    expect(canStart(readyState(), false, true)).toBe(false);
    expect(canStart(readyState(), true, false)).toBe(false);
  });
  it.each([
    { private_connected: false },
    { public_connected: false },
    { connected: false },
    { status: 'DEGRADED' },
    { status: 'RECONCILING' },
    { status: 'DISCONNECTED' },
    { status: 'RUNNING' },
  ] as Partial<BotState>[])('blocks unsafe exchange state %o', (overrides) => {
    expect(canStart(readyState(overrides), true, true)).toBe(false);
  });
  it('blocks incompatible accounts and Mainnet disabled default', () => {
    const state = readyState();
    expect(
      canStart({ ...state, account: { ...state.account!, hedge_mode: false } }, true, true),
    ).toBe(false);
    expect(
      canStart({ ...state, account: { ...state.account!, permissions: false } }, true, true),
    ).toBe(false);
    expect(canStart({ ...state, account: { ...state.account!, uta_status: 1 } }, true, true)).toBe(
      false,
    );
    expect(canStart({ ...state, environment: 'LIVE', mainnet_allowed: false }, true, true)).toBe(
      false,
    );
    expect(canStart({ ...state, environment: 'LIVE', mainnet_allowed: true }, true, true)).toBe(
      true,
    );
  });
});

describe('Home overview', () => {
  it('shows real state portfolio, neutral recovery and separate PnL cards', async () => {
    await home(readyState());
    expect(screen.getByText('10.000,00')).toBeInTheDocument();
    expect(screen.getByText('RECOVERY NON NECESSARIO')).toBeInTheDocument();
    expect(screen.getByText('LONG PnL')).toBeInTheDocument();
    expect(screen.getByText('SHORT PnL')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Avvia bot' })).toBeEnabled();
    await waitFor(() => expect(api.candles).toHaveBeenCalledWith('15'));
  });
  it('does not display financial values from stale account state when backend is offline', async () => {
    await home(readyState(), false);
    expect(screen.queryByText('10.000,00')).not.toBeInTheDocument();
    expect(screen.queryByText('+20,00')).not.toBeInTheDocument();
    expect(screen.getAllByText('NON CONNESSO').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Avvia bot' })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Chiudi tutto/ })).toBeDisabled();
  });
  it('pauses strategy without calling close all or recovery', async () => {
    const user = userEvent.setup();
    await home(readyState({ status: 'RUNNING' }));
    await user.click(screen.getByRole('button', { name: 'Pausa bot' }));
    await waitFor(() => expect(api.pause).toHaveBeenCalledTimes(1));
    expect(api.recovery).not.toHaveBeenCalled();
  });
  it('shows unsafe Recovery and blocks injection', async () => {
    await home(
      readyState({
        status: 'RUNNING',
        recovery: [{ ...recoveryFixture, safe: false, reason: 'Esposizione massima' }],
      }),
    );
    expect(screen.getByText(/RECOVERY NON SICURO/)).toHaveTextContent('Esposizione massima');
    expect(screen.getByRole('button', { name: 'Valuta Injection' })).toBeDisabled();
  });
  it('requires explicit manual Recovery confirmation before submitting', async () => {
    const user = userEvent.setup();
    await home(readyState({ status: 'RUNNING', recovery: [recoveryFixture] }));
    await user.click(screen.getByRole('button', { name: 'Valuta Injection' }));
    expect(screen.getByRole('dialog', { name: 'Injection SHORT' })).toBeInTheDocument();
    expect(api.recovery).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Conferma Injection' }));
    await waitFor(() => expect(api.recovery).toHaveBeenCalledWith('SHORT'));
  });
  it('never invents Recovery progress when the backend has no measured value', async () => {
    await home(readyState({ status: 'RUNNING', recovery: [recoveryFixture] }));
    expect(screen.getByText('In attesa')).toBeInTheDocument();
    expect(screen.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow');
  });
  it('updates automatic Recovery through validated backend config', async () => {
    const state = readyState();
    vi.mocked(api.config).mockResolvedValue({ config: { ...state.config, auto_recovery: true } });
    const user = userEvent.setup();
    await home(state);
    await user.click(screen.getByRole('switch', { name: 'Recovery automatico' }));
    await waitFor(() =>
      expect(api.config).toHaveBeenCalledWith({ ...state.config, auto_recovery: true }),
    );
  });
  it('values real exposure at the current mark price rather than the last trade', async () => {
    await home(
      readyState({
        mark_price: '66500',
        price: '67000',
        positions: [{ positionIdx: 1, size: '0.01', avgPrice: '65000' }],
      }),
    );
    expect(
      within(screen.getByText('Long exposure').parentElement!).getByText('665,00'),
    ).toBeInTheDocument();
  });
  it('leaves position exposure unknown if no verified mark price is available', async () => {
    await home(readyState({ mark_price: null, positions: [{ positionIdx: 1, size: '0.01' }] }));
    expect(screen.getByText('Long exposure').parentElement).toHaveTextContent('—');
  });
  it('shows actual funding separately from commissions in PnL breakdown', async () => {
    const user = userEvent.setup();
    const state = readyState();
    await home({ ...state, portfolio: { ...state.portfolio, funding: '-2.50' } });
    await user.click(screen.getByRole('button', { name: 'Composizione PnL' }));
    expect(screen.getByText('Funding')).toBeInTheDocument();
    expect(screen.getByText('-2,50')).toBeInTheDocument();
  });
});
