#!/bin/bash
set -e

IMAGE_NAME="jaas_agent_v1"
IMAGE_TAG="latest"
FULL_TAG="$IMAGE_NAME:$IMAGE_TAG"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Building base image: $FULL_TAG"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

docker build -t "$FULL_TAG" .

echo ""
echo "✓ Image built: $FULL_TAG"
echo ""
echo "── Installed tools ──────────────────────"
docker run --rm "$FULL_TAG" bash -c "
    echo 'git:    '$(git --version) &&
    echo 'node:   '$(node --version) &&
    echo 'gh:     '$(gh --version | head -1) &&
    echo 'gemini: '$(gemini --version 2>/dev/null || echo 'installed') &&
    echo 'claude: '$(claude --version 2>/dev/null || echo 'installed')
"

echo ""
echo "── To push to ECR ───────────────────────"
echo "  aws ecr get-login-password --region <region> | docker login --username AWS --password-stdin <account_id>.dkr.ecr.<region>.amazonaws.com"
echo "  docker tag $FULL_TAG <account_id>.dkr.ecr.<region>.amazonaws.com/$FULL_TAG"
echo "  docker push <account_id>.dkr.ecr.<region>.amazonaws.com/$FULL_TAG"
echo ""
echo "── To run locally ───────────────────────"
echo "  docker run --rm \\"
echo "    --env-file .env \\"
echo "    -v ~/.ssh:/root/.ssh:ro \\"
echo "    -e TICKET_ID=PROJ-1 \\"
echo "    -e REPO_NAME=myorg/my-repo \\"
echo "    -e MODEL_USED=claude \\"
echo "    -e TASK_PROMPT='Fix the login bug' \\"
echo "    $FULL_TAG"
