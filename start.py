# from . import create_app, socketio
import subprocess,os,json
from pathlib import Path
from appp import create_app, socketio, db
from main.models import User
import logging
from sqlalchemy.exc import OperationalError
from werkzeug.security import generate_password_hash
from datetime import datetime
import signal
import sys
from time import sleep

'''
    TODO:
        - settings file
        - Melhorar Logging
        - Templates.

        - Compilar só arquivos que importam (i.e., pegar usertop e components lá declarados)
        - Melhorar Timeouts: fazer inactivity para entrada e saída diferentes.
        nn Matar outro processo do usuário na criação de um novo.
        nn Controlar melhor processos de emulação.
        nn Desabilitar botões e chaves quando simulação não estiver rodando?
        - Melhorar gerenciamento de usuários.
'''

MAINPATH = os.path.dirname(os.path.abspath(__file__))
# print('Compiling the backend...')
ghwhierarchypath = Path(MAINPATH,'backend','ghwhierarchy.sh')
ghwhierarchypath.chmod(0o744)
ghwsignalspath = Path(MAINPATH,'backend','ghwgetsignals.sh')
ghwsignalspath.chmod(0o744)
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
# print('Backend compiled.\nStarting server...')

WORKDIR = Path(MAINPATH) / "work"

# If db.sqlite does not exist, erase seckey:
localdburl = 'sqlite:///db.sqlite'  # WARNING: do not put local database in other place without changing the seckey.
if not Path(MAINPATH,"db.sqlite").exists():
    seckeyfile = Path(MAINPATH,"seckey")
    if seckeyfile.exists():
        seckeyfile.unlink()

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
            app.logger.error('Failed loading recaptcha info at startup.')    

app = create_app(debug=debugopt,mainpath=MAINPATH,workdir=WORKDIR,localdburl=localdburl,recaptchakeys=recaptchakeys)

with app.app_context():
    try:        
        user = User.query.filter_by(email='admin@fpgaemu').first()
    except:# OperationalError as err:  
        # print('Database does not exist, creating...')
        app.logger.info('Database does not exist, creating...')
        db.create_all()
        db.session.commit()
        new_user = User(email='admin@fpgaemu', name='Admin', password=generate_password_hash('admin', method='sha256'), role='Admin', viewAs='')
        db.session.add(new_user)
        db.session.commit()


if __name__ == '__main__':
    socketio.run(app,host='0.0.0.0',port=5000)