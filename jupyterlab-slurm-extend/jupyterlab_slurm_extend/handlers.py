"""
Tornado request handlers for the Slurm job extend server extension.

Runs inside the Jupyter server process on the compute node.
SLURM_JOB_ID is read from the environment (set automatically by Slurm).
"""

import json
import os
import re
import subprocess

import tornado.web
from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join

EXTEND_SCRIPT = os.environ.get("EXTEND_SCRIPT", "/usr/local/sbin/extend_job.sh")
EXTEND_MINUTES = int(os.environ.get("EXTEND_MINUTES", "60"))
USE_SUDO = os.environ.get("EXTEND_USE_SUDO", "1") == "1"


def _run(cmd, timeout=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _parse_duration(s):
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


def _get_job_status(job_id):
    try:
        r = _run(["squeue", "-j", str(job_id), "-h",
                   "-o", "%i|%j|%T|%l|%M|%L|%P|%N"])
        if r.returncode != 0 or not r.stdout.strip():
            return {"error": f"Job {job_id} not found or completed"}

        cols = r.stdout.strip().split("|")
        if len(cols) < 6:
            return {"error": "Unexpected squeue output"}

        time_limit_s = _parse_duration(cols[3])
        run_time_s = _parse_duration(cols[4])
        remaining_s = _parse_duration(cols[5])

        if remaining_s is None and time_limit_s and run_time_s:
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
            "partition": cols[6] if len(cols) > 6 else "N/A",
            "nodes": cols[7] if len(cols) > 7 else "N/A",
            "extend_enabled": remaining_s is not None and remaining_s < 3600,
            "extend_minutes": EXTEND_MINUTES,
        }
    except subprocess.TimeoutExpired:
        return {"error": "Slurm query timed out"}
    except Exception as e:
        return {"error": str(e)}


def _extend_job(job_id):
    try:
        cmd = (["sudo", EXTEND_SCRIPT, str(job_id), str(EXTEND_MINUTES)]
               if USE_SUDO
               else [EXTEND_SCRIPT, str(job_id), str(EXTEND_MINUTES)])
        r = _run(cmd, timeout=30)
        if r.returncode == 0:
            return {"success": True,
                    "message": f"Job extended by {EXTEND_MINUTES} minutes"}
        return {"success": False,
                "message": r.stderr.strip() or r.stdout.strip() or "Extension failed"}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "Extension request timed out"}
    except Exception as e:
        return {"success": False, "message": str(e)}


class StatusHandler(APIHandler):
    """GET /jupyterlab-slurm-extend/status — job time remaining."""

    @tornado.web.authenticated
    def get(self):
        job_id = os.environ.get("SLURM_JOB_ID")
        if not job_id:
            self.finish(json.dumps({"error": "SLURM_JOB_ID not set — not inside a Slurm job"}))
            return
        self.finish(json.dumps(_get_job_status(job_id)))


class ExtendHandler(APIHandler):
    """POST /jupyterlab-slurm-extend/extend — request a time extension."""

    @tornado.web.authenticated
    def post(self):
        job_id = os.environ.get("SLURM_JOB_ID")
        if not job_id:
            self.finish(json.dumps({"success": False, "message": "Not inside a Slurm job"}))
            return

        status = _get_job_status(job_id)
        if "error" in status:
            self.finish(json.dumps({"success": False, "message": status["error"]}))
            return
        if not status.get("extend_enabled"):
            self.finish(json.dumps({
                "success": False,
                "message": "Extension only available when less than 1 hour remains"
            }))
            return

        self.finish(json.dumps(_extend_job(job_id)))


def setup_handlers(web_app):
    host_pattern = ".*$"
    base_url = web_app.settings["base_url"]
    route = url_path_join(base_url, "jupyterlab-slurm-extend")
    handlers = [
        (url_path_join(route, "status"), StatusHandler),
        (url_path_join(route, "extend"), ExtendHandler),
    ]
    web_app.add_handlers(host_pattern, handlers)
