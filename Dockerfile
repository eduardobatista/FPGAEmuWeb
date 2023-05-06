# FROM ghdl/vunit:llvm
FROM python:3.10

WORKDIR /home

# RUN apt-get install -y python3 python3-pip

RUN apt-get update \
    && apt-get install -y supervisor nginx redis-server ghdl-llvm gtkwave rsync cron \
    && pip install SQLAlchemy flask==2.2.2 Werkzeug==2.2.2 flask_socketio==5.3.2 flask_migrate flask_login flask_sqlalchemy==3.0.2 requests yagmail psycopg2-binary gevent gevent-websocket psutil gunicorn celery[redis]

EXPOSE 5000
EXPOSE 80
EXPOSE 6379

# RUN apt-get install -y 
# RUN apt-get install -y ghdl-llvm
# RUN apt-get install -y gtkwave
# COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

COPY ./ fpgaemuweb/
COPY nginx.conf /etc/nginx/nginx.conf
COPY nginxdefault.conf /etc/nginx/sites-enabled/default

VOLUME ["/home/fpgaemuweb/persistentwork"]

RUN mkdir /home/fpgaemuweb/work
RUN touch /home/stdout.log
RUN touch /home/stdout.err

# ENTRYPOINT ["/usr/bin/supervisord","-c","/home/fpgaemuweb/supervisord.conf"]
ENTRYPOINT [ "/home/fpgaemuweb/entrypoint.sh" ]
