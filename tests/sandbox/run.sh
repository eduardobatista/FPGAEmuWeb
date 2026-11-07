#!/bin/bash
# Full test, in throwaway containers, with fake data only. Usage: tests/sandbox/run.sh [bwrap|fallback|nolandlock]
#   bwrap     container with deploy/seccomp-bwrap.json
#   fallback  default Docker profile, as on a server whose container configuration cannot change
#   nolandlock  the same on a kernel without Landlock (simulated: a profile that denies its calls)
set -u
MODE=${1:-bwrap}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
IMG=${IMG:-fpgaemu-sbx}
C=fpgaemu-test-$MODE
V=fpgaemu-test-nfs-$MODE
OPTS=""
[ "$MODE" = bwrap ] && OPTS="--security-opt seccomp=$ROOT/deploy/seccomp-bwrap.json"
if [ "$MODE" = nolandlock ]; then
  NL=$(mktemp); trap 'rm -f "$NL"' EXIT
  python3 - "$ROOT/deploy/seccomp-bwrap.json" "$NL" <<'PY2'
import json, sys
p = json.load(open(sys.argv[1]))
p["syscalls"] = [s for s in p["syscalls"] if "unshare" not in s["names"]]
for s in p["syscalls"]:
    s["names"] = [n for n in s["names"] if not n.startswith("landlock_")]
json.dump(p, open(sys.argv[2], "w"))
PY2
  chmod 644 "$NL"; OPTS="--security-opt seccomp=$NL"
fi
docker rm -f $C >/dev/null 2>&1; docker volume rm $V >/dev/null 2>&1
fail=0

echo "=== prepare: a work/ as production has it (fake), owned by root"
docker volume create $V >/dev/null
psx() { docker exec $C sh -c 'for p in /proc/[0-9]*; do printf "%s " "$(stat -c %U $p 2>/dev/null)"; tr "\0" " " < $p/cmdline 2>/dev/null; echo; done'; }
docker run --rm -v $V:/w --entrypoint sh $IMG -c '
  cd /w
  mkdir -p legacy3@example.invalid rootonly4@example.invalid/sub
  echo "CANARY-OTHER-USER" > legacy3@example.invalid/secret.vhd
  echo "CANARY-ROOTONLY" > rootonly4@example.invalid/sub/x.vhd; chmod 700 rootonly4@example.invalid rootonly4@example.invalid/sub; chmod 600 rootonly4@example.invalid/sub/x.vhd
  echo "FAKE-DIAGKEY-0123456789" > .diagkey; chmod 600 .diagkey
  ln -s /etc/shadow legacy3@example.invalid/evil_link
  cp /bin/true legacy3@example.invalid/suid; chmod 4755 legacy3@example.invalid/suid
  echo x > legacy3@example.invalid/hl1; ln legacy3@example.invalid/hl1 legacy3@example.invalid/hl2
  mkfifo legacy3@example.invalid/oldfifo
  printf "\377\376u\000s\000e\000" > legacy3@example.invalid/utf16.vhd
  printf "use\000ieee" > legacy3@example.invalid/damaged.vhd
  chown -R 0:0 .'
echo "=== dry-run counts only, no names"
docker run --rm -v $V:/home/fpgaemuweb/work --entrypoint /usr/bin/python3 $IMG /home/fpgaemuweb/migrate_work.py scan --dry-run | tee /tmp/dry.$$ | tr -d '\n '; echo
grep -q example.invalid /tmp/dry.$$ && { echo "FAIL names in dry-run"; fail=1; }; rm -f /tmp/dry.$$

start() { docker run -d --name $C $OPTS -v $V:/home/fpgaemuweb/work -e ENVCACHEDWORK=True -e WORKSYNC_INTERVAL=10 -e MIGRATE_RETRY_SECONDS=5 $IMG >/dev/null; }
waitup() { for i in $(seq 1 120); do docker exec $C sh -c "python3 -c \"import urllib.request as u;u.urlopen('http://127.0.0.1:5000/login')\"" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
start
waitup || { echo "app did not start"; docker logs $C | tail -30; exit 1; }
for i in $(seq 1 60); do docker exec $C test -e /home/fpgaemuweb/.worksync/migration-ready && break; sleep 1; done
sleep 15
echo "=== processes"; psx | grep -E "gunicorn|huey|sandboxd|worksync|supervisord|diagnose" | cut -c1-90
psx | grep -E "gunicorn|huey" | grep -q '^root' && { echo "FAIL web as root"; fail=1; }
psx | grep sandboxd.py | grep -q '^fpgarun' || { echo "FAIL sandboxd user"; fail=1; }
echo "=== sandbox status"; docker exec $C su -s /bin/sh fpgaweb -c 'cd /home/fpgaemuweb && .venv/bin/python -c "
import sys;sys.path.insert(0,\".\")
import importlib.util as u
s=u.spec_from_file_location(\"sb\",\"main/sandbox.py\");m=u.module_from_spec(s);s.loader.exec_module(m);print(m.status())"' | cut -c1-300
echo "=== migration"; docker exec $C python3 /home/fpgaemuweb/migrate_work.py status | tr -d '\n ' ; echo
docker exec $C sh -c 'cd /home/fpgaemuweb/work && stat -c "%U %a %F" . .diagkey rootonly4@example.invalid/sub/x.vhd legacy3@example.invalid/secret.vhd legacy3@example.invalid/suid; stat -c "hardlink untouched: %U" legacy3@example.invalid/hl1; stat -c "symlink: %U" legacy3@example.invalid/evil_link; stat -c "shadow still: %U %a" /etc/shadow'

SECK=$(docker exec $C cat /home/fpgaemuweb/cachedwork/seckeyb | od -An -tx1 | tr -d ' \n')
ARGS="{\"mode\":\"$MODE\",\"workdir\":\"/home/fpgaemuweb/cachedwork\",\"canary_rel\":\"legacy3@example.invalid/secret.vhd\",\"canaries\":{\"other_user\":\"CANARY-OTHER-USER\",\"rootonly\":\"CANARY-ROOTONLY\",\"diagkey\":\"FAKE-DIAGKEY-0123456789\",\"victim_build\":\"CANARY-VICTIM-BUILD\"}}"
echo "=== e2e"; docker cp -q "$ROOT/tests/sandbox" $C:/tmp/sbtest; docker exec $C chmod -R a+rX /tmp/sbtest
docker exec -e E2E_ARGS="$ARGS" $C su -s /bin/bash fpgaweb -c 'cd /tmp/sbtest && E2E_ARGS="$E2E_ARGS" /home/fpgaemuweb/.venv/bin/python e2e.py' || fail=1

echo "=== worksync pushes what users save, with the right owner"
sleep 15
docker exec $C sh -c 'stat -c "%U %a" /home/fpgaemuweb/work/aluno1@example.invalid/proj/usertop.vhd' 2>&1 | sed 's/aluno1@example.invalid/<user>/' | tee /tmp/ow.$$
grep -q '^fpgaweb 600' /tmp/ow.$$ || { echo "FAIL owner of pushed file"; fail=1; }; rm -f /tmp/ow.$$

echo "=== diagnostics page: sandbox section, no names"
docker exec $C su -s /bin/sh fpgaweb -c 'HOME=/home/fpgaweb /usr/bin/python3 /home/fpgaemuweb/diagnostics/diagnose.py run --mode quick --reason test' >/tmp/dg.$$ 2>&1
docker exec $C sh -c 'cat /home/diagnostics/latest.json 2>/dev/null || ls -t /home/diagnostics/history/* | head -1 | xargs cat' > /tmp/dj.$$
python3 - /tmp/dj.$$ <<'PY2'
import json,sys
d=json.load(open(sys.argv[1]))
for c in d.get("checks",[]):
    if c["id"] in ("sandbox","image","toolchain","python","workdata"):
        print(c["id"],c["status"],"|",c["summary"][:120])
    if c["id"]=="sandbox":
        for lv,t in c["details"]:
            if t.startswith(("sandbox","migration","work:")): print("   ",lv,t[:170])
PY2
grep -c 'FAKE-\|CANARY' /tmp/dj.$$ | sed 's/^/secrets in report: /'
python3 - /tmp/dj.$$ <<'PY2' || fail=1
import json,sys
w=[c for c in json.load(open(sys.argv[1]))["checks"] if c["id"]=="workdata"][0]
utf16=[(l,t) for l,t in w["details"] if "utf16.vhd" in t]
dmg=[(l,t) for l,t in w["details"] if "damaged.vhd" in t]
ok=len(utf16)==1 and utf16[0][0]=="info" and "UTF-16" in utf16[0][1] and len(dmg)==1 and dmg[0][0]=="fail"
print(("PASS" if ok else "FAIL")+"  NUL notice: UTF-16 is info, other NUL is fail")
sys.exit(0 if ok else 1)
PY2
rm -f /tmp/dg.$$ /tmp/dj.$$

echo "=== backup as in production: docker exec + tar, as root"
docker exec $C tar -C /home/fpgaemuweb -czf - work cachedwork > /tmp/bk.$$.tgz; rc=$?; echo "tar rc=$rc"; [ $rc -eq 0 ] || [ $rc -eq 1 ] || fail=1
tar -tzf /tmp/bk.$$.tgz | grep -E -c '(work|cachedwork)/\.diagkey$' | grep -qE '^[12]$' || { echo "FAIL .diagkey not in backup"; fail=1; }; rm -f /tmp/bk.$$.tgz

echo "=== names of users in the logs of the new components"
docker exec $C sh -c 'cat /home/fpgaemuweb/.worksync/migration.json /home/fpgaemuweb/.worksync/status.json; ls /var/log/supervisor/ 2>/dev/null; cat /var/log/supervisor/sandboxd* /var/log/supervisor/workmigrate* /var/log/supervisor/worksync* 2>/dev/null' > /tmp/lg.$$
wc -l < /tmp/lg.$$; if grep -q 'example.invalid' /tmp/lg.$$; then echo "FAIL names in logs:"; grep -c example.invalid /tmp/lg.$$; fail=1; else echo "PASS no names"; fi; rm -f /tmp/lg.$$

echo "=== restart: worksync must drop root now"
docker restart $C >/dev/null; waitup; sleep 8
psx | grep "worksync.py daemon" | cut -c1-70
psx | grep "worksync.py daemon" | grep -q '^fpgaweb' || { echo "FAIL worksync still root"; fail=1; }
echo "=== worksync without root still pushes"
docker exec $C su -s /bin/sh fpgaweb -c 'echo x > /home/fpgaemuweb/cachedwork/aluno1@example.invalid/proj/after.vhd'
sleep 15; docker exec $C test -f /home/fpgaemuweb/work/aluno1@example.invalid/proj/after.vhd && docker exec $C stat -c "%U %a" /home/fpgaemuweb/work/aluno1@example.invalid/proj/after.vhd | grep -q '^fpgaweb 600' && echo "PASS pushed" || { echo "FAIL push without root"; fail=1; }
docker exec $C stat -c "%U %a" /home/fpgaemuweb/work/dbb.sqlite | sed 's/^/database on NFS: /'
echo "=== development switch cannot reach the container"
docker run --rm -e FPGAEMU_SANDBOX=off --entrypoint sh $IMG -c '. /dev/null; grep -c "unset FPGAEMU_SANDBOX" /home/fpgaemuweb/entrypoint.sh'
echo "=== diagnostics: a service still starting is not a FAIL, one that is down is"
docker run --rm --entrypoint sh $IMG -c '
  install -d -o fpgarun -g fpgaweb -m 0750 /run/fpgaemu
  CHK="import sys; sys.path.insert(0,\"/home/fpgaemuweb\")
from diagnostics import diagnose as d
c=d.Check(\"sandbox\",\"x\"); d._sandbox_runtime(c); print(c.status,c.summary)"
  FPGAEMU_DIAG_SANDBOX_WAIT=2 setpriv --reuid=fpgaweb --regid=fpgaweb --init-groups python3 -c "$CHK" | sed "s/^/down: /"
  ( sleep 6; exec setpriv --reuid=fpgarun --regid=fpgajob --init-groups env -i PATH=/usr/bin:/bin python3 /home/fpgaemuweb/backend/sandboxd.py >/dev/null ) &
  setpriv --reuid=fpgaweb --regid=fpgaweb --init-groups python3 -c "$CHK" | sed "s/^/starting: /"
  kill %1 2>/dev/null' 2>&1 | cut -c1-120 | tee /tmp/ds.$$
grep -q '^down: fail' /tmp/ds.$$ && echo "PASS real outage is a FAIL" || { echo "FAIL outage not reported"; fail=1; }
grep -q '^starting: \(ok\|info\|warn\)' /tmp/ds.$$ && echo "PASS waits for the service" || { echo "FAIL false FAIL while starting"; fail=1; }
rm -f /tmp/ds.$$

echo "=== migration when root cannot chown (root_squash): nothing changes, status tells"
docker run --rm -v $V:/x --entrypoint sh $IMG -c 'mkdir -p /home/fpgaemuweb/work/f@example.invalid; echo s > /home/fpgaemuweb/work/f@example.invalid/a; chmod 644 /home/fpgaemuweb/work/f@example.invalid/a
  setpriv --bounding-set=-chown --inh-caps=-chown python3 /home/fpgaemuweb/migrate_work.py probe; echo "probe rc=$?"
  setpriv --bounding-set=-chown --inh-caps=-chown python3 /home/fpgaemuweb/migrate_work.py daemon; echo "daemon rc=$?"
  python3 /home/fpgaemuweb/migrate_work.py status | tr -d "\n"; echo; stat -c "%U %a" /home/fpgaemuweb/work/f@example.invalid/a; test -e /home/fpgaemuweb/work/.fpgaemu-owner-migrated && echo "FAIL marker" || echo "no marker: ok"'
echo "=== migration when NFS stalls (every folder times out): retries, no marker"
docker run --rm -e MIGRATE_FOLDER_TIMEOUT=0 -e MIGRATE_RETRY_SECONDS=1 --entrypoint sh $IMG -c 'mkdir -p /home/fpgaemuweb/work/f@example.invalid; timeout 6 python3 /home/fpgaemuweb/migrate_work.py daemon | sed "s/{.*//" | head -2; python3 /home/fpgaemuweb/migrate_work.py status | tr -d "\n"; echo; test -e /home/fpgaemuweb/work/.fpgaemu-owner-migrated && echo "FAIL marker" || echo "no marker: ok"'
echo "=== without cache (ENVCACHEDWORK=False), work/ with root folders"
V2=$V-nc; docker volume create $V2 >/dev/null; docker run --rm -v $V2:/w --entrypoint sh $IMG -c 'mkdir -p /w/root5@example.invalid; echo s > /w/root5@example.invalid/x.vhd; chmod 700 /w/root5@example.invalid'
docker run -d --name $C-nc $OPTS -v $V2:/home/fpgaemuweb/work -e ENVCACHEDWORK=False $IMG >/dev/null
ok=0; for i in $(seq 1 60); do docker exec $C-nc sh -c "python3 -c \"import urllib.request as u;print(u.urlopen('http://127.0.0.1:5000/login').read()[:300])\"" 2>/dev/null | grep -qi 'starting' || { docker exec $C-nc sh -c "python3 -c \"import urllib.request as u;u.urlopen('http://127.0.0.1:5000/login')\"" >/dev/null 2>&1 && { ok=1; break; }; }; sleep 1; done
[ $ok = 1 ] && echo "PASS app up" || { echo "FAIL app not up"; docker logs $C-nc 2>&1 | tail -10 | cut -c1-150; fail=1; }
docker exec $C-nc stat -c "%U %a" /home/fpgaemuweb/work /home/fpgaemuweb/work/seckeyb; docker rm -f $C-nc >/dev/null; docker volume rm $V2 >/dev/null

# The starting page answers 503: its body counts too.
page() { docker exec $1 python3 -c "
import urllib.request as u, urllib.error as e
try:
    print(u.urlopen('http://127.0.0.1:5000/login').read().decode('utf-8','replace'))
except e.HTTPError as x:
    print(x.read().decode('utf-8','replace'))" 2>/dev/null; }
echo "=== without cache: a folder whose chown fails does not keep the site closed"
V3=$V-ro; V4=$V-rod; docker volume create $V3 >/dev/null; docker volume create $V4 >/dev/null
docker run --rm -v $V4:/d --entrypoint sh $IMG -c 'echo s > /d/x.vhd'
docker run --rm -v $V3:/w --entrypoint sh $IMG -c 'mkdir -p /w/good6@example.invalid; echo s > /w/good6@example.invalid/y.vhd'
docker run -d --name $C-ro $OPTS -v $V3:/home/fpgaemuweb/work -v $V4:/home/fpgaemuweb/work/stuck7@example.invalid:ro -e ENVCACHEDWORK=False -e MIGRATE_RETRY_SECONDS=2 $IMG >/dev/null
ok=0; for i in $(seq 1 90); do t=$(page $C-ro); if [ -n "$t" ] && ! echo "$t" | grep -qi 'is starting'; then ok=1; break; fi; sleep 1; done
[ $ok = 1 ] && echo "PASS app opened despite the failure" || { echo "FAIL app stayed closed"; docker logs $C-ro 2>&1 | tail -8 | cut -c1-150; fail=1; }
docker exec $C-ro python3 /home/fpgaemuweb/migrate_work.py status | tr -d '\n ' ; echo
docker exec $C-ro test -e /home/fpgaemuweb/work/.fpgaemu-owner-migrated && { echo "FAIL marker written with failures"; fail=1; } || echo "PASS no marker"
docker exec $C-ro stat -c "%U %a" /home/fpgaemuweb/work/good6@example.invalid/y.vhd | grep -q '^fpgaweb 600' && echo "PASS other folders migrated" || { echo "FAIL other folders"; fail=1; }
docker logs $C-ro 2>&1 | grep -c 'example.invalid' | sed 's/^/names in container log: /'
docker rm -f $C-ro >/dev/null

echo "=== without cache: a failure in the keys keeps the starting page, and it says why"
T=$(mktemp); echo K > "$T"; chmod 644 "$T"
docker run -d --name $C-top $OPTS -v $V3:/home/fpgaemuweb/work -v "$T":/home/fpgaemuweb/work/seckeyb:ro -e ENVCACHEDWORK=False -e MIGRATE_RETRY_SECONDS=2 $IMG >/dev/null
closed=0; for i in $(seq 1 30); do t=$(page $C-top); echo "$t" | grep -qi 'is starting' && closed=1; sleep 1; done
t=$(page $C-top); echo "$t" | grep -qi 'is starting' && [ $closed = 1 ] && echo "PASS stays on the starting page" || { echo "FAIL page: $(echo "$t" | head -c 200)"; fail=1; }
docker exec $C-top python3 /home/fpgaemuweb/migrate_work.py status | grep -q '"app_can_start": false' && echo "PASS status tells why" || { echo "FAIL status"; fail=1; }
docker rm -f $C-top >/dev/null; rm -f "$T"; docker volume rm $V3 $V4 >/dev/null
[ "${KEEP:-}" = 1 ] || { docker rm -f $C >/dev/null; docker volume rm $V >/dev/null; }
[ $fail -eq 0 ] && echo "ALL OK ($MODE)" || echo "FAILURES ($MODE)"
exit $fail
