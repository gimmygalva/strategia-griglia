import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Monterey ships WKWebView/Safari 15+.  Keep the production bundle inside
  // that JavaScript syntax baseline instead of relying on the build Mac's WebKit.
  build: { sourcemap: false, target: 'safari15' },
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
    css: true,
    restoreMocks: true,
    exclude: ['node_modules/**', 'dist/**', 'e2e/**'],
  },
});
