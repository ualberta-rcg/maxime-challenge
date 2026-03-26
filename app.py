#!/usr/bin/env python3
"""
Slurm Job Monitor — web server for monitoring and extending Slurm jobs.

Designed to run behind JupyterHub or Open OnDemand proxy on
Alliance Canada clusters.

Usage:
    python app.py [JOB_ID]

Environment variables:
    SLURM_JOB_ID     — job to monitor (auto-detected inside a job)
    EXTEND_SCRIPT    — path to custom extension script (optional)
    EXTEND_MINUTES   — minutes to add per extension (default: 60)
    MONITOR_PORT     — port to listen on (default: 8090)
"""

import logging
import os
import subprocess
import sys

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SLURM_JOB_ID = os.environ.get("SLURM_JOB_ID")
EXTEND_SCRIPT = os.environ.get("EXTEND_SCRIPT", "/usr/local/sbin/extend_job.sh")
EXTEND_MINUTES = int(os.environ.get("EXTEND_MINUTES", "60"))
PORT = int(os.environ.get("MONITOR_PORT", "8090"))
USE_SUDO = os.environ.get("EXTEND_USE_SUDO", "1") == "1"


def _parse_duration(s):
    """Parse Slurm duration (D-HH:MM:SS | HH:MM:SS | MM:SS) → seconds."""
    if not s or s in ("N/A", "UNLIMITED", "INVALID"):
        return None
    days = 0
    if "-" in s:
        day_part, s = s.split("-", 1)
        days = int(day_part)
    parts = s.split(":")
    if len(parts) == 3:
        h, m, sec = parts
    elif len(parts) == 2:
        h, m, sec = 0, parts[0], parts[1]
    else:
        return None
    return days * 86400 + int(h) * 3600 + int(m) * 60 + int(sec)


def _fmt(total):
    """Format seconds → human string."""
    if total is None:
        return "N/A"
    d, rem = divmod(int(total), 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    return f"{d}d {h:02d}:{m:02d}:{s:02d}" if d else f"{h:02d}:{m:02d}:{s:02d}"


def _run(cmd, timeout=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def get_job_info(job_id):
    """Return a dict with everything the frontend needs."""
    try:
        r = _run(["squeue", "-j", str(job_id), "-h",
                   "-o", "%i|%j|%T|%l|%M|%L|%P|%N|%D|%C|%S|%e|%b"])
        if r.returncode != 0 or not r.stdout.strip():
            # Job may have finished — try sacct
            r2 = _run(["sacct", "-j", str(job_id), "--format=JobID,JobName,State,Elapsed,Timelimit,Partition,NodeList,AllocCPUS",
                        "-n", "-P", "--delimiter=|"])
            if r2.returncode == 0 and r2.stdout.strip():
                line = r2.stdout.strip().split("\n")[0]
                parts = line.split("|")
                return {
                    "job_id": parts[0] if len(parts) > 0 else str(job_id),
                    "job_name": parts[1] if len(parts) > 1 else "N/A",
                    "state": parts[2] if len(parts) > 2 else "UNKNOWN",
                    "run_time": parts[3] if len(parts) > 3 else "N/A",
                    "time_limit": parts[4] if len(parts) > 4 else "N/A",
                    "partition": parts[5] if len(parts) > 5 else "N/A",
                    "nodes": parts[6] if len(parts) > 6 else "N/A",
                    "num_cpus": parts[7] if len(parts) > 7 else "N/A",
                    "num_nodes": "N/A",
                    "remaining_secs": 0,
                    "remaining_formatted": "00:00:00",
                    "time_limit_secs": 0,
                    "run_time_secs": 0,
                    "start_time": "N/A",
                    "end_time": "N/A",
                    "tres": "N/A",
                    "extend_enabled": False,
                    "extend_minutes": EXTEND_MINUTES,
                }
            return {"error": f"Job {job_id} not found"}

        cols = r.stdout.strip().split("|")
        if len(cols) < 12:
            return {"error": "Unexpected squeue output"}

        time_limit_s = _parse_duration(cols[3])
        run_time_s = _parse_duration(cols[4])
        remaining_s = _parse_duration(cols[5])

        if remaining_s is None and time_limit_s is not None and run_time_s is not None:
            remaining_s = max(0, time_limit_s - run_time_s)

        return {
            "job_id": cols[0],
            "job_name": cols[1],
            "state": cols[2],
            "time_limit": cols[3],
            "time_limit_secs": time_limit_s,
            "run_time": cols[4],
            "run_time_secs": run_time_s,
            "remaining_secs": remaining_s,
            "remaining_formatted": _fmt(remaining_s),
            "partition": cols[6],
            "nodes": cols[7],
            "num_nodes": cols[8],
            "num_cpus": cols[9],
            "start_time": cols[10],
            "end_time": cols[11],
            "tres": cols[12] if len(cols) > 12 else "N/A",
            "extend_enabled": remaining_s is not None and remaining_s < 3600,
            "extend_minutes": EXTEND_MINUTES,
        }
    except subprocess.TimeoutExpired:
        return {"error": "Slurm query timed out"}
    except Exception as exc:
        log.exception("get_job_info failed")
        return {"error": str(exc)}


def _verify_ownership(job_id):
    """Return True if the current user owns the given job."""
    try:
        r = _run(["squeue", "-j", str(job_id), "-h", "-o", "%u"])
        owner = r.stdout.strip()
        return owner == os.environ.get("USER", "")
    except Exception:
        return False


def extend_job(job_id):
    """Extend the job via the privileged wrapper script (requires sudo).

    Regular users cannot scontrol-update TimeLimit, so this calls
    sudo /usr/local/sbin/extend_job.sh which validates ownership
    and runs the update as root.
    """
    if not _verify_ownership(job_id):
        return {"success": False, "message": "You do not own this job"}

    try:
        cmd = ["sudo", EXTEND_SCRIPT, str(job_id), str(EXTEND_MINUTES)] if USE_SUDO \
              else [EXTEND_SCRIPT, str(job_id), str(EXTEND_MINUTES)]
        r = _run(cmd, timeout=30)

        if r.returncode == 0:
            return {"success": True,
                    "message": f"Job extended by {EXTEND_MINUTES} minutes"}
        return {"success": False,
                "message": r.stderr.strip() or r.stdout.strip() or "Extension failed"}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "Extension request timed out"}
    except Exception as exc:
        log.exception("extend_job failed")
        return {"success": False, "message": str(exc)}


# ── Routes ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    job_id = request.args.get("job_id", SLURM_JOB_ID)
    return render_template("index.html", job_id=job_id, extend_minutes=EXTEND_MINUTES)


@app.route("/api/status")
def api_status():
    job_id = request.args.get("job_id", SLURM_JOB_ID)
    if not job_id:
        return jsonify({"error": "No SLURM_JOB_ID. Pass ?job_id=XXXX or set the env var."}), 400
    return jsonify(get_job_info(job_id))


@app.route("/api/extend", methods=["POST"])
def api_extend():
    job_id = request.args.get("job_id", SLURM_JOB_ID)
    if not job_id:
        return jsonify({"success": False, "message": "No job ID"}), 400

    info = get_job_info(job_id)
    if "error" in info:
        return jsonify({"success": False, "message": info["error"]}), 400
    if not info.get("extend_enabled"):
        return jsonify({"success": False,
                        "message": "Extension only available when less than 1 hour remains"}), 403

    return jsonify(extend_job(job_id))


# ── Main ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1:
        SLURM_JOB_ID = sys.argv[1]

    if not SLURM_JOB_ID:
        log.warning("No SLURM_JOB_ID detected.  Use ?job_id=XXXX in the URL "
                     "or set the SLURM_JOB_ID environment variable.")

    log.info("Slurm Job Monitor starting on port %d (job=%s)", PORT, SLURM_JOB_ID or "auto")
    app.run(host="0.0.0.0", port=PORT)
