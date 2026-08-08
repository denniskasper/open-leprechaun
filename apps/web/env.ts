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
