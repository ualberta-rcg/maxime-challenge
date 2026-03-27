# Slurm Job Extend — OOD + JupyterLab

Two implementations of the **Extend Session** button for Slurm jobs:

1. **Open OnDemand integration** (`jupyter_app/`, `dashboard_config/`) —
   adds an extend widget to OOD session cards. For clusters running OOD 4.1+.
2. **JupyterLab extension** (`jupyterlab-slurm-extend/`) —
   a native JupyterLab plugin with a status bar countdown timer and extend
   dialog. For clusters where OOD is not available (e.g. Compute Quebec) and
   JupyterLab runs behind JupyterHub.

Both share the same `extend_job.sh` sudo wrapper for the actual `scontrol`
call. See each subdirectory's README for deployment details.

Built for **Alliance Canada** clusters (Eureka, Narval, etc.).

---

## Background

Maxime Boissonneault challenged us to build a mechanism where OOD users can
extend their running interactive sessions without leaving the dashboard.
The core difficulty is that **Slurm does not allow regular users to modify
`TimeLimit` on their own jobs** — `scontrol update` returns
"Access/permission denied". This project solves that with a privileged sudo
wrapper, an OOD dashboard API initializer, and a session-card widget.

---

## Repository layout

```
maxime-challenge/
├── README.md                                  # This file
├── requirements.txt                           # Python deps (Flask) for standalone app
├── .gitignore
│
│   ── OOD Integration (the main deliverable) ──────────────
│
├── jupyter_app/                               # Eureka's Jupyter OOD batch-connect app
│   ├── info.html.erb                          # ** NEW — extend widget on session card **
│   ├── view.html.erb                          # "Connect to Jupyter" button
│   ├── form.yml.erb                           # Launch form (CPUs, GPUs, memory, hours)
│   ├── form.js                                # Client-side form validation
│   ├── submit.yml.erb                         # Slurm sbatch parameters
│   ├── manifest.yml                           # App metadata
│   └── template/                              # Job scripts
│       ├── before.sh.erb                      # Port allocation, Jupyter config
│       ├── script.sh.erb                      # Launches jupyter lab
│       └── after.sh.erb                       # Waits for server readiness
│
├── dashboard_config/
│   └── initializers/
│       └── job_extend.rb                      # ** NEW — Rails routes for extend API **
│
├── extend_job.sh                              # ** NEW — privileged sudo wrapper **
│
│   ── JupyterLab Extension (for non-OOD clusters) ───────
│
├── jupyterlab-slurm-extend/                   # ** NEW — JupyterLab plugin **
│   ├── src/index.ts                           #   Frontend: status bar + extend dialog
│   ├── style/base.css                         #   Widget styling
│   ├── jupyterlab_slurm_extend/
│   │   ├── __init__.py                        #   Extension entry points
│   │   └── handlers.py                        #   Server API (squeue/scontrol)
│   ├── package.json                           #   npm / JupyterLab metadata
│   ├── pyproject.toml                         #   Python build config
│   └── README.md                              #   Install & deploy instructions
│
│   ── Standalone Flask App (bonus / testing) ──────────────
│
├── app.py                                     # Flask web server (full-page monitor)
├── templates/
│   └── index.html                             # Standalone UI with SVG countdown ring
└── static/                                    # (reserved for future static assets)
```

---

## Architecture

There are three new components that work together:

```
 ┌─────────────────────────────────────────────────────────────────┐
 │  Browser — OOD "My Interactive Sessions" page                   │
 │                                                                 │
 │  ┌──────────────────────────────────────────────────────────┐   │
 │  │  Session Card: Jupyter Lab (Job 1234)                    │   │
 │  │                                                          │   │
 │  │  Status: Running                  Time: 00:42:17         │   │
 │  │  ████████████████░░░░░░░░ 65%                            │   │
 │  │  Elapsed: 01:17:43            Limit: 02:00:00            │   │
 │  │                                                          │   │
 │  │  [ Extend Session (+60 min) ]   ← info.html.erb widget  │   │
 │  │  "Click to add 60 minutes to your job"                   │   │
 │  │                                                          │   │
 │  │  [ Connect to Jupyter ]          ← view.html.erb         │   │
 │  └──────────────────────────────────────────────────────────┘   │
 │       │ polls GET /slurm/job_time every 30s                     │
 │       │ sends POST /slurm/extend_job on click                   │
 └───────┼─────────────────────────────────────────────────────────┘
         │
         ▼
 ┌─────────────────────────────────────────────────────────────────┐
 │  OOD Dashboard (Rails app, PUN — runs as the logged-in user)    │
 │                                                                 │
 │  job_extend.rb initializer provides:                            │
 │    GET  /slurm/job_time   → squeue -j <id> → JSON              │
 │    POST /slurm/extend_job → validates ownership                 │
 │                            → sudo /usr/local/sbin/extend_job.sh │
 └───────┼─────────────────────────────────────────────────────────┘
         │
         ▼
 ┌─────────────────────────────────────────────────────────────────┐
 │  extend_job.sh (runs as root via sudo)                          │
 │                                                                 │
 │  1. Validate job_id is numeric                                  │
 │  2. Validate minutes is 15–120                                  │
 │  3. Verify SUDO_USER == job owner (via squeue)                  │
 │  4. scontrol update JobId=<id> TimeLimit=+<minutes>             │
 │  5. Log to syslog                                               │
 └─────────────────────────────────────────────────────────────────┘
```

### Why sudo?

Slurm's default configuration does not permit regular users to modify
`TimeLimit` on their own jobs. We tested this on Eureka and confirmed:

```
$ scontrol update JobId=1978 TimeLimit=10:00
Access/permission denied for job 1978

$ sudo scontrol update JobId=1978 TimeLimit=10:00
(success)
```

The `extend_job.sh` wrapper runs via sudo so it can call `scontrol` as root,
but it enforces strict ownership and input validation before doing so.

---

## Security model

There are **two independent layers** of authorization:

### Layer 1 — Rails initializer (`job_extend.rb`)

- The OOD PUN (Per-User Nginx) runs each user's dashboard as their own
  Unix user. User B cannot see or interact with User A's session cards.
- The initializer calls `squeue -j <job_id> -h -o "%u"` and compares the
  result to `ENV["USER"]`. If they don't match, the request is rejected
  with "Access denied" before sudo is ever invoked.

### Layer 2 — Privileged wrapper (`extend_job.sh`)

- Validates `job_id` is strictly numeric (regex `^[0-9]+$`).
- Validates `minutes` is numeric and within bounds (15–120 by default).
- Reads `$SUDO_USER` (set automatically by sudo) and compares it to the
  job owner from `squeue`. Rejects with a `DENIED` log entry if they
  don't match.
- Every attempt (success or failure) is logged to syslog via `logger -t extend_job`.

### What's logged

```
Mar 26 22:30:42 eureka-login1 extend_job: EXTEND: user 'alice' extending job 1984 by +60m
Mar 26 22:30:42 eureka-login1 extend_job: OK: job 1984 extended by 60 minutes
Mar 26 22:31:15 eureka-login1 extend_job: DENIED: user 'bob' attempted to extend job 1984 owned by 'alice'
```

### Test results

| Test | Input | Result |
|---|---|---|
| Non-numeric job_id | `abc` | Rejected: "job_id must be numeric" |
| Minutes out of bounds | `999` | Rejected: "must be between 15 and 120" |
| Wrong user | `SUDO_USER=bob`, job owned by alice | Rejected: "DENIED" |
| Valid extend | Own job, < 1 hr remaining | Success: TimeLimit updated |

---

## Component details

### 1. `jupyter_app/info.html.erb` — Session card widget

OOD's `info.html.erb` hook renders custom HTML on every session card for the
app. OOD provides these variables to the template: `id`, `cluster_id`,
`job_id`, `created_at`.

The widget shows:
- **Time remaining** badge — color-coded: blue (> 1 hr), amber (< 1 hr), red (< 15 min)
- **Progress bar** — elapsed fraction of the total wall-time
- **Extend button** — disabled/greyed when more than 1 hour remains; activates below 1 hour
- **Hint text** — shows a countdown to when the button will become available

The JavaScript:
- Polls `GET /pun/sys/dashboard/slurm/job_time?job_id=<job_id>` every 30 seconds
- Counts down locally (1-second ticks) between polls for smooth display
- On button click, sends `POST /pun/sys/dashboard/slurm/extend_job` with the
  CSRF token from the OOD dashboard's `<meta>` tag
- Shows inline success/error feedback using Bootstrap alert classes

All DOM element IDs are scoped by `job_id` so multiple session cards on the
same page don't conflict.

### 2. `dashboard_config/initializers/job_extend.rb` — API routes

A Rails initializer loaded by the OOD dashboard at startup. Follows the same
pattern as the existing Eureka initializers (`slurm_extension.rb`, etc.).

Defines:
- **`SlurmJobExtend` module** — helper methods for querying Slurm and extending jobs
  - `parse_duration(str)` — parses Slurm time formats (`D-HH:MM:SS`, `HH:MM:SS`, `MM:SS`) to seconds
  - `job_time(job_id, user)` — runs `squeue`, validates ownership, returns JSON hash
  - `extend_job(job_id, user)` — validates eligibility, calls `sudo extend_job.sh`, returns result

- **`SlurmExtendController`** — inherits from `ApplicationController` (gets CSRF protection for free)
  - `GET /slurm/job_time` — accepts `?job_id=`, returns time info as JSON
  - `POST /slurm/extend_job` — accepts `job_id` param, runs the extension

- **Routes** — appended to the dashboard's route table via `Rails.application.routes.append`

Configurable constants at the top of the file:
```ruby
EXTEND_SCRIPT = "/usr/local/sbin/extend_job.sh"
EXTEND_MINUTES = 60
```

### 3. `extend_job.sh` — Privileged wrapper

A bash script intended to be deployed as `/usr/local/sbin/extend_job.sh` and
called via `sudo`. It is the only component that runs as root.

Configurable constants:
```bash
MIN_MINUTES=15    # minimum allowed extension
MAX_MINUTES=120   # maximum allowed extension
```

---

## Deployment

### Prerequisites

- Open OnDemand 4.1 with PUN (Per-User Nginx)
- Slurm with `squeue` and `scontrol` available on the OOD login node
- sudo configured for OOD users (see step 2)

### Step 1 — Deploy the privileged wrapper

```bash
sudo install -o root -g root -m 755 extend_job.sh /usr/local/sbin/extend_job.sh
```

### Step 2 — Sudoers rule

If your cluster does not already grant broad sudo access, add a targeted rule:

```bash
cat <<'EOF' | sudo tee /etc/sudoers.d/ood-extend-job
# Allow all users to extend their own Slurm jobs via OOD
ALL ALL=(root) NOPASSWD: /usr/local/sbin/extend_job.sh
EOF
sudo chmod 440 /etc/sudoers.d/ood-extend-job
```

On Eureka this is already covered by the existing `(ALL) NOPASSWD: ALL` rule.

### Step 3 — Deploy the dashboard initializer

```bash
sudo cp dashboard_config/initializers/job_extend.rb \
  /etc/ood/config/apps/dashboard/initializers/job_extend.rb
```

### Step 4 — Deploy the session card widget

```bash
sudo cp jupyter_app/info.html.erb \
  /var/www/ood/apps/sys/jupyter_app/info.html.erb
```

To add this to other interactive apps (RStudio, VS Code, etc.), copy the same
`info.html.erb` into their app directories. The widget is generic — it only
uses the `job_id` variable which OOD provides to every batch-connect app.

### Step 5 — Restart OOD

```bash
# Full restart (all users)
sudo systemctl restart ondemand

# Or per-user PUN restart
sudo /usr/sbin/nginx_stage nginx_clean -u <username>
```

The user needs to reload their "My Interactive Sessions" page to see the widget.

---

## Configuration reference

| What | Where | Default | Notes |
|---|---|---|---|
| Extension amount (minutes) | `job_extend.rb` line 8 | 60 | Also shown in button label |
| Extension bounds (min/max) | `extend_job.sh` lines 17–18 | 15–120 | Rejects outside this range |
| Wrapper script path | `job_extend.rb` line 7 | `/usr/local/sbin/extend_job.sh` | Must match sudo rule |
| Poll interval | `info.html.erb` line 44 | 30000 ms | How often JS fetches Slurm status |
| Extend threshold | `job_extend.rb` line 61 | 3600 s (1 hr) | Button enables below this |

---

## Standalone Flask app (bonus)

`app.py` + `templates/index.html` provide a standalone full-page Slurm job
monitor with an SVG countdown ring. This was the initial prototype and remains
useful for testing or running behind JupyterHub's server-proxy.

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
SLURM_JOB_ID=1234 python app.py
# → http://localhost:8090
```

It uses the same `extend_job.sh` wrapper via sudo. Set `EXTEND_USE_SUDO=0` to
disable sudo (only works if the user has Slurm admin rights).

| Env var | Default | Purpose |
|---|---|---|
| `SLURM_JOB_ID` | (none) | Job to monitor; also accepts `?job_id=` in URL |
| `MONITOR_PORT` | 8090 | Port to bind |
| `EXTEND_SCRIPT` | `/usr/local/sbin/extend_job.sh` | Path to wrapper |
| `EXTEND_MINUTES` | 60 | Minutes per extension |
| `EXTEND_USE_SUDO` | 1 | Set to 0 to call wrapper without sudo |

---

## Known limitations and future work

- **Slurm permissions**: The sudo wrapper is necessary because Slurm's default
  config denies users from modifying `TimeLimit`. If your site configures Slurm
  to allow this (e.g. via a custom plugin or `AllowedScontrolUpdate`), you
  could simplify by removing the sudo layer.

- **Single extension amount**: Currently hardcoded to 60 minutes. Could be made
  user-configurable (dropdown or input field on the widget).

- **No maximum total extensions**: A user can click extend repeatedly. To limit
  this, add a counter in the wrapper script (e.g. a file in the job's working
  directory) or enforce a maximum `TimeLimit` in the wrapper.

- **Other interactive apps**: The `info.html.erb` widget works for any OOD
  batch-connect app — just copy it into the app's directory. The initializer
  and wrapper are global and don't need per-app changes.

- **OOD dashboard session card refresh**: OOD's session page may also refresh
  independently. The widget's polling is additive to OOD's own refreshes.

---

## Context for next session

- **Cluster**: Eureka (PAICE, University of Alberta), OOD at `eureka.paice-ua.com`
- **OOD version**: 4.1
- **Eureka OOD config repo**: `git@github.com:ualberta-rcg/eureka-ood.git` (read-only deploy key on this machine)
- **This repo**: `git@github.com:ualberta-rcg/maxime-challenge.git`
- **SSH key for push**: `~/.ssh/id_ed25519` (the env var `GIT_SSH_COMMAND` is globally set to use `archaeology-deploy-key` which is read-only for this repo, so pushes need: `GIT_SSH_COMMAND="ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes" git push origin main`)
- **Slurm**: squeue/scontrol at `/usr/bin/`, configless mode
- **sudo**: `(ALL) NOPASSWD: ALL` for this user; `extend_job.sh` deployed to `/usr/local/sbin/`
- **Python**: 3.11 via CVMFS, Flask in `./venv/`
- **Tested**: wrapper script validates all inputs, rejects wrong user, extends correctly; Flask app end-to-end confirmed working
- **Not yet tested in production OOD**: The Rails initializer and `info.html.erb` have not been deployed to the live OOD instance — that's the next step
