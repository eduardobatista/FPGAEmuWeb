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

# Server diagnostics: full check in background at every start (see diagnostics/diagnose.py).
# (the diagnostics URL with its key is printed by worksync.py once the data is available)
DIAG=/home/fpgaemuweb/diagnostics/diagnose.py
if command -v ionice >/dev/null 2>&1; then IONICE="ionice -c 3"; else IONICE=""; fi
nohup nice -n 10 $IONICE /usr/bin/python3 $DIAG run --mode full --reason startup > /home/diagnostics-startup.log 2>&1 &

crontab /home/fpgaemuweb/crontask
cron start

# exec: supervisord becomes PID 1 and receives SIGTERM on "docker stop", so worksync.py can
# make a final save to NFS before the container goes away.
exec /usr/bin/supervisord -c /home/fpgaemuweb/supervisord.conf