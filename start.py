# from . import create_app, socketio
import subprocess,os
from pathlib import Path
from appp import create_app, socketio, db
import main.models
import logging

MAINPATH = os.path.dirname(os.path.abspath(__file__))
# print('Compiling the backend...')
analyzerpath = Path(MAINPATH,'backend','analyze.sh')
analyzerpath.chmod(0o744)
simulatorpath = Path(MAINPATH,'backend','simulate.sh')
simulatorpath.chmod(0o744)
backendcompilerpath = Path(MAINPATH,'backend','compilebackend.sh')
backendcompilerpath.chmod(0o744)
subprocess.Popen(
                    [backendcompilerpath],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=Path(MAINPATH,'backend') 
            )
print('Backend compiled.\nStarting server...')

app = create_app(debug=True,mainpath=MAINPATH)

with app.app_context():
    db.create_all()

# log = logging.getLogger('werkzeug')
# log.setLevel(logging.ERROR)

if __name__ == '__main__':
    socketio.run(app,host='0.0.0.0',port=5000)