/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  base: process.env.VELORA_ASSET_BASE || "/",
  server: { host: "127.0.0.1", port: 5173, strictPort: true, proxy: { "/api": "http://127.0.0.1:8000" } },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true },
  build: {
    target: "es2020",
    outDir: "dist",
    emptyOutDir: true,
    manifest: "manifest.json",
    sourcemap: mode === "development",
    cssCodeSplit: true,
    reportCompressedSize: true,
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes("node_modules/react-dom") || id.includes("node_modules/scheduler")) return "react-dom";
          if (id.includes("node_modules/react/")) return "react";
        },
      },
    },
  },
  test: { environment: "jsdom", globals: true, css: false, restoreMocks: true, clearMocks: true },
}));
