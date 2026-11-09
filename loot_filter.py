"""The filter builder: a filter that follows the market.

Sakuya writes its own Sakuya.filter into the folder where Path of Exile 2 looks for filters (Documents\\My Games\\Path of Exile 2),
from the prices it already downloads and the lines the player sets on the «Filter» page: goods worth more stand out more. Below them
it adds the player's usual filter (a copy of it, or an Import line), so everything else looks as before. It writes only its own files (the filter, and sound files
the player picks, copied to «Sakuya sounds» there) and reads nothing of the game; the player picks the filter in the game, and may
need "Reload" in its options to see a newer file, as nothing is sent to the game.
"""
import ctypes
import ctypes.wintypes
import os
import re
import shutil
import math
import struct
import tkinter as tk
import wave
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk

from sakura import BODY

FILTER_NAME = "Sakuya.filter"
SOUND_FOLDER = "Sakuya sounds"
SOUND_TYPES = (".mp3", ".wav")
GAME_FOLDER = Path("My Games") / "Path of Exile 2"
MOST_TIERS = 6
COLORS = {  # label ground, letters, border, and the game's colour name for a beam and a minimap icon of that look
    "red": ((175, 25, 30), (255, 255, 255), (255, 255, 255), "Red"),
    "orange": ((230, 150, 40), (20, 12, 4), (255, 210, 120), "Orange"),
    "yellow": ((240, 205, 70), (24, 18, 4), (255, 240, 170), "Yellow"),
    "gold": ((40, 30, 10), (255, 236, 160), (235, 190, 70), "Yellow"),
    "pink": ((215, 75, 145), (255, 255, 255), (255, 195, 228), "Pink"),
    "purple": ((105, 45, 175), (255, 255, 255), (215, 175, 255), "Purple"),
    "blue": ((35, 80, 190), (255, 255, 255), (170, 200, 255), "Blue"),
    "cyan": ((25, 145, 165), (255, 255, 255), (170, 240, 255), "Cyan"),
    "green": ((40, 135, 60), (255, 255, 255), (170, 240, 180), "Green"),
    "white": ((235, 235, 235), (20, 20, 20), (255, 255, 255), "White"),
}
SHOWN_COLORS = ("red", "orange", "yellow", "gold", "pink", "purple", "cyan")
GAME_COLORS = {"Red": "Красный", "Orange": "Оранжевый", "Yellow": "Жёлтый", "Pink": "Розовый", "Purple": "Фиолетовый", "Blue": "Синий", "Cyan": "Голубой",
               "Green": "Зелёный", "White": "Белый", "Brown": "Коричневый", "Grey": "Серый"}  # the colours the game knows for beams and minimap icons
BEAM_SHADES = {"Red": (200, 40, 40), "Orange": (235, 150, 40), "Yellow": (240, 210, 70), "Pink": (230, 100, 170), "Purple": (140, 70, 210), "Blue": (60, 100, 220),
               "Cyan": (40, 190, 210), "Green": (60, 180, 80), "White": (240, 240, 240), "Brown": (140, 90, 50), "Grey": (150, 150, 150)}
ICON_SHAPES = {"Star": "Звезда", "Diamond": "Ромб", "Circle": "Круг", "Hexagon": "Шестиугольник", "Square": "Квадрат", "Triangle": "Треугольник", "Cross": "Крест",
               "Moon": "Луна", "Raindrop": "Капля", "Kite": "Воздушный змей", "Pentagon": "Пятиугольник", "UpsideDownHouse": "Домик"}
ICON_SIZES = {0: "Большой", 1: "Средний", 2: "Маленький"}  # the game's sizes: 0 is the largest
FONT_RANGE = (18, 45)
SOUND_IDS = range(1, 17)
LOUDNESS_TITLES = {"loud": "Громко", "noticeable": "Значок", "quiet": "Только цвет", "own": "Своё"}
DEFAULT_TIERS = [
    {"name": "Очень дорогое", "least": 1.0, "unit": "div", "color": "red", "font": 45, "beam": {"color": "Red", "temp": False},
     "icon": {"size": 0, "color": "Red", "shape": "Star"}, "sound": {"kind": "builtin", "id": 6, "volume": 300}},
    {"name": "Дорогое", "least": 60.0, "unit": "ex", "color": "orange", "font": 45, "beam": {"color": "Orange", "temp": False},
     "icon": {"size": 0, "color": "Orange", "shape": "Star"}, "sound": {"kind": "builtin", "id": 6, "volume": 300}},
    {"name": "Стоит поднять", "least": 12.0, "unit": "ex", "color": "gold", "font": 40, "beam": None,
     "icon": {"size": 1, "color": "Yellow", "shape": "Circle"}, "sound": None},
]
DEFAULT_SETTINGS = {"auto": False, "base": None, "hide_below": None, "tiers": DEFAULT_TIERS}
UNITS = ("ex", "div")
NEVER_HIDDEN = frozenset({"Exalted Orb", "Chaos Orb", "Divine Orb"})  # the coins prices are counted in: never hidden, however cheap one of them is
SAFE_FILE = re.compile(r"^[^\\/:*?\"<>|]+$")
KIND_TITLES = {"Currency": "Валюта", "Essences": "Эссенции", "Runes": "Руны", "SoulCores": "Ядра душ", "Ritual": "Знамения", "Breach": "Разлом", "Delirium": "Делириум",
               "Fragments": "Фрагменты", "Expedition": "Экспедиция", "Abyss": "Бездна", "Idols": "Идолы", "Verisium": "Веризий", "UncutGems": "Неогранённые камни",
               "LineageSupportGems": "Камни родословной"}  # the market's sections, as the prices name them
KIND_RULES = {"same": ("Как все", 1.0), "softer": ("Мягче", 0.5), "stricter": ("Строже", 2.0), "skip": ("Не трогать", None)}  # how a kind's thresholds move
ITEM_RULES = {"loud": "Всегда громко", "hide": "Всегда прятать", "normal": "Как в обычном фильтре"}
PRESETS = {  # a whole set of lines in one click: (threshold, unit, loudness) from the dearest, and the hiding line
    "soft": ("Мягко", ((1.0, "div", "loud"), (20.0, "ex", "loud"), (3.0, "ex", "noticeable")), None),
    "normal": ("Обычно", ((1.0, "div", "loud"), (60.0, "ex", "loud"), (12.0, "ex", "noticeable")), None),
    "strict": ("Строго", ((2.0, "div", "loud"), (150.0, "ex", "loud"), (40.0, "ex", "noticeable")), 10.0),
}
LINKS = {"copy": "Копией (надёжно)", "import": "Ссылкой Import (файл меньше)"}  # how the usual filter joins Sakuya's: its text copied in, or one Import line
TYPING_PAUSE_MS = 500  # a number typed with the file kept up by itself is written once the typing stops, not at every key
SOUND_PACKS = {"game": "Звуки игры", "chimes": "Колокольчики", "soft": "Мягкие", "coins": "Монеты", "none": "Без звука"}


# ----------------------------------------------------------------------------------- the file
def documents_folder() -> Path | None:
    """The player's Documents, where Windows keeps it (it may be moved, to OneDrive or another drive)."""
    try:
        buffer = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer) == 0:  # CSIDL_PERSONAL
            return Path(buffer.value)
    except (AttributeError, OSError):
        pass
    return None


def filter_folder(documents: Path | None = None) -> Path | None:
    """The game's own folder for filters, if the game has made it."""
    documents = documents or documents_folder()
    folder = documents / GAME_FOLDER if documents else None
    return folder if folder and folder.is_dir() else None


def usual_filters(folder: Path | None) -> list[str]:
    """The player's filter files to build on, by name only: Sakuya's own files are not among them."""
    if not folder:
        return []
    return sorted((path.name for path in folder.glob("*.filter") if path.name.casefold() not in (FILTER_NAME.casefold(), "sakuya_test.filter")), key=str.casefold)


def filtered_names(prices_in_divine: dict[str, float]) -> dict[str, float]:
    """The priced goods a filter can name: one base each. A name with a variant in brackets, such as a gem's level, is many items under one base."""
    return {name: value for name, value in prices_in_divine.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 and "(" not in name and '"' not in name and name.strip() == name and name}


def _number(value, low=0.0, high=1e7):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and low < value < high else None


def _whole(value, low: int, high: int, fallback: int) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high else fallback


def _clean_tier(raw: dict, default: dict) -> dict:
    """One line of the filter, from what was saved; the older shape (three switches and a size word) reads as its nearest."""
    color = raw.get("color") if raw.get("color") in COLORS else default["color"]
    beam, icon, sound = raw.get("beam", default["beam"]), raw.get("icon", default["icon"]), raw.get("sound", default["sound"])
    if isinstance(beam, bool):
        beam = {"color": COLORS[color][3], "temp": False} if beam else None
    if isinstance(icon, bool):
        icon = dict(default["icon"] or {"size": 1, "color": COLORS[color][3], "shape": "Circle"}) if icon else None
    if isinstance(sound, bool):
        sound = dict(default["sound"] or {"kind": "builtin", "id": 1, "volume": 250}) if sound else None
    beam = {"color": beam.get("color") if beam.get("color") in GAME_COLORS else "Red", "temp": beam.get("temp") is True} if isinstance(beam, dict) else None
    icon = ({"size": _whole(icon.get("size"), 0, 2, 1), "color": icon.get("color") if icon.get("color") in GAME_COLORS else "Yellow",
             "shape": icon.get("shape") if icon.get("shape") in ICON_SHAPES else "Circle"} if isinstance(icon, dict) else None)
    if isinstance(sound, dict) and sound.get("kind") == "custom" and isinstance(sound.get("file"), str) and SAFE_FILE.match(sound["file"]) and sound["file"].casefold().endswith(SOUND_TYPES):
        sound = {"kind": "custom", "file": sound["file"], "volume": _whole(sound.get("volume"), 0, 300, 250)}
    elif isinstance(sound, dict):
        sound = {"kind": "builtin", "id": _whole(sound.get("id"), 1, 16, 1), "volume": _whole(sound.get("volume"), 0, 300, 250)}
    else:
        sound = None
    name = raw.get("name") if isinstance(raw.get("name"), str) and raw["name"].strip() else default["name"]
    font = raw.get("font") if isinstance(raw.get("font"), int) and not isinstance(raw.get("font"), bool) else {"small": 35, "medium": 40, "large": 45}.get(raw.get("size"), default["font"])
    return {"name": name.strip()[:30], "least": _number(raw.get("least")) or default["least"], "unit": raw.get("unit") if raw.get("unit") in UNITS else default["unit"],
            "color": color, "font": min(max(int(font), FONT_RANGE[0]), FONT_RANGE[1]), "beam": beam, "icon": icon, "sound": sound}


def clean_settings(stored) -> dict:
    """filter.json as read: anything odd falls back to the defaults, one field at a time."""
    stored = stored if isinstance(stored, dict) else {}
    raw_tiers = [tier for tier in stored.get("tiers", []) if isinstance(tier, dict)][:MOST_TIERS] if isinstance(stored.get("tiers"), list) else []
    if not raw_tiers:
        raw_tiers = [{} for _ in DEFAULT_TIERS]
    fallback = lambda position: DEFAULT_TIERS[min(position, len(DEFAULT_TIERS) - 1)]
    base = stored.get("base")
    items = stored.get("items") if isinstance(stored.get("items"), dict) else {}
    kinds = stored.get("kinds") if isinstance(stored.get("kinds"), dict) else {}
    return {"auto": stored.get("auto") is True, "base": base if isinstance(base, str) and base.casefold().endswith(".filter") and SAFE_FILE.match(base) else None,
            "hide_below": _number(stored.get("hide_below")), "tiers": [_clean_tier(raw, fallback(position)) for position, raw in enumerate(raw_tiers)],
            "items": {name: rule for name, rule in items.items() if isinstance(name, str) and 0 < len(name) <= 120 and '"' not in name and rule in ITEM_RULES},
            "kinds": {kind: rule for kind, rule in kinds.items() if kind in KIND_TITLES and rule in KIND_RULES and rule != "same"},
            "sound_pack": stored.get("sound_pack") if stored.get("sound_pack") in SOUND_PACKS else None,
            "link": stored.get("link") if stored.get("link") in LINKS else "copy"}


def in_divine(amount: float, unit: str, exalted_per_divine: float | None) -> float | None:
    if unit == "div":
        return amount
    return amount / exalted_per_divine if exalted_per_divine else None


def dearest_first(settings: dict, exalted_per_divine: float | None) -> list[int]:
    """The lines from the dearest threshold down: an item goes to the first it reaches, whatever order the player made them in."""
    return sorted(range(len(settings["tiers"])), key=lambda position: -(in_divine(settings["tiers"][position]["least"], settings["tiers"][position]["unit"], exalted_per_divine) or 0))


def tiered(prices_in_divine: dict[str, float], settings: dict, exalted_per_divine: float | None, kinds: dict[str, str] | None = None) -> tuple[list[list[str]], list[str]]:
    """The goods of each line, dearest first, each in the dearest line it reaches; and the goods to hide below the hiding line.
    A kind made softer meets every threshold at half its price, a stricter one at twice; a kind left alone and the goods with a rule of their own are not placed."""
    kinds, kind_rules, own = kinds or {}, settings.get("kinds", {}), settings.get("items", {})
    factors = {name: KIND_RULES[kind_rules.get(kinds.get(name), "same")][1] for name in prices_in_divine}
    names = {name: value / factors[name] for name, value in filtered_names(prices_in_divine).items() if name not in own and factors[name] is not None}
    tiers, placed = [[] for _ in settings["tiers"]], set()
    for position in dearest_first(settings, exalted_per_divine):
        tier = settings["tiers"][position]
        least = in_divine(tier["least"], tier["unit"], exalted_per_divine)
        chosen = sorted((name for name, value in names.items() if least is not None and value >= least and name not in placed), key=lambda name: (-names[name], name))
        tiers[position] = chosen
        placed.update(chosen)
    line = in_divine(settings["hide_below"], "ex", exalted_per_divine) if settings.get("hide_below") else None
    hidden = sorted(name for name, value in names.items() if line is not None and value < line and name not in placed and name not in NEVER_HIDDEN) if line else []
    return tiers, hidden


def item_rules(settings: dict) -> tuple[list[str], list[str]]:
    """The goods the player set by hand: always loud, and always hidden. «As the usual filter» is neither: Sakuya leaves them alone."""
    own = settings.get("items", {})
    return sorted(name for name, rule in own.items() if rule == "loud"), sorted(name for name, rule in own.items() if rule == "hide" and name not in NEVER_HIDDEN)


def apply_preset(settings: dict, key: str, exalted_per_divine: float | None = None) -> None:
    """A whole set of lines at once: the thresholds and loudness of the preset, each line keeping its name and colour where there is one."""
    _, lines, hide_below = PRESETS[key]
    tiers = [settings["tiers"][position] for position in dearest_first(settings, exalted_per_divine)]
    fresh = []
    for number, (least, unit, loud) in enumerate(lines):
        tier = dict(tiers[number]) if number < len(tiers) else dict(DEFAULT_TIERS[number])
        tier.update(least=least, unit=unit)
        tier.update(loudness_marks(loud, tier))
        fresh.append(tier)
    settings["tiers"] = fresh
    settings["hide_below"] = hide_below


def loudness_marks(key: str, tier: dict) -> dict:
    """The beam, icon and sound a loudness choice gives, in the line's own colour."""
    named = COLORS[tier["color"]][3]
    if key == "loud":
        return {"beam": {"color": named, "temp": False}, "icon": {"size": 0, "color": named, "shape": "Star"}, "sound": {"kind": "builtin", "id": 6, "volume": 300}}
    if key == "noticeable":
        return {"beam": None, "icon": {"size": 1, "color": named, "shape": "Circle"}, "sound": None}
    return {"beam": None, "icon": None, "sound": None}


def loudness_of(tier: dict) -> str:
    """The one choice the main row shows for the beam, the icon and the sound; anything set by hand is «own»."""
    for key in ("loud", "noticeable", "quiet"):
        marks = loudness_marks(key, tier)
        if all(tier.get(part) == marks[part] for part in marks):
            return key
    return "own"


def _color(rgb) -> str:
    return " ".join(str(part) for part in rgb) + " 255"


def _block(names: list[str], tier: dict, title: str) -> str:
    back, text, border, _ = COLORS[tier["color"]]
    lines = [f"# {title}", "Show", "    BaseType == " + " ".join(f'"{name}"' for name in names), f"    SetFontSize {tier['font']}",
             f"    SetTextColor {_color(text)}", f"    SetBackgroundColor {_color(back)}", f"    SetBorderColor {_color(border)}"]
    if tier["beam"]:
        lines.append(f"    PlayEffect {tier['beam']['color']}" + (" Temp" if tier["beam"]["temp"] else ""))
    if tier["icon"]:
        lines.append(f"    MinimapIcon {tier['icon']['size']} {tier['icon']['color']} {tier['icon']['shape']}")
    sound = tier["sound"]
    if sound and sound["kind"] == "builtin":
        lines.append(f"    PlayAlertSound {sound['id']} {sound['volume']}")
    elif sound:
        lines.append(f'    CustomAlertSound "{SOUND_FOLDER}/{sound["file"]}" {sound["volume"]}')
    return "\n".join(lines) + "\n"


def filter_text(prices_in_divine: dict[str, float], league: str, settings: dict, exalted_per_divine: float | None, now: datetime, kinds: dict[str, str] | None = None,
                base_text: str | None = None) -> str:
    """The whole file: what it is, the goods set by hand, one block for each line of worth, the hidden cheap goods, and the player's usual filter for all the rest."""
    tiers, hidden = tiered(prices_in_divine, settings, exalted_per_divine, kinds)
    loud, hidden_by_hand = item_rules(settings)
    blocks = []
    if loud:
        top = settings["tiers"][dearest_first(settings, exalted_per_divine)[0]]
        blocks.append(_block(loud, {**top, **loudness_marks("loud", top)}, f"Set by hand to be loud: {len(loud)} goods"))
    if hidden_by_hand:
        blocks.append(f"# Set by hand to be hidden: {len(hidden_by_hand)} goods\nHide\n    BaseType == " + " ".join(f'"{name}"' for name in hidden_by_hand) + "\n")
    for position in dearest_first(settings, exalted_per_divine):
        tier = settings["tiers"][position]
        if tiers[position]:
            blocks.append(_block(tiers[position], tier, f"{tier['name']}: {tier['least']:g} {tier['unit']} and more, {len(tiers[position])} goods"))
    if hidden:
        blocks.append(f"# Below {settings['hide_below']:g} ex: {len(hidden)} goods hidden\nHide\n    BaseType == " + " ".join(f'"{name}"' for name in hidden) + "\n")
    head = ["# Sakuya.filter: written by Sakuya from current prices, rewritten when they change. Edits here are lost on the next write.",
            f"# League: {league}. Prices of {now.strftime('%Y-%m-%d %H:%M')}.",
            "# In the game, pick Sakuya in Options, Game, Item Filter. If a newer file does not show, press Reload there.", ""]
    base = settings.get("base")
    if base and settings.get("link", "copy") == "copy" and base_text is not None:  # the usual filter's own text below Sakuya's: it works whether or not the game knows Import
        tail = ["", f"# ---- Your usual filter, copied from {base}. Sakuya copies it again when it writes this file. ----", base_text.rstrip("\n")]
    elif base:
        tail = ["", f'Import "{base}" Optional']
    else:
        tail = ["", "# No usual filter chosen in Sakuya: everything else shows as the game does without a filter."]
    return "\n".join(head) + "\n".join(blocks) + "\n".join(tail) + "\n"


def read_usual_filter(folder: Path, name: str | None) -> str | None:
    """The player's usual filter as text, to copy in below Sakuya's rules. None when there is none or it cannot be read."""
    if not name:
        return None
    try:
        return (folder / name).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None


def write_filter(folder: Path, text: str) -> bool:
    """Writes Sakuya.filter when its rules changed; the time line alone is no reason to write. True when the file was written."""
    path = folder / FILTER_NAME
    try:
        old = path.read_text(encoding="utf-8")
    except OSError:
        old = ""
    if _without_time(old) == _without_time(text):
        return False
    temporary = path.with_suffix(".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
    return True


def _without_time(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.startswith("# League:"))


def add_sound(folder: Path, chosen: Path) -> str:
    """Copies a sound file the player picked into «Sakuya sounds» beside the filters, where the game looks for it. Gives the name to use."""
    if chosen.suffix.casefold() not in SOUND_TYPES or not SAFE_FILE.match(chosen.name):
        raise ValueError("only .mp3 and .wav files with a plain name")
    target = folder / SOUND_FOLDER
    target.mkdir(exist_ok=True)
    if chosen.resolve() != (target / chosen.name).resolve():
        shutil.copy2(chosen, target / chosen.name)
    return chosen.name


PACK_NOTES = {  # (notes in Hz, seconds between them, how fast each fades, overtones) for the dearest line, the next, and the rest
    "chimes": (((1047, 1319, 1568), 0.09, 4.0), ((1319, 1568), 0.09, 4.5), ((1568,), 0.0, 6.0)), "chimes_overtones": ((1, 1.0), (2, 0.3), (3, 0.1)),
    "soft": (((523, 659, 784), 0.15, 3.0), ((523, 659), 0.15, 3.5), ((659,), 0.0, 4.5)), "soft_overtones": ((1, 1.0), (2, 0.15)),
    "coins": (((2093, 2637, 2093, 2637), 0.07, 9.0), ((2093, 2637), 0.07, 9.0), ((2637,), 0.0, 10.0)), "coins_overtones": ((1, 1.0), (1.5, 0.5), (2.3, 0.3)),
}


def write_tone(path: Path, notes, gap: float, fade: float, overtones, seconds: float = 0.9, rate: int = 22050) -> None:
    """A short sound made from a few bell-like notes: no file of anyone else is used."""
    samples = []
    for index in range(int(seconds * rate)):
        moment, value = index / rate, 0.0
        for number, frequency in enumerate(notes):
            start = number * gap
            if moment >= start:
                age = moment - start
                value += math.exp(-age * fade) * sum(share * math.sin(2 * math.pi * frequency * multiple * age) for multiple, share in overtones)
        samples.append(value)
    loudest = max((abs(sample) for sample in samples), default=1.0) or 1.0
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(b"".join(struct.pack("<h", int(sample / loudest * 0.8 * 32767)) for sample in samples))


def pack_files(folder: Path, pack: str) -> list[str]:
    """The three sounds of one of Sakuya's own packs, made into «Sakuya sounds» the first time they are needed."""
    target = folder / SOUND_FOLDER
    target.mkdir(exist_ok=True)
    names = []
    for number, (notes, gap, fade) in enumerate(PACK_NOTES[pack], 1):
        name = f"Sakuya {pack} {number}.wav"
        if not (target / name).is_file():
            write_tone(target / name, notes, gap, fade, PACK_NOTES[pack + "_overtones"])
        names.append(name)
    return names


def apply_sound_pack(settings: dict, pack: str, folder: Path | None, exalted_per_divine: float | None = None) -> None:
    """One pack's sounds for the lines from the dearest down: the game's own numbers, Sakuya's made sounds, or silence. Lines past the third keep none."""
    order = dearest_first(settings, exalted_per_divine)
    files = pack_files(folder, pack) if pack in ("chimes", "soft", "coins") and folder else []
    for rank, position in enumerate(order):
        tier = settings["tiers"][position]
        volume = (tier["sound"] or {}).get("volume", 250)
        if pack == "game" and rank < 3:
            tier["sound"] = {"kind": "builtin", "id": (6, 2, 1)[rank], "volume": volume}
        elif files and rank < 3:
            tier["sound"] = {"kind": "custom", "file": files[rank], "volume": volume}
        else:
            tier["sound"] = None
    settings["sound_pack"] = pack


def play_sound(path: Path, volume: int = 300) -> None:
    """Plays a sound file through Windows, so the player hears it before choosing; the game's own sounds are its files and are not read."""
    winmm = ctypes.windll.winmm
    winmm.mciSendStringW("close sakuya_sound", None, 0, None)
    if winmm.mciSendStringW(f'open "{path}" type mpegvideo alias sakuya_sound', None, 0, None) == 0:
        winmm.mciSendStringW(f"setaudio sakuya_sound volume to {min(1000, int(volume / 300 * 1000))}", None, 0, None)
        winmm.mciSendStringW("play sakuya_sound", None, 0, None)


def _hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


# ----------------------------------------------------------------------------------- the page
GUIDES = {  # the «?» of each step: what it does, in plain words
    1: 'Sakuya.filter — это подсветка по ценам, а под ней ваш обычный фильтр. Всё, что Sakuya не подсвечивает, выглядит в игре как раньше.\n• В списке фильтры из папки игры. Нужного нет — скачайте его (NeverSink, FilterBlade и другие), положите в папку (кнопка в шаге 6) и откройте эту страницу заново.\n• «Без обычного фильтра» — останется только подсветка Sakuya, остальное игра покажет как без фильтра.\n• «Копией» — текст вашего фильтра вписывается в конец Sakuya.filter. Работает наверняка. Поменяли свой фильтр — сохраните Sakuya ещё раз или включите обновление в шаге 6.\n• «Ссылкой Import» — вместо текста одна строка со ссылкой на ваш фильтр. Файл меньше, но работает, только если игра понимает Import.',
    2: 'Строки — это ступени ценности. Например: «Очень дорогое» от 1 div, «Дорогое» от 10 ex, «Стоит поднять» от 2 ex. Вещь за 5 ex попадёт в «Стоит поднять», за 2 div — в «Очень дорогое».\n• Порог — цена, с которой вещь попадает в строку, в ex или div. Цены те же, что на странице «Цены», для выбранной лиги.\n• Цвет — цвет подписи и рамки на земле.\n• «Громко» — луч, звук и значок на миникарте. «Значок» — только значок. «Только цвет» — тихо, одним цветом.\n• «⚙» — всё у строки по-своему: размер шрифта, луч (с галочкой «только при выпадении» он мигнёт и погаснет), значок на миникарте, звук из игры или свой mp3 или wav (▶ — послушать) и громкость.\n• «Набор» ставит пороги и громкость всем строкам сразу: «Мягко» подсвечивает больше, «Строго» — только дорогое и прячет мелочь дешевле 10 ex. Названия и цвета строк остаются ваши.\n• «Звуки» — готовый набор звуков сразу на все строки.\n• «＋ Добавить строку» — до шести строк, «✕» убирает строку.',
    3: 'Тонкая настройка по видам товаров. Для вещей этого вида пороги из шага 2 меняются:\n• «Мягче» — порог вдвое ниже: эссенция за 1 ex подсветится как вещь за 2 ex.\n• «Строже» — порог вдвое выше: подсветится только то, что дороже.\n• «Не трогать» — Sakuya этот вид не подсвечивает и не прячет, его решает ваш обычный фильтр.\n• «Как все» — пороги как в шаге 2.\nНапример: крафтите и эссенции нужны — «Мягче»; руны не интересны — «Не трогать».',
    4: 'Правило для одного предмета, сильнее порогов и видов. Начните вводить название по-русски или по-английски и выберите из подсказок.\n• «Всегда громко» — подсветить, даже если он дешёвый (например, нужная вам руна или сфера для крафта).\n• «Всегда прятать» — не показывать вовсе.\n• «Как в обычном фильтре» — Sakuya его не трогает.\nПравило можно поменять в списке, «✕» его убирает.',
    5: 'Можно спрятать мелочь, чтобы она не мусорила на земле. Например, «Прятать то, что дешевле 2 ex» — Sakuya скроет валюту, эссенции, руны и прочее, что стоит меньше 2 ex.\n• Прячется только то, что продаётся по имени и у чего есть цена. Редкие, уникальные и прочие вещи решает ваш обычный фильтр.\n• Exalted, Chaos и Divine не прячутся никогда.\n• «Показывать как в обычном фильтре» — Sakuya ничего не прячет.',
    6: '1. «Сохранить фильтр в игру» — Sakuya запишет Sakuya.filter в папку фильтров игры (Документы\\My Games\\Path of Exile 2).\n2. В игре: Esc → Настройки → Игра → Фильтр предметов → выберите Sakuya.\n3. Игра читает фильтр, когда его выбирают. Чтобы увидеть свежий файл, нажмите в тех же настройках кнопку обновления фильтра рядом со списком.\n• «Обновлять самому, когда меняются цены» — Sakuya перепишет файл, когда скачает новые цены, и заодно после ваших правок на этой странице.\n• «Открыть папку фильтров» — там Sakuya.filter, ваши фильтры и папка «Sakuya sounds» со звуками.\n• Не понравилось — просто выберите в игре свой прежний фильтр, он не менялся.',
}


class FilterPage:
    """«Filter», step by step: the usual filter that stays, what to light up and how, what to do with the cheap, and saving it for the game."""

    def __init__(self, parent, colors: dict, translate, helpers: dict):
        self.colors, self.t, self.helpers = colors, translate, helpers
        self.settings = clean_settings(helpers["load"]())
        self.open_details: set[int] = set()
        self.open_help: set[int] = set()  # steps whose «?» is open; they stay open while the page is rebuilt
        page = tk.Frame(parent, bg=colors["background"], padx=10)
        page.pack(fill="both", expand=True)
        self.page = page
        intro = tk.Label(page, text=self.t("Sakuya делает свой фильтр поверх вашего: по текущим ценам подсвечивает то, что стоит поднять. Всё остальное остаётся как в вашем фильтре.") + " " + self.t('Нажмите «?» у любого шага — там подробно, что он делает.'),
                         bg=colors["background"], fg=colors["soft"], font=(BODY, 10), justify="left", anchor="w", wraplength=900)
        intro.pack(fill="x", pady=(0, 8))
        intro.bind("<Configure>", lambda event: intro.configure(wraplength=max(event.width - 8, 200)))  # wraps at the window's width, so no words run past its edge
        self.status = tk.Label(page, bg=colors["background"], fg=colors["soft"], font=(BODY, 9), anchor="w")
        self.status.pack(side="bottom", fill="x", pady=(6, 0))
        body = tk.Frame(page, bg=colors["background"])
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3, uniform="filter")
        body.columnconfigure(1, weight=2, uniform="filter")
        body.rowconfigure(0, weight=1)
        holder = tk.Frame(body, bg=colors["background"])
        holder.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        holder.columnconfigure(0, weight=1)
        holder.columnconfigure(1, minsize=11)
        holder.rowconfigure(0, weight=1)
        self.steps_canvas = tk.Canvas(holder, bg=colors["background"], highlightthickness=0, bd=0)
        self.steps_canvas.grid(row=0, column=0, sticky="nsew")
        self.steps = self._new_steps()
        self.steps_window = self.steps_canvas.create_window(0, 0, window=self.steps, anchor="nw")
        self.steps_canvas.bind("<Configure>", lambda event: self.steps_canvas.itemconfigure(self.steps_window, width=event.width))
        helpers["enable_scrolling"](holder, self.steps_canvas)
        side = tk.Frame(body, bg=colors["panel"], padx=12, pady=10)
        side.grid(row=0, column=1, sticky="nsew")
        tk.Label(side, text=self.t("Так это будет выглядеть в игре"), bg=colors["panel"], fg=colors["accent"], font=(BODY, 11, "bold"), anchor="w").pack(fill="x")
        self.counts = tk.Label(side, bg=colors["panel"], fg=colors["muted"], font=(BODY, 9), anchor="w", justify="left", wraplength=330)
        self.counts.pack(side="bottom", fill="x", pady=(8, 0))  # first, so a small screen takes its room from the preview rather than from these lines
        self.preview = tk.Canvas(side, bg="#141210", highlightthickness=0, height=200)
        self.preview.pack(fill="both", expand=True, pady=(8, 0))

    # ---- settings
    def _save(self) -> None:
        self.helpers["save"](self.settings)

    def _changed(self, redraw_steps: bool = True, typing: bool = False) -> None:
        """Any choice: saved at once, shown at once, and the file follows if it is kept up by itself. While a number is typed it follows once the typing stops."""
        self._save()
        if redraw_steps:
            self._render_lines()
        else:
            self._draw_preview()
        if not self.settings["auto"]:
            return
        if getattr(self, "write_job", None):
            self.page.after_cancel(self.write_job)
            self.write_job = None
        if typing:
            self.write_job = self.page.after(TYPING_PAUSE_MS, self._write_after_typing)
        else:
            self.write_now(quiet=True)

    def _write_after_typing(self) -> None:
        self.write_job = None
        if self.page.winfo_exists():
            self.write_now(quiet=True)

    def _open_folder(self) -> None:
        folder = filter_folder()
        if folder:
            os.startfile(folder)
        else:
            self.status.config(text=self.t("Папки фильтров нет: запустите игру хотя бы раз"))

    # ---- the file
    def write_now(self, quiet: bool = False) -> None:
        folder = filter_folder()
        if not folder:
            return self.status.config(text=self.t("Папки фильтров нет: запустите игру хотя бы раз"))
        prices = self.helpers["prices"]() or {}
        if not prices.get("prices_in_divine"):
            return self.status.config(text=self.t("Цены ещё загружаются"))
        text = filter_text(prices["prices_in_divine"], prices.get("league", ""), self.settings, prices.get("exalted_per_divine"), datetime.now(), prices.get("kinds"),
                           read_usual_filter(folder, self.settings.get("base")))
        try:
            written = write_filter(folder, text)
        except OSError as error:
            return self.status.config(text=self.t("Не удалось записать фильтр: {error}").format(error=error))
        stamp = datetime.now().strftime("%H:%M")
        self.status.config(text=self.t("Sakuya.filter записан в {time}").format(time=stamp) if written else self.t("Sakuya.filter уже такой, переписывать нечего"))

    def prices_changed(self) -> None:
        """New prices came: the file follows them when the player asked for that."""
        if self.settings["auto"]:
            self.write_now(quiet=True)
        if self.page.winfo_exists() and self.page.winfo_ismapped():
            self._draw_preview()

    # ---- drawing
    def _step(self, number: int, title: str, hint: str = "") -> tk.Frame:
        """One numbered step: a card with its number, title, a line of help, and a «?» that opens the step's guide in plain words."""
        colors = self.colors
        card = tk.Frame(self.steps, bg=colors["panel"], padx=12, pady=8)
        card.pack(fill="x", pady=(0, 6))
        head = tk.Frame(card, bg=colors["panel"])
        head.pack(fill="x")
        tk.Label(head, text=str(number), bg=colors["selected"], fg=colors.get("on_selected", colors["text"]), font=(BODY, 10, "bold"), width=2).pack(side="left")
        tk.Label(head, text=title, bg=colors["panel"], fg=colors["text"], font=(BODY, 11, "bold")).pack(side="left", padx=(8, 0))
        if hint:
            tk.Label(card, text=hint, bg=colors["panel"], fg=colors["muted"], font=(BODY, 9), anchor="w", justify="left", wraplength=500).pack(fill="x", pady=(4, 0))
        inner = tk.Frame(card, bg=colors["panel"])
        inner.pack(fill="x", pady=(6, 0))
        if number in GUIDES:
            guide = tk.Label(card, text=self.t(GUIDES[number]), bg=colors["raised"], fg=colors["text"], font=(BODY, 9), anchor="w", justify="left", wraplength=500, padx=10, pady=8)
            mark = tk.Label(head, text=" ? ", bg=colors["raised"], fg=colors["accent"], font=(BODY, 10, "bold"), cursor="hand2")
            mark.pack(side="right")

            def show(opened: bool) -> None:
                mark.config(text=" ✕ " if opened else " ? ")
                if opened:
                    guide.pack(fill="x", pady=(6, 0), before=inner)
                else:
                    guide.pack_forget()

            def toggle(_=None) -> None:
                self.open_help.symmetric_difference_update({number})
                show(number in self.open_help)

            mark.bind("<Button-1>", toggle)
            mark.bind("<Enter>", lambda _: mark.config(bg=colors["selected"], fg=colors.get("on_selected", colors["text"])))
            mark.bind("<Leave>", lambda _: mark.config(bg=colors["raised"], fg=colors["accent"]))
            show(number in self.open_help)
        return inner

    def _combo(self, parent, values: list[str], current: str, width: int, chose) -> ttk.Combobox:
        box = ttk.Combobox(parent, state="readonly", width=width, values=values)
        box.set(current)
        box.bind("<<ComboboxSelected>>", lambda _: chose(box))
        box.bind("<MouseWheel>", lambda _: "break")  # scrolling the page must not turn a choice over
        return box

    def _new_steps(self) -> tk.Frame:
        frame = tk.Frame(self.steps_canvas, bg=self.colors["background"])
        frame.bind("<Configure>", lambda _: self.steps_canvas.configure(scrollregion=self.steps_canvas.bbox("all")))
        return frame

    def render(self, keep_place: bool = False) -> None:
        """The steps are built anew out of sight and take the old ones' place in one stroke, at the same scroll: removing a line or opening its settings does not make the page jump."""
        colors, t, helpers = self.colors, self.t, self.helpers
        old = self.steps
        place = self.steps_canvas.yview()[0] * max(old.winfo_height(), 1) if keep_place else 0  # in pixels: the page above the change stays put
        self.steps = self._new_steps()
        folder = filter_folder()

        step = self._step(1, t("Ваш обычный фильтр"), t("Им показывается всё, что Sakuya не подсвечивает. Выберите тот, которым играете."))
        choices = [t("Без обычного фильтра"), *usual_filters(folder)]

        def chose_base(box):
            self.settings["base"] = None if box.current() == 0 else box.get()
            self._changed(redraw_steps=False)

        self._combo(step, choices, self.settings["base"] if self.settings["base"] in choices else choices[0], 40, chose_base).pack(side="left")
        if not folder:
            tk.Label(step, text=t("Папки фильтров нет: запустите игру хотя бы раз"), bg=colors["panel"], fg=colors["accent"], font=(BODY, 9)).pack(side="left", padx=10)
        link_row = tk.Frame(step.master, bg=colors["panel"])
        link_row.pack(fill="x", pady=(6, 0))
        tk.Label(link_row, text=t("Подключать:"), bg=colors["panel"], fg=colors["muted"], font=(BODY, 9)).pack(side="left", padx=(0, 6))
        link = tk.StringVar(value=self.settings["link"])

        def chose_link():
            self.settings["link"] = link.get()
            self._changed(redraw_steps=False)

        for key, title in LINKS.items():
            tk.Radiobutton(link_row, text=t(title), variable=link, value=key, command=chose_link, bg=colors["panel"], fg=colors["text"], selectcolor=colors["raised"],
                           activebackground=colors["panel"], activeforeground=colors["text"], font=(BODY, 9), cursor="hand2").pack(side="left", padx=(0, 8))

        step = self._step(2, t("Что подсвечивать"), t("Каждая вещь попадает в самую дорогую строку, до которой дотягивает её цена. «Громко» — луч, звук и значок на карте, «Значок» — только значок, «Только цвет» — без них. «⚙» — свой звук, шрифт, луч и значок."))
        quick = tk.Frame(step.master, bg=colors["panel"])
        quick.pack(fill="x", pady=(6, 0), before=step)
        tk.Label(quick, text=t("Набор:"), bg=colors["panel"], fg=colors["muted"], font=(BODY, 9)).pack(side="left", padx=(0, 4))
        for key, (title, _, _) in PRESETS.items():
            helpers["button"](quick, t(title), lambda k=key: self._use_preset(k)).pack(side="left", padx=(0, 4))
        tk.Label(quick, text=t("Звуки:"), bg=colors["panel"], fg=colors["muted"], font=(BODY, 9)).pack(side="left", padx=(12, 4))
        packs = list(SOUND_PACKS)
        chosen_pack = self.settings.get("sound_pack")
        self._combo(quick, [t(title) for title in SOUND_PACKS.values()], t(SOUND_PACKS[chosen_pack]) if chosen_pack else t("Свои"), 12,
                    lambda box: self._use_pack(packs[box.current()])).pack(side="left")
        helpers["button"](quick, "▶", self._play_pack).pack(side="left", padx=(4, 0))
        self.lines_box = tk.Frame(step, bg=colors["panel"])
        self.lines_box.pack(fill="x")
        self._fill_lines(self.lines_box)

        step = self._step(3, t("Виды предметов"), t("Пороги по видам, как смешанная строгость: «Мягче» — вещи этого вида подсвечиваются при вдвое меньшей цене, «Строже» — при вдвое большей, «Не трогать» — их решает обычный фильтр."))
        kinds_present = sorted({kind for kind in (self.helpers["prices"]() or {}).get("kinds", {}).values() if kind in KIND_TITLES}, key=lambda kind: list(KIND_TITLES).index(kind))
        grid = tk.Frame(step, bg=colors["panel"])
        grid.pack(fill="x")
        rule_keys = list(KIND_RULES)
        for number, kind in enumerate(kinds_present or KIND_TITLES):
            cell = tk.Frame(grid, bg=colors["panel"])
            cell.grid(row=number // 2, column=number % 2, sticky="w", padx=(0, 18), pady=1)
            tk.Label(cell, text=t(KIND_TITLES[kind]), bg=colors["panel"], fg=colors["text"], font=(BODY, 9), width=19, anchor="w").pack(side="left")

            def chose_kind(box, kind=kind):
                rule = rule_keys[box.current()]
                if rule == "same":
                    self.settings["kinds"].pop(kind, None)
                else:
                    self.settings["kinds"][kind] = rule
                self._changed(redraw_steps=False)

            self._combo(cell, [t(title) for title, _ in KIND_RULES.values()], t(KIND_RULES[self.settings["kinds"].get(kind, "same")][0]), 11, chose_kind).pack(side="left")

        step = self._step(4, t("Отдельные предметы"), t("Найдите предмет и задайте ему своё правило: оно сильнее порогов и видов."))
        self._item_rules_step(step)

        step = self._step(5, t("Дешёвое"), t("Только из того, что продаётся по имени: валюта, эссенции, руны, ядра. Exalted, Chaos и Divine не прячутся никогда."))
        hide_on = tk.BooleanVar(value=self.settings["hide_below"] is not None)
        amount = tk.StringVar(value=f"{self.settings['hide_below'] or 2:g}")

        def set_hide(*_):
            try:
                value = float(amount.get().replace(",", "."))
            except ValueError:
                return
            if value > 0:
                self.settings["hide_below"] = value if hide_on.get() else None
                self._changed(redraw_steps=False, typing=True)

        for on, title in ((False, t("Показывать как в обычном фильтре")), (True, t("Прятать то, что дешевле"))):
            tk.Radiobutton(step, text=title, variable=hide_on, value=on, command=set_hide, bg=colors["panel"], fg=colors["text"], selectcolor=colors["raised"],
                           activebackground=colors["panel"], activeforeground=colors["text"], font=(BODY, 10), cursor="hand2").pack(side="left", padx=(0, 6))
        entry = helpers["entry"](step, amount, 5)
        entry.pack(side="left", ipady=2)
        entry.bind("<KeyRelease>", set_hide)
        tk.Label(step, text="ex", bg=colors["panel"], fg=colors["muted"], font=(BODY, 9)).pack(side="left", padx=(4, 0))

        step = self._step(6, t("Сохранить и включить в игре"),
                          t("1. Нажмите «Сохранить фильтр в игру». 2. В игре: Настройки → Игра → Фильтр предметов → Sakuya. 3. Если потом фильтр обновился, а в игре не видно, нажмите там «Перезагрузить»."))
        helpers["button"](step, t("Сохранить фильтр в игру"), self.write_now, True).pack(side="left")
        helpers["button"](step, t("Открыть папку фильтров"), self._open_folder).pack(side="left", padx=(8, 0))
        second = tk.Frame(step.master, bg=colors["panel"])
        second.pack(fill="x", pady=(8, 0))
        auto = tk.BooleanVar(value=self.settings["auto"])

        def set_auto():
            self.settings["auto"] = auto.get()
            self._save()
            if self.settings["auto"]:
                self.write_now()

        helpers["switch"](second, t("Обновлять самому, когда меняются цены"), auto, set_auto, size=9).pack(side="left")
        self._draw_preview()
        self.steps.update_idletasks()  # the new steps have their size before they are shown
        self.steps_canvas.itemconfigure(self.steps_window, window=self.steps)
        self.steps_canvas.configure(scrollregion=(0, 0, self.steps_canvas.winfo_width(), self.steps.winfo_reqheight()))
        self.steps_canvas.yview_moveto(place / max(self.steps.winfo_reqheight(), 1))
        old.destroy()

    def _use_preset(self, key: str) -> None:
        apply_preset(self.settings, key, (self.helpers["prices"]() or {}).get("exalted_per_divine"))
        if self.settings.get("sound_pack"):
            self._use_pack(self.settings["sound_pack"], redraw=False)
        self.status.config(text=self.t("Набор «{name}»: пороги и громкость выставлены, дальше можно подстроить").format(name=self.t(PRESETS[key][0])))
        self._changed(redraw_steps=False)
        self.render(keep_place=True)  # a preset also changes the cheap goods step and the pack shown above the lines

    def _use_pack(self, pack: str, redraw: bool = True) -> None:
        folder = filter_folder()
        if pack in ("chimes", "soft", "coins") and not folder:
            return self.status.config(text=self.t("Папки фильтров нет: запустите игру хотя бы раз"))
        try:
            apply_sound_pack(self.settings, pack, folder, (self.helpers["prices"]() or {}).get("exalted_per_divine"))
        except OSError as error:
            return self.status.config(text=self.t("Не удалось взять звук: {error}").format(error=error))
        if redraw:
            self._changed(redraw_steps=False)
            self.render(keep_place=True)

    def _play_pack(self) -> None:
        pack, folder = self.settings.get("sound_pack"), filter_folder()
        if pack in ("chimes", "soft", "coins") and folder:
            try:
                play_sound(folder / SOUND_FOLDER / pack_files(folder, pack)[0], 300)
            except (AttributeError, OSError):
                pass
        elif pack == "game":
            self.status.config(text=self.t("Звуки игры слышно только в игре"))

    def _item_rules_step(self, step) -> None:
        """A search over the priced goods in both languages, and the goods given a rule of their own."""
        colors, t, helpers = self.colors, self.t, self.helpers
        show = helpers["show_item"]
        names = sorted(filtered_names((helpers["prices"]() or {}).get("prices_in_divine") or {}), key=lambda name: show(name).casefold())
        search_row = tk.Frame(step, bg=colors["panel"])
        search_row.pack(fill="x")
        tk.Label(search_row, text=t("Поиск"), bg=colors["panel"], fg=colors["muted"], font=(BODY, 9)).pack(side="left", padx=(0, 6))
        query = tk.StringVar()
        entry = helpers["entry"](search_row, query, 30)
        entry.pack(side="left", ipady=2)
        found = tk.Frame(step.master, bg=colors["panel"])
        found.pack(fill="x", pady=(4, 0))
        rules = tk.Frame(step.master, bg=colors["panel"])
        rules.pack(fill="x", pady=(4, 0))

        def add(name):
            self.settings["items"][name] = "loud"
            query.set("")
            paint_found()
            paint_rules()
            self._changed(redraw_steps=False)

        def paint_found(*_):
            for child in found.winfo_children():
                child.destroy()
            wanted = query.get().strip().casefold()
            if len(wanted) < 2:
                return
            matches = [name for name in names if name not in self.settings["items"] and (wanted in name.casefold() or wanted in show(name).casefold())][:6]
            for name in matches:
                label = tk.Label(found, text="＋ " + show(name) + (f"  ({name})" if show(name) != name else ""), bg=colors["raised"], fg=colors["text"], font=(BODY, 9), cursor="hand2", padx=6, pady=2)
                label.pack(anchor="w", pady=1)
                label.bind("<Button-1>", lambda _, n=name: add(n))
            if not matches:
                tk.Label(found, text=t("Ничего не найдено"), bg=colors["panel"], fg=colors["muted"], font=(BODY, 9)).pack(anchor="w")

        def paint_rules():
            for child in rules.winfo_children():
                child.destroy()
            keys = list(ITEM_RULES)
            for name in sorted(self.settings["items"], key=lambda name: show(name).casefold()):
                row = tk.Frame(rules, bg=colors["panel"])
                row.pack(fill="x", pady=1)
                tk.Label(row, text=show(name), bg=colors["panel"], fg=colors["text"], font=(BODY, 9, "bold"), width=28, anchor="w").pack(side="left")

                def chose(box, name=name):
                    self.settings["items"][name] = keys[box.current()]
                    self._changed(redraw_steps=False)

                self._combo(row, [t(title) for title in ITEM_RULES.values()], t(ITEM_RULES[self.settings["items"][name]]), 20, chose).pack(side="left")

                def drop(name=name):
                    self.settings["items"].pop(name, None)
                    paint_rules()
                    self._changed(redraw_steps=False)

                helpers["button"](row, "✕", drop).pack(side="left", padx=(4, 0))

        entry.bind("<KeyRelease>", paint_found)
        paint_rules()

    def _fill_lines(self, box) -> None:
        for position, tier in enumerate(self.settings["tiers"]):
            self._tier_row(box, position, tier)
        if len(self.settings["tiers"]) < MOST_TIERS:
            self.helpers["button"](box, self.t("＋ Добавить строку"), self._add_tier).pack(anchor="w", pady=(6, 0))

    def _render_lines(self) -> None:
        """Only the lines of step 2 are built anew, out of sight, and swapped in at the same scroll: a click there costs a few widgets, not the page."""
        old = getattr(self, "lines_box", None)
        if old is None or not old.winfo_exists():
            return self.render(keep_place=True)
        place = self.steps_canvas.yview()[0] * max(self.steps.winfo_height(), 1)
        fresh = tk.Frame(old.master, bg=self.colors["panel"])
        self._fill_lines(fresh)
        old.pack_forget()
        fresh.pack(fill="x")
        old.destroy()
        self.lines_box = fresh
        self._draw_preview()
        self.steps.update_idletasks()
        self.steps_canvas.configure(scrollregion=(0, 0, self.steps_canvas.winfo_width(), self.steps.winfo_reqheight()))
        self.steps_canvas.yview_moveto(place / max(self.steps.winfo_reqheight(), 1))

    def _add_tier(self) -> None:
        last = self.settings["tiers"][-1]
        self.settings["tiers"].append(_clean_tier({**last, "name": self.t("Строка {number}").format(number=len(self.settings["tiers"]) + 1),
                                                   "least": round(max(last["least"] / 2, 0.01), 2)}, last))
        self._changed()

    def _remove_tier(self, position: int) -> None:
        if len(self.settings["tiers"]) > 1:
            del self.settings["tiers"][position]
            self.open_details = {number - (number > position) for number in self.open_details if number != position}
            self._changed()

    def _tier_row(self, parent, position: int, tier: dict) -> None:
        colors, t, helpers = self.colors, self.t, self.helpers
        frame = tk.Frame(parent, bg=colors["panel"])
        frame.pack(fill="x", pady=2)
        row = tk.Frame(frame, bg=colors["panel"])
        row.pack(fill="x")
        name = tk.StringVar(value=t(tier["name"]))
        name_entry = helpers["entry"](row, name, 12)
        name_entry.pack(side="left", ipady=2)

        def renamed(_=None):
            if name.get().strip():
                tier["name"] = name.get().strip()[:30]
                self._changed(redraw_steps=False, typing=True)

        name_entry.bind("<KeyRelease>", renamed)
        tk.Label(row, text=t("от"), bg=colors["panel"], fg=colors["muted"], font=(BODY, 9)).pack(side="left", padx=(6, 0))
        amount = tk.StringVar(value=f"{tier['least']:g}")
        entry = helpers["entry"](row, amount, 5)
        entry.pack(side="left", padx=(4, 2), ipady=2)

        def typed(_=None):
            try:
                value = float(amount.get().replace(",", "."))
            except ValueError:
                return
            if value > 0 and value != tier["least"]:
                tier["least"] = value
                self._changed(redraw_steps=False, typing=True)

        entry.bind("<KeyRelease>", typed)

        def chose_unit(box):
            tier["unit"] = box.get()
            self._changed(redraw_steps=False)

        self._combo(row, list(UNITS), tier["unit"], 4, chose_unit).pack(side="left", padx=(0, 6))
        swatches = tk.Frame(row, bg=colors["panel"])
        swatches.pack(side="left", padx=(0, 6))

        def paint_swatches():
            for child in swatches.winfo_children():
                child.destroy()
            for color in SHOWN_COLORS:
                back, text_rgb, border, _ = COLORS[color]
                chosen = color == tier["color"]
                swatch = tk.Label(swatches, bg=_hex(back), width=1, text="✓" if chosen else " ", fg=_hex(text_rgb), font=(BODY, 8, "bold"), cursor="hand2",
                                  highlightthickness=2, highlightbackground=_hex(border) if chosen else colors["panel"])
                swatch.pack(side="left", padx=1)
                swatch.bind("<Button-1>", lambda _, c=color: chose_color(c))

        def chose_color(color):
            loud = loudness_of(tier)
            tier["color"] = color
            if loud != "own":  # a simple line keeps its beam and icon in its colour
                tier.update(loudness_marks(loud, tier))
            paint_swatches()
            self._changed(redraw_steps=False)

        paint_swatches()
        loud_keys = list(LOUDNESS_TITLES)

        def chose_loudness(box):
            key = loud_keys[box.current()]
            if key == "own":
                self.open_details.add(position)
            else:
                tier.update(loudness_marks(key, tier))
            self._changed()

        self._combo(row, [t(title) for title in LOUDNESS_TITLES.values()], t(LOUDNESS_TITLES[loudness_of(tier)]), 9, chose_loudness).pack(side="left")
        helpers["button"](row, "⚙", lambda: (self.open_details.symmetric_difference_update({position}), self._render_lines())).pack(side="left", padx=(4, 0))
        if len(self.settings["tiers"]) > 1:
            helpers["button"](row, "✕", lambda: self._remove_tier(position)).pack(side="left", padx=(2, 0))
        if position in self.open_details:
            self._details(frame, tier)

    def _details(self, parent, tier: dict) -> None:
        """The fine settings of one line: font, beam, minimap icon and sound, each its own choice."""
        colors, t, helpers = self.colors, self.t, self.helpers
        box = tk.Frame(parent, bg=colors["raised"], padx=10, pady=6)
        box.pack(fill="x", pady=(3, 4), padx=(14, 0))

        def line():
            frame = tk.Frame(box, bg=colors["raised"])
            frame.pack(fill="x", pady=2)
            return frame

        def caption(frame, text):
            tk.Label(frame, text=text, bg=colors["raised"], fg=colors["soft"], font=(BODY, 9), width=10, anchor="w").pack(side="left")

        def scale(frame, low, high, value, done, step=1):
            """− value +: a stepper reads more plainly than Tk's slider."""
            shown = tk.Label(frame, text=str(value), bg=colors["panel"], fg=colors["text"], font=(BODY, 10, "bold"), width=4)

            def move(by):
                new = min(max(int(shown.cget("text")) + by, low), high)
                shown.config(text=str(new))
                done(new)

            helpers["button"](frame, "−", lambda: move(-step)).pack(side="left")
            shown.pack(side="left", padx=2, ipady=3)
            helpers["button"](frame, "+", lambda: move(step)).pack(side="left")

        color_names, color_keys = [t(title) for title in GAME_COLORS.values()], list(GAME_COLORS)

        row = line()
        caption(row, t("Шрифт"))
        scale(row, FONT_RANGE[0], FONT_RANGE[1], tier["font"], lambda value: (tier.__setitem__("font", value), self._changed(redraw_steps=False)), step=1)
        tk.Label(row, text=f"{FONT_RANGE[0]}–{FONT_RANGE[1]}", bg=colors["raised"], fg=colors["muted"], font=(BODY, 8)).pack(side="left", padx=(6, 0))

        row = line()
        caption(row, t("Луч"))
        beam_on = tk.BooleanVar(value=tier["beam"] is not None)
        helpers["switch"](row, "", beam_on, lambda: (tier.__setitem__("beam", {"color": COLORS[tier["color"]][3], "temp": False} if beam_on.get() else None), self._changed()), size=9).pack(side="left")
        if tier["beam"]:
            self._combo(row, color_names, t(GAME_COLORS[tier["beam"]["color"]]), 11,
                        lambda b: (tier["beam"].__setitem__("color", color_keys[b.current()]), self._changed(redraw_steps=False))).pack(side="left", padx=(4, 6))
            temp = tk.BooleanVar(value=tier["beam"]["temp"])
            helpers["switch"](row, t("только при выпадении"), temp, lambda: (tier["beam"].__setitem__("temp", temp.get()), self._changed(redraw_steps=False)), size=9).pack(side="left")

        row = line()
        caption(row, t("Значок"))
        icon_on = tk.BooleanVar(value=tier["icon"] is not None)
        helpers["switch"](row, "", icon_on, lambda: (tier.__setitem__("icon", {"size": 1, "color": COLORS[tier["color"]][3], "shape": "Circle"} if icon_on.get() else None), self._changed()), size=9).pack(side="left")
        if tier["icon"]:
            sizes, shapes = list(ICON_SIZES), list(ICON_SHAPES)
            self._combo(row, [t(title) for title in ICON_SIZES.values()], t(ICON_SIZES[tier["icon"]["size"]]), 9,
                        lambda b: (tier["icon"].__setitem__("size", sizes[b.current()]), self._changed(redraw_steps=False))).pack(side="left", padx=(4, 4))
            self._combo(row, color_names, t(GAME_COLORS[tier["icon"]["color"]]), 11,
                        lambda b: (tier["icon"].__setitem__("color", color_keys[b.current()]), self._changed(redraw_steps=False))).pack(side="left", padx=(0, 4))
            self._combo(row, [t(title) for title in ICON_SHAPES.values()], t(ICON_SHAPES[tier["icon"]["shape"]]), 13,
                        lambda b: (tier["icon"].__setitem__("shape", shapes[b.current()]), self._changed(redraw_steps=False))).pack(side="left")

        row = line()
        caption(row, t("Звук"))
        sound = tier["sound"]
        kinds, kind_titles = ["none", "builtin", "custom"], [t("Без звука"), t("Звук игры"), t("Свой файл")]

        def chose_kind(b):
            kind = kinds[b.current()]
            if kind == "custom":
                return self._pick_sound(tier)
            tier["sound"] = None if kind == "none" else {"kind": "builtin", "id": 1, "volume": (sound or {}).get("volume", 250)}
            self.settings["sound_pack"] = None  # a sound set by hand: the page shows «own» rather than a pack
            self._changed()

        self._combo(row, kind_titles, kind_titles[kinds.index(sound["kind"]) if sound else 0], 11, chose_kind).pack(side="left")
        if sound and sound["kind"] == "builtin":
            self._combo(row, [t("№ {number}").format(number=number) for number in SOUND_IDS], t("№ {number}").format(number=sound["id"]), 5,
                        lambda b: (sound.__setitem__("id", list(SOUND_IDS)[b.current()]), self._changed(redraw_steps=False))).pack(side="left", padx=(4, 0))
            tk.Label(row, text=t("слышно только в игре"), bg=colors["raised"], fg=colors["muted"], font=(BODY, 8)).pack(side="left", padx=(6, 0))
        if sound and sound["kind"] == "custom":
            tk.Label(row, text=sound["file"] if len(sound["file"]) <= 22 else sound["file"][:21] + "…", bg=colors["raised"], fg=colors["text"], font=(BODY, 9)).pack(side="left", padx=(6, 4))
            helpers["button"](row, t("Выбрать…"), lambda: self._pick_sound(tier)).pack(side="left", padx=(0, 4))
            helpers["button"](row, "▶", lambda: self._play(sound)).pack(side="left")
        if sound:
            row = line()
            caption(row, t("Громкость"))
            scale(row, 0, 300, sound["volume"], lambda value: (sound.__setitem__("volume", value), self._changed(redraw_steps=False)), step=25)
            tk.Label(row, text="0–300", bg=colors["raised"], fg=colors["muted"], font=(BODY, 8)).pack(side="left", padx=(6, 0))

    def _pick_sound(self, tier: dict) -> None:
        folder = filter_folder()
        if not folder:
            return self.status.config(text=self.t("Папки фильтров нет: запустите игру хотя бы раз"))
        chosen = filedialog.askopenfilename(parent=self.page, title=self.t("Свой звук"), filetypes=[(self.t("Звук"), "*.mp3 *.wav")])
        if not chosen:
            return self.render(keep_place=True)
        try:
            name = add_sound(folder, Path(chosen))
        except (OSError, ValueError) as error:
            return self.status.config(text=self.t("Не удалось взять звук: {error}").format(error=error))
        tier["sound"] = {"kind": "custom", "file": name, "volume": (tier["sound"] or {}).get("volume", 250)}
        self.settings["sound_pack"] = None
        self.status.config(text=self.t("Звук {name} лежит в папке фильтров, в «Sakuya sounds»").format(name=name))
        self._changed()

    def _play(self, sound: dict) -> None:
        folder = filter_folder()
        path = folder / SOUND_FOLDER / sound["file"] if folder else None
        if path and path.is_file():
            try:
                play_sound(path, sound["volume"])
            except (AttributeError, OSError):
                pass

    def _draw_preview(self) -> None:
        canvas, t = self.preview, self.t
        canvas.delete("all")
        prices = self.helpers["prices"]() or {}
        rate = prices.get("exalted_per_divine")
        tiers, hidden = tiered(prices.get("prices_in_divine") or {}, self.settings, rate, prices.get("kinds"))
        show = self.helpers["show_item"]
        y, lines = 18, []
        for position in dearest_first(self.settings, rate):
            names, tier = tiers[position], self.settings["tiers"][position]
            back, text_rgb, border, _ = COLORS[tier["color"]]
            sample = show(names[0]) if names else t("Нет таких предметов")
            sample = sample if len(sample) <= 24 else sample[:23] + "…"  # the label must stay inside the preview
            label = canvas.create_text(24, y + 16, text=sample, font=(BODY, max(9, tier["font"] // 3), "bold"), anchor="w", fill=_hex(text_rgb))
            x1, y1, x2, y2 = canvas.bbox(label)
            canvas.create_rectangle(x1 - 10, y1 - 5, x2 + 10, y2 + 5, fill=_hex(back), outline=_hex(border), width=2)
            if tier["beam"]:
                canvas.create_line((x1 + x2) / 2, y1 - 6, (x1 + x2) / 2, max(y1 - 16, 2), fill=_hex(BEAM_SHADES[tier["beam"]["color"]]), width=4)
            canvas.tag_raise(label)
            marks = []
            if tier["beam"]:
                marks.append(t("луч"))
            if tier["icon"]:
                marks.append(t("значок: {shape}").format(shape=t(ICON_SHAPES[tier["icon"]["shape"]]).lower()))
            if tier["sound"]:
                marks.append(t("звук") if tier["sound"]["kind"] == "builtin" else t("свой звук"))
            canvas.create_text(24, y2 + 16, text=t(tier["name"]) + "  ·  " + (", ".join(marks) if marks else t("только цвет")), font=(BODY, 8), anchor="w", fill="#a99f8c")
            lines.append(t("{name}: {count} предметов").format(name=t(tier["name"]), count=len(names)) + (f" ({', '.join(show(name) for name in names[1:4])}…)" if len(names) > 1 else ""))
            y = y2 + 40
        loud, hidden_by_hand = item_rules(self.settings)
        if loud:
            lines.insert(0, t("Всегда громко: {names}").format(names=", ".join(show(name) for name in loud[:4]) + (" …" if len(loud) > 4 else "")))
        if hidden or hidden_by_hand:
            canvas.create_text(24, y + 4, text=t("Спрятано: {count} дешёвых").format(count=len(hidden) + len(hidden_by_hand)), font=(BODY, 9), anchor="w", fill="#7c7466")
        canvas.config(height=max(200, y + 20))
        self.counts.config(text="\n".join(lines))
