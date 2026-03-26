# Slurm Job Extend for Open OnDemand

Add an **Extend Session** button to OOD interactive app session cards (e.g. Jupyter).
When a job has less than 1 hour of wall-time remaining, the user can click the button
to add 60 minutes via `scontrol update`.

Built for **Open OnDemand 4.1** on **Alliance Canada** clusters (Eureka / PAICE).

---

## How it works

```
Browser (OOD session card)
  │
  │  GET /slurm/job_time?job_id=1234      (polls every 30s)
  │  POST /slurm/extend_job               (on button click)
  ▼
OOD Dashboard (Rails, PUN — runs as user)
  │
  │  initializer: job_extend.rb
  │  • validates job_id is numeric
  │  • verifies the requesting user owns the job
  │  • calls: sudo /usr/local/sbin/extend_job.sh <job_id> 60
  ▼
extend_job.sh (runs as root)
  │  • re-validates ownership (SUDO_USER == job owner)
  │  • enforces min/max bounds on extension minutes
  │  • scontrol update JobId=<id> TimeLimit=+60
  ▼
Slurm
```

## Components

| File | Deploy to | Purpose |
|---|---|---|
| `jupyter_app/info.html.erb` | `/var/www/ood/apps/sys/jupyter_app/` | Extend widget on the session card |
| `dashboard_config/initializers/job_extend.rb` | `/etc/ood/config/apps/dashboard/initializers/` | API routes for job time + extend |
| `extend_job.sh` | `/usr/local/sbin/extend_job.sh` | Privileged wrapper for scontrol |

## Security

- **Users cannot extend their own jobs directly** — `scontrol update TimeLimit` requires admin privileges in default Slurm configuration.
- **Privileged wrapper** (`extend_job.sh`) runs via sudo, validates all inputs, and checks that `$SUDO_USER` matches the job owner before calling scontrol.
- **Double ownership check** — both the Rails initializer and the bash script independently verify the user owns the job.
- **Input sanitisation** — job_id must be numeric; extension minutes are bounded (15–120).
- **Logging** — every extend attempt is logged to syslog via `logger`.

## Deployment

### 1. Deploy the privileged wrapper

```bash
sudo cp extend_job.sh /usr/local/sbin/extend_job.sh
sudo chown root:root /usr/local/sbin/extend_job.sh
sudo chmod 755 /usr/local/sbin/extend_job.sh
```

### 2. Sudoers rule (recommended for production)

If your cluster does not already grant `NOPASSWD: ALL`, add a targeted rule:

```bash
# /etc/sudoers.d/ood-extend-job
ALL ALL=(root) NOPASSWD: /usr/local/sbin/extend_job.sh
```

### 3. Deploy the dashboard initializer

```bash
sudo cp dashboard_config/initializers/job_extend.rb \
  /etc/ood/config/apps/dashboard/initializers/job_extend.rb
```

### 4. Deploy the session card widget

```bash
sudo cp jupyter_app/info.html.erb \
  /var/www/ood/apps/sys/jupyter_app/info.html.erb
```

### 5. Restart OOD

```bash
sudo systemctl restart ondemand
# or per-user: sudo /usr/sbin/nginx_stage nginx_clean -u <user>
```

## Configuration

Edit constants at the top of `job_extend.rb`:

```ruby
EXTEND_SCRIPT = "/usr/local/sbin/extend_job.sh"
EXTEND_MINUTES = 60
```

Edit bounds in `extend_job.sh`:

```bash
MIN_MINUTES=15
MAX_MINUTES=120
```

## Standalone Flask app

`app.py` + `templates/index.html` provide a standalone web server that can run
behind JupyterHub or OOD proxy for monitoring and extending a single job.
Useful for testing or as an alternative to the OOD integration.

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python app.py <JOB_ID>
# → http://localhost:8090
```

## Slurm permissions note

By default, Slurm does not allow users to modify `TimeLimit` on their own jobs.
The `extend_job.sh` wrapper runs as root via sudo to bypass this. If your site
uses a custom Slurm plugin or QOS that allows user-initiated extensions, you can
modify the wrapper accordingly or call scontrol directly.

## License

MIT
