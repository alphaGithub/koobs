# CLAUDE.md: notes for working on Koobs

Koobs is a personal ebook manager: a Tkinter desktop app, pure Python stdlib, no pip dependencies. The user's real library lives in this repo folder (`All/` for books, `.local/` for data). **Treat both as live user data.**

## Run / check
```sh
./run.sh                                  # launch (python3 app/koobs.py)
python3 -m py_compile app/*.py            # quick syntax check
pkill -f '[a]pp/koobs\.py'                # stop a running instance (bracket stops pkill matching its own shell)
```
- There is no test suite. Verify by driving the UI from a script (see *Testing safely*).
- Screenshots: `xwd -silent -id <widget.winfo_id()> -out f.xwd`, then convert to PNG with a small PIL script that parses the XWD header. The session is Wayland, so `PIL.ImageGrab` returns a black image.

## Layout
| File | Role |
|---|---|
| `app/store.py` | Data layer, with no Tk imports. Config (`load_config`, `save_config`, `load_pref`, `save_pref`), `parse_name`, `move_to_trash`, `progress()`, `STATUSES`, `PALETTE`, and `Library` (load/save/scan/rebase, tags, colors, `set_status`, `set_progress`, `import_files`, `trash_books`, `move_out`). |
| `app/ui.py` | All UI. `THEMES` + `INK` (active palette), drawing helpers (`rounded`, `fit`, `draw_chip`, `text_on`, `tint`), `CardList`, `TagSidebar`, `AddDialog`, `_book_list_dialog` (+ `confirm_trash`, `confirm_move_out`), `Tooltip`, `LocationsDialog`, `SettingsDialog`, `Theme`, `App`, `main()`. |
| `app/koobs.py` | Entry point, calls `ui.main()`. |
| `app/tagger.py` | One-off bulk tagger from the original category-folder shortcuts (those folders are gone). Reference only. |

## Data model
- `~/.config/koobs/config.json` (override with env `KOOBS_CONFIG`): `books_dir`, `data_dir`, `theme`. App-wide.
- `<data_dir>/library.json`: `{version, books_dir, tags[], tag_colors{}, books{rel_path: {...}}}`.
  - Book fields: `title`, `author`, `format`, `tags[]`, `added`, optional `missing`, `status` (`want|reading|finished|dropped`), `started`, `finished`, `page_current`, `page_total`.
  - **Keys are paths relative to `books_dir`.** `library.json` stores `books_dir`, and `Library._rebase()` re-keys and merges entries when it changes. This fixed a real bug: switching to the parent folder doubled every book.
- `<data_dir>/ui.json`: panel open/widths, window geometry, `move_out_dir`.
- Defaults: `DEFAULT_BOOKS_DIR = Koobs/All`, `DEFAULT_DATA_DIR = Koobs/.local`.
- Saves are atomic (write `.tmp`, then `os.replace`). Every mutation calls `lib.save()` immediately; there is no "unsaved" state.

## UI architecture notes
- The book list and the sidebar are **hand-drawn on a `tk.Canvas`**, not Treeview/Listbox. That's what makes cards, chips and badges possible. `CardList` selection and hover restyle items via `itemconfigure` on the `bg{i}` tag; a full `redraw()` happens only on data changes.
- **Theming:** never hard-code colors. Use `INK[...]` keys (`paper card ink muted faint rule hover sel danger press danger_press`). `Theme.apply()` swaps `INK` in place, re-runs `_style()`, and recolors plain-tk widgets by mapping old→new palette values. Canvases redraw via `App.refresh()`. To add a theme, add an entry to `THEMES`. `text_on()` deliberately returns a fixed dark or white, because chips sit on tag colors.
- **Fonts** live on `Theme` (`f_title`, `f_sub`, `f_chip`, `f_badge`, `f_side`, `f_side_b`, `f_ui`, `f_head`, `f_gear`). `App.__getattr__` forwards `f_*` to the theme.
- **Filters:** `App.filters` is a list of tokens: tag names, the specials `ALL/UNTAGGED/MISSING`, and `"status:<key>"` (see `is_status`, `filter_label`). Tags and specials combine with **AND**; statuses combine with **OR**.
- **`flush_edits()`** runs before any selection change. It saves half-typed title/author/page fields (a no-op unless something changed). Keep calling it from any new code path that changes the selection.
- Destructive dialogs (`_book_list_dialog`): focus starts on **Cancel**, and **Enter does not confirm**. Keep it that way.
- Changing locations saves the config, then restarts via `os.execv`.
- Native pickers go through `zenity`, with a Tk dialog fallback (`pick_book_files`, `pick_directory`). Trash uses `gio trash`, with a freedesktop-spec fallback.

## Testing safely (important)
- **Never test against the real `All/` or `.local/`.** Use a sandbox:
  - `KOOBS_CONFIG=<tmp>/config.json`, pointing `data_dir` at a *copy* of `library.json`. Point `books_dir` at a temp folder of dummy files whenever a test moves, trashes or imports files.
  - Set `XDG_DATA_HOME=<tmp>/xdg` so `gio trash` and the fallback write to a sandbox Trash, not the user's.
- Drive the UI by patching `ui.App.__init__` to schedule a `test(app)` with `root.after(...)`, then call `ui.main()`. Stub `ui.pick_directory`, `ui.pick_book_files`, `ui.messagebox.*`, `ui.os.execv` as needed.
- Before touching real data: stop the app (`pkill`), and back up `.local/library.json`.

## README screenshots
- `docs/screenshots/{ink,night,sepia,settings}.png` come from a **sandbox demo library of public-domain classics** (Moby-Dick, Meditations, …) with dummy files. Never screenshot the user's real library for the README.
- To regenerate: build the demo with `store.Library` in a temp dir (tags, statuses, pages), use a sandbox `KOOBS_CONFIG` with window geometry 1440x880, drive `ui.main()` (`set_theme`, `filters`, select a card), and `xwd` the window.

## Conventions / user preferences
- Pure stdlib only. The user chose to stay on Python/Tkinter (Electron and Tauri were considered and declined).
- Ink-mode aesthetic: paper background, hairline rules, serif titles, muted palette, no gradients.
- Ask before anything destructive. Removing books always needs confirmation.
- `All/`, `.local/`, book files, caches and `*.bak` are git-ignored. Don't commit user data.
- The user iterates on the UI in small steps. Show screenshots after visual changes.
