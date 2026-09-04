import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch, MagicMock

import runpod_shell.ssh_runner as ssh_runner


class TestSSHRunner(unittest.TestCase):

  @patch("pathlib.Path.exists", autospec=True)
  def test_find_ssh_private_key_explicit(self, mock_exists):
    mock_exists.return_value = True
    key = ssh_runner.find_ssh_private_key(explicit_private_key_path="~/.ssh/custom_key")
    self.assertEqual(key, Path("~/.ssh/custom_key").expanduser())

  @patch("pathlib.Path.exists", autospec=True)
  def test_find_ssh_private_key_explicit_missing(self, mock_exists):
    mock_exists.return_value = False
    with self.assertRaises(FileNotFoundError):
      ssh_runner.find_ssh_private_key(explicit_private_key_path="~/.ssh/missing_key")

  @patch("pathlib.Path.exists", autospec=True)
  def test_find_ssh_private_key_from_pub(self, mock_exists):
    def exists_side_effect(path_obj):
      return str(path_obj).endswith("id_ed25519")

    mock_exists.side_effect = exists_side_effect
    key = ssh_runner.find_ssh_private_key(public_key_path="~/.ssh/id_ed25519.pub")
    self.assertEqual(key, Path("~/.ssh/id_ed25519").expanduser())

  @patch("pathlib.Path.exists", autospec=True)
  def test_find_ssh_private_key_default(self, mock_exists):
    def exists_side_effect(path_obj):
      p = str(path_obj)
      return p.endswith(".ssh") or p.endswith("id_rsa")

    mock_exists.side_effect = exists_side_effect
    key = ssh_runner.find_ssh_private_key()
    self.assertEqual(key, Path.home() / ".ssh" / "id_rsa")

  def test_build_ssh_cmd(self):
    cmd = ssh_runner.build_ssh_cmd("1.2.3.4", 2222, "echo hello", private_key_path=Path("/key"), tty=True)
    self.assertIn("-p", cmd)
    self.assertIn("2222", cmd)
    self.assertIn("-t", cmd)
    self.assertIn("-i", cmd)
    self.assertIn("/key", cmd)
    self.assertIn("root@1.2.3.4", cmd)
    self.assertIn("echo hello", cmd)

  def test_build_scp_cmd(self):
    cmd = ssh_runner.build_scp_cmd(Path("/local/script.sh"), "/remote/script.sh", "1.2.3.4", 2222, private_key_path=Path("/key"))
    self.assertIn("-P", cmd)
    self.assertIn("2222", cmd)
    self.assertIn("-i", cmd)
    self.assertIn("/key", cmd)
    self.assertIn("/local/script.sh", cmd)
    self.assertIn("root@1.2.3.4:/remote/script.sh", cmd)

  @patch("subprocess.run")
  def test_wait_for_ssh_success(self, mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    res = ssh_runner.wait_for_ssh("1.2.3.4", 22, timeout=5, interval=0.1)
    self.assertTrue(res)

  @patch("time.sleep")
  @patch("subprocess.run")
  def test_wait_for_ssh_timeout(self, mock_run, mock_sleep):
    mock_run.return_value = MagicMock(returncode=1)
    with self.assertRaises(TimeoutError):
      ssh_runner.wait_for_ssh("1.2.3.4", 22, timeout=0.1, interval=0.05)

  @patch("subprocess.run")
  def test_wait_for_setup_success(self, mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    res = ssh_runner.wait_for_setup("1.2.3.4", 22, timeout=5, interval=0.1)
    self.assertTrue(res)

  @patch("pathlib.Path.exists", autospec=True)
  @patch("runpod_shell.ssh_runner.wait_for_ssh")
  @patch("runpod_shell.ssh_runner.wait_for_setup")
  @patch("subprocess.run")
  def test_execute_remote_script_detach(self, mock_run, mock_wait_setup, mock_wait_ssh, mock_exists):
    mock_exists.return_value = True

    # First call: scp (success)
    # Second call: launcher script (prints PID and LOG_FILE)
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),
        MagicMock(returncode=0, stdout="PID:12345\nLOG_FILE:/workspace/logs/job.log\nJOB_ID:job-1\n", stderr="")
    ]

    res = ssh_runner.execute_remote_script(
        host="1.2.3.4",
        port=22,
        script_path="train.py",
        script_args="--epochs 5",
        detach=True
    )

    self.assertEqual(res["pid"], "12345")
    self.assertEqual(res["log_file"], "/workspace/logs/job.log")
    self.assertEqual(res["exit_code"], 0)

  @patch("pathlib.Path.exists", autospec=True)
  @patch("runpod_shell.ssh_runner.wait_for_ssh")
  @patch("runpod_shell.ssh_runner.wait_for_setup")
  @patch("subprocess.run")
  def test_execute_remote_script_foreground(self, mock_run, mock_wait_setup, mock_wait_ssh, mock_exists):
    mock_exists.return_value = True

    # 1. scp
    # 2. launcher
    # 3. tail -f (streaming)
    # 4. exit_code read
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),
        MagicMock(returncode=0, stdout="PID:12345\nLOG_FILE:/workspace/logs/job.log\nJOB_ID:job-1\n", stderr=""),
        MagicMock(returncode=0),
        MagicMock(returncode=0, stdout="0\n")
    ]

    res = ssh_runner.execute_remote_script(
        host="1.2.3.4",
        port=22,
        script_path="train.py",
        detach=False
    )

    self.assertEqual(res["pid"], "12345")
    self.assertEqual(res["exit_code"], 0)

  @patch("subprocess.run")
  def test_list_remote_jobs(self, mock_run):
    sample_jobs = [
        {"job_id": "job-1", "pid": 1234, "status": "RUNNING", "started_at": 100}
    ]
    mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(sample_jobs))

    jobs = ssh_runner.list_remote_jobs("1.2.3.4", 22)
    self.assertEqual(len(jobs), 1)
    self.assertEqual(jobs[0]["job_id"], "job-1")

  @patch("runpod_shell.ssh_runner.list_remote_jobs")
  @patch("subprocess.run")
  def test_view_remote_logs_follow(self, mock_run, mock_list):
    mock_list.return_value = [
        {"job_id": "job-1", "log_file": "/workspace/logs/job-1.log"}
    ]
    ssh_runner.view_remote_logs("1.2.3.4", 22, job_id="job-1", follow=True)
    mock_run.assert_called_once()
    called_cmd = mock_run.call_args[0][0]
    self.assertIn("-t", called_cmd)
    self.assertIn("tail -n 50 -f '/workspace/logs/job-1.log'", called_cmd)

  @patch("runpod_shell.ssh_runner.list_remote_jobs")
  @patch("subprocess.run")
  def test_kill_remote_job(self, mock_run, mock_list):
    mock_list.return_value = [
        {"job_id": "job-1", "pid": 12345}
    ]
    mock_run.return_value = MagicMock(returncode=0, stdout="KILLED\n")
    ssh_runner.kill_remote_job("1.2.3.4", 22, "job-1", signal_name="SIGKILL")
    mock_run.assert_called_once()
    called_cmd = mock_run.call_args[0][0]
    self.assertIn("SIGKILL", called_cmd[-1])


if __name__ == "__main__":
  unittest.main()
