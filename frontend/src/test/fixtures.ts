// Local Simulator fixture data. This module is excluded from the production bundle.
import { EMPTY_STATE, DEFAULT_CONFIG } from '../lib/types';
import type { BotState, RecoveryBlock } from '../lib/types';

export function readyState(overrides: Partial<BotState> = {}): BotState {
  return {
    ...structuredClone(EMPTY_STATE),
    config: { ...DEFAULT_CONFIG },
    environment: 'DEMO',
    connected: true,
    public_connected: true,
    private_connected: true,
    status: 'READY',
    wizard_completed: true,
    latency_ms: 91,
    account: {
      uid: 'simulator-account',
      account_type: 'UNIFIED',
      uta_status: 5,
      equity: '10000',
      available_balance: '9500',
      hedge_mode: true,
      permissions: true,
      leverage_long: '1',
      leverage_short: '1',
    },
    price: '67000',
    portfolio: {
      equity: '10000',
      realized: '18',
      unrealized: '-2',
      fees: '1',
      net: '15',
      today: '15',
      grid: '17',
      recovery: '-2',
      long: '20',
      short: '-5',
    },
    candles: [
      {
        time: 1760000000,
        open: '66900',
        high: '67100',
        low: '66800',
        close: '67000',
        volume: '42',
      },
    ],
    ...overrides,
  };
}

export const recoveryFixture: RecoveryBlock = {
  side: 'SHORT',
  qty: '0.004',
  notional: '268',
  average: '65000',
  unrealized_pnl: '-8',
  break_even: '66800',
  target: '66870',
  tp: '66790',
  required_qty: '0.005',
  required_usdt: '335',
  new_average: '66870',
  safe: true,
  reason: '',
  progress: null,
  fees: '0.5',
  profit_target: '1',
};
