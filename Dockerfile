FROM ghdl/vunit:llvm

WORKDIR /home

COPY ./ fpgaemuweb/

VOLUME ["/home/fpgaemuweb/work"]

RUN pip install flask flask_socketio flask_migrate flask_login flask_sqlalchemy yagmail psycopg2-binary
EXPOSE 5000

# CMD cd /home/fpgaemuweb && python3 start.py

ENTRYPOINT ["python3", "/home/fpgaemuweb/start.py"]
