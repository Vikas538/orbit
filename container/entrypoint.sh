#!/bin/bash
set -e

# Runs as orbit (UID 1000). SSH keys mounted at /home/orbit/.ssh work natively.
# Gated PATH (/usr/local/orbit/bin) is injected only when launching the agent.

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

# ── Discover container IP ─────────────────────────────────────────────────────
# ECS metadata commented out — running as plain Docker container for now.
# ECS_META_URL="${ECS_CONTAINER_METADATA_URI_V4:-http://169.254.170.2/v2/metadata}"
# OWN_IP=$(curl -sf "${ECS_META_URL}" | python3 -c "...")
OWN_IP=$(hostname -i 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")
WS_URL="ws://${OWN_IP}:8001"
echo "[ORBIT] ws_url: ${WS_URL}"

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
echo "[ORBIT] Cloned into $REPO_DIR"

# ── Inject guardrails ─────────────────────────────────────────────────────────
case "$MODEL_USED" in
    claude)
        cp /guardrails/CLAUDE.md "$REPO_DIR/CLAUDE.md"
        echo "[ORBIT] Guardrails → CLAUDE.md"
        ;;
    gemini | *)
        cp /guardrails/GEMINI.md "$REPO_DIR/GEMINI.md"
        echo "[ORBIT] Guardrails → GEMINI.md"
        ;;
esac

# ── Read README ───────────────────────────────────────────────────────────────
README=""
for f in README.md readme.md README.txt README; do
    if [ -f "$REPO_DIR/$f" ]; then
        README=$(cat "$REPO_DIR/$f")
        echo "[ORBIT] README found: $f"
        break
    fi
done

# ── Setup environment (initial dep install — not agent-driven) ────────────────
echo "[ORBIT] ── Setting up environment ─────────────────────"
cd "$REPO_DIR"
if [ -f "package.json" ]; then
    npm install --silent
elif [ -f "requirements.txt" ]; then
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -q
elif [ -f "pyproject.toml" ]; then
    python3 -m venv .venv && .venv/bin/pip install . -q
elif [ -f "go.mod" ]; then
    go mod download
fi

# ── Configure MCP ────────────────────────────────────────────────────────────
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

# ── Run agent with gated PATH injected ───────────────────────────────────────
# The orbit-gate wrappers only take effect inside this env — not in the steps above.
echo "[ORBIT] ── Running agent ($MODEL_USED) ────────────────"
FULL_PROMPT="Project README:\n${README}\n\n---\n\nTask:\n${TASK_PROMPT} Once changes are done, push to git and create a new branch named after the ticket ID."
GATED_PATH="/usr/local/orbit/bin:${PATH}"

case "$MODEL_USED" in
    claude)
        echo "$MCP_CONFIG_JSON" > /tmp/mcp_config.json
        env PATH="$GATED_PATH" \
            claude --print --dangerously-skip-permissions \
                   --mcp-config /tmp/mcp_config.json \
                   "$FULL_PROMPT" 2>&1 \
        | python3 /container/agent_forwarder.py
        ;;
    gemini | *)
        mkdir -p /home/orbit/.gemini
        echo "$MCP_CONFIG_JSON" > /home/orbit/.gemini/settings.json
        env PATH="$GATED_PATH" \
            gemini --prompt "$FULL_PROMPT" \
                   --include-directories "$REPO_DIR" \
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

# Notify dashboard that agent is done
curl -s -X POST "${WS_SERVER_URL}/internal/push_plan" \
     -H "Content-Type: application/json" \
     -d "{\"content\": \"Agent finished. Container stays alive for ${POST_TASK_HOLD:-1800}s for review.\", \"msg_type\": \"system\"}" \
     || true

echo "[ORBIT] ── Done: $TICKET_ID ─────────────────────────────"

# Keep ws_server + file_watcher alive so dashboard can review diffs after task ends.
# Defaults to 30 minutes. Override with POST_TASK_HOLD env var (seconds).
HOLD="${POST_TASK_HOLD:-1800}"
echo "[ORBIT] Holding container alive for ${HOLD}s (set POST_TASK_HOLD to change)..."
sleep "$HOLD"

kill $SUPERVISORD_PID 2>/dev/null || true
