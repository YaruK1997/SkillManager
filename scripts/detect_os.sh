#!/usr/bin/env bash
# ==============================================================================
# SkillManager - Host OS and Skills Directory Detection Helper
# Supports: Windows (Git Bash/MSYS/Cygwin), macOS (Darwin), Linux
# ==============================================================================
set -euo pipefail

detect_host_os() {
    local os_raw
    os_raw="$(uname -s 2>/dev/null || echo "Unknown")"
    case "${os_raw}" in
        Darwin*)
            echo "macOS"
            ;;
        Linux*)
            echo "Linux"
            ;;
        CYGWIN*|MINGW*|MSYS*)
            echo "Windows"
            ;;
        *)
            if [ -n "${USERPROFILE:-}" ]; then
                echo "Windows"
            else
                echo "Linux"
            fi
            ;;
    esac
}

resolve_host_home() {
    local os_type="$1"
    if [ "${os_type}" = "Windows" ]; then
        echo "${USERPROFILE:-$HOME}"
    else
        echo "${HOME}"
    fi
}

HOST_OS="$(detect_host_os)"
HOST_HOME="$(resolve_host_home "${HOST_OS}")"
HOST_GEMINI_SKILLS_DIR="${HOST_HOME}/.gemini/antigravity/skills"
HOST_CLAUDE_SKILLS_DIR="${HOST_HOME}/.claude/skills"
HOST_CODEX_SKILLS_DIR="${HOST_HOME}/.codex/skills"
HOST_CURSOR_SKILLS_DIR="${HOST_HOME}/.cursor/skills"

create_host_dirs() {
    mkdir -p "${HOST_GEMINI_SKILLS_DIR}" \
             "${HOST_CLAUDE_SKILLS_DIR}" \
             "${HOST_CODEX_SKILLS_DIR}" \
             "${HOST_CURSOR_SKILLS_DIR}"
}

update_env_file() {
    local env_file="${1:-.env}"
    [ -f "${env_file}" ] || touch "${env_file}"

    python3 -c "
import sys, re
env_file = sys.argv[1]
vars_to_set = {
    'HOST_OS': sys.argv[2],
    'HOST_HOME': sys.argv[3],
    'HOST_GEMINI_SKILLS_DIR': sys.argv[4],
    'HOST_CLAUDE_SKILLS_DIR': sys.argv[5],
    'HOST_CODEX_SKILLS_DIR': sys.argv[6],
    'HOST_CURSOR_SKILLS_DIR': sys.argv[7],
}
try:
    with open(env_file, 'r', encoding='utf-8') as f:
        content = f.read()
except FileNotFoundError:
    content = ''

for k, v in vars_to_set.items():
    if re.search(rf'^{k}=.*$', content, flags=re.MULTILINE):
        content = re.sub(rf'^{k}=.*$', f'{k}={v}', content, flags=re.MULTILINE)
    else:
        if content and not content.endswith('\n'):
            content += '\n'
        content += f'{k}={v}\n'

with open(env_file, 'w', encoding='utf-8') as f:
    f.write(content)
" "${env_file}" "${HOST_OS}" "${HOST_HOME}" "${HOST_GEMINI_SKILLS_DIR}" "${HOST_CLAUDE_SKILLS_DIR}" "${HOST_CODEX_SKILLS_DIR}" "${HOST_CURSOR_SKILLS_DIR}"
}

# If script is executed directly (not sourced)
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    action="${1:---print}"
    case "${action}" in
        --json)
            python3 -c "
import json, sys
data = {
    'host_os': sys.argv[1],
    'host_home': sys.argv[2],
    'skills_dirs': {
        'antigravity': sys.argv[3],
        'claude': sys.argv[4],
        'codex': sys.argv[5],
        'cursor': sys.argv[6],
    }
}
print(json.dumps(data, indent=2))
" "${HOST_OS}" "${HOST_HOME}" "${HOST_GEMINI_SKILLS_DIR}" "${HOST_CLAUDE_SKILLS_DIR}" "${HOST_CODEX_SKILLS_DIR}" "${HOST_CURSOR_SKILLS_DIR}"
            ;;
        --create-dirs)
            create_host_dirs
            echo "[INFO] Host skill directories verified/created."
            ;;
        --env)
            create_host_dirs
            update_env_file "${2:-.env}"
            echo "[INFO] .env updated with host OS: ${HOST_OS}"
            ;;
        --print|*)
            echo "HOST_OS=${HOST_OS}"
            echo "HOST_HOME=${HOST_HOME}"
            echo "HOST_GEMINI_SKILLS_DIR=${HOST_GEMINI_SKILLS_DIR}"
            echo "HOST_CLAUDE_SKILLS_DIR=${HOST_CLAUDE_SKILLS_DIR}"
            echo "HOST_CODEX_SKILLS_DIR=${HOST_CODEX_SKILLS_DIR}"
            echo "HOST_CURSOR_SKILLS_DIR=${HOST_CURSOR_SKILLS_DIR}"
            ;;
    esac
else
    # Sourced mode: export variables to caller shell
    export HOST_OS
    export HOST_HOME
    export HOST_GEMINI_SKILLS_DIR
    export HOST_CLAUDE_SKILLS_DIR
    export HOST_CODEX_SKILLS_DIR
    export HOST_CURSOR_SKILLS_DIR
fi

