import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { Activity } from '../components/Activity';

describe('audit timeline and security', () => {
  it('shows clear empty state with no fabricated events', () => {
    render(<Activity events={[]} orders={[]} />);
    expect(screen.getByText('Nessuna attività registrata')).toBeInTheDocument();
    expect(screen.queryByText(/Long aperto/)).not.toBeInTheDocument();
  });
  it('shows actual Bybit IDs in technical details and redacts credentials in defense depth', async () => {
    const user = userEvent.setup();
    render(
      <Activity
        events={[
          {
            id: 'execution-1',
            time: '2026-09-12T12:40:00Z',
            title: 'Short eseguito',
            event: 'EXECUTION_CONFIRMED',
            details: {
              order_id: 'exchange-order-123',
              api_secret: 'never-display',
              nested: { token: 'never-display-two' },
            },
          },
        ]}
        orders={[
          {
            orderId: 'exchange-order-123',
            orderLinkId: 'grid-pair-abc',
            status: 'FILLED',
            qty: '0.004',
            side: 'SHORT',
            purpose: 'GRID',
          },
        ]}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Mostra dettagli tecnici' }));
    expect(screen.getByText('exchange-order-123')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Dettagli evento' }));
    expect(document.body.textContent).not.toContain('never-display');
    expect(document.body.textContent).toContain('exchange-order-123');
  });
  it('renders malicious event text as text, without XSS DOM nodes', () => {
    const title = '<img src=x onerror=alert(1) />';
    render(
      <Activity
        events={[{ id: 'x', time: '2026-09-12T12:40:00Z', title, event: 'ERROR', details: {} }]}
        orders={[]}
      />,
    );
    expect(screen.getByText(title)).toBeInTheDocument();
    expect(document.querySelector('img')).toBeNull();
  });
  it('renders SQL API order state for filled entries and accepted TP orders', async () => {
    const user = userEvent.setup();
    render(
      <Activity
        events={[]}
        orders={[
          {
            order_id: 'local-order-entry',
            order_link_id: 'ghb-entry',
            state: 'FILLED',
            environment: 'DEMO',
            symbol: 'BTCUSDT',
            side: 'LONG',
            qty: '0.001',
            purpose: 'GRID',
            reduce_only: false,
            executed_qty: '0.001',
            executed_notional: '67',
            fees: '0.0402',
          },
          {
            order_id: 'local-order-tp',
            order_link_id: 'ghb-tp',
            state: 'NEW',
            environment: 'DEMO',
            symbol: 'BTCUSDT',
            side: 'LONG',
            qty: '0.001',
            purpose: 'TP',
            reduce_only: true,
            executed_qty: '0',
            executed_notional: '0',
            fees: '0',
          },
        ]}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Mostra dettagli tecnici' }));
    const entryRow = screen.getByText('local-order-entry').closest('tr')!;
    const tpRow = screen.getByText('local-order-tp').closest('tr')!;
    expect(within(entryRow).getByText('FILLED')).toBeInTheDocument();
    expect(within(tpRow).getByText('NEW')).toBeInTheDocument();
  });
  it('filters real Recovery events', async () => {
    const user = userEvent.setup();
    render(
      <Activity
        events={[
          {
            id: 1,
            time: '2026-09-12T12:40:00Z',
            title: 'Bot avviato',
            event: 'BOT_STARTED',
            details: {},
          },
          {
            id: 2,
            time: '2026-09-12T12:41:00Z',
            title: 'Recovery Short attivato',
            event: 'RECOVERY_STARTED',
            details: {},
          },
        ]}
        orders={[]}
      />,
    );
    await user.selectOptions(screen.getByRole('combobox', { name: 'Filtra attività' }), 'RECOVERY');
    expect(screen.queryByText('Bot avviato')).not.toBeInTheDocument();
    expect(screen.getByText('Recovery Short attivato')).toBeInTheDocument();
  });
});
