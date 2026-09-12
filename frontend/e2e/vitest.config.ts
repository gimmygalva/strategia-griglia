import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const backend = process.env.GRIDBOT_E2E_URL;
if (!backend || !process.env.GRIDBOT_E2E_TOKEN || !process.env.GRIDBOT_E2E_REPORT_PATH) {
  throw new Error(
    'Start this E2E using scripts/run_frontend_backend_e2e.py; URL/token/report are required.',
  );
}
const url = new URL(backend);
if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1') {
  throw new Error('E2E accepts an actual loopback HTTP server only.');
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    environment: 'jsdom',
    environmentOptions: { jsdom: { url: backend } },
    setupFiles: ['./e2e/setup.ts'],
    include: ['e2e/real-runtime.test.tsx'],
    globals: true,
    css: true,
    restoreMocks: true,
    // Preserve Node Event/EventTarget in undici's host realm while jsdom owns
    // DOM events in its VM. Real jsdom WebSockets require this realm separation.
    pool: 'vmThreads',
    testTimeout: 60_000,
    hookTimeout: 10_000,
    fileParallelism: false,
    maxWorkers: 1,
  },
});
