#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCE_DIR="${REPO_ROOT}/skills/llm-rate-limiting"
TARGET_BASE="${CODEX_HOME:-$HOME/.codex}/skills"
TARGET_DIR="${TARGET_BASE}/llm-rate-limiting"
DRY_RUN="${1:-}"

if [[ ! -d "${SOURCE_DIR}" ]]; then
  echo "Source skill directory not found: ${SOURCE_DIR}" >&2
  exit 1
fi

mkdir -p "${TARGET_BASE}"

RSYNC_ARGS=(-a --delete)

if [[ "${DRY_RUN}" == "--dry-run" ]]; then
  RSYNC_ARGS+=(--dry-run --itemize-changes)
fi

rsync "${RSYNC_ARGS[@]}" "${SOURCE_DIR}/" "${TARGET_DIR}/"

if [[ "${DRY_RUN}" == "--dry-run" ]]; then
  echo "Dry run complete for ${TARGET_DIR}"
else
  echo "Synced skill to ${TARGET_DIR}"
fi
