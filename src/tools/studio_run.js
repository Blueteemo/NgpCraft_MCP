import { readFileSync } from "node:fs";
import { runStudio } from "./_studio_bridge.js";

export const definition = {
  name: "ngpc_studio_run",
  description:
    "PLAY an NgpCraft Studio game and LOOK at it: build a copy of the project that starts on a chosen scene (or reuse the `export` " +
    "dir of ngpc_studio_check), run it on the native NGPC core frame by frame (60 video frames per second, cartridge wait-states on), " +
    "follow a script of steps, and return per step the scene number, the player's position, the variables you `watch` BY NAME, and " +
    "screenshots as images you can see. Use it to prove a change works instead of assuming it: a menu, a pickup, a door, a boss, " +
    "a save that survives a power cycle. " +
    "Steps (JSON array, run in order): {frames: N, hold: 'RIGHT+A'} holds buttons for N frames (UP DOWN LEFT RIGHT A B OPTION; a menu " +
    "needs a press then frames without it: [{frames:4,hold:'A'},{frames:30}]); shot: true takes a picture after the step; " +
    "teleport: [x_px, y_px] moves the player; set: {VarName: value} writes variables; reboot: true power-cycles the console keeping " +
    "the cartridge's flash (the save). " +
    "Frames, not game ticks: a slow script shows as many frames of the same picture (a white screen while a title reads its save is a " +
    "frame count here). Uses the MCP's clean-room HLE BIOS unless bios_path is given. Variable names are the project's, " +
    "case-insensitive (Vie, VieMax...).",
  inputSchema: {
    type: "object",
    properties: {
      project_path: { type: "string", description: "The .gbsproj or its folder. Not needed with export_dir." },
      export_dir: { type: "string", description: "An `export` folder already built by ngpc_studio_check (fast: no rebuild). Starts on the project's start scene." },
      scene: { type: "string", description: "Start on this scene (its name or folder name) instead of the project's start scene. Builds a copy (about a minute for a big game)." },
      start_tiles: { type: "array", items: { type: "integer" }, minItems: 2, maxItems: 2, description: "Player start [x, y] in tiles in that scene." },
      steps: { type: "array", items: { type: "object" }, description: "The scenario (see the tool description). Default: 120 frames and a shot." },
      watch: { type: "array", items: { type: "string" }, description: "Variable names reported after every step." },
      all_variables: { type: "boolean", default: false, description: "Also return every named variable at the end." },
      out_dir: { type: "string", description: "Folder for the build and the PNGs (required)." },
      bios_path: { type: "string", description: "A real bios.bin instead of the HLE BIOS." },
      flash_path: { type: "string", description: "Start with this save area (16 KiB raw blocks, as written by keep_flash_path)." },
      keep_flash_path: { type: "string", description: "Write the save area here at the end (feed it to ngpc_studio_save or to a later run)." },
      max_images: { type: "integer", minimum: 0, maximum: 12, default: 4, description: "Screenshots returned as images (the last ones); all are written to out_dir." },
      v3_root: { type: "string", description: "NgpCraft V3 folder, when not the installed editor's." },
      toolchain_path: { type: "string", description: "Toshiba toolchain root." },
    },
    required: ["out_dir"],
  },
};

export async function handler({ project_path, export_dir, scene, start_tiles, steps, watch, all_variables, out_dir,
  bios_path, flash_path, keep_flash_path, max_images = 4, v3_root, toolchain_path }) {
  if (!project_path && !export_dir) throw new Error("give project_path or export_dir");
  const args = ["--out", out_dir];
  if (export_dir) args.push("--export", export_dir);
  else args.push("--project", project_path);
  if (scene) args.push("--scene", scene);
  if (start_tiles) args.push("--start", JSON.stringify(start_tiles));
  if (steps) args.push("--steps", JSON.stringify(steps));
  if (watch && watch.length) args.push("--watch", watch.join(","));
  if (all_variables) args.push("--all-vars");
  if (bios_path) args.push("--bios", bios_path);
  if (flash_path) args.push("--flash", flash_path);
  if (keep_flash_path) args.push("--keep-flash", keep_flash_path);
  if (toolchain_path) args.push("--toolchain", toolchain_path);
  const result = await runStudio("run", args, { v3Root: v3_root, timeoutMs: 900_000 });
  const shots = (result.shots || []).slice(-max_images);
  if (!result.ok || shots.length === 0) return result;
  const content = [{ type: "text", text: JSON.stringify(result, null, 2) }];
  for (const path of shots) {
    content.push({ type: "text", text: path });
    content.push({ type: "image", mimeType: "image/png", data: readFileSync(path).toString("base64") });
  }
  return { __mcp_content: content };
}
