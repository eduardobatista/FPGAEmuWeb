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
import fcntl
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


def _io_test(c, directory, size_mib):
    """Writes random data, fsyncs, evicts page cache and reads it back."""
    data = os.urandom(1 << 20)
    expected = hashlib.sha256()
    path = Path(directory) / f".fpgaemu-diag-{os.getpid()}.bin"
    res = {"dir": str(directory)}
    try:
        t0 = time.monotonic()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            for i in range(size_mib):
                block = bytes([i & 0xFF]) + data[1:]
                expected.update(block)
                os.write(fd, block)
            t1 = time.monotonic()
            os.fsync(fd)
            t2 = time.monotonic()
        finally:
            os.close(fd)
        res["write_mibs"] = round(size_mib / max(t2 - t0, 1e-6), 1)
        res["fsync_s"] = round(t2 - t1, 3)
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
        sdir = Path(directory) / f".fpgaemu-diag-small-{os.getpid()}"
        sdir.mkdir(exist_ok=True)
        for i in range(100):
            (sdir / f"f{i}").write_bytes(b"%d" % i * 50)
        bad_small = sum(1 for i in range(100) if (sdir / f"f{i}").read_bytes() != b"%d" % i * 50)
        shutil.rmtree(sdir)
        res["small_files_s"] = round(time.monotonic() - t5, 3)
        res["small_bad"] = bad_small
    except OSError as e:
        res["error"] = oserror_text(e)
    finally:
        try:
            path.unlink()
        except OSError:
            pass
    return res


def check_io(c, mode):
    size = 64 if mode == "full" else 8
    mounts = _mounts()
    done = set()
    for p in key_paths():
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
    rc2, out2, _ = run_cmd([str(py), "-c",
                            "import sys,pathlib\n"
                            "for p in pathlib.Path(sys.argv[1]).rglob('*.py'):\n"
                            "    if '.venv' in p.parts: continue\n"
                            "    try: compile(p.read_bytes(), str(p), 'exec')\n"
                            "    except BaseException as e: print('FAIL', p, type(e).__name__, e)\n",
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


def _sqlite_check(c, path, full):
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        try:
            rows = con.execute("PRAGMA integrity_check" if full else "PRAGMA quick_check").fetchall()
            res = [r[0] for r in rows]
            if res != ["ok"]:
                c.fail(f"SQLite {path} is CORRUPTED:")
                for r in res[:30]:
                    c.fail("    " + r)
                return
            tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            extra = ""
            if "user" in tables:
                extra = f", {con.execute('SELECT count(*) FROM user').fetchone()[0]} users"
            c.info(f"SQLite {path}: ok ({len(tables)} tables{extra})")
        finally:
            con.close()
    except sqlite3.DatabaseError as e:
        c.fail(f"SQLite {path}: {e}")
    except OSError as e:
        c.fail(f"SQLite {path}: {oserror_text(e)}")


TEXT_SUFFIXES = {".vhd", ".vhdl", ".map", ".json", ".conf", ".config", ".txt", ".py", ".sh", ".html", ".js", ".css"}


def check_workdata(c, mode):
    full = mode == "full"
    nfiles = nbytes = 0
    slow = []
    dbs = [APP_DIR / "huey.db"]
    for w in WORKDIRS:
        if not w.exists():
            continue
        dbs += [p for p in w.iterdir() if p.suffix in (".sqlite", ".db") and p.is_file()]
        if (w / "dbb.sqlite").exists():
            sk = w / "seckeyb"
            if not sk.exists() or sk.stat().st_size != 16:
                c.warn(f"{sk} missing or with unexpected size (sessions become invalid)")
        for p, err in iter_tree(w):
            if err:
                c.fail(f"Cannot list {p}: {oserror_text(err)}")
                continue
            if p.is_symlink() or not p.is_file():
                continue
            try:
                t0 = time.monotonic()
                data = p.read_bytes()
                secs = time.monotonic() - t0
            except OSError as e:
                c.fail(f"I/O ERROR reading {p}: {oserror_text(e)}" if e.errno == errno.EIO
                       else f"Cannot read {p}: {oserror_text(e)}")
                continue
            nfiles += 1
            nbytes += len(data)
            if secs > 1.0:
                slow.append((secs, str(p), len(data)))
            name = p.name.lower()
            if data and data.count(0) == len(data):
                c.fail(f"File contains only zero bytes (typical of lost data): {p} ({len(data)} B)")
            elif (p.suffix.lower() in TEXT_SUFFIXES or name == ".config") and b"\x00" in data:
                c.fail(f"Text file contains NUL bytes (possible corruption): {p}")
            elif p.suffix.lower() in (".vhd", ".vhdl", ".map"):
                try:
                    data.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        data.decode("latin-1").encode("latin-1")
                        c.info(f"Not UTF-8 (probably Latin-1, usually harmless): {p}")
                    except Exception:
                        c.warn(f"Undecodable text: {p}")
            if p.suffix == ".json" and p.parent == w:
                try:
                    json.loads(data or b"{}")
                except ValueError as e:
                    c.warn(f"Invalid JSON {p}: {e}")
    for db in dbs:
        if db.exists():
            _sqlite_check(c, db, full)
    for secs, path, size in sorted(slow, reverse=True)[:15]:
        c.warn(f"Slow read: {path} ({fmt_bytes(size)}) took {secs:.1f}s")
    c.summary = f"{nfiles} files ({fmt_bytes(nbytes)}) read, {len([d for d in dbs if d.exists()])} databases checked"


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


CHECKS = [
    ("environment", "Environment", check_environment),
    ("memory", "Memory, OOM and cgroup limits", check_memory),
    ("filesystems", "Filesystems: read-only mounts, free space", check_filesystems),
    ("io", "Disk write/read-back test", check_io),
    ("kernel", "Kernel log (dmesg)", check_kernel_log),
    ("image", "Image integrity (checksums vs build manifest)", check_image_integrity),
    ("dpkg", "System packages integrity (dpkg --verify)", check_dpkg),
    ("python", "Python environment (.venv)", check_python_env),
    ("toolchain", "GHDL/GCC compile and simulation test", check_toolchain),
    ("workdata", "User data and databases", check_workdata),
    ("processes", "Processes and web app response", check_processes),
    ("supervisor", "Supervisor restarts", check_supervisor),
    ("logs", "Application logs", check_logs),
]


# --------------------------------------------------------------------------- run

def run(args):
    d = diag_dir()
    lock = open(d / "run.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Another diagnostics run is in progress.")
        return 1
    report = {"started": now_iso(), "mode": args.mode, "reason": args.reason, "running": True,
              "diag_dir": str(d), "checks": []}
    t_start = time.monotonic()
    for cid, title, fn in CHECKS:
        report["current"] = title
        atomic_write(d / "running.json", json.dumps(report))
        c = Check(cid, title)
        t0 = time.monotonic()
        try:
            fn(c, args.mode)
        except Exception as e:
            c.fail(f"The check itself crashed: {type(e).__name__}: {e}")
            for l in traceback.format_exc().splitlines()[-8:]:
                c.info(l)
        c.duration = time.monotonic() - t0
        report["checks"].append(c.to_dict())
        print(f"[{c.status.upper():4}] {title}: {c.summary} ({c.duration:.1f}s)", flush=True)
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
    try:
        (d / "running.json").unlink()
    except OSError:
        pass
    print(f"Overall: {report['overall'].upper()} -> {d / 'latest.json'}")
    return 0


def start_background_run(mode, reason):
    """Spawns `run` detached (used by the web routes)."""
    py = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
    subprocess.Popen([py, str(Path(__file__).resolve()), "run", "--mode", mode, "--reason", reason],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, cwd=str(APP_DIR))


# --------------------------------------------------------------------------- access key

def access_key():
    """DIAG_KEY env var, or a random key persisted in the work dir (shown in the admin page)."""
    env = os.environ.get("DIAG_KEY", "").strip()
    if env:
        return env
    for f in (APP_DIR / "work" / ".diagkey", DIAG_DIR / "key", Path(tempfile.gettempdir()) / "fpgaemu-diagkey"):
        try:
            if f.exists():
                k = f.read_text().strip()
                if len(k) >= 16:
                    return k
            f.parent.mkdir(parents=True, exist_ok=True)
            k = secrets.token_urlsafe(18)
            f.write_text(k)
            f.chmod(0o600)
            return k
        except OSError:
            continue
    return None


def key_ok(given):
    k = access_key()
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
    if not rep:
        return "<p>No diagnostics report yet.</p>"
    parts = []
    if rep.get("in_progress"):
        parts.append(f"<p><b>Running now:</b> {e(rep['in_progress'].get('current', ''))}…</p>")
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
    if running:
        ip = rep["in_progress"]
        out.append(f"<div class='card'>⏳ <b>Diagnostics running</b> ({e(ip.get('mode', ''))}, started {e(ip.get('started', ''))}): "
                   f"{e(ip.get('current', ''))} — this page refreshes every 10 s.</div>")
    if not rep or not rep.get("started"):
        out.append("<div class='card'>No finished report yet.</div>")
    else:
        if rep.get("error"):
            out.append(f"<div class='card'>{e(rep['error'])}</div>")
        ov = rep.get("overall", "skip")
        out.append(f"<div class='card'><span class='badge b-{e(ov)}'>{e(ov.upper())}</span> "
                   f"<b>{e(rep.get('started', ''))}</b> — mode <b>{e(rep.get('mode', ''))}</b>, "
                   f"reason {e(str(rep.get('reason', '')))}, took {rep.get('duration', '?')} s "
                   f"<span class='muted'>({e(rep.get('diag_dir', ''))})</span></div>")
        for ch in rep.get("checks", []):
            st = ch["status"]
            op = " open" if st in ("warn", "fail") else ""
            out.append(f"<div class='card'><details{op}><summary><span class='badge b-{e(st)}'>{e(st.upper())}</span>"
                       f"<b>{e(ch['title'])}</b><span class='sum'>{e(ch['summary'])} · {ch['duration']} s</span></summary>")
            if ch["details"]:
                out.append("<div class='lines'>")
                for lvl, txt in ch["details"]:
                    out.append(f"<div class='l-{e(lvl)}'>{e(txt)}</div>")
                out.append("</div>")
            out.append("</details></div>")
    if hist:
        ids = [c[0] for c in CHECKS]
        out.append("<div class='card'><b>History</b> <span class='muted'>(newest first — intermittent problems show up here)</span>"
                   "<div class='scroll'><table><tr><th>Started</th><th>Mode</th><th>Reason</th><th>Overall</th>")
        out += [f"<th title='{e(t)}'>{e(i[:5])}</th>" for i, t, _ in CHECKS]
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


def serve_fallback(args):
    """Waits; if nothing answers on port 5000 for FALLBACK_DELAY seconds, serves the report there."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse, parse_qs

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
    banner = (f"The FPGAEmu web application has not been answering on port {APP_PORT} since "
              f"{now_iso()} (minus {FALLBACK_DELAY}s). This page is served by the diagnostics fallback server.")

    class H(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="text/html; charset=utf-8"):
            b = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b)

        def _key(self):
            return parse_qs(urlparse(self.path).query).get("key", [""])[0]

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/diagnostics", "/diagnostics.json"):
                if not key_ok(self._key()):
                    return self._send(403, "Forbidden: missing or wrong ?key=")
                if path.endswith(".json"):
                    rep, _ = load_latest()
                    return self._send(200, json.dumps(rep), "application/json")
                return self._send(200, render_html(self._key(), banner))
            self._send(503, "<h1>FPGAEmu is temporarily unavailable</h1><p>The server is being diagnosed.</p>")

        def do_POST(self):
            if urlparse(self.path).path != "/diagnostics/run" or not key_ok(self._key()):
                return self._send(403, "Forbidden")
            n = int(self.headers.get("Content-Length") or 0)
            mode = parse_qs(self.rfile.read(n).decode()).get("mode", ["quick"])[0]
            start_background_run("full" if mode == "full" else "quick", "manual (fallback)")
            self.send_response(303)
            self.send_header("Location", f"/diagnostics?key={self._key()}")
            self.end_headers()

        def log_message(self, *a):
            pass

    ThreadingHTTPServer(("0.0.0.0", APP_PORT), H).serve_forever()


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
