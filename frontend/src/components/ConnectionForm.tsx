import { useState } from 'react';
import { Cable, Check, LoaderCircle, ShieldCheck } from 'lucide-react';
import { api, ApiError } from '../lib/api';
import type { AccountInfo, BotState, Environment } from '../lib/types';
import { amount } from '../lib/format';
import { Alert } from './Alert';

const CONNECTION_STATUS: Record<string, string> = {
  AUTHENTICATION_ERROR: 'Authentication Failed',
  AUTHENTICATION_FAILED: 'Authentication Failed',
  PERMISSION_MISSING: 'Permission Missing',
  PERMISSION_ERROR: 'Permission Missing',
  NETWORK_ERROR: 'Network Error',
  ACCOUNT_TYPE_ERROR: 'Account Type Error',
  HEDGE_MODE_ERROR: 'Hedge Mode Error',
};

export function EnvironmentPicker({
  value,
  onChange,
  disabled = false,
}: {
  value: Environment;
  onChange: (env: Environment) => void;
  disabled?: boolean;
}) {
  return (
    <div className="environment-picker" role="group" aria-label="Ambiente Bybit">
      <button
        type="button"
        aria-pressed={value === 'DEMO'}
        className={value === 'DEMO' ? 'selected' : ''}
        onClick={() => onChange('DEMO')}
        disabled={disabled}
      >
        <span className="env-dot demo" />
        DEMO<small>Bybit Demo Trading</small>
      </button>
      <button
        type="button"
        aria-pressed={value === 'LIVE'}
        className={value === 'LIVE' ? 'selected live-selected' : ''}
        onClick={() => onChange('LIVE')}
        disabled={disabled}
      >
        <span className="env-dot live" />
        LIVE<small>Fondi reali</small>
      </button>
    </div>
  );
}

export function AccountChecks({ account }: { account: AccountInfo | null }) {
  if (!account)
    return (
      <div className="empty-inline">
        <ShieldCheck size={20} />
        <span>Testa la connessione per verificare account, UTA e Hedge Mode.</span>
      </div>
    );
  return (
    <div className="account-checks">
      <div>
        <span>UID</span>
        <strong>{account.uid}</strong>
      </div>
      <div>
        <span>Account</span>
        <strong>{account.account_type}</strong>
      </div>
      <div>
        <span>UTA</span>
        <strong className={account.uta_status >= 3 ? 'text-positive' : 'text-negative'}>
          {account.uta_status >= 3 ? 'Verificato' : 'Non compatibile'}{' '}
          <small>({account.uta_status})</small>
        </strong>
      </div>
      <div>
        <span>Hedge Mode</span>
        <strong className={account.hedge_mode ? 'text-positive' : 'text-negative'}>
          {account.hedge_mode ? 'Attivo · Long + Short' : 'Non attivo'}
        </strong>
      </div>
      <div>
        <span>Permessi trading</span>
        <strong className={account.permissions ? 'text-positive' : 'text-negative'}>
          {account.permissions ? 'Verificati' : 'Mancanti'}
        </strong>
      </div>
      <div>
        <span>Saldo disponibile</span>
        <strong>
          {amount(account.available_balance)} <small>USDT</small>
        </strong>
      </div>
      <div>
        <span>Leva Long / Short</span>
        <strong>
          {account.leverage_long}× / {account.leverage_short}×
        </strong>
      </div>
      {account.fee_source && (
        <div className="full-width">
          <span>Commissioni</span>
          <strong>{account.fee_source}</strong>
        </div>
      )}
    </div>
  );
}

export function ConnectionForm({
  state,
  onConnected,
  environment: externalEnv,
  setEnvironment: externalSet,
  showPicker = true,
  credentialsOnly = false,
  onSaved,
}: {
  state: BotState;
  onConnected: () => Promise<void>;
  environment?: Environment;
  setEnvironment?: (env: Environment) => void;
  showPicker?: boolean;
  credentialsOnly?: boolean;
  onSaved?: () => void;
}) {
  const [localEnv, setLocalEnv] = useState<Environment>(state.environment);
  const environment = externalEnv ?? localEnv;
  const [key, setKey] = useState('');
  const [secret, setSecret] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const running = state.status === 'RUNNING';
  const setEnvironment = (env: Environment) => {
    (externalSet ?? setLocalEnv)(env);
    setKey('');
    setSecret('');
    setResult(null);
    setError(null);
  };
  const test = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setResult(null);
    if (!!key.trim() !== !!secret.trim()) {
      setError('Inserisci sia API Key sia API Secret.');
      return;
    }
    if (credentialsOnly && !key.trim()) {
      setError('Inserisci API Key e API Secret prima di salvarli.');
      return;
    }
    if ((key && key.trim().length < 8) || (secret && secret.trim().length < 8)) {
      setError('API Key e API Secret non validi. Controlla le credenziali.');
      return;
    }
    setBusy(true);
    try {
      if (key.trim() && secret.trim()) {
        await api.credentials(environment, key.trim(), secret.trim());
        setKey('');
        setSecret('');
        onSaved?.();
      }
      if (credentialsOnly) {
        setResult('Credenziali salvate');
        return;
      }
      await api.connect(environment);
      await onConnected();
      setResult('Connected');
    } catch (err) {
      const status = err instanceof ApiError ? CONNECTION_STATUS[err.code] : undefined;
      setError(
        `${status ? `${status}: ` : ''}${err instanceof Error ? err.message : 'Connessione non riuscita.'}`,
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={(event) => void test(event)} className="connection-form">
      {showPicker && (
        <EnvironmentPicker
          value={environment}
          onChange={setEnvironment}
          disabled={running || busy}
        />
      )}
      {environment === 'LIVE' && (
        <Alert>
          LIVE utilizza fondi reali. Il trading richiede l’abilitazione backend e una doppia
          conferma.
        </Alert>
      )}
      <div className="endpoint-info">
        <Cable size={15} />
        <span>
          {environment === 'DEMO'
            ? 'api-demo.bybit.com · Demo ufficiale, diverso da Testnet'
            : 'api.bybit.com · Mainnet'}
        </span>
      </div>
      <div className="form-grid">
        <label className="field">
          <span>API Key</span>
          <input
            type="password"
            name="api_key"
            autoComplete="off"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="Inserisci API Key"
            disabled={busy || running}
            spellCheck={false}
          />
        </label>
        <label className="field">
          <span>API Secret</span>
          <input
            type="password"
            name="api_secret"
            autoComplete="new-password"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            placeholder="Inserisci API Secret"
            disabled={busy || running}
            spellCheck={false}
          />
        </label>
      </div>
      <p className="field-note">
        Le credenziali vengono salvate nel portachiavi di macOS. Lascia i campi vuoti per usare
        quelle già salvate.
      </p>
      {error && <Alert>{error}</Alert>}
      {result && (
        <Alert positive>
          <Check size={15} />
          {result}
          {!credentialsOnly && ' · account verificato'}
        </Alert>
      )}
      <button className="button primary" type="submit" disabled={busy || running}>
        {busy ? <LoaderCircle size={17} className="spin" /> : <Cable size={17} />}
        {busy
          ? credentialsOnly
            ? 'Salvataggio in corso…'
            : 'Verifica Bybit in corso…'
          : credentialsOnly
            ? 'Salva credenziali'
            : 'Test Connessione'}
      </button>
      {running && (
        <p className="field-note">Metti in pausa il bot prima di modificare la connessione.</p>
      )}
      {!credentialsOnly && state.environment === environment && (
        <AccountChecks account={state.connected ? state.account : null} />
      )}
    </form>
  );
}
