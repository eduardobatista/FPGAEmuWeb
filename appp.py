import os,logging
from logging.handlers import WatchedFileHandler
from pathlib import Path
from flask import Flask
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy # Database
from flask_login import LoginManager
from flask_migrate import Migrate
from sqlalchemy import create_engine


socketio = SocketIO(async_mode="gevent")
db = SQLAlchemy()  # Database
logger = logging.getLogger('FPGAEmuWeb')
logger.setLevel(logging.INFO)


def create_app(debug=False,mainpath="",workdir=""):
    """Create an application."""    
    app = Flask(__name__)
    app.debug = debug
    
    app.WORKDIR = workdir
    app.MAINPATH = mainpath

    global logger
    fhandler = WatchedFileHandler(Path(app.WORKDIR,'emulogs.log'))
    fhandler.setFormatter(logging.Formatter('%(asctime)s|%(levelname)s|%(message)s'))
    logger.handlers = [fhandler]
    if not debug:
        app.logger = logger

    migrate = Migrate(app, db)

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    seckeyfile = Path(app.WORKDIR,"seckey")
    if seckeyfile.exists():
        f = open(seckeyfile,"rb")
        app.config['SECRET_KEY'] = f.read()
        f.close()
    else:
        skey = os.urandom(16)
        app.config['SECRET_KEY'] = skey
        f = open(seckeyfile,"wb")
        f.write(skey)
        f.close()

    # app.config['SECRET_KEY'] = b'_5#y2L"F4z\n\xec]/'
    app.config['MAX_CONTENT_LENGTH'] = 1000000
    
    
    # Database:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///work/db.sqlite'   
    # app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite'
    db.init_app(app)

    # Cloud Database:
    app.config['CLOUDDBINFO'] = ''
    app.clouddb = None
    clouddbfile = app.WORKDIR / 'clouddb.conf';
    if clouddbfile.exists():
        try:
            with open(clouddbfile,'r') as cfile:
                clouddbconf = cfile.read();
                app.config['CLOUDDBINFO'] = clouddbconf
                app.clouddb = create_engine(clouddbconf,connect_args={'connect_timeout': 5})
        except Exception as ex:
            app.logger.error(f"Cloud DB Error - {str(ex)}")
            app.config['CLOUDDBINFO'] = ''
            app.clouddb = None
    
    # logging.basicConfig(filename=Path(mainpath,'activity.log'), level=logging.INFO)

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    from main.models import User

    @login_manager.user_loader
    def load_user(user_id):
        # since the user_id is just the primary key of our user table, use it in the query for the user
        return User.query.get(int(user_id))
    
    app.config['EMAILINFO'] = ""
    try:
        from yagmail import SMTP
        oauthfile = app.WORKDIR / "oauth2_creds.json"
        if oauthfile.exists():
            try:
                app.yag = SMTP("fpgaemuweb@gmail.com", oauth2_file=oauthfile)
                with open(oauthfile,"r") as ff:
                    app.config['EMAILINFO'] = ff.read()
            except Exception as ex:
                app.logger.error(f"Email Error - {str(ex)}")
                app.yag = None
        else:            
            app.yag = None
    except ImportError as e:
        app.logger.error(f"YagMail module missing.")
        app.yag = None

    from main import main as main_blueprint
    app.register_blueprint(main_blueprint)
    from main import auth as auth_blueprint
    app.register_blueprint(auth_blueprint)
    from main import adm as admin_blueprint
    app.register_blueprint(admin_blueprint)

    

    socketio.init_app(app)
    
    return app


