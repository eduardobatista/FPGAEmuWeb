#!/usr/bin/env python3
"""Gives work/ to the web app's user. Run as root; idempotent; safe while the app runs.

Folders in work/ are named after students' e-mail addresses, and that is why this program never
prints, logs or stores a name: only counts and folder numbers.

    local          cachedwork/ (container disk), at every start, before the app (entrypoint.sh)
    daemon         work/, folder by folder, each in a subprocess with a timeout since NFS may stall.
                   Retries what fails, and on success leaves a marker in work/ that tells
                   worksync.py it can stop being root. Started by supervisord.
    scan [--root DIR] [--dry-run]    one pass over DIR, printing the counts
    probe          exit 0 if root can chown on work/ (false with NFS root_squash)
    status         print the status of the migration

Order on each entry: chown first, chmod only if chown worked, so that a failure (root_squash)
cannot leave a file that nobody here can read. Symlinks are never followed.
Hard links and special files are left as they are, and counted: nothing legitimate creates them
in work/, but until now user code ran as root and could have (a hard link to a system file).
"""

import collections
import json
import os
import pwd
import stat
import subprocess
import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
NFS_DIR = APP_DIR / "work"
LOCAL_DIR = APP_DIR / "cachedwork"
STATE_DIR = APP_DIR / ".worksync"
STATUS = STATE_DIR / "migration.json"
READY = STATE_DIR / "migration-ready"       # work/ can be used by the web app's user
MARKER = ".fpgaemu-owner-migrated"          # in work/; excluded from the sync
WEB_USER = "fpgaweb"
FOLDER_TIMEOUT = int(os.environ.get("MIGRATE_FOLDER_TIMEOUT", "600"))
LIST_TIMEOUT = int(os.environ.get("MIGRATE_LIST_TIMEOUT", "600"))
RETRY_SECONDS = int(os.environ.get("MIGRATE_RETRY_SECONDS", "300"))
MAX_RETRY_SECONDS = 3600


def web_ids():
    pw = pwd.getpwnam(WEB_USER)
    return pw.pw_uid, pw.pw_gid


def fix(fd_or_name, st, uid, gid, mode, dry, counts, dir_fd=None):
    """chown, then chmod. fd_or_name is an fd, or for symlinks a name in dir_fd."""
    want_owner = (st.st_uid, st.st_gid) != (uid, gid)
    want_mode = mode is not None and stat.S_IMODE(st.st_mode) != mode
    if not want_owner and not want_mode:
        counts["already_ok"] += 1
        return
    if dry:
        counts["would_change"] += 1
        return
    try:
        if want_owner:
            if dir_fd is None:
                os.fchown(fd_or_name, uid, gid)
            else:
                os.chown(fd_or_name, uid, gid, dir_fd=dir_fd, follow_symlinks=False)
        if want_mode:
            os.fchmod(fd_or_name, mode)
        counts["changed"] += 1
    except OSError as e:
        counts["failed"] += 1
        counts[f"failed_errno_{e.errno}"] += 1


def migrate_entry(parent_fd, name, uid, gid, dry, counts):
    try:
        st = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as e:
        counts["failed"] += 1
        counts[f"failed_errno_{e.errno}"] += 1
        return
    m = st.st_mode
    if stat.S_ISLNK(m):
        fix(name, st, uid, gid, None, dry, counts, dir_fd=parent_fd)
    elif stat.S_ISREG(m):
        if st.st_nlink > 1:
            counts["skipped_hardlinks"] += 1
            return
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
        except OSError as e:
            counts["failed"] += 1
            counts[f"failed_errno_{e.errno}"] += 1
            return
        try:
            st = os.fstat(fd)
            if stat.S_ISREG(st.st_mode):
                # Also clears setuid/setgid. Keeps the execute bit of the owner only.
                fix(fd, st, uid, gid, (st.st_mode & 0o100) | 0o600, dry, counts)
        finally:
            os.close(fd)
    elif stat.S_ISDIR(m):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        except OSError as e:
            counts["failed"] += 1
            counts[f"failed_errno_{e.errno}"] += 1
            return
        try:
            fix(fd, os.fstat(fd), uid, gid, 0o700, dry, counts)
            for child in os.listdir(fd):
                migrate_entry(fd, child, uid, gid, dry, counts)
        except OSError as e:
            counts["failed"] += 1
            counts[f"failed_errno_{e.errno}"] += 1
        finally:
            os.close(fd)
    else:
        counts["skipped_special"] += 1


def worker(root, uid, gid, dry):
    """Migrates the top-level entries named on stdin (never on the command line, visible in ps)."""
    counts = collections.Counter()
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    for name in sys.stdin.read().split("\0"):
        if name:
            migrate_entry(fd, name, uid, gid, dry, counts)
    print(json.dumps(counts))


def run_worker(root, uid, gid, dry, names, timeout):
    cmd = [sys.executable, __file__, "worker", str(root), str(uid), str(gid), "1" if dry else "0"]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        out, _ = p.communicate("\0".join(names).encode("utf-8", "surrogateescape"), timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()         # if stuck in the kernel on NFS it stays until the I/O returns; we go on
        return None
    if p.returncode != 0:
        return None
    return collections.Counter(json.loads(out))


def list_root(root):
    """(subfolders, top-level files), through a subprocess, or None if NFS does not answer."""
    code = ("import json,os,sys;e=[(x.name,x.is_dir(follow_symlinks=False)) for x in os.scandir(sys.argv[1])];"
            "sys.stdout.buffer.write(json.dumps(e).encode())")
    try:
        p = subprocess.run([sys.executable, "-c", code, str(root)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=LIST_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None
    if p.returncode != 0:
        return None
    entries = json.loads(p.stdout)
    return [n for n, d in entries if d], [n for n, d in entries if not d]


def scan(root, uid, gid, dry=False, on_progress=None):
    """One pass. Returns (counts, folders that did not finish, or None if root could not be listed,
    whether the top of root is fine: without that, the app could not use its database and keys)."""
    listed = list_root(root)
    if listed is None:
        return collections.Counter(), None, False
    folders, files = listed
    counts = collections.Counter()
    # The top comes first: it has the keys, and closes work/ to the sandbox user at once.
    fd = None
    if not dry:
        try:
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            fix(fd, os.fstat(fd), uid, gid, 0o700, dry, counts)
        except OSError as e:
            counts["failed"] += 1
            counts[f"failed_errno_{e.errno}"] += 1
        finally:
            if fd is not None:
                os.close(fd)
    unfinished = []
    r = run_worker(root, uid, gid, dry, files, FOLDER_TIMEOUT) if files else collections.Counter()
    if r is None:
        unfinished.append("top")
    else:
        counts += r
    top_ok = r is not None and counts["failed"] == 0 and counts["skipped_hardlinks"] == 0
    for i, name in enumerate(sorted(folders)):
        r = run_worker(root, uid, gid, dry, [name], FOLDER_TIMEOUT)
        if r is None:
            unfinished.append(i)
        else:
            counts += r
        if on_progress and i % 50 == 0:
            on_progress(i, len(folders), counts, unfinished)
    return counts, unfinished, top_ok


def write_status(**st):
    st["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATUS.with_name(STATUS.name + ".tmp")
    tmp.write_text(json.dumps(st))
    os.chmod(tmp, 0o644)
    os.replace(tmp, STATUS)


def read_status():
    try:
        return json.loads(STATUS.read_text())
    except (OSError, ValueError):
        return {}


def status_line():
    st = read_status()
    line = f"Migration of work/: {st.get('state', 'not started')}, {st.get('done', '?')} of {st.get('total', '?')} folders."
    if st.get("app_can_start") is False:
        line += " The app cannot start: the database or keys at the top of work/ could not be given to its user."
    return line


def probe():
    """Can root chown a file in work/? Exit 0 yes, 1 no, 2 could not test."""
    uid, gid = web_ids()
    path = NFS_DIR / f".fpgaemu-diag-migrate-{os.getpid()}"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError:
        return 2
    try:
        os.fchown(fd, uid, gid)
        return 0 if os.fstat(fd).st_uid == uid else 1
    except OSError:
        return 1
    finally:
        os.close(fd)
        try:
            os.unlink(path)
        except OSError:
            pass


def daemon():
    uid, gid = web_ids()
    marker = NFS_DIR / MARKER

    def finish():
        READY.touch()
        os.chmod(READY, 0o644)
    delay = RETRY_SECONDS
    while True:
        try:
            rc = subprocess.run(["test", "-e", str(marker)], timeout=300).returncode
        except subprocess.TimeoutExpired:
            rc = 2
        if rc == 0:
            write_status(state="done")
            finish()
            return 0
        try:
            rc = subprocess.run([sys.executable, __file__, "probe"], timeout=120).returncode
        except subprocess.TimeoutExpired:
            rc = 2
        if rc == 1:
            # root_squash or similar. worksync.py stays as root and this keeps working as today.
            write_status(state="not possible: root cannot chown on work/ (NFS root_squash?)", chown_possible=False)
            return 0
        if rc == 0:
            def progress(i, total, counts, unfinished):
                write_status(state="running", chown_possible=True, done=i, total=total, counts=counts,
                             unfinished=len(unfinished))
            counts, unfinished, top_ok = scan(NFS_DIR, uid, gid, on_progress=progress)
            if unfinished is not None and not unfinished and counts["failed"] == 0:
                fd = os.open(marker, os.O_WRONLY | os.O_CREAT, 0o600)
                os.fchown(fd, uid, gid)
                os.close(fd)
                write_status(state="done", chown_possible=True, counts=counts)
                finish()
                print(f"migrate_work: work/ done: {dict(counts)}", flush=True)
                return 0
            # One folder that fails must not keep the site closed for everyone: without a cache
            # the app waits for READY, so give it after the first pass if the top is fine. No
            # marker, so worksync keeps its root and this keeps trying.
            if unfinished is not None and top_ok:
                finish()
            write_status(state="retrying", chown_possible=True, counts=counts, app_can_start=top_ok,
                         unfinished=None if unfinished is None else len(unfinished))
            print(f"migrate_work: incomplete, will retry: {dict(counts)}", flush=True)
        time.sleep(delay)
        delay = min(delay * 2, MAX_RETRY_SECONDS)     # each try reads the whole tree, maybe on NFS


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "worker":
        worker(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5] == "1")
    elif cmd == "probe":
        return probe()
    elif cmd == "status":
        print(json.dumps(read_status(), indent=1))
    elif cmd == "local":
        if LOCAL_DIR.is_dir():
            uid, gid = web_ids()
            counts, unfinished, _ = scan(LOCAL_DIR, uid, gid)
            print(f"migrate_work: cachedwork/: {dict(counts)}, unfinished: {len(unfinished or [])}", flush=True)
    elif cmd == "daemon":
        return daemon()
    elif cmd == "scan":
        args = sys.argv[2:]
        root = Path(args[args.index("--root") + 1]) if "--root" in args else NFS_DIR
        uid, gid = web_ids()
        counts, unfinished, _ = scan(root, uid, gid, dry="--dry-run" in args)
        print(json.dumps({"counts": counts, "unfinished": None if unfinished is None else len(unfinished)}, indent=1))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
