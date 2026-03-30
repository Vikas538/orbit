#!/usr/bin/env python3
"""
WebSocket server running inside every ECS container on port 8001.
Provides 4 channels: /ws/chat, /ws/plan, /ws/diff, /ws/perms
Also exposes internal HTTP endpoints for IPC with file_watcher, heartbeat,
agent_forwarder, and permission_gate (all co-located in the same container).
"""

import asyncio
import os
from datetime import datetime, timezone
from typing import Dict, Optional, Set

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Orbit Container WS Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Connection manager ────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self, name: str):
        self.name = name
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.active.discard(ws)

    async def broadcast(self, message: dict) -> None:
        dead: Set[WebSocket] = set()
        for ws in list(self.active):
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        self.active -= dead


chat_mgr  = ConnectionManager("chat")
plan_mgr  = ConnectionManager("plan")
diff_mgr  = ConnectionManager("diff")
perms_mgr = ConnectionManager("perms")


# ── State ─────────────────────────────────────────────────────────────────────

# Latest diff per file — replayed to any new /ws/diff connection
current_diffs: Dict[str, dict] = {}

# Pending permission requests — replayed to new /ws/perms connections
pending_permissions: Dict[str, dict] = {}
permission_responses: Dict[str, dict] = {}

# Queue of user chat messages waiting to be picked up by the standby agent loop
_chat_queue: asyncio.Queue = asyncio.Queue()


# ── WebSocket endpoints ───────────────────────────────────────────────────────

@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket) -> None:
    await chat_mgr.connect(ws)
    try:
        while True:
            data = await ws.receive_json()
            content = data.get("content", "").strip()
            if not content:
                continue
            msg = {"type": "user_message", "content": content, "timestamp": _now()}
            await chat_mgr.broadcast(msg)
            # Also enqueue for the standby agent loop in entrypoint.sh
            await _chat_queue.put(content)
    except (WebSocketDisconnect, Exception):
        chat_mgr.disconnect(ws)


@app.websocket("/ws/plan")
async def ws_plan(ws: WebSocket) -> None:
    await plan_mgr.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, Exception):
        plan_mgr.disconnect(ws)


@app.websocket("/ws/diff")
async def ws_diff(ws: WebSocket) -> None:
    await diff_mgr.connect(ws)
    # Replay all currently known diffs so late-joining clients see everything
    for diff in list(current_diffs.values()):
        try:
            await ws.send_json(diff)
        except Exception:
            break
    try:
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, Exception):
        diff_mgr.disconnect(ws)


@app.websocket("/ws/perms")
async def ws_perms(ws: WebSocket) -> None:
    await perms_mgr.connect(ws)
    for perm in list(pending_permissions.values()):
        try:
            await ws.send_json(perm)
        except Exception:
            break
    try:
        while True:
            data = await ws.receive_json()
            perm_id = data.get("permission_id")
            granted = bool(data.get("granted", False))
            if perm_id and perm_id in pending_permissions:
                permission_responses[perm_id] = {
                    "granted": granted,
                    "reason": "user approved" if granted else "user denied",
                }
                del pending_permissions[perm_id]
                await perms_mgr.broadcast({
                    "type": "permission_resolved",
                    "permission_id": perm_id,
                    "granted": granted,
                })
    except (WebSocketDisconnect, Exception):
        perms_mgr.disconnect(ws)


# ── Internal HTTP endpoints ───────────────────────────────────────────────────

class ChatLine(BaseModel):
    content: str
    source: str = "agent"


@app.post("/internal/push_chat")
async def push_chat(payload: ChatLine) -> dict:
    await chat_mgr.broadcast({
        "type": payload.source,
        "content": payload.content,
        "timestamp": _now(),
    })
    return {"status": "ok"}


class AgentPid(BaseModel):
    pid: int


_agent_pid: Optional[int] = None


@app.post("/internal/set_agent_pid")
async def set_agent_pid(payload: AgentPid) -> dict:
    """Called by entrypoint.sh whenever a new agent process starts."""
    global _agent_pid
    _agent_pid = payload.pid
    return {"status": "ok", "pid": _agent_pid}


@app.post("/internal/stop_agent")
async def stop_agent() -> dict:
    """Kill the agent process group — SIGTERM then SIGKILL after 3s.

    The agent runs under setsid so it is its own process-group leader.
    Sending to the process group (killpg) kills the agent AND all children
    (bash tool subprocesses, MCP servers, etc.) in one shot.
    """
    global _agent_pid
    if not _agent_pid:
        return {"status": "no_agent"}
    import os as _os, signal as _signal
    pid = _agent_pid
    try:
        pgid = _os.getpgid(pid)
        _os.killpg(pgid, _signal.SIGTERM)
        await asyncio.sleep(3)
        try:
            _os.killpg(pgid, _signal.SIGKILL)  # force-kill survivors
        except (ProcessLookupError, PermissionError):
            pass  # group already gone after SIGTERM — good
        await chat_mgr.broadcast({"type": "system", "content": "Agent stopped by user.", "timestamp": _now()})
        _agent_pid = None
        return {"status": "stopped"}
    except (ProcessLookupError, PermissionError):
        _agent_pid = None
        return {"status": "already_exited"}


@app.get("/internal/next_user_message")
async def next_user_message() -> dict:
    """
    Polled by the standby loop in entrypoint.sh.
    Returns the next queued user chat message or null if none pending.
    """
    try:
        msg = _chat_queue.get_nowait()
        return {"message": msg}
    except asyncio.QueueEmpty:
        return {"message": None}


class PlanMessage(BaseModel):
    content: str
    msg_type: str = "system"


@app.post("/internal/push_plan")
async def push_plan(payload: PlanMessage) -> dict:
    await plan_mgr.broadcast({
        "type": payload.msg_type,
        "content": payload.content,
        "timestamp": _now(),
    })
    return {"status": "ok"}


class DiffPayload(BaseModel):
    file: str
    patch: str


@app.post("/internal/push_diff")
async def push_diff(payload: DiffPayload) -> dict:
    msg = {
        "type": "diff",
        "file": payload.file,
        "patch": payload.patch,
        "timestamp": _now(),
    }
    current_diffs[payload.file] = msg   # cache so late joiners see it
    await diff_mgr.broadcast(msg)
    return {"status": "ok"}


class PermissionRequestPayload(BaseModel):
    id: str
    action: str
    command: str
    reason: str
    session_id: str


@app.post("/internal/permission_request")
async def create_permission_request(req: PermissionRequestPayload) -> dict:
    payload = {
        "type": "permission_request",
        "id": req.id,
        "action": req.action,
        "command": req.command,
        "reason": req.reason,
        "session_id": req.session_id,
        "timestamp": _now(),
    }
    pending_permissions[req.id] = payload
    await perms_mgr.broadcast(payload)
    return {"status": "ok"}


@app.get("/internal/permission_status/{permission_id}")
async def get_permission_status(permission_id: str) -> dict:
    if permission_id in permission_responses:
        result = permission_responses.pop(permission_id)
        return {"status": "resolved", **result}
    if permission_id in pending_permissions:
        return {"status": "pending"}
    return {"status": "not_found"}


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "connections": {
            "chat": len(chat_mgr.active),
            "plan": len(plan_mgr.active),
            "diff": len(diff_mgr.active),
            "perms": len(perms_mgr.active),
        },
        "pending_permissions": len(pending_permissions),
        "cached_diffs": len(current_diffs),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")
