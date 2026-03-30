#!/usr/bin/env python3
"""
Watches /workspace for file changes using watchdog.
On every change, runs `git diff` for that file and pushes the unified diff
to ws_server via POST /internal/push_diff.
"""

import os
import subprocess
import sys
import time

import httpx
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

WS_SERVER = os.environ.get("WS_SERVER_URL", "http://localhost:8001")
WATCH_DIR = os.environ.get("REPO_DIR", "/workspace")

IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache"}


def _should_ignore(path: str) -> bool:
    parts = path.replace(WATCH_DIR, "").lstrip("/").split("/")
    return any(p in IGNORED_DIRS for p in parts)


def _git_diff(file_path: str) -> str | None:
    """Return unified diff for a single file relative to HEAD."""
    try:
        result = subprocess.run(
            ["git", "diff", "--unified=3", "HEAD", "--", file_path],
            cwd=WATCH_DIR,
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = result.stdout.strip()
        if not output:
            # File may be untracked — diff against /dev/null
            result = subprocess.run(
                ["git", "diff", "--unified=3", "--no-index", "/dev/null", file_path],
                cwd=WATCH_DIR,
                capture_output=True,
                text=True,
                timeout=10,
            )
            output = result.stdout.strip()
        return output or None
    except Exception as e:
        print(f"[WATCHER] git diff failed for {file_path}: {e}", file=sys.stderr)
        return None


def _push_diff(file_path: str, patch: str) -> None:
    rel_path = os.path.relpath(file_path, WATCH_DIR)
    try:
        httpx.post(
            f"{WS_SERVER}/internal/push_diff",
            json={"file": rel_path, "patch": patch},
            timeout=5,
        )
    except Exception as e:
        print(f"[WATCHER] push_diff failed: {e}", file=sys.stderr)


class ChangeHandler(FileSystemEventHandler):
    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._handle(event.src_path)

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._handle(event.src_path)

    def _handle(self, path: str) -> None:
        if _should_ignore(path):
            return
        patch = _git_diff(path)
        if patch:
            print(f"[WATCHER] diff ready for {path}", file=sys.stderr)
            _push_diff(path, patch)


def main() -> None:
    if not os.path.isdir(WATCH_DIR):
        print(f"[WATCHER] Watch dir {WATCH_DIR} does not exist, waiting...", file=sys.stderr)
        # Wait up to 60s for the repo to be cloned
        for _ in range(60):
            time.sleep(1)
            if os.path.isdir(WATCH_DIR):
                break
        else:
            print(f"[WATCHER] ERROR: {WATCH_DIR} never appeared, exiting.", file=sys.stderr)
            sys.exit(1)

    print(f"[WATCHER] Watching {WATCH_DIR}", file=sys.stderr)
    observer = Observer()
    observer.schedule(ChangeHandler(), WATCH_DIR, recursive=True)
    observer.start()
    try:
        while observer.is_alive():
            observer.join(timeout=1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()


if __name__ == "__main__":
    main()
