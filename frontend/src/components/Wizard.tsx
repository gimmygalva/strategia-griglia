import { useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  Cable,
  Check,
  CirclePlay,
  LoaderCircle,
  ShieldCheck,
  X,
} from 'lucide-react';
import { api } from '../lib/api';
import type { BotState, Environment } from '../lib/types';
import { Brand } from './Brand';
import { Alert } from './Alert';
import { AccountChecks, ConnectionForm, EnvironmentPicker } from './ConnectionForm';
import { ConfigFields, parseConfig, toDraft } from './ConfigFields';
import { canStart } from './Home';

const STEPS = [
  'Benvenuto',
  'Ambiente',
  'Credenziali',
  'Connessione',
  'Account',
  'Grid',
  'Recovery',
  'Rischio',
  'Riepilogo',
  'Avvio',
];
const TITLES = [
  'Il tuo bot. Il tuo controllo.',
  'Scegli dove operare.',
  'Collega il tuo account.',
  'Verifichiamo Bybit.',
  'Tutto deve essere compatibile.',
  'Imposta la tua Grid.',
  'Definisci il Recovery.',
  'Imposta i tuoi limiti.',
  'Controlla ogni scelta.',
  'Pronto per il primo avvio.',
];

export function Wizard({
  state,
  backendOnline,
  socketOnline,
  refresh,
  onClose,
  onStart,
}: {
  state: BotState;
  backendOnline: boolean;
  socketOnline: boolean;
  refresh: () => Promise<void>;
  onClose: () => void;
  onStart: () => void;
}) {
  const [step, setStep] = useState(0);
  const [env, setEnv] = useState<Environment>('DEMO');
  const [saved, setSaved] = useState(false);
  const [verified, setVerified] = useState(false);
  const [draft, setDraft] = useState(toDraft(state.config));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const root = useRef<HTMLElement>(null);
  useEffect(() => {
    root.current
      ?.querySelector<HTMLElement>(
        '.wizard-body input, .wizard-body button, .wizard-bottom .primary',
      )
      ?.focus();
  }, [step]);
  const compatible =
    state.environment === env &&
    state.connected &&
    !!state.account?.permissions &&
    !!state.account?.hedge_mode &&
    (state.account?.uta_status ?? 0) >= 3;
  const canContinue =
    step === 2 ? saved : step === 3 ? verified && compatible : step === 4 ? compatible : true;
  const changeEnv = (value: Environment) => {
    setEnv(value);
    setSaved(false);
    setVerified(false);
  };
  const testConnection = async () => {
    setBusy(true);
    setError(null);
    setVerified(false);
    try {
      await api.connect(env);
      await refresh();
      setVerified(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Connessione non riuscita.');
    } finally {
      setBusy(false);
    }
  };
  const next = () => {
    setError(null);
    if (step >= 5 && step <= 7) {
      const parsed = parseConfig(draft);
      if (!parsed.config) {
        setError(parsed.error);
        return;
      }
    }
    if (canContinue) setStep((old) => Math.min(9, old + 1));
  };
  const complete = async (start: boolean) => {
    const parsed = parseConfig(draft);
    if (!parsed.config) {
      setError(parsed.error);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.config(parsed.config);
      await api.wizard();
      await refresh();
      onClose();
      if (start) onStart();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Configurazione non salvata.');
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="wizard-backdrop">
      <section
        className="wizard"
        role="dialog"
        aria-modal="true"
        aria-label="Configurazione guidata"
        ref={root}
      >
        <aside className="wizard-sidebar">
          <Brand />
          <p>
            Configura una strategia chiara.
            <br />
            Mantieni il controllo sul rischio.
          </p>
          <ol>
            {STEPS.map((name, index) => (
              <li
                key={name}
                className={`${index === step ? 'current' : ''} ${index < step ? 'complete' : ''}`}
              >
                <span>{index < step ? <Check size={13} /> : index + 1}</span>
                {name}
              </li>
            ))}
          </ol>
          <div className={`wizard-env ${env === 'LIVE' ? 'live' : ''}`}>
            <span className={`env-dot ${env.toLowerCase()}`} />
            {env} {env === 'DEMO' ? '· Bybit Demo Trading' : '· Fondi reali'}
          </div>
        </aside>
        <div className="wizard-main">
          <div className="wizard-top">
            <span>STEP {step + 1} DI 10</span>
            <button
              className="icon-button"
              aria-label="Chiudi configurazione guidata"
              onClick={onClose}
              disabled={busy}
            >
              <X size={20} />
            </button>
          </div>
          <div className="wizard-mobile-progress">
            <i style={{ width: `${(step + 1) * 10}%` }} />
          </div>
          <div className="wizard-body">
            <p className="eyebrow">{STEPS[step]}</p>
            <h1>{TITLES[step]}</h1>
            {error && <Alert>{error}</Alert>}
            {step === 0 && (
              <div className="welcome-content">
                <div className="welcome-symbol">
                  <ShieldCheck size={38} />
                </div>
                <p>
                  Grid Hedge apre Long e Short separati, protegge gli ordini con limiti di rischio e
                  ricostruisce lo stato dopo un riavvio.
                </p>
                <div className="welcome-features">
                  <span>
                    <Check size={16} />
                    Demo Bybit ufficiale
                  </span>
                  <span>
                    <Check size={16} />
                    Credenziali nel portachiavi
                  </span>
                  <span>
                    <Check size={16} />
                    LIVE bloccato per default
                  </span>
                </div>
                <p className="field-note">
                  Il Recovery aggiunge capitale a posizioni in perdita. Non garantisce un recupero e
                  deve rispettare tutti i tuoi limiti.
                </p>
              </div>
            )}
            {step === 1 && (
              <>
                <p className="wizard-description">
                  Parti da DEMO per verificare connessione e comportamento con fondi virtuali
                  sull’ambiente ufficiale Bybit.
                </p>
                <EnvironmentPicker value={env} onChange={changeEnv} />
                {env === 'LIVE' && (
                  <Alert>
                    LIVE usa fondi reali. Nessun ordine sarà inviato senza flag backend, conferma
                    esplicita e controlli di rischio.
                  </Alert>
                )}
                <p className="field-note">
                  Demo Trading è diverso da Testnet. Il feed di mercato pubblico è quello Mainnet in
                  entrambi gli ambienti.
                </p>
              </>
            )}
            {step === 2 && (
              <>
                <p className="wizard-description">
                  Usa API create nell’ambiente <strong>{env}</strong>. Il Secret non sarà più
                  leggibile dopo il salvataggio.
                </p>
                <ConnectionForm
                  state={state}
                  environment={env}
                  showPicker={false}
                  credentialsOnly
                  onConnected={refresh}
                  onSaved={() => setSaved(true)}
                />
                {!saved && state.environment === env && state.account && (
                  <button className="text-button" onClick={() => setSaved(true)}>
                    Usa le credenziali già salvate e verificate
                  </button>
                )}
              </>
            )}
            {step === 3 && (
              <>
                <p className="wizard-description">
                  Leggiamo saldo, strumento, permessi, UTA e configurazione Hedge Mode. Questo test
                  non invia ordini.
                </p>
                <button
                  className="button primary"
                  onClick={() => void testConnection()}
                  disabled={busy || !backendOnline}
                >
                  {busy ? <LoaderCircle size={18} className="spin" /> : <Cable size={18} />}
                  {busy ? 'Connessione in corso…' : 'Test Connessione'}
                </button>
                {verified && compatible && (
                  <Alert positive>Connected · account Bybit verificato</Alert>
                )}
                <div className="feed-checks">
                  <span className={state.public_connected ? 'text-positive' : 'text-muted'}>
                    Feed mercato {state.public_connected ? 'connesso' : 'in attesa'}
                  </span>
                  <span className={state.private_connected ? 'text-positive' : 'text-muted'}>
                    Feed privato {state.private_connected ? 'connesso' : 'in attesa'}
                  </span>
                </div>
              </>
            )}
            {step === 4 && (
              <>
                <p className="wizard-description">
                  Il bot richiede un Unified Trading Account, permessi di trading e Long + Short
                  simultanei.
                </p>
                <AccountChecks account={state.environment === env ? state.account : null} />
                {compatible && <Alert positive>Configurazione account compatibile.</Alert>}
              </>
            )}
            {step === 5 && <ConfigFields group="grid" draft={draft} onChange={setDraft} />}
            {step === 6 && <ConfigFields group="recovery" draft={draft} onChange={setDraft} />}
            {step === 7 && <ConfigFields group="risk" draft={draft} onChange={setDraft} />}
            {step === 8 && (
              <div className="review-list">
                <div>
                  <span>Ambiente</span>
                  <strong className={env === 'LIVE' ? 'text-negative' : 'text-blue'}>{env}</strong>
                </div>
                <div>
                  <span>Simbolo / leva</span>
                  <strong>BTCUSDT / {draft.leverage}×</strong>
                </div>
                <div>
                  <span>Importo per ordine</span>
                  <strong>{draft.order_size_usdt} USDT</strong>
                </div>
                <div>
                  <span>Livelli / spacing / TP</span>
                  <strong>
                    {draft.levels} + {draft.levels} / {draft.spacing_pct}% / {draft.tp_pct}%
                  </strong>
                </div>
                <div>
                  <span>Coppia iniziale a mercato</span>
                  <strong>{draft.initial_pair ? 'Sì · Long + Short' : 'No'}</strong>
                </div>
                <div>
                  <span>Recovery automatico</span>
                  <strong>{draft.auto_recovery ? 'ON' : 'OFF'}</strong>
                </div>
                <div>
                  <span>Injection massima</span>
                  <strong>{draft.max_injection_usdt} USDT</strong>
                </div>
                <div>
                  <span>Esposizione massima</span>
                  <strong>{draft.max_exposure_usdt} USDT</strong>
                </div>
                <div>
                  <span>Perdita giornaliera massima</span>
                  <strong>{draft.max_daily_loss_usdt} USDT</strong>
                </div>
              </div>
            )}
            {step === 9 && (
              <>
                <div className="welcome-symbol">
                  <CirclePlay size={40} />
                </div>
                <p className="wizard-description">
                  L’avvio esegue nuovamente i controlli, salva la Grid e attiva la strategia. Se hai
                  scelto la coppia iniziale, verranno aperti un Long e uno Short a mercato.
                </p>
                {!canStart(state, backendOnline, socketOnline) && (
                  <Alert>
                    {env === 'LIVE' && !state.mainnet_allowed
                      ? 'LIVE bloccato dal backend. Puoi salvare la configurazione e abilitarlo successivamente.'
                      : 'Feed o riconciliazione non pronti. Puoi salvare la configurazione e avviare dalla Home quando tutti i controlli saranno verdi.'}
                  </Alert>
                )}
                <button
                  className="button primary full-width"
                  onClick={() => void complete(true)}
                  disabled={busy || !canStart(state, backendOnline, socketOnline)}
                >
                  <CirclePlay size={18} />
                  {env === 'LIVE' ? 'Procedi alla conferma LIVE' : 'Salva e avvia bot DEMO'}
                </button>
                <button
                  className="text-button wizard-save-only"
                  onClick={() => void complete(false)}
                  disabled={busy || !backendOnline}
                >
                  Salva configurazione e avvia più tardi
                </button>
              </>
            )}
          </div>
          <div className="wizard-bottom">
            <button
              className="button secondary"
              onClick={() => {
                setStep((old) => Math.max(0, old - 1));
                setError(null);
              }}
              disabled={step === 0 || busy}
            >
              <ArrowLeft size={16} />
              Indietro
            </button>
            {step < 9 ? (
              <button className="button primary" onClick={next} disabled={!canContinue || busy}>
                {step === 0 ? 'Cominciamo' : 'Continua'}
                <ArrowRight size={16} />
              </button>
            ) : (
              <span className="wizard-safe-note">
                <ShieldCheck size={14} />
                Ogni ordine passa dal Risk Engine
              </span>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
