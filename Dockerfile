FROM python:3.11-slim

# python3, pip, venv all come free with the base image
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        curl \
        ca-certificates \
        gnupg \
        openssh-client \
        grep \
        procps \
        psmisc \
        net-tools \
        iputils-ping \
        vim \
        less \
        jq \
    # GitHub CLI
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    # Node.js (needed for gemini + claude CLIs)
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    # Purge tools only needed for keyring setup
    && apt-get purge -y gnupg \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Install AI CLIs and clean npm cache in the same layer
RUN npm install -g --no-fund --no-audit @google/gemini-cli @anthropic-ai/claude-code \
    && npm cache clean --force

# Install orbit MCP tool dependencies + ws_server/watcher/heartbeat deps + supervisord
RUN pip install --no-cache-dir mcp httpx fastapi "uvicorn[standard]" watchdog supervisor

RUN ssh-keyscan github.com >> /etc/ssh/ssh_known_hosts

RUN useradd -m -u 1000 orbit

WORKDIR /workspace
RUN chown orbit:orbit /workspace

COPY guardrails/CLAUDE.md /guardrails/CLAUDE.md
COPY guardrails/GEMINI.md /guardrails/GEMINI.md

# MCP tools
COPY orbit-tools/mcp_server.py     /orbit-tools/mcp_server.py
COPY orbit-tools/permission_gate.py /orbit-tools/permission_gate.py

# Container runtime scripts
COPY container/ws_server.py        /container/ws_server.py
COPY container/file_watcher.py     /container/file_watcher.py
COPY container/heartbeat.py        /container/heartbeat.py
COPY container/agent_forwarder.py  /container/agent_forwarder.py
COPY container/supervisord.conf    /container/supervisord.conf

# Install orbit-gate wrappers (must run as root before USER switch)
COPY container/orbit_wrappers /container/orbit_wrappers
RUN bash /container/orbit_wrappers/install_wrappers.sh

COPY container/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && chmod +x /orbit-tools/mcp_server.py \
    && chmod +x /orbit-tools/permission_gate.py

# Prepend wrapper dir so gated commands shadow system binaries
ENV PATH="/usr/local/orbit/bin:$PATH"

USER orbit

RUN mkdir -p /home/orbit/.ssh && chmod 700 /home/orbit/.ssh

ENTRYPOINT ["/entrypoint.sh"]
