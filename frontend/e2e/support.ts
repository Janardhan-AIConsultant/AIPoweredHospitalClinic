import { execFileSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import path from "node:path";

// Dedicated ports and database so the suite never touches a dev server or the dev/test databases.
export const API_PORT = 8100;
export const WEB_PORT = 3100;
export const API = `http://localhost:${API_PORT}`;
export const WEB = `http://localhost:${WEB_PORT}`;
/** E2E_PROXY=1 runs the browser through the same-origin /api rewrite (the recommended production topology). */
export const PROXY = process.env.E2E_PROXY === "1";
export const BROWSER_API = PROXY ? "/api" : API;
export const COOKIE_PATH = PROXY ? "/api/auth" : "/auth";
export const PASSWORD = "E2e-Passw0rd-123";
export const backend = path.resolve(__dirname, "../../backend");
export const python =
  process.env.E2E_PYTHON ??
  path.join(backend, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");

const b64url = (n: number) => randomBytes(n).toString("base64url");

export function backendEnv(): Record<string, string> {
  return {
    ...(process.env as Record<string, string>),
    APP_ENV: "test",
    DATABASE_URL:
      process.env.E2E_DATABASE_URL ?? "postgresql://clinic:clinic_dev_only@localhost:5432/clinic_e2e",
    FRONTEND_URL: WEB,
    ...(PROXY ? { AUTH_COOKIE_PATH: "/api/auth", AUTH_COOKIE_SAMESITE: "lax" } : {}),
    JWT_SECRET_KEY: b64url(48),
    FIELD_ENCRYPTION_KEY: randomBytes(32).toString("base64url") + "=",
    PHONE_HASH_KEY: b64url(32),
    CRON_SECRET: b64url(24),
    E2E_PASSWORD: PASSWORD,
    PYTHONPATH: backend,
  };
}

/** Fresh schema + demo data + one admin and one doctor account. */
export function prepareDatabase(env: Record<string, string>) {
  execFileSync(python, ["-m", "tests.e2e_prepare"], { cwd: backend, env: env as NodeJS.ProcessEnv, stdio: "inherit" });
}
