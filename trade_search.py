"""Turns a copied item into a search for the trade site, as a link for the player's own browser.

The program itself never contacts that site. The trade site has no official API, so whatever is searched there is searched by the player.
"""
import json
import math
import re
import urllib.parse
from dataclasses import dataclass

HOSTS = {"en": "https://www.pathofexile.com", "ru": "https://ru.pathofexile.com"}
STRONG_TIER = 2  # weaker mods barely move the price and only shrink the search
SEARCHES_REMEMBERED = 60
# What each plain stat adds to the site's totals. GGG's stat numbers are the same in every language; checked against the site's own stat list.
STAT_PARTS = {
    "3372524247": ("fire",), "4220027924": ("cold",), "1671376347": ("lightning",), "2923486259": ("chaos",), "2901986750": ("fire", "cold", "lightning"),
    "2915988346": ("fire", "cold"), "3441501978": ("fire", "lightning"), "4277795662": ("cold", "lightning"), "378817135": ("fire", "chaos"), "3393628375": ("cold", "chaos"), "3465022881": ("lightning", "chaos"),
    "4080418644": ("strength",), "3261801346": ("dexterity",), "328541901": ("intelligence",), "1379411836": ("strength", "dexterity", "intelligence"),
    "538848803": ("strength", "dexterity"), "2300185227": ("dexterity", "intelligence"), "1535626285": ("strength", "intelligence"),
    "3299347043": ("life",), "1050105434": ("mana",),
}
PSEUDO_TOTALS = (
    ("pseudo.pseudo_total_resistance", ("fire", "cold", "lightning", "chaos")), ("pseudo.pseudo_total_elemental_resistance", ("fire", "cold", "lightning")),
    ("pseudo.pseudo_total_attributes", ("strength", "dexterity", "intelligence")), ("pseudo.pseudo_total_life", ("life",)), ("pseudo.pseudo_total_mana", ("mana",)),
)
MOD_HEADER = re.compile(r'^\{(?P<head>[^}"]*?)(?:"(?P<name>[^"]*)")?(?P<rest>[^}]*)\}$')
TIER = re.compile(r"(?:Tier|Уровень): (\d+)")
RANGE = re.compile(r"\([^()]*\d[^()]*\)")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
ROLLED_RANGE = re.compile(r"(-?\d+(?:\.\d+)?)\((-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)\)")
TIER_STEP, LOWEST_TIER_SCORE, ROLL_WEIGHT = 12, 30, 10
TRADE_CATEGORIES = (("Body_Armours", "armour.chest"), ("Boots", "armour.boots"), ("Gloves", "armour.gloves"), ("Helmets", "armour.helmet"), ("Shields", "armour.shield"), ("Bucklers", "armour.buckler"), ("Foci", "armour.focus"), ("Quivers", "armour.quiver"),
                    ("Rings", "accessory.ring"), ("Amulets", "accessory.amulet"), ("Belts", "accessory.belt"), ("Bows", "weapon.bow"), ("Claws", "weapon.claw"), ("Crossbows", "weapon.crossbow"), ("Daggers", "weapon.dagger"), ("Flails", "weapon.flail"),
                    ("One_Hand_Axes", "weapon.oneaxe"), ("One_Hand_Maces", "weapon.onemace"), ("One_Hand_Swords", "weapon.onesword"), ("Quarterstaves", "weapon.warstaff"), ("Sceptres", "weapon.sceptre"), ("Spears", "weapon.spear"), ("Staves", "weapon.staff"),
                    ("Talismans", "weapon.talisman"), ("Two_Hand_Axes", "weapon.twoaxe"), ("Two_Hand_Maces", "weapon.twomace"), ("Two_Hand_Swords", "weapon.twosword"), ("Wands", "weapon.wand"))
UNSCALABLE = re.compile(r"\s*—\s*(?:Unscalable Value|Неизменяемое значение)\s*$")
MARKUP = re.compile(r"\[(?:[^\]|]*\|)?([^\]]*)\]")
SKIPPED_HEADERS = ("Implicit", "Собственное", "Rune", "Руна", "Enchant", "Зачарование", "Corrupt", "Осквернён")


# ------------------------------------------------------------- reading the item
@dataclass(frozen=True)
class StatFilter:
    ids: tuple[str, ...]  # several ids mean the same stat, such as its local and global versions
    value: float | None


@dataclass(frozen=True)
class ItemMod:
    label: str
    tier: int | None
    stats: tuple[StatFilter, ...]  # empty when the trade site's stat list has no match
    covers: tuple[str, ...] = ()  # for a total of several mods: what it adds up


def client_language(text: str) -> str:
    return "ru" if text.lstrip().startswith("Класс предмета") else "en"


def normalize_stat(text: str) -> str:
    """Reduces a stat text to its wording: '+70(61-73) to Life' and '# to Life' both become '# to life'."""
    text = MARKUP.sub(r"\1", text)
    text = NUMBER.sub("#", RANGE.sub("", text))
    return re.sub(r"\s+", " ", text.replace("+#", "#").replace("-#", "#")).strip().casefold()


def build_stat_index(stats: dict) -> dict[str, dict[str, list[str]]]:
    """Groups the trade site's stat list by kind and wording. A note in brackets, like (Local), does not change the wording."""
    index: dict[str, dict[str, list[str]]] = {}
    for group in stats["result"]:
        wording = index.setdefault(group["id"], {})
        for entry in group["entries"]:
            if not entry.get("option"):
                key = normalize_stat(re.sub(r"\s*\([^()]*\)$", "", entry["text"]))
                ids = wording.setdefault(key, [])
                if entry["id"] not in ids:
                    ids.append(entry["id"])
    return index


def read_stat_list(text: str) -> dict[str, dict[str, list[str]]]:
    """What the trade site can search by, from the list an open project keeps. Where a stat is a choice of options, the site writes the option's number after a bar.
    A negated matcher is the same stat read the other way round, which a minimum could not express."""
    groups: dict[str, list[dict]] = {}
    for line in filter(str.strip, text.splitlines()):
        stat = json.loads(line)
        trade = stat.get("trade") or {}
        for kind, values in (trade.get("ids") or {}).items():
            for matcher in stat.get("matchers", ()):
                if matcher.get("string") and not matcher.get("negate"):
                    option = matcher.get("value") if trade.get("option") else None
                    groups.setdefault(kind, []).extend({"id": stat_id if option is None else f"{stat_id}|{option}", "text": matcher["string"]} for stat_id in values)
    return build_stat_index({"result": [{"id": kind, "entries": entries} for kind, entries in groups.items()]})


def split_ranges(label: str) -> tuple[str, str]:
    """Separates a mod's wording from its possible rolls: '+70(61-73) to Life' gives '+70 to Life' and '61-73'."""
    return RANGE.sub("", label), " · ".join(found.strip("()") for found in RANGE.findall(label))


def roll_share(line: str) -> float | None:
    """Where a roll stands within its range, from 0 the lowest to 1 the highest, on average when a mod has several. None when it has no range to stand in."""
    shares = [(float(value) - float(low)) / (float(high) - float(low)) for value, low, high in ROLLED_RANGE.findall(line) if float(high) != float(low)]
    return min(max(sum(shares) / len(shares), 0.0), 1.0) if shares else None


def item_quality(mods: list[ItemMod]) -> int | None:
    """A mark out of 100 for an item's own mods: the tier counts most, and the roll within it a little. It says how good the mods are in themselves, not what anyone would pay."""
    scores = []
    for mod in mods:
        if mod.tier:
            share = roll_share(mod.label)
            scores.append(max(100 - (mod.tier - 1) * TIER_STEP, LOWEST_TIER_SCORE) - (1 - (share if share is not None else 1)) * ROLL_WEIGHT)
    return round(sum(scores) / len(scores)) if scores else None


def rolled_value(line: str) -> float | None:
    numbers = [float(number) for number in NUMBER.findall(RANGE.sub("", line))]
    return sum(numbers) / len(numbers) if numbers else None


def _mod_blocks(text: str):
    """The modifier blocks of the detailed item text that Ctrl+Alt+C copies: (kind of block, rest of its header, its lines)."""
    lines = text.replace("\r\n", "\n").split("\n")
    position = 0
    while position < len(lines):
        match = MOD_HEADER.match(lines[position].strip())
        position += 1
        if not match:
            continue
        head = ((match["head"] or "") + (match["rest"] if match["name"] is None else "")).strip()
        body = []
        while position < len(lines) and lines[position].strip() and lines[position].strip() != "--------" and not lines[position].startswith("{"):
            line = UNSCALABLE.sub("", lines[position].strip())
            position += 1
            if not line.startswith("("):  # a hint in brackets explains the mod and is no stat
                body.append(line)
        yield head, match["rest"] or "", body


def read_item_mods(text: str, index: dict[str, dict[str, list[str]]]) -> list[ItemMod]:
    mods: list[ItemMod] = []
    for head, rest, body in _mod_blocks(text):
        if head.startswith(SKIPPED_HEADERS) or not body:
            continue
        group = "fractured" if head.startswith(("Fractured", "Расколот")) else "desecrated" if head.startswith(("Desecrated", "Очернён")) else "explicit"
        wording = index.get(group, {})
        stats = tuple(StatFilter(tuple(wording[normalize_stat(line)]), rolled_value(line)) for line in body if normalize_stat(line) in wording)
        tier = TIER.search(rest)
        mods.append(ItemMod(" / ".join(body), int(tier.group(1)) if tier else None, stats if len(stats) == len(body) else ()))
    return mods


def stat_number(stat_id: str) -> str:
    """The same stat has one number whichever kind of mod carries it. A site total keeps its whole name."""
    return stat_id.rpartition("stat_")[2] if "stat_" in stat_id else stat_id


def _parts_of_line(line: str, index: dict[str, dict[str, list[str]]]) -> tuple[str, ...]:
    key = normalize_stat(line)
    for group, wording in index.items():
        if group != "pseudo" and key in wording:
            for stat_id in wording[key]:
                if stat_number(stat_id) in STAT_PARTS:
                    return STAT_PARTS[stat_number(stat_id)]
    return ()


def read_item_totals(text: str, index: dict[str, dict[str, list[str]]]) -> list[ItemMod]:
    """The site's totals, such as all elemental resistance, wherever an item spreads a stat over several mods.

    Implicit mods and runes count too, as they do on the site. One mod alone needs no total, unless it gives several stats at once.
    """
    values: dict[str, float] = {}
    sources: dict[str, int] = {}
    for _, _, body in _mod_blocks(text):
        for line in body:
            value = rolled_value(line)
            parts = _parts_of_line(line, index) if value else ()
            for part in parts:
                values[part] = values.get(part, 0) + value
                sources[part] = sources.get(part, 0) + 1
    names = {ids[0]: wording for wording, ids in index.get("pseudo", {}).items()}
    totals = []
    for stat_id, parts in PSEUDO_TOTALS:
        found = [part for part in parts if part in values]
        if stat_id == "pseudo.pseudo_total_resistance" and not ("chaos" in found and len(found) > 1):
            continue  # without chaos this is the elemental total, and with chaos alone it is that one mod
        if stat_id in names and sum(sources[part] for part in found) >= 2:
            total = sum(values[part] for part in found)
            label = names[stat_id].replace("#", f"{total:g}")
            totals.append(ItemMod(label[0].upper() + label[1:], None, (StatFilter((stat_id,), total),), tuple(found)))
    return totals


def lowest_roll(line: str) -> float | None:
    """The weakest value a mod's text allows: '+(61-73) to Life' gives 61."""
    numbers = [float(NUMBER.search(found).group()) for found in RANGE.findall(line)] + [float(number) for number in NUMBER.findall(RANGE.sub("", line))]
    return sum(numbers) / len(numbers) if numbers else None


def wanted_mod(lines: list[str], index: dict[str, dict[str, list[str]]]) -> ItemMod:
    """A mod the crafter aims for, as a search filter. Its stats stay empty when the site's list has no such wording."""
    wording = index.get("explicit", {})
    keys = [normalize_stat(RANGE.sub("#", line)) for line in lines]
    stats = tuple(StatFilter(tuple(wording[key]), lowest_roll(line)) for key, line in zip(keys, lines) if key in wording)
    return ItemMod(" / ".join(lines), None, stats if len(stats) == len(lines) else ())


def mods_on_by_default(mods: list[ItemMod], unique: bool) -> list[ItemMod]:
    """A unique is found by its name, so its mods start off. A rare starts with what sets its price: strong tiers and special mods."""
    if unique:
        return []
    totals = [mod for mod in mods if mod.covers]
    # Of two totals that overlap, the wider one alone says enough.
    totals = [mod for mod in totals if not any(set(mod.covers) < set(other.covers) for other in totals)]
    covered = {part for mod in totals for part in mod.covers}

    def added_up(mod: ItemMod) -> bool:
        parts = STAT_PARTS.get(stat_number(mod.stats[0].ids[0]))
        return bool(parts) and set(parts) <= covered

    usable = [mod for mod in mods if mod.stats and not mod.covers and not added_up(mod)]
    strong = [mod for mod in usable if mod.tier is None or mod.tier <= STRONG_TIER or not mod.stats[0].ids[0].startswith("explicit.")]
    if strong or totals:
        return [*totals, *strong]
    return sorted(usable, key=lambda mod: mod.tier)[:2]


def search_memory_key(copied: str, name: str | None, unique: bool) -> str:
    """A unique is remembered by its name, anything else by its kind: what matters on one helmet matters on the next."""
    return f"unique:{name}" if unique and name else copied.lstrip().split("\n", 1)[0].strip()


def remember_search(memory: dict, key: str, mods: list[ItemMod], strictness: float) -> dict:
    """The newest stays, and the oldest goes once there are too many."""
    kept = {name: entry for name, entry in memory.items() if name != key}
    kept[key] = {"stats": sorted({stat_number(stat.ids[0]) for mod in mods for stat in mod.stats}), "strictness": strictness}
    return dict(list(kept.items())[-SEARCHES_REMEMBERED:])


def recalled_mods(entry: dict | None, mods: list[ItemMod]) -> list[ItemMod]:
    """The mods of this item that the player chose last time. Empty when this item has none of them."""
    if not entry:
        return []
    chosen = set(entry.get("stats", ()))
    return [mod for mod in mods if mod.stats and all(stat_number(stat.ids[0]) in chosen for stat in mod.stats)]


def trade_category(page_name: str | None) -> str | None:
    """The site's word for a kind of item, for a search not tied to one base."""
    return next((category for start, category in TRADE_CATEGORIES if page_name and page_name.startswith(start)), None)


def item_values(text: str) -> dict[str, tuple[str, float | None]]:
    """Every mod line of a copied item, by its wording: what to call it and how much it gives."""
    found = {}
    for _, _, body in _mod_blocks(text):
        for line in body:
            found[normalize_stat(line)] = (split_ranges(line)[0], rolled_value(line))
    return found


def compared_lines(first: str, second: str) -> list[tuple[str, float | None, float | None]]:
    """(wording, value on the first item, value on the second), what they share first."""
    ours, theirs = item_values(first), item_values(second)
    rows = [(key, ours[key][1], theirs[key][1]) for key in ours if key in theirs]
    rows += [(key, ours[key][1], None) for key in ours if key not in theirs]
    return rows + [(key, None, theirs[key][1]) for key in theirs if key not in ours]


def build_query(name: str | None, base: str, unique: bool, mods: list[ItemMod], strictness: float, category: str | None = None) -> dict:
    """strictness is the share of the current roll a listing must reach; 0 only asks for the mod to be there. A category searches every base of that kind."""
    groups = []
    required = []
    for mod in mods:
        for stat in mod.stats:
            minimum = {"min": math.floor(stat.value * strictness)} if stat.value and strictness else {}
            filters = [{"id": stat_id, **({"value": minimum} if minimum else {})} for stat_id in stat.ids]
            if len(filters) == 1:
                required.extend(filters)
            else:
                groups.append({"type": "count", "value": {"min": 1}, "filters": filters})
    type_filters = {"rarity": {"option": "unique" if unique else "nonunique"}, **({"category": {"option": category}} if category else {})}
    query: dict = {"status": {"option": "online"}, **({} if category else {"type": base}), "stats": [{"type": "and", "filters": required}, *groups],
                   "filters": {"type_filters": {"filters": type_filters},
                               "trade_filters": {"filters": {"collapse": {"option": "true"}}}}}  # one listing per seller
    if unique and name:
        query["name"] = name
    return {"query": query, "sort": {"price": "asc"}}


def trade_site_url(language: str, league: str, query: dict) -> str:
    """The search as a link: the browser asks the site, just as if the player had filled in its form."""
    words = json.dumps(query, ensure_ascii=False, separators=(",", ":"))
    return f"{HOSTS.get(language, HOSTS['en'])}/trade2/search/poe2/{urllib.parse.quote(league)}?q={urllib.parse.quote(words, safe='{}[]:,')}"


