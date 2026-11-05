import { fileURLToPath } from "node:url";
import { loadEnv } from "vite";

/** The repository root, where the one .env shared with Compose and the API lives. */
export const repoRoot = fileURLToPath(new URL("../..", import.meta.url));

// An empty prefix, because those shared variables are not VITE_-prefixed. Only
// what a config file reads reaches the client; nothing here is exposed to it.
const env = loadEnv("development", repoRoot, "");

// `||` rather than `??`: a variable present but empty should fall back too,
// because Number("") is 0 and would bind to a random port.
export const apiHost = env.API_HOST || "127.0.0.1";
export const apiPort = Number(env.API_PORT || 8000);
export const webPort = Number(env.WEB_PORT || 5173);

// The end-to-end run's own API, web server and database, beside the
// development ones: a running dev server is never reused, and the tests never
// write into the development data.
export const e2eApiPort = Number(env.E2E_API_PORT || 8100);
export const e2eWebPort = Number(env.E2E_WEB_PORT || 5273);

/** The end-to-end database — asked for only by Playwright, so the web build and
 * unit tests never need a DATABASE_URL. */
export function e2eDatabaseUrl(): string {
  return env.E2E_DATABASE_URL || withSuffix(env.DATABASE_URL, "_e2e");
}

/** A database URL naming the database beside it: `.../leprechaun` → `.../leprechaun_e2e`. */
function withSuffix(url: string | undefined, suffix: string): string {
  const match = url?.match(/^(.*\/)([^/?]+)(\?.*)?$/);
  if (!match) {
    throw new Error("DATABASE_URL is unset or names no database; set E2E_DATABASE_URL instead.");
  }
  const [, base, name, query = ""] = match;
  return `${base}${name}${suffix}${query}`;
}
