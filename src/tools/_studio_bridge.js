// Shared helper of the ngpc_studio_* tools: runs src/tools/studio/ngpc_studio.py (check / run / save)
// with a Python that can import the NgpCraft V3 compiler, and parses its JSON answer.
//
// Where things are found (first found wins), the same order as NgpCraft Studio itself:
//   V3:     the tool's v3_root argument, NGPCRAFT_V3_HOME, the copy bundled with an installed
//           NgpCraft Studio (%LOCALAPPDATA%/ngpcraft_studio/app-*/resources/ngpcraft-v3/v3).
//   Python: NGPCRAFT_PYTHON, the Python bundled next to that installed V3 (it has the V3's
//           dependencies), else python / python3 on PATH.
//   Toshiba toolchain (to build a ROM): the tool's toolchain_path, NGPC_TOSHIBA_HOME, THOME, C:\t900.

import { spawn } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
export const STUDIO_SCRIPT = join(__dirname, "studio", "ngpc_studio.py");

function installedApp() {
  const base = process.env.LOCALAPPDATA;
  if (!base) return null;
  const root = join(base, "ngpcraft_studio");
  if (!existsSync(root)) return null;
  const apps = readdirSync(root).filter((d) => d.startsWith("app-")).sort().reverse();
  for (const app of apps) {
    const v3 = join(root, app, "resources", "ngpcraft-v3");
    if (existsSync(join(v3, "v3", "ngpcraft"))) return v3;
  }
  return null;
}

// { python, v3 }: v3 is passed explicitly to the script so both sides agree.
export function locate(v3Root) {
  const explicit = v3Root || process.env.NGPCRAFT_V3_HOME;
  if (explicit) {
    return { python: process.env.NGPCRAFT_PYTHON || (process.platform === "win32" ? "python" : "python3"),
             v3: resolve(explicit) };
  }
  const app = installedApp();
  if (app) {
    const bundled = join(app, "python", "python.exe");
    return { python: process.env.NGPCRAFT_PYTHON || (existsSync(bundled) ? bundled : "python"),
             v3: join(app, "v3") };
  }
  return { python: process.env.NGPCRAFT_PYTHON || (process.platform === "win32" ? "python" : "python3"), v3: null };
}

export function runStudio(cmd, args = [], { v3Root, timeoutMs = 600_000 } = {}) {
  const { python, v3 } = locate(v3Root);
  const full = [STUDIO_SCRIPT, cmd, ...args];
  if (v3 && cmd !== "save") full.push("--v3", v3);
  return new Promise((res, rej) => {
    const child = spawn(python, full, { windowsHide: true });
    let out = "";
    let err = "";
    let timedOut = false;
    const to = setTimeout(() => {
      timedOut = true;
      child.kill("SIGTERM");
    }, timeoutMs);
    child.stdout.on("data", (d) => (out += d.toString()));
    child.stderr.on("data", (d) => (err += d.toString()));
    child.on("error", (e) => {
      clearTimeout(to);
      rej(new Error(`Failed to start Python (${python}): ${e.message}. Set NGPCRAFT_PYTHON.`));
    });
    child.on("close", (code) => {
      clearTimeout(to);
      if (timedOut) return rej(new Error(`ngpc_studio ${cmd} timed out after ${timeoutMs} ms`));
      try {
        res(JSON.parse(out));
      } catch (e) {
        rej(new Error(`ngpc_studio ${cmd} exited ${code} without JSON.\nstderr: ${err.slice(-3000)}\nstdout: ${out.slice(-3000)}`));
      }
    });
  });
}
