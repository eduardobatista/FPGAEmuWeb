# from . import create_app, socketio
import subprocess,os
from pathlib import Path
from appp import create_app, socketio, db
from main.models import User
import logging
from sqlalchemy.exc import OperationalError
from werkzeug.security import generate_password_hash
from datetime import datetime
import signal
import sys

'''
    TODO:
        - Melhorar Logging
        - Templates.

        - Compilar só arquivos que importam (i.e., pegar usertop e components lá declarados)
        - Melhorar Timeouts: fazer inactivity para entrada e saída diferentes.
        nn Matar outro processo do usuário na criação de um novo.
        nn Controlar melhor processos de emulação.
        - Implementar escolha para compilação.
        - Limpar todos os "fpgatest" após compilação inicial?
        - Limpeza periódica dos diretórios de trabalho...
        nn Desabilitar botões e chaves quando simulação não estiver rodando?
        - Disponibilizar template de usertop?
        - Melhorar gerenciamento de usuários.
        - Manutenção de subdiretórios: apagar com certo tempo sem uso.
'''


def sigterm_handler(_signo, _stack_frame):
    try:
        crashfile = Path(MAINPATH,'work') / "crashes.log"
        with open(crashfile,"a") as cfile:
            cfile.write(f'Crashed at {datetime.now().strftime("%m/%d/%Y, %H:%M:%S")}.\n')
            stderrf = Path("/home","stderr.log")
            if stderrf.exists():
                with open(stderrf,"r") as ff:
                    cfile.write(ff.read())
            cfile.write("\n")
    except Exception as es:
        print(es)
    sys.exit(0)


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

app = create_app(debug=False,mainpath=MAINPATH)

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
        
# log = logging.getLogger('werkzeug')
# log.setLevel(logging.ERROR)
# gunicorn_error_logger = logging.getLogger('gunicorn.error')
# app.logger.handlers.extend(gunicorn_error_logger.handlers)
# app.logger.debug('this will show in the log')
# app.logger.info('Teeste!')
# app.logger.error('teste')
# app.logger.removeHandler(gunicorn_error_logger)
# app.logger.addHandler(logging.FileHandler('/home/dudu/error.log'))
# app.logger.setLevel(logging.INFO)
# fhandler = logging.FileHandler(Path(MAINPATH,'work','emulogs.log'))
# fhandler.setFormatter(logging.Formatter('%(asctime)s|%(levelname)s|%(message)s'))
# app.logger.handlers = [fhandler]

# logging.basicConfig(filename='/home/dudu/error.log',level=logging.INFO)

if __name__ == '__main__':
    signal.signal(signal.SIGTERM, sigterm_handler)
    signal.signal(signal.SIGABRT, sigterm_handler)
    signal.signal(signal.SIGINT, sigterm_handler)
    signal.signal(signal.SIGQUIT, sigterm_handler)
    socketio.run(app,host='0.0.0.0',port=5000)
    sigterm_handler(None, None)