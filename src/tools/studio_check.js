import { runStudio } from "./_studio_bridge.js";

export const definition = {
  name: "ngpc_studio_check",
  description:
    "Check an NgpCraft Studio project (a GB Studio 4.3.2 project, .gbsproj, compiled for the NGPC by the NgpCraft V3) in ONE call, " +
    "and build its ROM. Run it after every edit of the project files. Returns: " +
    "`lint` — GB Studio habits that misbehave or cost a lot on the NGPC (trigger scripts that wait: the player freezes, VM_LOCK; " +
    "a shared script with several Switch Scene called from many places; Text Draw of variables that are not padded; input scripts with " +
    "override), each with where / why / fix; " +
    "`budget` — per scene tiles used of 512 (background, sprites, text reserve) and palettes, `budget_over` lists the scenes that do not fit; " +
    "`export` — the V3 compile (refusals come back as `error` with the file and event path), script bytes, variables, its warnings grouped " +
    "by kind with a count; " +
    "`build` — ROM path and size, cartridge size, and `save`: pages per save slot and how many slots fit (a GB Studio slot is the whole " +
    "game state; often only one fits). Pass `out_dir` to keep the export (ngpc_studio_run and ngpc_studio_save take its `export` dir). " +
    "Needs the NgpCraft V3 (an installed NgpCraft Studio is found automatically; else v3_root / NGPCRAFT_V3_HOME) and, to build, the " +
    "Toshiba toolchain (toolchain_path / NGPC_TOSHIBA_HOME, default C:\\t900). A big project takes about a minute. " +
    "An error saying 'unknown NGPC extension' means the V3 is older than the editor that wrote the project.",
  inputSchema: {
    type: "object",
    properties: {
      project_path: { type: "string", description: "The project's .gbsproj, or its folder." },
      out_dir: { type: "string", description: "Folder for the export and ROM (default: a new temp folder). Its `export` subfolder is replaced." },
      build: { type: "boolean", default: true, description: "Also link the ROM (needs the Toshiba toolchain). false = lint, budget and compile only." },
      v3_root: { type: "string", description: "NgpCraft V3 folder (the one holding `ngpcraft/`), when not the installed editor's." },
      toolchain_path: { type: "string", description: "Toshiba toolchain root (holds BIN/cc900.exe...)." },
    },
    required: ["project_path"],
  },
};

export async function handler({ project_path, out_dir, build = true, v3_root, toolchain_path }) {
  const args = ["--project", project_path];
  if (out_dir) args.push("--out", out_dir);
  if (!build) args.push("--no-build");
  if (toolchain_path) args.push("--toolchain", toolchain_path);
  return await runStudio("check", args, { v3Root: v3_root, timeoutMs: 900_000 });
}
