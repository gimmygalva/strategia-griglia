import { describe, expect, it } from 'vitest';
import { isBotState } from '../lib/validation';
import { readyState } from './fixtures';

describe('realtime protocol validation', () => {
  it('accepts contract-complete server state', () => {
    expect(isBotState(readyState())).toBe(true);
  });
  it.each([
    null,
    {},
    { environment: 'TESTNET' },
    { ...readyState(), status: 'toString' },
    { ...readyState(), portfolio: null },
    { ...readyState(), price: 'Infinity' },
    { ...readyState(), candles: [{ time: 1 }] },
    { ...readyState(), account: { uid: 'unverified' } },
  ])('rejects invalid state shape without letting UI operate %o', (value) => {
    expect(isBotState(value)).toBe(false);
  });
});
