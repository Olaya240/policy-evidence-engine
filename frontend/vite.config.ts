import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5174,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8000", "/demo-api": "http://127.0.0.1:8083" }
  },
  build: { outDir: "dist", emptyOutDir: true }
});
