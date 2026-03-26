#!/usr/bin/env python3
from mcp.server.fastmcp import FastMCP
import httpx

mcp = FastMCP("orbit-tools")

ORBIT_BASE_URL = "https://sheep-amazed-oyster.ngrok-free.app"


@mcp.tool()
def save_plan(
    ticket_id: str,
    reasoning: str,
    files_affected: list[str],
    functions_affected: list[str],
    plan: str,
) -> str:
    """
    Save your plan BEFORE making any code changes.
    Call this once after analysing the codebase with:
    - ticket_id: the Jira ticket ID (e.g. PROJ-42)
    - reasoning: why you are making these changes
    - files_affected: list of file paths you intend to modify
    - functions_affected: list of function/method names you intend to change
    - plan: step-by-step description of what you will do
    """
    response = httpx.post(
        f"{ORBIT_BASE_URL}/agent/plan",
        json={
            "ticket_id": ticket_id,
            "reasoning": reasoning,
            "files_affected": files_affected,
            "functions_affected": functions_affected,
            "plan": plan,
        },
        timeout=10,
    )
    response.raise_for_status()
    return f"Plan saved for {ticket_id}. You may now proceed with code changes."


@mcp.tool()
def save_change(
    ticket_id: str,
    file: str,
    functions_changed: list[str],
    summary: str,
) -> str:
    """
    Record a change after modifying a file.
    Call this once per file you modify with:
    - ticket_id: the Jira ticket ID
    - file: relative path of the file changed
    - functions_changed: list of function/method names actually changed
    - summary: brief description of what changed in this file
    """
    response = httpx.post(
        f"{ORBIT_BASE_URL}/agent/change",
        json={
            "ticket_id": ticket_id,
            "file": file,
            "functions_changed": functions_changed,
            "summary": summary,
        },
        timeout=10,
    )
    response.raise_for_status()
    return f"Change recorded for {file}."


if __name__ == "__main__":
    mcp.run()
