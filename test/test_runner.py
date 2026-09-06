import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


RUNNER_PATH = Path(__file__).parent.parent / "src" / "runpod_shell" / "runner.py"


class TestRunnerScript(unittest.TestCase):

  def test_runner_run_and_list_success(self):
    with tempfile.TemporaryDirectory() as td:
      tdp = Path(td)
      script = tdp / "job.py"
      script.write_text("import time\nprint('starting task')\ntime.sleep(0.5)\nprint('finished task')\n")

      job_dir = tdp / ".runpod_jobs" / "test-job-1"
      log_file = tdp / "logs" / "test-job-1.log"
      log_file.parent.mkdir(parents=True, exist_ok=True)

      with open(log_file, "w") as lf:
        res = subprocess.run([
            sys.executable,
            str(RUNNER_PATH),
            "run",
            "--job-id", "test-job-1",
            "--script", str(script),
            "--job-dir", str(job_dir),
            "--log-file", str(log_file),
            "--work-dir", str(tdp)
        ], stdout=lf, stderr=subprocess.STDOUT)

      self.assertEqual(res.returncode, 0)
      log_content = log_file.read_text()
      self.assertIn("=== RUNPOD JOB STARTED: test-job-1", log_content)
      self.assertIn("starting task", log_content)
      self.assertIn("finished task", log_content)
      self.assertIn("=== RUNPOD JOB COMPLETED: test-job-1", log_content)
      self.assertIn("=== Exit Code:   0", log_content)

      # Verify exit_code and pid files
      self.assertEqual((job_dir / "exit_code").read_text().strip(), "0")
      self.assertTrue((job_dir / "pid").exists())
      self.assertTrue((job_dir / "child_pid").exists())

      # Verify list
      list_res = subprocess.run([
          sys.executable,
          str(RUNNER_PATH),
          "list",
          "--base-dir", str(tdp / ".runpod_jobs")
      ], capture_output=True, text=True)

      self.assertEqual(list_res.returncode, 0)
      jobs = json.loads(list_res.stdout)
      self.assertEqual(len(jobs), 1)
      self.assertEqual(jobs[0]["job_id"], "test-job-1")
      self.assertEqual(jobs[0]["status"], "COMPLETED")
      self.assertIn("duration", jobs[0])

  def test_runner_run_missing_script(self):
    with tempfile.TemporaryDirectory() as td:
      tdp = Path(td)
      missing_script = tdp / "does_not_exist.py"
      job_dir = tdp / ".runpod_jobs" / "missing-job"
      log_file = tdp / "logs" / "missing.log"
      log_file.parent.mkdir(parents=True, exist_ok=True)

      with open(log_file, "w") as lf:
        res = subprocess.run([
            sys.executable,
            str(RUNNER_PATH),
            "run",
            "--job-id", "missing-job",
            "--script", str(missing_script),
            "--job-dir", str(job_dir),
            "--log-file", str(log_file),
            "--work-dir", str(tdp)
        ], stdout=lf, stderr=subprocess.STDOUT)

      self.assertEqual(res.returncode, 127)
      self.assertEqual((job_dir / "exit_code").read_text().strip(), "127")

      list_res = subprocess.run([
          sys.executable,
          str(RUNNER_PATH),
          "list",
          "--base-dir", str(tdp / ".runpod_jobs")
      ], capture_output=True, text=True)

      jobs = json.loads(list_res.stdout)
      self.assertEqual(len(jobs), 1)
      self.assertEqual(jobs[0]["status"], "FAILED(127)")

  def test_runner_kill(self):
    with tempfile.TemporaryDirectory() as td:
      tdp = Path(td)
      script = tdp / "sleep_job.py"
      script.write_text("import time\nprint('sleeping')\ntime.sleep(60)\n")

      job_dir = tdp / ".runpod_jobs" / "kill-job"
      log_file = tdp / "logs" / "kill-job.log"
      job_dir.mkdir(parents=True, exist_ok=True)
      log_file.parent.mkdir(parents=True, exist_ok=True)

      lf = open(log_file, "w")
      proc = subprocess.Popen([
          sys.executable,
          str(RUNNER_PATH),
          "run",
          "--job-id", "kill-job",
          "--script", str(script),
          "--job-dir", str(job_dir),
          "--log-file", str(log_file),
          "--work-dir", str(tdp)
      ], stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)

      time.sleep(0.5)

      # Check running
      list_res = subprocess.run([
          sys.executable,
          str(RUNNER_PATH),
          "list",
          "--base-dir", str(tdp / ".runpod_jobs")
      ], capture_output=True, text=True)
      jobs = json.loads(list_res.stdout)
      self.assertEqual(jobs[0]["status"], "RUNNING")

      # Kill
      kill_res = subprocess.run([
          sys.executable,
          str(RUNNER_PATH),
          "kill",
          "--target", "kill-job",
          "--base-dir", str(tdp / ".runpod_jobs")
      ], capture_output=True, text=True)

      self.assertEqual(kill_res.stdout.strip(), "KILLED")
      proc.wait(timeout=5)
      lf.close()

      # Check killed status
      list_res2 = subprocess.run([
          sys.executable,
          str(RUNNER_PATH),
          "list",
          "--base-dir", str(tdp / ".runpod_jobs")
      ], capture_output=True, text=True)
      jobs2 = json.loads(list_res2.stdout)
      self.assertEqual(jobs2[0]["status"], "KILLED")

  def test_runner_kill_timeout_escalation(self):
    with tempfile.TemporaryDirectory() as td:
      tdp = Path(td)
      script = tdp / "stubborn.py"
      script.write_text(
          "#!/usr/bin/env python3\n"
          "import signal, time\n"
          "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
          "time.sleep(30)\n"
      )

      job_dir = tdp / ".runpod_jobs" / "kill-stubborn"
      log_file = tdp / "logs" / "kill-stubborn.log"
      log_file.parent.mkdir(parents=True, exist_ok=True)

      with open(log_file, "w") as lf:
        proc = subprocess.Popen([
            sys.executable,
            str(RUNNER_PATH),
            "run",
            "--job-id", "kill-stubborn",
            "--script", str(script),
            "--job-dir", str(job_dir),
            "--log-file", str(log_file),
            "--work-dir", str(tdp)
        ], stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)

      time.sleep(0.5)

      # Check running
      list_res = subprocess.run([
          sys.executable,
          str(RUNNER_PATH),
          "list",
          "--base-dir", str(tdp / ".runpod_jobs")
      ], capture_output=True, text=True)
      jobs = json.loads(list_res.stdout)
      self.assertEqual(jobs[0]["status"], "RUNNING")

      # Kill with 0.5s timeout to trigger SIGKILL escalation
      kill_res = subprocess.run([
          sys.executable,
          str(RUNNER_PATH),
          "kill",
          "--target", "kill-stubborn",
          "--timeout", "0.5",
          "--base-dir", str(tdp / ".runpod_jobs")
      ], capture_output=True, text=True)

      self.assertEqual(kill_res.stdout.strip(), "KILLED_SIGKILL")
      proc.wait(timeout=5)

      # Check killed status
      list_res2 = subprocess.run([
          sys.executable,
          str(RUNNER_PATH),
          "list",
          "--base-dir", str(tdp / ".runpod_jobs")
      ], capture_output=True, text=True)
      jobs2 = json.loads(list_res2.stdout)
      self.assertEqual(jobs2[0]["status"], "KILLED")

  def test_runner_run_script_without_shebang(self):
    with tempfile.TemporaryDirectory() as td:
      tdp = Path(td)
      script = tdp / "noshebang.py"
      # Pure python code without #!/usr/bin/env python3
      script.write_text("print('python executed without shebang')\n")

      job_dir = tdp / ".runpod_jobs" / "test-shebang-free"
      log_file = tdp / "logs" / "test-shebang-free.log"
      log_file.parent.mkdir(parents=True, exist_ok=True)

      with open(log_file, "w") as lf:
        res = subprocess.run([
            sys.executable,
            str(RUNNER_PATH),
            "run",
            "--job-id", "test-shebang-free",
            "--script", str(script),
            "--job-dir", str(job_dir),
            "--log-file", str(log_file),
            "--work-dir", str(tdp)
        ], stdout=lf, stderr=subprocess.STDOUT)

      self.assertEqual(res.returncode, 0)
      log_content = log_file.read_text()
      self.assertIn("python executed without shebang", log_content)
      self.assertIn("=== Exit Code:   0", log_content)

  def test_runner_oom_notice(self):
    with tempfile.TemporaryDirectory() as td:
      tdp = Path(td)
      script = tdp / "oom_job.py"
      script.write_text("import sys\nsys.exit(137)\n")

      job_dir = tdp / ".runpod_jobs" / "test-oom"
      log_file = tdp / "logs" / "test-oom.log"
      log_file.parent.mkdir(parents=True, exist_ok=True)

      with open(log_file, "w") as lf:
        res = subprocess.run([
            sys.executable,
            str(RUNNER_PATH),
            "run",
            "--job-id", "test-oom",
            "--script", str(script),
            "--job-dir", str(job_dir),
            "--log-file", str(log_file),
            "--work-dir", str(tdp)
        ], stdout=lf, stderr=subprocess.STDOUT)

      self.assertEqual(res.returncode, 137)
      log_content = log_file.read_text()
      self.assertIn("Exit code 137 indicates process was killed via SIGKILL", log_content)

  def test_runner_run_direct_command(self):
    with tempfile.TemporaryDirectory() as td:
      tdp = Path(td)
      job_dir = tdp / ".runpod_jobs" / "test-cmd-1"
      log_file = tdp / "logs" / "test-cmd-1.log"
      log_file.parent.mkdir(parents=True, exist_ok=True)

      with open(log_file, "w") as lf:
        res = subprocess.run([
            sys.executable,
            str(RUNNER_PATH),
            "run",
            "--job-id", "test-cmd-1",
            "--cmd", f"{sys.executable} -c \"print('direct command output')\"",
            "--job-dir", str(job_dir),
            "--log-file", str(log_file),
            "--work-dir", str(tdp)
        ], stdout=lf, stderr=subprocess.STDOUT)

      self.assertEqual(res.returncode, 0)
      log_content = log_file.read_text()
      self.assertIn("=== RUNPOD JOB STARTED: test-cmd-1", log_content)
      self.assertIn("direct command output", log_content)
      self.assertIn("=== RUNPOD JOB COMPLETED: test-cmd-1", log_content)
      self.assertIn("=== Exit Code:   0", log_content)

      self.assertEqual((job_dir / "exit_code").read_text().strip(), "0")
      meta = json.loads((job_dir / "meta.json").read_text())
      self.assertEqual(meta["job_id"], "test-cmd-1")
      self.assertEqual(meta["status"], "COMPLETED")


if __name__ == "__main__":
  unittest.main()
