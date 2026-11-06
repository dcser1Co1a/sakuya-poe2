"""What each saved file must look like. A file can be valid JSON and still hold nonsense after a failed disk, an old version or a hand edit,
so everything is put in shape here, once, as it is read: the rest of the program can then trust what it holds. What cannot be used is dropped, never guessed at."""
import math
from datetime import datetime


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def is_positive(value) -> bool:
    return is_number(value) and value > 0


def is_time(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def text_map(value) -> dict[str, str]:
    return {key: item for key, item in value.items() if isinstance(item, str)} if isinstance(value, dict) else {}


def time_map(value) -> dict[str, str]:
    return {key: item for key, item in value.items() if is_time(item)} if isinstance(value, dict) else {}


def number_map(value) -> dict[str, float | None]:
    return {key: item if is_number(item) else None for key, item in value.items()} if isinstance(value, dict) else {}


def numbers(value) -> list:
    return [item if is_number(item) else None for item in value] if isinstance(value, list) else []


def texts(value) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def keep_if(stored: dict, key: str, is_good) -> None:
    if key in stored and not is_good(stored[key]):
        del stored[key]


def clean_prices(stored: dict) -> dict:
    """Without a usable rate no price can be shown in any unit, so all of them are read again from the site."""
    stored = dict(stored)
    if not is_positive(stored.get("exalted_per_divine")):
        stored = {key: value for key, value in stored.items() if key in ("league", "league_checked", "skipped_leagues", "retry_after", "last_request", "leagues")}
    prices = stored.get("prices_in_divine")
    if isinstance(prices, dict):
        prices = {name: value for name, value in prices.items() if is_positive(value)}
        stored["prices_in_divine"] = prices
    else:
        stored.pop("prices_in_divine", None)
    for key in ("kinds", "icons", "etags"):
        if key in stored:
            stored[key] = text_map(stored[key])
    stored["updated"] = time_map(stored.get("updated"))
    for key in ("changes", "volumes"):
        if key in stored:
            stored[key] = number_map(stored[key])
    if "sparklines" in stored:
        stored["sparklines"] = {name: numbers(line) for name, line in stored["sparklines"].items()} if isinstance(stored["sparklines"], dict) else {}
    stored["skipped_leagues"] = texts(stored.get("skipped_leagues"))
    leagues = stored.get("leagues")
    stored["leagues"] = [league for league in leagues if isinstance(league, dict) and isinstance(league.get("name"), str) and league["name"] and isinstance(league.get("hardcore"), bool)] if isinstance(leagues, list) else []
    keep_if(stored, "league", lambda value: isinstance(value, str) and value)
    keep_if(stored, "chaos_per_divine", is_positive)
    seen = stored.get("last_seen")
    stored["last_seen"] = {name: entry for name, entry in seen.items() if isinstance(entry, dict) and is_positive(entry.get("price")) and is_time(entry.get("date"))} if isinstance(seen, dict) else {}
    for key in ("fetched_at", "league_checked", "retry_after"):
        keep_if(stored, key, is_time)
    return stored


def is_hotkey(value) -> bool:
    return isinstance(value, dict) and isinstance(value.get("mods"), int) and isinstance(value.get("vk"), int) and not isinstance(value.get("mods"), bool) and not isinstance(value.get("vk"), bool)


def clean_settings(stored: dict) -> dict:
    stored = dict(stored)
    keep_if(stored, "language", lambda value: value in ("ru", "en") if isinstance(value, str) else False)
    keep_if(stored, "craft_mode", lambda value: value in ("budget", "endgame") if isinstance(value, str) else False)
    for key in ("craft_budget", "price_window", "theme", "league_choice"):
        keep_if(stored, key, lambda value: isinstance(value, str))
    for key in ("trade_search", "trade_wait"):  # left by a version that searched the site from inside the program
        stored.pop(key, None)
    for key in ("topmost", "petals", "price_check"):
        keep_if(stored, key, lambda value: isinstance(value, bool))
    if "hotkeys" in stored:
        stored["hotkeys"] = {key: value for key, value in stored["hotkeys"].items() if is_hotkey(value)} if isinstance(stored["hotkeys"], dict) else {}
    if "craft_banned" in stored:
        stored["craft_banned"] = texts(stored["craft_banned"])
    return stored


def clean_unique_item(item) -> dict | None:
    if not isinstance(item, dict) or not isinstance(item.get("kind"), str) or not is_positive(item.get("price")):
        return None
    return {**item, "base": item["base"] if isinstance(item.get("base"), str) else "", "listings": item["listings"] if is_number(item.get("listings")) else 0, "change": item["change"] if is_number(item.get("change")) else None,
            "listings_change": item["listings_change"] if is_number(item.get("listings_change")) else None, "spark": numbers(item.get("spark")), "mods": texts(item.get("mods")), "icon": item["icon"] if isinstance(item.get("icon"), str) else ""}


def clean_demand(stored: dict) -> dict:
    stored = dict(stored)
    items = stored.get("items")
    cleaned = {name: clean_unique_item(item) for name, item in items.items()} if isinstance(items, dict) else {}
    stored["items"] = {name: item for name, item in cleaned.items() if item}
    stored["updated"] = time_map(stored.get("updated"))
    stored["etags"] = text_map(stored.get("etags"))
    keep_if(stored, "league", lambda value: isinstance(value, str))
    keep_if(stored, "source", lambda value: isinstance(value, str))
    return stored


def clean_uniques(stored: dict) -> dict:
    stored = dict(stored)
    for key in ("art", "russian", "items", "exchange", "tags"):
        if key in stored:
            stored[key] = text_map(stored[key])
    keep_if(stored, "fetched_at", is_time)
    return stored


def is_waystone_kind(kind) -> bool:
    return isinstance(kind, dict) and isinstance(kind.get("key"), str) and isinstance(kind.get("ru"), str) and isinstance(kind.get("forms"), list)


def clean_waystones(stored: dict) -> dict:
    stored = dict(stored)
    kinds = stored.get("kinds")
    stored["kinds"] = [{**kind, "forms": texts(kind["forms"])} for kind in kinds if is_waystone_kind(kind)] if isinstance(kinds, list) else []
    rewards = stored.get("rewards")
    stored["rewards"] = {code: texts(lines) for code, lines in rewards.items()} if isinstance(rewards, dict) else {}
    keep_if(stored, "fetched_at", is_time)
    return stored


def is_bookmark(mark) -> bool:
    return isinstance(mark, dict) and all(isinstance(mark.get(key), str) for key in ("name", "price", "link", "date"))


def is_deal(deal) -> bool:
    return isinstance(deal, dict) and all(isinstance(deal.get(key), str) for key in ("name", "unit", "date")) and is_number(deal.get("bought")) and all(deal.get(key) is None or is_number(deal.get(key)) for key in ("sold", "bought_exalted", "sold_exalted"))


def is_watch(watch) -> bool:
    return isinstance(watch, dict) and isinstance(watch.get("name"), str) and watch.get("direction") in ("below", "above") and is_positive(watch.get("amount")) and isinstance(watch.get("unit"), str) and isinstance(watch.get("fired"), bool)


def is_check(entry) -> bool:
    return isinstance(entry, dict) and all(isinstance(entry.get(key), str) for key in ("name", "copied", "price", "date")) and (entry.get("priced_name") is None or isinstance(entry.get("priced_name"), str)) and all(type(entry.get(key, 1)) is int and entry.get(key, 1) >= 0 for key in ("stack", "count"))


def is_goal_mod(mod) -> bool:
    return isinstance(mod, dict) and isinstance(mod.get("template"), str) and isinstance(mod.get("side"), str) and isinstance(mod.get("desecrated"), bool) and (mod.get("tier") is None or (type(mod.get("tier")) is int and mod["tier"] > 0))


def is_craft_goal(goal) -> bool:
    return isinstance(goal, dict) and isinstance(goal.get("base"), str) and type(goal.get("ilvl")) is int and isinstance(goal.get("label"), str) and isinstance(goal.get("mods"), list) and bool(goal["mods"]) and all(is_goal_mod(mod) for mod in goal["mods"])


def clean_tools(stored: dict) -> dict:
    """The player's own notes: a line that is damaged goes, the others stay."""
    stored = dict(stored)
    if "bookmarks" in stored:
        stored["bookmarks"] = [mark for mark in stored["bookmarks"] if is_bookmark(mark)] if isinstance(stored["bookmarks"], list) else []
    if "journal" in stored:
        stored["journal"] = [deal for deal in stored["journal"] if is_deal(deal)] if isinstance(stored["journal"], list) else []
    if "watches" in stored:
        stored["watches"] = [watch for watch in stored["watches"] if is_watch(watch)] if isinstance(stored["watches"], list) else []
    if "history" in stored:
        stored["history"] = [entry for entry in stored["history"] if is_check(entry)] if isinstance(stored["history"], list) else []
    if "craft_goals" in stored:
        stored["craft_goals"] = [goal for goal in stored["craft_goals"] if is_craft_goal(goal)] if isinstance(stored["craft_goals"], list) else []
    if "notes" in stored and not isinstance(stored["notes"], str):
        del stored["notes"]
    if "stash_lines" in stored:
        stored["stash_lines"] = texts(stored["stash_lines"])
    if "stash_fields" in stored:
        stored["stash_fields"] = {name: value for name, value in stored["stash_fields"].items() if isinstance(value, str)} if isinstance(stored["stash_fields"], dict) else {}
    if "waystone_danger" in stored:
        if isinstance(stored["waystone_danger"], list):
            stored["waystone_danger"] = texts(stored["waystone_danger"])
        else:
            del stored["waystone_danger"]  # None means the usual list, not an empty one
    if "search_memory" in stored:
        memory = stored["search_memory"] if isinstance(stored["search_memory"], dict) else {}
        stored["search_memory"] = {key: {"stats": [stat for stat in entry["stats"] if isinstance(stat, (str, int)) and not isinstance(stat, bool)], "strictness": entry["strictness"]}
                                   for key, entry in memory.items() if isinstance(entry, dict) and isinstance(entry.get("stats"), list) and is_number(entry.get("strictness"))}
    return stored


def clean_trade_stats(stored: dict) -> dict:
    return {language: entry for language, entry in stored.items() if isinstance(entry, dict) and is_time(entry.get("fetched_at")) and isinstance(entry.get("index"), dict)
            and all(isinstance(ids, dict) for ids in entry["index"].values())}


def clean_updates(stored: dict) -> dict:
    stored = dict(stored)
    for key in ("checked_at", "next_check"):
        keep_if(stored, key, is_time)
    keep_if(stored, "failures", lambda value: isinstance(value, int) and not isinstance(value, bool) and value >= 0)
    return stored


def clean_patch_watch(stored: dict) -> dict:
    stored = dict(stored)
    keep_if(stored, "build", lambda value: isinstance(value, int) and not isinstance(value, bool))
    keep_if(stored, "rush_since", is_time)
    keep_if(stored, "data_then", lambda value: isinstance(value, list) and len(value) == 2)
    if not stored.get("rush_since") or not stored.get("data_then"):
        stored["rush_since"] = stored["data_then"] = None
    return stored


def clean_market_sections(stored: dict) -> dict:
    stored = dict(stored)
    keep_if(stored, "checked_at", is_time)
    for key in ("reported", "sections", "section_slugs"):
        stored[key] = texts(stored.get(key))
    for key in ("unique_categories", "currency_categories"):
        lines = stored.get(key)
        stored[key] = [line for line in lines if isinstance(line, list) and len(line) == 2 and all(isinstance(part, str) for part in line)] if isinstance(lines, list) else []
    return stored
