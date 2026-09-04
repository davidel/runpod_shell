# RunPod Deploy CLI

A Python command-line interface to manage RunPod instances (create, list, stop, and terminate pods) with optional persistent network volumes, customized container environments, and automatic SSH setup.

## Features

- **Docker-like Subcommands**: Simple interface to `create`, `list`, `stop`, `terminate`, and list `gpus`.
- **GPU Querying & Resolution**: List all available GPU types using the `gpus` subcommand, and use case-insensitive, unique substring, or fuzzy matching auto-resolution for `--gpu-type` values (e.g. `4090` auto-resolves to `NVIDIA GeForce RTX 4090`).
- **Smart SSH Key Auto-Detection**: Searches for standard SSH public keys (`id_rsa.pub`, `id_ed25519.pub`, `id_ecdsa.pub`, `id_dsa.pub`) in your local `~/.ssh/` directory automatically.
- **Python Virtual Environments**: Resolves packages from `requirements.txt` (or custom path) and `--pip-packages` (CLI) and installs them in a persistent virtual environment (`/workspace/venv`).
- **Container Customization**: Merges CLI and file-based apt packages (via `--apt-packages` and `--apt-packages-file`) and loads credentials from a `.env` file (via `--env-file`).
- **Real SSH Address Output**: Resolves the exact host IP and external port from RunPod to print a ready-to-use SSH connection string.

---

## Installation

1. **Install the package**:
   ```bash
   pip install .
   ```
   Or for editable development mode:
   ```bash
   pip install -e .
   ```

2. **RunPod API Key**:
   Obtain an API key from your RunPod settings and expose it:
   ```bash
   export RUNPOD_API_KEY="your_runpod_api_key"
   ```

> **Note:** Once installed, the `runpod-deploy` executable is available in your `PATH`. Alternatively, you can run commands via the Python module syntax: `python3 -m runpod_deploy <subcommand>`.

---

## Command Reference

### Global Option
Every subcommand supports passing the API key directly:
*   `--api-key`: RunPod API key (or uses the local `RUNPOD_API_KEY` env var).

---

### 1. `create`
Launches and configures a new RunPod instance.

```bash
runpod-deploy create [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `--name` | `persistent-worker` | Name of the RunPod instance |
| `--volume-id` | *None* | Persistent Network Volume ID to mount |
| `--image-name` | `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404` | Base image for the container |
| `--gpu-type` | `NVIDIA GeForce RTX 4090` | GPU type ID to provision (supports case-insensitive, unique substring, and fuzzy matching, e.g. `4090`) |
| `--gpu-count` | `1` | Number of GPUs to allocate |
| `--volume-size` | `50` | Container disk size in GB |
| `--ssh-key-path` | *None* | Path to public key (checks default paths if omitted) |
| `--requirements-path` | *None* | Path to `requirements.txt` file |
| `--pip-packages` | *None* | Extra Python packages to install |
| `--apt-packages` | *None* | Extra apt packages to install (default: `screen curl htop ffmpeg git`) |
| `--apt-packages-file` | *None* | Path to a file containing extra apt packages to install |
| `--env` | *None* | Environment variables (e.g. `KEY=VALUE`) |
| `--env-file` | *None* | Path to a `.env` file containing environment variables |
| `--ports` | `22/tcp` | Container ports to expose |
| `--cloud-type` | `SECURE` | Type of cloud network (`SECURE`, `COMMUNITY`, or `ALL`) |
| `--container-disk-size` | `30` | Container local disk size in GB |
| `--volume-mount-path` | `/workspace` | Path inside container where the network volume is mounted |
| `--vcpu-count` | `4` | Minimum number of vCPUs to allocate |
| `--memory` | `8` | Minimum CPU RAM in GB to allocate |
| `--run-script` | *None* | Path to a local script to execute on the pod via SSH once initialized |
| `--script-args` | `""` | String arguments to pass to the script |
| `-d`, `--detach` | `False` | Run script in background without waiting / streaming |
| `--ssh-private-key-path` | *None* | Path to private SSH key (auto-detected if omitted) |
| `--no-wait-for-setup` | `False` | Do not wait for container disk setup to complete before executing script |
| `--ssh-timeout` | `180` | Max seconds to wait for SSH and setup readiness |

---

### 2. `list`
Lists all active and stopped pods associated with your account, showing Pod ID, Name, Status, GPU type, and connection endpoint.

```bash
runpod-deploy list
```

---

### 3. `stop`
Stops a running pod (releases GPU resources, but retains the data on the persistent network volume).

```bash
runpod-deploy stop <pod-id>
```

---

### 4. `terminate`
Deletes a pod and releases all associated resources.

```bash
runpod-deploy terminate <pod-id>
```

---

### 5. `gpus`
Retrieves and lists all available GPU models, including display names, VRAM sizes, CUDA Cores, maximum GPU configurations, and hourly pricing (Secure vs. Community cloud).

```bash
runpod-deploy gpus
```

---

### 6. `exec`
Uploads and executes an arbitrary local script on an active pod via SSH. Supports foreground streaming or detached background execution.

```bash
runpod-deploy exec <pod-id> <script-path> [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `--script-args` | `""` | String arguments to pass to the script |
| `-d`, `--detach` | `False` | Run script in background without waiting / streaming |
| `--ssh-private-key-path` | *None* | Path to private SSH key (auto-detected if omitted) |
| `--no-wait-for-setup` | `False` | Do not wait for container disk setup to complete |
| `--ssh-timeout` | `180` | Max seconds to wait for SSH and setup readiness |

---

### 7. `ps`
Lists remote processes and background jobs managed by `runpod-deploy` on the pod, including Job ID, PID, running/completed/failed status, start time, duration, and log file path.

```bash
runpod-deploy ps <pod-id>
```

---

### 8. `logs`
Inspects remote execution logs with full display (`cat`), tailing the last N lines, or live streaming (`-f`).

```bash
# Display entire log (cat)
runpod-deploy logs <pod-id> [job-id]

# Show last 100 lines
runpod-deploy logs <pod-id> [job-id] -n 100

# Live follow log output (tail -f)
runpod-deploy logs <pod-id> [job-id] -f
```

---

### 9. `kill`
Terminates a remote job and its entire process group using a signal (defaults to `SIGTERM`).

```bash
runpod-deploy kill <pod-id> <job-id-or-pid> [--signal SIGKILL]
```

---

## Examples

### Launch with default settings
```bash
runpod-deploy create
```

### Launch attaching a Network Volume and Python requirements
```bash
runpod-deploy create --volume-id "vol-abc123xyz" --requirements-path requirements.txt
```

### Launch and automatically run a script in the background
```bash
runpod-deploy create \
  --volume-id "vol-abc123xyz" \
  --run-script ./train.py \
  --script-args "--epochs 50 --lr 1e-4" \
  --detach
```

### Execute a script on an existing pod and follow logs
```bash
# Run in background
runpod-deploy exec pod-abc123xyz ./eval.py --script-args "--model best.pt" -d

# Check process status
runpod-deploy ps pod-abc123xyz

# Follow live output
runpod-deploy logs pod-abc123xyz -f

# Terminate if needed
runpod-deploy kill pod-abc123xyz job-1757000000-a1b2c3
```

### Fully customized creation
```bash
runpod-deploy create \
  --image-name "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-ubuntu22.04" \
  --gpu-type "NVIDIA RTX A6000" \
  --gpu-count 2 \
  --env-file secrets.env \
  --pip-packages torchinfo matplotlib
```
