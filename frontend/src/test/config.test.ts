import { describe, expect, it } from 'vitest';
import { DEFAULT_CONFIG } from '../lib/types';
import { parseConfig, toDraft } from '../components/ConfigFields';
import { amount, pnlClass, timeLabel } from '../lib/format';

describe('configuration validation', () => {
  it('preserves Decimal strings and integer config fields', () => {
    const draft = { ...toDraft(DEFAULT_CONFIG), order_size_usdt: '100.000001' };
    const { config, error } = parseConfig(draft);
    expect(error).toBeNull();
    expect(config?.order_size_usdt).toBe('100.000001');
    expect(config?.levels).toBe(20);
    expect(config?.auto_recovery).toBe(false);
  });
  it.each(['', '-5', 'NaN', 'Infinity', '0'])('rejects invalid order amount %s', (value) => {
    expect(parseConfig({ ...toDraft(DEFAULT_CONFIG), order_size_usdt: value }).config).toBeNull();
  });
  it.each(['0', '101', '2.5'])('rejects invalid level count %s', (value) => {
    expect(parseConfig({ ...toDraft(DEFAULT_CONFIG), levels: value }).config).toBeNull();
  });
  it('rejects recovery exposure larger than total exposure', () => {
    expect(
      parseConfig({ ...toDraft(DEFAULT_CONFIG), max_recovery_exposure_usdt: '6000' }).error,
    ).toMatch(/Recovery/);
  });
  it('rejects unsafe geometry', () => {
    expect(
      parseConfig({ ...toDraft(DEFAULT_CONFIG), levels: '100', spacing_pct: '1' }).error,
    ).toMatch(/ampia/);
  });
  it('rejects invalid debounce and hysteresis', () => {
    expect(parseConfig({ ...toDraft(DEFAULT_CONFIG), debounce_ms: '99' }).error).toMatch(
      /Debounce/,
    );
    expect(parseConfig({ ...toDraft(DEFAULT_CONFIG), hysteresis_ticks: '0' }).error).toMatch(
      /Isteresi/,
    );
  });
  it('supports zero recovery profit but not zero fee slippage', () => {
    expect(
      parseConfig({ ...toDraft(DEFAULT_CONFIG), recovery_profit_target_usdt: '0' }).config,
    ).not.toBeNull();
    expect(parseConfig({ ...toDraft(DEFAULT_CONFIG), slippage_pct: '0' }).config).toBeNull();
  });
  it('only accepts whitelisted leverage and timeframe', () => {
    expect(parseConfig({ ...toDraft(DEFAULT_CONFIG), leverage: '100' }).config).toBeNull();
    expect(
      parseConfig({ ...toDraft(DEFAULT_CONFIG), support_resistance_timeframe: '../../' }).config,
    ).toBeNull();
  });
});

describe('display formatting', () => {
  it('does not substitute zero when real data is missing', () => {
    expect(amount(null)).toBe('—');
    expect(amount(undefined)).toBe('—');
    expect(amount('bad')).toBe('—');
  });
  it('uses signed PnL, deterministic financial color and local UTC time conversion', () => {
    expect(amount('-12.42', 2, true)).toBe('-12,42');
    expect(pnlClass('-12')).toBe('text-negative');
    expect(pnlClass(null)).toBe('text-muted');
    expect(timeLabel('invalid')).toBe('invalid');
  });
});
