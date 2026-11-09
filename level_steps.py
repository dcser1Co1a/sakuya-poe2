"""Help a player below a build's level grow toward its gear.

For an item from the build page and the player's own level it finds, from the program's mod lists, the best tier of each
mod that an item of that level can carry, and builds a trade search link for a similar item the player can wear now:
any base of that kind, the level requirement at most the player's, and at least half of the item's mods at those tiers.
"Steps" give the same search for a few levels on the way to the build's item.

The level rule is the community's reading of the game, not an official figure: an item needs the higher of its base's level
and 80% of the level of its strongest mod. So at character level L the mods go up to level L / 0.8.

"""
import math
import re
import tkinter as tk
from tkinter import ttk

from sakura import BODY, MOD_OFF, MOD_ON, MOD_ON_GROUND
from build_items import ModLine, PobItem, ShownMod, make_template
from trade_search import ItemMod

LEVEL_SHARE = 0.8  # an item needs 80% of its strongest mod's level
KEY_MODS = 4  # the item's best mods by tier, which a looser search keeps to
# How strict a search is: (only the key mods, how many of them, the share of the tier's lowest value asked for). Strict found nothing at level 43.
# «key» is one mod, the one strongest at that level: the search that nearly always finds something, as «+3 to spell skills» staves for levelling.
MOST_STEPS = 5  # step buttons shown, the ones where the item gets most of its strength back
BAND_BELOW, BAND_ABOVE = 1, 6  # a search for level 15 looks at items needing 14 to 21: what a player of that level wears or soon will
SCOPE_TITLES = {"kind": "Любая база этого вида", "base": "Только эта база"}
chosen_scope = ["kind"]
REQUIRES = re.compile(r"^(?:Requires|Требуется):\s*(?:Level|Уровень)[^\d,]*(\d+)", re.MULTILINE)
ITEM_LEVEL = re.compile(r"^(?:Item Level|Уровень предмета): (\d+)", re.MULTILINE)
COPIED_MOD = re.compile(r'^\{\s*(?:(Fractured|Desecrated|Расколот\w*|Очерн\w*)\s+)?(Prefix|Suffix|Префикс|Суффикс)\b[^"\n]*"([^"]+)"([^\n]*)')
COPIED_TIER = re.compile(r"(?:Tier|Уровень):\s*(\d+)")
RARITY_WORDS = {"normal": "Normal", "обычный": "Normal", "magic": "Magic", "волшебный": "Magic", "rare": "Rare", "редкий": "Rare", "unique": "Unique", "уникальный": "Unique"}
# The slot an item from the game is shown in, by words of its item class in either language.
CLASS_SLOTS = (("Ring", "Ring 1"), ("Кольц", "Ring 1"), ("Amulet", "Amulet"), ("Амулет", "Amulet"), ("Belt", "Belt"), ("Пояс", "Belt"),
               ("Helmet", "Helmet"), ("Шлем", "Helmet"), ("Glove", "Gloves"), ("Перчат", "Gloves"), ("Boot", "Boots"), ("Сапог", "Boots"), ("Обув", "Boots"),
               ("Body Armour", "Body Armour"), ("Нательн", "Body Armour"), ("Shield", "Weapon 2"), ("Щит", "Weapon 2"), ("Buckler", "Weapon 2"), ("Баклер", "Weapon 2"),
               ("Foci", "Weapon 2"), ("Focus", "Weapon 2"), ("Фокус", "Weapon 2"), ("Quiver", "Weapon 2"), ("Колчан", "Weapon 2"), ("Flask", "Flask 1"), ("Флакон", "Flask 1"),
               ("Charm", "Charm 1"), ("Оберег", "Charm 1"))
VALUE = re.compile(r"([+-]?)\(?(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?\)?(%?)")
RANGE = re.compile(r"\((-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)\)")


def highest_mod_level(level: int) -> int:
    """The strongest mod an item a character of this level can wear may have."""
    return math.floor(level / LEVEL_SHARE)


def ladder_of(page, mod_name: str, side: str, wording: str = ""):
    """The ladder of tiers a mod belongs to, found by its name on the item and, as names repeat between mods («of Havoc» is a tier of
    several), by its wording. Only mods that roll by themselves: desecrated mods, alloys and runes do not turn up on low level gear,
    so a search or a craft for a lower level leaves them out."""
    named = [ladder for ladder in getattr(page, "ladders", []) if ladder.side == side and any(mod.name == mod_name for mod in ladder.mods)]
    if len(named) > 1 and wording:
        template = make_template(RANGE.sub("", wording).split(" / ")[0])
        fitting = [ladder for ladder in named if make_template(ladder.mods[0].text.split(" / ")[0]) == template]
        return fitting[0] if fitting else None
    return named[0] if named else None


def ladder_for(page, shown):
    """The ladder of a mod as the item shows it."""
    return ladder_of(page, shown.name, shown.kind, shown.text) if shown.kind in ("prefix", "suffix") and shown.name else None


def best_tier_at(ladder, level: int):
    """The best tier of a ladder an item for this character level can carry, or None when even the lowest is too high."""
    return next((mod for mod in ladder.mods if mod.level <= highest_mod_level(level)), None)


def lowest_roll(mod_text: str) -> str:
    """'+(100-119) to maximum Life' as the least that tier gives: '+100 to maximum Life'."""
    return RANGE.sub(lambda found: found.group(1), mod_text)


def mods_at_level(shown_mods: list, page, level: int) -> list[tuple[str, str]]:
    """(side, line) for each mod of the item at the best tier this level allows, each line the least that tier rolls.
    A mod with no tier low enough is left out: the item for this level simply does without it."""
    found = []
    for shown in shown_mods:
        if shown.kind not in ("prefix", "suffix") or not shown.name:
            continue
        ladder = ladder_for(page, shown)
        tier = best_tier_at(ladder, level) if ladder else None
        if tier is None:
            continue
        for line in lowest_roll(tier.text).split(" / "):
            if (shown.kind, line) not in found:
                found.append((shown.kind, line))
    return found


def available_mods(shown_mods: list, page, level: int) -> list:
    """The item's mods that some tier of rolls on an item of this level: the key mods are picked from these, not lost after picking."""
    return [mod for mod in shown_mods if mod.kind in ("prefix", "suffix") and mod.name and mod.special != "desecrated"
            and (ladder := ladder_for(page, mod)) and best_tier_at(ladder, level)]


def _value(text: str, high: bool = False) -> tuple[str, float, str] | None:
    """The first number of a mod's wording, as (sign, number, percent): the low end of a range, or its high end."""
    found = VALUE.search(text)
    if not found:
        return None
    number = float(found.group(3) if high and found.group(3) else found.group(2))
    return found.group(1), number, found.group(4)


def strength_at(ladder, level: int) -> float:
    """How much of a mod's full strength an item of this level can have: the least of the best tier it allows against the most of the top tier."""
    if ladder is None:
        return 0.0
    best = best_tier_at(ladder, level)
    now, top = (_value(best.text) if best else None), _value(ladder.mods[0].text, high=True)
    return now[1] / top[1] if now and top and top[1] else 0.0


def mod_note(shown, page, level: int) -> str | None:
    """«43 из 60%»: what this level allows of the mod against its best, for the mod list of the item."""
    ladder = ladder_for(page, shown)
    if not ladder:
        return None
    best = best_tier_at(ladder, level)
    top = _value(ladder.mods[0].text, high=True)
    now = _value(best.text) if best else None
    if not top:
        return None
    show = lambda value: f"{value[0]}{value[1]:g}{value[2]}"
    return f"{show(now)} / {show(top)}" if now else f"— / {show(top)}"


LOOT_MODS = re.compile(r"Rarity of Items|Quantity of Items|Light Radius|Attribute Requirements", re.IGNORECASE)  # they find loot or ease wearing, rather than make a character stronger


def key_order(shown_mods: list, page, level: int) -> list:
    """The mods by how much of their strength this level already allows, strongest first; ties go to the better tier on the build's item.
    Mods that find loot come last: item rarity keeps its strength well at a low level, but a levelling character needs life and damage."""
    return sorted(shown_mods, key=lambda mod: (bool(LOOT_MODS.search(mod.text)), -strength_at(ladder_for(page, mod), level), mod.tier or 99))


def tier_steps(shown_mods: list, page, mine: int, needed: int, russian: bool) -> list[tuple[int, str]]:
    """The levels on the way where one of the item's mods gets a better tier, as (level, what opens): «44: +4 к уровню всех чар».
    These are where a new item is worth buying, rather than every few levels. The biggest gains are kept."""
    gains: dict[int, list[tuple[float, str]]] = {}
    for shown in available_mods(shown_mods, page, needed):
        if LOOT_MODS.search(shown.text):  # a better tier of item rarity is no reason to buy a new item while levelling
            continue
        ladder = ladder_for(page, shown)
        top = _value(ladder.mods[0].text, high=True)
        for tier in ladder.mods:
            opens = math.ceil(tier.level * LEVEL_SHARE)
            if not (mine < opens <= needed) or not top:
                continue
            words = ((getattr(tier, "ru_text", "") or "") if russian else "") or tier.text
            low = _value(tier.text)
            gain = (low[1] / top[1]) if low and top[1] else 0.0
            gains.setdefault(opens, []).append((gain, lowest_roll(words.split(" / ")[0])))
    # Several tiers can open at one level: all are named there, and a level counts as big as its biggest gain.
    kept = sorted(sorted(gains.items(), key=lambda pair: -max(gain for gain, _ in pair[1]))[:MOST_STEPS])
    return [(level, "; ".join(line for _, line in sorted(found, key=lambda pair: -pair[0]))) for level, found in kept]


def craft_goal(shown_mods: list, page, base: str, level: int) -> dict | None:
    """The item's key mods at the best tiers this level allows, as a goal for the crafting planner. The item level is kept to what the
    character can wear, so nothing better than that rolls by chance and leaves the item too high to equip."""
    chosen = key_order(available_mods(shown_mods, page, level), page, level)[:KEY_MODS]
    mods = []
    for shown in chosen:
        ladder = ladder_for(page, shown)
        best = best_tier_at(ladder, level)
        mods.append({"template": ladder.template, "side": ladder.side, "desecrated": False, "rune": "", "tier": ladder.mods.index(best) + 1, "pool": False})
    return {"base": base, "ilvl": max(1, min(highest_mod_level(level), 86)), "mods": mods, "need": 0, "open": {}} if mods else None


def band(level: int) -> tuple[int, int]:
    """The level requirements a search for this level looks at: a little below, and a few levels to grow into."""
    return max(1, level - BAND_BELOW), min(100, level + BAND_ABOVE)


def mods_in_band(shown_mods: list, page, low: int, high: int, russian: bool = False) -> list[tuple[str, str]]:
    """(side, line) for the item's mods cut to a band of levels: each at the least of the best tier an item at the band's low end can have,
    so every item of the band can match; a mod that only appears higher in the band asks for its lowest tier there.
    The search reads the English lines; russian gives the same mods in Russian, to tell the player what will be searched."""
    found = []
    for shown in shown_mods:
        ladder = ladder_for(page, shown)
        tier = (best_tier_at(ladder, low) or best_tier_at(ladder, high)) if ladder else None
        if tier is None:
            continue
        if not best_tier_at(ladder, low):
            tier = next(mod for mod in reversed(ladder.mods) if mod.level <= highest_mod_level(high))  # the lowest tier that the band's top allows
        words = ((getattr(tier, "ru_text", "") or "") if russian else "") or tier.text
        for line in lowest_roll(words).split(" / "):
            if (shown.kind, line) not in found:
                found.append((shown.kind, line))
    return found


def jewel_tier(page, line: str):
    """(side, tier) of a jewel's mod line on its kind's page: the tier whose range holds the line's numbers, else the lowest one. None when not found."""
    template = make_template(RANGE.sub("", line))
    for ladder in getattr(page, "ladders", []):
        if ladder.template == template:
            numbers = [float(number) for number in re.findall(r"\d+(?:\.\d+)?", line)]
            for tier in ladder.mods:
                ranges = [(float(low), float(high)) for low, high in re.findall(r"\((\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\)", tier.text)]
                if ranges and len(ranges) <= len(numbers) and all(low <= value <= high for value, (low, high) in zip(numbers, ranges)):
                    return ladder.side, tier
            return ladder.side, ladder.mods[-1]
    return None


def jewel_range(tier_text: str) -> str:
    """The ranges of a mod as the player reads them: '(7-13)% increased Chaos Damage' is '7–13'."""
    return ", ".join(f"{low}–{high}" for low, high in re.findall(r"\((\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\)", tier_text))


def jewel_wording(line: str, tier, russian: bool) -> str:
    """The jewel's mod in the player's language with its own numbers: the Russian wording of its tier with the ranges filled in from the line."""
    if not (russian and tier is not None and getattr(tier, "ru_text", "")):
        return line
    numbers = iter(re.findall(r"\d+(?:\.\d+)?", line))
    ranges = re.findall(r"\(\d+(?:\.\d+)?-\d+(?:\.\d+)?\)", tier.ru_text)
    if len(ranges) != len(re.findall(r"\d+(?:\.\d+)?", line)):
        return line
    return re.sub(r"\(\d+(?:\.\d+)?-\d+(?:\.\d+)?\)", lambda _: next(numbers), tier.ru_text)


def estimated_requirement(shown_mods: list, page, base_level: int = 1) -> int | None:
    """The level an item needs when Path of Building does not write it: the higher of its base's level and 80% of its strongest mod's level.
    None when no mod of it is found in the mod lists."""
    levels = []
    for shown in shown_mods:
        ladder = ladder_for(page, shown) if page else None
        if ladder and shown.tier and shown.tier <= len(ladder.mods):
            levels.append(ladder.mods[shown.tier - 1].level)  # tier 1 is the first, strongest step of the ladder
    return max(base_level or 1, math.floor(max(levels) * LEVEL_SHARE)) if levels else None


def missing_at_level(shown_mods: list, page, level: int, russian: bool = False) -> list[tuple[str, int]]:
    """The item's mods that no item of this level can roll: (the wording of the mod's lowest tier, the character level from which it can be worn).
    Shown greyed out under the mods to search for, so a player sees why a search leaves them out."""
    found = []
    for shown in shown_mods:
        if shown.kind not in ("prefix", "suffix") or not shown.name or shown.special == "desecrated":
            continue
        ladder = ladder_for(page, shown)
        if not ladder or best_tier_at(ladder, level):
            continue
        lowest = min(ladder.mods, key=lambda mod: mod.level)
        words = ((getattr(lowest, "ru_text", "") or "") if russian else "") or lowest.text
        found.append((lowest_roll(words), max(math.ceil(lowest.level * LEVEL_SHARE), 1)))
    return found


def copied_item(text: str, page_of, find_base) -> tuple[str, "PobItem", list, str | None] | None:
    """An item copied in the game (Ctrl+Alt+C), read for the level tools: its slot, the item, its mods with tiers from the copy's own
    headers, and its base. The mod names are matched in either language to the program's mod lists."""
    text = (text or "").replace("\r\n", "\n").strip()
    if not text.startswith(("Item Class:", "Класс предмета:")):
        return None
    header = [line.strip() for line in text.split("--------")[0].split("\n") if line.strip()]
    item_class = header[0].partition(":")[2].strip()
    rarity = RARITY_WORDS.get(next((line.partition(":")[2].strip().casefold() for line in header if line.startswith(("Rarity:", "Редкость:"))), ""), "Normal")
    names = [line for line in header[2:]]
    name, base_line = (names[0], names[-1]) if len(names) >= 2 else ((names[0], names[0]) if names else ("", ""))
    base = find_base(base_line)
    page = page_of(base) if base else None
    lines = text.split("\n")
    shown: list = []
    implicits: list = []
    position = 0
    while position < len(lines):
        line = lines[position].strip()
        position += 1
        found = COPIED_MOD.match(line)
        if not line.startswith("{"):
            continue
        body = []
        while position < len(lines) and lines[position].strip() and not lines[position].startswith("{") and lines[position].strip() != "--------":
            if not lines[position].strip().startswith("("):
                body.append(lines[position].strip())
            position += 1
        if not found:
            implicits += [ModLine(RANGE.sub("", part).strip(), "implicit") for part in body if "Implicit" in line or "Собственн" in line]
            continue
        side = "prefix" if found.group(2) in ("Prefix", "Префикс") else "suffix"
        special = "fractured" if found.group(1) and found.group(1)[0] in "FР" else "desecrated" if found.group(1) else ""
        mod = getattr(page, "by_name", {}).get((side, found.group(3).casefold())) if page else None
        tier = COPIED_TIER.search(found.group(4))
        shown.append(ShownMod(side, " / ".join(body), int(tier.group(1)) if tier else None, mod.name if mod else found.group(3), special))
    requirement, item_level = REQUIRES.search(text), ITEM_LEVEL.search(text)
    item = PobItem(rarity, name, base_line, int(item_level.group(1)) if item_level else None, None, tuple(implicits), frozenset({"corrupted"} if re.search(r"^(Corrupted|Осквернено)$", text, re.MULTILINE) else ()),
                   frozenset(), frozenset(), int(requirement.group(1)) if requirement else None)
    slot = next((slot for word, slot in CLASS_SLOTS if word.casefold() in item_class.casefold()), "Weapon 1")
    return slot, item, shown, base


def detailed_text(lines: list[tuple[str, str]]) -> str:
    """The mods in the detailed copy's shape, which the trade search reads its stats from."""
    return "".join(f'{{ {side.capitalize()} Modifier "x" }}\n{line}\n' for side, line in lines)


def level_query(mods: list[ItemMod], level: int, category: str | None, base: str, need: int | None = None, share: float = 1.0, lowest: int | None = None) -> dict | None:
    """A search for an item this character can wear: the kind of item, the level requirement in the band, and every given mod at that share
    of its value or more. Each line of a hybrid mod is a filter of its own, and all of them are needed. A stat the site lists under several
    ids, such as flat energy shield (local on armour, global on jewellery), is asked for as any one of them, as the price window does.
    need is no longer used: the player ticks what they want, and all of it is wanted. None when no mod could be matched to the site's stats."""
    totals: dict[tuple[str, ...], float] = {}  # the same stat from a prefix and a suffix, such as item rarity, is one line in the game and on the site: its sum
    for mod in mods:
        for stat in mod.stats:
            totals[stat.ids] = totals.get(stat.ids, 0.0) + (stat.value or 0.0)
    required, either = [], []
    for ids, total in totals.items():
        least = math.floor(total * share)
        filters = [{"id": stat_id, **({"value": {"min": least}} if least > 0 else {})} for stat_id in ids]
        if len(filters) == 1:
            required.extend(filters)
        else:
            either.append({"type": "count", "value": {"min": 1}, "filters": filters})
    if not required and not either:
        return None
    type_filters = {"rarity": {"option": "nonunique"}, **({"category": {"option": category}} if category else {})}
    query = {"status": {"option": "online"}, **({} if category else {"type": base}), "stats": [*([{"type": "and", "filters": required}] if required else []), *either],
             "filters": {"type_filters": {"filters": type_filters}, "req_filters": {"filters": {"lvl": {**({"min": lowest} if lowest else {}), "max": level}}}, "trade_filters": {"filters": {"collapse": {"option": "true"}}}}}
    return {"query": query, "sort": {"price": "asc"}}


chosen_step: dict[tuple[str, str], int] = {}  # the level picked on the path, by item, for this run of the program
chosen_mods: dict[tuple[tuple[str, str], int], set[str]] = {}  # the mods ticked for a search, by item and level; none means all of them


def mod_key(shown) -> str:
    """One mod of an item, told apart from the others: rarity can be a prefix and a suffix on the same item."""
    return f"{shown.kind}:{shown.name}:{shown.text[:24]}"


def checked_keys(item_key: tuple[str, str], level: int, options: list[tuple[str, str, bool]]) -> set[str]:
    """The ticked mods: what the player ticked for this item and level, or else all of them."""
    known = {key for key, _, _ in options}
    picked = chosen_mods.get((item_key, level))
    return (picked & known) if picked is not None else {key for key, _, default in options if default}


def needed_count(ticked: int) -> int:
    """How many of the ticked mods a listing must have: all of them. A listing with one of two ticked mods is not what the player asked for."""
    return max(ticked, 1)


def search_summary(lines: list[str], low: int, high: int, need: int, scope: str, translate=lambda text: text) -> str:
    """What the search will ask for, said before it opens: the kind of base, the band of levels and the mods."""
    if not lines:
        return ""
    where = translate(SCOPE_TITLES.get(scope, SCOPE_TITLES["kind"])).casefold()
    count = translate("мод") if len(lines) == 1 else translate("все из") if need >= len(lines) else translate("хотя бы {count} из").format(count=need)
    return translate("Ищу: {where}, требование {low}–{high} ур., {need}: {mods}").format(where=where, low=low, high=high, need=count, mods="; ".join(lines))


def add_level_tools(holder, item, level: int | None, colors: dict, translate, actions: dict, steps: list[tuple[int, str]], refresh=lambda: None) -> bool:
    """«For your level», above the item's own buttons when the item cannot be worn yet: the path of levels toward it (a click picks a level,
    it does not leave for the site), what will be searched for at the picked level, and one button that opens that search.
    actions holds "search" (a level), "craft" (a level) and "summary" (a level, the text). True when the block is shown."""
    if not level or not item.level_req:
        return False
    t = translate
    if item.level_req <= level:
        tk.Label(holder, text=t("Наденешь уже сейчас: нужен {need} ур.").format(need=item.level_req), bg=colors["panel"], fg=colors["soft"], font=(BODY, 9), anchor="w").pack(fill="x", pady=(6, 0))
        return False
    tk.Label(holder, text=t("Нужен {need} ур., у тебя {mine}").format(need=item.level_req, mine=level), bg=colors["panel"], fg=colors["down"], font=(BODY, 9, "bold"), anchor="w").pack(fill="x", pady=(8, 0))
    if item.rarity == "Unique":
        tk.Label(holder, text=t("Уник не ослабить: до {need} ур. ищи редкую с теми же главными модами").format(need=item.level_req), bg=colors["panel"], fg=colors["muted"], font=(BODY, 9), anchor="w", wraplength=345, justify="left").pack(fill="x")
        return False
    tk.Label(holder, text=t("Под твой уровень"), bg=colors["panel"], fg=colors["accent"], font=(BODY, 10, "bold"), anchor="w").pack(fill="x", pady=(10, 0))
    tk.Frame(holder, bg=colors["border"], height=1).pack(fill="x", pady=(2, 6))

    def chip(parent, text, command, chosen=False, strong=False):
        return tk.Button(parent, text=text, command=command, relief="flat", bd=0, cursor="hand2", padx=8, pady=2,
                         bg=colors["selected"] if chosen else colors["raised"], fg=colors["on_selected"] if chosen else colors["text"], font=(BODY, 9, "bold" if strong or chosen else "normal"))

    key = (item.name, item.base_line)
    gains = dict(steps)
    path = [level, *(step for step, _ in steps if level < step < item.level_req), item.level_req]
    picked = chosen_step.get(key, level)
    if picked not in path:
        picked = level

    def pick(step: int) -> None:
        chosen_step[key] = step
        refresh()

    row = tk.Frame(holder, bg=colors["panel"])
    row.pack(fill="x")
    for number, step in enumerate(path):
        if number:
            tk.Label(row, text="►", bg=colors["panel"], fg=colors["muted"], font=(BODY, 8)).pack(side="left", padx=2)
        title = t("Ты {level}").format(level=step) if number == 0 else str(step)
        chip(row, title, lambda chosen=step: pick(chosen), step == picked).pack(side="left")
    if picked == item.level_req:
        opens = t("сама эта вещь")
    elif picked == level:
        opens = t("что можно надеть сейчас")
    else:
        opens = gains.get(picked, "")
    if opens:
        tk.Label(holder, text=t("На {level} ур.: {opens}").format(level=picked, opens=opens), bg=colors["panel"], fg=colors["soft"], font=(BODY, 9), anchor="w", wraplength=345, justify="left").pack(fill="x", pady=(4, 0))
    options = actions["options"](picked)  # (key, the mod at this level, ticked at first)
    summary_label = None
    if options:
        tk.Label(holder, text=t("Какие моды искать:"), bg=colors["panel"], fg=colors["muted"], font=(BODY, 9), anchor="w").pack(fill="x", pady=(6, 0))
        ticked = set(checked_keys(key, picked, options))

        def paint(row, label, on: bool, hover: bool = False) -> None:
            ground = MOD_ON_GROUND if on else colors["panel"]
            row.config(bg=ground, highlightbackground=colors["soft"] if hover else colors["border"])
            label.config(bg=ground, fg=MOD_ON if on else MOD_OFF, font=(BODY, 9, "bold" if on else "normal"))

        def toggle(mod: str, row, label) -> None:
            # Only this row and the line under the list change: the panel stays where it is, as on the trade site.
            ticked.symmetric_difference_update({mod})
            chosen_mods[(key, picked)] = set(ticked)
            paint(row, label, mod in ticked, True)
            if summary_label is not None:
                summary_label.config(text=actions["summary"](picked))

        for mod, words, _ in options:
            row = tk.Frame(holder, bg=colors["panel"], highlightthickness=1, highlightbackground=colors["border"], cursor="hand2")
            row.pack(fill="x", pady=1)
            label = tk.Label(row, text=words, anchor="w", justify="left", wraplength=350, padx=8, pady=4, cursor="hand2")
            label.pack(fill="x")
            paint(row, label, mod in ticked)
            for widget in (row, label):
                widget.bind("<Button-1>", lambda _, chosen=mod, r=row, l=label: toggle(chosen, r, l))
                widget.bind("<Enter>", lambda _, chosen=mod, r=row, l=label: paint(r, l, chosen in ticked, True))
                widget.bind("<Leave>", lambda _, chosen=mod, r=row, l=label: paint(r, l, chosen in ticked))
    for words, opens in actions["missing"](picked) if actions.get("missing") else []:  # what this level cannot have: grey, not clickable, with the level it comes at
        row = tk.Frame(holder, bg=colors["panel"], highlightthickness=1, highlightbackground=colors["border"])
        row.pack(fill="x", pady=1)
        tk.Label(row, text=words, bg=colors["panel"], fg=colors["muted"], font=(BODY, 9, "overstrike"), anchor="w", justify="left", wraplength=350, padx=8).pack(fill="x", pady=(3, 0))
        tk.Label(row, text=t("на этом уровне не бывает: появится с {level} ур.").format(level=opens), bg=colors["panel"], fg=colors["muted"], font=(BODY, 8), anchor="w", padx=8).pack(fill="x", pady=(0, 3))
    for words in actions["unsearchable"](picked) if actions.get("unsearchable") else []:  # the item has it, the trade site has no filter for it
        row = tk.Frame(holder, bg=colors["panel"], highlightthickness=1, highlightbackground=colors["border"])
        row.pack(fill="x", pady=1)
        tk.Label(row, text=words, bg=colors["panel"], fg=colors["muted"], font=(BODY, 9), anchor="w", justify="left", wraplength=350, padx=8).pack(fill="x", pady=(3, 0))
        tk.Label(row, text=t("сайт торговли этот мод не ищет"), bg=colors["panel"], fg=colors["muted"], font=(BODY, 8), anchor="w", padx=8).pack(fill="x", pady=(0, 3))
    summary = actions["summary"](picked)
    summary_label = tk.Label(holder, text=summary, bg=colors["panel"], fg=colors["text"], font=(BODY, 9), anchor="w", wraplength=345, justify="left")
    summary_label.pack(fill="x", pady=(6, 0))
    do = tk.Frame(holder, bg=colors["panel"])
    do.pack(fill="x", pady=(6, 0))
    low, high = band(picked)
    tk.Button(do, text=t("Открыть поиск на трейде ({low}–{high} ур.)").format(low=low, high=high), command=lambda: actions["search"](picked), relief="flat", bd=0, cursor="hand2", padx=12, pady=5,
              bg=colors["selected"], fg=colors["on_selected"], font=(BODY, 10, "bold")).pack(side="left")
    chip(holder, t("Скрафтить на {level} ур.").format(level=picked), lambda: actions["craft"](picked)).pack(anchor="w", pady=(4, 0), ipady=2)  # its own line: the window is narrow
    options = tk.Frame(holder, bg=colors["panel"])
    options.pack(fill="x", pady=(8, 0))
    tk.Label(options, text=t("База"), bg=colors["panel"], fg=colors["muted"], font=(BODY, 9)).pack(side="left", padx=(0, 4))
    scope = ttk.Combobox(options, state="readonly", width=20, values=[t(title) for title in SCOPE_TITLES.values()])
    scope.current(list(SCOPE_TITLES).index(chosen_scope[0]))
    scope.pack(side="left")
    scope.bind("<<ComboboxSelected>>", lambda _: (chosen_scope.__setitem__(0, list(SCOPE_TITLES)[scope.current()]), refresh()))
    help_text = tk.Label(holder, text=t("Сразу отмечены все моды вещи, что бывают на этом уровне: снимите лишние. Ищутся все отмеченные, со значениями тира, который бывает на этом уровне: у палки 65 ур. на 17–24 вместо T1 будет условный T7. Уровни ищутся диапазоном (для 15 — вещи на 14–21); очернённые моды, сплавы и руны не ищутся; правило уровня примерное."),
                         bg=colors["panel"], fg=colors["muted"], font=(BODY, 8), anchor="w", wraplength=345, justify="left")
    shown = {"on": False}

    def toggle_help() -> None:
        shown["on"] = not shown["on"]
        help_text.pack(fill="x", pady=(4, 0)) if shown["on"] else help_text.pack_forget()

    chip(options, "?", toggle_help).pack(side="left", padx=(8, 0))
    return True
