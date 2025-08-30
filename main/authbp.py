from flask import current_app, render_template, redirect, url_for, request, flash, session
from appp import db,celery
from werkzeug.security import generate_password_hash, check_password_hash
from . import auth
from flask_login import login_user, logout_user, current_user
from .models import User
from sqlalchemy.exc import OperationalError
import random
import string
import re
import requests
import json
import hashlib
import hmac
from datetime import datetime,timedelta
from sqlalchemy import Table,MetaData
# from .funcs import checkLogin,clearLoginAttempt,getLoginInfo

from .tasks import doLogin,doChangePass,doPassRecovery,MyTaskResp

# from celery.result import AsyncResult

def checkCeleryOn():
    insp = celery.control.inspect(timeout=0.1)   
    try: 
        celeryon = True if insp.ping() else False
    except BaseException as err:
        celeryon = False
        current_app.logger.error(err)
    return celeryon

def verifyCaptcha(captcha_response):
    secret = current_app.config['RECAPTCHA_SECRET_KEY']
    payload = {'response':captcha_response, 'secret':secret}
    response = requests.post("https://www.google.com/recaptcha/api/siteverify", payload)
    response_text = json.loads(response.text)
    return response_text['success']

@auth.route('/login')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.sendfiles'))
    return render_template('login.html')

@auth.route('/login', methods=['POST'])
def login_post():
    if current_user.is_authenticated:
        return redirect(url_for('main.sendfiles'))   

    # If CloudDb is not defined, use local database only:    
    if not current_app.clouddb:
        email = request.form.get('email').strip()
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()

        if not user:
            return "User not found in local database (cloud database is offline)."

        if not check_legacy_werkzeug_password(user.password, password):  
            return "Login failed! Please check your password and try again."

        login_user(user, remember=True)
        session["CurrentProject"] = ""
        current_app.logger.info(f"User {user.email} logged in successfully (local database).")
        return "Success"

    insp = celery.control.inspect(timeout=0.1)   
    try: 
        celeryon = True if insp.ping() else False
    except BaseException as err:
        celeryon = False
        current_app.logger.error(err) 

    if "logindata" in session.keys():

        if isinstance(session["logindata"][2],dict):
            task = MyTaskResp("SUCCESS", session["logindata"][2])           
        else: 
            task = doLogin.AsyncResult(session["logindata"][2])
 
        # print(task)     
        if task.status == "PENDING":
            return "Running"
        elif task.status == "SUCCESS": 
            if task.info['status'] == "NotFound":    
                del session["logindata"]             
                return "Login failed! Please check your login details and try again." 
            elif task.info['status'] == "Pass":
                user = User.query.filter_by(email=session["logindata"][0]).first()
                user.password = task.info['password']
                db.session.commit()
            elif task.info['status'] == "NewUser":
                new_user = User(email=task.info['email'], name=task.info['name'], password=task.info['password'], role=task.info['role'], viewAs=task.info['email'], 
                                        lastPassRecovery=None, topLevelEntity='usertop', testEntity='usertest')
                db.session.add(new_user)
                db.session.commit()
                user = User.query.filter_by(email=session["logindata"][0]).first()
            else:
                del session["logindata"]  
                return "Login failed."

        # print("=======")
        # stored = user.password.split("$",2) 
        # print(stored)
        # print(session["logindata"][1])
        # computed = hashlib.sha256((stored[1] + session["logindata"][1]).encode("utf-8")).hexdigest()
        # print(user.password)
        # print("=======")
        # print(check_legacy_werkzeug_password(session["logindata"][1],user.password))
        if not check_legacy_werkzeug_password(user.password,session["logindata"][1]): # check_password_hash(user.password, session["logindata"][1]):
            del session["logindata"]  
            return "Login failed! Please check your password and try again."

        del session["logindata"]                    
        login_user(user, remember=True)
        session["CurrentProject"] = ""
        current_app.logger.info(f"User {user.email} logged in successfully{' (cloudb only)' if not celeryon else ''}.")
        return "Success"


    email = request.form.get('email').strip()
    password = request.form.get('password')

    userexists = True if User.query.filter_by(email=email).first() else False

    if celeryon:
        task = doLogin.delay(userexists, email, password, current_app.config['CLOUDDBINFO'], email)
        session["logindata"] = (email,password,task.id)
        return "Starting"
    else:
        resp = doLogin(userexists, email, password, current_app.config['CLOUDDBINFO'], email)
        session["logindata"] = (email,password,resp)
        return "AlreadyDone"


def check_legacy_werkzeug_password(stored_hash,password):
    """Check password against legacy Werkzeug sha256 format and modern formats"""
    
    # First try modern Werkzeug format
    if stored_hash.startswith(('pbkdf2:', 'scrypt:', 'argon2:')):
        return check_password_hash(stored_hash, password)
    
    # Handle legacy Werkzeug sha256 format: sha256$salt$hash
    if stored_hash.startswith('sha256$'):
        try:
            method, salt, expected_hash = stored_hash.split('$', 2)
            # Old Werkzeug used HMAC with salt as key
            computed_hash = hmac.new(
                salt.encode('utf-8'), 
                password.encode('utf-8'), 
                hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(expected_hash, computed_hash)
        except ValueError:
            return False
    
    return False

@auth.route('/signup')
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('main.sendfiles'))
    return render_template('signup.html',recaptchaOn = current_app.config['RECAPTCHA_SITE_KEY'] if current_app.config['RECAPTCHA_SITE_KEY'] != "" else None)

@auth.route('/signup', methods=['POST'])
def signup_post():
    if current_user.is_authenticated:
        return redirect(url_for('main.sendfiles'))
    recaptchaOn = True if current_app.config['RECAPTCHA_SITE_KEY'] != "" else False
    if recaptchaOn:
        captcha_response = request.form['g-recaptcha-response']
        if not verifyCaptcha(captcha_response):
            flash(f"Recaptcha validation failed.")
            return redirect(url_for('auth.login'))
    email = request.form.get('email').strip().lower()
    if re.search(r"[^@a-zA-Z0-9_\.\-]", email):
        flash(f"Invalid email address: {email}.")
        return redirect(url_for('auth.login'))
    if len(email) > 40:
        flash(f"Email address is too long: {len(email)} characters. Max length is 40 characters.") 
        return redirect(url_for('auth.login'))
    name = request.form.get('name').strip()
    if len(name) > 50:
        flash(f"Name is too long: {len(name)} characters. Max length is 50 characters.")  
        return redirect(url_for('auth.login'))
    password = request.form.get('password')
    if len(password) > 30:
        flash(f"Password is too long: {len(password)} characters. Max length is 30 characters.")  
        return redirect(url_for('auth.login'))
    role = "Student"
    viewAs = ""
    topLevelEntity = "usertop"
    testEntity = "usertest"
    
    for ff in [email,name,password]:
        if ff == "":
            flash("At least one field is empty.")
            return redirect(url_for('auth.signup'))
        
    try:
        if User.query.count() >= 2000:
            flash('Too many users in the system. Please contact the administrator.')
            return redirect(url_for('auth.signup'))        
    except OperationalError as err:
        current_app.logger.error("Database does not exist.")
        flash("Database does not exist.") 
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=email).first() # if this returns a user, then the email already exists in database
    if user: # if a user is found, we want to redirect back to signup page so user can try again
        flash('Email address already exists.')
        return redirect(url_for('auth.signup'))
    elif current_app.clouddb is not None:
        try:             
            with current_app.clouddb.connect() as conncloud:     
                table1 = Table('user', MetaData(), autoload_with=current_app.clouddb)
                clouddata = conncloud.execute(table1.select().where(table1.c.email==email))
                if clouddata.first() is not None:
                    flash('Email address already exists (cloud).')
                    return redirect(url_for('auth.signup'))
                clouddata.close()
        except OperationalError as err:
            current_app.logger.error(err)
        except BaseException as err:
            current_app.logger.error(err)

    # create a new user with the form data. Hash the password so the plaintext version isn't saved.
    new_user = User(email=email, name=name, password=generate_password_hash(password, method='pbkdf2:sha256'), 
                    role=role, viewAs=viewAs, lastPassRecovery=None, topLevelEntity=topLevelEntity, testEntity=testEntity)

    # add the new user to the database
    db.session.add(new_user)
    db.session.commit()

    # add the new user to the cloud database
    if current_app.clouddb is not None:
        ndict = {'email': email, 'name': name, 'password': generate_password_hash(password, method='pbkdf2:sha256'), 
                        'role': role, 'viewAs': viewAs, 'lastPassRecovery': None, 'topLevelEntity': topLevelEntity, 'testEntity': testEntity}
        try:             
            with current_app.clouddb.connect() as conncloud:     
                table1 = Table('user', MetaData(), autoload_with=current_app.clouddb)
                clouddata = conncloud.execute(table1.select()).mappings().all()
                cloudusers = [row['email'] for row in clouddata]
                if email not in cloudusers:
                    conncloud.execute(table1.insert().values(ndict))
                    conncloud.commit()
                    conncloud.close()
                clouddata.close()
        except OperationalError as err:
            current_app.logger.error(err)
        except BaseException as err:
            current_app.logger.error(err)

    login_user(new_user, remember=True)
    session["CurrentProject"] = ""
    return redirect(url_for('main.sendfiles'))


@auth.route('/passrecoverystatus',methods=['POST'])
def passrecstatus(nocelery=False,resp=None):

    if ("passrecoverydata" in session.keys()) or nocelery:

        if nocelery:
            task = MyTaskResp("SUCCESS", resp)
        else:        
            task = doChangePass.AsyncResult(session["passrecoverydata"][2])

        # print(task.status)
        if task.status == "PENDING":
            return "Running"

        elif task.status == "SUCCESS":

            if 'passrecoverydata' in session:
                email = session['passrecoverydata'][0]
                randompass = session['passrecoverydata'][1]
                del session['passrecoverydata']
            else:
                return "Failed"

            if task.info['status'].startswith("NotAllowed10Min"):
                return "NotAllowed10Min"
            elif task.info['status'] == "Success": 
                current_app.yag.send(to=email,subject="FPGAEmuWeb: Password Recovery",
                         contents=f"Dear {email},\n\nYour FPGAEmuWeb password has been reset to \"{randompass}\".\n\nBest regards!")
                # return "New password generated and sent to your email address, please check your inbox and spam box as well. In case of problems, please contact the system administrator."
                current_app.logger.info(f"Successful password change for {email}{' (no celery)' if nocelery else ''}.")                
                return "Success"
            elif task.info['status'] == "NotFoundInCloud":
                return "NotFoundInCloud"
            elif task.info["status"] == "Error":
                current_app.logger.info(f"Pass change error: {task.info['message']}.")                
                return "Error"
            else:
                return "Failed"
        
        return "Failed"

    else:
        return "Failed"




@auth.route('/passrecovery',methods=['POST'])
def passrecovery():
    if current_app.yag is None:
        return "Password recovery not working in this machine. Please contact the system administrator."
    email = request.form.get('email').strip().lower()
    if email == "admin@fpgaemu":
        return "Can't recover password for this user."
    letters = string.ascii_lowercase
    randompass = ''.join(random.choice(letters) for i in range(6))
    randompasshash = generate_password_hash(randompass, method='pbkdf2:sha256')

    if not current_app.clouddb:
        user = User.query.filter_by(email=email).first()
        if user:
            if (user.lastPassRecovery is not None) and ( datetime.now() < (user.lastPassRecovery+timedelta(minutes=10)) ):
                    return "NotAllowed10Min"
            else:                
                user.password = randompasshash
                user.LastPassRecovery = datetime.now()
                db.session.commit()  
                current_app.yag.send(to=email,subject="FPGAEmuWeb: Password Recovery",
                            contents=f"Dear {email},\n\nYour FPGAEmuWeb password has been reset to \"{randompass}\".\n\nBest regards!")
                current_app.logger.info(f"Password recovered sucessfully for {email} (local database only).")
                return "LocalOnly"
        else:
            return "NotFoundLocal"

    if current_app.clouddb is not None:
        if checkCeleryOn():
            task = doPassRecovery.delay(email,randompasshash,current_app.config['CLOUDDBINFO'])
            session["passrecoverydata"] = (email,randompass,task.id)
            return "Starting"
        else:
            resp = doPassRecovery(email,randompasshash,current_app.config['CLOUDDBINFO'])
            session["passrecoverydata"] = (email,randompass)
            return passrecstatus(False,resp)


@auth.route('/changepassstatus', methods=['POST'])
def changepassstatus(nocelery=False,resp=None):

    if ("changepassdata" in session.keys()) or nocelery:

        if nocelery:
            task = MyTaskResp("SUCCESS", resp)
        else:        
            task = doChangePass.AsyncResult(session["changepassdata"][1])

        if task.status == "PENDING":
            return "Running"
        elif task.status == "SUCCESS":
            if 'changepassdata' in session:
                del session['changepassdata']
            if task.info['status'].startswith("PassUpdated"):
                current_app.logger.info(f"Successful password change for {current_user.email}{' (no celery)' if nocelery else ''}.")                
                return "Success"
            elif task.info["status"] == "Error":
                current_app.logger.info(f"Pass change error: {task.info['message']}.")                
                return "LocalOnly"
            else:
                return "Failed"


@auth.route('/changepass', methods=['POST'])
def changepass():    
    oldpass = request.form.get('oldpass')
    newpass = request.form.get('newpass')
    repeatnew = request.form.get('repeatnew')
    email = request.form.get('email')

    if newpass != repeatnew:
        flash("New passes do not match!")
        return redirect(url_for('adm.profile'))

    if newpass == "":
        flash("New pass is empty.")
        return redirect(url_for('adm.profile'))

    user = User.query.filter_by(email=email).first()
    
    if not check_legacy_werkzeug_password(user.password, oldpass):
        flash("Old password is not correct!")
        return redirect(url_for('adm.profile'))    

    user.password = generate_password_hash(newpass, method='pbkdf2:sha256')
    db.session.commit()

    if current_app.clouddb is None:

        current_app.logger.info(f"Successful password change for {email} (local database only).")
        return "Success"

    else:

        insp = celery.control.inspect(timeout=0.1)   
        try: 
            celeryon = True if insp.ping() else False
        except BaseException as err:
            celeryon = False
            current_app.logger.error(err)

        if celeryon:
            task = doChangePass.delay(email,generate_password_hash(newpass, method='pbkdf2:sha256'),user.name,user.role,current_app.config['CLOUDDBINFO'])
            session["changepassdata"] = (email,task.id)
            return "Starting"
        else:
            resp = doChangePass(email,generate_password_hash(newpass, method='pbkdf2:sha256'),user.name,user.role,current_app.config['CLOUDDBINFO'])
            return changepassstatus(True,resp)



@auth.route('/logout')
def logout():
    session["CurrentProject"] = ""
    logout_user()
    return redirect(url_for('auth.login'))



