import json
import os
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
import subprocess

from fastapi import FastAPI, Request
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- CONFIG ---
PENDING_FILE = "pending.json"
ONGOING_FILE = "ongoing.json"
DONE_FILE = "done.json"
POLL_INTERVAL_SECS = 10
TASK_TIMEOUT_MINS = 10

# --- FILE HELPERS ---

def read_json(filepath):
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r") as f:
        content = f.read().strip()
        if not content or content == "{}":
            return []
        return json.loads(content)

def write_json(filepath, data):
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

def get_ongoing():
    if not os.path.exists(ONGOING_FILE):
        return None
    with open(ONGOING_FILE, "r") as f:
        content = f.read().strip()
        if not content or content == "{}":
            return None
        return json.loads(content)

def set_ongoing(task):
    with open(ONGOING_FILE, "w") as f:
        json.dump(task, f, indent=2)

def clear_ongoing():
    with open(ONGOING_FILE, "w") as f:
        json.dump({}, f, indent=2)

def init_files():
    for f in [PENDING_FILE, DONE_FILE]:
        if not os.path.exists(f):
            write_json(f, [])
    if not os.path.exists(ONGOING_FILE):
        clear_ongoing()

# --- WATCHER LOGIC ---

def pick_next_task():
    pending = read_json(PENDING_FILE)
    if not pending:
        return None

    task = pending.pop(0)
    task["started_at"] = datetime.utcnow().isoformat()
    task["last_checked_at"] = datetime.utcnow().isoformat()

    write_json(PENDING_FILE, pending)
    set_ongoing(task)

    print(f"[WATCHER] Picked task: {task['task_id']} - {task['title']}")
    return task

def trigger_coding_agent(task):
    print(f"[WATCHER] Triggering coding agent for: {task['task_id']}")

    context = {
        "task_id": task["task_id"],
        "title": task["title"],
        "description": task["description"],
        "instruction": f"""
You are a coding agent. Your job is:
1. Read the task below carefully
2. Make the necessary code changes
3. Once done, append to done.json like this:

{{
  "task_id": "{task['task_id']}",
  "title": "{task['title']}",
  "completed_at": "<current timestamp>",
  "summary": "<what you did>"
}}

4. Then clear ongoing.json by writing {{}} to it.

TASK:
Title: {task['title']}
Description: {task['description']}
"""
    }

    with open("current_task.json", "w") as f:
        json.dump(context, f, indent=2)
    
    print("context=============================================>", type(json.dumps(context)))

    print(f"[WATCHER] Task context written to current_task.json")
    subprocess.run(["gemini","--prompt", json.dumps(context),"--include-directories", "./", "--approval-mode", "yolo"])

def check_if_done(ongoing):
    done = read_json(DONE_FILE)
    return any(t.get("task_id") == ongoing["task_id"] for t in done)

def check_timeout(ongoing):
    started_at = datetime.fromisoformat(ongoing["started_at"])
    elapsed = datetime.utcnow() - started_at

    if elapsed > timedelta(minutes=TASK_TIMEOUT_MINS):
        mins = int(elapsed.total_seconds() / 60)
        print(f"[WATCHER] ⚠️  Task {ongoing['task_id']} running for {mins} mins - asking agent for status...")

        ongoing["last_checked_at"] = datetime.utcnow().isoformat()
        set_ongoing(ongoing)

        # TODO: ping coding agent for status
        return True
    return False

async def watcher_job():
    print(f"[WATCHER] Running at {datetime.utcnow().isoformat()}")
    ongoing = get_ongoing()

    if not ongoing:
        pending = read_json(PENDING_FILE)
        if pending:
            print(f"[WATCHER] {len(pending)} pending task(s) found. Picking next...")
            task = pick_next_task()
            if task:
                trigger_coding_agent(task)
        else:
            print("[WATCHER] No pending tasks.")
    else:
        print(f"[WATCHER] Task in progress: {ongoing['task_id']}")
        if check_if_done(ongoing):
            print(f"[WATCHER] ✅ Task {ongoing['task_id']} DONE!")
            clear_ongoing()
        else:
            check_timeout(ongoing)

# --- APP LIFESPAN ---

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_files()
    # scheduler.add_job(watcher_job, "interval", seconds=POLL_INTERVAL_SECS)
    scheduler.start()
    print(f"[SCHEDULER] Watcher started — polling every {POLL_INTERVAL_SECS}s")
    yield
    scheduler.shutdown()
    print("[SCHEDULER] Watcher stopped")

app = FastAPI()

# --- WEBHOOK ENDPOINT ---

@app.post("/jira-webhook")
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
        "received_at": datetime.utcnow().isoformat()
    }

    pending = read_json(PENDING_FILE)
    existing_ids = [t["task_id"] for t in pending]

    if task["task_id"] not in existing_ids:
        pending.append(task)
        write_json(PENDING_FILE, pending)
        print(f"[WEBHOOK] New task added: {task['task_id']} - {task['title']}")
        return {"status": "added", "task_id": task["task_id"]}

    return {"status": "duplicate"}

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "pending": len(read_json(PENDING_FILE)),
        "ongoing": get_ongoing(),
        "done": len(read_json(DONE_FILE))
    }

@app.post("/webhook")
async def handle_webhook(request: Request):
    payload = await request.json()


    assignee = payload.get("issue", {}).get("fields", {}).get("assignee")
    fields = payload["issue"]["fields"]


    if not assignee:
        print("==================>")
        return {"status": "ignored - no assignee"}


    issue_key = payload["issue"]["key"]
    summary = payload["issue"]["fields"].get("summary", "")
    description = payload["issue"]["fields"].get("description")
    print("--------------------------------?",payload["issue"]["fields"])
    model_name = payload["issue"]["fields"].get("customfield_10071")
    github_repo_name = payload["issue"]["fields"].get("customfield_10104")

    print(f"[TRIGGER] Issue {issue_key}: {summary}")
    print(f"[DESCRIPTION] {description}")

    return {
        "status": "triggered",
        "issue_key": issue_key,
        "summary": summary,
        "description": description
    }


# --- RUN ---
# uvicorn main:app --reload