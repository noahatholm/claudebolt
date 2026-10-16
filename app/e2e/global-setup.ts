// Starts a real engine (`claudebolt serve`) on fixture media for the UI end-to-end tests.
// Needs uv and ffmpeg on PATH, like the engine's own tests.
import { execFileSync, spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ENGINE = resolve(HERE, "../../engine");

function stop(pid: number | undefined) {
  if (!pid) return;
  // uv starts the engine as a child process, so stop the whole tree.
  if (process.platform === "win32") {
    try {
      execFileSync("taskkill", ["/pid", String(pid), "/T", "/F"], { stdio: "ignore" });
    } catch {
      /* already gone */
    }
  } else {
    try {
      process.kill(-pid, "SIGTERM");
    } catch {
      /* already gone */
    }
  }
}

export default async function globalSetup() {
  const root = mkdtempSync(join(tmpdir(), "cbolt-e2e-"));
  const env = { ...process.env, CLAUDEBOLT_CACHE: join(root, "cache"), CLAUDEBOLT_CONFIG: join(root, "config") };
  const media = join(root, "media");
  execFileSync("uv", ["run", "--directory", ENGINE, "python", resolve(HERE, "seed.py"), media], {
    env,
    stdio: ["ignore", "ignore", "inherit"],
  });

  const engine = spawn("uv", ["run", "--directory", ENGINE, "claudebolt", "serve", "--port", "0"], {
    env,
    stdio: ["ignore", "pipe", "inherit"],
    detached: process.platform !== "win32",
  });
  const first = await new Promise<string>((ok, fail) => {
    const timer = setTimeout(() => fail(new Error("engine did not start within 120 s")), 120_000);
    createInterface({ input: engine.stdout! }).once("line", (line) => {
      clearTimeout(timer);
      ok(line);
    });
    engine.once("exit", (code) => fail(new Error(`engine exited early (${code})`)));
  });
  const { port, token } = JSON.parse(first) as { port: number; token: string };
  // Workers inherit the environment: this is how the specs find the engine and the media.
  process.env.CB_E2E = JSON.stringify({ port, token, media });

  return () => {
    stop(engine.pid);
    rmSync(root, { recursive: true, force: true, maxRetries: 5 });
  };
}
