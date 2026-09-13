import { STATUS_LABEL } from './types';
import type { BotState, StrategyEvent } from './types';

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function decimal(value: unknown): boolean {
  return (
    value === null ||
    (typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value)))
  );
}

export function isStrategyEvent(value: unknown): value is StrategyEvent {
  return (
    object(value) &&
    (value.environment === undefined || ['DEMO', 'LIVE'].includes(String(value.environment))) &&
    ((typeof value.id === 'number' && Number.isSafeInteger(value.id) && value.id > 0) ||
      (typeof value.id === 'string' && value.id.trim() !== '')) &&
    typeof value.time === 'string' &&
    Number.isFinite(Date.parse(value.time)) &&
    typeof value.title === 'string' &&
    typeof value.event === 'string' &&
    Object.prototype.hasOwnProperty.call(value, 'details')
  );
}

export function isBotState(value: unknown): value is BotState {
  if (
    !object(value) ||
    !['DEMO', 'LIVE'].includes(String(value.environment)) ||
    !Object.prototype.hasOwnProperty.call(STATUS_LABEL, String(value.status))
  )
    return false;
  for (const key of [
    'connected',
    'public_connected',
    'private_connected',
    'wizard_completed',
    'mainnet_allowed',
  ])
    if (typeof value[key] !== 'boolean') return false;
  if (!decimal(value.price) || !object(value.config) || !object(value.portfolio)) return false;
  if (value.mark_price !== undefined && !decimal(value.mark_price)) return false;
  if (value.portfolio.funding !== undefined && !decimal(value.portfolio.funding)) return false;
  if (value.config.symbol !== 'BTCUSDT' || !Number.isInteger(value.config.levels)) return false;
  for (const key of [
    'equity',
    'realized',
    'unrealized',
    'fees',
    'net',
    'today',
    'grid',
    'recovery',
    'long',
    'short',
  ])
    if (!decimal(value.portfolio[key])) return false;
  for (const key of ['grid', 'positions', 'recovery', 'candles'])
    if (!Array.isArray(value[key])) return false;
  if (
    !(value.grid as unknown[]).every(
      (level) => object(level) && Number.isInteger(level.index) && decimal(level.price),
    )
  )
    return false;
  if (
    !(value.candles as unknown[]).every(
      (candle) =>
        object(candle) &&
        typeof candle.time === 'number' &&
        Number.isFinite(candle.time) &&
        ['open', 'high', 'low', 'close'].every(
          (key) => typeof candle[key] === 'string' && decimal(candle[key]),
        ),
    )
  )
    return false;
  if (
    value.account !== null &&
    (!object(value.account) ||
      typeof value.account.uid !== 'string' ||
      typeof value.account.uta_status !== 'number' ||
      typeof value.account.hedge_mode !== 'boolean' ||
      typeof value.account.permissions !== 'boolean')
  )
    return false;
  if (
    !(value.recovery as unknown[]).every(
      (block) =>
        object(block) &&
        ['LONG', 'SHORT'].includes(String(block.side)) &&
        typeof block.safe === 'boolean',
    )
  )
    return false;
  return true;
}
