"""UI themes: Bloomberg / Notion styles x dark / light, plus up/down colour convention.

Palettes are plain data (testable without Tk). ``apply_ttk`` maps one palette
onto ttk widgets; tk widgets (Text, Label, Canvas) are recoloured by the app.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from typing import Dict, Tuple

STYLES = ("Bloomberg", "Notion")
MODES = ("dark", "light")


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str  # window background
    side: str  # sidebar / header band
    surface: str  # cards, table rows
    surface2: str  # table header, zebra rows, inputs
    border: str
    text: str
    muted: str
    accent: str
    accent_fg: str  # text on accent
    up: str
    down: str
    warn: str
    danger: str
    ok: str
    mono: bool  # use monospace for data (Bloomberg)
    pad: int  # base spacing
    row_h: int  # table row height


# ---- base palettes (up/down filled in by convention below) ---------------
_BASE: Dict[Tuple[str, str], Palette] = {
    ("Bloomberg", "dark"): Palette(
        "Bloomberg 深色", bg="#000000", side="#0a0a0a", surface="#0f0f0f", surface2="#1a1a1a",
        border="#2e2e2e", text="#e8e8e8", muted="#9a9a9a", accent="#ff9f1a", accent_fg="#000000",
        up="", down="", warn="#ffb020", danger="#ff6a3d", ok="#4cc38a",
        mono=True, pad=6, row_h=22,
    ),
    ("Bloomberg", "light"): Palette(
        "Bloomberg 淺色", bg="#f3f1ec", side="#e7e4dc", surface="#ffffff", surface2="#ece9e1",
        border="#c9c5ba", text="#16161a", muted="#5f5f66", accent="#b45309", accent_fg="#ffffff",
        up="", down="", warn="#b45309", danger="#c2410c", ok="#12805c",
        mono=True, pad=6, row_h=22,
    ),
    ("Notion", "light"): Palette(
        "Notion 淺色", bg="#ffffff", side="#f7f6f3", surface="#ffffff", surface2="#f7f6f3",
        border="#e9e9e7", text="#37352f", muted="#67665f", accent="#1f6fc5", accent_fg="#ffffff",
        up="", down="", warn="#a8721a", danger="#d44c47", ok="#448361",
        mono=False, pad=12, row_h=30,
    ),
    ("Notion", "dark"): Palette(
        "Notion 深色", bg="#191919", side="#202020", surface="#252525", surface2="#2b2b2b",
        border="#373737", text="#ebebea", muted="#9b9b9b", accent="#529cca", accent_fg="#0b1a24",
        up="", down="", warn="#d9a441", danger="#e0645e", ok="#4dab9a",
        mono=False, pad=12, row_h=30,
    ),
}

# Price up / down colours (kept off the alert colours so "danger" never means "up").
_UPDOWN = {
    "dark": {"red": "#f26b6b", "green": "#4cc38a"},
    "light": {"red": "#d92d20", "green": "#12805c"},
}


def get_palette(style: str, mode: str, red_up: bool = True) -> Palette:
    """red_up=True → 紅漲綠跌 (Taiwan); False → 綠漲紅跌 (US)."""
    base = _BASE[(style if style in STYLES else "Bloomberg", mode if mode in MODES else "dark")]
    ud = _UPDOWN["dark" if mode == "dark" else "light"]
    up, down = (ud["red"], ud["green"]) if red_up else (ud["green"], ud["red"])
    return replace(base, up=up, down=down)


def tone_color(p: Palette, tone: str) -> str:
    return {
        "up": p.up, "down": p.down, "warn": p.warn, "danger": p.danger,
        "ok": p.ok, "accent": p.accent, "muted": p.muted,
    }.get(tone, p.text)


def tint(fg: str, bg: str, alpha: float) -> str:
    """Blend fg over bg (alpha 0..1) — used for subtle row tints."""
    f = [int(fg[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(fv * alpha + bv * (1 - alpha)):02x}" for fv, bv in zip(f, b))


def luminance(hex_color: str) -> float:
    def chan(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# ---- fonts ---------------------------------------------------------------

def font_families() -> Tuple[str, str]:
    """(ui_font, mono_font) with sensible fallbacks per platform."""
    if sys.platform == "win32":
        return "Microsoft JhengHei UI", "Consolas"
    if sys.platform == "darwin":
        return "PingFang TC", "Menlo"
    return "Noto Sans CJK TC", "DejaVu Sans Mono"


def fonts(p: Palette) -> Dict[str, tuple]:
    ui, mono = font_families()
    data = mono if p.mono else ui
    base = 9 if p.mono else 10
    return {
        "ui": (ui, base),
        "ui_bold": (ui, base, "bold"),
        "small": (ui, base - 1),
        "h1": (ui, base + 6, "bold"),
        "title": (ui, base + 3, "bold"),
        "kpi": (data, base + 8, "bold"),
        "data": (data, base),
        "data_bold": (data, base, "bold"),
    }


def enable_hidpi() -> None:
    """Crisp text on Windows high-DPI screens (call before creating Tk)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# ---- ttk mapping ---------------------------------------------------------

def apply_ttk(root, p: Palette) -> Dict[str, tuple]:
    from tkinter import ttk

    f = fonts(p)
    s = ttk.Style(root)
    s.theme_use("clam")
    root.configure(background=p.bg)

    s.configure(".", background=p.bg, foreground=p.text, fieldbackground=p.surface2,
                bordercolor=p.border, lightcolor=p.bg, darkcolor=p.bg, troughcolor=p.bg,
                focuscolor=p.accent, font=f["ui"])
    s.configure("TFrame", background=p.bg)
    s.configure("Side.TFrame", background=p.side)
    s.configure("Card.TFrame", background=p.surface)
    s.configure("TLabel", background=p.bg, foreground=p.text, font=f["ui"])
    s.configure("Side.TLabel", background=p.side, foreground=p.text)
    s.configure("Muted.TLabel", foreground=p.muted)
    s.configure("SideMuted.TLabel", background=p.side, foreground=p.muted, font=f["small"])
    s.configure("Title.TLabel", font=f["title"], foreground=p.text)
    s.configure("H1.TLabel", font=f["h1"], foreground=p.text)
    s.configure("Section.TLabel", background=p.side, foreground=p.muted, font=f["small"])

    # buttons
    s.configure("TButton", background=p.surface2, foreground=p.text, bordercolor=p.border,
                padding=(p.pad + 2, p.pad // 2 + 2), relief="flat", font=f["ui"])
    s.map("TButton", background=[("active", p.border), ("disabled", p.surface)],
          foreground=[("disabled", p.muted)])
    s.configure("Accent.TButton", background=p.accent, foreground=p.accent_fg,
                bordercolor=p.accent, font=f["ui_bold"])
    s.map("Accent.TButton", background=[("active", tint(p.accent, p.text, 0.85)),
                                         ("disabled", p.border)],
          foreground=[("disabled", p.muted)])
    s.configure("Ghost.TButton", background=p.bg, foreground=p.muted, bordercolor=p.bg)
    s.map("Ghost.TButton", background=[("active", p.surface2)], foreground=[("active", p.text)])

    # inputs
    for w in ("TEntry", "TSpinbox", "TCombobox"):
        s.configure(w, fieldbackground=p.surface2, background=p.surface2, foreground=p.text,
                    bordercolor=p.border, insertcolor=p.text, arrowcolor=p.muted,
                    padding=4, selectbackground=p.accent, selectforeground=p.accent_fg)
    s.map("TCombobox", fieldbackground=[("readonly", p.surface2)],
          foreground=[("readonly", p.text)], selectbackground=[("readonly", p.surface2)],
          selectforeground=[("readonly", p.text)])
    root.option_add("*TCombobox*Listbox.background", p.surface2)
    root.option_add("*TCombobox*Listbox.foreground", p.text)
    root.option_add("*TCombobox*Listbox.selectBackground", p.accent)
    root.option_add("*TCombobox*Listbox.selectForeground", p.accent_fg)
    root.option_add("*TCombobox*Listbox.font", f["ui"])

    # notebook (tabs)
    s.configure("TNotebook", background=p.bg, borderwidth=0, tabmargins=(0, 0, 0, 0))
    s.configure("TNotebook.Tab", background=p.bg, foreground=p.muted, padding=(p.pad + 6, p.pad // 2 + 3),
                borderwidth=0, bordercolor=p.bg, lightcolor=p.bg, darkcolor=p.bg, font=f["ui"])
    s.map("TNotebook.Tab", background=[("selected", p.surface)],
          bordercolor=[("selected", p.surface)], lightcolor=[("selected", p.surface)],
          darkcolor=[("selected", p.surface)],
          foreground=[("selected", p.accent if p.mono else p.text)],
          font=[("selected", f["ui_bold"])])
    s.configure("Flat.TNotebook", background=p.bg, borderwidth=0)

    # table
    s.configure("Treeview", background=p.surface, fieldbackground=p.surface, foreground=p.text,
                rowheight=p.row_h, borderwidth=0, font=f["data"], relief="flat")
    s.configure("Treeview.Heading", background=p.surface2, foreground=p.muted, relief="flat",
                borderwidth=0, padding=(6, 5), font=f["ui_bold"])
    s.map("Treeview", background=[("selected", p.accent)], foreground=[("selected", p.accent_fg)])
    s.map("Treeview.Heading", background=[("active", p.border)])

    s.configure("TLabelframe", background=p.bg, bordercolor=p.border, relief="solid", borderwidth=1)
    s.configure("TLabelframe.Label", background=p.bg, foreground=p.muted, font=f["small"])
    s.configure("TSeparator", background=p.border)
    s.configure("TCheckbutton", background=p.bg, foreground=p.text)
    s.map("TCheckbutton", background=[("active", p.bg)])
    s.configure("TRadiobutton", background=p.bg, foreground=p.text)
    s.map("TRadiobutton", background=[("active", p.bg)])
    for w in ("Radiobutton", "Checkbutton"):
        s.configure(f"Card.T{w}", background=p.surface, foreground=p.text, font=f["small"],
                    indicatorcolor=p.surface2, indicatorbackground=p.surface2)
        s.map(f"Card.T{w}", background=[("active", p.surface)],
              indicatorcolor=[("selected", p.accent)], foreground=[("active", p.text)])
    for orient in ("Vertical", "Horizontal"):
        s.configure(f"{orient}.TScrollbar", background=p.surface2, troughcolor=p.bg,
                    bordercolor=p.bg, arrowcolor=p.muted, relief="flat")
        s.map(f"{orient}.TScrollbar", background=[("active", p.border)])
    s.configure("TPanedwindow", background=p.bg)
    return f
