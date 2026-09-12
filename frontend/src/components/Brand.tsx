export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className="brand">
      <span className="brand-mark" aria-hidden="true">
        <img src="/icon.svg" alt="" />
      </span>
      {!compact && (
        <span>
          <strong>GRID HEDGE</strong>
          <small>BOT</small>
        </span>
      )}
    </div>
  );
}
