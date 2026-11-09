"""The look of the program: Japan in cherry blossom season, in a choice of three moods.

The colors of paper, ink and blossom live here, along with the ornaments. They are drawn as pictures because
Tk has no textures and its own shapes have jagged edges. The theme is read once at the start, because every
window takes its colors from these constants.
"""
import base64
import zlib
import ctypes
import ctypes.wintypes as wt
import io
import json
import math
import os
import struct
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont

from tray import WNDCLASSW, WNDPROC, LRESULT

TITLE_FONT = "Yu Gothic UI"  # for titles and large prices, and it can write the seal's sign
BODY = "Segoe UI"  # for everything small, where thin strokes are hard to read
SEAL_SIGN = "桜"
SEAL_RED, SEAL_RED_LIGHT, ON_SEAL = "#a8302c", "#c8423c", "#fff2f5"
_NIGHT_COLORS = {
    "text": "#fbf6f7", "soft": "#cfc0c8", "muted": "#a4939d",  # three clear steps: what to read, what explains it, what can be skipped
    "accent": "#f7a8c0", "accent_light": "#fcc8d8", "ink": "#2a1620",  # blossom, and the dark letters that go on it
    "chosen": "#b5375f", "chosen_light": "#cc4c76", "on_chosen": "#fff6f8",  # deep pink marks what is chosen and fills the big buttons
    "up": "#b2e08c", "down": "#ff9e8c",  # matcha and persimmon
    "mod_on": "#ffdbe5", "mod_off": "#968690", "mod_on_ground": "#6e304b",
    "special": {"fractured": "#e9cf8a", "desecrated": "#b3d09a", "crafted": "#a9cbe3"},
    "rarity": {"unique": "#f0a868", "rare": "#f2e08a", "magic": "#b3bcff"},
    "dark_title": True, "blossom": (242, 167, 189), "bark": (92, 66, 74), "petal_strength": 0.10,
}
THEMES = {
    "yozakura": {**_NIGHT_COLORS, "titles": ("Ночная сакура", "Night sakura"),  # blossoms under the moon on plum dark paper
                 "bg": "#171219", "sidebar": "#0f0c11", "panel": "#302534", "tile": "#0e0b10", "raised": "#453649", "border": "#64505f", "thumb": "#947c8d",
                 "paper": (40, 31, 43), "fibers": 7, "title_bar": "#0f0c11"},
    "sumi": {**_NIGHT_COLORS, "titles": ("Тушь", "Ink"),  # black ink on grey paper, the blossom as the only color
             "bg": "#121214", "sidebar": "#0b0b0c", "panel": "#28282b", "tile": "#09090a", "raised": "#3d3d42", "border": "#5a5a60", "thumb": "#85858c",
             "text": "#f8f6f4", "soft": "#c9c6c2", "muted": "#9d9a96", "accent": "#f49fb8", "chosen": "#a8325a", "chosen_light": "#bf4670", "mod_on_ground": "#642c44",
             "paper": (34, 34, 37), "fibers": 7, "title_bar": "#0b0b0c", "blossom": (244, 159, 184), "bark": (70, 66, 68)},
    "washi": {"titles": ("Васи", "Washi"),  # handmade paper in evening light: dark letters on a middle tone
              "bg": "#aa9ca0", "sidebar": "#98898f", "panel": "#c6bab9", "tile": "#8d7f83", "raised": "#ded5d3", "border": "#74666b", "thumb": "#5b4d52",
              "text": "#150c10", "soft": "#33262c", "muted": "#3a2c32",
              "accent": "#701a38", "accent_light": "#8c2a4a", "ink": "#fbeef2", "chosen": "#7a1a3c", "chosen_light": "#962c50", "on_chosen": "#fff4f7",
              "up": "#1b4712", "down": "#771616", "mod_on": "#3a0a1d", "mod_off": "#51444a", "mod_on_ground": "#f4cfdb",
              "special": {"fractured": "#5a4208", "desecrated": "#235219", "crafted": "#17405c"},
              "rarity": {"unique": "#6e2f06", "rare": "#4f3c04", "magic": "#222d80"},
              "paper": (184, 171, 172), "fibers": -8, "title_bar": "#98898f", "dark_title": False,
              "blossom": (168, 62, 96), "bark": (74, 52, 56), "petal_strength": 0.12},
    "murasaki": {**_NIGHT_COLORS, "titles": ("Мурасаки", "Murasaki"),  # deep violet night from the player's five colours, #0C0032 #190061 #240090 #3500D3 #282828
                 "bg": "#0c0032", "sidebar": "#190061", "panel": "#240090", "tile": "#282828", "raised": "#3a2a9e", "border": "#5a46c8", "thumb": "#8c7ce0",
                 "text": "#f4f1ff", "soft": "#cdc6f4", "muted": "#958cc8", "accent": "#b3a5ff", "accent_light": "#d0c8ff", "ink": "#0c0032",
                 "chosen": "#3500d3", "chosen_light": "#4a1ff0", "on_chosen": "#ffffff", "mod_on": "#ffffff", "mod_off": "#a79fd8", "mod_on_ground": "#3500d3",
                 "paper": (14, 3, 56), "fibers": 7, "title_bar": "#0c0032", "blossom": (179, 165, 255), "bark": (60, 46, 140)},
    "kin": {**_NIGHT_COLORS, "titles": ("Золото", "Gold"),  # black lacquer and gold leaf, from the player's picture
            "bg": "#0b0a09", "sidebar": "#15130f", "panel": "#27231c", "tile": "#0f0e0c", "raised": "#3d3529", "border": "#564a37", "thumb": "#8c7a58",
            "text": "#f4ede0", "soft": "#d2c7b2", "muted": "#9d927e", "accent": "#d9ab4f", "accent_light": "#ecc97e", "ink": "#1a1307",
            "chosen": "#c4973e", "chosen_light": "#d8ae58", "on_chosen": "#17110a", "mod_on": "#fff1d2", "mod_off": "#9d927e", "mod_on_ground": "#5c4418",
            "paper": (20, 18, 16), "fibers": 7, "title_bar": "#080706", "blossom": (217, 171, 79), "bark": (96, 78, 44), "brand": "#e0b55a"},
}
DEFAULT_THEME = "kin"  # what a new player sees first
EARLIER_DEFAULT = "yozakura"  # a player from before Gold who never picked a theme keeps the one they have always had


def theme_named(name) -> str:
    """Whatever a damaged settings file holds, the program starts in some theme."""
    return name if isinstance(name, str) and name in THEMES else DEFAULT_THEME


def _chosen_theme() -> str:
    """POE_CRAFTER_THEME tries a theme out without saving it."""
    folder = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    try:
        settings = json.loads((folder / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = None
    if os.environ.get("POE_CRAFTER_THEME"):
        return theme_named(os.environ["POE_CRAFTER_THEME"])
    if isinstance(settings, dict):  # settings from before: their theme, or the one that was the default then
        return theme_named(settings.get("theme") or EARLIER_DEFAULT)
    return DEFAULT_THEME  # a new player: no settings yet


ACTIVE_THEME = _chosen_theme()
_theme = THEMES[ACTIVE_THEME]
BG, SIDEBAR, PANEL, TILE, RAISED, BORDER, THUMB = (_theme[key] for key in ("bg", "sidebar", "panel", "tile", "raised", "border", "thumb"))
TEXT, SOFT, MUTED = _theme["text"], _theme["soft"], _theme["muted"]
BRAND = _theme.get("brand", TEXT)  # the program's name in the banner; gold in the gold theme
ACCENT, ACCENT_LIGHT, INK = _theme["accent"], _theme["accent_light"], _theme["ink"]
CHOSEN, CHOSEN_LIGHT, ON_CHOSEN = _theme["chosen"], _theme["chosen_light"], _theme["on_chosen"]
UP_COLOR, DOWN_COLOR = _theme["up"], _theme["down"]
MOD_ON, MOD_OFF, MOD_ON_GROUND = _theme["mod_on"], _theme["mod_off"], _theme["mod_on_ground"]
SWITCH_TRACK_OFF = BORDER
SPECIAL_MOD_COLORS = _theme["special"]
RARITY_COLORS = {name: _theme["rarity"][kind] for name, kind in (("unique", "unique"), ("уникальный", "unique"), ("rare", "rare"), ("редкий", "rare"), ("magic", "magic"), ("волшебный", "magic"))}
ORNAMENT_SCALE = 4
WAVES_HEIGHT = 14
WAVES_LENGTH = 3000  # longer than any screen; a window only shows part of it
BANNER_HEIGHT = 64
SEAL_SIZE = 34
PAPER_SIZE = (2600, 900)
PAPER_PETALS = 420
PAPER_FIBERS = 2600
PAPER_VARIANTS = 5  # enough different cuts that neighbouring cards do not look stamped
DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR = 20, 35, 36

LOADING_SIZE = (560, 320)
LOADING_BRANCH_HEIGHT = 92
LOADING_SEAL_SIZE = 46
LOADING_PETALS = 30
LOADING_PETAL_FRAMES = 12
LOADING_PETAL_MARGIN = 14  # how far beyond the edge a petal goes before it comes round again
LOADING_DEPTHS = ((4.0, 150, 0.7), (6.0, 205, 1.0), (8.5, 255, 1.4))  # far to near: size, opacity, speed
LOADING_FRAME_SECONDS = 0.016
LOADING_POLL_MS = 15
LOADING_LONGEST_WAIT = 3  # how long the main thread waits to see the screen up before going on regardless
LOADING_TEXT_WIDTH = 500
LOADING_WINDOW_CLASS = "SakuyaLoading"
WS_POPUP, SW_SHOWNOACTIVATE, LWA_ALPHA, PM_REMOVE = 0x80000000, 4, 2, 1
LOADING_FADE_SECONDS = 0.22
LOADING_HOLD_SHARE = 0.9  # the bar waits here until the program is really ready
WAVE_STEP_SECONDS = 0.012  # along a line
WAVE_LINE_SECONDS = 0.04  # Only what lies between the moving cards is redrawn, so a wave running down in a narrow band costs less than one across the whole window
WAVE_CARD_SECONDS = 0.18
WAVE_WORDS_AT = 0.5  # how far through its slide a card gets its text. By then it is almost in place
WAVE_SLIDE_PIXELS = 18
WAVE_FRAME_MS = 11
DRIFT_PETALS = 10  # few, so they stay a mood and do not pull the eye
DRIFT_OPACITY = 0.55
DRIFT_FRAME_MS = 16
DRIFT_LEAST_WAIT_MS = 5
DRIFT_ASLEEP_MS = 250  # how soon they notice that the window is in front again
FINE_TIMER_SECONDS, FINE_TIMER_CHECK_MS = 0.3, 300
_fine_timer_on, _fine_timer_until, _short_move_until = False, 0.0, 0.0
_winmm = ctypes.WinDLL("winmm") if hasattr(ctypes, "WinDLL") else None
GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST = 0x00080000, 0x00000020, 0x08000000, 0x00000080, 0x00000008
GA_ROOT, GW_HWNDPREV = 2, 3
HWND_TOP, HWND_TOPMOST = 0, -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_NOOWNERZORDER = 0x0001, 0x0002, 0x0010, 0x0200

_user32 = ctypes.WinDLL("user32") if hasattr(ctypes, "WinDLL") else None  # its own copy, so the argument types set here reach no other module
if _user32:
    _user32.GetAncestor.argtypes = (ctypes.c_void_p, ctypes.c_uint)
    _user32.GetAncestor.restype = ctypes.c_void_p
    _user32.GetWindow.argtypes = (ctypes.c_void_p, ctypes.c_uint)
    _user32.GetWindow.restype = ctypes.c_void_p
    _user32.GetWindowLongW.argtypes = (ctypes.c_void_p, ctypes.c_int)
    _user32.SetWindowLongW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_long)
    _user32.SetWindowPos.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint)
_screen_user32 = ctypes.WinDLL("user32") if hasattr(ctypes, "WinDLL") else None  # the loading screen's own copies, for the same reason
_screen_gdi32 = ctypes.WinDLL("gdi32") if hasattr(ctypes, "WinDLL") else None
_screen_kernel32 = ctypes.WinDLL("kernel32") if hasattr(ctypes, "WinDLL") else None
if _screen_user32:
    _screen_user32.DefWindowProcW.argtypes = (wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
    _screen_user32.DefWindowProcW.restype = LRESULT
    _screen_user32.RegisterClassW.argtypes = (ctypes.POINTER(WNDCLASSW),)
    _screen_user32.RegisterClassW.restype = wt.ATOM
    _screen_user32.CreateWindowExW.argtypes = (wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID)
    _screen_user32.CreateWindowExW.restype = wt.HWND
    _screen_user32.SetLayeredWindowAttributes.argtypes = (wt.HWND, wt.DWORD, ctypes.c_ubyte, wt.DWORD)
    _screen_user32.ShowWindow.argtypes = (wt.HWND, ctypes.c_int)
    _screen_user32.GetDC.argtypes = (wt.HWND,)
    _screen_user32.GetDC.restype = wt.HDC
    _screen_user32.DestroyWindow.argtypes = (wt.HWND,)
    _screen_user32.PeekMessageW.argtypes = (ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT)
    _screen_user32.TranslateMessage.argtypes = (ctypes.POINTER(wt.MSG),)
    _screen_user32.DispatchMessageW.argtypes = (ctypes.POINTER(wt.MSG),)
    _screen_user32.DispatchMessageW.restype = LRESULT
    _screen_kernel32.GetModuleHandleW.argtypes = (wt.LPCWSTR,)
    _screen_kernel32.GetModuleHandleW.restype = wt.HMODULE
    _screen_gdi32.SetDIBitsToDevice.argtypes = (wt.HDC, ctypes.c_int, ctypes.c_int, wt.DWORD, wt.DWORD, ctypes.c_int, ctypes.c_int, wt.UINT, wt.UINT, ctypes.c_char_p, ctypes.c_char_p, wt.UINT)
_images: dict[tuple, tk.PhotoImage] = {}
_prepared_waves: dict[tuple, str] = {}
_paper: np.ndarray | None = None


def trace_while(variable: tk.Variable, owner: tk.Misc, callback) -> None:
    """Calls back on every change of the variable for as long as the owner widget lives. Tcl holds a trace, the trace holds the variable and whatever the
    callback reaches, so a trace left behind would keep a whole rebuilt page in memory, once for each change of language or theme."""
    name = variable.trace_add("write", callback)

    def let_go(event) -> None:
        if event.widget is owner and name in (variable._tclCommands or ()):
            variable.trace_remove("write", name)
    owner.bind("<Destroy>", let_go, add="+")


def _png(image: Image.Image) -> str:
    output = io.BytesIO()
    image.save(output, "PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def _as_photo(image: Image.Image) -> tk.PhotoImage:
    return tk.PhotoImage(data=_png(image))


def _draw_petal(draw: ImageDraw.ImageDraw, x: float, y: float, size: float, angle: float, color: tuple) -> None:
    """A single fallen petal: a rounded teardrop with a small notch at its wide end."""
    points = []
    for step in range(16):
        turn = step / 16 * 2 * math.pi
        radius = size * (0.55 + 0.45 * math.cos(turn)) * (0.82 if abs(math.sin(turn)) < 0.12 and math.cos(turn) > 0 else 1)
        across = radius * math.cos(turn)
        along = radius * math.sin(turn) * 0.72
        points.append((x + across * math.cos(angle) - along * math.sin(angle), y + across * math.sin(angle) + along * math.cos(angle)))
    draw.polygon(points, fill=color)


def _draw_blossom(draw: ImageDraw.ImageDraw, x: float, y: float, size: float, turn: float, petal: tuple, heart: tuple) -> None:
    """Five petals around a dark heart."""
    for number in range(5):
        angle = turn + number * 2 * math.pi / 5
        _draw_petal(draw, x + math.cos(angle) * size * 0.72, y + math.sin(angle) * size * 0.72, size * 0.86, angle, petal)
    radius = size * 0.22
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=heart)


def paper_pixels(width: int, height: int, seed: int = 7, theme: str | None = None) -> np.ndarray:
    """Washi: soft clouds, long fibers and a scatter of faint petals, gentle because prices and names are read on top."""
    chosen = THEMES[theme or ACTIVE_THEME]
    random = np.random.default_rng(seed)
    coarse = Image.fromarray((random.random((7, 7)) * 255).astype("uint8")).resize((width, height), Image.BICUBIC)
    clouds = np.asarray(coarse, dtype=np.float32) / 255
    fibers = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(fibers)
    area = width * height / (PAPER_SIZE[0] * PAPER_SIZE[1])
    for _ in range(max(int(PAPER_FIBERS * area), 40)):
        x, y = random.random() * width, random.random() * height
        length, angle = 12 + random.random() * 46, random.random() * math.pi
        bend = (random.random() - 0.5) * 14
        draw.line([(x, y), (x + math.cos(angle) * length / 2 - bend, y + math.sin(angle) * length / 2 + bend), (x + math.cos(angle) * length, y + math.sin(angle) * length)],
                  fill=int(90 + random.random() * 165))
    strands = np.asarray(fibers, dtype=np.float32) / 255
    base = np.array(chosen["paper"], dtype=np.float32) + (chosen["fibers"] * (0.5 * clouds + strands))[..., None]
    image = Image.fromarray(np.clip(base, 0, 255).astype("uint8")).convert("RGBA")
    petals = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(petals)
    alpha = int(255 * chosen["petal_strength"])
    for _ in range(max(int(PAPER_PETALS * area), 8)):
        _draw_petal(draw, random.random() * width, random.random() * height, 3 + random.random() * 5, random.random() * 2 * math.pi, (*chosen["blossom"], alpha))
    image.alpha_composite(petals)
    return np.asarray(image.convert("RGB"))


def _paper_cut(width: int, height: int, variant: int) -> Image.Image:
    global _paper
    if _paper is None:
        _paper = paper_pixels(*PAPER_SIZE)
    total_height, total_width = _paper.shape[:2]
    if width >= total_width or height >= total_height:
        return Image.fromarray(_paper).resize((width, height), Image.BICUBIC)
    left, top = variant * 487 % (total_width - width), variant * 211 % (total_height - height)
    return Image.fromarray(_paper[top:top + height, left:left + width])


def paper_variant(name: str) -> int:
    """Which cut of paper a card has. It goes by the name, so a card keeps its paper and what is baked into it wherever the card moves in the list."""
    return zlib.crc32(name.encode("utf-8")) % PAPER_VARIANTS


def paper_piece(width: int, height: int, variant: int, box: tuple[int, int, int, int]) -> Image.Image:
    """A part of a sheet of paper, to lay a picture on so that it needs no blending."""
    key = ("paper picture", width, height, variant % PAPER_VARIANTS)
    if key not in _images:
        _images[key] = _paper_cut(width, height, variant % PAPER_VARIANTS).convert("RGB")
    return _images[key].crop(box)


def paper_image(width: int, height: int, variant: int = 0) -> tk.PhotoImage:
    """A sheet of paper for a card. Only a few cuts of each size exist, so hundreds of rows cost little."""
    key = ("paper", width, height, variant % PAPER_VARIANTS)
    if key not in _images:
        _images[key] = _as_photo(_paper_cut(width, height, variant % PAPER_VARIANTS))
    return _images[key]


def _branch_layer(width: int, height: int, theme: str | None = None) -> Image.Image:
    """The branch alone on a clear picture, at ORNAMENT_SCALE times the asked size."""
    scale = ORNAMENT_SCALE
    random = np.random.default_rng(11)
    chosen = THEMES[theme or ACTIVE_THEME]
    layer = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    bark, blossom = (*chosen["bark"], 255), chosen["blossom"]
    petal_light = tuple(min(channel + 26, 255) for channel in blossom) + (255,)
    heart = tuple(int(channel * 0.55) for channel in blossom) + (255,)
    reach = min(width * 0.62, 620) * scale
    right, top, bottom = width * scale, height * scale * 0.04, height * scale
    points = []
    for step in range(25):
        share = step / 24
        wave = math.sin(share * 7.5) * height * scale * 0.09
        points.append((right - reach * share, top + height * scale * (0.16 + 0.42 * share ** 1.5) + wave))
    for start, end in zip(points, points[1:]):
        share = points.index(start) / 24
        draw.line([start, end], fill=bark, width=max(int((5.5 - 4.5 * share) * scale / 2), 2))
    spots = []
    for index, (x, y) in enumerate(points):
        if index and index % 3 == 0:
            direction = -1 if index % 6 == 0 else 1
            length = (0.20 + random.random() * 0.26) * height * scale
            lean = (0.4 + random.random() * 0.7) * length
            tip = (x - lean, y + direction * length)
            draw.line([(x, y), tip], fill=bark, width=max(scale // 2, 2))
            spots.append(tip)
        if index % 2 == 0:
            spots.append((x + (random.random() - 0.5) * 12 * scale, y + (random.random() - 0.5) * 12 * scale))
    for x, y in spots:
        if 0 <= y <= bottom:
            _draw_blossom(draw, x, y, (3.2 + random.random() * 2.2) * scale, random.random() * 6.3, petal_light if random.random() < 0.45 else (*blossom, 255), heart)
    for _ in range(14):
        _draw_petal(draw, right - reach * (0.2 + random.random() * 1.1), random.random() * bottom, (1.8 + random.random() * 1.8) * scale, random.random() * 6.3, (*blossom, 190))
    return layer


def branch_image(width: int, height: int = BANNER_HEIGHT) -> tk.PhotoImage:
    """A cherry branch reaching in from the top right, in bloom, with a few petals falling. Made once for each size."""
    key = ("banner", width, height)
    if key not in _images:
        base = _paper_cut(width, height, 1).convert("RGBA").resize((width * ORNAMENT_SCALE, height * ORNAMENT_SCALE), Image.BICUBIC)
        base.alpha_composite(_branch_layer(width, height))
        _images[key] = _as_photo(base.resize((width, height), Image.LANCZOS).convert("RGB"))
    return _images[key]


def add_branch(parent: tk.Misc, width: int, height: int = 26) -> tk.Label:
    """A small branch over a window of fixed width."""
    key = ("branch", width, height)
    if key not in _images:
        _images[key] = branch_image(width, height)
    label = tk.Label(parent, image=_images[key], bd=0)
    label.pack()
    return label


def seal_image(size: int = SEAL_SIZE) -> tk.PhotoImage:
    """A square red seal, as an artist stamps a painting. Its sign is written on it by the window."""
    key = ("seal", size)
    if key not in _images:
        _images[key] = _as_photo(_seal_picture(size))
    return _images[key]


def _seal_picture(size: int) -> Image.Image:
    scale = ORNAMENT_SCALE
    image = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    ImageDraw.Draw(image).rounded_rectangle((0, 0, size * scale - 1, size * scale - 1), radius=5 * scale, fill=ImageColor.getrgb(SEAL_RED))
    return image.resize((size, size), Image.LANCZOS)


def _waves_picture(color: str, height: int, length: int) -> Image.Image:
    """Seigaiha, the blue ocean wave pattern: rows of overlapping fans of arcs."""
    scale = ORNAMENT_SCALE
    width_px, height_px = length * scale, height * scale
    image = Image.new("RGBA", (width_px, height_px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = height_px * 0.62
    rings = (1.0, 0.68, 0.36)
    line = max(int(height_px / 22), 2)
    step = radius * 2
    rows = [(height_px * 1.02, 0.0), (height_px * 0.72, radius)]
    for center_y, shift in rows:
        x = -step + shift
        while x < width_px + step:
            for ring in rings:
                size = radius * ring
                box = (x - size, center_y - size, x + size, center_y + size)
                if ring == 1.0:
                    draw.pieslice(box, 180, 360, fill=(0, 0, 0, 0))
                draw.arc(box, 180, 360, fill=color, width=line)
            x += step
    return image.resize((length, height), Image.LANCZOS)


def prepare_art() -> None:
    """The slowest pictures, made without touching Tk, so a worker can do this while the loading screen keeps moving."""
    global _paper
    if _paper is None:
        _paper = paper_pixels(*PAPER_SIZE)
    key = (ACCENT, WAVES_HEIGHT, WAVES_LENGTH)
    if key not in _prepared_waves:
        _prepared_waves[key] = _png(_waves_picture(*key))


def waves_image(color: str, height: int = WAVES_HEIGHT, length: int = WAVES_LENGTH) -> tk.PhotoImage:
    key = ("waves", color, height, length)
    if key not in _images:
        prepared = _prepared_waves.get((color, height, length))
        _images[key] = tk.PhotoImage(data=prepared) if prepared else _as_photo(_waves_picture(color, height, length))
    return _images[key]


def add_waves(parent: tk.Misc, ground: str, color: str = ACCENT, **pack) -> tk.Frame:
    """A band of waves across the parent. The picture is much longer than the band, so it never widens the window."""
    band = tk.Frame(parent, bg=ground, height=WAVES_HEIGHT)
    band.pack_propagate(False)
    tk.Label(band, image=waves_image(color), bg=ground, bd=0).place(x=0, y=0)
    band.pack(fill="x", **pack)
    return band


def add_ground(parent: tk.Misc) -> tk.Frame:
    """A thin line of blossom along the bottom of the window."""
    ground = tk.Frame(parent, bg=BG)
    tk.Frame(ground, bg=BORDER, height=1).pack(fill="x")
    tk.Frame(ground, bg=ACCENT, height=2).pack(fill="x")
    return ground


def _moon_scene(draw: ImageDraw.ImageDraw, scale: int, width: int, height: int) -> None:
    """Night sakura: a pale moon with a soft ring of light."""
    x, y = 92 * scale, 74 * scale
    for radius in range(70, 36, -1):  # each smaller ring replaces the one below it, so the light grows evenly toward the moon
        alpha = int(62 * ((70 - radius) / 34) ** 2)
        draw.ellipse((x - radius * scale, y - radius * scale, x + radius * scale, y + radius * scale), fill=(250, 232, 226, alpha))
    radius = 36 * scale
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(250, 240, 228, 235))


def _mountains_scene(draw: ImageDraw.ImageDraw, scale: int, width: int, height: int) -> None:
    """Ink: mountains washed in with a wet brush, paler the further away they stand."""
    for level, alpha, wave, phase in ((0.56, 60, 34, 0.4), (0.68, 100, 26, 2.1), (0.8, 150, 18, 4.0)):
        ridge = [(x, height * level + (math.sin(x / width * 9 + phase) + 0.5 * math.sin(x / width * 23 + phase * 2)) * wave * scale) for x in range(0, width + scale, 8 * scale)]
        draw.polygon([*ridge, (width, height), (0, height)], fill=(6, 6, 8, alpha))


def _sun_scene(draw: ImageDraw.ImageDraw, scale: int, width: int, height: int) -> None:
    """Washi: a red evening sun, stamped on the paper."""
    x, y, radius = 92 * scale, 84 * scale, 44 * scale
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(164, 42, 48, 215))


LOADING_SCENES = {"yozakura": _moon_scene, "sumi": _mountains_scene, "washi": _sun_scene, "murasaki": _moon_scene, "kin": _mountains_scene}


def loading_background(theme: str) -> Image.Image:
    """The still part of the loading screen: paper, the theme's own scene, the branch and a band of waves."""
    width, height = LOADING_SIZE
    chosen, scale = THEMES[theme], ORNAMENT_SCALE
    image = Image.fromarray(paper_pixels(width, height, seed=3, theme=theme)).convert("RGBA")
    scene = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
    LOADING_SCENES[theme](ImageDraw.Draw(scene), scale, width * scale, height * scale)
    image.alpha_composite(scene.resize((width, height), Image.LANCZOS))
    branch = _branch_layer(width, LOADING_BRANCH_HEIGHT, theme)
    image.alpha_composite(branch.resize((width, LOADING_BRANCH_HEIGHT), Image.LANCZOS))
    image.alpha_composite(_waves_picture(chosen["accent"], WAVES_HEIGHT, width), (0, height - WAVES_HEIGHT - 3))
    return image.convert("RGB")


def _petal_colors(theme: str) -> tuple[tuple, ...]:
    blossom = THEMES[theme]["blossom"]
    lighter = tuple(min(channel + 34, 255) for channel in blossom)
    return ((*blossom,), lighter, (206, 202, 198)) if theme == "sumi" else ((*blossom,), lighter)


def petal_frames(size: float, opacity: int, color: tuple) -> list[Image.Image]:
    """One petal tumbling through the air: it turns and, seen edge on, grows thin."""
    scale, box = ORNAMENT_SCALE, int(size * 3)
    frames = []
    for number in range(LOADING_PETAL_FRAMES):
        turn = number / LOADING_PETAL_FRAMES * 2 * math.pi
        image = Image.new("RGBA", (box * scale, box * scale), (0, 0, 0, 0))
        _draw_petal(ImageDraw.Draw(image), box * scale / 2, box * scale / 2, size * scale, turn, (*color, opacity))
        frames.append(image.resize((box, max(int(box * (0.45 + 0.55 * abs(math.cos(turn)))), 2)), Image.LANCZOS))
    return frames


def falling_petals(count: int, colors: int, seed: int = 5) -> list[dict]:
    random = np.random.default_rng(seed)
    petals = []
    for number in range(count):
        depth = number % len(LOADING_DEPTHS)
        speed = LOADING_DEPTHS[depth][2]
        petals.append({"depth": depth, "color": int(random.integers(colors)), "x": random.random(), "y": random.random(), "fall": (20 + random.random() * 14) * speed, "drift": (-16 - random.random() * 10) * speed,
                       "sway": 8 + random.random() * 14, "pace": 0.8 + random.random() * 0.9, "phase": random.random() * 6.3, "spin": 2.5 + random.random() * 5})
    return petals


def petal_place(petal: dict, seconds: float, width: int = LOADING_SIZE[0], height: int = LOADING_SIZE[1]) -> tuple[float, float, int]:
    """Where a petal is at a moment, and which frame it shows. It depends only on the time, so a busy moment makes petals skip, never crawl."""
    margin = LOADING_PETAL_MARGIN
    x = (petal["x"] * width + petal["drift"] * seconds + petal["sway"] * math.sin(petal["pace"] * seconds + petal["phase"])) % (width + 2 * margin) - margin
    y = (petal["y"] * height + petal["fall"] * seconds) % (height + 2 * margin) - margin
    return x, y, int(petal["spin"] * seconds + petal["phase"] * 2) % LOADING_PETAL_FRAMES


def _font(size: int, *names: str):
    """A font from Windows' own folder, or None on a system without them."""
    for name in names:
        try:
            return ImageFont.truetype(str(Path(os.environ.get("WINDIR", r"C:\\Windows")) / "Fonts" / name), size)
        except OSError:
            continue
    return None


def _wrapped(text: str, font, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and font.getlength(trial) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return [*lines, line]


@dataclass(frozen=True)
class LoadingPicture:
    background: Image.Image
    words: Image.Image  # stays above the petals, so they never cross what is to be read


def loading_picture(theme: str, title: str, lines: tuple[str, ...]) -> LoadingPicture:
    """The still parts of the loading screen: the scene, the same seal and name as on top of the main window, and the lines under them."""
    chosen = THEMES[theme]
    width, height = LOADING_SIZE
    background = loading_background(theme)
    ImageDraw.Draw(background).rectangle((0, 0, width - 1, height - 1), outline=chosen["border"])
    words = Image.new("RGBA", LOADING_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(words)
    name_font = _font(35, "YuGothB.ttc", "segoeuib.ttf")
    sign_font = _font(31, "YuGothB.ttc", "msgothic.ttc")
    line_font = _font(14, "segoeui.ttf", "tahoma.ttf")
    middle = 132
    if name_font:
        name_width = name_font.getlength(title)
        left = (width - LOADING_SEAL_SIZE - 14 - name_width) / 2
        seal = _seal_picture(LOADING_SEAL_SIZE)
        words.paste(seal, (int(left), middle - LOADING_SEAL_SIZE // 2), seal)
        if sign_font:
            draw.text((left + LOADING_SEAL_SIZE / 2, middle), SEAL_SIGN, fill=ON_SEAL, font=sign_font, anchor="mm")
        draw.text((left + LOADING_SEAL_SIZE + 14, middle), title, fill=chosen.get("brand", chosen["text"]), font=name_font, anchor="lm")
    if line_font:
        top = 178
        for line in lines:
            for part in _wrapped(line, line_font, LOADING_TEXT_WIDTH):
                draw.text((width / 2, top), part, fill=chosen["text"], font=line_font, anchor="ma")
                top += 20
            top += 6
    return LoadingPicture(background, words)


class LoadingScreen:
    """Blossom falling past the program's seal, in the colors of the given theme. It stays until finish() and at least for its seconds.
    It is a plain Windows window drawn from finished pictures on a thread of its own, with no Tk in it: nothing the main window is building can stop
    the petals, and a second Tk on another thread was seen to hang for good."""

    def __init__(self, theme: str, title: str, lines: tuple[str, ...], seconds: float):
        self.theme, self.title, self.lines, self.seconds = theme, title, lines, seconds
        self.ready = False
        self.handle = None
        self.fade_started = None
        self.shown, self.time_up, self.may_fade, self.gone = threading.Event(), threading.Event(), threading.Event(), threading.Event()
        threading.Thread(target=self._run, daemon=True).start()
        self.shown.wait(LOADING_LONGEST_WAIT)

    def _run(self) -> None:
        try:
            self._prepare()
            self._open_window()
            self.started = time.monotonic()
            self.shown.set()
            message = wt.MSG()
            while True:
                begun = time.monotonic()
                while _screen_user32.PeekMessageW(ctypes.byref(message), self.handle, 0, 0, PM_REMOVE):
                    _screen_user32.TranslateMessage(ctypes.byref(message))
                    _screen_user32.DispatchMessageW(ctypes.byref(message))
                if not self._frame():
                    break
                time.sleep(max(LOADING_FRAME_SECONDS - (time.monotonic() - begun), 0.001))
            _screen_user32.DestroyWindow(self.handle)
        finally:  # without a loading screen the program still starts
            self.shown.set()
            self.time_up.set()
            self.gone.set()

    def _prepare(self) -> None:
        colors = _petal_colors(self.theme)
        self.picture = loading_picture(self.theme, self.title, self.lines)
        self.sprites = [[petal_frames(size, opacity, color) for color in colors] for size, opacity, _ in LOADING_DEPTHS]
        self.petals = falling_petals(LOADING_PETALS, len(colors))
        self.accent = ImageColor.getrgb(THEMES[self.theme]["accent"])

    def _open_window(self) -> None:
        width, height = LOADING_SIZE
        instance = _screen_kernel32.GetModuleHandleW(None)
        self.procedure = WNDPROC(lambda window, kind, wparam, lparam: _screen_user32.DefWindowProcW(window, kind, wparam, lparam))  # kept, because Windows calls it while the window lives
        window_class = WNDCLASSW(lpfnWndProc=self.procedure, hInstance=instance, lpszClassName=LOADING_WINDOW_CLASS)
        _screen_user32.RegisterClassW(ctypes.byref(window_class))
        self.handle = _screen_user32.CreateWindowExW(WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED, LOADING_WINDOW_CLASS, self.title, WS_POPUP,
                                                     (_screen_user32.GetSystemMetrics(0) - width) // 2, (_screen_user32.GetSystemMetrics(1) - height) // 2, width, height, None, None, instance, None)
        _screen_user32.SetLayeredWindowAttributes(self.handle, 0, 255, LWA_ALPHA)
        _screen_user32.ShowWindow(self.handle, SW_SHOWNOACTIVATE)
        self.device = _screen_user32.GetDC(self.handle)
        self.header = struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0)

    def finish(self, owner: tk.Tk, on_ready) -> None:
        """The work is done. When the screen's time is up, on_ready runs on the main thread, and only then does the screen fade, so the main window is there under it."""
        self.ready = True

        def wait() -> None:
            if not self.time_up.is_set():
                owner.after(LOADING_POLL_MS, wait)
                return
            try:
                on_ready()
                owner.update_idletasks()  # update() would also play out the animations that have just begun, and leave this screen standing over the open window until they end
            finally:
                self.may_fade.set()

        wait()

    def compose(self, seconds: float, share: float) -> Image.Image:
        """One frame: the still picture, the petals behind nothing but the words, which are part of the picture's own top layer, and the bar."""
        frame = self.picture.background.copy()
        for petal in self.petals:
            x, y, number = petal_place(petal, seconds)
            sprite = self.sprites[petal["depth"]][petal["color"]][number]
            frame.paste(sprite, (int(x - sprite.width / 2), int(y - sprite.height / 2)), sprite)
        frame.paste(self.picture.words, (0, 0), self.picture.words)
        width, height = LOADING_SIZE
        if share > 0:
            frame.paste(self.accent, (0, height - 3, int(width * share), height))
        return frame

    def _frame(self) -> bool:
        """Draws one frame. False when the screen has faded away."""
        now = time.monotonic()
        seconds = now - self.started
        share = min(seconds / self.seconds, 1 if self.ready else LOADING_HOLD_SHARE)
        self.last_frame = frame = self.compose(seconds, share)
        width, height = LOADING_SIZE
        _screen_gdi32.SetDIBitsToDevice(self.device, 0, 0, width, height, 0, 0, 0, height, frame.tobytes("raw", "BGRX"), self.header, 0)
        if self.ready and seconds >= self.seconds:
            self.time_up.set()
        if self.may_fade.is_set():
            self.fade_started = self.fade_started or now
            left = 1 - (now - self.fade_started) / LOADING_FADE_SECONDS
            if left <= 0:
                return False
            _screen_user32.SetLayeredWindowAttributes(self.handle, 0, int(255 * left), LWA_ALPHA)
        return True


def keep_timer_fine(widget: tk.Misc, endless: bool = False) -> None:
    """Windows wakes a program only every 15.6 ms unless it asks for better, and no animation can be smoother than that. Better costs the whole machine some power,
    so every frame of an animation asks anew, and the request lapses by itself soon after the last one. Work in the background waits for a short animation, but not for an endless one."""
    global _fine_timer_until, _fine_timer_on, _short_move_until
    _fine_timer_until = time.monotonic() + FINE_TIMER_SECONDS
    if not endless:
        _short_move_until = _fine_timer_until
    if not _fine_timer_on and _winmm:
        _fine_timer_on = True
        _winmm.timeBeginPeriod(1)
        widget._root().after(FINE_TIMER_CHECK_MS, _fine_timer_check, widget._root())


def something_is_moving() -> bool:
    return time.monotonic() < _short_move_until


def _fine_timer_check(root: tk.Misc) -> None:
    global _fine_timer_on
    if time.monotonic() < _fine_timer_until:
        root.after(FINE_TIMER_CHECK_MS, _fine_timer_check, root)
    else:
        _fine_timer_on = False
        _winmm.timeEndPeriod(1)


def wave_delay(column: int, line: int) -> float:
    """When a card's turn comes: the wave runs from the top left, to the right and down."""
    return column * WAVE_STEP_SECONDS + line * WAVE_LINE_SECONDS


def wave_offset(progress: float) -> int:
    """How far left of its place a card still is. It starts fast and settles softly, which hides any unevenness in the frames."""
    return round(WAVE_SLIDE_PIXELS * (1 - min(max(progress, 0.0), 1.0)) ** 3)


def wave_cover_left(left: int, right: int, progress: float) -> int:
    """Where the placeholder's left edge is as it draws aside to the right. Tk cannot fade one item on a canvas, and a solid edge moving is smooth and cheap."""
    return round(left + (right - left) * (1 - (1 - min(max(progress, 0.0), 1.0)) ** 3))


class CardWave:
    """Cards coming onto a list: placeholders at once, then each card is drawn at its moment in the wave and slides into place as its placeholder draws aside.
    Drawing them one by one is what keeps the window moving, so the wave is not only a cover for the work but the way it gets done.
    cards is a list of (left, top, right, bottom, delay), and draw(number) makes a card's items at their final place."""

    def __init__(self, canvas: tk.Canvas, cards: list[tuple], draw, placeholder: str, border: str, on_done=None, clock=time.monotonic):
        self.canvas, self.cards, self.draw, self.on_done, self.clock = canvas, cards, draw, on_done, clock
        self.window = canvas.winfo_toplevel()
        self.job = None
        self.started = clock()
        self.waiting = set(range(len(cards)))
        self.moving: dict[int, int] = {}  # a card in motion, and how far left of its place it is
        self.words: dict[int, list[int]] = {}  # its text, which waits at the card's final place
        for number, (left, top, right, bottom, _) in enumerate(cards):
            canvas.create_rectangle(left + 1, top, right - 1, bottom - 1, fill=placeholder, outline=border, tags=(f"wave_wait{number}",))
        self._tick()

    def stop(self) -> None:
        if self.job:
            self.window.after_cancel(self.job)
            self.job = None

    def _enter(self, number: int) -> None:
        left, top, right, bottom, _ = self.cards[number]
        canvas, cover = self.canvas, f"wave_wait{number}"
        canvas.itemconfigure(cover, state="hidden")  # so that it does not count as a part of the card
        self.draw(number)
        tag = f"wave{number}"
        canvas.addtag_enclosed(tag, left - 2, top - 2, right + 2, bottom + 2)
        canvas.dtag(cover, tag)
        words = [item for item in canvas.find_withtag(tag) if canvas.type(item) == "text"]
        for item in words:  # text is what a redraw of a card spends most on, and moving letters can hardly be read anyway
            canvas.dtag(item, tag)
            canvas.itemconfigure(item, state="hidden")
        self.words[number] = words
        canvas.move(tag, -WAVE_SLIDE_PIXELS, 0)
        canvas.itemconfigure(cover, state="normal")
        canvas.tag_raise(cover)
        self.moving[number] = WAVE_SLIDE_PIXELS

    def _advance(self, number: int, seconds: float) -> None:
        left, top, right, bottom, delay = self.cards[number]
        progress = (seconds - delay) / WAVE_CARD_SECONDS
        canvas, tag, cover = self.canvas, f"wave{number}", f"wave_wait{number}"
        offset = wave_offset(progress)
        if offset != self.moving[number]:
            canvas.move(tag, self.moving[number] - offset, 0)
            self.moving[number] = offset
        if progress >= WAVE_WORDS_AT or progress >= 1:
            for item in self.words.pop(number, ()):
                canvas.itemconfigure(item, state="normal")
        if progress >= 1:
            canvas.delete(cover)
            canvas.dtag(tag)
            del self.moving[number]
        else:
            canvas.coords(cover, wave_cover_left(left + 1, right - 1, progress), top, right - 1, bottom - 1)

    def _next_frame(self, began: float) -> None:
        """Runs once this frame is on screen, since Tk redraws only when no timer is due. The wait is counted from the start of the frame, so that the work is not added to it."""
        self.job = self.window.after(max(WAVE_FRAME_MS - int((self.clock() - began) * 1000), 1), self._tick)

    def _tick(self) -> None:
        self.job = None
        if not self.canvas.winfo_exists():  # a change of language rebuilt the page
            return
        began = self.clock()
        seconds = began - self.started
        try:
            for number in sorted(self.waiting):
                if self.cards[number][4] <= seconds:
                    self.waiting.discard(number)
                    self._enter(number)
            for number in list(self.moving):
                self._advance(number, seconds)
        finally:
            if self.waiting or self.moving:
                keep_timer_fine(self.window)
                self.job = self.window.after_idle(self._next_frame, began)
        if not self.job and self.on_done:
            self.on_done()


def _another_program_in_front() -> bool:
    """No window in front at all happens for a moment in every switch of windows, so it does not count."""
    if not _user32:
        return False
    window = _user32.GetForegroundWindow()
    if not window:
        return False
    owner = wt.DWORD()
    _user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
    return owner.value != os.getpid()


def on_paper_color(frame: Image.Image, ground: str) -> Image.Image:
    """A petal already laid on the color that will be see-through. Whole pixels draw far faster than blended ones, and the soft edge stays."""
    picture = Image.new("RGB", frame.size, ImageColor.getrgb(ground))
    picture.paste(frame, mask=frame.getchannel("A"))
    return picture


class DriftingBlossom:
    """A few petals drifting down the main window, below its banner. Tk cannot draw behind its own widgets,
    so they live in a see-through window just above it, which every click passes through."""

    def __init__(self, owner: tk.Tk):
        self.owner = owner
        self.job = None
        self.started = time.monotonic()
        self.window = tk.Toplevel(owner, bg=BG)
        self.window.withdraw()
        self.window.overrideredirect(True)  # not made transient: Tk then builds a child window, which can never rise above a window that is always on top
        self.window.attributes("-transparentcolor", BG)
        self.window.attributes("-alpha", DRIFT_OPACITY)
        self.canvas = tk.Canvas(self.window, bg=BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        colors = _petal_colors(ACTIVE_THEME)
        self.frames = [[[_as_photo(on_paper_color(frame, BG)) for frame in petal_frames(size, opacity, color)] for color in colors] for size, opacity, _ in LOADING_DEPTHS]
        self.petals = falling_petals(DRIFT_PETALS, len(colors), seed=9)
        self.items = [self.canvas.create_image(-LOADING_PETAL_MARGIN, -LOADING_PETAL_MARGIN, image=self.frames[petal["depth"]][petal["color"]][0]) for petal in self.petals]

    def exists(self) -> bool:
        return bool(self.window.winfo_exists())

    def follow(self) -> None:
        self.owner.update_idletasks()  # a move asked for a moment ago is not in the owner's numbers until this
        self.width, self.height = self.owner.winfo_width(), max(self.owner.winfo_height() - BANNER_HEIGHT, 1)
        self.window.geometry(f"{self.width}x{self.height}+{self.owner.winfo_rootx()}+{self.owner.winfo_rooty() + BANNER_HEIGHT}")

    def start(self) -> None:
        self.follow()
        self.window.deiconify()
        if not self.job:
            self._tick()

    def stop(self) -> None:
        if self.job:
            self.owner.after_cancel(self.job)
            self.job = None
        self.window.withdraw()

    def _tick(self) -> None:
        self.job = None
        if not self.exists():
            return
        if _another_program_in_front():  # most often the game, which should get what these would take
            self.job = self.owner.after(DRIFT_ASLEEP_MS, self._tick)
            return
        _settle_layer(self.window, self.owner)
        began = time.monotonic()
        seconds = began - self.started
        for petal, item in zip(self.petals, self.items):
            x, y, frame = petal_place(petal, seconds, self.width, self.height)
            self.canvas.coords(item, x, y)
            self.canvas.itemconfigure(item, image=self.frames[petal["depth"]][petal["color"]][frame])
        keep_timer_fine(self.owner, endless=True)
        self.job = self.owner.after_idle(self._next_frame, began)

    def _next_frame(self, began: float) -> None:
        """Runs once this frame is on screen. There must always be a real wait here: a timer that is already due when its frame ends would keep Tk's update() from ever returning, and the program calls that."""
        self.job = self.owner.after(max(DRIFT_FRAME_MS - int((time.monotonic() - began) * 1000), DRIFT_LEAST_WAIT_MS), self._tick)


def layer_place(previous: int | None, layer: int, main_on_top: bool) -> int | None:
    """Where the petals must go to lie directly above the main window, under whatever covers it. None when they are there already."""
    if previous == layer:
        return None
    if previous:
        return previous
    return HWND_TOPMOST if main_on_top else HWND_TOP


def _settle_layer(window: tk.Toplevel, owner: tk.Tk) -> None:
    """Asked for on every frame, because Tk makes the real window late and may make it anew, and because other windows come and go. The check costs microseconds."""
    if not _user32:
        return
    layer, main = _user32.GetAncestor(window.winfo_id(), GA_ROOT), _user32.GetAncestor(owner.winfo_id(), GA_ROOT)
    style = _user32.GetWindowLongW(layer, GWL_EXSTYLE)
    wanted = style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
    if style != wanted:
        _user32.SetWindowLongW(layer, GWL_EXSTYLE, wanted)
    place = layer_place(_user32.GetWindow(main, GW_HWNDPREV), layer, bool(_user32.GetWindowLongW(main, GWL_EXSTYLE) & WS_EX_TOPMOST))
    if place is not None:
        _user32.SetWindowPos(layer, place, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_NOOWNERZORDER)


def style_title_bar(handle: int) -> None:
    """A title bar in the theme's color on Windows 11. Older systems ignore the color and keep their own."""
    if not hasattr(ctypes, "windll"):
        return
    dwm = ctypes.windll.dwmapi
    dark = ctypes.c_int(1 if _theme["dark_title"] else 0)
    dwm.DwmSetWindowAttribute(handle, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(dark), ctypes.sizeof(dark))
    for attribute, color in ((DWMWA_CAPTION_COLOR, _theme["title_bar"]), (DWMWA_TEXT_COLOR, TEXT)):
        red, green, blue = ImageColor.getrgb(color)
        value = ctypes.c_int(red | green << 8 | blue << 16)
        dwm.DwmSetWindowAttribute(handle, attribute, ctypes.byref(value), ctypes.sizeof(value))
