import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import {
  api,
  ApiError,
  invalidateBootstrap,
  notifyFrontendReady,
  openStateSocket,
} from '../lib/api';
import { invoke } from '@tauri-apps/api/core';

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }));
beforeEach(() => {
  invalidateBootstrap();
  vi.mocked(invoke).mockReset();
  delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
});
afterEach(() => {
  delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
});
const desktop = () => {
  (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
};
const reply = (data: unknown, status = 200) => ({
  ok: status < 400,
  status,
  json: () => Promise.resolve(data),
});

describe('local API authentication and error handling', () => {
  it('uses same-origin HttpOnly-cookie auth in browser and never sends a token in a URL', async () => {
    const fetch = vi.fn().mockResolvedValue(reply({ environment: 'DEMO' }));
    vi.stubGlobal('fetch', fetch);
    await api.state();
    const [url, options] = fetch.mock.calls[0];
    expect(url).toBe('/api/state');
    expect(options.credentials).toBe('include');
    expect(options.cache).toBe('no-store');
    expect(options.headers.Authorization).toBeUndefined();
    expect(invoke).not.toHaveBeenCalled();
  });
  it('uses memory-only Tauri bootstrap token in Authorization header', async () => {
    desktop();
    vi.mocked(invoke).mockResolvedValue({
      url: 'http://127.0.0.1:43210',
      token: 'local-ephemeral-token',
    });
    const fetch = vi.fn().mockResolvedValue(reply({ environment: 'DEMO' }));
    vi.stubGlobal('fetch', fetch);
    await api.state();
    expect(invoke).toHaveBeenCalledWith('bootstrap');
    expect(fetch.mock.calls[0][0]).toBe('http://127.0.0.1:43210/api/state');
    expect(fetch.mock.calls[0][1].headers.Authorization).toBe('Bearer local-ephemeral-token');
    expect(fetch.mock.calls[0][0]).not.toContain('token');
  });
  it('re-bootstrap after network failure handles new sidecar port and token without retrying mutation', async () => {
    desktop();
    vi.mocked(invoke)
      .mockResolvedValueOnce({ url: 'http://127.0.0.1:43210', token: 'token-one' })
      .mockResolvedValueOnce({ url: 'http://127.0.0.1:43211', token: 'token-two' });
    const fetch = vi
      .fn()
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce(reply({ status: 'PAUSED' }));
    vi.stubGlobal('fetch', fetch);
    await expect(api.start()).rejects.toThrow('Backend non raggiungibile');
    expect(fetch).toHaveBeenCalledTimes(1);
    await api.state();
    expect(invoke).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[1][0]).toBe('http://127.0.0.1:43211/api/state');
    expect(fetch.mock.calls[1][1].headers.Authorization).toBe('Bearer token-two');
  });
  it('re-bootstrap after readiness command races a restart', async () => {
    desktop();
    vi.mocked(invoke)
      .mockRejectedValueOnce(new Error('backend restarting'))
      .mockResolvedValueOnce({ url: 'http://127.0.0.1:43211', token: 'token-new' });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply({ status: 'PAUSED' })));
    await expect(api.state()).rejects.toThrow('Backend non raggiungibile');
    await expect(api.state()).resolves.toMatchObject({ status: 'PAUSED' });
    expect(invoke).toHaveBeenCalledTimes(2);
  });
  it('never leaks Pydantic validation input values into API errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        reply(
          {
            detail: [
              { loc: ['body', 'api_secret'], msg: 'invalid', input: 'should-never-display' },
            ],
          },
          422,
        ),
      ),
    );
    await expect(api.credentials('DEMO', 'key', 'should-never-display')).rejects.toThrow(
      'Configurazione non valida',
    );
    try {
      await api.credentials('DEMO', 'key', 'should-never-display');
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect(String(error)).not.toContain('should-never-display');
    }
  });
  it('sends precise Mainnet and Close All safety payloads', async () => {
    const fetch = vi.fn().mockResolvedValue(reply({ status: 'PAUSED' }));
    vi.stubGlobal('fetch', fetch);
    await api.start(true);
    await api.closeAll();
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
      live_confirm: 'AVVIA LIVE',
      live_ack: true,
    });
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ confirm: 'CHIUDI TUTTO', ack: true });
  });
  it('rejects non-local desktop bootstrap endpoints', async () => {
    desktop();
    vi.mocked(invoke).mockResolvedValue({
      url: 'https://external.example',
      token: 'private-token',
    });
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    await expect(api.state()).rejects.toThrow('Backend non raggiungibile');
    expect(fetch).not.toHaveBeenCalled();
  });
  it('signals native readiness once per backend generation', async () => {
    desktop();
    vi.mocked(invoke).mockImplementation(async (command) =>
      command === 'bootstrap' ? { url: 'http://127.0.0.1:43211', token: 'token' } : undefined,
    );
    await notifyFrontendReady();
    await notifyFrontendReady();
    expect(
      vi.mocked(invoke).mock.calls.filter(([command]) => command === 'frontend_ready'),
    ).toHaveLength(1);
    invalidateBootstrap();
    await notifyFrontendReady();
    expect(
      vi.mocked(invoke).mock.calls.filter(([command]) => command === 'frontend_ready'),
    ).toHaveLength(2);
  });
});

describe('local WebSocket authentication', () => {
  class TestSocket extends EventTarget {
    sent: string[] = [];
    constructor(public url: string) {
      super();
    }
    send(value: string) {
      this.sent.push(value);
    }
  }
  it('transmits token only in first authentication frame after open, never the URL', async () => {
    desktop();
    vi.mocked(invoke).mockResolvedValue({
      url: 'http://127.0.0.1:4567',
      token: 'socket-private-token',
    });
    vi.stubGlobal('WebSocket', TestSocket);
    const socket = (await openStateSocket()) as unknown as TestSocket;
    expect(socket.url).toBe('ws://127.0.0.1:4567/api/ws');
    expect(socket.sent).toHaveLength(0);
    socket.dispatchEvent(new Event('open'));
    expect(JSON.parse(socket.sent[0])).toEqual({
      type: 'authenticate',
      token: 'socket-private-token',
    });
    socket.dispatchEvent(new Event('open'));
    expect(socket.sent).toHaveLength(1);
  });
  it('uses cookie bootstrap without synthetic authentication in browser', async () => {
    vi.stubGlobal('WebSocket', TestSocket);
    const socket = (await openStateSocket()) as unknown as TestSocket;
    expect(socket.url).toContain('/api/ws');
    socket.dispatchEvent(new Event('open'));
    expect(socket.sent).toHaveLength(0);
  });
});
