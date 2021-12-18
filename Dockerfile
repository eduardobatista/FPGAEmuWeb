FROM ghdl/vunit:llvm

WORKDIR /home

COPY ./ fpgaemuweb/

VOLUME ["/home/fpgaemuweb/work"]

RUN pip install flask flask_socketio flask_migrate flask_login flask_sqlalchemy yagmail psycopg2-binary gevent gevent-websocket psutil gunicorn
EXPOSE 5000

RUN apt-get update && apt-get install -y supervisor
# COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
RUN mkdir /home/work
RUN touch /home/stdout.log
RUN touch /home/stdout.err
RUN sleep 10

ENTRYPOINT ["/usr/bin/supervisord","-c","/home/fpgaemuweb/supervisord.conf"]
# ENTRYPOINT /usr/local/bin/gunicorn -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker -b :5000 -w 1 --chdir /home/fpgaemuweb start:app

# CMD cd /home/fpgaemuweb && python3 start.py

# ENTRYPOINT ["/bin/sh"]
