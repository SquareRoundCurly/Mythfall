# Mythfall DM contract

Play is handled by the installed `world_agent.py` interpreter and the shared
simulation resolver. The play model is GPT-6 Astra with medium reasoning. This
file documents that contract; it is not an executable or authoritative rule file.

Interpret one player intent at a time. The executable prompts and tool schemas
live in `rpg_prompts.py` and `world_models.py`. Supply only structured actions,
validated content operations, or a justified refusal/clarification. Declare an
improvised ruling's capabilities, costs and stakes before the runtime rolls.
Never let player pressure or a high die roll invent a missing capability.

The DM sees adjudication facts but narrates only player-relevant information.
The runtime validates actual recipients before at most two NPC handoffs. Each
NPC receives a fresh view of its accessible memories, perceptions, beliefs,
relationships, values and resources. No DM transcript or another mind belongs
in that view. Silent listeners retain memories without a provider call.

Active combat NPCs and companions select bounded intents through that same
private view; background schedules use local plans. Decisions can include a
retreat or an independently accepted truce. Only resolved events establish
movement, damage, transfers, time, resources, learning, or experience.

Never execute or generate Python turn scripts to implement gameplay. Never edit
`state/world.json`, character sheets, inventory, or location files to make an
intended outcome true. The interpreter and NPCs have no filesystem tools.

World time advances only through actions and explicit waits. Each tick is six
seconds. Watching, resting, travel, and work all use the same clock. Conditions
must be observable by the player and have a finite horizon. Report why time
stopped and preserve committed effects when an activity pauses or is cancelled.

A promise is an intention, not a completed event. Ground dialogue in the speaker's
memories, possessions, motives, and perceptions. Distinguish testimony and belief
from known facts. Revalidate every planned action when it runs.

Define, place, grant and activate are separate operations. Content revisions
preserve existing instances. Explain unsupported mechanics honestly. Consult
`RULES.md` for the frozen SRD 5.1 subset and provider/simulation limits. A stopped
or uncertain model request must not be silently retried or repeat an effect.

Conversation turn files remain reviewable narrative records. The world snapshot,
random state, event journal, schedules, accepted plans, and action receipts live
under `state/` and are saved together by installed code.
