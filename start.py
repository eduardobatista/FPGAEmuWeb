# from . import create_app, socketio
import subprocess,os
from pathlib import Path
from appp import create_app, socketio

MAINPATH = os.path.dirname(os.path.abspath(__file__))
# print('Compiling the backend...')
backendcompilerpath = Path(MAINPATH,'backend','compilebackend.sh')
backendcompilerpath.chmod(0o744)
subprocess.Popen(
                    [backendcompilerpath],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=Path(MAINPATH,'backend') 
            )
print('Backend compiled.\nStarting server...')

app = create_app(debug=False,mainpath=MAINPATH)

if __name__ == '__main__':
    socketio.run(app,host='0.0.0.0',port=5000)