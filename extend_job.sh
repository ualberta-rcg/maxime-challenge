#!/usr/bin/env bash
# extend_job.sh — extend a Slurm job's wall-time.
#
# Called by the monitor web server when the user clicks "Extend".
# Customize this for your site's policies (e.g. max extensions, logging).
#
# Usage: ./extend_job.sh <job_id> <minutes>

set -euo pipefail

JOB_ID="${1:?Usage: $0 <job_id> <minutes>}"
MINUTES="${2:-60}"

echo "Requesting +${MINUTES}m for job ${JOB_ID} ..."
scontrol update "JobId=${JOB_ID}" "TimeLimit=+${MINUTES}"
echo "Done."
