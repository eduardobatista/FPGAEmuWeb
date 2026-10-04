#!/usr/bin/env python3
"""
Keeps the application data on local disk and syncs it with the network storage.

The app works on LOCAL_DIR (cachedwork/, container disk). NFS_DIR (work/) is the
persistent copy on NFS, which may be very slow or stall for long periods. Only
subprocesses (rsync, find) touch NFS_DIR, and they are abandoned when they exceed
their timeout, so an NFS stall never blocks this process nor the web app.

Commands (stdlib only, run with /usr/bin/python3):
    daemon       Phase 1: copy the top-level files of work/ (databases, keys) NFS -> local;
                 the app starts right after it.
                 Phase 2, in the background: copy the user folders one by one, each with its
                 own timeout, retrying the ones that fail; never overwrites newer local files.
                 Meanwhile and afterwards: every WORKSYNC_INTERVAL seconds push to NFS only
                 what changed locally (an index of what NFS already has avoids scanning NFS),
                 once more on SIGTERM, and a full reconciliation once a night.
    wait-ready   serve a "starting" page on port 5000 until phase 1 is done,
                 then exec the command given after "--" (the web app)
    push         push the local changes now
    reconcile    full comparison local -> NFS now (slow on a slow NFS)
    status       print the sync status

Only active when ENVCACHEDWORK=True (otherwise the app works directly on work/).
"""

import datetime
import fnmatch
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))
from diagnostics import diagnose  # noqa: E402  (stdlib only)

NFS_DIR = APP_DIR / "work"
LOCAL_DIR = APP_DIR / "cachedwork"
STATE_DIR = APP_DIR / ".worksync"          # container disk; survives restarts, not re-creation
READY = STATE_DIR / "ready"
STATUS = STATE_DIR / "status.json"
INDEX = STATE_DIR / "index.tsv"            # what NFS has (as far as we know): type, size, mtime, path
FOLDERS_DONE = STATE_DIR / "folders_done.txt"
SNAP_DIR = STATE_DIR / "snapshots"
INTERVAL = int(os.environ.get("WORKSYNC_INTERVAL", "180"))
ESSENTIAL_TIMEOUT = int(os.environ.get("WORKSYNC_ESSENTIAL_TIMEOUT", "120"))
FOLDER_TIMEOUT = int(os.environ.get("WORKSYNC_FOLDER_TIMEOUT", "300"))
LIST_TIMEOUT = int(os.environ.get("WORKSYNC_LIST_TIMEOUT", "600"))
PUSH_TIMEOUT = int(os.environ.get("WORKSYNC_PUSH_TIMEOUT", "600"))
RECONCILE_TIMEOUT = int(os.environ.get("WORKSYNC_RECONCILE_TIMEOUT", "3600"))
RECONCILE_HOUR = int(os.environ.get("WORKSYNC_RECONCILE_HOUR", "3"))
MAX_DELETE = int(os.environ.get("WORKSYNC_MAX_DELETE", "2000"))
FOLDER_PARTIAL_ACCEPT = 3   # a folder with unreadable files is accepted after this many attempts

DB_SUFFIXES = (".sqlite", ".db")
# Never synced: SQLite side files (DBs are copied as snapshots), diagnostics leftovers,
# backups and compilation/simulation outputs (regenerated on demand).
EXCLUDES = ["*.sqlite-journal", "*.sqlite-wal", "*.sqlite-shm", "*.db-journal", "*.db-wal", "*.db-shm",
            ".fpgaemu-diag-*", "workbackup.tar", "*.o", "*.ghw", "work-obj*.cf", "e~*"]
RSYNC = ["rsync", "-rlt", "--omit-dir-times", "--stats"]
# rsync writes each file to a temp name and renames it; a killed rsync leaves that temp file
# behind, so keep temp files in dedicated directories (excluded, cleaned at start).
LOCAL_TMP = STATE_DIR / "tmp"                 # same filesystem as cachedwork/
NFS_TMP_NAME = ".worksync-tmp"                # inside work/ (same filesystem: atomic rename)
EXCLUDES.append(NFS_TMP_NAME)


def enabled():
    return os.environ.get("ENVCACHEDWORK", "False") not in ("", "False")


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def log(msg):
    diagnose.say(f"[worksync] {msg}")


# --------------------------------------------------------------------------- status

def load_status():
    try:
        return json.loads(STATUS.read_text())
    except (OSError, ValueError):
        return {}


_status_lock = threading.Lock()


def save_status(**changes):
    with _status_lock:
        st = load_status()
        st.update(changes)
        st["updated"] = now_iso()
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        diagnose.atomic_write(STATUS, json.dumps(st, indent=1))
        return st


# --------------------------------------------------------------------------- subprocesses

def run(cmd, timeout):
    """Runs cmd without ever waiting on it past the timeout (a process stuck on NFS
    cannot be killed until its I/O returns; we just abandon it).
    Returns (exit code or None on timeout, output, seconds)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    out_file = STATE_DIR / f"cmd-{os.getpid()}-{time.monotonic_ns()}.log"
    t0 = time.monotonic()
    with open(out_file, "wb") as out:
        p = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        try:
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.terminate()            # lets rsync clean up, if it is not stuck in the kernel
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
            rc = None
    text = diagnose.read_text(out_file)
    try:
        out_file.unlink()
    except OSError:
        pass
    return rc, text, time.monotonic() - t0


def rsync(args, timeout):
    return run(RSYNC + args, timeout)


_nfs_tmp_ready = False


def nfs_tmp_args():
    """--temp-dir inside work/ (created/cleaned through a subprocess: it touches NFS)."""
    global _nfs_tmp_ready
    tmp = NFS_DIR / NFS_TMP_NAME
    if not _nfs_tmp_ready:
        rc, out, _ = run(["sh", "-c", 'rm -rf "$1" && mkdir -p "$1"', "sh", str(tmp)], 120)
        if rc != 0:
            log(f"Could not prepare {tmp} ({'timeout' if rc is None else out.strip()}); using rsync defaults.")
            return []
        _nfs_tmp_ready = True
    return [f"--temp-dir={tmp}"]


def local_tmp_args():
    import shutil
    shutil.rmtree(LOCAL_TMP, ignore_errors=True)
    LOCAL_TMP.mkdir(parents=True, exist_ok=True)
    return [f"--temp-dir={LOCAL_TMP}"]


def stats(text):
    def num(label):
        m = re.search(label + r": ([\d,]+)", text)
        return int(m.group(1).replace(",", "")) if m else None
    return {"files": num("Number of files"), "transferred": num("Number of regular files transferred"),
            "deleted": num("Number of deleted files"), "bytes": num("Total transferred file size")}


def errors(text, n=8):
    return [l for l in text.splitlines() if l.startswith("rsync") or "error" in l.lower()][-n:]


def excludes():
    return [a for pat in EXCLUDES for a in ("--exclude", pat)]


# --------------------------------------------------------------------------- local index

def _excluded(rel):
    name = rel.rsplit("/", 1)[-1]
    if any(fnmatch.fnmatch(name, pat) for pat in EXCLUDES):
        return True
    return "/" not in rel and rel.endswith(DB_SUFFIXES)   # top-level DBs: synced as snapshots


def scan_local(sub=None):
    """{relative path: (type, size, mtime_ns)} of LOCAL_DIR (or of its folder `sub`).
    Directories are recorded with size/mtime 0 (only their existence matters)."""
    res = {}
    base = LOCAL_DIR / sub if sub else LOCAL_DIR
    if not base.is_dir():
        return res
    if sub:
        res[sub] = ("d", 0, 0)
    for d, dirs, files in os.walk(base):
        rd = os.path.relpath(d, LOCAL_DIR)
        rd = "" if rd == "." else rd + "/"
        keep = []
        for name in dirs:
            rel = rd + name
            if _excluded(rel):
                continue
            if os.path.islink(os.path.join(d, name)):
                files.append(name)
                continue
            keep.append(name)
            res[rel] = ("d", 0, 0)
        dirs[:] = keep
        for name in files:
            rel = rd + name
            if _excluded(rel):
                continue
            try:
                st = os.lstat(os.path.join(d, name))
            except OSError:
                continue
            res[rel] = ("l" if os.path.islink(os.path.join(d, name)) else "f", st.st_size, st.st_mtime_ns)
    return res


_index_lock = threading.Lock()


def load_index():
    idx = {}
    try:
        with open(INDEX, encoding="utf-8", errors="surrogateescape") as f:
            for line in f:
                t, size, mtime, rel = line.rstrip("\n").split("\t", 3)
                idx[rel] = (t, int(size), int(mtime))
    except (OSError, ValueError):
        return None
    return idx


def save_index(idx):
    tmp = INDEX.with_name(INDEX.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", errors="surrogateescape") as f:
        for rel, (t, size, mtime) in idx.items():
            f.write(f"{t}\t{size}\t{mtime}\t{rel}\n")
    os.replace(tmp, INDEX)


def index_add(entries):
    with _index_lock:
        idx = load_index() or {}
        idx.update(entries)
        save_index(idx)


def ready_ns():
    return load_status().get("ready_ns", 0)


def folders_done():
    try:
        return set(l for l in FOLDERS_DONE.read_text(encoding="utf-8", errors="surrogateescape").splitlines() if l)
    except OSError:
        return set()


def mark_folder_done(name):
    with open(FOLDERS_DONE, "a", encoding="utf-8", errors="surrogateescape") as f:
        f.write(name + "\n")


# --------------------------------------------------------------------------- phase 1

def pull_essential():
    """Phase 1, NFS -> local: only the files at the top of work/ (databases, keys, configuration).
    Small and fast; the app starts right after it. Returns True on success."""
    st = load_status()
    attempt = st.get("pull_attempts", 0) + 1
    save_status(phase="pulling essential files", pull_attempts=attempt, pull_started=now_iso())
    log(f"Phase 1: copying top-level files (databases, keys) NFS -> local, attempt {attempt}...")
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    rc, out, secs = rsync(local_tmp_args() + ["--exclude", "/*/"] + excludes() + [f"{NFS_DIR}/", f"{LOCAL_DIR}/"],
                          ESSENTIAL_TIMEOUT)
    if rc not in (0, 24):
        err = f"timed out after {ESSENTIAL_TIMEOUT}s (NFS stalled?)" if rc is None else \
              f"rsync exit {rc}: {' | '.join(errors(out))}"
        log(f"Phase 1 failed: {err}. Will retry.")
        save_status(phase="pull failed", last_error=f"{now_iso()}: phase 1 {err}")
        return False
    db_problems = check_local_dbs()
    # The top-level files now equal NFS: they are the start of the index.
    save_index({rel: v for rel, v in scan_local().items() if "/" not in rel and v[0] != "d"})
    FOLDERS_DONE.write_text("")
    READY.touch()
    save_status(phase="ready", ready_since=now_iso(), ready_ns=time.time_ns(), pull_seconds=round(secs, 1),
                pull_stats=stats(out), db_problems=db_problems,
                last_error=None if not db_problems else f"{now_iso()}: local DB problems: {db_problems}")
    log(f"Phase 1 done in {secs:.1f}s. App can start; user folders are copied in the background.")
    return True


def check_local_dbs():
    problems = []
    for db in sorted(LOCAL_DIR.glob("*")):
        if db.suffix not in DB_SUFFIXES or not db.is_file() or db.stat().st_size == 0:
            continue
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
            res = con.execute("PRAGMA quick_check").fetchone()[0]
            con.close()
            if res != "ok":
                problems.append(f"{db.name}: {res}")
        except sqlite3.Error as e:
            problems.append(f"{db.name}: {e}")
    for p in problems:
        log(f"WARNING: local database problem after copy: {p}")
    return problems


# --------------------------------------------------------------------------- phase 2

def list_nfs_folders():
    rc, out, secs = run(["find", f"{NFS_DIR}/", "-mindepth", "1", "-maxdepth", "1", "-type", "d", "-printf", "%f\\n"],
                        LIST_TIMEOUT)
    if rc != 0:
        return None, ("timed out" if rc is None else out.strip()[-300:]), secs
    names = [n for n in out.splitlines() if n and not _excluded(n)]
    return sorted(names), None, secs


def pull_folder(name):
    """Copies one user folder NFS -> local without overwriting newer local files.
    Returns 'ok', 'partial' (some files unreadable) or 'failed'."""
    rc, out, secs = rsync(local_tmp_args() + ["--update"] + excludes() + [f"{NFS_DIR}/{name}/", f"{LOCAL_DIR}/{name}/"],
                          FOLDER_TIMEOUT)
    if rc in (0, 24) or rc == 23:
        # Files not changed locally since the app started are identical to NFS: index them.
        # (Files edited by users meanwhile stay out of the index, so they get pushed.)
        rns = ready_ns()
        index_add({rel: v for rel, v in scan_local(name).items() if v[0] == "d" or v[2] < rns})
        if rc == 23:
            return "partial", f"rsync exit 23: {' | '.join(errors(out, 3))}", secs
        return "ok", None, secs
    return "failed", ("timed out after %ds" % FOLDER_TIMEOUT if rc is None else
                      f"rsync exit {rc}: {' | '.join(errors(out, 3))}"), secs


def pull_folders_loop():
    """Phase 2. Copies each user folder separately, retrying failed ones on later passes."""
    if load_status().get("full_pull_phase") == "done":
        return
    while not _stop:
        save_status(full_pull_phase="listing folders on NFS")
        names, err, secs = list_nfs_folders()
        if names is not None:
            log(f"Phase 2: {len(names)} user folders on NFS (listed in {secs:.0f}s).")
            break
        log(f"Phase 2: could not list the folders on NFS ({err}). Will retry.")
        save_status(full_pull_phase="retrying", full_pull_error=f"{now_iso()}: listing folders: {err}")
        _sleep(60)
    attempts = {}
    passes = 0
    while not _stop:
        done = folders_done()
        pending = [n for n in names if n not in done]
        if not pending:
            save_status(full_pull_phase="done", full_pull_done=now_iso(), folders_total=len(names),
                        folders_done=len(names), folders_failed={}, full_pull_error=None)
            log(f"Phase 2 done: all {len(names)} user folders copied.")
            return
        passes += 1
        save_status(full_pull_phase="copying", full_pull_attempts=passes, full_pull_started=now_iso(),
                    folders_total=len(names), folders_done=len(names) - len(pending))
        for i, name in enumerate(pending):
            if _stop:
                return
            save_status(folders_done=len(names) - len(pending) + i, current_folder=name)
            result, err, secs = pull_folder(name)
            if result == "ok" or (result == "partial" and attempts.get(name, 0) + 1 >= FOLDER_PARTIAL_ACCEPT):
                mark_folder_done(name)
                attempts.pop(name, None)
                if result == "partial":
                    log(f"Phase 2: folder {name} has unreadable files on NFS; accepted with what could be read ({err}).")
            else:
                attempts[name] = attempts.get(name, 0) + 1
                log(f"Phase 2: folder {name} failed (attempt {attempts[name]}, {secs:.0f}s): {err}")
                save_status(full_pull_error=f"{now_iso()}: {name}: {err}")
            save_status(folders_failed={k: v for k, v in attempts.items()})
            if (i + 1) % 100 == 0:
                log(f"Phase 2: {len(names) - len(pending) + i + 1}/{len(names)} folders copied.")
        save_status(current_folder=None)
        if [n for n in names if n not in folders_done()]:
            _sleep(60)


# --------------------------------------------------------------------------- push

def _db_signature(db):
    sig = []
    for f in (db, Path(str(db) + "-wal")):
        try:
            st = f.stat()
            sig.append([st.st_size, st.st_mtime_ns])
        except OSError:
            sig.append(None)
    return sig


def snapshot_dbs(st):
    """Consistent copies (SQLite backup API) of the local DBs that changed since the last push."""
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    sigs = {}
    changed = []
    for db in sorted(LOCAL_DIR.glob("*")):
        if db.suffix not in DB_SUFFIXES or not db.is_file():
            continue
        sig = _db_signature(db)
        sigs[db.name] = sig
        snap = SNAP_DIR / db.name
        if st.get("db_sigs", {}).get(db.name) == sig and snap.exists():
            continue
        tmp = SNAP_DIR / (db.name + ".tmp")
        src = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        os.replace(tmp, snap)
        changed.append(db.name)
    return sigs, changed


def _locked(fn):
    def wrapper(*a, **kw):
        if not READY.exists():
            log("Push skipped: phase 1 has not finished.")
            return False
        import fcntl
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        lock = open(STATE_DIR / "push.lock", "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log("Push skipped: another push is running.")
            return False
        try:
            return fn(*a, **kw)
        finally:
            lock.close()
    return wrapper


def _push_dbs(st, tmp, timeout):
    try:
        sigs, changed = snapshot_dbs(st)
    except sqlite3.Error as e:
        log(f"Push: could not snapshot databases: {e}")
        return st.get("db_sigs", {}), [], 0, ""
    if not changed:
        return sigs, [], 0, ""
    rc, out, _ = rsync(tmp + [f"{SNAP_DIR}/" + n for n in changed] + [f"{NFS_DIR}/"], timeout)
    return sigs, changed, rc, out


def _push_failed(st, err):
    n = st.get("consecutive_push_failures", 0) + 1
    save_status(phase="ready", last_push_failed=now_iso(), last_error=f"{now_iso()}: {err}",
                consecutive_push_failures=n)
    log(f"Push FAILED ({n} in a row): {err}")
    return False


def _write_list(paths):
    with tempfile.NamedTemporaryFile("wb", dir=STATE_DIR, delete=False) as lf:
        for rel in paths:
            lf.write(os.fsencode(rel) + b"\0")
        return lf.name


def _safe_rel(rel):
    parts = rel.split("/")
    return bool(rel) and not rel.startswith("/") and ".." not in parts and "" not in parts and "." not in parts


@_locked
def push(timeout=PUSH_TIMEOUT, reason="periodic"):
    """Sends to NFS only what changed locally, comparing the local tree with the index."""
    st = load_status()
    if load_index() is None:
        log("No index of the NFS contents yet: running a full reconciliation instead.")
        return _reconcile(RECONCILE_TIMEOUT, reason + ", no index")
    t0 = time.monotonic()
    save_status(phase="pushing", push_started=now_iso(), push_reason=reason)
    # Folders are marked done only after their files were indexed: read "done" before the index.
    done = folders_done()
    with _index_lock:
        idx = load_index() or {}
    cur = scan_local()
    rns = st.get("ready_ns", 0)
    phase2_done = st.get("full_pull_phase") == "done"

    def pulled(rel, v):
        # top-level files came with phase 1; folders (and their contents) once phase 2 copied them
        return phase2_done or ("/" not in rel and v[0] != "d") or rel.split("/", 1)[0] in done

    # Changed/new: differs from what NFS has. In folders phase 2 has not copied yet, only files
    # edited by users since the app started count (the rest is NFS data still being copied).
    changed = [rel for rel, v in cur.items()
               if idx.get(rel) != v and (pulled(rel, v) or (v[0] != "d" and v[2] >= rns))]
    deleted = [rel for rel in idx if rel not in cur]
    skipped_delete = 0
    if len(deleted) > MAX_DELETE:
        skipped_delete = len(deleted)
        log(f"Push: {len(deleted)} deletions exceed WORKSYNC_MAX_DELETE={MAX_DELETE}; NOT deleting on NFS.")
        deleted = []
    tmp = nfs_tmp_args()
    # 1. New/changed files. (--delete-missing-args would do the deletions too, but it is
    # broken in rsync 3.2.7 for local copies: "protocol incompatibility".)
    if changed:
        listfile = _write_list(changed)
        rc, out, _ = run(["rsync", "-lt", "--omit-dir-times", "--from0", f"--files-from={listfile}",
                          "--ignore-missing-args"] + tmp + [f"{LOCAL_DIR}/", f"{NFS_DIR}/"], timeout)
        os.unlink(listfile)
        if rc not in (0, 24):
            return _push_failed(st, "push timed out after %ds (NFS stalled?)" % timeout if rc is None else
                                f"push rsync exit {rc}: {' | '.join(errors(out))}")
    # 2. Deletions: paths from the index only (files/dirs we know were synced), in a subprocess.
    deleted = [rel for rel in deleted if _safe_rel(rel)]
    if deleted:
        listfile = _write_list(sorted(deleted, reverse=True))
        rc, out, _ = run(["sh", "-c", 'cd "$1" && xargs -0 -r rm -rf -- < "$2"', "sh", str(NFS_DIR), listfile],
                         max(30, timeout - int(time.monotonic() - t0)))
        os.unlink(listfile)
        if rc != 0:
            return _push_failed(st, "deleting on NFS timed out" if rc is None else
                                f"deleting on NFS failed: {out.strip()[-300:]}")
    sigs, dbs, rc2, out2 = _push_dbs(st, tmp, max(30, timeout - int(time.monotonic() - t0)))
    if rc2 != 0:
        return _push_failed(st, "database push timed out" if rc2 is None else
                            f"database push rsync exit {rc2}: {' | '.join(errors(out2))}")
    with _index_lock:
        idx = load_index() or {}
        for rel in changed:
            idx[rel] = cur[rel]
        for rel in deleted:
            idx.pop(rel, None)
        save_index(idx)
    total = time.monotonic() - t0
    save_status(phase="ready", last_push_ok=now_iso(), last_push_seconds=round(total, 1),
                last_push_stats={"transferred": len(changed), "deleted": len(deleted)},
                last_push_dbs=dbs, db_sigs=sigs, consecutive_push_failures=0,
                last_push_warning=(f"{skipped_delete} deletions not propagated (over WORKSYNC_MAX_DELETE)"
                                   if skipped_delete else None))
    if changed or deleted or dbs:
        log(f"Pushed to NFS in {total:.1f}s: {len(changed)} new/changed, {len(deleted)} deleted, "
            f"databases {dbs or 'unchanged'} ({reason})")
    return True


@_locked
def reconcile(timeout=RECONCILE_TIMEOUT, reason="nightly"):
    return _reconcile(timeout, reason)


def _reconcile(timeout, reason):
    """Full rsync local -> NFS (slow: compares every file on NFS). Safety net for anything the
    incremental push could miss; rebuilds the index."""
    st = load_status()
    t0 = time.monotonic()
    log(f"Full reconciliation local -> NFS ({reason})...")
    save_status(phase="reconciling", reconcile_started=now_iso())
    phase2_done = st.get("full_pull_phase") == "done"
    done = folders_done()
    args = nfs_tmp_args() + excludes() + ["--exclude", "/*.sqlite", "--exclude", "/*.db"]
    if phase2_done:
        args += ["--delete", f"--max-delete={MAX_DELETE}"]
    else:
        # Folders not copied from NFS yet: leave them alone (local copy incomplete).
        args += ["--update"] + [a for n in os.listdir(LOCAL_DIR)
                                if (LOCAL_DIR / n).is_dir() and n not in done for a in ("--exclude", f"/{n}/")]
    rc, out, _ = rsync(args + [f"{LOCAL_DIR}/", f"{NFS_DIR}/"], timeout)
    if rc not in (0, 24, 25):
        return _push_failed(st, "reconciliation timed out" if rc is None else
                            f"reconciliation rsync exit {rc}: {' | '.join(errors(out))}")
    sigs, dbs, rc2, out2 = _push_dbs(st, nfs_tmp_args(), 300)
    if rc2 != 0:
        return _push_failed(st, f"database push failed: {' | '.join(errors(out2))}")
    with _index_lock:
        save_index({rel: v for rel, v in scan_local().items()
                    if phase2_done or ("/" not in rel and v[0] != "d") or rel.split("/", 1)[0] in done})
    s = stats(out)
    total = time.monotonic() - t0
    save_status(phase="ready", last_push_ok=now_iso(), last_reconcile=now_iso(), last_reconcile_seconds=round(total),
                last_reconcile_stats=s, last_push_dbs=dbs, db_sigs=sigs, consecutive_push_failures=0,
                last_push_warning=f"max-delete ({MAX_DELETE}) reached" if rc == 25 else None)
    log(f"Reconciliation done in {total:.0f}s: {s.get('transferred')} files sent, {s.get('deleted') or 0} deleted, "
        f"databases {dbs or 'unchanged'}.")
    return True


def reconcile_due():
    last = load_status().get("last_reconcile")
    now = datetime.datetime.now().astimezone()
    if now.hour != RECONCILE_HOUR:
        return False
    return not last or (now - datetime.datetime.fromisoformat(last)).total_seconds() > 20 * 3600


# --------------------------------------------------------------------------- commands

_stop = False


def _on_term(signum, frame):
    global _stop
    _stop = True


def _sleep(seconds):
    end = time.monotonic() + seconds
    while not _stop and time.monotonic() < end:
        time.sleep(1)


def daemon():
    if not enabled():
        log("ENVCACHEDWORK is not True: the app works directly on work/; nothing to sync.")
        diagnose.say(f"Diagnostics page: http(s)://<server>/diagnostics?key={diagnose.access_key()}")
        while True:
            time.sleep(3600)
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    for f in STATE_DIR.glob("cmd-*.log"):
        f.unlink()
    if READY.exists():
        log("Container restarted: the local copy is the current one; saving its changes to NFS.")
        push(reason="restart")
    else:
        save_status(pull_attempts=0, consecutive_push_failures=0, db_sigs={}, full_pull_phase="pending",
                    full_pull_attempts=0, folders_failed={})
        while not _stop and not pull_essential():
            _sleep(30)
        if _stop:
            return
    threading.Thread(target=pull_folders_loop, daemon=True).start()
    diagnose.say(f"Diagnostics page: http(s)://<server>/diagnostics?key={diagnose.access_key()}")
    diag_pending = True   # the startup diagnostics ran before the data was here: run again
    while not _stop:
        _sleep(INTERVAL)
        if _stop:
            break
        if reconcile_due():
            reconcile()
        else:
            push()
        if diag_pending and not (diagnose.DIAG_DIR / "running.json").exists():
            diagnose.start_background_run("quick", "after initial sync")
            diag_pending = False
    log("Stopping: final push to NFS...")
    push(timeout=50, reason="shutdown")


def wait_ready(cmd):
    if enabled() and not READY.exists():
        def banner():
            st = load_status()
            return (f"FPGAEmu is starting: copying the data from the network storage (NFS) to the local disk. "
                    f"Phase: {st.get('phase', 'starting')}, attempt {st.get('pull_attempts', 0)}. "
                    f"Last error: {st.get('last_error') or 'none'}")
        diagnose.serve_page(banner, stop=READY.exists,
                            public_html="<h1>FPGAEmu is starting</h1><p>Please try again in a few minutes.</p>",
                            create_key=False)
    os.execvp(cmd[0], cmd)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "daemon":
        daemon()
    elif cmd == "wait-ready":
        rest = sys.argv[2:]
        if rest and rest[0] == "--":
            rest = rest[1:]
        if not rest:
            sys.exit("usage: worksync.py wait-ready -- <command...>")
        wait_ready(rest)
    elif cmd == "push":
        sys.exit(0 if push(reason="manual") else 1)
    elif cmd == "reconcile":
        sys.exit(0 if reconcile(reason="manual") else 1)
    elif cmd == "status":
        print(json.dumps(load_status(), indent=1))
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
