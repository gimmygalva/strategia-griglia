import { useState } from 'react';
import {
  ArrowDownRight,
  ArrowUpRight,
  CirclePause,
  CirclePlay,
  Layers3,
  LoaderCircle,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Wallet,
  XCircle,
} from 'lucide-react';
import { api } from '../lib/api';
import type { BotState, RecoveryBlock } from '../lib/types';
import { amount, pnlClass } from '../lib/format';
import { PriceChart } from './Chart';
import { Modal } from './Modal';
import { Alert } from './Alert';
import { STATUS_LABEL } from '../lib/types';

function exposure(state: BotState, side: 'LONG' | 'SHORT'): string | null {
  if (!state.connected) return null;
  const matching = state.positions.filter(
    (position) =>
      position.positionIdx === (side === 'LONG' ? 1 : 2) ||
      position.side === side ||
      position.side === (side === 'LONG' ? 'Buy' : 'Sell'),
  );
  if (
    matching.some(
      (position) =>
        (position.size ?? position.qty) == null ||
        !(state.mark_price ?? position.markPrice ?? position.mark_price) ||
        !Number.isFinite(Number(position.size ?? position.qty)) ||
        !Number.isFinite(Number(state.mark_price ?? position.markPrice ?? position.mark_price)),
    )
  )
    return null;
  return String(
    matching.reduce(
      (sum, position) =>
        sum +
        Number(position.size ?? position.qty) *
          Number(state.mark_price ?? position.markPrice ?? position.mark_price),
      0,
    ),
  );
}

export function canStart(state: BotState, backendOnline: boolean, socketOnline: boolean): boolean {
  return (
    backendOnline &&
    socketOnline &&
    state.connected &&
    state.public_connected &&
    state.private_connected &&
    ['READY', 'PAUSED'].includes(state.status) &&
    !!state.account?.permissions &&
    !!state.account?.hedge_mode &&
    state.account.uta_status >= 3 &&
    (state.environment === 'DEMO' || state.mainnet_allowed)
  );
}

export function Home({
  state,
  backendOnline,
  socketOnline,
  refresh,
  onStart,
  onCloseAll,
  onOpenSettings,
  busy,
}: {
  state: BotState;
  backendOnline: boolean;
  socketOnline: boolean;
  refresh: () => Promise<void>;
  onStart: () => void;
  onCloseAll: () => void;
  onOpenSettings: () => void;
  busy: boolean;
}) {
  const [recovery, setRecovery] = useState<RecoveryBlock | null>(null);
  const [recovering, setRecovering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [togglingAuto, setTogglingAuto] = useState(false);
  const [details, setDetails] = useState(false);
  const [pausing, setPausing] = useState(false);
  const online = state.connected && backendOnline;
  const visible = (value: string | null) => (online ? value : null);
  const active = state.status === 'RUNNING';
  const safeStart = canStart(state, backendOnline, socketOnline);
  const block = online ? state.recovery[0] : undefined;
  const pause = async () => {
    if (pausing) return;
    setPausing(true);
    setError(null);
    try {
      await api.pause();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Pausa non confermata.');
    } finally {
      setPausing(false);
    }
  };
  const toggleAuto = async () => {
    setTogglingAuto(true);
    setError(null);
    try {
      await api.config({ ...state.config, auto_recovery: !state.config.auto_recovery });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Impostazione non salvata.');
    } finally {
      setTogglingAuto(false);
    }
  };
  const inject = async () => {
    if (!recovery) return;
    setRecovering(true);
    setError(null);
    try {
      await api.recovery(recovery.side);
      await refresh();
      setRecovery(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Recovery rifiutato.');
    } finally {
      setRecovering(false);
    }
  };
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">IL TUO CENTRO DI CONTROLLO</p>
          <h1>
            Una visione chiara. <span>Sempre.</span>
          </h1>
        </div>
        <div className="strategy-chip">
          <Layers3 size={15} />
          Grid Hedge Bidirezionale
        </div>
      </div>
      {error && <Alert onClose={() => setError(null)}>{error}</Alert>}
      <div className="home-layout">
        <PriceChart state={state} backendOnline={backendOnline} />
        <aside className="home-cards" aria-label="Riepilogo bot">
          <section className="glass portfolio-card">
            <div className="card-heading">
              <h2>
                <Wallet size={17} />
                Portafoglio
              </h2>
              <span className="subtle-badge">USDT</span>
            </div>
            <p className="metric-label">Equity account</p>
            <div className="equity-value">
              {amount(visible(state.portfolio.equity))}
              <span>USDT</span>
            </div>
            {!online && <p className="disconnected-label">NON CONNESSO</p>}
            <div className="portfolio-split">
              <div>
                <span>PnL oggi</span>
                <strong className={pnlClass(visible(state.portfolio.today))}>
                  {amount(visible(state.portfolio.today), 2, true)}
                </strong>
              </div>
              <div>
                <span>PnL totale bot</span>
                <strong className={pnlClass(visible(state.portfolio.net))}>
                  {amount(visible(state.portfolio.net), 2, true)}
                </strong>
              </div>
            </div>
            <button
              className="text-button"
              onClick={() => setDetails(!details)}
              aria-expanded={details}
            >
              {details ? 'Nascondi composizione' : 'Composizione PnL'}
            </button>
            {details && (
              <div className="pnl-details">
                <div>
                  <span>Realizzato</span>
                  <strong>{amount(visible(state.portfolio.realized), 2, true)}</strong>
                </div>
                <div>
                  <span>Non realizzato</span>
                  <strong>{amount(visible(state.portfolio.unrealized), 2, true)}</strong>
                </div>
                <div>
                  <span>Commissioni</span>
                  <strong>{amount(visible(state.portfolio.fees))}</strong>
                </div>
                {state.portfolio.funding !== undefined && (
                  <div>
                    <span>Funding</span>
                    <strong>{amount(visible(state.portfolio.funding), 2, true)}</strong>
                  </div>
                )}
                <div>
                  <span>Recovery</span>
                  <strong>{amount(visible(state.portfolio.recovery), 2, true)}</strong>
                </div>
                <p>PnL derivato dalle esecuzioni del bot. Equity riferita all’account.</p>
              </div>
            )}
          </section>
          <section className="glass bot-card">
            <div className="card-heading">
              <h2>
                <Layers3 size={17} />
                Stato bot
              </h2>
              <span className={`status-pill ${active ? 'running' : ''}`}>
                <i />
                {backendOnline ? STATUS_LABEL[state.status] : 'Offline'}
              </span>
            </div>
            <div className="strategy-summary">
              <strong>Grid Hedge</strong>
              <span>
                {state.config.levels} + {state.config.levels} livelli · {state.config.spacing_pct}%
                · TP {state.config.tp_pct}%
              </span>
            </div>
            <div className="exposure-lines">
              <div>
                <span>
                  <ArrowUpRight size={14} className="text-positive" />
                  Long exposure
                </span>
                <strong>
                  {amount(visible(exposure(state, 'LONG')))}
                  <small> USDT</small>
                </strong>
              </div>
              <div>
                <span>
                  <ArrowDownRight size={14} className="text-negative" />
                  Short exposure
                </span>
                <strong>
                  {amount(visible(exposure(state, 'SHORT')))}
                  <small> USDT</small>
                </strong>
              </div>
            </div>
            {active ? (
              <button
                className="button secondary full-width"
                onClick={() => void pause()}
                disabled={!backendOnline || busy || pausing}
              >
                <CirclePause size={18} />
                {pausing ? 'Pausa in corso…' : 'Pausa bot'}
              </button>
            ) : (
              <button
                className="button primary full-width"
                onClick={onStart}
                disabled={!safeStart || busy}
              >
                {busy ? <LoaderCircle size={17} className="spin" /> : <CirclePlay size={18} />}Avvia
                bot
              </button>
            )}
            {!safeStart && !active && (
              <p className="card-note">
                {!online ? (
                  <>
                    Collega Bybit in{' '}
                    <button className="text-button" onClick={onOpenSettings}>
                      Impostazioni
                    </button>
                    .
                  </>
                ) : state.environment === 'LIVE' && !state.mainnet_allowed ? (
                  'LIVE bloccato: abilita il safety flag backend.'
                ) : (
                  'In attesa di feed privato, feed mercato e riconciliazione.'
                )}
              </p>
            )}
            <button className="danger-link" onClick={onCloseAll} disabled={!online || busy}>
              <XCircle size={13} />
              Chiudi tutto
            </button>
          </section>
          <section className={`glass recovery-card ${block ? 'recovery-active' : ''}`}>
            <div className="card-heading">
              <h2>
                <Sparkles size={17} />
                Smart Recovery
              </h2>
              <span className={`subtle-badge ${state.config.auto_recovery ? 'text-blue' : ''}`}>
                AUTO {state.config.auto_recovery ? 'ON' : 'OFF'}
              </span>
            </div>
            {!block ? (
              <div className="recovery-idle">
                <ShieldCheck size={28} />
                <strong>{online ? 'RECOVERY NON NECESSARIO' : 'NON CONNESSO'}</strong>
                <p>
                  {online
                    ? 'Nessun blocco richiede un intervento.'
                    : 'Collega Bybit per analizzare le posizioni.'}
                </p>
              </div>
            ) : (
              <>
                <div className="recovery-side">
                  <span className="pulse-dot" />
                  <strong>{block.side} IN RECUPERO</strong>
                </div>
                <div className="recovery-metrics">
                  <div>
                    <span>Perdita non realizzata</span>
                    <strong className="text-negative">
                      {amount(block.unrealized_pnl, 2, true)} <small>USDT</small>
                    </strong>
                  </div>
                  <div>
                    <span>Prezzo medio</span>
                    <strong>{amount(block.average)}</strong>
                  </div>
                  <div>
                    <span>Injection consigliata</span>
                    <strong>
                      {amount(block.required_usdt)} <small>USDT</small>
                    </strong>
                  </div>
                  <div>
                    <span>Recovery TP</span>
                    <strong className="text-purple">{amount(block.tp)}</strong>
                  </div>
                </div>
                <div className="recovery-progress">
                  <span>Avanzamento al break-even</span>
                  <strong>
                    {block.progress === null ? 'In attesa' : `${amount(block.progress, 0)}%`}
                  </strong>
                  <div
                    role="progressbar"
                    aria-label="Avanzamento Recovery"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={
                      block.progress === null
                        ? undefined
                        : Math.max(0, Math.min(100, Number(block.progress)))
                    }
                  >
                    <i
                      style={{
                        width: `${block.progress === null ? 0 : Math.max(0, Math.min(100, Number(block.progress)))}%`,
                      }}
                    />
                  </div>
                </div>
                {!block.safe && (
                  <p className="recovery-unsafe">RECOVERY NON SICURO · {block.reason}</p>
                )}
                <button
                  className="button recovery-button full-width"
                  disabled={!block.safe || !active || !socketOnline || recovering}
                  onClick={() => setRecovery(block)}
                >
                  Valuta Injection
                </button>
              </>
            )}
            <label className="toggle-row compact">
              <span>Recovery automatico</span>
              <input
                role="switch"
                type="checkbox"
                aria-label="Recovery automatico"
                checked={state.config.auto_recovery}
                disabled={!backendOnline || togglingAuto}
                onChange={() => void toggleAuto()}
              />
            </label>
          </section>
        </aside>
      </div>
      <div className="pnl-strip">
        {[
          ['LONG PnL', state.portfolio.long, ArrowUpRight],
          ['SHORT PnL', state.portfolio.short, ArrowDownRight],
          ['GRID PnL', state.portfolio.grid, TrendingUp],
        ].map(([label, value, Icon]) => {
          const Component = Icon as typeof ArrowUpRight;
          const metric = visible(value as string | null);
          return (
            <section className="glass mini-pnl" key={String(label)}>
              <div>
                <Component size={18} />
                <span>{String(label)}</span>
              </div>
              <strong className={pnlClass(metric)}>
                {amount(metric, 2, true)}
                <small> USDT</small>
              </strong>
            </section>
          );
        })}
      </div>
      <p className="home-footnote">
        Pausa e chiusura dell’app fermano le nuove strategie. Le posizioni su Bybit restano aperte e
        i TP già inviati restano sull’exchange.
      </p>
      {recovery && (
        <Modal
          title={`Injection ${recovery.side}`}
          onClose={() => {
            if (!recovering) setRecovery(null);
          }}
          busy={recovering}
        >
          <p className="modal-description">
            Aggiungere capitale aumenta l’esposizione. Il backend ricalcola il piano con prezzi e
            limiti aggiornati prima di inviare l’ordine.
          </p>
          <div className="review-list">
            <div>
              <span>Injection stimata</span>
              <strong>{amount(recovery.required_usdt)} USDT</strong>
            </div>
            <div>
              <span>Nuovo prezzo medio</span>
              <strong>{amount(recovery.new_average)}</strong>
            </div>
            <div>
              <span>Break-even con costi</span>
              <strong>{amount(recovery.break_even)}</strong>
            </div>
            <div>
              <span>TP Recovery</span>
              <strong>{amount(recovery.tp)}</strong>
            </div>
          </div>
          {error && <Alert>{error}</Alert>}
          <div className="modal-actions">
            <button
              className="button secondary"
              onClick={() => setRecovery(null)}
              disabled={recovering}
            >
              Annulla
            </button>
            <button
              className="button primary"
              onClick={() => void inject()}
              disabled={recovering || !recovery.safe}
            >
              {recovering ? 'Verifica rischio…' : 'Conferma Injection'}
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
