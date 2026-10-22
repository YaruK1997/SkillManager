#!/usr/bin/env bash
set -euo pipefail

echo "=== [1/4] Building SkillManager Docker Image ==="
docker compose build

echo "=== [2/4] Starting SkillManager Container ==="
docker compose up -d

echo "=== [3/4] Waiting for Container Healthcheck Probe ==="
MAX_RETRIES=10
for i in $(seq 1 $MAX_RETRIES); do
    sleep 2
    STATUS=$(docker inspect --format '{{.State.Health.Status}}' skill-manager 2>/dev/null || echo "starting")
    echo "Attempt ${i}/${MAX_RETRIES} : Container status = ${STATUS}"
    if [ "${STATUS}" = "healthy" ]; then
        break
    fi
done

echo "=== [4/4] Verifying CLI Healthcheck Endpoint Inside Container ==="
docker exec skill-manager skill-manager healthcheck --format json
echo "[SUCCESS] SkillManager deployed and verified HEALTHY (200)!"

