"""The «tools» tab: bookmarks, a deal journal, exchange gaps, a mod reference, Waystone warnings and a map timer.

Only two things go online: the exchange check, on a button press, and the Waystone list, once a week.
"""
import html
import json
import bisect
import math
import re
import time
import tkinter as tk
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from tkinter import font as tkfont
from tkinter import ttk

from sakura import BODY, TITLE_FONT, trace_while

# ------------------------------------------------------------------ bookmarks and deals
BOOKMARKS_KEPT = 100
JOURNAL_UNITS = ("Exalted Orb", "Chaos Orb", "Divine Orb")
WATCHES_KEPT = 50
HISTORY_KEPT = 50
CRAFT_GOALS_KEPT = 30
STASH_LINES_KEPT = 20
STASH_CAPTION_WIDTH = 18
NOTES_LIMIT = 20000
HISTORY_COUNT_LIMIT = 999
HISTORY_TEXT_LIMIT = 6000  # the text of one item is far shorter; it is only here so that nothing odd on the clipboard fills the file


def add_bookmark(bookmarks: list[dict], name: str, price: str, link: str, date: str) -> list[dict]:
    """The newest comes first, and the same search saved twice stays one bookmark."""
    kept = [mark for mark in bookmarks if mark["link"] != link]
    return [{"name": name, "price": price, "link": link, "date": date}, *kept][:BOOKMARKS_KEPT]


def add_watch(watches: list[dict], name: str, direction: str, amount: float, unit: str) -> list[dict]:
    """The same item watched the same way has one limit: the newest."""
    kept = [watch for watch in watches if (watch["name"], watch["direction"]) != (name, direction)]
    return [{"name": name, "direction": direction, "amount": amount, "unit": unit, "fired": False}, *kept][:WATCHES_KEPT]


def watch_is_met(watch: dict, price_exalted: float, prices: dict) -> bool | None:
    """None when it cannot be told, as with a limit in a currency whose rate is not known."""
    limit = to_exalted(watch["amount"], watch["unit"], prices)
    if limit is None:
        return None
    return price_exalted <= limit if watch["direction"] == "below" else price_exalted >= limit


def watches_reached(watches: list[dict], current_divine, prices: dict) -> tuple[list[dict], list[dict]]:
    """Which watches have just been reached, and the list with their state updated. Each speaks once, and is ready again when the price has moved back."""
    reached, kept = [], []
    rate = prices.get("exalted_per_divine")
    for watch in watches:
        divine = current_divine(watch["name"])
        met = watch_is_met(watch, divine * rate, prices) if divine and rate else None
        if met is None:
            kept.append(watch)
            continue
        if met and not watch["fired"]:
            reached.append(watch)
        kept.append({**watch, "fired": met})
    return reached, kept


def add_history(history: list[dict], name: str, copied: str, price: str, priced_name: str | None, date: str, stack: int = 1) -> list[dict]:
    """The newest comes first, and checking the same item again moves it up rather than listing it twice, keeping how many of them the player said there are."""
    copied = copied[:HISTORY_TEXT_LIMIT]
    count = next((entry.get("count", 1) for entry in history if entry["copied"] == copied), 1)
    kept = [entry for entry in history if entry["copied"] != copied]
    return [{"name": name, "copied": copied, "price": price, "priced_name": priced_name, "date": date, "stack": stack, "count": count}, *kept][:HISTORY_KEPT]


def history_total(history: list[dict], current_divine) -> tuple[float, int]:
    """What the listed items are worth at today's prices, and how many of them have no price. A count of 0 leaves one out."""
    total, unpriced = 0.0, 0
    for entry in history:
        divine = current_divine(entry["priced_name"]) if entry.get("priced_name") else None
        if divine:
            total += divine * entry.get("stack", 1) * entry.get("count", 1)
        else:
            unpriced += entry.get("count", 1)
    return total, unpriced


def change_count(history: list[dict], copied: str, change: int) -> list[dict]:
    return [{**entry, "count": min(max(entry.get("count", 1) + change, 0), HISTORY_COUNT_LIMIT)} if entry["copied"] == copied else entry for entry in history]


def add_craft_goal(goals: list[dict], base: str, ilvl: int, mods: list[dict], label: str, need: int = 0, open_slots: dict | None = None) -> list[dict]:
    """The newest comes first, and the same goal saved twice stays one. A group of "any N" and places kept free are kept only when there are any."""
    goal = {"base": base, "ilvl": ilvl, "mods": mods, "label": label, **({"need": need} if need else {}), **({"open": open_slots} if open_slots else {})}
    same = lambda other: {key: value for key, value in other.items() if key != "label"} == {key: value for key, value in goal.items() if key != "label"}
    return [goal, *(other for other in goals if not same(other))][:CRAFT_GOALS_KEPT]


def stash_words(text: str) -> list[str]:
    """What the player typed, as words for the game's search. Quotes would break the line, and a bar is one more way to list them."""
    return [word for word in (part.replace('"', "").strip() for part in re.split(r"[,|]", text)) if word]


def stash_search(all_of: list[str], any_of: list[str], none_of: list[str]) -> str:
    """For the game's search box: each word in its own quotes must be there, one quoted list with bars needs any of them, and a list after ! must have none."""
    parts = [f'"{word}"' for word in all_of]
    if any_of:
        parts.append('"' + "|".join(any_of) + '"')
    if none_of:
        parts.append(exclusion_search(none_of))
    return " ".join(parts)


def add_stash_line(lines: list[str], line: str) -> list[str]:
    return [line, *(other for other in lines if other != line)][:STASH_LINES_KEPT]


def read_amount(text: str) -> float | None:
    """A price as typed: both 1,5 and 1.5 work. Empty, negative or unreadable text gives None."""
    try:
        amount = float(text.strip().replace(",", "."))
    except ValueError:
        return None
    return amount if amount >= 0 and math.isfinite(amount) else None


def to_exalted(amount: float, unit: str, prices: dict) -> float | None:
    if unit == "Exalted Orb":
        return amount
    rate = prices.get("exalted_per_divine")
    if not rate:
        return None
    if unit == "Divine Orb":
        return amount * rate
    chaos = prices.get("chaos_per_divine")
    return amount * rate / chaos if chaos else None


def make_deal(name: str, bought: float, sold: float | None, unit: str, prices: dict, date: str) -> dict:
    """Values are kept in Exalted at today's rate, so a later change of rate does not rewrite an old deal."""
    return {"name": name, "bought": bought, "sold": sold, "unit": unit, "date": date, "bought_exalted": to_exalted(bought, unit, prices), "sold_exalted": None if sold is None else to_exalted(sold, unit, prices)}


def close_deal(deal: dict, sold: float, prices: dict) -> dict:
    return {**deal, "sold": sold, "sold_exalted": to_exalted(sold, deal["unit"], prices)}


def journal_totals(deals: list[dict]) -> tuple[float, float, int]:
    """Profit from closed deals, money still in open ones, and how many deals are closed."""
    closed = [deal for deal in deals if deal.get("sold_exalted") is not None and deal.get("bought_exalted") is not None]
    still_open = [deal for deal in deals if deal.get("sold_exalted") is None and deal.get("bought_exalted") is not None]
    return sum(deal["sold_exalted"] - deal["bought_exalted"] for deal in closed), sum(deal["bought_exalted"] for deal in still_open), len(closed)


# ---------------------------------------------------------------------- the currency exchange
EXCHANGE_URL = "https://web.poecdn.com/api/currency-exchange/poe2/{hour}"  # one public file per finished hour
EXCHANGE_GOODS = tuple(f"Metadata/Items/{kind}/" for kind in ("Currency", "SoulCores", "Gem", "Gems", "MapFragments", "Pinnacle", "Expedition", "Ultimatum"))
EXCHANGE_COINS = {"Exalted Orb": "Metadata/Items/Currency/CurrencyAddModToRare", "Chaos Orb": "Metadata/Items/Currency/CurrencyRerollRare", "Divine Orb": "Metadata/Items/Currency/CurrencyModValues"}
HOUR_SECONDS = 3600
TURNOVER_ROWS_SHOWN = 100


@dataclass(frozen=True)
class ExchangeRow:
    item: str
    traded_exalted: float  # what was paid for it in one hour, in all three coins together
    main_coin: str  # the coin most of it was traded for
    main_share: float


def convert_amount(amount: float, from_divine: float, to_divine: float) -> float:
    return amount * from_divine / to_divine


def exchange_names(base_items: dict) -> dict[str, str]:
    """The exchange names its goods by game path. This list turns them into names."""
    return {path: item["name"] for path, item in base_items.items() if path.startswith(EXCHANGE_GOODS) and item.get("name")}


def fetch_exchange(now: float, user_agent: str, opener=urllib.request.urlopen) -> tuple[int, dict]:
    """The file of the last finished hour. If that one is not published yet, the hour before it."""
    hour = int(now // HOUR_SECONDS) * HOUR_SECONDS
    for back in (1, 2):
        wanted = hour - back * HOUR_SECONDS
        request = urllib.request.Request(EXCHANGE_URL.format(hour=wanted), headers={"User-Agent": user_agent})
        try:
            with opener(request, timeout=60) as reply:
                return wanted, json.loads(reply.read())
        except urllib.error.HTTPError as error:
            if error.code != 404 or back == 2:
                raise
    raise OSError("no exchange file")


def exchange_rates(markets: list[dict], league: str) -> dict[str, dict[str, tuple[float, float]]]:
    """rates[a][b] is (how many b one a cost, how many b changed hands). The average of the hour: what changed hands, divided."""
    rates: dict[str, dict[str, tuple[float, float]]] = {}
    for market in markets:
        if market.get("league") != league or len(market.get("market_pair", ())) != 2:
            continue
        first, second = market["market_pair"]
        traded = market.get("volume_traded", {})
        amount_first, amount_second = traded.get(first, 0), traded.get(second, 0)
        if amount_first > 0 and amount_second > 0:
            rates.setdefault(first, {})[second] = (amount_second / amount_first, amount_second)
            rates.setdefault(second, {})[first] = (amount_first / amount_second, amount_first)
    return rates


def exchange_turnover(markets: list[dict], league: str, names: dict[str, str]) -> list[ExchangeRow]:
    """What sold most in the last hour, measured in the coins paid for it. Busiest first.

    The file's prices are not used for anything more: on real data the hour's averages for one item differed by up to 50% between coins
    and its price ranges by far more, so looking for profitable exchanges in them would only show false chances.
    """
    rates = exchange_rates(markets, league)
    exalted = EXCHANGE_COINS["Exalted Orb"]
    coin_values = {name: 1.0 if path == exalted else rates.get(path, {}).get(exalted, (0.0, 0))[0] for name, path in EXCHANGE_COINS.items()}
    rows = []
    for path, sold_for in rates.items():
        if path in EXCHANGE_COINS.values() or path not in names:
            continue
        paid = {name: sold_for[coin][1] * coin_values[name] for name, coin in EXCHANGE_COINS.items() if coin in sold_for and coin_values[name]}
        total = sum(paid.values())
        if total > 0:
            main = max(paid, key=paid.get)
            rows.append(ExchangeRow(names[path], total, main, paid[main] / total))
    return sorted(rows, key=lambda row: -row.traded_exalted)[:TURNOVER_ROWS_SHOWN]


# ------------------------------------------------------------------------------ Waystones
WAYSTONE_ROW = re.compile(r"<tr><td>\d+</td><td>([^<]+)</td><td>(.*?)</td></tr>", re.S)
WAYSTONE_NUMBER = re.compile(r"[+-]?\d+(?:\.\d+)?(?:\([^()]*\))?|[+-]?\([^()]*\d[^()]*\)")
WAYSTONE_CLASSES = ("waystones", "путевые камни")
TAG = re.compile(r"<[^>]+>")
SHORTEST_FRAGMENT = 4  # shorter pieces also turn up in item names, which this list cannot know
SHORTEST_SPACED_FRAGMENT = 7  # a short piece across two words is little more than two common word endings
LONGEST_SEARCH = 250  # sources disagree on the game's limit: this is the most recent figure found, not an official one
SEARCH_SEPARATORS = re.compile(r"[#%()+\-—:,.'\"]")
# A first list of what hurts most builds. The player changes it on the tab.
USUAL_DANGERS = frozenset({
    "#% maximum Player Resistances",
    "Players have #% less Recovery Rate of Life and Energy Shield",
    "Players have #% less Cooldown Recovery Rate",
    "Players gain #% reduced Flask Charges",
    "Players are periodically Cursed with Enfeeble",
    "Players are periodically Cursed with Temporal Chains",
    "Players are periodically Cursed with Elemental Weakness",
})


def waystone_template(line: str) -> str:
    """One wording for every roll: '(5—9)%', '7%' and '7(5-9)%' all become '#%'."""
    return re.sub(r"\s+", " ", WAYSTONE_NUMBER.sub("#", line)).strip()


def _waystone_rows(page: str) -> list[tuple[str, list[str]]]:
    rows = []
    for side, cell in WAYSTONE_ROW.findall(page):
        lines = [html.unescape(TAG.sub("", part)).strip() for part in re.split(r"<br\s*/?>", cell)]
        rows.append((side.strip(), [waystone_template(line) for line in lines if line]))
    return rows


def read_waystone_mods(english: str, russian: str) -> dict:
    """poe2db lists each mod as its danger on the first line and its rewards after that. Both pages list the same rows in the same order."""
    rows, ru_rows = _waystone_rows(english), _waystone_rows(russian)
    if not rows or len(rows) != len(ru_rows):
        raise ValueError("the Waystone pages do not match")
    kinds: dict[str, dict] = {}
    rewards: dict[str, set[str]] = {"en": set(), "ru": set()}
    for (side, lines), (_, ru_lines) in zip(rows, ru_rows):
        if not lines or not ru_lines:
            continue
        kind = kinds.setdefault(lines[0], {"key": lines[0], "side": side.casefold(), "ru": ru_lines[0], "forms": []})
        for form in (lines[0], ru_lines[0]):
            if form not in kind["forms"]:
                kind["forms"].append(form)
        rewards["en"].update(lines[1:])
        rewards["ru"].update(ru_lines[1:])
    if not kinds:
        raise ValueError("no Waystone mods on the page")
    return {"kinds": list(kinds.values()), "rewards": {code: sorted(lines) for code, lines in rewards.items()}}


def is_waystone(copied: str) -> bool:
    first = copied.lstrip().split("\n", 1)[0].casefold()
    return any(word in first for word in WAYSTONE_CLASSES)


def danger_keys(chosen: list[str] | None, kinds: list[dict]) -> set[str]:
    return USUAL_DANGERS & {kind["key"] for kind in kinds} if chosen is None else set(chosen)


def dangerous_lines(copied: str, kinds: list[dict], danger: set[str]) -> list[str]:
    """The lines of a copied Waystone that are on the player's list, as the game wrote them."""
    forms = {form.casefold() for kind in kinds if kind["key"] in danger for form in kind["forms"]}
    return [line.strip() for line in copied.replace("\r\n", "\n").split("\n") if waystone_template(line).casefold() in forms]


def shortest_fragment(text: str, others: list[str]) -> str:
    """The shortest piece of a line that no other line contains. A piece of one word comes first, however long: one across two words is mostly common endings."""
    pieces = [piece.strip() for piece in SEARCH_SEPARATORS.split(text.casefold())]
    others = [other.casefold() for other in others]
    longest = max(map(len, pieces), default=0)
    for allow_space in (False, True):
        for length in range(SHORTEST_SPACED_FRAGMENT if allow_space and longest >= SHORTEST_SPACED_FRAGMENT else SHORTEST_FRAGMENT, longest + 1):
            candidates = {piece[start:start + length] for piece in pieces for start in range(len(piece) - length + 1)}
            usable = sorted(found for found in candidates if found == found.strip() and (allow_space or " " not in found) and not any(found in other for other in others))
            if usable:
                return usable[0]
    return ""


def waystone_fragments(waystones: dict, code: str) -> dict[str, str]:
    """Each mod's search fragment in one language. Rewards count too: a fragment must not hide a good line by accident."""
    kinds = waystones.get("kinds", [])
    wording = {kind["key"]: kind["ru"] if code == "ru" else kind["key"] for kind in kinds}
    rewards = waystones.get("rewards", {}).get(code, [])
    return {key: shortest_fragment(line, [other for other in (*wording.values(), *rewards) if other != line]) for key, line in wording.items()}


def exclusion_search(fragments: list[str]) -> str:
    """For the game's search box: shows only what contains none of the fragments."""
    used = [fragment for fragment in fragments if fragment]
    return '"!' + "|".join(used) + '"' if used else ""


# ------------------------------------------------------------------------------ the map timer
class Stopwatch:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.reset()

    def reset(self) -> None:
        self.started_at: float | None = None
        self.banked = 0.0
        self.laps: list[float] = []

    @property
    def running(self) -> bool:
        return self.started_at is not None

    @property
    def elapsed(self) -> float:
        return self.banked + (self.clock() - self.started_at if self.running else 0.0)

    def toggle(self) -> None:
        if self.running:
            self.banked = self.elapsed
            self.started_at = None
        else:
            self.started_at = self.clock()

    def lap(self) -> None:
        """Ends this map and starts counting the next one straight away."""
        if self.elapsed > 0:
            self.laps.append(self.elapsed)
            self.banked = 0.0
            self.started_at = self.clock() if self.running else None

    @property
    def average(self) -> float | None:
        return sum(self.laps) / len(self.laps) if self.laps else None


def format_time(seconds: float) -> str:
    whole = int(seconds) if math.isfinite(seconds) else 0
    hours, minutes, rest = whole // 3600, whole // 60 % 60, whole % 60
    return f"{hours}:{minutes:02}:{rest:02}" if hours else f"{minutes:02}:{rest:02}"


# ------------------------------------------------------------------------------ mod reference
def mod_table(page, ilvl: int, side: str) -> list[tuple]:
    """Each modifier a base can roll on one side: (ladder, its share of the side, [(tier, mod, share)]). A share is the chance on an empty side."""
    ladders = [(ladder, ladder.available(ilvl)) for ladder in page.ladders if ladder.side == side]
    ladders = [(ladder, tiers) for ladder, tiers in ladders if tiers]
    total = sum(mod.weight for _, tiers in ladders for mod in tiers) or 1
    table = [(ladder, sum(mod.weight for mod in tiers) / total, [(ladder.mods.index(mod) + 1, mod, mod.weight / total) for mod in tiers]) for ladder, tiers in ladders]
    return sorted(table, key=lambda entry: -entry[1])


# ------------------------------------------------------------------------------ one canvas for every list
LINE_HEIGHT = 24
WRAPPED_LINE_HEIGHT = 16
RESIZE_SETTLE_MS = 120


@dataclass
class Cell:
    x: int  # from the left, or from the right when negative
    text: str = ""
    color: str | None = None
    size: int = 9
    bold: bool = False
    anchor: str = "w"
    wrap: bool = False  # takes the width to the right edge and wraps inside it
    image: object = None
    command: object = None
    room: int = 0  # for wrapped text: how much is left free on the right for the columns after it
    dy: int = 0  # up or down from the middle of the line, for two cells one above the other


@dataclass
class Line:
    cells: list[Cell] = field(default_factory=list)
    ground: str | None = None
    height: int = LINE_HEIGHT
    gap: int = 1
    command: object = None


class Board:
    """Draws every list on one canvas. Hundreds of widgets would take far too long to lay out.
    A lazy board draws only the lines in view and a screen around them, the rest as they scroll near: a long list then costs what a short one does."""

    LAZY_MARGIN = 1.0  # screens drawn ahead above and below the view
    FILL_BATCH, FILL_PAUSE_MS = 12, 30  # then the rest in the background: a few lines, a pause for the window to answer
    fill_job = None

    def __init__(self, parent, colors: dict[str, str], enable_scrolling, lazy: bool = False):
        self.colors = colors
        self.lazy = lazy
        self.tops: list[int] = []
        self.heights: list[int] = []
        self.drawn: set[int] = set()
        self.drawn_rows: dict[tuple, int] = {}  # wrapped text measured once: (text, size, bold, room) -> rows
        self.view_command = ""
        holder = tk.Frame(parent, bg=colors["background"])
        holder.pack(fill="both", expand=True)
        holder.columnconfigure(0, weight=1)
        holder.columnconfigure(1, minsize=11)
        holder.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(holder, bg=colors["background"], highlightthickness=0, bd=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        enable_scrolling(holder, self.canvas)
        if lazy:  # the scrollbar still hears of every move, and the board draws what came into view
            self.view_command = str(self.canvas.cget("yscrollcommand"))
            self.canvas.configure(yscrollcommand=self._on_view)
        self.lines: list[Line] = []
        self.drawn_width = None
        self.job = None
        self.fonts: dict[tuple[int, bool], tkfont.Font] = {}
        self.commands: dict[str, object] = {}
        self.canvas.bind("<Configure>", self._on_resize)
        # One handler for the whole canvas: a binding per drawn word would pile up with every redraw for as long as the program runs.
        self.canvas.bind("<Button-1>", self._on_click, add="+")
        self.canvas.bind("<Motion>", self._on_motion)

    def show(self, lines: list[Line], to_top: bool = True) -> None:
        self.lines = lines
        self._draw()
        if to_top:
            self.canvas.yview_moveto(0)

    def _on_resize(self, event) -> None:
        if event.width != self.drawn_width:
            window = self.canvas.winfo_toplevel()  # outlives this page, which a change of language rebuilds
            if self.job:
                window.after_cancel(self.job)
            self.job = window.after(RESIZE_SETTLE_MS, self._draw)

    def _font(self, cell: Cell) -> tkfont.Font:
        key = cell.size, cell.bold
        if key not in self.fonts:
            self.fonts[key] = tkfont.Font(self.canvas, family=BODY, size=cell.size, weight="bold" if cell.bold else "normal")
        return self.fonts[key]

    def _height(self, line: Line, width: int) -> int:
        height = line.height
        for cell in line.cells:
            if cell.wrap:
                room = max(width - cell.x - 12 - cell.room, 40)
                key = cell.text, cell.size, cell.bold, room
                rows = self.drawn_rows.get(key)
                if rows is None:
                    if len(self.drawn_rows) > 20000:
                        self.drawn_rows.clear()
                    rows = self.drawn_rows[key] = sum(max(math.ceil(self._font(cell).measure(part) * 1.06 / room), 1) for part in cell.text.split("\n"))
                height = max(height, rows * WRAPPED_LINE_HEIGHT + 8)
        return height

    def _on_view(self, first, last) -> None:
        if self.view_command:
            self.canvas.tk.call(self.view_command, first, last)
        self._draw_in_view()

    def _draw_in_view(self) -> None:
        canvas = self.canvas
        if not self.tops or not canvas.winfo_exists():
            return
        seen = max(canvas.winfo_height(), 200)
        top = canvas.canvasy(0) - seen * self.LAZY_MARGIN
        bottom = canvas.canvasy(0) + seen * (1 + self.LAZY_MARGIN)
        first = max(bisect.bisect_right(self.tops, top) - 1, 0)
        last = bisect.bisect_right(self.tops, bottom)
        for number in range(first, min(last, len(self.lines))):
            if number not in self.drawn:
                self._draw_line(number)
        if len(self.drawn) < len(self.lines) and not self.fill_job:  # timed on the window: the page and its canvas may be built anew meanwhile
            self.fill_job = canvas.winfo_toplevel().after(self.FILL_PAUSE_MS, self._fill_rest)

    def _fill_rest(self) -> None:
        """The lines out of view, a few at a time while the window is idle: by the time the player scrolls there they are drawn."""
        self.fill_job = None
        if not self.canvas.winfo_exists():
            return
        left = [number for number in range(len(self.lines)) if number not in self.drawn][:self.FILL_BATCH]
        for number in left:
            self._draw_line(number)
        if len(self.drawn) < len(self.lines):
            self.fill_job = self.canvas.winfo_toplevel().after(self.FILL_PAUSE_MS, self._fill_rest)

    def _command_under_pointer(self):
        return next((self.commands[tag] for tag in self.canvas.gettags("current") if tag in self.commands), None)

    def _on_click(self, _) -> None:
        command = self._command_under_pointer()
        if command:
            command()

    def _on_motion(self, _) -> None:
        self.canvas.config(cursor="hand2" if self._command_under_pointer() else "")

    def _draw(self) -> None:
        self.job = None
        canvas = self.canvas
        if not canvas.winfo_exists() or canvas.winfo_width() < 2:
            return
        width = canvas.winfo_width()
        self.drawn_width = width
        canvas.delete("all")
        canvas.config(cursor="")
        self.commands = {}
        self.drawn = set()
        if self.fill_job:
            canvas.winfo_toplevel().after_cancel(self.fill_job)
            self.fill_job = None
        self.tops, self.heights = [], []
        y = 0
        for line in self.lines:
            height = self._height(line, width)
            self.tops.append(y)
            self.heights.append(height)
            y += height + line.gap
        canvas.configure(scrollregion=(0, 0, width, max(y, 1)))
        if self.lazy:
            self._draw_in_view()
        else:
            for number in range(len(self.lines)):
                self._draw_line(number)

    def _draw_line(self, number: int) -> None:
        canvas, line = self.canvas, self.lines[number]
        width, y, height = self.drawn_width, self.tops[number], self.heights[number]
        self.drawn.add(number)
        tag = f"line{number}"
        ground = line.ground or (self.colors["background"] if line.command else None)
        if ground:
            canvas.create_rectangle(0, y, width, y + height, width=0, fill=ground, tags=(tag,))
        for place, cell in enumerate(line.cells):
            x = width + cell.x if cell.x < 0 else cell.x
            tags = (f"{tag}cell{place}",) if cell.command else (tag,)
            if cell.image:
                canvas.create_image(x, y + height // 2 + cell.dy, image=cell.image, anchor=cell.anchor, tags=tags)
            else:
                wrap = {"width": max(width - cell.x - 12 - cell.room, 40)} if cell.wrap else {}
                canvas.create_text(x, y + height // 2 + cell.dy, text=cell.text, fill=cell.color or self.colors["text"], font=(BODY, cell.size, "bold" if cell.bold else "normal"), anchor=cell.anchor, tags=tags, **wrap)
            if cell.command:
                self.commands[tags[0]] = cell.command
        if line.command:
            self.commands[tag] = line.command


# ----------------------------------------------------------------------------------- the tab
class ToolsPage:
    TABS = (("bookmarks", "Закладки"), ("journal", "Журнал"), ("exchange", "Биржа"), ("reference", "Справочник"), ("waystones", "Камни"), ("timer", "Таймер"), ("watch", "Слежение"), ("history", "История"), ("stash", "Тайник"), ("calc", "Счёт"), ("notes", "Заметки"))
    CALC_COINS = ("Divine Orb", "Exalted Orb", "Chaos Orb")
    NOTES_SAVE_MS = 800
    SIDE_TITLES = (("prefix", "Префиксы"), ("suffix", "Суффиксы"))
    TIMER_TICK_MS = 250
    timer_tick_job = None

    def __init__(self, parent, colors: dict[str, str], translate, helpers: dict, store: dict, stopwatch: Stopwatch):
        self.colors = colors
        self.t = translate
        self.helpers = helpers  # what the main window lends: names, icons, price formats, the clipboard
        self.store = store  # the contents of tools.json
        self.stopwatch = stopwatch
        self.tab = "bookmarks"
        self.exchange: tuple[int, list[ExchangeRow]] | None = None
        self.exchange_busy = False
        self.fields = {name: tk.StringVar() for name in ("deal_name", "deal_bought", "deal_sold", "base", "search", "watch_name", "watch_amount", "stash_all", "stash_any", "stash_none", "calc_amount", "calc_from", "calc_to")}
        self.notes_job = None
        self.stash_line = tk.StringVar()
        self.stash_note = None
        self.watch_direction = tk.StringVar(value="below")
        self.watch_unit = tk.StringVar(value=JOURNAL_UNITS[0])
        self.deal_unit = tk.StringVar(value=JOURNAL_UNITS[0])
        self.ilvl = tk.StringVar(value="82")
        self.search_job = None
        page = tk.Frame(parent, bg=colors["background"], padx=10)
        page.pack(fill="both", expand=True)
        for name in ("calc_amount", "calc_from", "calc_to"):
            trace_while(self.fields[name], page, lambda *_: self._draw_calc() if self.tab == "calc" else None)
        for name in ("stash_all", "stash_any", "stash_none"):
            trace_while(self.fields[name], page, lambda *_: self._draw_stash_line())
        trace_while(self.fields["search"], page, lambda *_: self._after_search())
        tabs = tk.Frame(page, bg=colors["background"])
        tabs.pack(fill="x", pady=(0, 8))
        self.tab_buttons = {}
        for column, (key, title) in enumerate(self.TABS):
            tabs.columnconfigure(column, weight=1, uniform="tools")
            button = tk.Button(tabs, text=self.t(title), command=lambda k=key: self.set_tab(k), relief="flat", bd=0, cursor="hand2", padx=1, pady=5, font=(BODY, 9))
            button.grid(row=0, column=column, sticky="ew", padx=(0, 4))
            self.tab_buttons[key] = button
        self.form = tk.Frame(page, bg=colors["background"])
        self.form.pack(fill="x")
        self.board = Board(page, colors, helpers["enable_scrolling"])
        self.canvas = self.board.canvas

    # ---- small shared pieces
    def _label(self, parent, text: str, color: str | None = None, size: int = 9, bold: bool = False, wrap: int = 0) -> tk.Label:
        return tk.Label(parent, text=text, bg=self.colors["background"], fg=color or self.colors["muted"], font=(BODY, size, "bold" if bold else "normal"), anchor="w", justify="left", wraplength=wrap)

    def _button(self, parent, text: str, command, primary: bool = False) -> tk.Button:
        button = self.helpers["button"](parent, text, command, primary)
        button.config(font=(BODY, 9), padx=10, pady=4)
        return button

    def _row(self, bottom: int = 6) -> tk.Frame:
        row = tk.Frame(self.form, bg=self.colors["background"])
        row.pack(fill="x", pady=(0, bottom))
        return row

    def _note(self, text: str) -> None:
        self._label(self._row(), text, wrap=860).pack(anchor="w")

    def _message_line(self, text: str) -> Line:
        return Line([Cell(10, text, self.colors["muted"], wrap=True)], height=32)

    def set_tab(self, key: str) -> None:
        self.tab = key
        self.render()

    def render(self) -> None:
        colors = self.colors
        for key, button in self.tab_buttons.items():
            active = key == self.tab
            ground, letters = (colors["selected"], colors["on_selected"]) if active else (colors["panel"], colors["soft"])
            button.config(bg=ground, fg=letters, activebackground=ground if active else colors["raised"], activeforeground=letters if active else colors["text"], font=(BODY, 9, "bold" if active else "normal"))
        for child in self.form.winfo_children():
            child.destroy()
        getattr(self, f"_render_{self.tab}")()

    def show_if_open(self, tab: str) -> None:
        if self.tab == tab and self.canvas.winfo_ismapped():
            self.render()

    def _save(self) -> None:
        self.helpers["save"]()

    # ---- bookmarks
    def _render_bookmarks(self) -> None:
        self._note(self.t("Сохраняйте поиски звёздочкой в окне цены. Закладка открывает тот же поиск на сайте торговли."))
        self._draw_bookmarks()

    def _draw_bookmarks(self) -> None:
        colors = self.colors
        marks = self.store.get("bookmarks", [])
        if not marks:
            return self.board.show([self._message_line(self.t("Закладок пока нет"))])
        lines = []
        for mark in marks:
            lines.append(Line([Cell(10, mark["name"], colors["text"], 10, True), Cell(-290, mark["price"], colors["soft"], 9, False, "e"), Cell(-170, mark["date"], colors["muted"], 9, False, "e"),
                               Cell(-95, self.t("открыть"), colors["accent"], 9, True, "e", command=lambda link=mark["link"]: self.helpers["open_link"](link)),
                               Cell(-12, self.t("удалить"), colors["muted"], 9, False, "e", command=lambda link=mark["link"]: self._remove_bookmark(link))], colors["panel"], 32))
        self.board.show(lines)

    def _remove_bookmark(self, link: str) -> None:
        self.store["bookmarks"] = [mark for mark in self.store.get("bookmarks", []) if mark["link"] != link]
        self._save()
        self._draw_bookmarks()

    # ---- price watches
    def _render_watch(self) -> None:
        row = self._row()
        make_entry = self.helpers["make_entry"]
        self._label(row, self.t("Предмет")).pack(side="left", padx=(0, 6))
        make_entry(row, self.fields["watch_name"], 34).pack(side="left", padx=(0, 12), ipady=4)
        directions = {self.t("дешевле"): "below", self.t("дороже"): "above"}
        direction = ttk.Combobox(row, values=list(directions), width=8, state="readonly")
        direction.set(next(title for title, key in directions.items() if key == self.watch_direction.get()))
        direction.bind("<<ComboboxSelected>>", lambda _: self.watch_direction.set(directions[direction.get()]))
        direction.pack(side="left", padx=(0, 8))
        make_entry(row, self.fields["watch_amount"], 8).pack(side="left", padx=(0, 8), ipady=4)
        titles = {self.helpers["unit_label"](unit): unit for unit in JOURNAL_UNITS}
        unit = ttk.Combobox(row, values=list(titles), width=9, state="readonly")
        unit.set(self.helpers["unit_label"](self.watch_unit.get()))
        unit.bind("<<ComboboxSelected>>", lambda _: self.watch_unit.set(titles[unit.get()]))
        unit.pack(side="left", padx=(0, 12))
        self._button(row, self.t("Поставить"), self._add_watch, True).pack(side="left")
        self.watch_note = self._label(self._row(8), self.t("Сообщу значком в трее и строкой внизу окна, когда цена дойдёт до порога. Цены уже обновляются программой, лишних запросов нет. Разделы со слежением обновляются раз в час, даже когда за компьютером никого нет."), wrap=860)
        self.watch_note.pack(anchor="w")
        self._draw_watches()

    def _add_watch(self) -> None:
        name = self.helpers["find_priced"](self.fields["watch_name"].get())
        amount = read_amount(self.fields["watch_amount"].get())
        if not self.fields["watch_name"].get().strip() or not amount:
            return self.watch_note.config(text=self.t("Нужно название и порог числом"), fg=self.colors["down"])
        if not name:
            return self.watch_note.config(text=self.t("Такого предмета нет в ценах этой лиги, либо под название подходит несколько: уточните"), fg=self.colors["down"])
        prices = self.helpers["prices"]() or {}
        if to_exalted(amount, self.watch_unit.get(), prices) is None:
            return self.watch_note.config(text=self.t("Курс этой валюты ещё не загружен"), fg=self.colors["down"])
        self.store["watches"] = add_watch(self.store.get("watches", []), name, self.watch_direction.get(), amount, self.watch_unit.get())
        self.fields["watch_name"].set("")
        self.fields["watch_amount"].set("")
        self._save()
        self.helpers["watches_changed"]()
        self.render()

    def _remove_watch(self, watch: dict) -> None:
        self.store["watches"] = [other for other in self.store.get("watches", []) if (other["name"], other["direction"]) != (watch["name"], watch["direction"])]
        self._save()
        self.helpers["watches_changed"]()
        self._draw_watches()

    def _draw_watches(self) -> None:
        colors = self.colors
        watches = self.store.get("watches", [])
        if not watches:
            return self.board.show([self._message_line(self.t("Слежений пока нет"))])
        lines = []
        for watch in watches:
            now = self.helpers["current_divine"](watch["name"])
            limit = f"{self.t('дешевле') if watch['direction'] == 'below' else self.t('дороже')} {watch['amount']:g} {self.helpers['unit_label'](watch['unit'])}"
            state, color = (self.t("нет обменов"), colors["muted"]) if not now else (self.t("дошла"), colors["accent"]) if watch["fired"] else (self.t("ждёт"), colors["muted"])
            icon = self.helpers["item_icon"](watch["name"], 24)
            lines.append(Line([*([Cell(10, image=icon)] if icon else []), Cell(42, self.helpers["show_item"](watch["name"]), colors["text"], 10, True), Cell(-400, limit, colors["soft"], 9, False, "e"), Cell(-230, self.t("сейчас {price}").format(price=self.helpers["item_price"](watch["name"])) if now else "—", colors["soft"], 9, False, "e"),
                               Cell(-95, state, color, 9, True, "e"), Cell(-12, self.t("удалить"), colors["muted"], 9, False, "e", command=lambda found=watch: self._remove_watch(found))], colors["panel"], 32))
        self.board.show(lines)

    # ---- the history of checked items
    def _render_history(self) -> None:
        row = self._row(8)
        self._label(row, self.t("Последние предметы, цену которых вы проверяли. Они лежат только на этом компьютере. «Открыть» показывает цену снова без игры. Кнопки − и + задают, сколько таких предметов считать в сумме, 0 убирает из неё."), wrap=760).pack(side="left")
        if self.store.get("history"):
            self._button(row, self.t("Очистить"), self._clear_history).pack(side="right", padx=(0, 10))
        self.history_sum = self._label(self._row(8), "", self.colors["text"], 12, True)
        self.history_sum.pack(anchor="w")
        self._draw_history()

    def _change_count(self, copied: str, change: int) -> None:
        self.store["history"] = change_count(self.store.get("history", []), copied, change)
        self._save()
        self._draw_history()

    def _clear_history(self) -> None:
        self.store["history"] = []
        self._save()
        self.render()

    def _draw_history(self) -> None:
        colors = self.colors
        history = self.store.get("history", [])
        total, unpriced = history_total(history, self.helpers["current_divine"])
        words = self.t("Всё вместе сейчас: {price}").format(price=self.helpers["price_text"](total)) if total else ""
        if unpriced and total:
            words += "  •  " + self.t("без цены: {count}").format(count=unpriced)
        self.history_sum.config(text=words)
        if not history:
            return self.board.show([self._message_line(self.t("Проверок пока нет"))])
        lines = []
        for entry in history:
            then = self.t("тогда {price}").format(price=entry["price"]) if entry["price"] else self.t("нужен поиск")
            now = "" if not entry["priced_name"] else self.t("сейчас {price}").format(price=self.helpers["item_price"](entry["priced_name"])) if self.helpers["current_divine"](entry["priced_name"]) else self.t("сейчас нет обменов")
            icon = self.helpers["item_icon"](entry["priced_name"], 24) if entry["priced_name"] else None
            stack = entry.get("stack", 1)
            title = f"{entry['name']} ×{stack}" if stack > 1 else entry["name"]
            copied = entry["copied"]
            lines.append(Line([*([Cell(10, image=icon)] if icon else []), Cell(42, title, colors["text"], 10, True), Cell(-420, then, colors["muted"], 9, False, "e"), Cell(-270, now, colors["soft"], 9, False, "e"), Cell(-185, entry["date"], colors["muted"], 9, False, "e"),
                               Cell(-152, "−", colors["soft"], 11, True, "e", command=lambda found=copied: self._change_count(found, -1)), Cell(-130, str(entry.get("count", 1)), colors["text"], 9, True, "e"), Cell(-106, "+", colors["soft"], 11, True, "e", command=lambda found=copied: self._change_count(found, 1)),
                               Cell(-12, self.t("открыть"), colors["accent"], 9, True, "e", command=lambda found=copied: self.helpers["recheck"](found))], colors["panel"], 32))
        self.board.show(lines)

    # ---- what one amount is worth in another currency
    def _render_calc(self) -> None:
        row = self._row(8)
        make_entry = self.helpers["make_entry"]
        for caption, name, width in (("Сколько", "calc_amount", 8), ("Чего", "calc_from", 28), ("Перевести в", "calc_to", 28)):
            self._label(row, self.t(caption)).pack(side="left", padx=(0, 6))
            make_entry(row, self.fields[name], width).pack(side="left", padx=(0, 12), ipady=4)
        self._note(self.t("По ценам, которые уже есть в программе. Без запросов. Название можно писать на любом языке, часть названия тоже подойдёт."))
        if not self.fields["calc_amount"].get():
            self.fields["calc_amount"].set("1")
            self.fields["calc_from"].set(self.helpers["show_currency"](self.CALC_COINS[0]))
        self._draw_calc()

    def _draw_calc(self) -> None:
        colors = self.colors
        amount = read_amount(self.fields["calc_amount"].get())
        source = self.helpers["find_priced"](self.fields["calc_from"].get())
        value = self.helpers["value_in_divine"](source) if source else None
        if amount is None or not value:
            return self.board.show([self._message_line(self.t("Нужно число и название предмета с ценой"))])
        goal = self.helpers["find_priced"](self.fields["calc_to"].get())
        names = [*([goal] if goal else []), *(name for name in self.CALC_COINS if name not in (goal, source))]
        lines = [Line([Cell(10, f"{amount:g}  ×  {self.helpers['show_item'](source)}", colors["text"], 10, True)], colors["panel"], 32)]
        for name in names:
            target = self.helpers["value_in_divine"](name)
            if target:
                result = convert_amount(amount, value, target)
                icon = self.helpers["item_icon"](name, 24)
                lines.append(Line([*([Cell(10, image=icon)] if icon else []), Cell(42, self.helpers["show_item"](name), colors["soft"], 10), Cell(-12, f"{result:,.2f}".replace(",", " "), colors["accent"], 11, True, "e")], colors["panel"], 32))
        self.board.show(lines)

    # ---- the player's own notes
    def _render_notes(self) -> None:
        colors = self.colors
        self.board.show([])
        self._note(self.t("Цели билда, что искать, что не забыть. Хранится только на этом компьютере."))
        self.notes_box = tk.Text(self._row(0), height=26, wrap="word", bg=colors["panel"], fg=colors["text"], insertbackground=colors["text"], relief="flat", bd=0, padx=10, pady=8, font=(BODY, 10), undo=True)
        self.notes_box.pack(fill="x")
        self.notes_box.insert("1.0", self.store.get("notes", ""))
        self.notes_box.bind("<KeyRelease>", lambda _: self._notes_typed())

    def _notes_typed(self) -> None:
        self.store["notes"] = self.notes_box.get("1.0", "end-1c")[:NOTES_LIMIT]
        root = self.notes_box.nametowidget(".")
        if self.notes_job:
            root.after_cancel(self.notes_job)
        self.notes_job = root.after(self.NOTES_SAVE_MS, self._save_notes)

    def _save_notes(self) -> None:
        self.notes_job = None
        self._save()

    # ---- a search line for the stash
    def _render_stash(self) -> None:
        self.stash_note = None
        saved = self.store.get("stash_fields", {})
        for caption, name in (("Должно быть всё из", "stash_all"), ("Хотя бы одно из", "stash_any"), ("Ничего из", "stash_none")):
            row = self._row()
            self._label(row, self.t(caption)).config(width=STASH_CAPTION_WIDTH)
            row.winfo_children()[-1].pack(side="left", padx=(0, 6))
            self.helpers["make_entry"](row, self.fields[name]).pack(side="left", fill="x", expand=True, ipady=4)
            self.fields[name].set(saved.get(name, ""))
        row = self._row()
        self._label(row, self.t("Строка для поиска")).config(width=STASH_CAPTION_WIDTH)
        row.winfo_children()[-1].pack(side="left", padx=(0, 6))
        self._button(row, self.t("Сохранить"), self._save_stash_line).pack(side="right", padx=(6, 0))
        self._button(row, self.t("Скопировать"), self._copy_stash_line, True).pack(side="right", padx=(6, 0))
        self.helpers["make_entry"](row, self.stash_line).pack(side="left", fill="x", expand=True, ipady=4)
        self.stash_note = self._label(self._row(4), "", wrap=860)
        self.stash_note.pack(anchor="w")
        self._note(self.t("Пишите через запятую слова или части модов на языке игры. Строку вставляете вы сами в поиск тайника, программа ничего не отправляет в игру. Синтаксис поиска взят из гайдов: проверьте на паре предметов."))
        self._draw_stash_line()
        self._draw_stash_lines()

    def _draw_stash_line(self) -> None:
        if self.tab != "stash" or not self.stash_note:
            return
        self.store["stash_fields"] = {name: self.fields[name].get() for name in ("stash_all", "stash_any", "stash_none")}
        line = stash_search(*(stash_words(self.fields[name].get()) for name in ("stash_all", "stash_any", "stash_none")))
        self.stash_line.set(line)
        too_long = len(line) > LONGEST_SEARCH
        self.stash_note.config(text=self.t("Длина строки {length}: игра может не принять больше {limit}, уберите часть модов" if too_long else "Длина строки: {length} из {limit}").format(length=len(line), limit=LONGEST_SEARCH), fg=self.colors["down"] if too_long else self.colors["muted"])

    def _copy_stash_line(self, line: str | None = None) -> None:
        line = line if line is not None else self.stash_line.get()
        if line:
            self.helpers["copy"](line)
            self._save()
            self.stash_note.config(text=self.t("Скопировано: вставьте в поиск тайника в игре"), fg=self.colors["up"])

    def _save_stash_line(self) -> None:
        if self.stash_line.get():
            self.store["stash_lines"] = add_stash_line(self.store.get("stash_lines", []), self.stash_line.get())
            self._save()
            self._draw_stash_lines()

    def _remove_stash_line(self, line: str) -> None:
        self.store["stash_lines"] = [other for other in self.store.get("stash_lines", []) if other != line]
        self._save()
        self._draw_stash_lines()

    def _draw_stash_lines(self) -> None:
        colors = self.colors
        saved = self.store.get("stash_lines", [])
        if not saved:
            return self.board.show([self._message_line(self.t("Сохранённых строк пока нет"))])
        self.board.show([Line([Cell(10, line[:96], colors["text"], 9), Cell(-95, self.t("копировать"), colors["accent"], 9, True, "e", command=lambda found=line: self._copy_stash_line(found)), Cell(-12, self.t("удалить"), colors["muted"], 9, False, "e", command=lambda found=line: self._remove_stash_line(found))], colors["panel"], 32) for line in saved])

    # ---- deal journal
    def _render_journal(self) -> None:
        row = self._row()
        make_entry = self.helpers["make_entry"]
        for caption, name, width in (("Предмет", "deal_name", 30), ("Куплено за", "deal_bought", 8), ("Продано за", "deal_sold", 8)):
            self._label(row, self.t(caption)).pack(side="left", padx=(0, 6))
            make_entry(row, self.fields[name], width).pack(side="left", padx=(0, 12), ipady=4)
        titles = {self.helpers["unit_label"](unit): unit for unit in JOURNAL_UNITS}
        chosen = ttk.Combobox(row, values=list(titles), width=9, state="readonly")
        chosen.set(self.helpers["unit_label"](self.deal_unit.get()))
        chosen.bind("<<ComboboxSelected>>", lambda _: self.deal_unit.set(titles[chosen.get()]))
        chosen.pack(side="left", padx=(0, 12))
        self._button(row, self.t("Добавить"), self._add_deal, True).pack(side="left")
        self.journal_note = self._label(self._row(), self.t("Записывается только то, что вы ввели сами. Программа не читает игру и ваши сделки."), wrap=860)
        self.journal_note.pack(anchor="w")
        self.journal_total = self._label(self._row(8), "", self.colors["text"], 12, True)
        self.journal_total.pack(anchor="w")
        self._draw_journal()

    def _draw_journal(self) -> None:
        colors = self.colors
        deals = self.store.get("journal", [])
        profit, still_open, closed = journal_totals(deals)
        cost = self.helpers["cost"]
        words = self.t("Прибыль: {profit}  •  закрыто сделок: {closed}").format(profit=("-" if profit < 0 else "+") + cost(abs(profit)), closed=closed)
        if still_open:
            words += "  •  " + self.t("вложено в открытые: {value}").format(value=cost(still_open))
        self.journal_total.config(text=words, fg=colors["up"] if profit > 0 else colors["down"] if profit < 0 else colors["text"])
        if not deals:
            return self.board.show([self._message_line(self.t("Сделок пока нет"))])
        lines = []
        for number, deal in reversed(list(enumerate(deals))):
            unit = self.helpers["unit_label"](deal["unit"])
            bought = f"{deal['bought']:g} {unit}"
            cells = [Cell(10, deal["name"], colors["text"], 10, True), Cell(-400, bought, colors["soft"], 9, False, "e"), Cell(-12, self.t("удалить"), colors["muted"], 9, False, "e", command=lambda n=number: self._remove_deal(n)), Cell(-80, deal["date"], colors["muted"], 9, False, "e")]
            if deal.get("sold") is None:
                cells.append(Cell(-280, self.t("продал"), colors["accent"], 9, True, "e", command=lambda n=number: self._close_deal(n)))
            else:
                change = (deal["sold_exalted"] or 0) - (deal["bought_exalted"] or 0)
                cells.append(Cell(-280, f"{deal['sold']:g} {unit}", colors["soft"], 9, False, "e"))
                cells.append(Cell(-170, ("-" if change < 0 else "+") + cost(abs(change)), colors["down"] if change < 0 else colors["up"], 9, True, "e"))
            lines.append(Line(cells, colors["panel"], 32))
        self.board.show(lines)

    def _add_deal(self) -> None:
        name = self.fields["deal_name"].get().strip()
        bought = read_amount(self.fields["deal_bought"].get())
        sold_text = self.fields["deal_sold"].get().strip()
        sold = read_amount(sold_text) if sold_text else None
        prices = self.helpers["prices"]()
        if not name or bought is None or (sold_text and sold is None):
            return self.journal_note.config(text=self.t("Нужны название и цена покупки числом"), fg=self.colors["down"])
        if not prices:
            return self.journal_note.config(text=self.t("Курсы ещё не загружены, подождите"), fg=self.colors["down"])
        self.store.setdefault("journal", []).append(make_deal(name, bought, sold, self.deal_unit.get(), prices, self.helpers["today"]()))
        self._save()
        for key in ("deal_name", "deal_bought", "deal_sold"):
            self.fields[key].set("")
        self._draw_journal()

    def _close_deal(self, number: int) -> None:
        sold = read_amount(self.fields["deal_sold"].get())
        prices = self.helpers["prices"]()
        if sold is None or not prices:
            return self.journal_note.config(text=self.t("Впишите цену продажи в поле «Продано за» и нажмите «продал» ещё раз"), fg=self.colors["accent"])
        deals = self.store["journal"]
        deals[number] = close_deal(deals[number], sold, prices)
        self.fields["deal_sold"].set("")
        self._save()
        self._draw_journal()

    def _remove_deal(self, number: int) -> None:
        del self.store["journal"][number]
        self._save()
        self._draw_journal()

    # ---- exchange
    def _render_exchange(self) -> None:
        row = self._row()
        self.exchange_button = self._button(row, self.t("Показать оборот"), self._check_exchange, True)
        self.exchange_button.pack(side="left", padx=(0, 12))
        self.exchange_note = self._label(row, "")
        self.exchange_note.pack(side="left")
        self._note(self.t("Что больше всего меняли за прошлый час на официальной бирже, в пересчёте на Exalted. Это показывает спрос, а не прибыль: выгодный обмен по этим данным найти нельзя, средние цены там слишком разбросаны."))
        self._draw_exchange()

    def _check_exchange(self) -> None:
        """The file changes once an hour, so a second press within the hour sends nothing."""
        if self.exchange_busy:
            return
        if self.exchange and self.exchange[0] == int(time.time() // HOUR_SECONDS) * HOUR_SECONDS - HOUR_SECONDS:
            return self.exchange_note.config(text=self.t("Новые курсы появятся в начале следующего часа"))
        self.exchange_busy = True
        self.exchange_note.config(text=self.t("Загружаю..."))
        self.helpers["check_exchange"]()

    def show_exchange(self, hour: int, rows: list[ExchangeRow]) -> None:
        self.exchange_busy = False
        self.exchange = hour, rows
        self.show_if_open("exchange")

    def show_exchange_error(self, text: str) -> None:
        self.exchange_busy = False
        if self.tab == "exchange" and self.canvas.winfo_ismapped():
            self.exchange_note.config(text=text)

    def _draw_exchange(self) -> None:
        colors = self.colors
        if self.exchange_busy:
            self.exchange_note.config(text=self.t("Загружаю..."))
        if not self.exchange:
            return self.board.show([self._message_line(self.t("Нажмите кнопку: программа один раз скачает файл биржи."))])
        hour, rows = self.exchange
        self.exchange_note.config(text=self.t("Файл биржи за {time}").format(time=self.helpers["local_time"](hour)))
        if not rows:
            return self.board.show([self._message_line(self.t("В этой лиге за час не было сделок"))])
        lines = [Line([Cell(10, self.t("Предмет"), colors["muted"], 8, True), Cell(-290, self.t("Оборот, час"), colors["muted"], 8, True, "e"), Cell(-130, self.t("Чаще платят"), colors["muted"], 8, True, "e"), Cell(-12, self.t("Цена ≈"), colors["muted"], 8, True, "e")], height=20)]
        label, show, cost, price_of = self.helpers["unit_label"], self.helpers["show_currency"], self.helpers["cost"], self.helpers["price_of"]
        for row in rows:
            icon = self.helpers["icon"](row.item, 24)
            cells = [Cell(10, image=icon)] if icon else []
            lines.append(Line([*cells, Cell(42, show(row.item), colors["text"], 10, True), Cell(-290, cost(row.traded_exalted), colors["text"], 10, True, "e"), Cell(-130, f"{label(row.main_coin)} {row.main_share:.0%}", colors["soft"], 9, False, "e"), Cell(-12, price_of(row.item), colors["soft"], 9, False, "e")], colors["panel"], 32))
        self.board.show(lines)

    # ---- reference
    def _render_reference(self) -> None:
        db = self.helpers["db"]()
        if not db:
            return self.board.show([self._message_line(self.t("Данные ещё загружаются"))])
        row = self._row()
        self._label(row, self.t("База")).pack(side="left", padx=(0, 6))
        box = ttk.Combobox(row, textvariable=self.fields["base"], width=34, values=sorted(db.show_base(base) for base in db.bases))
        box.pack(side="left", padx=(0, 12))
        box.bind("<Return>", lambda _: self._draw_reference())
        box.bind("<<ComboboxSelected>>", lambda _: self._draw_reference())
        self._label(row, "ilvl").pack(side="left", padx=(0, 6))
        self.helpers["make_entry"](row, self.ilvl, 4).pack(side="left", padx=(0, 12), ipady=3)
        self._button(row, self.t("Показать"), self._draw_reference, True).pack(side="left", padx=(0, 12))
        self._label(row, self.t("Поиск")).pack(side="left", padx=(0, 6))
        self.helpers["make_entry"](row, self.fields["search"]).pack(side="left", fill="x", expand=True, ipady=4)
        self.reference_note = self._label(self._row(8), self.t("Шанс показан для пустой стороны предмета. Занятые группы модов его меняют, точный расчёт делает вкладка «Крафт»."), wrap=860)
        self.reference_note.pack(anchor="w")
        self._draw_reference()

    def _after_search(self) -> None:
        window = self.canvas.winfo_toplevel()
        if self.search_job:
            window.after_cancel(self.search_job)
        self.search_job = window.after(RESIZE_SETTLE_MS, self._search_settled)

    def _search_settled(self) -> None:
        self.search_job = None
        if self.tab == "reference" and self.canvas.winfo_exists():
            self._draw_reference()

    def _draw_reference(self) -> None:
        db = self.helpers["db"]()
        wanted = self.fields["base"].get().strip()
        if not db or not wanted:
            return self.board.show([self._message_line(self.t("Выберите базу: покажу все её моды, уровни, веса и шансы, эссенции и знамения."))])
        try:
            base = db.find_base(wanted)
            ilvl = int(self.ilvl.get())
        except ValueError as error:
            return self.board.show([self._message_line(str(error))])
        page = db.pages.get(db.bases[base]["page"])
        if not page:
            return self.board.show([self._message_line(self.t("Для этой базы нет модов"))])
        query = self.fields["search"].get().strip()
        lines = []
        for side, title in self.SIDE_TITLES:
            lines.extend(self._side_lines(page, ilvl, side, self.t(title), query))
        lines.extend(self._desecrated_lines(page, ilvl, query))
        lines.extend(self._essence_lines(page, ilvl, query))
        lines.extend(self._omen_lines(query))
        self.board.show(lines or [self._message_line(self.t("Ничего не найдено"))])

    def _heading(self, text: str) -> Line:
        return Line([Cell(10, text, self.colors["accent"], 11, True)], height=30)

    def _side_lines(self, page, ilvl: int, side: str, title: str, query: str) -> list[Line]:
        colors = self.colors
        lines = []
        for ladder, share, tiers in mod_table(page, ilvl, side):
            texts = [mod.shown_text for _, mod, _ in tiers]
            if query and not any(self.helpers["matches"](query, text) for text in texts):
                continue
            lines.append(Line([Cell(10, ladder.title, colors["text"], 10, True, wrap=True), Cell(-12, f"{share:.1%}" if page.weights_known else "?", colors["soft"], 9, True, "e")], colors["panel"], 28))
            for tier, mod, tier_share in tiers:
                lines.append(Line([Cell(22, f"T{tier}", colors["accent"], 9, True), Cell(60, self.t("ур. {level}").format(level=mod.level), colors["muted"]), Cell(170, str(mod.weight) if mod.weight_known else "?", colors["muted"], 9, False, "e"), Cell(230, f"{tier_share:.2%}" if page.weights_known else "?", colors["soft"], 9, False, "e"),
                                   Cell(246, mod.shown_text, colors["soft"], wrap=True)], height=22, gap=0))
        return [self._heading(title), *lines] if lines else []

    def _desecrated_lines(self, page, ilvl: int, query: str) -> list[Line]:
        """Their real weights are unknown, so only the levels are shown."""
        colors = self.colors
        lines = []
        for ladder in page.desecrated_ladders:
            for number, mod in enumerate(ladder.mods, 1):
                if mod.level <= ilvl and (not query or self.helpers["matches"](query, mod.shown_text)):
                    side = self.t("префикс") if mod.side == "prefix" else self.t("суффикс")
                    lines.append(Line([Cell(22, f"T{number}", colors["accent"], 9, True), Cell(60, self.t("ур. {level}").format(level=mod.level), colors["muted"]), Cell(130, side, colors["muted"]), Cell(246, mod.shown_text, colors["soft"], wrap=True)], colors["panel"], 24))
        return [self._heading(self.t("Очернённые моды")), *lines] if lines else []

    def _essence_lines(self, page, ilvl: int, query: str) -> list[Line]:
        colors = self.colors
        lines = []
        for essence in sorted(page.essences, key=lambda found: (found.side, found.level)):
            shown = self.helpers["show_currency"](essence.name)
            text = self.helpers["essence_text"](essence)
            if essence.level > ilvl or (query and not self.helpers["matches"](query, f"{shown} {text}")):
                continue
            price = self.helpers["price_of"](essence.name)
            icon = self.helpers["icon"](essence.name, 24)
            side = self.t("префикс") if essence.side == "prefix" else self.t("суффикс")
            cells = [Cell(10, image=icon)] if icon else []
            lines.append(Line([*cells, Cell(42, shown, colors["text"], 9, True), Cell(320, side, colors["muted"]), Cell(390, text, colors["soft"], wrap=True), Cell(-12, price, colors["soft"], 9, True, "e")], colors["panel"], 30))
        return [self._heading(self.t("Эссенции")), *lines] if lines else []

    def _omen_lines(self, query: str) -> list[Line]:
        colors = self.colors
        lines = []
        for name, text in self.helpers["omens"]():
            shown = self.helpers["show_currency"](name)
            if query and not self.helpers["matches"](query, f"{shown} {text}"):
                continue
            icon = self.helpers["icon"](name, 24)
            cells = [Cell(10, image=icon)] if icon else []
            lines.append(Line([*cells, Cell(42, shown, colors["text"], 9, True), Cell(320, text, colors["soft"], wrap=True), Cell(-12, self.helpers["price_of"](name), colors["soft"], 9, True, "e")], colors["panel"], 30))
        return [self._heading(self.t("Знамения")), *lines] if lines else []

    # ---- Waystones
    def _render_waystones(self) -> None:
        waystones = self.helpers["waystones"]()
        if not waystones.get("kinds"):
            return self.board.show([self._message_line(self.t("Список модов путевых камней ещё не загружен"))])
        self.search_text = tk.StringVar()
        row = self._row()
        self._label(row, self.t("Строка для поиска")).pack(side="left", padx=(0, 6))
        self.helpers["make_entry"](row, self.search_text).pack(side="left", fill="x", expand=True, ipady=4)
        self._button(row, self.t("Скопировать"), self._copy_search, True).pack(side="left", padx=(8, 0))
        self._button(row, self.t("Сбросить список"), self._reset_dangers).pack(side="left", padx=(6, 0))
        self.search_note = self._label(self._row(), "", wrap=860)
        self.search_note.pack(anchor="w")
        self._note(self.t("Нажмите на мод, чтобы отметить его опасным. Строка в поиске тайника скрывает камни с такими модами, а окно цены предупредит о них. Синтаксис поиска взят из гайдов: проверьте на паре камней."))
        self._draw_waystones()

    def _dangers(self) -> set[str]:
        return danger_keys(self.store.get("waystone_danger"), self.helpers["waystones"]().get("kinds", []))

    def _toggle_danger(self, key: str) -> None:
        self.store["waystone_danger"] = sorted(self._dangers() ^ {key})
        self._save()
        self._draw_waystones(to_top=False)

    def _reset_dangers(self) -> None:
        self.store.pop("waystone_danger", None)
        self._save()
        self._draw_waystones(to_top=False)

    def _copy_search(self) -> None:
        if self.search_text.get():
            self.helpers["copy"](self.search_text.get())
            self.search_note.config(text=self.t("Скопировано: вставьте в поиск тайника в игре"), fg=self.colors["up"])

    def _draw_waystones(self, to_top: bool = True) -> None:
        colors = self.colors
        waystones = self.helpers["waystones"]()
        code = self.helpers["language"]()
        fragments = waystone_fragments(waystones, code)
        danger = self._dangers()
        kinds = waystones["kinds"]
        search = exclusion_search([fragments[kind["key"]] for kind in kinds if kind["key"] in danger])
        self.search_text.set(search)
        unusable = [kind for kind in kinds if kind["key"] in danger and not fragments[kind["key"]]]
        note, color = self.t("Длина строки: {length} из {limit}").format(length=len(search), limit=LONGEST_SEARCH), colors["muted"]
        if len(search) > LONGEST_SEARCH:
            note, color = self.t("Длина строки {length}: игра может не принять больше {limit}, уберите часть модов").format(length=len(search), limit=LONGEST_SEARCH), colors["down"]
        elif unusable:
            note, color = self.t("Модов без короткого слова для поиска: {count}, их строка не скроет").format(count=len(unusable)), colors["accent"]
        self.search_note.config(text=note, fg=color)
        lines = []
        for side, title in self.SIDE_TITLES:
            lines.append(self._heading(self.t(title)))
            for kind in sorted((kind for kind in kinds if kind["side"] == side), key=lambda found: found["key"] not in danger):
                active = kind["key"] in danger
                text = (kind["ru"] if code == "ru" else kind["key"]).replace("#", "X")
                lines.append(Line([Cell(10, "●" if active else "○", colors["down"] if active else colors["muted"], 10), Cell(32, text, colors["text"] if active else colors["soft"], 10, active, wrap=True)],
                                  colors["panel"], 28, command=lambda key=kind["key"]: self._toggle_danger(key)))
        self.board.show(lines, to_top)

    # ---- map timer
    def _render_timer(self) -> None:
        colors = self.colors
        self.timer_label = tk.Label(self._row(4), text="", bg=colors["background"], fg=colors["text"], font=(TITLE_FONT, 38, "bold"))
        self.timer_label.pack(anchor="w")
        row = self._row(6)
        self.timer_toggle = self._button(row, "", self._toggle_timer, True)
        self.timer_toggle.pack(side="left", padx=(0, 6))
        self._button(row, self.t("Новая карта"), self._lap).pack(side="left", padx=(0, 6))
        self._button(row, self.t("Сбросить"), self._reset_timer).pack(side="left")
        self.timer_average = self._label(row, "", colors["soft"], 10)
        self.timer_average.pack(side="left", padx=(16, 0))
        self._note(self.t("Секундомер ручной: программа не читает игру, поэтому карты отмечаете вы."))
        self._draw_laps()
        self._tick_timer()

    def _toggle_timer(self) -> None:
        self.stopwatch.toggle()
        self._paint_toggle()
        self._tick_timer()

    def _lap(self) -> None:
        self.stopwatch.lap()
        self._draw_laps()
        self._paint_clock()

    def _reset_timer(self) -> None:
        self.stopwatch.reset()
        self._draw_laps()
        self._paint_clock()
        self._paint_toggle()

    def _paint_toggle(self) -> None:
        self.timer_toggle.config(text=self.t("Пауза") if self.stopwatch.running else self.t("Старт"))

    def _paint_clock(self) -> None:
        shown = format_time(self.stopwatch.elapsed)
        if self.timer_label.cget("text") != shown:  # it changes once a second, so most ticks draw nothing
            self.timer_label.config(text=shown)

    def _tick_timer(self) -> None:
        """Keeps going while the window is hidden or another tab is open, and stops with the timer's own page.
        It must not ask whether it is on screen: right after a tab opens, the answer is still no, and the clock would stay frozen."""
        if not self.canvas.winfo_exists():  # a change of language rebuilt the page; the new one has its own tick
            return
        window = self.canvas.winfo_toplevel()
        if self.timer_tick_job:
            window.after_cancel(self.timer_tick_job)
            self.timer_tick_job = None
        if not self.timer_label.winfo_exists():
            return
        self._paint_clock()
        self._paint_toggle()
        if self.stopwatch.running:
            self.timer_tick_job = window.after(self.TIMER_TICK_MS, self._tick_timer)

    def _draw_laps(self) -> None:
        colors = self.colors
        laps = self.stopwatch.laps
        average = self.stopwatch.average
        self.timer_average.config(text=self.t("В среднем {time} за карту").format(time=format_time(average)) if average is not None else "")
        if not laps:
            return self.board.show([self._message_line(self.t("Пройденные карты появятся здесь"))])
        self.board.show([Line([Cell(10, self.t("Карта {number}").format(number=number), colors["soft"]), Cell(-12, format_time(seconds), colors["text"], 10, True, "e")], colors["panel"], 28)
                         for number, seconds in reversed(list(enumerate(laps, 1)))])
