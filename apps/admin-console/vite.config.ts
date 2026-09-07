import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  base: process.env.VITE_BASE_PATH || '/',
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    host: '0.0.0.0',
    port: Number(process.env.PORT || 9004),
    strictPort: true,
    proxy: {
      '/admin-api/': {
        target: process.env.DEV_API_PROXY_TARGET || 'http://127.0.0.1:8000',
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.spec.ts'],
    coverage: { reporter: ['text', 'html'] },
  },
})
