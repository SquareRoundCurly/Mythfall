# A Day in Emberwick acceptance

These observers are separate from the interpreter and NPC prompts. They drive
ordinary rendered controls, read canonical state independently, inspect Atlas
entities, and retain failures. No browser helper can teleport or change items.

## RPG milestone

Set `MYTHFALL_RPG_EVALUATION=1` when starting `local_server.py` to install the
Crowglass Ledger adventure. `rpg_adventure.mjs` exercises class selection,
recruitment, real skill checks, a four-participant encounter with live NPC
decisions, recovery, delivery, progression and save/reload. Its player budget is
65 actions and 42 live requests. It also checks Atlas error events; a successful
world-state assertion cannot hide a failed renderer.

`rpg_browser.mjs` covers refusal under pressure, DM handoff, ability pinning and
short-rest recovery on a separate fresh adventure. `rpg_mobile.mjs` runs against
a copy of a completed adventure and checks character/ability/party panels,
native touch panning, cancellation, pin persistence and pause acknowledgement.
Its delayed transport exercises an in-flight request; it does not fake world
state or simulated progress. Production ownership remains above the dock tabs.

`rpg_alternative.py <evidence> --gateway-env <protected file>` uses the same
public actions as the panels for a separate route. It supplies writing materials
and requests an actual NPC-authored letter; the recipient reads it before
deciding whether its terms suffice. Refusal may lead the player to wait for an
ordinary sleep schedule. `--resume-from <previous evidence>` copies a saved run
without editing its facts and retains the failed run. It also exercises live DM
content definition/placement and an actual consumable activation. The budget is
12 live requests and 70 public requests, including time continuations.

`rpg_minds_live.py <evidence> --gateway-env <protected file>` contrasts an NPC's
response before and after a validated memory alteration. It starts a fresh
model context and verifies canonical history remains separate from the mind.

The [RPG evidence](https://github.com/SquareRoundCurly/PocketRealms/blob/main/docs/validation/mythfall-rpg-2026-09-11/README.md)
records the shipped rules, measured budgets, failures and repairs. Its day
benchmark uses `install(new_world(seed=...))` with seven NPCs; the older benchmark
below retains the original five-NPC milestone and its own target.

Build the wheel and panels using the [repository instructions](../README.md).
Then start the pinned RealmEngine image with a fresh writable evidence directory
and the local evaluation transport. The [CI workflow](../.github/workflows/deploy.yml)
contains the exact container invocation. Set `MYTHFALL_UI_DIRECTORY` to the built
panel directory and `MYTHFALL_EVALUATION_WORKSPACE` to the evidence workspace.

Start the checksum-verified compiled browser host:

```sh
node .platform/host/serve.mjs .platform/host
MYTHFALL_EVIDENCE=/absolute/path/to/evidence node evaluation/panels.mjs
```

The host serves `/test/module-host.html` on port 4178 and proxies `/__module__/`
to the local game evaluation server on port 8831. The game owns its Playwright
installation; install Chromium with `npx playwright install chromium`.
`panels.mjs` needs no model calls and runs in ordinary CI. Other runners exercise
bounded live agent behavior and need a trusted gateway environment supplied only
to the server. Never put provider credentials in fixtures or the browser.

Run `browser.mjs` for the day-long scenario or `intervention.mjs` for the sword
intervention, second-item exchange, input, and narrow viewport scenario. Set
`MYTHFALL_EVIDENCE` to the absolute parent of the corresponding `workspace`.
Use a fresh fixture for each full run and retain failures.

`chat_touch.mjs` uses another fresh fixture and two bounded live Astra calls
to check the shared Game chat transcript, GUI/free-form actions, NPC replies,
rejection, activity continuation/pause, reload, and native camera alignment.
It sends actual Chromium touch gestures, including cancellation, two fingers,
dragging from labels, and tapping the next toolbar control. Camera operations
are checked against unchanged canonical state and the action request count.
Wait for the local server's `realm.observe` response before launching a runner;
starting Chromium while the server is still importing can lose its initial read.

The harness now mounts the production `WorkspaceEditor`, `Sidebar` and
`Dockspace`. Its local adapter handles workspace reads; layout persistence uses
local storage. Production sessions retain the existing server UI-state path.
`panels.mjs` uses a separate fresh fixture to test real docking, panel closure
during a pending wait, draft preservation, reload, phone layouts, and actual
WebGL pixels for a sword that starts hidden. This suite makes no model calls.

The acceptance host uses the installed Mythfall module hooks. Authentication
and the production WebSocket/restore fence have separate RealmEngine boundary
tests; this local host does not represent a deployed authentication test.

`generate_art.py` resumes the five persisted Fal jobs, skips installed assets,
and writes local artwork with complete prompts and provenance. It uses Model
Gateway and should not be run to regenerate assets during ordinary play.

The later battle-map art pass uses three prebuilt image sheets authored with
the built-in image generation tool; their prompts and hashes are under
`seed/assets/battlemap-v1/`. No image generation runs in the browser or per tick.

After an Atlas dependency or WASM rebuild, restart Vite: the symlinked dependency
is served under `node_modules`, outside the normal source watch path. Retain the
old run's evidence when repairing a problem, and start a new fixture for the
acceptance rerun. Run browser suites sequentially on constrained machines so
concurrent renderers do not distort latency measurements.
