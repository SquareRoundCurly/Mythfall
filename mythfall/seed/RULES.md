# Mythfall RPG rules, catalog 1

Rules source: classic **SRD 5.1**, not the revised 2024 rules. Content IDs carry
explicit revisions (`@1`). A later definition never silently changes an existing
item or learned ability. Custom content uses the installed effect operations.

Mythfall 0.4.1 extends Light to two hours (1,200 six-second turns), retaining
one illuminated object per caster. This is a deliberate Mythfall balance change
from the SRD duration. The release resets prior worlds during pre-alpha.

## Characters

Fighter, Rogue, Cleric and Wizard support character levels 1–3, the Champion,
Thief, Life Domain and School of Evocation subclasses, and multiclassing among
these classes. XP thresholds are 0, 300 and 900. Multiclassing checks the ability
score prerequisites of both existing and new classes. Slots combine caster
levels; learned/prepared spells still follow each individual class level.

Skills, expertise, saving throw proficiencies, fighting styles, Second Wind,
Action Surge, Sneak Attack, Cunning Action, Fast Hands, improved climbing,
Channel Divinity, Disciple of Life, Arcane Recovery and Sculpt Spells run through
installed rules. Evocation Savant reduces copying time and arcane ink costs.
Physical spell sources and inks are required to copy additional wizard spells.

Existing saves keep their six scores, identity, possessions, authored HP floor
and history. The first class choice supplies a starter kit once. This preserves
legacy characters whose original HP exceeds a normal first-level build.
Additional levels use average hit-die increases. Existing saves are never rebuilt
from the seed.

Active session computers retain the module version they started with. New
realms use the deployed version; existing saves migrate when their session is
deactivated and reactivated with the current runtime. Reloading the browser
alone does not replace that runtime. Updated browser panels keep earlier
sessions playable and identify features that require the new module.

## Clock and encounters

One tile is five feet. Movement uses the current cardinal grid and Manhattan
distance. An ordinary action outside combat usually takes one six-second tick.
Inspecting, selecting panels, reading game state, and inference take no game time.

Combat has at most eight participants, rolled initiative, one action, bonus
action, reaction, and a movement allowance per turn. There are explicit Shield,
Protection and opportunity-attack decisions; saves preserve a pending reaction
between its trigger and resolution. The clock advances once per completed round,
not once per participant. A requested opening attack rolls initiative first;
the attacker may have to wait for their turn. An offered truce ends the encounter only after every living participant agrees;
renewed aggression clears the offers. Combatants do not also act through
ordinary routines. NPCs and companions choose tactics through their own model
views; the engine enforces conditions, costs and legal targets.

Short rests take an uninterrupted hour; selected hit dice heal, and short-rest
resources refresh. Long rests take eight hours and restore HP, spell slots and
half the character's hit dice (minimum one), at most once per day. Partial or
cancelled rests do not restore resources. World-time midnight refreshes the
once-per-day Arcane Recovery use; a short rest is still required to activate it.
The world pauses while a session is inactive. Only nearby, conscious companions
join a party rest; recently recovered companions cannot gain a second long-rest
benefit. Stable unconscious characters recover 1 HP after a recorded 1d4 hours;
unstable party members make death saves as turns or world ticks advance.

## Frozen starting content

Cantrips: Light, Mage Hand, Guidance, Fire Bolt, Sacred Flame.

Level 1: Magic Missile, Shield, Mage Armor, Detect Magic, Burning Hands,
Thunderwave, Bless, Cure Wounds, Healing Word, Sanctuary, Command.

Level 2: Aid, Lesser Restoration, Spiritual Weapon, Hold Person, Misty Step,
Invisibility. Life Domain spells in these levels are included. The candidate
list's Grease, Sleep and Feather Fall are deferred; the engine must reject or
explain an unsupported effect, including a proposed spell with such mechanics.

Equipment includes melee and ranged weapons, ammunition, light/medium/heavy
armor, shields, rope, lanterns/oil, thieves' tools, healer's kits, rations,
writing materials, spellcasting foci, arcane inks and containers. Magic items:
Potion of Healing, Longsword +1, Cloak of Protection, Wand of Magic Detection,
Bag of Holding. Availability in the catalog does not grant ownership.

The inventory retains Mythfall's compact load units, not SRD pounds. This is a
small 2D world: no vertical flight/falling simulation, full grapple physics,
mounted rules, spell countering, or complete SRD spell/class catalog. Cones and
cubes use grid cells. Help currently supports skill checks. Improved climbing
is supported, but jumping and vertical features need a future movement extension.
Armor changes commit at the action boundary and charge their donning time; this
iteration does not model partially donned armor if that time is interrupted. Somatic or material casting requires a free hand; material
components represented in a definition require a carried focus. Armor or shields
without proficiency prevent casting and disadvantage STR/DEX checks and attacks. Expensive
material components and gold trade are not implied by a spell name.

## Shared effects and minds

Damage/healing, needs/resources, conditions, movement, light/sound, doors and
connections, destructible structures, beliefs, memories, identities,
relationships and thoughts have installed operations. Definitions with
unsupported fields or effect kinds are rejected. The same origin/target/effect
refreshes instead of stacking with itself. Expiry removes the effect; it does
not undo possessions, movement or other consequences that occurred meanwhile.

Normal vision, hearing around corners, barriers, language, whisper range and
telepathic delivery determine reception. A silent listener still receives a
memory. Physical letters retain location, seal state, contents and read state;
carrying a sealed letter alone reveals no contents. Canonical history is separate
from NPC memory. Memory alteration suppresses selected memories and dependent
knowledge, thoughts and relationship contributions, and invalidates plans.
Changed identities use opaque action references in NPC and browser views.

Background plans and schedules execute locally. Scheduled effect chains use a
stable queue, preserve unfinished jobs across saves, and record causal events.
There are at most 64 active schedules and 64 reactions per processing chunk;
individual failed jobs roll back their effects and retain failure records.
The DM can create, cancel or replace schedules through installed operations.

The DM can refuse, clarify, adjudicate, declare a checked ruling, define content,
place an item, grant an earned ability, approve values and award progression.
Rulings declare stakes before consuming dice. Acquisitions cite a real event
and an in-world reason; a player's request is not an acquisition. Reusing an
operation ID returns its original receipt. Plain narration creates no effects.

## Acceptance budgets (frozen before live runs)

- Active encounter: 8 actors; party: 4 members.
- Conversation: 1 DM decision and at most 2 NPC handoffs, depth 1. Direct NPC
  GUI speech selects that NPC; the DM can route free-form speech to listeners.
- Per provider decision: at most 3,000 output tokens, 90-second timeout, no
  automatic retry after an uncertain result. Record actual token usage.
- Client continuation: at most 8 NPC decisions per user action, then yield.
- Simulation advancement: at most 300 ticks per request; schedules as above.
- Local deterministic action p95 target: under 2 seconds. One day of background
  advancement target: under 30 seconds for the shipped adventure.
- Pause: stop initiating work on the next browser event; target under 250 ms.
  A submitted model call may finish within its 90-second bound; pause prevents
  the next call/chunk and does not roll back a committed decision. Consequence continuations also yield
  after 8 browser requests; unfinished work remains saved.

## Attribution

This work includes material taken from the System Reference Document 5.1
(“SRD 5.1”) by Wizards of the Coast LLC and available at
https://dnd.wizards.com/resources/systems-reference-document. The SRD 5.1 is
licensed under the Creative Commons Attribution 4.0 International License
available at https://creativecommons.org/licenses/by/4.0/legalcode.

Implementation notes and descriptions above are adapted for this supported
software subset. Rules source:
https://media.dndbeyond.com/compendium-images/srd/5.1/SRD_CC_v5.1.pdf
