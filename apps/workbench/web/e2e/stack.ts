// Starts `janus-workbench serve` once for the run, on an empty data directory, and returns the
// teardown that stops it and deletes the directory.
import { spawn } from "node:child_process";
import type { ChildProcess } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const SERVER = join(import.meta.dirname, "..", "..", "server");
const PORT = Number(process.env["JANUS_E2E_PORT"] ?? 8449);

const waitFor = async (url: string, child: ChildProcess) => {
  for (let i = 0; i < 120; i++) {
    if (child.exitCode !== null) throw new Error(`the server exited with ${child.exitCode}`);
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`${url} did not answer`);
};

export default async function stack() {
  const data = mkdtempSync(join(tmpdir(), "janus-e2e-"));
  const server = spawn("uv", ["run", "janus-workbench", "serve", "--port", String(PORT)], {
    cwd: SERVER,
    env: { ...process.env, JANUS_DATA_DIR: data },
    stdio: "inherit",
  });
  const stop = () => {
    server.kill("SIGTERM");
    rmSync(data, { recursive: true, force: true });
  };
  try {
    await waitFor(`http://127.0.0.1:${PORT}/api/documents`, server);
  } catch (error) {
    stop();
    throw error;
  }
  return stop;
}
