FROM eduardobatista/fpgaemubase:ghdl4

WORKDIR /home

# TODO: Remover celery e redis:
RUN apt-get update \
    && apt-get install -y supervisor nginx rsync cron \
    && pip install SQLAlchemy flask==2.2.2 Werkzeug==2.2.2 flask_socketio==5.3.2 flask_login flask_sqlalchemy requests yagmail psycopg2-binary gevent gevent-websocket psutil gunicorn celery[redis]

# EXPOSE 5000
EXPOSE 80
# EXPOSE 6379

COPY ./ fpgaemuweb/
COPY nginx.conf /etc/nginx/nginx.conf
COPY nginxdefault.conf /etc/nginx/sites-enabled/default

ARG CACHEDWORK
ENV ENVCACHEDWORK ${CACHEDWORK}
ARG BCKSERVER 
ENV ENV_BCKSERVER ${BCKSERVER}
ARG BCKPASS
ENV ENV_BCKPASS ${BCKPASS} 

VOLUME ["/home/fpgaemuweb/persistentwork"]

RUN mkdir /home/fpgaemuweb/work
RUN touch /home/stdout.log
RUN touch /home/stdout.err

# ENTRYPOINT ["/usr/bin/supervisord","-c","/home/fpgaemuweb/supervisord.conf"]
ENTRYPOINT [ "/home/fpgaemuweb/entrypoint.sh" ]
