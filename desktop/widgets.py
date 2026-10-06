"""Small themed tk widgets for the desktop GUI."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from theme import Palette, tone_color


class KpiCard(tk.Frame):
    """Label / big value / sub-line card, recoloured with the active palette."""

    def __init__(self, parent, label: str) -> None:
        super().__init__(parent, bd=0, highlightthickness=1)
        self._tone = "text"
        self.lbl = tk.Label(self, text=label, anchor="w")
        self.val = tk.Label(self, text="—", anchor="w")
        self.sub = tk.Label(self, text="", anchor="w", justify="left")
        self.lbl.pack(fill="x", padx=12, pady=(10, 0))
        self.val.pack(fill="x", padx=12)
        self.sub.pack(fill="x", padx=12, pady=(0, 10))

    def set(self, value: str, sub: str = "", tone: str = "text") -> None:
        self._tone = tone
        self.val.config(text=value)
        self.sub.config(text=sub)
        self._apply_tone()

    def restyle(self, p: Palette, fonts: dict) -> None:
        self.p = p
        self.config(bg=p.surface, highlightbackground=p.border, highlightcolor=p.border)
        for w in (self.lbl, self.val, self.sub):
            w.config(bg=p.surface)
        self.lbl.config(fg=p.muted, font=fonts["small"])
        self.sub.config(fg=p.muted, font=fonts["small"])
        self.val.config(font=fonts["kpi"])
        self._apply_tone()

    def _apply_tone(self) -> None:
        p = getattr(self, "p", None)
        if p is not None:
            self.val.config(fg=tone_color(p, self._tone))


def scrolled_text(parent, *, height: int = 10, width: int = 30, wrap: str = "word",
                  hscroll: bool = False, **kw):
    """Text + ttk scrollbars (so they follow the theme). Returns (frame, text)."""
    frame = ttk.Frame(parent)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    text = tk.Text(frame, height=height, width=width, wrap=wrap, bd=0, **kw)
    text.grid(row=0, column=0, sticky="nsew")
    vsb = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
    vsb.grid(row=0, column=1, sticky="ns")
    text.configure(yscrollcommand=vsb.set)
    if hscroll:
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
        hsb.grid(row=1, column=0, sticky="ew")
        text.configure(xscrollcommand=hsb.set)
    return frame, text


def bar_image(width: int, height: int, ratio: float, fill: str, track: str) -> tk.PhotoImage:
    """Small horizontal data bar (colour is free, unlike text blocks in a Treeview)."""
    img = tk.PhotoImage(width=width, height=height)
    img.put(track, to=(0, 0, width, height))
    n = max(0, min(width, int(round(width * max(0.0, min(1.0, ratio))))))
    if n:
        img.put(fill, to=(0, 0, n, height))
    return img
