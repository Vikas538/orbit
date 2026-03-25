from datetime import datetime

from fastapi import APIRouter, Request

from app.dao.session_dao import session_dao
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
        await session_dao.create(
            ticket_id=issue_key,
            ticket_details=fields,
            model_used=model_name,
            repo_name=github_repo_name,
            status="PENDING",
        )
        print(f"[DB] Created session record for {issue_key}")

    return {
        "status": "triggered",
        "issue_key": issue_key,
        "summary": summary,
        "description": description,
        "model_name": model_name,
        "github_repo_name": github_repo_name,
    }
