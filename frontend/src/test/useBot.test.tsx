import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useBot } from '../lib/useBot';
import { api, openStateSocket } from '../lib/api';
import { readyState } from './fixtures';
import type { BotState, StrategyEvent } from '../lib/types';

vi.mock('../lib/api', () => ({
  api: { state: vi.fn(), events: vi.fn() },
  openStateSocket: vi.fn(),
  invalidateBootstrap: vi.fn(),
  notifyFrontendReady: vi.fn().mockResolvedValue(undefined),
}));

class TestSocket {
  onopen: (() => void) | null = null;
  onmessage: ((message: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  close = vi.fn();
  frame(type: string, data: BotState | StrategyEvent) {
    this.onmessage?.({ data: JSON.stringify({ type, data }) });
  }
}
let sockets: TestSocket[] = [];
beforeEach(() => {
  sockets = [];
  vi.mocked(api.state).mockReset().mockResolvedValue(readyState());
  vi.mocked(api.events).mockReset().mockResolvedValue([]);
  vi.mocked(openStateSocket)
    .mockReset()
    .mockImplementation(async () => {
      const socket = new TestSocket();
      sockets.push(socket);
      return socket as unknown as WebSocket;
    });
});

describe('realtime account state lifecycle', () => {
  it('loads real API state and applies server state snapshots without synthetic data', async () => {
    const { result } = renderHook(() => useBot());
    await waitFor(() => expect(result.current.backendOnline).toBe(true));
    expect(result.current.state.price).toBe('67000');
    await act(async () => {
      sockets[0].onopen?.();
      sockets[0].frame('state', readyState({ status: 'RUNNING', price: '67123.5' }));
    });
    expect(result.current.socketOnline).toBe(true);
    expect(result.current.state.status).toBe('RUNNING');
    expect(result.current.state.price).toBe('67123.5');
  });
  it('deduplicates repeated local strategy event IDs', async () => {
    const { result } = renderHook(() => useBot());
    await waitFor(() => expect(sockets.length).toBe(1));
    const event: StrategyEvent = {
      id: 'same-execution',
      time: '2026-09-12T12:40:00Z',
      title: 'Eseguito',
      event: 'EXECUTION',
      details: {},
    };
    act(() => {
      sockets[0].frame('event', event);
      sockets[0].frame('event', event);
    });
    expect(result.current.events).toHaveLength(1);
  });
  it('does not let older REST response overwrite newer WebSocket state', async () => {
    let resolve!: (value: BotState) => void;
    const pending = new Promise<BotState>((done) => {
      resolve = done;
    });
    vi.mocked(api.state).mockReturnValue(pending);
    const { result } = renderHook(() => useBot());
    await waitFor(() => expect(sockets.length).toBe(1));
    act(() => {
      sockets[0].onopen?.();
      sockets[0].frame('state', readyState({ status: 'RUNNING', price: '68000' }));
    });
    await act(async () => {
      resolve(readyState({ status: 'PAUSED', price: '66000' }));
      await pending;
    });
    expect(result.current.state.status).toBe('RUNNING');
    expect(result.current.state.price).toBe('68000');
  });
  it('shows offline failure and restores read state on reconnection, without starting strategy', async () => {
    vi.mocked(api.state).mockRejectedValueOnce(new Error('Backend unavailable'));
    const { result } = renderHook(() => useBot());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.backendOnline).toBe(false);
    expect(result.current.error).toBe('Backend unavailable');
    act(() => {
      sockets[0].onopen?.();
    });
    await waitFor(() => expect(result.current.backendOnline).toBe(true));
    expect(result.current.state.status).toBe('READY');
  });
  it('reconnects with backoff and stops retrying after unmount', async () => {
    vi.useFakeTimers();
    const { result, unmount } = renderHook(() => useBot());
    await act(async () => {
      await Promise.resolve();
    });
    act(() => {
      sockets[0].onopen?.();
      sockets[0].onclose?.();
    });
    expect(result.current.socketOnline).toBe(false);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(openStateSocket).toHaveBeenCalledTimes(2);
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(31_000);
    });
    expect(openStateSocket).toHaveBeenCalledTimes(2);
    expect(sockets[1].close).toHaveBeenCalled();
  });
  it('rejects malformed realtime JSON, closes socket and blocks local realtime status', async () => {
    const { result } = renderHook(() => useBot());
    await waitFor(() => expect(sockets.length).toBe(1));
    await act(async () => {
      sockets[0].onopen?.();
    });
    await act(async () => {
      sockets[0].onmessage?.({ data: 'invalid-json' });
    });
    expect(result.current.socketOnline).toBe(false);
    expect(result.current.error).toMatch(/non valido/);
    expect(sockets[0].close).toHaveBeenCalled();
  });
});
