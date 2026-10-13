"""NgpCraft Studio (GB Studio projects compiled for the NGPC by the NgpCraft V3) for an agent.

    python ngpc_studio.py check --project P [--out DIR] [--no-build] [--v3 DIR] [--toolchain DIR]
    python ngpc_studio.py run   --project P --out DIR [--scene NAME] [--steps JSON] [--bios FILE] ...
    python ngpc_studio.py save  (--rom FILE | --flash FILE) --export DIR

Prints one JSON document. The V3 is found as the editor finds it: --v3, NGPCRAFT_V3_HOME, the copy
bundled with an installed NgpCraft Studio (%LOCALAPPDATA%/ngpcraft_studio/app-*/resources/ngpcraft-v3/v3).
The emulator is the MCP's own (vendor/emulator). No machine-specific path is written here.
"""
import argparse
import glob
import json
import os
import random
import re
import shutil
import struct
import sys
import tempfile
import traceback
import zlib
from collections import OrderedDict
from pathlib import Path

HERE = Path(__file__).resolve().parent
MCP_ROOT = HERE.parent.parent.parent
EMULATOR = MCP_ROOT / "vendor" / "emulator"
HLE_BIOS = EMULATOR / "hle_bios" / "bios_hle.bin"


# ------------------------------------------------------------------ locating the V3
def installed_v3():
    """The V3 bundled with an installed NgpCraft Studio (Windows Squirrel install), newest first."""
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return None
    found = sorted(glob.glob(os.path.join(base, "ngpcraft_studio", "app-*", "resources", "ngpcraft-v3", "v3")),
                   reverse=True)
    return found[0] if found else None


def find_v3(explicit):
    for candidate in (explicit, os.environ.get("NGPCRAFT_V3_HOME"), installed_v3()):
        if candidate and (Path(candidate) / "ngpcraft").is_dir():
            return str(Path(candidate).resolve())
    raise SystemExit(json.dumps({"ok": False, "error": "NgpCraft V3 not found: pass v3_root, set NGPCRAFT_V3_HOME, "
                                 "or install NgpCraft Studio (its V3 copy is used)."}))


def use_v3(explicit):
    root = find_v3(explicit)
    if root not in sys.path:
        sys.path.insert(0, root)
    return root


def toolchain_home(explicit):
    return explicit or os.environ.get("NGPC_TOSHIBA_HOME") or os.environ.get("THOME") or (
        "C:\\t900" if os.name == "nt" else "")


def project_root(path):
    p = Path(path)
    if p.is_file() and p.suffix.lower() == ".gbsproj":
        return p.parent, p
    if p.is_dir():
        projs = sorted(p.glob("*.gbsproj"))
        if projs:
            return p, projs[0]
    raise SystemExit(json.dumps({"ok": False, "error": f"no .gbsproj at {path}"}))


# ------------------------------------------------------------------ reading a project
def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def walk_events(events):
    """Every event of a script, children included (depth first)."""
    for e in events or []:
        if not isinstance(e, dict):
            continue
        yield e
        for sub in (e.get("children") or {}).values():
            yield from walk_events(sub)


def load_resources(root):
    """scenes (with their actors / triggers), custom scripts, prefabs: as GB Studio 4 stores them."""
    res = {"scenes": [], "scripts": {}, "actorPrefabs": {}, "triggerPrefabs": {}}
    for sp in sorted((root / "project" / "scenes").glob("*/scene.gbsres")):
        scene = read_json(sp)
        scene["_actors"] = [read_json(a) for a in sorted((sp.parent / "actors").glob("*.gbsres"))]
        scene["_triggers"] = [read_json(t) for t in sorted((sp.parent / "triggers").glob("*.gbsres"))]
        scene["_folder"] = sp.parent.name
        res["scenes"].append(scene)
    for f in sorted((root / "project").rglob("*.gbsres")):
        try:
            data = read_json(f)
        except Exception:
            continue
        kind = data.get("_resourceType")
        if kind == "script":
            res["scripts"][data["id"]] = data
        elif kind in ("actorPrefab", "triggerPrefab"):
            res[kind + "s"][data["id"]] = data
    return res


BLOCKING = {"EVENT_WAIT", "EVENT_ACTOR_MOVE_TO", "EVENT_ACTOR_MOVE_RELATIVE", "EVENT_TEXT", "EVENT_CHOICE",
            "EVENT_MENU", "EVENT_CAMERA_MOVE_TO", "EVENT_CAMERA_LOCK", "EVENT_FADE_IN", "EVENT_FADE_OUT",
            "EVENT_ACTOR_EFFECTS", "EVENT_CAMERA_SHAKE", "EVENT_AWAIT_INPUT", "EVENT_WAIT_FRAMES"}


def lint(res):
    """GB Studio habits that misbehave (or cost a lot) on the NGPC / in NgpCraft Studio; each finding says
    where, why and what to do. Rules learnt on a full platformer."""
    findings = []
    scripts = res["scripts"]

    def blocking_in(events, seen=()):
        for e in walk_events(events):
            cmd = e.get("command")
            if cmd in BLOCKING:
                return cmd
            if cmd == "EVENT_CALL_CUSTOM_EVENT":
                sid = (e.get("args") or {}).get("customEventId")
                if sid in scripts and sid not in seen:
                    inner = blocking_in(scripts[sid].get("script"), seen + (sid,))
                    if inner:
                        return f"{inner} (in custom script {scripts[sid].get('name')})"
        return None

    def trigger_scripts():
        for scene in res["scenes"]:
            for t in scene["_triggers"]:
                pref = res["triggerPrefabs"].get(t.get("prefabId") or "")
                for key in ("script", "leaveScript"):
                    yield scene, t, key, (t.get(key) or (pref or {}).get(key) or [])

    def leaves_scene(events, seen=()):
        for e in walk_events(events):
            cmd = e.get("command")
            if cmd in ("EVENT_SWITCH_SCENE", "EVENT_SCENE_POP_STATE", "EVENT_SCENE_POP_ALL_STATE", "EVENT_LOAD_DATA"):
                return True
            if cmd == "EVENT_CALL_CUSTOM_EVENT":
                sid = (e.get("args") or {}).get("customEventId")
                if sid in scripts and sid not in seen and leaves_scene(scripts[sid].get("script"), seen + (sid,)):
                    return True
        return False

    # R1: a trigger's script runs with the VM locked
    for scene, t, key, script in trigger_scripts():
        hit = blocking_in(script)
        if hit:
            transition = leaves_scene(script)
            findings.append({"rule": "trigger-script-waits", "severity": "info" if transition else "warning",
                             "where": f"scene '{scene.get('name')}' trigger '{t.get('name')}' {key}",
                             "found": hit + (" (then the scene changes)" if transition else ""),
                             "why": "GB Studio runs a trigger's script with the script engine locked (VM_LOCK): the "
                                    "player is frozen until it ends, so a wait or a move makes the game stop"
                                    + (" — fine for a transition (death, door, cutscene)." if transition else "."),
                             "fix": "Keep trigger scripts instant (set variables, start something); put waits in an "
                                    "actor's update script or a timer, or test the condition from an actor instead."})
    # R2: switch-scene fan-out in a shared script
    calls = {}
    for scene in res["scenes"]:
        holders = [scene.get("script")] + [a.get(k) for a in scene["_actors"] for k in
                                           ("script", "startScript", "updateScript", "hit1Script", "hit2Script",
                                            "hit3Script")] + [t.get("script") for t in scene["_triggers"]]
        for h in holders:
            for e in walk_events(h):
                if e.get("command") == "EVENT_CALL_CUSTOM_EVENT":
                    sid = (e.get("args") or {}).get("customEventId")
                    calls[sid] = calls.get(sid, 0) + 1
    for sid, s in scripts.items():
        switches = sum(1 for e in walk_events(s.get("script")) if e.get("command") == "EVENT_SWITCH_SCENE")
        if switches >= 2 and calls.get(sid, 0) >= 2:
            findings.append({"rule": "shared-script-many-switches", "severity": "warning",
                             "where": f"custom script '{s.get('name')}'",
                             "found": f"{switches} Switch Scene, called from {calls[sid]} places",
                             "why": "The editor draws one link per Switch Scene of each script at every call site "
                                    f"(here about {switches * calls[sid]}): the world view becomes unusable (one game "
                                    "reached 1964 links).",
                             "fix": "Switch to ONE relay scene (a black screen whose init picks the destination from a "
                                    "variable), so the shared script holds a single Switch Scene."})
    # R3: variables printed in a Text Draw
    for scene in res["scenes"]:
        holders = [("scene", scene.get("script"))] + [(f"actor '{a.get('name')}'", a.get(k)) for a in scene["_actors"]
                                                       for k in ("script", "startScript", "updateScript")]
        for who, h in holders:
            for e in walk_events(h):
                if e.get("command") == "EVENT_TEXT_DRAW" and re.search(r"\$[^$]+\$", str((e.get("args") or {}).get("text"))):
                    findings.append({"rule": "text-draw-variable-width", "severity": "info",
                                     "where": f"scene '{scene.get('name')}' {who}",
                                     "found": (e["args"]["text"])[:60],
                                     "why": "A variable prints with no padding ($00$ writes 7, not 07); a shorter "
                                            "redraw leaves the old text's last characters on screen.",
                                     "fix": "Pad each line with spaces to its longest form, and redraw every visible "
                                            "text of the screen together (text tiles are reused in a loop)."})
                    break
    # R4: input scripts with override
    for scene in res["scenes"]:
        for e in walk_events(scene.get("script")):
            if e.get("command") == "EVENT_SET_INPUT_SCRIPT" and (e.get("args") or {}).get("override"):
                findings.append({"rule": "input-override-repeats", "severity": "info",
                                 "where": f"scene '{scene.get('name')}'",
                                 "found": f"input {e['args'].get('input')} with override",
                                 "why": "With override, GBVM restarts the script on every frame the button is held "
                                        "(and hides the button from 'If Input'): a menu cursor races, a held fire "
                                        "button cannot be read.",
                                 "fix": "Use override only for a script that must run while held; menus: override off."})
    return findings


def scene_summary(res):
    out = []
    for s in res["scenes"]:
        out.append({"name": s.get("name"), "folder": s["_folder"], "type": s.get("type"),
                    "size_tiles": [s.get("width"), s.get("height")], "actors": len(s["_actors"]),
                    "triggers": len(s["_triggers"])})
    return out


# ------------------------------------------------------------------ warnings, grouped
def group_warnings(warnings, examples=2):
    """V3 export warnings by kind (paths and numbers stripped), with a count and a few examples."""
    groups = OrderedDict()
    for w in warnings or []:
        text = str(w)
        key = re.sub(r"project/\S+", "<file>", text)
        key = re.sub(r"\[[0-9]+\]|\d+(\.\d+)?", "#", key)
        key = re.sub(r"'[^']*'", "'…'", key)[:160]
        g = groups.setdefault(key, {"count": 0, "examples": []})
        g["count"] += 1
        if len(g["examples"]) < examples:
            g["examples"].append(text[:400])
    return [{"kind": k, **v} for k, v in groups.items()]


# ------------------------------------------------------------------ check
def cmd_check(a):
    v3 = use_v3(a.v3)
    from ngpcraft.compiler import CompileError
    from ngpcraft.pipeline import export_project
    root, gbsproj = project_root(a.project)
    out = Path(a.out) if a.out else Path(tempfile.mkdtemp(prefix="ngpc_studio_"))
    export = out / "export"
    if export.exists():
        shutil.rmtree(export)
    res = load_resources(root)
    findings = lint(res)
    summary = {}
    for f in findings:
        k = f"{f['rule']} ({f['severity']})"
        summary[k] = summary.get(k, 0) + 1
    # warnings first, then a few infos of each rule: the summary has the counts
    shown, per_rule = [], {}
    for f in sorted(findings, key=lambda f: f["severity"] != "warning"):
        per_rule[f["rule"]] = per_rule.get(f["rule"], 0) + 1
        if f["severity"] == "warning" or per_rule[f["rule"]] <= 3:
            shown.append(f)
    report = {"ok": True, "v3_root": v3, "project": str(gbsproj), "out": str(out),
              "scenes": scene_summary(res), "lint_summary": summary, "lint": shown[:40]}
    try:
        from ngpcraft.scene_budget import project_budget
        budget = project_budget(str(root))
        report["budget"] = [{"name": s.get("name"), "used_tiles": s.get("used_tiles"),
                             "tile_limit": s.get("tile_limit"), "over": s.get("over"),
                             "background_tiles": s.get("background_tiles"), "sprite_tiles": s.get("sprite_tiles"),
                             "text_reserve": s.get("text_reserve"), "background_palettes": s.get("background_palettes"),
                             "errors": s.get("errors")} for s in budget.get("scenes", [])]
        report["budget_over"] = [b["name"] for b in report["budget"] if b["over"] or b["errors"]]
    except Exception as exc:  # the budget is an estimate; the export below is the authority
        report["budget_error"] = f"{type(exc).__name__}: {exc}"
    try:
        manifest = export_project(str(root), str(export))
    except Exception as exc:
        report.update(ok=False, stage="export", error=f"{type(exc).__name__}: {exc}"[:6000])
        if "unknown NGPC extension" in str(exc) or "unknown field" in str(exc):
            report["hint"] = ("The project uses NgpCraft settings this V3 does not know: it is older than the editor "
                              "that wrote the project. Point v3_root (or NGPCRAFT_V3_HOME) to a newer V3, or update "
                              "NgpCraft Studio.")
        return report
    report["export"] = {"dir": str(export),
                        "script_bytes": sum(v.get("bytes", 0) for v in manifest.get("scripts", {}).values()),
                        "variables": len(manifest.get("variables", {})),
                        "warnings": group_warnings(manifest.get("warnings"))}
    if a.no_build:
        return report
    from ngpcraft.toolchain import build_rom
    try:
        build = build_rom(str(export), toolchain_home(a.toolchain) or None)
    except CompileError as exc:
        report.update(ok=False, stage="build", error=str(exc))
        return report
    rom = export / "rom" / "game.ngc"
    rep = {"rom": str(rom), "size_bytes": build["header"]["size_bytes"],
           "cartridge_mbit": next(c for c in (4, 8, 16) if build["header"]["size_bytes"] <= c * 0x20000),
           "features": build.get("features")}
    save = build.get("save")
    if save:
        pages = save["pages_per_slot"]
        rep["save"] = {**save, "slots_that_fit": min(3, (32 - 1) // pages),
                       "note": "A GB Studio save slot holds the WHOLE game state; the NGPC save block has 32 pages "
                               "of 256 bytes (1 kept for recovery). Several games in one slot: keep copies of the "
                               "variables that last and Peek them back."}
    report["build"] = rep
    return report


# ------------------------------------------------------------------ the emulator
def machine_for(rom, bios):
    sys.path.insert(0, str(EMULATOR))
    from core import native
    m = native.NativeMachine(rom, bios=Path(bios).read_bytes())
    m.set_timing_silicon(word_wait=10, bios_wait=8)
    return m


def power_on(m, flash=None, flash_at=None):
    m.reset(bios_handoff=True)
    if flash is not None:
        m.flash_restore(flash_at, flash)
    rng = random.Random(0x5EED)            # a console's RAM is not zero at power on
    m.write(0x4000, bytes(rng.randrange(256) for _ in range(0x6C00 - 0x4000)))


def save_blocks_at(rom_len):
    chip = next((c for c in (0x80000, 0x100000, 0x200000) if rom_len <= c), 0x200000)
    return 0x200000 + chip - 0x8000


BUTTONS = {"UP": 1, "DOWN": 2, "LEFT": 4, "RIGHT": 8, "A": 16, "B": 32, "OPTION": 64}


def pad_bits(hold):
    bits = 0
    for b in filter(None, str(hold or "").upper().replace(" ", "").split("+")):
        if b not in BUTTONS:
            raise SystemExit(json.dumps({"ok": False, "error": f"unknown button {b}: {sorted(BUTTONS)}"}))
        bits |= BUTTONS[b]
    return bits


def png_bytes(pixels, w=160, h=152):
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for p in pixels[y * w:(y + 1) * w]:
            raw += bytes(((p & 15) * 17, ((p >> 4) & 15) * 17, ((p >> 8) & 15) * 17))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


class Vars:
    """GB Studio variables by name (the export's table: the V3 renumbers them)."""

    def __init__(self, export, m, symbols):
        manifest = read_json(export / "export.json")
        self.table = {k.upper(): v for k, v in manifest.get("variables", {}).items()}
        self.m, self.base = m, symbols["_script_memory"]["address"]

    def slot(self, name):
        key = name.upper()
        for k in (key, "VAR_" + key, "VAR_" + re.sub(r"[^A-Z0-9]+", "_", key)):
            if k in self.table:
                return self.table[k]
        raise SystemExit(json.dumps({"ok": False, "error": f"unknown variable {name}",
                                     "variables": sorted(self.table)[:200]}))

    def get(self, name):
        return int.from_bytes(self.m.read(self.base + 2 * self.slot(name), 2), "little", signed=True)

    def set(self, name, value):
        self.m.write(self.base + 2 * self.slot(name), int(value).to_bytes(2, "little", signed=True))

    def all(self):
        return {k[4:] if k.startswith("VAR_") else k: int.from_bytes(self.m.read(self.base + 2 * v, 2), "little",
                                                                        signed=True)
                for k, v in sorted(self.table.items(), key=lambda kv: kv[1])}


def run_copy(root, scene, out, at):
    """A copy of the project that starts on `scene` (its name, or its folder name), at tile (x, y) if given."""
    res = load_resources(root)
    match = [s for s in res["scenes"] if scene in (s.get("name"), s["_folder"], s.get("id"))]
    if not match:
        raise SystemExit(json.dumps({"ok": False, "error": f"no scene {scene!r}",
                                     "scenes": [s.get("name") for s in res["scenes"]]}))
    copy = out / "project"
    if copy.exists():
        shutil.rmtree(copy)
    shutil.copytree(root, copy, ignore=shutil.ignore_patterns("build", "build_export", "*.ngc"))
    sp = copy / "project" / "settings.gbsres"
    st = read_json(sp)
    st["startSceneId"] = match[0]["id"]
    if at:
        st["startX"], st["startY"] = at
    sp.write_text(json.dumps(st, indent=2), encoding="utf-8")
    return copy


def cmd_run(a):
    use_v3(a.v3)
    from ngpcraft.compiler import CompileError
    from ngpcraft.pipeline import export_project
    from ngpcraft.toolchain import build_rom
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.export:
        export = Path(a.export)
    else:
        root, _ = project_root(a.project)
        src = run_copy(root, a.scene, out, json.loads(a.start) if a.start else None) if a.scene else root
        export = out / "export"
        if export.exists():
            shutil.rmtree(export)
        try:
            export_project(str(src), str(export))
            build_rom(str(export), toolchain_home(a.toolchain) or None)
        except CompileError as exc:
            return {"ok": False, "stage": "build", "error": str(exc)}
    rom = (export / "rom" / "game.ngc").read_bytes()
    build = read_json(export / "rom" / "build-report.json")
    symbols = build["link_audit"]["public_symbols"]
    bios = a.bios or (str(HLE_BIOS) if HLE_BIOS.exists() else None)
    if not bios:
        return {"ok": False, "error": "no BIOS: pass bios_path (a real bios.bin)"}
    m = machine_for(rom, bios)
    flash_at = save_blocks_at(len(rom))
    flash = Path(a.flash).read_bytes() if a.flash else None
    power_on(m, flash, flash_at)
    names = Vars(export, m, symbols)
    wide = "unsigned long act_x" in (export / "src" / "scene_actors.c").read_text(encoding="utf-8", errors="replace")
    size = 4 if wide else 2

    def player():
        return [int.from_bytes(m.read(symbols[s]["address"], size), "little") >> 5 for s in ("_act_x", "_act_y")]

    steps = json.loads(a.steps) if a.steps else [{"frames": 120, "shot": True}]
    frame, shots, log = 0, [], []
    watch = [w for w in (a.watch or "").split(",") if w]
    for i, step in enumerate(steps):
        if step.get("reboot"):
            blocks = m.read(flash_at, 0x4000)
            power_on(m, blocks, flash_at)
        for name, value in (step.get("set") or {}).items():
            names.set(name, value)
        if step.get("teleport"):
            x, y = step["teleport"]
            for s, v in (("_act_x", x), ("_act_y", y)):
                m.write(symbols[s]["address"], (int(v) << 5).to_bytes(size, "little"))
        bits = pad_bits(step.get("hold"))
        for _ in range(int(step.get("frames", 0))):
            m.write(0x00B0, bytes([bits]))
            m.run_frames(1)
            frame += 1
        entry = {"step": i, "frame": frame, "scene": m.read(symbols["_ngc_scene"]["address"], 1)[0],
                 "player_px": player()}
        if watch:
            entry["vars"] = {w: names.get(w) for w in watch}
        if step.get("shot"):
            path = out / f"shot_{len(shots):02d}_f{frame}.png"
            path.write_bytes(png_bytes(m.framebuffer()))
            entry["shot"] = str(path)
            shots.append(str(path))
        log.append(entry)
    result = {"ok": True, "export": str(export), "bios": "real" if a.bios else "hle", "frames": frame,
              "steps": log, "shots": shots, "timing": "silicon wait-states, video frames (60 per second)"}
    if a.all_vars:
        result["variables"] = names.all()
    if a.keep_flash:
        Path(a.keep_flash).write_bytes(m.read(flash_at, 0x4000))
        result["flash_saved"] = a.keep_flash
    return result


# ------------------------------------------------------------------ save
MAGIC, HEADER, PAGE, PAGES = b"NGS1", 22, 256, 32


def crc16(data, crc=0xFFFF):
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def journal_records(blocks):
    recs = []
    for b in range(2):
        data = blocks[b * 0x2000:(b + 1) * 0x2000]
        page = 0
        while page < PAGES:
            at = page * PAGE
            if data[at:at + PAGE] == b"\xff" * PAGE:
                page += 1
                continue
            head = data[at:at + HEADER]
            plausible = head[0:4] == MAGIC and 1 <= head[6] <= PAGES
            step = head[6] if plausible and page + head[6] <= PAGES else 1
            raw = data[at:at + step * PAGE]
            if plausible and len(raw) == step * PAGE:
                kind, slot, length = raw[4], raw[5], int.from_bytes(raw[16:18], "little")
                ok = (kind in (1, 2) and slot < 3 and raw[7] == 0 and raw[-1] == 0
                      and raw[20] == raw[18] ^ 0xFF and raw[21] == raw[19] ^ 0xFF
                      and crc16(raw[HEADER:-1], crc16(raw[0:18])) == int.from_bytes(raw[18:20], "little"))
                if ok:
                    recs.append({"block": b, "page": page, "kind": kind, "slot": slot, "pages": step,
                                 "sequence": int.from_bytes(raw[8:12], "little"),
                                 "signature": int.from_bytes(raw[12:16], "little"),
                                 "data": raw[HEADER:HEADER + length]})
            page += step
    return recs


def cmd_save(a):
    if a.rom:
        rom = Path(a.rom).read_bytes()
        at = save_blocks_at(len(rom)) - 0x200000
        if len(rom) < at + 0x4000:
            return {"ok": True, "slots": {}, "note": "this ROM file holds no save area (never saved in place)"}
        blocks = rom[at:at + 0x4000]
    elif Path(a.flash).stat().st_size == 0x4000:      # the two raw 8 KiB save blocks (run's keep_flash)
        blocks = Path(a.flash).read_bytes()
    else:                                             # NgpCraft Emulator's .flash (block file)
        sys.path.insert(0, str(EMULATOR))
        from core import flash_file
        parts = flash_file.read(Path(a.flash))
        if not parts:
            return {"ok": True, "slots": {}, "note": "empty .flash"}
        base = min(addr for addr, _ in parts) & ~0x3FFF
        buf = bytearray(b"\xff" * 0x4000)
        for addr, data in parts:
            off = addr - base
            if 0 <= off < 0x4000:
                buf[off:off + len(data)] = data[:0x4000 - off]
        blocks = bytes(buf)
    export = Path(a.export) if a.export else None
    signature, table = None, {}
    if export:
        game = (export / "src" / "game.c").read_text(encoding="utf-8", errors="replace")
        m = re.search(r"ngc_save_signature = 0x([0-9A-Fa-f]{8})ul;", game)
        signature = int(m[1], 16) if m else None
        table = read_json(export / "export.json").get("variables", {})
    recs = journal_records(blocks)
    best = {}
    for r in recs:
        cur = best.get(r["slot"])
        if cur is None or ((r["sequence"] - cur["sequence"]) & 0xFFFFFFFF) < 0x80000000:
            best[r["slot"]] = r
    slots = {}
    for slot, r in sorted(best.items()):
        entry = {"kind": "state" if r["kind"] == 1 else "cleared", "sequence": r["sequence"],
                 "bytes": len(r["data"]), "pages": r["pages"],
                 "signature": f"{r['signature']:08X}"}
        if signature is not None:
            entry["matches_this_build"] = r["signature"] == signature
        if r["kind"] == 1:
            words = [int.from_bytes(r["data"][12 + 2 * i:14 + 2 * i], "little", signed=True)
                     for i in range(max(table.values(), default=63) + 1) if 14 + 2 * i <= len(r["data"])]
            if table:
                entry["variables"] = {(k[4:] if k.startswith("VAR_") else k): words[v]
                                      for k, v in sorted(table.items(), key=lambda kv: kv[1]) if v < len(words)}
            else:
                entry["variables_by_index"] = words
        slots[slot] = entry
    note = None
    if signature is not None and any(not s.get("matches_this_build", True) for s in slots.values()):
        note = ("A slot signed by another build is IGNORED by this ROM (If Data Saved false, Peek 0): the game "
                "starts as on a blank cartridge after any change to the project's saved state.")
    return {"ok": True, "records": len(recs), "slots": slots, **({"note": note} if note else {})}


# ------------------------------------------------------------------ main
def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--project", required=True)
    c.add_argument("--out")
    c.add_argument("--no-build", action="store_true")
    c.add_argument("--v3")
    c.add_argument("--toolchain")
    r = sub.add_parser("run")
    r.add_argument("--project")
    r.add_argument("--export")
    r.add_argument("--out", required=True)
    r.add_argument("--scene")
    r.add_argument("--start")
    r.add_argument("--steps")
    r.add_argument("--watch")
    r.add_argument("--all-vars", action="store_true")
    r.add_argument("--bios")
    r.add_argument("--flash")
    r.add_argument("--keep-flash")
    r.add_argument("--v3")
    r.add_argument("--toolchain")
    s = sub.add_parser("save")
    s.add_argument("--rom")
    s.add_argument("--flash")
    s.add_argument("--export")
    a = p.parse_args()
    try:
        result = {"check": cmd_check, "run": cmd_run, "save": cmd_save}[a.cmd](a)
    except SystemExit as exc:          # the explained refusals above carry their JSON
        if isinstance(exc.code, str) and exc.code.startswith("{"):
            print(exc.code)
            return
        raise
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-2000:]}
    print(json.dumps(result, indent=1, default=str))


if __name__ == "__main__":
    main()
