import type {
  BotOrder,
  BotState,
  Candle,
  Environment,
  Side,
  StrategyConfig,
  StrategyEvent,
} from './types';

interface Bootstrap {
  url: string;
  token: string;
}
let bootstrap: Promise<Bootstrap | null> | undefined;
let readyFor: string | undefined;

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number = 0,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

const DESKTOP_DIAGNOSTIC =
  '~/Library/Application Support/Grid Hedge Bot/logs/backend-startup.log';

export function desktopBackendError(error: unknown): string {
  const raw =
    typeof error === 'string' ? error : error instanceof Error ? error.message : '';
  const reason = raw.replace(/\s+/g, ' ').trim().slice(0, 320) || 'causa non disponibile';
  const suffix = /backend-startup\.log/i.test(reason)
    ? ''
    : ` Diagnostica: ${DESKTOP_DIAGNOSTIC}`;
  return `Backend locale non disponibile: ${reason}${suffix}`;
}

export function invalidateBootstrap(): void {
  bootstrap = undefined;
  readyFor = undefined;
}

export async function notifyFrontendReady(): Promise<void> {
  if (!('__TAURI_INTERNALS__' in window)) return;
  const resolved = await resolveBootstrap();
  if (!resolved || readyFor === resolved.url) return;
  const { invoke } = await import('@tauri-apps/api/core');
  readyFor = resolved.url;
  try {
    await invoke('frontend_ready');
  } catch (error) {
    if (readyFor === resolved.url) readyFor = undefined;
    throw error;
  }
}

async function resolveBootstrap(): Promise<Bootstrap | null> {
  if (!bootstrap) {
    bootstrap = (async () => {
      if (!('__TAURI_INTERNALS__' in window)) return null;
      const { invoke } = await import('@tauri-apps/api/core');
      try {
        const result = await invoke<Bootstrap>('bootstrap');
        const parsed = new URL(result.url);
        if (parsed.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(parsed.hostname)) {
          throw new Error('Endpoint del backend locale non valido.');
        }
        return result;
      } catch (error) {
        if (error instanceof ApiError) throw error;
        throw new ApiError('BACKEND_STARTUP_ERROR', desktopBackendError(error));
      }
    })().catch((error) => {
      invalidateBootstrap();
      throw error;
    });
  }
  return bootstrap;
}

export async function request<T>(path: string, body?: unknown): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 25_000);
  try {
    const resolved = await resolveBootstrap();
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (resolved?.token) headers.Authorization = `Bearer ${resolved.token}`;
    const response = await fetch(`${resolved?.url ?? ''}${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      credentials: 'include',
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
      cache: 'no-store',
    });
    const result = await response.json().catch(() => null);
    if (!response.ok) {
      if ([401, 403, 503].includes(response.status)) invalidateBootstrap();
      const detail = result?.detail;
      // Validation errors may include request values. Never display or retain those values.
      const message = Array.isArray(detail)
        ? 'Configurazione non valida. Controlla i parametri e riprova.'
        : typeof detail === 'object' && detail !== null && typeof detail.message === 'string'
          ? detail.message
          : typeof detail === 'string'
            ? detail
            : 'Il backend ha rifiutato la richiesta.';
      throw new ApiError(detail?.code ?? `HTTP_${response.status}`, message, response.status);
    }
    return result as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    invalidateBootstrap();
    throw new ApiError(
      'NETWORK_ERROR',
      error instanceof Error && error.name === 'AbortError'
        ? 'Il backend non ha risposto in tempo. Nessuna nuova operazione verrà richiesta automaticamente.'
        : 'Backend non raggiungibile. Il trading locale non è disponibile.',
    );
  } finally {
    clearTimeout(timeout);
  }
}

export const api = {
  state: () => request<BotState>('/api/state'),
  events: () => request<StrategyEvent[]>('/api/events'),
  orders: () => request<BotOrder[]>('/api/orders'),
  candles: (interval: string) =>
    request<Candle[]>(`/api/candles?interval=${encodeURIComponent(interval)}`),
  credentials: (environment: Environment, api_key: string, api_secret: string) =>
    request<{ saved: boolean }>('/api/credentials', { environment, api_key, api_secret }),
  connect: (environment: Environment) =>
    request<{ status: string }>('/api/connect', { environment }),
  config: (config: StrategyConfig) => request<{ config: StrategyConfig }>('/api/config', config),
  start: (live?: boolean) =>
    request<{ status: string }>(
      '/api/start',
      live ? { live_confirm: 'AVVIA LIVE', live_ack: true } : {},
    ),
  pause: () => request<{ status: string }>('/api/pause', {}),
  recovery: (side: Side) => request<{ status: string }>('/api/recovery', { side, confirm: true }),
  closeAll: () =>
    request<{ status: string }>('/api/close-all', { confirm: 'CHIUDI TUTTO', ack: true }),
  wizard: () => request<{ saved: boolean }>('/api/wizard', { completed: true }),
};

export async function openStateSocket(): Promise<WebSocket> {
  const resolved = await resolveBootstrap();
  const base = new URL(resolved?.url ?? window.location.origin);
  base.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:';
  base.pathname = '/api/ws';
  base.search = '';
  const socket = new WebSocket(base.toString());
  if (resolved?.token)
    socket.addEventListener(
      'open',
      () => {
        socket.send(JSON.stringify({ type: 'authenticate', token: resolved.token }));
      },
      { once: true },
    );
  socket.addEventListener('close', invalidateBootstrap, { once: true });
  return socket;
}
