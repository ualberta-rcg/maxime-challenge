# Slurm Job Monitor

A lightweight web server that displays time remaining for a running Slurm job
and lets users extend it when the deadline approaches. Designed to run behind
**JupyterHub** or **Open OnDemand** reverse proxies on Alliance Canada clusters.

## Features

- **Live countdown** — queries Slurm every 15 seconds, smooth client-side tick in between.
- **SVG ring + progress bar** — colour shifts from blue → amber → red as time runs out.
- **Extend button** — greyed out until less than 1 hour remains, then calls
  `scontrol update JobId=… TimeLimit=+60` (or a custom script) to add time.
- **Proxy-friendly** — uses relative URLs so it works behind any path prefix.
- **Zero JavaScript dependencies** — vanilla JS, no build step.

## Quick start

```bash
# inside a Slurm job (SLURM_JOB_ID is auto-detected)
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python app.py
# → http://localhost:8090
```

Or pass a specific job ID:

```bash
python app.py 12345
# → monitors job 12345
```

## Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `SLURM_JOB_ID` | (auto) | Job to monitor |
| `MONITOR_PORT` | `8090` | Port the server listens on |
| `EXTEND_MINUTES` | `60` | Minutes added per extension click |
| `EXTEND_SCRIPT` | _(none)_ | Path to a custom script called as `script <job_id> <minutes>`. Falls back to `scontrol update`. |

## Running behind JupyterHub / Open OnDemand

The server binds to `0.0.0.0:<MONITOR_PORT>`. Both JupyterHub (via
`jupyter-server-proxy`) and Open OnDemand can reverse-proxy to that port on
the compute node. The frontend uses only relative URLs, so no extra path
configuration is needed.

**JupyterHub example** (jupyter-server-proxy entry):

```python
# jupyter_server_config.py
c.ServerProxy.servers = {
    "slurm-monitor": {
        "command": ["python", "/path/to/app.py"],
        "port": 8090,
        "timeout": 30,
        "launcher_entry": {
            "title": "Slurm Job Monitor",
        },
    },
}
```

**Open OnDemand example** — add an interactive-app `form.yml` / `submit.yml`
that starts `app.py` alongside the main application, then proxy to the port
in your `view.html.erb`.

## Custom extend script

If your site restricts direct `scontrol update`, point `EXTEND_SCRIPT` to a
wrapper that enforces local policy (max extensions, logging, etc.):

```bash
export EXTEND_SCRIPT=/path/to/extend_job.sh
python app.py
```

The script receives two positional arguments: `<job_id> <minutes>`.

## Screenshots

Launch the server, open the URL, and pass `?job_id=XXXX` if `SLURM_JOB_ID`
is not set:

```
http://localhost:8090/?job_id=1977
```

## License

MIT
