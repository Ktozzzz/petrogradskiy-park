import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Сборка идёт в frontend/dist -- этот каталог раздаёт бэкенд (единая точка входа).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
