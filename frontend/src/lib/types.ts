export type Environment = 'DEMO' | 'LIVE';
export type BotStatus =
  'DISCONNECTED' | 'READY' | 'RUNNING' | 'PAUSED' | 'DEGRADED' | 'RECONCILING';
export type Side = 'LONG' | 'SHORT';
export type Amount = string | null;

export interface StrategyConfig {
  symbol: string;
  order_size_usdt: string;
  levels: number;
  spacing_pct: string;
  tp_pct: string;
  leverage: string;
  initial_pair: boolean;
  hysteresis_ticks: number;
  debounce_ms: number;
  recovery_threshold_pct: string;
  max_injection_usdt: string;
  max_recovery_exposure_usdt: string;
  max_exposure_usdt: string;
  max_daily_loss_usdt: string;
  recovery_profit_target_usdt: string;
  recovery_retrace_pct: string;
  slippage_pct: string;
  support_resistance_timeframe: string;
  auto_recovery: boolean;
}

export const DEFAULT_CONFIG: StrategyConfig = {
  symbol: 'BTCUSDT',
  order_size_usdt: '100',
  levels: 20,
  spacing_pct: '0.50',
  tp_pct: '1.00',
  leverage: '1',
  initial_pair: true,
  hysteresis_ticks: 5,
  debounce_ms: 3000,
  recovery_threshold_pct: '3',
  max_injection_usdt: '500',
  max_recovery_exposure_usdt: '2000',
  max_exposure_usdt: '5000',
  max_daily_loss_usdt: '100',
  recovery_profit_target_usdt: '1',
  recovery_retrace_pct: '1',
  slippage_pct: '0.10',
  support_resistance_timeframe: '15',
  auto_recovery: false,
};

export interface AccountInfo {
  uid: string;
  account_type: string;
  uta_status: number;
  equity: string;
  available_balance: string;
  hedge_mode: boolean;
  permissions: boolean;
  leverage_long: string;
  leverage_short: string;
  taker_fee?: string;
  maker_fee?: string;
  fee_source?: string;
}
export interface Candle {
  time: number;
  open: string;
  high: string;
  low: string;
  close: string;
  volume?: string;
}
export interface Position {
  side?: string;
  positionIdx?: number;
  size?: string;
  qty?: string;
  avgPrice?: string;
  entry?: string;
  markPrice?: string;
  mark_price?: string;
  unrealisedPnl?: string;
  unrealized_pnl?: string;
}
export interface RecoveryBlock {
  side: Side;
  qty: string;
  notional: string;
  average: string;
  unrealized_pnl: string;
  break_even: string;
  target: string;
  tp: string;
  required_qty: string;
  required_usdt: string;
  new_average: string;
  safe: boolean;
  reason: string;
  progress: string | null;
  fees: string;
  profit_target: string;
}
export interface Portfolio {
  equity: Amount;
  realized: Amount;
  unrealized: Amount;
  fees: Amount;
  net: Amount;
  today: Amount;
  grid: Amount;
  recovery: Amount;
  long: Amount;
  short: Amount;
  funding?: Amount;
}
export interface BotOrder {
  orderId?: string;
  order_id?: string;
  orderLinkId?: string;
  order_link_id?: string;
  purpose?: string;
  price?: string;
  side?: string;
  positionIdx?: number;
  qty?: string;
  orderStatus?: string;
  status?: string;
  state?: string;
  [key: string]: unknown;
}
export interface BotState {
  environment: Environment;
  status: BotStatus;
  connected: boolean;
  public_connected: boolean;
  private_connected: boolean;
  latency_ms: number | null;
  error: string | null;
  account: AccountInfo | null;
  price: Amount;
  mark_price?: Amount;
  config: StrategyConfig;
  grid: { index: number; price: string }[];
  positions: Position[];
  recovery: RecoveryBlock[];
  portfolio: Portfolio;
  candles: Candle[];
  orders?: BotOrder[];
  support_resistance?: Record<string, string | number | null>;
  wizard_completed: boolean;
  mainnet_allowed: boolean;
}
export interface StrategyEvent {
  id: string | number;
  environment?: Environment;
  time: string;
  title: string;
  event: string;
  details: unknown;
}

export const EMPTY_STATE: BotState = {
  environment: 'DEMO',
  status: 'DISCONNECTED',
  connected: false,
  public_connected: false,
  private_connected: false,
  latency_ms: null,
  error: null,
  account: null,
  price: null,
  mark_price: null,
  config: DEFAULT_CONFIG,
  grid: [],
  positions: [],
  recovery: [],
  candles: [],
  orders: [],
  portfolio: {
    equity: null,
    realized: null,
    unrealized: null,
    fees: null,
    net: null,
    today: null,
    grid: null,
    recovery: null,
    long: null,
    short: null,
  },
  wizard_completed: false,
  mainnet_allowed: false,
};

export const STATUS_LABEL: Record<BotStatus, string> = {
  DISCONNECTED: 'Non connesso',
  READY: 'Pronto',
  RUNNING: 'Bot attivo',
  PAUSED: 'In pausa',
  DEGRADED: 'Pausa di sicurezza',
  RECONCILING: 'Riconciliazione',
};
