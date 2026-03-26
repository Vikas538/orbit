from datetime import datetime

from fastapi import APIRouter, Request

from app.chroma import get_collection
from app.dao.session_dao import session_dao
from app.services import container_service
from main import read_json, write_json

router = APIRouter(tags=["webhook"])


@router.post("/jira-webhook")
async def jira_webhook(request: Request):
    payload = await request.json()

    event = payload.get("webhookEvent", "")
    if event not in ["jira:issue_created", "jira:issue_updated"]:
        return {"status": "ignored"}

    issue = payload.get("issue", {})
    fields = issue.get("fields", {})
    assignee = fields.get("assignee")
    status = fields.get("status", {}).get("name", "")

    if not assignee or status not in ["To Do", "Open"]:
        return {"status": "ignored"}

    task = {
        "task_id": issue.get("key"),
        "title": fields.get("summary", ""),
        "description": fields.get("description", "") or "",
        "status": status,
        "assignee": assignee.get("displayName", ""),
        "received_at": datetime.utcnow().isoformat(),
    }

    pending = read_json("pending.json")
    existing_ids = [t["task_id"] for t in pending]

    if task["task_id"] not in existing_ids:
        pending.append(task)
        write_json("pending.json", pending)
        print(f"[WEBHOOK] New task added: {task['task_id']} - {task['title']}")
        return {"status": "added", "task_id": task["task_id"]}

    return {"status": "duplicate"}


@router.post("/webhook")
async def handle_webhook(request: Request):
    payload = await request.json()

    issue = payload.get("issue", {})
    fields = issue.get("fields", {})
    assignee = fields.get("assignee")

    if not assignee:
        return {"status": "ignored - no assignee"}

    issue_key = issue.get("key")
    summary = fields.get("summary", "")
    description = fields.get("description")
    model_name = fields.get("customfield_10071")
    github_repo_name = fields.get("customfield_10104")

    print(f"[TRIGGER] Issue {issue_key}: {summary}")

    existing = await session_dao.get_by_ticket_id(issue_key)
    if not existing:
        record = await session_dao.create(
            ticket_id=issue_key,
            ticket_details=fields,
            model_used=model_name,
            repo_name=github_repo_name,
            status="PENDING",
        )
        print(f"[DB] Created session record for {issue_key}")

        container_name, container_id = container_service.spin_up(record)
        await session_dao.update(
            record.session_id,
            container_name=container_name,
            container_id=container_id,
            status="IN_PROGRESS",
        )
        print(f"[CONTAINER] {container_name} ({container_id[:12]}) running")

    return {
        "status": "triggered",
        "issue_key": issue_key,
        "summary": summary,
        "description": description,
        "model_name": model_name,
        "github_repo_name": github_repo_name,
    }


@router.post("/agent/plan")
async def save_agent_plan(request: Request):
    print(f"[API] POST /agent/plan hit from {request.client.host}")
    payload = await request.json()
    print(f"[API] /agent/plan payload: {payload}")

    ticket_id = payload.get("ticket_id")
    if not ticket_id:
        return {"status": "error", "detail": "ticket_id required"}

    record = await session_dao.get_by_ticket_id(ticket_id)

    files_affected = payload.get("files_affected", [])
    functions_affected = payload.get("functions_affected", [])
    reasoning = payload.get("reasoning", "")
    plan = payload.get("plan", "")

    # Postgres — file and function names only (if session exists)
    if record:
        await session_dao.update(
            record.session_id,
            file_changes=files_affected,
            function_changes=functions_affected,
            status="PLANNING_DONE",
        )
    else:
        print(f"[PLAN] No session found for {ticket_id} — skipping postgres update")

    # ChromaDB — plan + reasoning as document, rich metadata
    session_id = record.session_id if record else "unknown"
    container_id = (record.container_id or "") if record else "unknown"

    print(f"[CHROMA] Saving plan for {ticket_id} ...")
    print(f"[CHROMA]   session_id         = {session_id}")
    print(f"[CHROMA]   container_id       = {container_id}")
    print(f"[CHROMA]   files_affected     = {files_affected}")
    print(f"[CHROMA]   functions_affected = {functions_affected}")
    print(f"[CHROMA]   reasoning (first 200 chars) = {reasoning[:200]}")
    print(f"[CHROMA]   plan (first 200 chars)      = {plan[:200]}")

    collection = get_collection()
    collection.upsert(
        ids=[ticket_id],
        documents=[f"{reasoning}\n\n{plan}"],
        metadatas=[{
            "ticket_id": ticket_id,
            "session_id": session_id,
            "container_id": container_id,
            "files_affected": ", ".join(files_affected),
            "functions_affected": ", ".join(functions_affected),
        }],
    )

    count = collection.count()
    print(f"[CHROMA] Upsert done. Collection 'orbit_plans' now has {count} document(s).")
    print(f"[PLAN] {ticket_id} → chroma saved | files={files_affected} fns={functions_affected}")
    return {"status": "ok", "ticket_id": ticket_id}


@router.post("/agent/complete")
async def complete_agent_session(request: Request):
    payload = await request.json()
    ticket_id = payload.get("ticket_id")
    if not ticket_id:
        return {"status": "error", "detail": "ticket_id required"}

    record = await session_dao.get_by_ticket_id(ticket_id)
    if not record:
        return {"status": "error", "detail": f"No session found for {ticket_id}"}

    await session_dao.update(record.session_id, status="COMPLETED")
    print(f"[COMPLETE] {ticket_id} → status=COMPLETED")
    return {"status": "ok", "ticket_id": ticket_id}


@router.post("/agent/change")
async def save_agent_change(request: Request):
    print(f"[API] POST /agent/change hit from {request.client.host}")
    payload = await request.json()
    print(f"[API] /agent/change payload: {payload}")

    ticket_id = payload.get("ticket_id")
    if not ticket_id:
        return {"status": "error", "detail": "ticket_id required"}

    record = await session_dao.get_by_ticket_id(ticket_id)
    if not record:
        return {"status": "error", "detail": f"No session found for {ticket_id}"}

    existing_files = record.file_changes or []
    existing_fns = record.function_changes or []

    new_file = payload.get("file")
    new_fns = payload.get("functions_changed", [])

    updated_files = list(set(existing_files + ([new_file] if new_file else [])))
    updated_fns = list(set(existing_fns + new_fns))

    await session_dao.update(
        record.session_id,
        file_changes=updated_files,
        function_changes=updated_fns,
    )

    print(f"[CHANGE] {ticket_id} → file={new_file} fns={new_fns}")
    return {"status": "ok", "ticket_id": ticket_id, "file": new_file}

