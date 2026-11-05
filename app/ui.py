"""Tkinter desktop UI for the Koobs library — ink mode, card list, colored tags."""
import datetime
import json
import os
import shutil
import subprocess
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont

from osutil import enable_hidpi, open_path, restart_app, wheel_units
from store import (BOOK_EXTS, DB_NAME, DEFAULT_BOOKS_DIR, DEFAULT_DATA_DIR, PALETTE,
                   STATUS_ICON, STATUS_KEYS, STATUS_LABEL, Library, load_config, load_pref,
                   norm_dir, progress, save_config, save_pref)

# ---------------------------------------------------------------- theme
# Each theme is a full palette. INK always holds the active one (switched in place).
THEMES = {
    "Ink": {        # warm paper, near-black ink (default)
        "paper": "#f4f1ea", "card": "#fffdf8", "ink": "#1a1915", "muted": "#6e6a60",
        "faint": "#a19c90", "rule": "#d9d4c7", "hover": "#9c978a", "sel": "#ebe6d9",
        "danger": "#a3271f", "press": "#3a3830", "danger_press": "#86201a",
    },
    "Paper": {      # cool white, crisp contrast
        "paper": "#f6f7f8", "card": "#ffffff", "ink": "#121417", "muted": "#5c6470",
        "faint": "#9aa1ab", "rule": "#dde1e6", "hover": "#9aa1ab", "sel": "#e9edf2",
        "danger": "#c22a22", "press": "#2f343b", "danger_press": "#9c1d17",
    },
    "Sepia": {      # old-book tones, easy on the eyes
        "paper": "#efe4cf", "card": "#f8efdc", "ink": "#3b2f22", "muted": "#7a6650",
        "faint": "#a8957b", "rule": "#d8c8aa", "hover": "#a08a6b", "sel": "#e6d5b5",
        "danger": "#9c2b1e", "press": "#5a4835", "danger_press": "#7d2015",
    },
    "Night": {      # warm dark: light ink on dark paper
        "paper": "#1b1a17", "card": "#252320", "ink": "#ece6d8", "muted": "#a59e8f",
        "faint": "#716b60", "rule": "#3b3832", "hover": "#6e685d", "sel": "#33302a",
        "danger": "#e46a5d", "press": "#cfc8b8", "danger_press": "#c9554a",
    },
    "Slate": {      # cool dark
        "paper": "#15181c", "card": "#1d2126", "ink": "#e4e7eb", "muted": "#9aa3ad",
        "faint": "#636c76", "rule": "#2e343b", "hover": "#5b646e", "sel": "#262b31",
        "danger": "#ef6b6b", "press": "#c6ccd3", "danger_press": "#d55858",
    },
}
DEFAULT_THEME = "Ink"
INK = dict(THEMES[DEFAULT_THEME])
ALL, UNTAGGED, MISSING = "All books", "Untagged", "Missing files"
SPECIAL = (ALL, UNTAGGED, MISSING)
STATUS_PREFIX = "status:"          # filter token for a reading status, e.g. "status:reading"


def is_status(token):
    return token.startswith(STATUS_PREFIX)


def filter_label(token):
    return STATUS_LABEL[token[len(STATUS_PREFIX):]] if is_status(token) else token


def fmt_date(iso):
    try:
        y, m, d = (int(x) for x in iso.split("-"))
        day = datetime.date(y, m, d)
        return f"{day.day} {day:%b %Y}"     # no %-d: Windows strftime lacks it
    except (ValueError, AttributeError):
        return iso or ""


def pick_family(candidates, fallback="TkDefaultFont"):
    fams = set(tkfont.families())
    return next((c for c in candidates if c in fams), fallback)


def text_on(hex_color):
    """Black or white text, whichever reads better on hex_color."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#1a1915" if lum > 0.6 else "#ffffff"   # fixed, so chips read in every theme


def tint(hex_color, amount=0.85):
    """Mix a color toward the card surface (for soft fills)."""
    h, p = hex_color.lstrip("#"), INK["card"].lstrip("#")
    mix = [round(int(h[i:i + 2], 16) * (1 - amount) + int(p[i:i + 2], 16) * amount)
           for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(mix)


def rounded(c, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def fit(text, font, width):
    if width <= 0:
        return ""
    if font.measure(text) <= width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.measure(text[:mid] + "…") <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + "…"


def bind_wheel(canvas):
    canvas.bind("<Button-4>", lambda e: canvas.yview_scroll(-3, "units"))
    canvas.bind("<Button-5>", lambda e: canvas.yview_scroll(3, "units"))
    canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(wheel_units(e.delta), "units"))


def draw_chip(c, x, y, text, color, font, style="solid", tags=()):
    """Draw a tag chip at (x, y); returns the x where the next chip may start."""
    w, h = font.measure(text) + 16, font.metrics("linespace") + 6
    if style == "solid":
        fill, outline, fg, dash = color, color, text_on(color), ()
    elif style == "mixed":
        fill, outline, fg, dash = tint(color, 0.8), color, color, (3, 2)
    else:  # off
        fill, outline, fg, dash = "", INK["rule"], INK["muted"], ()
    rounded(c, x, y, x + w, y + h, 8, fill=fill, outline=outline, dash=dash, tags=tags)
    c.create_text(x + w / 2, y + h / 2, text=text, fill=fg, font=font, tags=tags)
    return x + w + 6


# ---------------------------------------------------------------- card list
class CardList:
    H, GAP, PAD = 90, 8, 14

    def __init__(self, parent, app):
        self.app = app
        self.frame = tk.Frame(parent, bg=INK["paper"])
        self.c = tk.Canvas(self.frame, bg=INK["paper"], highlightthickness=0, takefocus=1)
        sb = ttk.Scrollbar(self.frame, orient=tk.VERTICAL, command=self.c.yview)
        self.c.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.c.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.rows, self.sel, self.anchor, self.hover = [], set(), None, None
        self._job, self._width = None, 0

        bind_wheel(self.c)
        self.c.bind("<Configure>", self._on_resize)
        self.c.bind("<Button-1>", self._click)
        self.c.bind("<Double-Button-1>", lambda e: app.open_selected())
        self.c.bind("<Motion>", self._motion)
        self.c.bind("<Leave>", lambda e: self._set_hover(None))
        self.c.bind("<Up>", lambda e: self._step(-1))
        self.c.bind("<Down>", lambda e: self._step(1))
        self.c.bind("<Return>", lambda e: app.open_selected())
        self.c.bind("<Control-a>", self._select_all)
        self.c.bind("<Delete>", lambda e: app.trash_selected())
        self.c.bind("<Button-3>", self._context_menu)
        # 1-4 set reading status of the selection, 0 clears it
        for n, key in enumerate(STATUS_KEYS, start=1):
            self.c.bind(f"<Key-{n}>", lambda e, k=key: app.set_status(k))
        self.c.bind("<Key-0>", lambda e: app.set_status(None))

    # data
    def set_rows(self, rows):
        self.rows = rows
        self.index = {rel: i for i, (rel, _) in enumerate(rows)}
        self.sel &= set(self.index)
        self.redraw()

    def selected(self):
        return [rel for rel, _ in self.rows if rel in self.sel]

    # drawing
    def _on_resize(self, e):
        if e.width != self._width:
            self._width = e.width
            if self._job:
                self.c.after_cancel(self._job)
            self._job = self.c.after(40, self.redraw)

    def redraw(self):
        c, a = self.c, self.app
        c.delete("all")
        w = max(c.winfo_width(), 400)
        for i, (rel, b) in enumerate(self.rows):
            self._draw_card(i, rel, b, w)
        total = self.GAP + len(self.rows) * (self.H + self.GAP)
        c.configure(scrollregion=(0, 0, w, max(total, c.winfo_height())))
        if not self.rows:
            c.create_text(w / 2, 80, text="No books match", fill=INK["faint"], font=a.f_sub)
        self.hover = None

    def _draw_card(self, i, rel, b, w):
        c, a = self.c, self.app
        y, x1, x2 = self.GAP + i * (self.H + self.GAP), self.PAD, w - self.PAD
        rounded(c, x1, y, x2, y + self.H, 10, tags=("card", f"bg{i}"), **self._card_style(i, rel))
        tx = x1 + 18

        # badges on the right, right-to-left: format, missing, reading status
        bx = x2 - 14
        badges = [(b["format"].upper(), INK["muted"], "")]
        if b.get("missing"):
            badges.append(("MISSING", INK["danger"], ""))
        st = b.get("status")
        if st in STATUS_LABEL:
            label = f"{STATUS_ICON[st]}  {STATUS_LABEL[st].upper()}"
            pct = progress(b)
            if st == "reading" and pct is not None:
                label += f"  {round(pct * 100)}%"
            # Reading stands out (solid ink); the rest are quiet outlines.
            fill = INK["ink"] if st == "reading" else ""
            col = INK["card"] if st == "reading" else \
                INK["ink"] if st == "finished" else INK["muted"]
            badges.append((label, col, fill))
        for label, col, fill in badges:
            bw = a.f_badge.measure(label) + 12
            rounded(c, bx - bw, y + 13, bx, y + 31, 6, fill=fill,
                    outline=fill or col)
            c.create_text(bx - bw / 2, y + 22, text=label, fill=col, font=a.f_badge)
            bx -= bw + 6

        title_col = INK["danger"] if b.get("missing") else INK["ink"]
        c.create_text(tx, y + 12, anchor="nw", font=a.f_title, fill=title_col,
                      text=fit(b["title"], a.f_title, bx - tx - 12))
        c.create_text(tx, y + 34, anchor="nw", font=a.f_sub, fill=INK["muted"],
                      text=fit(b["author"] or "Unknown author", a.f_sub, bx - tx - 12))

        cx, cy = tx, y + self.H - 32
        if not b["tags"]:
            c.create_text(cx, cy + 2, anchor="nw", text="untagged", fill=INK["faint"], font=a.f_sub)
        for k, t in enumerate(b["tags"]):
            if cx + a.f_chip.measure(t) + 16 > x2 - 50:
                c.create_text(cx + 2, cy + 2, anchor="nw", text=f"+{len(b['tags']) - k}",
                              fill=INK["muted"], font=a.f_chip)
                break
            cx = draw_chip(c, cx, cy, t, a.lib.color(t), a.f_chip)

        # progress: a thin line along the bottom of the card
        pct = progress(b)
        if pct is not None:
            lx1, lx2, ly = x1 + 12, x2 - 12, y + self.H - 6
            c.create_line(lx1, ly, lx2, ly, fill=INK["rule"], width=3, capstyle=tk.ROUND)
            if pct > 0:
                c.create_line(lx1, ly, lx1 + (lx2 - lx1) * pct, ly, fill=INK["ink"],
                              width=3, capstyle=tk.ROUND)

    def _card_style(self, i, rel):
        if rel in self.sel:
            return {"fill": INK["sel"], "outline": INK["ink"], "width": 2}
        if i == self.hover:
            return {"fill": INK["card"], "outline": INK["hover"], "width": 1}
        return {"fill": INK["card"], "outline": INK["rule"], "width": 1}

    def _restyle(self, i):
        if 0 <= i < len(self.rows):
            self.c.itemconfigure(f"bg{i}", **self._card_style(i, self.rows[i][0]))

    def _restyle_all(self):
        for i in range(len(self.rows)):
            self._restyle(i)

    # interaction
    def _index_at(self, y):
        y = self.c.canvasy(y) - self.GAP
        i, off = divmod(y, self.H + self.GAP)
        i = int(i)
        return i if 0 <= i < len(self.rows) and off <= self.H else None

    def _set_hover(self, i):
        if i != self.hover:
            old, self.hover = self.hover, i
            if old is not None:
                self._restyle(old)
            if i is not None:
                self._restyle(i)

    def _motion(self, e):
        self._set_hover(self._index_at(e.y))

    def _click(self, e):
        self.app.flush_edits()
        self.c.focus_set()
        i = self._index_at(e.y)
        if i is None:
            if not e.state & 0x5:
                self.sel.clear()
                self._changed()
            return
        rel = self.rows[i][0]
        if e.state & 0x1 and self.anchor in self.index:      # Shift: range
            j = self.index[self.anchor]
            self.sel = {r for r, _ in self.rows[min(i, j):max(i, j) + 1]}
        elif e.state & 0x4:                                   # Ctrl: toggle
            self.sel ^= {rel}
            self.anchor = rel
        else:
            self.sel = {rel}
            self.anchor = rel
        self._changed()

    def _step(self, d):
        if not self.rows:
            return
        self.app.flush_edits()
        cur = self.index.get(self.anchor, -1 if d > 0 else len(self.rows))
        i = max(0, min(len(self.rows) - 1, cur + d))
        self.anchor = self.rows[i][0]
        self.sel = {self.anchor}
        self._changed()
        self.see(i)

    def see(self, i):
        total = self.GAP + len(self.rows) * (self.H + self.GAP)
        top = self.GAP + i * (self.H + self.GAP)
        v0, v1 = self.c.yview()
        if top < v0 * total:
            self.c.yview_moveto((top - self.GAP) / total)
        elif top + self.H > v1 * total:
            self.c.yview_moveto((top + self.H + self.GAP) / total - (v1 - v0))

    def _context_menu(self, e):
        i = self._index_at(e.y)
        if i is None:
            return
        self.app.flush_edits()
        rel = self.rows[i][0]
        if rel not in self.sel:          # right-click on an unselected card selects it
            self.sel, self.anchor = {rel}, rel
            self._changed()
        n = len(self.sel)
        m = tk.Menu(self.c, tearoff=0)
        m.add_command(label="Open" if n == 1 else f"Open {min(n, 5)} books",
                      command=self.app.open_selected)
        cur = {self.app.lib.books[r].get("status") for r in self.sel}
        sm = tk.Menu(m, tearoff=0)
        for k, key in enumerate(STATUS_KEYS, start=1):
            mark = "  ✓" if cur == {key} else ""
            sm.add_command(label=f"{STATUS_ICON[key]}  {STATUS_LABEL[key]}{mark}",
                           accelerator=str(k),
                           command=lambda key=key: self.app.set_status(key))
        sm.add_separator()
        sm.add_command(label="No status", accelerator="0",
                       command=lambda: self.app.set_status(None))
        m.add_cascade(label="Mark as", menu=sm)
        m.add_separator()
        m.add_command(label="Move out…" if n == 1 else f"Move {n} books out…",
                      command=self.app.move_out_selected)
        m.add_command(label="Move to Trash…" if n == 1 else f"Move {n} books to Trash…",
                      foreground=INK["danger"], activeforeground=INK["danger"],
                      command=self.app.trash_selected)
        m.tk_popup(e.x_root, e.y_root)

    def _select_all(self, e=None):
        self.app.flush_edits()
        self.sel = set(self.index)
        self._changed()
        return "break"

    def _changed(self):
        self._restyle_all()
        self.app.on_select()


# ---------------------------------------------------------------- sidebar
class TagSidebar:
    ROW = 30

    def __init__(self, parent, app):
        self.app = app
        self.frame = tk.Frame(parent, bg=INK["paper"])
        self.c = tk.Canvas(self.frame, bg=INK["paper"], highlightthickness=0, width=230)
        self.c.pack(fill=tk.BOTH, expand=True)
        bind_wheel(self.c)
        self.c.bind("<Configure>", lambda e: self.redraw())
        self.c.bind("<Button-1>", self._click)
        self.c.bind("<Button-3>", self._menu)
        self.items = []  # (y0, y1, name)

    def redraw(self):
        c, a = self.c, self.app
        c.delete("all")
        w = max(c.winfo_width(), 200)
        counts = a.lib.counts()
        books = a.lib.books.values()
        special = {ALL: len(a.lib.books),
                   UNTAGGED: sum(1 for b in books if not b["tags"]),
                   MISSING: sum(1 for b in books if b.get("missing"))}
        self.items, y = [], 10

        def header(text):
            nonlocal y
            c.create_text(14, y + 6, anchor="w", text=text, fill=INK["faint"], font=a.f_badge)
            y += 20

        def row(name, count, color=None, icon=None, label=None):
            nonlocal y
            on = name in a.filters or (name == ALL and not a.filters)
            if on:
                c.create_rectangle(6, y, w - 6, y + self.ROW - 4, fill=INK["sel"], outline="")
                c.create_rectangle(6, y, 9, y + self.ROW - 4, fill=INK["ink"], outline="")
            mid = y + (self.ROW - 4) / 2
            if color:
                c.create_oval(18, mid - 5, 28, mid + 5, fill=color, outline=color)
            elif icon:
                c.create_text(23, mid, text=icon, fill=INK["ink"], font=a.f_side)
            tx = 36 if (color or icon) else 18
            c.create_text(tx, mid, anchor="w", font=a.f_side_b if on else a.f_side,
                          fill=INK["ink"], text=fit(label or name, a.f_side, w - tx - 50))
            c.create_text(w - 14, mid, anchor="e", text=str(count), font=a.f_badge,
                          fill=INK["muted"])
            self.items.append((y, y + self.ROW - 4, name))
            y += self.ROW

        header("LIBRARY")
        for s in SPECIAL:
            if s != MISSING or special[s]:
                row(s, special[s])
        y += 8
        header("READING")
        sc = a.lib.status_counts()
        for key in STATUS_KEYS:
            row(STATUS_PREFIX + key, sc[key], icon=STATUS_ICON[key], label=STATUS_LABEL[key])
        y += 8
        header("TAGS")
        for t in sorted(a.lib.tags, key=str.lower):
            row(t, counts.get(t, 0), a.lib.color(t))
        c.configure(scrollregion=(0, 0, w, y + 10))

    def _name_at(self, e):
        y = self.c.canvasy(e.y)
        return next((n for y0, y1, n in self.items if y0 <= y <= y1), None)

    def _click(self, e):
        name = self._name_at(e)
        if name is None:
            return
        a = self.app
        if name == ALL:
            a.filters = []
        elif e.state & 0x4:
            a.filters = [f for f in a.filters if f != name] if name in a.filters \
                else a.filters + [name]
        else:
            a.filters = [] if a.filters == [name] else [name]
        a.refresh()

    def _menu(self, e):
        name = self._name_at(e)
        if name is None or name in SPECIAL or is_status(name):
            return
        self.app.tag_menu(name, e.x_root, e.y_root)


# ---------------------------------------------------------------- add books
BOOK_PATTERNS = "*.pdf *.epub *.mobi *.azw3 *.djvu *.PDF *.EPUB *.MOBI *.AZW3 *.DJVU"


def pick_book_files(parent):
    """Native GTK picker via zenity when available, else Tk's dialog."""
    start = os.path.expanduser("~/Downloads")
    if not os.path.isdir(start):
        start = os.path.expanduser("~")
    if shutil.which("zenity"):
        try:
            out = subprocess.run(
                ["zenity", "--file-selection", "--multiple", "--separator=\n",
                 "--title=Add books", f"--filename={start}/",
                 f"--file-filter=Books | {BOOK_PATTERNS}", "--file-filter=All files | *"],
                capture_output=True, text=True)
            if out.returncode == 0:
                return [p for p in out.stdout.splitlines() if p.strip()]
            if out.returncode == 1:  # cancelled
                return []
        except OSError:
            pass
    return list(filedialog.askopenfilenames(
        parent=parent, title="Add books", initialdir=start,
        filetypes=[("Books", BOOK_PATTERNS), ("All files", "*")]))


class AddDialog:
    """Confirm an import: copy vs move, and tags to apply to the new books."""

    def __init__(self, app, paths):
        self.app, self.paths, self.result = app, paths, None
        self.chosen = set(t for t in app.filters if t in app.lib.tags)
        top = self.top = tk.Toplevel(app.root, bg=INK["paper"])
        top.title("Add books")
        top.transient(app.root)
        top.geometry("560x520")
        top.minsize(460, 420)

        f = ttk.Frame(top)
        f.pack(fill=tk.BOTH, expand=True, padx=18, pady=16)
        n = len(paths)
        ttk.Label(f, text=f"Add {n} book{'s' if n != 1 else ''}", style="Head.TLabel").pack(anchor="w")
        names = "\n".join(os.path.basename(p) for p in paths[:6])
        if n > 6:
            names += f"\n…and {n - 6} more"
        ttk.Label(f, text=names, style="Muted.TLabel", wraplength=510,
                  justify="left").pack(anchor="w", pady=(6, 12))

        ttk.Label(f, text="INTO ALL/", style="Cap.TLabel").pack(anchor="w")
        self.move = tk.BooleanVar(value=False)
        s = ttk.Style()
        s.configure("Ink.TRadiobutton", background=INK["paper"], foreground=INK["ink"],
                    indicatorcolor=INK["card"])
        s.map("Ink.TRadiobutton", indicatorcolor=[("selected", INK["ink"])],
              background=[("active", INK["paper"])])
        ttk.Radiobutton(f, text="Copy (keep the original file)", variable=self.move, value=False,
                        style="Ink.TRadiobutton").pack(anchor="w", pady=(2, 0))
        ttk.Radiobutton(f, text="Move (remove it from where it is now)", variable=self.move,
                        value=True, style="Ink.TRadiobutton").pack(anchor="w")

        ttk.Label(f, text="TAGS  ·  click to toggle", style="Cap.TLabel").pack(anchor="w", pady=(14, 4))
        add = ttk.Frame(f)
        add.pack(fill=tk.X, pady=(0, 6))
        self.new_tag = tk.StringVar()
        e = ttk.Entry(add, textvariable=self.new_tag)
        e.pack(side=tk.LEFT, fill=tk.X, expand=True)
        e.bind("<Return>", lambda ev: self._new_tag())
        ttk.Button(add, text="New tag", command=self._new_tag).pack(side=tk.LEFT, padx=(6, 0))
        self.c = tk.Canvas(f, bg=INK["paper"], highlightthickness=0, height=150)
        self.c.pack(fill=tk.BOTH, expand=True)
        bind_wheel(self.c)
        self.c.bind("<Configure>", lambda e: self._draw())
        self.c.bind("<Button-1>", self._click)
        self.extra = []  # new tags typed here, not yet in the library

        btns = ttk.Frame(f)
        btns.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(btns, text="Add to library", style="Primary.TButton",
                   command=self._ok).pack(side=tk.RIGHT)
        ttk.Button(btns, text="Cancel", command=top.destroy).pack(side=tk.RIGHT, padx=8)
        top.bind("<Escape>", lambda e: top.destroy())
        top.wait_visibility()
        top.grab_set()

    def _tags(self):
        return sorted(set(self.app.lib.tags) | set(self.extra), key=str.lower)

    def _draw(self):
        c, a = self.c, self.app
        c.delete("all")
        self.hits = []
        w = max(c.winfo_width(), 200)
        x, y, h = 0, 2, a.f_chip.metrics("linespace") + 6
        for t in self._tags():
            cw = a.f_chip.measure(t) + 16
            if x and x + cw > w:
                x, y = 0, y + h + 8
            color = a.lib.color(t) if t in a.lib.tags else INK["ink"]
            nx = draw_chip(c, x, y, t, color, a.f_chip, "solid" if t in self.chosen else "off")
            self.hits.append((x, y, x + cw, y + h, t))
            x = nx
        c.configure(scrollregion=(0, 0, w, y + h + 4))

    def _click(self, e):
        x, y = self.c.canvasx(e.x), self.c.canvasy(e.y)
        t = next((t for x0, y0, x1, y1, t in self.hits if x0 <= x <= x1 and y0 <= y <= y1), None)
        if t:
            self.chosen ^= {t}
            self._draw()

    def _new_tag(self):
        name = self.new_tag.get().strip()
        if not name:
            return
        name = self.app.lib.canonical(name)
        if name not in self.app.lib.tags and name.lower() not in (x.lower() for x in self.extra):
            self.extra.append(name)
        self.chosen.add(name)
        self.new_tag.set("")
        self._draw()

    def _ok(self):
        self.result = (self.move.get(), sorted(self.chosen))
        self.top.destroy()


# ---------------------------------------------------------------- remove confirm
def _book_list_dialog(app, window_title, head, note, ok_label, ok_style, rels):
    """Modal ink-style confirmation listing the books. Returns True if confirmed."""
    books = [app.lib.books[r] for r in rels]
    n = len(books)
    top = tk.Toplevel(app.root, bg=INK["paper"])
    top.title(window_title)
    top.transient(app.root)
    top.resizable(False, False)
    result = {"ok": False}

    f = ttk.Frame(top)
    f.pack(fill=tk.BOTH, expand=True, padx=22, pady=18)
    ttk.Label(f, text=head, font=app.f_title, wraplength=440,
              justify="left").pack(anchor="w")
    if n > 1:
        names = "\n".join(f"•  {b['title']}" for b in books[:6])
        if n > 6:
            names += f"\n…and {n - 6} more"
        ttk.Label(f, text=names, style="Muted.TLabel", wraplength=440,
                  justify="left").pack(anchor="w", pady=(8, 0))
    ttk.Label(f, text=note, style="Muted.TLabel", wraplength=440,
              justify="left").pack(anchor="w", pady=(10, 16))

    def done(ok):
        result["ok"] = ok
        top.destroy()

    btns = ttk.Frame(f)
    btns.pack(fill=tk.X)
    ttk.Button(btns, text=ok_label, style=ok_style,
               command=lambda: done(True)).pack(side=tk.RIGHT)
    cancel = ttk.Button(btns, text="Cancel", command=lambda: done(False))
    cancel.pack(side=tk.RIGHT, padx=8)
    top.bind("<Escape>", lambda e: done(False))
    top.protocol("WM_DELETE_WINDOW", lambda: done(False))
    top.update_idletasks()
    x = app.root.winfo_rootx() + (app.root.winfo_width() - top.winfo_reqwidth()) // 2
    y = app.root.winfo_rooty() + (app.root.winfo_height() - top.winfo_reqheight()) // 3
    top.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    top.wait_visibility()
    top.grab_set()
    cancel.focus_set()  # safe default: keyboard focus starts on Cancel; Enter does nothing
    app.root.wait_window(top)
    return result["ok"]


def confirm_trash(app, rels):
    books = [app.lib.books[r] for r in rels]
    n = len(books)
    head = f"Move “{books[0]['title']}” to the Trash?" if n == 1 \
        else f"Move {n} books to the Trash?"
    note = ("The file goes to your system Trash, so you can still restore it "
            "from the file manager. Its tags in Koobs are removed." if n == 1 else
            "The files go to your system Trash, so you can still restore them "
            "from the file manager. Their tags in Koobs are removed.")
    missing = sum(1 for b in books if b.get("missing"))
    if missing:
        note += (f"\n{missing} of these files are already missing and are just "
                 "removed from the library." if n > 1 else
                 "\nThis file is already missing, so it is just removed from the library.")
    return _book_list_dialog(app, "Move to Trash", head, note, "Move to Trash",
                             "DangerFill.TButton", rels)


def confirm_move_out(app, rels, dest):
    books = [app.lib.books[r] for r in rels]
    n = len(books)
    head = f"Move “{books[0]['title']}” out of Koobs?" if n == 1 \
        else f"Move {n} books out of Koobs?"
    note = (f"{'It' if n == 1 else 'They'} will be moved to:\n{dest}\n\n"
            f"{'It leaves' if n == 1 else 'They leave'} your library and "
            f"{'its' if n == 1 else 'their'} tags, status and progress in Koobs are removed. "
            "A file with the same name there is never overwritten; a number is added instead.")
    missing = sum(1 for b in books if b.get("missing"))
    if missing:
        note += (f"\n{missing} of these files are missing and will be skipped." if n > 1
                 else "\nThis file is missing, so there is nothing to move.")
    return _book_list_dialog(app, "Move out", head, note, "Move out",
                             "Primary.TButton", rels)


# ---------------------------------------------------------------- tooltip
class Tooltip:
    def __init__(self, widget, text, delay=450):
        self.w, self.text, self.delay = widget, text, delay
        self.tip = self.job = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, e=None):
        self._hide()
        self.job = self.w.after(self.delay, self._show)

    def _show(self):
        x = self.w.winfo_rootx()
        y = self.w.winfo_rooty() + self.w.winfo_height() + 4
        self.tip = tk.Toplevel(self.w)
        self.tip.wm_overrideredirect(True)
        tk.Label(self.tip, text=self.text, bg=INK["ink"], fg=INK["card"], padx=8, pady=3,
                 font=("TkDefaultFont", 9)).pack()
        self.tip.update_idletasks()
        sw = self.w.winfo_screenwidth()
        x = min(x, sw - self.tip.winfo_width() - 4)
        self.tip.wm_geometry(f"+{x}+{y}")

    def _hide(self, e=None):
        if self.job:
            self.w.after_cancel(self.job)
            self.job = None
        if self.tip:
            self.tip.destroy()
            self.tip = None


# ---------------------------------------------------------------- ui state
UI_STATE_NAME = "ui.json"
UI_DEFAULTS = {"left_open": True, "right_open": True, "left_w": 240, "right_w": 330,
               "geometry": "1320x800", "move_out_dir": ""}


def load_ui_state(data_dir):
    state = dict(UI_DEFAULTS)
    try:
        with open(os.path.join(data_dir, UI_STATE_NAME), encoding="utf-8") as f:
            state.update({k: v for k, v in json.load(f).items() if k in UI_DEFAULTS})
    except (OSError, ValueError):
        pass
    return state


def save_ui_state(data_dir, state):
    try:
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, UI_STATE_NAME), "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------- locations
def pick_directory(parent, title, start):
    """Native GTK folder picker via zenity when available, else Tk's dialog."""
    start = start if os.path.isdir(start) else os.path.expanduser("~")
    if shutil.which("zenity"):
        try:
            out = subprocess.run(["zenity", "--file-selection", "--directory",
                                  f"--title={title}", f"--filename={start}/"],
                                 capture_output=True, text=True)
            if out.returncode == 0:
                return out.stdout.strip()
            if out.returncode == 1:
                return ""
        except OSError:
            pass
    return filedialog.askdirectory(parent=parent, title=title, initialdir=start,
                                   mustexist=False)


def count_books(folder):
    n = 0
    for _, _, files in os.walk(folder):
        n += sum(1 for f in files if os.path.splitext(f)[1].lower() in BOOK_EXTS)
    return n


class LocationsDialog:
    """First-run welcome / later 'Library locations'. result = (books_dir, data_dir)."""

    def __init__(self, root, theme, books_dir, data_dir, first_run):
        self.root, self.t, self.result = root, theme, None
        self.first_run = first_run
        self.orig = (books_dir, data_dir)
        top = self.top = tk.Toplevel(root, bg=INK["paper"])
        top.title("Welcome to Koobs" if first_run else "Library locations")
        top.resizable(True, False)
        top.minsize(560, 0)
        if root.winfo_viewable():
            top.transient(root)

        f = ttk.Frame(top)
        f.pack(fill=tk.BOTH, expand=True, padx=24, pady=20)
        ttk.Label(f, text="Welcome to Koobs" if first_run else "Library locations",
                  style="Head.TLabel").pack(anchor="w")
        intro = ("Choose where your books live and where Koobs keeps its data. "
                 "You can change these later with the ⚙ button."
                 if first_run else
                 "Koobs restarts after saving. Your books are never moved by this.")
        ttk.Label(f, text=intro, style="Muted.TLabel", wraplength=520,
                  justify="left").pack(anchor="w", pady=(4, 14))

        self.books = tk.StringVar(value=books_dir)
        self.data = tk.StringVar(value=data_dir)
        self.books_info = self._row(f, "BOOKS FOLDER",
                                    "Your PDFs and EPUBs. Koobs scans it and its subfolders.",
                                    self.books, "Choose books folder")
        self.data_info = self._row(f, "DATA FOLDER",
                                   "Where Koobs keeps your tags and settings (library.json).",
                                   self.data, "Choose data folder")
        self.books.trace_add("write", lambda *a: self._refresh_info())
        self.data.trace_add("write", lambda *a: self._refresh_info())

        btns = ttk.Frame(f)
        btns.pack(fill=tk.X, pady=(18, 0))
        ttk.Button(btns, text="Use defaults", command=self._defaults).pack(side=tk.LEFT)
        self.ok = ttk.Button(btns, text="Start" if first_run else "Save and restart",
                             style="Primary.TButton", command=self._ok)
        self.ok.pack(side=tk.RIGHT)
        ttk.Button(btns, text="Quit" if first_run else "Cancel",
                   command=self._cancel).pack(side=tk.RIGHT, padx=8)
        top.bind("<Escape>", lambda e: self._cancel())
        top.protocol("WM_DELETE_WINDOW", self._cancel)
        self._refresh_info()

        top.update_idletasks()
        if root.winfo_viewable():
            x = root.winfo_rootx() + (root.winfo_width() - top.winfo_reqwidth()) // 2
            y = root.winfo_rooty() + (root.winfo_height() - top.winfo_reqheight()) // 3
        else:
            x = (top.winfo_screenwidth() - top.winfo_reqwidth()) // 2
            y = (top.winfo_screenheight() - top.winfo_reqheight()) // 3
        top.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        top.wait_visibility()
        top.grab_set()
        top.focus_set()

    def _row(self, parent, label, hint, var, title):
        ttk.Label(parent, text=label, style="Cap.TLabel").pack(anchor="w", pady=(6, 2))
        row = ttk.Frame(parent)
        row.pack(fill=tk.X)
        ttk.Entry(row, textvariable=var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        def browse():
            p = pick_directory(self.top, title, var.get())
            if p:
                var.set(p)
            self.top.lift()
        ttk.Button(row, text="Browse…", command=browse).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(parent, text=hint, style="Muted.TLabel").pack(anchor="w", pady=(3, 0))
        info = ttk.Label(parent, text="", style="Muted.TLabel")
        info.pack(anchor="w", pady=(0, 6))
        return info

    def _defaults(self):
        self.books.set(DEFAULT_BOOKS_DIR)
        self.data.set(DEFAULT_DATA_DIR)

    def _refresh_info(self):
        b, d = self.books.get().strip(), self.data.get().strip()
        if not b:
            bt = "✗  Choose a folder"
        elif os.path.isdir(norm_dir(b)):
            bt = f"✓  {count_books(norm_dir(b))} books found"
        elif os.path.exists(norm_dir(b)):
            bt = "✗  That is a file, not a folder"
        else:
            bt = "+  Folder will be created"
        if not d:
            dt = "✗  Choose a folder"
        elif os.path.isfile(os.path.join(norm_dir(d), DB_NAME)):
            try:
                with open(os.path.join(norm_dir(d), DB_NAME), encoding="utf-8") as fh:
                    data = json.load(fh)
                dt = (f"✓  Existing library: {len(data.get('books', {}))} books, "
                      f"{len(data.get('tags', []))} tags")
            except (OSError, ValueError):
                dt = "✗  library.json there is unreadable"
        elif os.path.exists(norm_dir(d)) and not os.path.isdir(norm_dir(d)):
            dt = "✗  That is a file, not a folder"
        elif not self.first_run and os.path.isfile(os.path.join(self.orig[1], DB_NAME)) \
                and norm_dir(d) != norm_dir(self.orig[1]):
            dt = "+  Your current tags will be copied here"
        else:
            dt = "+  A new library will be created"
        self.books_info.config(text=bt)
        self.data_info.config(text=dt)
        self.ok.state(["disabled"] if bt.startswith("✗") or dt.startswith("✗") else ["!disabled"])

    def _ok(self):
        b, d = norm_dir(self.books.get()), norm_dir(self.data.get())
        try:
            os.makedirs(b, exist_ok=True)
            os.makedirs(d, exist_ok=True)
            probe = os.path.join(d, ".koobs-write-test")
            with open(probe, "w") as fh:
                fh.write("")
            os.remove(probe)
        except OSError as e:
            messagebox.showerror("Koobs", f"Cannot use that folder:\n{e}", parent=self.top)
            return
        # Moving the data folder: bring the current tags along (never overwrite).
        old = self.orig[1]
        if not self.first_run and norm_dir(old) != d:
            for name in (DB_NAME, UI_STATE_NAME):
                src, dst = os.path.join(old, name), os.path.join(d, name)
                if os.path.isfile(src) and not os.path.exists(dst):
                    shutil.copy2(src, dst)
        self.result = (b, d)
        self.top.destroy()

    def _cancel(self):
        self.result = None
        self.top.destroy()


# ---------------------------------------------------------------- settings
class SettingsDialog:
    """Appearance (theme picker, applied live) and library locations."""
    TILE_W, TILE_H = 132, 92

    def __init__(self, app):
        self.app = app
        top = self.top = tk.Toplevel(app.root, bg=INK["paper"])
        top.title("Settings")
        top.transient(app.root)
        top.resizable(False, False)

        f = ttk.Frame(top)
        f.pack(fill=tk.BOTH, expand=True, padx=24, pady=20)
        ttk.Label(f, text="Settings", style="Head.TLabel").pack(anchor="w")

        ttk.Label(f, text="APPEARANCE", style="Cap.TLabel").pack(anchor="w", pady=(16, 6))
        tiles = ttk.Frame(f)
        tiles.pack(anchor="w")
        self.tiles = {}
        for i, name in enumerate(THEMES):
            c = tk.Canvas(tiles, width=self.TILE_W, height=self.TILE_H + 22,
                          bg=INK["paper"], highlightthickness=0, cursor="hand2")
            c.grid(row=0, column=i, padx=(0 if i == 0 else 10, 0))
            c.bind("<Button-1>", lambda e, n=name: self._pick(n))
            self.tiles[name] = c
        self._draw_tiles()

        ttk.Label(f, text="LIBRARY", style="Cap.TLabel").pack(anchor="w", pady=(18, 6))
        for label, path in (("Books folder", app.books_dir), ("Data folder", app.data_dir)):
            row = ttk.Frame(f)
            row.pack(fill=tk.X, pady=1)
            ttk.Label(row, text=label, width=13).pack(side=tk.LEFT)
            ttk.Label(row, text=path, style="Muted.TLabel").pack(side=tk.LEFT)
        ttk.Button(f, text="Change locations…", command=self._locations).pack(anchor="w",
                                                                             pady=(10, 0))

        btns = ttk.Frame(f)
        btns.pack(fill=tk.X, pady=(20, 0))
        ttk.Button(btns, text="Done", style="Primary.TButton",
                   command=top.destroy).pack(side=tk.RIGHT)
        top.bind("<Escape>", lambda e: top.destroy())

        top.update_idletasks()
        x = app.root.winfo_rootx() + (app.root.winfo_width() - top.winfo_reqwidth()) // 2
        y = app.root.winfo_rooty() + (app.root.winfo_height() - top.winfo_reqheight()) // 3
        top.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        top.wait_visibility()
        top.grab_set()

    def _draw_tiles(self):
        a, W, H = self.app, self.TILE_W, self.TILE_H
        sample_tags = PALETTE[:2]
        for name, c in self.tiles.items():
            t = THEMES[name]
            on = name == a.theme.name
            c.delete("all")
            c.configure(bg=INK["paper"])
            # outer ring marks the active theme (in the current palette)
            rounded(c, 1, 1, W - 1, H - 1, 10, fill=t["paper"],
                    outline=INK["ink"] if on else INK["rule"], width=2 if on else 1)
            # a miniature book card in that theme
            rounded(c, 12, 14, W - 12, H - 16, 7, fill=t["card"], outline=t["rule"])
            c.create_line(22, 27, W - 44, 27, fill=t["ink"], width=4, capstyle=tk.ROUND)
            c.create_line(22, 38, W - 64, 38, fill=t["muted"], width=3, capstyle=tk.ROUND)
            x = 22
            for col in sample_tags:
                rounded(c, x, 48, x + 26, 58, 4, fill=col, outline=col)
                x += 31
            c.create_line(18, H - 21, W - 18, H - 21, fill=t["rule"], width=3)
            c.create_line(18, H - 21, W * 0.55, H - 21, fill=t["ink"], width=3)
            rounded(c, W - 38, 20, W - 20, 30, 4, fill=t["ink"], outline=t["ink"])
            c.create_text(W / 2, H + 11, text=("✓ " if on else "") + name,
                          fill=INK["ink"], font=a.f_side_b if on else a.f_side)

    def _pick(self, name):
        self.app.set_theme(name)
        self._draw_tiles()

    def _locations(self):
        self.top.destroy()
        self.app.edit_locations()


# ---------------------------------------------------------------- theme
class Theme:
    """Fonts + ttk styles for the active palette. Create once per Tk root."""

    def __init__(self, root, name=DEFAULT_THEME):
        self.root = root
        self.name = name if name in THEMES else DEFAULT_THEME
        INK.clear()
        INK.update(THEMES[self.name])
        self._fonts()
        self._style()

    def apply(self, name):
        """Switch palette live: restyle ttk widgets and recolor plain tk widgets."""
        if name not in THEMES or name == self.name:
            return
        old = dict(INK)
        INK.clear()
        INK.update(THEMES[name])
        self.name = name
        self._style()
        by_old = {}
        for key, val in old.items():          # old color -> palette key
            by_old.setdefault(val.lower(), key)
        self._recolor(self.root, by_old)

    def _recolor(self, w, by_old):
        if not w.winfo_class().startswith("T") or w.winfo_class() in ("Tk", "Toplevel"):
            for opt in ("background", "highlightbackground", "foreground"):
                try:
                    cur = str(w.cget(opt)).lower()
                except tk.TclError:
                    continue
                if cur in by_old:
                    try:
                        w.configure(**{opt: INK[by_old[cur]]})
                    except tk.TclError:
                        pass
        for child in w.winfo_children():
            self._recolor(child, by_old)

    def _fonts(self):
        # Linux first, then Windows / macOS equivalents.
        serif = pick_family(["Noto Serif", "DejaVu Serif", "Liberation Serif",
                             "Georgia", "Cambria", "Times New Roman"])
        sans = pick_family(["Noto Sans", "Ubuntu", "Cantarell", "DejaVu Sans",
                            "Segoe UI", "Helvetica Neue", "Arial"])
        self.f_title = tkfont.Font(family=serif, size=12, weight="bold")
        self.f_sub = tkfont.Font(family=serif, size=10, slant="italic")
        self.f_chip = tkfont.Font(family=sans, size=8, weight="bold")
        self.f_badge = tkfont.Font(family=sans, size=7, weight="bold")
        self.f_side = tkfont.Font(family=sans, size=10)
        self.f_side_b = tkfont.Font(family=sans, size=10, weight="bold")
        self.f_ui = tkfont.Font(family=sans, size=10)
        self.f_head = tkfont.Font(family=serif, size=18, weight="bold")

    def _style(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        p, ink, rule = INK["paper"], INK["ink"], INK["rule"]
        s.configure(".", background=p, foreground=ink, font=self.f_ui,
                    bordercolor=rule, lightcolor=p, darkcolor=p, focuscolor=ink)
        s.configure("TFrame", background=p)
        s.configure("TLabel", background=p, foreground=ink)
        s.configure("Muted.TLabel", foreground=INK["muted"])
        s.configure("Head.TLabel", font=self.f_head)
        s.configure("Cap.TLabel", foreground=INK["faint"], font=self.f_badge)
        s.configure("TButton", background=INK["card"], foreground=ink, bordercolor=ink,
                    lightcolor=INK["card"], darkcolor=INK["card"], padding=(10, 4),
                    relief="solid", borderwidth=1)
        s.map("TButton", background=[("active", INK["sel"]), ("disabled", p)],
              foreground=[("disabled", INK["faint"])], bordercolor=[("disabled", rule)])
        s.configure("Primary.TButton", background=ink, foreground=INK["card"], bordercolor=ink,
                    lightcolor=ink, darkcolor=ink)
        s.map("Primary.TButton", background=[("active", INK["press"]), ("disabled", rule)])
        s.configure("TEntry", fieldbackground=INK["card"], bordercolor=rule,
                    lightcolor=INK["card"], darkcolor=INK["card"], insertcolor=ink, padding=5)
        s.map("TEntry", bordercolor=[("focus", ink)], fieldbackground=[("disabled", p)])
        s.configure("TCombobox", fieldbackground=INK["card"], background=INK["card"],
                    arrowcolor=ink, bordercolor=rule, lightcolor=INK["card"],
                    darkcolor=INK["card"], padding=4)
        s.map("TCombobox", fieldbackground=[("readonly", INK["card"])],
              background=[("readonly", INK["card"]), ("active", INK["sel"])],
              selectbackground=[("readonly", INK["card"])],
              selectforeground=[("readonly", ink)])
        s.configure("Vertical.TScrollbar", background=rule, troughcolor=p, bordercolor=p,
                    arrowcolor=INK["muted"], lightcolor=rule, darkcolor=rule, gripcount=0)
        s.configure("Danger.TButton", foreground=INK["danger"], bordercolor=INK["danger"])
        s.map("Danger.TButton", background=[("active", tint(INK["danger"], 0.88)),
                                            ("disabled", p)],
              foreground=[("disabled", INK["faint"])], bordercolor=[("disabled", rule)])
        s.configure("DangerFill.TButton", background=INK["danger"],
                    foreground=text_on(INK["danger"]),
                    bordercolor=INK["danger"], lightcolor=INK["danger"], darkcolor=INK["danger"])
        s.map("DangerFill.TButton", background=[("active", INK["danger_press"])])
        s.configure("Icon.TButton", background=p, lightcolor=p, darkcolor=p, bordercolor=p,
                    foreground=INK["muted"], padding=(2, 0), font=self.f_head)
        s.map("Icon.TButton", background=[("active", INK["sel"])],
              foreground=[("active", ink)], bordercolor=[("active", INK["sel"])])
        s.configure("Seg.TButton", padding=(6, 4), bordercolor=rule)
        s.map("Seg.TButton", background=[("active", INK["sel"]), ("disabled", p)],
              foreground=[("disabled", INK["faint"])], bordercolor=[("active", ink)])
        s.configure("SegOn.TButton", padding=(6, 4), background=ink, foreground=INK["card"],
                    bordercolor=ink, lightcolor=ink, darkcolor=ink)
        s.map("SegOn.TButton", background=[("active", INK["press"])])
        s.configure("TSpinbox", fieldbackground=INK["card"], background=INK["card"],
                    bordercolor=rule, lightcolor=INK["card"], darkcolor=INK["card"],
                    arrowcolor=ink, insertcolor=ink, padding=3)
        s.map("TSpinbox", bordercolor=[("focus", ink)], fieldbackground=[("disabled", p)],
              arrowcolor=[("disabled", INK["faint"])])
        self.f_gear = tkfont.Font(family=self.f_ui.cget("family"), size=13)
        s.configure("Gear.TButton", background=p, lightcolor=p, darkcolor=p, bordercolor=p,
                    foreground=INK["muted"], padding=(2, 2), font=self.f_gear)
        s.map("Gear.TButton", background=[("active", INK["sel"])],
              foreground=[("active", ink)], bordercolor=[("active", INK["sel"])])
        self.root.option_add("*TCombobox*Listbox.background", INK["card"])
        self.root.option_add("*Menu.background", INK["card"])
        self.root.option_add("*Menu.foreground", ink)
        self.root.option_add("*Menu.activeBackground", INK["sel"])
        self.root.option_add("*Menu.activeForeground", ink)
        self.root.option_add("*Menu.relief", "flat")


# ---------------------------------------------------------------- app
class App:
    def __init__(self, root, theme, books_dir, data_dir):
        self.root, self.theme = root, theme
        self.books_dir, self.data_dir = books_dir, data_dir
        self.lib = Library(books_dir, data_dir)
        self.lib.scan()
        self.lib.save()
        self.filters, self.sort_key = [], "title"
        self.chip_hits = []

        root.title("Koobs")
        root.minsize(720, 480)
        root.configure(bg=INK["paper"])
        self._build()
        root.geometry(self.ui["geometry"])
        self.refresh()

    def __getattr__(self, name):  # fonts (f_title, f_sub, …) live on the theme
        if name.startswith("f_"):
            return getattr(self.theme, name)
        raise AttributeError(name)

    def _side_panel(self, border_side):
        """A pane with a 1px hairline on its inner edge; returns (pane, content)."""
        pane = tk.Frame(self.pw, bg=INK["paper"], bd=0, highlightthickness=0)
        tk.Frame(pane, bg=INK["rule"], width=1).pack(side=border_side, fill=tk.Y)
        content = ttk.Frame(pane)
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        return pane, content

    def _build(self):
        self.ui = load_ui_state(self.data_dir)
        self.pw = pw = tk.PanedWindow(
            self.root, orient=tk.HORIZONTAL, bg=INK["paper"], bd=0, sashwidth=7,
            sashrelief=tk.FLAT, sashpad=0, opaqueresize=True, sashcursor="sb_h_double_arrow")
        pw.pack(fill=tk.BOTH, expand=True)

        # left: brand + tags
        self.left, left = self._side_panel(tk.RIGHT)
        head = ttk.Frame(left)
        head.pack(fill=tk.X, padx=(14, 8), pady=(12, 0))
        ttk.Label(head, text="Koobs", style="Head.TLabel").pack(side=tk.LEFT)
        ttk.Button(head, text="‹", style="Icon.TButton", width=2,
                   command=lambda: self.toggle_panel("left")).pack(side=tk.RIGHT)
        gear = ttk.Button(head, text="⚙", style="Gear.TButton", width=2,
                          command=self.open_settings)
        gear.pack(side=tk.RIGHT)
        Tooltip(gear, "Settings")
        self.sidebar = TagSidebar(left, self)
        self.sidebar.frame.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        ttk.Button(left, text="+  New tag", command=self.new_tag).pack(fill=tk.X, padx=12, pady=12)

        # center: toolbar + cards
        center = ttk.Frame(pw)
        bar = ttk.Frame(center)
        bar.pack(fill=tk.X, padx=14, pady=(14, 4))
        # Reopen arrows: only shown while their panel is closed.
        self.b_left = ttk.Button(bar, text="›", style="Icon.TButton", width=2,
                                 command=lambda: self.toggle_panel("left"))
        self.b_right = ttk.Button(bar, text="‹", style="Icon.TButton", width=2,
                                  command=lambda: self.toggle_panel("right"))
        Tooltip(self.b_left, "Show tags  (Ctrl+[)")
        Tooltip(self.b_right, "Show details  (Ctrl+])")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *a: self.refresh_books())
        self.search_entry = ent = ttk.Entry(bar, textvariable=self.search)
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ent.focus_set()
        ttk.Label(bar, text="  Sort", style="Muted.TLabel").pack(side=tk.LEFT)
        self.sort_var = tk.StringVar(value="Title")
        sort = ttk.Combobox(bar, textvariable=self.sort_var, state="readonly", width=15,
                            values=["Title", "Author", "Format", "Recently added",
                                    "Recently started", "Recently finished", "Progress"])
        sort.pack(side=tk.LEFT, padx=(4, 8))
        sort.bind("<<ComboboxSelected>>", lambda e: self.refresh_books())
        ttk.Button(bar, text="Rescan", command=self.rescan).pack(side=tk.LEFT)
        ttk.Button(bar, text="+  Add books", style="Primary.TButton",
                   command=self.add_books).pack(side=tk.LEFT, padx=(8, 0))
        self.status = ttk.Label(center, text="", style="Muted.TLabel")
        self.status.pack(anchor="w", padx=16, pady=(2, 0))
        self.cards = CardList(center, self)
        self.cards.frame.pack(fill=tk.BOTH, expand=True)

        # right: details
        self.right, right = self._side_panel(tk.LEFT)
        inner = ttk.Frame(right)
        inner.pack(fill=tk.BOTH, expand=True, padx=16, pady=(8, 14))
        head = ttk.Frame(inner)
        head.pack(fill=tk.X)
        self.d_head = ttk.Label(head, text="", style="Cap.TLabel")
        self.d_head.pack(side=tk.LEFT)
        ttk.Button(head, text="›", style="Icon.TButton", width=2,
                   command=lambda: self.toggle_panel("right")).pack(side=tk.RIGHT)
        self.d_title, self.d_author = tk.StringVar(), tk.StringVar()
        ttk.Label(inner, text="TITLE", style="Cap.TLabel").pack(anchor="w", pady=(10, 2))
        self.e_title = ttk.Entry(inner, textvariable=self.d_title)
        self.e_title.pack(fill=tk.X)
        ttk.Label(inner, text="AUTHOR", style="Cap.TLabel").pack(anchor="w", pady=(10, 2))
        self.e_author = ttk.Entry(inner, textvariable=self.d_author)
        self.e_author.pack(fill=tk.X)
        for e in (self.e_title, self.e_author):
            e.bind("<Return>", lambda ev: self.save_meta())
            e.bind("<FocusOut>", lambda ev: self.save_meta())
        self.d_file = ttk.Label(inner, text="", style="Muted.TLabel", wraplength=280)
        self.d_file.pack(anchor="w", pady=8)
        self.b_open = ttk.Button(inner, text="Open book", style="Primary.TButton",
                                 command=self.open_selected)
        self.b_open.pack(fill=tk.X)
        rm = ttk.Frame(inner)
        rm.pack(fill=tk.X, pady=(6, 0))
        rm.columnconfigure((0, 1), weight=1, uniform="rm")
        self.b_move = ttk.Button(rm, text="Move out…", command=self.move_out_selected)
        self.b_move.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        Tooltip(self.b_move, "Move the file to another folder and remove it from Koobs")
        self.b_trash = ttk.Button(rm, text="Move to Trash", style="Danger.TButton",
                                  command=self.trash_selected)
        self.b_trash.grid(row=0, column=1, sticky="ew", padx=(3, 0))

        # reading status: 2x2 segmented buttons; click the active one to clear
        ttk.Label(inner, text="READING  ·  keys 1–4, 0 clears",
                  style="Cap.TLabel").pack(anchor="w", pady=(18, 4))
        seg = ttk.Frame(inner)
        seg.pack(fill=tk.X)
        seg.columnconfigure((0, 1), weight=1, uniform="seg")
        self.st_btns = {}
        for i, key in enumerate(STATUS_KEYS):
            btn = ttk.Button(seg, text=f"{STATUS_ICON[key]}  {STATUS_LABEL[key]}",
                             style="Seg.TButton", command=lambda k=key: self.toggle_status(k))
            btn.grid(row=i // 2, column=i % 2, sticky="ew",
                     padx=(0, 3) if i % 2 == 0 else (3, 0), pady=(0, 6))
            self.st_btns[key] = btn
        self.d_dates = ttk.Label(inner, text="", style="Muted.TLabel")
        self.d_dates.pack(anchor="w")

        # progress: page X of Y, percent, and a thin bar
        ttk.Label(inner, text="PROGRESS", style="Cap.TLabel").pack(anchor="w", pady=(12, 4))
        prog = ttk.Frame(inner)
        prog.pack(fill=tk.X)
        self.pg_cur, self.pg_total = tk.StringVar(), tk.StringVar()
        ttk.Label(prog, text="Page").pack(side=tk.LEFT)
        self.sp_cur = ttk.Spinbox(prog, from_=0, to=100000, width=6,
                                  textvariable=self.pg_cur, command=self.save_progress)
        self.sp_cur.pack(side=tk.LEFT, padx=6)
        ttk.Label(prog, text="of").pack(side=tk.LEFT)
        self.sp_total = ttk.Spinbox(prog, from_=0, to=100000, width=6,
                                    textvariable=self.pg_total, command=self.save_progress)
        self.sp_total.pack(side=tk.LEFT, padx=6)
        self.pg_pct = ttk.Label(prog, text="", style="Muted.TLabel")
        self.pg_pct.pack(side=tk.RIGHT)
        for sp in (self.sp_cur, self.sp_total):
            sp.bind("<Return>", lambda e: self.save_progress())
            sp.bind("<FocusOut>", lambda e: self.save_progress())
        self.pg_bar = tk.Canvas(inner, height=8, bg=INK["paper"], highlightthickness=0)
        self.pg_bar.pack(fill=tk.X, pady=(8, 0))
        self.pg_bar.bind("<Configure>", lambda e: self._draw_progress_bar())

        ttk.Label(inner, text="TAGS  ·  click to toggle, right-click for color",
                  style="Cap.TLabel").pack(anchor="w", pady=(18, 4))
        add = ttk.Frame(inner)
        add.pack(fill=tk.X, pady=(0, 6))
        self.new_tag_var = tk.StringVar()
        e = ttk.Entry(add, textvariable=self.new_tag_var)
        e.pack(side=tk.LEFT, fill=tk.X, expand=True)
        e.bind("<Return>", lambda ev: self.add_tag_to_selection())
        ttk.Button(add, text="Add", command=self.add_tag_to_selection).pack(side=tk.LEFT, padx=(6, 0))
        self.chips = tk.Canvas(inner, bg=INK["paper"], highlightthickness=0, width=290)
        self.chips.pack(fill=tk.BOTH, expand=True)
        bind_wheel(self.chips)
        self.chips.bind("<Configure>", lambda e: self.draw_chips())
        self.chips.bind("<Button-1>", self._chip_click)
        self.chips.bind("<Button-3>", self._chip_menu)
        inner.bind("<Configure>", lambda e: self.d_file.config(wraplength=max(e.width - 8, 120)))

        pw.add(self.left, minsize=170, width=self.ui["left_w"], stretch="never")
        pw.add(center, minsize=420, stretch="always")
        pw.add(self.right, minsize=230, width=self.ui["right_w"], stretch="never")
        for side in ("left", "right"):
            if not self.ui[f"{side}_open"]:
                pw.paneconfigure(getattr(self, side), hide=True)
        self._update_toggle_buttons()

        self.root.bind("<Control-bracketleft>", lambda e: self.toggle_panel("left"))
        self.root.bind("<Control-bracketright>", lambda e: self.toggle_panel("right"))
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------ side panels
    def _panel_open(self, side):
        return not int(self.pw.panecget(getattr(self, side), "hide"))

    def _remember_widths(self):
        for side in ("left", "right"):
            pane = getattr(self, side)
            if self._panel_open(side) and pane.winfo_width() > 1:
                self.ui[f"{side}_w"] = pane.winfo_width()

    def toggle_panel(self, side):
        pane = getattr(self, side)
        self._remember_widths()
        if self._panel_open(side):
            self.pw.paneconfigure(pane, hide=True)
            self.ui[f"{side}_open"] = False
        else:
            self.pw.paneconfigure(pane, hide=False, width=self.ui[f"{side}_w"])
            self.ui[f"{side}_open"] = True
        self._update_toggle_buttons()
        save_ui_state(self.data_dir, self.ui)
        return "break"

    def _update_toggle_buttons(self):
        if self.ui["left_open"]:
            self.b_left.pack_forget()
        else:
            self.b_left.pack(side=tk.LEFT, padx=(0, 6), before=self.search_entry)
        if self.ui["right_open"]:
            self.b_right.pack_forget()
        else:
            self.b_right.pack(side=tk.RIGHT, padx=(6, 0))

    def _on_close(self):
        self._remember_widths()
        geo = self.root.geometry().split("+")[0]
        if self.root.state() == "normal":
            self.ui["geometry"] = geo
        save_ui_state(self.data_dir, self.ui)
        self.root.destroy()

    # ------------------------------------------------------------ refresh
    def refresh(self):
        self.sidebar.redraw()
        self.refresh_books()

    def matches(self, rel, b, q):
        """Search text AND every tag/special filter AND any one of the chosen statuses."""
        if q and q not in (b["title"] + " " + b["author"] + " " + rel).lower():
            return False
        statuses = [t[len(STATUS_PREFIX):] for t in self.filters if is_status(t)]
        if statuses and b.get("status") not in statuses:
            return False
        for t in self.filters:
            if is_status(t):
                continue
            if t == UNTAGGED:
                if b["tags"]:
                    return False
            elif t == MISSING:
                if not b.get("missing"):
                    return False
            elif t not in b["tags"]:
                return False
        return True

    def refresh_books(self):
        self.flush_edits()
        q = self.search.get().strip().lower()
        rows = [(r, b) for r, b in self.lib.books.items() if self.matches(r, b, q)]
        key = self.sort_var.get()
        date_field = {"Recently added": "added", "Recently started": "started",
                      "Recently finished": "finished"}.get(key)
        if date_field:   # newest first; books without that date go last
            rows.sort(key=lambda r: r[1]["title"].lower())
            rows.sort(key=lambda r: r[1].get(date_field) or "", reverse=True)
        elif key == "Progress":   # most-read first; no progress goes last
            rows.sort(key=lambda r: (-(progress(r[1]) if progress(r[1]) is not None else -1),
                                     r[1]["title"].lower()))
        else:
            k = key.lower()
            rows.sort(key=lambda r: (str(r[1].get(k, "")).lower() or "￿", r[1]["title"].lower()))
        self.cards.set_rows(rows)
        label = " + ".join(filter_label(f) for f in self.filters) if self.filters else ALL
        self.status.config(text=f"{label}  —  {len(rows)} of {len(self.lib.books)} books")
        self.on_select()

    def on_select(self):
        books = self.cards.selected()
        one = len(books) == 1
        if one:
            b = self.lib.books[books[0]]
            self.d_head.config(text="SELECTED BOOK")
            self.d_title.set(b["title"])
            self.d_author.set(b["author"])
            self.d_file.config(text=books[0] + ("\n(file missing)" if b.get("missing") else ""))
        else:
            self.d_head.config(text=f"{len(books)} BOOKS SELECTED" if books else "NOTHING SELECTED")
            self.d_title.set("")
            self.d_author.set("")
            self.d_file.config(text="Tag changes apply to all selected books." if books
                               else "Click a card. Ctrl/Shift-click to select several.")
        for w in (self.e_title, self.e_author):
            w.state(["!disabled"] if one else ["disabled"])
        self.b_open.state(["!disabled"] if books else ["disabled"])
        self.b_trash.state(["!disabled"] if books else ["disabled"])
        self.b_move.state(["!disabled"] if books else ["disabled"])
        self._show_reading(books)
        self.draw_chips()

    def _show_reading(self, books):
        statuses = {self.lib.books[r].get("status") for r in books}
        common = next(iter(statuses)) if len(statuses) == 1 else None
        for key, btn in self.st_btns.items():
            btn.configure(style="SegOn.TButton" if books and common == key else "Seg.TButton")
            btn.state(["!disabled"] if books else ["disabled"])
        one = len(books) == 1
        b = self.lib.books[books[0]] if one else {}
        dates = []
        if one and b.get("started"):
            dates.append(f"Started {fmt_date(b['started'])}")
        if one and b.get("finished"):
            dates.append(f"Finished {fmt_date(b['finished'])}")
        self.d_dates.config(text="  ·  ".join(dates))
        self.d_dates.pack_configure(pady=(0, 0) if dates else 0)
        self.pg_cur.set(str(b["page_current"]) if one and "page_current" in b else "")
        self.pg_total.set(str(b["page_total"]) if one and "page_total" in b else "")
        for sp in (self.sp_cur, self.sp_total):
            sp.state(["!disabled"] if one else ["disabled"])
        pct = progress(b) if one else None
        self.pg_pct.config(text=f"{round(pct * 100)}%" if pct is not None else "")
        self._draw_progress_bar(pct)

    def _draw_progress_bar(self, pct="current"):
        if pct == "current":
            books = self.cards.selected()
            pct = progress(self.lib.books[books[0]]) if len(books) == 1 else None
        c = self.pg_bar
        c.delete("all")
        w = max(c.winfo_width(), 50)
        c.create_line(2, 4, w - 2, 4, fill=INK["rule"], width=4, capstyle=tk.ROUND)
        if pct:
            c.create_line(2, 4, 2 + (w - 4) * pct, 4, fill=INK["ink"], width=4,
                          capstyle=tk.ROUND)

    def draw_chips(self):
        c = self.chips
        c.delete("all")
        self.chip_hits = []
        books = self.cards.selected() if hasattr(self, "cards") else []
        w = max(c.winfo_width(), 200)
        x, y, h = 0, 2, self.f_chip.metrics("linespace") + 6
        for t in sorted(self.lib.tags, key=str.lower):
            have = [t in self.lib.books[r]["tags"] for r in books]
            style = "solid" if books and all(have) else "mixed" if any(have) else "off"
            cw = self.f_chip.measure(t) + 16
            if x and x + cw > w:
                x, y = 0, y + h + 8
            nx = draw_chip(c, x, y, t, self.lib.color(t), self.f_chip, style)
            self.chip_hits.append((x, y, x + cw, y + h, t))
            x = nx
        c.configure(scrollregion=(0, 0, w, y + h + 4))

    def _chip_at(self, e):
        x, y = self.chips.canvasx(e.x), self.chips.canvasy(e.y)
        return next((t for x0, y0, x1, y1, t in self.chip_hits
                     if x0 <= x <= x1 and y0 <= y <= y1), None)

    def _chip_click(self, e):
        tag, books = self._chip_at(e), self.cards.selected()
        if not tag or not books:
            return
        remove = all(tag in self.lib.books[r]["tags"] for r in books)
        for r in books:
            (self.lib.untag_book if remove else self.lib.tag_book)(r, tag)
        self.commit()

    def _chip_menu(self, e):
        tag = self._chip_at(e)
        if tag:
            self.tag_menu(tag, e.x_root, e.y_root)

    # ------------------------------------------------------------ actions
    def commit(self):
        self.lib.save()
        self.refresh()

    def tag_menu(self, tag, x, y):
        m = tk.Menu(self.root, tearoff=0)
        colors = tk.Menu(m, tearoff=0)
        for col in PALETTE:
            mark = "  ✓" if col == self.lib.color(tag) else ""
            colors.add_command(label=f"   {col}{mark}", background=col, foreground="#ffffff",
                               activebackground=col, activeforeground="#ffffff",
                               command=lambda col=col: self.set_color(tag, col))
        colors.add_separator()
        colors.add_command(label="Custom…", command=lambda: self.custom_color(tag))
        m.add_cascade(label="Color", menu=colors)
        m.add_command(label="Rename…", command=lambda: self.rename_tag(tag))
        m.add_command(label="Delete…", command=lambda: self.delete_tag(tag))
        m.tk_popup(x, y)

    def set_color(self, tag, color):
        self.lib.set_color(tag, color)
        self.commit()

    def custom_color(self, tag):
        _, hx = colorchooser.askcolor(color=self.lib.color(tag), title=f"Color for {tag}",
                                      parent=self.root)
        if hx:
            self.set_color(tag, hx)

    def add_tag_to_selection(self):
        name = self.new_tag_var.get().strip()
        if not name:
            return
        tag = self.lib.add_tag(name)
        for r in self.cards.selected():
            self.lib.tag_book(r, tag)
        self.new_tag_var.set("")
        self.commit()

    def flush_edits(self):
        """Save a half-typed title/author/page before the selection changes."""
        # The fields always mirror the single selected book, so saving is a no-op
        # unless the user changed something.
        if not hasattr(self, "sp_total") or len(self.cards.selected()) != 1:
            return
        self.save_meta()
        self.save_progress()

    def set_status(self, status):
        books = self.cards.selected()
        if not books:
            return "break"
        self.lib.set_status(books, status)
        self.commit()
        return "break"

    def toggle_status(self, status):
        """Status button: set it, or clear it if every selected book already has it."""
        books = self.cards.selected()
        if books and all(self.lib.books[r].get("status") == status for r in books):
            status = None
        self.set_status(status)

    def save_progress(self):
        books = self.cards.selected()
        if len(books) != 1:
            return

        def num(var):
            v = var.get().strip()
            return int(v) if v.isdigit() else None
        rel = books[0]
        b = self.lib.books[rel]
        before = (b.get("page_current"), b.get("page_total"))
        self.lib.set_progress(rel, num(self.pg_cur), num(self.pg_total))
        if (b.get("page_current"), b.get("page_total")) != before:
            self.lib.save()
            self.cards.redraw()
        self._show_reading(books)   # also normalises the fields (e.g. clamped page)

    def save_meta(self):
        books = self.cards.selected()
        if len(books) != 1:
            return
        b = self.lib.books[books[0]]
        t, a = self.d_title.get().strip(), self.d_author.get().strip()
        if t and (t, a) != (b["title"], b["author"]):
            b["title"], b["author"] = t, a
            self.lib.save()
            self.cards.redraw()

    def new_tag(self):
        name = simpledialog.askstring("New tag", "Tag name:", parent=self.root)
        if name and name.strip():
            self.lib.add_tag(name)
            self.commit()

    def rename_tag(self, old):
        new = simpledialog.askstring("Rename tag", f"New name for '{old}'\n"
                                     "(an existing tag name merges the two):",
                                     initialvalue=old, parent=self.root)
        if new and new.strip() and new.strip() != old:
            self.lib.rename_tag(old, new)
            self.filters = [self.lib.canonical(new) if f == old else f for f in self.filters]
            self.commit()

    def delete_tag(self, tag):
        n = self.lib.counts().get(tag, 0)
        if messagebox.askyesno("Delete tag", f"Delete tag '{tag}'?\nIt is removed from {n} "
                               "books. The books themselves stay in All.", parent=self.root):
            self.lib.delete_tag(tag)
            self.filters = [f for f in self.filters if f != tag]
            self.commit()

    def add_books(self):
        paths = pick_book_files(self.root)
        if not paths:
            return
        dlg = AddDialog(self, paths)
        self.root.wait_window(dlg.top)
        if not dlg.result:
            return
        move, tags = dlg.result
        added, skipped = self.lib.import_files(paths, move=move)
        for rel in added:
            for t in tags:
                self.lib.tag_book(rel, t)
        self.lib.save()
        self.filters = []
        self.search.set("")
        self.refresh()
        if added:
            self.cards.sel = set(added)
            self.cards.anchor = added[0]
            self.cards._changed()
            self.cards.see(self.cards.index[added[0]])
        self.status.config(text=self.status.cget("text") +
                           f"   ·   added {len(added)}" +
                           (f", skipped {len(skipped)}" if skipped else ""))
        if skipped:
            lines = "\n".join(f"• {os.path.basename(p)} — {why}" for p, why in skipped[:15])
            more = f"\n…and {len(skipped) - 15} more" if len(skipped) > 15 else ""
            messagebox.showinfo("Koobs", f"Added {len(added)} book(s).\n\n"
                                f"Skipped {len(skipped)}:\n{lines}{more}", parent=self.root)

    def move_out_selected(self):
        books = self.cards.selected()
        if not books:
            return
        start = self.ui.get("move_out_dir") or os.path.expanduser("~/Desktop")
        dest = pick_directory(self.root, "Move books to…", start)
        if not dest:
            return
        dest = norm_dir(dest)
        root = norm_dir(self.books_dir)
        if dest == root or dest.startswith(root + os.sep):
            messagebox.showerror("Koobs", "That folder is inside your books folder, so the "
                                 "books would stay in the library.\nChoose a folder outside:\n"
                                 f"{root}", parent=self.root)
            return
        if not confirm_move_out(self, books, dest):
            return
        try:
            moved, failed = self.lib.move_out(books, dest)
        except (ValueError, OSError) as e:
            messagebox.showerror("Koobs", str(e), parent=self.root)
            return
        self.lib.save()
        self.ui["move_out_dir"] = dest
        save_ui_state(self.data_dir, self.ui)
        self.cards.sel -= {r for r, _ in moved}
        self.refresh()
        self.status.config(text=self.status.cget("text") +
                           f"   ·   moved {len(moved)} out to {dest}")
        if failed:
            lines = "\n".join(f"• {r} — {why}" for r, why in failed[:10])
            messagebox.showwarning("Koobs", f"Moved {len(moved)} book(s).\n\n"
                                   f"Could not move {len(failed)}:\n{lines}", parent=self.root)

    def trash_selected(self):
        books = self.cards.selected()
        if not books:
            return
        if not confirm_trash(self, books):
            return
        removed, failed = self.lib.trash_books(books)
        self.lib.save()
        self.cards.sel -= set(removed)
        self.refresh()
        self.status.config(text=self.status.cget("text") +
                           f"   ·   moved {len(removed)} to Trash")
        if failed:
            lines = "\n".join(f"• {r} — {why}" for r, why in failed[:10])
            messagebox.showerror("Koobs", f"Could not move {len(failed)} file(s) to "
                                 f"the Trash:\n\n{lines}", parent=self.root)

    def rescan(self):
        added, missing = self.lib.scan()
        self.commit()
        self.status.config(text=self.status.cget("text") + f"   ·   rescan: {added} new, {missing} missing")

    def open_selected(self):
        for r in self.cards.selected()[:5]:
            p = self.lib.abspath(r)
            if os.path.exists(p):
                try:
                    open_path(p)
                except OSError as e:
                    messagebox.showerror("Koobs", f"Could not open the book:\n{e}",
                                         parent=self.root)
                    return
            else:
                messagebox.showwarning("Koobs", f"File not found:\n{p}", parent=self.root)

    def open_settings(self):
        SettingsDialog(self)

    def set_theme(self, name):
        if name == self.theme.name:
            return
        self.theme.apply(name)
        save_pref("theme", name)
        self.refresh()                 # redraw the hand-drawn parts (cards, sidebar, chips)
        self._draw_progress_bar()

    def edit_locations(self):
        dlg = LocationsDialog(self.root, self.theme, self.books_dir, self.data_dir,
                              first_run=False)
        self.root.wait_window(dlg.top)
        if not dlg.result:
            return
        books, data = dlg.result
        if (books, data) == (norm_dir(self.books_dir), norm_dir(self.data_dir)):
            return
        save_config(books, data)
        self.data_dir = data       # so the panel/window state is saved to the new place
        self._on_close()           # saves panel state, destroys the window
        restart_app()              # a fresh Koobs starts; this one exits as mainloop ends


def main():
    enable_hidpi()
    root = tk.Tk()
    root.withdraw()                # stay hidden until locations are known
    root.title("Koobs")
    theme = Theme(root, load_pref("theme", DEFAULT_THEME))
    cfg = load_config()
    if cfg is None or not os.path.isdir(cfg["books_dir"]) or not os.path.isdir(cfg["data_dir"]):
        books = cfg["books_dir"] if cfg else DEFAULT_BOOKS_DIR
        data = cfg["data_dir"] if cfg else DEFAULT_DATA_DIR
        dlg = LocationsDialog(root, theme, books, data, first_run=True)
        root.wait_window(dlg.top)
        if not dlg.result:
            root.destroy()
            return
        save_config(*dlg.result)
        cfg = {"books_dir": dlg.result[0], "data_dir": dlg.result[1]}
    App(root, theme, cfg["books_dir"], cfg["data_dir"])
    root.deiconify()
    root.mainloop()
