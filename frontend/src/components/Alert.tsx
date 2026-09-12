import { AlertTriangle, CheckCircle2, X } from 'lucide-react';

export function Alert({
  children,
  positive = false,
  onClose,
}: {
  children: React.ReactNode;
  positive?: boolean;
  onClose?: () => void;
}) {
  return (
    <div
      className={`alert ${positive ? 'alert-positive' : ''}`}
      role={positive ? 'status' : 'alert'}
    >
      {positive ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}
      <span>{children}</span>
      {onClose && (
        <button className="icon-button" aria-label="Chiudi avviso" onClick={onClose}>
          <X size={16} />
        </button>
      )}
    </div>
  );
}
