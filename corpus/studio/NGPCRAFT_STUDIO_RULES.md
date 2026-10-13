# NgpCraft Studio — rules for an agent writing a game

NgpCraft Studio is GB Studio 4.3.2 whose projects are compiled for the Neo Geo Pocket Color by the
NgpCraft V3 compiler. A project is a normal GB Studio project (`.gbsproj` + `project/**/*.gbsres` +
`assets/`), plus `ngpcraft.json` for NGPC settings. These rules come from building a complete
platformer (stages, bosses, menus, saves) with it; each says what to do and why.

## 1. Work loop

1. Write events with **`ngpc_studio_event`** first: never guess an event's JSON.
2. Validate with **`ngpc_studio_check`** after each edit (lint, per-scene budget, compile, ROM, save capacity).
3. Prove it with **`ngpc_studio_run`**: start on the scene, play a short scenario, LOOK at the screenshots
   and read the variables by name. A counter that says "done" is not a playable game; the picture is.
4. Saves: test across a power cycle (`reboot: true` in a run), read the slots with **`ngpc_studio_save`**.

## 2. Project files and event JSON

- An event: `{"command": "EVENT_X", "args": {...}, "children": {...}, "id": "<uuid>"}`. Nested scripts
  are `children` (`EVENT_IF`: `children.true` / `children.false`), never `args`. Every `id` is unique in
  the whole project: generate a fresh uuid for each copy of an event.
- Values: `{"type": "number", "value": 3}`, `{"type": "variable", "value": "12"}`; expressions nest
  (`{"type": "add", "valueA": ..., "valueB": ...}`). Conditions: `{"type": "eq", "valueA": ..., "valueB": ...}`.
- Variables are numbered "0".."511" in events; names live in `project/variables.gbsres`. The V3
  renumbers them when compiling: read them back BY NAME (the run/save tools do).
- Actors in events: an actor's id, `"$self$"` (the actor running the script) or `"player"`. A custom
  script's actor parameters are `"0"`, `"1"`... inside it, bound at the call
  (`EVENT_CALL_CUSTOM_EVENT` args `"$actor[0]$"`).
- After writing files, open the project in the editor (or run the official loader) once: it must load
  with no warning.

## 3. NGPC limits (per scene) and what to do at the limit

| Limit | Value | When reached |
|---|---|---|
| Screen | 160 x 152 (GB Studio: 160 x 144) | 8 more rows at the bottom; GB-sized screens get them black. |
| Tiles | 512 for background + sprites + text | A scene that prints text (Text Draw, dialogue) reserves 128 of them. Reuse sprite sheets across enemies, cut frames, split a scene. `ngpc_studio_check` budget shows each part. |
| Background palettes | 16 (15 when the scene prints text) | 3 colours + transparent each, per 8x8 tile. Too many colours: reduce the art; the compiler warns per tile. |
| Sprite palettes | 16 per scene | Recolour enemies/projectiles into shared palettes. A projectile used by a script exists in every scene of that script. |
| Hardware sprites | 64 on screen | Big sprites (bosses, wide UI) count fast. |
| Actors | `ngpcraft.json` `ngpc.actor_capacity` | Raise it for big scenes (the save state grows with it). |
| Triggers | 30 per scene (GB Studio) | Merge areas; one trigger per row of hazards, not per tile. |
| Scene size | 4095 tiles per axis | Over 255 tiles the whole game uses 32-bit positions (automatic). |
| Scripts | over 64 KB is fine | Spread over several banks automatically. |
| Frame rate | 60, or `ngpc.frame_rate: 30` | 30 = same speed in seconds, logic every other frame: a stable choice for heavy scenes. |

## 4. Rules (pitfalls that cost real time)

- **Trigger scripts run with the script engine locked (VM_LOCK).** A wait, a move or a dialogue in a
  trigger freezes the player. Keep trigger scripts instant; a death or door transition that ends with
  a scene change is fine. For "something happens when the player stands there", let an actor's update
  script test the player's position.
- **One Switch Scene per shared custom script.** The editor draws a link per Switch Scene of a script
  at every call site: a "player dies" script with 20 destinations called from 100 places makes the
  world view unusable. Switch to ONE relay scene (black screen) whose init reads a variable and
  switches to the right checkpoint.
- **Text Draw: redraw every visible text of the screen together, and pad lines.** Text tiles are
  reused in a loop; redrawing one line alone can corrupt another. A variable prints without padding
  (`$12$` with value 7 prints "7"): pad the line with spaces to its longest form, or the old text's
  last characters stay. In a text, a variable is `$12$` (its number), and `$00$`, not `$0$`.
- **Input scripts: `override` restarts the script on every frame the button is held** and hides the
  button from "If Input". Menus: override off. A running input script ignores new presses until it ends:
  keep it short (rapid fire).
- **OPTION on the NGPC is Start/Select:** a short press acts on RELEASE (`ngpc.option_long_press`
  decides which). There are no other buttons: d-pad, A, B, OPTION.
- **Animation speed is a frame mask:** 3, 7 or 15 give even steps; other values stutter.
- **Projectile offset: a positive Y offset is UP.**
- **Timers tick every 16 frames** in GBVM: a 48-frame phase is exact, 50 is not.
- **The scene stack reloads the scene on pop** (Scene Push / Pop State): a pause screen built that way
  brings the player back to the same place, but enemies and blocks restart. Use a variable to skip the
  scene's intro on the way back. No such pause in a boss room (the boss would come back full).
- **Wall slide (platformer):** the engine turns the player AWAY from the wall; draw the slide frame
  facing away from the wall it grips, or it shows inverted.
- **Ladders:** the player is centred on ONE 8 px ladder tile; a 16 px ladder is its left tile with
  LADDER collision (the top tile on both).

## 5. Saves on the NGPC

- A GB Studio save slot holds the WHOLE game state (variables, actors, scripts): often 2–5 KB. The
  NGPC save block has 32 pages of 256 bytes, 1 kept for recovery, so a big game fits ONE slot.
  `ngpc_studio_check` says how many fit (`build.save.slots_that_fit`).
- Several saved games in one slot: keep copies of the variables that last (cleared stages, upgrades,
  per-game "used" flag) in per-game variables, write them all with ONE Save Data, read a game back with
  Peek Data into the live variables. Continue = back to a hub/select screen (no scene resume needed).
- A save written by another build of the project is ignored (signature): after changing the saved
  state, old saves read as empty. Normal during development.
- The first save that fills a block erases one (about 1 s frozen on hardware): save on still screens
  (menus, after a boss), not in the middle of action.
- A LOGO scene cannot be in a game that saves (use an ordinary scene for a logo).

## 6. Recipes that work

- **Menus:** one variable for the cursor line; Up/Down change it (bounded) and call ONE "draw" custom
  script that redraws the whole menu (cursor marks, every line, messages). A sprite cursor (actor moved
  to the line) avoids text for the cursor.
- **HUD numbers and bars without text:** a pinned actor whose frame is the value (Set Actor Frame from a
  variable), redrawn only when the value changes.
- **Respawn at checkpoints:** checkpoint triggers set a variable; "player dies" = hide, wait, lives - 1,
  switch to the relay scene; the relay picks the checkpoint scene and position (or game over).
- **Crumbling platforms:** no trigger (it would freeze the player); the row's first block reads the
  player's position every 0.2 s (standing on it, inside its width), then hides the row pair by pair and
  brings it back on a timer.
- **Appearing blocks:** a scene timer advances a phase variable every 48 frames; each block group shows
  on its phases.

## 7. Testing with the tools

- `ngpc_studio_run` counts VIDEO frames (60 per second) on the native core with the cartridge's
  wait-states: a slow script shows as many frames of the same picture. A white screen of several
  seconds after the logo is a script doing too much work in one scene init (it was, once, every
  Peek Data rescanning the save journal).
- Start on the scene under test (`scene`), teleport the player next to what you test, hold the
  buttons, and look at the shot. Watch the variables that prove the behaviour (life, flags, menu line).
- Test a save: run, act, `reboot: true`, check the title offers to continue and the values came back.
