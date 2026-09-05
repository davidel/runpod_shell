# RunPod Shell CLI

A Python command-line interface to manage RunPod instances (create, list, stop, and terminate pods) with optional persistent network volumes, customized container environments, and automatic SSH setup.

## Features

- **Docker-like Subcommands**: Simple interface to `create`, `list`, `stop`, `terminate`, and list `gpus`.
- **GPU Querying & Resolution**: List all available GPU types using the `gpus` subcommand, and use case-insensitive, unique substring, or fuzzy matching auto-resolution for `--gpu-type` values (e.g. `4090` auto-resolves to `NVIDIA GeForce RTX 4090`).
- **Smart SSH Key Auto-Detection**: Searches for standard SSH public keys (`id_rsa.pub`, `id_ed25519.pub`, `id_ecdsa.pub`, `id_dsa.pub`) in your local `~/.ssh/` directory automatically.
- **SSH Isolation & Sandbox Support**: Support for custom SSH config files via `--ssh-config` or `RUNPOD_SSH_CONFIG` (e.g. `/dev/null`), preventing "Bad owner or permissions" errors when running inside Bubblewrap, containers, or restricted user namespaces.
- **Python Package Management**: Resolves packages from `requirements.txt` (or custom path) and `--pip-packages` (CLI) and installs them directly to system Python with global pip configuration, utilizing pre-installed PyTorch and CUDA runtimes without redundant downloads.
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

2. **Environment Variables**:
   Obtain an API key from your RunPod settings and expose it:
   ```bash
   export RUNPOD_API_KEY="your_runpod_api_key"
   ```

   *(Optional)* When running within sandboxed or containerized environments (e.g. Bubblewrap), bypass system SSH config ownership checks:
   ```bash
   export RUNPOD_SSH_CONFIG="/dev/null"
   ```

> **Note:** Once installed, the `runpod-shell` executable is available in your `PATH`. Alternatively, you can run commands via the Python module syntax: `python3 -m runpod_shell <subcommand>`.

---

## Command Reference

### Global Option
Every subcommand supports passing the API key directly:
*   `--api-key`: RunPod API key (or uses the local `RUNPOD_API_KEY` env var).

---

### 1. `create`
Launches and configures a new RunPod instance.

```bash
runpod-shell create [OPTIONS]
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
| `--docker-args` | *None* | Optional custom docker arguments to override container entrypoint |
| `--cloud-type` | `SECURE` | Type of cloud network (`SECURE`, `COMMUNITY`, or `ALL`) |
| `--container-disk-size` | `30` | Container local disk size in GB |
| `--volume-mount-path` | `/workspace` | Path inside container where the network volume is mounted |
| `--vcpu-count` | `4` | Minimum number of vCPUs to allocate |
| `--memory` | `8` | Minimum CPU RAM in GB to allocate |
| `--run-script` | *None* | Path to a local script to execute on the pod via SSH once initialized |
| `--script-args` | `""` | String arguments to pass to the script |
| `-d`, `--detach` | `False` | Run script in background without waiting / streaming |
| `--ssh-private-key-path` | *None* | Path to private SSH key (auto-detected if omitted) |
| `--ssh-config` | *None* (or `$RUNPOD_SSH_CONFIG`) | Path to custom SSH config file (e.g. `/dev/null`, or `system`) |
| `--no-wait-for-setup` | `False` | Do not wait for container disk setup to complete before executing script |
| `--ssh-timeout` | `180` | Max seconds to wait for SSH and setup readiness |

---

### 2. `list`
Lists all active and stopped pods associated with your account, showing Pod ID, Name, Status, GPU type, and connection endpoint.

```bash
runpod-shell list
```

---

### 3. `stop`
Stops a running pod (releases GPU resources, but retains the data on the persistent network volume).

```bash
runpod-shell stop <pod-id>
```

---

### 4. `terminate`
Deletes a pod and releases all associated resources.

```bash
runpod-shell terminate <pod-id>
```

---

### 5. `gpus`
Retrieves and lists all available GPU models, including display names, VRAM sizes, maximum GPU configurations, and hourly pricing (Secure vs. Community cloud). Supports optional regex filtering on GPU ID or Display Name (case-insensitive).

```bash
# List all GPUs
runpod-shell gpus

# Filter by regex (positional or --regex/-r/--filter flag)
runpod-shell gpus 4090
runpod-shell gpus "A100|H100"
runpod-shell gpus -r "RTX 40\d0"
```

---

### 6. `exec`
Uploads and executes an arbitrary local script on an active pod via SSH. Supports foreground streaming or detached background execution.

```bash
runpod-shell exec <pod-id> <script-path> [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `--script-args` | `""` | String arguments to pass to the script |
| `-d`, `--detach` | `False` | Run script in background without waiting / streaming |
| `--ssh-private-key-path` | *None* | Path to private SSH key (auto-detected if omitted) |
| `--ssh-config` | *None* (or `$RUNPOD_SSH_CONFIG`) | Path to custom SSH config file (e.g. `/dev/null`, or `system`) |
| `--no-wait-for-setup` | `False` | Do not wait for container disk setup to complete |
| `--ssh-timeout` | `180` | Max seconds to wait for SSH and setup readiness |

---

### 7. `ps`
Lists remote processes and background jobs managed by `runpod-shell` on the pod, including Job ID, PID, running/completed/failed status, start time, duration, and log file path.

```bash
runpod-shell ps <pod-id> [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `--ssh-private-key-path` | *None* | Path to private SSH key (auto-detected if omitted) |
| `--ssh-config` | *None* (or `$RUNPOD_SSH_CONFIG`) | Path to custom SSH config file (e.g. `/dev/null`, or `system`) |

---

### 8. `logs`
Inspects remote execution logs with full display (`cat`), tailing the last N lines, or live streaming (`-f`).

```bash
# Display entire log (cat)
runpod-shell logs <pod-id> [job-id]

# Show last 100 lines
runpod-shell logs <pod-id> [job-id] -n 100

# Live follow log output (tail -f)
runpod-shell logs <pod-id> [job-id] -f
```

| Flag | Default | Description |
|---|---|---|
| `-n`, `--tail` | *None* | Number of lines to display from end of log |
| `-f`, `--follow` | `False` | Follow log output in real-time |
| `--ssh-private-key-path` | *None* | Path to private SSH key (auto-detected if omitted) |
| `--ssh-config` | *None* (or `$RUNPOD_SSH_CONFIG`) | Path to custom SSH config file (e.g. `/dev/null`, or `system`) |

---

### 9. `kill`
Terminates a remote job and its entire process group using a signal (defaults to `SIGTERM`).

```bash
runpod-shell kill <pod-id> <job-id-or-pid> [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `-s`, `--signal` | `SIGTERM` | Signal to send (e.g. `SIGTERM`, `SIGKILL`) |
| `--ssh-private-key-path` | *None* | Path to private SSH key (auto-detected if omitted) |
| `--ssh-config` | *None* (or `$RUNPOD_SSH_CONFIG`) | Path to custom SSH config file (e.g. `/dev/null`, or `system`) |

---

## Examples

### Launch with default settings
```bash
runpod-shell create
```

### Launch attaching a Network Volume and Python requirements
```bash
runpod-shell create --volume-id "vol-abc123xyz" --requirements-path requirements.txt
```

### Launch and automatically run a script in the background
```bash
runpod-shell create \
  --volume-id "vol-abc123xyz" \
  --run-script ./train.py \
  --script-args "--epochs 50 --lr 1e-4" \
  --detach
```

### Execute a script on an existing pod and follow logs
```bash
# Run in background
runpod-shell exec pod-abc123xyz ./eval.py --script-args "--model best.pt" -d

# Check process status
runpod-shell ps pod-abc123xyz

# Follow live output
runpod-shell logs pod-abc123xyz -f

# Terminate if needed
runpod-shell kill pod-abc123xyz job-1757000000-a1b2c3
```

### Fully customized creation
```bash
runpod-shell create \
  --image-name "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-ubuntu22.04" \
  --gpu-type "NVIDIA RTX A6000" \
  --gpu-count 2 \
  --env-file secrets.env \
  --pip-packages torchinfo matplotlib
```

### Running inside a Bubblewrap Sandbox or Container
When running inside unprivileged user namespaces or Bubblewrap sandboxes, host system files under `/etc/ssh/ssh_config.d/` can trigger OpenSSH `Bad owner or permissions` errors. You can bypass them either globally:

```bash
export RUNPOD_SSH_CONFIG="/dev/null"
runpod-shell exec pod-abc123xyz ./train.py
```

Or per-command using `--ssh-config`:

```bash
runpod-shell exec pod-abc123xyz ./train.py --ssh-config /dev/null
```

