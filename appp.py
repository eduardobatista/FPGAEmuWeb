from pathlib import Path
from flask import Flask
from flask_socketio import SocketIO

socketio = SocketIO()

def create_app(debug=False,mainpath=""):
    """Create an application."""
    app = Flask(__name__)
    app.debug = debug
    app.config['SECRET_KEY'] = b'_5#y2L"F4z\n\xec]/'
    app.config['MAX_CONTENT_LENGTH'] = 1000000 
    app.MAINPATH = mainpath

    from main import main as main_blueprint
    app.register_blueprint(main_blueprint)

    app.procs = {}
    app.fifowrite = {}

    socketio.init_app(app)
    return app


