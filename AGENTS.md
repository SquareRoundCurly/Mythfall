# Mythfall

The completed [open-ended RPG goal](https://github.com/SquareRoundCurly/PocketRealms/blob/main/docs/goals/goal_mythfall_open_ended_rpg.md)
extends the initial milestone. Preserve its validated behavior and recorded
limits when extending the catalog. The DM may author validated content and rulings;
the installed resolver owns their effects. NPC contexts contain only accessible
memories and perceptions, including after magical alteration. Test shared
mechanisms across different content sources rather than scripting example stories.

Follow [the milestone contract](https://github.com/SquareRoundCurly/PocketRealms/blob/main/docs/goals/goal_mythfall_world_simulation.md)
and preserve its recorded acceptance behavior.

The completed [game chat and touch goal](https://github.com/SquareRoundCurly/PocketRealms/blob/main/docs/goals/goal_mythfall_game_chat_and_touch.md)
adds a durable shared transcript. Record observable outcomes at the authoritative
action boundary, group activity continuations, and preserve effect-safe retries.

- World state, action resolution, schedules, and random state are authoritative
  runtime data. Agents submit bounded intents and narrate resolved events.
- Use one persisted simulation clock; conversational turns and rendered frames
  are not simulation ticks. Paused sessions never advance from wall-clock time.
- Fast-forward and ordinary advancement must produce equivalent state and
  ordered events with the same recorded decisions. Preserve interruption points.
- Player and NPC actions use the same rules. An item has exactly one physical
  location, independent of its social owner. Retries do not repeat transfers.
- Agent perceptions, visible scene projections, and wait predicates must respect
  what the observing character can know. Keep hidden facts out of NPC inputs.
- Backward compatibility and old saves are not required during pre-alpha. Preserve
  save/resume on the supported release. Keep rule execution in published module
  code and provider access in Model Gateway.
- Test meaningful mechanics with deterministic decisions, then run the actual
  Atlas browser and bounded live-agent acceptance. Save failure evidence.
- Game panels belong to the existing PWA dock and reuse its shared controls.
  Panel lifecycle must not own the world clock or submit duplicate actions.
- The main map follows a textured, top-down tabletop battle-map direction.
  Use reusable terrain/prop art and canonical geometry; keep actors, dropped
  items and doors separate. Verify initially hidden sprites in actual pixels.
