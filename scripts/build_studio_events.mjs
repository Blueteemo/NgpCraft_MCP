// Builds src/data/studio_events.json: the GB Studio event catalogue an agent needs to write
// NgpCraft Studio projects by hand (scene / actor / trigger / script .gbsres files).
//
//   node scripts/build_studio_events.mjs <NgpCraft Studio source root> [<ngpcraft-v3 root>]
//
// <NgpCraft Studio source root>: the editor's sources (a GB Studio 4.3.2 fork): its
//   src/lib/events/event*.js define each event's fields; src/lang/en.json their texts.
// <ngpcraft-v3 root> (default <studio root>/ngpcraft-v3): ngpcraft/parity/gbstudio.json gives
//   each event's NGPC status (identical / adapted / refused).
// Nothing machine-specific is written: paths only come from the arguments.

import { readFileSync, readdirSync, writeFileSync, renameSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const here = dirname(fileURLToPath(import.meta.url));
const studio = process.argv[2] && resolve(process.argv[2]);
if (!studio) {
  console.error("usage: node scripts/build_studio_events.mjs <NgpCraft Studio source root> [<ngpcraft-v3 root>]");
  process.exit(2);
}
const v3 = resolve(process.argv[3] || join(studio, "ngpcraft-v3"));
const eventsDir = join(studio, "src", "lib", "events");
const en = JSON.parse(readFileSync(join(studio, "src", "lang", "en.json"), "utf8"));
const parity = JSON.parse(readFileSync(join(v3, "ngpcraft", "parity", "gbstudio.json"), "utf8")).events;

// l10n(key, params): the English text, {placeholders} kept.
const l10n = (key) => (typeof key === "string" && en[key]) || key;
const stubs = {
  "../helpers/l10n": { default: l10n, __esModule: true },
  "shared/lib/scriptValue/types": { isConstScriptValue: (v) => !!v && v.type === "number" },
};

function load(file) {
  const code = readFileSync(join(eventsDir, file), "utf8");
  const module = { exports: {} };
  const require = (name) => {
    if (name in stubs) return stubs[name];
    throw new Error(`${file}: unexpected require ${name}`);
  };
  vm.runInNewContext(code, { module, exports: module.exports, require, console }, { filename: file });
  return module.exports;
}

// The fields as a project file stores them: groups / tabs flattened; "events" fields are the
// event's CHILDREN (event.children[key]), every other key goes in event.args[key].
function flatten(fields, out = []) {
  for (const f of fields || []) {
    if (Array.isArray(f.fields) && !f.key) {
      flatten(f.fields, out);
      continue;
    }
    if (!f.key) continue;
    const field = { key: f.key, type: f.type || "text" };
    for (const k of ["label", "description"]) if (f[k]) field[k] = l10n(f[k]);
    if (f.defaultValue !== undefined) field.default = f.defaultValue;
    for (const k of ["min", "max", "step", "unitsField", "unitsDefault", "unitsAllowed", "multiple", "filter"]) {
      if (f[k] !== undefined && typeof f[k] !== "function") field[k] = f[k];
    }
    if (Array.isArray(f.options)) field.options = f.options.map((o) => (Array.isArray(o) ? [o[0], l10n(o[1])] : o));
    if (Array.isArray(f.conditions)) field.conditions = f.conditions;
    if (f.type === "events") field.children = true;
    out.push(field);
  }
  return out;
}

const cleanNote = (s) =>
  String(s || "")
    .replace(/\s*\((?:docs\/|tools\/|tests\/)[^)]*\)/g, "")
    .replace(/\s*docs\/[A-Z0-9_]+\.md(?:\s*§\s*\S+)?/g, "")
    .trim();

const events = {};
for (const file of readdirSync(eventsDir).filter((f) => /^event.*\.js$/.test(f)).sort()) {
  let def;
  try {
    def = load(file);
  } catch (e) {
    console.error(`skip ${file}: ${e.message}`);
    continue;
  }
  if (!def || !def.id) continue;
  const fields = flatten(def.fields);
  const args = {};
  const children = {};
  for (const f of fields) {
    if (f.children) children[f.key] = [];
    else if (f.default !== undefined && f.type !== "break" && f.type !== "label") args[f.key] = f.default;
  }
  const p = parity[def.id];
  events[def.id] = {
    id: def.id,
    name: l10n(def.id),
    description: l10n(def.description) || "",
    groups: (def.groups || []).map(l10n),
    deprecated: !!def.deprecated,
    fields: fields.filter((f) => f.type !== "break" && f.type !== "label"),
    example: { command: def.id, args, ...(Object.keys(children).length ? { children } : {}), id: "<unique uuid>" },
    ngpc: p
      ? { status: { identique: "identical", adapte: "adapted", refuse: "refused" }[p.status] || p.status,
          note_fr: cleanNote(p.partiel || p.note || p.ecart || "") }
      : { status: "ngpc-only", note_fr: "" },
  };
}

const out = join(here, "..", "src", "data", "studio_events.json");
const doc = {
  about: "GB Studio 4.3.2 events as NgpCraft Studio project files store them (event = {command, args, children?, id}), " +
    "with each event's NGPC status from the NgpCraft V3 compiler. Field texts: GB Studio (MIT).",
  count: Object.keys(events).length,
  events,
};
writeFileSync(out + ".tmp", JSON.stringify(doc, null, 1));
renameSync(out + ".tmp", out);
const by = {};
for (const e of Object.values(events)) by[e.ngpc.status] = (by[e.ngpc.status] || 0) + 1;
console.log(`${doc.count} events ->`, out, by);
