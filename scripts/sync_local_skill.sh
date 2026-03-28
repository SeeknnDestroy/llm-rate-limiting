#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCE_DIR="${REPO_ROOT}/skills/llm-rate-limiting"
TARGET_KIND="auto"
TARGET_BASE=""
DRY_RUN=false

print_help() {
  cat <<'EOF'
Usage:
  bash scripts/sync_local_skill.sh [--target auto|codex|claude] [--target-dir /path] [--dry-run]

Examples:
  bash scripts/sync_local_skill.sh
  bash scripts/sync_local_skill.sh --target codex
  bash scripts/sync_local_skill.sh --target claude
  bash scripts/sync_local_skill.sh --target-dir /absolute/path/to/skills
  bash scripts/sync_local_skill.sh --target claude --dry-run
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      TARGET_KIND="${2:-}"
      shift 2
      ;;
    --target-dir)
      TARGET_BASE="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --help|-h)
      print_help
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      print_help >&2
      exit 1
      ;;
  esac
done

resolve_target_base() {
  case "${TARGET_KIND}" in
    codex)
      printf '%s\n' "${CODEX_HOME:-$HOME/.codex}/skills"
      ;;
    claude)
      printf '%s\n' "${CLAUDE_HOME:-$HOME/.claude}/skills"
      ;;
    auto)
      if [[ -d "${CODEX_HOME:-$HOME/.codex}/skills" ]]; then
        printf '%s\n' "${CODEX_HOME:-$HOME/.codex}/skills"
      elif [[ -d "${CLAUDE_HOME:-$HOME/.claude}/skills" ]]; then
        printf '%s\n' "${CLAUDE_HOME:-$HOME/.claude}/skills"
      else
        printf '%s\n' "${CODEX_HOME:-$HOME/.codex}/skills"
      fi
      ;;
    *)
      echo "Unsupported target: ${TARGET_KIND}" >&2
      exit 1
      ;;
  esac
}

if [[ ! -d "${SOURCE_DIR}" ]]; then
  echo "Source skill directory not found: ${SOURCE_DIR}" >&2
  exit 1
fi

if [[ -z "${TARGET_BASE}" ]]; then
  TARGET_BASE="$(resolve_target_base)"
fi

TARGET_DIR="${TARGET_BASE%/}/llm-rate-limiting"
RSYNC_ARGS=(-a --delete)

if [[ "${DRY_RUN}" == true ]]; then
  RSYNC_ARGS+=(--dry-run --itemize-changes)
else
  mkdir -p "${TARGET_BASE}"
fi

echo "Syncing from ${SOURCE_DIR} to ${TARGET_DIR}"
rsync "${RSYNC_ARGS[@]}" "${SOURCE_DIR}/" "${TARGET_DIR}/"

if [[ "${DRY_RUN}" == true ]]; then
  echo "Dry run complete for ${TARGET_DIR}"
else
  echo "Synced skill to ${TARGET_DIR}"
fi
