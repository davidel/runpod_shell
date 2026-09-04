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

  @patch("runpod_shell.cli.get_ssh_key")
  @patch("runpod_shell.cli.read_requirements")
  @patch("runpod_shell.cli.read_apt_packages_file")
  @patch("runpod.create_pod")
  @patch("runpod.get_pod")
  @patch("time.sleep")
  def test_create_command_escaping(self, mock_sleep, mock_get_pod, mock_create_pod, mock_apt_file, mock_req, mock_ssh_key):
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

    docker_args = kwargs["docker_args"]
    self.assertNotIn("\n", docker_args)
    self.assertNotIn('"', docker_args)
    m = re.search(r"echo\s+([A-Za-z0-9+/=]+)\s+\|\s+base64\s+-d", docker_args)
    self.assertIsNotNone(m)
    decoded_script = base64.b64decode(m.group(1)).decode("utf-8")
    self.assertIn(r"echo 'importlib-metadata==6.7.0; python_version < '\''3.8'\''' > /workspace/requirements.txt", decoded_script)
    self.assertIn('if [ -d "/workspace/venv" ] && [ -f "/root/.bashrc" ] && ! grep -q "source /workspace/venv/bin/activate" /root/.bashrc; then', decoded_script)
    self.assertIn('echo "source /workspace/venv/bin/activate" >> /root/.bashrc', decoded_script)

  @patch("runpod_shell.cli.get_ssh_key")
  @patch("runpod_shell.cli.read_requirements")
  @patch("runpod_shell.cli.read_apt_packages_file")
  @patch("runpod.create_pod")
  @patch("runpod.get_pod")
  @patch("time.sleep")
  def test_create_command_custom_vcpu_and_memory(self, mock_sleep, mock_get_pod, mock_create_pod, mock_apt_file, mock_req, mock_ssh_key):
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

  @patch("runpod_shell.cli.execute_remote_script")
  @patch("runpod_shell.cli.find_ssh_private_key")
  @patch("runpod_shell.cli.get_ssh_key")
  @patch("runpod_shell.cli.read_requirements")
  @patch("runpod_shell.cli.read_apt_packages_file")
  @patch("runpod.create_pod")
  @patch("runpod.get_pod")
  @patch("time.sleep")
  def test_create_with_run_script(self, mock_sleep, mock_get_pod, mock_create_pod, mock_apt_file, mock_req, mock_ssh_key, mock_find_priv, mock_exec):
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
        "--run-script", "script.sh",
        "--script-args", "--flag 1"
    ]

    with patch.object(sys, "argv", test_args):
      cli.main()

    mock_exec.assert_called_once_with(
        host="12.34.56.78",
        port=12345,
        script_path="script.sh",
        script_args="--flag 1",
        detach=False,
        private_key_path=Path("/fake/priv_key"),
        wait_for_setup_flag=True,
        ssh_timeout=180,
        ssh_config_path=None
    )

  @patch("runpod_shell.cli.execute_remote_script")
  @patch("runpod_shell.cli.find_ssh_private_key")
  @patch("runpod_shell.cli.get_ssh_key")
  @patch("runpod_shell.cli.read_requirements")
  @patch("runpod_shell.cli.read_apt_packages_file")
  @patch("runpod.create_pod")
  @patch("runpod.get_pod")
  @patch("time.sleep")
  def test_create_with_ssh_config(self, mock_sleep, mock_get_pod, mock_create_pod, mock_apt_file, mock_req, mock_ssh_key, mock_find_priv, mock_exec):
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
        "--run-script", "script.sh",
        "--ssh-config", "/dev/null"
    ]

    with patch.object(sys, "argv", test_args):
      cli.main()

    mock_exec.assert_called_once_with(
        host="12.34.56.78",
        port=12345,
        script_path="script.sh",
        script_args="",
        detach=False,
        private_key_path=Path("/fake/priv_key"),
        wait_for_setup_flag=True,
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


if __name__ == "__main__":
  unittest.main()
