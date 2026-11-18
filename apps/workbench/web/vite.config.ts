import react from "@vitejs/plugin-react";
import { defineConfig } from "vite-plus";

const GENERATED = ["src/api/JanusApi.gen.ts", "src/api/openapi.json"];
const apiTarget = process.env["JANUS_API_URL"] ?? "http://127.0.0.1:8440";

export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env["PORT"] ?? 5184),
    proxy: { "/api": apiTarget },
    // The logo lives at the repository root.
    fs: { allow: ["../../.."] },
  },
  build: {
    // `janus-workbench serve` serves the client from inside its own package.
    outDir: "../server/src/janus_workbench/static",
    emptyOutDir: true,
  },
  fmt: {
    ignorePatterns: ["node_modules", "pnpm-lock.yaml", "test-results", ...GENERATED],
    sortPackageJson: {},
  },
  lint: {
    ignorePatterns: ["node_modules", "test-results", ...GENERATED],
    plugins: ["eslint", "oxc", "react", "unicorn", "typescript"],
    rules: {
      "eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },
  test: {
    include: ["src/**/*.test.ts"],
    environment: "node",
    allowOnly: !process.env["CI"],
    retry: 0,
  },
});
