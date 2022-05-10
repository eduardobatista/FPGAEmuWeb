FROM ghdl/vunit:llvm

WORKDIR /home

COPY ./ fpgaemuweb/

VOLUME ["/home/fpgaemuweb/work"]

RUN pip install flask flask_socketio flask_migrate flask_login flask_sqlalchemy requests yagmail psycopg2-binary gevent gevent-websocket psutil gunicorn celery[redis]
EXPOSE 5000
EXPOSE 6379

RUN apt-get update && apt-get install -y supervisor
RUN apt-get install -y redis-server
# COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
RUN mkdir /home/work
RUN touch /home/stdout.log
RUN touch /home/stdout.err

ENTRYPOINT ["/usr/bin/supervisord","-c","/home/fpgaemuweb/supervisord.conf"]
# ENTRYPOINT /usr/local/bin/gunicorn -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker -b :5000 -w 1 --chdir /home/fpgaemuweb start:app

# ENTRYPOINT cd /home/fpgaemuweb && python3 start.py debug

# ENTRYPOINT ["/bin/sh"]
