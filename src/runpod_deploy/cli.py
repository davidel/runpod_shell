import argparse
import difflib
import os
from pathlib import Path
import sys
import time
import runpod


class ParseEnv(argparse.Action):

  def __call__(self, parser, namespace, values, option_string=None):
    env_dict = getattr(namespace, self.dest) or {}
    for val in values:
      if '=' in val:
        k, v = val.split('=', 1)
        env_dict[k] = v
      else:
        parser.error(f"Invalid environment variable format: {val}. Expected KEY=VALUE.")
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
      if "=" in line:
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip("'\"")
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
  # Build apt install command
  apt_packages_str = " ".join(apt_packages)
  apt_install_cmd = f"apt-get update && apt-get install -y {apt_packages_str}" if apt_packages else "true"

  # Build python venv setup script
  escaped_requirements = requirements_content.replace("'", "'\\''")
  write_requirements = f"echo '{escaped_requirements}' > {volume_mount_path}/requirements.txt" if requirements_content.strip() else "true"
  pip_packages_str = " ".join(pip_packages) if pip_packages else ""

  if requirements_content.strip() or pip_packages_str:
    venv_dir = f"{volume_mount_path}/venv"
    sentinel = f"{venv_dir}/.setup_complete"
    install_pip_packages = f"{venv_dir}/bin/pip install {pip_packages_str}" if pip_packages_str else "true"

    setup_requirements = f"""{write_requirements} && \\
if [ -d "{venv_dir}" ] && [ ! -f "{sentinel}" ]; then \\
    echo "Warning: Found incomplete or broken virtual environment. Cleaning up..."; \\
    rm -rf "{venv_dir}"; \\
fi && \\
if [ ! -d "{venv_dir}" ]; then \\
    echo "Creating fresh venv on Network Volume..."; \\
    python3 -m venv "{venv_dir}" && \\
    "{venv_dir}/bin/pip" install --upgrade pip && \\
    if [ -f "{volume_mount_path}/requirements.txt" ]; then "{venv_dir}/bin/pip" install -r "{volume_mount_path}/requirements.txt"; fi && \\
    {install_pip_packages} && \\
    touch "{sentinel}"; \\
else \\
    echo "Found healthy virtual environment."; \\
    if [ "{pip_packages_str}" != "" ]; then \\
        echo "Installing command-line pip packages..."; \\
        {install_pip_packages}; \\
    fi \\
fi && \\
if [ -d "{venv_dir}" ] && [ -f "/root/.bashrc" ] && ! grep -q "source {venv_dir}/bin/activate" /root/.bashrc; then \\
    echo "source {venv_dir}/bin/activate" >> /root/.bashrc; \\
fi"""
  else:
    setup_requirements = "true"

  return f"{apt_install_cmd} && {setup_requirements}"


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
  elif not args.apt_packages_file:
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

  # Launch Pod
  print(f"Launching RunPod instance '{args.name}'...")
  create_args = {
      "name": args.name,
      "image_name": args.image_name,
      "gpu_type_id": gpu_type,
      "gpu_count": args.gpu_count,
      "container_disk_in_gb": args.container_disk_size,
      "volume_in_gb": args.volume_size,
      "ports": args.ports,
      "env": container_env,
      "cloud_type": args.cloud_type,
      "min_vcpu_count": args.vcpu_count,
      "min_memory_in_gb": args.memory,
      "docker_args": f"/bin/bash -c '{container_disk_setup} && sleep infinity'"
  }

  if args.volume_id:
    create_args["network_volume_id"] = args.volume_id
    create_args["volume_mount_path"] = args.volume_mount_path

  try:
    pod = runpod.create_pod(**create_args)
  except Exception as e:
    fatal(f"Failed to create pod: {e}", exc=e.__class__)

  # Wait for the pod to boot up
  print("Waiting for pod to initialize...")
  while True:
    try:
      pod_info = runpod.get_pod(pod["id"])
      if pod_info.get("runtime") and pod_info["runtime"].get("gpus"):
        break
    except Exception as e:
      print(f"Error polling pod status: {e}")
    time.sleep(5)

  runtime = pod_info.get("runtime", {})
  ports = runtime.get("ports", [])
  ssh_port = None
  ssh_host = None

  for p in ports:
    if p.get("privatePort") == 22:
      ssh_port = p.get("isExternal")
      ssh_host = p.get("address")
      break

  if not ssh_host:
    ssh_host = pod_info.get("ipAddress") or pod_info.get("address")

  if not ssh_host:
    ssh_host = "your-runpod-proxy-endpoint.runpod.net"

  if not ssh_port:
    try:
      ssh_port = runtime["ports"]["isExternal"]
    except (KeyError, TypeError):
      ssh_port = "unknown"

  print(f"\nPod is ready! Connect via SSH:")
  print(f"ssh -p {ssh_port} root@{ssh_host}")


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
    gpu_type = p.get("gpuName") or p.get("gpuTypeId") or "CPU"
    gpu_count = p.get("gpuCount", 0)
    if gpu_count > 0:
      gpu_display = f"{gpu_count}x {gpu_type}"
    else:
      gpu_display = "CPU only"

    # Extract SSH endpoint
    runtime = p.get("runtime", {})
    ports = runtime.get("ports", []) if runtime else []
    ssh_endpoint = "N/A"
    for port_entry in ports:
      if port_entry.get("privatePort") == 22:
        ssh_endpoint = f"{port_entry.get('address')}:{port_entry.get('isExternal')}"
        break

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


def cmd_gpus(args):
  print("Fetching available GPU types...")
  try:
    from runpod.api.graphql import run_graphql_query
    query = """
    query GpuTypes {
      gpuTypes {
        id
        displayName
        memoryInGb
        cudaCores
        maxGpuCount
        securePrice
        communityPrice
      }
    }
    """
    response = run_graphql_query(query)
    gpus = response.get("data", {}).get("gpuTypes", [])
  except Exception:
    try:
      gpus = runpod.get_gpus()
    except Exception as e:
      fatal(f"Failed to retrieve GPUs: {e}", exc=e.__class__)

  if not gpus:
    print("No GPUs found.")
    return

  print(f"{'GPU ID':<30} | {'DISPLAY NAME':<25} | {'VRAM (GB)':<9} | {'CUDA CORES':<10} | {'MAX':<3} | {'SECURE':<7} | {'COMMUNITY':<9}")
  print("-" * 110)
  for g in gpus:
    gpu_id = g.get("id", "N/A")
    display_name = g.get("displayName", "N/A")
    ram = g.get("memoryInGb", "N/A")
    cores = g.get("cudaCores", "N/A")
    max_gpus = g.get("maxGpuCount", "N/A")
    sec_price = g.get("securePrice")
    comm_price = g.get("communityPrice")

    sec_price_str = f"${sec_price:.2f}/h" if isinstance(sec_price, (int, float)) else "N/A"
    comm_price_str = f"${comm_price:.2f}/h" if isinstance(comm_price, (int, float)) else "N/A"

    print(f"{gpu_id:<30} | {display_name:<25} | {ram:<9} | {cores:<10} | {max_gpus:<3} | {sec_price_str:<7} | {comm_price_str:<9}")


def main():
  parser = argparse.ArgumentParser(
      prog="runpod-deploy",
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
      default="runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404",
      help="Base image name (default: %(default)s)"
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
      help="Path inside the container where the network volume is mounted (default: %(default)s)"
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

  # List Command
  subparsers.add_parser("list", help="List all your RunPod instances")

  # Stop Command
  stop_parser = subparsers.add_parser("stop", help="Stop a running RunPod instance")
  stop_parser.add_argument("pod_id", help="The ID of the pod to stop")

  # Terminate Command
  terminate_parser = subparsers.add_parser("terminate", help="Terminate (delete) a RunPod instance")
  terminate_parser.add_argument("pod_id", help="The ID of the pod to terminate")

  # Gpus Command
  subparsers.add_parser("gpus", help="List all available GPU types and details on RunPod")

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


if __name__ == "__main__":
  main()
