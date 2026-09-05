#!/usr/bin/env python3
"""RunPod remote job supervisor and process manager.

This script runs on the remote RunPod instance to supervise jobs, record
environment snapshots, monitor process exit status, detect kernel OOM
events, and manage job lifecycles.
"""

import argparse
import base64
import datetime
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import time


def get_base_dir():
  if os.path.isdir("/workspace"):
    return Path("/workspace")
  return Path("/tmp")


def get_jobs_dirs():
  return [Path("/workspace/.runpod_jobs"), Path("/tmp/.runpod_jobs")]


def format_duration(seconds):
  seconds = max(0, int(seconds))
  mins, secs = divmod(seconds, 60)
  hours, mins = divmod(mins, 60)
  if hours > 0:
    return f"{hours}h {mins}m {secs}s"
  return f"{mins}m {secs}s"


def cmd_run(args):
  job_dir = Path(args.job_dir)
  job_dir.mkdir(parents=True, exist_ok=True)
  log_file = Path(args.log_file)
  log_file.parent.mkdir(parents=True, exist_ok=True)

  started_at = int(time.time())
  now_utc = datetime.datetime.now(datetime.timezone.utc)
  started_at_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
  started_at_human = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")

  pid = os.getpid()

  meta = {
      "job_id": args.job_id,
      "pid": pid,
      "script": Path(args.script).name,
      "args": args.args or "",
      "started_at": started_at,
      "started_at_iso": started_at_iso,
      "log_file": str(log_file),
      "script_path": args.script,
      "status": "RUNNING"
  }
  meta_file = job_dir / "meta.json"
  meta_file.write_text(json.dumps(meta, indent=2))
  (job_dir / "pid").write_text(str(pid))

  work_dir = get_base_dir()
  if args.work_dir and os.path.isdir(args.work_dir):
    work_dir = Path(args.work_dir)

  # Prepare environment
  env = os.environ.copy()
  env["PIP_BREAK_SYSTEM_PACKAGES"] = "1"
  job_env_b64 = env.pop("RUNPOD_JOB_ENV", None)
  if job_env_b64:
    try:
      job_env_data = json.loads(base64.b64decode(job_env_b64).decode("utf-8"))
      if isinstance(job_env_data, dict):
        env.update(job_env_data)
    except Exception as e:
      print(f"WARNING: Failed to decode RUNPOD_JOB_ENV payload: {e}", file=sys.stderr)

  python_executable = shutil.which("python3") or shutil.which("python") or "python3"

  # Log job start header
  print("=" * 80)
  print(f"=== RUNPOD JOB STARTED: {args.job_id}")
  print(f"=== Start Time:  {started_at_human}")
  print(f"=== Script:      {args.script} {args.args or ''}".strip())
  print(f"=== Working Dir: {work_dir}")
  print(f"=== Python:      {python_executable}")

  # Check GPU visibility
  try:
    gpu_res = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
        capture_output=True,
        text=True,
        timeout=3
    )
    if gpu_res.returncode == 0 and gpu_res.stdout.strip():
      for line in gpu_res.stdout.strip().splitlines():
        print(f"=== GPU:         {line.strip()}")
  except Exception:
    pass

  print("=" * 80)
  sys.stdout.flush()

  script_path = Path(args.script)
  if not script_path.exists():
    print(f"ERROR: Script not found at {script_path}", file=sys.stderr)
    sys.stderr.flush()
    (job_dir / "exit_code").write_text("127")
    meta["status"] = "FAILED(127)"
    meta["ended_at"] = int(time.time())
    meta_file.write_text(json.dumps(meta, indent=2))
    sys.exit(127)

  try:
    os.chmod(script_path, 0o755)
  except OSError:
    pass

  if script_path.suffix == ".py":
    cmd = [python_executable, str(script_path)]
  elif script_path.suffix == ".sh":
    cmd = ["/bin/bash", str(script_path)]
  else:
    cmd = [str(script_path)]

  if args.args:
    cmd.extend(shlex.split(args.args))

  child = None
  try:
    child = subprocess.Popen(
        cmd,
        cwd=str(work_dir),
        env=env,
        preexec_fn=os.setpgrp
    )
  except Exception as e:
    print(f"ERROR: Failed to launch child process: {e}", file=sys.stderr)
    sys.stderr.flush()
    (job_dir / "exit_code").write_text("1")
    meta["status"] = "FAILED(1)"
    meta["ended_at"] = int(time.time())
    meta_file.write_text(json.dumps(meta, indent=2))
    sys.exit(1)

  (job_dir / "child_pid").write_text(str(child.pid))
  meta["child_pid"] = child.pid
  meta_file.write_text(json.dumps(meta, indent=2))

  # Forward termination signals to child process group
  def handle_signal(signum, frame):
    if child and child.poll() is None:
      try:
        os.killpg(child.pid, signum)
      except OSError:
        pass

  signal.signal(signal.SIGTERM, handle_signal)
  signal.signal(signal.SIGINT, handle_signal)
  if hasattr(signal, "SIGHUP"):
    signal.signal(signal.SIGHUP, handle_signal)

  exit_code = child.wait()

  ended_at = int(time.time())
  end_utc = datetime.datetime.now(datetime.timezone.utc)
  ended_at_iso = end_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
  ended_at_human = end_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
  dur_secs = max(0, ended_at - started_at)
  dur_str = format_duration(dur_secs)

  (job_dir / "exit_code").write_text(str(exit_code))

  # Log job end footer
  print("\n" + "=" * 80)
  print(f"=== RUNPOD JOB COMPLETED: {args.job_id}")
  print(f"=== End Time:    {ended_at_human}")
  print(f"=== Duration:    {dur_str}")
  print(f"=== Exit Code:   {exit_code}")

  if exit_code in (137, -9):
    print("=== NOTICE: Exit code 137 indicates process was killed via SIGKILL (often Linux OOM Killer).")
    try:
      dmesg_res = subprocess.run(
          ["dmesg", "-T"],
          capture_output=True,
          text=True,
          timeout=3
      )
      oom_lines = [
          l for l in dmesg_res.stdout.splitlines()
          if any(k in l.lower() for k in ("oom-killer", "out of memory", "killed process"))
      ]
      if oom_lines:
        print("=== Kernel OOM Killer events detected in dmesg:")
        for l in oom_lines[-5:]:
          print(f"    {l}")
    except Exception:
      pass

  print("=" * 80)
  sys.stdout.flush()

  status = "COMPLETED" if exit_code == 0 else f"FAILED({exit_code})"
  if (job_dir / "killed").exists():
    status = "KILLED"

  meta["status"] = status
  meta["exit_code"] = exit_code
  meta["ended_at"] = ended_at
  meta["ended_at_iso"] = ended_at_iso
  meta["duration"] = dur_str
  meta["duration_seconds"] = dur_secs
  meta_file.write_text(json.dumps(meta, indent=2))

  try:
    log_escaped = shlex.quote(str(log_file))
    subprocess.run(
        f"pkill -f 'tail .* {log_escaped}'",
        shell=True,
        capture_output=True
    )
  except Exception:
    pass

  sys.exit(exit_code)


def cmd_list(args):
  jobs = []
  now = int(time.time())
  base_dirs = [Path(args.base_dir)] if getattr(args, "base_dir", None) else get_jobs_dirs()
  seen_job_ids = set()

  for base_dir in base_dirs:
    if not base_dir.exists():
      continue
    for entry in base_dir.iterdir():
      if not entry.is_dir():
        continue
      meta_file = entry / "meta.json"
      if not meta_file.exists():
        continue
      try:
        data = json.loads(meta_file.read_text())
      except Exception:
        continue

      job_id = data.get("job_id", entry.name)
      if job_id in seen_job_ids:
        continue
      seen_job_ids.add(job_id)

      pid = data.get("pid")
      child_pid = data.get("child_pid")
      is_running = False
      if pid:
        try:
          os.kill(int(pid), 0)
          is_running = True
        except OSError:
          is_running = False

      if not is_running and child_pid:
        try:
          os.kill(int(child_pid), 0)
          is_running = True
        except OSError:
          is_running = False

      exit_code_file = entry / "exit_code"
      killed_file = entry / "killed"

      if is_running:
        status = "RUNNING"
      elif killed_file.exists():
        status = "KILLED"
      elif exit_code_file.exists():
        try:
          ec = exit_code_file.read_text().strip()
          status = "COMPLETED" if ec == "0" else f"FAILED({ec})"
        except Exception:
          status = "EXITED"
      else:
        status = data.get("status", "EXITED")

      data["status"] = status
      started = data.get("started_at", now)

      if is_running:
        dur_secs = now - started
      elif "ended_at" in data:
        dur_secs = data["ended_at"] - started
      elif exit_code_file.exists():
        try:
          dur_secs = int(exit_code_file.stat().st_mtime) - started
        except OSError:
          dur_secs = data.get("duration_seconds", now - started)
      else:
        dur_secs = data.get("duration_seconds", now - started)

      data["duration"] = format_duration(dur_secs)
      jobs.append(data)

  jobs.sort(key=lambda x: x.get("started_at", 0), reverse=True)
  print(json.dumps(jobs))


def cmd_kill(args):
  target_id = str(args.target)
  sig_name = args.signal or "SIGTERM"
  try:
    sig_num = getattr(signal, sig_name)
  except AttributeError:
    sig_num = signal.SIGTERM

  target_job_dir = None
  target_pid = None
  target_child_pid = None
  base_dirs = [Path(args.base_dir)] if getattr(args, "base_dir", None) else get_jobs_dirs()

  for base_dir in base_dirs:
    if not base_dir.exists():
      continue
    for entry in base_dir.iterdir():
      if entry.name == target_id:
        target_job_dir = entry
        pid_file = entry / "pid"
        if pid_file.exists():
          target_pid = pid_file.read_text().strip()
        child_pid_file = entry / "child_pid"
        if child_pid_file.exists():
          target_child_pid = child_pid_file.read_text().strip()
        break
      meta_file = entry / "meta.json"
      if meta_file.exists():
        try:
          data = json.loads(meta_file.read_text())
          if str(data.get("pid")) == target_id or data.get("job_id") == target_id or str(data.get("child_pid")) == target_id:
            target_job_dir = entry
            target_pid = str(data.get("pid"))
            if "child_pid" in data:
              target_child_pid = str(data.get("child_pid"))
            break
        except Exception:
          pass
    if target_job_dir:
      break

  if not target_pid:
    target_pid = target_id

  killed_any = False

  # Try child process first (and its process group), then supervisor
  for p_str in (target_child_pid, target_pid):
    if not p_str:
      continue
    try:
      p_int = int(p_str)
    except ValueError:
      continue

    try:
      os.kill(p_int, 0)
    except OSError:
      continue

    killed_any = True
    my_pgid = os.getpgrp()
    try:
      pgid = os.getpgid(p_int)
      if pgid > 1 and pgid != my_pgid:
        os.killpg(pgid, sig_num)
      else:
        os.kill(p_int, sig_num)
    except OSError:
      try:
        os.kill(p_int, sig_num)
      except OSError:
        pass

  if target_job_dir and target_job_dir.exists():
    try:
      (target_job_dir / "killed").touch()
      meta_f = target_job_dir / "meta.json"
      if meta_f.exists():
        data = json.loads(meta_f.read_text())
        lf = data.get("log_file")
        if lf:
          log_escaped = shlex.quote(str(lf))
          subprocess.run(
              f"pkill -f 'tail .* {log_escaped}'",
              shell=True,
              capture_output=True
          )
    except Exception:
      pass

  if killed_any:
    print("KILLED")
  else:
    print("NOT_RUNNING")


def main():
  parser = argparse.ArgumentParser(description="RunPod Remote Job Runner")
  subparsers = parser.add_subparsers(dest="command", required=True)

  run_p = subparsers.add_parser("run")
  run_p.add_argument("--job-id", required=True)
  run_p.add_argument("--script", required=True)
  run_p.add_argument("--args", default="")
  run_p.add_argument("--job-dir", required=True)
  run_p.add_argument("--log-file", required=True)
  run_p.add_argument("--work-dir", default="")

  list_p = subparsers.add_parser("list")
  list_p.add_argument("--base-dir", default=None)

  kill_p = subparsers.add_parser("kill")
  kill_p.add_argument("--target", required=True)
  kill_p.add_argument("--signal", default="SIGTERM")
  kill_p.add_argument("--base-dir", default=None)

  args = parser.parse_args()
  if args.command == "run":
    cmd_run(args)
  elif args.command == "list":
    cmd_list(args)
  elif args.command == "kill":
    cmd_kill(args)


if __name__ == "__main__":
  main()
