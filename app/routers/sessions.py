"""
Session management endpoints + internal endpoints called by ECS tasks.
"""

import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from app.chroma import get_collection
from app.dao.permission_dao import permission_dao
from app.dao.session_dao import session_dao
from app.models.permission import PermissionStatus

router = APIRouter(tags=["sessions"])


# ── Public session endpoints ──────────────────────────────────────────────────

@router.get("/sessions")
async def list_sessions():
    """Returns all sessions with status, ws_url, ticket_id, and time_remaining."""
    records = await session_dao.get_all()
    return [_session_summary(r) for r in records]


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Single session detail including permission log."""
    record = await session_dao.get_by_session_id(session_id)
    if not record:
        raise HTTPException(status_code=404, detail="Session not found")

    perms = await permission_dao.get_by_session(session_id)
    return {
        **_session_summary(record),
        "ticket_details":    record.ticket_details,
        "plan":              record.plan,
        "reasoning":         record.reasoning,
        "file_changes":      record.file_changes or [],
        "function_changes":  record.function_changes or [],
        "task_arn":          record.task_arn,
        "permission_log":    [_perm_dict(p) for p in perms],
    }


# ── Internal endpoints called by ECS tasks ────────────────────────────────────

@router.post("/internal/register_task")
async def register_task(request: Request):
    """
    Called by the ECS task on startup.
    Payload: {session_id, ws_url, task_arn}
    """
    payload = await request.json()
    session_id = payload.get("session_id")
    ws_url     = payload.get("ws_url")
    task_arn   = payload.get("task_arn")

    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")

    record = await session_dao.update(
        session_id,
        ws_url=ws_url,
        task_arn=task_arn,
        started_at=datetime.now(timezone.utc),
    )
    if not record:
        raise HTTPException(status_code=404, detail=f"No session found for {session_id}")

    print(f"[REGISTER] session={session_id} ws_url={ws_url} task_arn={task_arn}")
    return {"status": "ok", "session_id": session_id}


@router.post("/internal/snapshot/{session_id}")
async def snapshot_session(session_id: str):
    """
    Triggered by the container heartbeat on session timeout.
    Reads the agent's JSONL conversation log from the shared EFS volume,
    summarises it via Gemini, and stores to ChromaDB.
    """
    record = await session_dao.get_by_session_id(session_id)
    if not record:
        raise HTTPException(status_code=404, detail="Session not found")

    gemini_home = os.environ.get("GEMINI_CLI_HOME", "/gemini_home")
    jsonl_path  = os.path.join(gemini_home, session_id, "conversation.jsonl")

    lines: list[dict] = []
    if os.path.exists(jsonl_path):
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    lines.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    else:
        print(f"[SNAPSHOT] JSONL not found at {jsonl_path}")

    summary = _summarise_with_gemini(lines, record.ticket_id or session_id)

    collection = get_collection()
    collection.upsert(
        ids=[f"snapshot-{session_id}"],
        documents=[summary],
        metadatas=[{
            "type":       "snapshot",
            "session_id": session_id,
            "ticket_id":  record.ticket_id or "",
        }],
    )

    await session_dao.update(session_id, status="SNAPSHOT_SAVED")
    print(f"[SNAPSHOT] Saved snapshot for session {session_id}")
    return {"status": "ok", "session_id": session_id, "lines_read": len(lines)}


# ── Internal: permission logging (called by permission_gate via ws_server) ────

@router.post("/internal/log_permission_request")
async def log_permission_request(request: Request):
    payload = await request.json()
    try:
        await permission_dao.create(
            permission_id=payload["id"],
            session_id=payload["session_id"],
            ticket_id=payload.get("ticket_id", ""),
            action=payload["action"],
            command=payload["command"],
            reason=payload.get("reason", ""),
        )
    except Exception as e:
        print(f"[PERM_LOG] create failed: {e}")
    return {"status": "ok"}


@router.post("/internal/log_permission_response")
async def log_permission_response(request: Request):
    payload = await request.json()
    perm_id    = payload.get("permission_id")
    granted    = payload.get("granted", False)
    resolved_by = payload.get("resolved_by", "user")

    if not perm_id:
        raise HTTPException(status_code=400, detail="permission_id required")

    if resolved_by == "timeout":
        await permission_dao.timeout(perm_id)
    else:
        await permission_dao.resolve(perm_id, granted=granted, resolved_by=resolved_by)

    return {"status": "ok"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _session_summary(record) -> dict:
    now = datetime.now(timezone.utc)
    started = record.started_at
    if started and started.tzinfo is None:
        from datetime import timezone as tz
        started = started.replace(tzinfo=tz.utc)

    if started:
        elapsed  = (now - started).total_seconds()
        remaining = max(0, int(7200 - elapsed))  # 2hr = 7200s
    else:
        remaining = 7200

    return {
        "session_id":     record.session_id,
        "ticket_id":      record.ticket_id,
        "status":         record.status,
        "ws_url":         record.ws_url,
        "model_used":     record.model_used,
        "repo_name":      record.repo_name,
        "started_at":     started.isoformat() if started else None,
        "time_remaining": remaining,
    }


def _perm_dict(p) -> dict:
    return {
        "permission_id": p.permission_id,
        "action":        p.action,
        "command":       p.command,
        "reason":        p.reason,
        "status":        p.status,
        "resolved_by":   p.resolved_by,
        "requested_at":  p.requested_at.isoformat() if p.requested_at else None,
        "resolved_at":   p.resolved_at.isoformat() if p.resolved_at else None,
    }


def _summarise_with_gemini(lines: list[dict], label: str) -> str:
    """Summarise a conversation JSONL via Gemini. Falls back to raw text if unavailable."""
    if not lines:
        return f"No conversation data found for {label}."

    text = "\n".join(json.dumps(l) for l in lines[:200])  # cap at 200 entries

    try:
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = (
            f"Summarise the following AI coding agent conversation for ticket {label}. "
            f"Focus on: what was attempted, what was completed, what problems were encountered, "
            f"and what files were modified.\n\n{text}"
        )
        return model.generate_content(prompt).text
    except Exception as e:
        print(f"[SNAPSHOT] Gemini summarise failed: {e}")
        return f"Raw context for {label} ({len(lines)} entries):\n{text[:4000]}"
