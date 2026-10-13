import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
let catalogue = null;
function load() {
  if (!catalogue) {
    catalogue = JSON.parse(readFileSync(join(__dirname, "..", "data", "studio_events.json"), "utf8"));
  }
  return catalogue;
}

export const definition = {
  name: "ngpc_studio_event",
  description:
    "The exact JSON of a GB Studio event for NgpCraft Studio projects (GB Studio 4.3.2 compiled for the NGPC by the NgpCraft V3). " +
    "USE IT BEFORE WRITING ANY EVENT into a .gbsres file by hand: an event is {command, args, children?, id} and its args keys, value shapes " +
    "({type:'number',value:..}, {type:'variable',value:'12'}, actor ids, '$self$'...) and child scripts (children.true / children.false, not args) " +
    "are what agents get wrong. Each entry gives: every field (key, type, default, min/max, options, units), a valid example to copy " +
    "(replace id with a fresh uuid), and the NGPC status: identical (as in GB Studio), adapted (works, with the difference in note_fr), " +
    "refused (the V3 will not compile it), ngpc-only (NgpCraft additions). " +
    "Call with `id` for one event (EVENT_IF, EVENT_ACTOR_SET_POSITION...), or `query` to search names/descriptions, optionally `group` " +
    "(Actor, Scene, Variables, Control Flow...) and `status`. 156 events.",
  inputSchema: {
    type: "object",
    properties: {
      id: { type: "string", description: "Exact event id, e.g. EVENT_SET_VALUE. Returns the full entry." },
      query: { type: "string", description: "Words to find in the id, name or description (all must match), e.g. 'save data' or 'camera shake'." },
      group: { type: "string", description: "Only events of this GB Studio group (case-insensitive substring), e.g. 'actor'." },
      status: { type: "string", enum: ["identical", "adapted", "refused", "ngpc-only"], description: "Only events with this NGPC status." },
      limit: { type: "integer", minimum: 1, maximum: 60, default: 20, description: "Max results of a search." },
    },
  },
};

export async function handler({ id, query, group, status, limit = 20 }) {
  const cat = load();
  if (id) {
    const key = id.toUpperCase().startsWith("EVENT_") ? id.toUpperCase() : `EVENT_${id.toUpperCase()}`;
    const e = cat.events[key];
    if (e) return e;
    return { error: `no event ${key}`, hint: "search with `query`", close: Object.keys(cat.events).filter((k) => k.includes(key.slice(6, 12))).slice(0, 10) };
  }
  const words = (query || "").toLowerCase().split(/\s+/).filter(Boolean);
  const hits = Object.values(cat.events).filter((e) => {
    const text = `${e.id} ${e.name} ${e.description}`.toLowerCase();
    return words.every((w) => text.includes(w)) &&
      (!group || e.groups.some((g) => g.toLowerCase().includes(group.toLowerCase()))) &&
      (!status || e.ngpc.status === status);
  });
  return {
    total: hits.length,
    results: hits.slice(0, limit).map((e) => ({ id: e.id, name: e.name, groups: e.groups, ngpc: e.ngpc.status,
                                                description: e.description.slice(0, 160) })),
    next: hits.length > limit ? "narrow the query or raise limit; call with `id` for fields and an example" : "call with `id` for fields and an example",
  };
}
