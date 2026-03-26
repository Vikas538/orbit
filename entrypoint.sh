#!/bin/bash
set -e

echo "[ORBIT] ── Container live ───────────────────────────────"
echo "[ORBIT] Ticket:  $TICKET_ID"
echo "[ORBIT] Repo:    $REPO_URL"
echo "[ORBIT] Model:   $MODEL_USED"

# ── Validate required env vars ───────────────────────────────
if [ -z "$REPO_URL" ]; then
    echo "[ORBIT] ERROR: REPO_URL is not set"
    exit 1
fi

# ── Clone repo via SSH (keys mounted at runtime via ~/.ssh) ──
echo "[ORBIT] ── Cloning $REPO_URL ───────────────────────────"
REPO_DIR="/workspace/$(basename "$REPO_URL" .git)"
git clone "$REPO_URL" "$REPO_DIR"
cd "$REPO_DIR"
echo "[ORBIT] Cloned into $REPO_DIR"

# ── Inject guardrails ─────────────────────────────────────────
case "$MODEL_USED" in
    claude)
        cp /guardrails/CLAUDE.md CLAUDE.md
        echo "[ORBIT] Guardrails → CLAUDE.md"
        ;;
    gemini | *)
        cp /guardrails/GEMINI.md GEMINI.md
        echo "[ORBIT] Guardrails → GEMINI.md"
        ;;
esac

# ── Read README ───────────────────────────────────────────────
README=""
for f in README.md readme.md README.txt README; do
    if [ -f "$f" ]; then
        README=$(cat "$f")
        echo "[ORBIT] README found: $f"
        break
    fi
done

# ── Setup environment ─────────────────────────────────────────
echo "[ORBIT] ── Setting up environment ──────────────────────"
if [ -f "package.json" ]; then
    echo "[ORBIT] Node project → npm install"
    npm install --silent
elif [ -f "requirements.txt" ]; then
    echo "[ORBIT] Python project → pip install"
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -q
elif [ -f "pyproject.toml" ]; then
    echo "[ORBIT] pyproject.toml → pip install"
    python3 -m venv .venv && .venv/bin/pip install . -q
elif [ -f "go.mod" ]; then
    echo "[ORBIT] Go project → go mod download"
    go mod download
fi

# ── Run agent ─────────────────────────────────────────────────
echo "[ORBIT] ── Running agent ($MODEL_USED) ─────────────────"
FULL_PROMPT="Project README:\n$README\n\n---\n\nTask:\n$TASK_PROMPT once the changes are done push the chanes back to git create a new branach as ticket-id "

case "$MODEL_USED" in
    claude)
        # Write MCP config so Claude can call the orbit-tools server
        cat > /tmp/mcp_config.json <<'MCPEOF'
{
  "mcpServers": {
    "orbit-tools": {
      "command": "python3",
      "args": ["/orbit-tools/mcp_server.py"]
    }
  }
}
MCPEOF
        claude --print --dangerously-skip-permissions \
               --mcp-config /tmp/mcp_config.json \
               "$FULL_PROMPT"
        ;;
    gemini | *)
        gemini --prompt "$FULL_PROMPT" --include-directories ./ --approval-mode yolo
        ;;
esac

echo "[ORBIT] ── Done: $TICKET_ID ─────────────────────────────"
