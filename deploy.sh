#!/usr/bin/env bash
set -euo pipefail

echo "=== [1/4] Detecting Host Operating System & Preparing Environment ==="
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "${SCRIPT_DIR}/scripts/detect_os.sh" ]; then
    # Sourcing helper exports HOST_OS, HOST_HOME, HOST_*_SKILLS_DIR
    source "${SCRIPT_DIR}/scripts/detect_os.sh"
    "${SCRIPT_DIR}/scripts/detect_os.sh" --env "${SCRIPT_DIR}/.env"
else
    # Fallback inline detection for Windows (Git Bash/MSYS), macOS, Linux
    OS_RAW="$(uname -s 2>/dev/null || echo "Unknown")"
    case "${OS_RAW}" in
        Darwin*)  HOST_OS="macOS"; HOST_HOME="${HOME}" ;;
        Linux*)   HOST_OS="Linux"; HOST_HOME="${HOME}" ;;
        CYGWIN*|MINGW*|MSYS*) HOST_OS="Windows"; HOST_HOME="${USERPROFILE:-$HOME}" ;;
        *)        HOST_OS="Linux"; HOST_HOME="${HOME}" ;;
    esac
    export HOST_OS HOST_HOME
    export HOST_GEMINI_SKILLS_DIR="${HOST_HOME}/.gemini/antigravity/skills"
    export HOST_CLAUDE_SKILLS_DIR="${HOST_HOME}/.claude/skills"
    export HOST_CODEX_SKILLS_DIR="${HOST_HOME}/.codex/skills"
    export HOST_CURSOR_SKILLS_DIR="${HOST_HOME}/.cursor/skills"
    mkdir -p "${HOST_GEMINI_SKILLS_DIR}" "${HOST_CLAUDE_SKILLS_DIR}" "${HOST_CODEX_SKILLS_DIR}" "${HOST_CURSOR_SKILLS_DIR}"
fi

echo "[INFO] Host Operating System : ${HOST_OS}"
echo "[INFO] Host Home Directory   : ${HOST_HOME}"
echo "[INFO] Host Gemini Skills    : ${HOST_GEMINI_SKILLS_DIR}"
echo "[INFO] Host Claude Skills    : ${HOST_CLAUDE_SKILLS_DIR}"

echo "=== [2/4] Building SkillManager Docker Image (${HOST_OS}) ==="
docker compose build --build-arg HOST_OS="${HOST_OS}"

echo "=== [3/4] Starting SkillManager Container & Mounting Host Skills ==="
docker compose up -d

echo "=== [4/4] Waiting for Container Healthcheck Probe ==="
MAX_RETRIES=10
for i in $(seq 1 $MAX_RETRIES); do
    sleep 2
    STATUS=$(docker inspect --format '{{.State.Health.Status}}' skill-manager 2>/dev/null || echo "starting")
    echo "Attempt ${i}/${MAX_RETRIES} : Container status = ${STATUS}"
    if [ "${STATUS}" = "healthy" ]; then
        break
    fi
done

echo "=== Verifying CLI Healthcheck Endpoint Inside Container ==="
docker exec skill-manager skill-manager healthcheck --format json
echo "[SUCCESS] SkillManager deployed and verified HEALTHY (200) on ${HOST_OS}!"
