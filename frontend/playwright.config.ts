import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL(".", import.meta.url));
const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));
const pythonExecutable = process.env.RESOLVEAI_PYTHON ?? (
  process.platform === "win32"
    ? `${repositoryRoot}\\.venv\\Scripts\\python.exe`
    : `${repositoryRoot}/.venv/bin/python`
);
const npmExecutable = process.platform === "win32" ? "npm.cmd" : "npm";
const configuredBrowser = process.env.RESOLVEAI_PLAYWRIGHT_EXECUTABLE;
const apiPort = process.env.RESOLVEAI_PLAYWRIGHT_API_PORT ?? "8000";
const frontendPort = process.env.RESOLVEAI_PLAYWRIGHT_FRONTEND_PORT ?? "5173";
const apiBaseUrl = process.env.VITE_API_BASE_URL ?? `http://127.0.0.1:${apiPort}`;
const productionAuthMode = process.env.VITE_AUTH_MODE === "production";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  // The functional suite shares one synthetic API process and its admission
  // state; serial workers keep the local fixture deterministic and avoid
  // treating concurrent test setup as customer traffic.
  workers: 1,
  reporter: "list",
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
    trace: "retain-on-failure",
    ...(configuredBrowser ? { launchOptions: { executablePath: configuredBrowser } } : {}),
  },
  webServer: [
    {
      command: `"${pythonExecutable}" -m uvicorn backend.app.main:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: repositoryRoot,
      // /docs is available on both the current app and older local processes,
      // allowing reuse without starting a second server on the same port.
      url: `http://127.0.0.1:${apiPort}/docs`,
      reuseExistingServer: !productionAuthMode,
      timeout: 120_000,
      env: {
        RESOLVEAI_DATABASE_URL: "sqlite+pysqlite:///:memory:",
        RESOLVEAI_POLICY_RETRIEVAL: "lexical",
        RESOLVEAI_CORS_ORIGINS: `http://127.0.0.1:${frontendPort},http://localhost:${frontendPort}`,
      },
    },
    {
      command: `${npmExecutable} run dev -- --host 127.0.0.1 --port ${frontendPort}`,
      cwd: frontendRoot,
      url: `http://127.0.0.1:${frontendPort}`,
      reuseExistingServer: !productionAuthMode,
      timeout: 120_000,
      env: {
        VITE_API_BASE_URL: apiBaseUrl,
      },
    },
  ],
});
