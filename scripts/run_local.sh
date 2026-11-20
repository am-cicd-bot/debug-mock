#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${ROOT_DIR}/.local_data"
mkdir -p "${DATA_DIR}"

export CORE_LEDGER_DB="${DATA_DIR}/core_ledger.db"
export DISPUTE_DB_PATH="${DATA_DIR}/disputes.db"
export POLICIES_DIR="${ROOT_DIR}/policies"
export CORE_LEDGER_URL="http://127.0.0.1:8081"

cleanup() {
  echo "Stopping local services..."
  kill "${LEDGER_PID:-}" "${AGENT_PID:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting core-ledger on http://127.0.0.1:8081 ..."
(
  cd "${ROOT_DIR}/services/core-ledger"
  python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8081
) &
LEDGER_PID=$!

sleep 1.5

echo "Starting dispute-agent on http://127.0.0.1:8080 ..."
(
  cd "${ROOT_DIR}/services/dispute-agent"
  python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --workers 1
) &
AGENT_PID=$!

echo "Meridian DisputeOps Workbench running at http://127.0.0.1:8080"
wait
