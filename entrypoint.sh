#!/bin/sh

cron start

rsync -a /home/fpgaemuweb/persistentwork/ /home/fpgaemuweb/work

/usr/bin/supervisord -c /home/fpgaemuweb/supervisord.conf