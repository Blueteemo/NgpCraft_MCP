import { runStudio } from "./_studio_bridge.js";

export const definition = {
  name: "ngpc_studio_save",
  description:
    "Read what an NgpCraft Studio game has SAVED, by variable name: the save journal in the cartridge flash (two 8 KiB blocks at the " +
    "top of the chip, records of 256-byte pages, slots 0..2), each slot's newest record, whether it is signed by THIS build, and its " +
    "variables. Use it when a save 'does not work': a slot signed by another build is ignored by the ROM (If Data Saved false, Peek 0), " +
    "which is what any change to the project's saved state does to an older save. " +
    "Input: a .ngc/.ngp the emulator wrote the save into (NgpCraft Emulator's 'save in ROM' grows it to the chip size), or a save area " +
    "file (16 KiB raw, from ngpc_studio_run keep_flash_path, or an NgpCraft Emulator .flash), plus the `export` dir of the build " +
    "(ngpc_studio_check) for the signature and the variable names. Without export_dir, variables come back by index.",
  inputSchema: {
    type: "object",
    properties: {
      rom_path: { type: "string", description: "ROM file holding the save (written in place by the emulator)." },
      flash_path: { type: "string", description: "Save area: 16 KiB raw, or a .flash block file." },
      export_dir: { type: "string", description: "The build's `export` folder (signature, variable names)." },
    },
  },
};

export async function handler({ rom_path, flash_path, export_dir }) {
  if (!rom_path && !flash_path) throw new Error("give rom_path or flash_path");
  const args = rom_path ? ["--rom", rom_path] : ["--flash", flash_path];
  if (export_dir) args.push("--export", export_dir);
  return await runStudio("save", args, { timeoutMs: 60_000 });
}
