import type { StrategyConfig } from '../lib/types';

export type ConfigDraft = {
  [K in keyof StrategyConfig]: StrategyConfig[K] extends boolean ? boolean : string;
};
export type ConfigGroup = 'grid' | 'recovery' | 'risk';
export function toDraft(config: StrategyConfig): ConfigDraft {
  return Object.fromEntries(
    Object.entries(config).map(([key, value]) => [
      key,
      typeof value === 'boolean' ? value : String(value),
    ]),
  ) as ConfigDraft;
}

interface FieldSpec {
  key: keyof ConfigDraft;
  label: string;
  unit?: string;
  min?: number;
  max?: number;
  integer?: boolean;
  help?: string;
}
const FIELDS: Record<ConfigGroup, FieldSpec[]> = {
  grid: [
    {
      key: 'order_size_usdt',
      label: 'Importo per ordine',
      unit: 'USDT',
      min: 0,
      help: 'Ogni tocco apre un Long e uno Short di questo importo.',
    },
    {
      key: 'levels',
      label: 'Livelli per lato',
      min: 1,
      max: 100,
      integer: true,
      help: 'Lo stesso numero sopra e sotto al prezzo.',
    },
    { key: 'spacing_pct', label: 'Distanza livelli', unit: '%', min: 0, max: 5 },
    { key: 'tp_pct', label: 'Take Profit per posizione', unit: '%', min: 0, max: 20 },
  ],
  recovery: [
    { key: 'recovery_threshold_pct', label: 'Soglia di attivazione', unit: '%', min: 0, max: 50 },
    { key: 'max_injection_usdt', label: 'Injection massima', unit: 'USDT', min: 0 },
    {
      key: 'recovery_profit_target_usdt',
      label: 'Profitto netto obiettivo',
      unit: 'USDT',
      min: 0,
      help: 'Dopo costi di ingresso, uscita e slippage stimato.',
    },
    { key: 'recovery_retrace_pct', label: 'Ritracciamento obiettivo', unit: '%', min: 0, max: 10 },
  ],
  risk: [
    { key: 'max_exposure_usdt', label: 'Esposizione totale massima', unit: 'USDT', min: 0 },
    {
      key: 'max_recovery_exposure_usdt',
      label: 'Esposizione Recovery massima',
      unit: 'USDT',
      min: 0,
    },
    {
      key: 'max_daily_loss_usdt',
      label: 'Perdita giornaliera massima',
      unit: 'USDT',
      min: 0,
      help: 'Blocca nuovi ordini; le posizioni restano aperte.',
    },
    { key: 'slippage_pct', label: 'Limite slippage', unit: '%', min: 0.01, max: 1 },
  ],
};

export function parseConfig(draft: ConfigDraft): {
  config: StrategyConfig | null;
  error: string | null;
} {
  for (const field of [...FIELDS.grid, ...FIELDS.recovery, ...FIELDS.risk]) {
    const raw = String(draft[field.key]);
    const value = Number(raw);
    if (
      !raw.trim() ||
      !Number.isFinite(value) ||
      (field.integer && !Number.isInteger(value)) ||
      (field.min !== undefined && value < field.min) ||
      (field.max !== undefined && value > field.max) ||
      (value === 0 && field.key !== 'recovery_profit_target_usdt')
    ) {
      return {
        config: null,
        error: `${field.label}: inserisci un valore valido${field.max ? ` (massimo ${field.max})` : ''}.`,
      };
    }
  }
  if (!['1', '2', '3'].includes(draft.leverage)) return { config: null, error: 'Leva non valida.' };
  if (!['1', '5', '15', '30', '60', '240', 'D'].includes(draft.support_resistance_timeframe))
    return { config: null, error: 'Timeframe non valido.' };
  if (Number(draft.max_recovery_exposure_usdt) > Number(draft.max_exposure_usdt))
    return { config: null, error: 'L’esposizione Recovery non può superare l’esposizione totale.' };
  if (Number(draft.levels) * Number(draft.spacing_pct) >= 95)
    return { config: null, error: 'La finestra Grid è troppo ampia. Riduci livelli o distanza.' };
  if (
    !Number.isInteger(Number(draft.hysteresis_ticks)) ||
    Number(draft.hysteresis_ticks) < 1 ||
    Number(draft.hysteresis_ticks) > 1000
  )
    return { config: null, error: 'Isteresi: inserisci da 1 a 1000 tick.' };
  if (
    !Number.isInteger(Number(draft.debounce_ms)) ||
    Number(draft.debounce_ms) < 100 ||
    Number(draft.debounce_ms) > 60000
  )
    return { config: null, error: 'Debounce: inserisci da 100 a 60000 ms.' };
  return {
    config: {
      ...draft,
      symbol: 'BTCUSDT',
      levels: Number(draft.levels),
      hysteresis_ticks: Number(draft.hysteresis_ticks),
      debounce_ms: Number(draft.debounce_ms),
    },
    error: null,
  };
}

export function ConfigFields({
  group,
  draft,
  onChange,
  disabled = false,
}: {
  group: ConfigGroup;
  draft: ConfigDraft;
  onChange: (value: ConfigDraft) => void;
  disabled?: boolean;
}) {
  const set = (key: keyof ConfigDraft, value: string | boolean) =>
    onChange({ ...draft, [key]: value });
  return (
    <fieldset className="config-fieldset" disabled={disabled}>
      {group === 'grid' && (
        <div className="inline-fields">
          <label className="field">
            <span>Simbolo</span>
            <input value="BTCUSDT · USDT Perpetual" readOnly />
          </label>
          <label className="field">
            <span>Leva</span>
            <select value={draft.leverage} onChange={(e) => set('leverage', e.target.value)}>
              <option value="1">1×</option>
              <option value="2">2×</option>
              <option value="3">3×</option>
            </select>
          </label>
        </div>
      )}
      <div className="form-grid">
        {FIELDS[group].map((spec) => (
          <label className="field" key={spec.key}>
            <span>{spec.label}</span>
            <div className="input-unit">
              <input
                aria-label={spec.label}
                type="number"
                inputMode="decimal"
                min={spec.min}
                max={spec.max}
                step={spec.integer ? '1' : 'any'}
                value={String(draft[spec.key])}
                onChange={(e) => set(spec.key, e.target.value)}
              />
              {spec.unit && <span>{spec.unit}</span>}
            </div>
            {spec.help && <small>{spec.help}</small>}
          </label>
        ))}
      </div>
      {group === 'grid' && (
        <>
          <label className="check-row">
            <input
              type="checkbox"
              checked={draft.initial_pair}
              onChange={(e) => set('initial_pair', e.target.checked)}
            />
            <span>Apri una coppia Long + Short a mercato all’avvio</span>
          </label>
          <details className="advanced-fields">
            <summary>Protezione micro oscillazioni</summary>
            <div className="form-grid">
              <label className="field">
                <span>Isteresi (tick)</span>
                <input
                  type="number"
                  min="1"
                  max="1000"
                  step="1"
                  value={draft.hysteresis_ticks}
                  onChange={(e) => set('hysteresis_ticks', e.target.value)}
                />
              </label>
              <label className="field">
                <span>Debounce (ms)</span>
                <input
                  type="number"
                  min="100"
                  max="60000"
                  step="1"
                  value={draft.debounce_ms}
                  onChange={(e) => set('debounce_ms', e.target.value)}
                />
              </label>
            </div>
          </details>
        </>
      )}
      {group === 'recovery' && (
        <>
          <label className="field">
            <span>Timeframe supporti / resistenze</span>
            <select
              value={draft.support_resistance_timeframe}
              onChange={(e) => set('support_resistance_timeframe', e.target.value)}
            >
              {[
                ['1', '1 minuto'],
                ['5', '5 minuti'],
                ['15', '15 minuti'],
                ['30', '30 minuti'],
                ['60', '1 ora'],
                ['240', '4 ore'],
                ['D', '1 giorno'],
              ].map(([value, text]) => (
                <option key={value} value={value}>
                  {text}
                </option>
              ))}
            </select>
          </label>
          <label className="toggle-row">
            <span>
              <strong>Recovery automatico</strong>
              <small>
                Invia un’Injection soltanto quando tutti i limiti di rischio sono rispettati.
              </small>
            </span>
            <input
              role="switch"
              type="checkbox"
              checked={draft.auto_recovery}
              onChange={(e) => set('auto_recovery', e.target.checked)}
              aria-label="Recovery automatico"
            />
          </label>
        </>
      )}
    </fieldset>
  );
}
