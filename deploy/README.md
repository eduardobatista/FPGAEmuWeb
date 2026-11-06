# Sandbox of the code sent by users: deployment

VHDL sent by users runs in a sandbox (`backend/sandboxd.py`), as the user `fpgarun`, which reads
nothing of `fpgaweb` (web app, keys, `work/`). Nothing runs outside it: if the sandbox cannot be
enforced, compilation, simulation, emulation and diagrams are refused with a message.

| Mode | Needs | Protection |
|---|---|---|
| `bwrap` (preferred) | the compose change below | separate uid, own mount, PID and network namespaces, seccomp |
| `fallback` (automatic) | nothing | separate uid, seccomp (no sockets, no ptrace), Landlock on kernels from 5.13 |

Fallback is weaker: jobs share the PID space, so they can see that others exist and send them
signals through `tgkill`. On kernels without Landlock it can read any world-readable file of the
image, and `/proc/<pid>/cwd` of other jobs running at the same time, so it is reported as FAIL.

The mode of each server, and what it allows, is in the **Sandbox** section of `/diagnostics`.
No command on the server is needed to find that out.

## Enabling `bwrap`

In the server's compose file, with `seccomp-bwrap.json` copied next to it:

```yaml
services:
  web:
    security_opt:
      - seccomp=./seccomp-bwrap.json
      # Only if the Sandbox section shows an AppArmor profile (apparmor: docker-default) and the mode
      # is still fallback. It removes that profile from the whole container.
      # - apparmor=unconfined
```

`seccomp-bwrap.json` is Docker's default profile plus `clone`, `clone3`, `unshare`, `mount`,
`umount2` and `pivot_root`. Without capabilities these only work inside a new user namespace.
No `privileged`, no `cap_add`.

On Ubuntu 23.10+ hosts, `kernel.apparmor_restrict_unprivileged_userns=1` also blocks bwrap. The
Sandbox section shows this value as `apparmor_restrict_userns`. The server then stays in fallback.

Recommended as well, whatever the mode, since RLIMIT_NPROC is per server and not per job:
`pids_limit: 2048`, and a `mem_limit` that suits the host.

## Migration of `work/`

Automatic and in the background (`migrate_work.py`, program `workmigrate`), no command needed:

1. `cachedwork/` (local disk) at every start, before the app.
2. `work/` (NFS) folder by folder, with a timeout per folder and retries.
3. On success, a marker `work/.fpgaemu-owner-migrated`. **`worksync` stays as root until it finds
   the marker when it starts**, and needs one more restart to drop root.

Without a cache (`ENVCACHEDWORK` not True) the app waits for the first pass, showing a "starting"
page. A folder that fails does not hold it: the app opens, that folder stays with its old owner,
and the migration keeps trying, at growing intervals up to one hour, without leaving the marker.
Only a failure at the top of `work/` (database, keys) keeps the page, since the app needs them.

While it stays as root it behaves as before, and files it writes get the right owner. If NFS does
not let root chown (`root_squash`), nothing is changed, the section says so, and `worksync` stays
as root. The app itself never runs as root.

Logs and the status have only counts and folder numbers, never the names of the folders.
Hard links and special files are left alone and counted: nothing legitimate creates them in
`work/`, and if the count is not zero they deserve a look, since user code used to run as root.

## Backup

`docker exec` keeps running as root, since the Dockerfile has no `USER`, so `docker exec + tar` keeps
working on `work/`, including the 0600 files of `fpgaweb` such as `.diagkey`. An exception would be
a backup with `docker exec -u` or a compose with `user:`.

## Rollback

The previous image still works with a migrated `work/`, since it runs as root. It creates new
files as root, though: delete `work/.fpgaemu-owner-migrated` before going forward again, so that
the migration runs once more.

## Tests

`tests/sandbox/run.sh bwrap` and `tests/sandbox/run.sh fallback`, after building the image with
`docker build -t fpgaemu-sbx .` They use throwaway containers and fake data only.
