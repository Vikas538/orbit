#!/bin/bash
set -e

echo "[ORBIT] ── Container live ───────────────────────────────"
echo "[ORBIT] Session: $SESSION_ID"
echo "[ORBIT] Ticket:  $TICKET_ID"
echo "[ORBIT] Repo:    $REPO_URL"
echo "[ORBIT] Model:   $MODEL_USED"

# ── Validate required env vars ───────────────────────────────────────────────
if [ -z "$REPO_URL" ]; then
    echo "[ORBIT] ERROR: REPO_URL is not set"
    exit 1
fi
if [ -z "$SESSION_ID" ]; then
    echo "[ORBIT] ERROR: SESSION_ID is not set"
    exit 1
fi

ORBIT_BASE_URL="${ORBIT_BASE_URL:-https://sheep-amazed-oyster.ngrok-free.app}"
WS_SERVER_URL="${WS_SERVER_URL:-http://localhost:8001}"
export WS_SERVER_URL

# ── Start background services via supervisord ────────────────────────────────
echo "[ORBIT] ── Starting background services (supervisord) ───"
supervisord -c /container/supervisord.conf &
SUPERVISORD_PID=$!

# Wait for ws_server to be ready (up to 15s)
echo "[ORBIT] ── Waiting for ws_server on :8001 ───────────────"
for i in $(seq 1 15); do
    if curl -sf "${WS_SERVER_URL}/health" > /dev/null 2>&1; then
        echo "[ORBIT] ws_server ready (${i}s)"
        break
    fi
    sleep 1
done

# ── Discover own public IP from ECS metadata ─────────────────────────────────
echo "[ORBIT] ── Fetching ECS metadata ───────────────────────"
ECS_META_URL="${ECS_CONTAINER_METADATA_URI_V4:-http://169.254.170.2/v2/metadata}"
OWN_IP=$(curl -sf "${ECS_META_URL}" \
    | python3 -c "import json,sys; m=json.load(sys.stdin); print(m['Containers'][0]['Networks'][0]['IPv4Addresses'][0])" \
    2>/dev/null || echo "127.0.0.1")
WS_URL="ws://${OWN_IP}:8001"
echo "[ORBIT] Public ws_url: ${WS_URL}"

# ── Register this task with host FastAPI ─────────────────────────────────────
echo "[ORBIT] ── Registering task with host ──────────────────"
TASK_ARN="${ECS_TASK_ARN:-local}"
curl -s -X POST "${ORBIT_BASE_URL}/internal/register_task" \
    -H "Content-Type: application/json" \
    -d "{\"session_id\": \"${SESSION_ID}\", \"ws_url\": \"${WS_URL}\", \"task_arn\": \"${TASK_ARN}\"}" \
    || echo "[ORBIT] WARNING: register_task failed"

# ── Clone repo via SSH ────────────────────────────────────────────────────────
echo "[ORBIT] ── Cloning $REPO_URL ──────────────────────────"
REPO_DIR="/workspace/$(basename "$REPO_URL" .git)"
export REPO_DIR
git clone "$REPO_URL" "$REPO_DIR"
cd "$REPO_DIR"
echo "[ORBIT] Cloned into $REPO_DIR"

# ── Inject guardrails ─────────────────────────────────────────────────────────
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

# ── Read README ───────────────────────────────────────────────────────────────
README=""
for f in README.md readme.md README.txt README; do
    if [ -f "$f" ]; then
        README=$(cat "$f")
        echo "[ORBIT] README found: $f"
        break
    fi
done

# ── Setup environment ─────────────────────────────────────────────────────────
echo "[ORBIT] ── Setting up environment ─────────────────────"
if [ -f "package.json" ]; then
    npm install --silent
elif [ -f "requirements.txt" ]; then
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -q
elif [ -f "pyproject.toml" ]; then
    python3 -m venv .venv && .venv/bin/pip install . -q
elif [ -f "go.mod" ]; then
    go mod download
fi

# ── Configure MCP for both models ────────────────────────────────────────────
MCP_CONFIG_JSON='{
  "mcpServers": {
    "orbit-tools": {
      "command": "python3",
      "args": ["/orbit-tools/mcp_server.py"]
    },
    "permission-gate": {
      "command": "python3",
      "args": ["/orbit-tools/permission_gate.py"]
    }
  }
}'

# ── Run agent with output forwarded to ws_server ─────────────────────────────
echo "[ORBIT] ── Running agent ($MODEL_USED) ────────────────"
FULL_PROMPT="Project README:\n${README}\n\n---\n\nTask:\n${TASK_PROMPT} Once changes are done, push to git and create a new branch named after the ticket ID."

case "$MODEL_USED" in
    claude)
        echo "$MCP_CONFIG_JSON" > /tmp/mcp_config.json
        claude --print --dangerously-skip-permissions \
               --mcp-config /tmp/mcp_config.json \
               "$FULL_PROMPT" 2>&1 \
        | python3 /container/agent_forwarder.py
        ;;
    gemini | *)
        mkdir -p /home/orbit/.gemini
        echo "$MCP_CONFIG_JSON" > /home/orbit/.gemini/settings.json
        gemini --prompt "$FULL_PROMPT" \
               --include-directories ./ \
               --approval-mode yolo 2>&1 \
        | python3 /container/agent_forwarder.py
        ;;
esac

# ── Mark session as COMPLETED ─────────────────────────────────────────────────
echo "[ORBIT] ── Marking $TICKET_ID as COMPLETED ─────────────"
curl -s -X POST "${ORBIT_BASE_URL}/agent/complete" \
     -H "Content-Type: application/json" \
     -d "{\"ticket_id\": \"$TICKET_ID\"}" \
     || echo "[ORBIT] WARNING: could not update status to COMPLETED"

echo "[ORBIT] ── Done: $TICKET_ID ─────────────────────────────"

# ── Stop supervisord (background services) ────────────────────────────────────
kill $SUPERVISORD_PID 2>/dev/null || true
