"""Versioned, executable starting content. See RULES.md for the supported subset."""

from copy import deepcopy

CATALOG_VERSION = "srd51-mythfall-1"
CLASSES = {
    "fighter": {"name": "Fighter", "hit_die": 10, "saves": ["str", "con"], "skill_count": 2,
        "skills": ["acrobatics", "animal_handling", "athletics", "history", "insight", "intimidation", "perception", "survival"],
        "armor": ["light", "medium", "heavy", "shield"], "weapons": ["simple", "martial"], "subclass": "champion", "subclass_level": 3},
    "rogue": {"name": "Rogue", "hit_die": 8, "saves": ["dex", "int"], "skill_count": 4,
        "skills": ["acrobatics", "athletics", "deception", "insight", "intimidation", "investigation", "perception", "performance", "persuasion", "sleight_of_hand", "stealth"],
        "armor": ["light"], "weapons": ["simple", "longsword", "rapier", "shortsword", "shortbow", "hand_crossbow"], "subclass": "thief", "subclass_level": 3},
    "cleric": {"name": "Cleric", "hit_die": 8, "saves": ["wis", "cha"], "skill_count": 2,
        "skills": ["history", "insight", "medicine", "persuasion", "religion"], "casting": "wis",
        "armor": ["light", "medium", "shield"], "weapons": ["simple"], "subclass": "life", "subclass_level": 1},
    "wizard": {"name": "Wizard", "hit_die": 6, "saves": ["int", "wis"], "skill_count": 2,
        "skills": ["arcana", "history", "insight", "investigation", "medicine", "religion"], "casting": "int",
        "armor": [], "weapons": ["dagger", "quarterstaff", "light_crossbow", "sling", "dart"], "subclass": "evocation", "subclass_level": 2},
}
SPELL_SLOTS = {0: [], 1: [2], 2: [3], 3: [4, 2]}
XP_THRESHOLDS = [0, 300, 900]


def power(key, name, *, level=0, classes=(), effects=(), **options):
    return {"id": "ability." + key + "@1", "type": "ability", "version": 1, "name": name,
        "description": options.pop("description", name), "level": level, "classes": list(classes),
        "economy": "action", "range": 1, "target": "creature", "max_targets": 1,
        "resolution": "automatic", "effects": list(effects), "spell": bool(classes),
        "components": ["v", "s"] if classes else [], "school": "evocation", **options}


def condition(name, duration):
    return {"kind": "condition", "condition": name, "duration": duration}


def hurt(expression, damage_type):
    return {"kind": "damage", "dice": expression, "damage_type": damage_type}


POWERS = [
    power("second_wind", "Second Wind", economy="bonus", target="self", mechanic="second_wind", resource="second_wind"),
    power("action_surge", "Action Surge", economy="free", target="self", mechanic="action_surge", resource="action_surge"),
    power("cunning_dash", "Cunning Action: Dash", economy="bonus", target="self", mechanic="dash"),
    power("cunning_disengage", "Cunning Action: Disengage", economy="bonus", target="self", mechanic="disengage"),
    power("cunning_hide", "Cunning Action: Hide", economy="bonus", target="self", mechanic="hide"),
    power("fast_hands", "Fast Hands", economy="bonus", target="object", mechanic="fast_hands", description="Use a mundane object or thieves' tools as a bonus action."),
    power("turn_undead", "Channel Divinity: Turn Undead", range=6, target="area", radius=6, max_targets=12,
        mechanic="turn_undead", resolution="save", save="wis", resource="channel_divinity", hostile=True),
    power("preserve_life", "Channel Divinity: Preserve Life", range=6, max_targets=4,
        mechanic="preserve_life", resource="channel_divinity"),
    power("arcane_recovery", "Arcane Recovery", economy="rest", target="self", mechanic="arcane_recovery", resource="arcane_recovery"),
    power("light", "Light", classes=["cleric", "wizard"], mechanic="light", target="object", duration=600),
    power("mage_hand", "Mage Hand", classes=["wizard"], mechanic="mage_hand", target="point", range=6, duration=10, school="conjuration"),
    power("guidance", "Guidance", classes=["cleric"], school="divination", concentration=True,
        effects=[{"kind": "check_bonus", "dice": "1d4", "duration": 10, "once": True}]),
    power("fire_bolt", "Fire Bolt", classes=["wizard"], range=24, resolution="attack", hostile=True,
        effects=[hurt("1d10", "fire")]),
    power("sacred_flame", "Sacred Flame", classes=["cleric"], range=12, resolution="save", save="dex", hostile=True,
        effects=[hurt("1d8", "radiant")]),
    power("magic_missile", "Magic Missile", level=1, classes=["wizard"], range=24, max_targets=4, hostile=True, mechanic="magic_missile"),
    power("shield", "Shield", level=1, classes=["wizard"], economy="reaction", target="self", school="abjuration",
        effects=[condition("shielded", 1)]),
    power("mage_armor", "Mage Armor", level=1, classes=["wizard"], school="abjuration", effects=[condition("mage_armor", 4800)]),
    power("detect_magic", "Detect Magic", level=1, classes=["cleric", "wizard"], school="divination", target="self",
        concentration=True, effects=[condition("detect_magic", 100)]),
    power("burning_hands", "Burning Hands", level=1, classes=["wizard"], range=3, target="cone", radius=3, max_targets=12,
        resolution="save", save="dex", half_save=True, hostile=True, effects=[hurt("3d6", "fire")], upcast="1d6"),
    power("thunderwave", "Thunderwave", level=1, classes=["wizard"], range=3, target="cube", radius=3, max_targets=12,
        resolution="save", save="con", half_save=True, hostile=True, effects=[hurt("2d8", "thunder")], upcast="1d8", mechanic="thunderwave"),
    power("bless", "Bless", level=1, classes=["cleric"], range=6, max_targets=3, concentration=True, school="enchantment",
        effects=[{"kind": "check_bonus", "dice": "1d4", "duration": 10, "attack": True},
                 {"kind": "check_bonus", "dice": "1d4", "duration": 10, "saving": True}]),
    power("cure_wounds", "Cure Wounds", level=1, classes=["cleric"], effects=[{"kind": "heal", "dice": "1d8"}],
        add_casting=True, upcast="1d8"),
    power("healing_word", "Healing Word", level=1, classes=["cleric"], range=12, economy="bonus", components=["v"],
        effects=[{"kind": "heal", "dice": "1d4"}], add_casting=True, upcast="1d4"),
    power("sanctuary", "Sanctuary", level=1, classes=["cleric"], range=6, economy="bonus", school="abjuration",
        effects=[condition("sanctuary", 10)]),
    power("command", "Command", level=1, classes=["cleric"], range=12, components=["v"], school="enchantment",
        resolution="save", save="wis", hostile=True, mechanic="command"),
    power("aid", "Aid", level=2, classes=["cleric"], range=6, max_targets=3, school="abjuration",
        mechanic="aid", effects=[{"kind": "max_hp", "amount": 5, "duration": 4800}]),
    power("lesser_restoration", "Lesser Restoration", level=2, classes=["cleric"], school="abjuration", mechanic="restoration"),
    power("spiritual_weapon", "Spiritual Weapon", level=2, classes=["cleric"], range=12, economy="bonus",
        target="point", mechanic="spiritual_weapon"),
    power("spiritual_strike", "Spiritual Weapon: Strike", economy="bonus", range=1, resolution="attack", hostile=True,
        mechanic="spiritual_strike", effects=[hurt("1d8", "force")], add_casting=True),
    power("hold_person", "Hold Person", level=2, classes=["cleric", "wizard"], range=12, concentration=True,
        school="enchantment", resolution="save", save="wis", hostile=True, species="humanoid",
        effects=[condition("paralyzed", 10)], repeat_save="wis"),
    power("misty_step", "Misty Step", level=2, classes=["wizard"], range=6, economy="bonus", components=["v"],
        school="conjuration", target="point", mechanic="misty_step"),
    power("invisibility", "Invisibility", level=2, classes=["wizard"], school="illusion", concentration=True,
        effects=[condition("invisible", 600)], breaks_on="attack_or_spell"),
]

for _power in POWERS:
    if _power["id"] in {"ability.light@1", "ability.mage_armor@1", "ability.bless@1", "ability.sanctuary@1", "ability.aid@1", "ability.hold_person@1", "ability.invisibility@1"}:
        _power["components"] = ["v", "m"] if _power["id"] == "ability.light@1" else ["v", "s", "m"]

DESCRIPTIONS = {
    "second_wind": "Recover 1d10 + Fighter level HP using a bonus action. Refreshes on a short rest.",
    "action_surge": "Take one additional action this turn. Refreshes on a short rest.",
    "cunning_dash": "Spend a bonus action to add your speed to this turn's movement.",
    "cunning_disengage": "Spend a bonus action to move without provoking opportunity attacks this turn.",
    "cunning_hide": "Make a Stealth check from concealment using a bonus action.",
    "fast_hands": "Use a mundane object or thieves' tools as a bonus action. Cannot activate a magic item.",
    "turn_undead": "Undead within 30 feet make a Wisdom save or must flee for up to one minute; damage ends the turning.",
    "preserve_life": "Share 5 × Cleric level healing among nearby creatures, up to half each creature's maximum HP.",
    "arcane_recovery": "After a short rest, recover spell slots whose levels total up to half Wizard level, rounded up; once per day.",
    "light": "Make a visible object illuminate nearby darkness for one hour. One lit object per caster.",
    "mage_hand": "Summon a spectral hand, then use it to move small unattended objects. It cannot attack or activate magic items.",
    "guidance": "Concentrate to add 1d4 to the recipient's next ability check within one minute.",
    "fire_bolt": "Ranged spell attack dealing 1d10 fire damage.",
    "sacred_flame": "A creature makes a Dexterity save or takes 1d8 radiant damage.",
    "magic_missile": "Three darts deal 1d4 + 1 force damage each, shared among chosen targets. Shield blocks them; a higher slot adds a dart.",
    "shield": "React to a hit or Magic Missile. Gain 5 AC until your next turn and block Magic Missile.",
    "mage_armor": "An unarmored creature gains base AC 13 + Dexterity for eight hours.",
    "detect_magic": "Concentrate to identify magical auras on visible objects within 30 feet for ten minutes.",
    "burning_hands": "A 15-foot cone deals 3d6 fire damage, halved by a Dexterity save. A higher slot adds 1d6.",
    "thunderwave": "A 15-foot cube deals 2d8 thunder damage, halved by a Constitution save. Failed saves also push creatures away; the noise carries.",
    "bless": "Concentrate to give three creatures 1d4 on attacks and saves for one minute.",
    "cure_wounds": "Touch a creature to restore 1d8 + casting modifier HP. A higher slot adds 1d8; Life Domain improves healing.",
    "healing_word": "Use a bonus action to heal a visible creature for 1d4 + casting modifier HP. A higher slot adds 1d4.",
    "sanctuary": "Before targeting the warded creature with an attack or harmful spell, an attacker must pass a Wisdom save.",
    "command": "A creature that understands you makes a Wisdom save or obeys a supported one-word command on its next turn.",
    "aid": "Up to three creatures gain 5 current and maximum HP for eight hours.",
    "lesser_restoration": "Touch a creature to remove blindness, deafness, paralysis or poison.",
    "spiritual_weapon": "Create a spectral weapon for one minute. A bonus action moves it and makes a melee spell attack for 1d8 + casting modifier force damage.",
    "spiritual_strike": "Move your existing spiritual weapon up to 20 feet and strike a creature within its reach using a bonus action.",
    "hold_person": "Concentrate to paralyze a humanoid that fails a Wisdom save; it repeats the save at the end of each turn.",
    "misty_step": "Use a bonus action to teleport to a visible, traversable point within 30 feet.",
    "invisibility": "Concentrate to hide a creature and its carried equipment from ordinary sight for up to one hour. Attacking or casting ends it.",
}
for _power in POWERS:
    _power["description"] = DESCRIPTIONS[_power["id"].removeprefix("ability.").removesuffix("@1")]


def item(key, name, kind, *, weight=1, **options):
    return {"id": "itemdef." + key + "@1", "type": "item", "version": 1, "name": name, "kind": kind,
            "description": options.pop("description", name), "weight": weight, **options}


ITEMS = [
    item("dagger", "Dagger", "weapon", dice="1d4", category="simple", weapon="dagger", finesse=True, light=True, damage_type="piercing"),
    item("quarterstaff", "Quarterstaff", "weapon", dice="1d6", category="simple", weapon="quarterstaff", damage_type="bludgeoning"),
    item("mace", "Mace", "weapon", dice="1d6", category="simple", weapon="mace", damage_type="bludgeoning"),
    item("shortsword", "Shortsword", "weapon", dice="1d6", category="martial", weapon="shortsword", finesse=True, light=True, damage_type="piercing"),
    item("longsword", "Longsword", "weapon", weight=3, dice="1d8", category="martial", weapon="longsword", damage_type="slashing"),
    item("shortbow", "Shortbow", "weapon", weight=2, dice="1d6", category="simple", weapon="shortbow", ranged=True, range=16, long_range=64, ammo="arrows", two_handed=True, damage_type="piercing"),
    item("arrows", "Arrow", "ammunition", weight=0, ammo="arrows"),
    item("leather", "Leather armor", "armor", weight=3, category="light", ac=11),
    item("scale_mail", "Scale mail", "armor", weight=5, category="medium", ac=14, dex_cap=2, stealth_disadvantage=True),
    item("chain_mail", "Chain mail", "armor", weight=6, category="heavy", ac=16, dex_cap=0, strength=13, stealth_disadvantage=True),
    item("shield", "Shield", "shield", weight=2, ac=2),
    item("rope", "Rope (50 ft)", "rope", weight=2, length=10),
    item("lantern", "Hooded lantern", "lantern", fuel_ticks=3600),
    item("oil", "Flask of oil", "oil", fuel_ticks=3600),
    item("tools", "Thieves' tools", "tools", tool="thieves_tools"),
    item("healers_kit", "Healer's kit", "kit", uses=10, use="stabilize"),
    item("food", "Travel ration", "food"),
    item("paper", "Parchment", "paper", weight=0),
    item("ink", "Ink and quill", "ink", uses=20),
    item("spell_ink", "Arcane inks (50 gp)", "spell_ink", weight=0, ink_gp=50),
    item("focus", "Spellcasting focus", "focus"),
    item("satchel", "Satchel", "container", capacity=6),
    item("healing_potion", "Potion of Healing", "potion", magic=True, consumable=True,
         effects=[{"kind": "heal", "dice": "2d4+2"}]),
    item("sword_plus_one", "Longsword +1", "weapon", weight=3, dice="1d8", category="martial", weapon="longsword", damage_type="slashing", magic=True, bonus=1),
    item("protection_cloak", "Cloak of Protection", "wondrous", magic=True, attunement=True, ac_bonus=1, save_bonus=1),
    item("detection_wand", "Wand of Magic Detection", "wand", magic=True, charges=3,
         ability="ability.detect_magic@1", recharge="dawn"),
    item("holding_bag", "Bag of Holding", "container", magic=True, weight=2, capacity=100),
]


def starting_catalog():
    return {definition["id"]: deepcopy(definition) for definition in POWERS + ITEMS}


def definition(world, key):
    from .state import require
    require(key in world["definitions"], "That content definition is unavailable.")
    return world["definitions"][key]


def class_level(actor, name):
    return actor["rpg"]["classes"].count(name)


def item_rules(world, instance):
    if instance.get("definition"):
        return definition(world, instance["definition"])
    # Existing item identities and authored names remain valid after migration.
    return {"type": "item", "kind": instance["kind"], "weapon": "longsword" if instance["kind"] == "sword" else "mace",
            "category": "martial" if instance["kind"] == "sword" else "simple",
            "dice": f"1d{instance.get('damage') or 4}", "damage_type": "slashing", "weight": instance["weight"]}
