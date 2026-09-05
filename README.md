# RunPod Shell CLI

A Python command-line interface to manage RunPod instances (create, list, stop, and terminate pods) with optional persistent network volumes, customized container environments, and automatic SSH setup.

## Features

- **Docker-like Subcommands**: Simple interface to `create`, `list`, `stop`, `terminate`, `templates`, and list `gpus`.
- **Automatic Pod Memory**: Automatically remembers the last created pod ID in `~/.config/runpod_shell/.last_pod_id` (overrideable with `RUNPOD_SHELL_CONFIG_DIR` or `RUNPOD_SHELL_LAST_POD_ID_FILE`). All pod commands (`exec`, `ps`, `logs`, `kill`, `stop`, `terminate`) work seamlessly without having to re-type the pod ID.
- **In-Memory Secret & Environment Injection**: Pass sensitive secrets (e.g. S3/GCS keys, R2 tokens) into remote scripts in-memory via SSH with `--env` / `-e` or `--env-file` without persisting credentials to the remote pod disk.
- **Graceful Job Termination**: Kills remote jobs by sending `SIGTERM` first, monitoring exit status, and escalating to `SIGKILL` after a configurable timeout (default: 15s).
- **Template Management & Image Resolution**: Browse and filter pod templates using `templates`, and launch pods via `--template-id` with automatic base image resolution.
- **GPU Querying & Resolution**: List all available GPU types using the `gpus` subcommand with regex filtering, and use case-insensitive, unique substring, or fuzzy matching auto-resolution for `--gpu-type` values (e.g. `4090` auto-resolves to `NVIDIA GeForce RTX 4090`).
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

   *(Optional)* Configure or isolate the pod ID persistence directory (defaults to `~/.config/runpod_shell`):
   ```bash
   export RUNPOD_SHELL_CONFIG_DIR="/path/to/config"
   # or specify the exact file path:
   export RUNPOD_SHELL_LAST_POD_ID_FILE="/path/to/.last_pod_id"
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
| `--template-id` | *None* | Pod Template ID to deploy (auto-resolves container image name) |
| `--image-name` | `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404` | Base image for the container (optional if `--template-id` is provided) |
| `--gpu-type` | `NVIDIA GeForce RTX 4090` | GPU type ID to provision (supports case-insensitive, unique substring, and fuzzy matching, e.g. `4090`) |
| `--gpu-count` | `1` | Number of GPUs to allocate |
| `--volume-id` | *None* | Persistent Network Volume ID to mount |
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

> **Tip:** Creating a pod automatically saves its ID to `~/.config/runpod_shell/.last_pod_id` so subsequent commands (`exec`, `ps`, `logs`, etc.) can be run without passing the pod ID.

---

### 2. `list`
Lists all active and stopped pods associated with your account, showing Pod ID, Name, Status, GPU type, and connection endpoint.

```bash
runpod-shell list
```

---

### 3. `templates`
Lists available pod templates associated with your account and public library, showing Template ID, Name, and Image name. Supports optional regex filtering.

```bash
# List all templates
runpod-shell templates

# Filter templates by pattern (case-insensitive regex)
runpod-shell templates pytorch
runpod-shell templates "vllm|tgi"
```

---

### 4. `stop`
Stops a running pod (releases GPU resources, but retains data on the persistent network volume). If `<pod-id>` is omitted, automatically targets the last created pod.

```bash
# Stop the last created pod
runpod-shell stop

# Or specify a pod explicitly
runpod-shell stop <pod-id>
runpod-shell stop --pod <pod-id>
```

---

### 5. `terminate`
Deletes a pod and releases all associated resources. If `<pod-id>` is omitted, automatically targets the last created pod. Also clears the cached `.last_pod_id` if it matches.

```bash
# Terminate the last created pod
runpod-shell terminate

# Or specify a pod explicitly
runpod-shell terminate <pod-id>
runpod-shell terminate --pod <pod-id>
```

---

### 6. `gpus`
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

### 7. `exec`
Uploads and executes an arbitrary local script on an active pod via SSH. Supports foreground streaming or detached background execution, in-memory environment variable injection, and default pod resolution.

```bash
# Execute on the last created pod
runpod-shell exec <script-path> [OPTIONS]

# Specify pod ID explicitly
runpod-shell exec <pod-id> <script-path> [OPTIONS]
runpod-shell exec --pod <pod-id> <script-path> [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `--pod` | *None* | Target pod ID (defaults to last created pod) |
| `-e`, `--env` | *None* | Environment variable to inject into the remote process in-memory (`KEY=VALUE` or `KEY` to inherit value from local environment). Can accept multiple variables or be repeated. |
| `--env-file` | *None* | Path to local `.env` file to inject into the remote process in-memory without persisting credentials to remote disk |
| `--script-args` | `""` | String arguments to pass to the script |
| `-d`, `--detach` | `False` | Run script in background without waiting / streaming |
| `--ssh-private-key-path` | *None* | Path to private SSH key (auto-detected if omitted) |
| `--ssh-config` | *None* (or `$RUNPOD_SSH_CONFIG`) | Path to custom SSH config file (e.g. `/dev/null`, or `system`) |
| `--no-wait-for-setup` | `False` | Do not wait for container disk setup to complete |
| `--ssh-timeout` | `180` | Max seconds to wait for SSH and setup readiness |

---

### 8. `ps`
Lists remote processes and background jobs managed by `runpod-shell` on the pod, including Job ID, PID, running/completed/failed status, start time, duration, and log file path. If `<pod-id>` is omitted, automatically targets the last created pod.

```bash
# List jobs on the last created pod
runpod-shell ps

# Or specify a pod explicitly
runpod-shell ps <pod-id>
runpod-shell ps --pod <pod-id>
```

| Flag | Default | Description |
|---|---|---|
| `--pod` | *None* | Target pod ID (defaults to last created pod) |
| `--ssh-private-key-path` | *None* | Path to private SSH key (auto-detected if omitted) |
| `--ssh-config` | *None* (or `$RUNPOD_SSH_CONFIG`) | Path to custom SSH config file (e.g. `/dev/null`, or `system`) |

---

### 9. `logs`
Inspects remote execution logs with full display (`cat`), tailing the last N lines, or live streaming (`-f`). If `<pod-id>` is omitted, automatically targets the last created pod.

```bash
# Follow logs on the last created pod (defaults to latest active job if job-id omitted)
runpod-shell logs -f

# View full logs of a specific job on the default pod
runpod-shell logs <job-id>

# Show last 100 lines for a specific pod and job
runpod-shell logs <pod-id> <job-id> -n 100
runpod-shell logs --pod <pod-id> <job-id> -f
```

| Flag | Default | Description |
|---|---|---|
| `--pod` | *None* | Target pod ID (defaults to last created pod) |
| `-n`, `--tail` | *None* | Number of lines to display from end of log |
| `-f`, `--follow` | `False` | Follow log output in real-time |
| `--ssh-private-key-path` | *None* | Path to private SSH key (auto-detected if omitted) |
| `--ssh-config` | *None* (or `$RUNPOD_SSH_CONFIG`) | Path to custom SSH config file (e.g. `/dev/null`, or `system`) |

---

### 10. `kill`
Terminates a remote job and its entire process group. By default, sends `SIGTERM` first, monitors process termination, and escalates to `SIGKILL` if the job has not exited within `--timeout` seconds. If `<pod-id>` is omitted, automatically targets the last created pod.

```bash
# Kill a job on the last created pod
runpod-shell kill <job-id-or-pid> [OPTIONS]

# Specify pod ID explicitly
runpod-shell kill <pod-id> <job-id-or-pid> [OPTIONS]
runpod-shell kill --pod <pod-id> <job-id-or-pid> [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `--pod` | *None* | Target pod ID (defaults to last created pod) |
| `-s`, `--signal` | `SIGTERM` | Initial signal to send (e.g. `SIGTERM`, `SIGKILL`) |
| `-t`, `--timeout` | `15.0` | Timeout in seconds to wait before escalating from SIGTERM to SIGKILL |
| `--ssh-private-key-path` | *None* | Path to private SSH key (auto-detected if omitted) |
| `--ssh-config` | *None* (or `$RUNPOD_SSH_CONFIG`) | Path to custom SSH config file (e.g. `/dev/null`, or `system`) |

---

## Examples

### Launch with default settings
```bash
runpod-shell create
# The newly created Pod ID is automatically remembered!
```

### Launch using a Template ID
```bash
# Search for templates
runpod-shell templates pytorch

# Create pod from template
runpod-shell create --template-id "runpod-pytorch" --gpu-type 4090
```

### Launch attaching a Network Volume and Python requirements
```bash
runpod-shell create --volume-id "vol-abc123xyz" --requirements-path requirements.txt
```

### Run a script with in-memory secrets and monitor jobs
```bash
# Run detached in background, injecting credentials directly from local env without writing to remote disk
runpod-shell exec -d -e R2_TOKEN R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY ./train.py

# Check process status on default pod
runpod-shell ps

# Follow logs in real-time
runpod-shell logs -f

# Terminate gracefully (sends SIGTERM, escalates to SIGKILL if still running after 15s)
runpod-shell kill job-1788613220-1817e4
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
runpod-shell exec ./train.py
```

Or per-command using `--ssh-config`:

```bash
runpod-shell exec ./train.py --ssh-config /dev/null
```
