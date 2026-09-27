import { defineConfig } from '@playwright/test'

// Local readiness checks must bypass workstation HTTP proxies.
process.env.NO_PROXY = [process.env.NO_PROXY, '127.0.0.1', 'localhost'].filter(Boolean).join(',')
const port = Number(process.env.PLAYWRIGHT_PORT || 4173)
const baseURL = `http://127.0.0.1:${port}`

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  workers: 2,
  use: { baseURL, browserName: 'chromium', trace: 'retain-on-failure' },
  webServer: {
    command: `node node_modules/vite/bin/vite.js --host 127.0.0.1 --port ${port} --strictPort`,
    url: baseURL,
    reuseExistingServer: false,
    env: { VITE_API_BASE_URL: baseURL, VITE_AMAP_WEB_JS_KEY: '' }
  }
})

