#!/usr/bin/env python3
"""
MCP tool: request_permission
Called by the agent before any dangerous operation.
Sends the request to ws_server, then polls until the user clicks Allow/Deny
on the dashboard, or auto-denies after 5 minutes.
"""

import asyncio
import json
import os
import uuid
import time

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("permission-gate")

WS_SERVER = os.environ.get("WS_SERVER_URL", "http://localhost:8001")
SESSION_ID = os.environ.get("SESSION_ID", "unknown")

TIMEOUT_SECONDS = 5 * 60  # 5 minutes
POLL_INTERVAL   = 2        # seconds between status polls


@mcp.tool()
async def request_permission(action: str, command: str, reason: str) -> str:
    """
    Request user permission before executing a potentially dangerous operation.

    Call this BEFORE any operation that:
    - Deletes files or directories
    - Runs shell commands with side effects (rm, curl, docker, kubectl, etc.)
    - Pushes code or creates pull requests
    - Modifies CI/CD configuration
    - Accesses secrets or credentials

    Args:
        action:  Short label for the action type (e.g. "delete_file", "run_command", "git_push")
        command: The exact command or operation to be executed
        reason:  Why this operation is necessary for the task

    Returns:
        JSON string: {"granted": true/false, "reason": "..."}
        If granted is false, ABORT the operation entirely — do not retry.
    """
    perm_id = str(uuid.uuid4())

    print(f"[PERM_GATE] Requesting permission: action={action} id={perm_id}", flush=True)

    # Register the request with ws_server (which broadcasts to dashboard)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{WS_SERVER}/internal/permission_request",
                json={
                    "id": perm_id,
                    "action": action,
                    "command": command,
                    "reason": reason,
                    "session_id": SESSION_ID,
                },
            )
            if resp.status_code != 200:
                print(f"[PERM_GATE] register failed: {resp.status_code}", flush=True)
                return json.dumps({"granted": False, "reason": "ws_server unavailable — auto-denied"})
    except Exception as e:
        print(f"[PERM_GATE] register error: {e}", flush=True)
        return json.dumps({"granted": False, "reason": f"ws_server error: {e} — auto-denied"})

    # Poll for user response
    deadline = time.monotonic() + TIMEOUT_SECONDS
    async with httpx.AsyncClient(timeout=10) as client:
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_INTERVAL)
            try:
                resp = await client.get(
                    f"{WS_SERVER}/internal/permission_status/{perm_id}"
                )
                data = resp.json()
                status = data.get("status")

                if status == "resolved":
                    granted = data.get("granted", False)
                    reason  = data.get("reason", "user responded")
                    print(f"[PERM_GATE] Permission {perm_id}: granted={granted}", flush=True)
                    return json.dumps({"granted": granted, "reason": reason})

                if status == "not_found":
                    # Was removed without a response (shouldn't happen normally)
                    return json.dumps({"granted": False, "reason": "permission request lost — auto-denied"})

            except Exception as e:
                print(f"[PERM_GATE] poll error: {e}", flush=True)

    # Timed out
    print(f"[PERM_GATE] Permission {perm_id} timed out — auto-denying", flush=True)
    return json.dumps({"granted": False, "reason": "timeout after 5 minutes — auto-denied"})


if __name__ == "__main__":
    mcp.run()
