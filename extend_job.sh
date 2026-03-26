#!/usr/bin/env bash
# extend_job.sh — privileged wrapper to extend a Slurm job's wall-time.
#
# Intended to be run via sudo from the OOD dashboard.
# Deploy to /usr/local/sbin/extend_job.sh  (owned by root, mode 0755).
#
# Usage: sudo extend_job.sh <job_id> <minutes>
#
# Security:
#   - Validates job_id and minutes are strictly numeric
#   - Enforces minutes within bounds (MIN_MINUTES..MAX_MINUTES)
#   - Verifies the calling user (SUDO_USER) owns the job
#   - Logs every attempt to syslog

set -euo pipefail

MIN_MINUTES=15
MAX_MINUTES=120

log() { logger -t extend_job "$*"; echo "$*"; }

# ── input validation ────────────────────────────────────────────────
JOB_ID="${1:-}"
MINUTES="${2:-60}"

if [[ -z "$JOB_ID" ]]; then
  log "ERROR: missing job_id argument"
  exit 1
fi

if ! [[ "$JOB_ID" =~ ^[0-9]+$ ]]; then
  log "ERROR: job_id must be numeric, got '${JOB_ID}'"
  exit 1
fi

if ! [[ "$MINUTES" =~ ^[0-9]+$ ]]; then
  log "ERROR: minutes must be numeric, got '${MINUTES}'"
  exit 1
fi

if (( MINUTES < MIN_MINUTES || MINUTES > MAX_MINUTES )); then
  log "ERROR: minutes must be between ${MIN_MINUTES} and ${MAX_MINUTES}, got ${MINUTES}"
  exit 1
fi

# ── ownership check ─────────────────────────────────────────────────
CALLER="${SUDO_USER:-$USER}"
JOB_OWNER=$(squeue -j "$JOB_ID" -h -o "%u" 2>/dev/null || true)

if [[ -z "$JOB_OWNER" ]]; then
  log "ERROR: job ${JOB_ID} not found or not running"
  exit 1
fi

if [[ "$JOB_OWNER" != "$CALLER" ]]; then
  log "DENIED: user '${CALLER}' attempted to extend job ${JOB_ID} owned by '${JOB_OWNER}'"
  exit 1
fi

# ── extend ──────────────────────────────────────────────────────────
log "EXTEND: user '${CALLER}' extending job ${JOB_ID} by +${MINUTES}m"
scontrol update "JobId=${JOB_ID}" "TimeLimit=+${MINUTES}"
log "OK: job ${JOB_ID} extended by ${MINUTES} minutes"
