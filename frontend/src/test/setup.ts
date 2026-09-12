import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

vi.mock('lightweight-charts', () => ({
  createChart: vi.fn(() => ({
    addSeries: vi.fn(() => ({
      setData: vi.fn(),
      createPriceLine: vi.fn(() => ({})),
      removePriceLine: vi.fn(),
    })),
    timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
    remove: vi.fn(),
  })),
  CandlestickSeries: {},
  ColorType: { Solid: 'solid' },
  LineStyle: { Solid: 0, Dashed: 2, Dotted: 1 },
}));
