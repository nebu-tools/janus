// The three screens driven in a browser against the real server: `janus-workbench serve` with the
// built client and a data directory of its own. `pnpm e2e` builds the client first.
import { defineConfig } from "@playwright/test";

const PORT = Number(process.env["JANUS_E2E_PORT"] ?? 8449);

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: process.env["CI"] ? [["list"], ["html", { open: "never" }]] : "list",
  globalSetup: "./e2e/stack.ts",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
