# Mythfall: The Crowglass Ledger

A persistent, turn-based village rendered in Atlas. Create a character in Chat,
then use the map, inventory, portrait conversations, and time controls. Arrow
keys move one tile; map clicks travel. Language actions use the same rules.

Game chat, World, Character, Abilities, Party & initiative, Inventory,
Conversation, Actions & time, and Journal are PWA
dock panels, using the same controls as the editor. Open or close them from the
sidebar, drag their tabs to arrange them, or use the map's panel shortcuts.
Selecting a person opens Conversation; selecting an object opens Inventory.
Game chat is the shared record: describe any intent to the DM there. Inventory,
map, conversation and ability controls submit actions to the same world rules.
Select a party character in Abilities, or pin their abilities as a separate tab.
Closing a panel does not stop an activity: use Pause in the map toolbar or
Actions & time. New phone layouts show one full-width tab at a time.

Leave your sword in the square and watch for someone to collect it. NPCs have
ordinary motives and routines; pickup is not guaranteed. Objects keep their
identity through transfers, conversations, saves, and reloads.

- `characters/`, `locations/`, and `quests/` contain authored setting material and
  legacy character creation data. Existing files are preserved during migration.
- `state/world.json` is the installed simulation's canonical versioned snapshot:
  clock, seeded randomness, actors, item locations, events, minds, beliefs,
  schedules, effects, class resources, authored definitions, party, initiative,
  reactions, bounded plans, pending waits, and operation receipts.
- `state/model_calls/` retains provider-call outcomes and usage. A retry does not
  repeat an accepted effect or silently repeat an uncertain paid model request.
- `scene/mythfall.json` and `game.json` are player-visible Atlas projections.
- `assets/portraits/` contains locally stored Fal artwork and provenance.
- `assets/battlemap-v1/` contains terrain, prop and character texture sheets,
  their prompts and provenance, and derived glTF geometry. The scenery follows
  the canonical wall grid; actors, items and doors retain independent entities.
- `turns/` retains conversation records. Conversation numbers are not world ticks.

The world pauses between player actions and while a session is closed. Each tick
is six seconds. Long actions yield in chunks of at most thirty simulated minutes;
Pause stops after the current chunk. Interrupted or saved activities can be
continued or cancelled. NPC work, meals, rest, and movement run locally without
per-tick inference. Model Gateway supplies bounded Astra interpretation/dialogue.

Choose Fighter, Rogue, Cleric or Wizard in Character. Explore, recruit a willing
companion, and recover the original mine ledger for Mara Vell. The watchkeepers
want their unpaid wages settled; negotiation, stealth, distractions and fighting
can have different consequences. A truce needs every surviving participant's
agreement. Companions make their own choices and can disagree with your tactics.

Skills, saves and rolls have recorded consequences. Earn XP and take levels up
to character level 3, including the supported subclass or multiclass choices.
Use short or long rests to recover; these advance actual world time. NPCs keep
their own memories, needs, values and relationships, and act on what they know.

The DM can refuse impossible requests, resolve improvised attempts, and author
items or powers using supported effects. A requested item is not automatically
granted, and narration alone cannot change the world. See [RULES.md](RULES.md)
for the exact classic SRD 5.1 subset, limits, deviations and attribution.
