import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createChart } from 'lightweight-charts';
import { PriceChart } from '../components/Chart';
import { api } from '../lib/api';
import { EMPTY_STATE } from '../lib/types';
import { readyState } from './fixtures';

vi.mock('../lib/api', () => ({ api: { candles: vi.fn() } }));
beforeEach(() => {
  vi.mocked(api.candles).mockReset().mockResolvedValue(readyState().candles);
  vi.mocked(createChart).mockClear();
});
const instance = () => vi.mocked(createChart).mock.results.at(-1)!.value;
const candleSeries = () => vi.mocked(instance().addSeries).mock.results[0].value;
const fit = () => vi.mocked(instance().timeScale).mock.results[0].value.fitContent;

describe('actual candle feed presentation', () => {
  it('plots only source OHLC data, sorted and deduplicated by exchange time', async () => {
    const original = readyState().candles[0];
    vi.mocked(api.candles).mockResolvedValue([
      { ...original, time: 20 },
      { ...original, time: 10, close: '67001' },
      { ...original, time: 10, close: '67002' },
    ]);
    await act(async () => {
      render(<PriceChart state={readyState({ candles: [] })} backendOnline />);
    });
    expect(candleSeries().setData).toHaveBeenLastCalledWith([
      { time: 10, open: 66900, high: 67100, low: 66800, close: 67002 },
      { time: 20, open: 66900, high: 67100, low: 66800, close: 67000 },
    ]);
  });
  it('shows no invented candles or market price when disconnected', async () => {
    vi.mocked(api.candles).mockResolvedValue([]);
    await act(async () => {
      render(<PriceChart state={EMPTY_STATE} backendOnline={false} />);
    });
    expect(candleSeries().setData).toHaveBeenLastCalledWith([]);
    expect(screen.getByText('In attesa dei dati di mercato')).toBeInTheDocument();
    expect(screen.getByText('Feed non connesso')).toBeInTheDocument();
  });
  it('keeps user zoom and source candles unchanged on ticker-only state updates', async () => {
    const state = readyState();
    let view!: ReturnType<typeof render>;
    await act(async () => {
      view = render(<PriceChart state={state} backendOnline />);
    });
    expect(fit()).toHaveBeenCalledTimes(1);
    await act(async () => {
      view.rerender(
        <PriceChart
          state={{ ...state, price: '70000', candles: [...state.candles] }}
          backendOnline
        />,
      );
    });
    expect(fit()).toHaveBeenCalledTimes(1);
    expect(candleSeries().setData).toHaveBeenLastCalledWith([
      { time: 1760000000, open: 66900, high: 67100, low: 66800, close: 67000 },
    ]);
  });
  it('fetches a selected timeframe and refreshes it with bounded REST polling', async () => {
    vi.useFakeTimers();
    await act(async () => {
      render(<PriceChart state={readyState()} backendOnline />);
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '1h' }));
    });
    expect(api.candles).toHaveBeenLastCalledWith('60');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(api.candles).toHaveBeenCalledTimes(3);
    expect(screen.getByRole('button', { name: '1h' })).toHaveAttribute('aria-pressed', 'true');
  });
  it('refetches initial candles when the authenticated market feed becomes connected', async () => {
    const state = readyState({ public_connected: false, candles: [] });
    let view!: ReturnType<typeof render>;
    await act(async () => {
      view = render(<PriceChart state={state} backendOnline />);
    });
    await act(async () => {
      view.rerender(<PriceChart state={{ ...state, public_connected: true }} backendOnline />);
    });
    expect(api.candles).toHaveBeenCalledTimes(2);
  });
});
