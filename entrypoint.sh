#!/bin/sh

rsync -a /home/fpgaemuweb/persistentwork/ /home/fpgaemuweb/work

crontab /home/fpgaemuweb/crontask
cron start

/usr/bin/supervisord -c /home/fpgaemuweb/supervisord.conf