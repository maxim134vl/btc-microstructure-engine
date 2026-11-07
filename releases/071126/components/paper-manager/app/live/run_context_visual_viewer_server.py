#!/usr/bin/env python3
"""No-cache static viewer for Market Context + Paper Trade overlays.

Serves apps/context_visualizer/public on 127.0.0.1:8765.
Does not compute trading logic. Does not write ledgers / decision log.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DIR = ROOT / "apps" / "context_visualizer" / "public"
PID_PATH = ROOT / "runtime_context_viewer.pid"
LOG_PATH = ROOT / "logs" / "context_viewer_8765.log"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _log(message: str) -> None:
    """Log once.

    When launched under ``nohup ... >> context_viewer_8765.log``, stdout is the
    log file — only print (avoids duplicate lines). When interactive (TTY), also
    mirror to the log file.
    """
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"{_iso_now()} {message}"
    print(line, flush=True)
    if sys.stdout.isatty():
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        _log(f"[http] {self.address_string()} {fmt % args}")


def write_pid() -> None:
    PID_PATH.write_text(f"{os.getpid()}\n", encoding="utf-8")


def clear_pid() -> None:
    try:
        if PID_PATH.exists():
            existing = int(PID_PATH.read_text(encoding="utf-8").strip() or "0")
            if existing == os.getpid():
                PID_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="No-cache context visual viewer on 127.0.0.1:8765")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--public-dir", type=Path, default=PUBLIC_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    public = Path(args.public_dir).resolve()
    if not public.is_dir():
        print(f"ERROR: public dir missing: {public}", file=sys.stderr)
        return 1

    os.chdir(public)
    write_pid()
    server = ThreadingHTTPServer((args.host, int(args.port)), NoCacheHandler)
    _log(f"viewer_start pid={os.getpid()} url=http://{args.host}:{args.port}/ dir={public}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _log("viewer_stop reason=KeyboardInterrupt")
    finally:
        server.server_close()
        clear_pid()
        _log("viewer_exit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
