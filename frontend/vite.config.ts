import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { sourcemap: false, target: 'es2022' },
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
