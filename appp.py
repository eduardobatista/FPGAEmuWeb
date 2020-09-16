from pathlib import Path
from flask import Flask
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy # Database

socketio = SocketIO()
db = SQLAlchemy() # Database

def create_app(debug=False,mainpath=""):
    """Create an application."""
    app = Flask(__name__)
    app.debug = debug
    app.config['SECRET_KEY'] = b'_5#y2L"F4z\n\xec]/'
    app.config['MAX_CONTENT_LENGTH'] = 1000000 
    app.MAINPATH = mainpath
    
    # Database:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite' 
    db.init_app(app)

    from main import main as main_blueprint
    app.register_blueprint(main_blueprint)
    from main import auth as auth_blueprint
    app.register_blueprint(auth_blueprint)

    socketio.init_app(app)
    return app


