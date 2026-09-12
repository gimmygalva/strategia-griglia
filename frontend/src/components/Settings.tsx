import { useEffect, useRef, useState } from 'react';
import {
  Cable,
  ChevronRight,
  CircleHelp,
  Layers3,
  LoaderCircle,
  Monitor,
  Save,
  Shield,
  Sparkles,
} from 'lucide-react';
import { api } from '../lib/api';
import type { BotState } from '../lib/types';
import { ConnectionForm } from './ConnectionForm';
import { ConfigFields, parseConfig, toDraft } from './ConfigFields';
import type { ConfigGroup } from './ConfigFields';
import { Alert } from './Alert';

const SECTIONS = [
  { key: 'connection', label: 'Connessione', icon: Cable },
  { key: 'grid', label: 'Grid', icon: Layers3 },
  { key: 'recovery', label: 'Recovery', icon: Sparkles },
  { key: 'risk', label: 'Rischio', icon: Shield },
  { key: 'app', label: 'App', icon: Monitor },
];
const TITLES: Record<string, string> = {
  connection: 'Il tuo account Bybit.',
  grid: 'Una Grid, due direzioni.',
  recovery: 'Recupero con limiti chiari.',
  risk: 'Il controllo prima di tutto.',
  app: 'La tua app, in locale.',
};

export function Settings({
  state,
  backendOnline,
  refresh,
  onWizard,
}: {
  state: BotState;
  backendOnline: boolean;
  refresh: () => Promise<void>;
  onWizard: () => void;
}) {
  const [section, setSection] = useState('connection');
  const [draft, setDraft] = useState(toDraft(state.config));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const dirty = useRef(false);
  useEffect(() => {
    if (!dirty.current) setDraft(toDraft(state.config));
  }, [state.config]);
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setSuccess(false);
    const parsed = parseConfig(draft);
    if (!parsed.config) {
      setError(parsed.error);
      return;
    }
    setBusy(true);
    try {
      await api.config(parsed.config);
      dirty.current = false;
      await refresh();
      setSuccess(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Impostazioni non salvate.');
    } finally {
      setBusy(false);
    }
  };
  const chooseSection = (key: string) => {
    setSection(key);
    setError(null);
    setSuccess(false);
  };
  const changeDraft = (next: typeof draft) => {
    dirty.current = true;
    setDraft(next);
    setSuccess(false);
  };
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">TUTTO SOTTO CONTROLLO</p>
          <h1>
            Le tue <span>impostazioni.</span>
          </h1>
        </div>
        <button
          className="button secondary"
          onClick={onWizard}
          disabled={state.status === 'RUNNING'}
        >
          <CircleHelp size={16} />
          Configurazione guidata
        </button>
      </div>
      <div className="settings-layout">
        <aside className="glass settings-nav" aria-label="Sezioni impostazioni">
          {SECTIONS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              className={section === key ? 'active' : ''}
              onClick={() => chooseSection(key)}
              aria-current={section === key ? 'page' : undefined}
            >
              <Icon size={18} />
              {label}
              <ChevronRight size={14} />
            </button>
          ))}
        </aside>
        <section className="glass settings-content">
          <div className="settings-heading">
            <p className="eyebrow">{SECTIONS.find((entry) => entry.key === section)?.label}</p>
            <h2>{TITLES[section]}</h2>
          </div>
          {!backendOnline && (
            <Alert>Backend non disponibile. Le modifiche non possono essere salvate.</Alert>
          )}
          {section === 'connection' ? (
            <ConnectionForm state={state} onConnected={refresh} />
          ) : section === 'app' ? (
            <div className="app-settings">
              <div className="app-version">
                <img src="/icon.svg" alt="Icona Grid Hedge Bot" />
                <div>
                  <strong>Grid Hedge Bot</strong>
                  <span>Versione 0.1.0 · dati locali</span>
                </div>
              </div>
              <div className="review-list">
                <div>
                  <span>Database, log e impostazioni</span>
                  <strong>Application Support / Grid Hedge Bot</strong>
                </div>
                <div>
                  <span>Credenziali macOS</span>
                  <strong>Keychain</strong>
                </div>
                <div>
                  <span>Ambiente attivo</span>
                  <strong className={state.environment === 'LIVE' ? 'text-negative' : 'text-blue'}>
                    {state.environment}
                  </strong>
                </div>
                <div>
                  <span>Trading Mainnet</span>
                  <strong>
                    {state.mainnet_allowed ? 'Abilitabile con conferma' : 'Bloccato dal backend'}
                  </strong>
                </div>
              </div>
              <p className="field-note">
                Alla riapertura il bot riconcilia lo stato con Bybit e rimane in pausa fino al tuo
                avvio. Il database e le credenziali vengono mantenuti durante gli aggiornamenti.
              </p>
            </div>
          ) : (
            <form onSubmit={(event) => void save(event)}>
              {error && <Alert>{error}</Alert>}
              {success && <Alert positive>Impostazioni salvate e validate dal backend.</Alert>}
              {state.status === 'RUNNING' && section !== 'recovery' && (
                <Alert>Metti in pausa il bot per modificare i parametri della strategia.</Alert>
              )}
              <ConfigFields
                group={section as ConfigGroup}
                draft={draft}
                onChange={changeDraft}
                disabled={
                  busy || !backendOnline || (state.status === 'RUNNING' && section !== 'recovery')
                }
              />
              <div className="settings-save">
                <button
                  className="button primary"
                  type="submit"
                  disabled={
                    busy || !backendOnline || (state.status === 'RUNNING' && section !== 'recovery')
                  }
                >
                  {busy ? <LoaderCircle size={16} className="spin" /> : <Save size={16} />}
                  {busy ? 'Validazione in corso…' : 'Salva impostazioni'}
                </button>
              </div>
            </form>
          )}
        </section>
      </div>
    </>
  );
}
