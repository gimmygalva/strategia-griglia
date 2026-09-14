import { writeFileSync } from 'node:fs';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { App } from '../src/App';
import type { BotState, StrategyEvent } from '../src/lib/types';

type Check = { name: string; result: 'PASS' | 'FAIL'; details: string };
interface ExchangeOrder {
  orderId: string;
  orderLinkId: string;
  reduceOnly: boolean;
  orderStatus: string;
  positionIdx: number;
  qty: string;
}
interface FixtureStats {
  orders: ExchangeOrder[];
  positions: { positionIdx: number; size: string; avgPrice: string }[];
  executions_count: number;
  ledger_executions_count: number;
  frontend_listeners: number;
  private_clients: number;
  public_clients: number;
  market_timestamp: number | null;
  reconciled: boolean;
  recovery_intents: number;
  credentials_saved: { DEMO: boolean; LIVE: boolean };
}
const NAMES = [
  'Fresh disconnected runtime and ten-step wizard',
  'Real credentials save and signed V5 connection',
  'UTA, permissions, Hedge Mode and both exchange feeds verified',
  'Configuration saved and bot explicitly started from UI',
  'Real initial LONG and SHORT fills with exchange TP orders',
  'Home Auto Recovery ON/OFF persists while running without new orders',
  'Portfolio and technical order IDs shown from real API data',
  'Real audit events shown in Activity',
  'Pause preserves executed positions and exchange TPs',
  'Actual losing recovery block displayed and unsafe injection blocked',
  'Auto ON rejects unsafe-cap recovery after a real running market tick',
  'UI socket disconnect and remount re-read state without duplicate orders',
];
const checks: Check[] = NAMES.map((name) => ({ name, result: 'FAIL', details: 'Not reached.' }));
const pass = (name: string, details: string) => {
  const check = checks.find((item) => item.name === name);
  if (!check) throw new Error('Unknown E2E check.');
  Object.assign(check, { result: 'PASS', details });
};
const base = process.env.GRIDBOT_E2E_URL!;
const token = process.env.GRIDBOT_E2E_TOKEN!;
const report = process.env.GRIDBOT_E2E_REPORT_PATH!;
const SIMULATOR_KEY = 'local-simulator-key';
const SIMULATOR_SECRET = 'local-simulator-secret';

async function read<T>(path: string): Promise<T> {
  const response = await fetch(`${base}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`Actual GET ${path} returned ${response.status}.`);
  return (await response.json()) as T;
}
async function mutate(path: string, body: unknown) {
  return await fetch(`${base}${path}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', Origin: base },
    body: JSON.stringify(body),
  });
}
async function until<T>(
  probe: () => Promise<T>,
  accepted: (value: T) => boolean,
  label: string,
): Promise<T> {
  const end = Date.now() + 20_000;
  do {
    const value = await probe();
    if (accepted(value)) return value;
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
  } while (Date.now() < end);
  throw new Error(`Actual server condition timed out: ${label}.`);
}
const state = () => read<BotState>('/api/state');
const stats = () => read<FixtureStats>('/api/e2e/stats');
const nav = () => screen.getByRole('navigation', { name: 'Navigazione principale' });

it('executes the DOM flow against production FastAPI and actual loopback V5 REST/WebSocket servers', async () => {
  const user = userEvent.setup();
  let view: ReturnType<typeof render> | undefined;
  let result: 'PASS' | 'FAIL' = 'FAIL';
  let failure: string | null = null;
  try {
    const initial = await state();
    expect(initial.status).toBe('DISCONNECTED');
    expect(initial.wizard_completed).toBe(false);
    expect(initial.account).toBeNull();
    expect(initial.portfolio.equity).toBeNull();
    expect((await stats()).credentials_saved).toEqual({ DEMO: false, LIVE: false });
    await act(async () => {
      view = render(<App />);
    });
    await screen.findByRole('dialog', { name: 'Configurazione guidata' });
    expect(screen.getAllByText('NON CONNESSO').length).toBeGreaterThan(0);
    pass(
      NAMES[0],
      'Fresh SQLite/runtime returned DISCONNECTED, null account/equity; production App opened step 1 without trading.',
    );

    await user.click(screen.getByRole('button', { name: /Cominciamo/ }));
    expect(screen.getByRole('button', { name: /DEMO/ })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: /Continua/ }));
    await user.type(screen.getByLabelText('API Key'), SIMULATOR_KEY);
    await user.type(screen.getByLabelText('API Secret'), SIMULATOR_SECRET);
    await user.click(screen.getByRole('button', { name: 'Salva credenziali' }));
    await waitFor(() => expect(screen.getByRole('button', { name: /Continua/ })).toBeEnabled());
    expect(screen.getByLabelText('API Secret')).toHaveValue('');
    expect((await stats()).credentials_saved).toEqual({ DEMO: true, LIVE: false });
    await user.click(screen.getByRole('button', { name: /Continua/ }));
    await user.click(screen.getByRole('button', { name: 'Test Connessione' }));
    const connected = await until(
      state,
      (value) => value.connected && value.public_connected && value.private_connected,
      'signed connection and both feeds',
    );
    expect(connected.environment).toBe('DEMO');
    expect(connected.account?.uid).toBe('424242');
    pass(
      NAMES[1],
      'UI saved Local Simulator credentials via real POST and connected through production Bybit adapter to the V5 loopback server. No official exchange credentials used.',
    );
    expect(connected.account?.uta_status).toBe(5);
    expect(connected.account?.hedge_mode).toBe(true);
    expect(connected.account?.permissions).toBe(true);
    const sockets = await stats();
    expect(sockets.private_clients).toBeGreaterThan(0);
    expect(sockets.public_clients).toBeGreaterThan(0);
    expect(sockets.frontend_listeners).toBeGreaterThan(0);
    pass(
      NAMES[2],
      'Real account response UID 424242/UTA5/hedge/permissions; actual private/public exchange WS and authenticated local UI WS were connected.',
    );
    await waitFor(() => expect(screen.getByRole('button', { name: /Continua/ })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: /Continua/ }));
    expect(screen.getByText('Configurazione account compatibile.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Continua/ }));
    const levels = screen.getByLabelText('Livelli per lato');
    await user.clear(levels);
    await user.type(levels, '2');
    const spacing = screen.getByLabelText('Distanza livelli');
    await user.clear(spacing);
    await user.type(spacing, '5');
    await user.click(screen.getByRole('button', { name: /Continua/ }));
    const injection = screen.getByLabelText('Injection massima');
    await user.clear(injection);
    await user.type(injection, '1');
    await user.click(screen.getByRole('button', { name: /Continua/ }));
    await user.click(screen.getByRole('button', { name: /Continua/ }));
    await user.click(screen.getByRole('button', { name: /Continua/ }));
    expect(screen.getByText('STEP 10 DI 10')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Salva e avvia bot DEMO' })).toBeEnabled(),
    );
    await user.click(screen.getByRole('button', { name: 'Salva e avvia bot DEMO' }));
    const running = await until(
      state,
      (value) => value.status === 'RUNNING' && value.wizard_completed,
      'explicit UI Start',
    );
    expect(running.config.levels).toBe(2);
    expect(running.config.max_injection_usdt).toBe('1');
    expect(running.config.spacing_pct).toBe('5');
    pass(
      NAMES[3],
      'UI completed all ten steps, persisted 2+2 levels at 5% spacing and 1-USDT injection cap, then real /api/start returned RUNNING.',
    );

    const opened = await until(
      stats,
      (value) =>
        value.orders.length === 4 &&
        value.executions_count === 2 &&
        value.ledger_executions_count === 2,
      'real two-side fills and TP protection',
    );
    const entries = opened.orders.filter((order) => !order.reduceOnly);
    const tps = opened.orders.filter((order) => order.reduceOnly);
    expect(entries).toHaveLength(2);
    expect(new Set(entries.map((order) => order.positionIdx))).toEqual(new Set([1, 2]));
    expect(entries.every((order) => order.orderStatus === 'Filled')).toBe(true);
    expect(tps).toHaveLength(2);
    expect(tps.every((order) => order.orderStatus === 'New')).toBe(true);
    expect(opened.positions.filter((position) => Number(position.size) > 0)).toHaveLength(2);
    pass(
      NAMES[4],
      `Actual V5 server accepted ${opened.orders.length} orders, confirmed ${opened.executions_count} executions, and holds distinct positionIdx 1/2 plus two reduce-only TPs.`,
    );
    await waitFor(() =>
      expect(
        screen.queryByRole('dialog', { name: 'Configurazione guidata' }),
      ).not.toBeInTheDocument(),
    );
    const protectedIdentifiers = opened.orders.map((order) => order.orderId).sort();
    const auto = screen.getByRole('switch', { name: 'Recovery automatico' });
    for (const desired of [true, false, true]) {
      const previousMarketTimestamp = (await stats()).market_timestamp;
      const refreshed = await mutate('/api/e2e/market', { price: '67000' });
      expect(refreshed.ok).toBe(true);
      await until(
        stats,
        (value) =>
          value.market_timestamp !== null &&
          (previousMarketTimestamp === null ||
            value.market_timestamp > previousMarketTimestamp),
        'fresh market feed before Auto Recovery setting',
      );
      const readyToToggle = await state();
      expect(
        readyToToggle.status,
        readyToToggle.error ?? 'Runtime must remain RUNNING before Auto Recovery setting',
      ).toBe('RUNNING');
      await waitFor(() => expect(auto).toBeEnabled());
      await user.click(auto);
      const toggled = await until(
        state,
        (value) => value.config.auto_recovery === desired,
        'real Home Auto Recovery setting',
      );
      expect(
        toggled.status,
        toggled.error ?? 'Runtime must remain RUNNING after Auto Recovery setting',
      ).toBe('RUNNING');
      await waitFor(() => (desired ? expect(auto).toBeChecked() : expect(auto).not.toBeChecked()));
      expect((await stats()).orders.map((order) => order.orderId).sort()).toEqual(
        protectedIdentifiers,
      );
    }
    pass(
      NAMES[5],
      'Real Home switch saved ON→OFF→ON through production /api/config during RUNNING. Grid/session and all four accepted exchange order IDs were preserved, with no extra order.',
    );
    const portfolio = await state();
    expect(portfolio.portfolio.equity).not.toBeNull();
    const walletAmount = new Intl.NumberFormat('it-IT', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(Number(portfolio.portfolio.equity));
    await screen.findByText(walletAmount);
    await user.click(within(nav()).getByRole('button', { name: 'Attività' }));
    await user.click(screen.getByRole('button', { name: 'Mostra dettagli tecnici' }));
    for (const order of opened.orders) await screen.findByText(order.orderId);
    const ledgerOrders = (await state()).orders ?? [];
    expect(ledgerOrders).toHaveLength(4);
    for (const order of ledgerOrders) {
      expect(order.state).toBeTruthy();
      const row = screen.getByText(String(order.order_id)).closest('tr')!;
      expect(within(row).getByText(String(order.state))).toBeInTheDocument();
    }
    pass(
      NAMES[6],
      `Portfolio shows actual fee-adjusted wallet equity ${portfolio.portfolio.equity}; Activity technical table shows all four V5 order IDs and exact SQLite API state values, including confirmed entries and accepted TPs.`,
    );
    const events = await read<StrategyEvent[]>('/api/events');
    const orderEvents = events.filter((event) =>
      /execution|order|filled|started/i.test(event.event),
    );
    expect(orderEvents.length).toBeGreaterThan(0);
    for (const event of orderEvents.slice(0, 3))
      expect(await screen.findAllByText(event.title)).not.toHaveLength(0);
    pass(
      NAMES[7],
      `UI timeline rendered titles from ${events.length} real SQLite audit events, including real order/execution events.`,
    );

    await user.click(within(nav()).getByRole('button', { name: 'Home' }));
    await user.click(screen.getByRole('button', { name: 'Pausa bot' }));
    await until(state, (value) => value.status === 'PAUSED', 'real UI Pause');
    const paused = await stats();
    expect(paused.orders).toHaveLength(4);
    expect(paused.positions).toEqual(opened.positions);
    expect(
      paused.orders
        .filter((order) => order.reduceOnly)
        .every((order) => order.orderStatus === 'New'),
    ).toBe(true);
    pass(
      NAMES[8],
      'Actual /api/pause set PAUSED; both executed positions and both accepted exchange TP orders remained unchanged.',
    );

    const moved = await mutate('/api/e2e/market', { price: '70000' });
    expect(moved.ok).toBe(true);
    const recovering = await until(
      state,
      (value) => value.recovery.some((block) => block.side === 'SHORT' && !block.safe),
      'real unsafe short recovery',
    );
    expect(recovering.recovery.find((block) => block.side === 'SHORT')?.average).toBe('67000');
    await screen.findByText('SHORT IN RECUPERO');
    await waitFor(() => expect(screen.getByText(/RECOVERY NON SICURO/)).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Valuta Injection' })).toBeDisabled();
    const recoveryResult = await mutate('/api/recovery', { side: 'SHORT', confirm: true });
    expect(recoveryResult.status).toBe(409);
    const recoveryBody = (await recoveryResult.json()) as {
      detail: { code: string; message: string };
    };
    expect(recoveryBody.detail.code).toBe('RECOVERY_ERROR');
    expect((await stats()).orders).toHaveLength(4);
    expect(recovering.config.auto_recovery).toBe(true);
    pass(
      NAMES[9],
      `Actual public exchange WS moved last/mark to 70000 while paused with Auto ON. SHORT recovery uses executed entry 67000 and is unsafe under the saved cap; UI disabled Injection and real backend rejected paused recovery (409 ${recoveryBody.detail.code}), with zero extra orders.`,
    );

    const resume = screen.getByRole('button', { name: 'Avvia bot' });
    await waitFor(() => expect(resume).toBeEnabled());
    await user.click(resume);
    await until(state, (value) => value.status === 'RUNNING', 'real UI resume with Auto ON');
    const resumedStats = await stats();
    expect(resumedStats.market_timestamp).not.toBeNull();
    expect(resumedStats.reconciled).toBe(true);
    const unchangedTick = await mutate('/api/e2e/market', { price: '70000' });
    expect(unchangedTick.ok).toBe(true);
    const evaluatedStats = await until(
      stats,
      (value) =>
        value.market_timestamp !== null && value.market_timestamp > resumedStats.market_timestamp!,
      'fresh exchange ticker completed under runtime actor while RUNNING',
    );
    const autoEvaluated = await state();
    expect(autoEvaluated.status).toBe('RUNNING');
    expect(autoEvaluated.config.auto_recovery).toBe(true);
    expect(autoEvaluated.price).toBe('70000');
    expect(autoEvaluated.recovery.find((block) => block.side === 'SHORT')?.safe).toBe(false);
    expect(evaluatedStats.recovery_intents).toBe(0);
    expect(evaluatedStats.orders.map((order) => order.orderId).sort()).toEqual(
      protectedIdentifiers,
    );
    expect(evaluatedStats.executions_count).toBe(2);
    expect(screen.getByRole('button', { name: 'Valuta Injection' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Pausa bot' }));
    await until(
      state,
      (value) => value.status === 'PAUSED',
      'UI pause after unsafe automatic evaluation',
    );
    pass(
      NAMES[10],
      `UI resumed the existing grid with Auto ON at 70000, below the first 5% grid level. A genuine exchange ticker advanced market timestamp ${resumedStats.market_timestamp}→${evaluatedStats.market_timestamp} and completed under the runtime actor. RUNNING unsafe SHORT remained blocked by the 1-USDT cap: zero RECOVERY intents, same four exchange IDs and two executions. UI paused again.`,
    );

    const identifiers = paused.orders.map((order) => order.orderId).sort();
    await act(async () => {
      view!.unmount();
    });
    await until(stats, (value) => value.frontend_listeners === 0, 'actual UI WS close');
    await act(async () => {
      view = render(<App />);
    });
    await until(stats, (value) => value.frontend_listeners === 1, 'actual UI WS reopen');
    await waitFor(() => expect(screen.getByRole('contentinfo')).toHaveTextContent('In pausa'));
    const reread = await state();
    const final = await stats();
    expect(reread.status).toBe('PAUSED');
    expect(reread.wizard_completed).toBe(true);
    expect(final.orders.map((order) => order.orderId).sort()).toEqual(identifiers);
    expect(final.executions_count).toBe(2);
    expect(final.ledger_executions_count).toBe(2);
    expect(final.positions).toEqual(paused.positions);
    pass(
      NAMES[11],
      'Real local UI WebSocket listener count went 1→0→1 on unmount/remount; actual API re-read PAUSED state and same two positions, four order IDs and two executions without any new Start.',
    );
    result = 'PASS';
  } catch (error) {
    failure = String(error)
      .replaceAll(token, '[redacted local token]')
      .replaceAll(SIMULATOR_SECRET, '[redacted simulator secret]');
    throw error;
  } finally {
    if (view)
      await act(async () => {
        view!.unmount();
      });
    writeFileSync(
      report,
      JSON.stringify(
        {
          result,
          timestamp_utc: new Date().toISOString(),
          checks,
          failure,
          limitations: [
            'DOM integration uses React/jsdom and real loopback HTTP/WebSocket servers; this is not manual browser, WKWebView or macOS installer proof.',
            'Only native Tauri bootstrap/event bridge and unavailable Lightweight Charts canvas renderer are substituted. Production api.ts, useBot, App and all server responses are real.',
            'Node fetch performs real bearer-auth HTTP; jsdom performs genuine Origin-bearing WebSocket handshake. Browser-generated REST CORS behavior is outside this test.',
            'LocalBybitServer is explicitly Local Simulator, never official Bybit Demo Trading. No real Bybit keys, Demo exchange connection or Live orders are used.',
            'UI unmount/remount proves network re-read and no automatic Start; full backend crash/restart and native app lifecycle are covered separately.',
            'Recovery checks prove executed-lot display, unsafe UI, paused backend rejection and zero injection intents/orders after real Auto-ON running market evaluation. No safe recovery injection is executed or claimed successful.',
          ],
        },
        null,
        2,
      ),
    );
  }
});
