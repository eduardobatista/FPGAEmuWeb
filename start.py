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
# problemfile = Path(MAINPATH,'work','marcos.r.grave@gmail.com','usertop.vhd')
# if problemfile.exists():
#     problemfile.chmod(0o444)

# WORKDIR = Path(MAINPATH) / "work"
WORKDIR = Path("/home/work")

app = create_app(debug=False,mainpath=MAINPATH,workdir=WORKDIR)

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