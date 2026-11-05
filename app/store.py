"""Library data: load/save <data dir>/library.json and keep it in sync with the books folder."""
import datetime
import filecmp
import json
import os
import re
import shutil
import time

from osutil import config_dir, move_to_trash  # noqa: F401  (re-exported)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_BOOKS_DIR = os.path.join(ROOT, "All")
DEFAULT_DATA_DIR = os.path.join(ROOT, ".local")
DB_NAME = "library.json"
BOOK_EXTS = {".pdf", ".epub", ".mobi", ".azw3", ".djvu"}

# Reading status: (key, label, symbol). Stored as book["status"] = key.
STATUSES = [("want", "Want to read", "○"), ("reading", "Reading", "◐"),
            ("finished", "Finished", "●"), ("dropped", "Dropped", "✕")]
STATUS_KEYS = [k for k, _, _ in STATUSES]
STATUS_LABEL = {k: label for k, label, _ in STATUSES}
STATUS_ICON = {k: icon for k, _, icon in STATUSES}


def progress(book):
    """Fraction 0..1 read, or None if pages are not filled in."""
    total, cur = book.get("page_total"), book.get("page_current")
    if not total or cur is None:
        return None
    return max(0.0, min(1.0, cur / total))


# Where the chosen locations are remembered. Lives outside the data folder,
# because the data folder itself is configurable. KOOBS_CONFIG overrides (tests).
# Linux: ~/.config/koobs · Windows: %APPDATA%\Koobs · macOS: ~/Library/Application Support/Koobs
CONFIG_PATH = os.environ.get("KOOBS_CONFIG") or os.path.join(config_dir(), "config.json")


def norm_dir(path):
    return os.path.abspath(os.path.expanduser(path.strip()))


def load_config():
    """{'books_dir', 'data_dir'} or None when the app has not been set up yet."""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        if cfg.get("books_dir") and cfg.get("data_dir"):
            return {"books_dir": cfg["books_dir"], "data_dir": cfg["data_dir"]}
    except (OSError, ValueError):
        pass
    return None


def _read_config_file():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_config_file(data):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


def save_config(books_dir, data_dir):
    data = _read_config_file()          # keep other preferences (e.g. theme)
    data.update({"books_dir": books_dir, "data_dir": data_dir})
    _write_config_file(data)


def load_pref(key, default=None):
    """App-wide preferences (not tied to a library), stored in the config file."""
    return _read_config_file().get(key, default)


def save_pref(key, value):
    data = _read_config_file()
    data[key] = value
    _write_config_file(data)

# Muted, ink-friendly tag colors (all dark enough for white chip text).
PALETTE = [
    "#3d5a80", "#a23e48", "#2a7f62", "#b5651d", "#6c4f8c", "#1f6f78",
    "#8c5a3c", "#a8577e", "#5a6b2e", "#c44536", "#44546a", "#8a6d1f",
    "#7b3f61", "#4f772d", "#9c6644", "#2e4f6e", "#7a4e2d", "#5b5f97",
    "#3f7d6e", "#8e3b46",
]

_ZLIB = re.compile(r"\s*\((?:z-lib[^)]*|z-library[^)]*|Z-Library)\)\s*$", re.I)


def parse_name(filename):
    """'Title (Author) (Z-Library).pdf' -> ('Title', 'Author')."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    stem = _ZLIB.sub("", stem).strip()
    # Drop trailing "(2008)" year or "(1)" copy markers, and a leading "(Series)".
    trailing_year = re.search(r"\s*\(\s*(\d{1,4})\s*\)$", stem)
    stem = re.sub(r"\s*\(\s*\d{1,4}\s*\)$", "", stem).strip()
    stem = re.sub(r"^\([^()]*\)\s*", "", stem).strip()
    # Library-genesis style: "Author - Title-Publisher (Year)".
    if trailing_year and " - " in stem:
        author, title = stem.split(" - ", 1)
        title = re.sub(r"(?<=[^\s-])-(?=[A-Z]).*$", "", title)
        return title.replace("_", ":").strip(), author.strip()
    m = re.match(r"^(.*\S)\s*\(([^()]+)\)$", stem)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = re.match(r"^(.*\S)\s+by\s+(.+)$", stem)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return stem.replace("_", " ").strip(), ""


def to_key(rel_os_path):
    """Book keys always use '/' so a library.json is portable between machines."""
    return rel_os_path.replace(os.sep, "/") if os.sep != "/" else rel_os_path


# Fields that are per-device or bookkeeping, so they don't count as an edit.
_VOLATILE = ("missing", "updated")


def _fingerprint(book):
    return json.dumps({k: v for k, v in book.items() if k not in _VOLATILE},
                      sort_keys=True, ensure_ascii=False)


def _merge_entry(keep, other):
    """Fold a duplicate book entry into `keep` without losing anything the user set."""
    for t in other.get("tags", []):
        if t not in keep.setdefault("tags", []):
            keep["tags"].append(t)
    keep["tags"].sort(key=str.lower)
    for f in ("status", "started", "finished", "page_current", "page_total"):
        if f not in keep and f in other:
            keep[f] = other[f]


def _same_file(a, b):
    return os.path.getsize(a) == os.path.getsize(b) and filecmp.cmp(a, b, shallow=False)


class Library:
    def __init__(self, books_dir, data_dir):
        self.path = os.path.join(data_dir, DB_NAME)
        self.all_dir = books_dir
        self.tags = []
        self.books = {}
        self.tag_colors = {}
        # Sync bookkeeping (see save()/merge_from()): when each tag last changed,
        # and when books/tags were removed ("tombstones", so a sync doesn't revive them).
        self.tag_updated = {}
        self.deleted = {}
        self.deleted_tags = {}
        self._snap_books, self._snap_tags = {}, {}
        self.load()

    # ---- colors ----
    def _next_color(self):
        used = list(self.tag_colors.values())
        return min(PALETTE, key=lambda c: (used.count(c), PALETTE.index(c)))

    def color(self, tag):
        return self.tag_colors.get(tag) or "#6b675c"

    def set_color(self, tag, color):
        if tag in self.tags:
            self.tag_colors[tag] = color

    # ---- persistence ----
    def load(self):
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self._apply_data(data)
            self._take_snapshot()
            old_root = data.get("books_dir")
            if old_root and os.path.abspath(old_root) != os.path.abspath(self.all_dir):
                self._rebase(old_root)      # changed keys get stamped on the next save
        for t in self.tags:
            if t not in self.tag_colors:
                self.tag_colors[t] = self._next_color()

    def _apply_data(self, data):
        self.tags = list(data.get("tags", []))
        self.books = {to_key(k): v for k, v in data.get("books", {}).items()}
        self.tag_colors = dict(data.get("tag_colors", {}))
        self.tag_updated = dict(data.get("tag_updated", {}))
        self.deleted = {to_key(k): v for k, v in data.get("deleted", {}).items()}
        self.deleted_tags = dict(data.get("deleted_tags", {}))

    def _take_snapshot(self):
        self._snap_books = {rel: _fingerprint(b) for rel, b in self.books.items()}
        self._snap_tags = {t: self.tag_colors.get(t) for t in self.tags}

    def _stamp_changes(self):
        """Mark what changed since the last save with a time; record removals."""
        now = round(time.time(), 3)
        for rel, b in self.books.items():
            if self._snap_books.get(rel) != _fingerprint(b):
                b["updated"] = now
                self.deleted.pop(rel, None)
        for rel in self._snap_books:
            if rel not in self.books:
                self.deleted[rel] = now
        for t in self.tags:
            if t not in self._snap_tags or self._snap_tags[t] != self.tag_colors.get(t):
                self.tag_updated[t] = now
                self.deleted_tags.pop(t, None)
        for t in self._snap_tags:
            if t not in self.tags:
                self.deleted_tags[t] = now
                self.tag_updated.pop(t, None)

    def to_data(self):
        self.tags.sort(key=str.lower)
        return {"version": 2,
                # Book keys are relative to this folder; used to remap if it changes.
                "books_dir": os.path.abspath(self.all_dir),
                "tags": self.tags,
                "tag_colors": {t: self.tag_colors[t] for t in self.tags if t in self.tag_colors},
                "tag_updated": {t: self.tag_updated[t] for t in self.tags
                                if t in self.tag_updated},
                "books": dict(sorted(self.books.items(), key=lambda kv: kv[0].lower())),
                "deleted": dict(sorted(self.deleted.items())),
                "deleted_tags": dict(sorted(self.deleted_tags.items()))}

    # ---- sync: checkpoints, so a sync can be undone before any file is touched ----
    def checkpoint(self):
        return json.loads(json.dumps(self.to_data()))

    def rollback(self, cp):
        """Restore a checkpoint exactly (no change stamps) and write it to disk."""
        self._apply_data(cp)
        self._take_snapshot()
        self.save()

    def touch(self, rels):
        """Mark books as just edited, so they win over removals from other devices."""
        now = round(time.time(), 3)
        for rel in rels:
            if rel in self.books:
                self.books[rel]["updated"] = now
                self.deleted.pop(rel, None)
        self._take_snapshot()
        self.save()

    # ---- sync: merge another copy of library.json into this one ----
    def merge_from(self, remote):
        """Merge another device's library data (a dict) into this library and save.

        Per book and per tag, the newest change wins: an edit (book["updated"],
        tag_updated) or a removal (deleted / deleted_tags). Device-only fields such as
        "missing" are never taken from the other side. Safe to repeat.
        Returns counts: {"books_in", "books_removed", "tags_in", "tags_removed"}.
        """
        self.save()                                  # stamp any pending local edits
        r_books = {to_key(k): v for k, v in remote.get("books", {}).items()}
        r_del = {to_key(k): v for k, v in remote.get("deleted", {}).items()}
        stats = {"books_in": 0, "books_removed": 0, "tags_in": 0, "tags_removed": 0}

        for k in set(self.books) | set(r_books) | set(self.deleted) | set(r_del):
            lb, rb = self.books.get(k), r_books.get(k)
            best = lb
            if rb is not None and (lb is None or rb.get("updated", 0) > lb.get("updated", 0)):
                best = rb
            best_ts = best.get("updated", 0) if best else None
            del_ts = max(self.deleted.get(k, 0), r_del.get(k, 0)) or None
            if del_ts is not None and (best is None or del_ts >= best_ts):
                if lb is not None:
                    stats["books_removed"] += 1
                    del self.books[k]
                self.deleted[k] = del_ts
            elif best is not lb:
                entry = {kk: vv for kk, vv in best.items() if kk != "missing"}
                if lb is not None and lb.get("missing"):
                    entry["missing"] = True
                self.books[k] = entry
                self.deleted.pop(k, None)
                stats["books_in"] += 1

        r_tags = set(remote.get("tags", []))
        r_colors, r_tu = remote.get("tag_colors", {}), remote.get("tag_updated", {})
        r_dt = remote.get("deleted_tags", {})
        for t in set(self.tags) | r_tags | set(self.deleted_tags) | set(r_dt):
            here, there = t in self.tags, t in r_tags
            l_ts = self.tag_updated.get(t, 0) if here else None
            r_ts = r_tu.get(t, 0) if there else None
            live_ts = max(x for x in (l_ts, r_ts, -1) if x is not None)
            del_ts = max(self.deleted_tags.get(t, 0), r_dt.get(t, 0)) or None
            if del_ts is not None and (not (here or there) or del_ts >= live_ts):
                if here:
                    self.tags.remove(t)
                    self.tag_colors.pop(t, None)
                    self.tag_updated.pop(t, None)
                    stats["tags_removed"] += 1
                self.deleted_tags[t] = del_ts
            elif there and (not here or r_ts > l_ts):
                if not here:
                    self.tags.append(t)
                    stats["tags_in"] += 1
                if t in r_colors:
                    self.tag_colors[t] = r_colors[t]
                self.tag_updated[t] = r_ts
                self.deleted_tags.pop(t, None)
        for b in self.books.values():               # a book may use a tag we don't list
            for t in b.get("tags", []):
                if t not in self.tags:
                    self.tags.append(t)
                    self.tag_colors.setdefault(t, self._next_color())
        for t in self.tags:
            self.tag_colors.setdefault(t, self._next_color())

        self._take_snapshot()                        # merged state isn't a local edit
        self.save()
        return stats

    def _rebase(self, old_root):
        """The books folder changed: map every entry to its path in the new folder.

        Keys are paths relative to the books folder, so moving the books folder from
        Koobs/All to its parent Koobs turns 'x.pdf' into 'All/x.pdf' (and back again).
        Entries that land on the same key are merged (tags unioned, status/progress
        kept) instead of duplicated. Entries outside the new folder keep their key
        and show up as missing.
        """
        new_root = os.path.abspath(self.all_dir)
        rebased = {}
        for rel, b in self.books.items():
            nrel = os.path.relpath(os.path.join(os.path.abspath(old_root), *rel.split("/")),
                                   new_root)
            if nrel == os.pardir or nrel.startswith(os.pardir + os.sep):
                nrel = rel                          # outside the new folder
            else:
                nrel = to_key(nrel)
            if nrel in rebased:
                _merge_entry(rebased[nrel], b)
            else:
                rebased[nrel] = b
        self.books = rebased

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._stamp_changes()
        data = self.to_data()
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)
        self._take_snapshot()

    # ---- sync with disk ----
    def import_files(self, paths, move=False):
        """Copy (or move) book files into All/ and register them.

        Returns (added_rels, skipped) where skipped is a list of (path, reason).
        Identical files already in All are skipped; name clashes get ' (2)', ' (3)'…
        """
        added, skipped = [], []
        os.makedirs(self.all_dir, exist_ok=True)
        for src in paths:
            src = os.path.abspath(src)
            name = os.path.basename(src)
            stem, ext = os.path.splitext(name)
            if ext.lower() not in BOOK_EXTS:
                skipped.append((src, "not a book file"))
                continue
            if not os.path.isfile(src):
                skipped.append((src, "not found"))
                continue
            if os.path.dirname(src).startswith(os.path.abspath(self.all_dir) + os.sep) or \
                    os.path.dirname(src) == os.path.abspath(self.all_dir):
                skipped.append((src, "already in All"))
                continue
            dest, n = os.path.join(self.all_dir, name), 2
            dup = False
            while os.path.exists(dest):
                if _same_file(src, dest):
                    dup = True
                    break
                dest = os.path.join(self.all_dir, f"{stem} ({n}){ext}")
                n += 1
            if dup:
                skipped.append((src, "duplicate of " + os.path.basename(dest)))
                continue
            if move:
                shutil.move(src, dest)
            else:
                shutil.copy2(src, dest)
            rel = to_key(os.path.relpath(dest, self.all_dir))
            title, author = parse_name(name)
            self.books[rel] = {"title": title, "author": author,
                               "format": ext[1:].lower(), "tags": [],
                               "added": datetime.date.today().isoformat()}
            added.append(rel)
        return added, skipped

    def trash_books(self, rels):
        """Move book files to the desktop Trash and drop them from the library.

        Entries whose file is already missing are just removed from the library.
        Returns (removed_rels, failed) where failed is a list of (rel, reason).
        """
        removed, failed = [], []
        for rel in rels:
            if rel not in self.books:
                continue
            path = self.abspath(rel)
            if os.path.lexists(path):
                try:
                    move_to_trash(path)
                except OSError as e:
                    failed.append((rel, str(e)))
                    continue
            del self.books[rel]
            removed.append(rel)
        return removed, failed

    def move_out(self, rels, dest_dir):
        """Move book files to dest_dir (outside the library) and drop them from it.

        Never overwrites: a name clash gets ' (2)', ' (3)'…  Missing files are skipped.
        Returns (moved, failed): moved = [(rel, new_path)], failed = [(rel, reason)].
        """
        dest_dir = os.path.abspath(dest_dir)
        books_root = os.path.abspath(self.all_dir)
        if dest_dir == books_root or dest_dir.startswith(books_root + os.sep):
            raise ValueError("The destination is inside the books folder.")
        os.makedirs(dest_dir, exist_ok=True)
        moved, failed = [], []
        for rel in rels:
            if rel not in self.books:
                continue
            src = self.abspath(rel)
            if not os.path.isfile(src):
                failed.append((rel, "file is missing"))
                continue
            stem, ext = os.path.splitext(os.path.basename(src))
            dest, n = os.path.join(dest_dir, stem + ext), 2
            while os.path.lexists(dest):
                dest = os.path.join(dest_dir, f"{stem} ({n}){ext}")
                n += 1
            try:
                shutil.move(src, dest)
            except OSError as e:
                failed.append((rel, str(e)))
                continue
            del self.books[rel]
            moved.append((rel, dest))
        return moved, failed

    def scan(self):
        """Add new files, flag missing ones. Returns (added, missing) counts."""
        found = set()
        for dirpath, _, files in os.walk(self.all_dir):
            for name in files:
                if os.path.splitext(name)[1].lower() in BOOK_EXTS:
                    found.add(to_key(os.path.relpath(os.path.join(dirpath, name),
                                                     self.all_dir)))
        added = 0
        for rel in found:
            b = self.books.get(rel)
            if b is None:
                title, author = parse_name(rel)
                self.books[rel] = {
                    "title": title, "author": author,
                    "format": os.path.splitext(rel)[1][1:].lower(),
                    "tags": [], "added": datetime.date.today().isoformat()}
                added += 1
            else:
                b.pop("missing", None)
        missing = 0
        for rel, b in self.books.items():
            if rel not in found:
                b["missing"] = True
                missing += 1
        return added, missing

    def abspath(self, rel):
        return os.path.join(self.all_dir, *rel.split("/"))

    # ---- tags ----
    def add_tag(self, tag):
        tag = tag.strip()
        if tag and tag.lower() not in (t.lower() for t in self.tags):
            self.tags.append(tag)
            self.tag_colors.setdefault(tag, self._next_color())
        return self.canonical(tag)

    def canonical(self, tag):
        for t in self.tags:
            if t.lower() == tag.strip().lower():
                return t
        return tag.strip()

    def rename_tag(self, old, new):
        new = new.strip()
        if not new or old not in self.tags:
            return
        existing = self.canonical(new)
        merge = existing in self.tags and existing != old
        self.tags.remove(old)
        color = self.tag_colors.pop(old, None)
        if not merge:
            self.tags.append(new)
            existing = new
            self.tag_colors[new] = color or self._next_color()
        for b in self.books.values():
            if old in b["tags"]:
                b["tags"].remove(old)
                if existing not in b["tags"]:
                    b["tags"].append(existing)

    def delete_tag(self, tag):
        if tag in self.tags:
            self.tags.remove(tag)
        self.tag_colors.pop(tag, None)
        for b in self.books.values():
            if tag in b["tags"]:
                b["tags"].remove(tag)

    def tag_book(self, rel, tag):
        tag = self.add_tag(tag)
        tags = self.books[rel]["tags"]
        if tag not in tags:
            tags.append(tag)
            tags.sort(key=str.lower)

    def untag_book(self, rel, tag):
        tags = self.books[rel]["tags"]
        if tag in tags:
            tags.remove(tag)

    # ---- reading status & progress ----
    def set_status(self, rels, status):
        """status: one of STATUS_KEYS, or None to clear. Keeps started/finished dates."""
        today = datetime.date.today().isoformat()
        for rel in rels:
            b = self.books[rel]
            if status is None:
                for k in ("status", "started", "finished"):
                    b.pop(k, None)
                continue
            if b.get("status") == status:
                continue
            b["status"] = status
            if status == "want":
                b.pop("started", None)
                b.pop("finished", None)
            elif status == "reading":
                b.setdefault("started", today)
                b.pop("finished", None)
            elif status == "finished":
                b["finished"] = today
            elif status == "dropped":
                b.pop("finished", None)

    def set_progress(self, rel, current, total):
        """Pages: ints >= 0 or None. current is clamped to total."""
        b = self.books[rel]
        if total is not None and total <= 0:
            total = None
        if current is not None and current < 0:
            current = 0
        if current is not None and total is not None:
            current = min(current, total)
        for key, val in (("page_current", current), ("page_total", total)):
            if val is None:
                b.pop(key, None)
            else:
                b[key] = val

    def status_counts(self):
        c = {k: 0 for k in STATUS_KEYS}
        for b in self.books.values():
            if b.get("status") in c:
                c[b["status"]] += 1
        return c

    def counts(self):
        c = {t: 0 for t in self.tags}
        for b in self.books.values():
            for t in b["tags"]:
                c[t] = c.get(t, 0) + 1
        return c
