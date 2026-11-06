"""Client of the sandbox service (backend/sandboxd.py), used for everything that executes or reads
what users control: ghdl, the compiled binaries, yosys, ghwdump.

Each job works in temp/.jobs/<random token>, with a copy of the user's sources in .src. Whatever
is in a job directory may have been written by the user's code: read it only with read_output() or
copy_output(), which do not follow symlinks. In particular, never give those paths to
send_from_directory, open() or Path.read_*().
"""

import json
import os
import secrets
import shutil
import socket
import stat
import struct
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

SOCKET_PATH = os.environ.get("FPGAEMU_SANDBOX_SOCKET", "/run/fpgaemu/sandbox.sock")
SRC_DIR = ".src"
TOKEN_FILE = ".buildtoken"
MAX_SOURCES = 64 * 2**20


class SandboxError(Exception):
    pass


def disabled():
    """Only for development outside the container: entrypoint.sh unsets this variable."""
    return os.environ.get("FPGAEMU_SANDBOX") == "off"


# --------------------------------------------------------------------------- jobs

class Job:
    """Same interface as subprocess.Popen for what the app needs. Closing the connection kills it."""

    def __init__(self, sock):
        self.sock = sock
        self.returncode = None
        self.reason = None
        self._buf = b""
        self._out, self._err = [], []
        self._frame()                # S (started) or X (refused)
        if self.returncode is None and self.reason is not None:
            self._close()
            raise SandboxError(self.reason)

    def _close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def _take(self):
        if len(self._buf) < 5:
            return None
        size = struct.unpack("=I", self._buf[1:5])[0]
        if len(self._buf) < 5 + size:
            return None
        kind, data = self._buf[:1], self._buf[5:5 + size]
        self._buf = self._buf[5 + size:]
        return kind, data

    def _apply(self, kind, data):
        if kind == b"O":
            self._out.append(data)
        elif kind == b"E":
            self._err.append(data)
        elif kind == b"X":
            info = json.loads(data)
            self.returncode, self.reason = info.get("rc"), info.get("reason")
            if self.returncode is None and self.reason is None:
                self.reason = "failed"
            self._finished = True
            return True
        return False

    _finished = False

    def _frame(self):
        """Blocks until one frame arrives. False when there is nothing more to read."""
        while True:
            fr = self._take()
            if fr:
                self._apply(*fr)
                return True
            d = self.sock.recv(65536)
            if not d:
                self._finished = True
                return False
            self._buf += d

    def communicate(self, timeout=None):
        if self.sock is not None and not self._finished:
            self.sock.settimeout(timeout)
            try:
                while not self._finished and self._frame():
                    pass
            except socket.timeout:
                raise subprocess.TimeoutExpired("sandbox job", timeout)
        out, err = b"".join(self._out), b"".join(self._err)
        self._out, self._err = [], []
        return out, err

    def poll(self):
        if self.sock is None or self._finished:
            return self.returncode if self.returncode is not None else -9
        self.sock.setblocking(False)
        try:
            while not self._finished:
                try:
                    d = self.sock.recv(65536)
                except (BlockingIOError, socket.timeout):
                    return None
                if not d:
                    self._finished = True
                    break
                self._buf += d
                while True:
                    fr = self._take()
                    if not fr:
                        break
                    self._apply(*fr)
        finally:
            if self.sock is not None:
                self.sock.setblocking(True)
        return self.returncode if self.returncode is not None else -9

    def kill(self):
        self._close()
        self._finished = True

    terminate = kill


class _LocalJob:
    """FPGAEMU_SANDBOX=off: no protection at all. Development only."""

    def __init__(self, proc):
        self.proc = proc
        self.reason = None

    returncode = property(lambda self: self.proc.returncode)
    poll = property(lambda self: self.proc.poll)
    terminate = property(lambda self: self.proc.terminate)

    def kill(self):
        self.proc.kill()

    def communicate(self, timeout=None):
        return self.proc.communicate(timeout=timeout)


def _request(req):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(10)
        s.connect(SOCKET_PATH)
        s.sendall(json.dumps(req).encode() + b"\n")
        s.settimeout(30)
    except OSError as e:
        s.close()
        raise SandboxError(f"sandbox service unavailable (errno {e.errno})")
    return s


def _split(cwd):
    """(token, working directory inside the job) of a path under temp/.jobs."""
    parts = Path(cwd).parts
    if ".jobs" not in parts:
        raise SandboxError("not a job directory")
    i = parts.index(".jobs")
    return parts[i + 1], "/".join(parts[i + 2:])


def start(profile, argv, cwd, env=None, discard=False, timeout=None):
    """Starts argv in the sandbox, in cwd (a job directory). Raises SandboxError if it cannot:
    there is no way of running without the sandbox, other than FPGAEMU_SANDBOX=off."""
    argv = [str(a) for a in argv]
    if disabled():
        full = dict(os.environ, **(env or {}))
        return _LocalJob(subprocess.Popen(argv, cwd=cwd, env=full, stdout=subprocess.DEVNULL if discard else subprocess.PIPE,
                                          stderr=subprocess.DEVNULL if discard else subprocess.PIPE))
    token, rel = _split(cwd)
    s = _request({"op": "run", "profile": profile, "token": token, "rel": rel, "argv": argv, "env": env or {},
                  "discard": discard, "timeout": timeout})
    return Job(s)


def status():
    if disabled():
        return {"mode": "off", "reason": "FPGAEMU_SANDBOX=off (development)", "tests": {}}
    try:
        s = _request({"op": "status"})
    except SandboxError as e:
        return {"mode": None, "reason": str(e), "tests": {}}
    try:
        return _read_reply(s)
    finally:
        s.close()


def _read_reply(s):
    buf = b""
    while True:
        d = s.recv(65536)
        if not d:
            raise SandboxError("no reply")
        buf += d
        if len(buf) >= 5:
            size = struct.unpack("=I", buf[1:5])[0]
            if len(buf) >= 5 + size:
                return json.loads(buf[5:5 + size])


def kill_pid(pid):
    """Kills a process of the sandbox user (admin page). True if it did."""
    s = _request({"op": "killpid", "pid": int(pid)})
    try:
        return _read_reply(s).get("rc") == 0
    finally:
        s.close()


# --------------------------------------------------------------------------- job directories

def _jobs_root(tempdir):
    root = Path(tempdir) / ".jobs"
    if not root.exists():            # in the container, entrypoint.sh creates it
        root.mkdir(parents=True, exist_ok=True)
    return root


def _shared_dir(path):
    """Directory the job can write to. The group comes from .jobs (setgid)."""
    path.mkdir(exist_ok=True)
    os.chmod(path, 0o2770)
    return path


def new_job_dir(tempdir):
    return _shared_dir(_jobs_root(tempdir) / secrets.token_hex(16))


def remove_job_dir(path):
    path = Path(path)
    shutil.rmtree(path, ignore_errors=True)
    if path.exists() and not disabled():      # the job made something inaccessible to this user
        try:
            s = _request({"op": "cleanup", "token": path.name})
            try:
                s.settimeout(60)
                _read_reply(s)
            finally:
                s.close()
        except (SandboxError, OSError):
            pass
        shutil.rmtree(path, ignore_errors=True)


@contextmanager
def tempjob(tempdir):
    path = new_job_dir(tempdir)
    try:
        yield path
    finally:
        remove_job_dir(path)


def user_private_dir(tempdir, user):
    """temp/<user>: only for the web app (zips, the simulation output already copied out). The
    jobs never see it, nor the name of the user."""
    d = Path(tempdir) / user
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_build(tempdir, user, create=True):
    """Job directory where the user's compilation stays between requests, or None if there is none."""
    tokenfile = Path(tempdir) / user / TOKEN_FILE
    try:
        token = tokenfile.read_text().strip()
        path = _jobs_root(tempdir) / token
        if path.is_dir():
            return path
    except OSError:
        pass
    if not create:
        return None
    path = new_job_dir(tempdir)
    user_private_dir(tempdir, user)
    tokenfile.write_text(path.name)
    return path


def reset_user_build(tempdir, user):
    """Starts over: removes the previous build and everything in temp/<user>."""
    old = user_build(tempdir, user, create=False)
    if old is not None:
        remove_job_dir(old)
    shutil.rmtree(Path(tempdir) / user, ignore_errors=True)
    return user_build(tempdir, user)


def project_dir(build, project):
    """Subdirectory of a project in a job directory, created by the web app."""
    path = Path(build)
    for part in Path(project).parts if project else ():
        if part in ("..", "/"):
            raise SandboxError("invalid project name")
        path = path / part
        try:
            if stat.S_ISLNK(os.lstat(path).st_mode):
                raise SandboxError("invalid project directory")
        except FileNotFoundError:
            pass
        _shared_dir(path)
    return path


def stage_sources(files, jobdir):
    """Copies the files into <jobdir>/.src and returns their paths relative to jobdir. The sandbox
    user cannot read work/, so a job gets this copy of the project and nothing else."""
    jobdir = Path(jobdir)
    src = jobdir / SRC_DIR
    src.mkdir(exist_ok=True)
    os.chmod(src, 0o2750)
    res, total = [], 0
    for f in files:
        f = Path(f)
        try:
            fd = os.open(f, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError:
            continue
        with os.fdopen(fd, "rb") as fin:
            st = os.fstat(fin.fileno())
            total += st.st_size
            if not stat.S_ISREG(st.st_mode):
                continue
            if total > MAX_SOURCES:
                raise SandboxError("project too large")
            write_job_file(src, f.name, fin.read())
        res.append(f"{SRC_DIR}/{f.name}")
    return res


def write_job_file(jobdir, name, data):
    """New file for a job. Never writes through what a job may have left with that name."""
    path = Path(jobdir) / name
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
    with os.fdopen(fd, "wb") as f:
        os.fchmod(f.fileno(), 0o640)
        f.write(data)


# --------------------------------------------------------------------------- outputs of jobs

def _open_regular(root, rel):
    """Opens a file under root without following any symlink on the way. OSError if it cannot."""
    parts = [p for p in Path(rel).parts]
    if not parts or any(p in ("..", "/") for p in parts):
        raise OSError("invalid path")
    dirfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dirfd)
            os.close(dirfd)
            dirfd = nxt
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dirfd)
    finally:
        os.close(dirfd)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise OSError("not a regular file")
    return fd


def read_output(root, rel, maxbytes=64 * 2**20):
    fd = _open_regular(root, rel)
    with os.fdopen(fd, "rb") as f:
        data = f.read(maxbytes + 1)
    if len(data) > maxbytes:
        raise OSError("output too large")
    return data


def copy_output(root, rel, dest, maxbytes=64 * 2**20):
    data = read_output(root, rel, maxbytes)
    dest = Path(dest)
    tmp = dest.with_name(dest.name + ".part")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dest)


def make_fifo(jobdir, name):
    path = Path(jobdir) / name
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    os.mkfifo(path, 0o660)
    os.chmod(path, 0o660)
    return path


def open_fifo(path, flags):
    """Opens a FIFO refusing anything else: the name is in a directory the job can write to."""
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK)
    if not stat.S_ISFIFO(os.fstat(fd).st_mode):
        os.close(fd)
        raise OSError("not a FIFO")
    return fd
