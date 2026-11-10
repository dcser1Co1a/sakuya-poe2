"""Where unique items and jewels come from: «Voices drops in the Simulacrum», «Time-Lost jewels come from a cache in the Trial of the Sekhemas».

The facts are the community wiki's (poe2wiki.net, text under CC BY-NC-SA 3.0), read through its public MediaWiki Cargo API
once a week: a few requests with the program's name and address, as the wiki asks of tools. They are shown with the
wiki named as their source, the usual wordings in Russian, and anything else as the wiki writes it.
"""
import html
import json
import re
import tkinter as tk
import urllib.parse
from dataclasses import dataclass

from sakura import BODY, trace_while
from tools import Board, Cell, Line

WIKI = "https://www.poe2wiki.net"
WIKI_API = f"{WIKI}/w/api.php"
ROWS_PER_PAGE = 500  # the most one Cargo query gives
MOST_PAGES = 6  # a reply that asks for more is a changed wiki, not a game with 3000 uniques
FIELDS = "items.name,items.base_item,items.class_id,items.rarity_id,items.drop_text,items.is_drop_restricted,items.drop_enabled,items.drop_level"
QUERIES = ('items.rarity_id="unique"', 'items.class_id="Jewel" AND items.rarity_id<>"unique"')  # every unique, and the jewel bases
KINDS = ("simulacrum", "boss", "vault", "trial", "craft", "event", "other", "world", "legacy")  # the order the list groups them in
KIND_TITLES = {"all": "Все", "special": "Особые места", "simulacrum": "Симулякр", "boss": "Боссы", "vault": "Хранилище Атзири", "trial": "Испытания",
               "craft": "Создаётся", "event": "Награды", "other": "Другое", "world": "Где угодно", "legacy": "Не падает"}
FILTERS = ("all", "special", "simulacrum", "boss", "trial", "world")
WIKI_LINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
FILE_LINK = re.compile(r"\[\[File:[^\]]*\]\]", re.IGNORECASE)
TAG = re.compile(r"<[^>]+>")
QUOTED = re.compile(r'"([^"]+)"')
LINK_TARGET = re.compile(r"\[\[(?!File:)([^\]|#]+)")
IL = re.compile(r"\{\{il\|([^{}]*)\}\}")
PERCENT = re.compile(r"[<~]?\d+(?:\.\d+)?%\??")
COLUMN = re.compile(r"Regular|Uber|Difficulty \d|Normal", re.IGNORECASE)
SAMPLE_VERSION = re.compile(r"Estimated drop rates? from \[\[version ([\d.]+)\]\]", re.IGNORECASE)
SAMPLE_SIZE = re.compile(r"\bn=(\d+)")
TITLES_PER_REQUEST = 50  # the most titles one MediaWiki query takes
COLUMN_WORDS = {"regular": "обычный", "uber": "убер", "normal": "обычный"}
# Wordings the wiki uses for several items, in Russian. Names stay as the wiki writes them.
USUAL_WORDINGS = (
    (r"Drops from (.+?) when completing a run using (.+?)\.?", "Падает с босса {0}, если пройти забег с реликвией {1}"),
    (r"Obtained by Runeforging an? (.+?)\.?", "Создаётся рунной ковкой из {0}"),
    (r"Can be created by reforging an? (.+?) in the Reforging Bench\.?", "Создаётся на Столе перековки из: {0}"),
    (r"Obtainable from (.+?) as a reward due to a bug\.?", "Выдавался наградой в {0} из-за ошибки игры"),
)


@dataclass(frozen=True)
class Drop:
    name: str
    base: str
    kind: str
    source: str  # the wiki's words, cleaned
    level: int | None
    jewel: bool
    chance: tuple = ()  # (column, rate) pairs, from players' samples quoted on the wiki
    sample: str = ""  # the version and size of that sample


def pages_url(titles: list[str]) -> str:
    """The text of several wiki pages in one request, following redirects such as «Simulacrum (encounter)» to «Simulacrum»."""
    return WIKI_API + "?" + urllib.parse.urlencode({"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main", "redirects": 1, "titles": "|".join(titles), "format": "json"})


def read_page_texts(answer) -> list[str]:
    pages = answer.get("query", {}).get("pages", {}) if isinstance(answer, dict) else {}
    texts = []
    for page in pages.values() if isinstance(pages, dict) else []:
        try:
            texts.append(str(page["revisions"][0]["slots"]["main"]["*"]))
        except (KeyError, IndexError, TypeError):
            continue
    return texts


def il_name(inner: str) -> str:
    """The item an {{il|...}} template names: its first plain part, or its name= or page= part."""
    parts = [part.strip() for part in inner.split("|")]
    for part in parts:
        key, _, value = part.partition("=")
        if key in ("name", "page") and value:
            return re.sub(r"\s*\([^)]*\)$", "", html.unescape(value)).strip()  # «Sekhema's Resolve (Fire)» is still Sekhema's Resolve
    return html.unescape(next((part for part in parts if part and "=" not in part), "")).strip()


def _labels(row: str) -> list[str]:
    """The rate columns a table header names, such as Regular and Uber, or Difficulty 1 to 3."""
    cells = re.split(r"!!|\n!", row.strip().lstrip("!"))
    found = [COLUMN.search(cell) for cell in cells]
    return [match.group(0) for match in found if match]


def read_rates(text: str) -> dict[str, dict]:
    """The estimated drop rates a boss or encounter page gives, from players' samples: tables with a rate per column
    and lists like «* Atziri's Step (35%)». A page without the wiki's estimate notice gives nothing."""
    version = SAMPLE_VERSION.search(text)
    if not version:
        return {}
    size = SAMPLE_SIZE.search(text[version.start():version.start() + 600])
    sample = version.group(1) + (f", n={size.group(1)}" if size else "")
    rates: dict[str, dict] = {}
    for table in re.findall(r"\{\|(.*?)\n\|\}", text, re.DOTALL):
        labels: list[str] = []
        for row in re.split(r"\n\|-", table):
            if row.strip().startswith("!"):
                labels = _labels(row)
                continue
            found = IL.search(row)
            if not found:
                continue
            rest = row[found.end():]
            pieces = rest.split("||")[1:] if rest.lstrip(" ").startswith("||") else rest.split("\n|")[1:]
            values = [PERCENT.search(piece) for piece in pieces]
            chance = []
            for place, value in enumerate(values):
                if value:
                    column = place - len(values) + len(labels)
                    chance.append([labels[column] if 0 <= column < len(labels) and len(labels) >= len(values) else "", value.group(0)])
            name = il_name(found.group(1))
            if chance and name and name not in rates:
                rates[name] = {"chance": chance, "sample": sample}
    for found in re.finditer(r"^\*+\s*\{\{il\|([^{}]*)\}\}\s*([^\n]*)", text, re.MULTILINE):
        value = PERCENT.search(found.group(2))
        name = il_name(found.group(1))
        if value and name and name not in rates and found.group(2).startswith("("):  # «(35%)» right after the item, not a figure later in the sentence
            rates[name] = {"chance": [["", value.group(0)]], "sample": sample}
    return rates


def chance_text(chance: list, russian: bool) -> str:
    """«≈42%», or «≈48% обычный · ≈41% убер», or «≈29.5% (сложность 3)»."""
    parts = []
    for label, value in chance:
        shown = value if value.startswith(("<", "~")) else "≈" + value
        if label and russian:
            label = COLUMN_WORDS.get(label.casefold(), label.replace("Difficulty", "сложность"))
        parts.append(f"{shown} {label}".strip() if len(chance) > 1 else (f"{shown} ({label})" if label else shown))
    return " · ".join(parts)


def query_url(where: str, offset: int) -> str:
    return WIKI_API + "?" + urllib.parse.urlencode({"action": "cargoquery", "tables": "items", "fields": FIELDS, "where": where, "limit": ROWS_PER_PAGE, "offset": offset, "format": "json"})


def _without_hover_cards(text: str) -> str:
    """The wiki puts a whole item card inside the sentence that names the item; only the name it was hung on stays."""
    while (start := text.find('<span class="hoverbox__display')) != -1:
        depth, position = 0, start
        while position < len(text):
            if text.startswith("<span", position):
                depth += 1
            elif text.startswith("</span>", position):
                depth -= 1
                if depth == 0:
                    position += len("</span>")
                    break
            position += 1
        text = text[:start] + text[position:]
    return text


def clean_wiki_text(text: str | None) -> str:
    if not text:
        return ""
    text = _without_hover_cards(html.unescape(html.unescape(text)))
    text = WIKI_LINK.sub(r"\1", FILE_LINK.sub("", text))
    return re.sub(r"\s+", " ", TAG.sub("", text)).strip()


def source_kind(text: str, restricted: bool, enabled: bool) -> str:
    lower = text.casefold()
    if not enabled:
        return "legacy"
    if not restricted:
        return "world"
    if "simulacrum" in lower:
        return "simulacrum"
    if "atziri's vault" in lower:
        return "vault"
    if "trial of" in lower:
        return "trial"
    if "event" in lower or "race reward" in lower:
        return "event"
    if any(word in lower for word in ("reforging", "runeforging", "obtained by", "created")):
        return "craft"
    if "drops from" in lower:
        return "boss"
    return "other"


def read_rows(answer) -> list[dict]:
    """The rows of one Cargo reply. Anything odd in it is left out rather than allowed to stop the rest."""
    rows = answer.get("cargoquery") if isinstance(answer, dict) else None
    if not isinstance(rows, list):
        raise ValueError("the wiki sent no rows")
    found = []
    for row in rows:
        title = row.get("title") if isinstance(row, dict) else None
        if isinstance(title, dict) and isinstance(title.get("name"), str) and title["name"].strip():
            found.append(title)
    return found


def build_drops(rows: list[dict]) -> dict[str, dict]:
    """One entry per item. Variants of a unique share a name; the one that says where it drops wins."""
    drops: dict[str, dict] = {}
    for row in rows:
        name = html.unescape(row["name"]).strip()
        text = clean_wiki_text(row.get("drop text"))
        restricted, enabled = row.get("is drop restricted") == "1", row.get("drop enabled") != "0"
        try:
            level = int(row.get("drop level") or "")
        except ValueError:
            level = None
        entry = {"base": html.unescape(row.get("base item") or "").strip(), "source": text, "kind": source_kind(text, restricted, enabled),
                 "level": level, "jewel": row.get("class id") == "Jewel"}
        target = LINK_TARGET.search(html.unescape(row.get("drop text") or ""))
        if restricted and target:
            entry["page"] = target.group(1).strip()  # the boss or encounter page, which may give estimated rates
        if name not in drops or (text and not drops[name]["source"]):
            drops[name] = entry
    return drops


def fetch_drops(fetch_text) -> dict:
    """Every page of both queries. fetch_text(url) returns the reply's text; it is the program's own, polite fetch."""
    rows: list[dict] = []
    for where in QUERIES:
        for page in range(MOST_PAGES):
            found = read_rows(json.loads(fetch_text(query_url(where, page * ROWS_PER_PAGE))))
            rows += found
            if len(found) < ROWS_PER_PAGE:
                break
    drops = build_drops(rows)
    if len(drops) < 100:  # far fewer than the game has: a changed wiki, and the saved list is better than this one
        raise ValueError(f"the wiki listed only {len(drops)} items")
    pages = sorted({entry["page"] for entry in drops.values() if entry.get("page")})
    try:
        for start in range(0, len(pages), TITLES_PER_REQUEST):
            for text in read_page_texts(json.loads(fetch_text(pages_url(pages[start:start + TITLES_PER_REQUEST])))):
                for name, rate in read_rates(text).items():
                    if name in drops and "chance" not in drops[name]:
                        drops[name].update(rate)
    except (OSError, ValueError):  # the rates are a bonus: the list of sources stands without them
        pass
    return drops


def russian_source(drop: Drop) -> str:
    """The usual wordings in Russian. Names of bosses and places stay as the wiki writes them, and so does anything unusual."""
    text = drop.source
    if drop.kind == "legacy":
        return "Больше не выпадает" + (f": {text}" if text else "")
    if drop.kind == "world":
        return "Падает где угодно" + (f", с уровня зоны {drop.level}" if drop.level and drop.level > 1 else "")
    if drop.kind == "simulacrum" and re.fullmatch(r"Drops in the Simulacrum\.?", text):
        return "Падает в Симулякре"
    if drop.kind == "vault":
        return "Хранилище Атзири в Храме Атзири, после победы над Атзири"
    if drop.kind == "trial" and "Trial of the Sekhemas" in text:
        chest = QUOTED.search(text)
        return f"Сундук «{chest.group(1)}» в Испытании сехем" if chest else "Испытание сехем"
    if drop.kind == "event":
        return "Награда за высокие места в гонках (события)"
    for pattern, wording in USUAL_WORDINGS:
        found = re.fullmatch(pattern, text)
        if found:
            return wording.format(*found.groups())
    plain = drop.kind == "boss" and not re.search(r"\b(?:when|if|using|after|while|during|with)\b", text)  # a condition is told as the wiki tells it
    found = re.fullmatch(r"Drops from (.+?)(?: at (?:the |a |an )?(.+?))?\.?", text) if plain else None
    if found:
        return f"Падает с босса {found.group(1)}" + (f" ({found.group(2)})" if found.group(2) else "")
    return text


def drops_of(stored: dict) -> list[Drop]:
    items = stored.get("items", {}) if isinstance(stored, dict) else {}
    return [Drop(name, entry["base"], entry["kind"], entry["source"], entry.get("level"), bool(entry.get("jewel")), tuple(tuple(pair) for pair in entry.get("chance") or ()), entry.get("sample", ""))
            for name, entry in items.items()]


def shown_drops(drops: list[Drop], kind: str, query: str, show_name, matches, show_base=lambda base: base) -> list[Drop]:
    """The list as the page shows it: the chosen kind, the search, the rare places first, then by name."""
    if kind == "special":
        chosen = [drop for drop in drops if drop.kind not in ("world", "legacy")]
    elif kind != "all":
        chosen = [drop for drop in drops if drop.kind == kind]
    else:
        chosen = list(drops)
    chosen = [drop for drop in chosen if matches(query, f"{drop.name} {show_name(drop.name)} {drop.base} {show_base(drop.base or drop.name)} {drop.source}")]
    return sorted(chosen, key=lambda drop: (KINDS.index(drop.kind) if drop.kind in KINDS else len(KINDS), show_name(drop.name).casefold()))


def _plain(text: str) -> str:
    return text.casefold().replace("ё", "е")


def search_place(query: str, names: list[str], text: str, matches) -> int | None:
    """How well the typed letters fit an item, ranked as the craft's base search ranks bases: a name that begins with them,
    then a name with a word that does, then one holding them anywhere; last, the words found anywhere, its source too. None when they do not fit."""
    typed = _plain(query.strip())
    if not typed:
        return 0
    names = [_plain(name) for name in names if name]
    if any(name.startswith(typed) for name in names):
        return 0
    if any(word.startswith(typed) for name in names for word in re.split(r"[\s\-'’,()]+", name)):
        return 1
    if any(typed in name for name in names):
        return 2
    words = [word for word in re.split(r"[^\w%+]+", typed) if len(word) > 1]  # one letter alone would match nearly everything here
    plain = _plain(text)
    if words and all(word in plain for word in words):
        return 3
    return None


def searched_drops(drops: list[Drop], kind: str, query: str, show_name, matches, show_base=lambda base: base) -> tuple[list[Drop], list[Drop]]:
    """What a search finds: in the chosen kind best fit first, and apart, what it finds in the other kinds."""
    inside, outside = [], []
    for drop in drops:
        names = [show_name(drop.name), drop.name, show_base(drop.base or drop.name), drop.base]
        place = search_place(query, names, f"{' '.join(name for name in names if name)} {drop.source} {russian_source(drop)}", matches)
        if place is None:
            continue
        rank = (place, _plain(names[0] if drop.base else names[2]))  # by the shown name within each fit, as the craft lists bases; a jewel base shows as a base
        (inside if in_kind(drop, kind) else outside).append((rank, drop))
    return [drop for _, drop in sorted(inside, key=lambda pair: pair[0])], [drop for _, drop in sorted(outside, key=lambda pair: pair[0])]


def in_kind(drop: Drop, kind: str) -> bool:
    if kind == "special":
        return drop.kind not in ("world", "legacy")
    return kind == "all" or drop.kind == kind


def wiki_page(name: str) -> str:
    return f"{WIKI}/wiki/{urllib.parse.quote(name.replace(' ', '_'))}"


# ------------------------------------------------------------------- the page
class DropPage:
    """«Where it drops»: every unique and jewel base, what the wiki says about where it comes from."""

    def __init__(self, parent, colors: dict[str, str], translate, helpers: dict):
        self.colors, self.t, self.helpers = colors, translate, helpers
        self.kind = "special"
        page = tk.Frame(parent, bg=colors["background"], padx=10)
        page.pack(fill="both", expand=True)
        top = tk.Frame(page, bg=colors["background"])
        top.pack(fill="x", pady=(0, 6))
        helpers["button"](top, self.t("Открыть вики"), lambda: helpers["open_link"](WIKI)).pack(side="right")
        self.subtitle = tk.Label(top, bg=colors["background"], fg=colors["muted"], font=(BODY, 9), anchor="w", justify="left")
        self.subtitle.pack(anchor="w", fill="x")
        filters = tk.Frame(page, bg=colors["background"])
        filters.pack(fill="x", pady=(0, 6))
        self.filter_buttons = {}
        for column, key in enumerate(FILTERS):
            filters.columnconfigure(column, weight=1, uniform="drops")
            button = helpers["button"](filters, self.t(KIND_TITLES[key]), lambda k=key: self.set_kind(k))
            button.grid(row=0, column=column, sticky="ew", padx=(0, 4))
            self.filter_buttons[key] = button
        bar = tk.Frame(page, bg=colors["background"])
        bar.pack(fill="x", pady=(0, 6))
        tk.Label(bar, text=self.t("Поиск"), bg=colors["background"], fg=colors["muted"], font=(BODY, 9)).pack(side="left", padx=(0, 8))
        self.search = tk.StringVar()
        trace_while(self.search, bar, lambda *_: helpers["after_typing"](self.render))
        helpers["make_entry"](bar, self.search).pack(side="left", fill="x", expand=True, ipady=5)
        self.board = Board(page, colors, helpers["enable_scrolling"], lazy=True)
        self.canvas = self.board.canvas
        self.images: list = []
        self.base_names: dict[str, str] = {}
        self.stale = True

    def data_changed(self) -> None:
        """Names, art or drop sources came: looked up again, and drawn again on the next visit."""
        self.base_names = {}
        self.stale = True

    def show(self) -> None:
        """Opening the tab: the list as it was left, drawn again only when something came meanwhile."""
        if self.stale:
            self.render()

    def _show_base(self, base: str) -> str:
        """A base in the player's language, looked up once: finding it among all names is slow, and a render asks for hundreds."""
        if base not in self.base_names:
            self.base_names[base] = self.helpers["show_base"](base)
        return self.base_names[base]

    def set_kind(self, kind: str) -> None:
        self.kind = kind
        self.render()

    def render(self) -> None:
        self.stale = False
        colors, helpers = self.colors, self.helpers
        for key, button in self.filter_buttons.items():
            chosen = key == self.kind
            button.config(bg=colors["selected"] if chosen else colors["raised"], fg=colors["on_selected"] if chosen else colors["text"])
        stored = helpers["drops"]()
        drops = drops_of(stored)
        stamp = stored.get("fetched_at", "") if isinstance(stored, dict) else ""
        self.subtitle.config(text=self.t("Где падают уники и самоцветы. Данные: poe2wiki.net (CC BY-NC-SA), обновляются раз в неделю.")
                             + (f"  •  {stamp[:10]}" if stamp else "") if drops else self.t("Список придёт с вики при следующем обновлении данных."))
        russian = helpers["language"]() == "ru"
        lines, self.images = [], []
        if drops:
            lines.append(Line([Cell(44, self.t("Предмет"), colors["muted"], 8, True), Cell(260, self.t("База"), colors["muted"], 8, True),
                               Cell(440, self.t("С кого падает"), colors["muted"], 8, True), Cell(-14, self.t("Шанс"), colors["muted"], 8, True, "e")], None, 24))
        query = self.search.get().strip()
        show_base = self._show_base
        if query:  # best fit first, as in the craft's base search; what the other kinds hold comes after
            found, elsewhere = searched_drops(drops, self.kind, query, helpers["show_unique"], helpers["matches"], show_base)
            shown = [*found, *([None] if elsewhere else []), *elsewhere]
        else:
            shown = shown_drops(drops, self.kind, "", helpers["show_unique"], helpers["matches"], show_base)
        current = None
        for drop in shown:
            if drop is None:
                lines.append(Line([Cell(10, self.t("В других разделах").upper(), colors["muted"], 8, True)], None, 30))
                continue
            if not query and drop.kind != current and self.kind in ("all", "special"):
                current = drop.kind
                lines.append(Line([Cell(10, self.t(KIND_TITLES.get(drop.kind, drop.kind)).upper(), colors["muted"], 8, True)], None, 26))
            icon = helpers["icon"](drop.name, drop.base, drop.jewel)
            if icon:
                self.images.append(icon)
            cells = [Cell(10, image=icon)] if icon else []
            is_base = not drop.base  # a jewel base is an item of its own, with no base under it
            shown_name = show_base(drop.name) if is_base else helpers["show_unique"](drop.name)
            where = russian_source(drop) if russian else drop.source or ("Drops anywhere" if drop.kind == "world" else "")
            chance, note = chance_lines(drop, russian, helpers["listings"](drop.name))
            cells += [Cell(44, shown_name, colors["text"] if is_base else colors["unique"], 10, True),
                      Cell(260, self.t("База самоцвета") if is_base else show_base(drop.base), colors["muted"], 9),
                      Cell(440, where, colors["soft"] if drop.kind in ("world", "legacy") else colors["text"], 9, False, "w", True, room=CHANCE_COLUMN)]
            if note:  # how many runs it takes in bold, the rate and the version small under it
                cells += [Cell(-14, chance, colors["accent"], 10, True, "e", dy=-7), Cell(-14, note, colors["muted"], 8, False, "e", dy=8)]
            else:
                cells.append(Cell(-14, chance, colors["muted"], 9, False, "e"))
            lines.append(Line(cells, colors["panel"], 40 if note else 34, command=lambda name=drop.name: helpers["open_link"](wiki_page(name))))
        if not lines and drops:
            lines.append(Line([Cell(10, self.t("Ничего не найдено"), colors["muted"], 10)], None, 34))
        self.board.show(lines)


CHANCE_COLUMN = 190  # pixels on the right for the chance, which the source column leaves free


def attempts_text(rate: str, russian: bool) -> str:
    """A rate per run or kill as how many it takes on average: «≈1%» is «1 из ~100», «<1%» is «реже 1 из 100»."""
    number = re.search(r"\d+(?:\.\d+)?", rate)
    percent = float(number.group()) if number else 0.0
    if percent <= 0:
        return "—"
    if rate.startswith("<"):
        return f"реже 1 из {round(100 / percent)}" if russian else f"rarer than 1 in {round(100 / percent)}"
    runs = 100 / percent
    if runs < 1.25:
        return "каждый раз" if russian else "every time"
    shown = str(round(runs)) if runs < 100 else str(int(round(runs, -1)))
    approximate = "" if runs < 10 else "~"
    return f"1 из {approximate}{shown}" if russian else f"1 in {approximate}{shown}"


def chance_lines(drop: Drop, russian: bool, listings: int | None = None) -> tuple[str, str]:
    """The chance column: the estimate, one line per column of the wiki's table, and below it where it comes from.
    Without a measured rate, how many are on the market, as a rough sign of how rare it is."""
    if drop.chance:
        version = drop.sample.split(",")[0]
        return attempts_text(drop.chance[0][1], russian), f"{chance_text([list(pair) for pair in drop.chance], russian)} · {version}"
    if listings and drop.kind in ("world", "boss", "other"):
        return (f"на рынке {listings}" if russian else f"{listings} on the market"), ""
    return "—", ""


def full_source(drop: Drop, russian: bool, listings: int | None = None) -> str:
    """Where it drops, its estimated chance there when players have measured one, and for anything else how many are on the market."""
    where = russian_source(drop) if russian else drop.source or ("Drops anywhere" if drop.kind == "world" else "")
    if drop.chance:
        version = drop.sample.split(",")[0]
        where += f"  •  {attempts_text(drop.chance[0][1], russian)} ({chance_text([list(pair) for pair in drop.chance], russian)}, {version})"
    elif listings and drop.kind in ("world", "boss", "other"):
        where += f"  •  {'на рынке' if russian else 'on the market'} {listings}"
    return where


def drop_line(stored: dict, name: str, language: str, listings: int | None = None) -> str | None:
    """One line for another page, such as the build's item details: where this unique comes from, in the player's language."""
    entry = (stored.get("items", {}) if isinstance(stored, dict) else {}).get(name)
    if not entry:
        return None
    return full_source(drops_of({"items": {name: entry}})[0], language == "ru", listings) or None
