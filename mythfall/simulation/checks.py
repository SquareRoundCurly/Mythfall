"""Recorded dice and the common ability/skill/save calculation."""

import re

from .state import require, roll


SKILLS = {
    "acrobatics": "dex", "animal_handling": "wis", "arcana": "int", "athletics": "str",
    "deception": "cha", "history": "int", "insight": "wis", "intimidation": "cha",
    "investigation": "int", "medicine": "wis", "nature": "int", "perception": "wis",
    "performance": "cha", "persuasion": "cha", "religion": "int", "sleight_of_hand": "dex",
    "stealth": "dex", "survival": "wis",
}
STATS = frozenset(SKILLS.values()) | {"con"}
DICE = re.compile(r"([1-9][0-9]?)d(3|4|6|8|10|12|20|100)([+-][0-9]{1,2})?")


def integer(value, minimum, maximum, label):
    require(type(value) is int and minimum <= value <= maximum, f"Invalid {label}.")
    return value


def validate_dice(expression):
    require(isinstance(expression, str), "Dice must be a bounded dice expression.")
    match = DICE.fullmatch(expression)
    require(match is not None and int(match[1]) <= 20, "Use at most 20 dice in a dice expression.")
    return int(match[1]), int(match[2]), int(match[3] or 0)


def dice(world, expression):
    count, sides, bonus = validate_dice(expression)
    rolls = [roll(world, sides) for _ in range(count)]
    return {"expression": expression, "rolls": rolls, "bonus": bonus, "total": max(0, sum(rolls) + bonus)}


def modifier(actor, stat):
    require(stat in STATS, "Unknown character stat.")
    return (actor["stats"][stat] - 10) // 2


def proficiency(actor):
    return 2 + max(0, len(actor.get("rpg", {}).get("classes", [])) - 1) // 4


def check(world, aid, *, stat=None, skill=None, tool=None, difficulty=12, advantage=0, saving=False, bonus=0):
    from .minds import active_effects, has_condition

    require(aid in world["actors"], "Unknown character for check.")
    require(skill is None or skill in SKILLS, "Unknown skill.")
    stat = stat or SKILLS.get(skill, "wis")
    require(stat in STATS, "Unknown check stat.")
    integer(difficulty, 0, 40, "difficulty")
    integer(advantage, -1, 1, "advantage")
    integer(bonus, -20, 20, "check bonus")
    actor = world["actors"][aid]
    help = actor["rpg"].get("help", {})
    if help.get("ends_at", 0) > world["tick"] and help.get("skill") == skill and not saving:
        advantage = 1 if advantage == 0 else 0 if advantage == -1 else 1
        actor["rpg"].pop("help", None)
    from .characters import passive_bonus
    if saving:
        bonus += passive_bonus(world, aid, "save_bonus")
    trained = actor.get("rpg", {}).get("saves" if saving else "skills", [])
    training = proficiency(actor) if (stat if saving else skill) in trained else 0
    if tool:
        require(tool in {"thieves_tools"}, "Unsupported tool proficiency.")
        training = proficiency(actor) if tool in actor["rpg"]["tools"] else 0
    if not saving and (tool or skill) in actor.get("rpg", {}).get("expertise", []):
        training *= 2
    disadvantage = has_condition(world, aid, "poisoned") and not saving
    from .characters import untrained_armor
    disadvantage |= stat in {"str", "dex"} and untrained_armor(world, aid)
    if saving and stat == "dex":
        disadvantage |= has_condition(world, aid, "restrained")
        if has_condition(world, aid, "guarded"):
            advantage = 1 if advantage >= 0 else 0
    if skill == "stealth":
        from .catalog import item_rules
        armor = world["items"].get(actor["rpg"].get("armor"))
        disadvantage |= bool(armor and item_rules(world, armor).get("stealth_disadvantage"))
    if disadvantage:
        advantage = 0 if advantage == 1 else -1
    rolls = [roll(world, 20) for _ in range(2 if advantage else 1)]
    chosen = min(rolls) if advantage < 0 else max(rolls)
    additions = []
    for effect in active_effects(world, aid, "check_bonus"):
        if not effect.get("attack") and effect.get("saving", False) == saving and effect.get("stat", stat) == stat:
            extra = dice(world, effect["dice"])
            additions.append(extra)
            if effect.get("once"):
                from .effects import remove_effect
                remove_effect(world, effect["id"])
    extra_total = sum(value["total"] for value in additions)
    total_modifier = modifier(actor, stat) + training + bonus + extra_total
    automatic_failure = saving and stat in {"str", "dex"} and any(
        has_condition(world, aid, condition) for condition in ("paralyzed", "unconscious", "stunned"))
    return {"die": chosen, "rolls": rolls, "stat": stat, "skill": skill, "saving": saving,
            "ability_modifier": modifier(actor, stat), "training": training, "bonuses": additions,
            "modifier": total_modifier, "total": chosen + total_modifier, "difficulty": difficulty,
            "success": not automatic_failure and chosen + total_modifier >= difficulty,
            "advantage": advantage, "automatic_failure": automatic_failure}
