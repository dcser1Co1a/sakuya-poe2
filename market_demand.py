"""Hot items: what the market buys and sells.

Unique items come from poe2scout's public API (https://api.poe2scout.com/swagger): prices, listings and a week
of history. No open source says what builds wear: poe.ninja closes its builds API to other programs and GGG's
ladder holds no items. So demand here is an estimate from the market itself: the price climbs while listings shrink.
"""
import json
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta

from sakura import BODY, CardWave, paper_image, paper_variant, wave_delay
from price_check import UNIT_LABELS, add_mod_text, baked_card, draw_change, spark_image
from trade_search import MARKUP

NINJA_API = "https://poe.ninja/poe2/api/"
SCOUT_API = "https://api.poe2scout.com/poe2/"
SOURCE = "poe2scout"
BUILD_GUIDES = "https://mobalytics.gg/poe-2/builds"
APP_USER_AGENT = "sakuya/1.0 (+https://github.com/dcser1Co1a/sakuya-poe2)"  # poe.ninja and poe2scout ask for the program's name and a contact
UPDATE_INTERVAL = timedelta(hours=1)
REQUEST_GAP_SECONDS = 3
ITEMS_PER_PAGE = 250  # the most poe2scout gives at once
UNFINISHED_ITEM = "INCOMPLETE"  # a placeholder in poe2scout's list, not a real unique
FEWEST_LISTINGS_FOR_A_MARKET = 5
FEWEST_LISTINGS_FOR_DEMAND = 20  # below this a single sale looks like a stampede
DEMAND_STEP = 15  # how far the estimate must move, in points, to count as rising or falling
LARGEST_CHANGE = 100  # one wild week must not outweigh everything else
CURRENCY_TAB, ALL_TAB = "currency", "all"
CURRENCY_ROWS_SHOWN = 100
UNIQUE_KINDS = ["accessory", "armour", "weapon", "jewel", "flask", "map", "sanctum"]  # poe2scout's list of categories can add to these while the program runs
LEARNED_UNIQUE_TITLES: dict[str, str] = {}
ROW_HEIGHT, ROW_GAP = 60, 5
SETTLE_MS = 60  # the mods card has laid itself out by then
MOST_PAGES = 20  # a reply naming more than any category has must not turn into a long run of requests
DRAWN_AT_ONCE = 16 # more than a tall window shows, so a tab never opens half empty
DRAW_TURN_SECONDS = 0.012  # short enough that the window keeps answering between turns
SPARK_WIDTH, SPARK_HEIGHT = 96, 28


def fetch_overview(url: str, etag: str | None, opener=urllib.request.urlopen) -> tuple[dict | None, str | None]:
    """Asks only for data that changed. None means the saved copy is still current."""
    headers = {"User-Agent": APP_USER_AGENT, "Accept": "application/json"}
    if etag:
        headers["If-None-Match"] = etag
    try:
        with opener(urllib.request.Request(url, headers=headers), timeout=60) as response:
            answer = json.loads(response.read())
            if not isinstance(answer, dict):
                raise ValueError("the reply is not a JSON object")
            return answer, response.headers.get("ETag")
    except urllib.error.HTTPError as error:
        if error.code == 304:
            return None, etag
        raise


def percent_change(values: list[float]) -> float | None:
    return (values[-1] / values[0] - 1) * 100 if len(values) >= 2 and values[0] else None


def demand_score(price_change: float | None, listings_change: float | None) -> float | None:
    """Points of estimated demand: a rising price and shrinking listings both add to it."""
    if price_change is None or listings_change is None:
        return None
    limit = lambda value: max(min(value, LARGEST_CHANGE), -LARGEST_CHANGE)
    return limit(price_change) - limit(listings_change)


def read_unique(item: dict, exalted_per_divine: float, kind: str) -> dict | None:
    """One line of poe2scout. It prices in Exalted Orbs, while the program counts in Divine."""
    if not item.get("Name") or item.get("Name") == UNFINISHED_ITEM or item.get("CurrentPrice") is None:
        return None
    logs = sorted((log for log in item.get("PriceLogs") or [] if log and log.get("Price") and log.get("Quantity")), key=lambda log: log["Time"])
    prices = [log["Price"] / exalted_per_divine for log in logs]
    details = item.get("ItemMetadata") or {}
    mods = [*(details.get("implicit_mods") or []), *(details.get("explicit_mods") or [])]
    return {"kind": kind, "base": item.get("Type") or details.get("base_type") or "", "price": item["CurrentPrice"] / exalted_per_divine, "listings": item.get("CurrentQuantity") or 0,
            "change": percent_change(prices), "listings_change": percent_change([log["Quantity"] for log in logs]), "spark": prices, "mods": [MARKUP.sub(r"\1", str(mod)) for mod in mods], "icon": item.get("IconUrl") or details.get("icon") or ""}


def merge_items(stored: dict, lines: list[dict] | None, kind: str, etag: str | None, stamp: str, exalted_per_divine: float) -> dict:
    """Replaces one kind's items. None means nothing changed. Of several versions of a unique the most listed one stays."""
    result = {**stored, "updated": {**stored.get("updated", {}), kind: stamp}, "etags": {**stored.get("etags", {}), kind: etag}}
    if lines is None:
        return result
    best: dict[str, dict] = {}
    for line in lines:
        try:
            item = read_unique(line, exalted_per_divine, kind)
        except (AttributeError, KeyError, TypeError, ValueError, ZeroDivisionError):  # one odd line must not cost the others
            continue
        if item and item["price"] > 0 and (line["Name"] not in best or item["listings"] > best[line["Name"]]["listings"]):
            best[line["Name"]] = item
    if not best and any(item["kind"] == kind for item in stored.get("items", {}).values()):
        return result  # a reply with nothing usable is a bad reply, and the saved items are better than none
    result["items"] = {**{name: item for name, item in stored.get("items", {}).items() if item["kind"] != kind}, **best}
    return result


def read_categories(answer: dict) -> tuple[list[list[str]], list[list[str]]]:
    """poe2scout's own list of what it sells, as (name, title) of uniques and of currency."""
    def pairs(key):
        lines = answer.get(key)
        return [[line["ApiId"], line["Label"] if isinstance(line.get("Label"), str) else line["ApiId"]] for line in lines if isinstance(line, dict) and isinstance(line.get("ApiId"), str)] if isinstance(lines, list) else []

    return pairs("UniqueCategories"), pairs("CurrencyCategories")


def learn_unique_kinds(categories: list[list[str]]) -> list[str]:
    """A category nobody has heard of is taken in as it is, so a new kind of unique reaches the list with its league. Returns the new ones."""
    tabs = {key for key, _ in DemandPage.TABS}
    new = []
    for name, title in categories:
        if name not in UNIQUE_KINDS:
            UNIQUE_KINDS.append(name)
            new.append(name)
        if name not in tabs:
            LEARNED_UNIQUE_TITLES[name] = title
    return new


def kinds_due(stored: dict, wanted=UNIQUE_KINDS, now: datetime | None = None) -> list[str]:
    """The wanted kinds that are at least an hour old. Update times live in the file, so a restart causes no extra requests."""
    now = now or datetime.now()
    updated = stored.get("updated", {}) if stored.get("source") == SOURCE else {}
    return [kind for kind in wanted if kind not in updated or now - datetime.fromisoformat(updated[kind]) > UPDATE_INTERVAL]


def update_demand(stored: dict, league: str, exalted_per_divine: float, save, on_changed, wanted=UNIQUE_KINDS, opener=urllib.request.urlopen, sleep=time.sleep) -> dict:
    """One request at a time without retries, saving after each kind."""
    if stored.get("league") != league or stored.get("source") != SOURCE:
        stored = {"league": league, "source": SOURCE, "items": {}, "updated": {}, "etags": {}}
    address = f"{SCOUT_API}Leagues/{urllib.parse.quote(league)}/Uniques/ByCategory"
    for kind in kinds_due(stored, wanted):
        query = {"category": kind, "perPage": ITEMS_PER_PAGE}
        page, etag = fetch_overview(f"{address}?{urllib.parse.urlencode(query)}", stored.get("etags", {}).get(kind), opener)
        lines = None
        if page is not None:
            if not isinstance(page.get("Items"), list):
                raise ValueError("poe2scout sent no list of items")
            lines = list(page["Items"])
            pages = page.get("Pages")
            for number in range(2, min(pages if isinstance(pages, int) else 1, MOST_PAGES) + 1):
                sleep(REQUEST_GAP_SECONDS)
                more, _ = fetch_overview(f"{address}?{urllib.parse.urlencode({**query, 'page': number})}", None, opener)
                if isinstance((more or {}).get("Items"), list):
                    lines += more["Items"]
        stored = merge_items(stored, lines, kind, etag, datetime.now().isoformat(timespec="seconds"), exalted_per_divine)
        save(stored)
        on_changed()
        sleep(REQUEST_GAP_SECONDS)
    return stored


# ------------------------------------------------------------------- what to show
@dataclass(frozen=True)
class DemandRow:
    name: str
    shown: str
    base: str
    price: float
    amount: float | None  # listings of a unique, traded volume of currency
    is_volume: bool
    change: float | None
    listings_change: float | None
    spark: tuple
    mods: tuple[str, ...]

    @property
    def market(self) -> float:
        """The size of the market: for a unique, what all its listings are worth. A lone listing can ask any price, so it is no market."""
        if not self.is_volume and (self.amount or 0) < FEWEST_LISTINGS_FOR_A_MARKET:
            return 0
        return (self.amount or 0) * (1 if self.is_volume else self.price)

    @property
    def demand(self) -> float | None:
        return demand_score(self.change, self.listings_change) if (self.amount or 0) >= FEWEST_LISTINGS_FOR_DEMAND else None

    @property
    def demand_word(self) -> str | None:
        if self.demand is None:
            return None
        return "высокий" if self.demand >= DEMAND_STEP else "низкий" if self.demand <= -DEMAND_STEP else "средний"


SORT_VALUES = {"demand": lambda row: row.demand, "market": lambda row: row.market or None, "price": lambda row: row.price if row.is_volume or row.market else None,
               "amount": lambda row: row.amount, "change": lambda row: row.change, "name": lambda row: row.shown.casefold()}


def demand_rows(demand: dict, prices: dict, tab: str, query: str, sort: str, show_unique, show_currency, matches, descending: bool = True) -> list[DemandRow]:
    rows = []
    if tab == CURRENCY_TAB:
        volumes = prices.get("volumes", {})
        ranked = sorted(prices.get("prices_in_divine", {}), key=lambda name: -(volumes.get(name) or 0))[:CURRENCY_ROWS_SHOWN]
        for name in ranked:
            rows.append(DemandRow(name, show_currency(name), "", prices["prices_in_divine"][name], volumes.get(name), True,
                                  prices.get("changes", {}).get(name), None, tuple(prices.get("sparklines", {}).get(name) or ()), ()))
    else:
        for name, item in demand.get("items", {}).items():
            if tab in (ALL_TAB, item["kind"]):
                rows.append(DemandRow(name, show_unique(name), item["base"], item["price"], item["listings"], False, item.get("change"), item.get("listings_change"), tuple(item.get("spark") or ()), tuple(item.get("mods") or ())))
    rows = [row for row in rows if matches(query, f"{row.name} {row.shown} {row.base}")]
    # Rows with nothing to compare stay at the end whichever way the column is sorted.
    value = SORT_VALUES[sort]
    known = sorted((row for row in rows if value(row) is not None), key=value, reverse=descending)
    return known + sorted((row for row in rows if value(row) is None), key=lambda row: -row.market)


class DemandPage:
    """The «hot items» tab. One canvas draws all rows, like the price tab."""
    TABS = ((ALL_TAB, "Все"), ("accessory", "Бижутерия"), ("armour", "Броня"), ("weapon", "Оружие"), ("jewel", "Самоцветы"), ("flask", "Флаконы"), ("map", "Карты"), ("sanctum", "Санктум"), (CURRENCY_TAB, "Валюта"))
    SORTS = (("demand", "По спросу"), ("market", "По рынку"), ("price", "По цене"))

    def __init__(self, parent, colors: dict[str, str], translate, tools: dict):
        self.colors = colors
        self.t = translate
        self.tools = tools  # helpers of the main window: names, icons, number formats, actions
        self.tab, self.sort, self.descending = ALL_TAB, "demand", True
        self.header_zones: list[tuple[float, float, str]] = []
        self.drawn_width: int | None = None
        self.detail_shown: str | None = None
        self.rows: list[DemandRow] = []
        self.selected = self.hovered = None
        self.drawn_key = self.draw_job = self.wave = None
        self.quiet_next = False  # the next drawing happens out of sight, so a wave would be wasted
        page = tk.Frame(parent, bg=colors["background"], padx=10)
        page.pack(fill="both", expand=True)
        top = tk.Frame(page, bg=colors["background"])
        top.pack(fill="x", pady=(0, 6))
        self._button(top, self.t("Гайды по билдам"), tools["open_guides"]).pack(side="right")
        self.subtitle = tk.Label(top, bg=colors["background"], fg=colors["muted"], font=(BODY, 9), anchor="w")
        self.subtitle.pack(anchor="w")
        tk.Label(top, text=self.t("Спрос это оценка: цена растёт, а объявлений становится меньше. Что носят билды, открытые данные не показывают."), bg=colors["background"], fg=colors["muted"], font=(BODY, 9), anchor="w").pack(anchor="w")
        tabs = tk.Frame(page, bg=colors["background"])
        tabs.pack(fill="x", pady=(0, 6))
        self.tab_buttons = {}
        for column, (key, title) in enumerate((*self.TABS[:-1], *LEARNED_UNIQUE_TITLES.items(), self.TABS[-1])):
            tabs.columnconfigure(column, weight=1, uniform="demand")
            button = self._button(tabs, self.t(title), lambda k=key: self.set_tab(k))
            button.grid(row=0, column=column, sticky="ew", padx=(0, 4))
            self.tab_buttons[key] = button
        bar = tk.Frame(page, bg=colors["background"])
        bar.pack(fill="x", pady=(0, 6))
        tk.Label(bar, text=self.t("Поиск"), bg=colors["background"], fg=colors["muted"], font=(BODY, 9)).pack(side="left", padx=(0, 8))
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.tools["after_typing"](lambda: self.render(True)))
        self.tools["make_entry"](bar, self.search).pack(side="left", fill="x", expand=True, ipady=5)
        self.sort_buttons = {}
        for key, title in self.SORTS:
            button = self._button(bar, self.t(title), lambda k=key: self.set_sort(k))
            button.pack(side="left", padx=(6, 0))
            self.sort_buttons[key] = button
        self.header = tk.Canvas(page, height=20, bg=colors["background"], highlightthickness=0, bd=0)
        self.header.pack(fill="x", padx=(0, 11))
        self.header.bind("<Button-1>", self._on_header_click)
        self.header.bind("<Motion>", lambda event: self.header.config(cursor="hand2" if self._zone_at(event.x) else ""))
        self.detail = tk.Frame(page, bg=colors["background"])
        holder = self.list_holder = tk.Frame(page, bg=colors["background"])
        holder.pack(fill="both", expand=True)
        holder.columnconfigure(0, weight=1)
        holder.columnconfigure(1, minsize=11)
        holder.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(holder, bg=colors["background"], highlightthickness=0, bd=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        tools["enable_scrolling"](holder, self.canvas)
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda _: self._hover(None))
        self.canvas.bind("<Button-1>", self._on_click, add="+")

    def _button(self, parent, text: str, command) -> tk.Button:
        colors = self.colors
        return tk.Button(parent, text=text, command=command, relief="flat", bd=0, cursor="hand2", padx=10, pady=4, bg=colors["panel"], fg=colors["soft"],
                         activebackground=colors["raised"], activeforeground=colors["text"], font=(BODY, 9))

    def _on_resize(self, event) -> None:
        """A new height only shows more or less of the same rows. Redrawing then would make the mods card and the list chase each other."""
        if event.width != self.drawn_width:
            self.drawn_width = event.width
            if self.drawn_key:  # a page nobody has opened yet draws when it is opened: its hundreds of rows would be work for no one
                self.tools["after_typing"](self.render)

    def kinds_on_screen(self) -> tuple[str, ...]:
        """Only what the player is looking at gets refreshed."""
        return UNIQUE_KINDS if self.tab == ALL_TAB else () if self.tab == CURRENCY_TAB else (self.tab,)

    def set_tab(self, key: str) -> None:
        self.tab, self.selected = key, None
        self.render(True)

    def set_sort(self, key: str) -> None:
        """A click on the chosen column flips it between high to low and low to high."""
        self.descending = not self.descending if key == self.sort else key != "name"
        self.sort = key
        self.render(True)

    def _zone_at(self, x: int) -> str | None:
        return next((key for left, right, key in self.header_zones if left <= x <= right), None)

    def _on_header_click(self, event) -> None:
        key = self._zone_at(event.x)
        if key:
            self.set_sort(key)

    def _columns(self, width: int) -> dict[str, int]:
        change = width - 12
        graph = change - 62 - SPARK_WIDTH
        amount = graph - 18
        price = amount - 84
        demand = price - 128
        return {"change": change, "graph": graph, "amount": amount, "price": price, "demand": demand, "name": 72}

    def render(self, to_top: bool = False, force: bool = False) -> None:
        """Coming back to an unchanged list draws nothing. force is for what the key cannot see: pictures that have just arrived."""
        colors, tools = self.colors, self.tools
        demand, prices = tools["demand"](), tools["prices"]() or {}
        width = max(self.canvas.winfo_width(), 400)
        key = (self.tab, self.sort, self.descending, self.search.get(), width, str(demand.get("updated")), str(prices.get("updated")), self.t("Поиск"))
        if key == self.drawn_key and not force:
            if to_top:
                self.canvas.yview_moveto(0)
            return
        wave = (not self.drawn_key or key[:3] != self.drawn_key[:3]) and not self.quiet_next  # a new tab or order comes in as a wave; a search or a quiet refresh just appears
        self.drawn_key, self.quiet_next = key, False
        if self.wave:
            self.wave.stop()
            self.wave = None
        for buttons, chosen in ((self.tab_buttons, self.tab), (self.sort_buttons, self.sort)):
            for key, button in buttons.items():
                active = key == chosen
                button.config(bg=colors["selected"] if active else colors["panel"], fg=colors["on_selected"] if active else colors["soft"], font=(BODY, 9, "bold" if active else "normal"))
        for key, title in self.SORTS:
            self.sort_buttons[key].config(text=self.t(title) + self._arrow(key))
        stamps = demand.get("updated", {}).values()
        self.subtitle.config(text=self.t("{league}  •  обновлено {time}  •  обновляется при просмотре, не чаще раза в час").format(league=demand.get("league", ""), time=max(stamps)[11:16]) if stamps else self.t("Данные придут при следующем обновлении"))
        self.rows = demand_rows(demand, prices, self.tab, self.search.get(), self.sort, tools["show_unique"], tools["show_currency"], tools["matches"], self.descending)
        canvas = self.canvas
        canvas.delete("all")
        self.hovered = None
        self.graphs = []
        columns = self._columns(width)
        self._draw_header(columns)
        if wave and self.rows and canvas.winfo_viewable():
            canvas.yview_moveto(0)
            self._start_wave(width, columns)
        else:
            self._draw_rows_from(0, width, columns)
        if not self.rows:
            none_here = demand.get("updated") and not demand.get("items") and not self.search.get()
            canvas.create_text(12, 20, text=self.t("В этой лиге сайт не считает уникальные предметы, цены валюты есть" if none_here else "Ничего не найдено"), fill=colors["muted"], font=(BODY, 10), anchor="w")
        canvas.configure(scrollregion=(0, 0, width, max(len(self.rows) * (ROW_HEIGHT + ROW_GAP), 1)))
        if to_top:
            canvas.yview_moveto(0)
        if not any(row.name == self.selected for row in self.rows):
            self.selected = None
        if self.detail_shown != self.selected:
            self._show_detail()

    def stop_drawing(self) -> None:
        if self.draw_job:
            self.canvas.winfo_toplevel().after_cancel(self.draw_job)
            self.draw_job = None

    def pause_drawing(self):
        """Stops the rows still to come and returns what starts them again."""
        waiting = self.draw_waiting if self.draw_job else None
        self.stop_drawing()
        return (lambda: self._draw_rows_from(*waiting)) if waiting else (lambda: None)

    def _start_wave(self, width: int, columns: dict[str, int]) -> None:
        """The rows on screen ride the wave, and the rest are drawn behind it in short turns."""
        window = self.canvas.winfo_toplevel()
        if self.draw_job:
            window.after_cancel(self.draw_job)
            self.draw_job = None
        step = ROW_HEIGHT + ROW_GAP
        on_screen = min(self.canvas.winfo_height() // step + 1, len(self.rows))
        boxes = [(0, number * step, width, number * step + ROW_HEIGHT, wave_delay(0, number)) for number in range(on_screen)]
        rows, colors = self.rows, self.colors
        self.wave = CardWave(self.canvas, boxes, lambda number: self._draw_row(number, rows[number], width, columns, baked=True), colors["panel"], colors["border"],
                             lambda: self._draw_rows_from(on_screen, width, columns) if on_screen < len(rows) else None)

    def _draw_rows_from(self, first: int, width: int, columns: dict[str, int]) -> None:
        """Hundreds of rows would stop the window for seconds the first time, so they are drawn in short turns, the visible ones first.
        Each row's place is fixed, so scrolling works before the last one is drawn."""
        if not self.canvas.winfo_exists():  # a change of language rebuilt the page
            return
        window = self.canvas.winfo_toplevel()
        if self.draw_job:
            window.after_cancel(self.draw_job)
            self.draw_job = None
        started = time.perf_counter()
        number = first
        while number < len(self.rows) and (number == first or number < DRAWN_AT_ONCE or time.perf_counter() - started < DRAW_TURN_SECONDS):  # every turn draws at least one, so the list always finishes
            self._draw_row(number, self.rows[number], width, columns)
            number += 1
        if number < len(self.rows):
            self.draw_waiting = number, width, columns
            self.draw_job = window.after_idle(self._draw_rows_later, window, number, width, columns)

    def _draw_rows_later(self, window, number: int, width: int, columns: dict[str, int]) -> None:
        """Runs once the last turn is on screen. Tk redraws only when no timer is due, so a turn that simply set its timer would keep the window from showing anything until the last row."""
        self.draw_job = window.after(1, self._draw_rows_from, number, width, columns)

    def _arrow(self, key: str) -> str:
        return (" ▼" if self.descending else " ▲") if key == self.sort else ""

    def _draw_header(self, columns: dict[str, int]) -> None:
        self.header.delete("all")
        self.header_zones = []
        amount = "Объём" if self.tab == CURRENCY_TAB else "Лотов"
        for key, x, title, anchor in (("name", columns["name"], "Предмет", "w"), ("demand", columns["demand"], "Спрос", "e"), ("price", columns["price"], "Цена ≈", "e"), ("amount", columns["amount"], amount, "e"), ("change", columns["change"], "Неделя", "e")):
            active = key == self.sort
            item = self.header.create_text(x, 9, text=self.t(title) + self._arrow(key), fill=self.colors["accent"] if active else self.colors["muted"], font=(BODY, 9, "bold" if active else "normal"), anchor=anchor)
            left, _, right, _ = self.header.bbox(item)
            self.header_zones.append((left - 6, right + 6, key))
        self.header.create_text(columns["graph"], 9, text=self.t("История"), fill=self.colors["muted"], font=(BODY, 9), anchor="w")

    def _draw_row(self, number: int, row: DemandRow, width: int, columns: dict[str, int], baked: bool = False) -> None:
        """baked is for the rows riding the wave. It costs a full sheet per row, which is too much memory for hundreds of them, so those behind the wave stay in parts."""
        canvas, colors, tools = self.canvas, self.colors, self.tools
        top = number * (ROW_HEIGHT + ROW_GAP)
        middle = top + ROW_HEIGHT // 2
        active = row.name == self.selected
        variant = paper_variant(row.name)
        shown, unit_name = tools["price"](row.price, row.name if row.is_volume else None)
        color = colors["muted"] if not row.change else colors["up"] if row.change > 0 else colors["down"]
        if baked:
            sheet = baked_card(width, ROW_HEIGHT, variant, (6, 4, 58, 56, colors["tile"], colors["border"]),
                               ((tools["stored_icon"](row.name, row.is_volume), 32, ROW_HEIGHT // 2, 1), (tools["stored_icon"](unit_name, True), columns["price"] - 12, ROW_HEIGHT // 2, 2)),
                               (list(row.spark), SPARK_WIDTH, SPARK_HEIGHT, color, columns["graph"], (ROW_HEIGHT - SPARK_HEIGHT) // 2))
            self.graphs.append(sheet)
            canvas.create_image(0, top, image=sheet, anchor="nw")
        else:
            canvas.create_image(0, top, image=paper_image(width, ROW_HEIGHT, variant), anchor="nw")
            canvas.create_rectangle(6, top + 4, 58, top + 56, fill=colors["tile"], outline=colors["border"])
            icon = tools["icon"](row.name, row.is_volume, tile=True)
            if icon:
                canvas.create_image(32, middle, image=icon)
            unit = tools["icon"](unit_name, True, 24)
            if unit:
                canvas.create_image(columns["price"] - 12, middle, image=unit)
            graph = spark_image(list(row.spark), SPARK_WIDTH, SPARK_HEIGHT, color, (width, ROW_HEIGHT, variant, columns["graph"], (ROW_HEIGHT - SPARK_HEIGHT) // 2))
            if graph:
                self.graphs.append(graph)
                canvas.create_image(columns["graph"], middle, image=graph, anchor="w")
        canvas.create_rectangle(1, top, width - 1, top + ROW_HEIGHT - 1, fill="", outline=colors["accent"] if active else colors["border"], width=2 if active else 1, tags=(f"card{number}",))
        if row.base:
            canvas.create_text(columns["name"], middle - 9, text=row.shown, fill=colors["text"], font=(BODY, 10, "bold"), anchor="w")
            canvas.create_text(columns["name"], middle + 10, text=row.base, fill=colors["muted"], font=(BODY, 9), anchor="w")
        else:
            canvas.create_text(columns["name"], middle, text=row.shown, fill=colors["text"], font=(BODY, 10, "bold"), anchor="w")
        word = row.demand_word
        canvas.create_text(columns["demand"], middle, text=self.t(word) if word else "—", fill={"высокий": colors["hot"], "низкий": colors["muted"], "средний": colors["soft"]}.get(word, colors["muted"]),
                           font=(BODY, 10, "bold" if word == "высокий" else "normal"), anchor="e")
        canvas.create_text(columns["price"] - 28, middle, text=shown, fill=colors["text"], font=(BODY, 10, "bold"), anchor="e")
        if row.amount is not None:
            canvas.create_text(columns["amount"], middle, text=tools["format_price"](row.amount), fill=colors["soft"], font=(BODY, 9), anchor="e")
        draw_change(canvas, columns["change"], middle, row.change, colors["up"], colors["down"], colors["soft"])

    def _row_at(self, event) -> int | None:
        y = self.canvas.canvasy(event.y)
        number = int(y // (ROW_HEIGHT + ROW_GAP))
        return number if 0 <= number < len(self.rows) and y % (ROW_HEIGHT + ROW_GAP) < ROW_HEIGHT else None

    def _on_motion(self, event) -> None:
        self._hover(self._row_at(event))

    def _hover(self, number: int | None) -> None:
        if number == self.hovered:
            return
        for old, outline in ((self.hovered, self.colors["border"]), (number, self.colors["soft"])):
            if old is not None and self.rows[old].name != self.selected:
                self.canvas.itemconfig(f"card{old}", outline=outline)
        self.hovered = number

    def _on_click(self, event) -> None:
        number = self._row_at(event)
        if number is None:
            return
        previous, self.selected = self.selected, None if self.rows[number].name == self.selected else self.rows[number].name
        # Only the two rows that changed are repainted: redrawing the whole list on a click is what made it blink.
        for position, row in enumerate(self.rows):
            if row.name == previous or row.name == self.selected:
                chosen = row.name == self.selected
                outline = "accent" if chosen else "soft" if position == self.hovered else "border"
                self.canvas.itemconfig(f"card{position}", outline=self.colors[outline], width=2 if chosen else 1)
        self._show_detail()
        self.canvas.winfo_toplevel().after(SETTLE_MS, self._keep_selected_in_view)

    def _keep_selected_in_view(self) -> None:
        """The card takes room from the list, which must not hide the row it belongs to."""
        number = next((position for position, row in enumerate(self.rows) if row.name == self.selected), None)
        if number is None or not self.rows or not self.canvas.winfo_exists():
            return
        total = len(self.rows) * (ROW_HEIGHT + ROW_GAP)
        first, last = self.canvas.yview()
        top, bottom = number * (ROW_HEIGHT + ROW_GAP) / total, (number * (ROW_HEIGHT + ROW_GAP) + ROW_HEIGHT) / total
        if top < first:
            self.canvas.yview_moveto(top)
        elif bottom > last:
            self.canvas.yview_moveto(first + bottom - last)

    def _show_detail(self) -> None:
        """The clicked item: how its market moved this week, a check against real listings, and its mods, which poe2scout writes in English."""
        colors = self.colors
        for child in self.detail.winfo_children():
            child.destroy()
        row = next((row for row in self.rows if row.name == self.selected and row.mods), None)
        self.detail_shown = row.name if row else None
        if not row:
            self.detail.pack_forget()  # an emptied frame keeps its height
            return
        self.detail.pack(side="bottom", fill="x", before=self.list_holder)
        card = tk.Frame(self.detail, bg=colors["panel"], highlightthickness=1, highlightbackground=colors["border"], padx=12, pady=8)
        card.pack(fill="x", pady=(6, 8))
        tk.Label(card, text=row.shown, bg=colors["panel"], fg=colors["unique"], font=(BODY, 11, "bold")).pack(anchor="w")
        if row.change is not None and row.listings_change is not None:
            week = self.t("За неделю: цена {price}, объявлений {listings}").format(price=f"{row.change:+.0f}%", listings=f"{row.listings_change:+.0f}%")
            tk.Label(card, text=week, bg=colors["panel"], fg=colors["soft"], font=(BODY, 9)).pack(anchor="w")
        self._button(card, self.t("Открыть на сайте торговли"), lambda: self.tools["open_on_site"](row.name, row.base)).place(relx=1, rely=0, anchor="ne")
        columns = tk.Frame(card, bg=colors["panel"])
        columns.pack(fill="x", pady=(3, 0))
        columns.columnconfigure((0, 1), weight=1, uniform="mods")
        room = max((self.canvas.winfo_width() - 40) // 2, 200)
        for number, mod in enumerate(row.mods):
            add_mod_text(columns, mod, colors["panel"], colors["soft"], colors["text"], 9, room).grid(row=number // 2, column=number % 2, sticky="w", pady=1)
