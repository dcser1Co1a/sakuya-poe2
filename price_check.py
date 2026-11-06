"""Price check: reads a copied item and shows its price in a window of its own.

Stackable items are priced from the hourly data the program already keeps, without any requests.
Other items get a search panel; trade_search.py sends its requests, and only when the player asks.
"""
import base64
import ctypes
import io
import json
import re
import threading
import time
import tkinter as tk
import urllib.parse
from dataclasses import dataclass
from tkinter import font as tkfont

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageOps

from sakura import BODY, CHOSEN, CHOSEN_LIGHT, MOD_OFF, MOD_ON, MOD_ON_GROUND, ON_CHOSEN, PAPER_VARIANTS, TITLE_FONT, THUMB, add_waves, add_branch, keep_timer_fine, paper_piece, something_is_moving, style_title_bar
from trade_search import roll_share, split_ranges

TRADE_SEARCH_URL = "https://www.pathofexile.com/trade2/search/poe2/"
CLASS_PREFIXES = ("Item Class:", "Класс предмета:")
RARITY_PREFIXES = ("Rarity:", "Редкость:")
UNIQUE_RARITIES = {"unique", "уникальный"}
STACK_SIZE = re.compile(r"^(?:Stack Size|Размер стопки): ([\d\s ,]+)/", re.MULTILINE)
GEM_LEVEL = re.compile(r"^(?:Level|Уровень): (\d+)", re.MULTILINE)
GWL_EXSTYLE, WS_EX_NOACTIVATE = -20, 0x08000000
GWL_STYLE, WS_MINIMIZEBOX, WS_MAXIMIZEBOX = -16, 0x00020000, 0x00010000
SWP_REDRAW_FRAME_ONLY = 0x0037  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
WINDOW_WIDTH = 444
WINDOW_MARGIN = 40
WINDOW_ALPHA = 0.95  # lets the game show through a little
FADE_STEPS, FADE_STEP_MS = 9, 11
REVEAL_STEP_MS = 11  # the parts of a long window come in one after another, top to bottom
REVEAL_FEWEST_PARTS = 3
PANEL_FIXED_HEIGHT = 620  # all of the search panel but its list of mods, with the title bar and a margin
PANEL_FEWEST_ROWS = 3
NEW_CONTENT_FADE_START = 0.45  # how see-through the window turns while new content comes in
SWITCH_SIZE = (30, 16)
SPARK_SCALE = 3  # drawn this many times larger and shrunk, which gives smooth edges
SPARK_LINE_WIDTH = 5  # at the larger scale
SPARK_PREPARE_PAUSE_SECONDS = 0.004  # graphs made ahead leave the window its share of the processor
SPARK_FILL_STRENGTH = 0.2
SPARK_CURVE_STEPS = 16
SPARK_CACHE_LIMIT = 2000
CARD_CACHE_LIMIT = 200  # a sheet takes about 250 KB in Tk, so all of them would take too much
FLAT_CHANGE = 0.5  # a smaller move in percent is shown as no move
SCROLLBAR_WIDTH = 10
SHORTEST_THUMB = 36  # a long list must not shrink the handle into a dot nobody can grab
UNIT_LABELS = {"Divine Orb": "Divine", "Chaos Orb": "Chaos", "Exalted Orb": "Exalted"}
NUMBERS = re.compile(r"[+-]?\d+(?:[.,]\d+)?(?:-\d+(?:[.,]\d+)?)?%?")


@dataclass(frozen=True)
class CopiedItem:
    rarity: str
    lines: tuple[str, ...]  # the name and base lines
    stack: int
    level: int | None


@dataclass(frozen=True)
class PriceMatch:
    name: str
    each: float
    stack: int


def read_copied_item(text: str) -> CopiedItem | None:
    """Reads the item text the game puts on the clipboard. Returns None for anything else."""
    text = text.replace("\r\n", "\n").strip()
    if not text.startswith(CLASS_PREFIXES):
        return None
    header = [line.strip() for line in text.split("--------")[0].strip().split("\n")]
    rarity = next((line.partition(":")[2].strip() for line in header if line.startswith(RARITY_PREFIXES)), "")
    lines = tuple(line for line in header if line and not line.startswith(CLASS_PREFIXES + RARITY_PREFIXES))
    stack = STACK_SIZE.search(text)
    level = GEM_LEVEL.search(text)
    amount = int(re.sub(r"\D", "", stack.group(1))) if stack else 1
    return CopiedItem(rarity, lines, amount or 1, int(level.group(1)) if level else None)


def build_price_index(prices: dict[str, float], russian_name) -> dict[str, str]:
    """Maps names as a game client writes them, in both languages, to the price list's names."""
    index = {}
    for name in prices:
        index[name.casefold()] = name
        index[russian_name(name).casefold()] = name
    return index


def find_price(item: CopiedItem, prices: dict[str, float], index: dict[str, str]) -> PriceMatch | None:
    for line in reversed(item.lines):
        candidates = [f"{line} (Level {item.level})", f"{line} (уровень {item.level})", line] if item.level else [line]  # the price list's Russian names say it their own way
        for candidate in candidates:
            name = index.get(candidate.casefold())
            if name:
                return PriceMatch(name, prices[name], item.stack)
    return None


def trade_search_url(item: CopiedItem, league: str, bases: dict[str, str]) -> str:
    """A link to the official trade site with the item's base filled in, when the base is known."""
    address = TRADE_SEARCH_URL + urllib.parse.quote(league)
    text = " ".join(item.lines).casefold()
    known = [shown for shown in bases if shown in text]
    if not known:
        return address
    rarity = "unique" if item.rarity.casefold() in UNIQUE_RARITIES else "nonunique"
    query = {"query": {"status": {"option": "online"}, "type": bases[max(known, key=len)],
                       "filters": {"type_filters": {"filters": {"rarity": {"option": rarity}}}}},
             "sort": {"price": "asc"}}
    return f"{address}?q={urllib.parse.quote(json.dumps(query, separators=(',', ':')))}"


def spark_curve(data: list | None, width: int, height: int, margin: int = 3) -> list[tuple[float, float]]:
    """A smooth curve through the prices. It never swings past the real highs and lows, because its slope is zero at each of them."""
    values = [value for value in data or [] if value is not None]
    if len(values) < 2:
        return []
    low, high = min(values), max(values)
    span = high - low
    step = (width - 2 * margin) / (len(values) - 1)
    ys = [height - margin - (value - low) / span * (height - 2 * margin) if span else height / 2 for value in values]
    slopes = [(after - before) / step for before, after in zip(ys, ys[1:])]
    tangents = [slopes[0]] + [0 if left * right <= 0 else 2 * left * right / (left + right) for left, right in zip(slopes, slopes[1:])] + [slopes[-1]]
    curve = []
    for index, (start, end) in enumerate(zip(ys, ys[1:])):
        for part in range(SPARK_CURVE_STEPS):
            s = part / SPARK_CURVE_STEPS
            y = ((2 * s ** 3 - 3 * s ** 2 + 1) * start + (s ** 3 - 2 * s ** 2 + s) * step * tangents[index]
                 + (3 * s ** 2 - 2 * s ** 3) * end + (s ** 3 - s ** 2) * step * tangents[index + 1])
            curve.append((margin + (index + s) * step, y))
    curve.append((width - margin, ys[-1]))
    return curve


_spark_images: dict[tuple, tk.PhotoImage] = {}
_spark_pictures: dict[tuple, str] = {}  # made ahead on another thread: only the step into Tk has to happen on the window's
_spark_fades: dict[tuple, Image.Image] = {}
_card_images: dict[tuple, tk.PhotoImage] = {}
_card_keeper_canvas: tk.Canvas | None = None
_kept_fonts: list[tuple] = []


def _spark_key(data: list | None, width: int, height: int, color: str, ground: tuple | None = None) -> tuple:
    return tuple(data or ()), width, height, color, ground


def _spark_picture(data: list | None, width: int, height: int, color: str, ground: tuple | None = None) -> str | None:
    """ground is the (sheet width, sheet height, variant, left, top) of the paper under the graph. Laid on that, the picture has whole pixels, which a redraw copies instead of blends."""
    curve = spark_curve(data, width, height)
    if not curve:
        return None
    size = (width * SPARK_SCALE, height * SPARK_SCALE)
    points = [(x * SPARK_SCALE, y * SPARK_SCALE) for x, y in curve]
    shape = Image.new("L", size, 0)
    ImageDraw.Draw(shape).polygon([*points, (points[-1][0], size[1]), (points[0][0], size[1])], fill=255)
    fade = _spark_fades.get(size)
    if fade is None:
        fade = _spark_fades[size] = ImageOps.flip(Image.linear_gradient("L")).resize(size).point(lambda value: int(value * SPARK_FILL_STRENGTH))
    red, green, blue = ImageColor.getrgb(color)
    image = Image.new("RGBA", size, (red, green, blue, 0))
    image.putalpha(ImageChops.multiply(shape, fade))
    ImageDraw.Draw(image).line(points, fill=(red, green, blue, 255), width=SPARK_LINE_WIDTH)
    output = io.BytesIO()
    small = image.reduce(SPARK_SCALE)
    if ground:
        sheet_width, sheet_height, variant, left, top = ground
        laid = paper_piece(sheet_width, sheet_height, variant, (left, top, left + width, top + height))
        laid.paste(small, mask=small.getchannel("A"))
        small = laid
    small.save(output, "PNG", compress_level=1)
    return base64.b64encode(output.getvalue()).decode("ascii")


def prepare_sparks(wanted: list[tuple]) -> None:
    """Makes graphs ahead of their first showing, on a thread of its own, so the cards can come in without stopping for them."""
    def work():
        for data, width, height, color, ground in wanted:
            while something_is_moving():  # any Python running on another thread makes the window wait after each of its calls into Tk
                time.sleep(0.05)
            key = _spark_key(data, width, height, color, ground)
            if key not in _spark_images and key not in _spark_pictures:
                try:
                    picture = _spark_picture(data, width, height, color, ground)
                except (OSError, ValueError, TypeError):
                    continue  # it will be tried when it is shown
                if picture:
                    if len(_spark_pictures) >= SPARK_CACHE_LIMIT:
                        return
                    _spark_pictures[key] = picture
                time.sleep(SPARK_PREPARE_PAUSE_SECONDS)

    threading.Thread(target=work, daemon=True).start()


def spark_image(data: list | None, width: int, height: int, color: str, ground: tuple | None = None) -> tk.PhotoImage | None:
    """The graph as a picture with a soft fade under the line. Tk's own lines have jagged edges. Whoever shows it keeps a reference."""
    key = _spark_key(data, width, height, color, ground)
    if key in _spark_images:
        return _spark_images[key]
    picture = _spark_pictures.pop(key, None) or _spark_picture(data, width, height, color, ground)
    if not picture:
        return None
    if len(_spark_images) >= SPARK_CACHE_LIMIT:
        _spark_images.clear()
    _spark_images[key] = tk.PhotoImage(data=picture)
    return _spark_images[key]


def _spark_layer(data: list | None, width: int, height: int, color: str) -> Image.Image | None:
    key = _spark_key(data, width, height, color)
    picture = _spark_pictures.get(key) or _spark_picture(data, width, height, color)
    if not picture:
        return None
    if len(_spark_pictures) >= SPARK_CACHE_LIMIT:
        _spark_pictures.clear()
    _spark_pictures[key] = picture
    return Image.open(io.BytesIO(base64.b64decode(picture)))


def baked_card(width: int, height: int, variant: int, tile: tuple, pictures: tuple, graph: tuple) -> tk.PhotoImage:
    """All that never changes on a card, as one sheet of whole pixels: its paper, its tile and pictures, and its graph. A window full of these redraws several times faster than one
    with every part apart, and that is what animation and scrolling wait for. tile is (left, top, right, bottom, fill, border), each of pictures is (stored picture, middle x, middle y, how many times smaller),
    and graph is (data, width, height, color, left, top). Whoever shows it keeps a reference."""
    key = (width, height, variant % PAPER_VARIANTS, tile, pictures, tuple(graph[0] or ()), graph[1:])
    if key in _card_images:
        return _card_images[key]
    sheet = paper_piece(width, height, variant, (0, 0, width, height))
    left, top, right, bottom, fill, border = tile
    ImageDraw.Draw(sheet).rectangle((left, top, right, bottom), fill=fill, outline=border)
    for encoded, x, y, shrink in pictures:
        if encoded:
            try:
                picture = Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGBA")
                picture = picture.reduce(shrink) if shrink > 1 else picture
                sheet.paste(picture, (x - picture.width // 2, y - picture.height // 2), picture)
            except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):  # a damaged picture must not stop the page it sits on
                continue
    data, graph_width, graph_height, color, graph_left, graph_top = graph
    layer = _spark_layer(data, graph_width, graph_height, color)
    if layer:
        sheet.paste(layer, (graph_left, graph_top), layer.convert("RGBA"))
    keeper = _card_keeper()
    if len(_card_images) >= CARD_CACHE_LIMIT:
        _card_images.clear()  # those on screen live on in the references their pages keep
        keeper.delete("all")
        keep_fonts_ready(list(_kept_fonts))
    _card_images[key] = tk.PhotoImage(data=b"P6 %d %d 255\n" % sheet.size + sheet.tobytes(), format="PPM")
    keeper.create_image(0, 0, image=_card_images[key])
    return _card_images[key]


def _card_keeper() -> tk.Canvas:
    """A canvas never shown. Tk forgets how to draw a picture as soon as nothing shows it, and working that out again takes milliseconds per card on every change of tab, so this always shows them all."""
    global _card_keeper_canvas
    try:
        alive = _card_keeper_canvas is not None and _card_keeper_canvas.winfo_exists()
    except tk.TclError:
        alive = False
    if not alive:
        _card_images.clear()
        _card_keeper_canvas = tk.Canvas()
    return _card_keeper_canvas


def keep_fonts_ready(fonts: list[tuple]) -> None:
    """Tk also forgets a font once nothing uses it, and finding it again is the slowest part of writing on a canvas."""
    _kept_fonts[:] = fonts
    keeper = _card_keeper()
    for font in fonts:
        keeper.create_text(0, 0, text="", font=font)


def best_unit(divine: float, exalted_per_divine: float | None, chaos_per_divine: float | None, own_name: str | None = None) -> tuple[float, str]:
    """The currency that makes a price easy to read: Divine from 1 up, Chaos from 1 Chaos up, Exalted below that. An orb is never priced in itself."""
    if not exalted_per_divine:
        return divine, "Divine Orb"
    exalted = divine * exalted_per_divine, "Exalted Orb"
    chaos = (divine * chaos_per_divine, "Chaos Orb") if chaos_per_divine else None
    if own_name == "Divine Orb" or own_name == "Chaos Orb":
        return exalted
    if own_name == "Exalted Orb":
        return chaos or (divine, "Divine Orb")
    if divine >= 1:
        return divine, "Divine Orb"
    return chaos if chaos and chaos[0] >= 1 else exalted


def thumb_place(first: float, last: float, height: int) -> tuple[float, float]:
    """Where the scrollbar's handle goes for a view of first..last, as fractions of the list."""
    span = last - first
    thumb = min(max(span * height, SHORTEST_THUMB), height)
    room = height - thumb
    top = first / (1 - span) * room if span < 1 else 0
    return top, top + thumb


def view_for_thumb(top: float, last_view_span: float, height: int) -> float:
    """The start of the view when the handle's top edge is dragged to this height."""
    thumb = min(max(last_view_span * height, SHORTEST_THUMB), height)
    room = height - thumb
    return max(min(top / room, 1), 0) * (1 - last_view_span) if room > 0 else 0


class SlimScrollbar(tk.Canvas):
    """A scrollbar with a handle that stays big enough to grab. Clicking the track jumps there."""

    def __init__(self, parent, command, track: str, active: str):
        super().__init__(parent, width=SCROLLBAR_WIDTH, height=1, bg=track, highlightthickness=0, bd=0, cursor="hand2")  # it takes the height of its list and must not ask for more
        self.command = command
        self.active = active
        self.view = (0.0, 1.0)
        self.grabbed_at: float | None = None
        self.bind("<Configure>", lambda _: self._paint())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Enter>", lambda _: self._paint(True))
        self.bind("<Leave>", lambda _: self._paint())

    def set(self, first, last) -> None:
        self.view = (float(first), float(last))
        self._paint(self.grabbed_at is not None)

    def _paint(self, lit: bool = False) -> None:
        self.delete("all")
        top, bottom = thumb_place(*self.view, self.winfo_height())
        self.create_rectangle(1, top, SCROLLBAR_WIDTH - 1, bottom, fill=self.active if lit else THUMB, outline="")

    def _press(self, event) -> None:
        top, bottom = thumb_place(*self.view, self.winfo_height())
        if not top <= event.y <= bottom:
            self._move_to(event.y - (bottom - top) / 2)
            top, bottom = thumb_place(*self.view, self.winfo_height())
        self.grabbed_at = event.y - top

    def _drag(self, event) -> None:
        if self.grabbed_at is not None:
            self._move_to(event.y - self.grabbed_at)

    def _release(self, _) -> None:
        self.grabbed_at = None

    def _move_to(self, top: float) -> None:
        self.command("moveto", view_for_thumb(top, self.view[1] - self.view[0], self.winfo_height()))


def format_change(change: float) -> tuple[str, str]:
    """A week's change as (direction mark, size). The size needs no decimals once it is large."""
    if abs(change) < FLAT_CHANGE:
        return "", "0%"
    return "▲" if change > 0 else "▼", f"{abs(change):.0f}%" if abs(change) >= 10 else f"{abs(change):.1f}%"


def draw_change(canvas: tk.Canvas, right: int, middle: int, change: float | None, up: str, down: str, neutral: str) -> None:
    """Calm numbers: only the small mark carries the color, because a page of bright percentages tires the eyes."""
    if change is None:
        return
    mark, size = format_change(change)
    number = canvas.create_text(right, middle, text=size, fill=neutral, font=(BODY, 9), anchor="e")
    if mark:
        canvas.create_text(canvas.bbox(number)[0] - 2, middle, text=mark, fill=up if change > 0 else down, font=(BODY, 7), anchor="e")


def switch_image(on: bool, track: str, knob: str) -> tk.PhotoImage:
    """A smooth on/off switch. It is drawn large and shrunk, because small shapes drawn by Tk have jagged edges."""
    scale = 4
    width, height = SWITCH_SIZE[0] * scale, SWITCH_SIZE[1] * scale
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=height // 2, fill=track)
    margin = 2 * scale
    left = width - height + margin if on else margin
    draw.ellipse((left, margin, left + height - margin * 2 - 1, height - margin - 1), fill=knob)
    output = io.BytesIO()
    image.resize(SWITCH_SIZE, Image.LANCZOS).save(output, "PNG")
    return tk.PhotoImage(data=base64.b64encode(output.getvalue()).decode("ascii"))


def add_mod_text(parent, text: str, ground: str, color: str, number_color: str, size: int, width: int, cursor: str = "arrow") -> tk.Text:
    """Wrapped text with its numbers in bold, the way players read mods. It looks like a label and cannot be selected."""
    normal = tkfont.Font(parent, family=BODY, size=size)
    bold = tkfont.Font(parent, family=BODY, size=size, weight="bold")
    characters = max(width // normal.measure("0"), 1)
    widget = tk.Text(parent, bg=ground, fg=color, font=normal, wrap="word", width=characters, height=1, bd=0, padx=0, pady=0, highlightthickness=0, takefocus=0, cursor=cursor, spacing1=1, spacing3=1)
    widget.fonts = (normal, bold)  # Tk forgets a font once Python lets go of it
    widget.tag_configure("number", font=bold, foreground=number_color)
    position = 0
    for found in NUMBERS.finditer(text):
        widget.insert("end", text[position:found.start()])
        widget.insert("end", found.group(), "number")
        position = found.end()
    widget.insert("end", text[position:])
    widget.config(state="disabled")
    widget.bindtags((str(widget), str(widget.winfo_toplevel()), "all"))
    # The height is known only once the text has been laid out, so it starts with a close estimate.
    room, lines, used = characters * normal.measure("0"), 1, 0
    for word in re.findall(r"\S+\s*", text):
        size_of_word = bold.measure(word)
        if used + size_of_word > room and used:
            lines, used = lines + 1, 0
        used += size_of_word
    widget.config(height=lines)

    def fit(_) -> None:
        counted = widget.count("1.0", "end-1c", "displaylines")
        breaks = counted[0] if isinstance(counted, tuple) else counted or 0
        if breaks + 1 != int(widget.cget("height")):
            widget.config(height=breaks + 1)

    widget.bind("<Configure>", fit)
    return widget


def fade_in(window: tk.Toplevel, start: float = 0.0) -> None:
    """Appears in a few steps instead of popping up. Only the transparency changes, so nothing is laid out again:
    resizing a Tk window step by step costs over 100 ms a step, which is why the height does not glide."""
    root = window.nametowidget(".")  # a timer on the window itself would turn into an error if the window closed first
    if getattr(window, "fade_job", None):
        root.after_cancel(window.fade_job)

    def step(number: int) -> None:
        if not window.winfo_exists():  # closed halfway through
            return
        window.attributes("-alpha", WINDOW_ALPHA * (start + (1 - start) * number / FADE_STEPS))
        keep_timer_fine(root)
        window.fade_job = root.after(FADE_STEP_MS, step, number + 1) if number < FADE_STEPS else None

    step(1)


def keep_from_taking_focus(window: tk.Toplevel) -> int:
    window.update_idletasks()
    user32 = ctypes.windll.user32
    handle = user32.GetAncestor(window.winfo_id(), 2) or window.winfo_id()
    user32.SetWindowLongW(handle, GWL_EXSTYLE, user32.GetWindowLongW(handle, GWL_EXSTYLE) | WS_EX_NOACTIVATE)
    return handle


class PriceWindow:
    """A separate window for price checks. It stays open, keeps its place and never takes focus from the game."""

    def __init__(self, root: tk.Tk, colors: dict[str, str], title: str, geometry: str | None, on_moved):
        self.colors = colors
        self.on_moved = on_moved
        self.window = tk.Toplevel(root, bg=colors["background"])
        self.window.withdraw()
        self.window.title(title)
        self.window.resizable(False, False)
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", WINDOW_ALPHA)
        self.window.protocol("WM_DELETE_WINDOW", self.window.withdraw)
        self.window.geometry(geometry or f"+{root.winfo_screenwidth() - WINDOW_WIDTH - WINDOW_MARGIN}+{WINDOW_MARGIN * 3}")
        add_branch(self.window, WINDOW_WIDTH)
        add_waves(self.window, colors["background"])
        self.body = tk.Frame(self.window, bg=colors["background"], width=WINDOW_WIDTH, padx=12, pady=12)
        self.body.pack(fill="both", expand=True)
        self.prepared = False
        self.reveal_job = None
        self.window.bind("<Configure>", self._remember_place)
        self.window.bind("<Unmap>", self._hide_if_minimized)

    def exists(self) -> bool:
        return bool(self.window.winfo_exists())

    def show(self, title: str, lines: list[tuple[str, str, bool]], image=None, graph=None, actions: tuple = ()) -> bool:
        """Fills the window with one item."""
        colors = self.colors
        self.clear()
        card = tk.Frame(self.body, bg=colors["panel"], highlightthickness=1, highlightbackground=colors["border"], padx=10, pady=10)
        card.pack(fill="both", expand=True)
        card.columnconfigure(1, weight=1, minsize=WINDOW_WIDTH - 130)
        if image:  # an empty frame would look like a picture that failed to load
            tile = tk.Frame(card, bg=colors["tile"], width=64, height=64, highlightthickness=1, highlightbackground=colors["border"])
            tile.pack_propagate(False)
            tk.Label(tile, bg=colors["tile"], image=image).pack(expand=True)
            tile.grid(row=0, column=0, sticky="n", padx=(0, 12))
        words = tk.Frame(card, bg=colors["panel"])
        words.grid(row=0, column=1, sticky="w")
        tk.Label(words, text=title, bg=colors["panel"], fg=colors["text"], justify="left", wraplength=WINDOW_WIDTH - 130, font=(TITLE_FONT, 12, "bold")).pack(anchor="w")
        for text, color, bold in lines:
            tk.Label(words, text=text, bg=colors["panel"], fg=color, justify="left", wraplength=WINDOW_WIDTH - 130, font=(BODY, 10, "bold" if bold else "normal")).pack(anchor="w")
        if graph:
            picture = tk.Label(words, image=graph, bg=colors["panel"], bd=0)
            picture.image = graph
            picture.pack(anchor="w", pady=(6, 0))
        for action_text, action in actions:
            tk.Button(words, text=action_text, command=action, relief="flat", bd=0, cursor="hand2", padx=10, pady=3, bg=colors["raised"], fg=colors["text"],
                      activebackground=colors["border"], activeforeground=colors["text"], font=(BODY, 9)).pack(anchor="w", pady=(6, 0))
        return self.open()

    def clear(self) -> None:
        """The body leaves the window first. On Windows every widget is a window of its own, and mapping them one by one is what takes the time: nothing is mapped until the window is ready."""
        self._stop_reveal()
        self.body.pack_forget()
        for child in self.body.winfo_children():
            child.destroy()

    def open(self) -> bool:
        """Shows the window. Returns True the first time, when Windows may still activate it.
        It takes its final size and place before anything is seen, so it does not grow in jerks while it fills."""
        first = not self.prepared
        hidden = self.window.state() != "normal"
        self.window.attributes("-alpha", 0 if hidden else WINDOW_ALPHA * NEW_CONTENT_FADE_START)
        self._stop_reveal()
        self.window.update_idletasks()
        height = self.window.winfo_reqheight() + (self.body.winfo_reqheight() if not self.body.winfo_manager() else 0)
        self._keep_on_screen(height)
        self._start_reveal(height)
        self.window.deiconify()
        self.window.lift()
        self._prepare()
        fade_in(self.window, 0.0 if hidden else NEW_CONTENT_FADE_START)
        return first

    def _keep_on_screen(self, height: int) -> None:
        overflow = self.window.winfo_y() + height + WINDOW_MARGIN * 2 - self.window.winfo_screenheight()
        if overflow > 0:
            self.window.geometry(f"+{self.window.winfo_x()}+{max(self.window.winfo_y() - overflow, 0)}")

    def _start_reveal(self, height: int) -> None:
        parts = [(child, child.pack_info()) for child in self.body.winfo_children() if child.winfo_manager() == "pack"]
        if len(parts) < REVEAL_FEWEST_PARTS:
            self.body.pack(fill="both", expand=True)
            return
        self.window.geometry(f"{max(self.window.winfo_reqwidth(), self.body.winfo_reqwidth())}x{height}")
        for child, _ in parts:
            child.pack_forget()
        self.body.pack(fill="both", expand=True)
        self._reveal_next(parts, 0)

    def _reveal_next(self, parts: list, number: int) -> None:
        self.reveal_job = None
        if not self.window.winfo_exists():  # closed halfway through
            return
        if number >= len(parts):
            self.window.geometry("")  # the window goes back to following what is in it
            return
        child, place = parts[number]
        if child.winfo_exists():
            child.pack(**place)
        keep_timer_fine(self.window)
        self.reveal_job = self.window.nametowidget(".").after(REVEAL_STEP_MS, self._reveal_next, parts, number + 1)

    def _stop_reveal(self) -> None:
        if self.reveal_job:
            self.window.nametowidget(".").after_cancel(self.reveal_job)
            self.reveal_job = None
            self.window.geometry("")

    def _prepare(self) -> None:
        if self.prepared or not hasattr(ctypes, "windll"):
            return
        self.prepared = True
        handle = keep_from_taking_focus(self.window)
        style_title_bar(handle)
        user32 = ctypes.windll.user32
        user32.SetWindowLongW(handle, GWL_STYLE, user32.GetWindowLongW(handle, GWL_STYLE) & ~(WS_MINIMIZEBOX | WS_MAXIMIZEBOX))
        user32.SetWindowPos(handle, 0, 0, 0, 0, 0, SWP_REDRAW_FRAME_ONLY)

    def _hide_if_minimized(self, event) -> None:
        """This window has no taskbar button, so a minimized one would sit as a small title bar in the corner of the screen."""
        if event.widget is self.window and self.window.state() == "iconic":
            self.window.withdraw()

    def _remember_place(self, event) -> None:
        if event.widget is self.window and self.window.state() == "normal":
            self.on_moved(f"+{self.window.winfo_x()}+{self.window.winfo_y()}")


def mod_rows_that_fit(screen_height: int, row_height: int) -> int:
    """How many mods the panel can show on this screen and still keep its buttons on it."""
    return max((screen_height - PANEL_FIXED_HEIGHT) // row_height, PANEL_FEWEST_ROWS)


class TradeSearchPanel:
    """Lets the player switch mods on and off, then opens the search in the browser. The program itself sends the site nothing."""
    STRICTNESS = ((1.0, "Как у предмета"), (0.9, "От 90%"), (0.8, "От 80%"), (0.0, "Любое"))
    ROW_HEIGHT = 40
    ROWS_SHOWN = 4
    ART_TILE = 92
    ROW_LETTERS = 27
    BARS = {"high": 3, "medium": 2, "low": 1}

    def __init__(self, parent, colors: dict[str, str], translate, title: str, subtitle: str, title_color: str, image, mods: list, preselected: list, on_search, on_bookmark, strictness: float = 0.9, remembered: bool = False, notes: tuple = (), extras: tuple = (), base_choice: bool = False, hints: dict | None = None):
        self.colors = colors
        self.t = translate
        self.mods = mods
        self.on_search = on_search
        self.on_bookmark = on_bookmark
        self.hints = hints or {}
        self.any_base = False
        self.strictness = strictness if strictness in {value for value, _ in self.STRICTNESS} else 0.9
        self.window = parent.winfo_toplevel()
        self.title_color = title_color
        self.image = image
        tk.Frame(parent, bg=colors["background"], width=WINDOW_WIDTH - 24, height=1).pack()  # keeps the width steady
        head = self.head = tk.Frame(parent, bg=colors["panel"], highlightthickness=1, highlightbackground=colors["border"], padx=8, pady=8)
        head.pack(fill="x", pady=(0, 10))
        tile = tk.Frame(head, bg=colors["tile"], width=self.ART_TILE, height=self.ART_TILE, highlightthickness=1, highlightbackground=colors["border"])
        tile.pack_propagate(False)
        self.art = tk.Label(tile, bg=colors["tile"], image=image or "")
        self.art.pack(expand=True)
        tile.pack(side="left", padx=(0, 12))
        words = tk.Frame(head, bg=colors["panel"])
        words.pack(side="left", fill="x")
        tk.Label(words, text=title, bg=colors["panel"], fg=title_color, wraplength=WINDOW_WIDTH - 160, justify="left", font=(TITLE_FONT, 14, "bold")).pack(anchor="w")
        if subtitle and subtitle != title:
            tk.Label(words, text=subtitle, bg=colors["panel"], fg=colors["soft"], wraplength=WINDOW_WIDTH - 160, justify="left", font=(BODY, 10)).pack(anchor="w", pady=(2, 0))
        for note, bold in notes:
            tk.Label(words, text=note, bg=colors["panel"], fg=colors["text"] if bold else colors["soft"], wraplength=WINDOW_WIDTH - 160, justify="left", font=(BODY, 10 if bold else 8, "bold" if bold else "normal")).pack(anchor="w", pady=(3, 0))
        self._section(parent, "Какие моды учитывать, как в прошлый раз" if remembered else "Какие моды учитывать")
        self.checks = []
        self.mods_canvas = None
        self._add_mods(parent, mods, preselected)
        self._section(parent, "Минимум значения мода").pack_configure(pady=(8, 4))
        row = tk.Frame(parent, bg=colors["border"], padx=1, pady=1)
        row.pack(fill="x", pady=(0, 10))
        self.strict_buttons = {}
        for column, (value, title_text) in enumerate(self.STRICTNESS):
            row.columnconfigure(column, weight=1, uniform="strictness")
            button = tk.Button(row, text=self.t(title_text), command=lambda v=value: self._set_strictness(v), relief="flat", bd=0, cursor="hand2", pady=5, font=(BODY, 9))
            button.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 1, 0))
            self.strict_buttons[value] = button
        self._set_strictness(self.strictness)
        self.base_buttons = {}
        if base_choice:
            row = tk.Frame(parent, bg=colors["border"], padx=1, pady=1)
            row.pack(fill="x", pady=(0, 10))
            for column, (value, title_text) in enumerate(((False, "Только эта база"), (True, "Любая база этого типа"))):
                row.columnconfigure(column, weight=1, uniform="base")
                button = tk.Button(row, text=self.t(title_text), command=lambda v=value: self._set_any_base(v), relief="flat", bd=0, cursor="hand2", pady=5, font=(BODY, 9))
                button.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 1, 0))
                self.base_buttons[value] = button
            self._set_any_base(False)
        self.search_button = tk.Button(parent, text=self.t("Открыть на сайте торговли"), command=self._search, relief="flat", bd=0, cursor="hand2", pady=7, bg=CHOSEN, fg=ON_CHOSEN,
                                       activebackground=CHOSEN_LIGHT, activeforeground=ON_CHOSEN, disabledforeground=colors["soft"], font=(BODY, 10, "bold"))
        self.search_button.pack(fill="x")
        self.search_button.bind("<Enter>", lambda _: self._paint_search(CHOSEN_LIGHT))
        self.search_button.bind("<Leave>", lambda _: self._paint_search(CHOSEN))
        self.bookmark_button = tk.Button(parent, text=self.t("★ В закладки"), command=self._bookmark, relief="flat", bd=0, cursor="hand2", pady=4, bg=colors["raised"], fg=colors["text"],
                                         activebackground=colors["border"], activeforeground=colors["text"], font=(BODY, 9))
        self.bookmark_button.pack(fill="x", pady=(6, 0))
        if extras:
            grid = tk.Frame(parent, bg=colors["background"])
            grid.pack(fill="x", pady=(4, 0))
            grid.columnconfigure((0, 1), weight=1, uniform="extras")
            for number, (text, command) in enumerate(extras):
                tk.Button(grid, text=text, command=command, relief="flat", bd=0, cursor="hand2", pady=4, bg=colors["raised"], fg=colors["text"], activebackground=colors["border"], activeforeground=colors["text"], font=(BODY, 9),
                          wraplength=WINDOW_WIDTH // 2 - 30).grid(row=number // 2, column=number % 2, sticky="nsew", padx=(0 if number % 2 == 0 else 2, 2 if number % 2 == 0 else 0), pady=(0, 2))
        self.note = tk.Label(parent, text="", bg=colors["background"], fg=colors["text"], justify="left", wraplength=WINDOW_WIDTH - 24, font=(BODY, 9, "bold"))
        self.note.pack(anchor="w")
        tk.Label(parent, text=self.t("Поиск откроется в вашем браузере, на сайте вы ищете сами. Программа к сайту не обращается."), bg=colors["background"], fg=colors["soft"], justify="left", wraplength=WINDOW_WIDTH - 24, font=(BODY, 8)).pack(anchor="w", pady=(6, 0))

    def _add_mods(self, parent, mods: list, preselected: list) -> None:
        """All the mods on one canvas. On Windows every widget is a window of its own, and four of them to a row were what made the panel slow to open.
        A long list on a small screen scrolls, or the buttons below it would leave the screen and could not be reached."""
        colors = self.colors
        area = tk.Frame(parent, bg=colors["background"])
        area.pack(fill="x", pady=(0, 3))
        canvas = tk.Canvas(area, bg=colors["background"], highlightthickness=0, bd=0, height=1, yscrollincrement=self.ROW_HEIGHT // 2, width=WINDOW_WIDTH - 24)
        self.fonts = (tkfont.Font(canvas, family=BODY, size=10), tkfont.Font(canvas, family=BODY, size=10, weight="bold"), tkfont.Font(canvas, family=BODY, size=9), tkfont.Font(canvas, family=BODY, size=8, weight="bold"))  # Tk forgets a font once Python lets go of it
        fit = mod_rows_that_fit(self.window.winfo_screenheight(), self.ROW_HEIGHT)
        scrolls = len(mods) > fit
        width = WINDOW_WIDTH - 24 - (SCROLLBAR_WIDTH + 3 if scrolls else 0)
        top = 0
        for number, mod in enumerate(mods):
            chosen = tk.BooleanVar(value=mod in preselected)
            self.checks.append(chosen)
            top = self._draw_mod(canvas, number, mod, chosen, top, width)
        canvas.configure(height=min(top, fit * self.ROW_HEIGHT) if scrolls else max(top, 1), scrollregion=(0, 0, width, top))
        if scrolls:
            self.mods_canvas = canvas
            bar = SlimScrollbar(area, canvas.yview, colors["panel"], colors["soft"])
            canvas.configure(yscrollcommand=bar.set)
            bar.pack(side="right", fill="y", padx=(3, 0))
            canvas.bind("<MouseWheel>", self._scroll_mods)
        canvas.pack(side="left", fill="x", expand=True)

    def _scroll_mods(self, event) -> str:
        self.mods_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"  # the main window must not scroll with it

    def _section(self, parent, text: str) -> tk.Label:
        label = tk.Label(parent, text=self.t(text), bg=self.colors["background"], fg=self.colors["accent"], font=(BODY, 9, "bold"))
        label.pack(anchor="w", pady=(0, 4))
        return label

    def _draw_mod(self, canvas: tk.Canvas, number: int, mod, chosen: tk.BooleanVar, top: int, width: int) -> int:
        """One row, with its numbers in bold, the way players read mods. Returns where the next row starts."""
        colors = self.colors
        small, chip = self.fonts[2:]
        shown, ranges = split_ranges(mod.label)
        share = roll_share(mod.label)
        ranges = f"{ranges} · {share:.0%}" if share is not None else ranges
        if self.hints.get(mod.label):
            ranges = f"{ranges}  {self.hints[mod.label]}"
        if not mod.stats:
            item = canvas.create_text(9, top, text=shown, fill=colors["soft"], font=small, anchor="nw", width=width - 18)
            return canvas.bbox(item)[3] + 3
        tag = f"mod{number}"
        back = canvas.create_rectangle(0, top, width - 1, top + 30, tags=(tag,), width=1)
        left = 9
        badge = None
        if mod.tier:
            badge = canvas.create_rectangle(left, top + 6, left + 26, top + 22, fill=colors["tile"], outline="", tags=(tag,))
            canvas.create_text(left + 13, top + 14, text=f"T{mod.tier}", font=chip, tags=(tag, f"{tag}words"))
            left += 34
        canvas.create_text(width - 9, top + 15, text=ranges, font=small, anchor="e", tags=(tag, f"{tag}words"))
        room = width - 9 - small.measure(ranges) - 8 - left  # the words start after the tier badge, and must stop short of the ranges
        bottom = self._draw_mod_words(canvas, left, top + 6, shown, room, tag)
        bottom = max(bottom + 6, top + 30)
        canvas.coords(back, 0, top, width - 1, bottom)
        if badge:
            middle = (top + bottom) // 2
            canvas.coords(badge, left - 34, middle - 8, left - 8, middle + 8)
            for item in canvas.find_withtag(f"{tag}words"):
                if canvas.itemcget(item, "text") == f"T{mod.tier}":
                    canvas.coords(item, left - 21, middle)

        def paint(*_):
            color, ground = (MOD_ON, MOD_ON_GROUND) if chosen.get() else (MOD_OFF, colors["panel"])
            canvas.itemconfigure(back, fill=ground, outline=colors["border"])
            canvas.itemconfigure(f"{tag}words", fill=color)

        chosen.trace_add("write", paint)
        paint()
        canvas.tag_bind(tag, "<Button-1>", lambda _: chosen.set(not chosen.get()))
        canvas.tag_bind(tag, "<Enter>", lambda _: canvas.itemconfigure(back, outline=colors["soft"]))
        canvas.tag_bind(tag, "<Leave>", lambda _: canvas.itemconfigure(back, outline=colors["border"]))
        canvas.configure(cursor="hand2")
        return bottom + 3

    def _draw_mod_words(self, canvas: tk.Canvas, left: int, top: int, text: str, room: int, tag: str) -> int:
        """The words, word by word so that they wrap, with numbers in bold. Returns the bottom of the last line."""
        normal, bold = self.fonts[0], self.fonts[1]
        line_height = normal.metrics("linespace") + 1
        x, y = left, top
        position = 0
        pieces = []
        for found in NUMBERS.finditer(text):
            pieces += [(word, normal) for word in re.findall(r"\S+\s*", text[position:found.start()])]
            spaces = re.match(r"\s*", text[found.end():]).group()  # the space after a number belongs to it, or «9 до» would be drawn as «9до»
            pieces.append((found.group() + spaces, bold))
            position = found.end() + len(spaces)
        pieces += [(word, normal) for word in re.findall(r"\S+\s*", text[position:])]
        for word, font in pieces:
            size = font.measure(word.rstrip())
            if x > left and x + size > left + room:
                x, y = left, y + line_height
            canvas.create_text(x, y, text=word, font=font, anchor="nw", tags=(tag, f"{tag}words"))
            x += font.measure(word)
        return y + line_height

    def set_art(self, image) -> None:
        """A large picture may arrive after the panel has opened."""
        if image and self.art.winfo_exists():
            self.image = image
            self.art.config(image=image)

    def _paint_search(self, color: str) -> None:
        if self.search_button["state"] == "normal":
            self.search_button.config(bg=color)

    def _set_strictness(self, value: float) -> None:
        self.strictness = value
        for option, button in self.strict_buttons.items():
            active = option == value
            ground, letters = (CHOSEN, ON_CHOSEN) if active else (self.colors["panel"], self.colors["soft"])
            button.config(bg=ground, fg=letters, activebackground=CHOSEN, activeforeground=ON_CHOSEN, font=(BODY, 9, "bold" if active else "normal"))

    def _set_any_base(self, value: bool) -> None:
        self.any_base = value
        for option, button in self.base_buttons.items():
            active = option == value
            ground, letters = (CHOSEN, ON_CHOSEN) if active else (self.colors["panel"], self.colors["soft"])
            button.config(bg=ground, fg=letters, activebackground=CHOSEN, activeforeground=ON_CHOSEN, font=(BODY, 9, "bold" if active else "normal"))

    def show_note(self, text: str) -> None:
        if self.note.winfo_exists():
            self.note.config(text=text)

    def selected_mods(self) -> list:
        return [mod for mod, chosen in zip(self.mods, self.checks) if chosen.get()]

    def _search(self) -> None:
        self.on_search(self.selected_mods(), self.strictness)

    def _bookmark(self) -> None:
        self.on_bookmark(self.selected_mods(), self.strictness)
        self.bookmark_button.config(text=self.t("★ В закладках"))
