import subprocess,time,os,select,sys,socket
import threading
from pathlib import Path
from flask import Flask, Blueprint, url_for, request, session, request, render_template, Response, send_from_directory
from flask_socketio import SocketIO, send, emit, disconnect
from werkzeug.utils import secure_filename
from random import randrange
import re
from . import db
MAINPATH = os.path.dirname(os.path.abspath(__file__))

'''
    TODO:
        - Melhorar Timeouts: fazer inactivity para entrada e saída diferentes.
        - Botão "Delete All"
        x TIMEOUT sem interação do usuário.
        nn Matar outro processo do usuário na criação de um novo.
        x BUG!!!: Sem arquivo, parece estar compilando.
        x BUG!!!: Extração de ports na emulação dá erro se "end entity" ao invés de "end usertop".
        nn Controlar melhor processos de emulação.
        x Implementar Botões RENAME.
        - Implementar escolha para compilação.
        x Compilar backend quando servidor iniciar?
        - Limpar todos os "fpgatest" após compilação inicial?
        - Limpeza periódica dos diretórios de trabalho...
        x Dar msg de erro se tentar emular sem compilar.
        nn Desabilitar botões e chaves quando simulação não estiver rodando?
        x Após upload, dar refresh na página de uploads para aparecer lista ou puxar lista de arquivos.
        x Quando der "Save As" no Editor, abrir página com arquivo salvo aberto.
        - Disponibilizar template de usertop?
        x Proteger uploads de arquivos grandes.
        x Proteger salvamentos de arquivos grandes.
        - Melhorar gerenciamento de usuários.
        x Fazer About.
        - Manutenção de subdiretórios: apagar com certo tempo sem uso.
'''


main = Blueprint('main', __name__)