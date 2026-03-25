FROM node:22-slim

RUN apt-get update && apt-get install -y \
    git \
    curl \
    gnupg \
    apt-transport-https \
    python3 \
    python3-pip \
    python3-venv \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        | tee /etc/apt/sources.list.d/github-cli.list > /dev/null && \
    apt-get update && apt-get install -y gh && \
    rm -rf /var/lib/apt/lists/*

# Install AI CLIs
RUN npm install -g @google/gemini-cli @anthropic-ai/claude-code

# SSH config — trust github.com host so git clone doesn't prompt
RUN mkdir -p /root/.ssh && \
    ssh-keyscan github.com >> /root/.ssh/known_hosts

WORKDIR /workspace

COPY guardrails/CLAUDE.md /guardrails/CLAUDE.md
COPY guardrails/GEMINI.md /guardrails/GEMINI.md
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# API keys and SSH keys are injected at runtime — nothing sensitive here
ENTRYPOINT ["/entrypoint.sh"]
