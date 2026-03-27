# jupyterlab-slurm-extend

A JupyterLab extension that monitors Slurm job wall-time and lets users extend
their session with a single click. Designed for Alliance Canada clusters where
JupyterLab runs on compute nodes behind JupyterHub.

## What it does

- **Status bar widget** in the JupyterLab footer shows time remaining for the
  current Slurm job, counting down in real-time.
- **Color-coded urgency**: normal (> 1 hr), amber/warning (< 1 hr),
  red/pulsing (< 15 min).
- **Click to open** a details dialog showing job info, progress bar, and an
  Extend button.
- **Extend button** is only active when less than 1 hour remains. Clicking it
  calls `scontrol update TimeLimit=+60` via the `extend_job.sh` sudo wrapper.
- **Server extension** adds two API endpoints to the Jupyter server — no
  separate web server or sidecar needed.
- Works through **JupyterHub's proxy** (including Unix socket configurations).

## Architecture

```
JupyterLab (browser)
  └── Status bar: "Slurm: 00:42:17"
       │
       │  Polls GET /jupyterlab-slurm-extend/status (every 30s)
       │  Sends POST /jupyterlab-slurm-extend/extend (on click)
       │
       │  (goes through JupyterHub proxy → compute node)
       ▼
Jupyter Server (compute node, runs as user inside Slurm job)
  └── Server extension: handlers.py
       │  reads SLURM_JOB_ID from environment
       │  calls squeue for status
       │  calls sudo extend_job.sh for extend
       ▼
Slurm (scontrol update)
```

The Jupyter server runs inside the Slurm job on the compute node, so
`SLURM_JOB_ID` and `squeue`/`scontrol` are available directly. JupyterHub's
token-based auth protects the API endpoints — no additional authentication
is needed.

## Install

### From source (development)

```bash
# Activate the JupyterLab environment
source /cvmfs/soft.computecanada.ca/easybuild/software/2023/x86-64-v3/Core/jupyterhub_node/7.2.1/bin/activate

cd jupyterlab-slurm-extend
pip install -ve .

# For development with hot reload:
jupyter labextension develop --overwrite .
jlpm watch   # in a separate terminal
```

### From built wheel

```bash
pip install jupyterlab_slurm_extend-0.1.0-py3-none-any.whl
```

### Deploy extend_job.sh

The extension needs the same `extend_job.sh` wrapper as the OOD version,
deployed on the **compute nodes** (not the login node):

```bash
sudo install -o root -g root -m 755 ../extend_job.sh /usr/local/sbin/extend_job.sh
```

And a sudoers rule on compute nodes:

```bash
echo 'ALL ALL=(root) NOPASSWD: /usr/local/sbin/extend_job.sh' | \
  sudo tee /etc/sudoers.d/ood-extend-job
```

## Configuration

Environment variables (set in the Slurm job environment):

| Variable | Default | Purpose |
|---|---|---|
| `SLURM_JOB_ID` | (auto) | Set by Slurm — the job to monitor |
| `EXTEND_SCRIPT` | `/usr/local/sbin/extend_job.sh` | Path to the wrapper |
| `EXTEND_MINUTES` | `60` | Minutes per extension |
| `EXTEND_USE_SUDO` | `1` | Set to `0` if users can scontrol directly |

## Security

- The server extension runs as the job owner inside the Slurm job.
- API endpoints are protected by JupyterHub's token authentication.
- The extend action uses `sudo extend_job.sh` which validates ownership
  and logs to syslog (see `../extend_job.sh`).
- JupyterHub can be configured to use **Unix sockets** instead of TCP ports,
  which prevents other users on the compute node from accessing the server.

## Build from source

Requires Node.js 18+ and JupyterLab 4.x:

```bash
jlpm install
jlpm build:lib
jlpm build:labextension
```

## File structure

```
jupyterlab-slurm-extend/
├── src/index.ts                    # Frontend: status bar widget + dialog
├── style/base.css                  # Widget styling
├── jupyterlab_slurm_extend/
│   ├── __init__.py                 # Extension entry points
│   └── handlers.py                 # Server API handlers (squeue/scontrol)
├── package.json                    # npm config, JupyterLab extension metadata
├── pyproject.toml                  # Python build config (hatchling)
└── tsconfig.json                   # TypeScript config
```
