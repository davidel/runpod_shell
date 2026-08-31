import sys
from unittest.mock import MagicMock
# Mock runpod module to avoid ModuleNotFoundError when importing cli
sys.modules['runpod'] = MagicMock()

import unittest
from unittest.mock import patch, mock_open
from pathlib import Path

# Import the module under test
import runpod_deploy.cli as cli


class TestRunPodDeployCLI(unittest.TestCase):

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

  @patch("runpod_deploy.cli.get_ssh_key")
  @patch("runpod_deploy.cli.read_requirements")
  @patch("runpod_deploy.cli.read_apt_packages_file")
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

    docker_args = kwargs["docker_args"]
    self.assertIn(r"echo 'importlib-metadata==6.7.0; python_version < '\''3.8'\''' > /workspace/requirements.txt", docker_args)


if __name__ == "__main__":
  unittest.main()
