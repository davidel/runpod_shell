import argparse
import base64
import difflib
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import runpod

from runpod_shell.ssh_runner import (
    find_ssh_private_key,
    resolve_ssh_config,
    execute_remote_script,
    list_remote_jobs,
    view_remote_logs,
    kill_remote_job,
    wait_for_ssh,
    build_ssh_cmd
)


class ParseEnv(argparse.Action):

  def __call__(self, parser, namespace, values, option_string=None):
    env_dict = getattr(namespace, self.dest)
    if env_dict is None or not isinstance(env_dict, dict):
      env_dict = {}
    for val in values:
      if '=' in val:
        k, v = val.split('=', 1)
        k = k.strip()
        if not k:
          parser.error(f"Invalid environment variable format: '{val}'. Key cannot be empty.")
        env_dict[k] = v
      else:
        k = val.strip()
        if not k:
          parser.error(f"Invalid environment variable format: '{val}'. Key cannot be empty.")
        if k in os.environ:
          env_dict[k] = os.environ[k]
        else:
          parser.error(f"Environment variable '{k}' is not set in the local environment.")
    setattr(namespace, self.dest, env_dict)


def fatal(msg, exc=RuntimeError):
  print(msg, file=sys.stderr)
  raise exc(msg)


def read_ssh_key(key_path):
  with open(key_path, 'r') as f:
    return f.read().strip()


def get_ssh_key(key_path_str=None):
  if key_path_str:
    key_path = Path(key_path_str).expanduser()
    if not key_path.exists():
      fatal(f"SSH key not found at {key_path}", FileNotFoundError)
    return read_ssh_key(key_path)

  # Check default paths in ~/.ssh
  ssh_dir = Path.home() / ".ssh"
  if ssh_dir.exists():
    for name in ["id_rsa.pub", "id_ed25519.pub", "id_ecdsa.pub", "id_dsa.pub"]:
      key_path = ssh_dir / name
      if key_path.exists():
        print(f"Using default SSH key: {key_path}")
        return read_ssh_key(key_path)

  fatal(
      "No SSH key path provided and no default key (id_rsa.pub, id_ed25519.pub, id_ecdsa.pub, id_dsa.pub) found in ~/.ssh/",
      FileNotFoundError
  )


def read_requirements(req_path_str=None):
  if not req_path_str:
    req_path = Path("requirements.txt")
    if not req_path.exists():
      return ""
  else:
    req_path = Path(req_path_str).expanduser()
    if not req_path.exists():
      fatal(f"Requirements file not found at {req_path}", FileNotFoundError)

  with open(req_path, 'r') as f:
    return f.read()


def parse_env_file(file_path_str):
  file_path = Path(file_path_str).expanduser()
  if not file_path.exists():
    fatal(f"Environment file not found at {file_path}", FileNotFoundError)

  env_dict = {}
  with open(file_path, "r") as f:
    for line in f:
      line = line.strip()
      # Skip comments and empty lines
      if not line or line.startswith("#"):
        continue
      if line.startswith("export "):
        line = line[7:].strip()
      if "=" in line:
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if len(v) >= 2 and ((v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'"))):
          v = v[1:-1]
        env_dict[k] = v
  return env_dict


def read_apt_packages_file(file_path_str):
  file_path = Path(file_path_str).expanduser()
  if not file_path.exists():
    fatal(f"Apt packages file not found at {file_path}", FileNotFoundError)

  packages = []
  with open(file_path, "r") as f:
    for line in f:
      line = line.strip()
      # Skip comments and empty lines
      if not line or line.startswith("#"):
        continue
      # Split by whitespace to handle multiple packages on same line if they exist
      packages.extend(line.split())
  return packages


def build_container_setup_script(apt_packages, requirements_content, pip_packages, volume_mount_path):
  apt_packages_str = " ".join(shlex.quote(p) for p in apt_packages) if apt_packages else ""
  pip_packages_str = " ".join(shlex.quote(p) for p in pip_packages) if pip_packages else ""

  lines = [
      "#!/bin/bash",
      "set -eo pipefail",
      "",
      "log() {",
      '  echo "[$(date \'+%Y-%m-%d %H:%M:%S\')] [setup] $*"',
      "}",
      "",
      'log "Starting container environment setup..."',
      f'mkdir -p "{volume_mount_path}" 2>/dev/null || true'
  ]

  if apt_packages_str:
    lines.extend([
        f'log "Updating apt repositories and installing packages: {apt_packages_str}..."',
        f"apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y {apt_packages_str}",
        'log "Apt packages installed successfully."'
    ])

  if requirements_content.strip() or pip_packages_str:
    lines.extend([
        'log "Configuring system pip for container environment..."',
        'mkdir -p /etc',
        'cat <<\'EOF\' > /etc/pip.conf',
        '[global]',
        'break-system-packages = true',
        'EOF',
        'export PIP_BREAK_SYSTEM_PACKAGES=1',
        'if [ -f /etc/environment ] && ! grep -q "PIP_BREAK_SYSTEM_PACKAGES" /etc/environment 2>/dev/null; then',
        '  echo "PIP_BREAK_SYSTEM_PACKAGES=1" >> /etc/environment',
        'fi',
        'if [ -f /root/.profile ] && ! grep -q "PIP_BREAK_SYSTEM_PACKAGES" /root/.profile 2>/dev/null; then',
        '  echo "export PIP_BREAK_SYSTEM_PACKAGES=1" >> /root/.profile',
        'fi',
        'if [ -f /root/.bashrc ] && ! grep -q "PIP_BREAK_SYSTEM_PACKAGES" /root/.bashrc 2>/dev/null; then',
        '  echo "export PIP_BREAK_SYSTEM_PACKAGES=1" >> /root/.bashrc',
        'fi'
    ])

  escaped_requirements = requirements_content.replace("'", "'\\''")
  if requirements_content.strip():
    lines.extend([
        'log "Writing requirements.txt..."',
        f"echo '{escaped_requirements}' > \"{volume_mount_path}/requirements.txt\"",
        f'log "Installing packages from {volume_mount_path}/requirements.txt..."',
        f'pip install -r "{volume_mount_path}/requirements.txt"'
    ])

  if pip_packages_str:
    lines.extend([
        f'log "Installing command-line pip packages: {pip_packages_str}..."',
        f'pip install {pip_packages_str}'
    ])

  lines.extend([
      f'mkdir -p "{volume_mount_path}" 2>/dev/null || true',
      f'touch "{volume_mount_path}/.setup_complete" 2>/dev/null || touch /tmp/.setup_complete',
      'log "Container environment setup finished successfully."'
  ])

  return "\n".join(lines) + "\n"


def run_container_setup(
    host,
    port,
    setup_script_content,
    private_key_path=None,
    detach=False,
    ssh_timeout=180,
    ssh_config_path=None
):
  import tempfile
  with tempfile.NamedTemporaryFile(mode="w", suffix="_setup_container.sh", delete=False) as tf:
    tf.write(setup_script_content)
    temp_path = tf.name

  try:
    print("\nRunning container environment setup via SSH...")
    res = execute_remote_script(
        host=host,
        port=port,
        script_path=temp_path,
        script_args="",
        detach=detach,
        private_key_path=private_key_path,
        wait_for_setup_flag=False,
        ssh_timeout=ssh_timeout,
        ssh_config_path=ssh_config_path
    )
    if not detach and res.get("exit_code", 0) != 0:
      fatal(f"Container setup failed with exit code: {res.get('exit_code')}")
    return res
  finally:
    if os.path.exists(temp_path):
      os.remove(temp_path)


def get_valid_gpus():
  try:
    gpus = runpod.get_gpus()
    return [g.get("id") for g in gpus if g.get("id")]
  except Exception:
    return None


def resolve_gpu_type(user_input, valid_gpus):
  if not valid_gpus:
    return user_input

  # 1. Exact match
  if user_input in valid_gpus:
    return user_input

  # 2. Case-insensitive match
  user_lower = user_input.lower()
  for gpu in valid_gpus:
    if gpu.lower() == user_lower:
      return gpu

  # 3. Substring match
  matches = []
  for gpu in valid_gpus:
    if user_lower in gpu.lower():
      matches.append(gpu)

  if len(matches) == 1:
    print(f"Auto-resolved GPU type '{user_input}' to '{matches[0]}'")
    return matches[0]
  elif len(matches) > 1:
    options_str = ", ".join(f"'{m}'" for m in matches)
    fatal(f"GPU type '{user_input}' is ambiguous. Did you mean one of: {options_str}?", ValueError)

  # 4. Fuzzy match
  close_matches = difflib.get_close_matches(user_input, valid_gpus, n=3, cutoff=0.4)
  if close_matches:
    options_str = ", ".join(f"'{m}'" for m in close_matches)
    fatal(f"GPU type '{user_input}' not found. Did you mean: {options_str}?", ValueError)

  # Fallback
  fatal(f"GPU type '{user_input}' not found and no close matches detected.", ValueError)


def get_pod_ssh_endpoint(pod_info):
  runtime = pod_info.get("runtime", {}) if pod_info else {}
  ports = runtime.get("ports", []) if runtime else []
  ssh_port = None
  ssh_host = None

  if isinstance(ports, list):
    for p in ports:
      if p.get("privatePort") == 22:
        ssh_port = p.get("publicPort") or p.get("isExternal")
        ssh_host = p.get("ip") or p.get("address")
        break

  if not ssh_host and pod_info:
    ssh_host = pod_info.get("ipAddress") or pod_info.get("address")

  if not ssh_port and isinstance(ports, dict):
    ssh_port = ports.get("publicPort") or ports.get("isExternal")

  return ssh_host, ssh_port


def cmd_create(args):
  # Resolve and validate GPU type
  valid_gpus = get_valid_gpus()
  gpu_type = resolve_gpu_type(args.gpu_type, valid_gpus)

  # Load SSH public key
  ssh_public_key = get_ssh_key(args.ssh_key_path)

  # Read requirements
  requirements_content = read_requirements(args.requirements_path)

  # Build apt packages list
  apt_packages = []
  if args.apt_packages_file:
    apt_packages.extend(read_apt_packages_file(args.apt_packages_file))

  if args.apt_packages is not None:
    apt_packages.extend(args.apt_packages)
  elif not args.apt_packages_file and (args.pip_packages or requirements_content.strip()):
    apt_packages = ["screen", "curl", "htop", "ffmpeg", "git"]

  # Build container disk setup script
  container_disk_setup = build_container_setup_script(
      apt_packages=apt_packages,
      requirements_content=requirements_content,
      pip_packages=args.pip_packages,
      volume_mount_path=args.volume_mount_path
  )

  # Load env file if provided
  env_file_vars = {}
  if args.env_file:
    env_file_vars = parse_env_file(args.env_file)

  # Set environment variables (ensuring SSH public key is present)
  container_env = env_file_vars.copy()
  container_env.update(args.env)
  container_env["PUBLIC_KEY"] = ssh_public_key

  # Check image_name and template_id
  template_id = getattr(args, "template_id", None)
  image_name = getattr(args, "image_name", None)
  if not template_id and not image_name:
    fatal("Either --template-id or --image-name must be specified.", ValueError)

  # Launch Pod
  print(f"Launching RunPod instance '{args.name}'...")
  create_args = {
      "name": args.name,
      "gpu_type_id": gpu_type,
      "gpu_count": args.gpu_count,
      "container_disk_in_gb": args.container_disk_size,
      "volume_in_gb": args.volume_size,
      "volume_mount_path": args.volume_mount_path,
      "ports": args.ports,
      "env": container_env,
      "cloud_type": args.cloud_type,
      "min_vcpu_count": args.vcpu_count,
      "min_memory_in_gb": args.memory
  }

  if getattr(args, "docker_args", None):
    create_args["docker_args"] = args.docker_args

  if template_id:
    create_args["template_id"] = template_id
    template = get_pod_template(template_id)
    if not template or not template.get("imageName"):
      fatal(f"Template '{template_id}' not found or does not specify an image name.", ValueError)
    create_args["image_name"] = template["imageName"]
  else:
    create_args["image_name"] = image_name

  if args.volume_id:
    create_args["network_volume_id"] = args.volume_id

  try:
    pod = runpod.create_pod(**create_args)
  except Exception as e:
    fatal(f"Failed to create pod: {e}", exc=e.__class__)

  # Wait for the pod to boot up
  print("Waiting for pod to initialize...")
  start_poll = time.time()
  poll_timeout = getattr(args, "ssh_timeout", 180)
  if poll_timeout < 300:
    poll_timeout = 300
  pod_info = None
  last_status = None

  while time.time() - start_poll < poll_timeout:
    try:
      pod_info = runpod.get_pod(pod["id"])
    except Exception as e:
      print(f"Error polling pod status: {e}")
      time.sleep(5)
      continue

    if not pod_info:
      time.sleep(5)
      continue

    status = pod_info.get("desiredStatus") or pod_info.get("status")
    if status in ("EXITED", "TERMINATED", "FAILED", "DEAD"):
      fatal(f"Pod initialization failed with status: {status}")

    if status != last_status:
      last_status = status
      print(f"Pod status: {status}")

    ssh_host, ssh_port = get_pod_ssh_endpoint(pod_info)
    if status == "RUNNING" and ssh_host and ssh_port and ssh_port != "unknown":
      break

    time.sleep(5)
  else:
    fatal(f"Timed out waiting for pod '{pod['id']}' to become ready after {poll_timeout} seconds.")

  ssh_host, ssh_port = get_pod_ssh_endpoint(pod_info)
  if not ssh_host or not ssh_port or ssh_port == "unknown":
    fatal(f"Could not resolve SSH endpoint for pod '{pod['id']}'.")

  ssh_config = getattr(args, "ssh_config", None)
  resolved_cfg = resolve_ssh_config(ssh_config)
  ssh_config_flag = f"-F {resolved_cfg} " if resolved_cfg else ""

  priv_key = find_ssh_private_key(args.ssh_key_path, getattr(args, "ssh_private_key_path", None))
  wait_for_ssh(
      host=ssh_host,
      port=ssh_port,
      private_key_path=priv_key,
      timeout=getattr(args, "ssh_timeout", 180),
      ssh_config_path=ssh_config
  )

  has_setup = bool(
      args.apt_packages or
      args.apt_packages_file or
      requirements_content.strip() or
      args.pip_packages
  )
  no_wait_setup = getattr(args, "no_wait_for_setup", False)

  if has_setup:
    detach_setup = getattr(args, "detach", False) and not getattr(args, "run_script", None)
    run_container_setup(
        host=ssh_host,
        port=ssh_port,
        setup_script_content=container_disk_setup,
        private_key_path=priv_key,
        detach=detach_setup,
        ssh_timeout=getattr(args, "ssh_timeout", 180),
        ssh_config_path=ssh_config
    )
  else:
    sentinel_cmd = f"mkdir -p {args.volume_mount_path} 2>/dev/null; touch {args.volume_mount_path}/.setup_complete 2>/dev/null || touch /tmp/.setup_complete"
    cmd = build_ssh_cmd(
        ssh_host,
        ssh_port,
        sentinel_cmd,
        private_key_path=priv_key,
        ssh_config_path=ssh_config
    )
    subprocess.run(cmd, capture_output=True, text=True)

  if getattr(args, "run_script", None):
    wait_setup = has_setup and not no_wait_setup
    res = execute_remote_script(
        host=ssh_host,
        port=ssh_port,
        script_path=args.run_script,
        script_args=getattr(args, "script_args", "") or "",
        detach=getattr(args, "detach", False),
        private_key_path=priv_key,
        wait_for_setup_flag=wait_setup,
        ssh_timeout=getattr(args, "ssh_timeout", 180),
        ssh_config_path=ssh_config
    )
    if not getattr(args, "detach", False) and res.get("exit_code", 0) != 0:
      sys.exit(res["exit_code"])

  print(f"\nPod is ready! Connect via SSH:")
  print(f"ssh {ssh_config_flag}-p {ssh_port} root@{ssh_host}")


def cmd_exec(args):
  print(f"Fetching connection details for pod '{args.pod_id}'...")
  try:
    pod_info = runpod.get_pod(args.pod_id)
  except Exception as e:
    fatal(f"Failed to fetch pod info: {e}", exc=e.__class__)

  if not pod_info:
    fatal(f"Pod '{args.pod_id}' not found.", FileNotFoundError)

  ssh_host, ssh_port = get_pod_ssh_endpoint(pod_info)
  if not ssh_host or not ssh_port or ssh_port == "unknown":
    fatal(f"Could not resolve SSH endpoint for pod '{args.pod_id}'. Is the pod running and exposing port 22?")

  priv_key = find_ssh_private_key(None, getattr(args, "ssh_private_key_path", None))
  wait_setup = not getattr(args, "no_wait_for_setup", False)

  # Resolve environment variables
  extra_env = {}
  env_files = getattr(args, "env_files", None) or []
  if isinstance(env_files, str):
    env_files = [env_files]
  for ef in env_files:
    if ef:
      extra_env.update(parse_env_file(ef))

  if getattr(args, "env", None):
    extra_env.update(args.env)

  res = execute_remote_script(
      host=ssh_host,
      port=ssh_port,
      script_path=args.script,
      script_args=getattr(args, "script_args", "") or "",
      detach=getattr(args, "detach", False),
      private_key_path=priv_key,
      wait_for_setup_flag=wait_setup,
      ssh_timeout=getattr(args, "ssh_timeout", 180),
      ssh_config_path=getattr(args, "ssh_config", None),
      extra_env=extra_env if extra_env else None
  )
  if not getattr(args, "detach", False) and res.get("exit_code", 0) != 0:
    sys.exit(res["exit_code"])


def cmd_ps(args):
  print(f"Checking processes on pod '{args.pod_id}'...")
  try:
    pod_info = runpod.get_pod(args.pod_id)
  except Exception as e:
    fatal(f"Failed to fetch pod info: {e}", exc=e.__class__)

  if not pod_info:
    fatal(f"Pod '{args.pod_id}' not found.", FileNotFoundError)

  ssh_host, ssh_port = get_pod_ssh_endpoint(pod_info)
  if not ssh_host or not ssh_port or ssh_port == "unknown":
    fatal(f"Could not resolve SSH endpoint for pod '{args.pod_id}'.")

  priv_key = find_ssh_private_key(None, getattr(args, "ssh_private_key_path", None))
  jobs = list_remote_jobs(
      ssh_host,
      ssh_port,
      private_key_path=priv_key,
      ssh_config_path=getattr(args, "ssh_config", None)
  )

  if not jobs:
    print(f"No managed jobs found on pod '{args.pod_id}'.")
    return

  print(f"{'JOB ID':<26} | {'PID':<8} | {'STATUS':<12} | {'STARTED':<20} | {'DURATION':<10} | {'SCRIPT':<18} | {'LOG FILE'}")
  print("-" * 120)
  for j in jobs:
    jid = j.get("job_id", "N/A")
    pid = str(j.get("pid", "N/A"))
    status = j.get("status", "N/A")
    started = j.get("started_at_iso", "N/A")
    dur = j.get("duration", "N/A")
    script = j.get("script", "N/A")
    log_f = j.get("log_file", "N/A")
    print(f"{jid:<26} | {pid:<8} | {status:<12} | {started:<20} | {dur:<10} | {script:<18} | {log_f}")


def cmd_logs(args):
  try:
    pod_info = runpod.get_pod(args.pod_id)
  except Exception as e:
    fatal(f"Failed to fetch pod info: {e}", exc=e.__class__)

  if not pod_info:
    fatal(f"Pod '{args.pod_id}' not found.", FileNotFoundError)

  ssh_host, ssh_port = get_pod_ssh_endpoint(pod_info)
  if not ssh_host or not ssh_port or ssh_port == "unknown":
    fatal(f"Could not resolve SSH endpoint for pod '{args.pod_id}'.")

  priv_key = find_ssh_private_key(None, getattr(args, "ssh_private_key_path", None))
  view_remote_logs(
      host=ssh_host,
      port=ssh_port,
      job_id=args.job_id,
      tail_lines=args.tail,
      follow=args.follow,
      private_key_path=priv_key,
      ssh_config_path=getattr(args, "ssh_config", None)
  )


def cmd_kill(args):
  try:
    pod_info = runpod.get_pod(args.pod_id)
  except Exception as e:
    fatal(f"Failed to fetch pod info: {e}", exc=e.__class__)

  if not pod_info:
    fatal(f"Pod '{args.pod_id}' not found.", FileNotFoundError)

  ssh_host, ssh_port = get_pod_ssh_endpoint(pod_info)
  if not ssh_host or not ssh_port or ssh_port == "unknown":
    fatal(f"Could not resolve SSH endpoint for pod '{args.pod_id}'.")

  priv_key = find_ssh_private_key(None, getattr(args, "ssh_private_key_path", None))
  kill_remote_job(
      host=ssh_host,
      port=ssh_port,
      target_id=args.target,
      signal_name=args.signal,
      private_key_path=priv_key,
      ssh_config_path=getattr(args, "ssh_config", None)
  )


def cmd_list(args):
  print("Listing your RunPod instances...")
  try:
    pods = runpod.get_pods()
  except Exception as e:
    fatal(f"Failed to retrieve pods: {e}", exc=e.__class__)

  if not pods:
    print("No pods found.")
    return

  # Print a nice table
  print(f"{'POD ID':<20} | {'NAME':<25} | {'STATUS':<12} | {'GPU TYPE':<22} | {'SSH ENDPOINT'}")
  print("-" * 100)
  for p in pods:
    pod_id = p.get("id", "N/A")
    name = p.get("name", "N/A")
    status = p.get("desiredStatus") or p.get("status", "N/A")

    # Extract GPU info
    machine_info = p.get("machine") or {}
    gpu_type = (
        machine_info.get("gpuDisplayName")
        or p.get("gpuDisplayName")
        or p.get("gpuName")
        or p.get("gpuTypeId")
        or "GPU"
    )
    gpu_count = p.get("gpuCount", 0)
    if gpu_count > 0:
      gpu_display = f"{gpu_count}x {gpu_type}"
    else:
      gpu_display = "CPU only"

    # Extract SSH endpoint
    host, port = get_pod_ssh_endpoint(p)
    ssh_endpoint = f"{host}:{port}" if host and port and port != "unknown" else "N/A"

    print(f"{pod_id:<20} | {name:<25} | {status:<12} | {gpu_display:<22} | {ssh_endpoint}")


def cmd_stop(args):
  print(f"Stopping pod '{args.pod_id}'...")
  try:
    runpod.stop_pod(args.pod_id)
    print(f"Stop request sent for pod '{args.pod_id}'.")
  except Exception as e:
    fatal(f"Failed to stop pod: {e}", exc=e.__class__)


def cmd_terminate(args):
  print(f"Terminating pod '{args.pod_id}'...")
  try:
    runpod.terminate_pod(args.pod_id)
    print(f"Termination request sent for pod '{args.pod_id}'.")
  except Exception as e:
    fatal(f"Failed to terminate pod: {e}", exc=e.__class__)


def run_graphql(query):
  from runpod.api.graphql import run_graphql_query
  return run_graphql_query(query)


def cmd_gpus(args):
  print("Fetching available GPU types...")
  try:
    query = """
    query GpuTypes {
      gpuTypes {
        id
        displayName
        memoryInGb
        maxGpuCount
        securePrice
        communityPrice
      }
    }
    """
    response = run_graphql(query)
    gpus = response.get("data", {}).get("gpuTypes", [])
  except Exception:
    try:
      gpus = runpod.get_gpus()
    except Exception as e:
      fatal(f"Failed to retrieve GPUs: {e}", exc=e.__class__)

  if not gpus:
    print("No GPUs found.")
    return

  filter_pattern = getattr(args, "regex_filter", None) or getattr(args, "filter", None)
  if filter_pattern:
    try:
      regex = re.compile(filter_pattern, re.IGNORECASE)
    except re.error as e:
      fatal(f"Invalid regex pattern '{filter_pattern}': {e}", ValueError)

    gpus = [
        g for g in gpus
        if regex.search(g.get("id") or "") or regex.search(g.get("displayName") or "")
    ]

    if not gpus:
      print(f"No GPUs matching pattern '{filter_pattern}' found.")
      return

  print(f"{'GPU ID':<30} | {'DISPLAY NAME':<25} | {'VRAM (GB)':<9} | {'MAX':<3} | {'SECURE':<7} | {'COMMUNITY':<9}")
  print("-" * 98)
  for g in gpus:
    gpu_id = g.get("id", "N/A")
    display_name = g.get("displayName", "N/A")
    ram = g.get("memoryInGb", "N/A")
    max_gpus = g.get("maxGpuCount", "N/A")
    sec_price = g.get("securePrice")
    comm_price = g.get("communityPrice")

    sec_price_str = f"${sec_price:.2f}/h" if isinstance(sec_price, (int, float)) else "N/A"
    comm_price_str = f"${comm_price:.2f}/h" if isinstance(comm_price, (int, float)) else "N/A"

    print(f"{gpu_id:<30} | {display_name:<25} | {ram:<9} | {max_gpus:<3} | {sec_price_str:<7} | {comm_price_str:<9}")


def get_pod_template(template_id):
  try:
    query = f"""
    query PodTemplate {{
      podTemplate(id: "{template_id}") {{
        id
        name
        imageName
      }}
    }}
    """
    response = run_graphql(query)
    template = response.get("data", {}).get("podTemplate")
    if template:
      return template
  except Exception:
    pass

  templates = get_pod_templates()
  for t in templates:
    if t.get("id") == template_id:
      return t

  return None


def get_pod_templates():
  try:
    query = """
    query PodTemplates {
      myself {
        podTemplates {
          id
          name
          imageName
        }
      }
    }
    """
    response = run_graphql(query)
    return response.get("data", {}).get("myself", {}).get("podTemplates", [])
  except Exception as e:
    fatal(f"Failed to retrieve templates: {e}", exc=e.__class__)


def cmd_templates(args):
  print("Fetching available pod templates...")
  templates = get_pod_templates()

  if not templates:
    print("No templates found.")
    return

  filter_pattern = getattr(args, "regex_filter", None) or getattr(args, "filter", None)
  if filter_pattern:
    try:
      regex = re.compile(filter_pattern, re.IGNORECASE)
    except re.error as e:
      fatal(f"Invalid regex pattern '{filter_pattern}': {e}", ValueError)

    templates = [
        t for t in templates
        if regex.search(t.get("id") or "") or regex.search(t.get("name") or "") or regex.search(t.get("imageName") or "")
    ]

    if not templates:
      print(f"No templates matching pattern '{filter_pattern}' found.")
      return

  print(f"{'TEMPLATE ID':<26} | {'NAME':<35} | {'IMAGE NAME'}")
  print("-" * 110)
  for t in templates:
    t_id = t.get("id", "N/A")
    name = t.get("name", "N/A")
    image = t.get("imageName", "N/A")
    print(f"{t_id:<26} | {name:<35} | {image}")


def main():
  parser = argparse.ArgumentParser(
      prog="runpod-shell",
      description="Manage RunPod instances with optional persistent volume and custom environment setup."
  )
  parser.add_argument(
      "--api-key",
      help="RunPod API Key (can also be set via RUNPOD_API_KEY environment variable)"
  )

  subparsers = parser.add_subparsers(dest="command", required=True, help="Subcommands")

  # Create Command
  create_parser = subparsers.add_parser("create", help="Create and launch a new RunPod instance")
  create_parser.add_argument(
      "--name",
      default="persistent-worker",
      help="Name of the RunPod instance (default: %(default)s)"
  )
  create_parser.add_argument(
      "--volume-id",
      help="Network volume ID to attach (optional)"
  )
  create_parser.add_argument(
      "--image-name",
      "--image_name",
      dest="image_name",
      default=None,
      help="Base image name (optional if --template-id is specified)"
  )
  create_parser.add_argument(
      "--template-id",
      "--template_id",
      dest="template_id",
      default=None,
      help="RunPod template ID (takes precedence over --image-name)"
  )
  create_parser.add_argument(
      "--gpu-type",
      default="NVIDIA GeForce RTX 4090",
      help="GPU type ID (default: %(default)s)"
  )
  create_parser.add_argument(
      "--volume-size",
      type=int,
      default=50,
      help="Container disk volume size in GB (default: %(default)s)"
  )
  create_parser.add_argument(
      "--ssh-key-path",
      help="Path to SSH public key file. If omitted, searches default keys in ~/.ssh/"
  )
  create_parser.add_argument(
      "--requirements-path",
      help="Path to requirements.txt file (optional)"
  )
  create_parser.add_argument(
      "--pip-packages",
      "--pip_packages",
      dest="pip_packages",
      nargs="+",
      help="Extra python packages to install in the virtual environment"
  )
  create_parser.add_argument(
      "--apt-packages",
      nargs="+",
      help="Extra apt packages to install (default: screen curl htop ffmpeg git)"
  )
  create_parser.add_argument(
      "--apt-packages-file",
      "--apt_packages_file",
      dest="apt_packages_file",
      help="Path to a file containing extra apt packages to install"
  )
  create_parser.add_argument(
      "--env",
      nargs="+",
      action=ParseEnv,
      default={},
      help="Extra environment variables to set in the container (e.g. KEY=VALUE KEY2=VALUE2)"
  )
  create_parser.add_argument(
      "--env-file",
      "--env_file",
      dest="env_file",
      help="Path to a .env file containing environment variables to set in the container"
  )
  create_parser.add_argument(
      "--ports",
      default="22/tcp",
      help="Container ports to expose (default: %(default)s)"
  )
  create_parser.add_argument(
      "--docker-args",
      "--docker_args",
      dest="docker_args",
      default=None,
      help="Custom docker arguments to override container entrypoint (optional)"
  )
  create_parser.add_argument(
      "--cloud-type",
      choices=["SECURE", "COMMUNITY", "ALL"],
      default="SECURE",
      help="Type of cloud network to deploy the pod on (default: %(default)s)"
  )
  create_parser.add_argument(
      "--gpu-count",
      type=int,
      default=1,
      help="Number of GPUs to allocate (default: %(default)s)"
  )
  create_parser.add_argument(
      "--container-disk-size",
      type=int,
      default=30,
      help="Container local disk size in GB (default: %(default)s)"
  )
  create_parser.add_argument(
      "--volume-mount-path",
      "--volume_mount_path",
      default="/workspace",
      dest="volume_mount_path",
      help="Path inside the container where the volume is mounted (default: %(default)s)"
  )
  create_parser.add_argument(
      "--vcpu-count",
      "--vcpu_count",
      type=int,
      default=4,
      dest="vcpu_count",
      help="Minimum number of vCPUs to allocate (default: %(default)s)"
  )
  create_parser.add_argument(
      "--memory",
      type=int,
      default=8,
      help="Minimum CPU RAM in GB to allocate (default: %(default)s)"
  )
  create_parser.add_argument(
      "--run-script",
      dest="run_script",
      help="Path to a local script to execute on the pod via SSH once initialized"
  )
  create_parser.add_argument(
      "--script-args",
      dest="script_args",
      default="",
      help="String arguments to pass to the script"
  )
  create_parser.add_argument(
      "-d",
      "--detach",
      dest="detach",
      action="store_true",
      help="Run the script in background on the pod without waiting"
  )
  create_parser.add_argument(
      "--ssh-private-key-path",
      dest="ssh_private_key_path",
      help="Path to private SSH key (auto-detected if omitted)"
  )
  create_parser.add_argument(
      "--no-wait-for-setup",
      dest="no_wait_for_setup",
      action="store_true",
      help="Do not wait for container disk setup to finish before executing script"
  )
  create_parser.add_argument(
      "--ssh-config",
      dest="ssh_config",
      default=os.environ.get("RUNPOD_SSH_CONFIG"),
      help="Path to custom SSH config file (e.g. /dev/null), or RUNPOD_SSH_CONFIG env var"
  )
  create_parser.add_argument(
      "--ssh-timeout",
      dest="ssh_timeout",
      type=int,
      default=180,
      help="Max seconds to wait for SSH and setup readiness (default: %(default)s)"
  )

  # Exec Command
  exec_parser = subparsers.add_parser("exec", help="Execute a local script on an active RunPod instance via SSH")
  exec_parser.add_argument("pod_id", help="The ID of the target pod")
  exec_parser.add_argument("script", help="Path to the local script to run")
  exec_parser.add_argument(
      "--script-args",
      dest="script_args",
      default="",
      help="String arguments to pass to the script"
  )
  exec_parser.add_argument(
      "-d",
      "--detach",
      dest="detach",
      action="store_true",
      help="Run the script in background on the pod without waiting"
  )
  exec_parser.add_argument(
      "--ssh-private-key-path",
      dest="ssh_private_key_path",
      help="Path to private SSH key (auto-detected if omitted)"
  )
  exec_parser.add_argument(
      "--ssh-config",
      dest="ssh_config",
      default=os.environ.get("RUNPOD_SSH_CONFIG"),
      help="Path to custom SSH config file (e.g. /dev/null), or RUNPOD_SSH_CONFIG env var"
  )
  exec_parser.add_argument(
      "--no-wait-for-setup",
      dest="no_wait_for_setup",
      action="store_true",
      help="Do not wait for container disk setup to finish before executing script"
  )
  exec_parser.add_argument(
      "--ssh-timeout",
      dest="ssh_timeout",
      type=int,
      default=180,
      help="Max seconds to wait for SSH and setup readiness (default: %(default)s)"
  )
  exec_parser.add_argument(
      "-e",
      "--env",
      dest="env",
      nargs="+",
      action=ParseEnv,
      default={},
      help="Environment variable to set for the remote script (KEY=VALUE or KEY to extract from local environment). Can be specified multiple times."
  )
  exec_parser.add_argument(
      "--env-file",
      "--env_file",
      dest="env_files",
      action="append",
      default=[],
      help="Path to a file containing environment variables (KEY=VALUE format). Can be specified multiple times."
  )

  # Ps Command
  ps_parser = subparsers.add_parser("ps", help="List remote processes and managed jobs on a RunPod instance")
  ps_parser.add_argument("pod_id", help="The ID of the pod")
  ps_parser.add_argument(
      "--ssh-private-key-path",
      dest="ssh_private_key_path",
      help="Path to private SSH key (auto-detected if omitted)"
  )
  ps_parser.add_argument(
      "--ssh-config",
      dest="ssh_config",
      default=os.environ.get("RUNPOD_SSH_CONFIG"),
      help="Path to custom SSH config file (e.g. /dev/null), or RUNPOD_SSH_CONFIG env var"
  )

  # Logs Command
  logs_parser = subparsers.add_parser("logs", help="View remote logs of managed jobs on a RunPod instance")
  logs_parser.add_argument("pod_id", help="The ID of the pod")
  logs_parser.add_argument("job_id", nargs="?", default=None, help="The Job ID or PID (optional if only 1 job)")
  logs_parser.add_argument(
      "-n",
      "--tail",
      dest="tail",
      type=int,
      default=None,
      help="Number of lines to display from end of log"
  )
  logs_parser.add_argument(
      "-f",
      "--follow",
      dest="follow",
      action="store_true",
      help="Follow log output in real-time"
  )
  logs_parser.add_argument(
      "--ssh-private-key-path",
      dest="ssh_private_key_path",
      help="Path to private SSH key (auto-detected if omitted)"
  )
  logs_parser.add_argument(
      "--ssh-config",
      dest="ssh_config",
      default=os.environ.get("RUNPOD_SSH_CONFIG"),
      help="Path to custom SSH config file (e.g. /dev/null), or RUNPOD_SSH_CONFIG env var"
  )

  # Kill Command
  kill_parser = subparsers.add_parser("kill", help="Kill a remote job or process on a RunPod instance")
  kill_parser.add_argument("pod_id", help="The ID of the pod")
  kill_parser.add_argument("target", help="The Job ID or PID to kill")
  kill_parser.add_argument(
      "-s",
      "--signal",
      dest="signal",
      default="SIGTERM",
      help="Signal to send (e.g. SIGTERM, SIGKILL; default: %(default)s)"
  )
  kill_parser.add_argument(
      "--ssh-private-key-path",
      dest="ssh_private_key_path",
      help="Path to private SSH key (auto-detected if omitted)"
  )
  kill_parser.add_argument(
      "--ssh-config",
      dest="ssh_config",
      default=os.environ.get("RUNPOD_SSH_CONFIG"),
      help="Path to custom SSH config file (e.g. /dev/null), or RUNPOD_SSH_CONFIG env var"
  )

  # List Command
  subparsers.add_parser("list", help="List all your RunPod instances")

  # Stop Command
  stop_parser = subparsers.add_parser("stop", help="Stop a running RunPod instance")
  stop_parser.add_argument("pod_id", help="The ID of the pod to stop")

  # Terminate Command
  terminate_parser = subparsers.add_parser("terminate", help="Terminate (delete) a RunPod instance")
  terminate_parser.add_argument("pod_id", help="The ID of the pod to terminate")

  # Gpus Command
  gpus_parser = subparsers.add_parser("gpus", help="List all available GPU types and details on RunPod")
  gpus_parser.add_argument(
      "filter",
      nargs="?",
      default=None,
      help="Optional regex pattern to filter GPUs by ID or Display Name (case-insensitive)"
  )
  gpus_parser.add_argument(
      "-r",
      "--regex",
      "--filter",
      dest="regex_filter",
      default=None,
      help="Optional regex pattern to filter GPUs by ID or Display Name (case-insensitive)"
  )

  # Templates Command
  templates_parser = subparsers.add_parser("templates", help="List available pod templates on RunPod")
  templates_parser.add_argument(
      "filter",
      nargs="?",
      default=None,
      help="Optional regex pattern to filter templates by ID, Name, or Image (case-insensitive)"
  )
  templates_parser.add_argument(
      "-r",
      "--regex",
      "--filter",
      dest="regex_filter",
      default=None,
      help="Optional regex pattern to filter templates by ID, Name, or Image (case-insensitive)"
  )

  args = parser.parse_args()

  # Set API Key
  if args.api_key:
    runpod.api_key = args.api_key
  elif not runpod.api_key:
    runpod.api_key = os.environ.get("RUNPOD_API_KEY")

  if not runpod.api_key:
    parser.error(
        "RunPod API key must be provided via --api-key or the RUNPOD_API_KEY environment variable."
    )

  if args.command == "create":
    cmd_create(args)
  elif args.command == "list":
    cmd_list(args)
  elif args.command == "stop":
    cmd_stop(args)
  elif args.command == "terminate":
    cmd_terminate(args)
  elif args.command == "gpus":
    cmd_gpus(args)
  elif args.command == "templates":
    cmd_templates(args)
  elif args.command == "exec":
    cmd_exec(args)
  elif args.command == "ps":
    cmd_ps(args)
  elif args.command == "logs":
    cmd_logs(args)
  elif args.command == "kill":
    cmd_kill(args)


if __name__ == "__main__":
  main()
