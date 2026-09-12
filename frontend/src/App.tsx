import { useEffect, useRef, useState } from 'react';
import {
  Activity as ActivityIcon,
  CirclePause,
  Home as HomeIcon,
  LoaderCircle,
  Radio,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { useBot } from './lib/useBot';
import { api } from './lib/api';
import { STATUS_LABEL } from './lib/types';
import { Brand } from './components/Brand';
import { Alert } from './components/Alert';
import { Home } from './components/Home';
import { Activity } from './components/Activity';
import { Settings } from './components/Settings';
import { Wizard } from './components/Wizard';
import { ConfirmDialog } from './components/ConfirmDialog';

const NAVIGATION = [
  { key: 'home', name: 'Home', icon: HomeIcon },
  { key: 'activity', name: 'Attività', icon: ActivityIcon },
  { key: 'settings', name: 'Impostazioni', icon: Settings2 },
];

export function App() {
  const {
    state,
    events,
    loading,
    error: backendError,
    backendOnline,
    socketOnline,
    refresh,
  } = useBot();
  const [page, setPage] = useState('home');
  const [wizard, setWizard] = useState(false);
  const [confirmation, setConfirmation] = useState<'live' | 'close' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const firstWizard = useRef(false);

  useEffect(() => {
    if (!loading && backendOnline && !firstWizard.current) {
      firstWizard.current = true;
      if (!state.wizard_completed) setWizard(true);
    }
  }, [loading, backendOnline, state.wizard_completed]);

  const start = async (live = false) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.start(live);
      await refresh();
      setNotice('Avvio confermato dal backend. Le esecuzioni vengono confermate da Bybit.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Avvio non confermato.');
      if (live) throw err;
    } finally {
      setBusy(false);
    }
  };
  const requestStart = () => {
    if (state.environment === 'LIVE') setConfirmation('live');
    else void start();
  };
  const pause = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.pause();
      await refresh();
      setNotice('Bot in pausa. Le posizioni rimangono su Bybit.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Pausa non confermata.');
    } finally {
      setBusy(false);
    }
  };
  const closeAll = async () => {
    await api.closeAll();
    await refresh();
    setNotice('Richiesta di chiusura inviata. Verifica gli aggiornamenti Bybit in Attività.');
  };
  const connected =
    backendOnline &&
    socketOnline &&
    state.connected &&
    state.public_connected &&
    state.private_connected;
  const alert = error ?? backendError ?? (backendOnline ? state.error : null);

  return (
    <div className="app-shell">
      <header className="topbar" inert={wizard || !!confirmation}>
        <Brand />
        <nav aria-label="Navigazione principale">
          {NAVIGATION.map(({ key, name, icon: Icon }) => (
            <button
              key={key}
              className={page === key ? 'active' : ''}
              aria-current={page === key ? 'page' : undefined}
              onClick={() => setPage(key)}
            >
              <Icon size={17} />
              {name}
            </button>
          ))}
        </nav>
        <div className="topbar-actions">
          <span className={`environment-badge ${state.environment.toLowerCase()}`}>
            <span className={`env-dot ${state.environment.toLowerCase()}`} />
            {state.environment}
          </span>
          {state.status === 'RUNNING' && (
            <button
              className="button stop-button"
              onClick={() => void pause()}
              disabled={busy || !backendOnline}
            >
              <CirclePause size={16} />
              Stop bot
            </button>
          )}
        </div>
      </header>
      <main className="main-content" inert={wizard || !!confirmation}>
        {loading ? (
          <div className="loading-screen">
            <LoaderCircle size={30} className="spin" />
            <h1>Connessione al backend locale…</h1>
            <p>Attendi la verifica di salute prima di operare.</p>
          </div>
        ) : (
          <>
            {!backendOnline && (
              <div className="backend-banner" role="status">
                <WifiOff size={19} />
                <div>
                  <strong>Backend non raggiungibile</strong>
                  <span>
                    I comandi di trading sono disabilitati. La riapertura richiede la
                    riconciliazione.
                  </span>
                </div>
                <button className="button secondary" onClick={() => void refresh()}>
                  <RefreshCw size={14} />
                  Riprova
                </button>
              </div>
            )}
            {backendOnline && !socketOnline && (
              <Alert>
                Realtime locale interrotto. L’avvio rimane bloccato fino al ripristino degli
                aggiornamenti.
              </Alert>
            )}
            {alert && <Alert onClose={error ? () => setError(null) : undefined}>{alert}</Alert>}
            {notice && (
              <Alert positive onClose={() => setNotice(null)}>
                {notice}
              </Alert>
            )}
            {page === 'home' && (
              <Home
                state={state}
                backendOnline={backendOnline}
                socketOnline={socketOnline}
                refresh={refresh}
                onStart={requestStart}
                onCloseAll={() => setConfirmation('close')}
                onOpenSettings={() => setPage('settings')}
                busy={busy}
              />
            )}
            {page === 'activity' && <Activity events={events} orders={state.orders ?? []} />}
            {page === 'settings' && (
              <Settings
                state={state}
                backendOnline={backendOnline}
                refresh={refresh}
                onWizard={() => setWizard(true)}
              />
            )}
          </>
        )}
      </main>
      <footer className="statusbar" aria-label="Stato connessione" inert={wizard || !!confirmation}>
        <div>
          <span className={`status-env ${state.environment.toLowerCase()}`}>
            {state.environment}
          </span>
          <span className={connected ? 'text-positive' : 'text-muted'}>
            {connected ? <Wifi size={12} /> : <WifiOff size={12} />}
            {connected ? 'Connected' : 'Disconnected'}
          </span>
          <span>
            <i
              className={`tiny-dot ${state.status === 'RUNNING' && backendOnline ? 'green' : ''}`}
            />
            {backendOnline ? STATUS_LABEL[state.status] : 'Bot non disponibile'}
          </span>
        </div>
        <div>
          <span>
            <Radio size={12} />
            API{' '}
            {backendOnline && state.latency_ms !== null
              ? `${Math.round(state.latency_ms)} ms`
              : '—'}
          </span>
          <span className="status-safe">
            <ShieldCheck size={12} />
            {state.environment === 'DEMO' ? 'Demo Trading ufficiale' : 'Mainnet · fondi reali'}
          </span>
        </div>
      </footer>
      {wizard && (
        <Wizard
          state={state}
          backendOnline={backendOnline}
          socketOnline={socketOnline}
          refresh={refresh}
          onClose={() => setWizard(false)}
          onStart={requestStart}
        />
      )}
      {confirmation && (
        <ConfirmDialog
          kind={confirmation}
          onClose={() => setConfirmation(null)}
          onConfirm={confirmation === 'live' ? () => start(true) : closeAll}
        />
      )}
    </div>
  );
}
