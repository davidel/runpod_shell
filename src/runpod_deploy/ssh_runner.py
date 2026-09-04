import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


def find_ssh_private_key(public_key_path=None, explicit_private_key_path=None):
  if explicit_private_key_path:
    priv_path = Path(explicit_private_key_path).expanduser()
    if not priv_path.exists():
      raise FileNotFoundError(f"SSH private key not found at {priv_path}")
    return priv_path

  if public_key_path:
    pub_path = Path(public_key_path).expanduser()
    if pub_path.name.endswith(".pub"):
      candidate = pub_path.with_name(pub_path.name[:-4])
      if candidate.exists():
        return candidate
    if pub_path.exists():
      return pub_path

  ssh_dir = Path.home() / ".ssh"
  if ssh_dir.exists():
    for name in ["id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"]:
      candidate = ssh_dir / name
      if candidate.exists():
        return candidate

  return None


def build_ssh_cmd(host, port, remote_command=None, private_key_path=None, tty=False):
  cmd = ["ssh", "-p", str(port)]
  cmd.extend(["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"])
  if private_key_path:
    cmd.extend(["-i", str(private_key_path)])
  if tty:
    cmd.append("-t")
  cmd.append(f"root@{host}")
  if remote_command:
    cmd.append(remote_command)
  return cmd


def build_scp_cmd(local_path, remote_path, host, port, private_key_path=None):
  cmd = ["scp", "-P", str(port)]
  cmd.extend(["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"])
  if private_key_path:
    cmd.extend(["-i", str(private_key_path)])
  cmd.extend([str(local_path), f"root@{host}:{remote_path}"])
  return cmd


def wait_for_ssh(host, port, private_key_path=None, timeout=180, interval=3):
  print(f"Waiting for SSH daemon at {host}:{port} to become available...")
  start_time = time.time()
  while time.time() - start_time < timeout:
    cmd = build_ssh_cmd(host, port, "true", private_key_path=private_key_path)
    try:
      res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
      if res.returncode == 0:
        print("SSH connection established successfully.")
        return True
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
      pass
    time.sleep(interval)
  raise TimeoutError(f"Timed out waiting for SSH daemon at {host}:{port} after {timeout} seconds.")


def wait_for_setup(host, port, private_key_path=None, timeout=300, interval=5):
  print("Waiting for container disk and environment setup to complete...")
  check_cmd = "test -f /workspace/.setup_complete || test -f /tmp/.setup_complete"
  start_time = time.time()
  while time.time() - start_time < timeout:
    cmd = build_ssh_cmd(host, port, check_cmd, private_key_path=private_key_path)
    try:
      res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
      if res.returncode == 0:
        print("Container environment setup is complete.")
        return True
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
      pass
    time.sleep(interval)
  raise TimeoutError("Timed out waiting for container setup sentinel file.")


def execute_remote_script(
    host,
    port,
    script_path,
    script_args="",
    detach=False,
    private_key_path=None,
    wait_for_setup_flag=True,
    ssh_timeout=180
):
  local_path = Path(script_path).expanduser()
  if not local_path.exists():
    raise FileNotFoundError(f"Local script not found at {local_path}")

  wait_for_ssh(host, port, private_key_path=private_key_path, timeout=ssh_timeout)

  if wait_for_setup_flag:
    wait_for_setup(host, port, private_key_path=private_key_path, timeout=ssh_timeout)

  job_id = f"job-{int(time.time())}-{uuid.uuid4().hex[:6]}"
  remote_script_path = f"/tmp/{job_id}_{local_path.name}"

  print(f"Uploading script '{local_path.name}' to remote pod...")
  scp_cmd = build_scp_cmd(local_path, remote_script_path, host, port, private_key_path=private_key_path)
  upload_res = subprocess.run(scp_cmd, capture_output=True, text=True)
  if upload_res.returncode != 0:
    raise RuntimeError(f"Failed to upload script via SCP: {upload_res.stderr.strip()}")

  # Launcher command on remote host
  launcher_script = f"""
chmod +x "{remote_script_path}"
BASE_DIR="/workspace"
if [ ! -d "/workspace" ]; then
  BASE_DIR="/tmp"
fi
JOBS_DIR="$BASE_DIR/.runpod_jobs/{job_id}"
LOGS_DIR="$BASE_DIR/logs"
mkdir -p "$JOBS_DIR" "$LOGS_DIR"
LOG_FILE="$LOGS_DIR/{job_id}_{local_path.name}.log"

cat <<'EOF' > "$JOBS_DIR/runner.sh"
#!/bin/bash
if [ -f /workspace/venv/bin/activate ]; then
  source /workspace/venv/bin/activate
fi
cd /workspace 2>/dev/null || cd /tmp
"{remote_script_path}" {script_args}
EXIT_CODE=$?
echo $EXIT_CODE > "$JOBS_DIR/exit_code"
exit $EXIT_CODE
EOF

chmod +x "$JOBS_DIR/runner.sh"
setsid nohup "$JOBS_DIR/runner.sh" > "$LOG_FILE" 2>&1 &
PID=$!
echo $PID > "$JOBS_DIR/pid"

cat <<EOF > "$JOBS_DIR/meta.json"
{{
  "job_id": "{job_id}",
  "pid": $PID,
  "script": "{local_path.name}",
  "args": "{script_args}",
  "started_at": $(date +%s),
  "started_at_iso": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "log_file": "$LOG_FILE",
  "script_path": "{remote_script_path}"
}}
EOF

echo "PID:$PID"
echo "LOG_FILE:$LOG_FILE"
echo "JOB_ID:{job_id}"
"""

  launch_cmd = build_ssh_cmd(host, port, launcher_script, private_key_path=private_key_path)
  launch_res = subprocess.run(launch_cmd, capture_output=True, text=True)
  if launch_res.returncode != 0:
    raise RuntimeError(f"Failed to launch script on pod: {launch_res.stderr.strip()}")

  pid = None
  log_file = None
  for line in launch_res.stdout.splitlines():
    if line.startswith("PID:"):
      pid = line.split("PID:", 1)[1].strip()
    elif line.startswith("LOG_FILE:"):
      log_file = line.split("LOG_FILE:", 1)[1].strip()

  print(f"\nRemote job registered:")
  print(f"  Job ID:   {job_id}")
  print(f"  PID:      {pid}")
  print(f"  Log file: {log_file}")

  if detach:
    print(f"\nScript is running in background.")
    print(f"To monitor logs: runpod-deploy logs <pod-id> {job_id} -f")
    return {"job_id": job_id, "pid": pid, "log_file": log_file, "exit_code": 0}

  # Foreground mode: stream logs until completion
  print("\nStreaming remote logs (Ctrl+C to detach without stopping job)...")
  tail_cmd = build_ssh_cmd(
      host,
      port,
      f"tail -n +1 --pid={pid} -f '{log_file}' 2>/dev/null || tail -n +1 -f '{log_file}'",
      private_key_path=private_key_path
  )

  try:
    subprocess.run(tail_cmd)
  except KeyboardInterrupt:
    print(f"\nDetached from remote process {pid}. Job continues running in background.")
    print(f"To re-attach: runpod-deploy logs <pod-id> {job_id} -f")
    return {"job_id": job_id, "pid": pid, "log_file": log_file, "exit_code": 0}

  # Check final exit code
  exit_code_cmd = build_ssh_cmd(
      host,
      port,
      f"cat /workspace/.runpod_jobs/{job_id}/exit_code 2>/dev/null || cat /tmp/.runpod_jobs/{job_id}/exit_code 2>/dev/null || echo unknown",
      private_key_path=private_key_path
  )
  code_res = subprocess.run(exit_code_cmd, capture_output=True, text=True)
  exit_code_str = code_res.stdout.strip()
  exit_code = int(exit_code_str) if exit_code_str.isdigit() else 0

  print(f"\nRemote job completed with exit code: {exit_code}")
  return {"job_id": job_id, "pid": pid, "log_file": log_file, "exit_code": exit_code}


def list_remote_jobs(host, port, private_key_path=None):
  script = """
python3 -c '
import json
import os
import time

jobs = []
base_dirs = ["/workspace/.runpod_jobs", "/tmp/.runpod_jobs"]
now = int(time.time())

for b in base_dirs:
  if not os.path.exists(b):
    continue
  for entry in os.listdir(b):
    job_dir = os.path.join(b, entry)
    meta_file = os.path.join(job_dir, "meta.json")
    if not os.path.isfile(meta_file):
      continue
    try:
      with open(meta_file, "r") as f:
        data = json.load(f)
    except Exception:
      continue

    pid = data.get("pid")
    is_running = False
    if pid:
      try:
        os.kill(int(pid), 0)
        is_running = True
      except OSError:
        is_running = False

    exit_code_file = os.path.join(job_dir, "exit_code")
    killed_file = os.path.join(job_dir, "killed")
    status = "UNKNOWN"
    if is_running:
      status = "RUNNING"
    elif os.path.exists(killed_file):
      status = "KILLED"
    elif os.path.exists(exit_code_file):
      try:
        with open(exit_code_file, "r") as ef:
          ec = ef.read().strip()
          status = "COMPLETED" if ec == "0" else f"FAILED({ec})"
      except Exception:
        status = "EXITED"
    else:
      status = "EXITED"

    data["status"] = status
    started = data.get("started_at", now)
    dur_secs = now - started
    mins, secs = divmod(dur_secs, 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
      data["duration"] = f"{hours}h {mins}m {secs}s"
    else:
      data["duration"] = f"{mins}m {secs}s"

    jobs.append(data)

jobs.sort(key=lambda x: x.get("started_at", 0), reverse=True)
print(json.dumps(jobs))
'
"""
  cmd = build_ssh_cmd(host, port, script, private_key_path=private_key_path)
  res = subprocess.run(cmd, capture_output=True, text=True)
  if res.returncode != 0:
    raise RuntimeError(f"Failed to list remote jobs: {res.stderr.strip()}")

  try:
    return json.loads(res.stdout.strip())
  except json.JSONDecodeError:
    return []


def view_remote_logs(host, port, job_id=None, tail_lines=None, follow=False, private_key_path=None):
  jobs = list_remote_jobs(host, port, private_key_path=private_key_path)
  target_job = None

  if job_id:
    for j in jobs:
      if j.get("job_id") == job_id or str(j.get("pid")) == str(job_id):
        target_job = j
        break
    if not target_job:
      raise ValueError(f"Job '{job_id}' not found on pod.")
  else:
    if not jobs:
      print("No jobs found on pod.")
      return
    if len(jobs) == 1:
      target_job = jobs[0]
      print(f"Selecting only active job: {target_job['job_id']}")
    else:
      target_job = jobs[0]
      print(f"Selecting most recent job: {target_job['job_id']} (use job-id to view others)")

  log_file = target_job.get("log_file")
  if not log_file:
    raise ValueError(f"Log file not specified in metadata for job {target_job.get('job_id')}")

  if follow:
    n = tail_lines if tail_lines else 50
    remote_cmd = f"tail -n {n} -f '{log_file}'"
    tty = True
  elif tail_lines:
    remote_cmd = f"tail -n {tail_lines} '{log_file}'"
    tty = False
  else:
    remote_cmd = f"cat '{log_file}'"
    tty = False

  cmd = build_ssh_cmd(host, port, remote_cmd, private_key_path=private_key_path, tty=tty)
  subprocess.run(cmd)


def kill_remote_job(host, port, target_id, signal_name="SIGTERM", private_key_path=None):
  jobs = list_remote_jobs(host, port, private_key_path=private_key_path)
  target_job = None

  for j in jobs:
    if j.get("job_id") == target_id or str(j.get("pid")) == str(target_id):
      target_job = j
      break

  target_pid = target_job.get("pid") if target_job else target_id
  job_dir = None
  if target_job:
    job_id = target_job.get("job_id")
    job_dir = f"/workspace/.runpod_jobs/{job_id}"

  kill_script = f"""
PID="{target_pid}"
JOB_DIR="{job_dir or ''}"
if kill -0 "$PID" 2>/dev/null; then
  PGID=$(ps -o pgid= -p "$PID" 2>/dev/null | tr -d ' ')
  if [ -n "$PGID" ] && [ "$PGID" != "0" ] && [ "$PGID" != "1" ]; then
    kill -s {signal_name} -"$PGID" 2>/dev/null || kill -s {signal_name} "$PID"
  else
    kill -s {signal_name} "$PID"
  fi
  if [ -n "$JOB_DIR" ] && [ -d "$JOB_DIR" ]; then
    touch "$JOB_DIR/killed"
  fi
  echo "KILLED"
else
  echo "NOT_RUNNING"
fi
"""

  cmd = build_ssh_cmd(host, port, kill_script, private_key_path=private_key_path)
  res = subprocess.run(cmd, capture_output=True, text=True)
  output = res.stdout.strip()

  if "KILLED" in output:
    print(f"Signal {signal_name} sent to process {target_pid} and its process group.")
  elif "NOT_RUNNING" in output:
    print(f"Process {target_pid} was not running.")
  else:
    print(f"Result: {output}")
