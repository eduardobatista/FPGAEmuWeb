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

cp /home/fpgaemuweb/work/dbb.sqlite /home/fpgaemuweb/work/seckeyb /home/fpgaemuweb/

crontab /home/fpgaemuweb/crontask
cron start

/usr/bin/supervisord -c /home/fpgaemuweb/supervisord.conf