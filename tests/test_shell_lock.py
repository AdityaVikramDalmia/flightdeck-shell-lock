import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

CLI = Path(__file__).resolve().parents[1] / "bin" / "shell-lock"


class ShellLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="shell lock ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lock = self.root / "locks with spaces" / "build.lock"
        self.processes = []
        self.child_groups = []
        self.addCleanup(self.stop_processes)

    def stop_processes(self):
        for proc in self.processes:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()
        for pid in self.child_groups:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def run_command(self, *command, timeout=1, lock=None):
        return subprocess.run([str(CLI), "--timeout", str(timeout), str(lock or self.lock),
                               "--", *command], capture_output=True, text=True, timeout=8)

    def holder(self, script=None, lock=None):
        ready = self.root / ("ready-" + str(len(self.processes)))
        code = script or "import os,pathlib,sys,time;pathlib.Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(30)"
        proc = subprocess.Popen([str(CLI), str(lock or self.lock), "--", sys.executable,
                                 "-c", code, str(ready)], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        self.processes.append(proc)
        limit = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < limit:
            if proc.poll() is not None:
                self.fail(proc.communicate()[1])
            time.sleep(0.01)
        self.assertTrue(ready.exists(), "holder did not become ready")
        pid = int(ready.read_text())
        self.child_groups.append(pid)
        return proc, pid

    def test_command_output_and_exit_are_preserved(self):
        result = self.run_command(sys.executable, "-c", "import sys;print('hello');sys.exit(17)")
        self.assertEqual(result.returncode, 17)
        self.assertEqual(result.stdout, "hello\n")

    def test_literal_argv_is_not_shell_interpreted(self):
        argument = "spaces; $(touch never)\nnext"
        result = self.run_command(sys.executable, "-c", "import sys;print(sys.argv[1],end='')", argument)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, argument)

    def test_lock_file_remains_with_same_inode_between_calls(self):
        self.assertEqual(self.run_command("true").returncode, 0)
        inode = self.lock.stat().st_ino
        self.assertEqual(self.run_command("true").returncode, 0)
        self.assertEqual(self.lock.stat().st_ino, inode)

    def test_busy_zero_timeout_never_starts_command(self):
        self.holder()
        marker = self.root / "must-not-exist"
        start = time.monotonic()
        result = self.run_command(sys.executable, "-c", "import pathlib,sys;pathlib.Path(sys.argv[1]).touch()", str(marker), timeout=0)
        self.assertEqual(result.returncode, 75)
        self.assertFalse(marker.exists())
        self.assertLess(time.monotonic() - start, 2)

    def test_timeout_waits_then_refuses(self):
        self.holder()
        start = time.monotonic()
        self.assertEqual(self.run_command("true", timeout=0.2).returncode, 75)
        self.assertGreaterEqual(time.monotonic() - start, 0.19)

    def test_term_stops_child_and_releases_lock(self):
        proc, _ = self.holder()
        proc.terminate()
        self.assertEqual(proc.wait(timeout=5), 143)
        self.assertEqual(self.run_command("true").returncode, 0)

    def test_killing_wrapper_does_not_unlock_surviving_child(self):
        proc, child = self.holder()
        proc.kill()
        proc.wait(timeout=5)
        self.assertEqual(self.run_command("true", timeout=0).returncode, 75)
        os.killpg(child, signal.SIGTERM)
        self.assertEqual(self.run_command("true", timeout=3).returncode, 0)

    def test_different_lock_names_do_not_contend(self):
        self.holder()
        self.assertEqual(self.run_command("true", lock=self.root / "other.lock").returncode, 0)

    def test_parallel_commands_never_overlap(self):
        counter = self.root / "counter"
        counter.write_text("0")
        occupied = self.root / "occupied"
        code = (
            "import pathlib,sys,time;"
            "counter=pathlib.Path(sys.argv[1]);marker=pathlib.Path(sys.argv[2]);"
            "marker.mkdir();value=int(counter.read_text());time.sleep(.015);"
            "counter.write_text(str(value+1));marker.rmdir()"
        )
        workers = []
        for _ in range(24):
            proc = subprocess.Popen([str(CLI), "--timeout", "10", str(self.lock), "--", sys.executable,
                                     "-c", code, str(counter), str(occupied)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.processes.append(proc)
            workers.append(proc)
        for proc in workers:
            out, err = proc.communicate(timeout=15)
            self.assertEqual(proc.returncode, 0, out + err)
        self.assertEqual(counter.read_text(), "24")

    def test_symbolic_lock_file_is_refused(self):
        self.lock.parent.mkdir()
        target = self.root / "target"
        target.write_text("untouched")
        self.lock.symlink_to(target)
        self.assertEqual(self.run_command("true").returncode, 73)
        self.assertEqual(target.read_text(), "untouched")

    def test_hardlinked_lock_file_is_refused(self):
        self.lock.parent.mkdir()
        self.lock.touch()
        os.link(self.lock, self.root / "alias")
        self.assertEqual(self.run_command("true").returncode, 73)

    def test_replaced_lock_while_waiting_is_refused(self):
        holder, _ = self.holder()
        waiter = subprocess.Popen([str(CLI), "--timeout", "5", str(self.lock), "--", "true"],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.processes.append(waiter)
        # Ensure the waiter has had time to open the original inode and enter flock.
        time.sleep(0.3)
        self.lock.unlink()
        self.lock.touch()
        holder.terminate()
        holder.wait(timeout=5)
        out, err = waiter.communicate(timeout=5)
        self.assertEqual(waiter.returncode, 73, out + err)

    def test_missing_command_returns_127(self):
        self.assertEqual(self.run_command(str(self.root / "missing")).returncode, 127)

    def test_non_executable_command_returns_126(self):
        path = self.root / "not-executable"
        path.write_text("hello")
        self.assertEqual(self.run_command(str(path)).returncode, 126)

    def test_closed_standard_streams_stay_closed_in_command(self):
        probe = (
            "import errno,os,sys;"
            "assert int(os.environ['SHELL_LOCK_FD']) >= 3;"
            "stream=int(sys.argv[1]);"
            "\ntry: os.fstat(stream)"
            "\nexcept OSError as e: sys.exit(0 if e.errno==errno.EBADF else 18)"
            "\nelse: sys.exit(19)"
        )
        for stream in (0, 1, 2):
            with self.subTest(stream=stream):
                proc = subprocess.run(
                    [str(CLI), str(self.lock), "--", sys.executable, "-c", probe, str(stream)],
                    preexec_fn=lambda: os.close(stream), capture_output=True, text=True, timeout=5,
                )
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual(self.lock.read_bytes(), b"")

    def test_executable_without_interpreter_returns_126(self):
        path = self.root / "invalid-executable"
        path.write_text("plain text without an interpreter\n")
        path.chmod(0o755)
        proc = self.run_command(str(path))
        self.assertEqual(proc.returncode, 126)
        self.assertIn("not executable", proc.stderr)
        self.assertEqual(self.run_command("true").returncode, 0)

    def test_closed_stderr_does_not_reopen_as_lock_or_redirect_diagnostic(self):
        proc = subprocess.run(
            [str(CLI), str(self.lock), "--", str(self.root / "missing")],
            preexec_fn=lambda: os.close(2), capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(proc.returncode, 127)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(self.lock.read_bytes(), b"")

    def test_broken_diagnostic_pipe_preserves_exit_code(self):
        reader, writer = os.pipe()
        os.close(reader)
        try:
            proc = subprocess.run(
                [str(CLI), str(self.lock), "--", str(self.root / "missing")],
                stdout=subprocess.PIPE, stderr=writer, text=True, timeout=5,
            )
        finally:
            os.close(writer)
        self.assertEqual(proc.returncode, 127)
        self.assertEqual(proc.stdout, "")

    def test_fifo_lock_is_refused_without_blocking(self):
        self.lock.parent.mkdir()
        os.mkfifo(self.lock)
        start = time.monotonic()
        proc = self.run_command("true", timeout=0)
        self.assertEqual(proc.returncode, 73)
        self.assertLess(time.monotonic() - start, 2)

    def test_recursive_lock_times_out_instead_of_reentering(self):
        proc = self.run_command(str(CLI), "--timeout", "0.1", str(self.lock), "--", "true")
        self.assertEqual(proc.returncode, 75)
        self.assertEqual(self.run_command("true").returncode, 0)

    def test_child_signal_exit_status_is_preserved(self):
        proc = self.run_command(sys.executable, "-c", "import os,signal;os.kill(os.getpid(),signal.SIGTERM)")
        self.assertEqual(proc.returncode, 143)
        self.assertEqual(self.run_command("true").returncode, 0)

    def test_forwarding_permission_error_still_waits_and_holds_lock(self):
        ready = self.root / "permission-ready"
        finished = self.root / "permission-finished"
        attempted = self.root / "signal-attempted"
        release = self.root / "release-child"
        self.addCleanup(release.touch)
        # Isolate killpg(EPERM) in a subprocess. The child closes its inherited
        # descriptor, making the wrapper's obligation to keep waiting observable.
        child_code = (
            "import os,pathlib,sys,time;"
            "os.close(int(os.environ['SHELL_LOCK_FD']));"
            "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()));"
            "\nwhile not pathlib.Path(sys.argv[3]).exists(): time.sleep(.005)"
            "\npathlib.Path(sys.argv[2]).touch()"
        )
        runner = (
            "import errno,os,pathlib,runpy,signal,sys,threading,time;"
            "namespace=runpy.run_path(sys.argv[1]);"
            "ready=pathlib.Path(sys.argv[3]);"
            "\ndef refuse(*args):"
            "\n pathlib.Path(sys.argv[5]).touch()"
            "\n raise PermissionError(errno.EPERM, 'signal denied')"
            "\ndef interrupt():"
            "\n while not ready.exists(): time.sleep(.005)"
            "\n os.kill(os.getpid(),signal.SIGTERM)"
            "\nnamespace['os'].killpg=refuse;"
            "threading.Thread(target=interrupt,daemon=True).start();"
            "sys.exit(namespace['main']([sys.argv[2],'--',sys.executable,'-c',"
            "sys.argv[7],sys.argv[3],sys.argv[4],sys.argv[6]]))"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", runner, str(CLI), str(self.lock), str(ready),
             str(finished), str(attempted), str(release), child_code],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.processes.append(proc)
        deadline = time.monotonic() + 4
        while not attempted.exists() and time.monotonic() < deadline:
            if proc.poll() is not None:
                self.fail(proc.communicate()[1])
            time.sleep(.01)
        self.assertTrue(ready.exists())
        self.child_groups.append(int(ready.read_text()))
        self.assertTrue(attempted.exists())
        self.assertEqual(self.run_command("true", timeout=0).returncode, 75)
        release.touch()
        out, err = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 143, out + err)
        self.assertTrue(finished.exists())
        self.assertIn("could not forward signal", err)
        self.assertEqual(self.run_command("true").returncode, 0)

    def test_staged_install_is_self_contained(self):
        stage = self.root / "staging directory"
        result = subprocess.run(
            ["make", "install", "PREFIX=/opt/example", "DESTDIR=" + str(stage)],
            cwd=CLI.parent.parent, capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        installed = stage / "opt/example/bin/shell-lock"
        result = subprocess.run(
            [str(installed), str(self.lock), "--", "true"], capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_bad_timeout_and_missing_command_are_usage_errors(self):
        for value in ("-1", "nan", "inf"):
            self.assertEqual(self.run_command("true", timeout=value).returncode, 2)
        proc = subprocess.run([str(CLI), str(self.lock)], capture_output=True)
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
