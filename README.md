<h1 align="center">📚 Koobs</h1>

<p align="center">
  <b>Your ebook folder, finally organized.</b><br>
  Tag it. Track it. Find it. Read it, in a calm, ink-on-paper desktop app.
</p>

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-1a1915?style=flat-square">
  <img alt="No dependencies" src="https://img.shields.io/badge/dependencies-none-2a7f62?style=flat-square">
  <img alt="Linux" src="https://img.shields.io/badge/platform-Linux-3d5a80?style=flat-square">
  <img alt="Themes" src="https://img.shields.io/badge/themes-5-a23e48?style=flat-square">
</p>

<p align="center">
  <img src="docs/screenshots/ink.png" alt="Koobs: the library in the Ink theme" width="900">
</p>

---

## Why Koobs?

You have a folder of PDFs and EPUBs. Hundreds of them, maybe. Names like
`Meditations (Marcus Aurelius) (z-lib.org).pdf`. You know there's a great physics
book in there somewhere, and you started *something* last month but can't remember what.

**Koobs turns that folder into a library you actually want to open:**

- 🏷️ **Tag anything.** Colored tags, as many per book as you like, and filters that stack.
- 📖 **Know where you are.** Want to read, Reading, Finished, Dropped, with page progress drawn right on the card.
- 🔎 **Find it in a keystroke.** Live search across titles, authors and file names.
- 🎨 **Make it yours.** Five hand-tuned themes, from warm paper to deep night.
- 🪶 **Weightless.** Pure Python, no installs, starts instantly, and your files stay where they are.

---

## Get started in 10 seconds

```sh
git clone <this repo> koobs && cd koobs
./run.sh
```

That's it. On first launch Koobs asks two questions:

> **Where are your books?** → any folder (subfolders included)
> **Where should Koobs keep its notes?** → defaults to a hidden `.local/` folder right here

<sub>Needs Python 3.10+ with Tkinter (`sudo apt install python3-tk` if missing).
<code>zenity</code>, <code>gio</code> and <code>xdg-open</code> are used when present, for native file pickers, the desktop Trash and opening books.</sub>

---

## A quick tour

### 🏷️ Tags that stay out of your way
Every tag gets its own color. Click a tag in the sidebar to filter, or **Ctrl-click** several to
narrow down ("Philosophy **and** Strategy"). Select ten books and click a tag chip to tag all ten
at once. Right-click any tag to recolor, rename or merge it.

### 📖 Reading status, at a glance
Mark books as **○ Want to read · ◐ Reading · ● Finished · ✕ Dropped**. Use a button, a
right-click, or just press **1–4**. Koobs notes when you started and finished. Enter
*page 212 of 635* and a thin progress line appears along the bottom of the card.

<p align="center">
  <img src="docs/screenshots/night.png" alt="Filtering by Reading in the Night theme" width="760"><br>
  <sub>Everything you're currently reading, in the <b>Night</b> theme.</sub>
</p>

### ➕ Adding and tidying up
- **+ Add books:** pick files, copy *or* move them in, and tag them in the same step. Exact duplicates are skipped, and name clashes get `(2)` added automatically.
- **Move out…:** send books to another folder when you're done with them.
- **Move to Trash:** they land in your desktop Trash, so it can be undone.

Nothing destructive happens without a confirmation, and **Cancel** is always the default.

### 🎨 Five themes, switched live
**Ink** · **Paper** · **Sepia** · **Night** · **Slate.** Pick one in ⚙ **Settings** and the whole app
changes instantly, with no restart.

<p align="center">
  <img src="docs/screenshots/sepia.png" alt="The Sepia theme filtered by Philosophy" width="49%">
  <img src="docs/screenshots/settings.png" alt="Settings with theme previews" width="49%">
</p>

### 🪟 A layout that bends
Drag the panel edges to resize, or close them with **‹ ›** for a distraction-free list. Koobs
remembers your layout, window size and theme.

---

## ⌨️ Keyboard

| Key | Does |
|---|---|
| <kbd>↑</kbd> <kbd>↓</kbd> | move through books |
| <kbd>Enter</kbd> / double-click | open the book |
| <kbd>Ctrl</kbd>+<kbd>A</kbd> | select everything visible |
| <kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd> <kbd>4</kbd> | Want to read · Reading · Finished · Dropped |
| <kbd>0</kbd> | clear status |
| <kbd>Delete</kbd> | move to Trash (asks first) |
| <kbd>Ctrl</kbd>+<kbd>[</kbd> · <kbd>Ctrl</kbd>+<kbd>]</kbd> | toggle tags panel · details panel |

---

## 🔒 Your data, your files

Koobs never renames or reorganizes your books. All it keeps is a small JSON notebook:

```
~/.config/koobs/config.json   where your books and data live, plus your theme
<data>/library.json           tags, colors, statuses, page progress
<data>/ui.json                panel sizes, window size
```

- Point Koobs at a different folder (even a parent or child of the old one) and every tag, status and page number is **re-mapped automatically**. Nothing is duplicated or lost.
- Every save is atomic: written to a temp file, then swapped in.
- Your books (`All/`) and data (`.local/`) are **git-ignored**, so they never end up in a commit.

---

## 🧭 Under the hood

```
app/
├── koobs.py    entry point
├── ui.py       the interface: themes, card list, sidebar, dialogs
├── store.py    the library: config, scanning, tags, status, import / trash / move-out
└── tagger.py   one-off bulk tagger used to seed the first library
run.sh          launcher
```

The card list and sidebar are drawn by hand on a Tk canvas. That's how a stock Tkinter app gets
rounded cards, colored chips and progress lines without a single dependency.

<p align="center"><sub>Made for people with too many PDFs. 📚</sub></p>
