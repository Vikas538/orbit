#!/bin/bash
set -e

echo "[ORBIT] ── Installing CLIs ──────────────────────────────"
npm install -g @google/gemini-cli @anthropic-ai/claude-code --silent

# GitHub CLI
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | tee /etc/apt/sources.list.d/github-cli.list > /dev/null
apt-get update -qq && apt-get install -y gh -qq
echo "[ORBIT] GitHub CLI $(gh --version | head -1)"

echo "[ORBIT] ── Cloning repo: $REPO_NAME ────────────────────"
if [ -z "$REPO_NAME" ]; then
    echo "[ORBIT] ERROR: REPO_NAME is not set"
    exit 1
fi

# Authenticate gh CLI and clone using repo_name as the full GitHub URL
echo "$GITHUB_TOKEN" | gh auth login --with-token
REPO_URL="https://github.com/$REPO_NAME"
WORKSPACE="/workspace/$(basename "$REPO_NAME")"
gh repo clone "$REPO_URL" "$WORKSPACE"
cd "$WORKSPACE"

echo "[ORBIT] ── Reading README ──────────────────────────────"
README=""
for f in README.md readme.md README.txt README; do
    if [ -f "$f" ]; then
        README=$(cat "$f")
        echo "[ORBIT] Found $f"
        break
    fi
done

echo "[ORBIT] ── Setting up environment ──────────────────────"
if [ -f "package.json" ]; then
    echo "[ORBIT] Detected Node project → npm install"
    npm install --silent
elif [ -f "requirements.txt" ]; then
    echo "[ORBIT] Detected Python project → pip install"
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -q
elif [ -f "pyproject.toml" ]; then
    echo "[ORBIT] Detected pyproject.toml → pip install"
    python3 -m venv .venv && .venv/bin/pip install . -q
elif [ -f "Gemfile" ]; then
    echo "[ORBIT] Detected Ruby project → bundle install"
    bundle install --quiet
elif [ -f "go.mod" ]; then
    echo "[ORBIT] Detected Go project → go mod download"
    go mod download
fi

echo "[ORBIT] ── Running agent ($MODEL_USED) ─────────────────"
FULL_PROMPT="Project README:\n$README\n\n---\n\nTask:\n$TASK_PROMPT"

case "$MODEL_USED" in
    claude)
        claude \
            --print \
            --dangerously-skip-permissions \
            "$FULL_PROMPT"
        ;;
    gemini | *)
        gemini \
            --prompt "$FULL_PROMPT" \
            --include-directories ./ \
            --approval-mode yolo
        ;;
esac

echo "[ORBIT] ── Done: $TICKET_ID ($REPO_URL) ────────────────"
