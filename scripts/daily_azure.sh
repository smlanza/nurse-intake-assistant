#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/daily_azure.sh start [--config FILE]
  scripts/daily_azure.sh inspect [--config FILE]
  scripts/daily_azure.sh stop [--config FILE]
  scripts/daily_azure.sh check [--config FILE]

Commands:
  start    Run the live rebuild coordinator, including its startup cleanup preflight.
  inspect  Inspect cleanup targets without changing Azure resources.
  stop     Run the explicit, default-no end-of-day cleanup workflow.
  check    Validate the cleanup and rebuild contracts offline.
EOF
}

if [[ $# -eq 0 ]]; then
  usage >&2
  exit 2
fi

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  usage
  exit 0
fi

COMMAND="$1"
shift

case "${COMMAND}" in
  start|inspect|stop|check)
    ;;
  *)
    printf 'Unknown command: %s\n' "${COMMAND}" >&2
    usage >&2
    exit 2
    ;;
esac

if [[ $# -eq 1 && ( "$1" == "--help" || "$1" == "-h" ) ]]; then
  usage
  exit 0
fi

CONFIG_FILE=".env.daily-azure.local"
if [[ $# -gt 0 ]]; then
  if [[ "$1" != "--config" ]]; then
    printf 'Unknown argument: %s\n' "$1" >&2
    usage >&2
    exit 2
  fi
  if [[ $# -lt 2 || -z "$2" ]]; then
    printf 'Missing value for --config.\n' >&2
    usage >&2
    exit 2
  fi
  if [[ $# -gt 2 ]]; then
    printf 'Unexpected argument: %s\n' "$3" >&2
    usage >&2
    exit 2
  fi
  CONFIG_FILE="$2"
fi

SCRIPT_DIRECTORY="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "${SCRIPT_DIRECTORY}/.." && pwd)"
cd "${REPOSITORY_ROOT}"

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  printf 'Configuration file is unavailable: %s\n' "${CONFIG_FILE}" >&2
  exit 1
fi

if [[ "${PYTHON_BIN}" == */* ]]; then
  if [[ ! -x "${PYTHON_BIN}" ]]; then
    printf 'Python interpreter is unavailable: %s\n' "${PYTHON_BIN}" >&2
    exit 1
  fi
elif ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  printf 'Python interpreter is unavailable: %s\n' "${PYTHON_BIN}" >&2
  exit 1
fi

run_json() {
  "${PYTHON_BIN}" "$@" | "${PYTHON_BIN}" -m json.tool
}

case "${COMMAND}" in
  start)
    printf 'Starting the rebuild coordinator; it performs the authoritative startup cleanup preflight.\n' >&2
    run_json scripts/rebuild_daily_azure_environment.py \
      --config "${CONFIG_FILE}" \
      --live \
      --json
    ;;
  inspect)
    printf 'Inspecting cleanup targets; this operation is read-only.\n' >&2
    run_json scripts/cleanup_daily_azure_environment.py \
      --config "${CONFIG_FILE}" \
      --inspect \
      --live \
      --json
    ;;
  stop)
    printf 'Warning: this is the explicit, default-no, destructive end-of-day cleanup workflow.\n' >&2
    run_json scripts/cleanup_daily_azure_environment.py \
      --config "${CONFIG_FILE}" \
      --cleanup \
      --live \
      --json
    ;;
  check)
    printf 'Running offline cleanup and rebuild contract checks; no Azure or HTTP calls are made.\n' >&2
    run_json scripts/cleanup_daily_azure_environment.py \
      --config "${CONFIG_FILE}" \
      --check \
      --json
    run_json scripts/rebuild_daily_azure_environment.py \
      --config "${CONFIG_FILE}" \
      --check \
      --json
    ;;
esac
