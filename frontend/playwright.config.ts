import { defineConfig, devices } from "@playwright/test";
import { API, API_PORT, BROWSER_API, PROXY, WEB, WEB_PORT, backend, backendEnv, python } from "./e2e/support";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false, // one shared database
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: [["list"]],
  globalSetup: "./e2e/global-setup.ts",
  use: { baseURL: WEB, trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `"${python}" -m uvicorn tests.e2e_server:app --port ${API_PORT}`,
      cwd: backend,
      env: backendEnv(),
      url: `${API}/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npm run build && npm run start -- -p ${WEB_PORT}`,
      env: {
        ...(process.env as Record<string, string>),
        NEXT_PUBLIC_API_URL: BROWSER_API,
        ...(PROXY ? { API_PROXY_TARGET: API, API_INTERNAL_URL: API } : {}),
      },
      url: WEB,
      reuseExistingServer: false,
      timeout: 240_000,
    },
  ],
});
