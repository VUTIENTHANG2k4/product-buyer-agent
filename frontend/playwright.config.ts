import { defineConfig, devices } from '@playwright/test'

/**
 * E2E (docs/09): trình duyệt thật → frontend Vite → backend thật với `LLM_PROVIDER=fake` trên DB riêng
 * `*_e2e` (script `backend/scripts/e2e_server.py` tạo DB, migrate, seed `e2e --reset`, rồi chạy API).
 * Không dùng lại server có sẵn: một Vite/API của `make dev` sẽ trỏ vào DB dev nên phải tắt trước.
 */
const API_PORT = 8010
const WEB_PORT = 5173 // CORS của backend chỉ cho origin http://localhost:5173

export default defineConfig({
  testDir: './e2e',
  // Các spec dùng chung một DB (danh sách, cảnh báo) nên chạy lần lượt, mỗi spec tự đặt tên riêng.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: 'list',
  use: { baseURL: `http://localhost:${WEB_PORT}`, trace: 'on-first-retry' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `uv run python -m scripts.e2e_server --port ${API_PORT}`,
      cwd: '../backend',
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 180_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: 'npm run dev',
      env: { VITE_API_BASE_URL: `http://localhost:${API_PORT}` },
      url: `http://localhost:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
})
