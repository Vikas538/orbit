#!/usr/bin/env python3
"""
WebSocket server running inside every ECS container on port 8001.
Provides 4 channels: /ws/chat, /ws/plan, /ws/diff, /ws/perms
Also exposes internal HTTP endpoints for IPC with file_watcher, heartbeat,
agent_forwarder, and permission_gate (all co-located in the same container).
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Dict, Set

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
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


# ── Permission state (keyed by permission_id) ─────────────────────────────────

# pending: requests waiting for user action, broadcast immediately to new clients
pending_permissions: Dict[str, dict] = {}
# responses: resolved entries, consumed by permission_gate poll
permission_responses: Dict[str, dict] = {}


# ── WebSocket endpoints ───────────────────────────────────────────────────────

@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket) -> None:
    await chat_mgr.connect(ws)
    try:
        while True:
            data = await ws.receive_json()
            # Broadcast user messages to all chat clients
            await chat_mgr.broadcast({
                "type": "user_message",
                "content": data.get("content", ""),
                "timestamp": _now(),
            })
    except WebSocketDisconnect:
        chat_mgr.disconnect(ws)
    except Exception:
        chat_mgr.disconnect(ws)


@app.websocket("/ws/plan")
async def ws_plan(ws: WebSocket) -> None:
    await plan_mgr.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keep-alive reads
    except WebSocketDisconnect:
        plan_mgr.disconnect(ws)
    except Exception:
        plan_mgr.disconnect(ws)


@app.websocket("/ws/diff")
async def ws_diff(ws: WebSocket) -> None:
    await diff_mgr.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        diff_mgr.disconnect(ws)
    except Exception:
        diff_mgr.disconnect(ws)


@app.websocket("/ws/perms")
async def ws_perms(ws: WebSocket) -> None:
    await perms_mgr.connect(ws)
    # Replay any already-pending permissions to the new client
    for perm in list(pending_permissions.values()):
        try:
            await ws.send_json(perm)
        except Exception:
            break
    try:
        while True:
            data = await ws.receive_json()
            # Dashboard sends: {"permission_id": "...", "granted": true/false}
            perm_id = data.get("permission_id")
            granted = bool(data.get("granted", False))
            if perm_id and perm_id in pending_permissions:
                permission_responses[perm_id] = {
                    "granted": granted,
                    "reason": "user approved" if granted else "user denied",
                }
                del pending_permissions[perm_id]
                # Ack to all perms clients so the panel clears
                await perms_mgr.broadcast({
                    "type": "permission_resolved",
                    "permission_id": perm_id,
                    "granted": granted,
                })
    except WebSocketDisconnect:
        perms_mgr.disconnect(ws)
    except Exception:
        perms_mgr.disconnect(ws)


# ── Internal HTTP endpoints (used by co-located processes) ────────────────────

class ChatLine(BaseModel):
    content: str
    source: str = "agent"  # "agent" | "system"


@app.post("/internal/push_chat")
async def push_chat(payload: ChatLine) -> dict:
    """Called by agent_forwarder to stream agent output to dashboard."""
    await chat_mgr.broadcast({
        "type": payload.source,
        "content": payload.content,
        "timestamp": _now(),
    })
    return {"status": "ok"}


class PlanMessage(BaseModel):
    content: str
    msg_type: str = "system"  # "system" | "plan" | "heartbeat"


@app.post("/internal/push_plan")
async def push_plan(payload: PlanMessage) -> dict:
    """Called by heartbeat and MCP save_plan to update the plan panel."""
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
    """Called by file_watcher on every file change."""
    await diff_mgr.broadcast({
        "type": "diff",
        "file": payload.file,
        "patch": payload.patch,
        "timestamp": _now(),
    })
    return {"status": "ok"}


class PermissionRequestPayload(BaseModel):
    id: str
    action: str
    command: str
    reason: str
    session_id: str


@app.post("/internal/permission_request")
async def create_permission_request(req: PermissionRequestPayload) -> dict:
    """Called by permission_gate MCP tool when agent needs user approval."""
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
    """Polled by permission_gate until user responds or timeout."""
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
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")
