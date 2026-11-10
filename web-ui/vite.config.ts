import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The build goes straight into the Python package, so `pip install` ships the app.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../creature_lab/web/static",
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
  server: {
    // 127.0.0.1, not localhost: Node tries IPv6 first and each request then waits for a fallback.
    // `npm run dev` talks to a running `creature-lab app --no-open-browser --port 8080`.
    proxy: { "/api": { target: "http://127.0.0.1:8080", changeOrigin: false } },
  },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
