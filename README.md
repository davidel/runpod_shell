# RunPod Deploy CLI

A Python command-line interface to easily create, configure, and launch RunPod instances with persistent network volumes, customized container environments, and automatic SSH setup.

## Features

- **Argparse CLI Support**: Configure image, volume, GPU type, ports, environment variables, and packages via command-line arguments.
- **Smart SSH Key Auto-Detection**: Searches for standard SSH public keys (`id_rsa.pub`, `id_ed25519.pub`, `id_ecdsa.pub`, `id_dsa.pub`) in your local `~/.ssh/` directory automatically.
- **Smart python packages installation**: Reads a local `requirements.txt` file (or custom path) and automatically sets up a python virtual environment (`venv`) on your persistent network volume.
- **Container Customization**: Installs custom apt packages and sets environment variables in the container.
- **Boot Status Polling**: Waits for the instance to initialize and prints the exact command needed to connect via SSH.

---

## Prerequisites

1. **Install python dependencies**:
   ```bash
   pip install runpod
   ```

2. **RunPod API Key**:
   Obtain an API key from your RunPod settings and expose it:
   ```bash
   export RUNPOD_API_KEY="your_runpod_api_key"
   ```

3. **SSH Public Key**:
   Ensure you have an SSH public key generated locally at `~/.ssh/id_rsa.pub` or another standard name, or pass one manually using the `--ssh-key-path` flag.

---

## Usage

Run the script using python:

```bash
python3 cli.py [OPTIONS]
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--api-key` | *None* | RunPod API key (or use `RUNPOD_API_KEY` env var) |
| `--name` | `persistent-worker` | Name of the RunPod instance |
| `--volume-id` | *None* | Persistent Network Volume ID to mount |
| `--image-name` | `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404` | Base image for the container |
| `--gpu-type` | `NVIDIA GeForce RTX 4090` | GPU type ID to provision |
| `--volume-size` | `50` | Container disk size in GB |
| `--ssh-key-path` | *None* | Path to public key (checks default paths if omitted) |
| `--requirements-path` | *None* | Path to `requirements.txt` file |
| `--apt-packages` | `screen`, `curl`, `htop`, `ffmpeg`, `git` | Additional packages to install |
| `--apt-packages-file` | *None* | Path to a file containing extra apt packages to install |
| `--env` | *None* | Environment variables (e.g. `KEY=VALUE`) |
| `--env-file` | *None* | Path to a `.env` file containing environment variables |
| `--ports` | `22/tcp` | Container ports to expose |
| `--cloud-type` | `SECURE` | Type of cloud network (`SECURE`, `COMMUNITY`, or `ALL`) |
| `--gpu-count` | `1` | Number of GPUs to allocate |
| `--container-disk-size` | `30` | Container local disk size in GB |
| `--volume-mount-path` | `/workspace` | Path inside container where the network volume is mounted |

---

## Examples

### 1. Simple Launch
Launches a PyTorch container with default settings and your default SSH key:
```bash
python3 cli.py
```

### 2. Attach a Network Volume and Install Requirements
Mounts your persistent storage volume `vol-abc123xyz` and installs packages from `requirements.txt` into a persistent virtual environment (`/workspace/venv`):
```bash
python3 cli.py --volume-id "vol-abc123xyz" --requirements-path requirements.txt
```

### 3. Fully Customized Environment
Specify a custom image, GPU, extra apt packages, and environment variables:
```bash
python3 cli.py \
  --image-name "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-ubuntu22.04" \
  --gpu-type "NVIDIA RTX A6000" \
  --apt-packages screen git wget htop \
  --env CLOUDFLARE_API_KEY="your_cloudflare_key" MY_CUSTOM_VAR="hello"
```

### 4. Deploy using an Environment File
Load credentials (e.g. Cloudflare and GCS keys) from a local `.env` file and override or augment them via command line options:
```bash
python3 cli.py --env-file secrets.env --env RUN_ID="run_42"
```

### 5. Deploy using an Apt Packages File
Specify a file containing one package per line to install:
```bash
python3 cli.py --apt-packages-file apt-packages.txt
```
