"""Operating-system specifics, kept in one place: Linux, Windows and macOS.

Everything here is stdlib-only. Linux is the primary platform; Windows and macOS
code paths follow each platform's own conventions.
"""
import datetime
import os
import shutil
import subprocess
import sys
import urllib.parse

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"


# ---------------------------------------------------------------- config location
def config_dir():
    """Per-user settings folder, following each OS's convention."""
    if IS_WIN:
        base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        return os.path.join(base, "Koobs")
    if IS_MAC:
        return os.path.expanduser("~/Library/Application Support/Koobs")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                        "koobs")


# ---------------------------------------------------------------- open a file
def open_path(path):
    """Open a file with the user's default app. Raises OSError if that fails."""
    if IS_WIN:
        os.startfile(path)  # noqa: S606 - opening the user's own file is the point
        return
    cmd = ["open", path] if IS_MAC else ["xdg-open", path]
    if not shutil.which(cmd[0]):
        raise OSError(f"'{cmd[0]}' is not available to open files")
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if not IS_WIN:
        kwargs["start_new_session"] = True     # don't tie the reader to Koobs
    subprocess.Popen(cmd, **kwargs)


# ---------------------------------------------------------------- trash / recycle bin
def move_to_trash(path):
    """Send a file to the desktop Trash / Recycle Bin, so it can be restored."""
    path = os.path.abspath(path)
    if IS_WIN:
        _trash_windows(path)
    elif IS_MAC:
        _trash_mac(path)
    else:
        _trash_linux(path)


def _trash_windows(path):
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE = 0x0003
    FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 0x4, 0x10, 0x40, 0x400
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = path + "\0"           # list must be double-NUL terminated
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0 or op.fAnyOperationsAborted:
        raise OSError(f"Could not move to the Recycle Bin (code {rc}): {path}")


def _trash_mac(path):
    # Finder's delete keeps "Put Back" working; fall back to ~/.Trash.
    script = f'tell application "Finder" to delete POSIX file "{path}"'
    if shutil.which("osascript"):
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if r.returncode == 0 or not os.path.lexists(path):
            return
    trash = os.path.expanduser("~/.Trash")
    os.makedirs(trash, exist_ok=True)
    shutil.move(path, _unique(os.path.join(trash, os.path.basename(path))))


def _trash_linux(path):
    if shutil.which("gio"):
        r = subprocess.run(["gio", "trash", "--", path], capture_output=True, text=True)
        if r.returncode == 0 or not os.path.lexists(path):
            return
    # Fallback: freedesktop.org Trash spec (home trash).
    base = os.path.join(os.environ.get("XDG_DATA_HOME") or
                        os.path.expanduser("~/.local/share"), "Trash")
    files, info = os.path.join(base, "files"), os.path.join(base, "info")
    os.makedirs(files, exist_ok=True)
    os.makedirs(info, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(path))
    target, n = stem + ext, 1
    while os.path.lexists(os.path.join(files, target)) or \
            os.path.lexists(os.path.join(info, target + ".trashinfo")):
        n += 1
        target = f"{stem}.{n}{ext}"
    with open(os.path.join(info, target + ".trashinfo"), "w", encoding="utf-8") as f:
        f.write("[Trash Info]\nPath={}\nDeletionDate={}\n".format(
            urllib.parse.quote(path),
            datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")))
    shutil.move(path, os.path.join(files, target))


def _unique(dest):
    stem, ext = os.path.splitext(dest)
    n = 2
    while os.path.lexists(dest):
        dest = f"{stem} ({n}){ext}"
        n += 1
    return dest


# ---------------------------------------------------------------- app lifecycle
def restart_app():
    """Start a fresh copy of Koobs. The caller then lets the current one exit.

    (os.execv mangles arguments containing spaces on Windows, so spawn instead.)
    """
    subprocess.Popen([sys.executable] + sys.argv, close_fds=True)


def enable_hidpi():
    """Sharp text on scaled Windows displays. Call before creating the Tk root."""
    if not IS_WIN:
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)      # Windows 8.1+
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()      # Vista+
        except (AttributeError, OSError):
            pass


def wheel_units(delta):
    """Tk <MouseWheel> delta -> scroll units (Windows: ±120 per notch; macOS: small ints)."""
    if abs(delta) >= 120:
        return int(-delta / 120 * 3)
    return -1 if delta > 0 else (1 if delta < 0 else 0)
