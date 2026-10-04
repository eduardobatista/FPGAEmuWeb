#!/usr/bin/env python3
"""
FPGAEmuWeb server diagnostics.

Uses ONLY the Python standard library, so it keeps working even when the
application virtualenv (.venv) or the database are damaged. It is run with the
system interpreter (/usr/bin/python3, installed together with supervisor).

Commands:
    manifest        (build time) hash every file of the image -> manifest
    run             run the checks and store a report (--mode quick|full)
    serve-fallback  if the web app stays down, serve the report on port 5000
    print-url       print the diagnostics URL (with access key)

Reports are written to DIAG_DIR (latest.json + history/).
"""

import argparse
import datetime
import errno
import gzip
import hashlib
import hmac
import html
import json
import os
import platform
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DIAG_DIR = Path(os.environ.get("FPGAEMU_DIAG_DIR", "/home/diagnostics"))
MANIFEST_FILE = Path(os.environ.get("FPGAEMU_DIAG_MANIFEST", "/home/fpgaemu-manifest.json.gz"))
HISTORY_KEEP = 40
MAX_DETAILS = 300
APP_PORT = 5000
FALLBACK_DELAY = int(os.environ.get("FPGAEMU_DIAG_FALLBACK_DELAY", "300"))

# Trees hashed at build time and verified at run time.
MANIFEST_ROOTS = [
    APP_DIR,
    Path("/usr/local"),                    # GHDL
    Path("/home/surferdist"),              # Surfer (waveform viewer)
    Path("/root/.local/share/uv/python"),  # Python interpreter managed by uv
    Path("/bin/uv"),
    Path("/bin/uvx"),
]
# Things that legitimately change while the container runs.
EXCLUDE_DIR_NAMES = {"__pycache__", ".git"}
EXCLUDE_PATHS = {
    APP_DIR / "work", APP_DIR / "cachedwork", APP_DIR / "persistentwork", APP_DIR / "temp",
    APP_DIR / "backend" / "fpgacompileweb", APP_DIR / "backend" / "fpgaemu_c.o",
    APP_DIR / "workbackup.tar", APP_DIR / ".venv" / ".lock",
}
EXCLUDE_NAME_RE = re.compile(r"(\.pyc$|^huey\.db|\.log$)")

WORKDIRS = [APP_DIR / "work", APP_DIR / "cachedwork", APP_DIR / "persistentwork"]
PYTHON_MODULES = ["flask", "flask_socketio", "flask_login", "flask_sqlalchemy", "sqlalchemy",
                  "gevent", "geventwebsocket", "huey", "psutil", "psycopg2", "requests",
                  "werkzeug", "yagmail", "gunicorn"]

STATUS_ORDER = {"ok": 0, "info": 1, "skip": 1, "warn": 2, "fail": 3}

# Text that usually points to storage / filesystem trouble.
DISK_ERROR_RE = re.compile(
    r"I/O error|Input/output error|Errno 5\b|blk_update_request|Buffer I/O|EXT4-fs (error|warning)"
    r"|XFS .*(error|corrupt|Corruption)|BTRFS (error|warning|critical)|critical medium error|Medium Error"
    r"|ata\d+.*(error|failed|exception)|nvme.*(timeout|error|reset)|SCSI error|Sense Key"
    r"|Remounting filesystem read-only|Read-only file system|Errno 30\b|journal.*abort"
    r"|database disk image is malformed|disk I/O error|file is not a database|Stale file handle"
    r"|Bus error|SIGBUS|squashfs error|overlayfs.*error", re.I)
OTHER_ERROR_RE = re.compile(
    r"Traceback|Segmentation fault|SIGSEGV|segfault|Illegal instruction|Killed|Out of memory|oom-kill"
    r"|No space left|Errno 28\b|WORKER TIMEOUT|database is locked|Cannot allocate memory|Errno 12\b"
    r"|Resource temporarily unavailable|EDAC|Machine check|mce:", re.I)


# --------------------------------------------------------------------------- utils

def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def diag_dir():
    """DIAG_DIR, or a temp dir if it cannot be written (a symptom in itself)."""
    for d in (DIAG_DIR, Path(tempfile.gettempdir()) / "fpgaemu-diagnostics"):
        try:
            (d / "history").mkdir(parents=True, exist_ok=True)
            probe = d / ".probe"
            probe.write_text("x")
            probe.unlink()
            return d
        except OSError:
            continue
    raise RuntimeError("No writable directory for diagnostics")


def atomic_write(path, text):
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def run_cmd(cmd, timeout=60, cwd=None, shell=False):
    env = dict(os.environ)
    env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:" + env.get("PATH", "")
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd=cwd, shell=shell, env=env, timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = p.stdout.decode("utf-8", "replace")
        return p.returncode, out, time.monotonic() - t0
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode("utf-8", "replace")
        return None, out + f"\n[TIMEOUT after {timeout}s]", time.monotonic() - t0
    except OSError as e:
        return -1, f"[cannot run {cmd}: {e}]", time.monotonic() - t0


def tail(text, n=15):
    lines = text.strip().splitlines()
    return lines[-n:]


def fmt_bytes(n):
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PiB"


def hash_file(path, chunk=1 << 20):
    """Returns (sha256, size, seconds). Raises OSError on read errors."""
    h = hashlib.sha256()
    size = 0
    t0 = time.monotonic()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
            size += len(b)
    return h.hexdigest(), size, time.monotonic() - t0


def oserror_text(e):
    code = errno.errorcode.get(e.errno, str(e.errno)) if e.errno else "?"
    return f"{code}: {e.strerror or e}"


def read_text(path, default=""):
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return default


_PROGRESS_FILE = None
_progress_last = 0.0


def progress(msg):
    """Records what the running check is doing (shown in the UI; tells where a hung check got stuck)."""
    global _progress_last
    if _PROGRESS_FILE is None:
        return
    now = time.monotonic()
    if now - _progress_last < 1.0:
        return
    _progress_last = now
    try:
        with open(_PROGRESS_FILE, "w") as f:
            f.write(f"{msg} (since {now_iso()})")
    except OSError:
        pass


# --------------------------------------------------------------------------- check object

class Check:
    def __init__(self, cid, title):
        self.id = cid
        self.title = title
        self.status = "ok"
        self.summary = ""
        self.details = []   # list of [level, text]
        self.data = {}
        self.duration = 0.0
        self._dropped = 0

    def _add(self, level, msg):
        if STATUS_ORDER[level] > STATUS_ORDER[self.status]:
            self.status = level
        if len(self.details) < MAX_DETAILS:
            self.details.append([level, str(msg)])
        else:
            self._dropped += 1

    def info(self, msg):
        if len(self.details) < MAX_DETAILS:
            self.details.append(["info", str(msg)])
        else:
            self._dropped += 1

    def warn(self, msg):
        self._add("warn", msg)

    def fail(self, msg):
        self._add("fail", msg)

    def to_dict(self):
        det = list(self.details)
        if self._dropped:
            det.append(["info", f"... {self._dropped} more lines omitted"])
        return {"id": self.id, "title": self.title, "status": self.status, "summary": self.summary,
                "details": det, "data": self.data, "duration": round(self.duration, 2)}


# --------------------------------------------------------------------------- manifest

def iter_tree(root):
    """Yields files/symlinks of root, honoring exclusions. Errors are yielded as (path, OSError)."""
    root = Path(root)
    if root.is_symlink() or root.is_file():
        yield root, None
        return
    if not root.is_dir():
        return
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError as e:
            yield d, e
            continue
        for ent in entries:
            p = Path(ent.path)
            if p in EXCLUDE_PATHS:
                continue
            try:
                if ent.is_dir(follow_symlinks=False):
                    if ent.name not in EXCLUDE_DIR_NAMES:
                        stack.append(p)
                    continue
            except OSError as e:
                yield p, e
                continue
            if EXCLUDE_NAME_RE.search(ent.name):
                continue
            yield p, None


def build_manifest(_args):
    files = {}
    t0 = time.monotonic()
    for root in MANIFEST_ROOTS:
        for p, err in iter_tree(root):
            if err:
                print(f"WARNING: {p}: {err}", file=sys.stderr)
                continue
            if p.is_symlink():
                files[str(p)] = {"link": os.readlink(p)}
            elif p.is_file():
                digest, size, _ = hash_file(p)
                files[str(p)] = {"sha256": digest, "size": size}
    body = json.dumps(files, sort_keys=True)
    manifest = {
        "created": now_iso(),
        "git_commit": os.environ.get("GIT_COMMIT", ""),
        "roots": [str(r) for r in MANIFEST_ROOTS],
        "count": len(files),
        "total_bytes": sum(v.get("size", 0) for v in files.values()),
        "files_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "files": files,
    }
    with gzip.open(MANIFEST_FILE, "wt") as f:
        json.dump(manifest, f)
    print(f"Manifest: {len(files)} files, {fmt_bytes(manifest['total_bytes'])}, "
          f"{time.monotonic() - t0:.1f}s -> {MANIFEST_FILE}")


def load_manifest():
    with gzip.open(MANIFEST_FILE, "rt") as f:
        m = json.load(f)
    body = json.dumps(m["files"], sort_keys=True)
    if hashlib.sha256(body.encode()).hexdigest() != m["files_sha256"]:
        raise ValueError("manifest content does not match its own checksum")
    return m


# --------------------------------------------------------------------------- checks

def check_environment(c, mode):
    c.info(f"Host: {socket.gethostname()} | {platform.platform()} | Python {platform.python_version()}")
    try:
        uptime = float(read_text("/proc/uptime").split()[0])
        c.info(f"System uptime: {datetime.timedelta(seconds=int(uptime))}")
        ticks = os.sysconf("SC_CLK_TCK")
        pid1_start = int(read_text("/proc/1/stat").rsplit(")", 1)[1].split()[19]) / ticks
        c.data["container_uptime_s"] = int(uptime - pid1_start)
        c.info(f"Container uptime: {datetime.timedelta(seconds=int(uptime - pid1_start))}")
    except Exception as e:
        c.info(f"Uptime unavailable: {e}")
    try:
        la = os.getloadavg()
        ncpu = os.cpu_count() or 1
        c.info(f"Load average: {la[0]:.2f} {la[1]:.2f} {la[2]:.2f} ({ncpu} CPUs)")
        if la[1] > 2 * ncpu:
            c.warn(f"High 5-min load ({la[1]:.1f} for {ncpu} CPUs). Processes stuck on I/O also raise the load.")
    except OSError:
        pass
    c.info(f"ENVCACHEDWORK={os.environ.get('ENVCACHEDWORK', '(unset)')}")
    for w in WORKDIRS:
        if w.exists():
            c.info(f"Work directory present: {w}")
    try:
        m = load_manifest()
        c.data["image_built"] = m.get("created")
        c.data["git_commit"] = m.get("git_commit")
        c.info(f"Image built at {m.get('created')} commit {m.get('git_commit') or '(unknown)'}")
    except Exception:
        pass
    c.summary = f"{socket.gethostname()}, mode {mode}"


def check_memory(c, mode):
    mi = {}
    for line in read_text("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        try:
            mi[k] = int(v.split()[0]) * 1024
        except (ValueError, IndexError):
            pass
    if mi:
        c.info(f"Host RAM: total {fmt_bytes(mi.get('MemTotal', 0))}, available {fmt_bytes(mi.get('MemAvailable', 0))}, "
               f"swap free {fmt_bytes(mi.get('SwapFree', 0))}/{fmt_bytes(mi.get('SwapTotal', 0))}")
    cg = Path("/sys/fs/cgroup")
    if (cg / "memory.max").exists():  # cgroup v2
        mx = read_text(cg / "memory.max").strip()
        cur = read_text(cg / "memory.current").strip()
        c.info(f"Container memory: current {fmt_bytes(int(cur or 0))}, limit {mx if mx == 'max' else fmt_bytes(int(mx))}")
        if mx != "max" and cur and int(cur) > 0.9 * int(mx):
            c.warn("Container is using more than 90% of its memory limit.")
        ev = dict(l.split() for l in read_text(cg / "memory.events").splitlines() if l.strip())
        c.data["memory_events"] = ev
        if int(ev.get("oom_kill", 0)) > 0:
            c.fail(f"The kernel killed {ev['oom_kill']} process(es) of this container for lack of memory (oom_kill).")
        elif int(ev.get("max", 0)) > 0:
            c.warn(f"Memory limit reached {ev['max']} times (memory.events max).")
        pe = dict(l.split() for l in read_text(cg / "pids.events").splitlines() if l.strip())
        if int(pe.get("max", 0)) > 0:
            c.fail(f"Process limit reached {pe['max']} times (fork failures). pids.max={read_text(cg / 'pids.max').strip()}")
        cs = dict(l.split() for l in read_text(cg / "cpu.stat").splitlines() if l.strip())
        if cs.get("nr_throttled") and int(cs["nr_throttled"]) > 0:
            c.info(f"CPU throttled {cs['nr_throttled']} times ({int(cs.get('throttled_usec', 0)) / 1e6:.0f}s total).")
        io = read_text(cg / "io.pressure").strip()
        if io:
            c.info(f"I/O pressure: {io.splitlines()[-1]}")
            m = re.search(r"full avg10=([\d.]+) avg60=([\d.]+)", io)
            if m and float(m.group(2)) > 20:
                c.warn(f"Processes fully stalled waiting for I/O {m.group(2)}% of the last minute.")
    elif (cg / "memory" / "memory.limit_in_bytes").exists():  # cgroup v1
        mem = cg / "memory"
        c.info(f"Container memory usage: {fmt_bytes(int(read_text(mem / 'memory.usage_in_bytes', '0') or 0))}, "
               f"limit {fmt_bytes(int(read_text(mem / 'memory.limit_in_bytes', '0') or 0))}")
        fc = read_text(mem / "memory.failcnt").strip()
        if fc and int(fc) > 0:
            c.warn(f"Memory limit hit {fc} times (memory.failcnt).")
        m = re.search(r"oom_kill (\d+)", read_text(mem / "memory.oom_control"))
        if m and int(m.group(1)) > 0:
            c.fail(f"The kernel killed {m.group(1)} process(es) of this container for lack of memory.")
    else:
        c.info("cgroup information not available.")
    c.summary = f"available {fmt_bytes(mi.get('MemAvailable', 0))}" if mi else "no data"


def _mounts():
    res = []
    for line in read_text("/proc/self/mountinfo").splitlines():
        parts = line.split()
        try:
            sep = parts.index("-")
        except ValueError:
            continue
        res.append({"mountpoint": parts[4].replace("\\040", " "), "opts": parts[5],
                    "fstype": parts[sep + 1], "source": parts[sep + 2], "superopts": parts[sep + 3]})
    return res


def _mount_for(path, mounts):
    path = str(Path(path).resolve())
    best = None
    for m in mounts:
        mp = m["mountpoint"]
        if path == mp or path.startswith(mp.rstrip("/") + "/") or mp == "/":
            if best is None or len(mp) > len(best["mountpoint"]):
                best = m
    return best


def key_paths():
    paths = [Path("/"), APP_DIR, Path("/tmp"), Path("/home")] + [w for w in WORKDIRS if w.exists()]
    try:
        paths.append(diag_dir())
    except RuntimeError:
        pass
    return paths


def check_filesystems(c, mode):
    mounts = _mounts()
    seen = set()
    for p in key_paths():
        m = _mount_for(p, mounts)
        if not m:
            continue
        ro = "ro" in m["opts"].split(",") or "ro" in m["superopts"].split(",")
        line = f"{p} -> {m['mountpoint']} ({m['fstype']} from {m['source']}, {m['opts']})"
        if m["fstype"].startswith("nfs") and m["mountpoint"] not in seen:
            c.warn(f"{p} is on NETWORK storage ({m['fstype']}, server options: {m['superopts']}). "
                   f"Any NFS stall blocks the processes reading it (state D) and freezes the single web worker; "
                   f"SQLite on NFS is also not recommended (unreliable locking).")
        if ro:
            c.fail(f"READ-ONLY mount: {line}. Linux remounts a filesystem read-only after detecting errors.")
        elif m["mountpoint"] not in seen:
            c.info(line)
        if m["mountpoint"] in seen:
            continue
        seen.add(m["mountpoint"])
        try:
            st = os.statvfs(p)
        except OSError as e:
            c.fail(f"statvfs({p}) failed: {oserror_text(e)}")
            continue
        total, free = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
        pct = 100 * free / total if total else 100
        ipct = 100 * st.f_favail / st.f_files if st.f_files else 100
        msg = f"{m['mountpoint']}: free {fmt_bytes(free)} of {fmt_bytes(total)} ({pct:.1f}%), free inodes {ipct:.1f}%"
        if pct < 3 or ipct < 3:
            c.fail(msg)
        elif pct < 10 or ipct < 10:
            c.warn(msg)
        else:
            c.info(msg)
    c.summary = f"{len(seen)} filesystems checked"


IO_TEST_PREFIX = ".fpgaemu-diag-"


def _remove_io_leftovers(directory):
    """Leftovers of previous (killed) runs. Older versions created a directory here, which the
    profile page would list as a user, so remove those too."""
    removed = []
    try:
        for old in Path(directory).glob(IO_TEST_PREFIX + "*"):
            # Only old ones: a test of another container (or a stuck one that woke up) may be running.
            if time.time() - old.lstat().st_mtime < 3600:
                continue
            progress(f"removing leftover {old}")
            if old.is_dir() and not old.is_symlink():
                shutil.rmtree(old, ignore_errors=True)
            else:
                old.unlink()
            removed.append(str(old))
    except OSError:
        pass
    return removed


def _io_test(c, directory, size_mib):
    """Writes random data, fsyncs, evicts page cache and reads it back."""
    data = os.urandom(1 << 20)
    expected = hashlib.sha256()
    # Unique per container and run: PIDs repeat in every container (the test process is often
    # pid 17), so a stuck test of an old container could otherwise delete this one's files.
    prefix = f"{IO_TEST_PREFIX}{socket.gethostname()}-{os.getpid()}-{secrets.token_hex(3)}"
    path = Path(directory) / f"{prefix}.bin"
    res = {"dir": str(directory)}
    progress(f"write/read test in {directory}")
    small = [Path(directory) / f"{prefix}-s{i}" for i in range(100)]
    try:
        t0 = time.monotonic()
        res["step"] = "create/write big file"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            for i in range(size_mib):
                block = bytes([i & 0xFF]) + data[1:]
                expected.update(block)
                view = memoryview(block)
                while view:
                    view = view[os.write(fd, view):]
            t1 = time.monotonic()
            os.fsync(fd)
            t2 = time.monotonic()
        finally:
            os.close(fd)
        res["write_mibs"] = round(size_mib / max(t2 - t0, 1e-6), 1)
        res["fsync_s"] = round(t2 - t1, 3)
        res["step"] = "read back big file"
        fd = os.open(path, os.O_RDONLY)
        try:
            if hasattr(os, "posix_fadvise"):
                os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)  # force reading from disk
            t3 = time.monotonic()
            got = hashlib.sha256()
            while True:
                b = os.read(fd, 1 << 20)
                if not b:
                    break
                got.update(b)
            t4 = time.monotonic()
        finally:
            os.close(fd)
        res["read_mibs"] = round(size_mib / max(t4 - t3, 1e-6), 1)
        res["match"] = got.digest() == expected.digest()
        # Small files / metadata operations
        t5 = time.monotonic()
        res["step"] = "write 100 small files"
        for i, f in enumerate(small):
            f.write_bytes(b"%d" % i * 50)
        res["step"] = "read 100 small files"
        bad_small = sum(1 for i, f in enumerate(small) if f.read_bytes() != b"%d" % i * 50)
        res["step"] = "delete 100 small files"
        for f in small:
            f.unlink()
        res["small_files_s"] = round(time.monotonic() - t5, 3)
        res["small_bad"] = bad_small
    except OSError as e:
        res["error"] = f"{oserror_text(e)} (during: {res.get('step', '?')}, file {e.filename or '?'})"
    finally:
        for f in [path] + small:
            try:
                f.unlink()
            except OSError:
                pass
    return res


def check_io(c, mode):
    size = 64 if mode == "full" else 8
    mounts = _mounts()
    done = set()
    for p in key_paths():
        for f in _remove_io_leftovers(p):
            c.info(f"Removed leftover of a previous test: {f}")
        m = _mount_for(p, mounts)
        mp = m["mountpoint"] if m else str(p)
        if mp in done or not os.access(p, os.W_OK):
            continue
        done.add(mp)
        r = _io_test(c, p, size)
        c.data[str(p)] = r
        if "error" in r:
            c.fail(f"{p}: write/read test failed: {r['error']}")
            continue
        line = (f"{p}: write {r['write_mibs']} MiB/s, fsync {r['fsync_s']}s, read {r['read_mibs']} MiB/s, "
                f"100 small files {r['small_files_s']}s")
        if not r["match"] or r["small_bad"]:
            c.fail(f"{p}: DATA READ BACK DIFFERS FROM DATA WRITTEN ({size} MiB test, {r['small_bad']} bad small files). {line}")
        elif r["fsync_s"] > 10 or r["small_files_s"] > 10:
            c.fail(f"{p}: extremely slow storage. {line}")
        elif r["fsync_s"] > 2 or r["small_files_s"] > 3 or r["read_mibs"] < 5:
            c.warn(f"{p}: slow storage. {line}")
        else:
            c.info(line)
    c.summary = f"{size} MiB write/fsync/read test on {len(done)} filesystems"


def check_kernel_log(c, mode):
    rc, out, _ = run_cmd(["dmesg", "-T"], timeout=15)
    if rc != 0:
        rc, out, _ = run_cmd(["dmesg"], timeout=15)
    if rc != 0:
        c.status = "skip"
        c.summary = "kernel log not readable from inside the container (normal)"
        c.info("Ask the host administrator to check `dmesg`, `journalctl -k` and `smartctl -a` on the server disk.")
        c.info(out.strip()[:300])
        return
    disk = [l for l in out.splitlines() if DISK_ERROR_RE.search(l)]
    other = [l for l in out.splitlines() if OTHER_ERROR_RE.search(l)]
    for l in disk[-60:]:
        c.fail(l)
    for l in other[-30:]:
        c.warn(l)
    c.summary = f"{len(disk)} disk-related and {len(other)} other error lines"


def check_image_integrity(c, mode):
    if not MANIFEST_FILE.exists():
        c.warn(f"No manifest at {MANIFEST_FILE}: the image was built without `diagnose.py manifest`.")
        c.summary = "manifest missing"
        return
    try:
        m = load_manifest()
    except Exception as e:
        c.fail(f"The manifest file itself is unreadable/corrupted: {e}")
        c.summary = "manifest corrupted"
        return
    files = m["files"]
    if mode != "full":  # quick mode: only the application code (not .venv / GHDL / Surfer)
        venv = str(APP_DIR / ".venv")
        files = {k: v for k, v in files.items() if k.startswith(str(APP_DIR)) and not k.startswith(venv)}
    bad, missing, ioerr, slow = [], [], [], []
    nbytes = 0
    t0 = time.monotonic()
    for path, info in sorted(files.items()):
        p = Path(path)
        try:
            if "link" in info:
                if os.readlink(p) != info["link"]:
                    bad.append(f"{path}: symlink now points to {os.readlink(p)} (expected {info['link']})")
                continue
            digest, size, secs = hash_file(p)
            nbytes += size
            if digest != info["sha256"]:
                bad.append(f"{path}: content changed (size {size}, expected {info['size']})")
            if secs > 1.0:
                slow.append((secs, path, size))
        except FileNotFoundError:
            missing.append(path)
        except OSError as e:
            (ioerr if e.errno == errno.EIO else bad).append(f"{path}: {oserror_text(e)}")
    elapsed = time.monotonic() - t0
    for l in ioerr:
        c.fail(f"I/O ERROR reading {l}")
    for l in bad:
        c.fail(f"CORRUPTED/CHANGED: {l}")
    for l in missing:
        c.fail(f"MISSING: {l}")
    for secs, path, size in sorted(slow, reverse=True)[:15]:
        c.warn(f"Slow read: {path} ({fmt_bytes(size)}) took {secs:.1f}s")
    c.data.update({"checked": len(files), "bad": len(bad), "missing": len(missing), "io_errors": len(ioerr),
                   "bytes": nbytes, "seconds": round(elapsed, 1)})
    scope = "whole image" if mode == "full" else "application code only"
    c.summary = (f"{len(files)} files ({fmt_bytes(nbytes)}, {scope}) in {elapsed:.0f}s: "
                 f"{len(bad)} changed, {len(missing)} missing, {len(ioerr)} I/O errors")


def check_dpkg(c, mode):
    if mode != "full":
        c.status = "skip"
        c.summary = "only in full mode"
        return
    if not shutil.which("dpkg"):
        c.status = "skip"
        c.summary = "dpkg not available"
        return
    rc, out, secs = run_cmd(["dpkg", "--verify"], timeout=900)
    changed, missing, other = [], [], []
    for line in out.splitlines():
        if line.startswith("missing"):
            missing.append(line)
        elif re.match(r"^\S{9} +c ", line):
            continue  # configuration files are expected to change
        elif re.match(r"^\S{2}5", line):
            changed.append(line)
        elif line.strip():
            other.append(line)
    # Paths excluded from the slim image (docs, man pages, locales) show up as "missing".
    real_missing = [l for l in missing if not re.search(r"/usr/share/(doc|man|locale|info|lintian)/", l)]
    for l in changed:
        c.fail(f"System file checksum differs from Debian package: {l}")
    for l in real_missing[:50]:
        c.warn(f"System file missing: {l}")
    for l in other[:20]:
        c.info(l)
    if rc is None:
        c.warn("dpkg --verify timed out")
    c.summary = f"{len(changed)} modified system files, {len(real_missing)} missing ({secs:.0f}s)"


def check_python_env(c, mode):
    py = APP_DIR / ".venv" / "bin" / "python"
    if not py.exists():
        c.fail(f"{py} does not exist")
        c.summary = "virtualenv missing"
        return
    code = ("import importlib,time,sys\n"
            "for m in sys.argv[1:]:\n"
            "    t=time.time()\n"
            "    try:\n"
            "        importlib.import_module(m); print('OK',m,round(time.time()-t,2))\n"
            "    except BaseException as e:\n"
            "        print('FAIL',m,type(e).__name__,e)\n")
    rc, out, secs = run_cmd([str(py), "-c", code] + PYTHON_MODULES, timeout=180, cwd=str(APP_DIR))
    failed = [l for l in out.splitlines() if l.startswith("FAIL")]
    for l in failed:
        c.fail(l)
    if rc != 0:
        c.fail(f"Interpreter exited with {rc}:")
        for l in tail(out, 20):
            c.fail(l)
    # Compile application sources (catches damaged .py files that were not imported above)
    # (never walk the data dirs: work/ is on NFS and may stall)
    rc2, out2, _ = run_cmd([str(py), "-c",
                            "import os,sys\n"
                            "skip={'.venv','work','cachedwork','persistentwork','temp','.worksync','.git','node_modules'}\n"
                            "for d,dirs,files in os.walk(sys.argv[1]):\n"
                            "    dirs[:]=[x for x in dirs if x not in skip]\n"
                            "    for f in files:\n"
                            "        if not f.endswith('.py'): continue\n"
                            "        p=os.path.join(d,f)\n"
                            "        try: compile(open(p,'rb').read(), p, 'exec')\n"
                            "        except BaseException as e: print('FAIL', p, type(e).__name__, e)\n",
                            str(APP_DIR)], timeout=120)
    for l in out2.splitlines():
        if l.startswith("FAIL"):
            c.fail(l)
    if rc2 not in (0,):
        c.fail(f"Compile check exited with {rc2}: {' | '.join(tail(out2, 5))}")
    if secs > 30:
        c.warn(f"Importing the modules took {secs:.0f}s (slow disk?)")
    c.summary = f"{len(PYTHON_MODULES) - len(failed)}/{len(PYTHON_MODULES)} modules import ({secs:.1f}s)"


TEST_VHDL = """library ieee; use ieee.std_logic_1164.all; use ieee.numeric_std.all;
entity diagtb is end diagtb;
architecture a of diagtb is
  signal c : unsigned(7 downto 0) := (others => '0');
  signal clk : std_logic := '0';
begin
  clk <= not clk after 5 ns;
  process(clk) begin if rising_edge(clk) then c <= c + 1; end if; end process;
  process begin
    wait for 1000 ns;
    assert c = to_unsigned(100, 8) report "DIAG_MISMATCH" severity failure;
    report "DIAG_OK";
    wait;
  end process;
end a;
"""


def check_toolchain(c, mode):
    rc, out, _ = run_cmd(["ghdl", "--version"], timeout=30)
    if rc != 0:
        c.fail(f"ghdl --version failed: {' | '.join(tail(out, 5))}")
    else:
        c.info(out.splitlines()[0] if out else "ghdl ok")
    backend = APP_DIR / "backend"
    for name in ("fpgacompileweb", "fpgaemu_c.o", "fpgaemu.vhd", "fpgaemu.c"):
        if not (backend / name).exists():
            c.warn(f"backend/{name} does not exist (compilebackend.sh not run or failed?)")
    with tempfile.TemporaryDirectory(prefix="fpgaemu-diag-") as td:
        steps = [
            ("gcc backend", ["gcc", "-c", "-Wall", "-W", "-D_REENTRANT", str(backend / "fpgaemu.c"), "-o", "t.o"]),
            ("ghdl -a fpgaemu.vhd", ["ghdl", "-a", "-fexplicit", "--ieee=synopsys", str(backend / "fpgaemu.vhd")]),
        ]
        Path(td, "diagtb.vhd").write_text(TEST_VHDL)
        steps += [
            ("ghdl -a testbench", ["ghdl", "-a", "-fexplicit", "--ieee=synopsys", "diagtb.vhd"]),
            ("ghdl -e testbench", ["ghdl", "-e", "-fexplicit", "--ieee=synopsys", "diagtb"]),
            ("ghdl -r testbench", ["ghdl", "-r", "diagtb", "--stop-time=2us"]),
        ]
        for label, cmd in steps:
            rc, out, secs = run_cmd(cmd, timeout=180, cwd=td)
            ok = rc == 0 and (label != "ghdl -r testbench" or "DIAG_OK" in out)
            if not ok:
                c.fail(f"{label} FAILED (rc={rc}, {secs:.1f}s):")
                for l in tail(out, 12):
                    c.fail("    " + l)
                if label.startswith("ghdl -a test") or label.startswith("ghdl -e"):
                    break
            elif secs > 60:
                c.warn(f"{label}: ok but slow ({secs:.1f}s)")
            else:
                c.info(f"{label}: ok ({secs:.1f}s)")
    c.summary = "compile/simulate test " + ("passed" if c.status in ("ok", "info") else "with problems")


SQLITE_PROBE = r"""
import sqlite3, sys, time
path, pragma = sys.argv[1], sys.argv[2]
t = time.time()
con = sqlite3.connect('file:' + path + '?mode=ro', uri=True, timeout=5)
print('OPEN', round(time.time() - t, 2), flush=True)
t = time.time()
res = [r[0] for r in con.execute('PRAGMA ' + pragma).fetchall()]
print('CHECK', round(time.time() - t, 2), flush=True)
for r in res[:30]:
    print('RES', r, flush=True)
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print('TABLES', ' '.join(tables), flush=True)
if 'user' in tables:
    t = time.time()
    n = con.execute('SELECT count(*) FROM user').fetchone()[0]
    print('USERS', n, round(time.time() - t, 2), flush=True)
"""


def _file_locks(path):
    """Processes holding POSIX/flock locks on path (from /proc/locks)."""
    try:
        st = os.stat(path)
    except OSError:
        return []
    res = []
    for line in read_text("/proc/locks").splitlines():
        parts = line.split()
        if "->" in parts:  # waiting for a lock
            parts.remove("->")
            waiting = True
        else:
            waiting = False
        try:
            maj, mnr, ino = parts[5].split(":")
            if int(ino) != st.st_ino:
                continue
            pid = int(parts[4])
        except (IndexError, ValueError):
            continue
        cmd = " ".join(read_text(f"/proc/{pid}/cmdline").replace("\0", " ").split())
        res.append(f"{'WAITING for ' if waiting else ''}{parts[1]} {parts[3]} lock, range {' '.join(parts[6:8])}, "
                   f"pid {pid} {cmd[:120]}")
    return res


def _open_by(path):
    """Processes that have path open (via /proc/*/fd)."""
    target = str(Path(path).resolve())
    res = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            for fd in (d / "fd").iterdir():
                try:
                    if os.readlink(fd) == target:
                        st = read_text(d / "stat")
                        state = st[st.rindex(")") + 2] if ")" in st else "?"
                        cmd = " ".join(read_text(d / "cmdline").replace("\0", " ").split())
                        res.append(f"pid {d.name} (state {state}, waiting in {read_text(d / 'wchan').strip() or '?'}): {cmd[:120]}")
                        break
                except OSError:
                    continue
        except OSError:
            continue
    return res


def _sqlite_check(c, path, full):
    try:
        st = path.stat()
        c.info(f"{path}: {fmt_bytes(st.st_size)}, modified {datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec='seconds')}")
    except OSError as e:
        c.fail(f"Cannot stat {path}: {oserror_text(e)}")
        return
    for suffix in ("-journal", "-wal", "-shm"):
        side = Path(str(path) + suffix)
        if side.exists():
            sz = side.stat().st_size
            msg = f"{side.name} exists ({fmt_bytes(sz)})"
            if suffix == "-journal" and sz > 0:
                c.warn(msg + ": unfinished transaction (hot journal) — a writer crashed or is stuck mid-write.")
            else:
                c.info(msg)
    locks = _file_locks(path)
    for l in locks:
        c.info(f"Lock on {path.name}: {l}")
    for l in _open_by(path):
        c.info(f"Open by {l}")
    # Raw read of the whole file, in a subprocess so a blocked read cannot hang us.
    progress(f"raw read of {path}")
    rc, out, secs = run_cmd(["dd", f"if={path}", "of=/dev/null", "bs=1M"], timeout=120)
    if rc is None:
        c.fail(f"Reading the raw file {path} did NOT finish in 120 s (blocked read — disk/filesystem problem).")
        return
    if rc != 0:
        c.fail(f"Raw read of {path} failed ({secs:.1f}s): {' | '.join(tail(out, 3))}")
        return
    c.info(f"Raw read of the whole file: {secs:.2f}s")
    progress(f"SQLite check of {path}")
    py = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
    rc, out, secs = run_cmd([py, "-c", SQLITE_PROBE, str(path), "integrity_check" if full else "quick_check"],
                            timeout=300)
    lines = out.splitlines()
    res = [l[4:] for l in lines if l.startswith("RES ")]
    if rc is None:
        stage = "opening the database" if not any(l.startswith("OPEN") for l in lines) else "running the integrity check"
        c.fail(f"SQLite {path}: HUNG while {stage} (killed after 300 s).")
        return
    if rc != 0:
        err = tail(out, 1)[0] if out.strip() else f"exit {rc}"
        if "locked" in err:
            c.fail(f"SQLite {path}: {err} — another process holds a lock:")
            for l in locks:
                c.fail(f"    {l}")
        else:
            c.fail(f"SQLite {path}: {err}")
        return
    if res != ["ok"]:
        c.fail(f"SQLite {path} is CORRUPTED:")
        for r in res:
            c.fail("    " + r)
        return
    users = next((l.split() for l in lines if l.startswith("USERS")), None)
    tables = next((l[7:].split() for l in lines if l.startswith("TABLES")), [])
    extra = f", {users[1]} users (count took {users[2]}s)" if users else ""
    c.info(f"SQLite {path}: integrity ok in {secs:.1f}s ({len(tables)} tables{extra})")
    if secs > 30:
        c.warn(f"SQLite check of {path} was slow ({secs:.0f}s)")


def _databases():
    dbs = [APP_DIR / "huey.db"]
    for w in WORKDIRS:
        if w.exists():
            dbs += sorted(p for p in w.iterdir() if p.suffix in (".sqlite", ".db") and p.is_file())
    return [d for d in dbs if d.exists()]


def check_databases(c, mode):
    """Local SQLite databases. The one the app uses is <workdir>/dbb.sqlite."""
    cw = os.environ.get("ENVCACHEDWORK", "")
    active = APP_DIR / ("work" if cw in ("", "False") else "cachedwork") / "dbb.sqlite"
    c.info(f"Database used by the app (ENVCACHEDWORK={cw or 'unset'}): {active}")
    if not active.exists():
        c.warn(f"{active} does not exist (the app creates a new empty one at start).")
    else:
        sk = active.parent / "seckeyb"
        if not sk.exists() or sk.stat().st_size != 16:
            c.warn(f"{sk} missing or with unexpected size (sessions become invalid)")
    dbs = _databases()
    # The active database first: it is the one that matters.
    dbs.sort(key=lambda p: p != active)
    for db in dbs:
        _sqlite_check(c, db, mode == "full")
    c.summary = f"{len(dbs)} SQLite databases checked"


TEXT_SUFFIXES = {".vhd", ".vhdl", ".map", ".json", ".conf", ".config", ".txt", ".py", ".sh", ".html", ".js", ".css"}


def _scan_file(p, text_check):
    """Streams the file. Returns (size, seconds, all_zero, has_nul, head)."""
    size = 0
    all_zero = True
    has_nul = False
    head = b""
    t0 = time.monotonic()
    with open(p, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            if size == 0:
                head = b[:1 << 20]
            size += len(b)
            if all_zero and b.count(0) != len(b):
                all_zero = False
            if text_check and not has_nul and b"\x00" in b:
                has_nul = True
    return size, time.monotonic() - t0, all_zero and size > 0, has_nul, head


NFS_SAMPLE = 200


def _nfs_sample(c):
    """With worksync, reading the whole NFS tree (100k+ files) takes long and loads a struggling
    NFS: read a random sample of the files the index says are there, and time it."""
    import random
    paths = []
    try:
        with open(APP_DIR / ".worksync" / "index.tsv", encoding="utf-8", errors="surrogateescape") as f:
            paths = [l.rstrip("\n").split("\t", 3)[3] for l in f if l.startswith("f\t")]
    except (OSError, IndexError):
        pass
    if not paths:
        c.info("NFS sample skipped: no worksync index yet.")
        return
    sample = random.sample(paths, min(NFS_SAMPLE, len(paths)))
    times, errs = [], 0
    for rel in sample:
        p = APP_DIR / "work" / rel
        progress(f"NFS sample: reading {p}")
        try:
            t0 = time.monotonic()
            _scan_file(p, False)
            times.append((time.monotonic() - t0, str(p)))
        except FileNotFoundError:
            pass
        except OSError as e:
            errs += 1
            c.fail(f"I/O ERROR reading {p} on NFS: {oserror_text(e)}" if e.errno == errno.EIO
                   else f"Cannot read {p} on NFS: {oserror_text(e)}")
    if times:
        ts = sorted(t for t, _ in times)
        line = (f"NFS sample: {len(times)} random files read, median {ts[len(ts) // 2] * 1000:.0f} ms, "
                f"slowest {ts[-1]:.1f} s, {sum(1 for t in ts if t > 1)} over 1 s")
        (c.warn if ts[len(ts) // 2] > 0.5 or ts[-1] > 5 else c.info)(line)
        for t, p in sorted(times, reverse=True)[:5]:
            if t > 1:
                c.info(f"    slow NFS read: {p} {t:.1f} s")


def check_workdata(c, mode):
    nfiles = nbytes = 0
    slow, big = [], []
    synced = sync_status() is not None
    if synced:
        _nfs_sample(c)
    for w in WORKDIRS:
        if not w.exists() or (synced and w == APP_DIR / "work"):
            continue
        for p, err in iter_tree(w):
            if err:
                c.fail(f"Cannot list {p}: {oserror_text(err)}")
                continue
            if p.is_symlink() or not p.is_file():
                continue
            progress(f"reading {p}")
            name = p.name.lower()
            suffix = p.suffix.lower()
            is_text = suffix in TEXT_SUFFIXES or name == ".config"
            try:
                size, secs, all_zero, has_nul, head = _scan_file(p, is_text)
            except OSError as e:
                c.fail(f"I/O ERROR reading {p}: {oserror_text(e)}" if e.errno == errno.EIO
                       else f"Cannot read {p}: {oserror_text(e)}")
                continue
            nfiles += 1
            nbytes += size
            big.append((size, str(p)))
            if secs > 1.0:
                slow.append((secs, str(p), size))
            if all_zero:
                c.fail(f"File contains only zero bytes (typical of lost data): {p} ({size} B)")
            elif is_text and has_nul:
                c.fail(f"Text file contains NUL bytes (possible corruption): {p}")
            elif suffix in (".vhd", ".vhdl", ".map") and size <= len(head):
                try:
                    head.decode("utf-8")
                except UnicodeDecodeError:
                    c.info(f"Not UTF-8 (probably Latin-1, usually harmless): {p}")
            if suffix == ".json" and p.parent == w and size <= len(head):
                try:
                    json.loads(head or b"{}")
                except ValueError as e:
                    c.warn(f"Invalid JSON {p}: {e}")
    for secs, path, size in sorted(slow, reverse=True)[:15]:
        c.warn(f"Slow read: {path} ({fmt_bytes(size)}) took {secs:.1f}s")
    for size, path in sorted(big, reverse=True)[:5]:
        c.info(f"Large file: {path} ({fmt_bytes(size)})")
    c.summary = f"{nfiles} files ({fmt_bytes(nbytes)}) read"


def _procs():
    res = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            stat = (d / "stat").read_text()
            cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
            name = stat[stat.index("(") + 1:stat.rindex(")")]
            state = stat[stat.rindex(")") + 2]
            res.append({"pid": int(d.name), "name": name, "state": state, "cmd": cmd or f"[{name}]"})
        except (OSError, ValueError):
            continue
    return res


def check_processes(c, mode):
    procs = _procs()
    expect = {"supervisord": "supervisord", "gunicorn (web app)": "gunicorn", "huey (task worker)": "huey_consumer",
              "cron": "cron"}
    for label, pat in expect.items():
        found = [p for p in procs if pat in p["cmd"]]
        if not found:
            (c.warn if label == "cron" else c.fail)(f"Process not running: {label}")
        else:
            c.info(f"{label}: running (pid {', '.join(str(p['pid']) for p in found[:5])})")
    dstate = [p for p in procs if p["state"] == "D"]
    zombies = [p for p in procs if p["state"] == "Z"]
    for p in dstate:
        c.warn(f"Process in uninterruptible I/O wait (state D): pid {p['pid']} {p['cmd'][:150]}")
        wchan = read_text(f"/proc/{p['pid']}/wchan").strip() or "?"
        c.info(f"    kernel wait channel: {wchan}")
        files = set()
        try:
            for fd in Path(f"/proc/{p['pid']}/fd").iterdir():
                try:
                    t = os.readlink(fd)
                    if t.startswith("/") and not t.startswith(("/dev/", "/proc/")):
                        files.add(t)
                except OSError:
                    pass
        except OSError:
            pass
        for f in sorted(files)[:10]:
            c.info(f"    open file: {f}")
    if len(zombies) > 5:
        c.warn(f"{len(zombies)} zombie processes")
    old_ghdl = [p for p in procs if p["name"] in ("ghdl", "ghdl1-llvm", "fpgatest") or "fpgacompileweb" in p["cmd"]]
    if old_ghdl:
        c.info(f"{len(old_ghdl)} GHDL/emulation processes running")
    # Is the web app answering?
    # Right after container start gunicorn may still be booting: give it up to 2 minutes.
    deadline = time.monotonic() + 120
    while not _port_in_use(APP_PORT) and time.monotonic() < deadline:
        time.sleep(5)
    try:
        t0 = time.monotonic()
        s = socket.create_connection(("127.0.0.1", APP_PORT), timeout=15)
        s.settimeout(30)
        s.sendall(b"GET /login HTTP/1.0\r\nHost: localhost\r\n\r\n")
        first = s.recv(200).split(b"\r\n")[0].decode("latin-1")
        s.close()
        secs = time.monotonic() - t0
        if not re.search(r" (200|30\d)\b", first):
            c.fail(f"Web app on port {APP_PORT} answered '{first}' to GET /login ({secs:.1f}s)")
        elif secs > 5:
            c.warn(f"Web app answered '{first}' but took {secs:.1f}s")
        else:
            c.info(f"Web app answered '{first}' in {secs:.2f}s")
    except OSError as e:
        c.fail(f"Web app is not answering on port {APP_PORT}: {e}")
    c.summary = f"{len(procs)} processes, {len(dstate)} in I/O wait"


def _log_candidates():
    c = [Path("/home/supervisord.log"), Path("/supervisord.log"), Path("/var/log/supervisor/supervisord.log"),
         APP_DIR / "supervisord.log"]
    return [p for p in c if p.exists()]


def check_supervisor(c, mode):
    logs = _log_candidates()
    if not logs:
        c.status = "skip"
        c.summary = "supervisord log not found"
        return
    text = ""
    for p in logs:
        for q in (Path(str(p) + ".1"), p):
            text += read_text(q)
    counts = {}
    events = []
    for line in text.splitlines():
        m = re.search(r"(spawned|exited|gave up|success): '?([\w-]+)'?", line)
        if m:
            counts.setdefault(m.group(2), {}).setdefault(m.group(1), 0)
            counts[m.group(2)][m.group(1)] += 1
            if m.group(1) in ("exited", "gave up"):
                events.append(line)
    for prog, cnt in counts.items():
        ex = cnt.get("exited", 0)
        msg = f"{prog}: started {cnt.get('spawned', 0)}x, exited {ex}x" + (", GAVE UP" if cnt.get("gave up") else "")
        if cnt.get("gave up"):
            c.fail(msg)
        elif ex >= 3 and prog != "diagfallback":
            c.warn(msg)
        else:
            c.info(msg)
    for l in events[-20:]:
        c.info(l)
    c.summary = ", ".join(f"{k}: {v.get('exited', 0)} exits" for k, v in counts.items()) or "no events"


def check_logs(c, mode):
    files = [Path("/home/stderr.log"), Path("/home/stdout.log")] + [w / "emulogs.log" for w in WORKDIRS]
    files = [f for f in files if f.exists()]
    files += [Path(str(f) + ".1") for f in files if Path(str(f) + ".1").exists()]
    total_disk = total_other = 0
    for f in files:
        try:
            with open(f, "rb") as fh:
                fh.seek(0, 2)
                size = fh.tell()
                fh.seek(max(0, size - 2_000_000))
                lines = fh.read().decode("utf-8", "replace").splitlines()
        except OSError as e:
            c.fail(f"Cannot read {f}: {oserror_text(e)}")
            continue
        disk = [l for l in lines if DISK_ERROR_RE.search(l)]
        other = [l for l in lines if OTHER_ERROR_RE.search(l)]
        total_disk += len(disk)
        total_other += len(other)
        c.info(f"{f}: {len(lines)} lines, {len(disk)} disk-related errors, {len(other)} other errors")
        for l in disk[-15:]:
            c.fail(f"[{f.name}] {l[:400]}")
        for l in other[-10:]:
            c.warn(f"[{f.name}] {l[:400]}")
    c.summary = f"{total_disk} disk-related and {total_other} other error lines in {len(files)} log files"


WORKSYNC_STATUS = APP_DIR / ".worksync" / "status.json"


def sync_status():
    """(level, text lines) describing worksync.py, or None when it is not in use."""
    if os.environ.get("ENVCACHEDWORK", "") in ("", "False"):
        return None
    try:
        st = json.loads(WORKSYNC_STATUS.read_text())
    except (OSError, ValueError):
        return "warn", ["No sync status yet (worksync.py starting?)."]
    lines = []
    level = "ok"
    interval = int(os.environ.get("WORKSYNC_INTERVAL", "180"))
    if not (APP_DIR / ".worksync" / "ready").exists():
        level = "fail"
        lines.append(f"Initial copy NFS → local NOT finished: phase {st.get('phase')}, "
                     f"attempt {st.get('pull_attempts')}, started {st.get('pull_started')}. The web app waits for it.")
    else:
        ps = st.get("pull_stats") or {}
        lines.append(f"App works on local disk since {st.get('ready_since') or '(before this restart)'}"
                     + (f"; initial copy took {st.get('pull_seconds')} s, {ps.get('files')} entries." if ps else "."))
        last_ok = st.get("last_push_ok")
        lines.append(f"Last successful save to NFS: {last_ok or 'none yet'}"
                     + (f" ({st.get('last_push_seconds')} s, {(st.get('last_push_stats') or {}).get('transferred')} files, "
                        f"{(st.get('last_push_stats') or {}).get('deleted') or 0} deleted, "
                        f"databases {st.get('last_push_dbs') or 'unchanged'})" if last_ok else "")
                     + f". Saves every {interval} s.")
        ref = last_ok or st.get("ready_since")
        if ref:
            age = (datetime.datetime.now().astimezone() - datetime.datetime.fromisoformat(ref)).total_seconds()
            if age > 3 * interval + 600:
                level = "fail"
                lines.append(f"Local changes NOT saved to NFS for {int(age // 60)} min.")
        fp = st.get("full_pull_phase")
        if fp and fp != "done":
            level = "fail" if level == "fail" else "warn"
            failed = st.get("folders_failed") or {}
            lines.append(f"User folders being copied from NFS ({fp}): {st.get('folders_done', 0)} of "
                         f"{st.get('folders_total', '?')} done, pass {st.get('full_pull_attempts')}"
                         + (f", now {st['current_folder']}" if st.get("current_folder") else "")
                         + (f", {len(failed)} failed so far (retried later)" if failed else "")
                         + ". Students whose folder was not copied yet may not see their projects.")
            if st.get("full_pull_error"):
                lines.append(f"Last folder problem: {st['full_pull_error']}")
        elif fp == "done":
            lines.append(f"All {st.get('folders_total', '?')} user folders copied from NFS at {st.get('full_pull_done')}.")
        if st.get("last_reconcile"):
            rs = st.get("last_reconcile_stats") or {}
            lines.append(f"Last full reconciliation: {st['last_reconcile']} ({st.get('last_reconcile_seconds')} s, "
                         f"{rs.get('transferred')} files sent).")
        if st.get("consecutive_push_failures"):
            level = "fail" if level == "fail" else "warn"
            lines.append(f"{st['consecutive_push_failures']} consecutive failed saves.")
        if not st.get("push_delete", True):
            level = "fail" if level == "fail" else "warn"
            lines.append("Initial copy was incomplete (unreadable files on NFS): deletions are not propagated to NFS.")
        if st.get("db_problems"):
            level = "fail"
            lines.append(f"Database problems after the copy: {st['db_problems']}")
        if st.get("last_push_warning"):
            lines.append(f"Warning: {st['last_push_warning']}")
    if st.get("last_error"):
        lines.append(f"Last error: {st['last_error']}")
    return level, lines


def check_worksync(c, mode):
    s = sync_status()
    if s is None:
        c.status = "skip"
        c.summary = "not in use (ENVCACHEDWORK is not True: the app works directly on work/)"
        return
    level, lines = s
    add = {"ok": c.info, "warn": c.warn, "fail": c.fail}[level]
    for l in lines:
        add(l)
    c.summary = lines[0][:200]


def _sync_card():
    s = sync_status()
    if s is None:
        return ""
    level, lines = s
    e = html.escape
    return (f"<div class='card'><span class='badge b-{level}'>{level.upper()}</span> <b>Data sync (local disk ↔ NFS)</b>"
            f"<div class='lines'>" + "".join(f"<div>{e(l)}</div>" for l in lines) + "</div></div>")


# (id, title, function, timeout in seconds for quick mode, for full mode)
CHECKS = [
    ("environment", "Environment", check_environment, 60, 60),
    ("memory", "Memory, OOM and cgroup limits", check_memory, 60, 60),
    ("filesystems", "Filesystems: read-only mounts, free space", check_filesystems, 120, 120),
    ("worksync", "Data sync between local disk and NFS (worksync)", check_worksync, 30, 30),
    ("io", "Disk write/read-back test", check_io, 300, 600),
    ("kernel", "Kernel log (dmesg)", check_kernel_log, 60, 60),
    ("databases", "Local SQLite databases (locks, integrity)", check_databases, 900, 1800),
    ("image", "Image integrity (checksums vs build manifest)", check_image_integrity, 600, 3600),
    ("dpkg", "System packages integrity (dpkg --verify)", check_dpkg, 60, 1200),
    ("python", "Python environment (.venv)", check_python_env, 400, 400),
    ("toolchain", "GHDL/GCC compile and simulation test", check_toolchain, 900, 900),
    ("workdata", "User data files", check_workdata, 600, 1200),
    ("processes", "Processes and web app response", check_processes, 300, 300),
    ("supervisor", "Supervisor restarts", check_supervisor, 60, 60),
    ("logs", "Application logs", check_logs, 120, 120),
]


# --------------------------------------------------------------------------- run

def _run_isolated(cid, title, fn, mode, timeout, d, report):
    """Runs one check in a forked child, so a check blocked on I/O cannot hang the whole run."""
    global _PROGRESS_FILE
    pfile = d / "progress.txt"
    try:
        pfile.unlink()
    except OSError:
        pass
    report["current"] = f"{title} — starting"
    report["step_started"] = time.time()
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:  # child
        os.close(r)
        _PROGRESS_FILE = pfile
        c = Check(cid, title)
        t0 = time.monotonic()
        try:
            fn(c, mode)
        except Exception as e:
            c.fail(f"The check itself crashed: {type(e).__name__}: {e}")
            for l in traceback.format_exc().splitlines()[-8:]:
                c.info(l)
        c.duration = time.monotonic() - t0
        data = json.dumps(c.to_dict()).encode()
        with os.fdopen(w, "wb") as f:
            f.write(data)
        os._exit(0)
    os.close(w)
    buf = b""
    t0 = time.monotonic()
    os.set_blocking(r, False)
    import select
    eof = False
    while True:
        remaining = timeout - (time.monotonic() - t0)
        if remaining <= 0:
            break
        ready, _, _ = select.select([r], [], [], min(3.0, remaining))
        if ready:
            chunk = os.read(r, 1 << 16)
            if not chunk:
                eof = True
                break
            buf += chunk
        report["current"] = f"{title} — {read_text(pfile).strip() or 'starting'}"
        report["heartbeat"] = time.time()
        try:
            atomic_write(d / "running.json", json.dumps(report))
        except OSError:
            pass
    os.close(r)
    if eof:  # the child closed the pipe: it finished (or died); reap it and use its result
        try:
            _, wstatus = os.waitpid(pid, 0)
        except ChildProcessError:
            wstatus = 0
        try:
            return json.loads(buf)
        except ValueError:
            c = Check(cid, title)
            c.fail(f"The check process ended without a result (wait status {wstatus}).")
            c.summary = "check process died"
            c.duration = time.monotonic() - t0
            return c.to_dict()
    else:
        try:
            os.kill(pid, 9)
            os.waitpid(pid, os.WNOHANG)
        except OSError:
            pass
        c = Check(cid, title)
        last = read_text(pfile).strip() or "(no progress information)"
        c.fail(f"The check did NOT finish within {timeout} s and was abandoned. Last activity: {last}")
        c.info("A process stuck here usually means a read/write that never returns (disk or filesystem problem) "
               "or a lock held by another process. See 'Processes' below for processes in I/O wait (state D).")
        c.summary = f"HUNG — last activity: {last[:150]}"
        c.duration = time.monotonic() - t0
        return c.to_dict()


def say(line):
    """Prints and also writes to the container log (stdout of PID 1), visible in Portainer even
    when the web app is down."""
    print(line, flush=True)
    if os.getpid() == 1:
        return
    try:
        if os.path.samefile("/proc/self/fd/1", "/proc/1/fd/1"):
            return
    except OSError:
        pass
    try:
        with open("/proc/1/fd/1", "a") as f:
            f.write(f"[diagnostics {datetime.datetime.now():%H:%M:%S}] {line}\n")
    except OSError:
        pass


def run(args):
    d = diag_dir()
    running = d / "running.json"
    if running.exists():
        try:
            hb = json.loads(running.read_text()).get("heartbeat", 0)
        except (OSError, ValueError):
            hb = 0
        if time.time() - max(hb, running.stat().st_mtime) < 120:
            print("Another diagnostics run is in progress.")
            return 1
        print("Previous run looks dead (no heartbeat for 2 min); starting a new one.")
    say(f"Starting {args.mode} diagnostics ({args.reason})")
    report = {"started": now_iso(), "mode": args.mode, "reason": args.reason, "running": True,
              "diag_dir": str(d), "pid": os.getpid(), "heartbeat": time.time(), "checks": [],
              "steps": [c[1] for c in CHECKS]}
    atomic_write(running, json.dumps(report))
    t_start = time.monotonic()
    for cid, title, fn, tq, tf in CHECKS:
        res = _run_isolated(cid, title, fn, args.mode, tf if args.mode == "full" else tq, d, report)
        report["checks"].append(res)
        say(f"[{res['status'].upper():4}] {title}: {res['summary']} ({res['duration']}s)")
        problems = [t for lvl, t in res["details"] if lvl in ("warn", "fail")]
        for t in problems[:15]:
            say(f"       {t[:300]}")
        if len(problems) > 15:
            say(f"       ... {len(problems) - 15} more (see /diagnostics)")
    report.pop("current", None)
    report["running"] = False
    report["finished"] = now_iso()
    report["duration"] = round(time.monotonic() - t_start, 1)
    worst = max((ch["status"] for ch in report["checks"]), key=lambda s: STATUS_ORDER[s])
    report["overall"] = worst if worst in ("warn", "fail") else "ok"
    text = json.dumps(report, indent=1)
    atomic_write(d / "latest.json", text)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    atomic_write(d / "history" / f"{stamp}-{args.mode}.json", text)
    for old in sorted((d / "history").glob("*.json"))[:-HISTORY_KEEP]:
        old.unlink()
    for f in (running, d / "progress.txt"):
        try:
            f.unlink()
        except OSError:
            pass
    say(f"Overall ({args.mode}, {args.reason}): {report['overall'].upper()} -> {d / 'latest.json'}")
    return 0


def start_background_run(mode, reason):
    """Spawns `run` detached (used by the web routes)."""
    py = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
    subprocess.Popen([py, str(Path(__file__).resolve()), "run", "--mode", mode, "--reason", reason],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, cwd=str(APP_DIR))


# --------------------------------------------------------------------------- access key

def _active_workdir():
    cw = os.environ.get("ENVCACHEDWORK", "")
    return APP_DIR / ("work" if cw in ("", "False") else "cachedwork")


def access_key(create=True):
    """DIAG_KEY env var, or a random key persisted in the app's work dir (shown in the admin page).
    With ENVCACHEDWORK=True that is cachedwork/, synced to work/ (NFS) by worksync.py, so the key
    survives re-deploys. create=False while the initial copy from NFS is not done (the key will
    come from there)."""
    env = os.environ.get("DIAG_KEY", "").strip()
    if env:
        return env
    for f in (_active_workdir() / ".diagkey", DIAG_DIR / "key", Path(tempfile.gettempdir()) / "fpgaemu-diagkey"):
        try:
            if f.exists():
                k = f.read_text().strip()
                if len(k) >= 16:
                    return k
            if not create:
                continue
            f.parent.mkdir(parents=True, exist_ok=True)
            k = secrets.token_urlsafe(18)
            f.write_text(k)
            f.chmod(0o600)
            return k
        except OSError:
            continue
    return None


def key_ok(given, create=True):
    k = access_key(create)
    return bool(k and given and hmac.compare_digest(str(given), k))


# --------------------------------------------------------------------------- report access / html

def load_latest():
    for d in (DIAG_DIR, Path(tempfile.gettempdir()) / "fpgaemu-diagnostics"):
        f = d / "latest.json"
        if f.exists():
            try:
                rep = json.loads(f.read_text())
            except (OSError, ValueError) as e:
                rep = {"error": f"Cannot read {f}: {e}", "checks": []}
            running = d / "running.json"
            if running.exists():
                try:
                    rep["in_progress"] = json.loads(running.read_text())
                except (OSError, ValueError):
                    pass
            return rep, d
        running = d / "running.json"
        if running.exists():
            try:
                return {"checks": [], "in_progress": json.loads(running.read_text())}, d
            except (OSError, ValueError):
                pass
    return None, None


def load_history(d):
    res = []
    if not d:
        return res
    for f in sorted((d / "history").glob("*.json"), reverse=True)[:HISTORY_KEEP]:
        try:
            r = json.loads(f.read_text())
            res.append({"file": f.name, "started": r.get("started"), "mode": r.get("mode"),
                        "reason": r.get("reason"), "overall": r.get("overall"),
                        "checks": {c["id"]: c["status"] for c in r.get("checks", [])}})
        except (OSError, ValueError) as e:
            res.append({"file": f.name, "started": "?", "overall": "fail", "mode": "", "reason": f"unreadable: {e}",
                        "checks": {}})
    return res


def summary_html(key_qs=""):
    """Small fragment for the admin page."""
    rep, _ = load_latest()
    e = html.escape
    parts = []
    ss = sync_status()
    if ss:
        level, lines = ss
        parts.append(f"<p><b>Data sync:</b> <b class='diag-{level}'>{level.upper()}</b> — " +
                     "<br>".join(e(l) for l in lines) + "</p>")
    if not rep:
        return "".join(parts) + "<p>No diagnostics report yet.</p>"
    if rep.get("in_progress"):
        ip = rep["in_progress"]
        done = ip.get("checks", [])
        nsteps = len(ip.get("steps") or CHECKS)
        parts.append(f"<p><b>Running now</b> (step {min(len(done) + 1, nsteps)}/{nsteps}): "
                     f"{e(ip.get('current', ''))}…</p>")
        probs = [ch for ch in done if ch["status"] in ("warn", "fail")]
        if probs:
            parts.append("<p>Problems found so far in this run:</p><ul>")
            for ch in probs:
                parts.append(f"<li><b class='diag-{e(ch['status'])}'>{e(ch['status'].upper())}</b> "
                             f"{e(ch['title'])}: {e(ch['summary'])}</li>")
            parts.append("</ul>")
    if rep.get("started"):
        parts.append(f"<p>Last report: <b class='diag-{e(rep.get('overall', ''))}'>{e(str(rep.get('overall', '')).upper())}</b> "
                     f"— {e(rep.get('started', ''))} ({e(rep.get('mode', ''))}, {e(str(rep.get('reason', '')))})</p><ul>")
        for ch in rep["checks"]:
            if ch["status"] in ("warn", "fail"):
                parts.append(f"<li><b class='diag-{e(ch['status'])}'>{e(ch['status'].upper())}</b> "
                             f"{e(ch['title'])}: {e(ch['summary'])}</li>")
        parts.append("</ul>")
    return "".join(parts)


CSS = """
:root{--bg:#f6f7f9;--fg:#1d2330;--card:#fff;--muted:#667;--line:#dde1e7;--ok:#1a7f37;--info:#3b6fb6;
--warn:#a96b00;--fail:#c62828;--skip:#888}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--fg:#e4e7ec;--card:#1d2128;--muted:#99a;--line:#2e343e;
--ok:#4cc265;--info:#7aa7e6;--warn:#e0a63a;--fail:#ff6b6b;--skip:#888}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:16px}h1{font-size:22px;margin:4px 0 12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:10px 0}
.badge{display:inline-block;min-width:44px;text-align:center;border-radius:4px;padding:1px 6px;font-weight:700;
font-size:12px;color:#fff}.b-ok{background:var(--ok)}.b-info{background:var(--info)}.b-warn{background:var(--warn)}
.b-fail{background:var(--fail)}.b-skip{background:var(--skip)}
details>summary{cursor:pointer;list-style:none;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
details>summary .sum{color:var(--muted)}.lines{margin:8px 0 0;font:12px/1.5 ui-monospace,monospace;
white-space:pre-wrap;word-break:break-all}.l-warn{color:var(--warn)}.l-fail{color:var(--fail);font-weight:600}
.l-info{color:var(--fg)}table{border-collapse:collapse;width:100%;font-size:12px}td,th{border-bottom:1px solid var(--line);
padding:3px 6px;text-align:left}.dot{display:inline-block;width:10px;height:10px;border-radius:50%}
.d-ok,.d-info{background:var(--ok)}.d-warn{background:var(--warn)}.d-fail{background:var(--fail)}.d-skip{background:var(--skip)}
button{font:inherit;padding:6px 12px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--fg);
cursor:pointer}.muted{color:var(--muted)}.scroll{overflow-x:auto}
"""


def _checks_html(checks, open_problems=True):
    e = html.escape
    out = []
    for ch in checks:
        st = ch["status"]
        op = " open" if open_problems and st in ("warn", "fail") else ""
        out.append(f"<div class='card'><details{op}><summary><span class='badge b-{e(st)}'>{e(st.upper())}</span>"
                   f"<b>{e(ch['title'])}</b><span class='sum'>{e(ch['summary'])} · {ch['duration']} s</span></summary>")
        if ch["details"]:
            out.append("<div class='lines'>")
            for lvl, txt in ch["details"]:
                out.append(f"<div class='l-{e(lvl)}'>{e(txt)}</div>")
            out.append("</div>")
        out.append("</details></div>")
    return out


def _progress_html(ip):
    """The run in progress: finished steps with results, the current step, the pending ones."""
    e = html.escape
    done = ip.get("checks", [])
    steps = ip.get("steps") or [c[1] for c in CHECKS]
    now = time.time()
    hb_age = now - ip.get("heartbeat", now)
    step_age = now - ip.get("step_started", now)
    current = ip.get("current", "")
    out = [f"<div class='card' style='border-color:var(--info)'>⏳ <b>Diagnostics running</b> — "
           f"{e(ip.get('mode', ''))} mode, reason {e(str(ip.get('reason', '')))}, started {e(ip.get('started', ''))}. "
           f"Step {min(len(done) + 1, len(steps))} of {len(steps)}. "
           f"<span class='muted'>This page refreshes every 10 s.</span></div>"]
    if hb_age > 120:
        out.append(f"<div class='card' style='border-color:var(--fail)'><b>The diagnostics process stopped reporting "
                   f"{int(hb_age)} s ago.</b> It is probably stuck itself (e.g. blocked on disk I/O). "
                   f"Last known activity: {e(current)}</div>")
    out += _checks_html(done, open_problems=True)
    if len(done) < len(steps):
        title, _, act = current.partition(" — ")
        out.append(f"<div class='card'><span class='badge b-info'>NOW</span> <b>{e(title or steps[len(done)])}</b> "
                   f"<span class='muted'>running for {int(step_age)} s</span>"
                   f"<div class='lines'>{e(act)}</div></div>")
        pending = steps[len(done) + 1:]
        if pending:
            out.append("<div class='card muted'>Pending: " + " · ".join(e(t) for t in pending) + "</div>")
    return out


def render_html(key="", banner="", run_url="/diagnostics/run", json_url="/diagnostics.json"):
    rep, d = load_latest()
    hist = load_history(d)
    e = html.escape
    kq = f"?key={e(key)}" if key else ""
    running = bool(rep and rep.get("in_progress"))
    out = ["<!doctype html><html lang='en'><head><meta charset='utf-8'>",
           "<meta name='viewport' content='width=device-width,initial-scale=1'>",
           "<title>FPGAEmu Diagnostics</title>"]
    if running:
        out.append("<meta http-equiv='refresh' content='10'>")
    out.append(f"<style>{CSS}</style></head><body><main><h1>FPGAEmu server diagnostics</h1>")
    if banner:
        out.append(f"<div class='card' style='border-color:var(--fail)'><b>{banner}</b></div>")
    out.append(f"<div class='card'><form method='post' action='{e(run_url)}{kq}' style='display:inline'>"
               "<button name='mode' value='quick'>Run quick check</button> "
               "<button name='mode' value='full'>Run full check (slow, reads the whole image)</button></form> "
               f"<a href='{e(json_url)}{kq}'>JSON</a></div>")
    out.append(_sync_card())
    if running:
        out += _progress_html(rep["in_progress"])
    if not rep or not rep.get("started"):
        out.append("<div class='card'>No finished report yet.</div>")
    else:
        if rep.get("error"):
            out.append(f"<div class='card'>{e(rep['error'])}</div>")
        ov = rep.get("overall", "skip")
        if running:
            out.append("<h2 style='font-size:17px;margin:22px 0 4px'>Previous finished report</h2>")
        out.append(f"<div class='card'><span class='badge b-{e(ov)}'>{e(ov.upper())}</span> "
                   f"<b>{e(rep.get('started', ''))}</b> — mode <b>{e(rep.get('mode', ''))}</b>, "
                   f"reason {e(str(rep.get('reason', '')))}, took {rep.get('duration', '?')} s "
                   f"<span class='muted'>({e(rep.get('diag_dir', ''))})</span></div>")
        out += _checks_html(rep.get("checks", []), open_problems=not running)
    if hist:
        ids = [c[0] for c in CHECKS]
        out.append("<div class='card'><b>History</b> <span class='muted'>(newest first — intermittent problems show up here)</span>"
                   "<div class='scroll'><table><tr><th>Started</th><th>Mode</th><th>Reason</th><th>Overall</th>")
        out += [f"<th title='{e(ch[1])}'>{e(ch[0][:5])}</th>" for ch in CHECKS]
        out.append("</tr>")
        for h in hist:
            out.append(f"<tr><td>{e(str(h['started']))}</td><td>{e(str(h['mode']))}</td><td>{e(str(h['reason']))}</td>"
                       f"<td><span class='badge b-{e(str(h['overall']))}'>{e(str(h['overall']).upper())}</span></td>")
            out += [f"<td><span class='dot d-{e(h['checks'].get(i, 'skip'))}' title='{e(h['checks'].get(i, '-'))}'></span></td>"
                    for i in ids]
            out.append("</tr>")
        out.append("</table></div></div>")
    out.append("</main></body></html>")
    return "".join(out)


# --------------------------------------------------------------------------- fallback server

def _port_in_use(port):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=5).close()
        return True
    except OSError:
        return False


def serve_page(banner, stop=lambda: False, public_html=None, create_key=True, port=APP_PORT):
    """Minimal server on `port`: /diagnostics (with ?key=) and a 503 page for everything else.
    `banner` is a function returning the text shown on top. Returns when stop() is true."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse, parse_qs

    public_html = public_html or "<h1>FPGAEmu is temporarily unavailable</h1><p>The server is being diagnosed.</p>"

    class H(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="text/html; charset=utf-8"):
            b = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            if code == 503:
                self.send_header("Retry-After", "60")
            self.end_headers()
            self.wfile.write(b)

        def _key(self):
            return parse_qs(urlparse(self.path).query).get("key", [""])[0]

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/diagnostics", "/diagnostics.json"):
                if not key_ok(self._key(), create_key):
                    return self._send(403, "Forbidden: missing or wrong ?key=")
                if path.endswith(".json"):
                    rep, _ = load_latest()
                    rep = dict(rep or {}, sync=sync_status())
                    return self._send(200, json.dumps(rep), "application/json")
                return self._send(200, render_html(self._key(), html.escape(banner())))
            self._send(503, public_html)

        def do_POST(self):
            if urlparse(self.path).path != "/diagnostics/run" or not key_ok(self._key(), create_key):
                return self._send(403, "Forbidden")
            n = int(self.headers.get("Content-Length") or 0)
            mode = parse_qs(self.rfile.read(n).decode()).get("mode", ["quick"])[0]
            start_background_run("full" if mode == "full" else "quick", "manual (fallback)")
            self.send_response(303)
            self.send_header("Location", f"/diagnostics?key={self._key()}")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    srv.timeout = 1
    try:
        while not stop():
            srv.handle_request()
    finally:
        srv.server_close()


def serve_fallback(args):
    """Waits; if nothing answers on port 5000 for FALLBACK_DELAY seconds, serves the report there."""
    down_since = None
    while True:
        if _port_in_use(APP_PORT):
            down_since = None
        else:
            down_since = down_since or time.monotonic()
            if time.monotonic() - down_since >= FALLBACK_DELAY:
                break
        time.sleep(20)

    print(f"Web app down for {FALLBACK_DELAY}s: serving diagnostics on port {APP_PORT}", flush=True)
    start_background_run("quick", "app down (fallback)")
    since = now_iso()
    serve_page(lambda: f"The FPGAEmu web application has not been answering on port {APP_PORT} since "
                       f"{since} (minus {FALLBACK_DELAY}s). This page is served by the diagnostics fallback server.")


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("manifest")
    r = sub.add_parser("run")
    r.add_argument("--mode", choices=["quick", "full"], default="quick")
    r.add_argument("--reason", default="manual")
    sub.add_parser("serve-fallback")
    sub.add_parser("print-url")
    args = ap.parse_args()
    if args.cmd == "manifest":
        build_manifest(args)
    elif args.cmd == "run":
        sys.exit(run(args))
    elif args.cmd == "serve-fallback":
        serve_fallback(args)
    elif args.cmd == "print-url":
        print(f"Diagnostics page: http(s)://<server>/diagnostics?key={access_key()}")


if __name__ == "__main__":
    main()
