# job_extend.rb — OOD dashboard initializer that adds API endpoints
# for querying Slurm job time and extending jobs.
#
# Deploy to: /etc/ood/config/apps/dashboard/initializers/job_extend.rb
# Restart PUN after deploying.

EXTEND_SCRIPT = "/usr/local/sbin/extend_job.sh"
EXTEND_MINUTES = 60

Rails.application.config.after_initialize do
  Rails.logger.info "[job_extend] Loading Slurm job-extend routes"

  # ── Helper module ─────────────────────────────────────────────────
  module SlurmJobExtend
    SQUEUE_BIN    = "squeue"
    SCONTROL_BIN  = "scontrol"

    module_function

    def parse_duration(str)
      return nil if str.nil? || str.empty? || str == "N/A" || str == "INVALID"
      days = 0
      if str.include?("-")
        day_part, str = str.split("-", 2)
        days = day_part.to_i
      end
      parts = str.split(":")
      case parts.length
      when 3 then days * 86400 + parts[0].to_i * 3600 + parts[1].to_i * 60 + parts[2].to_i
      when 2 then days * 86400 + parts[0].to_i * 60 + parts[1].to_i
      else nil
      end
    end

    def job_time(job_id, user)
      out = `#{SQUEUE_BIN} -j #{job_id.to_i} -h -o "%i|%u|%T|%l|%M|%L" 2>&1`.strip
      return { error: "Job #{job_id} not found" } if out.empty?

      cols = out.split("|")
      return { error: "Unexpected squeue output" } if cols.length < 6

      job_owner = cols[1]
      return { error: "Access denied" } if job_owner != user

      time_limit_s  = parse_duration(cols[3])
      run_time_s    = parse_duration(cols[4])
      remaining_s   = parse_duration(cols[5])

      if remaining_s.nil? && time_limit_s && run_time_s
        remaining_s = [0, time_limit_s - run_time_s].max
      end

      {
        job_id:             cols[0],
        state:              cols[2],
        time_limit:         cols[3],
        time_limit_secs:    time_limit_s,
        run_time:           cols[4],
        run_time_secs:      run_time_s,
        remaining_secs:     remaining_s,
        extend_enabled:     remaining_s.is_a?(Numeric) && remaining_s < 3600,
        extend_minutes:     EXTEND_MINUTES
      }
    end

    def extend_job(job_id, user)
      # Ownership is also verified inside the wrapper script
      info = job_time(job_id, user)
      return { success: false, message: info[:error] } if info[:error]
      unless info[:extend_enabled]
        return { success: false, message: "Extension only available when less than 1 hour remains" }
      end

      result = `sudo #{EXTEND_SCRIPT} #{job_id.to_i} #{EXTEND_MINUTES} 2>&1`
      if $?.success?
        { success: true, message: "Job extended by #{EXTEND_MINUTES} minutes" }
      else
        { success: false, message: result.strip.empty? ? "Extension failed" : result.strip }
      end
    end
  end

  # ── Controller ────────────────────────────────────────────────────
  class SlurmExtendController < ApplicationController
    def job_time
      jid = params[:job_id].to_s
      if jid.empty? || jid !~ /\A\d+\z/
        return render json: { error: "Invalid job_id" }, status: :bad_request
      end
      render json: SlurmJobExtend.job_time(jid, ENV["USER"])
    end

    def extend_job
      jid = params[:job_id].to_s
      if jid.empty? || jid !~ /\A\d+\z/
        return render json: { success: false, message: "Invalid job_id" }, status: :bad_request
      end
      render json: SlurmJobExtend.extend_job(jid, ENV["USER"])
    end
  end

  # ── Routes ────────────────────────────────────────────────────────
  Rails.application.routes.append do
    get  "slurm/job_time",    to: "slurm_extend#job_time"
    post "slurm/extend_job",  to: "slurm_extend#extend_job"
  end

  Rails.logger.info "[job_extend] Slurm job-extend routes loaded"
end
