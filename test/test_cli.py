import sys
from unittest.mock import MagicMock
# Mock runpod module to avoid ModuleNotFoundError when importing cli
sys.modules['runpod'] = MagicMock()

import base64
from pathlib import Path
import re
import unittest
from unittest.mock import patch, mock_open

# Import the module under test
import runpod_shell.cli as cli


class TestRunPodShellCLI(unittest.TestCase):

  @patch("pathlib.Path.exists", autospec=True)
  @patch("builtins.open", new_callable=mock_open, read_data="ssh-rsa AAAAB3...")
  def test_get_ssh_key_explicit(self, mock_file, mock_exists):
    mock_exists.return_value = True
    key = cli.get_ssh_key("~/.ssh/id_ed25519.pub")
    self.assertEqual(key, "ssh-rsa AAAAB3...")
    mock_file.assert_called_once_with(Path("~/.ssh/id_ed25519.pub").expanduser(), 'r')

  def test_get_ssh_key_explicit_not_found(self):
    with patch("pathlib.Path.exists", autospec=True, return_value=False):
      with self.assertRaises(FileNotFoundError):
        cli.get_ssh_key("~/.ssh/nonexistent.pub")

  @patch("pathlib.Path.exists", autospec=True)
  @patch("builtins.open", new_callable=mock_open, read_data="ssh-rsa default_key...")
  def test_get_ssh_key_default(self, mock_file, mock_exists):
    def exists_side_effect(path_obj):
      path_str = str(path_obj)
      if ".ssh" in path_str:
        if path_str.endswith("id_rsa.pub") or path_str.endswith(".ssh"):
          return True
      return False

    mock_exists.side_effect = exists_side_effect

    key = cli.get_ssh_key()
    self.assertEqual(key, "ssh-rsa default_key...")

  @patch("pathlib.Path.exists", autospec=True)
  @patch("builtins.open", new_callable=mock_open, read_data="numpy==1.24.3")
  def test_read_requirements_exists(self, mock_file, mock_exists):
    mock_exists.return_value = True
    content = cli.read_requirements("requirements.txt")
    self.assertEqual(content, "numpy==1.24.3")

  @patch("pathlib.Path.exists", autospec=True)
  def test_read_requirements_not_exists_default(self, mock_exists):
    mock_exists.return_value = False
    content = cli.read_requirements()
    self.assertEqual(content, "")

  @patch("pathlib.Path.exists", autospec=True)
  @patch("builtins.open", new_callable=mock_open, read_data="# Comment\nKEY=VALUE\nOTHER='quotes'\n")
  def test_parse_env_file(self, mock_file, mock_exists):
    mock_exists.return_value = True
    env_vars = cli.parse_env_file(".env")
    self.assertEqual(env_vars, {"KEY": "VALUE", "OTHER": "quotes"})

  @patch("pathlib.Path.exists", autospec=True)
  @patch("builtins.open", new_callable=mock_open, read_data="# Comment\nscreen curl\nhtop\n")
  def test_read_apt_packages_file(self, mock_file, mock_exists):
    mock_exists.return_value = True
    packages = cli.read_apt_packages_file("apt.txt")
    self.assertEqual(packages, ["screen", "curl", "htop"])

  @patch("runpod_shell.cli.wait_for_ssh")
  @patch("runpod_shell.cli.run_container_setup")
  @patch("runpod_shell.cli.get_ssh_key")
  @patch("runpod_shell.cli.read_requirements")
  @patch("runpod_shell.cli.read_apt_packages_file")
  @patch("runpod.create_pod")
  @patch("runpod.get_pod")
  @patch("time.sleep")
  def test_create_command_escaping(self, mock_sleep, mock_get_pod, mock_create_pod, mock_apt_file, mock_req, mock_ssh_key, mock_setup, mock_wait_ssh):
    mock_ssh_key.return_value = "ssh-rsa fake_public_key"
    mock_req.return_value = "importlib-metadata==6.7.0; python_version < '3.8'"
    mock_apt_file.return_value = ["git"]

    mock_create_pod.return_value = {"id": "pod-123"}
    mock_get_pod.return_value = {
        "id": "pod-123",
        "desiredStatus": "RUNNING",
        "runtime": {
            "gpus": True,
            "ports": [
                {
                    "privatePort": 22,
                    "isExternal": 12345,
                    "address": "12.34.56.78"
                }
            ]
        }
    }

    test_args = [
        "cli.py",
        "--api-key", "fake-api-key",
        "create",
        "--name", "test-worker",
        "--image-name", "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404",
        "--pip-packages", "scipy"
    ]

    with patch.object(sys, "argv", test_args):
      cli.main()

    mock_create_pod.assert_called_once()
    kwargs = mock_create_pod.call_args[1]

    self.assertEqual(kwargs["name"], "test-worker")
    self.assertEqual(kwargs["gpu_count"], 1)
    self.assertEqual(kwargs["min_vcpu_count"], 4)
    self.assertEqual(kwargs["min_memory_in_gb"], 8)
    self.assertEqual(kwargs["volume_mount_path"], "/workspace")
    self.assertNotIn("docker_args", kwargs)

    mock_wait_ssh.assert_called_once()
    mock_setup.assert_called_once()
    setup_kwargs = mock_setup.call_args[1]
    setup_script = setup_kwargs["setup_script_content"]
    self.assertIn("echo 'importlib-metadata==6.7.0; python_version < '\\''3.8'\\''' > \"/workspace/requirements.txt\"", setup_script)
    self.assertIn('echo "source $VENV_DIR/bin/activate" >> /root/.bashrc', setup_script)

  @patch("subprocess.run")
  @patch("runpod_shell.cli.wait_for_ssh")
  @patch("runpod_shell.cli.get_ssh_key")
  @patch("runpod_shell.cli.read_requirements")
  @patch("runpod_shell.cli.read_apt_packages_file")
  @patch("runpod.create_pod")
  @patch("runpod.get_pod")
  @patch("time.sleep")
  def test_create_command_custom_vcpu_and_memory(self, mock_sleep, mock_get_pod, mock_create_pod, mock_apt_file, mock_req, mock_ssh_key, mock_wait_ssh, mock_sub_run):
    mock_ssh_key.return_value = "ssh-rsa fake_public_key"
    mock_req.return_value = ""
    mock_apt_file.return_value = []

    mock_create_pod.return_value = {"id": "pod-123"}
    mock_get_pod.return_value = {
        "id": "pod-123",
        "desiredStatus": "RUNNING",
        "runtime": {
            "gpus": True,
            "ports": [
                {
                    "privatePort": 22,
                    "isExternal": 12345,
                    "address": "12.34.56.78"
                }
            ]
        }
    }

    test_args = [
        "cli.py",
        "--api-key", "fake-api-key",
        "create",
        "--name", "test-worker-custom",
        "--image-name", "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404",
        "--vcpu-count", "8",
        "--memory", "16"
    ]

    with patch.object(sys, "argv", test_args):
      cli.main()

    mock_create_pod.assert_called_once()
    kwargs = mock_create_pod.call_args[1]

    self.assertEqual(kwargs["name"], "test-worker-custom")
    self.assertEqual(kwargs["min_vcpu_count"], 8)
    self.assertEqual(kwargs["min_memory_in_gb"], 16)
    self.assertNotIn("docker_args", kwargs)
    mock_wait_ssh.assert_called_once()

  @patch("sys.stderr")
  def test_fatal(self, mock_stderr):
    with self.assertRaises(ValueError):
      cli.fatal("An error occurred", exc=ValueError)
    mock_stderr.write.assert_any_call("An error occurred")

  @patch("runpod.get_gpus")
  def test_get_valid_gpus(self, mock_get_gpus):
    mock_get_gpus.return_value = [
        {"id": "NVIDIA GeForce RTX 4090", "displayName": "RTX 4090"},
        {"id": "NVIDIA RTX A6000", "displayName": "RTX A6000"}
    ]
    gpus = cli.get_valid_gpus()
    self.assertEqual(gpus, ["NVIDIA GeForce RTX 4090", "NVIDIA RTX A6000"])

  def test_resolve_gpu_type(self):
    valid = ["NVIDIA GeForce RTX 4090", "NVIDIA RTX A6000"]
    # Exact match
    self.assertEqual(cli.resolve_gpu_type("NVIDIA GeForce RTX 4090", valid), "NVIDIA GeForce RTX 4090")
    # Case-insensitive
    self.assertEqual(cli.resolve_gpu_type("nvidia geforce rtx 4090", valid), "NVIDIA GeForce RTX 4090")
    # Substring match (unique)
    self.assertEqual(cli.resolve_gpu_type("4090", valid), "NVIDIA GeForce RTX 4090")
    # Substring match (ambiguous)
    with self.assertRaises(ValueError):
      cli.resolve_gpu_type("RTX", valid)
    # Not found / Fuzzy match close suggestions
    with self.assertRaises(ValueError):
      cli.resolve_gpu_type("NVIDA 4090", valid)

  @patch("runpod.get_gpus")
  @patch("sys.stdout")
  def test_gpus_command(self, mock_stdout, mock_get_gpus):
    mock_get_gpus.return_value = [
        {"id": "RTX 4090", "displayName": "RTX 4090", "memoryInGb": 24}
    ]
    test_args = ["cli.py", "gpus"]
    with patch.object(sys, "argv", test_args):
      cli.main()
    mock_stdout.write.assert_any_call("RTX 4090                       | RTX 4090                  | 24        | N/A | N/A     | N/A      ")

  @patch("runpod.get_gpus")
  @patch("sys.stdout")
  def test_gpus_command_regex_match_id(self, mock_stdout, mock_get_gpus):
    mock_get_gpus.return_value = [
        {"id": "NVIDIA GeForce RTX 4090", "displayName": "RTX 4090", "memoryInGb": 24},
        {"id": "NVIDIA RTX A6000", "displayName": "RTX A6000", "memoryInGb": 48}
    ]
    test_args = ["cli.py", "gpus", "4090"]
    with patch.object(sys, "argv", test_args):
      cli.main()
    calls = [call[0][0] for call in mock_stdout.write.call_args_list]
    matched_lines = [line for line in calls if "4090" in line]
    unmatched_lines = [line for line in calls if "A6000" in line]
    self.assertTrue(len(matched_lines) > 0)
    self.assertEqual(len(unmatched_lines), 0)

  @patch("runpod.get_gpus")
  @patch("sys.stdout")
  def test_gpus_command_regex_match_display_name(self, mock_stdout, mock_get_gpus):
    mock_get_gpus.return_value = [
        {"id": "AMD Instinct MI300X OAM", "displayName": "MI300X", "memoryInGb": 192},
        {"id": "NVIDIA RTX A6000", "displayName": "RTX A6000", "memoryInGb": 48}
    ]
    test_args = ["cli.py", "gpus", "-r", "mi300"]
    with patch.object(sys, "argv", test_args):
      cli.main()
    calls = [call[0][0] for call in mock_stdout.write.call_args_list]
    matched_lines = [line for line in calls if "MI300X" in line]
    unmatched_lines = [line for line in calls if "A6000" in line]
    self.assertTrue(len(matched_lines) > 0)
    self.assertEqual(len(unmatched_lines), 0)

  @patch("runpod.get_gpus")
  @patch("sys.stdout")
  def test_gpus_command_regex_no_match(self, mock_stdout, mock_get_gpus):
    mock_get_gpus.return_value = [
        {"id": "RTX 4090", "displayName": "RTX 4090", "memoryInGb": 24}
    ]
    test_args = ["cli.py", "gpus", "nonexistent"]
    with patch.object(sys, "argv", test_args):
      cli.main()
    mock_stdout.write.assert_any_call("No GPUs matching pattern 'nonexistent' found.")

  @patch("runpod.get_gpus")
  def test_gpus_command_invalid_regex(self, mock_get_gpus):
    mock_get_gpus.return_value = [
        {"id": "RTX 4090", "displayName": "RTX 4090", "memoryInGb": 24}
    ]
    test_args = ["cli.py", "gpus", "["]
    with patch.object(sys, "argv", test_args):
      with self.assertRaises(ValueError):
        cli.main()

  @patch("subprocess.run")
  @patch("runpod_shell.cli.wait_for_ssh")
  @patch("runpod_shell.cli.execute_remote_script")
  @patch("runpod_shell.cli.find_ssh_private_key")
  @patch("runpod_shell.cli.get_ssh_key")
  @patch("runpod_shell.cli.read_requirements")
  @patch("runpod_shell.cli.read_apt_packages_file")
  @patch("runpod.create_pod")
  @patch("runpod.get_pod")
  @patch("time.sleep")
  def test_create_with_run_script(self, mock_sleep, mock_get_pod, mock_create_pod, mock_apt_file, mock_req, mock_ssh_key, mock_find_priv, mock_exec, mock_wait_ssh, mock_sub_run):
    mock_ssh_key.return_value = "ssh-rsa fake_public_key"
    mock_req.return_value = ""
    mock_apt_file.return_value = []
    mock_create_pod.return_value = {"id": "pod-123"}
    mock_get_pod.return_value = {
        "id": "pod-123",
        "desiredStatus": "RUNNING",
        "runtime": {
            "gpus": True,
            "ports": [{"privatePort": 22, "isExternal": 12345, "address": "12.34.56.78"}]
        }
    }
    mock_find_priv.return_value = Path("/fake/priv_key")
    mock_exec.return_value = {"job_id": "job-1", "pid": "123", "exit_code": 0}

    test_args = [
        "cli.py",
        "--api-key", "fake-api-key",
        "create",
        "--name", "test-worker",
        "--image-name", "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404",
        "--run-script", "script.sh",
        "--script-args", "--flag 1"
    ]

    with patch.object(sys, "argv", test_args):
      cli.main()

    mock_wait_ssh.assert_called_once()
    mock_exec.assert_called_once_with(
        host="12.34.56.78",
        port=12345,
        script_path="script.sh",
        script_args="--flag 1",
        detach=False,
        private_key_path=Path("/fake/priv_key"),
        wait_for_setup_flag=False,
        ssh_timeout=180,
        ssh_config_path=None
    )

  @patch("subprocess.run")
  @patch("runpod_shell.cli.wait_for_ssh")
  @patch("runpod_shell.cli.execute_remote_script")
  @patch("runpod_shell.cli.find_ssh_private_key")
  @patch("runpod_shell.cli.get_ssh_key")
  @patch("runpod_shell.cli.read_requirements")
  @patch("runpod_shell.cli.read_apt_packages_file")
  @patch("runpod.create_pod")
  @patch("runpod.get_pod")
  @patch("time.sleep")
  def test_create_with_ssh_config(self, mock_sleep, mock_get_pod, mock_create_pod, mock_apt_file, mock_req, mock_ssh_key, mock_find_priv, mock_exec, mock_wait_ssh, mock_sub_run):
    mock_ssh_key.return_value = "ssh-rsa fake_public_key"
    mock_req.return_value = ""
    mock_apt_file.return_value = []
    mock_create_pod.return_value = {"id": "pod-123"}
    mock_get_pod.return_value = {
        "id": "pod-123",
        "desiredStatus": "RUNNING",
        "runtime": {
            "gpus": True,
            "ports": [{"privatePort": 22, "isExternal": 12345, "address": "12.34.56.78"}]
        }
    }
    mock_find_priv.return_value = Path("/fake/priv_key")
    mock_exec.return_value = {"job_id": "job-1", "pid": "123", "exit_code": 0}

    test_args = [
        "cli.py",
        "--api-key", "fake-api-key",
        "create",
        "--name", "test-worker",
        "--image-name", "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404",
        "--run-script", "script.sh",
        "--ssh-config", "/dev/null"
    ]

    with patch.object(sys, "argv", test_args):
      cli.main()

    mock_wait_ssh.assert_called_once()
    mock_exec.assert_called_once_with(
        host="12.34.56.78",
        port=12345,
        script_path="script.sh",
        script_args="",
        detach=False,
        private_key_path=Path("/fake/priv_key"),
        wait_for_setup_flag=False,
        ssh_timeout=180,
        ssh_config_path="/dev/null"
    )

  @patch("runpod_shell.cli.find_ssh_private_key")
  @patch("runpod_shell.cli.execute_remote_script")
  @patch("runpod.get_pod")
  def test_exec_command(self, mock_get_pod, mock_exec, mock_find_priv):
    mock_find_priv.return_value = None
    mock_get_pod.return_value = {
        "id": "pod-123",
        "runtime": {
            "ports": [{"privatePort": 22, "isExternal": 12345, "address": "12.34.56.78"}]
        }
    }
    mock_exec.return_value = {"job_id": "job-1", "pid": "123", "exit_code": 0}

    test_args = [
        "cli.py",
        "--api-key", "fake-api-key",
        "exec",
        "pod-123",
        "script.sh",
        "--script-args", "arg1 arg2",
        "--detach",
        "--ssh-config", "/dev/null"
    ]

    with patch.object(sys, "argv", test_args):
      cli.main()

    mock_exec.assert_called_once_with(
        host="12.34.56.78",
        port=12345,
        script_path="script.sh",
        script_args="arg1 arg2",
        detach=True,
        private_key_path=None,
        wait_for_setup_flag=True,
        ssh_timeout=180,
        ssh_config_path="/dev/null"
    )

  @patch("runpod_shell.cli.find_ssh_private_key")
  @patch("runpod_shell.cli.list_remote_jobs")
  @patch("runpod.get_pod")
  @patch("sys.stdout")
  def test_ps_command(self, mock_stdout, mock_get_pod, mock_list_jobs, mock_find_priv):
    mock_find_priv.return_value = None
    mock_get_pod.return_value = {
        "id": "pod-123",
        "runtime": {
            "ports": [{"privatePort": 22, "isExternal": 12345, "address": "12.34.56.78"}]
        }
    }
    mock_list_jobs.return_value = [
        {
            "job_id": "job-1",
            "pid": 1234,
            "status": "RUNNING",
            "started_at_iso": "2026-09-04T12:00:00Z",
            "duration": "5m 0s",
            "script": "train.py",
            "log_file": "/workspace/logs/job-1.log"
        }
    ]

    test_args = [
        "cli.py",
        "--api-key", "fake-api-key",
        "ps",
        "pod-123",
        "--ssh-config", "/dev/null"
    ]

    with patch.object(sys, "argv", test_args):
      cli.main()

    mock_list_jobs.assert_called_once_with("12.34.56.78", 12345, private_key_path=None, ssh_config_path="/dev/null")

  @patch("runpod_shell.cli.find_ssh_private_key")
  @patch("runpod_shell.cli.view_remote_logs")
  @patch("runpod.get_pod")
  def test_logs_command(self, mock_get_pod, mock_view_logs, mock_find_priv):
    mock_find_priv.return_value = None
    mock_get_pod.return_value = {
        "id": "pod-123",
        "runtime": {
            "ports": [{"privatePort": 22, "isExternal": 12345, "address": "12.34.56.78"}]
        }
    }

    test_args = [
        "cli.py",
        "--api-key", "fake-api-key",
        "logs",
        "pod-123",
        "job-1",
        "-f",
        "--ssh-config", "/dev/null"
    ]

    with patch.object(sys, "argv", test_args):
      cli.main()

    mock_view_logs.assert_called_once_with(
        host="12.34.56.78",
        port=12345,
        job_id="job-1",
        tail_lines=None,
        follow=True,
        private_key_path=None,
        ssh_config_path="/dev/null"
    )

  @patch("runpod_shell.cli.find_ssh_private_key")
  @patch("runpod_shell.cli.kill_remote_job")
  @patch("runpod.get_pod")
  def test_kill_command(self, mock_get_pod, mock_kill, mock_find_priv):
    mock_find_priv.return_value = None
    mock_get_pod.return_value = {
        "id": "pod-123",
        "runtime": {
            "ports": [{"privatePort": 22, "isExternal": 12345, "address": "12.34.56.78"}]
        }
    }

    test_args = [
        "cli.py",
        "--api-key", "fake-api-key",
        "kill",
        "pod-123",
        "job-1",
        "-s", "SIGKILL",
        "--ssh-config", "/dev/null"
    ]

    with patch.object(sys, "argv", test_args):
      cli.main()

    mock_kill.assert_called_once_with(
        host="12.34.56.78",
        port=12345,
        target_id="job-1",
        signal_name="SIGKILL",
        private_key_path=None,
        ssh_config_path="/dev/null"
    )

  @patch("runpod_shell.cli.find_ssh_private_key")
  @patch("runpod_shell.cli.execute_remote_script")
  @patch("runpod.get_pod")
  def test_exec_with_env_ssh_config(self, mock_get_pod, mock_exec, mock_find_priv):
    mock_find_priv.return_value = None
    mock_get_pod.return_value = {
        "id": "pod-123",
        "runtime": {
            "ports": [{"privatePort": 22, "isExternal": 12345, "address": "12.34.56.78"}]
        }
    }
    mock_exec.return_value = {"job_id": "job-1", "pid": "123", "exit_code": 0}

    test_args = [
        "cli.py",
        "--api-key", "fake-api-key",
        "exec",
        "pod-123",
        "script.sh"
    ]

    with patch.dict("os.environ", {"RUNPOD_SSH_CONFIG": "/env/ssh/config"}):
      with patch.object(sys, "argv", test_args):
        cli.main()

    mock_exec.assert_called_once_with(
        host="12.34.56.78",
        port=12345,
        script_path="script.sh",
        script_args="",
        detach=False,
        private_key_path=None,
        wait_for_setup_flag=True,
        ssh_timeout=180,
        ssh_config_path="/env/ssh/config"
    )

  @patch("subprocess.run")
  @patch("runpod_shell.cli.wait_for_ssh")
  @patch("runpod_shell.cli.get_pod_template")
  @patch("runpod_shell.cli.get_ssh_key")
  @patch("runpod_shell.cli.read_requirements")
  @patch("runpod_shell.cli.read_apt_packages_file")
  @patch("runpod.create_pod")
  @patch("runpod.get_pod")
  @patch("time.sleep")
  def test_create_with_template_id(self, mock_sleep, mock_get_pod, mock_create_pod, mock_apt_file, mock_req, mock_ssh_key, mock_get_template, mock_wait_ssh, mock_sub_run):
    mock_ssh_key.return_value = "ssh-rsa fake_public_key"
    mock_req.return_value = ""
    mock_apt_file.return_value = []
    mock_get_template.return_value = {
        "id": "runpod-torch-v280",
        "name": "Runpod Pytorch 2.8.0",
        "imageName": "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404"
    }
    mock_create_pod.return_value = {"id": "pod-123"}
    mock_get_pod.return_value = {
        "id": "pod-123",
        "desiredStatus": "RUNNING",
        "runtime": {
            "gpus": True,
            "ports": [{"privatePort": 22, "isExternal": 12345, "address": "12.34.56.78"}]
        }
    }

    test_args = [
        "cli.py",
        "--api-key", "fake-api-key",
        "create",
        "--name", "test-template-worker",
        "--template-id", "runpod-torch-v280"
    ]

    with patch.object(sys, "argv", test_args):
      cli.main()

    mock_wait_ssh.assert_called_once()
    mock_create_pod.assert_called_once()
    kwargs = mock_create_pod.call_args[1]
    self.assertEqual(kwargs["name"], "test-template-worker")
    self.assertEqual(kwargs["template_id"], "runpod-torch-v280")
    self.assertEqual(kwargs["image_name"], "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404")
    self.assertNotIn("docker_args", kwargs)

  @patch("subprocess.run")
  @patch("runpod_shell.cli.wait_for_ssh")
  @patch("runpod_shell.cli.get_pod_template")
  @patch("runpod_shell.cli.get_ssh_key")
  @patch("runpod_shell.cli.read_requirements")
  @patch("runpod_shell.cli.read_apt_packages_file")
  @patch("runpod.create_pod")
  @patch("runpod.get_pod")
  @patch("time.sleep")
  def test_create_template_id_precedence_over_image_name(self, mock_sleep, mock_get_pod, mock_create_pod, mock_apt_file, mock_req, mock_ssh_key, mock_get_template, mock_wait_ssh, mock_sub_run):
    mock_ssh_key.return_value = "ssh-rsa fake_public_key"
    mock_req.return_value = ""
    mock_apt_file.return_value = []
    mock_get_template.return_value = {
        "id": "runpod-torch-v280",
        "name": "Runpod Pytorch 2.8.0",
        "imageName": "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404"
    }
    mock_create_pod.return_value = {"id": "pod-123"}
    mock_get_pod.return_value = {
        "id": "pod-123",
        "desiredStatus": "RUNNING",
        "runtime": {
            "gpus": True,
            "ports": [{"privatePort": 22, "isExternal": 12345, "address": "12.34.56.78"}]
        }
    }

    test_args = [
        "cli.py",
        "--api-key", "fake-api-key",
        "create",
        "--name", "test-precedence-worker",
        "--template-id", "runpod-torch-v280",
        "--image-name", "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"
    ]

    with patch.object(sys, "argv", test_args):
      cli.main()

    mock_wait_ssh.assert_called_once()
    mock_create_pod.assert_called_once()
    kwargs = mock_create_pod.call_args[1]
    self.assertEqual(kwargs["name"], "test-precedence-worker")
    self.assertEqual(kwargs["template_id"], "runpod-torch-v280")
    self.assertEqual(kwargs["image_name"], "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404")

  @patch("runpod_shell.cli.get_pod_template")
  @patch("runpod_shell.cli.get_ssh_key")
  @patch("runpod_shell.cli.read_requirements")
  @patch("runpod_shell.cli.read_apt_packages_file")
  def test_create_template_not_found_fails(self, mock_apt_file, mock_req, mock_ssh_key, mock_get_template):
    mock_ssh_key.return_value = "ssh-rsa fake_public_key"
    mock_req.return_value = ""
    mock_apt_file.return_value = []
    mock_get_template.return_value = None

    test_args = [
        "cli.py",
        "--api-key", "fake-api-key",
        "create",
        "--name", "test-fail-worker",
        "--template-id", "invalid-template"
    ]

    with patch.object(sys, "argv", test_args):
      with self.assertRaises(ValueError) as ctx:
        cli.main()
      self.assertIn("Template 'invalid-template' not found", str(ctx.exception))

  @patch("runpod_shell.cli.get_ssh_key")
  @patch("runpod_shell.cli.read_requirements")
  @patch("runpod_shell.cli.read_apt_packages_file")
  @patch("runpod.create_pod")
  @patch("runpod.get_pod")
  @patch("time.sleep")
  def test_create_without_template_or_image_fails(self, mock_sleep, mock_get_pod, mock_create_pod, mock_apt_file, mock_req, mock_ssh_key):
    mock_ssh_key.return_value = "ssh-rsa fake_public_key"
    mock_req.return_value = ""
    mock_apt_file.return_value = []

    test_args = [
        "cli.py",
        "--api-key", "fake-api-key",
        "create",
        "--name", "test-fail-worker"
    ]

    with patch.object(sys, "argv", test_args):
      with self.assertRaises(ValueError) as ctx:
        cli.main()
      self.assertIn("Either --template-id or --image-name must be specified.", str(ctx.exception))

  @patch("sys.stdout")
  @patch("runpod_shell.cli.get_pod_templates")
  def test_cmd_templates_listing_and_filtering(self, mock_get_templates, mock_stdout):
    mock_get_templates.return_value = [
        {
            "id": "runpod-torch-v240",
            "name": "Runpod Pytorch 2.4.0",
            "imageName": "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"
        },
        {
            "id": "runpod-torch-v280",
            "name": "Runpod Pytorch 2.8.0",
            "imageName": "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404"
        },
        {
            "id": "runpod-ubuntu",
            "name": "Runpod Ubuntu 20.04",
            "imageName": "runpod/base:0.7.0-ubuntu2004"
        }
    ]

    test_args = [
        "cli.py",
        "--api-key", "fake-api-key",
        "templates",
        "--filter", "torch"
    ]

    with patch.object(sys, "argv", test_args):
      cli.main()

    mock_get_templates.assert_called_once()
    calls = [call[0][0] for call in mock_stdout.write.call_args_list]
    matched_lines = [line for line in calls if "runpod-torch" in line]
    unmatched_lines = [line for line in calls if "runpod-ubuntu" in line]
    self.assertTrue(len(matched_lines) > 0)
    self.assertEqual(len(unmatched_lines), 0)

  @patch("runpod_shell.cli.run_graphql")
  def test_get_pod_template_direct(self, mock_graphql):
    mock_graphql.return_value = {
        "data": {
            "podTemplate": {
                "id": "runpod-torch-v280",
                "name": "Runpod Pytorch 2.8.0",
                "imageName": "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404"
            }
        }
    }
    template = cli.get_pod_template("runpod-torch-v280")
    self.assertIsNotNone(template)
    self.assertEqual(template["id"], "runpod-torch-v280")
    self.assertEqual(template["imageName"], "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404")

  @patch("runpod_shell.cli.get_pod_templates")
  @patch("runpod_shell.cli.run_graphql")
  def test_get_pod_template_fallback(self, mock_graphql, mock_get_templates):
    mock_graphql.return_value = {"data": {"podTemplate": None}}
    mock_get_templates.return_value = [
        {
            "id": "custom-template",
            "name": "Custom",
            "imageName": "custom/image:tag"
        }
    ]
    template = cli.get_pod_template("custom-template")
    self.assertIsNotNone(template)
    self.assertEqual(template["id"], "custom-template")
    self.assertEqual(template["imageName"], "custom/image:tag")

  def test_build_container_setup_script_quoting(self):
    script = cli.build_container_setup_script(
        apt_packages=["screen", "tree", "gcc"],
        requirements_content="",
        pip_packages=["scdiag[all] @ git+https://github.com/davidel/scdiag.git", "nvidia-ml-py"],
        volume_mount_path="/workspace"
    )
    self.assertIn("install 'scdiag[all] @ git+https://github.com/davidel/scdiag.git' nvidia-ml-py", script)
    self.assertIn("apt-get install -y screen tree gcc", script)

  @patch("runpod_shell.cli.wait_for_ssh")
  @patch("runpod_shell.cli.run_container_setup")
  @patch("runpod_shell.cli.get_ssh_key")
  @patch("runpod_shell.cli.read_requirements")
  @patch("runpod_shell.cli.read_apt_packages_file")
  @patch("runpod.create_pod")
  @patch("runpod.get_pod")
  @patch("time.sleep")
  def test_create_command_pip_packages_with_spaces(self, mock_sleep, mock_get_pod, mock_create_pod, mock_apt_file, mock_req, mock_ssh_key, mock_setup, mock_wait_ssh):
    mock_ssh_key.return_value = "ssh-rsa fake_public_key"
    mock_req.return_value = ""
    mock_apt_file.return_value = []
    mock_create_pod.return_value = {"id": "pod-123"}
    mock_get_pod.return_value = {
        "id": "pod-123",
        "desiredStatus": "RUNNING",
        "runtime": {
            "gpus": True,
            "ports": [{"privatePort": 22, "isExternal": 12345, "address": "12.34.56.78"}]
        }
    }
    test_args = [
        "cli.py",
        "--api-key", "fake-api-key",
        "create",
        "--name", "test-worker",
        "--image-name", "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404",
        "--pip-packages", "scdiag[all] @ git+https://github.com/davidel/scdiag.git", "nvidia-ml-py"
    ]
    with patch.object(sys, "argv", test_args):
      cli.main()
    mock_create_pod.assert_called_once()
    kwargs = mock_create_pod.call_args[1]
    self.assertNotIn("docker_args", kwargs)
    mock_wait_ssh.assert_called_once()
    mock_setup.assert_called_once()
    setup_kwargs = mock_setup.call_args[1]
    setup_script = setup_kwargs["setup_script_content"]
    self.assertIn("install 'scdiag[all] @ git+https://github.com/davidel/scdiag.git' nvidia-ml-py", setup_script)

  @patch("subprocess.run")
  @patch("runpod_shell.cli.wait_for_ssh")
  @patch("runpod_shell.cli.get_ssh_key")
  @patch("runpod_shell.cli.read_requirements")
  @patch("runpod_shell.cli.read_apt_packages_file")
  @patch("runpod.create_pod")
  @patch("runpod.get_pod")
  @patch("time.sleep")
  def test_create_with_explicit_docker_args(self, mock_sleep, mock_get_pod, mock_create_pod, mock_apt_file, mock_req, mock_ssh_key, mock_wait_ssh, mock_sub_run):
    mock_ssh_key.return_value = "ssh-rsa fake_public_key"
    mock_req.return_value = ""
    mock_apt_file.return_value = []
    mock_create_pod.return_value = {"id": "pod-123"}
    mock_get_pod.return_value = {
        "id": "pod-123",
        "desiredStatus": "RUNNING",
        "runtime": {
            "ports": [{"privatePort": 22, "publicPort": 12345, "ip": "12.34.56.78"}]
        }
    }
    test_args = [
        "cli.py",
        "--api-key", "fake-api-key",
        "create",
        "--name", "test-custom-docker",
        "--image-name", "custom/image:tag",
        "--docker-args", "bash -c 'sleep 3600'"
    ]
    with patch.object(sys, "argv", test_args):
      cli.main()
    mock_create_pod.assert_called_once()
    kwargs = mock_create_pod.call_args[1]
    self.assertEqual(kwargs.get("docker_args"), "bash -c 'sleep 3600'")

  @patch("subprocess.run")
  @patch("runpod_shell.cli.wait_for_ssh")
  @patch("runpod_shell.cli.get_ssh_key")
  @patch("runpod_shell.cli.read_requirements")
  @patch("runpod_shell.cli.read_apt_packages_file")
  @patch("runpod.create_pod")
  @patch("runpod.get_pod")
  @patch("time.sleep")
  def test_create_with_custom_volume_mount_path(self, mock_sleep, mock_get_pod, mock_create_pod, mock_apt_file, mock_req, mock_ssh_key, mock_wait_ssh, mock_sub_run):
    mock_ssh_key.return_value = "ssh-rsa fake_public_key"
    mock_req.return_value = ""
    mock_apt_file.return_value = []
    mock_create_pod.return_value = {"id": "pod-123"}
    mock_get_pod.return_value = {
        "id": "pod-123",
        "desiredStatus": "RUNNING",
        "runtime": {
            "ports": [{"privatePort": 22, "publicPort": 12345, "ip": "12.34.56.78"}]
        }
    }
    test_args = [
        "cli.py",
        "--api-key", "fake-api-key",
        "create",
        "--name", "test-custom-mount",
        "--image-name", "custom/image:tag",
        "--volume-size", "150",
        "--volume-mount-path", "/custom/mount"
    ]
    with patch.object(sys, "argv", test_args):
      cli.main()
    mock_create_pod.assert_called_once()
    kwargs = mock_create_pod.call_args[1]
    self.assertEqual(kwargs.get("volume_in_gb"), 150)
    self.assertEqual(kwargs.get("volume_mount_path"), "/custom/mount")

  def test_get_pod_ssh_endpoint_graphql_fields(self):
    pod_info = {
        "runtime": {
            "ports": [
                {
                    "ip": "1.2.3.4",
                    "privatePort": 22,
                    "publicPort": 54321
                }
            ]
        }
    }
    host, port = cli.get_pod_ssh_endpoint(pod_info)
    self.assertEqual(host, "1.2.3.4")
    self.assertEqual(port, 54321)

  @patch("runpod.get_pods")
  @patch("sys.stdout")
  def test_cmd_list_with_graphql_endpoint(self, mock_stdout, mock_get_pods):
    mock_get_pods.return_value = [
        {
            "id": "pod-123",
            "name": "my-worker",
            "desiredStatus": "RUNNING",
            "machine": {
                "gpuDisplayName": "RTX 4090"
            },
            "gpuCount": 1,
            "runtime": {
                "ports": [
                    {
                        "ip": "1.2.3.4",
                        "privatePort": 22,
                        "publicPort": 54321
                    }
                ]
            }
        }
    ]
    test_args = ["cli.py", "--api-key", "fake-api-key", "list"]
    with patch.object(sys, "argv", test_args):
      cli.main()
    calls = [call[0][0] for call in mock_stdout.write.call_args_list if call[0]]
    output = "".join(calls)
    self.assertIn("1.2.3.4:54321", output)
    self.assertIn("1x RTX 4090", output)

  @patch("runpod_shell.cli.get_ssh_key")
  @patch("runpod_shell.cli.read_requirements")
  @patch("runpod_shell.cli.read_apt_packages_file")
  @patch("runpod.create_pod")
  @patch("runpod.get_pod")
  @patch("time.sleep")
  def test_create_polling_failed_status(self, mock_sleep, mock_get_pod, mock_create_pod, mock_apt_file, mock_req, mock_ssh_key):
    mock_ssh_key.return_value = "ssh-rsa fake_public_key"
    mock_req.return_value = ""
    mock_apt_file.return_value = []
    mock_create_pod.return_value = {"id": "pod-123"}
    mock_get_pod.return_value = {
        "id": "pod-123",
        "desiredStatus": "FAILED"
    }
    test_args = [
        "cli.py",
        "--api-key", "fake-api-key",
        "create",
        "--name", "test-fail-worker",
        "--image-name", "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404"
    ]
    with patch.object(sys, "argv", test_args):
      with self.assertRaises(RuntimeError) as ctx:
        cli.main()
      self.assertIn("Pod initialization failed with status: FAILED", str(ctx.exception))

  @patch("runpod_shell.cli.execute_remote_script")
  def test_run_container_setup_failure(self, mock_exec):
    mock_exec.return_value = {"exit_code": 1}
    with self.assertRaises(RuntimeError) as ctx:
      cli.run_container_setup("1.2.3.4", 22, "#!/bin/bash\nexit 1")
    self.assertIn("Container setup failed with exit code: 1", str(ctx.exception))


if __name__ == "__main__":
  unittest.main()

