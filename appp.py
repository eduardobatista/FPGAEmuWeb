import os
import logging
from logging.handlers import WatchedFileHandler
from pathlib import Path
from flask import Flask
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy # Database
from flask_login import LoginManager
from sqlalchemy import create_engine
from celery import Celery

socketio = SocketIO(async_mode="gevent",cors_allowed_origins='*')
# socketio = SocketIO(cors_allowed_origins='*')
db = SQLAlchemy()  # Database
logger = logging.getLogger('FPGAEmuWeb')
logger.setLevel(logging.INFO)

celery = Celery('main.tasks', include=["main.tasks"])
celery.conf.broker_url = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
celery.conf.result_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/0")
# celery.autodiscover_tasks()


def create_app(debug=False,mainpath="",workdir="",recaptchakeys=None):
    """Create an application."""    
    app = Flask(__name__)
    app.debug = debug
    
    app.WORKDIR = workdir
    app.MAINPATH = mainpath
    app.TEMPDIR = Path(mainpath) / "temp"
    if not app.TEMPDIR.exists():
        app.TEMPDIR.mkdir()

    global logger
    fhandler = WatchedFileHandler(Path(app.WORKDIR,'emulogs.log'))
    fhandler.setFormatter(logging.Formatter('%(asctime)s|%(levelname)s|%(message)s'))
    logger.handlers = [fhandler]
    if not debug:
        app.logger = logger

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "pool_size": 10,
        "connect_args": {"timeout": 5}
    }

    app.config['CELERY_BROKER_URL'] = celery.conf.broker_url
    app.config['CELERY_RESULT_BACKEND'] = celery.conf.result_backend

    # If db.sqlite does not exist, erase seckey:
    localdbfile = Path(workdir,"dbb.sqlite")
    localdburl = 'sqlite:///' + str(localdbfile) # WARNING: do not put local database in other place without changing the seckey.
    seckeyfile = Path(workdir,"seckeyb")  # WARNING: do not put seckey in other place.
    
    if not localdbfile.exists():
        if seckeyfile.exists():
            seckeyfile.unlink()

    if seckeyfile.exists():
        f = open(seckeyfile,"rb")
        app.config['SECRET_KEY'] = f.read()
        f.close()
    else:
        logger.info("SECKEY does not exist, creating new...")
        skey = os.urandom(16)
        app.config['SECRET_KEY'] = skey
        f = open(seckeyfile,"wb")
        f.write(skey)
        f.close()

    app.config['MAX_CONTENT_LENGTH'] = 1000000
        
    # Database: 
    app.config['SQLALCHEMY_DATABASE_URI'] = localdburl
    db.init_app(app)

    # Cloud Database:
    app.config['CLOUDDBINFO'] = ''
    app.clouddb = None
    clouddbfile =  Path(workdir,'clouddb.conf')
    if clouddbfile.exists():
        try:
            with open(clouddbfile,'r') as cfile:
                clouddbconf = cfile.read()
                app.config['CLOUDDBINFO'] = clouddbconf
                app.clouddb = create_engine(clouddbconf,connect_args={'connect_timeout': 10})
        except Exception as ex:
            app.logger.error(f"Cloud DB Error - {str(ex)}")
            app.config['CLOUDDBINFO'] = ''
            app.clouddb = None
    
    app.config['RECAPTCHA_SITE_KEY'] = recaptchakeys['RECAPTCHA_SITE_KEY']
    app.config['RECAPTCHA_SECRET_KEY'] = recaptchakeys['RECAPTCHA_SECRET_KEY']
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
        app.logger.error(f"YagMail module missing. {e}")
        app.yag = None

    from main import main as main_blueprint
    app.register_blueprint(main_blueprint)
    from main import auth as auth_blueprint
    app.register_blueprint(auth_blueprint)
    from main import adm as admin_blueprint
    app.register_blueprint(admin_blueprint)    

    socketio.init_app(app)
    
    return app


