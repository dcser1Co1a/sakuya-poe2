"""The items of a Path of Building build, laid out as the game lays them out.

The player pastes the code that Path of Building, a build guide or poe.ninja's character page gives them.
It is read on this computer: base64, then zlib, then the build's XML (the format of PathOfBuilding-PoE2, MIT).
Nothing is fetched. poe.ninja's build, profile and Path of Building endpoints are closed to programs
(poe.ninja/docs/api), and a link to one is not followed: the player copies the code instead.

Each item is written out the way the game's Ctrl+Alt+C copies it, with the tier and rolls of every mod found
in the program's own mod lists, so the price window, the trade link and the crafting planner take it as they
take an item copied in the game.
"""
import base64
import binascii
import re
import tkinter as tk
import urllib.parse
import xml.etree.ElementTree as ElementTree
from tkinter import ttk
import zlib
from dataclasses import dataclass
from datetime import datetime

from sakura import BODY, MOD_OFF, MOD_ON, MOD_ON_GROUND, trace_while

LARGEST_BUILD = 8_000_000  # a whole build is well under a megabyte of XML; more is a bomb, not a build
LINK = re.compile(r"^(?:https?://|www\.|pobb\.in|poe2?\.ninja)", re.IGNORECASE)
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
RANGE_IN_TEXT = re.compile(r"\((-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)\)")
VALUE_OR_RANGE = re.compile(r"\((-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)\)|(-?\d+(?:\.\d+)?)")
MARKS = re.compile(r"^\{([^{}]*)\}")
FLAG_LINES = {"Corrupted": "corrupted", "Twice Corrupted": "corrupted", "Mirrored": "mirrored", "Sanctified": "sanctified"}
RARITY_TITLES = {"NORMAL": "Normal", "MAGIC": "Magic", "RARE": "Rare", "UNIQUE": "Unique", "RELIC": "Unique"}
SEPARATOR = "--------"
# Where each slot sits, in cells: (left, top, width, height). The game's own paper doll, weapons at the sides.
SLOT_PLACES = {
    "Weapon 1": (0, 0.5, 2, 4), "Helmet": (4, 0, 2, 2), "Weapon 2": (8, 0.5, 2, 4),
    "Ring 3": (2.6, 1, 1, 1), "Amulet": (6.4, 1, 1, 1),
    "Body Armour": (4, 2.3, 2, 3), "Ring 1": (2.6, 3.3, 1, 1), "Ring 2": (6.4, 3.3, 1, 1),
    "Gloves": (2, 4.9, 2, 2), "Belt": (4, 5.6, 2, 1), "Boots": (6, 4.9, 2, 2),
    "Flask 1": (2.3, 7.2, 1, 2), "Charm 1": (3.6, 7.6, 1, 1), "Charm 2": (4.5, 7.6, 1, 1), "Charm 3": (5.4, 7.6, 1, 1), "Flask 2": (6.7, 7.2, 1, 2),
}
SLOT_TITLES = {"Weapon 1": "Оружие", "Weapon 2": "Вторая рука", "Helmet": "Шлем", "Body Armour": "Нательная броня", "Gloves": "Перчатки", "Boots": "Сапоги", "Amulet": "Амулет",
               "Ring 1": "Кольцо", "Ring 2": "Кольцо", "Ring 3": "Кольцо", "Belt": "Пояс", "Flask 1": "Флакон", "Flask 2": "Флакон", "Charm 1": "Оберег", "Charm 2": "Оберег", "Charm 3": "Оберег"}
JEWEL_TITLE = "Самоцвет"
CELL = 52  # a ring's cell then holds the 48 pixel icon whole
HISTORY_SIZE = 30  # builds kept in the history, newest first
jewel_ticks: dict[tuple[str, str], set[str]] = {}  # the mods ticked for a jewel's search, by jewel; none means all of them
jewel_by_range = [True]  # search from the least of each mod's range, or from the jewel's own values
LEVEL_TYPING_MS = 350  # The pause after the last key of «my level» before the item updates
NICK_TYPING_MS = 400  # the pause after the last key of a character's name before it is saved
NICK_LENGTH = 40
# poe.ninja's export link, a Path of Building address of theirs that is not to be used: only the account and the name are taken from it,
# to open the character's own page in the player's browser.
NINJA_EXPORT = re.compile(r"^https://poe\.ninja/poe2/pob/raw/profile/code/([^/?#]+)/[^/?#]+/([^/?#]+)/?$")
REFRESH_SECONDS = 3600  # the character's page opens once an hour at most: poe.ninja does not see a character change much faster
IMPORT_CHARACTER = re.compile(r"/profile/.*/([^/?#]+)/?$")  # poe.ninja's export link ends with the character's name; the account before it is not kept
GRID_WIDTH, GRID_HEIGHT = 10, 9.3
JEWEL = "Jewel "  # the start of a jewel's slot name; the rest is its socket on the passive tree
# Jewels fill the free room under the weapons, a column on each side, then rows under everything.
JEWEL_SIDE_PLACES = [(left, 5.0 + row * 1.05, 1, 1) for left in (0, 0.98) for row in range(4)] + [(left, 5.0 + row * 1.05, 1, 1) for left in (8.02, 9.0) for row in range(4)]
JEWELS_PER_ROW = 9


class BuildCodeError(ValueError):
    """Says in the player's words what is wrong with what they pasted."""


@dataclass(frozen=True)
class ModLine:
    text: str
    kind: str  # implicit, rune, enchant, explicit


@dataclass(frozen=True)
class PobItem:
    rarity: str  # Normal, Magic, Rare or Unique, as the game writes it
    name: str
    base_line: str  # the line with the base in it: the base itself, or a magic item's whole name
    item_level: int | None
    quality: int | None
    lines: tuple[ModLine, ...]
    flags: frozenset[str]
    fractured: frozenset[str]  # the explicit lines Path of Building marks as fractured
    desecrated: frozenset[str]
    level_req: int | None = None  # the level a character needs to wear it, as Path of Building writes it


@dataclass(frozen=True)
class Build:
    level: int | None
    class_name: str
    ascendancy: str
    slots: dict
    jewels: tuple = ()  # (socket, item) for each jewel on the passive tree, in the tree's order
    character: str = ""  # the character's name, when the code was exported from a character
    page: str = ""  # the character's page on poe.ninja, when the code was exported there


@dataclass(frozen=True)
class ShownMod:
    """One mod as the item card and the details list show it."""
    kind: str  # implicit, rune, enchant, prefix, suffix, unique, unknown
    text: str
    tier: int | None = None
    name: str = ""
    special: str = ""  # fractured or desecrated
    shown_text: str = ""  # the same mod in the player's language, where the mod lists have it


def decode_build_code(text: str) -> str:
    """The build's XML from a pasted code. A link is refused with a hint, as following it would mean asking a site that is closed to programs."""
    code = "".join((text or "").split())
    if not code:
        raise BuildCodeError("Вставьте код Path of Building")
    if LINK.match(code):
        raise BuildCodeError("Это ссылка, а нужен сам код: откройте её в браузере и нажмите «Копировать код» или Export")
    try:
        packed = base64.urlsafe_b64decode(code.replace("+", "-").replace("/", "_") + "=" * (-len(code) % 4))
        unpack = zlib.decompressobj()
        xml = unpack.decompress(packed, LARGEST_BUILD)
    except (binascii.Error, ValueError, zlib.error):
        raise BuildCodeError("Это не код Path of Building: скопируйте его целиком") from None
    if unpack.unconsumed_tail or not unpack.eof:
        raise BuildCodeError("Это не код Path of Building: скопируйте его целиком")
    found = xml.decode("utf-8", errors="replace")
    if "<!DOCTYPE" in found or "<!ENTITY" in found:  # a build never declares any; one that does is no build
        raise BuildCodeError("Это не код Path of Building: скопируйте его целиком")
    return found


def apply_range(line: str, share: float) -> str:
    """Path of Building keeps a unique's mods as ranges and the roll apart: '+(10-20) to Life' at 0.5 is '+15 to Life'."""
    def rolled(found):
        low, high = float(found.group(1)), float(found.group(2))
        value = low + share * (high - low)
        whole = low.is_integer() and high.is_integer()
        return str(int(value + 0.5) if value >= 0 else -int(-value + 0.5)) if whole else f"{value:.2f}".rstrip("0").rstrip(".")
    return RANGE_IN_TEXT.sub(rolled, line)


def _read_line(line: str, selected: str | None) -> tuple[str, set[str]] | None:
    """A mod line without Path of Building's marks, and the marks. None for a line of another variant of the item."""
    marks: set[str] = set()
    share = 0.5  # what Path of Building assumes for a roll it has not been told
    while (found := MARKS.match(line)):
        mark = found.group(1)
        name, _, value = mark.partition(":")
        if name == "range":
            try:
                share = min(max(float(value), 0.0), 1.0)
            except ValueError:
                pass
        elif name == "variant" and selected is not None and selected not in value.split(","):
            return None
        marks.add(name)
        line = line[found.end():]
    return apply_range(line.strip(), share), marks


def parse_pob_item(raw: str) -> PobItem:
    lines = [line.strip() for line in (raw or "").replace("\r\n", "\n").split("\n") if line.strip()]
    if not lines or not lines[0].startswith("Rarity:"):
        raise BuildCodeError("Предмет в коде не прочитан")
    rarity = RARITY_TITLES.get(lines[0].partition(":")[2].strip().upper(), "Normal")
    named = 2 if rarity in ("Rare", "Unique") and len(lines) > 2 else 1
    name, base_line = (lines[1], lines[2]) if named == 2 else (lines[1] if len(lines) > 1 else "", lines[1] if len(lines) > 1 else "")
    rest = lines[1 + named:]
    implicit_at = next((index for index, line in enumerate(rest) if line.startswith("Implicits:")), None)
    header = rest if implicit_at is None else rest[:implicit_at]
    body = [] if implicit_at is None else rest[implicit_at + 1:]

    def header_number(prefix: str) -> int | None:
        found = next((line for line in header if line.startswith(prefix)), None)
        number = NUMBER.search(found.partition(":")[2]) if found else None
        return int(float(number.group())) if number else None

    selected = next((line.partition(":")[2].strip() for line in header if line.startswith("Selected Variant:")), None)
    try:
        implicit_count = int(rest[implicit_at].partition(":")[2]) if implicit_at is not None else 0
    except ValueError:
        implicit_count = 0
    flags = {FLAG_LINES[line] for line in body if line in FLAG_LINES}
    mods, fractured, desecrated = [], set(), set()
    for position, line in enumerate(line for line in body if line not in FLAG_LINES):
        read = _read_line(line, selected)
        if not read or not read[0]:
            continue
        text, marks = read
        if position < implicit_count:
            kind = "rune" if "rune" in marks else "enchant" if "enchant" in marks else "implicit"
        else:
            kind = "explicit"
            if "fractured" in marks:
                fractured.add(text)
            if "desecrated" in marks:
                desecrated.add(text)
        mods.append(ModLine(text, kind))
    return PobItem(rarity, name, base_line, header_number("Item Level:"), header_number("Quality:"), tuple(mods), frozenset(flags), frozenset(fractured), frozenset(desecrated),
                   header_number("LevelReq:"))


def read_build(xml_text: str) -> Build:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        raise BuildCodeError("Это не код Path of Building: скопируйте его целиком") from None
    if root.tag != "PathOfBuilding2":
        raise BuildCodeError("Это код Path of Building для первой части игры, а нужен для PoE2" if root.tag == "PathOfBuilding" else "Это не код Path of Building: скопируйте его целиком")
    build = root.find("Build")
    attributes = build.attrib if build is not None else {}
    try:
        level = int(attributes.get("level", ""))
    except ValueError:
        level = None
    items_node = root.find("Items")
    slots: dict[str, PobItem] = {}
    if items_node is not None:
        raw_items = {node.get("id"): node.text or "" for node in items_node.findall("Item")}
        sets = items_node.findall("ItemSet")
        active = next((found for found in sets if found.get("id") == items_node.get("activeItemSet")), sets[0] if sets else None)
        for slot in active.findall("Slot") if active is not None else []:
            name, item_id = slot.get("name", ""), slot.get("itemId", "0")
            if name in SLOT_PLACES and item_id in raw_items:
                try:
                    slots[name] = parse_pob_item(raw_items[item_id])
                except BuildCodeError:
                    continue  # one odd item must not cost the others
    imported = root.find("Import")
    link = imported.get("importLink", "") if imported is not None else ""
    named = IMPORT_CHARACTER.search(link)
    character = urllib.parse.unquote(named.group(1)) if named else ""
    return Build(level, attributes.get("className", ""), attributes.get("ascendClassName", "") if attributes.get("ascendClassName") != "None" else "", slots,
                 _tree_jewels(root, raw_items if items_node is not None else {}), character[:40], character_page(link))


def character_page(link: str) -> str:
    """The character's page on poe.ninja, the one a player opens in the browser, from the export link in the code; empty for a code made elsewhere."""
    found = NINJA_EXPORT.match(link.strip())
    if not found:
        return ""
    account, name = (urllib.parse.quote(urllib.parse.unquote(part), safe="") for part in found.groups())
    return f"https://poe.ninja/poe2/profile/{account}/character/{name}"


def refresh_wait(entry: dict, now: str) -> int:
    """Seconds until the character's page may open again; 0 when it may now."""
    try:
        spent = (datetime.fromisoformat(now) - datetime.fromisoformat(entry.get("refreshed_at") or "")).total_seconds()
    except ValueError:
        return 0
    return max(int(REFRESH_SECONDS - spent), 0) if spent >= 0 else 0


def marked_refreshed(history: list[dict], code: str, now: str) -> list[dict]:
    return [{**entry, "refreshed_at": now} if entry.get("code") == code else entry for entry in history]


def history_label(entry: dict, translate) -> str:
    """The character, class, ascendancy and level, such as RaorasFootArc · Witch · Blood Mage · level 94: what the history list shows of a build."""
    level = translate("уровень {level}").format(level=entry["level"]) if entry.get("level") else ""
    return " · ".join(part for part in (entry.get("name", ""), entry.get("class_name", ""), entry.get("ascendancy", ""), level) if part) or translate("Билд")


def add_to_history(history: list[dict], code: str, build: Build, now: str) -> list[dict]:
    """The build at the top of the history. The same code again moves up rather than taking a second place, and keeps a name the player gave it
    when the code carries none. A newer code of the same character takes the place of the older one: that is how a build is brought up to date."""
    plain = "".join(code.split())
    character = build.character.casefold()

    def same(old: dict) -> bool:
        return old.get("code") == plain or bool(character) and old.get("name", "").casefold() == character

    earlier = next((old for old in history if same(old)), {})
    entry = {"code": plain, "name": build.character or earlier.get("name", ""), "class_name": build.class_name, "ascendancy": build.ascendancy, "level": build.level, "saved_at": now}
    if earlier.get("refreshed_at"):
        entry["refreshed_at"] = earlier["refreshed_at"]  # the hour's wait goes on with the newer code
    return [entry, *(old for old in history if not same(old))][:HISTORY_SIZE]


def renamed(history: list[dict], code: str, name: str) -> list[dict]:
    """The history with the build of this code under the player's name for its character."""
    return [{**entry, "name": name.strip()[:NICK_LENGTH]} if entry.get("code") == code else entry for entry in history]


def _tree_jewels(root, raw_items: dict) -> tuple:
    """The jewels socketed in the active passive tree: Tree/Spec/Sockets/Socket names the node and the item."""
    tree = root.find("Tree")
    specs = tree.findall("Spec") if tree is not None else []
    if not specs:
        return ()
    try:
        spec = specs[int(tree.get("activeSpec", "1")) - 1]
    except (ValueError, IndexError):
        spec = specs[0]
    jewels = []
    for socket in spec.iter("Socket"):
        item_id = socket.get("itemId", "0")
        if item_id != "0" and item_id in raw_items:
            try:
                jewels.append((socket.get("nodeId", ""), parse_pob_item(raw_items[item_id])))
            except BuildCodeError:
                continue
    return tuple(jewels)


def jewel_places(count: int) -> list[tuple[float, float, float, float]]:
    """Where the jewels go: the two free columns under the weapons first, then rows under the doll."""
    places = JEWEL_SIDE_PLACES[:count]
    for index in range(count - len(places)):
        places.append((0.05 + (index % JEWELS_PER_ROW) * 1.1, GRID_HEIGHT + 0.2 + (index // JEWELS_PER_ROW) * 1.05, 1, 1))
    return places


def make_template(text: str) -> str:
    """The same as the crafting planner's: numbers and ranges become #."""
    return re.sub(r"\(?-?\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?\)?", "#", text)


def _ranges(mod_text: str) -> list[tuple[float, float]]:
    return [(float(low), float(high)) if low else (float(single), float(single)) for low, high, single in VALUE_OR_RANGE.findall(mod_text)]


def _fits(values: list[float], ranges: list[tuple[float, float]]) -> bool:
    return len(values) == len(ranges) and all(min(low, high) - 1e-6 <= value <= max(low, high) + 1e-6 for value, (low, high) in zip(values, ranges))


def _candidates(text: str, page, special: str) -> list[tuple[str, int, object, object]]:
    """(side, tier, mod, ladder) for every ladder this line fits, at the tier its numbers fall in."""
    template, values = make_template(text), [float(number) for number in NUMBER.findall(text)]
    regular, desecrated = list(page.ladders), list(getattr(page, "desecrated_ladders", []))
    # Essences, alloys and runes of warping bring mods of their own; those come last, after anything that rolls by itself.
    rare = list(getattr(page, "special_ladders", [])) + list(getattr(page, "rune_ladders", []))
    ladders = (desecrated + regular if special == "desecrated" else regular + desecrated) + rare
    found = []
    for ladder in ladders:
        if ladder.template != template:
            continue
        for tier, mod in enumerate(ladder.mods, start=1):
            if _fits(values, _ranges(mod.text)):
                found.append((ladder.side, tier, mod, ladder))
                break
    return found


def _with_ranges(text: str, mod_text: str) -> str:
    """'+70 to Life' with the tier's '+(61-73) to Life' becomes '+70(61-73) to Life', as the game's detailed copy writes it."""
    ranges = iter(_ranges(mod_text))

    def marked(found):
        low, high = next(ranges, (None, None))
        if low is None or low == high:
            return found.group()
        return f"{found.group()}({low:g}-{high:g})"
    return NUMBER.sub(marked, text)


def _russian(text: str, russian: str) -> str:
    """The mod in Russian with the item's own numbers, where the mod lists have its Russian text."""
    values = iter(NUMBER.findall(text))
    if not russian or len(VALUE_OR_RANGE.findall(russian)) != len(NUMBER.findall(text)):
        return ""
    return VALUE_OR_RANGE.sub(lambda _: next(values), russian)


def explicit_mods(item: PobItem, page, limits: dict[str, int]) -> list[ShownMod]:
    """Each explicit line with its side, tier and name, found in the program's mod lists for the base.
    A line that fits a prefix and a suffix alike, such as item rarity, goes where there is room."""
    lines = [line.text for line in item.lines if line.kind == "explicit"]
    if item.rarity == "Unique" or page is None:
        return [ShownMod("unique" if item.rarity == "Unique" else "unknown", text) for text in lines]
    # Two lines of one hybrid mod come one after the other: those are tried together first.
    units: list[tuple[list[str], list]] = []
    position = 0
    while position < len(lines):
        special = "fractured" if lines[position] in item.fractured else "desecrated" if lines[position] in item.desecrated else ""
        if position + 1 < len(lines):
            pair = f"{lines[position]} / {lines[position + 1]}"
            both = _candidates(pair, page, special)
            if both:
                units.append(([lines[position], lines[position + 1]], both))
                position += 2
                continue
        units.append(([lines[position]], _candidates(lines[position], page, special)))
        position += 1
    room = dict(limits)
    taken: set = set()  # an item holds one mod of a group, so one line cannot take a ladder another already took
    best: dict = {"score": -1, "choice": None}

    def place(index: int, chosen: list, score: int):
        if index == len(units):
            if score > best["score"]:
                best.update(score=score, choice=list(chosen))
            return
        for side, tier, mod, ladder in units[index][1]:
            groups = {(side, group) for group in getattr(mod, "groups", ()) or ()} | {id(ladder)}  # rarity as a prefix and as a suffix may share a group name
            if room.get(side, 0) > 0 and not groups & taken:
                room[side] -= 1
                taken.update(groups)
                place(index + 1, chosen + [(side, tier, mod)], score + 1)
                taken.difference_update(groups)
                room[side] += 1
        place(index + 1, chosen + [None], score)

    place(0, [], 0)
    shown = []
    for (texts, _), choice in zip(units, best["choice"] or [None] * len(units)):
        special = "fractured" if texts[0] in item.fractured else "desecrated" if texts[0] in item.desecrated or (choice and getattr(choice[2], "desecrated", False)) else ""
        if choice is None:
            shown.extend(ShownMod("unknown", text, special=special) for text in texts)
            continue
        side, tier, mod = choice
        parts = mod.text.split(" / ")
        russian = getattr(mod, "ru_text", "") or ""
        russian_parts = russian.split(" / ") if russian else []
        for number, text in enumerate(texts):
            part = parts[number] if len(parts) == len(texts) else mod.text
            russian_part = russian_parts[number] if len(russian_parts) == len(texts) else ""
            shown.append(ShownMod(side, _with_ranges(text, part), tier, mod.name, special, _russian(text, russian_part)))
    return shown


def game_text(item: PobItem, item_class: str, mods: list[ShownMod]) -> str:
    """The item as the game's Ctrl+Alt+C copies it, so everything that reads a copied item reads this one too."""
    head = [f"Item Class: {item_class or 'Item'}", f"Rarity: {item.rarity}"]
    head += [item.name, item.base_line] if item.rarity in ("Rare", "Unique") else [item.base_line]
    parts = ["\n".join(head)]
    if item.quality:
        parts.append(f"Quality: +{item.quality}% (augmented)")
    if item.item_level:
        parts.append(f"Item Level: {item.item_level}")
    for kind, title, note in (("enchant", "Enchant Modifier", "enchant"), ("rune", "Rune Modifier", "rune"), ("implicit", "Implicit Modifier", "implicit")):
        block = [f"{{ {title} }}\n{line.text} ({note})" for line in item.lines if line.kind == kind]
        if block:
            parts.append("\n".join(block))
    explicit = []
    for mod in mods:
        if mod.kind in ("prefix", "suffix"):
            special = f"{mod.special.capitalize()} " if mod.special else ""
            explicit.append(f'{{ {special}{mod.kind.capitalize()} Modifier "{mod.name}" (Tier: {mod.tier}) }}\n{mod.text}')
        else:
            explicit.append(f"{{ {'Unique Modifier' if mod.kind == 'unique' else 'Modifier'} }}\n{mod.text}")
    if explicit:
        parts.append("\n".join(explicit))
    if "corrupted" in item.flags:
        parts.append("Corrupted")
    return f"\n{SEPARATOR}\n".join(parts) + "\n"


# ------------------------------------------------------------------- the page
class BuildPage:
    """Paste a code, see the build's items where the game shows them, click one for its mods, price and trade link."""

    def __init__(self, parent, colors: dict[str, str], translate, helpers: dict):
        self.colors, self.t, self.helpers = colors, translate, helpers
        self.build: Build | None = None
        self.views: dict[str, tuple[PobItem, list[ShownMod], str, str | None]] = {}  # slot: item, mods, game text, base
        self.selected: str | None = None
        self.hovered: str | None = None
        self.places: dict[str, tuple] = dict(SLOT_PLACES)
        self.refresh_button, self.refresh_job, self.current_code = None, None, ""
        self.pages_of_codes: dict[str, str] = {}
        page = tk.Frame(parent, bg=colors["background"], padx=10)
        page.pack(fill="both", expand=True)
        top = tk.Frame(page, bg=colors["background"])
        top.pack(fill="x", pady=(0, 6))
        tk.Label(top, text=self.t("Код Path of Building"), bg=colors["background"], fg=colors["muted"], font=(BODY, 9)).pack(side="left", padx=(0, 8))
        self.code = tk.StringVar()
        entry = helpers["make_entry"](top, self.code)
        entry.pack(side="left", fill="x", expand=True, ipady=5)
        entry.bind("<Return>", lambda _: self.open_code())
        if helpers.get("level_tools"):  # The player's level, for the searches toward the build's gear
            tk.Label(top, text=self.t("Мой уровень"), bg=colors["background"], fg=colors["muted"], font=(BODY, 9)).pack(side="left", padx=(10, 6))
            # Typing is enough: the item updates a moment after the last key, and the level is remembered for the next build and the next start.
            self.level = tk.StringVar(value=helpers["saved_level"]() if helpers.get("saved_level") else "")
            self.level_job = None
            level_entry = helpers["make_entry"](top, self.level, 4)
            level_entry.pack(side="left", ipady=5)
            level_entry.bind("<Return>", lambda _: self._apply_level())
            trace_while(self.level, level_entry, lambda *_: self._level_typed())
        helpers["button"](top, self.t("Вставить и открыть"), self.paste_and_open, True).pack(side="left", padx=(6, 0))
        self.note = tk.Label(page, text=self.t("Код даёт Path of Building, гайд или кнопка экспорта у персонажа на poe.ninja. Он читается на этом компьютере, в сеть ничего не уходит."),
                             bg=colors["background"], fg=colors["muted"], font=(BODY, 9), anchor="w", justify="left", wraplength=880)
        self.note.pack(fill="x", pady=(0, 6))
        if helpers.get("history"):  # the builds opened before, to come back to in one click
            remembered = tk.Frame(page, bg=colors["background"])
            remembered.pack(fill="x", pady=(0, 6))
            tk.Label(remembered, text=self.t("История билдов"), bg=colors["background"], fg=colors["muted"], font=(BODY, 9)).pack(side="left", padx=(0, 8))
            self.history_box = ttk.Combobox(remembered, state="readonly", width=60)
            self.history_box.pack(side="left", ipady=2)
            self.history_box.bind("<<ComboboxSelected>>", lambda _: self.open_from_history())
            helpers["button"](remembered, self.t("Убрать из истории"), self.forget_from_history).pack(side="left", padx=(6, 0))
            # A newer code of the same character: its page on poe.ninja opens in the browser, the player copies the code there, and the entry updates.
            self.refresh_button = helpers["button"](remembered, self.t("Обновить с poe.ninja"), self.refresh_from_ninja)
            self.refresh_button.pack(side="left", padx=(6, 0))
            # The character's name: filled in from the code when it carries one, and typed in by the player when it does not.
            naming = tk.Frame(page, bg=colors["background"])  # a line of its own: beside the history it fell off a narrow window
            naming.pack(fill="x", pady=(0, 6))
            tk.Label(naming, text=self.t("Ник персонажа"), bg=colors["background"], fg=colors["muted"], font=(BODY, 9)).pack(side="left", padx=(0, 8))
            self.nick = tk.StringVar()
            self.nick_job, self.current_code, self.nick_quiet = None, "", False
            nick_entry = helpers["make_entry"](naming, self.nick, 24)
            nick_entry.pack(side="left", ipady=4)
            trace_while(self.nick, nick_entry, lambda *_: self._nick_typed())
            self.nick_hint = tk.Label(naming, text="", bg=colors["background"], fg=colors["accent"], font=(BODY, 9))
            self.nick_hint.pack(side="left", padx=(8, 0))
            self.refresh_hint = tk.Label(page, text="", bg=colors["background"], fg=colors["accent"], font=(BODY, 9), anchor="w", justify="left", wraplength=880)
            self.refresh_line_after = naming
            self._fill_history()
            self._paint_refresh()
        self.title = tk.Label(page, text="", bg=colors["background"], fg=colors["text"], font=(BODY, 12, "bold"), anchor="w")
        self.title.pack(fill="x")
        body = tk.Frame(page, bg=colors["background"])
        body.pack(fill="both", expand=True, pady=(6, 0))
        self.canvas = tk.Canvas(body, width=int(GRID_WIDTH * CELL) + 8, height=int(GRID_HEIGHT * CELL) + 8, bg=colors["background"], highlightthickness=0, bd=0)
        self.canvas.pack(side="left", anchor="n")
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda _: self._set_hovered(None))
        # The details scroll: a long item with its notes and searches is taller than the window.
        holder = tk.Frame(body, bg=colors["panel"], highlightthickness=1, highlightbackground=colors["border"])
        holder.pack(side="left", fill="both", expand=True, padx=(10, 0))
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        self.details_canvas = tk.Canvas(holder, bg=colors["panel"], highlightthickness=0, bd=0)
        self.details_canvas.grid(row=0, column=0, sticky="nsew")
        self.details = tk.Frame(self.details_canvas, bg=colors["panel"], padx=12, pady=10)
        inside = self.details_canvas.create_window(0, 0, window=self.details, anchor="nw")
        self.details.bind("<Configure>", lambda _: self.details_canvas.configure(scrollregion=self.details_canvas.bbox("all")))
        self.details_canvas.bind("<Configure>", lambda event: self.details_canvas.itemconfigure(inside, width=event.width))
        if helpers.get("enable_scrolling"):
            helpers["enable_scrolling"](holder, self.details_canvas)
        self.images: list = []  # Tk shows a picture only while something holds it

    def _level_typed(self) -> None:
        """Waits for the typing to pause, so a two digit level is not drawn twice."""
        if self.level_job:
            self.canvas.after_cancel(self.level_job)
        self.level_job = self.canvas.after(LEVEL_TYPING_MS, self._apply_level)

    def _apply_level(self) -> None:
        self.level_job = None
        typed = self.level.get().strip()
        if typed and not (typed.isdigit() and 1 <= int(typed) <= 100):
            return  # half typed or not a level: the item stays as it is
        if self.helpers.get("save_level"):
            self.helpers["save_level"](int(typed) if typed else None)
        if self.views:
            self._render_details(keep_scroll=True)

    # ---- reading
    def paste_and_open(self) -> None:
        self.code.set(self.helpers["clipboard"]().strip())
        self.open_code()

    def _fill_history(self) -> None:
        if not self.helpers.get("history"):
            return
        self.history = self.helpers["history"]()
        self.history_box["values"] = [history_label(entry, self.t) for entry in self.history]
        self.history_box.set(self.t("Выберите билд") if self.history else self.t("Пока пусто: откройте код, и он появится здесь"))

    def open_from_history(self) -> None:
        chosen = self.history_box.current()
        if 0 <= chosen < len(self.history):
            self.code.set(self.history[chosen]["code"])
            self.open_code()

    def _nick_typed(self) -> None:
        if self.nick_quiet or not self.current_code:
            return  # the name was filled in by the program, or no build is open to name
        if self.nick_job:
            self.canvas.after_cancel(self.nick_job)
        self.nick_job = self.canvas.after(NICK_TYPING_MS, self._save_nick)

    def _save_nick(self) -> None:
        self.nick_job = None
        history = renamed(self.helpers["history"](), self.current_code, self.nick.get())
        self.helpers["save_history"](history)
        self._fill_history()
        shown = next((number for number, entry in enumerate(self.history) if entry.get("code") == self.current_code), None)
        if shown is not None:
            self.history_box.current(shown)
            self.title.config(text=history_label(self.history[shown], self.t))
        self._paint_nick_hint()

    def _show_nick(self, name: str) -> None:
        self.nick_quiet = True  # setting the field is not the player typing
        self.nick.set(name)
        self.nick_quiet = False
        self._paint_nick_hint()

    def _paint_nick_hint(self) -> None:
        """A word beside the field while the open build has no name: a code made in Path of Building itself carries none."""
        self.nick_hint.config(text="" if self.nick.get().strip() or not self.current_code else self.t("← в коде нет имени, впишите ник, и он появится в истории"))

    def forget_from_history(self) -> None:
        chosen = self.history_box.current()
        if 0 <= chosen < len(self.history):
            self.helpers["save_history"]([entry for number, entry in enumerate(self.history) if number != chosen])
            self._fill_history()
            self._paint_refresh()

    # ---- bringing a build up to date
    def _current_entry(self) -> dict | None:
        return next((entry for entry in getattr(self, "history", []) if entry.get("code") == self.current_code), None) if self.current_code else None

    def _page_of_code(self, code: str) -> str:
        if code not in self.pages_of_codes:
            try:
                self.pages_of_codes[code] = read_build(decode_build_code(code)).page
            except BuildCodeError:
                self.pages_of_codes[code] = ""
        return self.pages_of_codes[code]

    def _paint_refresh(self) -> None:
        """The button says when it works: now, in so many minutes, or not for a code without a link to the character."""
        if not self.refresh_button or not self.refresh_button.winfo_exists():
            return
        if self.refresh_job:
            self.refresh_button.winfo_toplevel().after_cancel(self.refresh_job)
            self.refresh_job = None
        entry = self._current_entry()
        wait = refresh_wait(entry, self.helpers["now"]()) if entry and self._page_of_code(entry["code"]) else 0
        ready = bool(entry) and bool(self._page_of_code(entry["code"])) and not wait
        text = self.t("Обновить через {minutes} мин").format(minutes=max(1, -(-wait // 60))) if wait else self.t("Обновить с poe.ninja")
        self.refresh_button.config(text=text, fg=self.colors["text"] if ready else self.colors["muted"])
        if wait:
            self.refresh_job = self.refresh_button.winfo_toplevel().after(min(wait, 60) * 1000, self._paint_refresh)  # on the window: the page may be built anew

    def _say_refresh(self, text: str) -> None:
        self.refresh_hint.config(text=text)
        if text:
            self.refresh_hint.pack(fill="x", pady=(0, 6), after=self.refresh_line_after)
        else:
            self.refresh_hint.pack_forget()

    def refresh_from_ninja(self) -> None:
        entry = self._current_entry()
        if not entry:
            return self._say_refresh(self.t("Сначала откройте билд из истории."))
        page = self._page_of_code(entry["code"])
        if not page:
            return self._say_refresh(self.t("В этом коде нет ссылки на персонажа: так бывает у кода из Path of Building или гайда. Возьмите код кнопкой экспорта у персонажа на poe.ninja, и кнопка заработает."))
        now = self.helpers["now"]()
        wait = refresh_wait(entry, now)
        if wait:
            return self._say_refresh(self.t("Страницу персонажа можно открывать раз в час: осталось {minutes} мин.").format(minutes=max(1, -(-wait // 60))))
        self.helpers["open_link"](page)
        self.helpers["save_history"](marked_refreshed(self.helpers["history"](), entry["code"], now))
        self._fill_history()
        shown = next((number for number, kept in enumerate(self.history) if kept.get("code") == self.current_code), None)
        if shown is not None:
            self.history_box.current(shown)
        self._say_refresh(self.t("Открыта страница персонажа на poe.ninja. Скопируйте там код для Path of Building и нажмите «Вставить и открыть»: запись в истории обновится."))
        self._paint_refresh()

    def open_code(self) -> None:
        found = self.helpers["copied_item"](self.code.get()) if self.helpers.get("copied_item") else None  # An item copied in the game
        if found:
            slot, item, mods, base = found
            self.build, self.places, self.selected = Build(None, "", "", {slot: item}), dict(SLOT_PLACES), slot
            self.views = {slot: (item, mods, self.code.get().replace("\r\n", "\n").strip() + "\n", base)}
            self.title.config(text=self.t("Предмет из игры"), fg=self.colors["text"])
            return self.render()
        try:
            build = read_build(decode_build_code(self.code.get()))
            self.show_build(build)
            if self.helpers.get("history") and build.slots:
                self.helpers["save_history"](add_to_history(self.helpers["history"](), self.code.get(), build, self.helpers["now"]()))
                self._fill_history()
                self.history_box.set(history_label(self.history[0], self.t))
                self.current_code = self.history[0]["code"]
                self._show_nick(self.history[0].get("name", ""))
                self.title.config(text=history_label(self.history[0], self.t))
                self._say_refresh("")
                self._paint_refresh()
        except BuildCodeError as error:
            self.build, self.views, self.selected = None, {}, None
            self.title.config(text=self.t(str(error)), fg=self.colors["down"])
            self.render()

    def show_build(self, build: Build) -> None:
        self.build, self.views = build, {}
        jewel_slots = [f"{JEWEL}{socket}" for socket, _ in build.jewels]
        self.places = {**SLOT_PLACES, **dict(zip(jewel_slots, jewel_places(len(jewel_slots))))}
        rows = max((top + height for _, top, _, height in self.places.values()), default=GRID_HEIGHT)
        self.canvas.config(height=int(max(rows, GRID_HEIGHT) * CELL) + 8)
        for slot, item in [*build.slots.items(), *zip(jewel_slots, (item for _, item in build.jewels))]:
            base = self.helpers["find_base"](item.base_line)
            info = self.helpers["base_info"](base) if base else None
            page = self.helpers["page_of"](base) if base else None
            mods = explicit_mods(item, page, self.helpers["limits"](base or ""))
            item_class = (info or {}).get("item_class", "") or ("Jewel" if slot.startswith(JEWEL) else "")
            self.views[slot] = (item, mods, game_text(item, item_class, mods), base)
        if not build.slots and not build.jewels:
            self.title.config(text=self.t("В этом коде нет надетых предметов"), fg=self.colors["muted"])
        else:
            who = " · ".join(part for part in (build.character, build.class_name, build.ascendancy,self.t("уровень {level}").format(level=build.level) if build.level else "") if part)
            self.title.config(text=who or self.t("Билд"), fg=self.colors["text"])
        self.selected = next((slot for slot in self.places if slot in self.views), None)
        self.render()

    # ---- drawing
    @staticmethod
    def _title(slot: str) -> str:
        return JEWEL_TITLE if slot.startswith(JEWEL) else SLOT_TITLES[slot]

    def _box(self, slot: str) -> tuple[float, float, float, float]:
        left, top, width, height = self.places[slot]
        return 4 + left * CELL, 4 + top * CELL, 4 + (left + width) * CELL - 4, 4 + (top + height) * CELL - 4

    def render(self, details: bool = True) -> None:
        canvas, colors = self.canvas, self.colors
        canvas.delete("all")
        self.images = []
        jewels = [slot for slot in self.places if slot.startswith(JEWEL)]
        if jewels:  # a caption over each column of jewels
            for left in sorted({self.places[slot][0] for slot in jewels if self.places[slot][1] < GRID_HEIGHT})[::2]:
                canvas.create_text(4 + left * CELL, 4 + 4.68 * CELL, text=self.t("Самоцветы"), fill=colors["muted"], font=(BODY, 8), anchor="w")
        for slot in self.places:
            if slot == "Ring 3" and slot not in self.views:
                continue
            x1, y1, x2, y2 = self._box(slot)
            view = self.views.get(slot)
            rarity = view[0].rarity if view else ""
            chosen = slot == self.selected
            edge = colors["accent"] if chosen else colors["muted"] if view else colors["border"]  # grey frames, the chosen one pink: rarity shows in the item's name
            canvas.create_rectangle(x1, y1, x2, y2, fill=colors["raised"] if slot == self.hovered and view else colors["panel"], outline=edge, width=2 if chosen else 1)
            if not view:
                canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2, text=self.t(self._title(slot)), fill=colors["muted"], font=(BODY, 8), width=x2 - x1 - 4)
                continue
            item, _, _, base = view
            large = self.places[slot][2] > 1 or self.places[slot][3] > 1
            picture = self.helpers["item_picture"](item.name if item.rarity == "Unique" else "", base, item.base_line, large)
            if picture:
                self.images.append(picture)
                canvas.create_image((x1 + x2) / 2, (y1 + y2) / 2, image=picture)
            else:  # no art yet: the slot's name, in the colour of the item's rarity
                canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2, text=self.t(self._title(slot)), fill=self.helpers["rarity_color"](rarity), font=(BODY, 8, "bold"), width=x2 - x1 - 4)
        if details:
            self._render_details()

    def _jewel_block(self, holder, item, text: str) -> None:
        """«Find a similar jewel»: its mods to tick (all at first), searched from the least of each mod's range or from the jewel's own values."""
        colors, helpers, t = self.colors, self.helpers, self.t
        rows = helpers["jewel_rows"](text, item.base_line)
        if not rows:
            return
        key = (item.name, item.base_line)
        searchable = [row for row in rows if row["searchable"]]
        ticked = jewel_ticks.get(key, {row["key"] for row in searchable})
        tk.Label(holder, text=t("Найти похожий самоцвет"), bg=colors["panel"], fg=colors["accent"], font=(BODY, 10, "bold"), anchor="w").pack(fill="x", pady=(10, 0))
        tk.Frame(holder, bg=colors["border"], height=1).pack(fill="x", pady=(2, 4))
        summary = tk.Label(holder, bg=colors["panel"], fg=colors["text"], font=(BODY, 9), anchor="w", wraplength=345, justify="left")

        def paint(row, label, on: bool, hover: bool = False) -> None:
            ground = MOD_ON_GROUND if on else colors["panel"]
            row.config(bg=ground, highlightbackground=colors["soft"] if hover else colors["border"])
            label.config(bg=ground, fg=MOD_ON if on else MOD_OFF, font=(BODY, 9, "bold" if on else "normal"))

        def toggle(mod_key: str, row, label) -> None:  # only this row and the line under the list change: the panel stays where it is
            ticked.symmetric_difference_update({mod_key})
            jewel_ticks[key] = set(ticked)
            paint(row, label, mod_key in ticked, True)
            summary.config(text=helpers["jewel_summary"](text, item.base_line, ticked, jewel_by_range[0]))

        for entry in rows:
            words = entry["shown"] + (f"   ({entry['range']})" if entry["range"] else "")
            if not entry["searchable"]:
                box = tk.Frame(holder, bg=colors["panel"], highlightthickness=1, highlightbackground=colors["border"])
                box.pack(fill="x", pady=1)
                tk.Label(box, text=words, bg=colors["panel"], fg=colors["muted"], font=(BODY, 9), anchor="w", justify="left", wraplength=350, padx=8).pack(fill="x", pady=(3, 0))
                tk.Label(box, text=t("сайт торговли этот мод не ищет"), bg=colors["panel"], fg=colors["muted"], font=(BODY, 8), anchor="w", padx=8).pack(fill="x", pady=(0, 3))
                continue
            box = tk.Frame(holder, bg=colors["panel"], highlightthickness=1, highlightbackground=colors["border"], cursor="hand2")
            box.pack(fill="x", pady=1)
            label = tk.Label(box, text=words, anchor="w", justify="left", wraplength=350, padx=8, pady=4, cursor="hand2")
            label.pack(fill="x")
            paint(box, label, entry["key"] in ticked)
            for widget in (box, label):
                widget.bind("<Button-1>", lambda _, k=entry["key"], b=box, l=label: toggle(k, b, l))
                widget.bind("<Enter>", lambda _, k=entry["key"], b=box, l=label: paint(b, l, k in ticked, True))
                widget.bind("<Leave>", lambda _, k=entry["key"], b=box, l=label: paint(b, l, k in ticked))
        values = tk.Frame(holder, bg=colors["panel"])
        values.pack(fill="x", pady=(6, 0))
        for by_range, title in ((True, "Диапазон мода"), (False, "Как на предмете")):
            chosen = jewel_by_range[0] == by_range
            tk.Button(values, text=t(title), command=lambda b=by_range: (jewel_by_range.__setitem__(0, b), self._render_details(keep_scroll=True)), relief="flat", bd=0, cursor="hand2", padx=8, pady=2,
                      bg=colors["selected"] if chosen else colors["raised"], fg=colors.get("on_selected", colors["text"]) if chosen else colors["text"],
                      font=(BODY, 9, "bold" if chosen else "normal")).pack(side="left", padx=(0, 4))
        if jewel_by_range[0] and not any(entry["range"] for entry in rows):
            tk.Label(holder, text=t("Моды самоцветов ещё не скачаны: ищу по значениям на предмете"), bg=colors["panel"], fg=colors["muted"], font=(BODY, 8), anchor="w", wraplength=345, justify="left").pack(fill="x", pady=(2, 0))
        summary.config(text=helpers["jewel_summary"](text, item.base_line, ticked, jewel_by_range[0]))
        summary.pack(fill="x", pady=(6, 0))
        tk.Button(holder, text=t("Открыть поиск на трейде"), command=lambda: helpers["jewel_search"](text, item.base_line, ticked, jewel_by_range[0]), relief="flat", bd=0, cursor="hand2", padx=12, pady=5,
                  bg=colors["selected"], fg=colors.get("on_selected", colors["text"]), font=(BODY, 10, "bold")).pack(anchor="w", pady=(6, 0))

    def _scroll_details_to(self, where: float) -> None:
        """Back to where the player was. The panel may be gone by then, as a language change builds the page anew."""
        try:
            if where is not None and self.details_canvas.winfo_exists():  # a canvas with nothing to scroll yet tells no place
                self.details_canvas.yview_moveto(float(where))
        except (tk.TclError, TypeError, ValueError):
            pass

    def _render_details(self, keep_scroll: bool = False) -> None:
        """keep_scroll is for a change made inside the panel, which must not throw the player back to its top."""
        where = self.details_canvas.yview()[0]
        self.details_canvas.yview_moveto(0)
        if keep_scroll:
            self.details_canvas.after_idle(lambda: self._scroll_details_to(where))
        for child in self.details.winfo_children():
            child.destroy()
        colors, holder = self.colors, self.details
        view = self.views.get(self.selected or "")
        if not view:
            text = self.t("Вставьте код билда: здесь появятся его предметы") if not self.build else self.t("Выберите предмет")
            tk.Label(holder, text=text, bg=colors["panel"], fg=colors["muted"], font=(BODY, 10), justify="left", wraplength=380).pack(anchor="w")
            return
        item, mods, text, base = view
        color = self.helpers["rarity_color"](item.rarity)
        tk.Label(holder, text=self.t(self._title(self.selected)), bg=colors["panel"], fg=colors["muted"], font=(BODY, 9), anchor="w").pack(fill="x")
        if item.rarity in ("Rare", "Unique"):
            tk.Label(holder, text=self.helpers["show_unique"](item.name) if item.rarity == "Unique" else item.name, bg=colors["panel"], fg=color, font=(BODY, 12, "bold"), anchor="w", wraplength=380, justify="left").pack(fill="x")
        shown_base = self.helpers["show_base"](base, item.base_line)  # in the player's language where the name is known; a magic item's affixes are not
        facts = [shown_base] + ([self.t("ур. предмета {level}").format(level=item.item_level)] if item.item_level else []) + ([self.t("качество {quality}%").format(quality=item.quality)] if item.quality else [])
        if item.level_req:  # the level a character needs to wear it
            facts.append(self.t("требует {level} ур.").format(level=item.level_req))
        elif self.helpers.get("estimate_req") and (guess := self.helpers["estimate_req"](mods, base)):  # not in the code: the level rule's estimate
            facts.append(self.t("требует ~{level} ур.").format(level=guess))
        tk.Label(holder, text="  ·  ".join(facts), bg=colors["panel"], fg=color if item.rarity in ("Normal", "Magic") else colors["soft"], font=(BODY, 10), anchor="w", wraplength=380, justify="left").pack(fill="x", pady=(0, 6))
        russian = self.helpers["language"]() == "ru"
        own = [line for line in item.lines if line.kind != "explicit"]  # implicits, runes and enchants; the explicit mods come below with their tiers
        for line in own:
            tk.Label(holder, text=line.text, bg=colors["panel"], fg=colors["soft"], font=(BODY, 9), anchor="w", wraplength=380, justify="left").pack(fill="x")
        if own and mods:
            tk.Frame(holder, bg=colors["border"], height=1).pack(fill="x", pady=4)
        for mod in mods:
            row = tk.Frame(holder, bg=colors["panel"])
            row.pack(fill="x", pady=1)
            if any(shown.tier for shown in mods):  # the side and tier column, only where some mod has a tier to show
                side = {"prefix": self.t("П"), "suffix": self.t("С")}.get(mod.kind, "")
                mark = f"{side} T{mod.tier}" if mod.tier else ""
                tk.Label(row, text=mark, width=6, anchor="w", bg=colors["panel"], fg=colors["accent"] if mod.tier == 1 else colors["muted"], font=(BODY, 9, "bold")).pack(side="left")
            wording = (mod.shown_text if russian and mod.shown_text else re.sub(r"\(-?\d+(?:\.\d+)?--?\d+(?:\.\d+)?\)", "", mod.text))
            special = {"fractured": self.t("расколот"), "desecrated": self.t("очернён")}.get(mod.special)
            label = f"{wording}  ({special})" if special else wording
            if self.helpers.get("mod_note") and mod.kind in ("prefix", "suffix"):  # What the player's level allows of this mod
                typed = self.level.get().strip()
                note = self.helpers["mod_note"](mod, base, int(typed)) if typed.isdigit() and 1 <= int(typed) <= 100 else None
                if note:
                    label += f"   ·  {typed}: {note}"
            tk.Label(row, text=label, bg=colors["panel"], fg=colors["text"], font=(BODY, 9), anchor="w", wraplength=330, justify="left").pack(side="left", fill="x")
        for_my_level = False
        if self.helpers.get("level_tools"):  # «For your level» comes first when the item cannot be worn yet
            level = self.level.get().strip()
            for_my_level = bool(self.helpers["level_tools"](holder, item, mods, base, int(level) if level.isdigit() and 1 <= int(level) <= 100 else None))
        if (self.selected or "").startswith(JEWEL) and item.rarity != "Unique" and self.helpers.get("jewel_rows"):
            self._jewel_block(holder, item, text)
        where = self.helpers.get("drop_of", lambda _: None)(item.name) if item.rarity == "Unique" else None
        if where:  # where this unique comes from, from the wiki
            caption = self.t("Где падает")
            tk.Label(holder, text=f"{caption}: {where}", bg=colors["panel"], fg=colors["accent"], font=(BODY, 9), anchor="w", wraplength=380, justify="left").pack(fill="x", pady=(6, 0))
        if "corrupted" in item.flags:
            tk.Label(holder, text=self.t("Осквернён"), bg=colors["panel"], fg=colors["down"], font=(BODY, 9, "bold"), anchor="w").pack(fill="x", pady=(4, 0))
        if for_my_level:  # The item's own searches, apart from the ones for the player's level
            tk.Label(holder, text=self.t("Эта вещь"), bg=colors["panel"], fg=colors["soft"], font=(BODY, 10, "bold"), anchor="w").pack(fill="x", pady=(12, 0))
            tk.Frame(holder, bg=colors["border"], height=1).pack(fill="x", pady=(2, 0))
        buttons = tk.Frame(holder, bg=colors["panel"])
        buttons.pack(fill="x", pady=(8 if for_my_level else 10, 0))
        self.helpers["button"](buttons, self.t("Цена этой вещи") if for_my_level else self.t("Цена и трейд"), lambda: self.helpers["check_price"](text), not for_my_level).pack(side="left")
        if item.rarity in ("Normal", "Magic", "Rare") and base and "corrupted" not in item.flags:
            self.helpers["button"](buttons, self.t("Улучшить в крафте"), lambda: self.helpers["open_in_craft"](text)).pack(side="left", padx=(6, 0))
        self.helpers["button"](buttons, self.t("Копировать"), lambda: self.helpers["copy"](text)).pack(side="left", padx=(6, 0))

    # ---- the mouse
    def _slot_at(self, x: float, y: float) -> str | None:
        for slot in self.places:
            x1, y1, x2, y2 = self._box(slot)
            if x1 <= x <= x2 and y1 <= y <= y2 and (slot != "Ring 3" or slot in self.views):
                return slot
        return None

    def _on_click(self, event) -> None:
        slot = self._slot_at(event.x, event.y)
        if slot and slot in self.views and slot != self.selected:
            self.selected = slot
            self.render()

    def _on_motion(self, event) -> None:
        slot = self._slot_at(event.x, event.y)
        self._set_hovered(slot if slot in self.views else None)

    def _set_hovered(self, slot: str | None) -> None:
        if slot != self.hovered:
            self.hovered = slot
            self.canvas.config(cursor="hand2" if slot else "")
            self.render(details=False)  # only the doll changes on a hover
