import { useState } from 'react';
import { ShieldAlert } from 'lucide-react';
import { Modal } from './Modal';
import { Alert } from './Alert';

export function ConfirmDialog({
  kind,
  onConfirm,
  onClose,
}: {
  kind: 'live' | 'close';
  onConfirm: () => Promise<void>;
  onClose: () => void;
}) {
  const [step, setStep] = useState(1);
  const [ack, setAck] = useState(false);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const live = kind === 'live';
  const phrase = live ? 'AVVIA LIVE' : 'CHIUDI TUTTO';
  const submit = async () => {
    if (!ack || text !== phrase) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Operazione rifiutata.');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title={live ? 'Attivare il trading LIVE?' : 'Chiudere tutte le posizioni?'}
      onClose={onClose}
      busy={busy}
    >
      <div className="danger-symbol">
        <ShieldAlert size={30} />
      </div>
      <p className="modal-description">
        {live
          ? 'LIVE invia ordini su Bybit Mainnet e utilizza denaro reale. Grid e Recovery possono accumulare perdite.'
          : 'Il bot verrà fermato. Gli ordini del bot saranno cancellati e le posizioni del simbolo corrente saranno chiuse a mercato, con commissioni e possibile slippage.'}
      </p>
      {error && <Alert>{error}</Alert>}
      {step === 1 ? (
        <>
          <label className="check-row">
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
            <span>
              {live
                ? 'Comprendo che userò fondi reali e accetto i limiti di rischio configurati.'
                : 'Comprendo che la chiusura realizzerà i profitti o le perdite delle posizioni.'}
            </span>
          </label>
          <div className="modal-actions">
            <button className="button secondary" onClick={onClose}>
              Annulla
            </button>
            <button className="button danger" disabled={!ack} onClick={() => setStep(2)}>
              Continua
            </button>
          </div>
        </>
      ) : (
        <>
          <label className="field">
            <span>
              Per confermare, scrivi <strong>{phrase}</strong>
            </span>
            <input
              autoComplete="off"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={phrase}
              disabled={busy}
              autoFocus
            />
          </label>
          <div className="modal-actions">
            <button className="button secondary" onClick={onClose} disabled={busy}>
              Annulla
            </button>
            <button
              className="button danger"
              disabled={text !== phrase || !ack || busy}
              onClick={() => void submit()}
            >
              {busy ? 'Verifica in corso…' : live ? 'Avvia con fondi reali' : 'Conferma chiusura'}
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}
