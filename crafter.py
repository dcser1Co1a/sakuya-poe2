"""Crafting advisor overlay for Path of Exile 2. Run from this folder: .venv/Scripts/python.exe crafter.py

Mods and weights come from poe2db, base items from RePoE, prices from poe.ninja.
"""
import sys

if __name__ == "__main__" and "--watch-game" in sys.argv[1:]:  # the watcher that opens Sakuya with the game: before the heavy libraries, so it stays small
    import game_watch

    raise SystemExit(game_watch.run(sys.argv[1:]))

import base64
import bisect
import ctypes
import ctypes.wintypes
import faulthandler
import gc
import hashlib
import html
import http.client
import io
import json
import math
import os
import queue
import random
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
import game_watch
import traceback
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from tkinter import ttk
from typing import NamedTuple

# Measured: two threads solve plans faster than all cores and leave the processor to the game.
for _variable in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_variable, "2")

import webbrowser
import zlib

import numpy as np
from PIL import Image, ImageColor

from sakura import (
    trace_while,
    ACTIVE_THEME,
    BODY,
    CardWave,
    DriftingBlossom,
    LoadingScreen,
    wave_delay,
    ON_SEAL,
    SEAL_RED,
    SEAL_RED_LIGHT,
    prepare_art,
    RARITY_COLORS,
    THEMES,
    ACCENT,
    ACCENT_LIGHT,
    BG,
    BORDER,
    DOWN_COLOR,
    BANNER_HEIGHT,
    CHOSEN,
    CHOSEN_LIGHT,
    INK,
    MOD_ON_GROUND,
    MUTED,
    ON_CHOSEN,
    PANEL,
    RAISED,
    SEAL_SIGN,
    SEAL_SIZE,
    TITLE_FONT,
    SIDEBAR,
    SOFT,
    SWITCH_TRACK_OFF,
    TEXT,
    BRAND,
    THUMB,
    TILE,
    UP_COLOR,
    add_waves,
    add_ground,
    paper_image, paper_variant,
    seal_image,
    branch_image,
)
from build_items import BuildPage
import level_steps
from drop_sources import DropPage, drop_line, fetch_drops, wiki_page
from market_demand import APP_USER_AGENT, BUILD_GUIDES, NINJA_API, SCOUT_API, UNIQUE_KINDS, DemandPage, fetch_overview, kinds_due, learn_unique_kinds, read_categories, read_unique, update_demand
from price_check import UNIQUE_RARITIES, UNIT_LABELS, PriceWindow, SlimScrollbar, TradeSearchPanel, baked_card, best_unit, build_price_index, draw_change, find_price, keep_fonts_ready, prepare_sparks, read_copied_item, spark_image, switch_image, trade_search_url
from tools import EXCHANGE_COINS, add_craft_goal, add_history, exchange_rates, watches_reached, Stopwatch, ToolsPage, add_bookmark, danger_keys, dangerous_lines, exchange_names, exchange_turnover, fetch_exchange, is_waystone, read_waystone_mods
from shapes import is_craft_goal, clean_demand, clean_market_sections, clean_patch_watch, clean_prices, clean_settings, clean_tools, clean_trade_stats, clean_uniques, clean_drops, clean_build_history, clean_updates, clean_waystones, text_map
from tray import TrayIcon
from trade_search import RANGE, build_query, client_language, compared_lines, item_quality, mods_on_by_default, normalize_stat, read_item_mods, read_item_totals, read_stat_list, recalled_mods, remember_search, search_memory_key, trade_category, trade_site_url, wanted_mod

# ---------------------------------------------------------------- data update
# Inside the exe __file__ points to a temporary folder, so data is kept next to the exe.
APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
DATA_PATH = APP_DIR / "data.json"
PRICES_PATH = APP_DIR / "prices.json"
ICONS_PATH = APP_DIR / "icons.json"
SETTINGS_PATH = APP_DIR / "settings.json"
TRADE_STATS_PATH = APP_DIR / "trade_stats.json"
STAT_LIST_URL = "https://raw.githubusercontent.com/Kvan7/Exiled-Exchange-2/master/renderer/public/data/{language}/stats.ndjson"
STAT_LIST_MAX_AGE = timedelta(days=1)  # its authors follow patches, so the list is looked at more often than the game changes
BROWSER_LONGEST_WAIT_SECONDS = 6
STAT_LIST_FEWEST_MODS = 1000  # fewer than this is not the whole list
LANGUAGES = ("en", "ru")
UNIQUES_PATH = APP_DIR / "uniques.json"
BUILDS_PATH = APP_DIR / "builds.json"  # the build codes the player opened, newest first
DROPS_PATH = APP_DIR / "drops.json"  # where uniques and jewels drop, from poe2wiki
JEWELS_PATH = APP_DIR / "jewels.json"  # the mods jewels can have, with their ranges, from poe2db: for the build page's jewel search, apart from the planner
DROPS_FORMAT = 2  # bump when drops.json gains something, so a saved file is read again at once; 2 brought the estimated chances
DEMAND_PATH = APP_DIR / "demand.json"
TOOLS_PATH = APP_DIR / "tools.json"
WAYSTONES_PATH = APP_DIR / "waystones.json"
UPDATES_PATH = APP_DIR / "updates.json"
MARKET_SECTIONS_PATH = APP_DIR / "market_sections.json"
PATCH_WATCH_PATH = APP_DIR / "patch_watch.json"
LEAGUE_FOLDER = APP_DIR / "leagues"
_repoe_pass: dict[str, tuple[bytes, str | None]] = {}
LOG_PATH = APP_DIR / "errors.log"
LOG_MAX_BYTES = 200_000
SERVICE_RESTART_SECONDS = 60
FILE_REPLACE_ATTEMPTS = 5
POE2DB_URL = "https://poe2db.tw/us/"
POE2DB_RU_URL = "https://poe2db.tw/ru/"
SCHEMA_VERSION = 10  # bump when the data.json layout changes to force a rebuild; 10 brought the mods' crafting tags
CRAFTING_TAG = re.compile(r'data-tag="([a-z_]+)"')
REPOE_URL = "https://repoe-fork.github.io/poe2/"
NINJA_URL = "https://poe.ninja/poe2/api/"
USER_AGENT = "Mozilla/5.0 (compatible; sakuya)"
REQUEST_DELAY_SECONDS = 1.5
PRICE_UPDATE_INTERVAL = timedelta(hours=1)  # poe.ninja refreshes this data about hourly, so asking more often gains nothing
NINJA_REQUEST_GAP_SECONDS = 3  # the pause between sections within one update
ACTIVE_SECONDS = 2 * 3600  # a program nobody has touched for this long asks poe.ninja for nothing
RECENT_USE_SECONDS = 600
NINJA_RETRY_PAUSE = timedelta(minutes=10)
NINJA_BLOCK_PAUSE = timedelta(minutes=30)
LEAGUE_CHECK_INTERVAL = timedelta(hours=6)
# Every exchange section poe.ninja lists for PoE2: (type, Russian title, English title).
PRICE_SECTIONS = (
    ("Currency", "Валюта", "Currency"), ("Ritual", "Ритуал", "Ritual"), ("Essences", "Эссенции", "Essences"), ("Abyss", "Бездна", "Abyss"),
    ("Breach", "Разлом", "Breach"), ("Delirium", "Делириум", "Delirium"), ("Expedition", "Экспедиция", "Expedition"), ("Fragments", "Фрагменты", "Fragments"),
    ("Runes", "Руны", "Runes"), ("SoulCores", "Ядра душ", "Soul Cores"), ("Idols", "Идолы", "Idols"), ("Verisium", "Верисий", "Verisium"),
    ("UncutGems", "Камни", "Uncut Gems"), ("LineageSupportGems", "Родословная", "Lineage"), ("PrecursorTablets", "Скрижали", "Tablets"),
)
# Sections poe.ninja prices from stash listings rather than the exchange: another address and another shape, read by stash_to_exchange.
STASH_SECTIONS = frozenset({"PrecursorTablets"})
ITEM_VARIANT = re.compile(r" \((Normal|Magic|Rare)\)$")  # one tablet comes as plain, magic and rare, each with its own price
VARIANT_WORDS = {"Normal": "обычная", "Magic": "магическая", "Rare": "редкая"}
PRICE_KINDS = [section[0] for section in PRICE_SECTIONS]  # a section found on poe.ninja later joins these, and its items go under Other
LEARNED_SECTIONS: set[str] = set()
CORE_SECTIONS = frozenset({"Currency", "Ritual", "Essences"})  # the crafting plans need these: orbs, omens, essences
# poe.ninja files many special items under Currency. The Currency tab keeps the everyday orbs, the rest goes to Other.
OTHER_SECTION = "Other"
PRICE_TABS = (*PRICE_SECTIONS, (OTHER_SECTION, "Прочее", "Other"))
TAB_KINDS = frozenset(section[0] for section in PRICE_TABS)
SCOUT_KIND = "Scout"  # priced by poe2scout, for what poe.ninja has no section for yet
EXCHANGE_KIND = "Exchange"  # priced from the official exchange's last hour, for what no site lists in a thin league
SCOUT_CURRENCY_COVERED = frozenset({"currency", "fragments", "runes", "essences", "ultimatum", "expedition", "ritual", "vaultkeys", "breach", "abyss", "uncutgems", "lineagesupportgems", "delirium", "incursion", "idol", "verisium", "vaal"})  # all of these are also on poe.ninja
SCOUT_CURRENCY_PAGE = 250
CORE_CURRENCY = frozenset({
    "Mirror of Kalandra", "Divine Orb", "Fracturing Orb", "Orb of Annulment", "Vaal Orb", "Orb of Chance", "Orb of Alchemy", "Artificer's Orb",
    "Chaos Orb", "Greater Chaos Orb", "Perfect Chaos Orb", "Exalted Orb", "Greater Exalted Orb", "Perfect Exalted Orb",
    "Regal Orb", "Greater Regal Orb", "Perfect Regal Orb", "Orb of Augmentation", "Greater Orb of Augmentation", "Perfect Orb of Augmentation",
    "Orb of Transmutation", "Greater Orb of Transmutation", "Perfect Orb of Transmutation",
    "Lesser Jeweller's Orb", "Greater Jeweller's Orb", "Perfect Jeweller's Orb",
    "Armourer's Scrap", "Blacksmith's Whetstone", "Arcanist's Etcher", "Glassblower's Bauble", "Gemcutter's Prism",
})
# The picture on each section's tab. Other sections use their most traded item.
TAB_ICON_ITEMS = {"Currency": "Exalted Orb", "Ritual": "Omen of Whittling", "Essences": "Greater Essence of Enhancement", OTHER_SECTION: "Hinekora's Lock"}
ICON_REQUEST_DELAY_SECONDS = 0.3
ICON_SAVE_BATCH = 25
ICON_SIZE = 48
ART_SIZE = 84
LARGE_ART = "large:"
UNIQUE_CARD = re.compile(r'href="/ru/([^"]+)"><span class="uniqueName">([^<]+)<')
SIDEBAR_WIDTH = 176
DATA_MAX_AGE = timedelta(days=7)
DATA_CHECK_INTERVAL = timedelta(hours=6)  # a new patch reaches the program the same day, for three small requests
DATA_RETRY_PAUSE = timedelta(minutes=10)  # doubled after each failure in a row, up to DATA_CHECK_INTERVAL
PROGRAM_CHECK_SECONDS = 600  # a new version shows within ten minutes: 6 requests an hour, GitHub allows 60 without a sign-in
DATA_NAP_SECONDS = 600  # short naps, so a computer back from sleep does not wait out the rest of a long one
SMALLEST_SOUND_SHARE = 0.8  # new data with less than this share of the old is a changed site, not a smaller game
NAMES_PER_PASS = 60  # an item's own page is one request each, so a new league's items come in over a few passes
NAMES_ENOUGH_SHARE = 0.9  # fewer priced items with a Russian name than this means poe2db has changed
OWN_PAGE_TITLE = re.compile(r"<title>\s*([^<]+?)\s+-\s+PoE2DB", re.IGNORECASE)
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
LANGUAGE_LINK = "RU Русский"  # every Russian page links to itself in its language menu
NINJA_SITEMAP = "https://poe.ninja/sitemap-en.xml"
MARKET_CHECK_INTERVAL = timedelta(days=1)
STEAM_APP_ID = "2694490"
STEAM_BUILD_URL = f"https://api.steamcmd.net/v1/info/{STEAM_APP_ID}"
LOCAL_BUILD_SECONDS = 1
STEAM_FIND_SECONDS = 300
ONLINE_BUILD_SECONDS = 60
ONLINE_BUILD_FAILED_SECONDS = 300
RUSH_NAP_SECONDS = 15
RUSH_FIRST_SPELL = timedelta(hours=1)
RUSH_FIRST_PAUSE = timedelta(minutes=2)
RUSH_LATER_PAUSE = timedelta(minutes=10)
RUSH_LONGEST = timedelta(hours=12)
KNOWN_MARKET_SECTIONS = frozenset({
    "abyssal-bones", "breach-catalyst", "currency", "essences", "expedition", "fragments", "idols", "lineage-support-gems", "liquid-emotions", "omens", "runes", "soul-cores", "uncut-gems", "verisium",
    "unique-accessories", "unique-armours", "unique-charms", "unique-flasks", "unique-jewels", "unique-relics", "unique-tablets", "unique-weapons", "precursor-tablets",
})
# Jewels, flasks and charms have other affix limits and are not supported yet.
UNSUPPORTED_PAGES = re.compile(r"Ruby|Emerald|Sapphire|Diamond|Flasks|Charms")
JEWEL_PAGES = ("Ruby", "Emerald", "Sapphire", "Diamond", "Time-Lost_Ruby", "Time-Lost_Emerald", "Time-Lost_Sapphire", "Time-Lost_Diamond")  # read on their own, for searches only
SIDES = {"1": "prefix", "2": "suffix"}


def download(request: urllib.request.Request, attempts: int) -> tuple[bytes, str | None]:
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read(), response.headers.get("ETag")
        except urllib.error.HTTPError as error:
            if error.code < 500 or attempt == attempts:
                raise  # a refusal stays a refusal, and asking again only risks a block
            time.sleep(2 * attempt)
        except http.client.HTTPException as error:  # a connection cut mid-reply counts as a lost connection, whatever the library calls it
            if attempt == attempts:
                raise ConnectionError(f"the reply broke off: {error!r}") from error
            time.sleep(2 * attempt)
        except OSError:
            if attempt == attempts:
                raise
            time.sleep(2 * attempt)
    raise AssertionError("unreachable")


def fetch_bytes(url: str, attempts: int = 5, user_agent: str = USER_AGENT) -> bytes:
    return download(urllib.request.Request(url, headers={"User-Agent": user_agent}), attempts)[0]


def fetch(url: str, attempts: int = 5, user_agent: str = USER_AGENT) -> str:
    return fetch_bytes(url, attempts, user_agent).decode("utf-8", errors="replace")


def read_repoe(name: str, known_tag: str | None = None) -> tuple[bytes | None, str | None]:
    """A file from RePoE and its tag, or None for the file when it is unchanged since known_tag, which costs no download. Within one pass each file comes down once."""
    if name not in _repoe_pass:
        headers = {"User-Agent": USER_AGENT, **({"If-None-Match": known_tag} if known_tag else {})}
        try:
            _repoe_pass[name] = download(urllib.request.Request(REPOE_URL + name, headers=headers), 5)
        except urllib.error.HTTPError as error:
            if error.code == 304:
                return None, known_tag
            raise
    body, tag = _repoe_pass[name]
    return (None if tag and tag == known_tag else body), tag


def log_error(where: str, details: str | None = None) -> None:
    """Keeps what went wrong next to the program, since a program without a console has nowhere else to say it. Stays on this computer."""
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > LOG_MAX_BYTES:
            LOG_PATH.write_text(LOG_PATH.read_text(encoding="utf-8", errors="replace")[-LOG_MAX_BYTES // 2:], encoding="utf-8")
        with LOG_PATH.open("a", encoding="utf-8") as log:
            log.write(f"{datetime.now().isoformat(timespec='seconds')} {where}\n{details or traceback.format_exc()}\n")
    except OSError:
        pass  # failing to write down an error must not become a second error


def keep_running(target, *args) -> None:
    """Runs a background service and starts it again if it fails, so one bad reply cannot end price updates until the next start."""
    while True:
        try:
            return target(*args)
        except Exception:
            log_error(getattr(target, "__name__", "service"))
            time.sleep(SERVICE_RESTART_SECONDS)


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    for attempt in range(FILE_REPLACE_ATTEMPTS):
        try:
            return temporary.replace(path)
        except PermissionError:  # an antivirus or a backup can hold a file for a moment
            if attempt == FILE_REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(0.1)


def read_json(path: Path) -> dict | None:
    """A damaged file is set aside and treated as missing, so the program still starts and rebuilds what it can."""
    if not path.exists():
        return None
    try:
        for attempt in range(FILE_REPLACE_ATTEMPTS):
            try:
                text = path.read_text(encoding="utf-8")
                break
            except OSError:  # an antivirus or a backup can hold a file for a moment, and that does not make it damaged
                if attempt == FILE_REPLACE_ATTEMPTS - 1:
                    log_error(f"reading {path.name}")
                    return None
                time.sleep(0.1)
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("not a JSON object")
        return value
    except ValueError as error:
        log_error(f"damaged file {path.name}", str(error))
        try:
            path.replace(path.with_name(path.name + ".broken"))
        except OSError:
            pass
        return None


def is_older_than(stored: dict | None, age: timedelta, key: str = "fetched_at") -> bool:
    return not stored or not stored.get(key) or datetime.now() - datetime.fromisoformat(stored[key]) > age


def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def extract_mods_view(page_html: str) -> dict:
    marker = "new ModsView("
    start = page_html.find(marker)
    if start < 0:
        raise ValueError("ModsView data not found, the poe2db page layout may have changed")
    return json.JSONDecoder().raw_decode(page_html, start + len(marker))[0]


def name_forms(name: str) -> list[str]:
    """Russian names can hold grammatical forms: <if:MS>{Светящийся}<elif:FS>{Светящаяся}."""
    return re.findall(r"\{([^}]*)\}", name) or [name]


def clean_text(text: str) -> str:
    text = re.sub(r"<if:[^>]*>\{([^}]*)\}(?:<elif:[^>]*>\{[^}]*\})*", r"\1", text)
    text = re.sub(r"<[^>]+>", "", re.sub(r"<br\s*/?>|\n", " / ", text))
    return re.sub(r"\s+", " ", html.unescape(text).replace("—", "-")).strip()


def make_template(text: str) -> str:
    return re.sub(r"\(?-?\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?\)?", "#", text)


def normalize_mod(raw: dict) -> dict | None:
    side = SIDES.get(str(raw.get("ModGenerationTypeID")))
    weight = int(raw.get("DropChance") or 0)
    if side is None or weight <= 0:
        return None
    text = clean_text(raw["str"])
    # The crafting tags poe2db shows as badges, such as cold or life: catalyst quality raises the chance of mods that carry its tag.
    tags = sorted(set(CRAFTING_TAG.findall(" ".join(str(badge) for badge in raw.get("mod_no") or ()))))
    return {"name": raw["Name"], "side": side, "level": int(raw["Level"]), "groups": raw["ModFamilyList"],
            "weight": weight, "text": text, "template": make_template(text), "tags": tags}


def normalize_page(view: dict, ru_view: dict) -> dict:
    normal, ru_normal = view["normal"], ru_view["normal"]
    aligned = len(normal) == len(ru_normal) and all(
        a["Level"] == b["Level"] and a["ModFamilyList"] == b["ModFamilyList"] for a, b in zip(normal, ru_normal))
    mods = []
    for index, raw in enumerate(normal):
        if mod := normalize_mod(raw):
            ru = ru_normal[index] if aligned else raw
            mods.append({**mod, "ru_name": ru["Name"], "ru_text": clean_text(ru["str"])})
    return {"item_class": view["opt"]["ItemClassesCode"], "tag": view["opt"].get("tags"), "mods": mods,
            "essences": [*normalize_essences(view.get("essence", []), ru_view.get("essence", [])), *normalize_perfect_essences(view.get("perfect_essence", []), ru_view.get("perfect_essence", []))],
            "desecrated": normalize_desecrated(view.get("desecrated", []), ru_view.get("desecrated", [])),
            "warped": {group: normalize_desecrated(view[group], ru_view.get(group, [])) for group in WARPING_RUNES if view.get(group)}}


def normalize_desecrated(raw_entries: list[dict], ru_entries: list[dict]) -> list[dict]:
    """Mods that only a Desecration can add. poe2db lists a weight of 1 for each, which is no real weight, so none is kept."""
    aligned = len(raw_entries) == len(ru_entries)
    found = []
    for index, raw in enumerate(raw_entries):
        side = SIDES.get(str(raw.get("ModGenerationTypeID")))
        if side:
            ru = ru_entries[index] if aligned else raw
            text = clean_text(raw["str"])
            found.append({"name": clean_text(raw["Name"]), "side": side, "level": int(raw["Level"]), "groups": raw["ModFamilyList"], "text": text, "template": make_template(text),
                          "ru_name": clean_text(ru["Name"]), "ru_text": clean_text(ru["str"])})
    return found


def normalize_essences(raw_entries: list[dict], ru_entries: list[dict]) -> list[dict]:
    """Essences that upgrade a magic item to rare. Those with a random result, like «the Infinite», are skipped."""
    aligned = len(raw_entries) == len(ru_entries)
    found: dict[str, list[dict]] = {}
    for index, raw in enumerate(raw_entries):
        side = SIDES.get(str(raw.get("ModGenerationTypeID")))
        if side:
            ru = ru_entries[index] if aligned else raw
            name = clean_text(raw["Name"])
            found.setdefault(name, []).append({"name": name, "ru_name": clean_text(ru["Name"]), "side": side, "level": int(raw["Level"]),
                                               "groups": raw["ModFamilyList"], "text": clean_text(raw["str"]), "ru_text": clean_text(ru["str"])})
    return [entries[0] for entries in found.values() if len({tuple(e["groups"]) for e in entries}) == 1]


def normalize_perfect_essences(raw_entries: list[dict], ru_entries: list[dict]) -> list[dict]:
    """What acts on a rare item: perfect and corrupted essences and alloys, all of which remove a random modifier and add a guaranteed one."""
    return [{**entry, "perfect": True} for entry in normalize_essences(raw_entries, ru_entries)]


def name_key(name: str) -> str:
    return name.replace("'", "").replace("_", " ").casefold()  # poe2db links drop apostrophes: Hexers_Robe


def read_names(page_html: str) -> dict[str, str]:
    """Maps name keys to the names shown on a Russian poe2db page, using the English link targets."""
    names: dict[str, str] = {}
    for link, content in re.findall(r'href="([^"]+)"[^>]*>(.*?)</a>', page_html):
        slug = urllib.parse.unquote(html.unescape(link)).removeprefix("/ru/")  # some pages link with the language in front
        if slug and "#" not in slug and "/" not in slug and (name := clean_text(content)) and name != LANGUAGE_LINK:  # a slash is another language or another site
            names.setdefault(name_key(slug), name)
    return names


RUSSIAN_NAME_PAGES = ("Stackable_Currency", "Omen", "Soul_Core", "Runes", "Idol", "Delirium", "Breach", "Expedition", "Map_Fragments", "Uncut_Skill_Gems", "Lineage_Supports")


def own_page_name(name: str) -> str | None:
    """An item's Russian name from the title of its own page, which needs no list of addresses, so items of a new league come in by themselves."""
    try:
        page = fetch(POE2DB_RU_URL + urllib.parse.quote(name.replace("'", "").replace(" ", "_")), attempts=1)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    title = OWN_PAGE_TITLE.search(page)
    shown = html.unescape(title.group(1)).strip() if title else ""
    return shown if CYRILLIC.search(shown) else None


OTHER_BASE_ART = ("/Jewels/", "/Flasks/Basetypes/", "/Charms/Basetypes/")  # bases the build page shows that crafting does not cover


def other_bases(item_art: dict[str, str]) -> list[str]:
    """Jewel, flask and charm bases, whose Russian names come from their own poe2db pages like those of priced items."""
    return sorted(name for name, path in item_art.items() if any(part in path for part in OTHER_BASE_ART) and "/Uniques/" not in path)


def names_to_look_up(priced, keys: dict[str, str], not_found: dict[str, str]) -> list[str]:
    """Priced items without a Russian name. One whose page had none is tried again after a week."""
    plain = {plain_item_name(name) for name in priced}  # the variants of a tablet share one page
    return sorted(name for name in plain if name_key(name) not in keys and is_older_than(not_found, DATA_MAX_AGE, name))


def update_names(patches: dict, status, on_changed) -> None:
    """Fills in the names the list pages did not give. What was found is kept even if a later request is refused."""
    stored = read_json(DATA_PATH)
    if not stored:
        return
    priced = read_prices().get("prices_in_divine", {})
    keys, own, not_found = stored.get("currency_keys", {}), stored.get("names_from_own_pages", {}), stored.get("names_not_found", {})
    wanted = names_to_look_up([*priced, *other_bases(clean_uniques(read_json(UNIQUES_PATH) or {}).get("items", {}))], keys, not_found)[:NAMES_PER_PASS]
    try:
        for name in wanted:
            shown = own_page_name(name)
            if shown:
                own[name_key(name)] = keys[name_key(name)] = shown
            else:
                not_found[name] = now_text()
            time.sleep(REQUEST_DELAY_SECONDS)
    finally:
        if wanted:
            write_json(DATA_PATH, {**stored, "currency_keys": keys, "names_from_own_pages": own, "names_not_found": not_found})
    if wanted:
        on_changed()
    named = sum(1 for name in priced if name_key(plain_item_name(name)) in keys)
    if priced and named < len(priced) * NAMES_ENOUGH_SHARE and not names_to_look_up(priced, keys, not_found):
        log_error("russian names", f"only {named} of {len(priced)} priced items have a Russian name")
        status(t("poe2db изменился: часть русских названий не найдена, подробности в errors.log"))


def new_market_sections(site_map: str, league: str, known: frozenset | set) -> list[str]:
    """Sections poe.ninja lists for this league that the program has not heard of. A map without the league says nothing."""
    slug = re.sub(r"\W", "", league).casefold()
    return sorted(set(re.findall(rf"/poe2/economy/{slug}/([a-z0-9-]+)", site_map)) - set(known))


def section_kinds(slug: str) -> list[str]:
    """The name a section may go by in poe.ninja's data, going by its address. It is usually soul-cores to SoulCores, and now and then breach-catalyst to Breach."""
    words = slug.split("-")
    return list(dict.fromkeys(("".join(word.capitalize() for word in words), words[0].capitalize())))


def find_section_kind(slug: str, league: str) -> str | None:
    for kind in section_kinds(slug):
        query = urllib.parse.urlencode({"league": league, "type": kind})
        try:
            answer = json.loads(fetch(f"{NINJA_API}economy/exchange/current/overview?{query}", attempts=1, user_agent=APP_USER_AGENT))
        except ValueError:
            continue
        if isinstance(answer, dict) and answer.get("lines"):
            return kind
        time.sleep(NINJA_REQUEST_GAP_SECONDS)
    return None


def learn_market(stored: dict) -> tuple[list[str], list[str]]:
    """Takes in what has been found out about the market. Returns the new sections and the new kinds of unique."""
    sections = [kind for kind in stored.get("sections", ()) if kind not in PRICE_KINDS]
    PRICE_KINDS.extend(sections)
    LEARNED_SECTIONS.update(stored.get("sections", ()))
    return sections, learn_unique_kinds(stored.get("unique_categories", ()))


def update_market_sections(patches: dict, status, on_changed) -> None:
    """A new league can bring new parts of the market. Once a day the sites' own lists are read and whatever is new is taken in.
    A section whose data cannot be found is tried again the next day, and is reported once."""
    stored = clean_market_sections(read_json(MARKET_SECTIONS_PATH) or {})
    league = read_prices().get("league")
    if not league or not is_older_than(stored, MARKET_CHECK_INTERVAL, "checked_at"):
        return
    fresh = new_market_sections(fetch(NINJA_SITEMAP, attempts=1, user_agent=APP_USER_AGENT), league, {*KNOWN_MARKET_SECTIONS, *stored["section_slugs"]})
    for slug in fresh:
        kind = find_section_kind(slug, league)
        if kind:
            stored["sections"].append(kind)
            stored["section_slugs"].append(slug)
    unfound = [slug for slug in fresh if slug not in stored["section_slugs"]]
    unreported = [slug for slug in unfound if slug not in stored["reported"]]
    if unreported:
        log_error("poe.ninja", f"sections whose data could not be found: {', '.join(unreported)}")
        status(t("На poe.ninja есть новые разделы, программа их пока не показывает: {names}").format(names=", ".join(unreported)))
    try:
        answer = json.loads(fetch(f"{SCOUT_API}Leagues/{urllib.parse.quote(league)}/Items/Categories", attempts=1, user_agent=APP_USER_AGENT))
        unique_categories, currency_categories = read_categories(answer if isinstance(answer, dict) else {})
    except (OSError, ValueError):  # this list is a bonus, and the sections above still count
        unique_categories, currency_categories = stored["unique_categories"], stored["currency_categories"]
    fresh_state = {**stored, "checked_at": now_text(), "reported": [*stored["reported"], *unreported], "unique_categories": unique_categories or stored["unique_categories"], "currency_categories": currency_categories or stored["currency_categories"]}
    write_json(MARKET_SECTIONS_PATH, fresh_state)
    sections, kinds = learn_market(fresh_state)
    if sections or kinds:
        status(t("Рынок пополнился: {names}").format(names=", ".join((*sections, *kinds))))


def scout_lines_to_prices(stored: dict, lines: list) -> dict:
    """Items only poe2scout has, in the program's own terms. poe.ninja's price stays where there is one."""
    rate = stored["exalted_per_divine"]
    known = stored.get("prices_in_divine", {})
    kinds = stored.get("kinds", {})
    prices, icons, new_kinds = {}, {}, {}
    for line in lines:
        name = line.get("Text") if isinstance(line, dict) else None
        price = line.get("CurrentPrice") if isinstance(line, dict) else None
        if isinstance(name, str) and name and is_positive_number(price) and (name not in known or kinds.get(name) == SCOUT_KIND):
            prices[name], new_kinds[name] = price / rate, SCOUT_KIND
            if isinstance(line.get("IconUrl"), str):
                icons[name] = line["IconUrl"]
    return {**stored, "prices_in_divine": {**known, **prices}, "kinds": {**kinds, **new_kinds}, "icons": {**stored.get("icons", {}), **icons}}


def exchange_lines_to_prices(stored: dict, markets: list, names: dict[str, str]) -> dict:
    """Goods nothing else prices, from GGG's public file of the last hour. The coin that most changed hands sets the price, as one hour's averages differ between coins.
    Last hour's prices go first, so that what stopped trading does not keep an old one."""
    rate, chaos = stored["exalted_per_divine"], stored.get("chaos_per_divine")
    worth = {EXCHANGE_COINS["Exalted Orb"]: 1.0, EXCHANGE_COINS["Divine Orb"]: rate, **({EXCHANGE_COINS["Chaos Orb"]: rate / chaos} if chaos else {})}
    kinds = {name: kind for name, kind in stored.get("kinds", {}).items() if kind != EXCHANGE_KIND}
    prices = {name: value for name, value in stored.get("prices_in_divine", {}).items() if stored.get("kinds", {}).get(name) != EXCHANGE_KIND}
    for path, sold_for in exchange_rates(markets, stored["league"]).items():
        name = names.get(path)
        offers = [(sold_for[coin][1] * value, sold_for[coin][0] * value) for coin, value in worth.items() if coin in sold_for]
        if name and name not in prices and path not in worth and offers:
            prices[name], kinds[name] = max(offers)[1] / rate, EXCHANGE_KIND
    return {**stored, "prices_in_divine": prices, "kinds": kinds}


def update_exchange_prices(stored: dict, on_changed, switches: int) -> dict:
    """For a league that is not the main one, where many goods have no price on poe.ninja. One public file an hour."""
    leagues = stored.get("leagues", [])
    if not leagues or league_rule(stored["league"], leagues) == AUTO_LEAGUE or not is_older_than(stored, PRICE_UPDATE_INTERVAL, "exchange_checked"):
        return stored
    names = clean_uniques(read_json(UNIQUES_PATH) or {}).get("exchange", {})
    if not names:
        return stored
    stored = {**stored, "exchange_checked": now_text()}
    try:
        _, digest = fetch_exchange(time.time(), APP_USER_AGENT)
        stored = exchange_lines_to_prices(stored, digest["markets"], names)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, http.client.HTTPException):
        log_error("exchange prices")  # a bonus: the prices from poe.ninja still stand
    league_board.save_prices(stored, switches)
    on_changed()
    return stored


def update_scout_currency(stored: dict, on_changed, switches: int | None = None) -> dict:
    """Currency in a category poe.ninja does not cover: a league's new goods can have a price here before they have a section there."""
    market = clean_market_sections(read_json(MARKET_SECTIONS_PATH) or {})
    stamps = stored.get("scout_updated", {})
    switches = league_board.switches if switches is None else switches
    for name, _ in market["currency_categories"]:
        if name in SCOUT_CURRENCY_COVERED or not is_older_than(stamps, PRICE_UPDATE_INTERVAL, name):
            continue
        query = urllib.parse.urlencode({"category": name, "perPage": SCOUT_CURRENCY_PAGE})
        answer, _ = fetch_overview(f"{SCOUT_API}Leagues/{urllib.parse.quote(stored['league'])}/Currencies/ByCategory?{query}", None)
        if isinstance((answer or {}).get("Items"), list):
            stored = scout_lines_to_prices(stored, answer["Items"])
        stamps = {**stamps, name: now_text()}
        stored = {**stored, "scout_updated": stamps}
        league_board.save_prices(stored, switches)
        on_changed()
        time.sleep(NINJA_REQUEST_GAP_SECONDS)
    return stored


UPDATE_SUFFIX = ".update"  # the new exe while it downloads and is checked, next to the running one
REPLACED_SUFFIX = ".old"  # the exe that stepped aside for the new one; removed at the next start
UPDATE_SIZE_LIMIT = 200 * 2 ** 20
UPDATE_CHUNK = 2 ** 16
UPDATE_TIMEOUT_SECONDS = 60
SHA256_DIGEST = re.compile(r"sha256:([0-9a-f]{64})")


class Release(NamedTuple):
    """A newer version. The download, its sha256 and size come from GitHub's own record of the file; without them the player is sent to the page instead."""
    tag: str
    link: str
    download: str | None = None
    sha256: str | None = None
    size: int | None = None


def read_release(answer: dict, current: str) -> Release | None:
    """A version newer than this one, and where it lies. None for anything else, including what cannot be read."""
    tag = answer.get("tag_name")
    link = answer.get("html_url")
    if not isinstance(tag, str) or not isinstance(link, str) or answer.get("draft") or answer.get("prerelease"):
        return None
    try:
        if version_order(tag.removeprefix("v")) <= version_order(current):
            return None
    except (AttributeError, ValueError):
        return None
    home = f"https://github.com/{GITHUB_REPOSITORY}/releases/download/"
    for asset in answer.get("assets") or ():
        if not isinstance(asset, dict):
            continue
        url, size, digest = asset.get("browser_download_url"), asset.get("size"), SHA256_DIGEST.fullmatch(str(asset.get("digest") or ""))
        if (str(asset.get("name", "")).lower().endswith(".exe") and isinstance(url, str) and url.startswith(home) and digest
                and isinstance(size, int) and 0 < size <= UPDATE_SIZE_LIMIT):
            return Release(tag, link, url, digest.group(1), size)
    return Release(tag, link)


def update_program(patches: dict, status, on_changed, told: set | None = None) -> None:
    """Says when a newer version is out. Nothing is fetched or replaced until the player asks for it.
    told holds the versions already shown, so a check every ten minutes says each one once."""
    if GITHUB_REPOSITORY:
        release = read_release(json.loads(fetch(f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest", attempts=1, user_agent=APP_USER_AGENT)), VERSION)
        if release and (told is None or release.tag not in told):
            if told is not None:
                told.add(release.tag)
            status(t("Вышла новая версия {version}: обновить можно в разделе Divine или в меню значка").format(version=release.tag))
            if on_changed:
                on_changed(release)


def run_program_checks(status, on_release, nap=time.sleep) -> None:
    """Looks for a newer version at the start and then every ten minutes, apart from the slower data checks, so a release reaches everyone the same hour.
    Being offline is not an error worth a log line every ten minutes."""
    told: set = set()
    while True:
        try:
            update_program({}, status, on_release, told)
        except (OSError, ValueError):
            pass
        except Exception:
            log_error("update_program")
        nap(PROGRAM_CHECK_SECONDS)


def replaced_path(exe: Path) -> Path:
    return exe.with_name(f"{exe.stem}{REPLACED_SUFFIX}{exe.suffix}")


def download_update(release: Release, exe: Path, progress) -> Path:
    """Fetches the new exe next to the running one and checks it is whole and is the very file GitHub published. Returns where it lies.
    progress(done, total) is told as it comes. Anything wrong removes what came and raises."""
    fresh = exe.with_name(exe.stem + UPDATE_SUFFIX)
    digest, done = hashlib.sha256(), 0
    try:
        request = urllib.request.Request(release.download, headers={"User-Agent": APP_USER_AGENT})
        with urllib.request.urlopen(request, timeout=UPDATE_TIMEOUT_SECONDS) as answer, open(fresh, "wb") as file:
            while chunk := answer.read(UPDATE_CHUNK):
                done += len(chunk)
                if done > release.size:
                    raise ValueError("the file is larger than GitHub says")
                file.write(chunk)
                digest.update(chunk)
                progress(done, release.size)
        if done != release.size or digest.hexdigest() != release.sha256:
            raise ValueError(t("скачанный файл не совпал с опубликованным"))
        with open(fresh, "rb") as file:
            if file.read(2) != b"MZ":
                raise ValueError(t("скачанный файл не программа"))
    except BaseException:
        fresh.unlink(missing_ok=True)
        raise
    return fresh


def swap_in_update(exe: Path, fresh: Path) -> Path:
    """A running exe can be moved but not overwritten: it steps aside and the new one takes its name. If that fails, the old one goes back."""
    old = replaced_path(exe)
    old.unlink(missing_ok=True)  # left by an earlier update
    os.replace(exe, old)
    try:
        os.replace(fresh, exe)
    except OSError:
        os.replace(old, exe)
        raise
    return old


def remove_update_leftovers(exe: Path) -> bool:
    """Removes what the last update left: the old exe and a download that never finished. True when nothing is left.
    The old copy may still be closing, so a False is tried again a little later."""
    clean = True
    for path in (replaced_path(exe), exe.with_name(exe.stem + UPDATE_SUFFIX)):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            clean = False
    return clean

def build_bases(raw_bases: dict, pages: dict[str, dict]) -> dict[str, dict]:
    bases: dict[str, dict] = {}
    for raw in raw_bases.values():
        # "[DNT]" marks unfinished items the game does not use.
        if raw.get("domain") != "item" or raw.get("release_state") != "released" or raw["name"] in bases or raw["name"].startswith("["):
            continue
        tags = set(raw.get("tags", []))
        for name, page in pages.items():
            page_tags = set(page["tag"].split(",")) if page["tag"] else set()
            if page["item_class"] == raw.get("item_class") and (not page_tags or page_tags & tags):
                icon = raw.get("visual_identity", {}).get("dds_file", "").removesuffix(".dds")
                bases[raw["name"]] = {"item_class": raw["item_class"], "drop_level": raw.get("drop_level", 1), "page": name, "icon": icon}
                break
    return bases


def version_order(patch: str) -> tuple:
    """So that 0.5.10 counts as newer than 0.5.9, and 0.5.5e as newer than 0.5.5."""
    number, letter = re.fullmatch(r"([\d.]+)([a-z]?)", patch).groups()
    return tuple(int(part) for part in number.split(".")), letter


def find_patches() -> dict:
    patches = re.findall(r"\b0\.\d+\.\d+[a-z]?\b", fetch(POE2DB_URL))
    repoe = re.search(r"version\s*(\d+(?:\.\d+)+)", fetch(REPOE_URL), re.IGNORECASE)
    return {"schema": SCHEMA_VERSION, "poe2db_patch": max(patches, key=version_order, default=None), "game_version": repoe.group(1) if repoe else None}


def data_is_sound(fresh: dict, old: dict | None) -> bool:
    """A changed page on the site must not replace a working base with an empty one. The last word goes to the code that will read the file."""
    def sizes(data: dict) -> tuple[int, int, int]:
        pages = data.get("pages", {})
        return len(pages), len(data.get("bases", {})), sum(len(page.get("mods", ())) for page in pages.values())

    new_sizes = sizes(fresh)
    if not all(new_sizes) or (old and any(new < before * SMALLEST_SOUND_SHARE for new, before in zip(new_sizes, sizes(old)))):
        return False
    try:
        Database(fresh)
    except Exception:
        log_error("checking new data")
        return False
    return True


def kept_enough(fresh: dict | list, old: dict | list | None) -> bool:
    return bool(fresh) and (not old or len(fresh) >= len(old) * SMALLEST_SOUND_SHARE)


def update_data(patches: dict, status) -> None:
    modifiers = fetch(POE2DB_URL + "Modifiers")
    names = re.findall(r'href="/us/([^"#]+)#ModifiersCalc"', modifiers)
    names = [name for name in dict.fromkeys(names) if not UNSUPPORTED_PAGES.search(name)]
    pages, translations = {}, {}
    for number, name in enumerate(names, 1):
        status(t("Обновляю моды и веса: {number}/{total}").format(number=number, total=len(names)))
        view = extract_mods_view(fetch(POE2DB_URL + name))
        time.sleep(REQUEST_DELAY_SECONDS)
        ru_html = fetch(POE2DB_RU_URL + name)
        pages[name] = normalize_page(view, extract_mods_view(ru_html))
        translations.update(read_names(ru_html))
        time.sleep(REQUEST_DELAY_SECONDS)
    old = read_json(DATA_PATH) or {}
    own_pages = old.get("names_from_own_pages", {})
    currency_keys = dict(own_pages)
    for name in RUSSIAN_NAME_PAGES:
        try:
            currency_keys.update(read_names(fetch(POE2DB_RU_URL + name, attempts=1)))
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            log_error("russian names", f"the page {name} is gone; its items now come from their own pages")
        time.sleep(REQUEST_DELAY_SECONDS)
    translations.update(currency_keys)
    bases = build_bases(json.loads(read_repoe("base_items.min.json")[0]), pages)
    for base, info in bases.items():
        info["ru"] = translations.get(name_key(base), base)
    shown = {name: translations[name_key(name)] for name in [*(c[0] for c in CURRENCIES.values()), *OMENS] if name_key(name) in translations}
    shown.update({essence["name"]: essence["ru_name"] for page in pages.values() for essence in page["essences"]})
    fresh = {**patches, "fetched_at": now_text(), "pages": pages, "bases": bases, "currency_names": shown, "currency_keys": currency_keys, "names_from_own_pages": own_pages}
    if not data_is_sound(fresh, old):
        raise ValueError("the new mods look incomplete, the old ones stay")
    write_json(DATA_PATH, fresh)


def read_prices() -> dict:
    """Prices are stored in Divine Orbs. Files from older versions kept them in Exalted Orbs."""
    stored = read_json(PRICES_PATH) or {}
    if "prices_in_exalted" in stored:
        rate = stored.get("exalted_per_divine")
        old = stored.pop("prices_in_exalted")
        if is_positive_number(rate) and isinstance(old, dict):
            stored["prices_in_divine"] = {name: value / rate for name, value in old.items() if is_positive_number(value)}
    return clean_prices(stored)


def prices_in_exalted(stored: dict) -> dict[str, float]:
    return {name: value * stored["exalted_per_divine"] for name, value in stored["prices_in_divine"].items()}


def is_hardcore_league(name: str) -> bool:
    words = name.split()
    return "HC" in words or "Hardcore" in words


def economy_leagues(answer) -> dict:
    """poe.ninja's public list of economy leagues, newest first with the permanent ones last (poe.ninja/docs/api).
    Its other league list belongs to the site itself and is not for programs. This one has no hardcore flag, so the name tells."""
    if not isinstance(answer, list):
        raise ValueError("poe.ninja sent an odd league list")
    names = [found["id"] for found in answer if isinstance(found, dict) and isinstance(found.get("id"), str) and found["id"].strip()]
    if not names:
        raise ValueError(t("poe.ninja не вернул лигу с ценами"))
    return {"economyLeagues": [{"name": name, "hardcore": is_hardcore_league(name)} for name in names]}


def league_candidates(index_state: dict, choice: str | None = None) -> list[str]:
    """Newest first with the permanent league last, as the site gives them. The 'indexed' flag does not mean prices are missing.
    The choice is AUTO_LEAGUE, AUTO_HARDCORE, or the name of one league. A named league that has ended leaves the others of its kind to fall back on."""
    leagues = index_state["economyLeagues"]
    named = next((league for league in leagues if league["name"] == choice), None)
    hardcore = choice == AUTO_HARDCORE or bool(named and named["hardcore"]) or (choice not in (None, AUTO_LEAGUE) and not named and "HC" in str(choice).split())
    names = [league["name"] for league in leagues if bool(league["hardcore"]) == hardcore]
    names = sorted(names, key=lambda name: name in PERMANENT_LEAGUES)
    return [named["name"], *(name for name in names if name != named["name"])] if named else names


def league_rule(name: str, leagues: list[dict]) -> str:
    """What the player's pick means. The newest league of a kind is a choice of that kind, so the next league follows by itself; any other is a choice of that one league."""
    for kind, rule in ((False, AUTO_LEAGUE), (True, AUTO_HARDCORE)):
        names = sorted((league["name"] for league in leagues if bool(league["hardcore"]) == kind), key=lambda found: found in PERMANENT_LEAGUES)
        if names and names[0] == name:
            return rule
    return name


def apply_league(stored: dict, index_state: dict, choice: str | None = None) -> dict:
    skipped = [] if is_older_than(stored, LEAGUE_CHECK_INTERVAL, "league_checked") else stored.get("skipped_leagues", [])
    league = next((name for name in league_candidates(index_state, choice) if name not in skipped), None)
    if not league:
        raise ValueError(t("poe.ninja не вернул лигу с ценами"))
    same_league = league == stored.get("league")
    updated, etags = (stored.get("updated", {}), stored.get("etags", {})) if same_league else ({}, {})
    listed = [{"name": found["name"], "hardcore": bool(found["hardcore"])} for found in index_state["economyLeagues"]]
    last_seen = stored.get("last_seen", {}) if same_league else {}
    return {**stored, "league": league, "league_checked": now_text(), "skipped_leagues": skipped, "updated": updated, "etags": etags, "leagues": listed, "last_seen": last_seen}


class SteppingAside:
    """Windows that made way for the browser. They come back when the player is in the game again.
    A browser that never took the screen must not leave them away, so they come back after a while if the game never lost it."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.windows: list = []
        self.since = 0.0
        self.left_game = False

    def start(self, windows: list) -> None:
        self.windows, self.since, self.left_game = windows, self.clock(), False

    def cancel(self) -> None:
        self.windows = []

    def windows_to_bring_back(self, foreground, game) -> list:
        if not self.windows:
            return []
        if foreground != game:
            self.left_game = True
            return []
        if self.left_game or self.clock() - self.since > BROWSER_LONGEST_WAIT_SECONDS:
            back, self.windows = self.windows, []
            return back
        return []


class LeagueSwitched(Exception):
    """The player picked another league while a section was on its way: that answer belongs to the old one."""


class LeagueBoard:
    """What the price service and the window share about the league. A section read for one league must not be saved after the player moved to another."""

    def __init__(self):
        self.choice = None
        self.switches = 0
        self.lock = threading.Lock()

    def save_prices(self, stored: dict, switches: int) -> None:
        with self.lock:
            if switches != self.switches:
                raise LeagueSwitched
            write_json(PRICES_PATH, stored)

    def save_demand(self, stored: dict, switches: int) -> None:
        with self.lock:
            if switches != self.switches:
                raise LeagueSwitched
            write_json(DEMAND_PATH, stored)


league_board = LeagueBoard()


def league_slug(league: str) -> str:
    return re.sub(r"\W", "", league).casefold() or "league"


def switch_league_files(old: str | None, new: str) -> None:
    """Each league keeps what it has seen, so going back to one is instant and only what is out of date is read again."""
    LEAGUE_FOLDER.mkdir(exist_ok=True)
    for path, part in ((PRICES_PATH, "prices"), (DEMAND_PATH, "demand")):
        if old and path.exists():
            shutil.copyfile(path, LEAGUE_FOLDER / f"{league_slug(old)}_{part}.json")
    kept_prices = read_json(LEAGUE_FOLDER / f"{league_slug(new)}_prices.json")
    leagues = (read_json(PRICES_PATH) or {}).get("leagues", [])
    write_json(PRICES_PATH, {**(kept_prices or {"league": new}), "league": new, "leagues": leagues, "league_checked": now_text(), "retry_after": None})
    write_json(DEMAND_PATH, read_json(LEAGUE_FOLDER / f"{league_slug(new)}_demand.json") or {"league": new})


def is_positive_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def usable_line(item: dict, line: dict) -> bool:
    return isinstance(item.get("name"), str) and bool(item["name"]) and is_positive_number(line.get("primaryValue"))


def number_or_none(value) -> float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def plain_item_name(name: str) -> str:
    """The item's own name without the variant the program adds, which is the name poe2db knows."""
    return ITEM_VARIANT.sub("", name)


def stash_to_exchange(answer: dict) -> dict:
    """poe.ninja's stash overview in the shape of its exchange overview, so the same checks and merge serve both.
    Each variant of an item is its own line with its own price. Listings are a count, not a traded value, so no volume is made up from them."""
    if not isinstance(answer, dict) or not isinstance(answer.get("lines"), list) or not isinstance(answer.get("core"), dict):
        raise ValueError("poe.ninja sent an odd stash overview")
    items, lines = [], []
    for line in answer["lines"]:
        if not isinstance(line, dict) or not isinstance(line.get("name"), str) or not line["name"].strip() or line.get("corrupted") is True:
            continue
        variant = line.get("variant")
        name = f"{line['name']} ({variant})" if variant in VARIANT_WORDS else line["name"]
        icon = line.get("icon") if isinstance(line.get("icon"), str) else ""
        key = f"stash:{len(lines)}"
        items.append({"id": key, "name": name, "image": icon.removeprefix("https://web.poecdn.com")})  # the path from /gen/image on, as the exchange gives it
        lines.append({"id": key, "primaryValue": line.get("primaryValue"), "volumePrimaryValue": None, "sparkline": line.get("sparkLine") if isinstance(line.get("sparkLine"), dict) else {}})
    return {"core": {**answer["core"], "items": []}, "items": items, "lines": lines}


def merge_overview(stored: dict, overview: dict, kind: str) -> dict:
    """A reply is checked before it can reach the file: every price on screen and in every plan comes from here, and a bad one would stay until the next good reply."""
    core = overview["core"]
    if kind == "Currency" and not overview["lines"]:
        # This league has no prices yet: the next request picks another one.
        return {**stored, "league": None, "skipped_leagues": [*stored.get("skipped_leagues", []), stored["league"]]}
    result = {**stored, "updated": {**stored.get("updated", {}), kind: now_text()}}
    if overview["lines"]:
        if core["primary"] != "divine":
            raise ValueError(t("poe.ninja считает цены не в Divine, а в {unit}").format(unit=core["primary"]))
        rate = core["rates"].get("exalted")
        if not is_positive_number(rate):
            raise ValueError(f"poe.ninja sent an odd rate: {rate!r}")
        items = {item["id"]: item for item in core["items"] + overview["items"]}
        lines = [(items[line["id"]], line) for line in overview["lines"] if line["id"] in items and usable_line(items[line["id"]], line)]
        if not lines:
            raise ValueError("poe.ninja sent no usable prices")
        sparks = {item["name"]: line["sparkline"] if isinstance(line.get("sparkline"), dict) else {} for item, line in lines}
        # A section is replaced whole: what has left the market, or belonged to the last league, must not keep its old price for ever.
        gone = {name for name, owner in stored.get("kinds", {}).items() if owner == kind} - set(sparks)

        def kept(key: str) -> dict:
            return {name: value for name, value in stored.get(key, {}).items() if name not in gone}

        # Thin markets come and go, so the price it last had is worth keeping. A first reply for a league has nothing of its own to remember.
        last_time = stored.get("updated", {}).get(kind)
        left = {name: {"price": stored["prices_in_divine"][name], "date": last_time} for name in gone if last_time and name in stored.get("prices_in_divine", {})}
        result["last_seen"] = {**{name: value for name, value in stored.get("last_seen", {}).items() if name not in sparks}, **left}

        result["prices_in_divine"] = {**kept("prices_in_divine"), **{item["name"]: line["primaryValue"] for item, line in lines}}
        result["kinds"] = {**kept("kinds"), **{item["name"]: kind for item, _ in lines}}
        result["icons"] = {**kept("icons"), **{item["name"]: icon_path_from_ninja(item["image"] if isinstance(item.get("image"), str) else "") for item, _ in lines}}
        result["changes"] = {**kept("changes"), **{name: number_or_none(spark.get("totalChange")) for name, spark in sparks.items()}}
        result["sparklines"] = {**kept("sparklines"), **{name: [number_or_none(point) for point in spark["data"]] if isinstance(spark.get("data"), list) else [] for name, spark in sparks.items()}}
        result["volumes"] = {**kept("volumes"), **{item["name"]: number_or_none(line.get("volumePrimaryValue")) for item, line in lines}}
        result["exalted_per_divine"] = rate
        chaos = core["rates"].get("chaos")
        result["chaos_per_divine"] = chaos if is_positive_number(chaos) else stored.get("chaos_per_divine")
        result["fetched_at"] = now_text()
    return result


def icon_path_from_ninja(image_url: str) -> str:
    """poe.ninja image links hold the game art path, which also works on RePoE, so icons never touch the poe.ninja limit."""
    parts = image_url.split("/")
    if len(parts) < 4 or parts[2] != "image":
        return ""
    try:
        encoded = parts[3]
        return "Art/" + json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))[2]["f"]
    except (ValueError, KeyError, IndexError, TypeError):
        return ""


def make_art(payload: bytes) -> str:
    """Item art for a large picture: it keeps its shape, because a weapon is much taller than it is wide."""
    image = Image.open(io.BytesIO(payload)).convert("RGBA")
    image.thumbnail((ART_SIZE, ART_SIZE), Image.LANCZOS)
    output = io.BytesIO()
    image.save(output, "PNG", optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii")


def make_icon(payload: bytes) -> str:
    """Shrinks game art to a small transparent square PNG, ready for Tk."""
    image = Image.open(io.BytesIO(payload)).convert("RGBA")
    image.thumbnail((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
    canvas = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    canvas.paste(image, ((ICON_SIZE - image.width) // 2, (ICON_SIZE - image.height) // 2), image)
    output = io.BytesIO()
    canvas.save(output, "PNG", optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii")


def run_icon_downloads(wanted: queue.Queue, icons: dict[str, str], on_changed) -> None:
    """Saves and shows pictures as they come, because closing the program mustn't lose a long queue's work."""
    fresh = 0
    while True:
        path = wanted.get()
        # Some art has spaces in its name: an unquoted address raises an error that would end this thread for good.
        address = path if path.startswith("http") else REPOE_URL + urllib.parse.quote(path.removeprefix(LARGE_ART)) + ".png"
        try:
            payload = fetch_bytes(address, attempts=2)
            icons[path] = make_art(payload) if path.startswith(LARGE_ART) else make_icon(payload)
            fresh += 1
        except urllib.error.HTTPError as error:
            if error.code == 404:
                icons[path] = ""
        except (OSError, ValueError, http.client.HTTPException):
            pass  # tried again the next time the program asks for this picture
        if fresh and (wanted.empty() or fresh >= ICON_SAVE_BATCH):
            fresh = 0
            write_json(ICONS_PATH, dict(icons))
            on_changed()
        time.sleep(ICON_REQUEST_DELAY_SECONDS)


def league_is_due(stored: dict) -> bool:
    return not stored.get("league") or not stored.get("leagues") or is_older_than(stored, LEAGUE_CHECK_INTERVAL, "league_checked")


def sections_due(stored: dict, wanted=PRICE_KINDS) -> list[str]:
    """The wanted sections that are at least an hour old. Update times live in the file, so a restart causes no extra requests."""
    updated = stored.get("updated", {})
    return [kind for kind in wanted if is_older_than(updated, PRICE_UPDATE_INTERVAL, kind)]


def update_prices_once(stored: dict, on_changed, wanted=PRICE_KINDS, switches: int | None = None) -> dict:
    """Refreshes the wanted sections that are due, one request at a time without retries, saving after each."""
    switches = league_board.switches if switches is None else switches
    if league_is_due(stored):
        stored = apply_league(stored, economy_leagues(json.loads(fetch(NINJA_URL + "economy/leagues", attempts=1, user_agent=APP_USER_AGENT))), league_board.choice)
        league_board.save_prices(stored, switches)
        time.sleep(NINJA_REQUEST_GAP_SECONDS)
    for kind in sections_due(stored, wanted):
        query = urllib.parse.urlencode({"league": stored["league"], "type": kind})
        where = "stash/current/item" if kind in STASH_SECTIONS else "exchange/current"
        overview, etag = fetch_overview(f"{NINJA_API}economy/{where}/overview?{query}", stored.get("etags", {}).get(kind))
        if overview and kind in STASH_SECTIONS:
            overview = stash_to_exchange(overview)
        # Nothing new comes back when the data has not changed, which spares poe.ninja the work.
        stored = merge_overview(stored, overview, kind) if overview else {**stored, "updated": {**stored.get("updated", {}), kind: now_text()}}
        if stored.get("league"):
            stored = {**stored, "etags": {**stored.get("etags", {}), kind: etag}}
        league_board.save_prices(stored, switches)
        on_changed()
        if not stored.get("league"):
            break  # this league has no prices yet: the next pass picks another one
        time.sleep(NINJA_REQUEST_GAP_SECONDS)
    return stored


def pause_price_updates(pause: timedelta) -> None:
    with league_board.lock:  # read here, as the player may have just moved to another league
        write_json(PRICES_PATH, {**read_prices(), "retry_after": (datetime.now() + pause).isoformat(timespec="seconds")})


def updates_paused(stored: dict) -> bool:
    return bool(stored.get("retry_after")) and datetime.fromisoformat(stored["retry_after"]) > datetime.now()


class UpdateInterest:
    """Decides what poe.ninja is asked for: only what is in use, and nothing at all once the player has left."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.active_at = clock()
        self.viewed: frozenset[str] = frozenset()
        self.used_at: dict[str, float] = {}
        self.league_recheck = False
        self.watched: frozenset[str] = frozenset()  # sections with a price watch: these stay fresh when nobody is at the computer, as that is what a watch is for
        self.wake = threading.Event()

    def is_active(self) -> bool:
        return self.clock() - self.active_at < ACTIVE_SECONDS

    def mark_active(self) -> None:
        was_active = self.is_active()
        self.active_at = self.clock()
        if not was_active:
            self.wake.set()  # back after a break: the prices should catch up now

    def show(self, kinds) -> None:
        """Called with what is on screen. A new sight counts as use."""
        kinds = frozenset(kinds)
        if kinds != self.viewed:
            self.viewed = kinds
            self.mark_active()
            self.wake.set()

    def use(self, kind: str) -> None:
        """A price from this section was just shown, so it should not stay old."""
        self.used_at[kind] = self.clock()
        self.mark_active()
        self.wake.set()

    def patch_is_out(self) -> None:
        """A patch may start a league, so the next pass asks about that rather than waiting its turn."""
        self.league_recheck = True
        self.mark_active()
        self.wake.set()

    def wanted_sections(self, updated: dict) -> list[str]:
        if not self.is_active():
            return [kind for kind in PRICE_KINDS if kind in self.watched]
        recent = {kind for kind, stamp in self.used_at.items() if self.clock() - stamp < RECENT_USE_SECONDS}
        # A section never loaded is fetched once, because the price key needs to know its items.
        return [kind for kind in PRICE_KINDS if kind in CORE_SECTIONS or kind in LEARNED_SECTIONS or kind in self.viewed or kind in self.watched or kind in recent or kind not in updated]

    def wanted_uniques(self) -> list[str]:
        recent = {kind for kind, stamp in self.used_at.items() if self.clock() - stamp < RECENT_USE_SECONDS}
        return [kind for kind in UNIQUE_KINDS if kind in self.watched or (self.is_active() and (kind in self.viewed or kind in recent))]

    def nap(self, seconds: float) -> None:
        self.wake.wait(seconds)
        self.wake.clear()


def run_price_updates(status, on_changed, on_demand_changed=lambda: None, interest: UpdateInterest | None = None) -> None:
    """Prices and hot items share one queue, so poe.ninja never gets two requests at once."""
    interest = interest or UpdateInterest()
    while True:
        switches = league_board.switches
        stored = read_prices()
        if interest.league_recheck:
            interest.league_recheck = False
            stored = {**stored, "league_checked": None}
        wanted, uniques = interest.wanted_sections(stored.get("updated", {})), interest.wanted_uniques()
        demand = clean_demand(read_json(DEMAND_PATH) or {})
        due = (bool(wanted or uniques) and league_is_due(stored)) or sections_due(stored, wanted) or kinds_due(demand, uniques)
        if updates_paused(stored) or not due:
            interest.nap(60)
            continue
        try:
            stored = update_prices_once(stored, on_changed, wanted, switches)
            if stored.get("league") and stored.get("exalted_per_divine") and wanted:
                stored = update_scout_currency(stored, on_changed, switches)
                stored = update_exchange_prices(stored, on_changed, switches)
            if stored.get("league") and stored.get("exalted_per_divine") and uniques:
                update_demand(clean_demand(read_json(DEMAND_PATH) or {}), stored["league"], stored["exalted_per_divine"], lambda fresh: league_board.save_demand(fresh, switches), on_demand_changed, uniques)
        except LeagueSwitched:
            continue  # the next pass starts from the league now chosen
        except urllib.error.HTTPError as error:
            pause_price_updates(NINJA_BLOCK_PAUSE if error.code == 429 else NINJA_RETRY_PAUSE)
            status(t("poe.ninja ответил ошибкой {code}, использую сохранённые цены").format(code=error.code))
        except Exception as error:  # whatever an odd reply causes, the pause below keeps it from repeating every minute
            if not isinstance(error, OSError):
                log_error("price update")
            pause_price_updates(NINJA_RETRY_PAUSE)
            status(t("Не удалось обновить цены, использую сохранённые: {error}").format(error=error))


def read_unique_art(uniques: dict, russian_page: str) -> dict[str, str]:
    """Maps the name of each unique item, as either client writes it, to its art. The name decides the picture, not the base."""
    english = {unique["name"]: unique["visual_identity"]["dds_file"].removesuffix(".dds") for unique in uniques.values()
               if not unique.get("is_alternate_art") and unique.get("visual_identity", {}).get("dds_file")}
    art = {name.casefold(): path for name, path in english.items()}
    by_link = {name_key(name): path for name, path in english.items()}
    for link, shown in UNIQUE_CARD.findall(russian_page):
        path = by_link.get(name_key(urllib.parse.unquote(link)))
        if path:
            art[html.unescape(shown).strip().casefold()] = path
    return art


def read_unique_russian(uniques: dict, russian_page: str) -> dict[str, str]:
    """English name of each unique to its name in the Russian client."""
    by_link = {name_key(unique["name"]): unique["name"] for unique in uniques.values()}
    return {by_link[name_key(urllib.parse.unquote(link))]: html.unescape(shown).strip() for link, shown in UNIQUE_CARD.findall(russian_page) if name_key(urllib.parse.unquote(link)) in by_link}


def read_item_art(bases: dict, uniques: dict) -> dict[str, str]:
    """Pictures by name, for the few things poe.ninja lists without one, such as idols."""
    art = {}
    for item in (*bases.values(), *uniques.values()):
        path = (item.get("visual_identity") or {}).get("dds_file", "")
        if item.get("name") and path and not item.get("is_alternate_art") and not item["name"].startswith("["):
            art.setdefault(item["name"], path.removesuffix(".dds"))
    return art


def base_is_due(stored: dict | None, patches: dict) -> bool:
    """A base follows the game: it is read again when a patch comes out, and at least once a week."""
    version = patches.get("game_version")
    return is_older_than(stored, DATA_MAX_AGE) or bool(version and stored.get("game_version") != version)


def update_mods(patches: dict, status, on_changed) -> None:
    """Mods and weights: their pages are many, so they are read when the patch changes or the data gets old."""
    stored = read_json(DATA_PATH)
    if is_older_than(stored, DATA_MAX_AGE) or any(stored.get(key) != value for key, value in patches.items() if value):
        update_data(patches, status)
        on_changed()
        status(t("Моды и веса обновлены"))


def update_uniques(patches: dict, status, on_changed) -> None:
    """RePoE says at no cost whether its files changed, so a correction without a new version is noticed too."""
    stored = read_json(UNIQUES_PATH)
    tags = (stored or {}).get("tags", {})
    uniques_file, uniques_tag = read_repoe("uniques.min.json", tags.get("uniques"))
    items_file, items_tag = read_repoe("base_items.min.json", tags.get("base_items"))
    if base_is_due(stored, patches) or "items" not in stored or "exchange" not in stored or uniques_file or items_file:
        uniques, page = json.loads(uniques_file or read_repoe("uniques.min.json")[0]), fetch(POE2DB_RU_URL + "Unique_item")
        art = read_unique_art(uniques, page)
        if not kept_enough(art, (stored or {}).get("art")):
            raise ValueError("the new unique items look incomplete, the old ones stay")
        base_items = json.loads(items_file or read_repoe("base_items.min.json")[0])
        write_json(UNIQUES_PATH, {"fetched_at": now_text(), "game_version": patches.get("game_version"), "tags": {"uniques": uniques_tag, "base_items": items_tag}, "art": art, "russian": read_unique_russian(uniques, page), "items": read_item_art(base_items, uniques), "exchange": exchange_names(base_items)})
        on_changed()


def update_trade_stats(patches: dict, status, on_changed) -> None:
    """What the trade site can search by, for the links the program builds. It comes from an open project's list on GitHub, so nothing has to ask the site itself."""
    stored = clean_trade_stats(read_json(TRADE_STATS_PATH) or {})
    if all(language in stored and "source" in stored[language] and not is_older_than(stored[language], STAT_LIST_MAX_AGE) for language in LANGUAGES):
        return
    fresh = {}
    for language in LANGUAGES:
        index = read_stat_list(fetch(STAT_LIST_URL.format(language=language), attempts=1, user_agent=APP_USER_AGENT))
        if len(index.get("explicit", {})) < STAT_LIST_FEWEST_MODS:
            raise ValueError("the list of trade stats looks incomplete, the old one stays")
        fresh[language] = {"fetched_at": now_text(), "source": "Exiled Exchange 2", "index": index}
        time.sleep(REQUEST_DELAY_SECONDS)
    write_json(TRADE_STATS_PATH, fresh)
    on_changed()


def update_waystones(patches: dict, status, on_changed) -> None:
    """The Waystone mods for the warnings and the search line. Their page has its own layout, so they are read apart from the item pages."""
    stored = read_json(WAYSTONES_PATH)
    if base_is_due(stored, patches):
        english = fetch(POE2DB_URL + "Waystones")
        time.sleep(REQUEST_DELAY_SECONDS)
        fresh = read_waystone_mods(english, fetch(POE2DB_RU_URL + "Waystones"))
        if not kept_enough(fresh["kinds"], (stored or {}).get("kinds")):
            raise ValueError("the new Waystone mods look incomplete, the old ones stay")
        write_json(WAYSTONES_PATH, {"fetched_at": now_text(), "game_version": patches.get("game_version"), **fresh})
        on_changed()


def find_steam_manifest() -> Path | None:
    """Steam's own record of the installed game. It is Steam's file, not the game's, and only its build number is read."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam = Path(winreg.QueryValueEx(key, "SteamPath")[0])
        libraries = re.findall(r'"path"\s+"([^"]+)"', (steam / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace"))
    except (OSError, ImportError):
        return None
    for library in (str(steam), *libraries):
        path = Path(library.replace("\\\\", "\\")) / "steamapps" / f"appmanifest_{STEAM_APP_ID}.acf"
        if path.exists():
            return path
    return None


def read_manifest_build(text: str) -> int | None:
    found = re.search(r'"buildid"\s+"(\d+)"', text)
    return int(found.group(1)) if found else None


def read_online_build(reply: str) -> int | None:
    try:
        return int(json.loads(reply)["data"][STEAM_APP_ID]["depots"]["branches"]["public"]["buildid"])
    except (ValueError, KeyError, TypeError):
        return None


class PatchWatch:
    """Notices a new build of the game long before the data sites have anything to offer, then has them asked far more often until they do.
    What it has seen lives in a file, so a patch that came while the program was closed counts too."""

    def __init__(self, on_patch, clock=datetime.now):
        self.on_patch, self.clock = on_patch, clock
        self.wake = threading.Event()
        self.lock = threading.Lock()
        stored = clean_patch_watch(read_json(PATCH_WATCH_PATH) or {})
        self.build, self.rush_since, self.data_then = stored.get("build"), stored.get("rush_since"), stored.get("data_then")

    def _save(self) -> None:
        try:
            write_json(PATCH_WATCH_PATH, {"build": self.build, "rush_since": self.rush_since, "data_then": self.data_then})
        except OSError:
            log_error("saving patch_watch.json")

    def see(self, build: int | None) -> None:
        if build is None:
            return
        with self.lock:
            known, self.build = self.build, max(build, self.build or 0)
            changed = known is not None and build > known
            if changed:
                data = read_json(DATA_PATH) or {}
                self.rush_since, self.data_then = self.clock().isoformat(timespec="seconds"), [data.get("poe2db_patch"), data.get("game_version")]
            if changed or known is None:
                self._save()
        if changed:
            self.wake.set()
            self.on_patch()

    def rushing(self) -> bool:
        return bool(self.rush_since)

    def check_is_due(self, state: dict) -> bool:
        """Often at first, since that is when the sites catch up, then less often for the slower one."""
        if not self.rush_since:
            return False
        since = self.clock() - datetime.fromisoformat(self.rush_since)
        pause = RUSH_FIRST_PAUSE if since < RUSH_FIRST_SPELL else RUSH_LATER_PAUSE
        return not state.get("checked_at") or self.clock() - datetime.fromisoformat(state["checked_at"]) >= pause

    def review(self, data: dict | None) -> None:
        """The rush ends when both sites show something new, or when it has lasted so long that this build changed neither, as a small hotfix may."""
        if not self.rush_since:
            return
        data = data or {}
        moved = all(now and now != then for now, then in zip((data.get("poe2db_patch"), data.get("game_version")), self.data_then or (None, None)))
        if moved or self.clock() - datetime.fromisoformat(self.rush_since) > RUSH_LONGEST:
            with self.lock:
                self.rush_since = self.data_then = None
                self._save()


def run_local_build_watch(watch: PatchWatch, find=find_steam_manifest) -> None:
    """Asks the disk once a second whether Steam has changed its record, which costs next to nothing and reads the file only when it has."""
    path, seen, seconds = None, None, STEAM_FIND_SECONDS
    while True:
        if path is None:
            seconds += LOCAL_BUILD_SECONDS
            if seconds >= STEAM_FIND_SECONDS:
                path, seconds = find(), 0
        else:
            try:
                stamp = path.stat().st_mtime_ns
                if stamp != seen:
                    seen = stamp
                    watch.see(read_manifest_build(path.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                path = None
        time.sleep(LOCAL_BUILD_SECONDS)


def run_online_build_watch(watch: PatchWatch) -> None:
    """Steam's public build number, for a patch Steam has not downloaded here yet. A failure only means asking again later."""
    while True:
        try:
            watch.see(read_online_build(fetch(STEAM_BUILD_URL, attempts=1, user_agent=APP_USER_AGENT)))
            time.sleep(ONLINE_BUILD_SECONDS)
        except (OSError, ValueError):
            time.sleep(ONLINE_BUILD_FAILED_SECONDS)


def place_on_screen(place: str | None, screen: tuple[int, int, int, int], size: tuple[int, int] = (200, 100)) -> str | None:
    """A saved place on a monitor that is no longer there would leave a window nobody can reach. screen is left, top, width, height of all monitors together."""
    found = re.fullmatch(r"\+(-?\d+)\+(-?\d+)", place or "")
    if not found:
        return None
    left, top, width, height = screen
    x, y = int(found.group(1)), int(found.group(2))
    return place if left <= x <= left + width - size[0] and top <= y <= top + height - size[1] else None


def all_monitors() -> tuple[int, int, int, int]:
    metrics = ctypes.windll.user32.GetSystemMetrics
    return metrics(76), metrics(77), metrics(78), metrics(79)  # SM_XVIRTUALSCREEN and so on


def settle_window(window, x: int, y: int) -> None:
    """Tk asks Windows to move a window only when the place it asked for changes. In a long random run Windows left the preset window where it was
    once the main one had been hidden, shown and moved, and Tk never asked again, so it stayed behind. A step aside and back makes it ask."""
    window.update_idletasks()
    if (window.winfo_rootx(), window.winfo_rooty()) != (x, y):
        size = window.geometry().split("+")[0]
        window.geometry(f"{size}+{x}+{y + 1}")
        window.update_idletasks()
        window.geometry(f"{size}+{x}+{y}")


def retry_pause(failures: int) -> timedelta:
    return min(DATA_RETRY_PAUSE * 2 ** min(max(failures - 1, 0), 8), DATA_CHECK_INTERVAL)  # the power has its own limit, or a long time offline would overflow it


def check_databases(state: dict, status, steps: tuple) -> dict:
    """One pass over every base, each step being (update, its listener). One that fails leaves its old file and does not stop the others."""
    problem = None
    try:
        patches = find_patches()
        for update, on_changed in steps:
            try:
                update(patches, status, on_changed)
            except Exception as error:
                problem = error
                log_error(update.__name__)
    except Exception as error:
        problem = error
        log_error("finding the patch")
    _repoe_pass.clear()
    failures = state.get("failures", 0) + 1 if problem else 0
    pause = retry_pause(failures) if problem else DATA_CHECK_INTERVAL
    if problem:
        status(t("Базы не обновились, работаю на сохранённых. Повторю через {minutes} мин").format(minutes=int(pause.total_seconds() // 60)))
    return {"checked_at": now_text(), "next_check": (datetime.now() + pause).isoformat(timespec="seconds"), "failures": failures, "last_error": str(problem) if problem else None}


def drops_outdated() -> bool:
    """A drops.json from an older version lacks what this one shows, so it is fetched again without waiting for its week."""
    stored = read_json(DROPS_PATH)
    return isinstance(stored, dict) and stored.get("format") != DROPS_FORMAT


def check_is_due(state: dict) -> bool:
    return not state.get("next_check") or datetime.fromisoformat(state["next_check"]) <= datetime.now() or not all(path.exists() for path in (DATA_PATH, UNIQUES_PATH, WAYSTONES_PATH, DROPS_PATH, JEWELS_PATH)) or drops_outdated()  # a base a new version brings comes at once, not with the next check


def update_jewel_mods(patches: dict, status, on_changed) -> None:
    """The mods of each kind of jewel with their ranges, from poe2db, once a week and on a new patch: 16 small requests.
    The planner does not use them (jewels have other affix rules); the build page searches a similar jewel by them."""
    stored = read_json(JEWELS_PATH)
    if stored and set(JEWEL_PAGES) <= set(stored.get("pages", {})) and not base_is_due(stored, patches):
        return
    pages = {}
    for number, name in enumerate(JEWEL_PAGES, 1):
        status(t("Обновляю моды самоцветов: {number}/{total}").format(number=number, total=len(JEWEL_PAGES)))
        view = extract_mods_view(fetch(POE2DB_URL + name))
        time.sleep(REQUEST_DELAY_SECONDS)
        pages[name] = {"mods": normalize_page(view, extract_mods_view(fetch(POE2DB_RU_URL + name)))["mods"]}
        time.sleep(REQUEST_DELAY_SECONDS)
    if not all(page["mods"] for page in pages.values()):
        raise ValueError("a jewel page came without mods, the old ones stay")
    write_json(JEWELS_PATH, {"fetched_at": now_text(), "game_version": patches.get("game_version"), "pages": pages})
    if on_changed:
        on_changed()


def update_drop_sources(patches: dict, status, on_changed) -> None:
    """Where uniques and jewels drop, from the wiki once a week and on a new patch. Three small requests."""
    stored = read_json(DROPS_PATH)
    if stored and stored.get("format") == DROPS_FORMAT and not base_is_due(stored, patches):
        return
    write_json(DROPS_PATH, {"format": DROPS_FORMAT, "fetched_at": now_text(), "game_version": patches.get("game_version"), "items": fetch_drops(lambda url: fetch(url, attempts=1, user_agent=APP_USER_AGENT))})
    on_changed()


def run_data_updates(status, on_data, on_uniques=lambda: None, on_waystones=lambda: None, watch: PatchWatch | None = None, on_trade_stats=lambda: None) -> None:
    """Keeps every base current with nobody's help. The time of the next check lives in a file, so restarts cause no extra requests, and a failure is tried again sooner, then less often.
    A new build of the game wakes this at once."""
    steps = ((update_mods, on_data), (update_drop_sources, on_uniques), (update_jewel_mods, None), (update_names, on_data), (update_uniques, on_uniques), (update_waystones, on_waystones), (update_trade_stats, on_trade_stats), (update_market_sections, None))
    watch = watch or PatchWatch(lambda: None)
    while True:
        state = clean_updates(read_json(UPDATES_PATH) or {})
        if check_is_due(state) or watch.check_is_due(state):
            write_json(UPDATES_PATH, check_databases(state, status, steps))
            watch.review(read_json(DATA_PATH))
        watch.wake.wait(RUSH_NAP_SECONDS if watch.rushing() else DATA_NAP_SECONDS)
        watch.wake.clear()


# ------------------------------------------------------------------ game data
MAX_PER_SIDE = {"normal": 0, "magic": 1, "rare": 3}
UNKNOWN_WEIGHT = 1  # poe2db shows 1 when a weight is not known
# A rune in an Augment Socket lets its item roll one more group of mods, and it cannot be taken out again.
WARPING_RUNES = {"marksman": "Kolr's Hunt", "decay": "Katla's Gloom", "soul": "Medved's Tending", "destruction": "Thrud's Might", "chronomancy": "Uhtred's Sidereus", "berserking": "Vorana's Carnage"}
SOCKET_ORB = "Artificer's Orb"
RESISTANCE_FLUXES = {"Fire": "Blazing Flux", "Cold": "Chilling Flux", "Lightning": "Crackling Flux", "Chaos": "Void Flux"}
CATALYSTS = (("Adaptive Catalyst", r"Strength|Dexterity|Intelligence|Attributes"), ("Flesh Catalyst", r"\bLife\b"), ("Neural Catalyst", r"\bMana\b"), ("Carapace Catalyst", r"Armour|Evasion|Energy Shield"),
             ("Chayula's Catalyst", r"\bChaos\b"), ("Esh's Catalyst", r"Lightning"), ("Tul's Catalyst", r"\bCold\b"), ("Xoph's Catalyst", r"\bFire\b"), ("Uul-Netol's Catalyst", r"Physical"),
             ("Necrotic Catalyst", r"Minion"), ("Reaver Catalyst", r"\bAttack"), ("Sibilant Catalyst", r"Spell|Cast"), ("Skittering Catalyst", r"Speed"))
QUALITY_ITEMS = (("Armourer's Scrap", ("Body_Armours", "Boots", "Gloves", "Helmets", "Shields", "Bucklers")), ("Arcanist's Etcher", ("Wands", "Staves", "Sceptres")),
                 ("Blacksmith's Whetstone", ("Bows", "Claws", "Crossbows", "Daggers", "Flails", "One_Hand", "Quarterstaves", "Spears", "Talismans", "Two_Hand")))
FINISHING_HINTS_SHOWN = 4
UNIQUE_FEW_LISTINGS = 5
UPGRADE_OTHERS_KEPT = 2
COMPARE_LINES_SHOWN = 14
DEFAULT_WEIGHT = 1000
NEW_BASE = "Новая база"
language = "ru"
ENGLISH = {
    # The build page (build_items.py) and where items drop (drop_sources.py).
    # For your level (level_steps.py).
    "Какие моды искать:": "Which mods to search for:",
    "хотя бы {count} из": "at least {count} of",
    "все из": "all of",
    "Открывать вместе с Path of Exile 2": "Open with Path of Exile 2",
    "Не удалось: {error}": "Failed: {error}",
    "Перезапуск, план крафта сбросится": "Restarts; an open plan is reset",
    "Сторож без окна стартует с Windows и открывает Sakuya с игрой. Игру не читает.": "A watcher with no window starts with Windows and opens Sakuya with the game. It reads nothing of the game.",
    "Это работает только в Sakuya.exe": "This works in Sakuya.exe only",
    "Sakuya откроется, когда запустится Path of Exile 2": "Sakuya will open when Path of Exile 2 starts",
    "Sakuya больше не открывается вместе с игрой": "Sakuya no longer opens with the game",
    "Обновляю моды самоцветов: {number}/{total}": "Updating jewel mods: {number}/{total}",
    "Отметьте хотя бы один мод": "Tick at least one mod",
    "Ищу: {base}, все из: {mods}": "Looking for: {base}, all of: {mods}",
    "Найти похожий самоцвет": "Find a similar jewel",
    "Диапазон мода": "Mod's range",
    "Как на предмете": "As on the item",
    "Открыть поиск на трейде": "Open the trade search",
    "Моды самоцветов ещё не скачаны: ищу по значениям на предмете": "Jewel mods have not come yet: searching by the item's values",
    "требует ~{level} ур.": "needs about level {level}",
    "сайт торговли этот мод не ищет": "the trade site has no filter for this mod",
    "Сразу отмечены все моды вещи, что бывают на этом уровне: снимите лишние. Ищутся все отмеченные, со значениями тира, который бывает на этом уровне: у палки 65 ур. на 17–24 вместо T1 будет условный T7. Уровни ищутся диапазоном (для 15 — вещи на 14–21); очернённые моды, сплавы и руны не ищутся; правило уровня примерное.": "Every mod of the item this level can have is ticked at once: untick what you do not need. All ticked mods are searched for, at the values of the tier this level has: for a level 65 staff searched at 17–24, a T1 becomes something like a T7. Levels are searched as a band (for 15, items needing 14–21); desecrated mods, alloys and runes are not searched for; the level rule is approximate.",
    "на этом уровне не бывает: появится с {level} ур.": "not at this level: comes at level {level}",
    "Под твой уровень": "For your level",
    "Эта вещь": "This item",
    "Цена этой вещи": "Price of this item",
    "Ты {level}": "You {level}",
    "сама эта вещь": "this very item",
    "что можно надеть сейчас": "what you can wear now",
    "На {level} ур.: {opens}": "At level {level}: {opens}",
    "Открыть поиск на трейде ({low}–{high} ур.)": "Open the trade search (level {low}–{high})",
    "Ищу: {where}, требование {low}–{high} ур., {need}: {mods}": "Looking for: {where}, needing level {low}–{high}, {need}: {mods}",
    "мод": "the mod",
    "хотя бы 1 из": "at least 1 of",
    "хотя бы 2 из": "at least 2 of",
    "хотя бы половина из": "at least half of",
    "Любая база этого вида": "Any base of this kind",
    "Предмет из игры": "Item from the game",
    "Скрафтить на {level} ур.": "Craft for level {level}",
    "ур.": "lvl",
    "Мой уровень": "My level",
    "На этом уровне у вещи нет модов из её списка": "At this level the item has none of its mods",
    "Наденешь уже сейчас: нужен {need} ур.": "You can wear it now: it needs level {need}",
    "Нужен {need} ур., у тебя {mine}": "Needs level {need}, you are {mine}",
    "Уник не ослабить: до {need} ур. ищи редкую с теми же главными модами": "A unique cannot be weaker: until level {need}, look for a rare with its main mods",
    "← в коде нет имени, впишите ник, и он появится в истории": "← the code has no name: type one and it shows in the history",
    "Ник персонажа": "Character name",
    "требует {level} ур.": "needs level {level}",
    "История билдов": "Build history",
    "Убрать из истории": "Remove from history",
    "Выберите билд": "Choose a build",
    "Пока пусто: откройте код, и он появится здесь": "Empty for now: open a code and it will appear here",
    "С кого падает": "Drops from",
    "Шанс": "Chance",
    "База самоцвета": "Jewel base",
    "Боссы": "Bosses",
    "Где падают уники и самоцветы. Данные: poe2wiki.net (CC BY-NC-SA), обновляются раз в неделю.": "Where uniques and jewels drop. Data: poe2wiki.net (CC BY-NC-SA), updated weekly.",
    "Где угодно": "Anywhere",
    "Другое": "Other",
    "Испытания": "Trials",
    "Награды": "Rewards",
    "Не падает": "No longer drops",
    "Особые места": "Special places",
    "Открыть вики": "Open the wiki",
    "Вики": "Wiki",
    "Симулякр": "Simulacrum",
    "Создаётся": "Crafted",
    "Список придёт с вики при следующем обновлении данных.": "The list comes from the wiki with the next data update.",
    "Хранилище Атзири": "Atziri's Vault",
    "Где падает": "Where it drops",
    "Амулет": "Amulet",
    "Самоцвет": "Jewel",
    "Билд": "Build",
    "В этом коде нет надетых предметов": "This code has no equipped items",
    "Вставить и открыть": "Paste and open",
    "Вставьте код Path of Building": "Paste a Path of Building code",
    "Вставьте код билда: здесь появятся его предметы": "Paste a build code: its items will show here",
    "Вторая рука": "Off hand",
    "Выберите предмет": "Choose an item",
    "Код Path of Building": "Path of Building code",
    "Код даёт Path of Building, гайд или кнопка экспорта у персонажа на poe.ninja. Он читается на этом компьютере, в сеть ничего не уходит.": "Path of Building, a guide or the export button on a poe.ninja character gives the code. It is read on this computer, and nothing is sent anywhere.",
    "Кольцо": "Ring",
    "Копировать": "Copy",
    "Оберег": "Charm",
    "Осквернён": "Corrupted",
    "П": "P",
    "Пояс": "Belt",
    "Предмет в коде не прочитан": "An item in the code could not be read",
    "С": "S",
    "Флакон": "Flask",
    "Цена и трейд": "Price and trade",
    "Шлем": "Helmet",
    "Это код Path of Building для первой части игры, а нужен для PoE2": "This is a Path of Building code for the first game; a PoE2 one is needed",
    "Это не код Path of Building: скопируйте его целиком": "This is not a Path of Building code: copy all of it",
    "Это ссылка, а нужен сам код: откройте её в браузере и нажмите «Копировать код» или Export": "This is a link, and the code itself is needed: open it in the browser and press Copy code or Export",
    "качество {quality}%": "quality {quality}%",
    "очернён": "desecrated",
    "расколот": "fractured",
    "ур. предмета {level}": "item level {level}",
    "уровень {level}": "level {level}",
    "Новая база": "New base",
    "обычный": "normal", "волшебный": "magic", "редкий": "rare",
    "Обновляю моды и веса: {number}/{total}": "Updating mods and weights: {number}/{total}",
    "poe.ninja не вернул лигу с ценами": "poe.ninja returned no league with prices",
    "poe.ninja считает цены не в Divine, а в {unit}": "poe.ninja prices are not in Divine but in {unit}",
    "poe.ninja ответил ошибкой {code}, использую сохранённые цены": "poe.ninja answered with error {code}, using saved prices",
    "Не удалось обновить цены, использую сохранённые: {error}": "Could not update prices, using saved ones: {error}",
    "Моды и веса обновлены": "Mods and weights updated",
    "Базы не обновились, работаю на сохранённых. Повторю через {minutes} мин": "The bases did not update; working from the saved ones. Trying again in {minutes} min",
    "poe2db изменился: часть русских названий не найдена, подробности в errors.log": "poe2db has changed: some Russian names were not found, details in errors.log",
    "На poe.ninja есть новые разделы, программа их пока не показывает: {names}": "poe.ninja has new sections the program does not show yet: {names}",
    "Предмет не найден: {query}": "Item not found: {query}",
    "Под «{query}» подходит {count} предметов, уточните название": "{count} items match “{query}”, please be more specific",
    "«{title}» T{tier} требует уровень предмета {needed}+, сейчас {ilvl}": "“{title}” T{tier} needs item level {needed}+, this item is {ilvl}",
    "Выберите хотя бы один мод": "Select at least one mod",
    "Префиксов на этом предмете не больше {count}": "This item can have at most {count} prefixes",
    "Суффиксов на этом предмете не больше {count}": "This item can have at most {count} suffixes",
    "Эти моды несовместимы: «{first}» и «{second}»": "These mods cannot be together: “{first}” and “{second}”",
    "Расколот мод слишком слабого тира, его не убрать: цель на этом предмете недостижима": "A mod of too low a tier is fractured and cannot be removed: this goal is impossible on this item",
    "Расколотый мод занимает нужный слот: цель на этом предмете недостижима": "The fractured mod takes a slot you need: this goal is impossible on this item",
    
    "слабый тир: {title}": "low tier: {title}",
    "лишние: {prefixes} преф., {suffixes} суфф.": "extra: {prefixes} prefix, {suffixes} suffix",
    "закреплён: {title}": "fractured: {title}",
    "закреплён лишний мод": "an extra mod is fractured",
    "нужного нет": "nothing needed yet",
    "пропал: {title}": "lost: {title}",
    "лишний префикс": "extra prefix", "лишний суффикс": "extra suffix",
    "убран лишний префикс": "extra prefix removed", "убран лишний суффикс": "extra suffix removed",
    "ничего полезного": "nothing useful",
    "Не удалось прочитать предмет: держите курсор на нём или выберите базу вручную": "Could not read the item: keep the cursor on it or pick the base by hand",
    "Этот предмет нельзя крафтить здесь: редкость «{rarity}»": "This item cannot be crafted here: rarity “{rarity}”",
    "нет": "none",
    "Сначала опознайте предмет": "Identify the item first",
    "База «{base}» не поддерживается: нет данных о модах": "Base “{base}” is not supported: there is no mod data",
    "В описании предмета нет уровня предмета": "The item text has no item level",
    "Крафт": "Craft", "Валюта": "Currency",
    "База": "Base", "Открыть": "Open", "Поиск": "Search",
    "Предмет": "Item", "Объём": "Volume", "История": "History", "Неделя": "Week",
    "Цены ещё загружаются": "Prices are still loading",
    "{league}  •  обновлено {time}  •  обновляется при просмотре, не чаще раза в час": "{league}  •  updated {time}  •  refreshed when viewed, at most once an hour",
    "Ничего не найдено": "Nothing found",
    "Цены этого раздела придут при следующем обновлении": "Prices for this section arrive with the next update",
    "Лига: {league}  |  ": "League: {league}  |  ",
    "Патч {version}  |  ": "Patch {version}  |  ",
    "Наведите курсор на предмет в игре и нажмите {copy}": "Hover an item in game and press {copy}",
    
    "Готово": "Ready",
    "Загружаю данные, первая загрузка займёт пару минут...": "Loading data, the first run takes a couple of minutes...",
    "{name} уже занята другой программой": "{name} is already used by another program",
    "Предмет не скопировался: держите курсор на предмете в игре и нажмите {copy} ещё раз": "The item was not copied: keep the cursor on it in game and press {copy} again",
    "Данные ещё загружаются, подождите": "Data is still loading, please wait",
    "предмет осквернён, менять его нельзя": "the item is corrupted and cannot be changed",
    "игра не показала подробные моды, текущие моды не учтены": "the game did not show detailed mods, current mods are not counted",
    "не распознано модов: {count}, считаю их лишними": "{count} mods not recognised, counting them as extra",
    "Выберите нужные моды и нажмите «Рассчитать»": "Select the mods you want and press Calculate",
    "Данные ещё загружаются": "Data is still loading",
    "например: добавляет от до  •  холоду  •  скорость атаки": "for example: adds  •  cold  •  attack speed",
    "Префиксы": "Prefixes", "Суффиксы": "Suffixes",
    "Можно брать новую базу, цена в Divine:": "New bases allowed, price in Divine:",
    "⚠ Весов этого типа нет на poe2db: шансы очень грубые": "⚠ poe2db has no weights for this type: odds are very rough",
    "Сначала заточите предмет катализаторами до предела, это около {count} шт. «{catalyst}», и активируйте знамение.": "First fill the item's quality with catalysts, about {count} × «{catalyst}», and activate the omen.",
    "Качество сгорит, а моды этого типа выпадут с повышенным шансом, но не наверняка.": "The quality is used up, and mods of that type come more often, but not for sure.",
    "Заточите предмет: «{name}» до предела качества, это около {count} шт.": "Fill the item's quality with “{name}”: about {count} of them.",
    "План использует катализаторы со знамением, поэтому шансы оценочные: насколько качество повышает шанс, известно лишь по двум числам с вики PoE2.": "This plan uses catalysts with the omen, so its odds are estimates: how much quality raises the chance is known only from two numbers on the PoE2 wiki.",
    "Кость на оружии или бижутерии точно предложит мод лича {lich}.": "On a weapon or jewellery the bone will surely offer a mod of {lich}.",
    "Один из вариантов точно будет модом лича {lich}.": "One of the options will surely be a mod of {lich}.",
    "Уламана": "Ulaman",
    "Аманаму": "Amanamu",
    "Кургала": "Kurgal",
    "поднимет потолок качества до {cap}%. Это делается посреди крафта, пока на предмете есть лишний мод: со знамением кристаллизации сущность снимет его. Потом около {count} катализаторов, и знамение оттачивания со сферой хаоса снимет мод сущности, а качество останется":
        "raises the quality cap to {cap}%. It is done mid-craft, while the item has a mod you do not need: with a Crystallisation omen the essence removes it. Then about {count} catalysts, and the Omen of Whittling with a Chaos Orb removes the essence's mod while the quality stays",
    "Рассчитать": "Calculate", "Считаю...": "Calculating...",
    "Наложите Прядь Хинекоры и посмотрите, что дадут сферы хаоса, возвышения и отмены всех уровней. Примените ту, что даёт лучший результат: Прядь сгорит вместе с ней.": "Put Hinekora's Lock on the item and look at what Chaos, Exalted and Annulment Orbs of every grade would do. Use the one with the best result: the Lock goes with it.",
    "на предмете: T{tier}": "on item: T{tier}",
    "вес неизвестен": "weight unknown",
    "любой тир": "any tier", "T{tier} и лучше": "T{tier} or better",
    "найдено {count}": "found {count}",
    "{title}  {chosen} из {limit}{found}": "{title}  {chosen} of {limit}{found}",
    "Цена базы должна быть положительной": "The base price must be positive",
    "Считаю лучший путь, для 6 модов это занимает до двух минут": "Finding the best path, six mods can take up to two minutes",
    "Такого состояния не было в плане, пересчитываю...": "This result was not in the plan, recalculating...",
    "←  Выбор модов": "←  Choose mods",
    "Цены от {time}": "Prices from {time}",
    "Цель": "Goal", "В среднем с начала": "Average from the start",
    "Дальше примерно так": "What comes next, roughly",
    "Процент: шанс, что шаг даст нужный мод": "Percent: the chance the step gives a mod you need",
    "Скрыть подробности": "Hide details", "Подробнее о расходе": "Spending details",
    "Это сумма за все неудачи, а не за один заход: около {attempts} попыток с новой базой.": "This adds up all failures, not one try: about {attempts} attempts with new bases.",
    "Это среднее с учётом неудачных бросков на этом предмете: повезти может раньше или позже.": "This is the average including failed rolls on this item: luck can come sooner or later.",
    "   ({count} на попытку)": "   ({count} per attempt)",
    "Раскалывающая сфера не учтена: цель слишком большая для быстрого расчёта.": "The Fracturing Orb is not counted: this goal is too large for a quick calculation.",
    "Готово! Все нужные моды на предмете.": "Done! All the mods you wanted are on the item.",
    "Потрачено по подсказкам: {cost}": "Spent following the steps: {cost}",
    "Что сделать сейчас": "What to do now",
    "Включите знамение: правый клик по «{name}» в инвентаре": "Activate the omen: right click “{name}” in your inventory",
    "Примените «{name}» на предмет": "Use “{name}” on the item",
    "Возьмите новую базу того же типа": "Take a new base of the same type",
    "Нажмите {copy} на предмете: программа сама увидит результат и скажет следующий шаг": "Press {copy} on the item: the program reads the result and shows the next step",
    "Группа «любые {count}» не помещается на предмет вместе с остальными модами": "The group \"any {count}\" does not fit on the item with the other mods",
    "любой из группы": "any of the group",
    "Вставить код": "Paste code",
    "Код цели": "Goal code",
    "Вставить код цели": "Paste a goal code",
    "Код цели скопирован: вставьте его другу, а он нажмёт «Вставить код»": "Goal code copied: send it to a friend, who presses \"Paste code\"",
    "В буфере обмена нет кода цели Sakuya": "The clipboard holds no Sakuya goal code",
    "Такой базы нет в данных: {base}": "This base is not in the data: {base}",
    "Из группы ◇ нужно:": "Needed from the ◇ group:",
    "из {count}": "of {count}",
    "оставить место": "keep a place free",
    "Нужно {need} из {count} отмеченных ◇": "{need} of the {count} marked ◇ are needed",
    "Свободным останется: {places}": "Kept free: {places}",
    "{count} преф.": "{count} prefix",
    "{count} суфф.": "{count} suffix",
    "{title}  {chosen} из {limit}, свободно {free}{found}": "{title}  {chosen} of {limit}, {free} free{found}",
    "Уже считаю план, дождитесь результата": "Already working out a plan, wait for the result",
    "Дешевле всего": "Cheapest",
    "Меньше действий": "Fewer steps",
    "Меньше трат, можно менять базы": "Least spent, bases can be replaced",
    "Меньше нажатий, база остаётся той же": "Fewer clicks, the same base stays",
    "примерно {count} действий": "about {count} actions",
    "Настройки": "Settings",
    "Горячие клавиши": "Hotkeys",
    "Открыть предмет в крафте": "Open the item in the crafter",
    "Показать или скрыть главное окно": "Show or hide the main window",
    "Изменить": "Change",
    "Нажмите сочетание...": "Press the keys...",
    "Нажмите новое сочетание клавиш, Esc отменяет": "Press the new keys, Esc cancels",
    "Сбросить клавиши": "Reset hotkeys",
    "Проверить цену предмета": "Check the item's price",
    "Проверка цены": "Price check",
    "Окно цены по клавише": "Price window on a hotkey",
    "Цены валюты обновляются раз в час и показываются без лишних запросов.": "Currency prices refresh once an hour and are shown without extra requests.",
    "{count} шт. = {total}": "{count} pcs = {total}",
    "обновлено {time}": "updated {time}",
    "неделя {change}": "week {change}",
    "Предмет не прочитан: держите курсор на нём и нажмите {key} ещё раз": "The item was not read: keep the cursor on it and press {key} again",
    
    "Открыть сайт торговли": "Open the trade site",
    
    
    
    
    
    "Как у предмета": "As on the item", "От 90%": "From 90%", "От 80%": "From 80%", "Любое": "Any",
    
    
    
    
    
    "Ходовое": "Hot items", "Гайды по билдам": "Build guides", "Все": "All", "Бижутерия": "Jewellery", "Броня": "Armour", "Оружие": "Weapons",
    "Самоцветы": "Jewels", "Флаконы": "Flasks", "По спросу": "By demand", "По рынку": "By market", "По цене": "By price", "Спрос": "Demand", "Лотов": "Listed", "Цена ≈": "Price ≈",
    "высокий": "high", "средний": "medium", "низкий": "low", 
    
    
    "За неделю: цена {price}, объявлений {listings}": "This week: price {price}, listings {listings}",
    "Спрос это оценка: цена растёт, а объявлений становится меньше. Что носят билды, открытые данные не показывают.": "Demand is an estimate: the price climbs while listings shrink. Open data does not show what builds wear.",
    "Данные придут при следующем обновлении": "The data arrives with the next update",
    "Поддержать автора (скопировать адрес USDT TRC20)": "Support the author (copy the USDT TRC20 address)",
    "Поддержать автора: {network}, только эта сеть": "Support the author: {network}, this network only",
    "Энергощит": "Energy shield",
    "Энергощит + здоровье": "Energy shield + life",
    "Сопротивления + хаос": "Resistances + chaos",
    "Дух": "Spirit",
    "Блок": "Block",
    "Пояс на броню": "Armour belt",
    "Перчатки на скорость атаки": "Attack speed gloves",
    "Ближний бой": "Melee",
    "Лук": "Bow",
    "Арбалет": "Crossbow",
    "Чары холода": "Cold spells",
    "Чары огня": "Fire spells",
    "Чары молнии": "Lightning spells",
    "Миньоны": "Minions",
    "Шлем на миньонов": "Minion helmet",
    "Амулет на миньонов": "Minion amulet",
    "Колчан на стрелу": "Extra arrow quiver",
    "Кольцо на 4 флэта": "Four flats ring",
    "Уклонение": "Evasion",
    "Броня + уклонение": "Armour + evasion",
    "Броня + энергощит": "Armour + energy shield",
    "Уклонение + энергощит": "Evasion + energy shield",
    "Скорость передвижения": "Movement speed",
    "Физический урон": "Physical damage",
    "Стихийный урон": "Elemental damage",
    "Чары": "Spells",
    "Кольцо атаки": "Attack ring",
    "Здоровье и сопротивления": "Life and resistances",
    "Пресет: {name}": "Preset: {name}",
    "Мои цели и пресеты": "My goals and presets",
    "Пресеты": "Presets",
    "Амулет на чары": "Spell amulet",
    "Амулет на ближний бой": "Melee amulet",
    "Амулет на снаряды": "Projectile amulet",
    "Перчатки на атаку": "Attack gloves",
    "Колчан": "Quiver",
    "Фокус на энергощит": "Energy shield focus",
    "Нательная броня": "Body armours",
    "Шлемы": "Helmets",
    "Перчатки": "Gloves",
    "Сапоги": "Boots",
    "Щиты": "Shields",
    "Баклеры": "Bucklers",
    "Фокусы": "Foci",
    "Колчаны": "Quivers",
    "Кольца": "Rings",
    "Амулеты": "Amulets",
    "Пояса": "Belts",
    "Луки": "Bows",
    "Арбалеты": "Crossbows",
    "Копья": "Spears",
    "Боевые посохи": "Quarterstaves",
    "Посохи": "Staves",
    "Жезлы": "Wands",
    "Скипетры": "Sceptres",
    "Одноручные булавы": "One-handed maces",
    "Двуручные булавы": "Two-handed maces",
    "Одноручные мечи": "One-handed swords",
    "Двуручные мечи": "Two-handed swords",
    "Одноручные топоры": "One-handed axes",
    "Двуручные топоры": "Two-handed axes",
    "Цепы": "Flails",
    "Когти": "Claws",
    "Кинжалы": "Daggers",
    "Талисманы": "Talismans",
    "Ловушки": "Traps",
    "Скопировать адрес": "Copy address", "Спасибо за поддержку!": "Thank you for the support!",
    "Адрес скопирован. Отправляйте только {network}, другие сети и монеты потеряются": "Address copied. Send only {network}: other networks and coins will be lost",
    "Выход": "Quit","{toggle} открывает и прячет окно, {price} показывает цену": "{toggle} shows and hides the window, {price} shows a price",
    "Чёрточка вверху справа прячет окно в трей, горячие клавиши продолжают работать.": "The dash at the top right hides the window in the tray, and the hotkeys keep working.",
    "Вышел патч: обновляю базы, как только сайты их выложат": "A patch is out: updating the bases as soon as the sites publish them",
    "Рынок пополнился: {names}": "The market has grown: {names}",
    "Лига: {league}. Обновляю цены...": "League: {league}. Updating prices...",
    "В этой лиге сайт не считает уникальные предметы, цены валюты есть": "The site does not track uniques in this league; currency prices are there",
    "Сфера хаоса уберёт мод самого низкого уровня.": "A Chaos Orb removes the lowest level modifier.",
    "Совершенная эссенция уберёт только префикс.": "A Perfect Essence removes only a prefix.",
    "Совершенная эссенция уберёт только суффикс.": "A Perfect Essence removes only a suffix.",
    "Уберёт 1 случайный мод и гарантированно добавит нужный.": "Removes 1 random modifier and adds the one you need for certain.",
    "Уберёт мод самого низкого уровня и добавит новый.": "Removes the lowest level modifier and adds a new one.",
    "Шанс оценён по уровням возможных модов.": "The chance is reckoned from the levels of the possible modifiers.",
    "Убирает только префиксы.": "Removes only prefixes.",
    "Убирает только суффиксы.": "Removes only suffixes.",
    "{name}: {price}, порог {limit}": "{name}: {price}, limit {limit}",
    "Цена дошла до порога": "A price has reached its limit",
    "Предмет": "Item",
    "Следить за ценой": "Watch the price",
    "Только эта база": "This base only",
    "Любая база этого типа": "Any base of this kind",
    "▲ {rolls}, нужен ур. {level}": "▲ {rolls}, needs level {level}",
    "Цена улучшения": "Upgrade price",
    "Сравнить с: {name}": "Compare with: {name}",
    "Открыть на poe2db": "Open on poe2db",
    "Считаю цену улучшения...": "Working out the upgrade price...",
    "Не удалось посчитать, подробности в errors.log": "Could not work it out, details in errors.log",
    "{mod}: на тир выше, в среднем {cost}. Другие лучшие моды сохраняются.": "{mod}: one tier up, about {cost} on average. The other best mods are kept.",
    "Сравнение: слева этот, справа {name}": "Comparison: this one on the left, {name} on the right",
    "Нет модов для сравнения": "No mods to compare",
    "Назад": "Back",
    "По обменам за прошлый час, цена примерная": "From last hour's exchange, an approximate price",
    "Журнал": "Journal", "Биржа": "Exchange", "Камни": "Waystones", "Таймер": "Timer", "Счёт": "Calculator", "Заметки": "Notes",
    "Сколько": "How much", "Чего": "Of what", "Перевести в": "Convert to",
    "По ценам, которые уже есть в программе. Без запросов. Название можно писать на любом языке, часть названия тоже подойдёт.": "At the prices already in the program, with no requests. Names work in either language, and part of a name is enough.",
    "Нужно число и название предмета с ценой": "A number and the name of a priced item are needed",
    "Цели билда, что искать, что не забыть. Хранится только на этом компьютере.": "Build goals, what to look for, what not to forget. Kept on this computer only.",
    "Улучшить в крафте": "Improve in the planner",
    "Средняя цена {price}, объявлений {count}": "Average price {price}, listings {count}",
    "Без учёта роллов.": "Rolls are not counted.",
    "Объявлений мало, цена неточная.": "Few listings, so the price is rough.",
    "Средней цены нет: сайт цен не считает этот предмет в этой лиге.": "No average price: the price site does not track this item in this league.",
    "Качество модов: {score} из 100": "Mod quality: {score} of 100",
    "Оценка тиров и роллов, это не цена.": "A rating of tiers and rolls, not a price.",
    "Для этого мода нужна руна «{rune}», а её цены нет или она запрещена": "This mod needs the rune «{rune}», which has no price or is banned",
    "Этот мод даёт только «{item}», а его цены нет или он запрещён": "Only «{item}» gives this mod, and it has no price or is banned",
    "нужна руна «{rune}», вес неизвестен": "needs the rune «{rune}», weight unknown",
    "только через «{item}»": "only through «{item}»",
    "Сначала в гнездо: {items}. Это уже в цене. Руну нельзя вынуть.": "First, into a socket: {items}. This is in the price. The rune cannot be taken out.",
    "Шансы модов руны оценочные: настоящего веса нет на poe2db.": "The chances of the rune's mods are estimates: poe2db has no real weight for them.",
    "После крафта": "After the craft",
    "если выпало другое сопротивление, превратит все такие моды в нужное": "if another resistance came, turns all such mods into this one",
    "качеством усилит подходящие моды": "its quality strengthens matching mods",
    "поднимет качество предмета": "raises the item's quality",
    'Или выберите базу вручную вверху. {toggle} показывает и скрывает окно.\nИгра должна быть в оконном режиме без рамок.': 'Or pick a base above. {toggle} shows and hides this window.\nThe game must run in windowed fullscreen.',
    "Открыть на сайте торговли": "Open on the trade site",
    "Поиск откроется в вашем браузере, на сайте вы ищете сами. Программа к сайту не обращается.": "The search opens in your browser, and you search on the site yourself. The program does not contact the site.",
    "Список модов для поиска ещё загружается, пока сайт откроется только с базой предмета.": "The list of mods for searching is still loading, so for now the site opens with the item's base only.",
    "Посмотреть цену на сайте": "See the price on the site",
    "Без учёта: {mods}": "Left out: {mods}",
    "Всё вместе сейчас: {price}": "All together now: {price}",
    "без цены: {count}": "no price: {count}",
    "Сохранить цель": "Save goal",
    "Мои цели": "My goals",
    "Цель сохранена": "Goal saved",
    "Цель открыта, но модов не хватает: {count}": "Goal opened, but {count} mods are not available here",
    "Цель открыта: нажмите «Рассчитать»": "Goal opened: press «Calculate»",
    "Тайник": "Stash",
    "Должно быть всё из": "All of",
    "Хотя бы одно из": "Any of",
    "Ничего из": "None of",
    "Сохранить": "Save",
    "копировать": "copy",
    "Сохранённых строк пока нет": "No saved lines yet",
    "Пишите через запятую слова или части модов на языке игры. Строку вставляете вы сами в поиск тайника, программа ничего не отправляет в игру. Синтаксис поиска взят из гайдов: проверьте на паре предметов.": "Separate words or parts of mods with commas, in the game's language. You paste the line into the stash search yourself; the program sends nothing to the game. The search syntax comes from guides: check it on a couple of items.",
    "Слежение": "Watches",
    "История": "History",
    "дешевле": "below",
    "дороже": "above",
    "Поставить": "Add",
    "Сообщу значком в трее и строкой внизу окна, когда цена дойдёт до порога. Цены уже обновляются программой, лишних запросов нет. Разделы со слежением обновляются раз в час, даже когда за компьютером никого нет.": "A tray notice and a line at the bottom of the window will say when a price reaches its limit. The prices are already being updated, so this adds no requests of its own. Sections with a watch update hourly even when nobody is at the computer.",
    "Слежений пока нет": "No watches yet",
    "Такого предмета нет в ценах этой лиги, либо под название подходит несколько: уточните": "No such item among this league's prices, or the name fits several: be more specific",
    "Нужно название и порог числом": "A name and a numeric limit are needed",
    "Курс этой валюты ещё не загружен": "The rate of this currency is not loaded yet",
    "сейчас {price}": "now {price}",
    "дошла": "reached",
    "ждёт": "waiting",
    "нет обменов": "no trades",
    "сейчас нет обменов": "no trades now",
    "Сейчас обменов нет": "No trades right now",
    "Последняя цена {price}, {date}": "Last price {price}, {date}",
    "В этой лиге программа ещё не видела его цену": "The program has not seen its price in this league yet",
    "Последние предметы, цену которых вы проверяли. Они лежат только на этом компьютере. «Открыть» показывает цену снова без игры. Кнопки − и + задают, сколько таких предметов считать в сумме, 0 убирает из неё.": "The last items whose price you checked. They stay on this computer. «Open» shows the price again without the game. The − and + buttons set how many of an item count in the total; 0 leaves it out.",
    "Проверок пока нет": "No checks yet",
    "тогда {price}": "then {price}",
    "Очистить": "Clear",
    "нужен поиск": "needs a search",
    "Вышла новая версия {version}: обновить можно в разделе Divine или в меню значка": "A new version is out, {version}: update it on the Divine page or from the tray menu",
    "Вышла новая версия {version}, у вас {current}": "A new version is out, {version}; you have {current}",
    "Вышла Sakuya {version}: нажмите, чтобы обновить": "Sakuya {version} is out: click to update",
    "Вышла новая версия Sakuya {version}": "Sakuya {version} is out",
    "Обновить можно в разделе Divine или в меню значка в трее": "Update it on the Divine page or from the tray menu",
    "Обновить до {version}": "Update to {version}", "Что нового": "What's new", "Sakuya на GitHub": "Sakuya on GitHub",
    "Нашли ошибку или странный план крафта? Напишите, и мы починим": "Found a bug or an odd crafting plan? Tell us and we will fix it",
    "Сообщить о проблеме": "Report a problem",
    "Скачиваю новую версию: {percent}%": "Downloading the new version: {percent}%",
    "Открываю страницу новой версии: скачайте её оттуда": "Opening the new version's page: download it from there",
    "Не удалось обновить ({reason}). Открываю страницу новой версии, скачайте её вручную": "Could not update ({reason}). Opening the new version's page: download it by hand",
    "Sakuya обновлена до версии {version}": "Sakuya is updated to version {version}",
    "скачанный файл не совпал с опубликованным": "the downloaded file does not match the published one",
    "скачанный файл не программа": "the downloaded file is not a program",
    "Карты": "Maps",
    "Санктум": "Sanctum",
    "Выйти из программы": "Quit the program",
    "Скрыть": "Hide",
    "Лепестки": "Petals",
    "Оформление": "Appearance", "Программа перезапустится, открытый план крафта сбросится": "The program will restart, and an open crafting plan will be lost",
    "Не удалось перезапустить программу, оформление сменится при следующем запуске": "Could not restart the program; the look will change at the next start",
    "Оформление сменится при следующем запуске": "The appearance changes at the next start",
    "Какие моды учитывать": "Mods to search for", "Минимум значения мода": "Minimum mod value", 
    "{count} мин": "{count} min", "{count} ч": "{count} h", "{count} д": "{count} d",
    
    
    
    
    
    
    
    
    "Окно": "Window",
    "Поверх всех окон": "Always on top",
    "Язык": "Language",
    "Нужен Ctrl или Alt, либо клавиша F1-F24": "Ctrl or Alt is needed, or a key from F1 to F24",
    "{name} занято системой или самой программой": "{name} is used by the system or by this program",
    "Это сочетание уже назначено на другое действие": "These keys are already set for another action",
    "Клавиша изменена: {name}": "Hotkey changed: {name}",
    "Осталось примерно {left}  •  потрачено {spent}": "About {left} left  •  {spent} spent",
    "На предмете: {rarity}, {state}": "On the item: {rarity}, {state}",
    "Сделано, дальше": "Done, next",
    "Или выберите, что выпало:": "Or choose what you got:",
    "Сделает обычный предмет волшебным и добавит 1 случайный мод.": "Makes a normal item magic and adds 1 random mod.",
    "Добавит волшебному предмету второй случайный мод.": "Adds a second random mod to a magic item.",
    "Сделает предмет редким с 4 случайными модами. Старые моды пропадут.": "Makes the item rare with 4 random mods. Old mods are lost.",
    "Сделает предмет редким и добавит 1 случайный мод.": "Makes the item rare and adds 1 random mod.",
    "Сделает предмет редким и гарантированно добавит нужный мод.": "Makes the item rare and guarantees a mod you need.",
    "Добавит 1 случайный мод.": "Adds 1 random mod.",
    "Добавит 2 случайных мода.": "Adds 2 random mods.",
    "Уберёт 1 случайный мод и добавит новый.": "Removes 1 random mod and adds a new one.",
    "Уберёт 1 случайный мод.": "Removes 1 random mod.",
    "Уберёт 2 случайных мода.": "Removes 2 random mods.",
    "Навсегда закрепит 1 случайный мод: его больше нельзя будет убрать.": "Locks 1 random mod forever: it can no longer be removed.",
    "Только префиксы.": "Prefixes only.", "Только суффиксы.": "Suffixes only.",
    "Новые моды будут уровня {level}+.": "New mods will be level {level}+.",
    "Закреплённый мод не тронет.": "The fractured mod stays untouched.",
    "Выгоднее заменить предмет, чем чинить этот.": "Replacing the item is cheaper than fixing this one.",
    "Как выйдет дешевле": "How to make it cheaper",
    "Ищу варианты дешевле...": "Looking for cheaper options...",
    "Заметно дешевле варианта нет": "No noticeably cheaper option",
    "{title}: T{old} → T{new}": "{title}: T{old} → T{new}",
    "Без мода: {title}": "Without: {title}",
    "Взять": "Use",
    "Инструменты": "Tools", "Закладки": "Bookmarks", "Журнал сделок": "Deal journal", "Оборот биржи": "Exchange", "Справочник": "Reference", "Путевые камни": "Waystones", "Секундомер": "Timer",
    "Сохраняйте поиски звёздочкой в окне цены. Закладка открывает тот же поиск на сайте торговли.": "Save searches with the star in the price window. A bookmark opens the same search on the trade site.",
    "Закладок пока нет": "No bookmarks yet", "открыть": "open", "удалить": "delete",
    "Куплено за": "Bought for", "Продано за": "Sold for", "Добавить": "Add", "продал": "sold",
    "Записывается только то, что вы ввели сами. Программа не читает игру и ваши сделки.": "Only what you type is recorded. The program does not read the game or your trades.",
    "Прибыль: {profit}  •  закрыто сделок: {closed}": "Profit: {profit}  •  closed deals: {closed}",
    "вложено в открытые: {value}": "tied up in open deals: {value}",
    "Сделок пока нет": "No deals yet",
    "Нужны название и цена покупки числом": "A name and a numeric purchase price are needed",
    "Курсы ещё не загружены, подождите": "Rates are not loaded yet, please wait",
    "Впишите цену продажи в поле «Продано за» и нажмите «продал» ещё раз": "Type the sale price into «Sold for» and press «sold» again",
    "Показать оборот": "Show turnover",
    "Что больше всего меняли за прошлый час на официальной бирже, в пересчёте на Exalted. Это показывает спрос, а не прибыль: выгодный обмен по этим данным найти нельзя, средние цены там слишком разбросаны.": "What was exchanged most in the last hour on the official exchange, converted to Exalted. This shows demand, not profit: these data cannot find a profitable exchange, their average prices are too scattered.",
    "Новые курсы появятся в начале следующего часа": "New data appears at the start of the next hour",
    "Загружаю...": "Loading...",
    "Нажмите кнопку: программа один раз скачает файл биржи.": "Press the button: the program downloads the exchange file once.",
    "Файл биржи за {time}": "Exchange file for {time}",
    "В этой лиге за час не было сделок": "No trades in this league during the hour",
    "Оборот, час": "Traded, hour", "Чаще платят": "Mostly paid in",
    "Не удалось загрузить курсы": "Could not load the exchange data",
    "Названия товаров ещё не загружены, попробуйте позже": "Item names are not loaded yet, try again later",
    "Показать": "Show",
    "Шанс показан для пустой стороны предмета. Занятые группы модов его меняют, точный расчёт делает вкладка «Крафт».": "The chance is for an empty side of the item. Mod groups already taken change it; the Craft tab does the exact calculation.",
    "Выберите базу: покажу все её моды, уровни, веса и шансы, эссенции и знамения.": "Pick a base to see all its mods, levels, weights and chances, essences and omens.",
    "Для этой базы нет модов": "This base has no mods",
    "ур. {level}": "lvl {level}", "префикс": "prefix", "суффикс": "suffix", "Эссенции": "Essences", "Знамения": "Omens",
    "Действует на: {orb}.": "Works with: {orb}.", "Сразу 2 мода.": "2 mods at once.",
    "Список модов путевых камней ещё не загружен": "The Waystone mod list is not loaded yet",
    "Строка для поиска": "Search line", "Скопировать": "Copy", "Сбросить список": "Reset the list",
    "Нажмите на мод, чтобы отметить его опасным. Строка в поиске тайника скрывает камни с такими модами, а окно цены предупредит о них. Синтаксис поиска взят из гайдов: проверьте на паре камней.": "Click a mod to mark it dangerous. The line in the stash search hides Waystones with such mods, and the price window warns about them. The search syntax comes from guides: try it on a couple of Waystones.",
    "Скопировано: вставьте в поиск тайника в игре": "Copied: paste it into the stash search in the game",
    "Длина строки: {length} из {limit}": "Line length: {length} of {limit}",
    "Длина строки {length}: игра может не принять больше {limit}, уберите часть модов": "Line length {length}: the game may not accept more than {limit}, remove some mods",
    "Модов без короткого слова для поиска: {count}, их строка не скроет": "Mods with no short search word: {count}, the line will not hide them",
    "Новая карта": "New map", "Сбросить": "Reset", "Пауза": "Pause", "Старт": "Start",
    "Секундомер ручной: программа не читает игру, поэтому карты отмечаете вы.": "The timer is manual: the program does not read the game, so you mark the maps.",
    "В среднем {time} за карту": "{time} per map on average",
    "Пройденные карты появятся здесь": "Finished maps will appear here",
    "Карта {number}": "Map {number}",
    "★ В закладки": "★ Bookmark", "★ В закладках": "★ Bookmarked",
    "Опасные моды: {count}": "Dangerous mods: {count}",
    "Опасных модов из вашего списка нет": "No dangerous mods from your list",
    "Искать цену": "Search for a price",
    "Проверяю план прогонами...": "Testing the plan with trial runs...",
    "Проверка, {runs} прогонов: половина дешевле {median}, 9 из 10 не дороже {unlucky}, 1 из 100 дороже {worst}": "Check, {runs} runs: half cost less than {median}, 9 of 10 at most {unlucky}, 1 of 100 more than {worst}",
    "Скопировать рецепт": "Copy the recipe",
    "Рецепт скопирован": "Recipe copied",
    "Цель:": "Goal:",
    "В среднем с начала: {cost}": "On average from the start: {cost}",
    "Дальше примерно так:": "Roughly what comes next:",
    
    
    
    
    
    
    
    "Без учёта: {mods}": "Not counted: {mods}",
    
    "Какие моды учитывать, как в прошлый раз": "Mods to count, as last time",
    "Без каких сфер": "Which orbs to skip", "Без каких сфер ({count})": "Which orbs to skip ({count})",
    "Нажмите на то, чего у вас нет или что не хотите тратить: план обойдётся без этого.": "Click what you do not have or do not want to spend: the plan will do without it.",
    "С такими сферами цель недостижима: разрешите больше сфер или новую базу": "The goal cannot be reached with these orbs: allow more orbs or a new base",
    "Мой бюджет, Divine": "My budget, Divine",
    "Шанс уложиться с начала крафта: {chance}.": "Chance to fit from the start of the craft: {chance}.",
    "Режим «{mode}» уложится чаще: {chance}.": "The «{mode}» mode fits more often: {chance}.",
    "В среднем на эти деньги выйдет: {goal}.": "On average this money gets you: {goal}.",
    "9 из 10 до {cost}": "9 of 10 up to {cost}", "надёжнее": "safer",
    "только через кость Бездны": "only through an Abyssal bone",
    "Очернить предмет можно только раз: выберите один очернённый мод": "An item can be desecrated only once: pick one desecrated mod",
    "Для очернённого мода нужна кость Бездны, а её цены нет или она запрещена": "A desecrated mod needs an Abyssal bone, but it has no price or is forbidden",
    "Сначала раскройте очернённый мод, потом скопируйте предмет ещё раз": "Reveal the desecrated mod first, then copy the item again",
    "уже очернён": "already desecrated",
    "Добавит скрытый мод. Раскройте его и выберите лучший из вариантов.": "Adds a hidden mod. Reveal it and pick the best of the options.",
    "При раскрытии можно один раз перебросить варианты.": "The options can be rerolled once at the reveal.",
    "Уберёт только очернённый мод, после этого предмет можно очернить снова.": "Removes only the desecrated mod, so the item can be desecrated again.",
    "Сфера отмены уберёт только очернённый мод.": "An Orb of Annulment removes only the desecrated mod.",
    "кости Бездны": "Abyssal bones",
    "Раскройте мод у Колодца душ и выберите нужный из вариантов": "Reveal the mod at the Well of Souls and pick the one you need",
    "План использует кость Бездны, поэтому шансы здесь грубые: вес очернённых модов взят из замера POE2_HTC по 40 костям, а 3 варианта при раскрытии не подтверждены poe2db.": "This plan uses an Abyssal bone, so its odds are rough: the weight of desecrated mods comes from a POE2_HTC measurement over 40 bones, and 3 options at a reveal are not confirmed by poe2db.",
    "Очернённые моды": "Desecrated mods",
    
    "Что-то пошло не так, подробности в errors.log": "Something went wrong, see errors.log",
    "Не удалось рассчитать план, подробности в errors.log": "Could not work out the plan, see errors.log",
    "Не удалось сохранить настройки": "Could not save the settings",
    "Не удалось сохранить данные вкладки «Инструменты»": "Could not save the Tools tab's data",
}


def t(text: str) -> str:
    return ENGLISH.get(text, text) if language == "en" else text


def set_language(code: str) -> None:
    global language
    language = code
RARITY_NAMES = {"normal": "обычный", "magic": "волшебный", "rare": "редкий"}
currency_names: dict[str, str] = {}


currency_keys: dict[str, str] = {}


def russian_currency_name(name: str) -> str:
    return currency_names.get(name) or currency_keys.get(name_key(name), name)


class TierChoice:
    """The tier a row asks for. Its drop-down exists only while the row is selected: a widget for each of the many rows is what used to make the list slow."""

    def __init__(self, values: list[str]):
        self.values = values
        self.index = 0
        self.box = None
        self.item = None
        self.canvas = None

    def __getitem__(self, key: str):
        return self.values

    def get(self) -> str:
        return self.values[self.index]

    def current(self, index: int | None = None) -> int:
        if index is not None:
            self.index = index
            if self.box:
                self.box.current(index)
        return self.index

    def show(self, canvas: tk.Canvas, right: int, middle: int, owner) -> None:
        if self.box:
            canvas.coords(self.item, right, middle)
            return
        self.canvas = canvas
        self.box = ttk.Combobox(canvas, values=self.values, width=12, state="readonly", font=(FONT, 9))
        self.box.current(self.index)
        self.box.bind("<<ComboboxSelected>>", lambda _: setattr(self, "index", self.box.current()))
        self.box.bind("<MouseWheel>", lambda _: "break")  # scrolling down the list must not change a tier in passing
        self.item = canvas.create_window(right, middle, window=self.box, anchor="e")

    def forget(self, canvas: tk.Canvas | None = None) -> None:
        if self.box:
            self.box.destroy()
            self.box = None
            self.item = None


GOAL_CODE = re.compile(r"sakuya:([A-Za-z0-9_-]{8,4000})")


def goal_code(goal: dict) -> str:
    """A goal as one line of text to paste in a chat: the base, item level, mods with tiers, the group and the free places. Squeezed and in base64, so it stays short."""
    opened = goal.get("open", {})
    packed = [goal["base"], goal["ilvl"], [[mod["template"], mod["side"], mod["desecrated"], mod.get("rune", ""), mod["tier"], bool(mod.get("pool"))] for mod in goal["mods"]],
              goal.get("need", 0), [opened.get("prefix", 0), opened.get("suffix", 0)]]
    data = zlib.compress(json.dumps(packed, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9)
    return "sakuya:" + base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def read_goal_code(text: str) -> dict | None:
    """The goal in a pasted line, or None. Whatever came in is checked as a saved goal would be; a code that grows too big when unpacked is refused."""
    found = GOAL_CODE.search(text or "")
    if not found:
        return None
    try:
        raw = found.group(1) + "=" * (-len(found.group(1)) % 4)
        unpacker = zlib.decompressobj()
        unpacked = unpacker.decompress(base64.urlsafe_b64decode(raw), 200_000)
        if unpacker.unconsumed_tail:
            return None
        base, ilvl, mods, need, opened = json.loads(unpacked.decode("utf-8"))
        goal = {"base": base, "ilvl": ilvl, "label": "", "need": need, "open": {side: count for side, count in zip(("prefix", "suffix"), opened) if count},
                "mods": [{"template": template, "side": side, "desecrated": desecrated, "rune": rune, "tier": tier, **({"pool": True} if pool else {})}
                         for template, side, desecrated, rune, tier, pool in mods]}
    except (ValueError, TypeError, zlib.error, UnicodeDecodeError):
        return None
    return goal if is_craft_goal(goal) else None


def goal_key(ladder: "Ladder") -> dict:
    """What finds a mod again, whatever the language: its wording in English, its side, whether only a Desecration brings it, and which rune it needs."""
    return {"template": ladder.template, "side": ladder.side, "desecrated": all(mod.desecrated for mod in ladder.mods), "rune": ladder.mods[0].rune}


# Ready goals from crafting guides: (name, the item pages it is for, the mods as (words in the English wording, best tier asked for)).
# A preset fits a base only if every one of its mods can roll there, so the defence presets sort themselves by base type.
ARMOUR_PAGES = ("Body_Armours", "Helmets", "Gloves", "Boots", "Shields", "Bucklers")
MARTIAL_PAGES = ("Bows", "Crossbows", "Spears", "One_Hand_Maces", "Two_Hand_Maces", "Quarterstaves", "One_Hand_Swords", "Two_Hand_Swords", "One_Hand_Axes", "Two_Hand_Axes",
                 "Flails", "Claws", "Daggers", "Talismans")
CRAFT_PRESETS = (
    ("Энергощит", ARMOUR_PAGES, (("#% increased energy shield", 2), ("+# to maximum energy shield", 2), ("+#% to fire resistance", 2), ("+#% to cold resistance", 2))),
    ("Энергощит + здоровье", ARMOUR_PAGES,
     (("#% increased energy shield", 2), ("+# to maximum energy shield", 2), ("+# to maximum life", 2), ("+#% to fire resistance", 2), ("+#% to cold resistance", 2))),
    ("Уклонение", ARMOUR_PAGES,
     (("#% increased evasion rating", 2), ("+# to evasion rating", 2), ("+# to maximum life", 2), ("+#% to fire resistance", 2), ("+#% to cold resistance", 2))),
    ("Броня", ARMOUR_PAGES, (("#% increased armour", 2), ("+# to armour", 2), ("+# to maximum life", 2), ("+#% to fire resistance", 2), ("+#% to cold resistance", 2))),
    ("Броня + уклонение", ARMOUR_PAGES, (("#% increased armour and evasion", 2), ("+# to maximum life", 2), ("+#% to fire resistance", 2), ("+#% to cold resistance", 2))),
    ("Броня + энергощит", ARMOUR_PAGES, (("#% increased armour and energy shield", 2), ("+# to maximum life", 2), ("+#% to fire resistance", 2), ("+#% to cold resistance", 2))),
    ("Уклонение + энергощит", ARMOUR_PAGES, (("#% increased evasion and energy shield", 2), ("+# to maximum life", 2), ("+#% to fire resistance", 2), ("+#% to cold resistance", 2))),
    ("Здоровье и сопротивления", (*ARMOUR_PAGES, "Rings", "Amulets", "Belts"),
     (("+# to maximum life", 2), ("+#% to fire resistance", 2), ("+#% to cold resistance", 2), ("+#% to lightning resistance", 2))),
    ("Сопротивления + хаос", (*ARMOUR_PAGES, "Rings", "Amulets", "Belts"),
     (("+# to maximum life", 2), ("+#% to fire resistance", 2), ("+#% to cold resistance", 2), ("+#% to chaos resistance", 2))),
    # Guides ask 30% and more of boots, with life and all three resistances.
    ("Скорость передвижения", ("Boots",),
     (("#% increased movement speed", 1), ("+# to maximum life", 2), ("+#% to fire resistance", 2), ("+#% to cold resistance", 2), ("+#% to lightning resistance", 2))),
    ("Дух", ("Body_Armours",), (("+# to spirit", 1), ("+# to maximum life", 2), ("+#% to fire resistance", 2), ("+#% to cold resistance", 2), ("+#% to lightning resistance", 2))),
    ("Блок", ("Shields", "Bucklers"), (("#% increased block chance", 1), ("+# to maximum life", 2), ("+#% to fire resistance", 2), ("+#% to cold resistance", 2))),
    ("Пояс на броню", ("Belts",), (("+# to maximum life", 2), ("+# to armour", 2), ("+#% to fire resistance", 2), ("+#% to cold resistance", 2), ("+#% to lightning resistance", 2))),
    ("Перчатки на атаку", ("Gloves",),
     (("adds # to # physical damage to attacks", 1), ("#% increased attack speed", 2), ("#% increased critical damage bonus", 2), ("+# to maximum life", 2))),
    ("Перчатки на скорость атаки", ("Gloves",), (("#% increased attack speed", 2), ("+# to maximum life", 2), ("+#% to fire resistance", 2), ("+#% to cold resistance", 2))),
    ("Физический урон", MARTIAL_PAGES,
     (("#% increased physical damage", 1), ("adds # to # physical damage", 1), ("#% increased attack speed", 2), ("+#% to critical hit chance", 2))),
    ("Стихийный урон", MARTIAL_PAGES,
     (("adds # to # lightning damage", 2), ("adds # to # cold damage", 2), ("adds # to # fire damage", 2), ("#% increased attack speed", 2))),
    ("Ближний бой", MARTIAL_PAGES,
     (("#% increased physical damage", 1), ("adds # to # physical damage", 1), ("#% increased attack speed", 2), ("+# to level of all melee skills", 1))),
    ("Лук", ("Bows",),
     (("#% increased physical damage", 1), ("adds # to # physical damage", 1), ("#% increased attack speed", 2), ("+# to level of all projectile skills", 1),
      ("+#% surpassing chance to fire an additional arrow", 2))),
    ("Арбалет", ("Crossbows",),
     (("#% increased physical damage", 1), ("adds # to # physical damage", 1), ("+# to level of all projectile skills", 1), ("loads # additional bolts", 1))),
    ("Чары", ("Wands", "Staves", "Foci"),
     (("#% increased spell damage", 2), ("#% increased cast speed", 2), ("+# to level of all spell skills", 1))),
    ("Чары холода", ("Wands", "Staves"),
     (("#% increased spell damage", 2), ("#% increased cold damage", 2), ("+# to level of all cold spell skills", 1), ("#% increased cast speed", 2))),
    ("Чары огня", ("Wands", "Staves"),
     (("#% increased spell damage", 2), ("#% increased fire damage", 2), ("+# to level of all fire spell skills", 1), ("#% increased cast speed", 2))),
    ("Чары молнии", ("Wands", "Staves"),
     (("#% increased spell damage", 2), ("#% increased lightning damage", 2), ("+# to level of all lightning spell skills", 1), ("#% increased cast speed", 2))),
    ("Фокус на энергощит", ("Foci",),
     (("#% increased energy shield", 2), ("+# to maximum energy shield", 2), ("+# to level of all spell skills", 1), ("#% increased cast speed", 2))),
    ("Миньоны", ("Sceptres",), (("+# to level of all minion skills", 1), ("allies in your presence deal #% increased damage", 2), ("#% increased spirit", 2))),
    ("Шлем на миньонов", ("Helmets",), (("+# to level of all minion skills", 1), ("#% increased energy shield", 2), ("+# to maximum energy shield", 2), ("+# to maximum life", 2))),
    ("Кольцо атаки", ("Rings",),
     (("adds # to # physical damage to attacks", 1), ("adds # to # cold damage to attacks", 1), ("adds # to # lightning damage to attacks", 2), ("+#% to fire resistance", 2), ("+#% to lightning resistance", 2))),
    # Rings with more room for prefixes, such as Dusk and Penumbra, take a flat damage for every element.
    ("Кольцо на 4 флэта", ("Rings",),
     (("adds # to # physical damage to attacks", 2), ("adds # to # fire damage to attacks", 2), ("adds # to # cold damage to attacks", 2), ("adds # to # lightning damage to attacks", 2),
      ("+#% to fire resistance", 2))),
    ("Амулет на чары", ("Amulets",),
     (("+# to level of all spell skills", 1), ("+# to spirit", 2), ("#% increased cast speed", 2), ("+# to maximum energy shield", 2))),
    ("Амулет на ближний бой", ("Amulets",),
     (("+# to level of all melee skills", 1), ("#% increased critical hit chance", 2), ("#% increased critical damage bonus", 2), ("+# to maximum life", 2))),
    ("Амулет на снаряды", ("Amulets",),
     (("+# to level of all projectile skills", 1), ("#% increased critical hit chance", 2), ("#% increased critical damage bonus", 2), ("+# to maximum life", 2))),
    ("Амулет на миньонов", ("Amulets",), (("+# to level of all minion skills", 1), ("+# to spirit", 2), ("+# to maximum life", 2), ("+#% to fire resistance", 2))),
    ("Колчан", ("Quivers",),
     (("+# to level of all projectile skills", 1), ("#% increased attack speed", 2), ("adds # to # physical damage to attacks", 2), ("#% increased critical hit chance for attacks", 2))),
    ("Колчан на стрелу", ("Quivers",), (("+#% surpassing chance to fire an additional arrow", 1), ("+# to level of all projectile skills", 1), ("#% increased attack speed", 2))),
)


def preset_goal(page: "Page", ilvl: int, mods: tuple, base: str = "") -> dict | None:
    """The preset as a goal on this page, each mod found by its whole English wording. None if one of them cannot roll here,
    or if the base has no room for them, so a preset shows only where it fits."""
    chosen = []
    for wording, tier in mods:
        options = [ladder for ladder in page.ladders if ladder.template.casefold() == wording and ladder.available(ilvl) and not all(mod.desecrated or mod.rune for mod in ladder.mods)]
        if not options:
            return None
        ladder = max(options, key=lambda ladder: len(ladder.available(ilvl)))
        chosen.append({**goal_key(ladder), "tier": min(tier, len(ladder.available(ilvl)))})
    limits = affix_limits(base)
    if any(sum(mod["side"] == side for mod in chosen) > limits[side] for side in limits):
        return None
    return {"mods": chosen}


# The kinds of item the base list is split into, by the page a base belongs to.
BASE_GROUPS = (("Body_Armours", "Нательная броня"), ("Helmets", "Шлемы"), ("Gloves", "Перчатки"), ("Boots", "Сапоги"), ("Shields", "Щиты"), ("Bucklers", "Баклеры"), ("Foci", "Фокусы"), ("Quivers", "Колчаны"), ("Rings", "Кольца"), ("Amulets", "Амулеты"), ("Belts", "Пояса"), ("Bows", "Луки"), ("Crossbows", "Арбалеты"), ("Spears", "Копья"), ("Quarterstaves", "Боевые посохи"), ("Staves", "Посохи"), ("Wands", "Жезлы"), ("Sceptres", "Скипетры"), ("One_Hand_Maces", "Одноручные булавы"), ("Two_Hand_Maces", "Двуручные булавы"), ("One_Hand_Swords", "Одноручные мечи"), ("Two_Hand_Swords", "Двуручные мечи"), ("One_Hand_Axes", "Одноручные топоры"), ("Two_Hand_Axes", "Двуручные топоры"), ("Flails", "Цепы"), ("Claws", "Когти"), ("Daggers", "Кинжалы"), ("Talismans", "Талисманы"), ("Traps", "Ловушки"))


def base_group(page_name: str) -> str:
    return next((label for prefix, label in BASE_GROUPS if page_name.startswith(prefix)), page_name)


def grouped_bases(matches: list[str], page_of) -> list[str | None]:
    """The rows of the base list: None for a kind's heading, in the order its best match came, then that kind's bases."""
    groups: dict[str, list[str]] = {}
    for base in matches:
        groups.setdefault(base_group(page_of(base)), []).append(base)
    return [row for bases in groups.values() for row in (None, *bases)]


def ladder_of_line(page: "Page", label: str) -> "Ladder | None":
    """The tiers a mod line on an item belongs to, as either client writes it."""
    wording = normalize_stat(label.split(" / ")[0])
    for ladder in page.ladders:
        for mod in ladder.mods:
            if wording in (normalize_stat(RANGE.sub("#", text.split(" / ")[0])) for text in (mod.text, mod.ru_text) if text):
                return ladder
    return None


def next_tier_hint(page: "Page", label: str, tier: int, ilvl: int) -> str | None:
    """What the tier above gives, and the item level if this item does not reach it."""
    ladder = ladder_of_line(page, label)
    if not ladder or not 2 <= tier <= len(ladder.mods):
        return None
    better = ladder.mods[tier - 2]
    ranges = RANGE.findall(better.text)
    rolls = ranges[0].strip("()") if ranges else better.text[:12]
    return f"▲ {rolls}" if better.level <= ilvl else t("▲ {rolls}, нужен ур. {level}").format(rolls=rolls, level=better.level)


def upgrade_goal(page: "Page", mods: list, ilvl: int, base: str = "") -> "tuple[list[Want], str] | None":
    """The weakest mod that can go one tier up, kept with the two best others. More would take long to work out for a question asked in passing."""
    known = [(ladder, mod.tier) for ladder, mod in ((ladder_of_line(page, mod.label), mod) for mod in mods if mod.tier) if ladder and mod.tier <= len(ladder.mods)]
    can_rise = [(ladder, tier) for ladder, tier in known if tier >= 2 and ladder.mods[tier - 2].level <= ilvl]
    if not can_rise:
        return None
    weakest, tier = max(can_rise, key=lambda entry: entry[1])
    try:
        wants = [make_want(weakest, tier - 1, ilvl)]
        for ladder, kept in sorted(known, key=lambda entry: entry[1]):
            if ladder is not weakest and len(wants) <= UPGRADE_OTHERS_KEPT and not any(ladder.groups & want.ladder.groups for want in wants) and sum(want.side == ladder.side for want in wants) < affix_limits(base)[ladder.side]:
                wants.append(make_want(ladder, kept, ilvl))
    except ValueError:  # the item says a tier this item level should not have
        return None
    return wants, weakest.title


def poe2db_link(name: str, language_code: str) -> str:
    return (POE2DB_RU_URL if language_code == "ru" else POE2DB_URL) + urllib.parse.quote(name.replace("'", "").replace(" ", "_"))


def finishing_hints(page_name: str, wants: "list[Want]", prices: dict[str, float], base: str = "") -> list[tuple[str, str]]:
    """What can still help outside the plan: its results depend on what the item has by then, or only raise values, so these are advice and not steps."""
    hints = []
    # The Essence of the Breach raises the cap by 20% on a ring or amulet: a Breach Ring takes 60% this way, and an amulet's +3 to skills 34% for +4.
    if (base in QUALITY_CAP_BY_BASE or page_name == "Amulets") and prices.get(OMEN_OF_WHITTLING, 0) > 0:
        hints.append(("Essence of the Breach", "quality_cap"))
    texts = [mod_text for want in wants for mod_text in [next(iter(want.qualifying)).text]]
    elements = {found.group(1) for found in (re.fullmatch(r"\+[^ ]*% to (Fire|Cold|Lightning|Chaos) Resistance", text) for text in texts) if found}
    if len(elements) == 1:
        element = next(iter(elements))
        hints.append((RESISTANCE_FLUXES[element], "flux"))
    if page_name in ("Rings", "Amulets"):
        hints += [(name, "catalyst") for name, words in CATALYSTS if any(re.search(words, text) for text in texts)]
    hints += [(name, "quality") for name, pages in QUALITY_ITEMS if page_name.startswith(pages)]
    return [(name, kind) for name, kind in hints if prices.get(name, 0) > 0][:FINISHING_HINTS_SHOWN]


def exchange_good_key(item) -> str | None:
    """The name of a good the exchange deals in, as the game wrote it in either language, whether or not it has a price right now."""
    known = {name_key(shown): key for key, shown in currency_keys.items()} | {key: key for key in currency_keys}
    for line in reversed(item.lines):
        for candidate in ([f"{line} (Level {item.level})", f"{line} (уровень {item.level})", line] if item.level else [line]):
            found = known.get(name_key(candidate))
            if found:
                return found
    return None


def show_currency(name: str) -> str:
    if name == NEW_BASE:
        return t(NEW_BASE)
    if language == "en":
        return name
    variant = ITEM_VARIANT.search(name)
    if variant:
        return f"{show_currency(plain_item_name(name))} ({VARIANT_WORDS[variant.group(1)]})"
    return currency_names.get(name) or currency_keys.get(name_key(name), name)


# slug: (name, family, minimum modifier level)
CURRENCIES = {
    "new_base": (NEW_BASE, "new_base", 0),
    "essence": ("", "essence", 0),  # the item name comes from Action.essence
    "perfect_essence": ("", "perfect_essence", 0),
    "desecrate": ("", "desecrate", 0),  # so does the bone's
    "ancient_desecrate": ("", "desecrate", 40),
    "fracture": ("Fracturing Orb", "fracture", 0),
    "lock": ("Hinekora's Lock", "lock", 0),
    "transmutation": ("Orb of Transmutation", "transmutation", 0),
    "greater_transmutation": ("Greater Orb of Transmutation", "transmutation", 44),
    "perfect_transmutation": ("Perfect Orb of Transmutation", "transmutation", 70),
    "augmentation": ("Orb of Augmentation", "augmentation", 0),
    "greater_augmentation": ("Greater Orb of Augmentation", "augmentation", 44),
    "perfect_augmentation": ("Perfect Orb of Augmentation", "augmentation", 70),
    "alchemy": ("Orb of Alchemy", "alchemy", 0),
    "regal": ("Regal Orb", "regal", 0),
    "greater_regal": ("Greater Regal Orb", "regal", 35),
    "perfect_regal": ("Perfect Regal Orb", "regal", 50),
    "exalted": ("Exalted Orb", "exalted", 0),
    "greater_exalted": ("Greater Exalted Orb", "exalted", 35),
    "perfect_exalted": ("Perfect Exalted Orb", "exalted", 50),
    "chaos": ("Chaos Orb", "chaos", 0),
    "greater_chaos": ("Greater Chaos Orb", "chaos", 35),
    "perfect_chaos": ("Perfect Chaos Orb", "chaos", 50),
    "annulment": ("Orb of Annulment", "annulment", 0),
}
# name: (family, side, mods added or removed)
OMENS = {
    "Omen of Sinistral Alchemy": ("alchemy", "prefix", 1),
    "Omen of Dextral Alchemy": ("alchemy", "suffix", 1),
    "Omen of Sinistral Coronation": ("regal", "prefix", 1),
    "Omen of Dextral Coronation": ("regal", "suffix", 1),
    "Omen of Sinistral Exaltation": ("exalted", "prefix", 1),
    "Omen of Dextral Exaltation": ("exalted", "suffix", 1),
    "Omen of Greater Exaltation": ("exalted", None, 2),
    "Omen of Sinistral Erasure": ("chaos", "prefix", 1),
    "Omen of Dextral Erasure": ("chaos", "suffix", 1),
    "Omen of Sinistral Annulment": ("annulment", "prefix", 1),
    "Omen of Dextral Annulment": ("annulment", "suffix", 1),
    "Omen of Greater Annulment": ("annulment", None, 2),
    "Omen of Light": ("annulment", None, 1),
    "Omen of Sinistral Necromancy": ("desecrate", "prefix", 1),
    "Omen of Dextral Necromancy": ("desecrate", "suffix", 1),
    "Omen of Abyssal Echoes": ("desecrate", None, 1),
    "Omen of the Sovereign": ("desecrate", None, 1),
    "Omen of the Liege": ("desecrate", None, 1),
    "Omen of the Blackblooded": ("desecrate", None, 1),
    "Omen of Whittling": ("chaos", None, 1),
    "Omen of Sinistral Crystallisation": ("perfect_essence", "prefix", 1),
    "Omen of Dextral Crystallisation": ("perfect_essence", "suffix", 1),
}
OMEN_OF_LIGHT, OMEN_OF_ECHOES, OMEN_OF_WHITTLING = "Omen of Light", "Omen of Abyssal Echoes", "Omen of Whittling"
# Each makes the next Desecration of a weapon or jewellery offer one mod of its lich. Every desecrated mod carries its lich's name, as in "Ulaman's" or "of Kurgal".
LICH_OMENS = {"Omen of the Sovereign": "Ulaman", "Omen of the Liege": "Amanamu", "Omen of the Blackblooded": "Kurgal"}
LICH_SHOWN = {"Ulaman": "Уламана", "Amanamu": "Аманаму", "Kurgal": "Кургала"}  # as in "a mod of Ulaman"
# Under this omen the next Exalted Orb uses up all catalyst quality to raise the chance of mods with the catalyst's tag. It is not in OMENS: without quality it does nothing.
CATALYSING_OMEN = "Omen of Catalysing Exaltation"
# Which of poe2db's crafting tags each jewellery catalyst's quality favours.
CATALYST_TAGS = {"Flesh Catalyst": ("life",), "Neural Catalyst": ("mana",), "Carapace Catalyst": ("armour", "evasion", "energy_shield", "defences"),
                 "Uul-Netol's Catalyst": ("physical",), "Xoph's Catalyst": ("fire",), "Tul's Catalyst": ("cold",), "Esh's Catalyst": ("lightning",),
                 "Chayula's Catalyst": ("chaos",), "Reaver Catalyst": ("attack",), "Sibilant Catalyst": ("caster",), "Skittering Catalyst": ("speed",),
                 "Adaptive Catalyst": ("attribute",), "Necrotic Catalyst": ("minion",)}
CATALYST_PAGES = frozenset({"Rings", "Amulets"})
QUALITY_CAP = 20
QUALITY_CAP_BY_BASE = {"Breach Ring": 40, "Refined Breach Ring": 45}  # their own mods give +20% and +25% to maximum quality
# These rings and amulets trade room on one side for the other, by their own mod, as in "+2 Prefix Modifiers allowed, -2 Suffix Modifiers allowed".
# The game data names the mod with a number but not the counts, so they are written here, checked against the mods' stats in RePoE.
AFFIX_LIMITS_BY_BASE = {
    "Dusk Ring": (4, 2), "Dusk Amulet": (4, 2), "Gloam Ring": (2, 4), "Gloam Amulet": (2, 4),
    "Penumbra Ring": (5, 1), "Penumbra Amulet": (5, 1), "Tenebrous Ring": (1, 5), "Tenebrous Amulet": (1, 5),
    "Twisted Amulet": (2, 3), "Lament Amulet": (2, 3), "Distorted Amulet": (3, 2), "Portent Amulet": (3, 2), "Absent Amulet": (2, 2),
}


def affix_limits(base: str = "") -> dict[str, int]:
    """How many prefixes and suffixes a rare item of this base takes."""
    prefixes, suffixes = AFFIX_LIMITS_BY_BASE.get(base, (MAX_PER_SIDE["rare"], MAX_PER_SIDE["rare"]))
    return {"prefix": prefixes, "suffix": suffixes}


CATALYSTS_PER_QUALITY = 57 / 60  # a catalyst gives 1 to 2%, and players count 55 to 59 of them for 60%
QUALITY_CAP_MOD = "+20% to Maximum Quality"  # the Essence of the Breach's mod: with it a Breach Ring takes 60%
ESSENCE_QUALITY_CAP = 20
# How much the omen multiplies the weight of matching mods at a given quality. The PoE2 wiki gives these two points; between and past them is a straight line,
# so a plan that uses it is marked as rough.
CATALYST_BOOST = ((0, 1.0), (20, 5.0), (40, 7.5))


def catalyst_boost(quality: float) -> float:
    for (low, low_boost), (high, high_boost) in zip(CATALYST_BOOST, CATALYST_BOOST[1:]):
        if quality <= high:
            return low_boost + (high_boost - low_boost) * (max(quality, low) - low) / (high - low)
    (low, low_boost), (high, high_boost) = CATALYST_BOOST[-2:]
    return high_boost + (high_boost - low_boost) * (quality - high) / (high - low)


def catalysts_needed(quality: float) -> int:
    return math.ceil(quality * CATALYSTS_PER_QUALITY)
# Which bone fits which item, from each bone's description on poe2db: weapons and quivers, armour, jewellery.
COLLARBONE_PAGES = frozenset({"Amulets", "Rings", "Belts"})
def lich_of(mod: "Mod") -> str | None:
    return next((lich for lich in LICH_OMENS.values() if lich in mod.name), None) if mod.desecrated else None


JAWBONE_PAGES = frozenset({"Claws", "Daggers", "Wands", "One_Hand_Swords", "One_Hand_Axes", "One_Hand_Maces", "Sceptres", "Spears", "Flails", "Bows", "Staves", "Two_Hand_Swords", "Two_Hand_Axes", "Two_Hand_Maces", "Quarterstaves", "Crossbows", "Traps", "Talismans", "Quivers"})
# The lich omens name weapons and jewellery: a quiver is neither, and a belt is not counted as jewellery here, to be safe.
LICH_OMEN_PAGES = (JAWBONE_PAGES | {"Amulets", "Rings"}) - {"Quivers"}
GNAWED_BONE_MAX_ILVL = 64
# poe2db gives no real weight for desecrated mods. This one was measured by POE2_HTC over 40 bones on one base, so it is an estimate.
DESECRATED_WEIGHT = 2500
DESECRATE_OPTIONS = 3  # how many mods a reveal offers; poe2db does not state it, so plans that use it are marked as rough
DESECRATE_STATE_LIMIT = 4000  # states without bones, which multiply them by about ten: six mods at top tiers come to about 3000 and still keep bones, as mirror crafts use them


@dataclass(frozen=True)
class Action:
    currency: str
    omens: tuple[str, ...] = ()
    essence: str = ""
    catalyst: str = ""  # an Exalted Orb under the Catalysing omen, after this many of the catalyst have filled the quality
    catalysts: int = 0

    @property
    def family(self) -> str:
        return CURRENCIES[self.currency][1]

    @property
    def floor(self) -> int:
        return CURRENCIES[self.currency][2]

    @property
    def side(self) -> str | None:
        return next((OMENS[o][1] for o in self.omens if OMENS[o][1]), None)

    @property
    def count(self) -> int:
        return max((OMENS[o][2] for o in self.omens), default=1)

    @property
    def items(self) -> list[str]:
        catalysed = [CATALYSING_OMEN, *[self.catalyst] * self.catalysts] if self.catalyst else []
        return [self.essence or CURRENCIES[self.currency][0], *self.omens, *catalysed]

    @property
    def main_name(self) -> str:
        return show_currency(self.essence or CURRENCIES[self.currency][0])

    @property
    def omen_names(self) -> list[str]:
        return [show_currency(name) for name in self.omens]

    @property
    def label(self) -> str:
        catalysed = [f"{self.catalysts} × {show_currency(self.catalyst)}", show_currency(CATALYSING_OMEN)] if self.catalyst else []
        return " + ".join([*catalysed, *self.omen_names, self.main_name])


def build_actions() -> list[Action]:
    actions = []
    for slug, (_, family, _) in CURRENCIES.items():
        omens = [name for name, omen in OMENS.items() if omen[0] == family]
        actions.append(Action(slug))
        actions.extend(Action(slug, (omen,)) for omen in omens)
        doubled = [o for o in omens if OMENS[o][2] > 1]
        actions.extend(Action(slug, (s, d)) for s in omens if OMENS[s][1] for d in doubled)
    return actions


@dataclass(frozen=True)
class Mod:
    name: str
    side: str
    level: int
    groups: tuple[str, ...]
    weight: int
    weight_known: bool
    text: str
    template: str
    ru_name: str = ""
    ru_text: str = ""
    desecrated: bool = False  # only a Desecration can add it
    rune: str = ""  # only an item with this rune socketed can roll it
    only_from: str = ""  # it never rolls: this item is the one way to get it
    tags: tuple[str, ...] = ()  # poe2db's crafting tags, such as cold or life

    @property
    def shown_text(self) -> str:
        return (self.ru_text if language == "ru" else "") or self.text


def mod_values(text: str) -> tuple[float, float] | None:
    """The lowest and highest a modifier's first number can roll, from its text."""
    found = MOD_NUMBER.search(text)
    if not found:
        return None
    low, high, single = found.groups()
    return (float(low), float(high)) if low else (float(single), float(single))


def perfect_essence_status(essence: "Essence", want: "Want") -> int | None:
    """A perfect essence brings a mod of its own, and its family can hold other stats too: «+2 to Attack Skills» is not «+3 to Melee Skills».
    So it counts only for the same stat, and its text says how strong it is. When that cannot be read it is counted as too weak."""
    if make_template(essence.text) != want.ladder.template:
        return None
    needed = [values[0] for values in (mod_values(mod.text) for mod in want.qualifying) if values]
    values = mod_values(essence.text)
    if not values and not needed:  # a mod with no number in it, which either is there or is not
        return HIT
    return HIT if values and needed and values[0] >= min(needed) else WRONG_TIER


@dataclass(frozen=True)
class Ladder:
    """All tiers of one modifier, best tier first."""
    side: str
    template: str
    mods: tuple[Mod, ...]

    def available(self, ilvl: int) -> list[Mod]:
        return [mod for mod in self.mods if mod.level <= ilvl]

    @property
    def title(self) -> str:
        return make_template(self.mods[0].shown_text).replace("#", "X")

    @property
    def groups(self) -> set[str]:
        return {group for mod in self.mods for group in mod.groups}


@dataclass(frozen=True)
class Essence:
    """Upgrades a magic item to rare and adds this guaranteed modifier."""
    name: str
    side: str
    level: int
    groups: tuple[str, ...]
    text: str = ""
    ru_text: str = ""
    perfect: bool = False  # acts on a rare item: removes a random modifier, then adds this one


class Page:
    def __init__(self, name: str, mods: list[Mod], essences: list[Essence] | None = None, desecrated: list[Mod] | None = None, warped: list[Mod] | None = None):
        self.name = name
        self.mods = mods
        self.essences = essences or []
        self.desecrated = desecrated or []
        self.ladders = self._make_ladders(mods)
        self.desecrated_ladders = self._make_ladders(self.desecrated)
        self.warped = warped or []
        self.rune_ladders = [ladder for rune in dict.fromkeys(mod.rune for mod in self.warped) for ladder in self._make_ladders([mod for mod in self.warped if mod.rune == rune])]
        regular = {(ladder.side, ladder.template) for ladder in self.ladders}
        self.special_ladders = self._make_ladders([Mod(essence.name, essence.side, essence.level, essence.groups, 0, True, essence.text, make_template(essence.text), "", essence.ru_text, only_from=essence.name)
                                                   for essence in self.essences if essence.perfect and essence.text and (essence.side, make_template(essence.text)) not in regular])
        self.by_name = {(mod.side, name.casefold()): mod for mod in [*self.desecrated, *mods] for name in (mod.name, *name_forms(mod.ru_name)) if name}
        self.weights_known = any(mod.weight_known for mod in mods)

    @staticmethod
    def _make_ladders(mods: list[Mod]) -> list[Ladder]:
        grouped: dict[tuple[str, str], list[Mod]] = {}
        for mod in mods:
            grouped.setdefault((mod.side, mod.template), []).append(mod)
        return [Ladder(side, template, tuple(sorted(tiers, key=lambda m: -m.level))) for (side, template), tiers in sorted(grouped.items())]

    def find_mod(self, side: str, name: str) -> Mod | None:
        return self.by_name.get((side, name.casefold()))

    def find_desecrated(self, side: str, line: str) -> Mod | None:
        """Several desecrated mods share one name, so the words of the mod tell them apart."""
        wording = normalize_stat(line)
        for mod in self.desecrated:
            if mod.side == side and wording in (normalize_stat(RANGE.sub("#", text.split(" / ")[0])) for text in (mod.text, mod.ru_text) if text):
                return mod
        return None

    @staticmethod
    def _pool_of(ladders: list[Ladder], ilvl: int, floor: int) -> list[Mod]:
        pool = []
        for ladder in ladders:
            available = ladder.available(ilvl)
            # A modifier whose every tier is below the floor still rolls at its top tier.
            pool.extend([mod for mod in available if mod.level >= floor] or available[:1])
        return pool

    def pool(self, ilvl: int, floor: int = 0, runes=()) -> list[Mod]:
        return self._pool_of([*self.ladders, *(ladder for ladder in self.rune_ladders if ladder.mods[0].rune in runes)], ilvl, floor)

    def reveal_pool(self, ilvl: int, floor: int = 0, runes=()) -> list[Mod]:
        """What a reveal can offer: the regular mods and the ones only a Desecration can add."""
        return [*self.pool(ilvl, floor, runes), *self._pool_of(self.desecrated_ladders, ilvl, floor)]

    @property
    def bone_kind(self) -> str:
        return "Collarbone" if self.name in COLLARBONE_PAGES else "Jawbone" if self.name in JAWBONE_PAGES else "Rib"

    def bones(self, ilvl: int) -> list[str]:
        """The bones that work on this item, cheapest kind first. A page without desecrated mods has no reliable data for them."""
        if not self.desecrated:
            return []
        kind = self.bone_kind
        return [*([f"Gnawed {kind}"] if ilvl <= GNAWED_BONE_MAX_ILVL else []), f"Preserved {kind}", f"Ancient {kind}"]


def resolve_weights(raw_mods: list[dict]) -> list[Mod]:
    known = [raw["weight"] for raw in raw_mods if raw["weight"] != UNKNOWN_WEIGHT]
    fallback = int(median(known)) if known else DEFAULT_WEIGHT
    return [Mod(raw["name"], raw["side"], raw["level"], tuple(raw["groups"]),
                raw["weight"] if raw["weight"] != UNKNOWN_WEIGHT else fallback, raw["weight"] != UNKNOWN_WEIGHT,
                raw["text"], raw["template"], raw.get("ru_name", ""), raw.get("ru_text", ""), tags=tuple(raw.get("tags", ()))) for raw in raw_mods]


def warped_mods(raw: dict) -> list[Mod]:
    """poe2db has no real weight for these, so each gets the page's usual weight and says so."""
    known = [mod["weight"] for mod in raw["mods"] if mod["weight"] != UNKNOWN_WEIGHT]
    weight = int(median(known)) if known else DEFAULT_WEIGHT
    return [Mod(e["name"], e["side"], e["level"], tuple(e["groups"]), weight, False, e["text"], e["template"], e.get("ru_name", ""), e.get("ru_text", ""), False, WARPING_RUNES[group])
            for group, entries in raw.get("warped", {}).items() if group in WARPING_RUNES for e in entries]


class Database:
    def __init__(self, data: dict):
        self.pages = {name: Page(name, resolve_weights(raw["mods"]),
                                 [Essence(e["name"], e["side"], e["level"], tuple(e["groups"]), e.get("text", ""), e.get("ru_text", ""), e.get("perfect", False)) for e in raw.get("essences", [])],
                                 [Mod(e["name"], e["side"], e["level"], tuple(e["groups"]), DESECRATED_WEIGHT, False, e["text"], e["template"], e.get("ru_name", ""), e.get("ru_text", ""), True) for e in raw.get("desecrated", [])],
                                 warped_mods(raw))
                      for name, raw in data["pages"].items()}
        self.bases = data["bases"]
        self.game_version = data.get("game_version")
        # Both languages lead to the English key used everywhere else.
        self.names = {shown.casefold(): name for name, info in self.bases.items() for shown in (name, info.get("ru", name))}
        currency_names.clear()
        currency_names.update(data.get("currency_names", {}))
        currency_keys.clear()
        currency_keys.update(data.get("currency_keys", {}))

    def show_base(self, base: str) -> str:
        return self.bases[base].get("ru", base) if language == "ru" else base

    def find_base(self, query: str) -> str:
        query = query.casefold()
        if query in self.names:
            return self.names[query]
        matches = {name for shown, name in self.names.items() if query in shown}
        if len(matches) != 1:
            raise ValueError(t("Предмет не найден: {query}").format(query=query) if not matches else t("Под «{query}» подходит {count} предметов, уточните название").format(query=query, count=len(matches)))
        return matches.pop()


# -------------------------------------------------------------------- planner
NONE, HIT, WRONG_TIER = 0, 1, 2
UNLOCKED = -1
LOCKED_JUNK = {"prefix": -2, "suffix": -3}
FRACTURE_MIN_MODS = 4
LOCK_PREVIEW_FAMILIES = frozenset({"chaos", "exalted", "annulment"})  # what players look at under Hinekora's Lock
FRACTURE_MIN_ILVL = 75
FRACTURE_STATE_LIMIT = 4000  # states without it: six mods at top tiers come to about 3000
LET_GO_BATCH = 400
DENSE_SOLVE_LIMIT = 1500  # larger layers are solved sparse, which is exact to the tolerance and needs no gigabytes
CHAIN_SOLVE_TOLERANCE = 1e-11
CHAIN_SOLVE_STEPS, CHAIN_SOLVE_RESTARTS = 4000, 6
# limit: the most one step may cost, in Divine. step: what one extra action is worth, in Divine; it makes a plan prefer fewer, stronger steps.
# "budget" is the least spent on average. "endgame" takes fewer steps with better orbs, paying a little more: each step weighs on top of its price what an average step
# of the cheapest plan costs, times this share. A fixed weight (it was 0.25 Divine) made a ring of 2 Chaos cost 2 Divine to save a few clicks, and meant nothing for a mirror goal.
# A plan against bad luck was tried as well (each result weighed by e^(theta * cost)), and on real prices it came out as the cheapest plan within noise:
# the spread lies in the orbs themselves, and no step trades a higher price for less of it. The old budget limit of 0.2 Divine a step cut needed omens and made plans absurd.
CRAFT_MODES = {"budget": {}, "endgame": {"step_share": 1.0}}
ALTERNATIVE_MIN_SAVING = 0.8  # a variant is offered only when it costs at most this share of the plan
ALTERNATIVES_SHOWN = 3
ALTERNATIVES_STATE_LIMIT = 1500
ALTERNATIVES_MAX_WANTS = 4
DISCOUNT = 1 - 1e-7  # keeps improper policies solvable while the policy iteration improves them
MAX_POLICY_ITERATIONS = 100


def let_go_slowly(heap: dict) -> None:
    """Freeing millions of small objects at once holds Python for seconds, and the window with it. Freed a little at a time on a thread of its own, the window never notices.
    Only for what nothing reads any more."""
    def work():
        while heap:
            for _ in range(LET_GO_BATCH):
                if not heap:
                    break
                heap.popitem()
            time.sleep(0.001)

    if heap:
        threading.Thread(target=work, daemon=True).start()


def solve_chain(rows: np.ndarray, columns: np.ndarray, chances: np.ndarray, totals: np.ndarray, guess: np.ndarray | None = None) -> np.ndarray:
    """Solves x = totals + P x, where P holds a chance at (row, column) for each entry. Mirror goals have tens of thousands of states but only a handful of outcomes per state,
    so the dense matrix would take gigabytes while this takes a few vectors. BiCGSTAB with each state's own chance of staying put as the preconditioner."""
    count = len(totals)

    def product(vector):
        return vector - np.bincount(rows, chances * vector[columns], minlength=count)

    stays = rows == columns
    diagonal = 1 - np.bincount(rows[stays], chances[stays], minlength=count)
    inverse = np.where(diagonal > 1e-12, 1 / np.where(diagonal > 1e-12, diagonal, 1), 1.0)
    x = guess.astype(float).copy() if guess is not None and len(guess) == count else totals * inverse
    scale = max(float(np.linalg.norm(totals)), 1e-30)
    residual = totals - product(x)
    for _ in range(CHAIN_SOLVE_RESTARTS):
        if np.linalg.norm(residual) <= CHAIN_SOLVE_TOLERANCE * scale:
            return x
        shadow = residual.copy()
        rho = alpha = omega = 1.0
        direction = along = np.zeros(count)
        for _ in range(CHAIN_SOLVE_STEPS):
            rho_next = float(shadow @ residual)
            if rho_next == 0:
                break  # starts over from where it stands
            direction = residual + (rho_next / rho) * (alpha / omega) * (direction - omega * along)
            scaled = inverse * direction
            along = product(scaled)
            alpha = rho_next / float(shadow @ along)
            half = residual - alpha * along
            if np.linalg.norm(half) <= CHAIN_SOLVE_TOLERANCE * scale:
                return x + alpha * scaled
            half_scaled = inverse * half
            turned = product(half_scaled)
            omega = float(turned @ half) / float(turned @ turned)
            x = x + alpha * scaled + omega * half_scaled
            residual = half - omega * turned
            if np.linalg.norm(residual) <= CHAIN_SOLVE_TOLERANCE * scale:
                return x
            if omega == 0:
                break
            rho = rho_next
        residual = totals - product(x)
    if np.linalg.norm(residual) <= CHAIN_SOLVE_TOLERANCE * 1e3 * scale:
        return x
    raise np.linalg.LinAlgError("the plan did not settle")


class PlanCancelled(Exception):
    """The plan is no longer wanted: another base was opened, the league changed, or the plan it was a variant of is gone."""


CANCEL_CHECK_STATES = 1024  # how often the search for states looks whether it is still wanted


@dataclass(frozen=True)
class Want:
    ladder: Ladder
    min_tier: int
    qualifying: frozenset[Mod]
    need: int = 0  # a mod of the group "any N of these" carries N, as every other member does; 0 for a mod that must be there

    @property
    def side(self) -> str:
        return self.ladder.side

    @property
    def label(self) -> str:
        return self.ladder.title + (f" (T{self.min_tier}+)" if self.min_tier < len(self.ladder.mods) else "")

    @property
    def desecrated_only(self) -> bool:
        return all(mod.desecrated for mod in self.qualifying)


NOT_DESECRATED = 0
DESECRATED_JUNK = {"prefix": -1, "suffix": -2}


class State(NamedTuple):
    rarity: str
    status: tuple[int, ...]
    junk_prefix: int
    junk_suffix: int
    locked: int = UNLOCKED  # the fractured modifier: a want index or a LOCKED_* value
    desecrated: int = NOT_DESECRATED  # the desecrated modifier: a want index plus one, or a DESECRATED_JUNK value


def make_want(ladder: Ladder, min_tier: int | None, ilvl: int) -> Want:
    min_tier = min_tier or len(ladder.mods)
    qualifying = [mod for mod in ladder.mods[:min_tier] if mod.level <= ilvl]
    if not qualifying:
        needed = min(mod.level for mod in ladder.mods[:min_tier])
        raise ValueError(t("«{title}» T{tier} требует уровень предмета {needed}+, сейчас {ilvl}").format(title=ladder.title, tier=min_tier, needed=needed, ilvl=ilvl))
    return Want(ladder, min_tier, frozenset(qualifying))


def group_need(wants: list[Want]) -> int:
    """How many of the group "any N of these" must be there: never more than the group has."""
    return min(max((want.need for want in wants), default=0), sum(1 for want in wants if want.need))


def needed_slots(wants: list[Want], side: str, open_slots: dict | None = None) -> int:
    """The fewest places on one side a goal can take: the mods that must be there, the group's members that cannot go on the other side, and the places kept free."""
    other = "suffix" if side == "prefix" else "prefix"
    required = sum(1 for want in wants if not want.need and want.side == side)
    from_group = max(0, group_need(wants) - sum(1 for want in wants if want.need and want.side == other))
    return required + from_group + (open_slots or {}).get(side, 0)


def validate_wants(wants: list[Want], base: str = "", open_slots: dict | None = None) -> None:
    if not wants:
        raise ValueError(t("Выберите хотя бы один мод"))
    limits = affix_limits(base)
    for side, message in (("prefix", "Префиксов на этом предмете не больше {count}"), ("suffix", "Суффиксов на этом предмете не больше {count}")):
        if needed_slots(wants, side, open_slots) > limits[side]:
            raise ValueError(t(message).format(count=limits[side]))
    need = group_need(wants)
    if need:
        # Each side alone may fit while the group as a whole does not: N members must find room on the two sides together.
        room = {side: limits[side] - sum(1 for want in wants if not want.need and want.side == side) - (open_slots or {}).get(side, 0) for side in ("prefix", "suffix")}
        members = {side: sum(1 for want in wants if want.need and want.side == side) for side in ("prefix", "suffix")}
        if min(room["prefix"], members["prefix"]) + min(room["suffix"], members["suffix"]) < need:
            raise ValueError(t("Группа «любые {count}» не помещается на предмет вместе с остальными модами").format(count=need))
    for index, want in enumerate(wants):
        for other in wants[index + 1:]:
            if want.ladder.groups & other.ladder.groups:
                raise ValueError(t("Эти моды несовместимы: «{first}» и «{second}»").format(first=want.ladder.title, second=other.ladder.title))
    if sum(want.desecrated_only for want in wants) > 1:
        raise ValueError(t("Очернить предмет можно только раз: выберите один очернённый мод"))


def state_of_mods(rarity: str, mods: list[tuple[str, Mod | None]], wants: list[Want], fractured: tuple[str, Mod | None] | None = None, desecrated: tuple[str, Mod | None] | None = None) -> State:
    """Builds a state from (side, known mod or None) pairs read from a real item."""
    status = [NONE] * len(wants)
    junk = {"prefix": 0, "suffix": 0}
    locked = UNLOCKED
    marked = NOT_DESECRATED
    for side, mod in mods:
        for index, want in enumerate(wants):
            if mod and want.ladder.groups.intersection(mod.groups):
                status[index] = HIT if mod in want.qualifying else WRONG_TIER
                locked = index if (side, mod) == fractured else locked
                marked = index + 1 if (side, mod) == desecrated else marked
                break
        else:
            junk[side] += 1
            locked = LOCKED_JUNK[side] if (side, mod) == fractured else locked
            marked = DESECRATED_JUNK[side] if (side, mod) == desecrated else marked
    return State(rarity, tuple(status), junk["prefix"], junk["suffix"], locked, marked)


class Planner:
    def __init__(self, page: Page, ilvl: int, wants: list[Want], prices: dict[str, float], mode: str | None = None, base: str = "", open_slots: dict | None = None,
                 cancelled=None):
        self.cancelled = cancelled or (lambda: False)
        self.cost_cache: dict[Action, float] = {}
        self.keep_explored = False  # set when the other mode of the same goal will reuse this search
        self.explored_out = None
        self.open_slots = {side: (open_slots or {}).get(side, 0) for side in ("prefix", "suffix")}
        validate_wants(wants, base, self.open_slots)
        self.wants = wants
        self.mode = mode
        self.base = base
        self.limits = affix_limits(base)
        self.required = [index for index, want in enumerate(wants) if not want.need]
        self.group = [index for index, want in enumerate(wants) if want.need]
        self.need = group_need(wants)
        self.kept_free = [(side, self.limits[side] - count) for side, count in self.open_slots.items() if count]
        # Rings and amulets take catalyst quality, a Breach Ring more of it.
        self.quality = QUALITY_CAP_BY_BASE.get(base, QUALITY_CAP) if page.name in CATALYST_PAGES else 0
        # A rune goes in before anything else, and every new base needs its own.
        self.runes = sorted({mod.rune for want in wants for mod in want.qualifying if mod.rune})
        for rune in self.runes:
            if prices.get(rune, 0) <= 0:
                raise ValueError(t("Для этого мода нужна руна «{rune}», а её цены нет или она запрещена").format(rune=show_currency(rune)))
        self.setup = [item for rune in self.runes for item in (*((SOCKET_ORB,) if prices.get(SOCKET_ORB, 0) > 0 else ()), rune)]
        self.setup_cost = sum(prices[item] for item in self.setup)
        self.plain_prices = prices
        prices = {**prices, NEW_BASE: prices[NEW_BASE] + self.setup_cost} if self.setup_cost and NEW_BASE in prices else prices
        self.prices = prices
        settings = CRAFT_MODES.get(mode, {})
        rate = prices.get("Divine Orb", 0)
        self.step_cost = settings.get("step", 0) * rate
        self.base_step_cost = self.step_cost  # the second solve of the "fewer steps" mode adds to it, from this each time
        self.step_share = settings.get("step_share", 0.0)
        self.actions = [action for action in build_actions() if all(prices.get(item, 0) > 0 for item in action.items)]
        self.essences = self._useful_essences(page, ilvl)
        self.perfect_essences = {essence.name for essence in page.essences if essence.perfect}
        self.required_items = {mod.only_from for want in wants if all(mod.only_from for mod in want.qualifying) for mod in want.qualifying}
        for want in wants:
            sources = {mod.only_from for mod in want.qualifying}
            if all(sources) and not sources & set(self.essences):
                raise ValueError(t("Этот мод даёт только «{item}», а его цены нет или он запрещён").format(item=show_currency(min(sources))))
        self.actions += [Action("essence", essence=name) for name in self.essences if name not in self.perfect_essences]
        for name in self.essences:
            if name in self.perfect_essences:
                # The omens speak of essences, so an alloy goes without them.
                omen_sets = ((), ("Omen of Sinistral Crystallisation",), ("Omen of Dextral Crystallisation",)) if "Essence" in name else ((),)
                self.actions += [action for action in (Action("perfect_essence", omens, name) for omens in omen_sets) if all(prices.get(item, 0) > 0 for item in action.items)]
        self.actions += self._catalysed_actions(prices)
        wanted_groups = {group for want in wants for group in want.ladder.groups}
        self.unwanted_levels = [(mod.level, mod.weight) for mod in page.pool(ilvl, 0, self.runes) if not wanted_groups.intersection(mod.groups)]
        # A lich's omen is offered only for a wanted mod of that lich: it changes nothing for the others. The omen speaks of weapons and jewellery.
        self.liches = sorted({lich_of(mod) for want in wants for mod in want.qualifying if lich_of(mod)}) if page.name in LICH_OMEN_PAGES else []
        bones = self._bone_actions(page, ilvl)
        bones += [Action(action.currency, (*action.omens, omen), action.essence) for action in bones for omen, lich in LICH_OMENS.items() if lich in self.liches]
        self.bones = [action for action in bones if all(prices.get(item, 0) > 0 for item in action.items)]
        must_desecrate = any(want.desecrated_only for want in wants)
        if must_desecrate:
            if not self.bones:
                raise ValueError(t("Для очернённого мода нужна кость Бездны, а её цены нет или она запрещена"))
            self.actions, self.bones = [*self.actions, *self.bones], []
        # Fracturing is an endgame tool: below this item level the orb costs far more than the item is worth.
        self.fracture = next((action for action in self.actions if action.family == "fracture" and ilvl >= FRACTURE_MIN_ILVL), None)
        # The Lock costs hundreds of Divine: it is for the last steps of an endgame item, and it reaches no state the orbs themselves do not.
        self.lock = next((action for action in self.actions if action.family == "lock" and ilvl >= FRACTURE_MIN_ILVL), None)
        self.lock_choices: dict[State, tuple] = {}  # (orbs' average cost, where the item goes, how often each orb is used, orb cost by result)
        self.actions = [action for action in self.actions if action.family not in ("fracture", "lock")]
        self.tables = {floor: self._weight_table(page.pool(ilvl, floor, self.runes)) for floor in {c[2] for c in CURRENCIES.values()}}
        for action in self.actions:  # an omen-catalysed Exalted Orb draws from the same mods with the catalyst's ones weighing more
            if action.catalyst and (action.floor, action.catalyst) not in self.tables:
                self.tables[(action.floor, action.catalyst)] = self._weight_table(page.pool(ilvl, action.floor, self.runes), CATALYST_TAGS[action.catalyst], catalyst_boost(self.quality))
        self.reveal_tables = {floor: self._reveal_table(page.reveal_pool(ilvl, floor, self.runes)) for floor in {c[2] for c in CURRENCIES.values() if c[1] == "desecrate"}}
        self.lich_tables = {(floor, lich): self._reveal_table([mod for mod in page.reveal_pool(ilvl, floor, self.runes) if lich_of(mod) == lich]) for floor in self.reveal_tables for lich in self.liches}
        self.add_cache: dict[tuple, dict[State, float]] = {}

    @staticmethod
    def _bone_actions(page: Page, ilvl: int) -> list[Action]:
        actions = []
        for bone in page.bones(ilvl):
            slug = "ancient_desecrate" if bone.startswith("Ancient") else "desecrate"
            for omens in ((), ("Omen of Sinistral Necromancy",), ("Omen of Dextral Necromancy",), (OMEN_OF_ECHOES,), ("Omen of Sinistral Necromancy", OMEN_OF_ECHOES), ("Omen of Dextral Necromancy", OMEN_OF_ECHOES)):
                actions.append(Action(slug, omens, bone))
        return actions

    def _reveal_table(self, pool: list[Mod]) -> dict:
        total = {"prefix": 0, "suffix": 0}
        for mod in pool:
            total[mod.side] += mod.weight
        return {"total": total, "hit": [sum(mod.weight for mod in pool if mod in want.qualifying) for want in self.wants]}

    def _useful_essences(self, page: Page, ilvl: int) -> dict[str, tuple[int, int]]:
        """Maps priced essences that give a wanted modifier to (want index, resulting status)."""
        useful = {}
        for essence in page.essences:
            if essence.level > ilvl or self.prices.get(essence.name, 0) <= 0:
                continue
            for index, want in enumerate(self.wants):
                if want.side == essence.side and want.ladder.groups.intersection(essence.groups):
                    if essence.perfect:
                        status = perfect_essence_status(essence, want)
                        if status is not None:
                            useful[essence.name] = (index, status)
                        continue
                    # An essence modifier is as strong as the regular tier of the same level.
                    good_enough = essence.level >= min(mod.level for mod in want.qualifying)
                    useful[essence.name] = (index, HIT if good_enough else WRONG_TIER)
        return useful

    def cost(self, action: Action) -> float:
        """Asked hundreds of thousands of times while a large goal is searched, so each action's price is added up once."""
        found = self.cost_cache.get(action)
        if found is None:
            found = self.cost_cache[action] = sum(self.prices[item] for item in action.items)
        return found

    def _catalysed_actions(self, prices: dict[str, float]) -> list[Action]:
        """Each Exalted Orb, with its side and Greater omens, again after catalysts and the Catalysing omen: only catalysts whose tag a wanted mod carries."""
        if not self.quality or prices.get(CATALYSING_OMEN, 0) <= 0:
            return []
        wanted_tags = {tag for want in self.wants for mod in want.qualifying for tag in mod.tags}
        count = catalysts_needed(self.quality)
        return [replace(action, catalyst=catalyst, catalysts=count) for catalyst, tags in CATALYST_TAGS.items() if prices.get(catalyst, 0) > 0 and wanted_tags.intersection(tags)
                for action in self.actions if action.family == "exalted" and not action.catalyst]

    def _weight_table(self, pool: list[Mod], boosted: tuple[str, ...] = (), boost: float = 1.0) -> dict:
        weigh = lambda mod: mod.weight * boost if boosted and set(boosted).intersection(mod.tags) else mod.weight
        junk = {"prefix": 0, "suffix": 0}
        for mod in pool:
            junk[mod.side] += weigh(mod)
        hit, wrong = [], []
        for want in self.wants:
            hit.append(sum(weigh(mod) for mod in pool if mod in want.qualifying))
            wrong.append(sum(weigh(mod) for mod in pool if mod not in want.qualifying and want.ladder.groups.intersection(mod.groups)))
            junk[want.side] -= hit[-1] + wrong[-1]
        return {"hit": hit, "wrong": wrong, "junk": junk}

    def side_limit(self, rarity: str, side: str) -> int:
        return self.limits[side] if rarity == "rare" else MAX_PER_SIDE[rarity]

    def side_count(self, state: State, side: str) -> int:
        junk = state.junk_prefix if side == "prefix" else state.junk_suffix
        return junk + sum(w.side == side and s != NONE for w, s in zip(self.wants, state.status))

    def is_goal(self, state: State) -> bool:
        """Every mod that must be there, enough of the group, and the places kept free still free."""
        status = state.status
        return (all(status[index] == HIT for index in self.required) and (not self.group or sum(status[index] == HIT for index in self.group) >= self.need)
                and all(self.side_count(state, side) <= most for side, most in self.kept_free))

    def _add(self, state: State, side: str | None, floor: int) -> dict[State, float]:
        key = (state, side, floor)
        if key in self.add_cache:
            return self.add_cache[key]
        table = self.tables[floor]
        sides = {s for s in ("prefix", "suffix") if side in (None, s) and self.side_count(state, s) < self.side_limit(state.rarity, s)}
        options = []
        for index, want in enumerate(self.wants):
            if want.side in sides and state.status[index] == NONE:
                for status, weight in ((HIT, table["hit"][index]), (WRONG_TIER, table["wrong"][index])):
                    if weight > 0:
                        options.append((state._replace(status=state.status[:index] + (status,) + state.status[index + 1:]), weight))
        if "prefix" in sides and table["junk"]["prefix"] > 0:
            options.append((state._replace(junk_prefix=state.junk_prefix + 1), table["junk"]["prefix"]))
        if "suffix" in sides and table["junk"]["suffix"] > 0:
            options.append((state._replace(junk_suffix=state.junk_suffix + 1), table["junk"]["suffix"]))
        total = sum(weight for _, weight in options)
        self.add_cache[key] = {new: weight / total for new, weight in options}
        return self.add_cache[key]

    def _junk_removals(self, state: State, side: str | None) -> list[tuple[State, int]]:
        options = []
        for name, field in (("prefix", "junk_prefix"), ("suffix", "junk_suffix")):
            count = getattr(state, field) - (state.locked == LOCKED_JUNK[name])
            if side in (None, name) and count > 0:
                gone = state._replace(**{field: getattr(state, field) - 1})
                if state.desecrated == DESECRATED_JUNK[name]:  # one of these is the desecrated mod, and once it is gone the item can be desecrated again
                    options.append((gone._replace(desecrated=NOT_DESECRATED), 1))
                    count -= 1
                if count:
                    options.append((gone, count))
        return options

    def _wanted_removal(self, state: State, index: int) -> State:
        gone = state._replace(status=state.status[:index] + (NONE,) + state.status[index + 1:])
        return gone._replace(desecrated=NOT_DESECRATED) if state.desecrated == index + 1 else gone

    def _remove(self, state: State, side: str | None) -> dict[State, float]:
        options = [(self._wanted_removal(state, index), 1) for index, want in enumerate(self.wants) if state.status[index] != NONE and side in (None, want.side) and index != state.locked]
        options += self._junk_removals(state, side)
        total = sum(weight for _, weight in options)
        return {new: weight / total for new, weight in options}

    def _remove_lowest(self, state: State) -> dict[State, float]:
        """Omen of Whittling: the mod of the lowest level goes. The plan does not know the level of an unwanted mod, so it reckons with how the possible ones are spread:
        a wanted mod is at risk only if every unwanted one on the item happens to stand above it."""
        present = [(min(mod.level for mod in want.qualifying), index) for index, want in enumerate(self.wants) if state.status[index] != NONE and index != state.locked]
        junk = self._junk_removals(state, None)
        count = sum(weight for _, weight in junk)
        if not present:
            return {new: weight / count for new, weight in junk} if junk else {}
        lowest, index = min(present)
        at_risk = self._wanted_removal(state, index)
        if not junk:
            return {at_risk: 1.0}
        total = sum(weight for _, weight in self.unwanted_levels)
        above = sum(weight for level, weight in self.unwanted_levels if level > lowest) / total if total else 0.0
        risk = above ** count
        result = {new: (1 - risk) * weight / count for new, weight in junk}
        result[at_risk] = result.get(at_risk, 0) + risk
        return {new: chance for new, chance in result.items() if chance > 0}

    def _remove_desecrated(self, state: State) -> dict[State, float]:
        """Omen of Light: only the desecrated mod goes. It is only worth paying for when that mod is not one of the wanted ones."""
        for name, field in (("prefix", "junk_prefix"), ("suffix", "junk_suffix")):
            if state.desecrated == DESECRATED_JUNK[name] and getattr(state, field) - (state.locked == LOCKED_JUNK[name]) > 0:  # a fractured mod stays
                return {state._replace(**{field: getattr(state, field) - 1}, desecrated=NOT_DESECRATED): 1.0}
        return {}

    def _desecrate(self, state: State, side: str | None, floor: int, rounds: int, lich: str | None = None) -> dict[State, float]:
        """A bone adds a hidden mod and the player picks the best of those a reveal offers: a wanted one if any turns up, otherwise something unwanted.
        Under a lich's omen one of the offered mods is that lich's, the others come as usual. Whether a reroll under Abyssal Echoes keeps that is not known, so it is counted once."""
        table = self.reveal_tables[floor]
        guided = self.lich_tables.get((floor, lich)) if lich else None
        sides = [name for name in ("prefix", "suffix") if side in (None, name) and self.side_count(state, name) < self.limits[name] and table["total"][name] > 0]
        everything = sum(table["total"][name] for name in sides)
        result: dict[State, float] = {}
        for name in sides:
            share = table["total"][name] / everything
            open_wants = [index for index, want in enumerate(self.wants) if want.side == name and state.status[index] == NONE and table["hit"][index] > 0]
            chances = {index: table["hit"][index] / table["total"][name] for index in open_wants}
            lich_chances = {index: guided["hit"][index] / guided["total"][name] for index in open_wants} if guided and guided["total"][name] > 0 else {}
            draws = DESECRATE_OPTIONS * rounds - bool(lich_chances)
            miss = (1 - min(sum(chances.values()), 1.0)) ** draws * (1 - min(sum(lich_chances.values()), 1.0))
            odds = {index: draws * chances[index] + lich_chances.get(index, 0) for index in open_wants}
            spread = sum(odds.values())
            for index in open_wants:
                found = state._replace(status=state.status[:index] + (HIT,) + state.status[index + 1:], desecrated=index + 1)
                result[found] = result.get(found, 0) + share * (1 - miss) * odds[index] / spread
            field = "junk_prefix" if name == "prefix" else "junk_suffix"
            if miss > 0:
                unwanted = state._replace(**{field: getattr(state, field) + 1}, desecrated=DESECRATED_JUNK[name])
                result[unwanted] = result.get(unwanted, 0) + share * miss
        return result

    def _fracture(self, state: State) -> dict[State, float]:
        """Locks a random modifier. It is not offered when an unlucky result could make the goal impossible."""
        count = self.side_count(state, "prefix") + self.side_count(state, "suffix")
        if state.rarity != "rare" or state.locked != UNLOCKED or count < FRACTURE_MIN_MODS or WRONG_TIER in state.status:
            return {}
        # A desecrated mod counts towards the four but is never the one locked, so the chance falls on the others.
        count -= state.desecrated != NOT_DESECRATED
        options = {state._replace(locked=index): 1 / count for index, status in enumerate(state.status) if status == HIT and state.desecrated != index + 1}
        for side, junk in (("prefix", state.junk_prefix - (state.desecrated == DESECRATED_JUNK["prefix"])), ("suffix", state.junk_suffix - (state.desecrated == DESECRATED_JUNK["suffix"]))):
            if junk:
                if needed_slots(self.wants, side, self.open_slots) + 1 > self.limits[side]:
                    return {}
                options[state._replace(locked=LOCKED_JUNK[side])] = junk / count
        return options

    def check_winnable(self, state: State) -> None:
        if state.locked >= 0 and state.status[state.locked] == WRONG_TIER and not self.wants[state.locked].need:  # a group's member may be left to the others
            raise ValueError(t("Расколот мод слишком слабого тира, его не убрать: цель на этом предмете недостижима"))
        for side, value in LOCKED_JUNK.items():
            if state.locked == value and needed_slots(self.wants, side, self.open_slots) + 1 > self.limits[side]:
                raise ValueError(t("Расколотый мод занимает нужный слот: цель на этом предмете недостижима"))

    @staticmethod
    def _chain(first: dict[State, float], step) -> dict[State, float]:
        result: dict[State, float] = {}
        for state, probability in first.items():
            for new, chance in (step(state) or {state: 1.0}).items():
                result[new] = result.get(new, 0) + probability * chance
        return result

    def outcomes(self, state: State, action: Action) -> dict[State, float]:
        family, side, floor = action.family, action.side, action.floor
        empty = State("normal", (NONE,) * len(self.wants), 0, 0)
        if family == "new_base" and state.rarity != "normal":
            return {empty: 1.0}
        if family == "fracture":
            return self._fracture(state)
        if family == "lock":
            return dict(self.lock_choices[state][1]) if state in self.lock_choices else {}  # known once the plan is solved: which orb is used depends on what each result is worth
        if family == "essence" and state.rarity == "magic":
            index, status = self.essences[action.essence]
            if state.status[index] != NONE:
                return {}
            return {state._replace(rarity="rare", status=state.status[:index] + (status,) + state.status[index + 1:]): 1.0}
        if family == "transmutation" and state.rarity == "normal":
            return self._add(state._replace(rarity="magic"), None, floor)
        if family == "augmentation" and state.rarity == "magic":
            return self._add(state, None, floor)
        if family == "alchemy" and state.rarity != "rare":
            other = {"prefix": "suffix", "suffix": "prefix"}.get(side)
            result = {empty._replace(rarity="rare"): 1.0}
            first = min(self.limits[side], 4) if side else 0  # the omen's side takes all the room it has, of the orb's four mods
            for roll_side in ([side] * first + [other] * (4 - first) if side else [None] * 4):
                result = self._chain(result, lambda s, roll_side=roll_side: self._add(s, roll_side, 0))
            return result
        if family == "regal" and state.rarity == "magic":
            return self._add(state._replace(rarity="rare"), side, floor)
        if family == "exalted" and state.rarity == "rare":
            table = (floor, action.catalyst) if action.catalyst else floor  # with the Greater omen both mods are counted with the boost: the omen's text speaks of the orb
            result = self._add(state, side, table)
            return self._chain(result, lambda s: self._add(s, side, table)) if action.count > 1 and result else result
        if family == "perfect_essence" and state.rarity == "rare":
            return self._perfect_essence(state, action)
        if family == "chaos" and state.rarity == "rare":
            removed = self._remove_lowest(state) if OMEN_OF_WHITTLING in action.omens else self._remove(state, side)
            return self._chain(removed, lambda s: self._add(s, None, floor)) if removed else {}
        if family == "desecrate" and state.rarity == "rare" and state.desecrated == NOT_DESECRATED:
            lich = next((LICH_OMENS[omen] for omen in action.omens if omen in LICH_OMENS), None)
            return self._desecrate(state, side, floor, 2 if OMEN_OF_ECHOES in action.omens else 1, lich)
        # The game also allows it on magic items, but no real craft pays for that: a magic base is replaced or upgraded.
        if family == "annulment" and state.rarity == "rare":
            if OMEN_OF_LIGHT in action.omens:
                return self._remove_desecrated(state)
            result = self._remove(state, side)
            return self._chain(result, lambda s: self._remove(s, side)) if action.count > 1 and result else result
        return {}

    def _perfect_essence(self, state: State, action: Action) -> dict[State, float]:
        """Removes a random modifier, from one side under a Crystallisation omen, then adds the essence's. The game's rule for a side with no room after the removal is not known, so a chance of that is not risked."""
        index, status = self.essences[action.essence]
        if state.status[index] != NONE:
            return {}
        result: dict[State, float] = {}
        for new, chance in self._remove(state, action.side).items():
            if new.status[index] != NONE or self.side_count(new, self.wants[index].side) >= self.limits[self.wants[index].side]:
                return {}
            added = new._replace(status=new.status[:index] + (status,) + new.status[index + 1:])
            result[added] = result.get(added, 0) + chance
        return result

    def _explore(self, start: State, actions: list[Action], known: dict | None = None, extra: list[Action] = ()) -> dict[State, list[tuple[Action, dict[State, float]]]]:
        """Every state the actions can reach, with each action's results. A six-mod goal with bones has millions of results, so each state is kept once and shared,
        and an action whose results repeat a cheaper one's exactly is dropped: it could never be the choice. The Lock's orbs stay, as each is a draw of its own under it.
        Given an earlier search of fewer actions (known), its states keep their results and only the extra actions are tried on them: the search with bones and the
        Fracturing Orb used to start again from nothing and took as long as the first."""
        states, seen, listed, moves = [start], {start: start}, {start}, {}
        for state, options in (known or {}).items():
            seen.setdefault(state, state)
            for _, outcomes in options:
                for new in outcomes:
                    seen.setdefault(new, new)
        for number, state in enumerate(states):
            if number % CANCEL_CHECK_STATES == CANCEL_CHECK_STATES - 1 and self.cancelled():
                raise PlanCancelled()
            if self.is_goal(state):
                continue
            options, cheapest = [], {}
            tried = actions
            if known and state in known:
                tried = extra
                for action, shared in known[state]:
                    if not (self.lock and action.family in LOCK_PREVIEW_FAMILIES and not action.omens):
                        cheapest[frozenset(zip(map(id, shared), shared.values()))] = len(options)
                    options.append((action, shared))
            for action in tried:
                outcomes = self.outcomes(state, action)
                if not outcomes or outcomes.get(state, 0) >= 1 - 1e-12:
                    continue
                shared = {seen.setdefault(new, new): chance for new, chance in outcomes.items()}
                previewed = self.lock and action.family in LOCK_PREVIEW_FAMILIES and not action.omens
                signature = None if previewed else frozenset(zip(map(id, shared), shared.values()))  # each state is kept once, so where it is in memory names it, which is far quicker to compare
                if signature is not None and signature in cheapest:
                    position = cheapest[signature]
                    if self.cost(options[position][0]) <= self.cost(action):
                        continue
                    options[position] = (action, shared)
                    continue
                if signature is not None:
                    cheapest[signature] = len(options)
                options.append((action, shared))
            moves[state] = options
            for _, shared in options:
                for new in shared:
                    if new not in listed:
                        listed.add(new)
                        states.append(new)
        return moves

    def _without_dead_ends(self, moves: dict, start: State) -> dict:
        """Drops every action that risks a state the goal cannot be reached from. Forbidding orbs makes such states possible: a full item with nothing to remove a mod."""
        kept = {state: list(options) for state, options in moves.items()}
        while True:
            if self.cancelled():
                raise PlanCancelled()
            before: dict[State, list[State]] = {}
            for state, options in kept.items():
                for _, outcomes in options:
                    for new in outcomes:
                        before.setdefault(new, []).append(state)
            alive = {state for state in before if self.is_goal(state)}
            waiting = list(alive)
            while waiting:
                for state in before.get(waiting.pop(), ()):
                    if state not in alive:
                        alive.add(state)
                        waiting.append(state)
            changed = False
            for state in list(kept):
                good = [(action, outcomes) for action, outcomes in kept[state] if all(new in alive for new in outcomes)] if state in alive else []
                if len(good) != len(kept[state]) or not good:
                    changed = True
                    if good:
                        kept[state] = good
                    else:
                        del kept[state]
            if not changed:
                break
        if start not in kept and not self.is_goal(start):
            raise ValueError(t("С такими сферами цель недостижима: разрешите больше сфер или новую базу"))
        return kept

    def _lock_options(self, state: State, moves: dict) -> list[tuple[Action, dict[State, float]]]:
        """The orbs a player would look at under the Lock: Chaos, Exalted and Annulment of every grade, without omens, so the estimate errs on the careful side. Only those already safe here."""
        if sum(status != HIT for status in state.status) != 1:
            return []  # players save it for the last roll, and looking everywhere would make a mirror goal take minutes
        options = [(action, outcomes) for action, outcomes in moves.get(state, ()) if action.family in LOCK_PREVIEW_FAMILIES and not action.omens]
        return options if len(options) >= 2 else []

    def _best_preview(self, options: list[tuple[Action, dict[State, float]]], value_of) -> tuple[float, float, dict[State, float], dict[Action, float]]:
        """Each orb's result is drawn on its own and the best is used. Returns the expected value after the orb, what the orbs cost on average, where the item goes, and how often each orb is the one used.
        Every result of every orb is taken from best to worst: it is the one used when each other orb's result is worse, which is the chance still left in those orbs."""
        results = sorted(((self.cost(action) + value_of(new), order, action, new, chance) for order, (action, outcomes) in enumerate(options) for new, chance in outcomes.items()), key=lambda entry: entry[:2])
        left = [1.0] * len(options)
        expected = spent = 0.0
        going: dict[State, float] = {}
        used: dict[Action, float] = {}
        spent_on: dict[State, float] = {}
        for total, order, action, new, chance in results:
            others = math.prod(max(share, 0.0) for number, share in enumerate(left) if number != order)
            share = chance * others
            left[order] -= chance
            if share > 0:
                expected += share * (total - self.cost(action))
                spent += share * self.cost(action)
                going[new] = going.get(new, 0.0) + share
                used[action] = used.get(action, 0.0) + share
                spent_on[new] = spent_on.get(new, 0.0) + share * self.cost(action)
        scale = sum(going.values()) or 1.0  # rounding leaves a trace off one
        orb_cost = {new: spent_on[new] / going[new] for new in going}  # what the orb costs on average when the item ends up here
        return expected / scale, spent / scale, {new: share / scale for new, share in going.items()}, {action: share / scale for action, share in used.items()}, orb_cost

    def _layer_tables(self, states: list[State], moves: dict) -> tuple:
        """The layer as arrays: each action's price, where its results go inside the layer, and which results leave it. Building them is most of the work of a solve,
        and the second solve of the "fewer steps" mode only weighs steps differently, so they are built once and kept."""
        index = {state: position for position, state in enumerate(states)}
        prices, choices, offsets, owners, targets, chances = [], [], [], [], [], []
        leaving, gone_to, gone_chances = [], [], []
        for state in states:
            offsets.append(len(prices))
            for action, outcomes in moves[state]:
                row = len(prices)
                for new, chance in outcomes.items():
                    position = index.get(new)
                    if position is not None:
                        owners.append(row)
                        targets.append(position)
                        chances.append(chance)
                    else:
                        leaving.append(row)
                        gone_to.append(new)
                        gone_chances.append(chance)
                prices.append(self.cost(action))
                choices.append(action)
        owners = np.array(owners, dtype=int)
        return (index, np.array(prices, dtype=float), choices, offsets, owners, np.array(targets, dtype=int), np.array(chances, dtype=float),
                np.searchsorted(owners, np.arange(len(prices) + 1)), np.array(leaving, dtype=int), gone_to, np.array(gone_chances, dtype=float))

    def _solve_layer(self, states: list[State], moves: dict, values: dict[State, float], policy: dict[State, Action], tables: tuple | None = None) -> tuple:
        """Finds the cheapest action for states that can reach each other. States outside the layer already have values. Returns the layer's tables, for a second solve."""
        tables = tables or self._layer_tables(states, moves)
        index, prices, choices, offsets, owners, targets, chances, starts, leaving, gone_to, gone_chances = tables
        costs = prices + self.step_cost
        if len(leaving):
            costs += np.bincount(leaving, gone_chances * np.array([values.get(new, 0.0) for new in gone_to]), minlength=len(prices))
        count = len(states)
        ends = offsets[1:] + [len(costs)]

        # Hinekora's Lock: where at least two orbs could be looked at, the player sees each one's result and uses the best.
        previews = {row: options for row, state in enumerate(states) if (options := self._lock_options(state, moves))} if self.lock else {}
        lock_price = self.cost(self.lock) + self.step_cost if self.lock else 0.0
        locked: dict[int, tuple[float, dict[State, float]]] = {}  # rows that use the Lock: what the orbs cost on average, and where the item goes

        def value_of(layer_values, discount):
            return lambda state: discount * (layer_values[index[state]] if state in index else values.get(state, 0.0))

        def locked_row(row):
            spent, going = locked[row]
            inside = [(index[new], chance) for new, chance in going.items() if new in index]
            outside = sum(chance * values.get(new, 0.0) for new, chance in going.items() if new not in index)
            return lock_price + spent + outside, inside

        def evaluate(chosen, discount, guess=None):
            totals = costs[chosen].copy()
            extra = {row: locked_row(row) for row in locked}
            for row, (total, _) in extra.items():
                totals[row] = total
            if count > DENSE_SOLVE_LIMIT:
                plain_rows = [row for row in range(count) if row not in extra]
                picks = np.concatenate([np.arange(starts[chosen[row]], starts[chosen[row] + 1]) for row in plain_rows] or [np.zeros(0, dtype=int)])
                rows = np.repeat(np.array(plain_rows, dtype=int), [starts[chosen[row] + 1] - starts[chosen[row]] for row in plain_rows])
                columns, weights = targets[picks], discount * chances[picks]
                if extra:
                    rows = np.concatenate([rows, [row for row, (_, inside) in extra.items() for _ in inside]]).astype(int)
                    columns = np.concatenate([columns, [column for _, inside in extra.values() for column, _ in inside]]).astype(int)
                    weights = np.concatenate([weights, [discount * chance for _, inside in extra.values() for _, chance in inside]])
                return solve_chain(rows, columns, weights, totals, guess)
            matrix = np.eye(count)
            for row, choice in enumerate(chosen):
                if row in extra:
                    for column, chance in extra[row][1]:
                        matrix[row, column] -= discount * chance
                    continue
                low, high = starts[choice], starts[choice + 1]
                np.subtract.at(matrix[row], targets[low:high], discount * chances[low:high])
            return np.linalg.solve(matrix, totals)

        chosen = np.array([offset + int(np.argmin(costs[offset:end])) for offset, end in zip(offsets, ends)])
        layer_values = None
        for _ in range(MAX_POLICY_ITERATIONS):
            if self.cancelled():
                raise PlanCancelled()
            layer_values = evaluate(chosen, DISCOUNT, layer_values)
            q_values = costs + DISCOUNT * np.bincount(owners, chances * layer_values[targets], minlength=len(costs))
            best = np.minimum.reduceat(q_values, offsets)
            current = np.array(layer_values, dtype=float)
            if not previews:  # without the Lock every row is a plain choice, settled at once instead of row by row in Python
                better = np.flatnonzero(best < current - 1e-9 * (1 + np.abs(current)))
                if not len(better):
                    break
                for row in better:
                    chosen[row] = offsets[row] + int(np.argmin(q_values[offsets[row]:ends[row]]))
                continue
            changed = False
            seen = value_of(layer_values, DISCOUNT)
            for row in range(count):
                # The Lock alone costs more than all that is left here, so it cannot pay: most states are skipped this way without working out the best of each orb.
                lock_choice = self._best_preview(previews[row], seen) if row in previews and (lock_price < current[row] or row in locked) else None
                lock_q = lock_price + lock_choice[0] + lock_choice[1] if lock_choice else math.inf
                tolerance = 1e-9 * (1 + abs(current[row]))
                if min(best[row], lock_q) < current[row] - tolerance or (row in locked and best[row] < lock_q - tolerance):
                    changed = True
                    if lock_q < best[row]:
                        locked[row] = (lock_choice[1], lock_choice[2])
                    else:
                        locked.pop(row, None)
                        chosen[row] = offsets[row] + int(np.argmin(q_values[offsets[row]:ends[row]]))
                elif row in locked and lock_choice:
                    locked[row] = (lock_choice[1], lock_choice[2])  # the same choice, with the item's chances under the newest values
            if not changed:
                break
        layer_values = evaluate(chosen, 1.0, layer_values)
        for state, row in index.items():
            values[state] = float(layer_values[row])
            policy[state] = self.lock if row in locked else choices[chosen[row]]
        final = value_of(layer_values, 1.0)
        for row in locked:
            self.lock_choices[states[row]] = self._best_preview(previews[row], final)[1:]
        return tables

    def _count_usage(self, layers: list[list[State]], moves: dict, policy: dict[State, Action]) -> tuple[list[str], dict[State, np.ndarray]]:
        names = sorted({item for action in policy.values() for item in action.items} | {item for choice in self.lock_choices.values() for orb in choice[2] for item in orb.items})
        usage: dict[State, np.ndarray] = {}
        for states in layers:
            index = {state: position for position, state in enumerate(states)}
            rows, columns, chances = [], [], []
            rewards = np.zeros((len(states), len(names)))
            for state, row in index.items():
                action = policy[state]
                if action.family == "lock":
                    _, going, used, _ = self.lock_choices[state]
                    rewards[row] = [action.items.count(name) + sum(share * orb.items.count(name) for orb, share in used.items()) for name in names]
                else:
                    going = dict(moves[state])[action]
                    rewards[row] = [action.items.count(name) for name in names]
                for new, chance in going.items():
                    if new in index:
                        rows.append(row)
                        columns.append(index[new])
                        chances.append(chance)
                    elif new in usage:
                        rewards[row] += chance * usage[new]
            if len(states) > DENSE_SOLVE_LIMIT:
                rows, columns, chances = np.array(rows, dtype=int), np.array(columns, dtype=int), np.array(chances, dtype=float)
                solved = np.column_stack([solve_chain(rows, columns, chances, rewards[:, column]) for column in range(len(names))]) if names else rewards
            else:
                matrix = np.eye(len(states))
                np.subtract.at(matrix, (np.array(rows, dtype=int), np.array(columns, dtype=int)), np.array(chances, dtype=float))
                solved = np.linalg.solve(matrix, rewards)
            usage.update({state: solved[row] for state, row in index.items()})
        return names, usage

    def solve(self, start: State, shared: tuple | None = None) -> "Plan":
        """Python's collector would walk the millions of states of a large goal again and again, half a second at a time, and the window would stand still for each walk:
        nothing here makes reference cycles, so it rests until the plan is done."""
        collecting = gc.isenabled()
        gc.disable()
        try:
            return self._solve_quietly(start, shared)
        finally:
            if collecting:
                gc.enable()

    def _solve_quietly(self, start: State, shared: tuple | None = None) -> "Plan":
        # Catalysts were tried as actions offered only where they would beat the plan: on rings and amulets they beat it in many states,
        # and the rounds of solving again took longer than solving with them from the start.
        self.check_winnable(start)
        if shared:
            plan = self._solve_shared(start, shared)
            if plan:
                return plan
        plain = self._explore(start, self.actions)
        # Very large goals skip the Fracturing Orb: its extra states would take minutes to solve.
        fracture_counted = bool(self.fracture) and len(plain) <= FRACTURE_STATE_LIMIT
        bones = self.bones if len(plain) <= DESECRATE_STATE_LIMIT else []
        try:
            plan = self._solve_with(start, plain, bones, fracture_counted)
        except (np.linalg.LinAlgError, MemoryError):
            if not bones:
                raise
            let_go_slowly(self.add_cache)
            self.add_cache = {}
            plan = self._solve_with(start, plain, [], fracture_counted)  # bones make the largest chains, and the plan is still right without them, only dearer; six mods with bones take about a gigabyte
        if not (self.explored_out and self.explored_out[0] is plain):
            let_go_slowly(plain)
        return plan

    def _solve_shared(self, start: State, shared: tuple) -> "Plan | None":
        """The other mode's search, without the actions this one does not have, such as a new base. Searching took most of the time of a plan, and was done twice.
        The prices are the same apart from what this mode leaves out, so the other search dropped the same repeated actions this one would have."""
        explored, used, fracture_counted, with_bones = shared
        mine = {*self.actions, *(self.bones if with_bones else ()), *((self.fracture,) if fracture_counted and self.fracture else ())}
        if not mine <= used or start not in explored:
            return None
        kept, waiting = {}, [start]
        while waiting:  # only what this mode can reach: without a new base a whole start from nothing may be out of reach
            state = waiting.pop()
            if state in kept or state not in explored:
                continue
            kept[state] = [(action, outcomes) for action, outcomes in explored[state] if action in mine]
            waiting.extend(new for _, outcomes in kept[state] for new in outcomes if new not in kept)
        try:
            moves = self._without_dead_ends(kept, start)
            return self._plan_from(start, moves, fracture_counted)
        except (np.linalg.LinAlgError, MemoryError):
            return None  # its own search, as before

    def _solve_with(self, start: State, plain: dict, bones: list, fracture_counted: bool) -> "Plan":
        extras = [*bones, *((self.fracture,) if fracture_counted else ())]
        explored = self._explore(start, [*self.actions, *extras], plain, extras) if extras else plain
        let_go_slowly(self.add_cache)  # half the memory of a large goal, and only the few steps shown later need any of it again
        self.add_cache = {}
        if self.keep_explored:
            self.explored_out = (explored, frozenset([*self.actions, *extras]), fracture_counted, bool(bones))
        moves = self._without_dead_ends(explored, start)
        if explored is not plain and not self.keep_explored:
            let_go_slowly(explored)
        try:
            return self._plan_from(start, moves, fracture_counted)
        finally:
            let_go_slowly(moves)

    def _plan_from(self, start: State, moves: dict, fracture_counted: bool) -> "Plan":
        if not moves:
            return Plan(self, start, {}, {}, {}, fracture_counted)
        # A fracture cannot be undone, so fractured states are solved first and the rest builds on them.
        groups: dict[int, list[State]] = {}
        for state in moves:
            groups.setdefault(state.locked, []).append(state)
        layers = [states for locked, states in sorted(groups.items(), key=lambda entry: entry[0] == UNLOCKED)]
        # A new base takes a fractured item back to the start, which is solved last: its value would be read as nothing, and fracturing junk and starting over
        # would look free. Then everything is solved as one.
        order = {state: number for number, states in enumerate(layers) for state in states}
        if any(order.get(new, -1) > order[state] for state, options in moves.items() for _, outcomes in options for new in outcomes):
            layers = [[state for states in layers for state in states]]
        self.step_cost = self.base_step_cost
        values: dict[State, float] = {}
        policy: dict[State, Action] = {}
        tables = [self._solve_layer(states, moves, values, policy) for states in layers]
        plan = self._plan_of(start, layers, moves, policy, fracture_counted)
        if self.step_share and plan.action_count > 0 and plan.values.get(start, 0) > 0:
            # The cheapest plan sets what a step is worth here, and the plan is made again with each step weighing that much more.
            self.step_cost += self.step_share * plan.values[start] / plan.action_count
            values, policy = {}, {}
            self.lock_choices = {}
            for states, kept in zip(layers, tables):
                self._solve_layer(states, moves, values, policy, kept)
            plan = self._plan_of(start, layers, moves, policy, fracture_counted)
        return plan

    def _plan_of(self, start: State, layers: list[list[State]], moves: dict, policy: dict[State, Action], fracture_counted: bool) -> "Plan":
        names, usage = self._count_usage(layers, moves, policy)
        # The shown price is the real spending, without the extra weight a mode puts on each action.
        item_prices = np.array([self.prices[name] for name in names])
        spending = {state: float(counts @ item_prices) for state, counts in usage.items()}
        spending[start] += self.setup_cost
        counted = dict(zip(names, map(float, usage[start])))
        for item in self.setup:
            counted[item] = counted.get(item, 0) + 1
        return Plan(self, start, policy, spending, counted, fracture_counted)


def solve_modes(planners: dict[str, Planner], start: State) -> dict[str, "Plan"]:
    """Both modes of one goal. The one with more actions searches, the other reuses that search, which halves the time and the memory of a large goal."""
    order = sorted(planners, key=lambda mode: -len(planners[mode].actions))
    first = planners[order[0]]
    first.keep_explored = True
    plans = {order[0]: first.solve(start)}
    shared, first.explored_out = first.explored_out, None
    try:
        for mode in order[1:]:
            plans[mode] = planners[mode].solve(start, shared)
    finally:
        if shared:
            let_go_slowly(shared[0])
    return {mode: plans[mode] for mode in planners}


@dataclass
class Plan:
    planner: Planner
    start: State
    policy: dict[State, Action]
    values: dict[State, float]
    usage: dict[str, float]
    fracture_counted: bool = True
    simulation: object = None  # None until asked for, then SIMULATING, then a Simulation, or False if the plan is too long to test

    @property
    def attempts(self) -> float:
        """Average number of tries: the first base plus every new base the plan takes."""
        return 1 + self.usage.get(NEW_BASE, 0)

    @property
    def action_count(self) -> float:
        """Average number of orbs thrown and bases taken, without counting omens twice."""
        return sum(count for name, count in self.usage.items() if name not in OMENS and name != CATALYSING_OMEN and name not in CATALYST_TAGS)

    @property
    def uses_desecration(self) -> bool:
        return any(count > 1e-6 and name.endswith(("Jawbone", "Rib", "Collarbone")) for name, count in self.usage.items())

    @property
    def uses_catalysts(self) -> bool:
        return self.usage.get(CATALYSING_OMEN, 0) > 1e-6

    def outcomes(self, state: State) -> list[tuple[State, float]]:
        return sorted(self.planner.outcomes(state, self.policy[state]).items(), key=lambda entry: -entry[1])

    def route(self, start: State | None = None, max_steps: int = 12) -> list[tuple[Action, float]]:
        """The most likely successful route with the chance of progress at each step."""
        steps, state, visited = [], start or self.start, set()
        while state in self.policy and state not in visited and len(steps) < max_steps:
            visited.add(state)
            outcomes = dict(self.outcomes(state))
            progress = {s: p for s, p in outcomes.items() if s.status.count(HIT) > state.status.count(HIT)}
            steps.append((self.policy[state], sum(progress.values())))
            options = progress or {s: p for s, p in outcomes.items() if s != state}
            state = max(options, key=options.get)
        return steps


SIMULATING = "running"
SIMULATION_RUNS = 2000
SIMULATION_STEP_BUDGET = 2_000_000  # keeps the check to a couple of seconds, however long the plan is
FEWEST_SIMULATION_RUNS = 100  # fewer say nothing about bad luck


@dataclass(frozen=True)
class Simulation:
    runs: int
    mean: float
    median: float
    unlucky: float  # 9 runs of 10 stay at or below this
    worst: float  # 1 run of 100 goes above this
    costs: tuple[float, ...] = ()  # every run, cheapest first

    def chance_within(self, budget: float) -> float:
        return bisect.bisect_right(self.costs, budget) / len(self.costs) if self.costs else 0.0


def simulate_plan(plan: Plan, runs: int = SIMULATION_RUNS, rng: random.Random | None = None, budget: int = SIMULATION_STEP_BUDGET) -> Simulation | None:
    """Plays the plan many times with random results. The average checks the calculation; the spread shows what bad luck costs."""
    rng = rng or random.Random()
    moves: dict[State, tuple[list[State], list[float], float]] = {}
    costs = []
    while len(costs) < runs:
        state, total = plan.start, plan.planner.setup_cost
        while state in plan.policy and budget > 0:
            budget -= 1
            if state not in moves:
                outcomes = plan.outcomes(state)
                chances = np.cumsum([chance for _, chance in outcomes]).tolist()
                base_cost = plan.planner.cost(plan.policy[state])
                orb_cost = plan.planner.lock_choices[state][3] if plan.policy[state].family == "lock" else {}  # under the Lock the orb used depends on the result
                moves[state] = [found for found, _ in outcomes], chances, [base_cost + orb_cost.get(found, 0.0) for found, _ in outcomes]
            targets, chances, costs_by_result = moves[state]
            picked = min(bisect.bisect(chances, rng.random() * chances[-1]), len(targets) - 1)
            total += costs_by_result[picked]
            state = targets[picked]
        if state in plan.policy:
            break  # out of budget in the middle of a run, which must not count as a finished one
        costs.append(total)
    if len(costs) < min(runs, FEWEST_SIMULATION_RUNS):
        return None
    costs.sort()
    return Simulation(len(costs), sum(costs) / len(costs), costs[len(costs) // 2], costs[int(len(costs) * 0.9)], costs[int(len(costs) * 0.99)], tuple(costs))


SURER_MARGIN = 0.95  # below this share a plan's bad luck is cheaper enough to mention


def surer_mode(plans: dict[str, Plan]) -> str | None:
    """The plan whose bad luck costs clearly less. It need not be the one that is cheapest on average."""
    results = {mode: plan.simulation for mode, plan in plans.items() if isinstance(plan.simulation, Simulation)}
    if len(results) < len(plans) or len(results) < 2:
        return None
    best = min(results, key=lambda mode: results[mode].unlucky)
    return best if all(mode == best or results[best].unlucky <= results[mode].unlucky * SURER_MARGIN for mode in results) else None


def budget_advice(plans: dict[str, Plan], mode: str, budget: float, alternatives: list[dict] | None) -> tuple[float | None, str | None, str | None]:
    """The chance that the chosen plan fits the budget, a mode that fits it clearly better, and a simpler goal that fits on average."""
    own = plans[mode].simulation
    if not isinstance(own, Simulation):
        return None, None, None
    chance = own.chance_within(budget)
    better = None
    for other, plan in plans.items():
        if other != mode and isinstance(plan.simulation, Simulation) and plan.simulation.chance_within(budget) >= chance + 0.05:
            better = other
    goal = next((option["label"] for option in alternatives or () if option["cost"] <= budget), None) if plans[mode].values.get(plans[mode].start, 0) > budget else None
    return chance, better, goal


def goal_notes(planner: Planner) -> list[str]:
    """What the list of mods alone does not say: how many of the group are needed, and which places stay free."""
    notes = [t("Нужно {need} из {count} отмеченных ◇").format(need=planner.need, count=len(planner.group))] if planner.need else []
    free = [t("{count} преф.").format(count=count) if side == "prefix" else t("{count} суфф.").format(count=count) for side, count in planner.open_slots.items() if count]
    return notes + ([t("Свободным останется: {places}").format(places=", ".join(free))] if free else [])


def recipe_text(plan: Plan, title: str, cost: str) -> str:
    """The plan as plain text, to paste anywhere."""
    lines = [title, t("Цель:"), *(f"- {want.label}{'  ◇' if want.need else ''}" for want in plan.planner.wants), *goal_notes(plan.planner), t("В среднем с начала: {cost}").format(cost=cost), t("Дальше примерно так:")]
    for number, (action, count, chance) in enumerate(merge_route(plan.route()), 1):
        times = f" × {count}" if count > 1 else ""
        odds = f" ({chance:.0%})" if chance else ""
        lines.append(f"{number}. {action.label}{times}{odds}")
    return "\n".join(lines)


def omen_text(name: str) -> str:
    family, side, count = OMENS[name]
    if name == OMEN_OF_LIGHT:
        return t("Сфера отмены уберёт только очернённый мод.")
    if name == OMEN_OF_ECHOES:
        return t("При раскрытии можно один раз перебросить варианты.")
    if name in LICH_OMENS:
        return t("Кость на оружии или бижутерии точно предложит мод лича {lich}.").format(lich=t(LICH_SHOWN[LICH_OMENS[name]]))
    if name == OMEN_OF_WHITTLING:
        return t("Сфера хаоса уберёт мод самого низкого уровня.")
    if family == "perfect_essence":
        return t("Совершенная эссенция уберёт только префикс.") if side == "prefix" else t("Совершенная эссенция уберёт только суффикс.")
    orb = next(currency[0] for currency in CURRENCIES.values() if currency[1] == family)
    words = [t("Действует на: {orb}.").format(orb=show_currency(orb) if orb else t("кости Бездны"))]
    if side:
        words.append(t("Только префиксы.") if side == "prefix" else t("Только суффиксы."))
    if count > 1:
        words.append(t("Сразу 2 мода."))
    return " ".join(words)


def format_price(value: float) -> str:
    if value >= 100:
        return f"{value:,.0f}".replace(",", " ")
    if value >= 1:
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{value:.3f}".rstrip("0").rstrip(".") or "0"


def format_age(days: float) -> str:
    if not math.isfinite(days):
        return "—"
    minutes = days * 1440
    if minutes < 60:
        return t("{count} мин").format(count=max(int(minutes), 1))
    if minutes < 2880:
        return t("{count} ч").format(count=int(minutes / 60))
    return t("{count} д").format(count=int(days))


def price_section(name: str, stored: dict) -> str:
    kind = stored.get("kinds", {}).get(name)
    if not kind and name.startswith("Omen"):
        kind = "Ritual"
    elif not kind:
        kind = "Essences" if "Essence" in name else "Currency"
    return OTHER_SECTION if (kind == "Currency" and name not in CORE_CURRENCY) or kind not in TAB_KINDS else kind


def tab_icon_item(tab: str, stored: dict) -> str | None:
    """The item whose picture marks a section's tab."""
    chosen = TAB_ICON_ITEMS.get(tab)
    if chosen:
        return chosen
    names = [name for name in stored.get("prices_in_divine", {}) if price_section(name, stored) == tab]
    volumes = stored.get("volumes", {})
    return max(names, key=lambda name: volumes.get(name) or 0, default=None)


def price_source(tab: str) -> str:
    """The poe.ninja section that holds a tab's prices."""
    return "Currency" if tab == OTHER_SECTION else tab


def format_amount(amount: float, unit: str) -> str:
    """Divine keeps its decimals. Chaos and Exalted are small coins, so whole numbers read best once they are large."""
    if not math.isfinite(amount):
        return "—"
    if 0 < amount < 0.001:
        return "<0.001"
    if unit == "Divine Orb":
        return format_price(amount)
    return format_price(round(amount) if amount >= 10 else round(amount, 1) if amount >= 0.95 else round(amount, 2))


def format_cost(exalted: float, exalted_per_divine: float, chaos_per_divine: float | None = None) -> str:
    if not exalted_per_divine:
        return f"{format_amount(exalted, 'Exalted Orb')} {UNIT_LABELS['Exalted Orb']}"
    amount, unit = best_unit(exalted / exalted_per_divine, exalted_per_divine, chaos_per_divine)
    return f"{format_amount(amount, unit)} {UNIT_LABELS[unit]}"


def describe_state(state: State, wants: list[Want]) -> str:
    parts = []
    done = [w.ladder.title for w, s in zip(wants, state.status) if s == HIT]
    wrong = [w.ladder.title for w, s in zip(wants, state.status) if s == WRONG_TIER]
    if done:
        parts.append("✓ " + "; ".join(done))
    if wrong:
        parts.append(t("слабый тир: {title}").format(title="; ".join(wrong)))
    if state.junk_prefix or state.junk_suffix:
        parts.append(t("лишние: {prefixes} преф., {suffixes} суфф.").format(prefixes=state.junk_prefix, suffixes=state.junk_suffix))
    if state.locked >= 0:
        parts.append(t("закреплён: {title}").format(title=wants[state.locked].ladder.title))
    elif state.locked != UNLOCKED:
        parts.append(t("закреплён лишний мод"))
    if state.desecrated != NOT_DESECRATED:
        parts.append(t("уже очернён"))
    return "  •  ".join(parts) or t("нужного нет")


def describe_change(old: State, new: State, wants: list[Want]) -> str:
    """Says only what a step changed, so the list of results stays short."""
    parts = []
    for want, before, after in zip(wants, old.status, new.status):
        if before != after:
            title = want.ladder.title
            parts.append({HIT: f"✓ {title}", WRONG_TIER: t("слабый тир: {title}").format(title=title)}.get(after, t("пропал: {title}").format(title=title)))
    for delta, added, removed in ((new.junk_prefix - old.junk_prefix, "лишний префикс", "убран лишний префикс"),
                                  (new.junk_suffix - old.junk_suffix, "лишний суффикс", "убран лишний суффикс")):
        if delta:
            parts.append(t(added if delta > 0 else removed) + (f" × {abs(delta)}" if abs(delta) > 1 else ""))
    if new.locked != old.locked:
        parts.append(t("закреплён: {title}").format(title=wants[new.locked].ladder.title) if new.locked >= 0 else t("закреплён лишний мод"))
    return "  •  ".join(parts) or t("ничего полезного")


def explain_action(action: Action, state: State) -> str:
    """Plain words about what the step does to the item."""
    family, floor = action.family, action.floor
    if family == "new_base":
        return t("Выгоднее заменить предмет, чем чинить этот.")
    if family == "lock":
        return t("Наложите Прядь Хинекоры и посмотрите, что дадут сферы хаоса, возвышения и отмены всех уровней. Примените ту, что даёт лучший результат: Прядь сгорит вместе с ней.")
    if OMEN_OF_LIGHT in action.omens:
        return t("Уберёт только очернённый мод, после этого предмет можно очернить снова.")
    two = action.count > 1
    sentences = [t({
        "transmutation": "Сделает обычный предмет волшебным и добавит 1 случайный мод.",
        "augmentation": "Добавит волшебному предмету второй случайный мод.",
        "alchemy": "Сделает предмет редким с 4 случайными модами. Старые моды пропадут.",
        "regal": "Сделает предмет редким и добавит 1 случайный мод.",
        "essence": "Сделает предмет редким и гарантированно добавит нужный мод.",
        "perfect_essence": "Уберёт 1 случайный мод и гарантированно добавит нужный.",
        "exalted": "Добавит 2 случайных мода." if two else "Добавит 1 случайный мод.",
        "chaos": "Уберёт мод самого низкого уровня и добавит новый." if OMEN_OF_WHITTLING in action.omens else "Уберёт 1 случайный мод и добавит новый.",
        "annulment": "Уберёт 2 случайных мода." if two else "Уберёт 1 случайный мод.",
        "fracture": "Навсегда закрепит 1 случайный мод: его больше нельзя будет убрать.",
        "desecrate": "Добавит скрытый мод. Раскройте его и выберите лучший из вариантов.",
    }[family])]
    if action.side and family == "perfect_essence":
        sentences.append(t("Убирает только префиксы." if action.side == "prefix" else "Убирает только суффиксы."))
    elif action.side:
        sentences.append(t("Только префиксы." if action.side == "prefix" else "Только суффиксы."))
    if action.catalyst:
        sentences.insert(0, t("Сначала заточите предмет катализаторами до предела, это около {count} шт. «{catalyst}», и активируйте знамение.").format(count=action.catalysts, catalyst=show_currency(action.catalyst)))
        sentences.append(t("Качество сгорит, а моды этого типа выпадут с повышенным шансом, но не наверняка."))
    if OMEN_OF_ECHOES in action.omens:
        sentences.append(t("При раскрытии можно один раз перебросить варианты."))
    for omen in action.omens:
        if omen in LICH_OMENS:
            sentences.append(t("Один из вариантов точно будет модом лича {lich}.").format(lich=t(LICH_SHOWN[LICH_OMENS[omen]])))
    if OMEN_OF_WHITTLING in action.omens:
        sentences.append(t("Шанс оценён по уровням возможных модов."))
    if floor:
        sentences.append(t("Новые моды будут уровня {level}+.").format(level=floor))
    if family in ("chaos", "annulment", "perfect_essence") and state.locked != UNLOCKED:
        sentences.append(t("Закреплённый мод не тронет."))
    return " ".join(sentences)


def merge_route(steps: list[tuple[Action, float]]) -> list[tuple[Action, int, float]]:
    """Joins repeated steps, so three Exalted Orbs in a row read as one line."""
    merged: list[tuple[Action, int, float]] = []
    for action, chance in steps:
        if merged and merged[-1][0] == action:
            merged[-1] = (action, merged[-1][1] + 1, max(merged[-1][2], chance))
        else:
            merged.append((action, 1, chance))
    return merged


def cheaper_goals(page: Page, ilvl: int, wants: list[Want], prices: dict[str, float], state_for, current_cost: float, mode: str | None = None, base: str = "",
                  open_slots: dict | None = None, cancelled=None) -> list[dict]:
    """Finds simpler goals worth taking: the nearest lower tier that saves enough, then the goal without one mod. Each is a whole plan, so they stop with their plan."""
    def cost_of(variant: list[Want]) -> float:
        start = state_for(variant)
        return Planner(page, ilvl, variant, prices, mode, base, open_slots, cancelled).solve(start).values.get(start, 0.0)

    lower_tiers, fewer_mods = [], []
    for index, want in enumerate(wants):
        others = wants[:index] + wants[index + 1:]
        for tier in range(want.min_tier + 1, len(want.ladder.mods) + 1):
            variant = wants[:index] + [replace(make_want(want.ladder, tier, ilvl), need=want.need)] + wants[index + 1:]
            cost = cost_of(variant)
            if cost <= current_cost * ALTERNATIVE_MIN_SAVING:
                label = t("{title}: T{old} → T{new}").format(title=want.ladder.title, old=want.min_tier, new=tier)
                lower_tiers.append({"label": label, "wants": variant, "cost": cost})
                break
        if others:
            cost = cost_of(others)
            if cost <= current_cost * ALTERNATIVE_MIN_SAVING:
                fewer_mods.append({"label": t("Без мода: {title}").format(title=want.ladder.title), "wants": others, "cost": cost})
    by_cost = lambda option: option["cost"]
    return (sorted(lower_tiers, key=by_cost) + sorted(fewer_mods, key=by_cost))[:ALTERNATIVES_SHOWN]


# -------------------------------------------------------------- clipboard item
# The game writes e.g. { Prefix Modifier "Name" (Tier: 1) } or { Префикс "Имя" (Уровень: 1) }.
MOD_HEADER = re.compile(r'^\{[^"\n]*?(Prefix|Suffix|Префикс|Суффикс)[^"\n]*"([^"]+)"', re.MULTILINE | re.IGNORECASE)
FRACTURED_HEADER = re.compile(r'^\{[^"\n]*?(?:Fractured|Расколот)[^"\n]*?(Prefix|Suffix|Префикс|Суффикс)[^"\n]*"([^"]+)"', re.MULTILINE | re.IGNORECASE)
DESECRATED_HEADER = re.compile(r'^\{[^"\n]*?(?:Desecrated|Очерн[её]н)[^"\n]*?(Prefix|Suffix|Префикс|Суффикс)[^"\n]*"([^"]+)"[^\n]*\n([^\n]*)', re.MULTILINE | re.IGNORECASE)
UNREVEALED_MOD = re.compile(r'^\{?[^\n]*(?:Unrevealed|Нераскрыт)', re.MULTILINE | re.IGNORECASE)
MOD_SIDES = {"prefix": "prefix", "префикс": "prefix", "suffix": "suffix", "суффикс": "suffix"}
RARITIES = {"normal": "normal", "обычный": "normal", "magic": "magic", "волшебный": "magic", "rare": "rare", "редкий": "rare"}


@dataclass
class ParsedItem:
    base: str
    ilvl: int
    rarity: str
    name: str
    mods: list[tuple[str, str]]
    corrupted: bool
    fractured: tuple[str, str] | None = None
    desecrated: tuple[str, str, str] | None = None  # side, name and the mod's first line


def parse_item(text: str, db: Database) -> ParsedItem:
    text = text.replace("\r\n", "\n").strip()
    if not text.startswith(("Item Class:", "Класс предмета:")):
        raise ValueError(t("Не удалось прочитать предмет: держите курсор на нём или выберите базу вручную"))
    header = text.split("--------")[0].strip().split("\n")
    rarity_line = next((line for line in header if line.startswith(("Rarity:", "Редкость:"))), "")
    rarity_text = rarity_line.partition(":")[2].strip()
    rarity = RARITIES.get(rarity_text.casefold())
    if not rarity:
        raise ValueError(t("Этот предмет нельзя крафтить здесь: редкость «{rarity}»").format(rarity=rarity_text or t("нет")))
    if re.search(r"^(Unidentified|Неопознано)\b", text, re.MULTILINE):
        raise ValueError(t("Сначала опознайте предмет"))
    if UNREVEALED_MOD.search(text):
        raise ValueError(t("Сначала раскройте очернённый мод, потом скопируйте предмет ещё раз"))
    base_line = header[-1].strip()
    candidates = [shown for shown in db.names if shown in base_line.casefold()]
    if not candidates:
        raise ValueError(t("База «{base}» не поддерживается: нет данных о модах").format(base=base_line))
    level = re.search(r"^(?:Item Level|Уровень предмета): (\d+)", text, re.MULTILINE)
    if not level:
        raise ValueError(t("В описании предмета нет уровня предмета"))
    mods = [(MOD_SIDES[side.casefold()], name) for side, name in MOD_HEADER.findall(text)]
    corrupted = bool(re.search(r"^(Corrupted|Осквернено)\s*$", text, re.MULTILINE))
    fractured = FRACTURED_HEADER.search(text)
    desecrated = DESECRATED_HEADER.search(text)
    return ParsedItem(db.names[max(candidates, key=len)], int(level.group(1)), rarity, header[2].strip() if len(header) > 2 else base_line,
                      mods, corrupted, (MOD_SIDES[fractured.group(1).casefold()], fractured.group(2)) if fractured else None,
                      (MOD_SIDES[desecrated.group(1).casefold()], desecrated.group(2), desecrated.group(3).strip()) if desecrated else None)


# ------------------------------------------------------------------- overlay
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT, WM_HOTKEY = 0x0001, 0x0002, 0x0004, 0x4000, 0x0312
WM_RELOAD_HOTKEYS = 0x8001
VK_SHIFT, VK_CONTROL, VK_MENU, VK_C, KEYEVENTF_KEYUP = 0x10, 0x11, 0x12, 0x43, 0x0002
DEFAULT_HOTKEYS = {"copy": {"mods": MOD_CONTROL, "vk": 0x45}, "toggle": {"mods": MOD_CONTROL, "vk": 0x52}, "price": {"mods": MOD_CONTROL, "vk": 0x44}}
HOTKEY_ACTIONS = ("copy", "toggle", "price")  # the position plus one is the id given to Windows
RESERVED_HOTKEYS = {(MOD_CONTROL, ord(key)) for key in "ACVXZ"} | {(MOD_CONTROL | MOD_ALT, VK_C)}  # Ctrl+Alt+C is what reads the item
TK_SHIFT, TK_CONTROL, TK_ALT = 0x0001, 0x0004, 0x20000
COPY_TIMEOUT_SECONDS = 1.0
AUTHOR = "Divine"
GREETING = f"To all exiles, from {AUTHOR}."
ABOUT_LINES = (
    "Made so nobody has to guess what to slam next.",
    "Hover an item, press Ctrl+E, pick the mods you want and follow the steps.",
    "Good luck with your crafts, exile.",
)
ABOUT_CREDITS = "Mods and weights: poe2db  •  Items and art: RePoE  •  Prices: poe.ninja, poe2scout  •  Drop sources: poe2wiki.net  •  Desecrated mod weight: POE2_HTC\nThis product isn't affiliated with or endorsed by Grinding Gear Games in any way."
# The author's wallet for those who want to say thanks. Only copied for the player to paste into their own wallet; nothing is sent anywhere.
SUPPORT_ADDRESS = "TVwS7gPpNCBY1PAzAbgciWiJJoYQZDFzz1"
SUPPORT_NETWORK = "USDT, Tron (TRC20)"
NORMAL_PRIORITY, BELOW_NORMAL_PRIORITY = 0x0020, 0x4000
POLL_MS = 16  # how soon a hotkey's result reaches the window
SCROLL_PIXELS = 110
SCROLL_KEY_PIXELS = 65
SEARCH_DELAY_MS = 120
PRICE_CARD_WIDTH, PRICE_CARD_HEIGHT, PRICE_CARD_GAP = 250, 104, 6
PRICE_GRAPH_TOP, PRICE_GRAPH_HEIGHT = 68, 30
PRICE_DRAW_TURN_SECONDS = 0.012  # short enough that the window keeps answering between turns
LONGEST_CARD_NAME = 44
SECTIONS_PER_LINE = 6  # 16 sections in three lines; at 8 the Russian names do not fit a small screen
INTRO_SECONDS = 2.2
GOALS_ON_START = 6
LOADING_SWITCH_SECONDS, NORMAL_SWITCH_SECONDS = 0.001, 0.005
APP_NAME = "Sakuya"
AUTO_LEAGUE, AUTO_HARDCORE = "auto", "auto_hc"
MOD_NUMBER = re.compile(r"\((\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\)|(\d+(?:\.\d+)?)")
PERMANENT_LEAGUES = frozenset({"Standard", "Hardcore"})
VERSION = "1.3.1"
GITHUB_REPOSITORY = "dcser1Co1a/sakuya-poe2"  # "owner/name"; empty means the program does not look for new versions
GITHUB_PAGE = f"https://github.com/{GITHUB_REPOSITORY}"
ISSUES_PAGE = f"{GITHUB_PAGE}/issues/new/choose"
LEFTOVER_RETRY_MS, LEFTOVER_TRIES = 5000, 12  # the copy that was replaced may take a moment to close
UPDATE_TAG_GAP, UPDATE_TAG_PAD_X, UPDATE_TAG_PAD_Y = 6, 18, 7
BASE_SUGGESTIONS_SHOWN, BASE_SUGGESTIONS_CLOSE_MS = 12, 150
PRESET_PANEL_GAP = "0.25c"  # how far from the main window the presets stand, in Tk's centimetres: close beside it
PRESET_PANEL_WIDTH = 220
FORMER_EXE_NAMES = ("poe2crafter.exe", "sakuraforge.exe")  # a copy still running under an old name holds the same hotkeys
MAIN_WINDOW_SIZE = (1140, 860)
MAIN_WINDOW_PLACE = "+40+40"
MINIMIZE_SPOT = (34, 22)  # the corner of the banner that hides the window
REOPEN_ARGUMENT = "--reopen="
RESTART_WAIT_MS = 30000
HOT_COLOR = ACCENT
NAV_ICONS = {"craft": "Chaos Orb", "build": "Orb of Chance", "drops": "Orb of Alchemy", "prices": "Exalted Orb", "demand": "Mirror of Kalandra", "tools": "Artificer's Orb", "settings": "Blacksmith's Whetstone", "about": "Divine Orb"}
MODE_ICONS = {"budget": "Orb of Transmutation", "endgame": "Perfect Exalted Orb"}
MODE_TITLES = {"budget": "Дешевле всего", "endgame": "Меньше действий"}
ROUTE_STEPS_SHOWN = 6
FONT = BODY
GIL_TURN_SECONDS = 0.001  # The window lets go of Python at each call into Tk, and by default waits 5 ms to get it back from a thread that is busy, which adds up to whole frames.
user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_CLOSE_ACCESS = 0x00100001  # SYNCHRONIZE | PROCESS_TERMINATE
CLOSE_WAIT_MS = 3000


def hotkey_label(hotkey: dict) -> str:
    mods, vk = hotkey["mods"], hotkey["vk"]
    if 0x70 <= vk <= 0x87:
        key = f"F{vk - 0x6F}"
    elif 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        key = chr(vk)
    else:
        key = f"#{vk}"
    prefix = ("Ctrl+" if mods & MOD_CONTROL else "") + ("Alt+" if mods & MOD_ALT else "") + ("Shift+" if mods & MOD_SHIFT else "")
    return prefix + key


TEXT_FIELD_CLASSES = ("Entry", "TEntry", "TCombobox", "Text")
# Windows key codes, the same in every layout: Tk's own shortcuts go by the letter, so with a Russian layout Ctrl+V types nothing.
FIELD_KEYS = {86: "<<Paste>>", 67: "<<Copy>>", 88: "<<Cut>>", 90: "<<Undo>>"}
KEY_A, KEY_BACKSPACE = 65, 8


def field_shortcut(event) -> str | None:
    """Ctrl+V, C, X and Z by the key rather than the letter, Ctrl+A selects everything, Ctrl+Backspace deletes a word."""
    widget = event.widget
    if not event.state & TK_CONTROL:
        return None
    if event.keycode == KEY_A:
        if isinstance(widget, tk.Text):
            widget.tag_add("sel", "1.0", "end-1c")
        else:
            widget.select_range(0, "end")
            widget.icursor("end")
        return "break"
    if event.keycode == KEY_BACKSPACE and not isinstance(widget, tk.Text):
        text, end = widget.get(), widget.index("insert")
        start = len(text[:end].rstrip()) - len(text[:end].rstrip().split(" ")[-1]) if text[:end].strip() else 0
        widget.delete(start, end)
        return "break"
    action = FIELD_KEYS.get(event.keycode)
    if action:  # Tk runs one binding of a class per key, so this is the only paste: no double with its own
        widget.event_generate(action)
        return "break"
    return None


def hotkey_from_event(state: int, keycode: int) -> dict:
    """On Windows Tk reports the virtual key, so the bind does not depend on the keyboard layout."""
    mods = (MOD_CONTROL if state & TK_CONTROL else 0) | (MOD_ALT if state & TK_ALT else 0) | (MOD_SHIFT if state & TK_SHIFT else 0)
    return {"mods": mods, "vk": keycode}


def hotkey_problem(hotkey: dict, action: str, hotkeys: dict) -> str | None:
    mods, vk = hotkey["mods"], hotkey["vk"]
    if not mods & (MOD_CONTROL | MOD_ALT) and not 0x70 <= vk <= 0x87:
        return t("Нужен Ctrl или Alt, либо клавиша F1-F24")
    if (mods, vk) in RESERVED_HOTKEYS:
        return t("{name} занято системой или самой программой").format(name=hotkey_label(hotkey))
    if any(other == hotkey for name, other in hotkeys.items() if name != action):
        return t("Это сочетание уже назначено на другое действие")
    return None


def copies_to_close(processes: list[tuple[int, int, str]], own_pid: int, own_parent: int, exe_name: str) -> list[int]:
    """processes are (pid, parent, name). A packed program is a starter and the program it runs.
    Only the program is closed, so the starter can still remove its temporary files."""
    same = {pid: parent for pid, parent, name in processes if name.casefold() == exe_name.casefold()}

    def is_starter(pid: int) -> bool:
        """A program started by the theme button is a child of the old program, so having a child is not enough: starters and programs alternate down the family."""
        depth, seen = 0, {pid}
        while same[pid] in same and same[pid] not in seen:
            pid = same[pid]
            seen.add(pid)
            depth += 1
        return depth % 2 == 0

    parents = set(same.values())
    return [pid for pid in same if pid not in (own_pid, own_parent) and not (pid in parents and is_starter(pid))]


def under_one_name(processes: list[tuple[int, int, str]], exe_name: str) -> list[tuple[int, int, str]]:
    return [(pid, parent, exe_name if name.casefold() in FORMER_EXE_NAMES else name) for pid, parent, name in processes]


def main_window_geometry(screen_width: int, screen_height: int, place: str = MAIN_WINDOW_PLACE) -> str:
    """The one size of the main window, smaller only where the screen itself is."""
    return f"{min(MAIN_WINDOW_SIZE[0], screen_width - 20)}x{min(MAIN_WINDOW_SIZE[1], screen_height - 80)}{place}"


def in_minimize_spot(x: int, y: int, banner_width: int) -> bool:
    return x >= banner_width - MINIMIZE_SPOT[0] and y < MINIMIZE_SPOT[1]


def place_to_reopen(arguments: list[str]) -> str | None:
    """Where the previous copy's window stood, when this copy was started by the theme button."""
    for argument in arguments:
        if argument.startswith(REOPEN_ARGUMENT) and re.fullmatch(r"\+-?\d+\+-?\d+", argument[len(REOPEN_ARGUMENT):]):
            return argument[len(REOPEN_ARGUMENT):]
    return None


class ProcessEntry(ctypes.Structure):
    _fields_ = [("size", ctypes.wintypes.DWORD), ("usage", ctypes.wintypes.DWORD), ("pid", ctypes.wintypes.DWORD), ("heap", ctypes.c_size_t), ("module", ctypes.wintypes.DWORD),
                ("threads", ctypes.wintypes.DWORD), ("parent", ctypes.wintypes.DWORD), ("priority", ctypes.c_long), ("flags", ctypes.wintypes.DWORD), ("name", ctypes.c_wchar * 260)]


def close_other_copies() -> None:
    """A copy left running keeps the hotkeys, so the new one would seem to do nothing. The newest start always wins."""
    if not user32 or not getattr(sys, "frozen", False):
        return
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.OpenProcess.restype = ctypes.c_void_p
    for function in (kernel32.Process32FirstW, kernel32.Process32NextW):
        function.argtypes = (ctypes.c_void_p, ctypes.POINTER(ProcessEntry))
    for function in (kernel32.TerminateProcess, kernel32.WaitForSingleObject):
        function.argtypes = (ctypes.c_void_p, ctypes.wintypes.DWORD)
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    entry = ProcessEntry(size=ctypes.sizeof(ProcessEntry))
    processes = []
    found = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
    while found:
        processes.append((entry.pid, entry.parent, entry.name))
        found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    kernel32.CloseHandle(snapshot)
    exe_name = os.path.basename(sys.executable)
    watcher = game_watch.watcher_pids(Path(sys.executable), processes)  # the watcher that opens Sakuya with the game is no copy of it
    for pid in [pid for pid in copies_to_close(under_one_name(processes, exe_name), os.getpid(), os.getppid(), exe_name) if pid not in watcher]:
        handle = kernel32.OpenProcess(PROCESS_CLOSE_ACCESS, False, pid)
        if handle:
            kernel32.TerminateProcess(handle, 0)
            kernel32.WaitForSingleObject(handle, CLOSE_WAIT_MS)  # its hotkeys are free only once it is gone
            kernel32.CloseHandle(handle)


def set_process_priority(priority: int) -> None:
    """While a plan is solved the game keeps priority over this program."""
    if not user32:
        return
    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.wintypes.DWORD)
    kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), priority)


class IconStore:
    """Item art from RePoE, downloaded once and kept in icons.json next to the program."""

    def __init__(self, on_changed):
        self.raw: dict[str, str] = text_map(read_json(ICONS_PATH))
        self.images: dict[tuple[str, int], tk.PhotoImage] = {}
        self.tile_images: dict[tuple[str, str], tk.PhotoImage] = {}
        self.wanted: queue.Queue = queue.Queue()
        self.requested: set[str] = set()
        threading.Thread(target=keep_running, args=(run_icon_downloads, self.wanted, self.raw, on_changed), daemon=True).start()

    def on_tile(self, path: str | None, ground: str) -> tk.PhotoImage | None:
        """A full-size icon already laid on its tile. Whole pixels are copied on a redraw, where blended ones are worked out anew."""
        plain = self.get(path)
        if not plain:
            return None
        key = (path, ground)
        if key not in self.tile_images:
            try:
                picture = Image.open(io.BytesIO(base64.b64decode(self.raw[path]))).convert("RGBA")
                laid = Image.new("RGB", picture.size, ImageColor.getrgb(ground))
                laid.paste(picture, mask=picture.getchannel("A"))
                output = io.BytesIO()
                laid.save(output, "PNG", compress_level=1)
                self.tile_images[key] = tk.PhotoImage(data=base64.b64encode(output.getvalue()).decode("ascii"))
            except (OSError, ValueError, KeyError, tk.TclError):
                self.tile_images[key] = plain
        return self.tile_images[key]

    def stored(self, path: str | None) -> str | None:
        """The picture as it is kept, asked for if it is not here yet."""
        if not path:
            return None
        encoded = self.raw.get(path)
        if encoded is None and path not in self.requested:
            self.requested.add(path)
            self.wanted.put(path)
        return encoded or None

    def get(self, path: str | None, size: int = ICON_SIZE) -> tk.PhotoImage | None:
        encoded = self.stored(path)
        if not encoded:
            return None
        if (path, size) not in self.images:
            try:
                image = tk.PhotoImage(data=encoded)
            except tk.TclError:  # a damaged picture must not stop the page it sits on; it is downloaded again on the next start
                self.raw.pop(path, None)
                return None
            self.images[(path, size)] = image if size >= ICON_SIZE else image.subsample(ICON_SIZE // size)
        return self.images[(path, size)]


def normalize_search(text: str) -> str:
    return text.casefold().replace("ё", "е")


def matches_search(query: str, text: str) -> bool:
    """Every word of the query must occur in the text, whatever its ending. One-letter words like «и» are ignored."""
    words = [word for word in re.split(r"[^\w%+]+", normalize_search(query)) if len(word) > 1 or word.isdigit()]
    text = normalize_search(text)
    return all((word[:-2] if len(word) > 4 else word[:-1] if len(word) == 4 else word) in text for word in words)


def send_copy_keys(game_window: int | None, hotkey: dict) -> bool:
    """Presses Ctrl+Alt+C in the game and waits for the clipboard to change. It is one key press per hotkey."""
    if game_window:
        user32.SetForegroundWindow(game_window)
        time.sleep(0.05)
    deadline = time.monotonic() + 0.4
    # Held Shift would turn the game's copy keys into something else.
    held = [hotkey["vk"]] + ([VK_SHIFT] if hotkey["mods"] & MOD_SHIFT else [])
    while any(user32.GetAsyncKeyState(key) & 0x8000 for key in held) and time.monotonic() < deadline:
        time.sleep(0.01)
    sequence = user32.GetClipboardSequenceNumber()
    for key in (VK_CONTROL, VK_MENU, VK_C):
        user32.keybd_event(key, 0, 0, 0)
        time.sleep(0.015)
    for key in (VK_C, VK_MENU, VK_CONTROL):
        user32.keybd_event(key, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.015)
    deadline = time.monotonic() + COPY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if user32.GetClipboardSequenceNumber() != sequence:
            time.sleep(0.03)
            return True
        time.sleep(0.02)
    return False


class App:
    show_details = False
    new_release: Release | None = None
    updating = False
    update_box = update_tag = update_tag_words = None
    base_popup = base_list = None
    preset_panel = None
    picker_open = False
    root_place: tuple[int, int] | None = None
    base_suggestions: list[str] = []
    base_icon_label = None
    current_tab = "prices"
    alternatives_box = None
    search_job = None
    plans = None
    copy_busy = False
    price_window = None
    place_job = None
    trade_panel = None
    tray = None
    closing = False
    main_prepared = False
    scroll_target = None
    switches = None
    solve_token = 0
    solves_running = 0  # plans being worked out; a second is not started beside one, as two large ones would not fit in memory
    upgrade_token = 0
    earlier_check = None
    last_check = None
    trade_page_name = None
    solve_button = None  # the craft page is built when it is first opened
    last_goal = None  # the goal of the last plan, chosen again on the way back to the mods
    watching = False
    trade_stats = None
    trade_item = None
    capturing = None
    capture_bind = None
    hotkey_thread = 0
    tools_page = None
    simulation_box = None
    market_box = None
    budget_box = None
    ban_box = None
    bottom_bar = None
    ban_button = None
    mode_risk = None
    trade_memory_key = None
    petals = None
    loading = None
    changing_language = False
    wheel_handler = None
    settings_current = False
    list_width = 0
    row_wrap = 0
    price_wave = None
    price_draw_job = None
    drag_grip = None
    drag_place = None
    drag_job = None

    def __init__(self, intro: bool = True, reopen: str | None = None):
        if user32:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Divine.Sakuya")  # the taskbar shows our icon
        self.settings = clean_settings(read_json(SETTINGS_PATH) or {})
        if "theme" not in self.settings and not os.environ.get("POE_CRAFTER_THEME"):  # the theme this start chose is kept, so a new player stays in Gold after the settings file appears
            self.settings["theme"] = ACTIVE_THEME
            try:
                write_json(SETTINGS_PATH, self.settings)
            except OSError:
                log_error("saving settings.json")
        league_board.choice = self.settings.get("league_choice")
        set_language(self.settings.get("language", "ru"))
        self.hotkeys = {**DEFAULT_HOTKEYS, **self.settings.get("hotkeys", {})}
        self.craft_mode = self.settings.get("craft_mode", "budget")
        self.base_allowed = {"budget": True, "endgame": False}
        self.solve_prices: dict[str, dict] = {}
        self.root = tk.Tk()
        self.root.withdraw()
        for widget_class in TEXT_FIELD_CLASSES:  # copy, paste, cut and select all work in every field whatever the keyboard layout
            self.root.bind_class(widget_class, "<Control-KeyPress>", field_shortcut, add="+")
            for sequence in ("<Control-a>", "<Control-A>", "<Control-BackSpace>"):  # Tk's own Ctrl+A goes to the start of the line, and its Backspace takes one letter
                self.root.bind_class(widget_class, sequence, field_shortcut)
        self.events: queue.Queue = queue.Queue()
        self.root.report_callback_exception = self._on_window_error
        threading.excepthook = self._on_thread_error
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)  # no button on the taskbar, since the program lives in the tray, and no system cross, which looks like quitting but only hides
        self.root.configure(highlightthickness=1, highlightbackground=BORDER)
        self.root.protocol("WM_DELETE_WINDOW", self.root.withdraw)  # Alt+F4 only hides it too; the tray menu and the settings quit
        self.root.geometry(main_window_geometry(self.root.winfo_screenwidth(), self.root.winfo_screenheight(), place_on_screen(reopen, all_monitors()) or MAIN_WINDOW_PLACE))
        self.root.resizable(False, False)  # stretching redraws the whole window on every step, and the game's frames pay for it
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", self.settings.get("topmost", True))
        self.root.bind("<Escape>", lambda _: self._on_escape())
        self.root.bind_all("<MouseWheel>", lambda event: self.wheel_handler(event) if self.wheel_handler else None)
        self.root.bind("<Map>", lambda event: self._show_petals() if event.widget is self.root else None)
        self.root.bind("<Unmap>", lambda event: self._hide_petals() if event.widget is self.root else None)
        self.reopen = reopen
        for event in ("<Configure>", "<Map>", "<Unmap>"):  # the update tag follows the window, and hides with it
            self.root.bind(event, lambda event: (self._place_update_tag(), self._place_preset_panel()) if event.widget is self.root else None, add="+")
        self.root.bind("<Configure>", self._on_root_moved, add="+")
        self.root.bind("<Unmap>", lambda event: self._hide_base_suggestions() if event.widget is self.root else None, add="+")
        learn_market(clean_market_sections(read_json(MARKET_SECTIONS_PATH) or {}))  # before the pages are built, so a kind found earlier has its tab
        if intro:
            self._show_intro()
        self.db: Database | None = None
        self.prices: dict | None = None
        self.item: ParsedItem | None = None
        self.base: str | None = None
        self.ilvl = 82
        self.rows: list[dict] = []
        self.plan: Plan | None = None
        self.state: State | None = None
        self.spent = 0.0
        self.game_window: int | None = None
        self.stepping_aside = SteppingAside()
        self.own_window = 0
        self.price_tab = "Currency"
        sys.setswitchinterval(GIL_TURN_SECONDS)
        self.icons = IconStore(lambda: self.events.put(("icons", None)))
        uniques = clean_uniques(read_json(UNIQUES_PATH) or {})
        self.unique_art, self.unique_russian, self.item_art = uniques.get("art", {}), uniques.get("russian", {}), uniques.get("items", {})
        self.drops = clean_drops(read_json(DROPS_PATH) or {})
        self.exchange_names = uniques.get("exchange", {})
        self.update_interest = UpdateInterest()
        self.demand = clean_demand(read_json(DEMAND_PATH) or {})
        self.tools_store = clean_tools(read_json(TOOLS_PATH) or {})
        self.waystones = clean_waystones(read_json(WAYSTONES_PATH) or {})
        self.stopwatch = Stopwatch()
        self.banned = set(self.settings.get("craft_banned", ()))
        self.budget_var = tk.StringVar(value=self.settings.get("craft_budget", ""))
        self.budget_var.trace_add("write", lambda *_: self._after_typing(self._on_budget_typed))
        self._build_style()
        self._build_shell()
        self.load_prices()
        self.update_interest.watched = self._watch_sections()
        self.show_tab("prices")
        if intro:
            self.root.after(30, self._finish_start)
        else:
            self._start_services()
            self._show_main()

    def _on_window_error(self, kind, value, trace) -> None:
        """One failed click must not go unnoticed, and must not take anything else down with it."""
        log_error("window", "".join(traceback.format_exception(kind, value, trace)))
        self.events.put(("status", t("Что-то пошло не так, подробности в errors.log")))

    def _on_thread_error(self, failure) -> None:
        log_error(failure.thread.name if failure.thread else "thread", "".join(traceback.format_exception(failure.exc_type, failure.exc_value, failure.exc_traceback)))
        self.events.put(("status", t("Что-то пошло не так, подробности в errors.log")))

    def _save_tools(self) -> None:
        try:
            write_json(TOOLS_PATH, self.tools_store)
        except OSError:
            log_error("saving tools.json")
            self.set_status(t("Не удалось сохранить данные вкладки «Инструменты»"))

    def _loading_screen(self, theme: str) -> LoadingScreen:
        hint = t("{toggle} открывает и прячет окно, {price} показывает цену").format(toggle=hotkey_label(self.hotkeys["toggle"]), price=hotkey_label(self.hotkeys["price"]))
        # A collection on the screen's thread would stop it to release this thread's Tk objects, so it waits, and the threads take turns more often while it is up.
        gc.disable()
        sys.setswitchinterval(LOADING_SWITCH_SECONDS)
        return LoadingScreen(theme, APP_NAME, (GREETING, hint), INTRO_SECONDS)

    def _show_intro(self) -> None:
        """Blossom falls while the program gets ready. The loading screen comes first, so that a copy being replaced is gone only once this one is on screen."""
        self.loading = self._loading_screen(ACTIVE_THEME)
        close_other_copies()
        if self._opens_with_game():  # after an update, or a watcher that ended: it watches again
            try:
                game_watch.start_watcher(Path(sys.executable))
            except OSError:
                log_error("starting the game watcher")
        prepare_art()

    def _opens_with_game(self) -> bool:
        return bool(getattr(sys, "frozen", False) and user32) and game_watch.is_registered(Path(sys.executable))

    def toggle_with_game(self) -> None:
        """Puts the watcher in the user's Run key and starts it, or takes it out; a watcher whose key is gone ends by itself."""
        exe = Path(sys.executable)
        if not getattr(sys, "frozen", False):
            self.with_game_var.set(False)
            return self.set_status(t("Это работает только в Sakuya.exe"))
        try:
            if self.with_game_var.get():
                game_watch.register(exe)
                game_watch.start_watcher(exe)
                self.set_status(t("Sakuya откроется, когда запустится Path of Exile 2"))
            else:
                game_watch.unregister()
                self.set_status(t("Sakuya больше не открывается вместе с игрой"))
        except OSError as error:
            log_error("the game watcher setting")
            self.with_game_var.set(self._opens_with_game())
            self.set_status(t("Не удалось: {error}").format(error=error))

    def _finish_start(self) -> None:
        try:
            self._start_services()
        finally:
            self.loading.finish(self.root, self._on_loaded)

    def _on_loaded(self) -> None:
        """The window opens by itself. After the theme button it comes back to the settings the player was in."""
        screen, self.loading = self.loading, None
        self._when_screen_is_gone(screen)
        if self.reopen:
            self.show_tab("settings")
        self.bring_up()

    def _when_screen_is_gone(self, screen: LoadingScreen) -> None:
        if not screen.gone.is_set():
            self.root.after(100, self._when_screen_is_gone, screen)
            return
        gc.enable()
        sys.setswitchinterval(NORMAL_SWITCH_SECONDS)

    def _on_patch(self) -> None:
        self.update_interest.patch_is_out()
        self.events.put(("status", t("Вышел патч: обновляю базы, как только сайты их выложат")))

    def _show_main(self) -> None:
        self.main_prepared = True
        self.root.deiconify()
        self.root.lift()
        self.root.update_idletasks()
        # An icon set while the window was still hidden does not stick, so it is set again here.
        icon = self.currency_icon("Divine Orb", ICON_SIZE)
        if icon:
            self.root.iconphoto(True, icon)
        if user32:
            self.own_window = user32.GetAncestor(self.root.winfo_id(), 2)

    def _start_services(self) -> None:
        try:
            self.load_data()
            self.show_start()
        except Exception:  # a window with no data still has its hotkeys and will fill itself once the bases come down
            log_error("first drawing")
        if user32:
            threading.Thread(target=self._hotkey_loop, daemon=True).start()
            self._start_tray()
        self.watching = True  # a price that got there while the program was closed is told now, when the tray can say so
        self._check_watches()
        status = lambda text: self.events.put(("status", text))
        threading.Thread(target=keep_running, args=(run_price_updates, status, lambda: self.events.put(("prices", None)), lambda: self.events.put(("demand", None)), self.update_interest), daemon=True).start()
        self.root.bind_all("<Button-1>", lambda _: self.update_interest.mark_active(), add="+")
        for key in ("Up", "Down", "Prior", "Next", "Home", "End"):
            self.root.bind(f"<{key}>", self._on_scroll_key)
        threading.Thread(target=self._saved_trade_stats, args=(language,), daemon=True).start()  # so the first price check does not stall on a large file
        self._price_window()  # built now, hidden, so the first press of the price key opens it without a stall
        watch = PatchWatch(self._on_patch)
        threading.Thread(target=keep_running, args=(run_data_updates, status, lambda: self.events.put(("reload", None)), lambda: self.events.put(("uniques", None)), lambda: self.events.put(("waystones", None)), watch,
                                                    lambda: self.events.put(("trade_stats", None))), daemon=True).start()
        threading.Thread(target=keep_running, args=(run_program_checks, status, lambda release: self.events.put(("new_version", release))), daemon=True).start()
        self._remove_update_leftovers()
        threading.Thread(target=keep_running, args=(run_local_build_watch, watch), daemon=True).start()
        threading.Thread(target=keep_running, args=(run_online_build_watch, watch), daemon=True).start()
        self.root.after(POLL_MS, self._poll)

    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=RAISED, background=RAISED, foreground=TEXT, arrowcolor=SOFT, bordercolor=BORDER,
                        lightcolor=RAISED, darkcolor=RAISED, insertcolor=TEXT, selectbackground=RAISED, selectforeground=TEXT, padding=3)
        style.map("TCombobox", fieldbackground=[("readonly", RAISED)], foreground=[("readonly", TEXT)], background=[("active", BORDER)],
                  bordercolor=[("focus", SOFT)], selectbackground=[("readonly", RAISED)], selectforeground=[("readonly", TEXT)])
        # A thin scrollbar: only a thumb on a track, without arrows.
        style.layout("Thin.Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        style.configure("Thin.Vertical.TScrollbar", arrowsize=7, gripcount=0, background=THUMB, troughcolor=BG,
                        bordercolor=BG, lightcolor=THUMB, darkcolor=THUMB, relief="flat")
        style.map("Thin.Vertical.TScrollbar", background=[("active", SOFT)])
        for option, value in (("background", RAISED), ("foreground", TEXT), ("selectBackground", TEXT), ("selectForeground", BG)):
            self.root.option_add(f"*TCombobox*Listbox.{option}", value)

    def _label(self, parent, text="", color=TEXT, size=10, bold=False, wrap=0, bg=None) -> tk.Label:
        return tk.Label(parent, text=text, fg=color, bg=bg or parent["bg"], justify="left", anchor="w", wraplength=wrap,
                        font=(TITLE_FONT if size >= 13 else FONT, size, "bold" if bold else "normal"))

    def _switch(self, parent, text: str, variable: tk.BooleanVar, command, color=TEXT, size=10) -> tk.Frame:
        """An on/off switch with its caption. Clicking anywhere on it flips the setting."""
        if not self.switches:
            self.switches = {True: switch_image(True, ACCENT, INK), False: switch_image(False, SWITCH_TRACK_OFF, SOFT)}
        holder = tk.Frame(parent, bg=parent["bg"], cursor="hand2")
        picture = tk.Label(holder, bg=parent["bg"], bd=0, image=self.switches[variable.get()])
        picture.pack(side="left", padx=(0, 8))
        caption = self._label(holder, text, color, size)
        caption.pack(side="left")

        def flip(_) -> None:
            variable.set(not variable.get())
            picture.config(image=self.switches[variable.get()])
            command()

        for part in (holder, picture, caption):
            part.bind("<Button-1>", flip)
        return holder

    def _button(self, parent, text, command, primary=False) -> tk.Button:
        idle, hover = (CHOSEN, CHOSEN_LIGHT) if primary else (RAISED, BORDER)
        color = ON_CHOSEN if primary else TEXT
        button = tk.Button(parent, text=text, command=command, relief="flat", bd=0, cursor="hand2", padx=14, pady=6, bg=idle, fg=color,
                           activebackground=hover, activeforeground=color, disabledforeground=MUTED, font=(FONT, 10, "bold" if primary else "normal"))
        button.bind("<Enter>", lambda _: button.config(bg=hover))
        button.bind("<Leave>", lambda _: button.config(bg=idle))
        return button

    def _entry(self, parent, variable, width=None) -> tk.Entry:
        return tk.Entry(parent, textvariable=variable, width=width, bg=RAISED, fg=TEXT, insertbackground=TEXT, relief="flat", font=(FONT, 10),
                        highlightthickness=1, highlightbackground=BORDER, highlightcolor=SOFT)

    def _panel(self, parent) -> tk.Frame:
        return tk.Frame(parent, bg=PANEL, padx=12, pady=10, highlightthickness=1, highlightbackground=BORDER)

    def _build_shell(self) -> None:
        # A painted scroll: a cherry branch on top, the menu at the side behind a thin line, a line of blossom below.
        # All of it stands in one frame, so a change of language can build the new window under the old one.
        self.root.configure(bg=BG)
        shell = self.shell = tk.Frame(self.root, bg=BG)
        shell.place(x=0, y=0, relwidth=1, relheight=1)
        shell.columnconfigure(2, weight=1)
        shell.rowconfigure(1, weight=1)
        self.rates_key = None
        self.price_drawn_key = None
        self.settings_current = False
        self.banner = tk.Canvas(shell, height=BANNER_HEIGHT, bg=BG, highlightthickness=0, bd=0)
        self.banner.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.banner.bind("<Configure>", lambda _: self._draw_banner())
        self.banner.bind("<Button-1>", self._on_banner_press)
        self.banner.bind("<B1-Motion>", self._drag_window)
        self.banner.bind("<ButtonRelease-1>", self._end_window_drag)
        self.banner.bind("<Motion>", lambda event: self._light_minimize(in_minimize_spot(event.x, event.y, self.banner.winfo_width())))
        self.banner.bind("<Leave>", lambda _: self._light_minimize(False))
        sidebar = tk.Frame(shell, bg=SIDEBAR, width=SIDEBAR_WIDTH)
        sidebar.grid(row=1, column=0, sticky="ns")
        sidebar.pack_propagate(False)
        tk.Frame(shell, bg=BORDER, width=1).grid(row=1, column=1, sticky="ns")
        main = tk.Frame(shell, bg=BG)
        main.grid(row=1, column=2, sticky="nsew")
        add_ground(shell).grid(row=2, column=0, columnspan=3, sticky="ew")

        self.nav = {}
        tk.Frame(sidebar, bg=SIDEBAR, height=10).pack()
        self._nav_button(sidebar, "prices", t("Валюта"), lambda: self.show_tab("prices"))
        self._nav_button(sidebar, "demand", t("Ходовое"), lambda: self.show_tab("demand"))
        self._nav_button(sidebar, "craft", t("Крафт"), lambda: self.show_tab("craft"))
        self._nav_button(sidebar, "build", t("Билд"), lambda: self.show_tab("build"))
        self._nav_button(sidebar, "drops", t("Где падает"), lambda: self.show_tab("drops"))
        self._nav_button(sidebar, "tools", t("Инструменты"), lambda: self.show_tab("tools"))
        self._nav_button(sidebar, "about", AUTHOR, lambda: self.show_tab("about"), side="bottom")
        self._nav_button(sidebar, "settings", t("Настройки"), lambda: self.show_tab("settings"), side="bottom")

        top = tk.Frame(main, bg=BG, padx=10, pady=8)
        top.pack(fill="x")
        add_waves(main, BG, padx=10, pady=(0, 8))
        self.page_title = self._label(top, "", TEXT, 15, True)
        self.page_title.pack(side="left")
        languages = tk.Frame(top, bg=BG)
        languages.pack(side="right")
        for code in ("ru", "en"):
            active = code == language
            tk.Button(languages, text=code.upper(), command=lambda c=code: self.change_language(c), relief="flat", bd=0, cursor="hand2", padx=10, pady=4,
                      bg=RAISED if active else BG, fg=TEXT if active else MUTED, activebackground=BORDER, activeforeground=TEXT,
                      font=(FONT, 9, "bold" if active else "normal")).pack(side="left", padx=1)
        self.league_box = ttk.Combobox(top, width=20, state="readonly", font=(FONT, 9))
        self.league_box.pack(side="right", padx=(10, 2))
        self.league_box.bind("<<ComboboxSelected>>", lambda _: self.change_league(self.league_box.get()))
        self.league_box.bind("<MouseWheel>", lambda _: "break")  # scrolling past it must not move the player to another league
        self.rates = tk.Frame(top, bg=BG)
        self.rates.pack(side="right", padx=16)
        self.status = self._label(main, "", MUTED, 9)
        self.status.pack(side="bottom", fill="x", padx=10, pady=7)
        tk.Frame(main, bg=BORDER, height=1).pack(side="bottom", fill="x")
        # Only the page in use is on screen, since Tk lays out and paints whatever is, seen or not.
        stack = tk.Frame(main, bg=BG)
        stack.pack(fill="both", expand=True)
        self.pages = {key: tk.Frame(stack, bg=BG) for key in ("craft", "build", "drops", "prices", "demand", "tools", "settings", "about")}
        base_bar = tk.Frame(self.pages["craft"], bg=BG, padx=10)
        base_bar.pack(fill="x", pady=(0, 10))
        self._label(base_bar, t("База"), MUTED, 9).pack(side="left")
        self.base_box = ttk.Combobox(base_bar, width=34)
        self.base_box.pack(side="left", padx=(6, 12))
        self.base_box.bind("<Return>", self._on_base_return)
        self.base_box.bind("<KeyRelease>", self._on_base_typing)
        self.base_box.bind("<Down>", lambda _: self._move_base_suggestion(1))
        self.base_box.bind("<Up>", lambda _: self._move_base_suggestion(-1))
        self.base_box.bind("<Escape>", lambda _: self._hide_base_suggestions() or "break" if self._base_suggestions_shown() else None)
        self.base_box.bind("<FocusOut>", lambda _: self.root.after(BASE_SUGGESTIONS_CLOSE_MS, self._hide_base_suggestions_unless_focused))
        self._label(base_bar, "ilvl", MUTED, 9).pack(side="left")
        self.ilvl_var = tk.StringVar(value=str(self.ilvl))
        self._entry(base_bar, self.ilvl_var, 4).pack(side="left", padx=(6, 12), ipady=3)
        self._button(base_bar, t("Открыть"), self.open_manual).pack(side="left")
        self.body_area = tk.Frame(self.pages["craft"], bg=BG)
        self.body_area.pack(fill="both", expand=True, pady=(0, 10))
        self.body = self._new_body()
        self.body_job = None
        self.body_shown = self.body
        self._build_prices_page()
        self._build_demand_page()
        self._build_build_page()
        self._build_drop_page()
        self._build_tools_page()
        self._build_about_page()

    def change_language(self, code: str) -> None:
        """Rebuilds the window in the chosen language and keeps what the player was doing."""
        if code == language or self.changing_language:
            return
        self.changing_language = True
        try:
            self._rebuild_in_language(code)
        finally:
            self.changing_language = False

    def _rebuild_in_language(self, code: str) -> None:
        """The new window is built whole under the old one, which stays on screen untouched, and then takes its place in one stroke."""
        set_language(code)
        self.save_settings(language=code)
        chosen = {row["ladder"].template: row["tier"].current() for row in self.rows if row["checked"].get()}
        tab = self.current_tab
        old = self.shell
        self._end_window_drag(None)  # the banner that would hear the mouse let go is about to be replaced
        still_on_screen = self.banner_image, self.price_graphs, self.demand_page, self.tools_page  # the pictures of the old window must outlive it
        for job in (self.search_job, self.price_draw_job, self.body_job):
            if job:
                self.root.after_cancel(job)
        self.search_job = self.price_draw_job = self.body_job = None
        for wave in (self.price_wave, self.demand_page.wave):
            if wave:
                wave.stop()
        self.price_wave = None
        self.demand_page.stop_drawing()
        if self.price_window and self.price_window.exists():
            self.price_window.window.destroy()  # its words are in the old language
        self.base_icon_label = self.alternatives_box = None
        self.mode_cards = {}
        self._build_shell()
        self.shell.lower(old)
        self.demand_page.quiet_next = True
        self.root.update_idletasks()  # gives the hidden window its real sizes
        self._offer_bases()
        self.load_prices()
        self.show_tab(tab)
        self.set_status(t("Готово"))
        if self.base:
            self.base_box.set(self.db.show_base(self.base))
            self.ilvl_var.set(str(self.ilvl))
        if self.plan:
            self.alternatives = None  # their labels are in the old language
            self.show_guide()
            self._find_alternatives(self.plan)
        elif self.base:
            self.show_picker()
            for row in self.rows:
                if row["ladder"].template in chosen:
                    row["checked"].set(True)
                    row["tier"].current(chosen[row["ladder"].template])
            self.update_counters()
        else:
            self.show_start()
        resume_drawing = self.demand_page.pause_drawing()  # the rows nobody can see yet can wait until the window has changed
        self.root.update()  # everything on screen is drawn, still under cover
        self.render_prices()  # in case the real size came only now; nothing happens if it did not
        self.shell.lift()
        self.root.update()  # painted over the old window before that goes, so the background never shows between them
        old.destroy()
        del still_on_screen
        resume_drawing()
        self._price_window()

    def _start_window_drag(self, event) -> None:
        self.drag_grip = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())
        self._hide_petals()  # their window would only lag behind

    def _drag_window(self, event) -> None:
        """The banner does the work of the title bar it replaced. A mouse reports far more often than a window can move, so only the latest place is kept,
        and the window goes there once the queue of events is empty. That way it never falls behind the pointer."""
        if self.drag_grip:
            self.drag_place = f"+{event.x_root - self.drag_grip[0]}+{event.y_root - self.drag_grip[1]}"
            if not self.drag_job:
                self.drag_job = self.root.after_idle(self._move_to_drag_place)

    def _move_to_drag_place(self) -> None:
        self.drag_job = None
        if self.drag_place:
            self.root.geometry(self.drag_place)
            self.drag_place = None

    def _end_window_drag(self, _) -> None:
        if self.drag_grip:
            self.drag_grip = None
            if self.drag_job:
                self.root.after_cancel(self.drag_job)
            self._move_to_drag_place()
            self._show_petals()

    def _on_banner_press(self, event) -> None:
        if in_minimize_spot(event.x, event.y, self.banner.winfo_width()):
            self.drag_grip = None
            self._light_minimize(False)
            self.root.withdraw()
        else:
            self._start_window_drag(event)

    def _light_minimize(self, lit: bool) -> None:
        self.banner.itemconfigure("minimize_corner", fill=SEAL_RED_LIGHT if lit else SEAL_RED)
        self.banner.configure(cursor="hand2" if lit else "")

    def _draw_banner(self) -> None:
        """The program's name beside a red seal, with the cherry branch reaching in from the other side."""
        canvas = self.banner
        width = canvas.winfo_width()
        if width < 2:
            return
        self.banner_image = branch_image(width)
        canvas.delete("all")
        canvas.create_image(0, 0, image=self.banner_image, anchor="nw")
        middle = BANNER_HEIGHT // 2
        canvas.create_image(30, middle, image=seal_image())
        canvas.create_text(30, middle, text=SEAL_SIGN, fill="#fff2f5", font=(TITLE_FONT, SEAL_SIZE // 2, "bold"))
        canvas.create_text(58, middle, text=APP_NAME, fill=BRAND, font=(TITLE_FONT, 17, "bold"), anchor="w")
        canvas.create_rectangle(width - MINIMIZE_SPOT[0], 0, width, MINIMIZE_SPOT[1], fill=SEAL_RED, width=0, tags=("minimize_corner",))  # the red of the seal, which stands out on the blossom in every theme
        canvas.create_line(width - 24, MINIMIZE_SPOT[1] // 2, width - 10, MINIMIZE_SPOT[1] // 2, fill=ON_SEAL, width=2)

    def _show_petals(self) -> None:
        """Petals drift only while the window is on screen, so a hidden program spends nothing on them."""
        if not self.settings.get("petals", True) or self.root.state() != "normal":
            return self._hide_petals()
        if not self.petals or not self.petals.exists():
            self.petals = DriftingBlossom(self.root)
        self.petals.start()

    def _hide_petals(self) -> None:
        if self.petals and self.petals.exists():
            self.petals.stop()

    def toggle_petals(self) -> None:
        self.save_settings(petals=self.petals_var.get())
        self._show_petals()

    def _nav_button(self, parent, key: str, title: str, command, side: str = "top") -> None:
        button = tk.Button(parent, text=f"  {title}", command=command, relief="flat", bd=0, cursor="hand2", anchor="w", padx=10, pady=7, compound="left",
                           bg=SIDEBAR, fg=SOFT, activebackground=RAISED, activeforeground=TEXT, font=(FONT, 10))
        button.pack(side=side, fill="x", padx=8, pady=(1, 8 if side == "bottom" else 1))
        self.nav[key] = button

    def _refresh_nav(self) -> None:
        for key, button in self.nav.items():
            icon = self.currency_icon(NAV_ICONS[key], 24)
            active = key == self.current_tab
            button.config(bg=CHOSEN if active else SIDEBAR, fg=ON_CHOSEN if active else TEXT, activebackground=CHOSEN if active else RAISED, activeforeground=ON_CHOSEN if active else TEXT,
                          font=(FONT, 10, "bold" if active else "normal"), image=icon or "")
        self.page_title.config(text={"craft": t("Крафт"), "build": t("Билд"), "drops": t("Где падает"), "prices": t("Валюта"), "demand": t("Ходовое"), "tools": t("Инструменты"), "settings": t("Настройки"), "about": AUTHOR}[self.current_tab])

    def show_tab(self, key: str) -> None:
        page = self.pages[key]
        page.place(x=0, y=0, relwidth=1, relheight=1)
        page.lift()
        self.current_tab = key
        self._show_preset_panel() if key == "craft" else self._hide_preset_panel()
        if key != "craft":
            self._hide_base_suggestions()  # a list left open by a tab changed with the keyboard or the tray would hang over another page
        self.root.update_idletasks()  # the page has its real size for what is drawn on it next
        self.root.after_idle(self._take_away_other_pages)  # the old page goes once the new one covers it, so nothing shows between them
        self.scroll_target = {"prices": self.price_canvas, "demand": self.demand_page.canvas, "tools": self.tools_page.canvas, "drops": self.drop_page.canvas}.get(key)
        self._refresh_nav()
        if key == "settings":
            if not self.settings_current:  # the page stays as drawn until a setting changes
                self.render_settings()
        elif key == "demand":
            self.demand_page.render()
        elif key == "build":
            self.build_page.render()
        elif key == "drops":
            self.drop_page.render()
        elif key == "tools":
            self.tools_page.render()

    def _take_away_other_pages(self) -> None:
        for key, page in self.pages.items():
            if key != self.current_tab and page.winfo_exists() and page.winfo_manager():
                page.place_forget()

    def _build_demand_page(self) -> None:
        colors = {"background": BG, "panel": PANEL, "tile": TILE, "border": BORDER, "text": TEXT, "soft": SOFT, "muted": MUTED, "raised": RAISED, "selected": CHOSEN, "on_selected": ON_CHOSEN, "accent": ACCENT,
                  "up": UP_COLOR, "down": DOWN_COLOR, "hot": HOT_COLOR, "unique": RARITY_COLORS["unique"]}
        self.demand_page = DemandPage(self.pages["demand"], colors, t, {
            "demand": lambda: self.demand, "prices": lambda: self.prices, "show_unique": self._show_unique, "show_currency": show_currency, "matches": matches_search,
            "icon": self._demand_icon, "stored_icon": lambda name, is_currency: self.icons.stored(self._demand_icon_path(name, is_currency)), "format_price": format_price, "price": self._price_and_unit, "open_on_site": self.open_unique_on_site, "enable_scrolling": self._enable_scrolling,
            "after_typing": self._after_typing, "make_entry": self._entry, "open_guides": lambda: webbrowser.open(BUILD_GUIDES), "open_wiki": lambda name: webbrowser.open(wiki_page(plain_item_name(name)))})

    def _build_build_page(self) -> None:
        """The build page: a pasted Path of Building code, its items where the game shows them. A language change keeps what is open."""
        colors = {"background": BG, "panel": PANEL, "border": BORDER, "text": TEXT, "soft": SOFT, "muted": MUTED, "raised": RAISED, "selected": CHOSEN, "accent": ACCENT, "down": DOWN_COLOR}
        helpers = {"make_entry": self._entry, "button": self._button, "clipboard": self._clipboard_text, "find_base": self._base_in_line, "language": lambda: language, "enable_scrolling": self._enable_scrolling,
                   "base_info": lambda base: self.db.bases.get(base) if self.db else None, "page_of": self._page_of_base, "limits": affix_limits,
                   "show_base": self._show_base_line, "show_unique": self._show_unique,
                   "rarity_color": lambda rarity: RARITY_COLORS.get(rarity.casefold(), TEXT), "item_picture": self._build_item_picture,
                   "history": lambda: clean_build_history((read_json(BUILDS_PATH) or {}).get("builds")), "save_history": lambda history: write_json(BUILDS_PATH, {**(read_json(BUILDS_PATH) or {}), "builds": history}), "now": now_text,
                   "saved_level": self._saved_level, "save_level": self._save_level,
                   "check_price": lambda text: self.check_price(again=text), "open_in_craft": self._open_in_craft, "copy": self._copy_text,
                   "drop_of": lambda name: drop_line(self.drops, name, language, self._unique_listings(name)),
                   "level_tools": self._level_tools, "estimate_req": self._estimated_requirement,
                   "jewel_rows": self._jewel_rows, "jewel_search": self._open_jewel_search, "jewel_summary": self._jewel_summary,
                   "copied_item": lambda text: level_steps.copied_item(text, self._page_of_base, self._base_in_line),
                   "mod_note": lambda mod, base, level: level_steps.mod_note(mod, self._page_of_base(base), level) if self._page_of_base(base) else None}
        previous = getattr(self, "build_page", None)
        self.build_page = BuildPage(self.pages["build"], colors, t, helpers)
        if previous and previous.build:
            self.build_page.code.set(previous.code.get())
            self.build_page.show_build(previous.build)
            self.build_page.selected = previous.selected
            self.build_page.render()

    def _build_drop_page(self) -> None:
        colors = {"background": BG, "panel": PANEL, "text": TEXT, "soft": SOFT, "muted": MUTED, "raised": RAISED, "selected": CHOSEN, "on_selected": ON_CHOSEN, "accent": ACCENT, "unique": RARITY_COLORS["unique"]}
        helpers = {"button": self._button, "make_entry": self._entry, "enable_scrolling": self._enable_scrolling, "after_typing": self._after_typing, "matches": matches_search,
                   "drops": lambda: self.drops, "language": lambda: language, "show_unique": self._show_unique, "show_base": lambda text: self._show_base_line(self._base_in_line(text), text),
                   "icon": self._drop_icon, "open_link": webbrowser.open, "listings": self._unique_listings}
        self.drop_page = DropPage(self.pages["drops"], colors, t, helpers)

    def _unique_listings(self, name: str) -> int | None:
        """How many of this unique are listed, from hot items: a rough sign of how often it drops where nobody has measured a rate."""
        listings = self.demand.get("items", {}).get(name, {}).get("listings")
        return listings if isinstance(listings, int) and listings > 0 else None

    def _drop_icon(self, name: str, base: str, jewel: bool):
        """A unique's art, or a jewel base's, small enough for a row."""
        path = self._demand_icon_path(name, False) if base else None
        if not path:
            path = self.item_art.get(base or name) or (self.db.bases.get(base, {}).get("icon") if self.db and base else None)
        return self.icons.get(path, 24) if path else None

    def _saved_level(self) -> str:
        """«My level» as it was last typed, kept beside the build history."""
        level = (read_json(BUILDS_PATH) or {}).get("my_level")
        return str(level) if isinstance(level, int) and not isinstance(level, bool) and 1 <= level <= 100 else ""

    def _save_level(self, level: int | None) -> None:
        stored = read_json(BUILDS_PATH) or {}
        if stored.get("my_level") != level:
            write_json(BUILDS_PATH, {**stored, "my_level": level})

    def _level_tools(self, holder, item, mods, base, level) -> bool:
        """«For your level» on the item: the path of levels toward it, what will be searched, and the search."""
        colors = {"panel": PANEL, "text": TEXT, "soft": SOFT, "muted": MUTED, "raised": RAISED, "selected": CHOSEN, "on_selected": ON_CHOSEN, "down": DOWN_COLOR,
                  "accent": ACCENT, "border": BORDER}
        page = self._page_of_base(base)
        if not item.level_req:  # Path of Building did not write it: the level rule gives it
            item = replace(item, level_req=self._estimated_requirement(mods, base))
        steps = level_steps.tier_steps(mods, page, level, item.level_req, language == "ru") if page and level and item.level_req else []
        actions = {"search": lambda chosen: self._open_level_search(item, mods, base, chosen), "craft": lambda chosen: self._craft_for_level(mods, base, chosen),
                   "summary": lambda chosen: self._level_summary(item, mods, base, chosen), "options": lambda chosen: self._level_options(mods, base, chosen),
                   "missing": lambda chosen: level_steps.missing_at_level(mods, page, level_steps.band(chosen)[1], language == "ru") if page else [],
                   "unsearchable": lambda chosen: self._level_unsearchable(mods, base, chosen)}
        return level_steps.add_level_tools(holder, item, level, colors, t, actions, steps, lambda: self.build_page._render_details(keep_scroll=True))

    def _jewel_page(self, base_line: str):
        """The mods a jewel of this kind can have, from jewels.json, read again when the file changes. None before it has come."""
        try:
            stamp = JEWELS_PATH.stat().st_mtime
        except OSError:
            return None
        if getattr(self, "jewel_pages_stamp", None) != stamp:
            self.jewel_pages_stamp, self.jewel_pages = stamp, {}
            for name, raw in ((read_json(JEWELS_PATH) or {}).get("pages") or {}).items():
                try:
                    self.jewel_pages[name] = Page(name, resolve_weights(raw["mods"]))
                except (KeyError, TypeError, ValueError):
                    log_error("reading a jewel page")
        name = next((name for name in JEWEL_PAGES if name.replace("_", " ").casefold() == (base_line or "").strip().casefold()), None)
        return self.jewel_pages.get(name) if name else None

    def _jewel_rows(self, text: str, base_line: str) -> list[dict]:
        """The jewel's mods for its search: each with its range on this kind of jewel, the least of that range, and whether the site can search it."""
        index = self._saved_trade_stats("en")
        if not index:
            return []
        page = self._jewel_page(base_line)
        rows = []
        for mod in read_item_mods(text, index):
            if mod.stats and not all(stat.ids[0].startswith("explicit.") for stat in mod.stats):
                continue  # implicits and the like are not what makes a jewel
            tier = level_steps.jewel_tier(page, mod.label) if page else None
            lowest = read_item_mods(level_steps.detailed_text([(tier[0], level_steps.lowest_roll(tier[1].text))]), index) if tier else []
            rows.append({"key": mod.label, "mod": mod, "lowest": lowest[0] if lowest and lowest[0].stats else None, "searchable": bool(mod.stats),
                         "shown": level_steps.jewel_wording(mod.label, tier[1] if tier else None, language == "ru"),
                         "range": level_steps.jewel_range(tier[1].text) if tier else "",
                         "shown_lowest": level_steps.lowest_roll((tier[1].ru_text if language == "ru" and tier[1].ru_text else tier[1].text)) if tier else ""})
        return rows

    def _jewel_chosen(self, text: str, base_line: str, ticked: set, by_range: bool) -> list:
        return [row["lowest"] if by_range and row["lowest"] else row["mod"] for row in self._jewel_rows(text, base_line) if row["searchable"] and row["key"] in ticked]

    def _jewel_summary(self, text: str, base_line: str, ticked: set, by_range: bool) -> str:
        rows = [row for row in self._jewel_rows(text, base_line) if row["searchable"] and row["key"] in ticked]
        if not rows:
            return t("Отметьте хотя бы один мод")
        lines = [row["shown_lowest"] if by_range and row["lowest"] else row["shown"] for row in rows]
        return t("Ищу: {base}, все из: {mods}").format(base=self._show_base_line(None, base_line), mods="; ".join(lines))

    def _open_jewel_search(self, text: str, base_line: str, ticked: set, by_range: bool) -> None:
        """The trade site with jewels of this kind that have every ticked mod: from the least of its range, or from the jewel's own value."""
        chosen = self._jewel_chosen(text, base_line, ticked, by_range)
        if not chosen:
            return self.set_status(t("Отметьте хотя бы один мод"))
        query = build_query(None, base_line.strip(), False, chosen, 1.0, None)
        self._open_on_site(trade_site_url("en", (self.prices or {}).get("league", "Standard"), query))

    def _estimated_requirement(self, mods, base) -> int | None:
        page = self._page_of_base(base)
        drop_level = (self.db.bases.get(base) or {}).get("drop_level", 1) if self.db and base else 1
        return level_steps.estimated_requirement(mods, page, drop_level) if page else None

    def _level_options(self, mods, base, level: int) -> list[tuple[str, str, bool]]:
        """The item's mods an item of this level can have, strongest first, each at its value there; all of them are ticked at first."""
        page = self._page_of_base(base)
        if not page:
            return []
        _, high = level_steps.band(level)
        pool = level_steps.available_mods(mods, page, high)
        return [(level_steps.mod_key(mod), " / ".join(line for _, line in level_steps.mods_in_band([mod], page, level, high, language == "ru")), True)
                for mod in level_steps.key_order(pool, page, level) if self._trade_knows(mod, page, level, high)]

    def _trade_knows(self, mod, page, level: int, high: int) -> bool:
        """Whether the trade site has a filter for this mod. Before its list of filters has come, every mod is taken as known."""
        index = self._saved_trade_stats("en")
        if not index:
            return True
        found = read_item_mods(level_steps.detailed_text(level_steps.mods_in_band([mod], page, level, high)), index)
        return any(item_mod.stats for item_mod in found)

    def _level_unsearchable(self, mods, base, level: int) -> list[str]:
        """The item's mods this level can have but the trade site cannot search for, in the player's language: shown greyed, never ticked."""
        page = self._page_of_base(base)
        if not page:
            return []
        _, high = level_steps.band(level)
        return [" / ".join(line for _, line in level_steps.mods_in_band([mod], page, level, high, language == "ru"))
                for mod in level_steps.key_order(level_steps.available_mods(mods, page, high), page, level) if not self._trade_knows(mod, page, level, high)]

    def _level_selection(self, item, mods, base, level: int):
        """The ticked mods for this item and level, how many of them a listing needs, and the share of their values."""
        page = self._page_of_base(base)
        _, high = level_steps.band(level)
        pool = level_steps.available_mods(mods, page, high) if page else []
        options = self._level_options(mods, base, level)
        keys = level_steps.checked_keys((item.name, item.base_line), level, options)
        chosen = [mod for mod in level_steps.key_order(pool, page, level) if level_steps.mod_key(mod) in keys] if page else []
        return page, chosen, level_steps.needed_count(len(chosen)), 1.0  # the values of the tier this level has

    def _level_summary(self, item, mods, base, level: int) -> str:
        """What a search for this level will ask for, in the player's language, before it opens."""
        page, chosen, need, _ = self._level_selection(item, mods, base, level)
        if not page:
            return ""
        low, high = level_steps.band(level)
        lines = [line for _, line in level_steps.mods_in_band(chosen, page, level, high, language == "ru")]
        return level_steps.search_summary(lines, low, high, need, level_steps.chosen_scope[0], t)

    def _craft_for_level(self, mods, base, level: int) -> None:
        """The item's key mods at the tiers this level allows, opened in the planner."""
        page = self._page_of_base(base)
        goal = level_steps.craft_goal(mods, page, base, level) if page and level else None
        if not goal:
            return self.set_status(t("На этом уровне у вещи нет модов из её списка"))
        self.show_tab("craft")
        self._open_goal(goal)

    def _open_level_search(self, item, mods, base, level: int) -> None:
        """The trade site with a search for a similar item this character level can wear."""
        page = self._page_of_base(base)
        index = self._saved_trade_stats("en")
        if not index or not page:
            return self.set_status(t("Список модов для поиска ещё загружается, пока сайт откроется только с базой предмета."))
        low, high = level_steps.band(level)
        _, chosen, need, share = self._level_selection(item, mods, base, level)
        found = read_item_mods(level_steps.detailed_text(level_steps.mods_in_band(chosen, page, level, high)), index)
        category = trade_category(page.name) if level_steps.chosen_scope[0] == "kind" else None
        query = level_steps.level_query(found, high, category, base, need, share, low)
        if not query:
            return self.set_status(t("На этом уровне у вещи нет модов из её списка"))
        self._open_on_site(trade_site_url("en", (self.prices or {}).get("league", "Standard"), query))

    def _clipboard_text(self) -> str:
        try:
            return self.root.clipboard_get()
        except tk.TclError:
            return ""

    def _base_in_line(self, line: str) -> str | None:
        """The base named in an item's line, in either language: the longest name that fits, as a magic item wraps its base in affixes."""
        if not self.db:
            return None
        text = line.casefold()
        found = [shown for shown in self.db.names if shown in text]
        return self.db.names[max(found, key=len)] if found else None

    def _page_of_base(self, base: str):
        if not self.db or base not in self.db.bases:
            return None
        return self.db.pages.get(self.db.bases[base]["page"])

    def _art_name_in(self, line: str) -> str | None:
        """The longest item name in the line that has art: a jewel, flask or charm base, which the crafting data does not hold."""
        text = line.casefold()
        return max((name for name in self.item_art if name.casefold() in text), key=len, default=None)

    def _show_base_line(self, base: str | None, line: str) -> str:
        """An item's base in the player's language: a crafting base from the data, anything else by its name from poe2db."""
        if self.db and base in self.db.bases:
            return self.db.show_base(base)
        named = self._art_name_in(line)
        return show_currency(named) if named else line

    def _build_item_picture(self, unique: str, base: str | None, line: str, large: bool):
        """A unique's own art, or the base's. Flasks and charms have no crafting base, so their art is found by name among all items."""
        path = self._demand_icon_path(unique, False) if unique else None
        if not path and self.db and base:
            path = self.db.bases.get(base, {}).get("icon")
        if not path:
            named = self._art_name_in(line)
            path = self.item_art.get(named) if named else None
        if not path:
            return None
        return (self.icons.get(LARGE_ART + path) if large and not path.startswith("http") else None) or self.icons.get(path)

    def _build_tools_page(self) -> None:
        colors = {"background": BG, "panel": PANEL, "text": TEXT, "soft": SOFT, "muted": MUTED, "raised": RAISED, "selected": CHOSEN, "on_selected": ON_CHOSEN, "accent": ACCENT, "up": UP_COLOR, "down": DOWN_COLOR}
        helpers = {"enable_scrolling": self._enable_scrolling, "make_entry": self._entry, "button": self._button, "matches": matches_search, "show_currency": show_currency, "db": lambda: self.db, "prices": lambda: self.prices,
                   "cost": self._tools_cost, "price_of": self._tools_price, "unit_label": lambda unit: UNIT_LABELS[unit], "icon": self.currency_icon, "copy": self._copy_text, "open_link": self._open_on_site, "save": self._save_tools,
                   "waystones": lambda: self.waystones, "language": lambda: language, "check_exchange": self.check_exchange, "essence_text": lambda essence: (essence.ru_text if language == "ru" else "") or essence.text,
                   "find_priced": self._find_priced, "current_divine": self._current_divine, "watches_changed": self._watches_changed, "recheck": self.check_price, "value_in_divine": self._value_in_divine, "show_item": self._show_item, "item_icon": self._item_icon, "item_price": self._item_price, "price_text": self._price_text,
                   "omens": lambda: [(name, omen_text(name)) for name in OMENS], "today": lambda: datetime.now().strftime("%d.%m.%Y"), "local_time": lambda moment: datetime.fromtimestamp(moment).strftime("%H:%M")}
        previous = self.tools_page
        self.tools_page = ToolsPage(self.pages["tools"], colors, t, helpers, self.tools_store, self.stopwatch)
        if previous:  # the language changed: the page is rebuilt, but it still knows what the player has seen
            self.tools_page.tab, self.tools_page.exchange = previous.tab, previous.exchange

    def _current_divine(self, name: str) -> float | None:
        """What anything on the market costs now: currency from the price list, a unique from hot items."""
        value = (self.prices or {}).get("prices_in_divine", {}).get(name)
        if value is None:
            value = self.demand.get("items", {}).get(name, {}).get("price")
        return value

    def _value_in_divine(self, name: str) -> float | None:
        prices = self.prices or {}
        coins = {"Divine Orb": 1.0, "Exalted Orb": 1 / prices["exalted_per_divine"] if prices.get("exalted_per_divine") else None, "Chaos Orb": 1 / prices["chaos_per_divine"] if prices.get("chaos_per_divine") else None}
        return coins[name] if name in coins else self._current_divine(name)

    def _show_item(self, name: str) -> str:
        return self._show_unique(name) if name in self.demand.get("items", {}) else show_currency(name)

    def _item_icon(self, name: str, size: int = 24):
        return self._demand_icon(name, name not in self.demand.get("items", {}), size)

    def _item_price(self, name: str) -> str:
        divine = self._current_divine(name)
        return self._price_text(divine) if divine else "—"

    def _find_priced(self, text: str) -> str | None:
        """The one item that typed text means, in either language. A name that fits several gives nothing, so a watch never lands on the wrong item."""
        wanted = text.strip().casefold()
        if not wanted:
            return None
        names = [*(self.prices or {}).get("prices_in_divine", {}), *self.demand.get("items", {}), "Divine Orb", "Exalted Orb", "Chaos Orb"]
        shown = {name: (name, show_currency(name), self._show_unique(name)) for name in names}
        exact = [name for name, forms in shown.items() if any(form.casefold() == wanted for form in forms)]
        if exact:
            return exact[0]
        partial = [name for name, forms in shown.items() if any(wanted in form.casefold() for form in forms)]
        return partial[0] if len(partial) == 1 else None

    def _watch_sections(self) -> frozenset[str]:
        kinds = (self.prices or {}).get("kinds", {})
        items = self.demand.get("items", {})
        found = set()
        for watch in self.tools_store.get("watches", ()):
            name = watch["name"]
            found.add(items[name]["kind"] if name in items and name not in kinds else kinds.get(name, "Currency"))
        return frozenset(found)

    def _watches_changed(self) -> None:
        self.update_interest.watched = self._watch_sections()
        self.update_interest.wake.set()

    def _check_watches(self) -> None:
        """Runs whenever prices arrive, so it costs no request of its own."""
        watches = self.tools_store.get("watches")
        if not self.watching or not watches or not self.prices:
            return
        reached, kept = watches_reached(watches, self._current_divine, self.prices)
        if kept != watches:
            self.tools_store["watches"] = kept
            self._save_tools()
        for watch in reached:
            text = t("{name}: {price}, порог {limit}").format(name=self._show_item(watch["name"]), price=self._item_price(watch["name"]), limit=f"{watch['amount']:g} {UNIT_LABELS[watch['unit']]}")
            self.set_status(text)
            if self.tray:
                self.tray.notify(t("Цена дошла до порога"), text)
        if reached:
            self.tools_page.show_if_open("watch")

    def _remember_check(self, name: str, copied: str, price: str, priced_name: str | None, stack: int = 1) -> None:
        self.tools_store["history"] = add_history(self.tools_store.get("history", []), name, copied, price, priced_name, datetime.now().strftime("%d.%m %H:%M"), stack)
        self._save_tools()
        self.tools_page.show_if_open("history")

    def _tools_cost(self, exalted: float) -> str:
        return format_cost(exalted, self.prices["exalted_per_divine"], self.prices.get("chaos_per_divine")) if self.prices else f"{exalted:g} {UNIT_LABELS['Exalted Orb']}"

    def _tools_price(self, name: str) -> str:
        divine = self.prices["prices_in_divine"].get(name) if self.prices else None
        return self._price_text(divine) if divine else "—"

    def _copy_text(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def check_exchange(self) -> None:
        """One file from the official exchange, only on the button."""
        if not self.exchange_names or not self.prices:
            return self.tools_page.show_exchange_error(t("Названия товаров ещё не загружены, попробуйте позже"))
        league, names = self.prices.get("league", "Standard"), self.exchange_names

        def work():
            try:
                hour, digest = fetch_exchange(time.time(), APP_USER_AGENT)
                self.events.put(("exchange", (hour, exchange_turnover(digest["markets"], league, names))))
            except Exception:
                log_error("exchange")
                self.events.put(("exchange_error", t("Не удалось загрузить курсы")))
        threading.Thread(target=work, daemon=True).start()

    def _show_unique(self, name: str) -> str:
        return self.unique_russian.get(name, name) if language == "ru" else name

    def _demand_icon_path(self, name: str, is_currency: bool) -> str | None:
        if is_currency:
            return self._currency_icon_path(name)
        path = self.unique_art.get(name.casefold())
        if not path or self.icons.raw.get(path) == "":  # RePoE has no picture of it, but poe2scout links one
            path = self.demand.get("items", {}).get(name, {}).get("icon")
        return path

    def _demand_icon(self, name: str, is_currency: bool, size: int = ICON_SIZE, tile: bool = False):
        path = self._demand_icon_path(name, is_currency)
        return self.icons.on_tile(path, TILE) if tile else self.icons.get(path, size)

    def _price_and_unit(self, divine: float, own_name: str | None = None) -> tuple[str, str]:
        prices = self.prices or {}
        amount, unit = best_unit(divine, prices.get("exalted_per_divine"), prices.get("chaos_per_divine"), own_name)
        return format_amount(amount, unit), unit

    def _price_text(self, divine: float) -> str:
        shown, unit = self._price_and_unit(divine)
        return f"{shown} {UNIT_LABELS[unit]}"

    def _build_about_page(self) -> None:
        page = tk.Frame(self.pages["about"], bg=BG)
        page.place(relx=0.5, rely=0.5, anchor="center")
        self.about_icon = tk.Label(page, bg=BG)
        self.about_icon.pack(pady=(0, 10))
        self._label(page, GREETING, TEXT, 20, True).pack(pady=(0, 12))
        for line in ABOUT_LINES:
            self._label(page, line.replace("Ctrl+E", hotkey_label(self.hotkeys["copy"])), SOFT, 11).pack(pady=2)
        self.update_box = tk.Frame(page, bg=BG)  # filled when a newer version is out
        self.update_box.pack()
        self._fill_update_box()
        support = tk.Frame(page, bg=BG)
        support.pack(pady=(16, 0))
        self._label(support, t("Поддержать автора: {network}, только эта сеть").format(network=SUPPORT_NETWORK), SOFT, 10).pack()
        self._label(support, SUPPORT_ADDRESS, TEXT, 10, True).pack(pady=(4, 6))
        buttons = tk.Frame(support, bg=BG)
        buttons.pack()
        self._button(buttons, t("Скопировать адрес"), self.copy_support_address).pack(side="left", padx=4)
        self._button(buttons, t("Sakuya на GitHub"), self.open_github).pack(side="left", padx=4)
        self._label(page, ABOUT_CREDITS, MUTED, 9).pack(pady=(18, 0))

    def _fill_update_box(self, progress: str = "") -> None:
        """A newer version, with a button that puts it in place, or how far its download has come: on the Divine page and on the tag above the window."""
        self._show_update_tag(progress)
        box = self.update_box
        if not box or not box.winfo_exists():
            return
        for child in box.winfo_children():
            child.destroy()
        release = self.new_release
        if not release:  # the same place asks for reports of what went wrong
            self._label(box, t("Нашли ошибку или странный план крафта? Напишите, и мы починим"), SOFT, 10).pack(pady=(14, 6))
            self._button(box, t("Сообщить о проблеме"), self.report_problem).pack()
            return
        self._label(box, t("Вышла новая версия {version}, у вас {current}").format(version=release.tag, current=VERSION), ACCENT, 11, True).pack(pady=(14, 6))
        if progress:
            self._label(box, progress, SOFT, 10).pack()
            return
        buttons = tk.Frame(box, bg=BG)
        buttons.pack()
        self._button(buttons, t("Обновить до {version}").format(version=release.tag), self.start_update, primary=True).pack(side="left", padx=4)
        self._button(buttons, t("Что нового"), lambda: webbrowser.open(release.link)).pack(side="left", padx=4)

    def _show_update_tag(self, progress: str = "") -> None:
        """A small window of its own just above the main one, which goes where it goes: a newer version is out, click to update."""
        if not self.new_release or self.closing:
            return self._hide_update_tag()
        tag = self.update_tag
        if not tag or not tag.winfo_exists():
            tag = self.update_tag = tk.Toplevel(self.root, bg=ACCENT)
            tag.withdraw()
            tag.overrideredirect(True)
            words = self.update_tag_words = tk.Label(tag, bg=CHOSEN, fg=ON_CHOSEN, font=(FONT, 10, "bold"), padx=UPDATE_TAG_PAD_X, pady=UPDATE_TAG_PAD_Y, cursor="hand2")
            words.pack(padx=1, pady=1)  # the tag's own colour shows round it as a thin frame
            for widget in (tag, words):
                widget.bind("<Button-1>", lambda _: self.start_update())
            words.bind("<Enter>", lambda _: words.config(bg=CHOSEN_LIGHT))
            words.bind("<Leave>", lambda _: words.config(bg=CHOSEN))
        tag.attributes("-topmost", bool(self.root.attributes("-topmost")))
        self.update_tag_words.config(text=progress or t("Вышла Sakuya {version}: нажмите, чтобы обновить").format(version=self.new_release.tag),
                                     cursor="watch" if progress else "hand2")
        self._place_update_tag()

    def _place_update_tag(self) -> None:
        tag = self.update_tag
        if not tag or not tag.winfo_exists():
            return
        try:
            if self.closing or not self.root.winfo_viewable():
                return tag.withdraw()
            tag.update_idletasks()
            width, height = tag.winfo_reqwidth(), tag.winfo_reqheight()
            x = self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2
            y = self.root.winfo_rooty() - height - UPDATE_TAG_GAP
            if y < all_monitors()[1]:  # the window is at the top of the screen: the tag lies over its banner instead
                y = self.root.winfo_rooty() + UPDATE_TAG_GAP
            tag.geometry(f"+{x}+{y}")
            if tag.state() != "normal":
                tag.deiconify()
            tag.lift()
            settle_window(tag, x, y)
        except tk.TclError:  # the window is being rebuilt or closed
            pass

    def _hide_update_tag(self) -> None:
        tag = self.update_tag
        if tag and tag.winfo_exists():
            tag.withdraw()

    def open_github(self) -> None:
        webbrowser.open(GITHUB_PAGE)

    def report_problem(self) -> None:
        """GitHub's page for a new issue, where the form for a wrong crafting plan waits. Nothing is sent from here."""
        webbrowser.open(ISSUES_PAGE)

    def offer_update(self, release: Release) -> None:
        """Said once per version: the check comes back every few hours."""
        known = self.new_release
        self.new_release = release
        if self.updating:
            return
        self._fill_update_box()
        if self.tray and (not known or known.tag != release.tag):
            self.tray.notify(t("Вышла новая версия Sakuya {version}").format(version=release.tag), t("Обновить можно в разделе Divine или в меню значка в трее"))

    def start_update(self) -> None:
        """Only on the player's word. A copy run from the source, or a release without a checked file, sends the player to the page instead."""
        release = self.new_release
        if not release or self.updating:
            return
        if not getattr(sys, "frozen", False) or not release.download:
            webbrowser.open(release.link)
            return self.set_status(t("Открываю страницу новой версии: скачайте её оттуда"))
        self.updating = True
        exe = Path(sys.executable)
        shown = [-1]

        def progress(done: int, total: int) -> None:
            percent = done * 100 // max(total, 1)
            if percent != shown[0]:
                shown[0] = percent
                self.events.put(("update_progress", percent))

        def fetch_it() -> None:
            try:
                self.events.put(("update_ready", download_update(release, exe, progress)))
            except Exception as error:
                log_error("downloading an update")
                self.events.put(("update_failed", str(error)))
        self._fill_update_box(t("Скачиваю новую версию: {percent}%").format(percent=0))
        threading.Thread(target=fetch_it, daemon=True).start()

    def finish_update(self, fresh: Path) -> None:
        """The checked file takes the running one's place, and the new version starts. It closes this copy itself, as any new start does."""
        exe = Path(sys.executable)
        try:
            game_watch.stop_watcher(exe)  # it runs from the old file; the new version starts it again
        except OSError:
            log_error("stopping the game watcher")
        try:
            old = swap_in_update(exe, fresh)
        except OSError as error:
            log_error("putting an update in place")
            fresh.unlink(missing_ok=True)
            return self.update_failed(str(error))
        try:
            subprocess.Popen([str(exe)], cwd=str(exe.parent), env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"})
        except OSError as error:
            log_error("starting the update")
            os.replace(exe, fresh)
            os.replace(old, exe)
            fresh.unlink(missing_ok=True)
            return self.update_failed(str(error))
        self._save_tools()
        self.closing = True  # no more hotkeys or events here: they belong to the new copy now
        if self.tray:
            self.tray.remove()
            self.tray = None
        if self.price_window and self.price_window.exists():
            self.price_window.window.withdraw()
        self.root.withdraw()
        self.root.after(RESTART_WAIT_MS, self.quit)  # whatever happened to the new copy, this one must not stay behind

    def update_failed(self, reason: str) -> None:
        self.updating = False
        self._fill_update_box()
        self.set_status(t("Не удалось обновить ({reason}). Открываю страницу новой версии, скачайте её вручную").format(reason=reason))
        if self.new_release:
            webbrowser.open(self.new_release.link)

    def _remove_update_leftovers(self, tries: int = LEFTOVER_TRIES) -> None:
        """After an update the old exe is still next to the new one, and its copy may be closing for a moment."""
        exe = Path(sys.executable)
        if not getattr(sys, "frozen", False):
            return
        if tries == LEFTOVER_TRIES and replaced_path(exe).exists():
            self.set_status(t("Sakuya обновлена до версии {version}").format(version=VERSION))
        if not remove_update_leftovers(exe) and tries > 1:
            self.root.after(LEFTOVER_RETRY_MS, self._remove_update_leftovers, tries - 1)

    def copy_support_address(self) -> None:
        """Puts the wallet address on the clipboard for the player to paste into their own wallet."""
        self.root.clipboard_clear()
        self.root.clipboard_append(SUPPORT_ADDRESS)
        text = t("Адрес скопирован. Отправляйте только {network}, другие сети и монеты потеряются").format(network=SUPPORT_NETWORK)
        self.set_status(text)
        if self.tray:
            self.tray.notify(t("Спасибо за поддержку!"), text)

    def _build_prices_page(self) -> None:
        page = tk.Frame(self.pages["prices"], bg=BG, padx=10)
        page.pack(fill="both", expand=True)
        self.price_subtitle = self._label(page, "", MUTED, 9)
        self.price_subtitle.pack(anchor="w", pady=(0, 8))
        tabs = tk.Frame(page, bg=BG)
        tabs.pack(fill="x", pady=(0, 8))
        tabs.columnconfigure(tuple(range(SECTIONS_PER_LINE)), weight=1, uniform="sections")
        self.price_buttons = {}
        self.price_button_looks = {}
        self.price_tab_icons_of, self.price_tab_icons = object(), {}
        keep_fonts_ready([(FONT, 9, "bold"), (FONT, 9), (FONT, 10, "bold"), (FONT, 10), (FONT, 12, "bold")])
        for index, (kind, russian, english) in enumerate(PRICE_TABS):
            # The 1 pixel frame around the button is the card's border.
            card = tk.Frame(tabs, bg=BORDER)
            card.grid(row=index // SECTIONS_PER_LINE, column=index % SECTIONS_PER_LINE, sticky="nsew", padx=(0, 5), pady=(0, 5))
            button = tk.Button(card, text=f" {russian if language == 'ru' else english}", command=lambda k=kind: self.set_price_tab(k), relief="flat", bd=0, cursor="hand2",
                               compound="left", anchor="w", padx=8, pady=4, bg=PANEL, fg=SOFT, activebackground=RAISED, activeforeground=TEXT, font=(FONT, 9))
            button.pack(fill="both", expand=True, padx=1, pady=1)
            button.bind("<Enter>", lambda _, k=kind: self._hover_price_tab(k, True))
            button.bind("<Leave>", lambda _, k=kind: self._hover_price_tab(k, False))
            self.price_buttons[kind] = (button, card)
        bar = tk.Frame(page, bg=BG)
        bar.pack(fill="x", pady=(0, 8))
        self._label(bar, t("Поиск"), MUTED, 9).pack(side="left", padx=(0, 8))
        self.price_search = tk.StringVar()
        trace_while(self.price_search, bar, lambda *_: self._after_typing(lambda: self.render_prices(True)))
        self._entry(bar, self.price_search).pack(side="left", fill="x", expand=True, ipady=5)
        holder = tk.Frame(page, bg=BG)
        holder.pack(fill="both", expand=True)
        holder.columnconfigure(0, weight=1)
        holder.columnconfigure(1, minsize=11)
        holder.rowconfigure(0, weight=1)
        # One canvas draws all cards: hundreds of widgets would make scrolling stutter.
        self.price_canvas = tk.Canvas(holder, bg=BG, highlightthickness=0, bd=0)
        self.price_canvas.grid(row=0, column=0, sticky="nsew")
        self._enable_scrolling(holder, self.price_canvas)
        self.price_drawn_width = None
        self.price_canvas.bind("<Configure>", self._on_price_resize)
        self.price_canvas.bind("<Motion>", self._hover_price_row)
        self.price_canvas.bind("<Leave>", lambda _: self._set_hovered_row(None))
        self.price_canvas.bind("<Button-1>", self._open_price_card_wiki, add="+")  # a card opens its item on poe2wiki
        self.hovered_row = None
        self.price_row_names: list[str] = []

    def _on_price_resize(self, event) -> None:
        """Only a new width moves the cards. A new height just shows more of them."""
        if self.changing_language:  # the rebuild draws them itself, out of sight
            self.price_drawn_width = event.width
        elif event.width != self.price_drawn_width:
            self.price_drawn_width = event.width
            self._after_typing(lambda: self.render_prices(wave=True))

    def _after_typing(self, action) -> None:
        """Runs an action once the input has settled instead of on every key or resize step."""
        if self.search_job:
            self.root.after_cancel(self.search_job)
        self.search_job = self.root.after(SEARCH_DELAY_MS, action)

    def set_price_tab(self, kind: str) -> None:
        self.price_tab = kind
        self.render_prices(True, wave=True)

    def _hover_price_tab(self, kind: str, inside: bool) -> None:
        if kind != self.price_tab:
            self.price_buttons[kind][0].config(bg=RAISED if inside else PANEL, fg=TEXT if inside else SOFT)

    def _price_grid(self, width: int) -> tuple[int, int]:
        """How many cards fit in a line, and how wide each one is."""
        columns = max((width + PRICE_CARD_GAP) // (PRICE_CARD_WIDTH + PRICE_CARD_GAP), 1)
        return columns, (width - PRICE_CARD_GAP * (columns - 1)) // columns

    def render_prices(self, to_top: bool = False, wave: bool = False) -> None:
        """A new section comes in as a wave. A search or a quiet refresh of prices just appears, since motion there would only get in the way.
        A list that has not changed is not touched at all: prices come in section by section, and most of those are not the one on screen."""
        if self.price_tab_icons_of is not self.prices:
            self.price_tab_icons_of = self.prices
            self.price_tab_icons = {kind: tab_icon_item(kind, self.prices or {}) for kind in self.price_buttons}
        for kind, (button, card) in self.price_buttons.items():
            active = kind == self.price_tab
            icon = self.currency_icon(self.price_tab_icons.get(kind), 24) or ""
            if self.price_button_looks.get(kind) != (active, str(icon)):  # most of them stay as they are, and each call into Tk counts when a wave is about to start
                self.price_button_looks[kind] = (active, str(icon))
                button.config(image=icon, fg=ON_CHOSEN if active else SOFT, font=(FONT, 9, "bold" if active else "normal"))
                card.config(bg=ACCENT if active else BORDER)
                button.config(bg=CHOSEN if active else PANEL)
        canvas = self.price_canvas
        width = max(canvas.winfo_width(), PRICE_CARD_WIDTH)
        rows, query, source_updated = [], self.price_search.get(), None
        if self.prices:
            source_updated = self.prices.get("updated", {}).get(price_source(self.price_tab))
            updated = source_updated or self.prices.get("fetched_at", "")
            self.price_subtitle.config(text=t("{league}  •  обновлено {time}  •  обновляется при просмотре, не чаще раза в час").format(league=self.prices.get("league"), time=updated[11:16]))
            rows = [(name, value) for name, value in self.prices["prices_in_divine"].items()
                    if price_section(name, self.prices) == self.price_tab and matches_search(query, f"{name} {show_currency(name)}")]
            rows.sort(key=lambda row: -row[1])
        changes = (self.prices or {}).get("changes", {})
        key = (self.price_tab, width, bool(self.prices), bool(source_updated), tuple((name, value, changes.get(name), self.currency_icon(name, ICON_SIZE) is not None) for name, value in rows))
        if key == self.price_drawn_key:
            if to_top:
                canvas.yview_moveto(0)
            return
        self.price_drawn_key = key
        if self.price_wave:
            self.price_wave.stop()
            self.price_wave = None
        if self.price_draw_job:
            self.root.after_cancel(self.price_draw_job)
            self.price_draw_job = None
        canvas.delete("all")
        self.hovered_row = None
        self.price_columns, card = self._price_grid(width)
        self.price_graphs = []
        graphs_unknown = card != getattr(self, "price_card_width", None)
        self.price_card_width = card
        if graphs_unknown:
            self._prepare_graphs()
        if not self.prices:
            canvas.create_text(12, 20, text=t("Цены ещё загружаются"), fill=MUTED, font=(FONT, 10), anchor="w")
            return
        if wave and rows and canvas.winfo_viewable():
            canvas.yview_moveto(0)
            self._start_price_wave(rows)
        else:
            for number, (name, value) in enumerate(rows):
                self._draw_price_card(canvas, number, name, value)
        if not rows:
            empty = "Ничего не найдено" if query or source_updated else "Цены этого раздела придут при следующем обновлении"
            canvas.create_text(12, 20, text=t(empty), fill=MUTED, font=(FONT, 10), anchor="w")
        lines = (len(rows) + self.price_columns - 1) // self.price_columns
        canvas.configure(scrollregion=(0, 0, width, max(lines * (PRICE_CARD_HEIGHT + PRICE_CARD_GAP), 1)))
        self.price_row_count = len(rows)
        self.price_row_names = [name for name, _ in rows]
        if to_top:
            canvas.yview_moveto(0)

    def _start_price_wave(self, rows: list[tuple[str, float]]) -> None:
        """The cards on screen ride the wave, and the rest are drawn behind it in short turns."""
        canvas, card, columns = self.price_canvas, self.price_card_width, self.price_columns
        step_x, step_y = card + PRICE_CARD_GAP, PRICE_CARD_HEIGHT + PRICE_CARD_GAP
        on_screen = min((canvas.winfo_height() // step_y + 1) * columns, len(rows))
        boxes = [((number % columns) * step_x, (number // columns) * step_y, (number % columns) * step_x + card, (number // columns) * step_y + PRICE_CARD_HEIGHT, wave_delay(number % columns, number // columns)) for number in range(on_screen)]
        self.price_wave = CardWave(canvas, boxes, lambda number: self._draw_price_card(canvas, number, *rows[number]), PANEL, BORDER, lambda: self._draw_price_cards_from(rows, on_screen))

    def _draw_price_cards_from(self, rows: list[tuple[str, float]], first: int) -> None:
        self.price_draw_job = None
        canvas = self.price_canvas
        if not canvas.winfo_exists():
            return
        started = time.perf_counter()
        number = first
        while number < len(rows) and (number == first or time.perf_counter() - started < PRICE_DRAW_TURN_SECONDS):
            self._draw_price_card(canvas, number, *rows[number])
            number += 1
        if number < len(rows):
            self.price_draw_job = self.root.after_idle(self._draw_price_cards_later, rows, number)

    def _draw_price_cards_later(self, rows: list[tuple[str, float]], number: int) -> None:
        """Runs once the last turn is on screen. Tk redraws only when no timer is due, so a turn that simply set its timer would keep the window from showing anything until the last card."""
        self.price_draw_job = self.root.after(1, self._draw_price_cards_from, rows, number)

    def _draw_price_card(self, canvas: tk.Canvas, number: int, name: str, value: float) -> None:
        """A card: picture and name on top, the price under the name, and the week's trend along the bottom."""
        card = self.price_card_width
        left = (number % self.price_columns) * (card + PRICE_CARD_GAP)
        top = (number // self.price_columns) * (PRICE_CARD_HEIGHT + PRICE_CARD_GAP)
        price, unit = self._price_and_unit(value, name)
        price_text = canvas.create_text(left + 68, top + 50, text=price, fill=TEXT, font=(FONT, 12, "bold"), anchor="w")
        change = self.prices.get("changes", {}).get(name)
        color = MUTED if not change else UP_COLOR if change > 0 else DOWN_COLOR
        sheet = baked_card(card, PRICE_CARD_HEIGHT, paper_variant(name), (8, 8, 60, 60, TILE, BORDER),
                           ((self.icons.stored(self._currency_icon_path(name)), 34, 34, 1), (self.icons.stored(self._currency_icon_path(unit)), canvas.bbox(price_text)[2] - left + 14, 50, ICON_SIZE // 24)),
                           (self.prices.get("sparklines", {}).get(name), card - 20, PRICE_GRAPH_HEIGHT, color, 10, PRICE_GRAPH_TOP))
        self.price_graphs.append(sheet)
        canvas.tag_lower(canvas.create_image(left, top, image=sheet, anchor="nw"), price_text)
        canvas.create_rectangle(left + 1, top, left + card - 1, top + PRICE_CARD_HEIGHT - 1, fill="", outline=BORDER, tags=(f"card{number}",))
        shown = show_currency(name)
        shown = shown if len(shown) <= LONGEST_CARD_NAME else shown[:LONGEST_CARD_NAME - 1] + "…"
        canvas.create_text(left + 68, top + 8, text=shown, fill=TEXT, font=(FONT, 9, "bold"), anchor="nw", width=card - 76)
        draw_change(canvas, left + card - 10, top + 50, change, UP_COLOR, DOWN_COLOR, SOFT)

    def _hover_price_row(self, event) -> None:
        y = self.price_canvas.canvasy(event.y)
        step = self.price_card_width + PRICE_CARD_GAP
        column = event.x // step
        number = int(y // (PRICE_CARD_HEIGHT + PRICE_CARD_GAP)) * self.price_columns + column
        inside = column < self.price_columns and event.x % step < self.price_card_width and y % (PRICE_CARD_HEIGHT + PRICE_CARD_GAP) < PRICE_CARD_HEIGHT
        self._set_hovered_row(number if inside and 0 <= number < getattr(self, "price_row_count", 0) else None)

    def _set_hovered_row(self, number: int | None) -> None:
        if number == self.hovered_row:
            return
        if self.hovered_row is not None:
            self.price_canvas.itemconfig(f"card{self.hovered_row}", outline=BORDER, width=1)
        if number is not None:
            self.price_canvas.itemconfig(f"card{number}", outline=ACCENT, width=2)
        self.hovered_row = number
        self.price_canvas.config(cursor="hand2" if number is not None else "")

    def _open_price_card_wiki(self, event) -> None:
        self._hover_price_row(event)
        if self.hovered_row is not None and self.hovered_row < len(self.price_row_names):
            webbrowser.open(wiki_page(plain_item_name(self.price_row_names[self.hovered_row])))

    def _icon_tile(self, parent, image, size: int = 52, bg: str = TILE) -> tk.Frame:
        tile = tk.Frame(parent, bg=bg, width=size, height=size, highlightthickness=1, highlightbackground=BORDER)
        tile.pack_propagate(False)
        tk.Label(tile, bg=bg, image=image or "").pack(expand=True)
        return tile

    def _currency_icon_path(self, name: str) -> str | None:
        return (self.prices or {}).get("icons", {}).get(name) or self.item_art.get(name)

    def currency_icon(self, name: str, size: int = 24) -> tk.PhotoImage | None:
        return self.icons.get(self._currency_icon_path(name), size)

    def render_rates(self) -> None:
        """Comes with every section of prices, so it changes the screen only when the rate or its pictures did."""
        icon = self.currency_icon("Divine Orb", ICON_SIZE)
        key = (self.prices or {}).get("exalted_per_divine"), icon is not None, self.currency_icon("Exalted Orb", 24) is not None
        if key == self.rates_key:
            return
        self.rates_key = key
        for child in self.rates.winfo_children():
            child.destroy()
        if not self.prices:
            return
        if icon:
            self.root.iconphoto(True, icon)
            self.about_icon.config(image=icon)
        self._rate_chip("1 Divine", "Divine Orb")
        self._label(self.rates, "  =  ", MUTED, 10).pack(side="left")
        self._rate_chip(f"{format_price(self.prices['exalted_per_divine'])} Exalted", "Exalted Orb")

    def _rate_chip(self, text: str, name: str) -> None:
        label = self._label(self.rates, f" {text}", TEXT, 10, True)
        icon = self.currency_icon(name, 24)
        if icon:
            label.config(image=icon, compound="left")
        label.pack(side="left")

    def clear_body(self) -> None:
        self.base_icon_label = None
        self.alternatives_box = self.simulation_box = self.market_box = self.budget_box = self.ban_box = None
        self.rows = []
        if self.body is not self.body_shown:  # built and replaced before anyone saw it
            self.body.destroy()
        self.body = self._new_body()
        self.body.lower(self.body_shown)
        if not self.body_job:
            self.body_job = self.root.after_idle(self._show_new_body)

    def _new_body(self) -> tk.Frame:
        body = tk.Frame(self.body_area, bg=BG, padx=10)
        body.place(x=0, y=0, relwidth=1, relheight=1)
        return body

    def _show_new_body(self) -> None:
        """The crafting page's new content is laid out under the old one and only then shown."""
        self.body_job = None
        self.root.update_idletasks()
        if self.body is not self.body_shown and self.body.winfo_exists():
            self.body.lift()
            self.body_shown.destroy()
            self.body_shown = self.body

    def _show_built_page(self, built: tk.Frame, old: list) -> None:
        if built.winfo_exists():
            self.root.update_idletasks()
        if built.winfo_exists():  # looked at again: that update can run a newer rebuild of this page, which replaces this one
            built.lift()
            for child in old:
                if child.winfo_exists():
                    child.destroy()

    def load_data(self) -> None:
        data = read_json(DATA_PATH)
        try:
            self.db = Database(data) if data else None
        except Exception:  # readable but not usable: set aside, so the update builds it anew instead of failing at every start
            log_error("reading the mods")
            self.db = None
            try:
                DATA_PATH.replace(DATA_PATH.with_name(DATA_PATH.name + ".broken"))
            except OSError:
                pass
        self._offer_bases()
        if self.base and (not self.db or self.base not in self.db.bases):  # a patch can remove the open base
            self.base, self.plan, self.plans = None, None, None
            self.show_start()
        self.load_prices()

    def _offer_bases(self) -> None:
        if self.db:
            self.base_box["values"] = sorted(self.db.show_base(base) for base in self.db.bases)

    def base_matches(self, query: str) -> list[str]:
        """Bases whose English or Russian name holds what was typed: a name that begins with it first, then one with a word that does, then the rest, each by name."""
        query = query.strip().casefold()
        if not self.db or not query:
            return []
        rank: dict[str, int] = {}
        for shown, base in self.db.names.items():
            if query in shown:
                place = 0 if shown.startswith(query) else 1 if any(word.startswith(query) for word in shown.split()) else 2
                rank[base] = min(rank.get(base, place), place)
        return sorted(rank, key=lambda base: (rank[base], self.db.show_base(base).casefold()))

    def _on_base_typing(self, event) -> None:
        if event.keysym in ("Up", "Down", "Return", "KP_Enter", "Escape", "Tab"):
            return
        self._show_base_suggestions()

    def _show_base_suggestions(self) -> None:
        """A list under the base field that narrows as the player types. The field keeps the keyboard; arrows move through the list."""
        matches = self.base_matches(self.base_box.get())
        if not matches or (len(matches) == 1 and self.db.show_base(matches[0]).casefold() == self.base_box.get().strip().casefold()):
            return self._hide_base_suggestions()
        popup = self.base_popup
        if not popup or not popup.winfo_exists():
            popup = self.base_popup = tk.Toplevel(self.root, bg=BORDER)
            popup.withdraw()
            popup.overrideredirect(True)
            self.base_list = tk.Listbox(popup, bg=RAISED, fg=TEXT, selectbackground=CHOSEN, selectforeground=ON_CHOSEN, activestyle="none", relief="flat", bd=0,
                                        highlightthickness=0, font=(FONT, 10), exportselection=False, cursor="hand2")
            self.base_list.pack(padx=1, pady=1, fill="both", expand=True)
            self.base_list.bind("<ButtonRelease-1>", lambda _: self._pick_base_suggestion())
            self.base_list.bind("<Motion>", lambda event: self._hover_base_suggestion(self.base_list.nearest(event.y)))
        page_of = lambda base: self.db.bases[base]["page"]
        self.base_suggestions = grouped_bases(matches, page_of)
        self.base_list.delete(0, "end")
        for index, base in enumerate(self.base_suggestions):
            if base is None:  # a heading: the kind of the bases under it, which cannot be picked
                self.base_list.insert("end", t(base_group(page_of(self.base_suggestions[index + 1]))).upper())
                self.base_list.itemconfig(index, foreground=MUTED, background=PANEL, selectforeground=MUTED, selectbackground=PANEL)
            else:
                self.base_list.insert("end", "   " + self.db.show_base(base))
        self.base_list.configure(height=min(len(self.base_suggestions), BASE_SUGGESTIONS_SHOWN))  # the rest scroll
        self._select_base_suggestion(1)
        self.base_list.yview_moveto(0)  # the first kind's heading in sight
        popup.attributes("-topmost", bool(self.root.attributes("-topmost")))
        popup.update_idletasks()
        popup.geometry(f"{self.base_box.winfo_width()}x{self.base_list.winfo_reqheight() + 2}+{self.base_box.winfo_rootx()}+{self.base_box.winfo_rooty() + self.base_box.winfo_height()}")
        popup.deiconify()
        popup.lift()

    def _on_root_moved(self, event) -> None:
        """The base list stays under its field: when the window moves it closes. Windows also sends this when the list itself appears, so only a real move counts."""
        if event.widget is self.root and (event.x, event.y) != self.root_place:
            self.root_place = (event.x, event.y)
            self._hide_base_suggestions()

    def _base_suggestions_shown(self) -> bool:
        return bool(self.base_popup and self.base_popup.winfo_exists() and self.base_popup.state() == "normal")

    def _select_base_suggestion(self, index: int, step: int = 1) -> None:
        """Headings are stepped over, in the way the selection was going."""
        last = len(self.base_suggestions) - 1
        while 0 <= index <= last and self.base_suggestions[index] is None:
            index += step
        if not 0 <= index <= last:
            return
        self.base_list.selection_clear(0, "end")
        self.base_list.selection_set(index)
        self.base_list.see(index)
        if step < 0 and index > 0 and self.base_suggestions[index - 1] is None:
            self.base_list.see(index - 1)  # going up, the kind's heading stays in sight

    def _hover_base_suggestion(self, index: int) -> None:
        if 0 <= index < len(self.base_suggestions) and self.base_suggestions[index] is not None:
            self._select_base_suggestion(index)

    def _move_base_suggestion(self, step: int) -> str | None:
        if not self._base_suggestions_shown():
            return None  # the box's own list opens, as before
        chosen = self.base_list.curselection()
        self._select_base_suggestion((chosen[0] if chosen else 0) + step, step)
        return "break"

    def _pick_base_suggestion(self) -> None:
        chosen = self.base_list.curselection()
        if chosen and self.base_suggestions[chosen[0]] is not None:
            self.base_box.set(self.db.show_base(self.base_suggestions[chosen[0]]))
        self._hide_base_suggestions()
        self.base_box.focus_set()
        self.base_box.icursor("end")
        self.open_manual()

    def _on_base_return(self, _event=None) -> str:
        if self._base_suggestions_shown():
            self._pick_base_suggestion()
        else:
            self.open_manual()
        return "break"

    def _hide_base_suggestions(self) -> None:
        if self.base_popup and self.base_popup.winfo_exists():
            self.base_popup.withdraw()

    def _hide_base_suggestions_unless_focused(self) -> None:
        """The field loses the keyboard for a moment when the list is clicked; the list then closes itself after the pick."""
        try:
            focused = self.root.focus_get()
        except (KeyError, tk.TclError):
            focused = None
        if focused is not self.base_box:
            self._hide_base_suggestions()

    def load_prices(self) -> None:
        stored = read_prices()
        self.prices = stored if stored.get("prices_in_divine") else None
        self.league_box["values"] = [league["name"] for league in stored.get("leagues", ())] or ([stored["league"]] if stored.get("league") else [])
        self.league_box.set(stored.get("league") or "")
        self._check_watches()
        self.render_rates()
        self._refresh_nav()
        self.render_prices()
        self._prepare_graphs()

    def _prepare_graphs(self) -> None:
        """Only those not seen yet, and only when there is any point: the cards are drawn at a known width from the first time on."""
        if not self.prices or not getattr(self, "price_card_width", 0):
            return
        changes = self.prices.get("changes", {})
        card = self.price_card_width
        prepare_sparks([(data, card - 20, PRICE_GRAPH_HEIGHT, MUTED if not changes.get(name) else UP_COLOR if changes[name] > 0 else DOWN_COLOR, None) for name, data in self.prices.get("sparklines", {}).items()])

    def change_league(self, name: str) -> None:
        """Keeps what this league has seen, brings back what the other one saw, and asks for the rest. Nothing else in the program needs to know: it all goes by the league in the prices."""
        stored = read_prices()
        if name == stored.get("league"):
            return
        self._drop_what_used_old_prices()
        with league_board.lock:
            league_board.switches += 1
            league_board.choice = league_rule(name, stored.get("leagues", []))
            switch_league_files(stored.get("league"), name)
        self.save_settings(league_choice=league_board.choice)
        self.demand = clean_demand(read_json(DEMAND_PATH) or {})
        self.price_drawn_key = None
        self.load_prices()
        if self.current_tab == "demand":
            self.demand_page.render(force=True)
        self.league_box.selection_clear()
        self.update_interest.mark_active()
        self.update_interest.wake.set()
        self.set_status(t("Лига: {league}. Обновляю цены...").format(league=name))

    def _drop_what_used_old_prices(self) -> None:
        """A plan is an answer in one league's prices, and a search belongs to one league's market."""
        solving = self.solve_button and self.solve_button.winfo_exists() and self.solve_button["state"] == "disabled"
        self.solve_token += 1
        self.upgrade_token += 1
        self.stepping_aside.cancel()
        self.trade_panel = None
        if self.price_window and self.price_window.exists():
            self.price_window.window.destroy()
        if self.plan or solving:
            self.back_to_picker()

    def set_status(self, text: str) -> None:
        league = t("Лига: {league}  |  ").format(league=self.prices["league"]) if self.prices else ""
        version = t("Патч {version}  |  ").format(version=self.db.game_version) if self.db else ""
        self.status.config(text=f"{league}{version}{text}")

    def show_start(self) -> None:
        self.picker_open = False
        self._hide_preset_panel()
        self.clear_body()
        hint = tk.Frame(self.body, bg=PANEL, padx=34, pady=26, highlightthickness=1, highlightbackground=BORDER)
        hint.place(relx=0.5, rely=0.4, anchor="center")
        self._label(hint, t("Наведите курсор на предмет в игре и нажмите {copy}").format(copy=hotkey_label(self.hotkeys["copy"])), TEXT, 13, True).pack()
        self._label(hint, t("Или выберите базу вручную вверху. {toggle} показывает и скрывает окно.\nИгра должна быть в оконном режиме без рамок.").format(toggle=hotkey_label(self.hotkeys["toggle"])), MUTED, 10).pack(pady=(10, 0))
        paste = self._button(hint, t("Вставить код цели"), self.paste_goal_code)
        paste.config(font=(FONT, 9), padx=10, pady=3)
        paste.pack(pady=(14, 0))
        goals = [goal for goal in self.tools_store.get("craft_goals", []) if self.db and goal["base"] in self.db.bases][:GOALS_ON_START]
        if goals:
            self._label(hint, t("Мои цели"), SOFT, 10, True).pack(anchor="w", pady=(18, 4))
        for goal in goals:
            row = tk.Frame(hint, bg=PANEL)
            row.pack(fill="x", pady=(0, 4))
            remove = self._button(row, "×", lambda found=goal: self._remove_goal(found))
            remove.config(font=(FONT, 9), padx=8, pady=3)
            remove.pack(side="right", padx=(6, 0))
            words = self._button(row, f"{self.db.show_base(goal['base'])}  •  ilvl {goal['ilvl']}  •  {goal['label']}", lambda found=goal: self._open_goal(found))
            words.config(font=(FONT, 9), padx=10, pady=3, anchor="w")
            words.pack(side="left", fill="x", expand=True)
        self.set_status(t("Готово") if self.db else t("Загружаю данные, первая загрузка займёт пару минут..."))

    # ---- hotkeys
    def _register_hotkeys(self) -> None:
        for hotkey_id, key in enumerate(HOTKEY_ACTIONS, 1):
            user32.UnregisterHotKey(None, hotkey_id)
            enabled = key != "price" or self.settings.get("price_check", True)
            if enabled and not self.capturing and not user32.RegisterHotKey(None, hotkey_id, self.hotkeys[key]["mods"] | MOD_NOREPEAT, self.hotkeys[key]["vk"]):
                self.events.put(("status", t("{name} уже занята другой программой").format(name=hotkey_label(self.hotkeys[key]))))

    def _hotkey_loop(self) -> None:
        self.hotkey_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        self._register_hotkeys()
        message = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if message.message == WM_HOTKEY:
                self.update_interest.mark_active()
            if message.message == WM_RELOAD_HOTKEYS:
                self._register_hotkeys()
            elif message.message == WM_HOTKEY and message.wParam == 2:
                self.events.put(("toggle", None))
            elif message.message == WM_HOTKEY and not self.copy_busy:
                # One key press reads the item once; presses during a read are ignored.
                self.copy_busy = True
                foreground = user32.GetForegroundWindow()
                if foreground != self.own_window:
                    self.game_window = foreground
                purpose = HOTKEY_ACTIONS[message.wParam - 1]
                threading.Thread(target=self._copy_item, args=(purpose,), daemon=True).start()

    def _reload_hotkeys(self) -> None:
        if user32 and self.hotkey_thread:
            user32.PostThreadMessageW(self.hotkey_thread, WM_RELOAD_HOTKEYS, 0, 0)

    def _copy_item(self, purpose: str) -> None:
        try:
            self.events.put(("copied" if send_copy_keys(self.game_window, self.hotkeys[purpose]) else "not_copied", purpose))
        finally:
            self.copy_busy = False

    # ---- settings
    def save_settings(self, **changes) -> None:
        self.settings.update(changes)
        self.settings_current = False
        try:
            write_json(SETTINGS_PATH, self.settings)
        except OSError:  # the choice still works until the program closes
            log_error("saving settings.json")
            self.set_status(t("Не удалось сохранить настройки"))

    def _on_escape(self) -> None:
        if self.capturing:
            self._finish_capture()
            self.render_settings()
        else:
            self.root.withdraw()

    def render_settings(self) -> None:
        self.settings_current = True
        page = self.pages["settings"]
        old = page.winfo_children()
        built = tk.Frame(page, bg=BG, padx=10)
        built.place(x=0, y=0, relwidth=1, relheight=1)
        if old:
            built.lower(old[0])
        self.root.after_idle(self._show_built_page, built, old)
        holder = self._scroll_area(built, remember_width=False)  # all of it fits at full size; on a small screen the rest scrolls into reach

        def section(title):
            self._label(holder, title, MUTED, 9).pack(anchor="w", pady=(10, 6))

        def card():
            frame = tk.Frame(holder, bg=PANEL, highlightthickness=1, highlightbackground=BORDER, padx=12, pady=9)
            frame.pack(fill="x", pady=(0, 5))
            return frame

        section(t("Горячие клавиши"))
        for action, title in (("copy", "Открыть предмет в крафте"), ("toggle", "Показать или скрыть главное окно"), ("price", "Проверить цену предмета")):
            row = card()
            self._label(row, t(title), TEXT, 10, True).pack(side="left")
            waiting = self.capturing == action
            button = self._button(row, t("Нажмите сочетание...") if waiting else t("Изменить"), lambda a=action: self.start_capture(a))
            button.config(font=(FONT, 9), padx=10, pady=3)
            button.pack(side="right")
            self._label(row, hotkey_label(self.hotkeys[action]), SOFT, 10, True).pack(side="right", padx=14)
        reset = self._button(holder, t("Сбросить клавиши"), self.reset_hotkeys)
        reset.config(font=(FONT, 9), padx=10, pady=3)
        reset.pack(anchor="w")

        section(t("Проверка цены"))
        row = card()
        self.price_check_var = tk.BooleanVar(value=self.settings.get("price_check", True))
        self._switch(row, t("Окно цены по клавише"), self.price_check_var, self.toggle_price_check).pack(side="left")
        self._label(row, t("Цены валюты обновляются раз в час и показываются без лишних запросов."), MUTED, 9).pack(side="left", padx=14)

        section(t("Окно"))
        row = card()
        self.topmost_var = tk.BooleanVar(value=self.settings.get("topmost", True))
        self._switch(row, t("Поверх всех окон"), self.topmost_var, self.toggle_topmost).pack(side="left")
        self._label(row, t("Чёрточка вверху справа прячет окно в трей, горячие клавиши продолжают работать."), MUTED, 9).pack(side="left", padx=14)
        self._button(row, t("Выйти из программы"), self.quit).pack(side="right")
        row = card()
        self.with_game_var = tk.BooleanVar(value=self._opens_with_game())
        self._switch(row, t("Открывать вместе с Path of Exile 2"), self.with_game_var, self.toggle_with_game).pack(side="left")
        self._label(row, t("Сторож без окна стартует с Windows и открывает Sakuya с игрой. Игру не читает."), MUTED, 9).pack(side="left", padx=14)

        section(t("Оформление"))
        row = card()
        for key, theme in THEMES.items():
            self._button(row, theme["titles"][0 if language == "ru" else 1], lambda k=key: self.change_theme(k), primary=key == ACTIVE_THEME).pack(side="left", padx=(0, 6))
        self._label(row, t("Перезапуск, план крафта сбросится"), MUTED, 9).pack(side="left", padx=8)
        self.petals_var = tk.BooleanVar(value=self.settings.get("petals", True))
        self._switch(row, t("Лепестки"), self.petals_var, self.toggle_petals).pack(side="right")

        section(t("Язык"))
        row = card()
        for code, title in (("ru", "Русский"), ("en", "English")):
            active = code == language
            button = tk.Button(row, text=title, command=lambda c=code: self.change_language(c), relief="flat", bd=0, cursor="hand2", padx=14, pady=4,
                               bg=RAISED if active else PANEL, fg=TEXT if active else MUTED, activebackground=BORDER, activeforeground=TEXT, font=(FONT, 10, "bold" if active else "normal"))
            button.pack(side="left", padx=(0, 4))

    def toggle_price_check(self) -> None:
        self.save_settings(price_check=self.price_check_var.get())
        self._reload_hotkeys()

    def change_theme(self, key: str) -> None:
        """Colors are fixed when the program starts, so a new theme needs a new start.
        This copy goes quiet and shows the new theme's loading screen until the new copy, ready with its own, closes it."""
        if key == ACTIVE_THEME:
            return
        self.save_settings(theme=key)
        if not getattr(sys, "frozen", False):
            return self.set_status(t("Оформление сменится при следующем запуске"))
        place = f"+{self.root.winfo_x()}+{self.root.winfo_y()}"
        try:
            subprocess.Popen([sys.executable, REOPEN_ARGUMENT + place], env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"})
        except OSError:
            log_error("restarting for a theme")
            return self.set_status(t("Не удалось перезапустить программу, оформление сменится при следующем запуске"))
        self.closing = True  # no more hotkeys or events here: they belong to the new copy now
        if self.tray:
            self.tray.remove()
            self.tray = None
        if self.price_window and self.price_window.exists():
            self.price_window.window.withdraw()
        self.root.withdraw()
        self.loading = self._loading_screen(key)
        self.root.after(RESTART_WAIT_MS, self.quit)  # whatever happened to the new copy, this one must not stay behind

    def toggle_topmost(self) -> None:
        self.save_settings(topmost=self.topmost_var.get())
        self.root.attributes("-topmost", self.topmost_var.get())

    def start_capture(self, action: str) -> None:
        if self.capturing:
            self._finish_capture()
        self.capturing = action
        self._reload_hotkeys()  # the current keys must reach this window while a new bind is chosen
        self.capture_bind = self.root.bind("<KeyPress>", self._on_capture_key)
        self.root.focus_force()
        self.set_status(t("Нажмите новое сочетание клавиш, Esc отменяет"))
        self.render_settings()

    def _finish_capture(self) -> None:
        self.root.unbind("<KeyPress>", self.capture_bind)
        self.capturing = None
        self._reload_hotkeys()

    def _on_capture_key(self, event) -> None:
        if event.keysym.split("_")[0] in ("Control", "Alt", "Shift", "Win", "Caps", "Meta") or event.keysym == "Escape":
            return
        hotkey = hotkey_from_event(event.state, event.keycode)
        problem = hotkey_problem(hotkey, self.capturing, self.hotkeys)
        if problem:
            return self.set_status(problem)
        self.hotkeys[self.capturing] = hotkey
        self.save_settings(hotkeys=self.hotkeys)
        self._finish_capture()
        self.set_status(t("Клавиша изменена: {name}").format(name=hotkey_label(hotkey)))
        self.render_settings()

    def reset_hotkeys(self) -> None:
        self.hotkeys = dict(DEFAULT_HOTKEYS)
        self.save_settings(hotkeys=self.hotkeys)
        self._reload_hotkeys()
        self.render_settings()

    def _on_scroll_key(self, event) -> None:
        """Arrow keys, Page Up and Page Down, Home and End scroll the list on screen."""
        canvas = self.scroll_target
        focused = self.root.focus_get()
        typing = focused is not None and focused.winfo_class() in ("Entry", "TCombobox")
        if not canvas or not canvas.winfo_exists() or not canvas.winfo_ismapped() or (typing and event.keysym not in ("Prior", "Next")):
            return
        total = float(str(canvas.cget("scrollregion") or "0 0 0 1").split()[3]) or 1
        page = canvas.winfo_height()
        first = canvas.yview()[0]
        steps = {"Up": first - SCROLL_KEY_PIXELS / total, "Down": first + SCROLL_KEY_PIXELS / total, "Prior": first - page / total, "Next": first + page / total, "Home": 0, "End": 1}
        canvas.yview_moveto(steps[event.keysym])

    def _kinds_on_screen(self) -> tuple[str, ...]:
        if self.root.state() != "normal":
            return ()
        if self.current_tab == "prices":
            return (price_source(self.price_tab),)
        return self.demand_page.kinds_on_screen() if self.current_tab == "demand" else ()

    def _poll(self) -> None:
        try:
            self.update_interest.show(self._kinds_on_screen())
            self._come_back_with_game()
            self._handle_events()
        finally:
            if not self.closing:
                self.root.after(POLL_MS, self._poll)  # one failed event must not switch off the hotkeys for good

    def quit(self) -> None:
        self.closing = True
        self._save_tools()  # notes typed a moment ago wait a little before they are saved
        if self.tray:
            self.tray.remove()
        self.root.destroy()

    def _start_tray(self) -> None:
        self.tray = TrayIcon(APP_NAME, lambda: self.events.put(("toggle", None)), self._tray_menu)
        self.tray.start()

    def _tray_menu(self) -> tuple:
        """Asked anew at every right click, on the tray's own thread: it only reads, and everything it does goes through the events."""
        release = self.new_release
        return ((t("Показать или скрыть главное окно"), lambda: self.events.put(("toggle", None))),
                *(((t("Обновить до {version}").format(version=release.tag), lambda: self.events.put(("update", None))),) if release else ()),
                (t("Sakuya на GitHub"), lambda: self.events.put(("github", None))),
                (t("Сообщить о проблеме"), lambda: self.events.put(("report", None))),
                (t("Поддержать автора (скопировать адрес USDT TRC20)"), lambda: self.events.put(("support", None))),
                (t("Выход"), lambda: self.events.put(("quit", None))))

    def _handle_events(self) -> None:
        while not self.events.empty():
            kind, payload = self.events.get()
            if kind == "status":
                self.set_status(payload)
            elif kind == "reload":
                self.load_data()
                # The data brings the Russian names of currency: on a first start the cards were drawn before it came, with the English ones.
                self.price_drawn_key = None
                if self.current_tab == "prices" and self.prices:
                    self.render_prices()
                elif self.current_tab == "demand":
                    self.demand_page.render(force=True)
            elif kind == "prices":
                self.load_prices()
            elif kind == "icons":
                self.on_icons_ready()
                self._refresh_trade_art()
                if self.current_tab == "demand":
                    self.demand_page.render(force=True)
                elif self.current_tab == "build":
                    self.build_page.render(details=False)
            elif kind == "uniques":
                uniques = clean_uniques(read_json(UNIQUES_PATH) or {})
                self.unique_art, self.unique_russian, self.item_art = uniques.get("art", {}), uniques.get("russian", {}), uniques.get("items", {})
                self.exchange_names = uniques.get("exchange", {})
                self.drops = clean_drops(read_json(DROPS_PATH) or {})
                if self.current_tab == "drops":
                    self.drop_page.render()
            elif kind == "waystones":
                self.waystones = clean_waystones(read_json(WAYSTONES_PATH) or {})
            elif kind == "exchange":
                self.tools_page.show_exchange(*payload)
            elif kind == "exchange_error":
                self.tools_page.show_exchange_error(payload)
            elif kind == "simulation":
                self.on_simulation(*payload)
            elif kind == "demand":
                self.demand = clean_demand(read_json(DEMAND_PATH) or {})
                self._check_watches()
                if self.current_tab == "demand":
                    self.demand_page.render()
            elif kind == "quit":
                return self.quit()
            elif kind == "toggle":
                self.hide_or_show()
            elif kind == "support":
                self.copy_support_address()
            elif kind == "github":
                self.open_github()
            elif kind == "report":
                self.report_problem()
            elif kind == "new_version":
                self.offer_update(payload)
            elif kind == "update":
                self.start_update()
            elif kind == "update_progress":
                self._fill_update_box(t("Скачиваю новую версию: {percent}%").format(percent=payload))
            elif kind == "update_ready":
                self.finish_update(payload)
            elif kind == "update_failed":
                self.update_failed(payload)
            elif kind == "copied" and payload == "price":
                self.root.withdraw()  # a price check only needs its own window; the toggle key brings this one back
                self.check_price()
            elif kind == "copied":
                self.read_clipboard()
            elif kind == "not_copied" and payload == "price":
                self.root.withdraw()
                self._show_price(t("Проверка цены"), [(t("Предмет не прочитан: держите курсор на нём и нажмите {key} ещё раз").format(key=hotkey_label(self.hotkeys["price"])), SOFT, False)])
            elif kind == "not_copied":
                self.bring_up()
                self.set_status(t("Предмет не скопировался: держите курсор на предмете в игре и нажмите {copy} ещё раз").format(copy=hotkey_label(self.hotkeys["copy"])))
            elif kind == "plan":
                self.on_plan(payload)
            elif kind == "solve_done":
                self.on_solve_done()
            elif kind == "error":
                self.on_error(payload)
            elif kind == "alternatives":
                self.on_alternatives(*payload)
            elif kind == "trade_stats":
                self.trade_stats = None  # a new list is on disk
            elif kind == "upgrade":
                self.on_upgrade(*payload)

    def on_icons_ready(self) -> None:
        self.render_rates()
        self._refresh_nav()
        self.render_prices()
        if self.base_icon_label and self.base_icon_label.winfo_exists():
            self.base_icon_label.config(image=self.icons.get(self.db.bases.get(self.base, {}).get("icon")) or "")  # a patch can remove the open base

    def bring_up(self) -> None:
        if not self.main_prepared:  # the first time since the start, which leaves the window hidden
            self._show_main()
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", self.settings.get("topmost", True))
        self.root.focus_force()  # a window without a title bar does not take the keyboard by itself when it appears

    def hide_or_show(self) -> None:
        self.stepping_aside.cancel()  # the player has decided
        if self.root.state() == "withdrawn":
            self.bring_up()
        else:
            self.root.withdraw()

    # ---- price check
    def _price_window(self) -> PriceWindow:
        if not self.price_window or not self.price_window.exists():
            colors = {"background": BG, "panel": PANEL, "tile": TILE, "border": BORDER, "text": TEXT, "soft": SOFT, "raised": RAISED}
            self.trade_panel = None
            self.price_window = PriceWindow(self.root, colors, t("Проверка цены"), place_on_screen(self.settings.get("price_window"), all_monitors()), self._remember_price_window)
        return self.price_window

    def _remember_price_window(self, place: str) -> None:
        """Saves where the player moved the window, once it has stopped moving."""
        if self.place_job:
            self.root.after_cancel(self.place_job)
        self.place_job = self.root.after(500, lambda: self.save_settings(price_window=place))

    def _show_price(self, title: str, lines: list, image=None, **details) -> None:
        # The search panel is about to be replaced, so a late answer must not touch it.
        self.trade_panel = None
        if self._price_window().show(title, lines, image, **details) and user32 and self.game_window:
            user32.SetForegroundWindow(self.game_window)  # the first opening may take focus, so it goes straight back

    def check_price(self, again: str | None = None) -> None:
        """Shows the price of the copied item, or of one from the history. No request is sent: the prices are already on this computer."""
        self.stepping_aside.cancel()
        try:
            copied = again if again is not None else self.root.clipboard_get()
        except tk.TclError:
            copied = ""
        item = read_copied_item(copied)
        if not item or not self.prices:
            return self._show_price(t("Проверка цены"), [(t("Предмет не прочитан: держите курсор на нём и нажмите {key} ещё раз").format(key=hotkey_label(self.hotkeys["price"])), SOFT, False)])
        prices = self.prices["prices_in_divine"]
        match = None if is_waystone(copied) else find_price(item, prices, build_price_index(prices, russian_currency_name))
        good = None if match or is_waystone(copied) else exchange_good_key(item)
        unique = self._known_unique(item) if not match and not good and item.rarity.casefold() in UNIQUE_RARITIES else None
        if again is None and (not self.last_check or self.last_check[1] != copied):
            self.earlier_check, self.last_check = self.last_check, (item.lines[0] if item.lines else t("Предмет"), copied)
        if again is None:  # looking at one from the history again keeps the price it had back then
            price = self._price_text(match.each) if match else t("нет обменов") if good else self._item_price(unique) if unique else ""
            self._remember_check(show_currency(match.name) if match else item.lines[0] if item.lines else t("Предмет"), copied, price, match.name if match else unique, item.stack)
        if is_waystone(copied) and self.waystones.get("kinds"):
            return self._show_waystone(item, copied)
        if good:
            return self._show_no_trades(item, copied, good)
        if not match:
            return self._open_trade_search(item, copied)
        each, each_unit = self._price_and_unit(match.each, match.name)
        lines = [(f"{each} {UNIT_LABELS[each_unit]}", TEXT, True)]
        if match.stack > 1:
            lines.append((t("{count} шт. = {total}").format(count=format_price(match.stack), total=self._price_text(match.each * match.stack)), SOFT, False))
        change = self.prices.get("changes", {}).get(match.name)
        color = MUTED if not change else UP_COLOR if change > 0 else DOWN_COLOR
        if change is not None:
            lines.append((t("неделя {change}").format(change=f"{change:+.1f}%"), color, False))
        section = price_source(price_section(match.name, self.prices))
        if self.prices.get("kinds", {}).get(match.name) == EXCHANGE_KIND:
            lines.append((t("По обменам за прошлый час, цена примерная"), MUTED, False))
        self.update_interest.use(section)
        lines.append((t("обновлено {time}").format(time=(self.prices.get("updated", {}).get(section) or self.prices.get("fetched_at", ""))[11:16]), MUTED, False))
        graph = spark_image(self.prices.get("sparklines", {}).get(match.name), 200, 40, color)
        self._show_price(show_currency(match.name), lines, self.currency_icon(match.name, ICON_SIZE), graph=graph, actions=((t("Следить за ценой"), lambda: self._watch_from_window(match.name)), (t("Открыть на poe2db"), lambda: self._open_on_site(poe2db_link(match.name, language)))))

    def _watch_from_window(self, name: str) -> None:
        self.tools_page.fields["watch_name"].set(show_currency(name))
        self.show_tab("tools")
        self.tools_page.set_tab("watch")
        self.bring_up()

    def _show_no_trades(self, item, copied: str, good: str) -> None:
        """Hardcore markets are thin: many goods have no trades at a given moment. An old price says roughly what to expect, and the site may still have someone selling."""
        seen = next((entry for name, entry in self.prices.get("last_seen", {}).items() if name_key(name) == good), None)
        words = (t("Последняя цена {price}, {date}").format(price=self._price_text(seen["price"]), date=datetime.fromisoformat(seen["date"]).strftime("%d.%m %H:%M")), SOFT, False) if seen else (t("В этой лиге программа ещё не видела его цену"), MUTED, False)
        icon = self.icons.get(self._trade_art_path(item, self._trade_base(item, client_language(copied))))
        self._show_price(item.lines[0] if item.lines else t("Проверка цены"), [(t("Сейчас обменов нет"), TEXT, True), words], icon, actions=((t("Искать цену"), lambda: self._open_trade_search(item, copied)),))

    def _show_waystone(self, item, copied: str) -> None:
        """Warns about the mods on the player's list. It reads only the text the player copied, so nothing is sent."""
        kinds = self.waystones["kinds"]
        found = dangerous_lines(copied, kinds, danger_keys(self.tools_store.get("waystone_danger"), kinds))
        lines = [(t("Опасные моды: {count}").format(count=len(found)), DOWN_COLOR, True), *((line, DOWN_COLOR, False) for line in found)] if found else [(t("Опасных модов из вашего списка нет"), UP_COLOR, True)]
        icon = self.icons.get(self._trade_art_path(item, self._trade_base(item, client_language(copied))))
        self._show_price(item.lines[0] if item.lines else t("Проверка цены"), lines, icon, actions=((t("Искать цену"), lambda: self._open_trade_search(item, copied)),))

    # ---- the trade site: the program prepares a search, and the player's browser asks the site
    def _open_trade_search(self, item, copied: str) -> None:
        self.trade_panel = None
        language = client_language(copied)
        self.trade_item = (item, copied, language)
        stats = self._saved_trade_stats(language)
        if stats:
            return self._show_trade_panel(stats)
        url = trade_search_url(item, self.prices.get("league", "Standard"), self.db.names if self.db else {})  # the list of mods has not come yet, but the site can still be opened on the base
        icon = self.icons.get(self._trade_art_path(item, self._trade_base(item, language)))
        self._show_price(item.lines[0] if item.lines else t("Проверка цены"), [(t("Список модов для поиска ещё загружается, пока сайт откроется только с базой предмета."), SOFT, False)], icon, actions=((t("Открыть сайт торговли"), lambda: self._open_on_site(url)),))

    def _saved_trade_stats(self, language: str) -> dict | None:
        if self.trade_stats is None:
            self.trade_stats = clean_trade_stats(read_json(TRADE_STATS_PATH) or {})
        saved = self.trade_stats.get(language)
        return saved["index"] if saved else None

    def _known_unique(self, item) -> str | None:
        """The name hot items know a unique by, as either client writes it."""
        shown = (item.lines[0] if item.lines else "").casefold()
        return next((name for name in self.demand.get("items", {}) if shown and shown in (name.casefold(), self.unique_russian.get(name, "").casefold())), None)

    def _open_in_craft(self, copied: str) -> None:
        self.show_tab("craft")
        try:
            self.take_item(parse_item(copied, self.db))
        except ValueError as error:
            self.set_status(str(error))
        self.bring_up()

    def _open_on_site(self, url: str) -> None:
        """The browser gets the screen: the windows that would cover it wait until the player is back in the game."""
        if not webbrowser.open(url) or not user32 or not self.game_window or not user32.IsWindow(self.game_window):
            return  # no browser came up, or no game to come back to: nothing waits for it
        windows = [window for window in (self.price_window.window if self.price_window and self.price_window.exists() else None, self.root) if window and window.state() == "normal"]
        for window in windows:
            window.withdraw()
        self.stepping_aside.start(windows)

    def _come_back_with_game(self) -> None:
        if not user32 or not self.stepping_aside.windows:
            return
        if not user32.IsWindow(self.game_window):  # the game has closed, so nothing would ever bring them back
            self.stepping_aside.left_game = True
        foreground = self.game_window if not user32.IsWindow(self.game_window) else user32.GetForegroundWindow()
        for window in self.stepping_aside.windows_to_bring_back(foreground, self.game_window):
            if self.price_window and self.price_window.exists() and window is self.price_window.window:
                self.price_window.open()
            elif window is self.root:
                self.root.deiconify()
                self.root.lift()

    def _price_upgrade(self, page_name: str, parsed, mods: list) -> None:
        """Worked out only when asked, on its own thread at low priority: the game is usually running."""
        page = self.db.pages[page_name]
        panel = self.trade_panel
        try:
            wants, title = upgrade_goal(page, mods, parsed.ilvl, parsed.base)
            start = self._state_of(parsed, wants, page)
            prices = {name: value for name, value in prices_in_exalted(self.prices).items() if name not in self.banned}
        except (ValueError, TypeError) as error:
            return panel.show_note(str(error))
        panel.show_note(t("Считаю цену улучшения..."))
        self.upgrade_token += 1
        token = self.upgrade_token

        def work():
            set_process_priority(BELOW_NORMAL_PRIORITY)
            try:
                cost = Planner(page, parsed.ilvl, wants, prices, base=parsed.base).solve(start).values.get(start)
                self.events.put(("upgrade", (token, title, cost)))
            except ValueError as error:
                self.events.put(("upgrade", (token, str(error), None)))
            except Exception:
                log_error("pricing an upgrade")
                self.events.put(("upgrade", (token, t("Не удалось посчитать, подробности в errors.log"), None)))
            finally:
                set_process_priority(NORMAL_PRIORITY)
        threading.Thread(target=work, daemon=True).start()

    def on_upgrade(self, token: int, words: str, cost: float | None) -> None:
        if token == self.upgrade_token and self.trade_panel and self.prices:
            rate = self.prices["exalted_per_divine"]
            self.trade_panel.show_note(words if cost is None else t("{mod}: на тир выше, в среднем {cost}. Другие лучшие моды сохраняются.").format(mod=words, cost=format_cost(cost, rate, self.prices.get("chaos_per_divine"))))

    def _compare_items(self, item, copied: str) -> None:
        name, other = self.earlier_check
        lines = [(t("Сравнение: слева этот, справа {name}").format(name=name), SOFT, False)]
        for wording, ours, theirs in compared_lines(copied, other)[:COMPARE_LINES_SHOWN]:
            better = (ours or 0) > (theirs or 0)
            same = ours == theirs
            lines.append((f"{(ours if ours is not None else 0):g}  ·  {(theirs if theirs is not None else 0):g}   {wording}", SOFT if same else UP_COLOR if better else DOWN_COLOR, False))
        self._show_price(item.lines[0] if item.lines else t("Проверка цены"), lines if len(lines) > 1 else [(t("Нет модов для сравнения"), SOFT, False)], None, actions=((t("Назад"), lambda: self._open_trade_search(item, copied)),))

    def _site_link(self, mods: list, strictness: float, base: str, unique: bool) -> str:
        item, _, language = self.trade_item
        category = trade_category(self.trade_page_name) if self.trade_panel and self.trade_panel.any_base else None
        query = build_query(item.lines[0] if unique and item.lines else None, base, unique, mods, strictness, category)
        return trade_site_url(language, (self.prices or {}).get("league", "Standard"), query)

    def _open_search_on_site(self, mods: list, strictness: float, base: str, unique: bool) -> None:
        self.tools_store["search_memory"] = remember_search(self.tools_store.get("search_memory", {}), self.trade_memory_key, mods, strictness)
        self._save_tools()
        self._open_on_site(self._site_link(mods, strictness, base, unique))

    def _bookmark_search(self, mods: list, strictness: float, base: str, unique: bool) -> None:
        link = self._site_link(mods, strictness, base, unique)
        name = " ".join(dict.fromkeys(self.trade_item[0].lines[:2])) or link
        self.tools_store["bookmarks"] = add_bookmark(self.tools_store.get("bookmarks", []), name, "", link, datetime.now().strftime("%d.%m.%Y"))
        self._save_tools()
        self.tools_page.show_if_open("bookmarks")

    def open_unique_on_site(self, name: str, base: str) -> None:
        self._open_on_site(trade_site_url("en", (self.prices or {}).get("league", "Standard"), build_query(name, base, True, [], 0)))

    def _trade_base(self, item, language: str) -> str:
        names = self.db.names if self.db else {}
        text = " ".join(item.lines).casefold()
        known = [shown for shown in names if shown in text]
        if not known:
            return item.lines[-1] if item.lines else ""
        base = names[max(known, key=len)]
        return self.db.bases[base].get("ru", base) if language == "ru" else base

    def _trade_art_path(self, item, base: str) -> str | None:
        """A unique has art of its own. Any other item looks like its base."""
        if item.rarity.casefold() in UNIQUE_RARITIES and item.lines and item.lines[0].casefold() in self.unique_art:
            return self.unique_art[item.lines[0].casefold()]
        name = next((key for key, info in (self.db.bases.items() if self.db else ()) if base in (key, info.get("ru"))), None)
        if name:
            return self.db.bases[name].get("icon")
        named = self._art_name_in(item.lines[-1]) if item.lines and item.rarity.casefold() not in UNIQUE_RARITIES else None  # a jewel, flask or charm: no crafting base, but art all the same
        return self.item_art.get(named) if named else None

    def _trade_art(self):
        item, _, language = self.trade_item
        path = self._trade_art_path(item, self._trade_base(item, language))
        return (self.icons.get(LARGE_ART + path) or self.icons.get(path)) if path else None

    def _refresh_trade_art(self) -> None:
        if self.trade_panel:
            self.trade_panel.set_art(self._trade_art())

    def _show_trade_panel(self, index: dict) -> None:
        item, copied, language = self.trade_item
        unique = item.rarity.casefold() in UNIQUE_RARITIES
        base = self._trade_base(item, language)
        colors = {"background": BG, "panel": PANEL, "tile": TILE, "border": BORDER, "text": TEXT, "soft": SOFT, "muted": MUTED, "raised": RAISED, "stripe": BG, "up": UP_COLOR, "down": DOWN_COLOR, "accent": ACCENT, "accent_light": ACCENT_LIGHT, "ink": INK}
        colors["away"] = RARITY_COLORS["unique"]
        window = self._price_window()
        self.upgrade_token += 1  # an answer still on its way was about the item shown before
        mods = read_item_mods(copied, index)
        if not unique:
            mods = [*read_item_totals(copied, index), *mods]
        art = self._trade_art()
        self.trade_memory_key = search_memory_key(copied, item.lines[0] if item.lines else None, unique)
        memory = self.tools_store.get("search_memory", {}).get(self.trade_memory_key)
        recalled = recalled_mods(memory, mods)
        window.clear()  # only now: a failure above must not leave an empty window
        notes = []
        if unique:
            known = self._known_unique(item)
            if known:
                entry = self.demand["items"][known]
                notes.append((t("Средняя цена {price}, объявлений {count}").format(price=self._price_text(entry["price"]), count=format_price(entry["listings"])), True))
                notes.append((t("Без учёта роллов.") + (" " + t("Объявлений мало, цена неточная.") if entry["listings"] < UNIQUE_FEW_LISTINGS else ""), False))
                self.update_interest.use(entry["kind"])
            else:
                notes.append((t("Средней цены нет: сайт цен не считает этот предмет в этой лиге."), False))
        else:
            quality = item_quality(read_item_mods(copied, index))
            if quality is not None:
                notes.append((t("Качество модов: {score} из 100").format(score=quality), True))
                notes.append((t("Оценка тиров и роллов, это не цена."), False))
        base_key = next((name for name, info in self.db.bases.items() if base in (name, info.get("ru"))), None) if self.db and base else None
        page_name = self.db.bases[base_key]["page"] if base_key else None
        hints, extras = {}, []
        parsed = None
        if page_name and not unique:
            try:
                parsed = parse_item(copied, self.db)
            except ValueError:
                pass  # the window still works without what this adds
        if parsed:
            page = self.db.pages[page_name]
            hints = {mod.label: next_tier_hint(page, mod.label, mod.tier, parsed.ilvl) for mod in mods if mod.tier}
            extras.append((t("Улучшить в крафте"), lambda: self._open_in_craft(copied)))
            if not parsed.corrupted and upgrade_goal(page, mods, parsed.ilvl, parsed.base):
                extras.append((t("Цена улучшения"), lambda: self._price_upgrade(page_name, parsed, mods)))
        if self.earlier_check and self.earlier_check[1] != copied:
            extras.append((t("Сравнить с: {name}").format(name=self.earlier_check[0][:22]), lambda: self._compare_items(item, copied)))
        site_name = self._known_unique(item) if unique else base_key
        if site_name:
            extras.append((t("Открыть на poe2db"), lambda: self._open_on_site(poe2db_link(site_name, language))))
        self.trade_panel = TradeSearchPanel(window.body, colors, t, item.lines[0] if item.lines else base, item.lines[-1] if item.lines else "", RARITY_COLORS.get(item.rarity.casefold(), TEXT), art, mods, recalled or mods_on_by_default(mods, unique),
                                            lambda mods, strictness: self._open_search_on_site(mods, strictness, base, unique), lambda mods, strictness: self._bookmark_search(mods, strictness, base, unique), memory["strictness"] if recalled else 0.9, bool(recalled), tuple(notes), tuple(extras), bool(not unique and trade_category(page_name)), hints)
        self.trade_page_name = page_name
        if window.open() and user32 and self.game_window:
            user32.SetForegroundWindow(self.game_window)

    # ---- item intake
    def read_clipboard(self) -> None:
        """The page is made ready first, and only then does the window come up, so the old page does not flash and jump."""
        self.stepping_aside.cancel()
        self.show_tab("craft")
        if not self.db:
            self.set_status(t("Данные ещё загружаются, подождите"))
            return self.bring_up()
        try:
            self.take_item(parse_item(self.root.clipboard_get(), self.db))
        except (tk.TclError, ValueError) as error:
            self.set_status(str(error))
        self.bring_up()

    def take_item(self, item: ParsedItem) -> None:
        if self.plan and item.base == self.base and item.ilvl == self.ilvl:
            self.item = item
            return self.follow_item(item)
        self.solve_token += 1
        self.item, self.base, self.ilvl, self.plan, self.plans = item, item.base, item.ilvl, None, None
        self.base_box.set(self.db.show_base(item.base))
        self.ilvl_var.set(str(item.ilvl))
        self.show_picker()
        page = self.db.pages[self.db.bases[item.base]["page"]]
        unknown = sum(page.find_mod(side, name) is None for side, name in item.mods)
        warnings = []
        if item.corrupted:
            warnings.append(t("предмет осквернён, менять его нельзя"))
        if item.rarity != "normal" and not item.mods:
            warnings.append(t("игра не показала подробные моды, текущие моды не учтены"))
        if unknown:
            warnings.append(t("не распознано модов: {count}, считаю их лишними").format(count=unknown))
        self.set_status("; ".join(warnings) or t("Выберите нужные моды и нажмите «Рассчитать»"))

    def open_manual(self) -> None:
        try:
            base = self.db.find_base(self.base_box.get().strip())
            if base != self.base:
                self.solve_token += 1  # a plan of the old base, still being worked out, stops
            self.base = base
            self.ilvl = int(self.ilvl_var.get())
        except (ValueError, AttributeError) as error:
            return self.set_status(str(error) if self.db else t("Данные ещё загружаются"))
        self.base_box.set(self.db.show_base(self.base))
        self.item, self.plan, self.plans = None, None, None
        self.show_picker()

    # ---- mod picker
    def show_picker(self) -> None:
        self.clear_body()
        page = self.db.pages[self.db.bases[self.base]["page"]]
        shown_base = self.db.show_base(self.base)
        name = f"{self.item.name}  •  " if self.item and self.item.name != shown_base else ""
        self._craft_header(f"{name}{shown_base}  •  ilvl {self.ilvl}")
        search_bar = tk.Frame(self.body, bg=BG)
        search_bar.pack(fill="x", pady=(0, 8))
        self._label(search_bar, t("Поиск"), MUTED, 9).pack(side="left", padx=(0, 8))
        self.search = tk.StringVar()
        trace_while(self.search, search_bar, lambda *_: self._after_typing(self.apply_search))
        search_entry = self._entry(search_bar, self.search)
        search_entry.pack(side="left", fill="x", expand=True, ipady=5)
        self._label(search_bar, t("например: добавляет от до  •  холоду  •  скорость атаки"), MUTED, 9).pack(side="left", padx=(10, 0))
        for text, command in ((t("Вставить код"), self.paste_goal_code), (t("Код цели"), self.copy_goal_code), (t("Сохранить цель"), self.save_craft_goal)):
            button = self._button(search_bar, text, command)
            button.config(font=(FONT, 9), padx=10, pady=3)
            button.pack(side="right", padx=(8, 0))
        self.goal_box = ttk.Combobox(search_bar, width=18, state="readonly", font=(FONT, 9))
        self.goal_box.pack(side="right", padx=(8, 0))
        self.goal_box.bind("<<ComboboxSelected>>", lambda _: self._pick_goal())
        self.goal_box.bind("<MouseWheel>", lambda _: "break")  # scrolling past it must not change the choice
        self._offer_goals()
        columns = self.picker_columns = tk.Frame(self.body, bg=BG)
        columns.pack(fill="both", expand=True)
        columns.columnconfigure((0, 1), weight=1, uniform="sides")
        columns.rowconfigure(0, weight=1)
        self.rows = []
        self.counters = {}
        self.lists = {}
        self.open_vars, self.open_switches = {}, {}
        on_item = self._mods_on_item(page)
        for column, (side, title) in enumerate((("prefix", t("Префиксы")), ("suffix", t("Суффиксы")))):
            panel = tk.Frame(columns, bg=BG)
            panel.grid(row=0, column=column, sticky="nsew", padx=(0, 6) if column == 0 else (6, 0))
            header_row = tk.Frame(panel, bg=BG)
            header_row.pack(fill="x")
            header = self._label(header_row, title, SOFT, 10, True)
            header.pack(side="left")
            self.open_vars[side] = tk.BooleanVar(value=False)
            self.open_switches[side] = self._switch(header_row, t("оставить место"), self.open_vars[side], self._update_headers, MUTED, 8)
            self.open_switches[side].pack(side="right")
            self.counters[side] = (header, title)
            canvas = self._mod_list(panel, side)
            for ladder in page.ladders:
                if ladder.side == side and ladder.available(self.ilvl):
                    self._add_row(canvas, ladder, on_item.get(ladder.template))
            for ladder in page.desecrated_ladders:
                if ladder.side == side and ladder.available(self.ilvl):
                    self._add_row(canvas, ladder, on_item.get(ladder.template), t("только через кость Бездны"))
            for ladder in page.rune_ladders:
                if ladder.side == side and ladder.available(self.ilvl):
                    self._add_row(canvas, ladder, on_item.get(ladder.template), t("нужна руна «{rune}», вес неизвестен").format(rune=show_currency(ladder.mods[0].rune)))
            for ladder in page.special_ladders:
                if ladder.side == side and ladder.available(self.ilvl):
                    self._add_row(canvas, ladder, on_item.get(ladder.template), t("только через «{item}»").format(item=show_currency(ladder.mods[0].only_from)))
            self._draw_mod_list(side)
        bottom = self.bottom_bar = tk.Frame(self.body, bg=PANEL, highlightthickness=1, highlightbackground=BORDER, padx=10, pady=7)
        bottom.pack(side="bottom", fill="x", pady=(8, 0), before=columns)  # placed before the lists, so that when room runs out they shrink and the buttons stay
        self.allow_new_base = tk.BooleanVar(value=self.base_allowed[self.craft_mode])
        self._switch(bottom, t("Можно брать новую базу, цена в Divine:"), self.allow_new_base, self._remember_base_choice, SOFT, 9).pack(side="left")
        self.base_price = tk.StringVar(value="0.01")
        self._entry(bottom, self.base_price, 6).pack(side="left", padx=8, ipady=3)
        self.pool_bar = tk.Frame(bottom, bg=PANEL)  # shown once two mods are in the group
        self.pool_bar.pack(side="left", padx=(8, 0))
        self._label(self.pool_bar, t("Из группы ◇ нужно:"), SOFT, 9, bg=PANEL).pack(side="left")
        self.pool_need_box = ttk.Combobox(self.pool_bar, width=3, state="readonly", font=(FONT, 9))
        self.pool_need_box.pack(side="left", padx=6)
        self.pool_need_box.bind("<MouseWheel>", lambda _: "break")
        self.pool_size = self._label(self.pool_bar, "", SOFT, 9, bg=PANEL)
        self.pool_size.pack(side="left")
        if not page.weights_known:
            self._label(bottom, t("⚠ Весов этого типа нет на poe2db: шансы очень грубые"), SOFT, 9).pack(side="left", padx=8)
        self.solve_button = self._button(bottom, t("Рассчитать"), self.start_solve, primary=True)
        self.solve_button.pack(side="right")
        self.ban_button = self._button(bottom, "", self.toggle_ban_box)
        self.ban_button.config(font=(FONT, 9), padx=10, pady=4)
        self.ban_button.pack(side="right", padx=(0, 8))
        self._paint_ban_button()
        self.update_counters()
        search_entry.focus_set()
        self.picker_open = True
        self._show_preset_panel()

    def _show_preset_panel(self) -> None:
        """A window of its own beside the main one, a few centimetres off, with the ready goals that fit the open base. It follows the main window and hides with it."""
        if not (self.picker_open and self.current_tab == "craft" and self.db and self.base) or self.closing:
            return self._hide_preset_panel()
        presets = self._presets_here()
        if not presets:
            return self._hide_preset_panel()
        panel = self.preset_panel
        if not panel or not panel.winfo_exists():
            panel = self.preset_panel = tk.Toplevel(self.root, bg=BORDER)
            panel.withdraw()
            panel.overrideredirect(True)
        for child in panel.winfo_children():
            child.destroy()
        inner = tk.Frame(panel, bg=PANEL, padx=12, pady=10)
        inner.pack(padx=1, pady=1, fill="both", expand=True)
        self._label(inner, t("Пресеты"), TEXT, 11, True, bg=PANEL).pack(anchor="w", pady=(0, 8))
        for label, goal in presets:
            card = tk.Frame(inner, bg=RAISED, padx=10, pady=7, cursor="hand2")
            card.pack(fill="x", pady=(0, 6))
            title = self._label(card, label, TEXT, 10, True, wrap=PRESET_PANEL_WIDTH - 2 - 24 - 20 - 4, bg=RAISED)  # a long name goes on a second line inside the card's padding
            title.pack(anchor="w")
            for widget in (card, title):
                widget.bind("<Button-1>", lambda _, goal=goal: self._use_preset(goal))
                widget.bind("<Enter>", lambda _, card=card: self._paint_card(card, BORDER))
                widget.bind("<Leave>", lambda _, card=card: self._paint_card(card, RAISED))
        panel.attributes("-topmost", bool(self.root.attributes("-topmost")))
        self._paint_presets()
        self._place_preset_panel()

    def _use_preset(self, goal: dict) -> None:
        """A click on a preset marks its mods and works out the path at once. From a plan it goes back to the mods first.
        While a plan is being worked out, another click waits: each plan of a large goal takes up to a gigabyte, and two at once brought the program down."""
        if self.solves_running:
            return self.set_status(t("Уже считаю план, дождитесь результата"))
        if not self.rows:
            self.show_picker()
        self._apply_goal(goal)
        self.start_solve()

    @staticmethod
    def _paint_card(card: tk.Frame, color: str) -> None:
        for widget in (card, *card.winfo_children()):
            widget.configure(bg=color)

    def _place_preset_panel(self) -> None:
        panel = self.preset_panel
        if not panel or not panel.winfo_exists() or not panel.winfo_children():
            return
        try:
            if self.closing or not self.picker_open or self.current_tab != "craft" or not self.root.winfo_viewable():
                return panel.withdraw()
            panel.update_idletasks()
            gap = round(self.root.winfo_fpixels(PRESET_PANEL_GAP))
            height = min(panel.winfo_reqheight(), self.root.winfo_height())
            left, top, right, _ = all_monitors()
            x = self.root.winfo_rootx() + self.root.winfo_width() + gap
            if x + PRESET_PANEL_WIDTH > left + right:  # no room on the right: the left side
                x = self.root.winfo_rootx() - gap - PRESET_PANEL_WIDTH
            x, y = max(x, left), self.root.winfo_rooty()
            panel.geometry(f"{PRESET_PANEL_WIDTH}x{height}+{x}+{y}")
            if panel.state() != "normal":
                panel.deiconify()
            panel.lift()
            settle_window(panel, x, y)
        except tk.TclError:  # the window is being rebuilt or closed
            pass

    def _hide_preset_panel(self) -> None:
        panel = self.preset_panel
        if panel and panel.winfo_exists():
            panel.withdraw()

    def _presets_here(self) -> list[tuple[str, dict]]:
        """Ready goals from guides that fit this base: each is kept only if every one of its mods can roll here."""
        page = self.db.pages[self.db.bases[self.base]["page"]]
        found = []
        for label, pages, mods in CRAFT_PRESETS:
            if not page.name.startswith(pages):
                continue
            goal = preset_goal(page, self.ilvl, mods, self.base)
            if goal:
                found.append((t(label), goal))
        return found

    def _goals_here(self) -> list[dict]:
        """Goals for any base of this kind: they share their mods."""
        page = self.db.bases[self.base]["page"]
        return [goal for goal in self.tools_store.get("craft_goals", []) if goal["base"] in self.db.bases and self.db.bases[goal["base"]]["page"] == page]

    def _offer_goals(self) -> None:
        self.goal_box["values"] = [goal["label"] for goal in self._goals_here()]
        self.goal_box.set(t("Мои цели"))

    def _pick_goal(self) -> None:
        goals = self._goals_here()
        if 0 <= self.goal_box.current() < len(goals):
            self._apply_goal(goals[self.goal_box.current()])

    def save_craft_goal(self) -> None:
        chosen = [row for row in self.rows if row["checked"].get()]
        if not chosen:
            return self.set_status(t("Выберите хотя бы один мод"))
        goal = self._current_goal()
        label = " + ".join(row["text"] for row in chosen[:2])[:56] + (f" +{len(chosen) - 2}" if len(chosen) > 2 else "")
        self.tools_store["craft_goals"] = add_craft_goal(self.tools_store.get("craft_goals", []), self.base, self.ilvl, goal["mods"], label, goal.get("need", 0), goal.get("open"))
        self._save_tools()
        self._offer_goals()
        self.set_status(t("Цель сохранена"))

    def _current_goal(self) -> dict:
        """The goal as chosen on the screen, in the shape goals are saved in."""
        mods = []
        need = self.pool_need()
        for row in self.rows:
            if row["checked"].get():
                tier = re.match(r"T(\d+)", row["tier"].get())
                mods.append({**goal_key(row["ladder"]), "tier": int(tier.group(1)) if tier else None, **({"pool": True} if need and row["pool"] else {})})
        return {"base": self.base, "ilvl": self.ilvl, "label": "", "mods": mods, **({"need": need} if need else {}), **({"open": self.open_slots()} if self.open_slots() else {})}

    def copy_goal_code(self) -> None:
        goal = self._current_goal()
        if not goal["mods"]:
            return self.set_status(t("Выберите хотя бы один мод"))
        self.root.clipboard_clear()
        self.root.clipboard_append(goal_code(goal))
        self.set_status(t("Код цели скопирован: вставьте его другу, а он нажмёт «Вставить код»"))

    def paste_goal_code(self) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            text = ""
        goal = read_goal_code(text)
        if not goal:
            return self.set_status(t("В буфере обмена нет кода цели Sakuya"))
        if not self.db or goal["base"] not in self.db.bases:
            return self.set_status(t("Такой базы нет в данных: {base}").format(base=goal["base"]))
        self._open_goal(goal)

    def _apply_goal(self, goal: dict) -> None:
        """Marks the goal's mods. One this item cannot have stays out, and the player is told."""
        wanted = {(mod["template"], mod["side"], mod["desecrated"], mod.get("rune", "")): mod for mod in goal["mods"]}
        found = set()
        for row in self.rows:
            key = tuple(goal_key(row["ladder"]).values())
            row["checked"].set(key in wanted)
            row["pool"] = bool(key in wanted and wanted[key].get("pool"))
            if key in wanted:
                found.add(key)
                values = list(row["tier"]["values"])
                tier = t("T{tier} и лучше").format(tier=wanted[key]["tier"])
                row["tier"].current(values.index(tier) if tier in values else 0)
        for side, chosen in getattr(self, "open_vars", {}).items():
            chosen.set(bool(goal.get("open", {}).get(side)))
        self.update_counters()
        self._redraw_open_switches()
        if goal.get("need"):
            values = list(self.pool_need_box["values"])
            if str(goal["need"]) in values:
                self.pool_need_box.set(str(goal["need"]))
        self.apply_search()
        self.set_status(t("Цель открыта, но модов не хватает: {count}").format(count=len(wanted) - len(found)) if len(found) < len(wanted) else t("Цель открыта: нажмите «Рассчитать»"))

    def _open_goal(self, goal: dict) -> None:
        self.solve_token += 1
        self.base, self.ilvl = goal["base"], goal["ilvl"]
        self.base_box.set(self.db.show_base(self.base))
        self.ilvl_var.set(str(self.ilvl))
        self.item, self.plan, self.plans = None, None, None
        self.show_picker()
        self._apply_goal(goal)

    def _remove_goal(self, goal: dict) -> None:
        self.tools_store["craft_goals"] = [other for other in self.tools_store.get("craft_goals", []) if other != goal]
        self._save_tools()
        self.show_start()

    def _ban_choices(self) -> list[str]:
        page = self.db.pages[self.db.bases[self.base]["page"]]
        orbs = [currency[0] for currency in CURRENCIES.values() if currency[0] and currency[0] != NEW_BASE]
        return [*orbs, *OMENS, *page.bones(self.ilvl)]

    def _paint_ban_button(self) -> None:
        self.ban_button.config(text=t("Без каких сфер ({count})").format(count=len(self.banned)) if self.banned else t("Без каких сфер"))

    def toggle_ban_box(self) -> None:
        if self.ban_box and self.ban_box.winfo_exists():
            self.ban_box.destroy()
            self.ban_box = None
            return
        self.ban_box = tk.Frame(self.body, bg=PANEL, highlightthickness=1, highlightbackground=BORDER, padx=8, pady=6)
        self.ban_box.pack(fill="x", pady=(0, 8), before=self.picker_columns)  # above the lists, which give up their height to it
        self._label(self.ban_box, t("Нажмите на то, чего у вас нет или что не хотите тратить: план обойдётся без этого."), MUTED, 9).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        hide = self._button(self.ban_box, t("Скрыть"), self.toggle_ban_box)
        hide.config(font=(FONT, 9), padx=10, pady=2)
        hide.grid(row=0, column=3, sticky="e", padx=2, pady=(0, 4))
        for column in range(4):
            self.ban_box.columnconfigure(column, weight=1, uniform="ban")
        for number, name in enumerate(self._ban_choices()):
            # Omens differ only at the end of their names, which the long common start would push out of the button.
            button = tk.Button(self.ban_box, text=f" {show_currency(name).removeprefix('Предзнаменование ').removeprefix('Omen of ')}", image=self.currency_icon(name, 20) or "", compound="left", anchor="w", relief="flat", bd=0, cursor="hand2", padx=2, pady=0, font=(FONT, 8))
            button.config(command=lambda n=name, b=button: self._toggle_ban(n, b))
            button.grid(row=number // 4 + 1, column=number % 4, sticky="ew", padx=2, pady=1)
            self._paint_ban_choice(name, button)

    def _paint_ban_choice(self, name: str, button: tk.Button) -> None:
        banned = name in self.banned
        button.config(bg=MOD_ON_GROUND if banned else RAISED, fg=DOWN_COLOR if banned else TEXT, activebackground=BORDER, activeforeground=TEXT, font=(FONT, 8, "overstrike" if banned else "normal"))

    def _toggle_ban(self, name: str, button: tk.Button) -> None:
        self.banned ^= {name}
        self.save_settings(craft_banned=sorted(self.banned))
        self._paint_ban_choice(name, button)
        self._paint_ban_button()

    def _remember_base_choice(self) -> None:
        self.base_allowed[self.craft_mode] = self.allow_new_base.get()

    def _craft_header(self, title: str, plans: dict | None = None, back: bool = False) -> None:
        """The item on the left, the two ways to craft it next to it."""
        head = tk.Frame(self.body, bg=BG)
        head.pack(fill="x", pady=(0, 10))
        head.columnconfigure(1, weight=1)
        item = tk.Frame(head, bg=BG)
        item.grid(row=0, column=0, sticky="w", padx=(0, 14))
        tile = self._icon_tile(item, self.icons.get(self.db.bases[self.base].get("icon")), 56)
        tile.pack(side="left", padx=(0, 10))
        self.base_icon_label = tile.winfo_children()[0]
        self._label(item, title, TEXT, 12, True, 250).pack(side="left")
        cards = tk.Frame(head, bg=BG)
        cards.grid(row=0, column=1, sticky="ew")
        cards.columnconfigure((0, 1), weight=1, uniform="modes")
        self.mode_cards = {}
        self.mode_risk = {}
        for column, mode in enumerate(CRAFT_MODES):
            self._mode_card(cards, mode, column, plans)
        self._style_mode_cards()
        self._render_mode_risk()
        if back:
            self._button(head, t("←  Выбор модов"), self.back_to_picker).grid(row=0, column=2, padx=(10, 0))

    def _mode_card(self, parent, mode: str, column: int, plans: dict | None) -> None:
        card = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=BORDER, cursor="hand2")
        card.grid(row=0, column=column, sticky="nsew", padx=(0, 6) if column == 0 else (0, 0))
        tile = self._icon_tile(card, self.currency_icon(MODE_ICONS[mode], ICON_SIZE), 52)
        tile.pack(side="left", padx=4, pady=4)
        words = tk.Frame(card, bg=PANEL)
        words.pack(side="left", fill="x", padx=(6, 6))
        title = self._label(words, t(MODE_TITLES[mode]), TEXT, 11, True)
        title.pack(anchor="w")
        painted = [card, words, title]
        if plans:
            plan = plans[mode]
            lines = [(format_cost(plan.values.get(plan.start, 0), self.prices["exalted_per_divine"], self.prices.get("chaos_per_divine")), TEXT, True),
                     (t("примерно {count} действий").format(count=format_price(round(plan.action_count))), MUTED, False)]
        else:
            lines = [(t("Меньше трат, можно менять базы") if mode == "budget" else t("Меньше нажатий, база остаётся той же"), SOFT, False)]
        for line, color, bold in lines:
            label = self._label(words, line, color, 9, bold)
            label.pack(anchor="w")
            painted.append(label)
        if plans:
            self.mode_risk[mode] = self._label(words, "", SOFT, 9, wrap=170)
            self.mode_risk[mode].pack(anchor="w")
            painted.append(self.mode_risk[mode])
        for widget in (*painted, tile, *tile.winfo_children()):
            widget.bind("<Button-1>", lambda _, m=mode: self.set_craft_mode(m))
        self.mode_cards[mode] = painted

    def _style_mode_cards(self) -> None:
        for mode, painted in self.mode_cards.items():
            active = mode == self.craft_mode
            for widget in painted:
                widget.config(bg=RAISED if active else PANEL)
            painted[0].config(highlightbackground=ACCENT if active else BORDER)

    def _render_mode_risk(self) -> None:
        """What bad luck costs in each way to craft, so that a cheap average does not hide a wide spread."""
        if not self.plans or not self.mode_risk:
            return
        surer = surer_mode(self.plans)
        rate, chaos = self.prices["exalted_per_divine"], self.prices.get("chaos_per_divine")
        for mode, label in self.mode_risk.items():
            result = self.plans[mode].simulation
            if label.winfo_exists() and isinstance(result, Simulation):
                words = t("9 из 10 до {cost}").format(cost=format_cost(result.unlucky, rate, chaos))
                label.config(text=f"{words}  •  {t('надёжнее')}" if mode == surer else words, fg=UP_COLOR if mode == surer else SOFT)

    def set_craft_mode(self, mode: str) -> None:
        if mode == self.craft_mode:
            return
        self.craft_mode = mode
        self.save_settings(craft_mode=mode)
        if not self.plan:
            self.allow_new_base.set(self.base_allowed[mode])
            return self._style_mode_cards()
        plan = self.plans[mode]
        if self.state in plan.policy or plan.planner.is_goal(self.state):
            self.plan, self.alternatives = plan, None
            self.show_guide()
            self._find_alternatives(plan)
        else:
            self.set_status(t("Такого состояния не было в плане, пересчитываю..."))
            self._solve_async(self.db.pages[self.db.bases[self.base]["page"]], self.plan.planner.wants, self.state)

    def _mods_on_item(self, page: Page) -> dict[str, str]:
        marks = {}
        for side, name in (self.item.mods if self.item else []):
            mod = page.find_mod(side, name)
            if mod:
                ladder = next(l for l in (*page.ladders, *page.desecrated_ladders) if mod in l.mods)
                marks[ladder.template] = t("на предмете: T{tier}").format(tier=ladder.mods.index(mod) + 1)
        return marks

    def _scroll_area(self, parent, remember_width: bool = True) -> tk.Frame:
        color = parent["bg"]
        holder = tk.Frame(parent, bg=color)
        holder.pack(fill="both", expand=True, pady=(8, 0))
        holder.columnconfigure(0, weight=1)
        holder.columnconfigure(1, minsize=11)  # keeps the width stable when the scrollbar hides
        holder.rowconfigure(0, weight=1)
        canvas = tk.Canvas(holder, bg=color, highlightthickness=0, bd=0, height=1)  # asks for no height of its own: a list takes what is left, and scrolls
        inner = tk.Frame(canvas, bg=color)
        window = canvas.create_window((0, 0), window=inner, anchor="nw", **({"width": self.list_width} if remember_width and self.list_width else {}))  # the width from last time, as the window never changes size, spares laying the list out several times over
        inner.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))

        def on_resize(event):
            if remember_width:
                self.list_width = event.width
            canvas.itemconfigure(window, width=event.width)

        canvas.bind("<Configure>", on_resize)
        canvas.grid(row=0, column=0, sticky="nsew")
        self._enable_scrolling(holder, canvas)
        inner.canvas = canvas
        return inner

    def _enable_scrolling(self, holder, canvas: tk.Canvas) -> None:
        """A thin scrollbar that appears on overflow, and a wheel that glides instead of jumping."""
        scrollbar = SlimScrollbar(holder, canvas.yview, BG, ACCENT)
        canvas.bind("<Button-1>", lambda _: canvas.focus_set(), add="+")  # leaves a text field, so the arrow keys scroll
        glide = {"target": 0.0, "job": None}

        def on_view_change(first, last):
            scrollbar.set(first, last)
            if float(first) <= 0 and float(last) >= 1:
                scrollbar.grid_remove()
            else:
                scrollbar.grid(row=0, column=1, sticky="nse")

        def step():
            if not canvas.winfo_exists():
                return
            first = canvas.yview()[0]
            gap = glide["target"] - first
            total = float(str(canvas.cget("scrollregion") or "0 0 0 1").split()[3]) or 1
            if abs(gap) * total < 1:
                canvas.yview_moveto(glide["target"])
                glide["job"] = None
                return
            canvas.yview_moveto(first + gap * 0.3)
            glide["job"] = self.root.after(12, step)

        def on_wheel(event):
            if not canvas.winfo_exists():
                return
            first, last = canvas.yview()
            if first <= 0 and last >= 1:
                return
            total = float(str(canvas.cget("scrollregion") or "0 0 0 1").split()[3]) or 1
            start = glide["target"] if glide["job"] else first
            glide["target"] = min(max(start - event.delta / 120 * SCROLL_PIXELS / total, 0.0), 1.0 - (last - first))
            if not glide["job"]:
                step()

        canvas.configure(yscrollcommand=on_view_change)
        def on_enter(_):
            self.wheel_handler = on_wheel  # only noted: binding anew on every entry would leave a command behind each time
            self.scroll_target = canvas

        holder.bind("<Enter>", on_enter)

    def _mod_list(self, parent, side: str) -> tk.Canvas:
        """One list of mods. The rows are drawn on a single canvas: on Windows every widget is a window of its own, and hundreds of them took seconds to appear."""
        holder = tk.Frame(parent, bg=parent["bg"])
        holder.pack(fill="both", expand=True, pady=(8, 0))
        holder.columnconfigure(0, weight=1)
        holder.columnconfigure(1, minsize=11)  # keeps the width stable when the scrollbar hides
        holder.rowconfigure(0, weight=1)
        canvas = tk.Canvas(holder, bg=parent["bg"], highlightthickness=0, bd=0, height=1)  # asks for no height of its own: a list takes what is left, and scrolls
        canvas.grid(row=0, column=0, sticky="nsew")
        canvas.drawn_width = 0
        canvas.bind("<Configure>", lambda event: self._mod_list_resized(side, event.width))
        self._enable_scrolling(holder, canvas)
        self.lists[side] = canvas
        return canvas

    def _mod_list_resized(self, side: str, width: int) -> None:
        canvas = self.lists.get(side)
        if canvas and canvas.winfo_exists() and width != canvas.drawn_width:
            self.list_width = width
            self._draw_mod_list(side)

    def _add_row(self, canvas: tk.Canvas, ladder: Ladder, mark: str | None, note: str | None = None) -> None:
        best = ladder.available(self.ilvl)[0]
        known = f"  •  {note}" if note else "" if best.weight_known else "  •  " + t("вес неизвестен")
        tiers = [n for n, mod in enumerate(ladder.mods, 1) if mod.level <= self.ilvl]
        position = len(self.rows)

        def toggle(_=None):
            checked.set(not checked.get())
            self._paint_row(self.rows[position])
            self._update_headers()

        checked = tk.BooleanVar()
        self.rows.append({"ladder": ladder, "checked": checked, "tier": TierChoice([t("любой тир")] + [t("T{tier} и лучше").format(tier=n) for n in tiers]), "frame": canvas, "title": ladder.title, "detail": f"{best.shown_text}{known}", "mark": mark,
                          "text": f"{ladder.title} {ladder.template} {best.shown_text}", "toggle": toggle, "position": position, "shown": True, "drawn": False, "pool": False})

    def _draw_mod_list(self, side: str) -> None:
        """Lays out one column. Called when its width or the rows on show have changed, not for a click."""
        canvas = self.lists[side]
        width = canvas.winfo_width() if canvas.winfo_width() > 50 else self.list_width
        if width <= 50:
            return  # its first <Configure> brings the width
        canvas.drawn_width = width
        canvas.delete("all")
        rows = [row for row in self.rows if row["ladder"].side == side]
        for row in rows:
            row["drawn"] = False
            row["tier"].forget()
        wrap = max(width - 175, 120)
        top = 0
        for row in rows:
            if not row["shown"]:
                continue
            tag = f"row{row['position']}"
            background = canvas.create_rectangle(0, top, width - 1, top + 50, tags=(tag, f"{tag}back"))
            title = canvas.create_text(48, top + 7, text=row["title"], fill=TEXT, font=(FONT, 10, "bold"), anchor="nw", width=wrap, tags=(tag, f"{tag}words"))
            bottom = canvas.bbox(title)[3]
            detail = canvas.create_text(48, bottom, text=row["detail"], fill=MUTED, font=(FONT, 8), anchor="nw", width=wrap, tags=(tag, f"{tag}words"))
            bottom = canvas.bbox(detail)[3]
            if row["mark"]:
                mark = canvas.create_text(48, bottom + 1, text=row["mark"], fill=SOFT, font=(FONT, 8, "bold"), anchor="nw", width=wrap, tags=(tag, f"{tag}words"))
                bottom = canvas.bbox(mark)[3]
            bottom = max(bottom + 7, top + 48)
            canvas.coords(background, 0, top, width - 1, bottom)
            middle = (top + bottom) // 2
            canvas.create_rectangle(6, middle - 19, 44, middle + 19, tags=(tag, f"{tag}box"))
            canvas.create_text(25, middle, text="", fill=INK, font=(FONT, 13, "bold"), tags=(tag, f"{tag}check"))
            canvas.tag_bind(tag, "<Button-1>", row["toggle"])
            row["drawn"], row["middle"], row["width"] = True, middle, width
            self._paint_row(row)
            top = bottom + 5
        if not any(row["shown"] for row in rows):
            canvas.create_text(4, 14, text=t("Ничего не найдено"), fill=MUTED, font=(FONT, 9), anchor="w")
        canvas.configure(scrollregion=(0, 0, width, max(top, 1)), cursor="hand2")

    def _paint_row(self, record: dict) -> None:
        if not record["drawn"]:
            return
        selected = record["checked"].get()
        canvas, tag = record["frame"], f"row{record['position']}"
        canvas.itemconfigure(f"{tag}back", fill=RAISED if selected else PANEL, outline=ACCENT if selected else BORDER)
        canvas.itemconfigure(f"{tag}box", fill=ACCENT if selected else TILE, outline=BORDER)
        canvas.itemconfigure(f"{tag}check", text="✓" if selected else "")
        canvas.delete(f"{tag}pool")
        if selected:
            record["tier"].show(canvas, record["width"] - 8, record["middle"], self)
            # The mark has a tag of its own, not the row's: a click on it must not unselect the row.
            mark = canvas.create_text(record["width"] - 10, record["middle"] + 19, text=("◆ " if record["pool"] else "◇ ") + t("любой из группы"), anchor="e",
                                      fill=ACCENT if record["pool"] else MUTED, font=(FONT, 8, "bold" if record["pool"] else "normal"), tags=(f"{tag}pool",))
            canvas.tag_bind(mark, "<Button-1>", lambda _: self._toggle_pool(record))
        else:
            record["tier"].forget(canvas)

    def _toggle_pool(self, record: dict) -> None:
        record["pool"] = not record["pool"]
        self._paint_row(record)
        self._update_headers()

    def _update_pool_bar(self) -> None:
        """The count of the group "any N" shows once two chosen mods are in it; N stays as the player set it while it still fits."""
        bar = getattr(self, "pool_bar", None)
        if not bar or not bar.winfo_exists():
            return
        size = sum(1 for row in self.rows if row["checked"].get() and row["pool"])
        if size < 2:
            return bar.pack_forget() if bar.winfo_manager() else None
        values = [str(count) for count in range(1, size)]
        was = self.pool_need_box.get()
        default_was = str(getattr(self, "pool_size_was", 0) - 1)  # left as it came, the count grows with the group: "any 2 of 3", then "any 3 of 4"
        self.pool_size_was = size
        self.pool_need_box["values"] = values
        self.pool_need_box.set(was if was in values and was != default_was else values[-1])
        self.pool_size.config(text=t("из {count}").format(count=size))
        if not bar.winfo_manager():
            bar.pack(side="left", padx=(8, 0))

    def _redraw_open_switches(self) -> None:
        """A switch draws itself only when clicked; a goal opened sets it from outside."""
        for side, holder in getattr(self, "open_switches", {}).items():
            if holder.winfo_exists():
                holder.winfo_children()[0].config(image=self.switches[self.open_vars[side].get()])
        self._update_headers()

    def pool_need(self) -> int:
        size = sum(1 for row in self.rows if row["checked"].get() and row["pool"])
        try:
            return min(int(self.pool_need_box.get()), size - 1) if size >= 2 else 0
        except (ValueError, AttributeError, tk.TclError):
            return 0

    def open_slots(self) -> dict:
        return {side: 1 for side, chosen in getattr(self, "open_vars", {}).items() if chosen.get()}

    def update_counters(self) -> None:
        for side in self.lists:
            self._draw_mod_list(side)
        self._update_headers()

    def _update_headers(self) -> None:
        for side, (header, title) in self.counters.items():
            rows = [r for r in self.rows if r["ladder"].side == side]
            chosen = sum(r["checked"].get() for r in rows)
            shown = sum(r["shown"] for r in rows)
            found = "  •  " + t("найдено {count}").format(count=shown) if shown < len(rows) else ""
            limit = affix_limits(self.base or "")[side]
            if side in getattr(self, "open_vars", {}) and self.open_vars[side].get():
                header.config(text=t("{title}  {chosen} из {limit}, свободно {free}{found}").format(title=title, chosen=chosen, limit=limit, free=1, found=found))
            else:
                header.config(text=t("{title}  {chosen} из {limit}{found}").format(title=title, chosen=chosen, limit=limit, found=found))
        self._update_pool_bar()

    def apply_search(self) -> None:
        """Hides mods that do not match. Selected mods stay visible so a choice never disappears."""
        query = self.search.get()
        for row in self.rows:
            row["shown"] = row["checked"].get() or matches_search(query, row["text"])
        for side, canvas in self.lists.items():
            self._draw_mod_list(side)
            canvas.yview_moveto(0)
        self._update_headers()

    # ---- planning
    def selected_wants(self) -> list[Want]:
        wants = []
        need = self.pool_need()
        for row in self.rows:
            if row["checked"].get():
                choice = re.match(r"T(\d+)", row["tier"].get())
                min_tier = int(choice.group(1)) if choice else None
                want = make_want(row["ladder"], min_tier, self.ilvl)
                wants.append(replace(want, need=need) if need and row["pool"] else want)
        return wants

    def item_state(self, wants: list[Want], page: Page) -> State:
        return self._state_of(self.item, wants, page)

    @staticmethod
    def _state_of(item, wants: list[Want], page: Page) -> State:
        if not item:
            return State("normal", (NONE,) * len(wants), 0, 0)
        desecrated = None
        if item.desecrated:
            side, name, line = item.desecrated
            desecrated = (side, page.find_desecrated(side, line) or page.find_mod(side, name))
        mods = [desecrated if desecrated and side == desecrated[0] and item.desecrated[1] == name else (side, page.find_mod(side, name)) for side, name in item.mods]
        fractured = item.fractured and (item.fractured[0], page.find_mod(*item.fractured))
        return state_of_mods(item.rarity, mods, wants, fractured, desecrated)

    def start_solve(self) -> None:
        if self.solves_running:
            return self.set_status(t("Уже считаю план, дождитесь результата"))
        try:
            wants = self.selected_wants()
            validate_wants(wants, self.base or "", self.open_slots())
            self.last_goal = self._current_goal()
            if not self.prices:
                raise ValueError(t("Цены ещё загружаются"))
            prices = {name: value for name, value in prices_in_exalted(self.prices).items() if name not in self.banned}  # an orb without a price is one the planner never uses
            base_price = float(self.base_price.get().replace(",", ".")) * self.prices["exalted_per_divine"]
            if base_price <= 0:
                raise ValueError(t("Цена базы должна быть положительной"))
        except ValueError as error:
            return self.set_status(str(error))
        self.solve_prices = {mode: {**prices, NEW_BASE: base_price} if self.base_allowed[mode] else prices for mode in CRAFT_MODES}
        page = self.db.pages[self.db.bases[self.base]["page"]]
        self.solve_button.config(state="disabled", text=t("Считаю..."))
        self.set_status(t("Считаю лучший путь, для 6 модов это занимает до двух минут"))
        self.spent = 0.0
        self._solve_async(page, wants, self.item_state(wants, page))

    def _solve_async(self, page: Page, wants: list[Want], start: State) -> None:
        """Both ways to craft are solved, so they can be compared side by side."""
        prices, ilvl, base, open_slots = self.solve_prices, self.ilvl, self.base or "", self.open_slots()
        self.solve_token += 1
        token = self.solve_token
        stale = lambda: token != self.solve_token  # another base or league since: the plan stops where it is
        self.solves_running += 1
        self._paint_presets()

        def work():
            set_process_priority(BELOW_NORMAL_PRIORITY)
            try:
                self.events.put(("plan", (token, solve_modes({mode: Planner(page, ilvl, wants, prices[mode], mode, base, open_slots, stale) for mode in CRAFT_MODES}, start))))
            except PlanCancelled:
                pass
            except (ValueError, np.linalg.LinAlgError) as error:
                self.events.put(("error", str(error)))
            except Exception:  # the button must not stay on «calculating» for good
                log_error("solving a plan")
                self.events.put(("error", t("Не удалось рассчитать план, подробности в errors.log")))
            finally:
                set_process_priority(NORMAL_PRIORITY)
                self.events.put(("solve_done", None))
        threading.Thread(target=work, daemon=True).start()

    def on_solve_done(self) -> None:
        self.solves_running = max(self.solves_running - 1, 0)
        self._paint_presets()
        if not self.solves_running and self.plan is None and self.solve_button and self.solve_button.winfo_exists():
            self.solve_button.config(state="normal", text=t("Рассчитать"))

    def _paint_presets(self) -> None:
        """The presets look asleep while a plan is being worked out, so a click that would wait is not expected to do anything."""
        panel = self.preset_panel
        if not panel or not panel.winfo_exists() or not panel.winfo_children():
            return
        busy = bool(self.solves_running)
        for card in panel.winfo_children()[0].winfo_children():
            if isinstance(card, tk.Frame):
                card.config(cursor="watch" if busy else "hand2")
                for words in card.winfo_children():
                    words.config(fg=MUTED if busy else TEXT, cursor="watch" if busy else "hand2")

    def on_plan(self, answer: tuple[int, dict[str, Plan]]) -> None:
        token, plans = answer
        if token != self.solve_token:  # worked out in the prices of the league the player has left
            return
        self.plans = plans
        self.plan = plans[self.craft_mode]
        self.state = self.plan.start
        self.alternatives = None
        self.show_guide()
        for plan in plans.values():
            self._simulate(plan)
        self._find_alternatives(self.plan)

    def _find_alternatives(self, plan: Plan) -> None:
        planner = plan.planner
        if not plan.usage or len(planner.wants) > ALTERNATIVES_MAX_WANTS or len(plan.policy) > ALTERNATIVES_STATE_LIMIT:
            self.alternatives = []
            return self._render_alternatives()
        page = self.db.pages[self.db.bases[self.base]["page"]]
        ilvl, cost = self.ilvl, plan.values.get(plan.start, 0.0)

        def work():
            set_process_priority(BELOW_NORMAL_PRIORITY)
            try:
                self.events.put(("alternatives", (plan, cheaper_goals(page, ilvl, planner.wants, planner.plain_prices, lambda wants: self.item_state(wants, page), cost, planner.mode, planner.base,
                                                                      planner.open_slots, lambda: plan is not self.plan))))
            except PlanCancelled:
                pass  # the player has moved on from this plan
            except (ValueError, np.linalg.LinAlgError):
                self.events.put(("alternatives", (plan, [])))
            except Exception:
                log_error("cheaper goals")
                self.events.put(("alternatives", (plan, [])))
            finally:
                set_process_priority(NORMAL_PRIORITY)
        threading.Thread(target=work, daemon=True).start()

    def on_alternatives(self, plan: Plan, options: list[dict]) -> None:
        if plan is self.plan:
            self.alternatives = options
            self._render_alternatives()

    def _render_alternatives(self) -> None:
        box = self.alternatives_box
        if not box or not box.winfo_exists():
            return
        for child in box.winfo_children():
            child.destroy()
        rate = self.prices["exalted_per_divine"]
        self._render_budget_result()
        if self.alternatives is None:
            return self._label(box, t("Ищу варианты дешевле..."), MUTED, 9).pack(anchor="w")
        if not self.alternatives:
            return self._label(box, t("Заметно дешевле варианта нет"), MUTED, 9).pack(anchor="w")
        for option in self.alternatives:
            row = tk.Frame(box, bg=BG, highlightthickness=1, highlightbackground=BORDER, padx=10, pady=7)
            row.pack(fill="x", pady=(0, 4), padx=(0, 10))
            row.columnconfigure(0, weight=1)
            self._label(row, option["label"], TEXT, 9, wrap=210).grid(row=0, column=0, sticky="w")
            self._label(row, format_cost(option["cost"], rate, self.prices.get("chaos_per_divine")), SOFT, 9, True).grid(row=1, column=0, sticky="w")
            button = self._button(row, t("Взять"), lambda wants=option["wants"]: self.use_alternative(wants))
            button.config(font=(FONT, 9), padx=10, pady=3)
            button.grid(row=0, column=1, rowspan=2, padx=(8, 0))

    def use_alternative(self, wants: list[Want]) -> None:
        page = self.db.pages[self.db.bases[self.base]["page"]]
        self.set_status(t("Считаю лучший путь, для 6 модов это занимает до двух минут"))
        self.spent = 0.0
        self._solve_async(page, wants, self.item_state(wants, page))

    def on_error(self, text: str) -> None:
        self.set_status(text)
        if self.plan is None and self.solve_button.winfo_exists():
            self.solve_button.config(state="normal", text=t("Рассчитать"))

    def follow_item(self, item: ParsedItem) -> None:
        planner = self.plan.planner
        page = self.db.pages[self.db.bases[self.base]["page"]]
        state = self.item_state(planner.wants, page)
        self.state = state
        if state in self.plan.policy or planner.is_goal(state):
            return self.show_guide()
        self.set_status(t("Такого состояния не было в плане, пересчитываю..."))
        self._solve_async(page, planner.wants, state)

    # ---- guide
    def show_guide(self) -> None:
        self.clear_body()
        rate = self.prices["exalted_per_divine"]
        self._craft_header(f"{self.db.show_base(self.base)}  •  ilvl {self.ilvl}", self.plans, back=True)
        columns = tk.Frame(self.body, bg=BG)
        columns.pack(fill="both", expand=True)
        columns.columnconfigure(0, weight=3, uniform="guide")
        columns.columnconfigure(1, weight=2, uniform="guide")
        columns.rowconfigure(0, weight=1)
        action_panel = self._panel(columns)
        action_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        info_panel = self._panel(columns)
        info_panel.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self._render_action(action_panel, rate)
        self._render_info(self._scroll_area(info_panel), rate)
        self.set_status(t("Цены от {time}").format(time=self.prices["fetched_at"].replace("T", " ")))

    def _render_info(self, info, rate: float) -> None:
        plan, planner = self.plan, self.plan.planner
        wrap = 300

        def heading(text):
            self._label(info, text, MUTED, 9).pack(anchor="w", pady=(16, 6))

        self._label(info, t("Цель"), MUTED, 9).pack(anchor="w", pady=(0, 6))
        for want, status in zip(planner.wants, self.state.status):
            mark, color = {HIT: ("✓", TEXT), WRONG_TIER: ("~", SOFT)}.get(status, ("○", SOFT))
            card = tk.Frame(info, bg=BG, highlightthickness=1, highlightbackground=ACCENT if status == HIT else BORDER, padx=10, pady=7)
            card.pack(fill="x", pady=(0, 4), padx=(0, 10))
            self._label(card, f"{mark}   {want.label}{'  ◇' if want.need else ''}", color, 9, status == HIT, wrap).pack(anchor="w")
        for line in goal_notes(planner):
            self._label(info, line, SOFT, 9, wrap=wrap).pack(anchor="w", pady=(2, 0))
        if not plan.usage:
            return
        heading(t("В среднем с начала"))
        self._label(info, format_cost(plan.values.get(plan.start, 0), rate, self.prices.get("chaos_per_divine")), TEXT, 18, True).pack(anchor="w")
        self.simulation_box = tk.Frame(info, bg=PANEL)
        self.simulation_box.pack(fill="x", pady=(4, 0))
        self._simulate(plan)
        self._render_simulation()
        if plan.uses_desecration:
            self._label(info, t("План использует кость Бездны, поэтому шансы здесь грубые: вес очернённых модов взят из замера POE2_HTC по 40 костям, а 3 варианта при раскрытии не подтверждены poe2db."), DOWN_COLOR, 8, wrap=wrap).pack(anchor="w", pady=(4, 0))
        if plan.uses_catalysts:
            self._label(info, t("План использует катализаторы со знамением, поэтому шансы оценочные: насколько качество повышает шанс, известно лишь по двум числам с вики PoE2."), DOWN_COLOR, 8, wrap=wrap).pack(anchor="w", pady=(4, 0))
        if planner.setup:
            self._label(info, t("Сначала в гнездо: {items}. Это уже в цене. Руну нельзя вынуть.").format(items=" + ".join(show_currency(item) for item in planner.setup)), TEXT, 9, True, wrap=wrap).pack(anchor="w", pady=(6, 0))
            self._label(info, t("Шансы модов руны оценочные: настоящего веса нет на poe2db."), DOWN_COLOR, 8, wrap=wrap).pack(anchor="w", pady=(2, 0))
        self._build_budget_box(info)
        self.market_box = tk.Frame(info, bg=PANEL)
        self.market_box.pack(fill="x", pady=(8, 0))
        self._render_market()
        hints = finishing_hints(self.db.bases[self.base]["page"], planner.wants, planner.prices, self.base)
        cap = QUALITY_CAP_BY_BASE.get(self.base, QUALITY_CAP) + ESSENCE_QUALITY_CAP
        if hints:
            heading(t("После крафта"))
        for name, kind in hints:
            words = {"flux": t("если выпало другое сопротивление, превратит все такие моды в нужное"), "catalyst": t("качеством усилит подходящие моды"), "quality": t("поднимет качество предмета"),
                     "quality_cap": t("поднимет потолок качества до {cap}%. Это делается посреди крафта, пока на предмете есть лишний мод: со знамением кристаллизации сущность снимет его. Потом около {count} катализаторов, и знамение оттачивания со сферой хаоса снимет мод сущности, а качество останется").format(cap=cap, count=catalysts_needed(cap))}[kind]
            self._label(info, f"{show_currency(name)}, {format_cost(planner.prices[name], rate, self.prices.get('chaos_per_divine'))}: {words}", SOFT, 9, wrap=wrap).pack(anchor="w", pady=1)
        heading(t("Как выйдет дешевле"))
        self.alternatives_box = tk.Frame(info, bg=PANEL)
        self.alternatives_box.pack(fill="x")
        self._render_alternatives()
        steps = merge_route(plan.route(self.state))[:ROUTE_STEPS_SHOWN]
        if steps:
            heading(t("Дальше примерно так"))
            self._render_route(info, steps)
            self._label(info, t("Процент: шанс, что шаг даст нужный мод"), MUTED, 8, wrap=wrap).pack(anchor="w")
        toggle = t("Скрыть подробности") if self.show_details else t("Подробнее о расходе")
        buttons = tk.Frame(info, bg=PANEL)
        buttons.pack(anchor="w", pady=(10, 0))
        for text, command in ((toggle, self.toggle_details), (t("Скопировать рецепт"), self.copy_recipe)):
            button = self._button(buttons, text, command)
            button.config(font=(FONT, 9), padx=10, pady=4)
            button.pack(side="left", padx=(0, 6))
        if self.show_details:
            self._render_details(info, wrap)

    def _simulate(self, plan: Plan) -> None:
        if plan.simulation is not None:
            return
        plan.simulation = SIMULATING

        def work():
            try:
                self.events.put(("simulation", (plan, simulate_plan(plan) or False)))
            except Exception:
                log_error("testing a plan")
                self.events.put(("simulation", (plan, False)))
        threading.Thread(target=work, daemon=True).start()

    def on_simulation(self, plan: Plan, result) -> None:
        plan.simulation = result
        if plan is self.plan:
            self._render_simulation()
        self._render_mode_risk()
        self._render_budget_result()

    def _build_budget_box(self, parent) -> None:
        self.budget_box = tk.Frame(parent, bg=PANEL)
        self.budget_box.pack(fill="x", pady=(8, 0))
        row = tk.Frame(self.budget_box, bg=PANEL)
        row.pack(anchor="w")
        self._label(row, t("Мой бюджет, Divine"), SOFT, 9).pack(side="left", padx=(0, 6))
        self._entry(row, self.budget_var, 7).pack(side="left", ipady=3)
        self.budget_result = self._label(self.budget_box, "", SOFT, 9, wrap=300)
        self.budget_result.pack(anchor="w", pady=(4, 0))
        self._render_budget_result()

    def _on_budget_typed(self) -> None:
        self.save_settings(craft_budget=self.budget_var.get().strip())
        self._render_budget_result()

    def _render_budget_result(self) -> None:
        box = self.budget_box
        if not box or not box.winfo_exists() or not self.plans:
            return
        try:
            budget = float(self.budget_var.get().strip().replace(",", ".")) * self.prices["exalted_per_divine"]
        except ValueError:
            return self.budget_result.config(text="")
        chance, better, goal = budget_advice(self.plans, self.craft_mode, budget, self.alternatives)
        if chance is None:
            return self.budget_result.config(text=t("Проверяю план прогонами..."))
        words = [t("Шанс уложиться с начала крафта: {chance}.").format(chance=f"{chance:.0%}")]
        if better:
            words.append(t("Режим «{mode}» уложится чаще: {chance}.").format(mode=t(MODE_TITLES[better]), chance=f"{self.plans[better].simulation.chance_within(budget):.0%}"))
        if goal:
            words.append(t("В среднем на эти деньги выйдет: {goal}.").format(goal=goal))
        self.budget_result.config(text=" ".join(words))

    def _render_simulation(self) -> None:
        box = self.simulation_box
        if not box or not box.winfo_exists():
            return
        for child in box.winfo_children():
            child.destroy()
        result = self.plan.simulation
        if result == SIMULATING:
            self._label(box, t("Проверяю план прогонами..."), MUTED, 9, wrap=300).pack(anchor="w")
        elif result:
            rate, chaos = self.prices["exalted_per_divine"], self.prices.get("chaos_per_divine")
            words = t("Проверка, {runs} прогонов: половина дешевле {median}, 9 из 10 не дороже {unlucky}, 1 из 100 дороже {worst}").format(
                runs=result.runs, median=format_cost(result.median, rate, chaos), unlucky=format_cost(result.unlucky, rate, chaos), worst=format_cost(result.worst, rate, chaos))
            self._label(box, words, SOFT, 9, wrap=300).pack(anchor="w")

    def copy_recipe(self) -> None:
        rate, chaos = self.prices["exalted_per_divine"], self.prices.get("chaos_per_divine")
        title = f"{self.db.show_base(self.base)}, ilvl {self.ilvl}"
        first = t("Сначала в гнездо: {items}. Это уже в цене. Руну нельзя вынуть.").format(items=" + ".join(show_currency(item) for item in self.plan.planner.setup)) + "\n" if self.plan.planner.setup else ""
        self._copy_text(first + recipe_text(self.plan, title, format_cost(self.plan.values.get(self.plan.start, 0), rate, chaos)))
        self.set_status(t("Рецепт скопирован"))

    def _render_market(self) -> None:
        box = self.market_box
        if not box or not box.winfo_exists():
            return
        for child in box.winfo_children():
            child.destroy()
        button = self._button(box, t("Посмотреть цену на сайте"), self.compare_with_market)
        button.config(font=(FONT, 9), padx=10, pady=4)
        button.pack(anchor="w")

    def compare_with_market(self) -> None:
        """The same goal on the trade site, in the player's browser, to set against the cost of the plan."""
        index = self._saved_trade_stats(language) or {}
        goals = [(want.label, min(want.qualifying, key=lambda mod: mod.level).shown_text.split(" / ")) for want in self.plan.planner.wants]
        mods = [wanted_mod(lines, index) for _, lines in goals]
        query = build_query(None, self.db.show_base(self.base), False, [mod for mod in mods if mod.stats], 1.0)
        missing = [label for (label, _), mod in zip(goals, mods) if not mod.stats]
        if missing:
            self.set_status(t("Без учёта: {mods}").format(mods=", ".join(missing)))
        self._open_on_site(trade_site_url(language, (self.prices or {}).get("league", "Standard"), query))

    def _render_route(self, parent, steps: list[tuple[Action, int, float]]) -> None:
        for number, (action, count, chance) in enumerate(steps, 1):
            row = tk.Frame(parent, bg=BG, highlightthickness=1, highlightbackground=BORDER)
            row.pack(fill="x", pady=(0, 4), padx=(0, 10))
            row.columnconfigure(2, weight=1)
            self._label(row, str(number), MUTED, 9).grid(row=0, column=0, padx=(10, 8))
            self._icon_tile(row, self.currency_icon(action.items[0], 24), 32).grid(row=0, column=1, padx=(0, 10), pady=6)
            words = tk.Frame(row, bg=BG)
            words.grid(row=0, column=2, sticky="w")
            times = f"  × {count}" if count > 1 else ""
            self._label(words, action.main_name + times, TEXT, 9, True, 200).pack(anchor="w")
            for omen in action.omen_names:
                self._label(words, f"+ {omen}", MUTED, 8, wrap=200).pack(anchor="w")
            if chance:
                self._label(row, f"{chance:.0%}", SOFT, 9).grid(row=0, column=3, padx=10)

    def _render_details(self, parent, wrap: int) -> None:
        plan, planner = self.plan, self.plan.planner
        attempts = plan.attempts
        reason = (t("Это сумма за все неудачи, а не за один заход: около {attempts} попыток с новой базой.").format(attempts=f"{attempts:.0f}") if attempts >= 2 else
                  t("Это среднее с учётом неудачных бросков на этом предмете: повезти может раньше или позже."))
        self._label(parent, reason, SOFT, 9, wrap=wrap).pack(anchor="w", pady=(12, 8))
        for name, count in sorted(plan.usage.items(), key=lambda e: -e[1] * planner.prices[e[0]])[:8]:
            per_attempt = t("   ({count} на попытку)").format(count=f"{count / attempts:.2f}") if attempts >= 2 else ""
            self._label(parent, f"{count:.0f}  ×  {show_currency(name)}{per_attempt}", SOFT, 9, wrap=wrap).pack(anchor="w", pady=1)
        if planner.fracture and not plan.fracture_counted:
            self._label(parent, t("Раскалывающая сфера не учтена: цель слишком большая для быстрого расчёта."), MUTED, 9, wrap=wrap).pack(anchor="w", pady=(8, 0))

    def toggle_details(self) -> None:
        self.show_details = not self.show_details
        self.show_guide()

    def _render_action(self, parent, rate: float) -> None:
        planner, state = self.plan.planner, self.state
        if planner.is_goal(state):
            self._label(parent, t("Готово! Все нужные моды на предмете."), TEXT, 17, True, wrap=520).pack(anchor="w", pady=(8, 0))
            self._label(parent, t("Потрачено по подсказкам: {cost}").format(cost=format_cost(self.spent, rate, self.prices.get("chaos_per_divine"))), SOFT, 11).pack(anchor="w", pady=8)
            return
        action = self.plan.policy[state]
        self._label(parent, t("Что сделать сейчас"), MUTED, 10).pack(anchor="w", pady=(2, 8))
        hero = tk.Frame(parent, bg=PANEL)
        hero.pack(anchor="w")
        self._icon_tile(hero, self.currency_icon(action.items[0], ICON_SIZE), 64).pack(side="left", padx=(0, 14))
        words = tk.Frame(hero, bg=PANEL)
        words.pack(side="left")
        self._label(words, action.main_name, TEXT, 19, True, 420).pack(anchor="w")
        self._label(words, explain_action(action, state), SOFT, 10, wrap=420).pack(anchor="w", pady=(2, 0))
        self._render_instructions(parent, action)
        self._label(parent, t("Осталось примерно {left}  •  потрачено {spent}").format(left=format_cost(self.plan.values[state], rate, self.prices.get("chaos_per_divine")), spent=format_cost(self.spent, rate, self.prices.get("chaos_per_divine"))), MUTED, 9).pack(anchor="w", pady=(10, 2))
        self._label(parent, t("На предмете: {rarity}, {state}").format(rarity=t(RARITY_NAMES[state.rarity]), state=describe_state(state, planner.wants)), MUTED, 9, wrap=520).pack(anchor="w", pady=(0, 10))
        outcomes = self.plan.outcomes(state)
        if len(outcomes) == 1:
            self._button(parent, t("Сделано, дальше"), lambda: self.choose_outcome(outcomes[0][0], action), primary=True).pack(anchor="w")
            return
        self._label(parent, t("Или выберите, что выпало:"), MUTED, 9).pack(anchor="w")
        inner = self._scroll_area(parent)
        hits = state.status.count(HIT)
        for new, chance in outcomes:
            good = new.status.count(HIT) > hits
            button = tk.Button(inner, text=f"{chance:>4.0%}    {describe_change(state, new, planner.wants)}", command=lambda s=new: self.choose_outcome(s, action), relief="flat", bd=0,
                               cursor="hand2", anchor="w", justify="left", wraplength=470, bg=RAISED if good else BG, fg=TEXT if good else SOFT,
                               activebackground=BORDER, activeforeground=TEXT, font=(FONT, 9, "bold" if good else "normal"), padx=12, pady=7)
            button.pack(fill="x", pady=(0, 4), padx=(0, 10))

    def _render_instructions(self, parent, action: Action) -> None:
        """Numbered steps: what to press in the game, in this order."""
        lines = [t("Включите знамение: правый клик по «{name}» в инвентаре").format(name=omen) for omen in action.omen_names]
        if action.catalyst:
            lines[:0] = [t("Заточите предмет: «{name}» до предела качества, это около {count} шт.").format(name=show_currency(action.catalyst), count=action.catalysts),
                         t("Включите знамение: правый клик по «{name}» в инвентаре").format(name=show_currency(CATALYSING_OMEN))]
        lines.append(t("Возьмите новую базу того же типа") if action.family == "new_base" else t("Примените «{name}» на предмет").format(name=action.main_name))
        if action.family == "desecrate":
            lines.append(t("Раскройте мод у Колодца душ и выберите нужный из вариантов"))
        lines.append(t("Нажмите {copy} на предмете: программа сама увидит результат и скажет следующий шаг").format(copy=hotkey_label(self.hotkeys["copy"])))
        box = tk.Frame(parent, bg=BG, highlightthickness=1, highlightbackground=BORDER, padx=12, pady=8)
        box.pack(fill="x", pady=(12, 0))
        for number, line in enumerate(lines, 1):
            self._label(box, f"{number}.  {line}", TEXT, 10, wrap=520).pack(anchor="w", pady=2)

    def choose_outcome(self, state: State, action: Action) -> None:
        self.spent += self.plan.planner.cost(action)
        self.state = state
        self.item = None
        self.show_guide()

    def back_to_picker(self) -> None:
        """The mods chosen for the plan stay chosen, with the group and the free places, so a goal can be changed instead of picked again."""
        goal = self.last_goal if self.last_goal and self.last_goal.get("base") == self.base else None
        self.plan = self.plans = None
        self.show_picker()
        if goal:
            self._apply_goal(goal)
            self.set_status(t("Выберите нужные моды и нажмите «Рассчитать»"))

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    try:
        faulthandler.enable(open(APP_DIR / "crash.log", "a", encoding="utf-8"))  # a crash below Python, in Tk or Windows, would otherwise leave no trace
    except OSError:
        pass
    try:
        App(reopen=place_to_reopen(sys.argv[1:])).run()
    except Exception:
        log_error("start")
        raise
    os._exit(0)  # the window is closed and all is saved, so no thread still waiting on the network may keep the process alive
