import argparse
import os
from pathlib import Path
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


def read_ssh_key(key_path):
  with open(key_path, 'r') as f:
    return f.read().strip()


def get_ssh_key(key_path_str=None):
  if key_path_str:
    key_path = Path(key_path_str).expanduser()
    if not key_path.exists():
      raise FileNotFoundError(f"SSH key not found at {key_path}")
    return read_ssh_key(key_path)

  # Check default paths in ~/.ssh
  ssh_dir = Path.home() / ".ssh"
  if ssh_dir.exists():
    for name in ["id_rsa.pub", "id_ed25519.pub", "id_ecdsa.pub", "id_dsa.pub"]:
      key_path = ssh_dir / name
      if key_path.exists():
        print(f"🔑 Using default SSH key: {key_path}")
        return read_ssh_key(key_path)

  raise FileNotFoundError(
      "No SSH key path provided and no default key (id_rsa.pub, id_ed25519.pub, id_ecdsa.pub, id_dsa.pub) found in ~/.ssh/"
  )


def read_requirements(req_path_str=None):
  if not req_path_str:
    req_path = Path("requirements.txt")
    if not req_path.exists():
      return ""
  else:
    req_path = Path(req_path_str).expanduser()
    if not req_path.exists():
      raise FileNotFoundError(f"Requirements file not found at {req_path}")

  with open(req_path, 'r') as f:
    return f.read()


def main():
  parser = argparse.ArgumentParser(
      description="Create and run RunPod instances with optional persistent volume and custom environment setup."
  )
  parser.add_argument(
      "--api-key",
      help="RunPod API Key (can also be set via RUNPOD_API_KEY environment variable)"
  )
  parser.add_argument(
      "--name",
      default="persistent-worker",
      help="Name of the RunPod instance (default: %(default)s)"
  )
  parser.add_argument(
      "--volume-id",
      help="Network volume ID to attach (optional)"
  )
  parser.add_argument(
      "--image-name",
      default="runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404",
      help="Base image name (default: %(default)s)"
  )
  parser.add_argument(
      "--gpu-type",
      default="NVIDIA GeForce RTX 4090",
      help="GPU type ID (default: %(default)s)"
  )
  parser.add_argument(
      "--volume-size",
      type=int,
      default=50,
      help="Container disk volume size in GB (default: %(default)s)"
  )
  parser.add_argument(
      "--ssh-key-path",
      help="Path to SSH public key file. If omitted, searches default keys in ~/.ssh/"
  )
  parser.add_argument(
      "--requirements-path",
      help="Path to requirements.txt file (optional)"
  )
  parser.add_argument(
      "--apt-packages",
      nargs="+",
      default=["screen", "curl", "htop", "ffmpeg", "git"],
      help="Extra apt packages to install (default: %(default)s)"
  )
  parser.add_argument(
      "--env",
      nargs="+",
      action=ParseEnv,
      default={},
      help="Extra environment variables to set in the container (e.g. KEY=VALUE KEY2=VALUE2)"
  )
  parser.add_argument(
      "--ports",
      default="22/tcp",
      help="Container ports to expose (default: %(default)s)"
  )
  parser.add_argument(
      "--cloud-type",
      choices=["SECURE", "COMMUNITY", "ALL"],
      default="SECURE",
      help="Type of cloud network to deploy the pod on (default: %(default)s)"
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

  # Load SSH public key
  try:
    ssh_public_key = get_ssh_key(args.ssh_key_path)
  except FileNotFoundError as e:
    parser.error(str(e))

  # Read requirements
  try:
    requirements_content = read_requirements(args.requirements_path)
  except FileNotFoundError as e:
    parser.error(str(e))

  # Build container disk setup script
  apt_packages_str = " ".join(args.apt_packages)
  apt_install_cmd = f"apt-get update && apt-get install -y {apt_packages_str}" if args.apt_packages else "true"

  if requirements_content.strip():
    setup_requirements = f"""echo '{requirements_content}' > /workspace/requirements.txt && \\
if [ ! -d "/workspace/venv" ]; then \\
    echo "📦 Creating fresh venv on Network Volume..."; \\
    python3 -m venv /workspace/venv && \\
    /workspace/venv/bin/pip install --upgrade pip && \\
    /workspace/venv/bin/pip install -r /workspace/requirements.txt; \\
else \\
    echo "✅ Found existing venv on Network Volume. Skipping installation."; \\
fi"""
  else:
    setup_requirements = "true"

  container_disk_setup = f"{apt_install_cmd} && {setup_requirements}"

  # Set environment variables (ensuring SSH public key is present)
  container_env = args.env.copy()
  container_env["PUBLIC_KEY"] = ssh_public_key

  # Launch Pod
  print(f"🚀 Launching RunPod instance '{args.name}'...")
  create_args = {
      "name": args.name,
      "image_name": args.image_name,
      "gpu_type_id": args.gpu_type,
      "volume_in_gb": args.volume_size,
      "ports": args.ports,
      "env": container_env,
      "cloud_type": args.cloud_type,
      "docker_args": f"/bin/bash -c '{container_disk_setup} && sleep infinity'"
  }

  if args.volume_id:
    create_args["network_volume_id"] = args.volume_id

  try:
    pod = runpod.create_pod(**create_args)
  except Exception as e:
    print(f"❌ Failed to create pod: {e}")
    return

  # Wait for the pod to boot up
  print("⏳ Waiting for pod to initialize...")
  while True:
    try:
      pod_info = runpod.get_pod(pod["id"])
      if pod_info.get("runtime") and pod_info["runtime"].get("gpus"):
        break
    except Exception as e:
      print(f"⚠️ Error polling pod status: {e}")
    time.sleep(5)

  runtime = pod_info["runtime"]
  # Find external port for SSH
  ports = runtime.get("ports", [])
  ssh_port = None
  for p in ports:
    if p.get("privatePort") == 22:
      ssh_port = p.get("isExternal")
      break

  if not ssh_port:
    # Fallback to general parsing if ports structure is different
    try:
      ssh_port = runtime["ports"]["isExternal"]
    except (KeyError, TypeError):
      ssh_port = "unknown"

  print(f"\n✅ Pod is ready! Connect via SSH:")
  print(f"ssh -p {ssh_port} root@your-runpod-proxy-endpoint.runpod.net")


if __name__ == "__main__":
  main()
