#!/bin/sh

# if ${ENV_BCKSERVER+"false"} 
# then
#   echo "ENV_BCKSERVER is empty."
# else
#   echo "00 * * * * rsync -a /home/fpgaemuweb/work/ $ENV_BCKSERVER" >> /home/fpgaemuweb/crontask
# fi


# if [[ -v "${ENV_BCKPASS}" ]]; then
#   echo "ENV_BCKPASS is empty."
# else
#   echo $ENV_BCKPASS > /home/fpgaemuweb/bckpass.txt
# fi

echo ${ENVCACHEDWORK}
if [ "${ENVCACHEDWORK}" = "True" ];
then
  echo "ENVCACHEDWORK is true.";
  mkdir -p /home/fpgaemuweb/cachedwork;
  # work/ (NFS) is synced by worksync.py (supervisord); do not touch it here, it may stall.
  # cp -r /home/fpgaemuweb/work/* /home/fpgaemuweb/cachedwork/;
  # rm /home/fpgaemuweb/crontask;
  # echo "00,10,20,30,40,50 * * * * rsync -a /home/fpgaemuweb/cachedwork/ /home/fpgaemuweb/work/" >> /home/fpgaemuweb/crontask;
else
  echo "ENVCACHEDWORK is false.";
fi

# The app and the sandbox run without root (see supervisord.conf). What only root can prepare:
unset FPGAEMU_SANDBOX    # development switch: never in the container
APP=/home/fpgaemuweb
install -d -o fpgarun -g fpgaweb -m 0750 /run/fpgaemu
# temp/ has only what can be regenerated. Jobs of a previous run may have left anything there.
mkdir -p $APP/temp
find $APP/temp -mindepth 1 -delete
chown fpgaweb:fpgaweb $APP/temp
chmod 0711 $APP/temp
install -d -o fpgaweb -g fpgajob -m 2710 $APP/temp/.jobs
install -d -o fpgaweb -g fpgaweb -m 0750 $APP/.worksync /home/diagnostics
chown -R --no-dereference fpgaweb:fpgaweb /home/diagnostics
touch /home/stdout.log /home/stderr.log
chmod 0640 /home/stdout.log /home/stderr.log
chown root:fpgaweb /home/stdout.log /home/stderr.log
# Local disk: fast, done before the app. work/ (NFS) may stall, so it is left to workmigrate.
rm -f $APP/.worksync/migration-ready
if [ -d $APP/cachedwork ]; then chown -R --no-dereference fpgaweb:fpgaweb $APP/.worksync; /usr/bin/python3 $APP/migrate_work.py local; fi

# Server diagnostics: full check in background at every start (see diagnostics/diagnose.py).
# (the diagnostics URL with its key is printed by worksync.py once the data is available)
DIAG=/home/fpgaemuweb/diagnostics/diagnose.py
if command -v ionice >/dev/null 2>&1; then IONICE="ionice -c 3"; else IONICE=""; fi
nohup nice -n 10 $IONICE setpriv --reuid=fpgaweb --regid=fpgaweb --init-groups env HOME=/home/fpgaweb /usr/bin/python3 $DIAG run --mode full --reason startup > /home/diagnostics-startup.log 2>&1 &

crontab /home/fpgaemuweb/crontask
cron start

# exec: supervisord becomes PID 1 and receives SIGTERM on "docker stop", so worksync.py can
# make a final save to NFS before the container goes away.
exec /usr/bin/supervisord -c /home/fpgaemuweb/supervisord.conf