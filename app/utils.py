import json
import os

PENDING_FILE = "pending.json"
ONGOING_FILE = "ongoing.json"
DONE_FILE = "done.json"

def read_json(filepath):
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r") as f:
        content = f.read().strip()
        if not content or content == "{}":
            return []
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return []

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
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None

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
