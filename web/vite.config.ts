import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 900 },
  server: { proxy: { "/api": "http://127.0.0.1:8080", "/v1": "http://127.0.0.1:8080" } },
});
