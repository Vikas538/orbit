import os
import pathlib

import docker
from docker.errors import APIError

from app.config import settings
from app.models.session import OrbitSessions

client = docker.from_env()

# .env file path — passed as env_file to the container so all keys are available
_ENV_FILE = str(pathlib.Path(__file__).resolve().parents[2] / ".env")
_SSH_DIR = os.path.expanduser("~/.ssh")


def _build_task_prompt(session: OrbitSessions) -> str:
    details = session.ticket_details or {}
    summary = details.get("summary", session.ticket_id)
    description = details.get("description", "")
    return (
        f"Ticket: {session.ticket_id}\n"
        f"Summary: {summary}\n"
        f"Description: {description}\n\n"
        "Make the necessary code changes to complete this ticket. "
        "Commit your changes when done."
    )


def _load_env_file(path: str) -> dict:
    """Parse .env file into a dict (mirrors docker-compose env_file behaviour)."""
    env = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env


def spin_up(session: OrbitSessions) -> tuple[str, str]:
    """
    Spin up an isolated agent container from the shared AI-tools image.
    The image already has all CLI tools and API keys baked in via env_file.
    Returns (container_name, container_id).
    """
    container_name = session.ticket_id  # e.g. "PROJ-42"
    task_prompt = _build_task_prompt(session)

    # Start from keys already in the image (.env), then layer task-specific vars on top
    env = _load_env_file(_ENV_FILE)
    env.update({
        "TICKET_ID": session.ticket_id or "",
        "REPO_NAME": session.repo_name or "",
        "MODEL_USED": session.model_used or "gemini",
        "TASK_PROMPT": task_prompt,
    })

    try:
        container = client.containers.run(
            settings.AGENT_IMAGE,
            name=container_name,
            detach=True,
            stdin_open=True,
            tty=True,
            environment=env,
            volumes={
                _SSH_DIR: {"bind": "/root/.ssh", "mode": "ro"},
            },
            mem_limit="2g",
            cpu_quota=100000,  # 1 CPU
            network_mode="bridge",
            labels={
                "orbit.session_id": session.session_id,
                "orbit.ticket_id": session.ticket_id,
            },
        )
        print(f"[CONTAINER] Started {container_name} → {container.short_id}")
        return container_name, container.id

    except APIError as e:
        print(f"[CONTAINER] Failed to start container for {session.ticket_id}: {e}")
        raise
