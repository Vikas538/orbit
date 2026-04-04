Got it. Here's an accurate, compelling README:

---

# OrbIT 🚀

**Autonomous Jira-to-Code Agent Platform**

OrbIT connects your Jira board to an AI coding agent that spins up an isolated container, executes the ticket, and pushes a reviewed branch — with a human-in-the-loop permission gate for anything risky.

---

## How It Works

1. Jira ticket created in structured format
2. Webhook triggers FastAPI server
3. Isolated Docker container spawned with AI coding agent (Claude Code / Gemini CLI)
4. Agent executes the ticket within defined scope
5. Permission gate intercepts dangerous operations (file deletes, installs, schema changes) — polls FastAPI for human approval before proceeding
6. Reviewer agent scores the output diff against acceptance criteria
7. Clean branch pushed to GitHub on completion
8. Task context stored in ChromaDB for future sessions

---

## Architecture

```
Jira Webhook
     │
     ▼
FastAPI Server
     │
     ▼
Docker Container
  ├── AI Coding Agent (Claude Code / Gemini CLI)
  ├── Permission Gate (HTTP poll → FastAPI)
  └── Reviewer Agent (diff scoring)
     │
     ▼
GitHub Branch + ChromaDB
```

---

## Stack

- **Backend** — Python, FastAPI, PostgreSQL
- **Agent Runtime** — Docker (local), Claude Code / Gemini CLI
- **Memory** — ChromaDB
- **Integration** — Jira Webhooks, GitHub API

---

## Current Status

✅ Jira webhook → container spawn → agent execution  
✅ Permission gate with HTTP approval flow  
✅ Reviewer agent with diff scoring  
✅ Branch push on completion  
✅ ChromaDB context storage  
🔲 Cloud deployment (ECS Fargate — in progress)  
🔲 OrbIT Dashboard UI (separate repo — in progress)

---

## Why OrbIT

Solo devs and small teams waste hours context-switching into tickets that are mechanical but risky to automate blindly. OrbIT gives you an agent that does the work inside a blast-radius-limited container, asks before doing anything dangerous, and leaves a reviewable branch — not a mystery commit.
