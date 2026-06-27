"""
sync_daemon.py — BullLogic live-sync watcher

Watches the project directory for file changes and automatically reloads
the Gunicorn server so every save is live within ~1 second.

Usage:
    python sync_daemon.py                  # watch + reload on any change
    python sync_daemon.py --git-pull       # git pull before every reload
    python sync_daemon.py --debounce 1.5   # wait 1.5s after last change

Ctrl-C to stop.
"""

import os
import sys
import time
import signal
import argparse
import subprocess
import threading
from datetime import datetime

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ── ANSI colours ─────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BLUE   = "\033[94m"
DIM    = "\033[2m"

def ts():
    return datetime.now().strftime("%H:%M:%S")

def log(colour, icon, msg):
    print(f"{DIM}{ts()}{RESET}  {colour}{icon}  {msg}{RESET}", flush=True)

def log_ok(msg):   log(GREEN,  "✔", msg)
def log_info(msg): log(CYAN,   "→", msg)
def log_warn(msg): log(YELLOW, "⚠", msg)
def log_err(msg):  log(RED,    "✖", msg)
def log_chg(msg):  log(BLUE,   "~", msg)


# ── Extensions to watch ───────────────────────────────────────────────────────

WATCH_EXTS = {".py", ".html", ".css", ".js", ".json", ".env"}

IGNORE_DIRS = {
    "__pycache__", ".git", "node_modules", ".venv", "venv",
    "Saved Models", "Saved", "Data", ".mypy_cache",
}

IGNORE_FILES = {"sync_daemon.py"}   # don't reload when we edit ourselves


# ── Gunicorn control ──────────────────────────────────────────────────────────

def find_gunicorn_pid() -> int | None:
    """Return master Gunicorn PID, or None if not running."""
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "gunicorn: master"],
            text=True
        ).strip()
        for line in out.splitlines():
            pid = line.strip()
            if pid.isdigit():
                return int(pid)
    except subprocess.CalledProcessError:
        pass
    return None


def reload_gunicorn(git_pull: bool = False) -> bool:
    """Gracefully reload Gunicorn (SIGHUP on master). Returns True on success."""
    if git_pull:
        log_info("Running git pull…")
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True, text=True
        )
        if result.returncode == 0:
            log_ok(f"git pull: {result.stdout.strip() or 'already up to date'}")
        else:
            log_warn(f"git pull failed: {result.stderr.strip()}")

    pid = find_gunicorn_pid()
    if pid is None:
        log_err("Gunicorn master not found — is the server running?")
        return False

    try:
        os.kill(pid, signal.SIGHUP)
        log_ok(f"Gunicorn reloaded  (PID {pid})")
        return True
    except ProcessLookupError:
        log_err(f"PID {pid} not found")
        return False
    except PermissionError:
        log_err(f"No permission to signal PID {pid} — try sudo")
        return False


# ── File-change handler ───────────────────────────────────────────────────────

class ChangeHandler(FileSystemEventHandler):

    def __init__(self, debounce: float, git_pull: bool):
        super().__init__()
        self._debounce  = debounce
        self._git_pull  = git_pull
        self._timer     = None
        self._lock      = threading.Lock()
        self._pending   = []        # list of changed paths buffered in window

    # watchdog fires on_modified / on_created / on_moved / on_deleted
    def on_any_event(self, event):
        if event.is_directory:
            return

        path = getattr(event, "dest_path", None) or event.src_path
        path = os.path.normpath(path)

        # Skip ignored directories
        parts = path.split(os.sep)
        if any(p in IGNORE_DIRS for p in parts):
            return

        # Skip ignored files and unsupported extensions
        fname = os.path.basename(path)
        ext   = os.path.splitext(fname)[1].lower()
        if fname in IGNORE_FILES or ext not in WATCH_EXTS:
            return

        with self._lock:
            self._pending.append(path)
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self):
        with self._lock:
            changed = list(self._pending)
            self._pending.clear()
            self._timer = None

        # Print each changed file (relative path, trimmed)
        base = os.path.dirname(os.path.abspath(__file__))
        for p in changed:
            rel = os.path.relpath(p, base)
            log_chg(f"Changed: {rel}")

        reload_gunicorn(self._git_pull)
        print()   # blank line for readability


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="BullLogic live-sync watcher")
    parser.add_argument("--debounce", type=float, default=0.8,
                        help="Seconds to wait after last change before reloading (default: 0.8)")
    parser.add_argument("--git-pull", action="store_true",
                        help="Run 'git pull' before every Gunicorn reload")
    args = parser.parse_args()

    watch_dir = os.path.dirname(os.path.abspath(__file__))

    print()
    print(f"{BOLD}{GREEN}  BullLogic Sync Daemon{RESET}")
    print(f"  {DIM}Watching: {watch_dir}{RESET}")
    print(f"  {DIM}Debounce: {args.debounce}s   |   Git pull: {'yes' if args.git_pull else 'no'}{RESET}")
    print(f"  {DIM}Extensions: {', '.join(sorted(WATCH_EXTS))}{RESET}")
    print()

    # Check Gunicorn is actually up
    pid = find_gunicorn_pid()
    if pid:
        log_ok(f"Gunicorn master found at PID {pid}")
    else:
        log_warn("Gunicorn master not found — start the server first")
    print()

    handler  = ChangeHandler(debounce=args.debounce, git_pull=args.git_pull)
    observer = Observer()
    observer.schedule(handler, watch_dir, recursive=True)
    observer.start()

    log_info("Watching for changes… (Ctrl-C to stop)")
    print()

    try:
        while True:
            time.sleep(0.5)
            # Re-check Gunicorn periodically so we warn if it goes down
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        print()
        log_info("Sync daemon stopped.")


if __name__ == "__main__":
    main()
