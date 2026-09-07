import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: [
      {
        find: /^quasar$/,
        replacement: fileURLToPath(
          new URL('./node_modules/quasar/dist/quasar.client.js', import.meta.url),
        ),
      },
      { find: '@', replacement: fileURLToPath(new URL('./src', import.meta.url)) },
    ],
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.spec.ts'],
    css: true,
    coverage: { reporter: ['text', 'html'] },
  },
})
