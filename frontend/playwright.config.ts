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

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `"${pythonExecutable}" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000`,
      cwd: repositoryRoot,
      // /docs is available on both the current app and older local processes,
      // allowing reuse without starting a second server on the same port.
      url: "http://127.0.0.1:8000/docs",
      reuseExistingServer: true,
      timeout: 120_000,
      env: {
        RESOLVEAI_DATABASE_URL: "sqlite+pysqlite:///:memory:",
        RESOLVEAI_POLICY_RETRIEVAL: "lexical",
      },
    },
    {
      command: `${npmExecutable} run dev -- --host 127.0.0.1 --port 5173`,
      cwd: frontendRoot,
      url: "http://127.0.0.1:5173",
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
