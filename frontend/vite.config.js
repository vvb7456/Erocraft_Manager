import { defineConfig } from 'vite';
import { resolve } from 'path';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  root: '.',
  base: '/',
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  build: {
    outDir: resolve(__dirname, '..', 'static', 'dist'),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
      },
    },
  },
  server: {
    port: 3000,
    host: true,
    allowedHosts: true,
    proxy: {
      '/api': 'http://localhost:5001',
      '/login': 'http://localhost:5001',
      '/logout': 'http://localhost:5001',
    },
  },
});
