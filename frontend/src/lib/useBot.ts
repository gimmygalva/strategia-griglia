import { useCallback, useEffect, useRef, useState } from 'react';
import {
  api,
  desktopBackendError,
  invalidateBootstrap,
  notifyFrontendReady,
  openStateSocket,
} from './api';
import { EMPTY_STATE } from './types';
import type { BotState, StrategyEvent } from './types';
import { isBotState, isStrategyEvent } from './validation';

export function useBot() {
  const [state, setState] = useState<BotState>(EMPTY_STATE);
  const [events, setEvents] = useState<StrategyEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [backendOnline, setBackendOnline] = useState(false);
  const [socketOnline, setSocketOnline] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);
  const generation = useRef(0);
  const revision = useRef(0);
  const environment = useRef(EMPTY_STATE.environment);

  const refresh = useCallback(async () => {
    const lifecycle = generation.current;
    const requestRevision = ++revision.current;
    const active = () => alive.current && lifecycle === generation.current;
    const current = () => active() && requestRevision === revision.current;
    try {
      const next = await api.state();
      if (!active()) return;
      if (!isBotState(next))
        throw new Error('Stato del backend non valido. I comandi di trading restano bloccati.');
      if (current()) {
        if (environment.current !== next.environment) setEvents([]);
        environment.current = next.environment;
        setState(next);
        setBackendOnline(true);
        setError(null);
        await notifyFrontendReady();
      }
      try {
        const audit = await api.events();
        if (!audit.every(isStrategyEvent)) throw new Error('Invalid audit');
        if (active() && environment.current === next.environment)
          setEvents((old) =>
            [
              ...new Map(
                [...audit, ...old]
                  .filter(
                    (event) =>
                      event.environment === undefined || event.environment === environment.current,
                  )
                  .map((event) => [String(event.id), event]),
              ).values(),
            ]
              .sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime())
              .slice(0, 250),
          );
      } catch {
        if (active() && environment.current === next.environment)
          setError('Timeline non disponibile. Verifica la connessione al backend.');
      }
    } catch (err) {
      if (current()) {
        setBackendOnline(false);
        setError(err instanceof Error ? err.message : 'Connessione non disponibile.');
      }
    } finally {
      if (alive.current && lifecycle === generation.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    generation.current++;
    const activeGeneration = generation.current;
    let disposed = false;
    let socket: WebSocket | undefined;
    let reconnect: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    void refresh();
    const connect = async () => {
      if (disposed) return;
      try {
        socket = await openStateSocket();
        if (disposed) {
          socket.close();
          return;
        }
        socket.onopen = () => {
          if (disposed) return;
          attempts = 0;
          setSocketOnline(true);
          void refresh();
        };
        socket.onmessage = (message) => {
          if (disposed) return;
          try {
            const frame = JSON.parse(message.data) as {
              type: string;
              data: BotState | StrategyEvent;
            };
            if (frame.type === 'state') {
              if (!isBotState(frame.data)) throw new Error('Invalid state');
              revision.current++;
              if (environment.current !== frame.data.environment) setEvents([]);
              environment.current = frame.data.environment;
              setState(frame.data as BotState);
              setBackendOnline(true);
              setError(null);
              setLoading(false);
              void notifyFrontendReady().catch(() => {
                if (!disposed) setError('Backend in riavvio. Attendi la verifica di salute.');
              });
            } else if (frame.type === 'event') {
              if (!isStrategyEvent(frame.data)) throw new Error('Invalid strategy event');
              const event = frame.data as StrategyEvent;
              if (event.environment !== undefined && event.environment !== environment.current)
                return;
              setEvents((old) =>
                [event, ...old.filter((item) => String(item.id) !== String(event.id))].slice(
                  0,
                  250,
                ),
              );
            }
          } catch {
            setError('Aggiornamento realtime non valido. Verifica lo stato prima di operare.');
            setSocketOnline(false);
            socket?.close();
          }
        };
        socket.onerror = () => {
          if (!disposed) setSocketOnline(false);
        };
        socket.onclose = () => {
          if (disposed) return;
          setSocketOnline(false);
          reconnect = setTimeout(
            () => {
              void refresh();
              void connect();
            },
            Math.min(30_000, 1_000 * 2 ** attempts++),
          );
        };
      } catch (err) {
        if (disposed) return;
        setError(err instanceof Error ? err.message : 'Realtime locale non disponibile.');
        setSocketOnline(false);
        reconnect = setTimeout(
          () => {
            void refresh();
            void connect();
          },
          Math.min(30_000, 1_000 * 2 ** attempts++),
        );
      }
    };
    void connect();
    let unlisten: (() => void)[] = [];
    if ('__TAURI_INTERNALS__' in window) {
      void import('@tauri-apps/api/event')
        .then(async ({ listen }) => {
          for (const name of ['backend-restarted', 'backend-unavailable']) {
            const stop = await listen<unknown>(name, (event) => {
              invalidateBootstrap();
              setBackendOnline(false);
              setSocketOnline(false);
              setError(
                name === 'backend-unavailable' ? desktopBackendError(event.payload) : null,
              );
              socket?.close();
              if (name === 'backend-restarted') void refresh();
            });
            if (disposed) stop();
            else unlisten.push(stop);
          }
        })
        .catch(() => {
          if (!disposed) setError('Notifiche desktop non disponibili.');
        });
    }
    return () => {
      disposed = true;
      alive.current = false;
      generation.current = activeGeneration + 1;
      clearTimeout(reconnect);
      if (socket) {
        socket.onclose = null;
        socket.close();
      }
      unlisten.forEach((stop) => stop());
      unlisten = [];
    };
  }, [refresh]);

  return { state, events, loading, error, backendOnline, socketOnline, refresh };
}
