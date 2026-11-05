"""Sync the library (books + library.json) with Google Drive via rclone. Linux only.

Layout on the remote:   <remote><folder>/library.json
                        <remote><folder>/books/<same paths as the local books folder>

A sync runs in three steps so the UI can keep the slow parts off the main thread:

    plan = prepare(lib, remote)          # worker thread: fetch remote library + file list
    plan = apply_merge(lib, plan)        # main thread: merge library.json, work out transfers
    transfer(lib, remote, plan, cb)      # worker thread: move files, upload library.json

Books removed on another device are moved to the local Trash (restorable), never
deleted outright. A sync that would remove many books stops and asks first.
"""
import json
import os
import shutil
import subprocess
import tempfile
import threading

from osutil import IS_MAC, IS_WIN, move_to_trash

SUPPORTED = not (IS_WIN or IS_MAC)          # Linux only, by design
DEFAULT_REMOTE_NAME = "koobs-drive"
DEFAULT_FOLDER = "Koobs"

# Ask before a sync removes more than this many books (or this share of the library).
BIG_REMOVAL_COUNT = 10
BIG_REMOVAL_SHARE = 0.10


class SyncError(Exception):
    pass


# ---------------------------------------------------------------- remotes
class RcloneRemote:
    """Talks to any rclone remote (Google Drive in practice) through the rclone CLI."""

    def __init__(self, remote, folder=DEFAULT_FOLDER):
        # remote: "koobs-drive:" for a configured remote, or a plain local path (tests).
        base = remote if remote.endswith((":", "/")) else remote + "/"
        self.root = f"{base}{folder}"
        self.books = f"{self.root}/books"
        self.library = f"{self.root}/library.json"
        self._proc = None
        self._cancelled = False

    # -- helpers
    def _run(self, args, input_text=None, check=True):
        if self._cancelled:
            raise SyncError("Sync was cancelled.")
        r = subprocess.run(["rclone"] + args, capture_output=True, text=True, input=input_text)
        if check and r.returncode != 0:
            raise SyncError(_rclone_message(r.stderr) or f"rclone {args[0]} failed")
        return r

    def cancel(self):
        self._cancelled = True
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    # -- interface used by the engine
    def read_library(self):
        r = self._run(["cat", self.library], check=False)
        if r.returncode != 0:
            if _not_found(r.stderr) or not r.stdout:
                return None
            raise SyncError(_rclone_message(r.stderr))
        try:
            return json.loads(r.stdout)
        except ValueError as e:
            raise SyncError(f"The library.json on the remote is damaged: {e}")

    def list_books(self):
        """{key: size} for every file under books/."""
        r = self._run(["lsjson", "-R", "--files-only", "--no-mimetype", "--no-modtime",
                       self.books], check=False)
        if r.returncode != 0:
            if _not_found(r.stderr):
                return {}
            raise SyncError(_rclone_message(r.stderr))
        return {e["Path"]: e.get("Size", -1) for e in json.loads(r.stdout or "[]")}

    def write_library(self, local_path):
        self._run(["copyto", local_path, self.library])

    def upload(self, keys, local_root, progress=None):
        self._copy_files(keys, local_root, self.books, progress)

    def download(self, keys, local_root, progress=None):
        self._copy_files(keys, self.books, local_root, progress)

    def delete(self, keys):
        if not keys:
            return
        with _key_list(keys) as listfile:
            self._run(["delete", "--files-from-raw", listfile, self.books])

    def _copy_files(self, keys, src, dst, progress):
        if not keys:
            return
        with _key_list(keys) as listfile:
            args = ["rclone", "copy", "--files-from-raw", listfile, "--ignore-existing",
                    "--use-json-log", "--stats", "1s", "-v", src, dst]
            self._proc = subprocess.Popen(args, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                          text=True)
            last_error = ""
            for line in self._proc.stderr:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("level") == "error":
                    last_error = rec.get("msg", "")
                st = rec.get("stats")
                if st and progress:
                    progress(st.get("bytes", 0), st.get("totalBytes", 0),
                             st.get("transfers", 0), st.get("totalTransfers", 0))
            rc = self._proc.wait()
            self._proc = None
            if self._cancelled:
                raise SyncError("Sync was cancelled.")
            if rc != 0:
                raise SyncError(last_error or "rclone copy failed")


class FolderRemote:
    """A plain folder standing in for Google Drive, same interface (used by tests)."""

    def __init__(self, path, folder=DEFAULT_FOLDER):
        self.root = os.path.join(path, folder)
        self.books = os.path.join(self.root, "books")
        self.library = os.path.join(self.root, "library.json")

    def cancel(self):
        pass

    def read_library(self):
        if not os.path.exists(self.library):
            return None
        with open(self.library, encoding="utf-8") as f:
            return json.load(f)

    def list_books(self):
        out = {}
        for dirpath, _, files in os.walk(self.books):
            for name in files:
                p = os.path.join(dirpath, name)
                out[os.path.relpath(p, self.books).replace(os.sep, "/")] = os.path.getsize(p)
        return out

    def write_library(self, local_path):
        os.makedirs(self.root, exist_ok=True)
        shutil.copyfile(local_path, self.library)

    def upload(self, keys, local_root, progress=None):
        self._copy(keys, local_root, self.books, progress)

    def download(self, keys, local_root, progress=None):
        self._copy(keys, self.books, local_root, progress)

    def delete(self, keys):
        for k in keys:
            p = os.path.join(self.books, *k.split("/"))
            if os.path.exists(p):
                os.remove(p)

    @staticmethod
    def _copy(keys, src, dst, progress):
        total = len(keys)
        for i, k in enumerate(keys, 1):
            s, d = os.path.join(src, *k.split("/")), os.path.join(dst, *k.split("/"))
            if os.path.exists(d):
                continue
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
            if progress:
                progress(i, total, i, total)


# ---------------------------------------------------------------- engine
class Plan:
    def __init__(self):
        self.remote_lib = None       # dict or None (nothing on the remote yet)
        self.remote_files = {}       # key -> size
        self.merge_stats = {}
        self.downloads = []          # keys
        self.uploads = []
        self.remote_deletes = []
        self.local_trash = []        # keys whose local file should go to the Trash
        self.checkpoint = None       # library state before the merge (for cancel / keep)


def prepare(lib, remote):
    """Worker thread: read what's on the remote."""
    plan = Plan()
    plan.remote_lib = remote.read_library()
    plan.remote_files = remote.list_books()
    return plan


def apply_merge(lib, plan):
    """Main thread: register local files, merge library.json, decide every transfer.

    Doesn't touch any book file yet. Check plan.local_trash against needs_confirmation()
    before calling trash_removed().
    """
    lib.scan()
    lib.save()                                   # stamp local edits/new files first
    plan.checkpoint = lib.checkpoint()           # to undo the merge if the user says no
    if plan.remote_lib is not None:
        plan.merge_stats = lib.merge_from(plan.remote_lib)
    on_remote = plan.remote_files
    for key, b in lib.books.items():
        here = os.path.isfile(lib.abspath(key))
        if here and key not in on_remote:
            plan.uploads.append(key)
        elif not here and key in on_remote:
            plan.downloads.append(key)
    for key in lib.deleted:
        if key in on_remote:
            plan.remote_deletes.append(key)
        if os.path.lexists(lib.abspath(key)):
            plan.local_trash.append(key)
    for lst in (plan.uploads, plan.downloads, plan.remote_deletes, plan.local_trash):
        lst.sort()
    return plan


def needs_confirmation(lib, plan):
    """True if this sync would trash many books *on this device* because they were
    removed elsewhere (or re-keyed by a books-folder change on another device).

    Removals this device made itself were already confirmed in the Trash/Move-out
    dialogs, so pushing them never asks again; on Google Drive rclone moves deleted
    files to Drive's own trash, so those stay recoverable too.
    """
    n = len(plan.local_trash)
    size = max(len(lib.books) + n, 1)
    return n > BIG_REMOVAL_COUNT or (n > 3 and n / size > BIG_REMOVAL_SHARE)


def resolve_removals(lib, plan, choice):
    """The user's answer when needs_confirmation(): "trash", "keep" or "cancel".

    trash  -> go ahead (returns the same plan)
    keep   -> keep this device's copies: they win and are re-uploaded (returns a new plan)
    cancel -> undo the merge, touch nothing (returns None)
    """
    if choice == "trash":
        return plan
    keys = list(plan.local_trash)
    lib.rollback(plan.checkpoint)
    if choice == "cancel":
        return None
    lib.touch(keys)
    fresh = Plan()
    fresh.remote_lib, fresh.remote_files = plan.remote_lib, plan.remote_files
    return apply_merge(lib, fresh)


def trash_removed(lib, plan):
    """Main thread: move files of books removed on another device to the local Trash."""
    failed = []
    for key in plan.local_trash:
        try:
            move_to_trash(lib.abspath(key))
        except OSError as e:
            failed.append((key, str(e)))
    return failed


def transfer(lib, remote, plan, progress=None):
    """Worker thread: move the files, then publish the merged library.json."""
    def stage(name):
        def cb(done, total, files_done, files_total):
            if progress:
                progress(name, done, total, files_done, files_total)
        return cb
    if plan.downloads:
        remote.download(plan.downloads, lib.all_dir, stage("Downloading"))
    if plan.uploads:
        remote.upload(plan.uploads, lib.all_dir, stage("Uploading"))
    if plan.remote_deletes:
        remote.delete(plan.remote_deletes)
    remote.write_library(lib.path)


def run_sync(lib, remote, progress=None, confirm=None):
    """Whole sync in one call (no threads). Used by tests and scripts.

    confirm(plan) -> "trash" | "keep" | "cancel" is asked before a large removal
    (default: cancel). Returns the plan; raises SyncError if cancelled.
    """
    plan = prepare(lib, remote)
    plan = apply_merge(lib, plan)
    if needs_confirmation(lib, plan):
        n = len(plan.local_trash)
        plan = resolve_removals(lib, plan, confirm(plan) if confirm else "cancel")
        if plan is None:
            raise SyncError(f"Sync stopped: it would move {n} books on this device "
                            "to the Trash.")
    trash_removed(lib, plan)
    transfer(lib, remote, plan, progress)
    lib.scan()
    lib.save()
    return plan


# ---------------------------------------------------------------- rclone setup
def rclone_path():
    return shutil.which("rclone")


def list_remotes():
    if not rclone_path():
        return []
    r = subprocess.run(["rclone", "listremotes"], capture_output=True, text=True)
    return [x.strip() for x in r.stdout.splitlines() if x.strip()]


def connect_google_drive(name=DEFAULT_REMOTE_NAME, on_output=None):
    """Create an rclone Google Drive remote. Opens the browser for Google sign-in.

    Uses the drive.file scope: rclone (and so Koobs) can only see files it created,
    not the rest of your Drive. Blocks until sign-in finishes. Returns "name:".
    """
    if not rclone_path():
        raise SyncError("rclone is not installed.")
    proc = subprocess.Popen(["rclone", "config", "create", name, "drive", "scope=drive.file"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    output = []
    for line in proc.stdout:
        output.append(line)
        if on_output:
            on_output(line.rstrip())
    if proc.wait() != 0 or f"{name}:" not in list_remotes():
        raise SyncError("Google Drive sign-in did not finish.\n" + "".join(output[-5:]))
    return f"{name}:"


def check_remote(remote):
    r = subprocess.run(["rclone", "lsd", remote], capture_output=True, text=True)
    if r.returncode != 0:
        raise SyncError(_rclone_message(r.stderr) or "Could not reach the remote.")


# ---------------------------------------------------------------- utils
def _not_found(stderr):
    s = (stderr or "").lower()
    return "not found" in s or "doesn't exist" in s or "no such file" in s


def _rclone_message(stderr):
    lines = [x for x in (stderr or "").strip().splitlines() if x.strip()]
    return lines[-1] if lines else ""


class _key_list:
    """Temp file with one key per line, for rclone --files-from-raw."""

    def __init__(self, keys):
        self.keys = keys

    def __enter__(self):
        fd, self.path = tempfile.mkstemp(prefix="koobs-sync-", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(self.keys) + "\n")
        return self.path

    def __exit__(self, *exc):
        os.remove(self.path)


class Worker(threading.Thread):
    """Run fn in the background; the UI polls .done / .result / .error."""

    def __init__(self, fn, *args):
        super().__init__(daemon=True)
        self.fn, self.args = fn, args
        self.done, self.result, self.error = False, None, None

    def run(self):
        try:
            self.result = self.fn(*self.args)
        except Exception as e:                    # surfaced to the UI, never swallowed
            self.error = e
        finally:
            self.done = True
