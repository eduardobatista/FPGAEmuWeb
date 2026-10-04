#!/usr/bin/env python3
"""
Keeps the application data on local disk and syncs it with the network storage.

The app works on LOCAL_DIR (cachedwork/, container disk). NFS_DIR (work/) is the
persistent copy on NFS, which may stall for long periods. Only rsync subprocesses
touch NFS_DIR, and they are abandoned when they exceed their timeout, so an NFS
stall never blocks this process nor the web app.

Commands (stdlib only, run with /usr/bin/python3):
    daemon       initial pull NFS -> local (retried until it succeeds), then push
                 local -> NFS every WORKSYNC_INTERVAL seconds and once more on SIGTERM
    wait-ready   serve a "starting" page on port 5000 until the initial pull is done,
                 then exec the command given after "--" (the web app)
    push         push once now
    status       print the sync status

Only active when ENVCACHEDWORK=True (otherwise the app works directly on work/).
"""

import datetime
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
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
SNAP_DIR = STATE_DIR / "snapshots"
INTERVAL = int(os.environ.get("WORKSYNC_INTERVAL", "180"))
PULL_TIMEOUT = int(os.environ.get("WORKSYNC_PULL_TIMEOUT", "900"))
PUSH_TIMEOUT = int(os.environ.get("WORKSYNC_PUSH_TIMEOUT", "600"))
MAX_DELETE = int(os.environ.get("WORKSYNC_MAX_DELETE", "200"))
PARTIAL_PULL_ACCEPT = 3   # after this many partial (not timed out) pulls, start anyway

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


def load_status():
    try:
        return json.loads(STATUS.read_text())
    except (OSError, ValueError):
        return {}


def save_status(**changes):
    st = load_status()
    st.update(changes)
    st["updated"] = now_iso()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    diagnose.atomic_write(STATUS, json.dumps(st, indent=1))
    return st


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


# --------------------------------------------------------------------------- pull

def pull():
    """NFS -> local. Returns True when the local copy can be used."""
    st = load_status()
    attempt = st.get("pull_attempts", 0) + 1
    save_status(phase="pulling", pull_attempts=attempt, pull_started=now_iso())
    log(f"Initial copy NFS -> local, attempt {attempt} (timeout {PULL_TIMEOUT}s)...")
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    rc, out, secs = rsync(local_tmp_args() + excludes() + [f"{NFS_DIR}/", f"{LOCAL_DIR}/"], PULL_TIMEOUT)
    s = stats(out)
    if rc is None:
        log(f"Initial copy did NOT finish in {PULL_TIMEOUT}s (NFS stalled?). Will retry.")
        save_status(phase="pull failed", last_error=f"{now_iso()}: pull timed out after {PULL_TIMEOUT}s")
        return False
    partial = rc in (23, 24)
    if rc != 0 and not partial:
        log(f"Initial copy failed (rsync exit {rc}): {' | '.join(errors(out))}")
        save_status(phase="pull failed", last_error=f"{now_iso()}: pull rsync exit {rc}: {' | '.join(errors(out))}")
        return False
    push_delete = True
    if partial:
        n = st.get("pull_partial_count", 0) + 1
        save_status(pull_partial_count=n)
        msg = f"Initial copy incomplete (rsync exit {rc}, some files unreadable): {' | '.join(errors(out))}"
        if n < PARTIAL_PULL_ACCEPT:
            log(msg + " Will retry.")
            save_status(phase="pull failed", last_error=f"{now_iso()}: {msg}")
            return False
        # Some files cannot be read from NFS at all: start anyway, but never delete on NFS,
        # so files missing locally are not removed there.
        log(msg + f" Accepting after {n} attempts; deletions will NOT be propagated to NFS.")
        push_delete = False
    db_problems = check_local_dbs()
    READY.touch()
    save_status(phase="ready", ready_since=now_iso(), pull_seconds=round(secs, 1), pull_stats=s,
                pull_complete=not partial, push_delete=push_delete, db_problems=db_problems,
                last_error=None if not db_problems else f"{now_iso()}: local DB problems: {db_problems}")
    log(f"Initial copy done in {secs:.0f}s: {s.get('files')} entries, {s.get('transferred')} files copied. App can start.")
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


def push(timeout=PUSH_TIMEOUT, reason="periodic"):
    if not READY.exists():
        log("Push skipped: the initial copy has not finished (pushing now could delete data on NFS).")
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
        return _push(timeout, reason)
    finally:
        lock.close()


def _push(timeout, reason):
    st = load_status()
    t0 = time.monotonic()
    save_status(phase="pushing", push_started=now_iso(), push_reason=reason)
    try:
        sigs, changed = snapshot_dbs(st)
    except sqlite3.Error as e:
        log(f"Push: could not snapshot databases: {e}")
        sigs, changed = st.get("db_sigs", {}), []
    # 1. Files (databases excluded here: they go as snapshots below)
    delete = ["--delete", f"--max-delete={MAX_DELETE}"] if st.get("push_delete", True) else []
    tmp = nfs_tmp_args()
    args = tmp + delete + excludes() + ["--exclude", "/*.sqlite", "--exclude", "/*.db", f"{LOCAL_DIR}/", f"{NFS_DIR}/"]
    rc, out, secs = rsync(args, timeout)
    ok = rc in (0, 24)
    s = stats(out)
    # 2. Database snapshots (rsync writes a temp file and renames it: atomic on NFS)
    rc2, out2 = 0, ""
    if ok and changed:
        rc2, out2, _ = rsync(tmp + [f"{SNAP_DIR}/" + n for n in changed] + [f"{NFS_DIR}/"],
                             max(30, timeout - int(time.monotonic() - t0)))
    total = time.monotonic() - t0
    if ok and rc2 == 0:
        save_status(phase="ready", last_push_ok=now_iso(), last_push_seconds=round(total, 1), last_push_stats=s,
                    last_push_dbs=changed, db_sigs=sigs, consecutive_push_failures=0,
                    last_push_warning=f"max-delete ({MAX_DELETE}) reached" if rc == 25 else None)
        if s.get("transferred") or s.get("deleted") or changed:
            log(f"Pushed to NFS in {total:.1f}s: {s.get('transferred')} files, {s.get('deleted') or 0} deleted, "
                f"databases {changed or 'unchanged'} ({reason})")
        return True
    if rc is None or rc2 is None:
        err = f"push timed out after {timeout}s (NFS stalled?)"
    else:
        err = f"push rsync exit {rc}/{rc2}: {' | '.join(errors(out + out2))}"
    n = st.get("consecutive_push_failures", 0) + 1
    save_status(phase="ready", last_push_failed=now_iso(), last_error=f"{now_iso()}: {err}",
                consecutive_push_failures=n)
    log(f"Push FAILED ({n} in a row): {err}")
    return False


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
        log("Container restarted: the local copy is the current one; saving it to NFS.")
        push(reason="restart")
    else:
        save_status(pull_attempts=0, pull_partial_count=0, consecutive_push_failures=0, db_sigs={})
        while not _stop and not pull():
            _sleep(30)
        if _stop:
            return
    diagnose.say(f"Diagnostics page: http(s)://<server>/diagnostics?key={diagnose.access_key()}")
    diag_pending = True   # the startup diagnostics ran before the data was here: run again
    while not _stop:
        _sleep(INTERVAL)
        if not _stop:
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
    elif cmd == "status":
        print(json.dumps(load_status(), indent=1))
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
