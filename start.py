# from . import create_app, socketio
import subprocess
import os
import json
from pathlib import Path
from appp import create_app, socketio, db
# from sqlalchemy import create_engine
# from sqlalchemy.exc import OperationalError
from main.models import User
from werkzeug.security import generate_password_hash
import sys
# from time import sleep

'''
    TODO:
        - settings file
        - Templates.
        - Melhorar gerenciamento de usuários.
'''

MAINPATH = os.path.dirname(os.path.abspath(__file__))
# print('Compiling the backend...')
# In the container the backend is compiled in the image (backend/setup-image.sh) and this user
# cannot write there. This is for running from a checkout.
if os.access(Path(MAINPATH,'backend'),os.W_OK):
    for script in ('ghwhierarchy.sh','ghwgetsignals.sh','analyze.sh','simulate.sh','compilebackend.sh'):
        Path(MAINPATH,'backend',script).chmod(0o755)
    subprocess.Popen(
                        [Path(MAINPATH,'backend','compilebackend.sh')],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        cwd=Path(MAINPATH,'backend') 
                )
# print('Backend compiled.\nStarting server...')

cwork = os.environ.get("ENVCACHEDWORK", "False")
if (cwork == "False") or (cwork == ""):
    WORKDIR = Path(MAINPATH) / "work"
else:
    WORKDIR = Path(MAINPATH) / "cachedwork"

if not WORKDIR.exists():
    WORKDIR.mkdir()

debugopt = False
if "debug" in sys.argv:
    debugopt = True

recaptchakeys = {'RECAPTCHA_SITE_KEY':"",'RECAPTCHA_SECRET_KEY':""}
recaptchafile = WORKDIR / "recaptcha.json"
if recaptchafile.exists():
    with open(recaptchafile,"r") as ff:
        info = ff.read()
        try:
            data = json.loads(info)        
            recaptchakeys['RECAPTCHA_SITE_KEY'] = data['RECAPTCHA_SITE_KEY']
            recaptchakeys['RECAPTCHA_SECRET_KEY'] = data['RECAPTCHA_SECRET_KEY']
        except Exception as e:
            # app.logger.error('Failed loading recaptcha info at startup.') 
            print(f'Failed loading recaptcha info at startup: {e}')
            pass   

app = create_app(debug=debugopt,mainpath=MAINPATH,workdir=WORKDIR,recaptchakeys=recaptchakeys)

with app.app_context():
    try:        
        user = User.query.filter_by(email='admin@fpgaemu').first()
    except BaseException as ee:# OperationalError as err:  
        print(f'Error: {ee}')
        app.logger.info('Database does not exist, creating...')
        db.create_all()
        db.session.commit()
        new_user = User(email='admin@fpgaemu', name='Admin', password=generate_password_hash('admin', method='scrypt'), role='Admin', viewAs='')
        db.session.add(new_user)
        db.session.commit()


if __name__ == '__main__':
    socketio.run(app,host='0.0.0.0',port=5000)
