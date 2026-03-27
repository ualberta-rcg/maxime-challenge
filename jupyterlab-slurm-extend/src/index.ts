import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';

import { IStatusBar } from '@jupyterlab/statusbar';
import { Dialog, showDialog } from '@jupyterlab/apputils';
import { URLExt } from '@jupyterlab/coreutils';
import { ServerConnection } from '@jupyterlab/services';
import { Widget } from '@lumino/widgets';
import { Poll } from '@lumino/polling';

const PLUGIN_ID = 'jupyterlab-slurm-extend:plugin';
const API_NAMESPACE = 'jupyterlab-slurm-extend';
const POLL_INTERVAL = 30_000;
const EXTEND_THRESHOLD = 3600;

interface IJobStatus {
  job_id?: string;
  job_name?: string;
  state?: string;
  time_limit?: string;
  time_limit_secs?: number | null;
  run_time?: string;
  run_time_secs?: number | null;
  remaining_secs?: number | null;
  partition?: string;
  nodes?: string;
  extend_enabled?: boolean;
  extend_minutes?: number;
  error?: string;
}

interface IExtendResult {
  success: boolean;
  message: string;
}

function makeSettings(): ServerConnection.ISettings {
  return ServerConnection.makeSettings();
}

async function fetchStatus(): Promise<IJobStatus> {
  const settings = makeSettings();
  const url = URLExt.join(settings.baseUrl, API_NAMESPACE, 'status');
  const resp = await ServerConnection.makeRequest(url, {}, settings);
  if (!resp.ok) {
    return { error: `Server returned ${resp.status}` };
  }
  return resp.json();
}

async function requestExtend(): Promise<IExtendResult> {
  const settings = makeSettings();
  const url = URLExt.join(settings.baseUrl, API_NAMESPACE, 'extend');
  const resp = await ServerConnection.makeRequest(
    url,
    { method: 'POST' },
    settings
  );
  return resp.json();
}

function formatTime(secs: number | null | undefined): string {
  if (secs == null) return '--:--:--';
  const s = Math.max(0, Math.round(secs));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const hms =
    String(h).padStart(2, '0') +
    ':' +
    String(m).padStart(2, '0') +
    ':' +
    String(sec).padStart(2, '0');
  return d > 0 ? `${d}d ${hms}` : hms;
}

/**
 * Status bar widget showing Slurm job time remaining.
 */
class SlurmTimeWidget extends Widget {
  private _text: HTMLSpanElement;
  private _remaining: number | null = null;
  private _totalLimit: number | null = null;
  private _extendEnabled = false;
  private _jobId: string | null = null;
  private _state: string | null = null;
  private _jobName: string | null = null;
  private _extendMinutes = 60;
  private _tickTimer: ReturnType<typeof setInterval> | null = null;

  constructor() {
    super();
    this.addClass('jp-SlurmExtend-status');
    this.node.title = 'Slurm job time remaining (click for details)';

    const icon = document.createElement('span');
    icon.className = 'jp-SlurmExtend-icon';
    icon.textContent = '\u23F1';
    this.node.appendChild(icon);

    this._text = document.createElement('span');
    this._text.className = 'jp-SlurmExtend-text';
    this._text.textContent = 'Slurm: --:--:--';
    this.node.appendChild(this._text);

    this.node.style.cursor = 'pointer';
    this.node.addEventListener('click', () => {
      void this._showDialog();
    });

    this._tickTimer = setInterval(() => this._tick(), 1000);
  }

  dispose(): void {
    if (this._tickTimer) {
      clearInterval(this._tickTimer);
    }
    super.dispose();
  }

  applyStatus(data: IJobStatus): void {
    if (data.error) {
      this._text.textContent = 'Slurm: N/A';
      this.node.title = data.error;
      this._setUrgency('none');
      return;
    }
    this._jobId = data.job_id ?? null;
    this._jobName = data.job_name ?? null;
    this._state = data.state ?? null;
    this._remaining =
      data.remaining_secs != null
        ? Math.max(0, Math.round(data.remaining_secs))
        : null;
    this._totalLimit = data.time_limit_secs ?? null;
    this._extendEnabled = !!data.extend_enabled;
    this._extendMinutes = data.extend_minutes ?? 60;
    this._updateDisplay();
  }

  private _tick(): void {
    if (this._remaining != null && this._remaining > 0) {
      this._remaining--;
      if (this._remaining < EXTEND_THRESHOLD) {
        this._extendEnabled = true;
      }
      this._updateDisplay();
    }
  }

  private _updateDisplay(): void {
    const r = this._remaining;
    this._text.textContent = `Slurm: ${formatTime(r)}`;

    if (r == null) {
      this._setUrgency('none');
    } else if (r <= 900) {
      this._setUrgency('danger');
    } else if (r <= 3600) {
      this._setUrgency('warning');
    } else {
      this._setUrgency('normal');
    }
  }

  private _setUrgency(level: 'none' | 'normal' | 'warning' | 'danger'): void {
    this.node.classList.remove(
      'jp-SlurmExtend-normal',
      'jp-SlurmExtend-warning',
      'jp-SlurmExtend-danger'
    );
    if (level !== 'none') {
      this.node.classList.add(`jp-SlurmExtend-${level}`);
    }
  }

  private async _showDialog(): Promise<void> {
    const body = document.createElement('div');
    body.className = 'jp-SlurmExtend-dialog';

    const addRow = (label: string, value: string): void => {
      const row = document.createElement('div');
      row.className = 'jp-SlurmExtend-row';
      row.innerHTML = `<strong>${label}:</strong> <span>${value}</span>`;
      body.appendChild(row);
    };

    addRow('Job ID', this._jobId ?? 'N/A');
    addRow('Job Name', this._jobName ?? 'N/A');
    addRow('State', this._state ?? 'N/A');
    addRow('Time Remaining', formatTime(this._remaining));
    addRow('Time Limit', formatTime(this._totalLimit));

    if (this._totalLimit && this._remaining != null) {
      const pct = Math.min(
        100,
        ((this._totalLimit - this._remaining) / this._totalLimit) * 100
      );
      const bar = document.createElement('div');
      bar.className = 'jp-SlurmExtend-progress';
      const barColor =
        this._remaining <= 900
          ? '#dc3545'
          : this._remaining <= 3600
            ? '#ffc107'
            : '#0d6efd';
      bar.innerHTML = `
        <div style="background:#e9ecef;border-radius:4px;height:8px;margin:8px 0">
          <div style="background:${barColor};width:${pct.toFixed(1)}%;height:100%;border-radius:4px;transition:width .3s"></div>
        </div>`;
      body.appendChild(bar);
    }

    if (!this._extendEnabled) {
      const hint = document.createElement('p');
      hint.style.cssText =
        'color:#6c757d;font-size:0.85em;margin-top:12px;text-align:center';
      if (this._remaining != null && this._remaining > EXTEND_THRESHOLD) {
        const mins = Math.ceil((this._remaining - EXTEND_THRESHOLD) / 60);
        hint.textContent = `Extend available in ~${mins} min (when < 1 hr remains)`;
      } else {
        hint.textContent = 'Extend available when less than 1 hour remains';
      }
      body.appendChild(hint);
    }

    const bodyWidget = new Widget({ node: body });

    const buttons = this._extendEnabled
      ? [
          Dialog.cancelButton({ label: 'Close' }),
          Dialog.okButton({
            label: `Extend +${this._extendMinutes} min`,
            caption: 'Add time to your Slurm job'
          })
        ]
      : [Dialog.okButton({ label: 'Close' })];

    const result = await showDialog({
      title: 'Slurm Job Status',
      body: bodyWidget,
      buttons
    });

    if (this._extendEnabled && result.button.accept && result.button.label !== 'Close') {
      const extResult = await requestExtend();
      await showDialog({
        title: extResult.success ? 'Job Extended' : 'Extension Failed',
        body: extResult.message,
        buttons: [Dialog.okButton({ label: 'OK' })]
      });
    }
  }
}

const plugin: JupyterFrontEndPlugin<void> = {
  id: PLUGIN_ID,
  description: 'Monitor Slurm job time and extend wall-time from JupyterLab',
  autoStart: true,
  optional: [IStatusBar],
  activate: (app: JupyterFrontEnd, statusBar: IStatusBar | null) => {
    console.log('jupyterlab-slurm-extend activated');

    const widget = new SlurmTimeWidget();

    if (statusBar) {
      statusBar.registerStatusItem(PLUGIN_ID, {
        item: widget,
        align: 'left',
        rank: 100
      });
    }

    const poll = new Poll({
      auto: true,
      factory: async () => {
        const data = await fetchStatus();
        widget.applyStatus(data);
        return data;
      },
      frequency: { interval: POLL_INTERVAL, backoff: true },
      name: 'slurm-extend:poll'
    });

    app.restored.then(() => {
      void poll.start();
    });
  }
};

export default plugin;
