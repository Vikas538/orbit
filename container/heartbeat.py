#!/usr/bin/env python3
"""
2-hour countdown heartbeat.
- Sends remaining time every 60s to /ws/plan channel via ws_server
- On expiry: POSTs to host FastAPI /internal/snapshot/{session_id} then exits
  (supervisord will stop all other programs in the group)
"""

import os
import sys
import time

import httpx

SESSION_ID    = os.environ.get("SESSION_ID", "unknown")
ORBIT_BASE_URL = os.environ.get("ORBIT_BASE_URL", "http://host.docker.internal:8000")
WS_SERVER     = os.environ.get("WS_SERVER_URL", "http://localhost:8001")

TIMEOUT_SECONDS = int(os.environ.get("SESSION_TIMEOUT_SECONDS", str(2 * 60 * 60)))  # 2hr
TICK_INTERVAL   = 60  # seconds between heartbeat ticks


def _push_heartbeat(remaining_seconds: int) -> None:
    minutes = remaining_seconds // 60
    hours   = minutes // 60
    label   = f"{hours}h {minutes % 60}m" if hours > 0 else f"{minutes}m"
    try:
        httpx.post(
            f"{WS_SERVER}/internal/push_plan",
            json={"content": f"[HEARTBEAT] {label} remaining", "msg_type": "heartbeat"},
            timeout=5,
        )
    except Exception as e:
        print(f"[HEARTBEAT] push failed: {e}", file=sys.stderr)


def _trigger_snapshot() -> None:
    print(f"[HEARTBEAT] Session timeout — triggering snapshot for {SESSION_ID}", file=sys.stderr)
    try:
        httpx.post(
            f"{WS_SERVER}/internal/push_plan",
            json={"content": "[HEARTBEAT] Session timeout — saving context snapshot...", "msg_type": "system"},
            timeout=5,
        )
    except Exception:
        pass

    try:
        resp = httpx.post(
            f"{ORBIT_BASE_URL}/internal/snapshot/{SESSION_ID}",
            timeout=60,
        )
        print(f"[HEARTBEAT] Snapshot response: {resp.status_code}", file=sys.stderr)
    except Exception as e:
        print(f"[HEARTBEAT] Snapshot request failed: {e}", file=sys.stderr)


def main() -> None:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    print(f"[HEARTBEAT] Started — {TIMEOUT_SECONDS}s countdown for session {SESSION_ID}", file=sys.stderr)

    while True:
        remaining = int(deadline - time.monotonic())
        if remaining <= 0:
            break

        _push_heartbeat(remaining)
        sleep_time = min(TICK_INTERVAL, remaining)
        time.sleep(sleep_time)

    _trigger_snapshot()
    sys.exit(0)  # supervisord will stop all programs in the group


if __name__ == "__main__":
    main()
