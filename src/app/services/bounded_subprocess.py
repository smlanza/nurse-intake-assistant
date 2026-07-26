from __future__ import annotations

from dataclasses import dataclass
import os
import signal
import subprocess


TIMEOUT_RETURN_CODE = 124


@dataclass(frozen=True)
class BoundedCommandResult:
    return_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


def run_bounded_subprocess(
    args: list[str],
    *,
    timeout_seconds: float,
    cleanup_timeout_seconds: float,
) -> BoundedCommandResult:
    if timeout_seconds <= 0 or cleanup_timeout_seconds <= 0:
        raise ValueError("Subprocess timeouts must be positive.")
    try:
        process = subprocess.Popen(
            args,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=os.name == "posix",
        )
    except OSError:
        return BoundedCommandResult(127, "", "")
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        return BoundedCommandResult(
            process.returncode,
            stdout,
            stderr,
        )
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process)
        try:
            process.communicate(timeout=cleanup_timeout_seconds)
        except subprocess.TimeoutExpired:
            _kill_process_tree(process)
            try:
                process.communicate(timeout=cleanup_timeout_seconds)
            except subprocess.TimeoutExpired:
                return BoundedCommandResult(
                    TIMEOUT_RETURN_CODE,
                    "",
                    "",
                    timed_out=True,
                )
        return BoundedCommandResult(
            TIMEOUT_RETURN_CODE,
            "",
            "",
            timed_out=True,
        )


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except (OSError, ProcessLookupError):
        pass


def _kill_process_tree(process: subprocess.Popen[str]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except (OSError, ProcessLookupError):
        pass
