import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

// Only native Tauri communication is substituted. Every HTTP response and local
// WebSocket message comes from the actual servers started by the Python parent.
vi.mock('@tauri-apps/api/core', () => ({
  invoke: async (command: string) => {
    if (command === 'bootstrap')
      return {
        url: process.env.GRIDBOT_E2E_URL,
        token: process.env.GRIDBOT_E2E_TOKEN,
      };
    if (command === 'frontend_ready') return undefined;
    throw new Error(`Unsupported native bridge command: ${command}`);
  },
}));
vi.mock('@tauri-apps/api/event', () => ({
  listen: async () => () => undefined,
}));

// jsdom has no usable chart canvas. Chart data loading and UI state are real;
// pixel rendering, WKWebView and native window lifecycle are outside this test.
vi.mock('lightweight-charts', () => ({
  createChart: () => ({
    addSeries: () => ({
      setData: () => undefined,
      createPriceLine: () => ({}),
      removePriceLine: () => undefined,
    }),
    timeScale: () => ({ fitContent: () => undefined }),
    remove: () => undefined,
  }),
  CandlestickSeries: {},
  ColorType: { Solid: 'solid' },
  LineStyle: { Solid: 0, Dashed: 2, Dotted: 1 },
}));

Object.defineProperty(window, '__TAURI_INTERNALS__', { value: {}, configurable: true });
// This is jsdom's real undici-backed WebSocket, including its actual window
// Origin header. It is not a fixture or a fabricated socket implementation.
Object.defineProperty(globalThis, 'WebSocket', { value: window.WebSocket, configurable: true });
