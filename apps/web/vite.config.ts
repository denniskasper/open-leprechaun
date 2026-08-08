import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { apiHost, apiPort, repoRoot, webPort } from "./env";

export default defineConfig({
  envDir: repoRoot,
  plugins: [react(), tailwindcss()],
  server: {
    port: webPort,
    strictPort: true,
    proxy: {
      // Same-origin in the browser, so there is no CORS configuration to keep
      // in step between here and the API.
      "/api": {
        target: `http://${apiHost}:${apiPort}`,
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "node",
    // Modules only. Individual React components are deliberately not tested in
    // isolation — the seam above them is Playwright.
    include: ["src/**/*.test.ts"],
  },
});
