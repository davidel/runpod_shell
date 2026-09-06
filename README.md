# RunPod Shell CLI

A Python command-line interface to manage RunPod instances (create, list, stop, and terminate pods) with optional persistent network volumes, customized container environments, and automatic SSH setup.

## Features

- **Docker-like Subcommands**: Simple interface to `create`, `list`, `stop`, `terminate`, `templates`, `gpus`, `run`, and `exec`.
- **Automatic Pod & Job Memory**: Automatically remembers the last created pod ID in `~/.config/runpod_shell/.last_pod_id` and the last executed job ID in `~/.config/runpod_shell/.last_job_id` (overrideable with `RUNPOD_SHELL_CONFIG_DIR`, `RUNPOD_SHELL_LAST_POD_ID_FILE`, or `RUNPOD_SHELL_LAST_JOB_ID_FILE`). All pod commands (`run`, `exec`, `ps`, `logs`, `kill`, `stop`, `terminate`) work seamlessly without having to re-type the pod ID, and commands managing jobs (`logs`, `kill`) implicitly target the last executed job unless overridden with `-j` / `--job`.
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

   *(Optional)* Configure or isolate the pod and job ID persistence directory (defaults to `~/.config/runpod_shell`):
   ```bash
   export RUNPOD_SHELL_CONFIG_DIR="/path/to/config"
   # or specify the exact file paths:
   export RUNPOD_SHELL_LAST_POD_ID_FILE="/path/to/.last_pod_id"
   export RUNPOD_SHELL_LAST_JOB_ID_FILE="/path/to/.last_job_id"
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
runpod-shell templates -r "pytorch|cuda"
```

| Argument / Flag | Default | Description |
|---|---|---|
| `filter` | *None* | Optional regex pattern to filter templates by ID, Name, or Image (case-insensitive) |
| `-r`, `--regex`, `--filter` | *None* | Optional regex pattern to filter templates by ID, Name, or Image (case-insensitive) |

---

### 4. `stop`
Stops a running pod (releases GPU resources, but retains data on the persistent network volume). If `<pod-id>` is omitted, automatically targets the last created pod.

```bash
# Stop the last created pod
runpod-shell stop

# Or specify a pod explicitly
runpod-shell stop <pod-id>
runpod-shell stop -p <pod-id>
runpod-shell stop --pod <pod-id>
```

| Argument / Flag | Default | Description |
|---|---|---|
| `pod-id` | *None* | The ID of the pod to stop (optional positional, defaults to last created pod) |
| `-p`, `--pod` | *None* | The ID of the pod to stop (defaults to last created pod) |

---

### 5. `terminate`
Deletes a pod and releases all associated resources. If `<pod-id>` is omitted, automatically targets the last created pod. Also clears the cached `.last_pod_id` if it matches.

```bash
# Terminate the last created pod
runpod-shell terminate

# Or specify a pod explicitly
runpod-shell terminate <pod-id>
runpod-shell terminate -p <pod-id>
runpod-shell terminate --pod <pod-id>
```

| Argument / Flag | Default | Description |
|---|---|---|
| `pod-id` | *None* | The ID of the pod to terminate (optional positional, defaults to last created pod) |
| `-p`, `--pod` | *None* | The ID of the pod to terminate (defaults to last created pod) |

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

| Argument / Flag | Default | Description |
|---|---|---|
| `filter` | *None* | Optional regex pattern to filter GPUs by ID or Display Name (case-insensitive) |
| `-r`, `--regex`, `--filter` | *None* | Optional regex pattern to filter GPUs by ID or Display Name (case-insensitive) |

---

### 7. `exec`
Uploads and executes an arbitrary local script on an active pod via SSH. Supports foreground streaming or detached background execution, in-memory environment variable injection, and default pod resolution. Automatically remembers the executed Job ID in `~/.config/runpod_shell/.last_job_id`.

```bash
# Execute on the last created pod
runpod-shell exec <script-path> [OPTIONS]

# Specify pod ID explicitly
runpod-shell exec <pod-id> <script-path> [OPTIONS]
runpod-shell exec -p <pod-id> <script-path> [OPTIONS]
```

| Argument / Flag | Default | Description |
|---|---|---|
| `script-path` | *Required* | Path to the local script to run (or 2nd positional if pod ID is given first) |
| `pod-id` | *None* | Optional target pod ID if passed as the first positional argument |
| `-p`, `--pod` | *None* | Target pod ID (defaults to last created pod) |
| `-e`, `--env` | *None* | Environment variable to inject into the remote process in-memory (`KEY=VALUE` or `KEY` to inherit value from local environment). Can accept multiple variables or be repeated. |
| `--env-file`, `--env_file` | *None* | Path to local `.env` file to inject into the remote process in-memory without persisting credentials to remote disk. Can be specified multiple times. |
| `--script-args` | `""` | String arguments to pass to the script |
| `-d`, `--detach` | `False` | Run script in background without waiting / streaming |
| `--ssh-private-key-path` | *None* | Path to private SSH key (auto-detected if omitted) |
| `--ssh-config` | *None* (or `$RUNPOD_SSH_CONFIG`) | Path to custom SSH config file (e.g. `/dev/null`, or `system`) |
| `--no-wait-for-setup` | `False` | Do not wait for container disk setup to complete |
| `--ssh-timeout` | `180` | Max seconds to wait for SSH and setup readiness |

---

### 8. `run`
Executes an arbitrary command line directly (binary + args) on an active pod via SSH. Supports foreground streaming or detached background execution, in-memory environment variable injection, and default pod resolution. Automatically remembers the executed Job ID in `~/.config/runpod_shell/.last_job_id`.

```bash
# Run command on the last created pod
runpod-shell run python3 -c "print('hello')"
runpod-shell run nvidia-smi

# Pass arguments and options to the remote command
runpod-shell run python train.py --epochs 10 --batch-size 32

# Run detached in background on a specific pod
runpod-shell run -p <pod-id> -d python train.py
```

| Argument / Flag | Default | Description |
|---|---|---|
| `cmd` | *Required* | Command line to execute directly on the remote pod (binary + args) |
| `-p`, `--pod` | *None* | Target pod ID (defaults to last created pod) |
| `-d`, `--detach` | `False` | Run command in background without waiting / streaming |
| `-e`, `--env` | *None* | Environment variable to inject into the remote process in-memory (`KEY=VALUE` or `KEY` to inherit value from local environment). Can accept multiple variables or be repeated. |
| `--env-file`, `--env_file` | *None* | Path to local `.env` file to inject into the remote process in-memory without persisting credentials to remote disk. Can be specified multiple times. |
| `--ssh-private-key-path` | *None* | Path to private SSH key (auto-detected if omitted) |
| `--ssh-config` | *None* (or `$RUNPOD_SSH_CONFIG`) | Path to custom SSH config file (e.g. `/dev/null`, or `system`) |
| `--no-wait-for-setup` | `False` | Do not wait for container disk setup to complete |
| `--ssh-timeout` | `180` | Max seconds to wait for SSH and setup readiness |

---

### 9. `ps`
Lists remote processes and background jobs managed by `runpod-shell` on the pod, including Job ID, PID, running/completed/failed status, start time, duration, and log file path. If `<pod-id>` is omitted, automatically targets the last created pod.

```bash
# List jobs on the last created pod
runpod-shell ps

# Or specify a pod explicitly
runpod-shell ps <pod-id>
runpod-shell ps -p <pod-id>
runpod-shell ps --pod <pod-id>
```

| Argument / Flag | Default | Description |
|---|---|---|
| `pod-id` | *None* | Target pod ID (optional positional, defaults to last created pod) |
| `-p`, `--pod` | *None* | Target pod ID (defaults to last created pod) |
| `--ssh-private-key-path` | *None* | Path to private SSH key (auto-detected if omitted) |
| `--ssh-config` | *None* (or `$RUNPOD_SSH_CONFIG`) | Path to custom SSH config file (e.g. `/dev/null`, or `system`) |

---

### 10. `logs`
Inspects remote execution logs with full display (`cat`), tailing the last N lines, or live streaming (`-f`). If `-p`/`--pod` or `<pod-id>` is omitted, automatically targets the last created pod. If `-j`/`--job` or `<job-id>` is omitted, automatically targets the last executed job.

```bash
# Follow logs on the last executed job on the default pod
runpod-shell logs -f

# View full logs of a specific job on the default pod
runpod-shell logs -j <job-id>
runpod-shell logs <job-id>

# Show last 100 lines for a specific pod and job
runpod-shell logs -p <pod-id> -j <job-id> -n 100
runpod-shell logs -p <pod-id> -j <job-id> -f
```

| Argument / Flag | Default | Description |
|---|---|---|
| `-j`, `--job` | *None* | Target Job ID or PID (defaults to last executed job ID) |
| `job-id` | *None* | Target Job ID or PID (optional positional; defaults to last executed job ID) |
| `pod-id` | *None* | Target pod ID (optional positional, defaults to last created pod) |
| `-p`, `--pod` | *None* | Target pod ID (defaults to last created pod) |
| `-n`, `--tail` | *None* | Number of lines to display from end of log |
| `-f`, `--follow` | `False` | Follow log output in real-time |
| `--ssh-private-key-path` | *None* | Path to private SSH key (auto-detected if omitted) |
| `--ssh-config` | *None* (or `$RUNPOD_SSH_CONFIG`) | Path to custom SSH config file (e.g. `/dev/null`, or `system`) |

---

### 11. `kill`
Terminates a remote job and its entire process group. By default, sends `SIGTERM` first, monitors process termination, and escalates to `SIGKILL` if the job has not exited within `--timeout` seconds. If `-p`/`--pod` or `<pod-id>` is omitted, automatically targets the last created pod. If `-j`/`--job` or `<job-id>` is omitted, automatically targets the last executed job.

```bash
# Kill the last executed job on the last created pod
runpod-shell kill

# Kill a specific job on the default pod
runpod-shell kill -j <job-id-or-pid> [OPTIONS]
runpod-shell kill <job-id-or-pid> [OPTIONS]

# Specify pod ID and job ID explicitly
runpod-shell kill -p <pod-id> -j <job-id-or-pid> [OPTIONS]
```

| Argument / Flag | Default | Description |
|---|---|---|
| `-j`, `--job` | *None* | Target Job ID or PID to kill (defaults to last executed job ID) |
| `job-id-or-pid` | *None* | Target Job ID or PID to kill (optional positional, defaults to last executed job ID) |
| `pod-id` | *None* | Target pod ID (optional positional if specified before target job/PID) |
| `-p`, `--pod` | *None* | Target pod ID (defaults to last created pod) |
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

### Run commands or scripts with in-memory secrets and monitor jobs
```bash
# Execute a command directly in the background with in-memory credentials
runpod-shell run -d -e R2_TOKEN R2_ACCESS_KEY_ID python train.py --epochs 50
# Both the target Pod ID and newly launched Job ID are remembered automatically!

# Or upload and run a local script
runpod-shell exec -d ./train.py

# Check process status on default pod
runpod-shell ps

# Follow logs in real-time (automatically targets the last job ID on default pod)
runpod-shell logs -f

# Or view logs for a specific job explicitly
runpod-shell logs -j job-1788613220-1817e4 -f

# Terminate gracefully (automatically targets the last job ID, or specify with -j)
runpod-shell kill
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
