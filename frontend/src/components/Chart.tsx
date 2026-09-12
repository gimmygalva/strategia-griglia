import { useEffect, useRef, useState } from 'react';
import { createChart, CandlestickSeries, ColorType, LineStyle } from 'lightweight-charts';
import type { IChartApi, ISeriesApi, IPriceLine, UTCTimestamp } from 'lightweight-charts';
import { CandlestickChart, Expand, Radio } from 'lucide-react';
import { api } from '../lib/api';
import type { BotState, Candle } from '../lib/types';
import { amount } from '../lib/format';

const INTERVALS = [
  ['1', '1m'],
  ['5', '5m'],
  ['15', '15m'],
  ['60', '1h'],
  ['240', '4h'],
  ['D', '1D'],
];
function preserveCandles(previous: Candle[], next: Candle[]): Candle[] {
  return previous.length === next.length &&
    previous.every(
      (candle, index) =>
        candle.time === next[index].time &&
        candle.open === next[index].open &&
        candle.high === next[index].high &&
        candle.low === next[index].low &&
        candle.close === next[index].close,
    )
    ? previous
    : next;
}

export function PriceChart({ state, backendOnline }: { state: BotState; backendOnline: boolean }) {
  const element = useRef<HTMLDivElement>(null);
  const container = useRef<HTMLElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const lines = useRef<IPriceLine[]>([]);
  const fitted = useRef(false);
  const [interval, setInterval] = useState(state.config.support_resistance_timeframe);
  const [candles, setCandles] = useState<Candle[]>(state.candles);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const changeInterval = (next: string) => {
    if (next === interval) return;
    fitted.current = false;
    setCandles([]);
    setFetchError(null);
    setInterval(next);
  };

  useEffect(() => {
    if (interval === state.config.support_resistance_timeframe)
      setCandles((previous) => preserveCandles(previous, state.candles));
  }, [state.candles, state.config.support_resistance_timeframe, interval]);

  useEffect(() => {
    let active = true;
    let inFlight = false;
    if (!backendOnline) return;
    const load = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const next = await api.candles(interval);
        if (active) {
          setCandles((previous) => preserveCandles(previous, next));
          setFetchError(null);
        }
      } catch (error) {
        if (active) {
          setCandles([]);
          setFetchError(error instanceof Error ? error.message : 'Candele non disponibili.');
        }
      } finally {
        inFlight = false;
      }
    };
    void load();
    const poll =
      state.public_connected && interval !== state.config.support_resistance_timeframe
        ? window.setInterval(() => void load(), 30_000)
        : undefined;
    return () => {
      active = false;
      window.clearInterval(poll);
    };
  }, [interval, backendOnline, state.public_connected, state.config.support_resistance_timeframe]);

  useEffect(() => {
    if (!element.current) return;
    const instance = createChart(element.current, {
      autoSize: true,
      height: 470,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#8391a9',
        fontFamily: 'Inter, system-ui, sans-serif',
        fontSize: 11,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: 'rgba(102, 130, 176, .06)' },
        horzLines: { color: 'rgba(102, 130, 176, .09)' },
      },
      crosshair: {
        vertLine: { color: '#7187a7', labelBackgroundColor: '#273653' },
        horzLine: { color: '#7187a7', labelBackgroundColor: '#273653' },
      },
      rightPriceScale: {
        borderColor: 'rgba(123, 145, 180, .10)',
        scaleMargins: { top: 0.12, bottom: 0.1 },
      },
      timeScale: {
        borderColor: 'rgba(123, 145, 180, .10)',
        timeVisible: true,
        secondsVisible: false,
      },
      localization: { locale: 'it-IT' },
    });
    chart.current = instance;
    series.current = instance.addSeries(CandlestickSeries, {
      upColor: '#40c7a1',
      downColor: '#f1758c',
      borderVisible: false,
      wickUpColor: '#40c7a1',
      wickDownColor: '#f1758c',
      priceLineVisible: false,
    });
    return () => {
      series.current = null;
      chart.current = null;
      lines.current = [];
      instance.remove();
    };
  }, []);

  useEffect(() => {
    const mapped = candles
      .filter((candle) =>
        [candle.time, candle.open, candle.high, candle.low, candle.close].every((value) =>
          Number.isFinite(Number(value)),
        ),
      )
      .map((candle) => ({
        time: candle.time as UTCTimestamp,
        open: Number(candle.open),
        high: Number(candle.high),
        low: Number(candle.low),
        close: Number(candle.close),
      }));
    const unique = new Map(mapped.map((candle) => [candle.time, candle]));
    series.current?.setData([...unique.values()].sort((a, b) => Number(a.time) - Number(b.time)));
    if (!fitted.current && unique.size) {
      chart.current?.timeScale().fitContent();
      fitted.current = true;
    }
  }, [candles]);

  useEffect(() => {
    const candleSeries = series.current;
    if (!candleSeries) return;
    lines.current.forEach((line) => candleSeries.removePriceLine(line));
    lines.current = [];
    const add = (
      price: string | number | null | undefined,
      title: string,
      color: string,
      label = true,
      style = LineStyle.Dashed,
    ) => {
      if (price == null || !Number.isFinite(Number(price)) || Number(price) <= 0) return;
      lines.current.push(
        candleSeries.createPriceLine({
          price: Number(price),
          color,
          lineWidth: 1,
          lineStyle: style,
          axisLabelVisible: label,
          title,
        }),
      );
    };
    if (state.public_connected && backendOnline)
      add(state.price, '', '#6595ff', true, LineStyle.Solid);
    const price = Number(state.price);
    [...state.grid]
      .sort((a, b) => Math.abs(Number(a.price) - price) - Math.abs(Number(b.price) - price))
      .slice(0, 8)
      .forEach((level) => add(level.price, 'Grid', '#4874b866', false, LineStyle.Dotted));
    state.recovery.forEach((block) => {
      add(block.average, `Media ${block.side}`, '#e9b75f');
      add(block.tp, 'TP Recovery', '#b193ff');
    });
    (state.orders ?? [])
      .filter(
        (order) =>
          ['TP', 'RECOVERY_TP'].includes(String(order.purpose)) &&
          !['CANCELED', 'CLOSED', 'FILLED', 'REJECTED', 'Cancelled', 'Filled'].includes(
            String(order.status ?? order.orderStatus),
          ),
      )
      .slice(0, 3)
      .forEach((order) => add(order.price, 'TP', '#40c7a188'));
    const sr = state.support_resistance;
    if (sr) {
      add(sr.S1 ?? sr.s1, 'S1', '#3db6a366');
      add(sr.R1 ?? sr.r1, 'R1', '#e2859566');
    }
  }, [
    state.price,
    state.public_connected,
    state.grid,
    state.recovery,
    state.orders,
    state.support_resistance,
    backendOnline,
  ]);

  return (
    <section className="glass chart-panel" ref={container} aria-label="Grafico BTCUSDT">
      <div className="chart-header">
        <div className="market-title">
          <span className="bitcoin-icon">₿</span>
          <div>
            <h2>
              Bitcoin <span>BTCUSDT</span>
            </h2>
            <p>USDT Perpetual · Bybit</p>
          </div>
        </div>
        <div className="market-price">
          <strong>{state.public_connected && backendOnline ? amount(state.price) : '—'}</strong>
          <small>USDT</small>
        </div>
      </div>
      <div className="chart-toolbar">
        <div className="chart-intervals" role="group" aria-label="Timeframe grafico">
          {INTERVALS.map(([value, text]) => (
            <button
              key={value}
              onClick={() => changeInterval(value)}
              aria-pressed={interval === value}
              className={interval === value ? 'active' : ''}
            >
              {text}
            </button>
          ))}
        </div>
        <button
          className="icon-button"
          aria-label="Adatta grafico"
          title="Adatta grafico"
          onClick={() => chart.current?.timeScale().fitContent()}
        >
          <Expand size={16} />
        </button>
      </div>
      <div className="chart-canvas-wrap">
        <div ref={element} className="chart-canvas" data-testid="price-chart" />
        {!candles.length && (
          <div className="chart-empty">
            <CandlestickChart size={38} />
            <strong>
              {fetchError ? 'Grafico non disponibile' : 'In attesa dei dati di mercato'}
            </strong>
            <p>{fetchError ?? 'Collega Bybit per visualizzare le candele reali.'}</p>
          </div>
        )}
      </div>
      <div className="chart-footer">
        <div className="chart-legend">
          <span>
            <i className="legend-grid" />
            Grid
          </span>
          <span>
            <i className="legend-tp" />
            Take Profit
          </span>
          <span>
            <i className="legend-recovery" />
            Recovery
          </span>
          <span>
            <i className="legend-sr" />
            S/R
          </span>
        </div>
        <span
          className={`feed-status ${state.public_connected && backendOnline ? 'text-positive' : 'text-muted'}`}
        >
          <Radio size={12} />
          {state.public_connected && backendOnline ? 'Market feed Mainnet' : 'Feed non connesso'}
        </span>
      </div>
    </section>
  );
}
