import { unlink } from "node:fs/promises";
import { resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const standalonePolicyComparisonPage = "policy-comparison-demo.html";

function excludeStandalonePolicyComparisonFromBuild(): Plugin {
  let outputDirectory = "";

  return {
    name: "exclude-standalone-policy-comparison-from-build",
    apply: "build",
    configResolved(config) {
      outputDirectory = resolve(config.root, config.build.outDir);
    },
    async closeBundle() {
      try {
        await unlink(resolve(outputDirectory, standalonePolicyComparisonPage));
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), excludeStandalonePolicyComparisonFromBuild()],
  server: {
    host: "127.0.0.1",
    port: 5174,
    strictPort: true,
    proxy: {
      "/api": "http://127.0.0.1:8081",
      "/demo-api": "http://127.0.0.1:8083",
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
