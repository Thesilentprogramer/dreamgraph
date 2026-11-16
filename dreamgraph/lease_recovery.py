"""Recover from a HydraDB writer lease that remains stuck on another node.

The API owns the retry loop: call :func:`handle_writer_lease_error` for each
lease failure and keep retrying with backoff while it returns ``True``. After
the lease has failed continuously for ``DG_LEASE_RESTART_AFTER`` seconds, this
module restarts the local ``graph-node`` process. It does that at most three
times per API process, then leaves the API retry loop running indefinitely.
Call :func:`reset_writer_lease_state` after a successful write/seed operation.
"""

from __future__ import annotations

import glob
import os
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

GRAPH_NODE = "/usr/local/bin/graph-node"
GRAPH_NODE_LOG = "/tmp/graph-node.log"
GRAPH_NODE_PID_FILE = os.environ.get("DG_GRAPH_NODE_PID_FILE", "/tmp/graph-node.pid")
LEASE_PHRASE = "not owned by this node"


def is_writer_lease_error(exc: BaseException) -> bool:
    """Return whether an exception reports that this node does not own a cell."""

    return LEASE_PHRASE in str(exc).casefold()


def _proc_argv0(pid: int) -> str | None:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return None
    first = raw.split(b"\0", 1)[0]
    return os.fsdecode(first) if first else None


def _find_graph_node_pid() -> int | None:
    """Find the node started by the boot script, tolerating a stale pid file."""

    candidates: list[int] = []
    try:
        candidates.append(int(Path(GRAPH_NODE_PID_FILE).read_text().strip()))
    except (FileNotFoundError, ValueError, OSError):
        pass

    for proc_dir in glob.glob("/proc/[0-9]*"):
        try:
            candidates.append(int(proc_dir.rsplit("/", 1)[1]))
        except ValueError:
            continue

    own_pid = os.getpid()
    for pid in dict.fromkeys(candidates):
        if pid == own_pid:
            continue
        argv0 = _proc_argv0(pid)
        if argv0 == GRAPH_NODE or Path(argv0 or "").name == "graph-node":
            return pid
    return None


def _process_is_running(pid: int) -> bool:
    """Check liveness and reap the node when it is our direct child."""

    try:
        waited_pid, _status = os.waitpid(pid, os.WNOHANG)
        if waited_pid == pid:
            return False
    except (ChildProcessError, ProcessLookupError):
        pass
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        # A zombie has exited; it may remain visible until its parent reaps it.
        if stat.rsplit(")", 1)[-1].lstrip().startswith("Z"):
            return False
        os.kill(pid, 0)
    except (FileNotFoundError, ProcessLookupError):
        return False
    except PermissionError:
        return True
    return True


def _stop_graph_node(pid: int, *, timeout: float = 10.0) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_is_running(pid):
            return
        time.sleep(0.2)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and _process_is_running(pid):
        time.sleep(0.1)


def restart_graph_node() -> int:
    """Restart graph-node with its original environment and append-only log.

    The container boot script records the first child PID. Since that script
    later ``exec``s uvicorn, graph-node remains a direct child of the API
    process and can be terminated and reaped here. The ``/proc`` scan also
    handles a missing or stale pid file.
    """

    pid = _find_graph_node_pid()
    if pid is None:
        raise RuntimeError(f"could not find running {GRAPH_NODE}")
    _stop_graph_node(pid)

    log_path = Path(GRAPH_NODE_LOG)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab", buffering=0) as log_file:
        child = subprocess.Popen(
            [GRAPH_NODE],
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            close_fds=True,
        )

    pid_path = Path(GRAPH_NODE_PID_FILE)
    try:
        with tempfile.NamedTemporaryFile(
            "w", dir=pid_path.parent, prefix=f"{pid_path.name}.", delete=False
        ) as temp_file:
            temp_file.write(f"{child.pid}\n")
            temp_path = Path(temp_file.name)
        temp_path.replace(pid_path)
    finally:
        if "temp_path" in locals():
            temp_path.unlink(missing_ok=True)
    return child.pid


class WriterLeaseRecovery:
    """Track persistent lease errors and make at most three node restarts."""

    def __init__(
        self,
        *,
        restart_after: float = 60.0,
        max_restarts: int = 3,
        clock: Callable[[], float] = time.monotonic,
        restart: Callable[[], int] | None = None,
    ) -> None:
        self.restart_after = max(0.0, restart_after)
        self.max_restarts = max(0, max_restarts)
        self._clock = clock
        self._restart = restart or restart_graph_node
        self._lock = threading.Lock()
        self._first_error_at: float | None = None
        self._restarts = 0
        self.last_restart_error: str | None = None

    @property
    def restart_count(self) -> int:
        with self._lock:
            return self._restarts

    def reset(self) -> None:
        """Clear the persistence timer after a successful operation."""

        with self._lock:
            self._first_error_at = None
            self.last_restart_error = None

    def handle_error(self, exc: BaseException) -> bool:
        """Record a failure, restarting after the persistence threshold.

        Returns ``True`` for lease failures so callers can continue retrying
        those forever. Restart failures are retained for diagnostics and do
        not interrupt the caller's retry loop.
        """

        if not is_writer_lease_error(exc):
            return False

        with self._lock:
            now = self._clock()
            if self._first_error_at is None:
                self._first_error_at = now
            if (
                now - self._first_error_at >= self.restart_after
                and self._restarts < self.max_restarts
            ):
                self._restarts += 1
                # Require another full persistence interval before a further
                # restart, but continue returning True if the lease persists.
                self._first_error_at = now
                try:
                    self._restart()
                    self.last_restart_error = None
                except Exception as restart_error:  # noqa: BLE001 — retry loop owns recovery
                    self.last_restart_error = str(restart_error)
        return True


_recovery = WriterLeaseRecovery(
    restart_after=float(os.environ.get("DG_LEASE_RESTART_AFTER", "60")),
    max_restarts=3,
)


def handle_writer_lease_error(exc: BaseException) -> bool:
    """API integration: return true for a lease failure and restart if due."""

    return _recovery.handle_error(exc)


def reset_writer_lease_state() -> None:
    """API integration: clear the lease timer after the operation succeeds."""

    _recovery.reset()


def writer_lease_restart_count() -> int:
    """Return the number of Python-initiated node restarts this API process made."""

    return _recovery.restart_count


def writer_lease_last_restart_error() -> str | None:
    """Return the most recent supervisor error, if a node restart failed."""

    return _recovery.last_restart_error
