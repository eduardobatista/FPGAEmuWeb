import os,logging
from pathlib import Path
from flask import Flask
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy # Database
from flask_login import LoginManager
from flask_migrate import Migrate

socketio = SocketIO()
db = SQLAlchemy()  # Database

def create_app(debug=False,mainpath=""):
    """Create an application."""
    app = Flask(__name__)
    app.debug = debug

    migrate = Migrate(app, db)

    if Path(mainpath,"seckey").exists():
        # print("Skey Found!")
        f = open(Path(mainpath,"seckey"),"rb")
        app.config['SECRET_KEY'] = f.read()
        f.close()
    else:
        skey = os.urandom(16)
        app.config['SECRET_KEY'] = skey
        f = open(Path(mainpath,"seckey"),"wb")
        f.write(skey)
        f.close()

    # app.config['SECRET_KEY'] = b'_5#y2L"F4z\n\xec]/'
    app.config['MAX_CONTENT_LENGTH'] = 1000000
    app.MAINPATH = mainpath
    
    # Database:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite' 
    db.init_app(app)
    
    # logging.basicConfig(filename=Path(mainpath,'activity.log'), level=logging.INFO)

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    from main.models import User

    @login_manager.user_loader
    def load_user(user_id):
        # since the user_id is just the primary key of our user table, use it in the query for the user
        return User.query.get(int(user_id))
    
    try:
        from yagmail import SMTP
        oauthfile = Path(mainpath,"oauth2_creds.json")
        if oauthfile.exists():
            app.yag = SMTP("fpgaemuweb@gmail.com", oauth2_file=oauthfile)
        else:
            app.yag = None
    except ImportError as e:
        app.yag = None

    from main import main as main_blueprint
    app.register_blueprint(main_blueprint)
    from main import auth as auth_blueprint
    app.register_blueprint(auth_blueprint)
    from main import adm as admin_blueprint
    app.register_blueprint(admin_blueprint)

    socketio.init_app(app)
    
    return app


