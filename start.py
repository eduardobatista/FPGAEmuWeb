# from . import create_app, socketio
import subprocess,os
from pathlib import Path
from appp import create_app, socketio, db
from main.models import User
import logging
from sqlalchemy.exc import OperationalError
from werkzeug.security import generate_password_hash

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
    try:
        user = User.query.filter_by(email='admin@fpgaemu').first()
    except OperationalError as err:
        print('Database does not exist, creating...')
        db.create_all()
        new_user = User(email='admin@fpgaemu', name='Admin', password=generate_password_hash('admin', method='sha256'), role='Admin')
        db.session.add(new_user)
        db.session.commit()  



# log = logging.getLogger('werkzeug')
# log.setLevel(logging.ERROR)

if __name__ == '__main__':
    socketio.run(app,host='0.0.0.0',port=5000)