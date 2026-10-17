import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Dùng chung cấu hình môi trường ở thư mục gốc dự án (chỉ biến VITE_* được đưa ra trình duyệt).
  envDir: '..',
  // Cổng cố định để Playwright (baseURL localhost:5173) và CORS của API luôn khớp;
  // cổng bận thì báo lỗi thay vì tự nhảy sang cổng khác.
  server: { port: 5173, strictPort: true },
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, 'src') },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    env: { VITE_API_BASE_URL: 'http://api.test' },
  },
})
