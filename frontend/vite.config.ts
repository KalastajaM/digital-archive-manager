/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The backend (dam serve) listens on 127.0.0.1:8765. changeOrigin makes the proxy send
// Host: 127.0.0.1:8765, which the API's host check requires; the browser's Origin
// (http://localhost:5173) is kept and must be allowed with DAM_DEV_ORIGIN (see README).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    // Help bundles ../docs/guide.md (the one copy of the guide), outside this folder
    fs: { allow: [".", "../docs"] },
    proxy: {
      "/api": { target: "http://127.0.0.1:8765", changeOrigin: true },
    },
  },
  build: {
    rolldownOptions: {
      output: {
        // the libraries in their own chunk: the app's own code stays small (no 500 kB warning)
        codeSplitting: { groups: [{ name: "vendor", test: /node_modules/ }] },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    restoreMocks: true,
    unstubGlobals: true,
    // styles.test.ts and shell.test.ts read the sheets as text (no component test imports it)
    css: { include: [/(styles|theme)\.css/] },
  },
});
