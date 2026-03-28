#!/bin/bash
# Run during Docker image build (as root, before switching to orbit user).
# Installs the orbit-gate wrapper and symlinks dangerous commands to it.
# The wrapper dir is prepended to PATH in the container environment.

set -e

WRAPPER_DIR="/usr/local/orbit/bin"
GATE_SCRIPT="/container/orbit_wrappers/orbit-gate"

mkdir -p "$WRAPPER_DIR"
cp "$GATE_SCRIPT" "$WRAPPER_DIR/orbit-gate"
chmod +x "$WRAPPER_DIR/orbit-gate"

# Commands that require user approval before running
GATED_COMMANDS=(
    pip pip3
    npm npx
    apt apt-get apt-cache
    curl wget
    rm rmdir
    git
    docker kubectl
    ssh scp
    chmod chown
    sudo su
)

for cmd in "${GATED_COMMANDS[@]}"; do
    ln -sf "$WRAPPER_DIR/orbit-gate" "$WRAPPER_DIR/$cmd"
    echo "[WRAPPERS] Installed gate for: $cmd"
done

echo "[WRAPPERS] Done. Add $WRAPPER_DIR to the FRONT of PATH."
echo "           e.g.  ENV PATH=\"$WRAPPER_DIR:\$PATH\""
