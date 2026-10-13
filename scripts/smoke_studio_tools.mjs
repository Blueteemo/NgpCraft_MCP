// Smoke test of the ngpc_studio_* tools through their MCP handlers (not the Python alone):
//   node scripts/smoke_studio_tools.mjs <project .gbsproj or folder> <work dir> [<v3 root>]
// Each case asserts a CONTRACT on the answer (a field that must be there and make sense), so an
// answer that is merely non-empty does not pass. Needs the NgpCraft V3 (installed editor, NGPCRAFT_V3_HOME
// or the 3rd argument) and the Toshiba toolchain (NGPC_TOSHIBA_HOME or C:\t900).
import { mkdirSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";
import * as studio_event from "../src/tools/studio_event.js";
import * as studio_check from "../src/tools/studio_check.js";
import * as studio_run from "../src/tools/studio_run.js";
import * as studio_save from "../src/tools/studio_save.js";

const [project, work, v3] = process.argv.slice(2);
if (!project || !work) {
  console.error("usage: node scripts/smoke_studio_tools.mjs <project> <work dir> [<v3 root>]");
  process.exit(2);
}
mkdirSync(work, { recursive: true });
let failed = 0;
async function check(name, fn, contract) {
  const t = Date.now();
  try {
    const r = await fn();
    const problem = contract(r);
    if (problem) throw new Error(problem);
    console.log(`ok   ${name} (${((Date.now() - t) / 1000).toFixed(1)} s)`);
    return r;
  } catch (e) {
    failed++;
    console.log(`FAIL ${name}: ${String(e.message).slice(0, 600)}`);
    return null;
  }
}

await check("event: EVENT_IF has true/false children", () => studio_event.handler({ id: "EVENT_IF" }),
  (r) => (r.example?.children?.true && r.example?.children?.false ? null : "no children.true/false"));
await check("event: search 'save data'", () => studio_event.handler({ query: "save data" }),
  (r) => (r.results?.some((e) => e.id === "EVENT_SAVE_DATA") ? null : "EVENT_SAVE_DATA not found"));
await check("event: refused ones are listed", () => studio_event.handler({ status: "refused" }),
  (r) => (r.total > 0 ? null : "no refused event"));
const out = resolve(work, "check");
const c = await check("check: export + build", () => studio_check.handler({ project_path: project, out_dir: out, v3_root: v3 }),
  (r) => (!r.ok ? `${r.stage}: ${r.error}` : !r.build?.rom ? "no ROM" : !Array.isArray(r.budget) ? "no budget" : null));
if (c) {
  const exportDir = c.export.dir;
  const runOut = join(work, "run");
  const flash = join(runOut, "flash.bin");
  const r = await check("run: 4 s from the start scene, then a power cycle", () => studio_run.handler({
    export_dir: exportDir, out_dir: runOut, keep_flash_path: flash, v3_root: v3,
    steps: [{ frames: 240, shot: true }, { reboot: true, frames: 120, shot: true }],
  }), (r) => {
    const body = r.__mcp_content ? JSON.parse(r.__mcp_content[0].text) : r;
    if (!body.ok) return body.error;
    if (body.frames !== 360) return `frames ${body.frames}`;
    const images = (r.__mcp_content || []).filter((x) => x.type === "image");
    return images.length === 2 ? null : `${images.length} images`;
  });
  if (r && existsSync(flash)) {
    await check("save: reads the save area", () => studio_save.handler({ flash_path: flash, export_dir: exportDir }),
      (s) => (s.ok ? null : s.error));
  }
}
console.log(failed ? `${failed} failed` : "all ok");
process.exit(failed ? 1 : 0);
