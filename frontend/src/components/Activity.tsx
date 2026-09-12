import { useState } from 'react';
import {
  Activity as ActivityIcon,
  CheckCheck,
  ChevronDown,
  ChevronUp,
  Clock3,
  Code2,
  ListFilter,
} from 'lucide-react';
import type { BotOrder, StrategyEvent } from '../lib/types';
import { dateLabel, timeLabel } from '../lib/format';

function safeDetails(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(safeDetails);
  if (value && typeof value === 'object')
    return Object.fromEntries(
      Object.entries(value)
        .filter(([key]) => !/secret|api_key|token|authorization/i.test(key))
        .map(([key, entry]) => [key, safeDetails(entry)]),
    );
  return value;
}

function EventRow({ event, technical }: { event: StrategyEvent; technical: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const positive = /CLOSED|TP|COMPLETED|CONNECTED/i.test(event.event);
  return (
    <article className="timeline-row">
      <div className="timeline-time">
        <strong>{timeLabel(event.time)}</strong>
        <small>{dateLabel(event.time)}</small>
      </div>
      <div className={`timeline-marker ${positive ? 'positive' : ''}`}>
        {positive ? <CheckCheck size={15} /> : <ActivityIcon size={15} />}
      </div>
      <div className="timeline-content">
        <h3>{event.title}</h3>
        <span>{event.event.replaceAll('_', ' ').toLowerCase()}</span>
        {technical && (
          <>
            <button
              className="text-button"
              onClick={() => setExpanded(!expanded)}
              aria-expanded={expanded}
            >
              {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}Dettagli evento
            </button>
            {expanded && (
              <pre className="technical-json">
                {JSON.stringify(safeDetails(event.details), null, 2)}
              </pre>
            )}
          </>
        )}
      </div>
    </article>
  );
}

export function Activity({ events, orders }: { events: StrategyEvent[]; orders: BotOrder[] }) {
  const [technical, setTechnical] = useState(false);
  const [filter, setFilter] = useState('ALL');
  const shown = events.filter(
    (event) =>
      filter === 'ALL' ||
      (filter === 'RECOVERY'
        ? /RECOVERY|INJECTION/i.test(event.event)
        : filter === 'RISK'
          ? /RISK|ERROR|PAUSE|REJECT|DISCONNECT/i.test(event.event)
          : /ORDER|EXECUTION|TP|PAIR|FILL/i.test(event.event)),
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">OGNI OPERAZIONE, IN CHIARO</p>
          <h1>
            Attività <span>del bot.</span>
          </h1>
        </div>
        <button
          className={`button secondary ${technical ? 'selected' : ''}`}
          onClick={() => setTechnical(!technical)}
          aria-pressed={technical}
        >
          <Code2 size={16} />
          {technical ? 'Nascondi dettagli tecnici' : 'Mostra dettagli tecnici'}
        </button>
      </div>
      <section className="glass activity-panel">
        <div className="activity-toolbar">
          <h2>
            <Clock3 size={18} />
            Timeline
          </h2>
          <label className="filter-select">
            <ListFilter size={15} />
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              aria-label="Filtra attività"
            >
              <option value="ALL">Tutte le attività</option>
              <option value="ORDERS">Ordini ed esecuzioni</option>
              <option value="RECOVERY">Smart Recovery</option>
              <option value="RISK">Rischio e connessione</option>
            </select>
          </label>
        </div>
        {!shown.length ? (
          <div className="large-empty">
            <ActivityIcon size={36} />
            <strong>
              {events.length ? 'Nessun evento con questo filtro' : 'Nessuna attività registrata'}
            </strong>
            <p>Qui troverai gli eventi reali del bot e le conferme di Bybit.</p>
          </div>
        ) : (
          <div className="timeline">
            {shown.map((event) => (
              <EventRow key={String(event.id)} event={event} technical={technical} />
            ))}
          </div>
        )}
      </section>
      {technical && (
        <section className="glass orders-panel">
          <h2>Ordini sull’exchange</h2>
          {!orders.length ? (
            <p className="text-muted">Nessun ordine disponibile.</p>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Order ID Bybit</th>
                    <th>Client ID</th>
                    <th>Lato</th>
                    <th>Quantità</th>
                    <th>Tipo</th>
                    <th>Stato</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.map((order, index) => (
                    <tr key={String(order.orderId ?? order.order_id ?? index)}>
                      <td className="mono">{String(order.orderId ?? order.order_id ?? '—')}</td>
                      <td className="mono">
                        {String(order.orderLinkId ?? order.order_link_id ?? '—')}
                      </td>
                      <td>{String(order.side ?? '—')}</td>
                      <td>{String(order.qty ?? '—')}</td>
                      <td>{String(order.purpose ?? '—')}</td>
                      <td>{String(order.orderStatus ?? order.status ?? order.state ?? '—')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </>
  );
}
