#!/usr/bin/env python3
"""
Reads lines from stdin (piped from the agent process) and forwards each line
to ws_server /internal/push_chat so it appears in the dashboard TerminalChat.
"""

import os
import sys

import httpx

WS_SERVER = os.environ.get("WS_SERVER_URL", "http://localhost:8001")


def main() -> None:
    client = httpx.Client(timeout=5)
    try:
        for raw_line in sys.stdin:
            line = raw_line.rstrip("\n")
            if not line:
                continue
            try:
                client.post(
                    f"{WS_SERVER}/internal/push_chat",
                    json={"content": line, "source": "agent"},
                )
            except Exception as e:
                # Don't crash the forwarder if ws_server is temporarily unavailable
                print(f"[FORWARDER] push failed: {e}", file=sys.stderr)
    finally:
        client.close()


if __name__ == "__main__":
    main()
