import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch, MagicMock

import runpod_shell.ssh_runner as ssh_runner


class TestSSHRunner(unittest.TestCase):

  def setUp(self):
    ssh_runner._ENSURED_RUNNER_HOSTS.clear()

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

    # 1. scp runner.py
    # 2. scp user script
    # 3. launcher script
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),
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
    launch_script = mock_run.call_args_list[2][0][0][-1]
    self.assertIn("python3 /tmp/.runpod_runner.py run", launch_script)
    self.assertIn('--job-id "job-1', launch_script)

  @patch("pathlib.Path.exists", autospec=True)
  @patch("runpod_shell.ssh_runner.wait_for_ssh")
  @patch("runpod_shell.ssh_runner.wait_for_setup")
  @patch("subprocess.run")
  def test_execute_remote_script_foreground(self, mock_run, mock_wait_setup, mock_wait_ssh, mock_exists):
    mock_exists.return_value = True

    # 1. scp runner.py
    # 2. scp user script
    # 3. launcher
    # 4. tail -f (streaming)
    # 5. exit_code read
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),
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
    tail_script = mock_run.call_args_list[3][0][0][-1]
    self.assertIn("-s 0.2", tail_script)

  @patch("subprocess.run")
  def test_list_remote_jobs(self, mock_run):
    sample_jobs = [
        {"job_id": "job-1", "pid": 1234, "status": "RUNNING", "started_at": 100}
    ]
    # 1. scp runner.py, 2. list command
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),
        MagicMock(returncode=0, stdout=json.dumps(sample_jobs), stderr="")
    ]

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
    self.assertNotIn("-t", called_cmd)
    self.assertIn("tail -n 50 -f '/workspace/logs/job-1.log'", called_cmd)

  @patch("runpod_shell.ssh_runner.list_remote_jobs")
  @patch("subprocess.run")
  def test_view_remote_logs_keyboard_interrupt(self, mock_run, mock_list):
    mock_list.return_value = [
        {"job_id": "job-1", "log_file": "/workspace/logs/job-1.log"}
    ]
    mock_run.side_effect = KeyboardInterrupt
    # Should handle KeyboardInterrupt gracefully without raising
    ssh_runner.view_remote_logs("1.2.3.4", 22, job_id="job-1", follow=True)
    mock_run.assert_called_once()

  @patch("subprocess.run")
  def test_kill_remote_job(self, mock_run):
    # 1. scp runner.py, 2. kill command
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),
        MagicMock(returncode=0, stdout="KILLED\n", stderr="")
    ]
    ssh_runner.kill_remote_job("1.2.3.4", 22, "job-1", signal_name="SIGKILL")
    self.assertEqual(mock_run.call_count, 2)
    called_cmd = mock_run.call_args_list[1][0][0]
    self.assertIn("SIGKILL", called_cmd[-1])
    self.assertIn("python3 /tmp/.runpod_runner.py kill", called_cmd[-1])

  @patch("subprocess.run")
  def test_ensure_remote_runner(self, mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    path1 = ssh_runner.ensure_remote_runner("1.2.3.4", 22)
    self.assertEqual(path1, "/tmp/.runpod_runner.py")
    self.assertEqual(mock_run.call_count, 1)

    # Second call should use cache
    path2 = ssh_runner.ensure_remote_runner("1.2.3.4", 22)
    self.assertEqual(path2, "/tmp/.runpod_runner.py")
    self.assertEqual(mock_run.call_count, 1)

  @patch("subprocess.run")
  def test_ensure_remote_runner_failure(self, mock_run):
    mock_run.return_value = MagicMock(returncode=1, stderr="SCP failed")
    with self.assertRaises(RuntimeError):
      ssh_runner.ensure_remote_runner("1.2.3.4", 22)

  def test_resolve_ssh_config(self):
    # Explicit config
    self.assertEqual(ssh_runner.resolve_ssh_config("/dev/null"), "/dev/null")
    self.assertEqual(ssh_runner.resolve_ssh_config(Path("/custom/config")), "/custom/config")

    # Disabled keywords
    for kw in ["none", "system", "default", "", "NONE", "DEFAULT"]:
      self.assertIsNone(ssh_runner.resolve_ssh_config(kw))

    # Env var fallback
    with patch.dict("os.environ", {"RUNPOD_SSH_CONFIG": "/env/ssh/config"}):
      self.assertEqual(ssh_runner.resolve_ssh_config(), "/env/ssh/config")

    with patch.dict("os.environ", {"RUNPOD_SSH_CONFIG": "none"}):
      self.assertIsNone(ssh_runner.resolve_ssh_config())

    with patch.dict("os.environ", {}, clear=True):
      self.assertIsNone(ssh_runner.resolve_ssh_config())

  def test_build_ssh_cmd_with_ssh_config(self):
    cmd = ssh_runner.build_ssh_cmd("1.2.3.4", 2222, ssh_config_path="/dev/null")
    self.assertIn("-F", cmd)
    idx = cmd.index("-F")
    self.assertEqual(cmd[idx + 1], "/dev/null")

  def test_build_scp_cmd_with_ssh_config(self):
    cmd = ssh_runner.build_scp_cmd(Path("/local/script.sh"), "/remote/script.sh", "1.2.3.4", 2222, ssh_config_path="/dev/null")
    self.assertIn("-F", cmd)
    idx = cmd.index("-F")
    self.assertEqual(cmd[idx + 1], "/dev/null")


if __name__ == "__main__":
  unittest.main()
