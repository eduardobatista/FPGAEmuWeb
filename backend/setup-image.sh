#!/bin/sh
# Image build step, shared by the Dockerfiles: users, sandbox tool, compiled backend, permissions.
#   fpgaweb  web app, huey, worksync, diagnostics. Owns work/ and the keys.
#   fpgarun  code sent by users (backend/sandboxd.py). Owns nothing and reads nothing of fpgaweb.
#   fpgajob  group of both: the job directories (temp/.jobs/<token>) are the only thing they share.
# Fixed, high ids: they are stored on NFS, and RLIMIT_NPROC counts all processes of a uid.
set -e
APP=/home/fpgaemuweb

DEBIAN_FRONTEND=noninteractive apt-get -y install --no-install-recommends bubblewrap
groupadd -g 61001 fpgaweb
groupadd -g 61002 fpgarun
groupadd -g 61003 fpgajob
useradd -u 61001 -g fpgaweb -G fpgajob -M -d /home/fpgaweb -s /usr/sbin/nologin fpgaweb
useradd -u 61002 -g fpgajob -M -d /nonexistent -s /usr/sbin/nologin fpgarun
install -d -o fpgaweb -g fpgaweb -m 0700 /home/fpgaweb

cd "$APP/backend"
bash ./compilebackend.sh
chown -R root:root "$APP/backend"
chmod -R a+rX,go-w "$APP/backend"
chmod 0755 fpgacompileweb analyze.sh simulate.sh ghwhierarchy.sh ghwgetsignals.sh compilebackend.sh sandboxd.py
