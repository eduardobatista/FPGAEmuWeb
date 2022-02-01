from flask import current_app, render_template, redirect, url_for, request, flash
from appp import db
from werkzeug.security import generate_password_hash, check_password_hash
from . import auth
from flask_login import login_user, logout_user, current_user
from .models import User
from sqlalchemy.exc import OperationalError
from pathlib import Path
import random
import string
from datetime import datetime,timedelta
from sqlalchemy import Table,MetaData

@auth.route('/login')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.sendfiles'))
    return render_template('login.html')

@auth.route('/login', methods=['POST'])
def login_post():
    if current_user.is_authenticated:
        return redirect(url_for('main.sendfiles'))
    email = request.form.get('email').strip()
    password = request.form.get('password')
    # remember = True if request.form.get('remember') else False

    user = User.query.filter_by(email=email).first()

    # if (not user) and (current_app.clouddb is not None):
    if current_app.clouddb is not None:
        try:
            with current_app.clouddb.connect() as conncloud:     
                table1 = Table('user', MetaData(), autoload=True, autoload_with=current_app.clouddb)
                clouddata = conncloud.execute(table1.select())
                for row in clouddata:
                    if email == row['email']:
                        if not user:
                            new_user = User(email=email, name=row['name'], password=row['password'], role=row['role'], viewAs=email, 
                                        lastPassRecovery=None, topLevelEntity='usertop', testEntity='usertest')
                            db.session.add(new_user)
                            user = new_user
                        else:
                            user.password = row['password']
                        db.session.commit()                        
                clouddata.close()
        except OperationalError as err:
            current_app.logger.error(err)
        except BaseException as err:
            current_app.logger.error(err)

    # check if the user actually exists
    # take the user-supplied password, hash it, and compare it to the hashed password in the database
    if not user or not check_password_hash(user.password, password):
        flash('Please check your login details and try again.')
        return redirect(url_for('auth.login')) # if the user doesn't exist or password is wrong, reload the page

    # if the above check passes, then we know the user has the right credentials
    login_user(user, remember=True)
    current_app.logger.info(f"User {user.id}:{user.email}|{current_user.email} logged in.")
    if email != current_user.email:
        logout_user()
    return redirect(url_for('main.sendfiles'))

@auth.route('/signup')
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('main.sendfiles'))
    return render_template('signup.html')

@auth.route('/signup', methods=['POST'])
def signup_post():
    if current_user.is_authenticated:
        return redirect(url_for('main.sendfiles'))
    email = request.form.get('email').strip()
    name = request.form.get('name').strip()
    password = request.form.get('password')
    role = "Student"
    viewAs = ""
    topLevelEntity = "usertop"
    testEntity = "usertest"
    
    for ff in [email,name,password]:
        if ff == "":
            flash("At least one field is empty.")
            return redirect(url_for('auth.signup'))
        
    try:
        if User.query.count() >= 1000:
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
                table1 = Table('user', MetaData(), autoload=True, autoload_with=current_app.clouddb)
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
    new_user = User(email=email, name=name, password=generate_password_hash(password, method='sha256'), 
                    role=role, viewAs=viewAs, lastPassRecovery=None, topLevelEntity=topLevelEntity, testEntity=testEntity)

    # add the new user to the database
    db.session.add(new_user)
    db.session.commit()

    # add the new user to the cloud database
    if current_app.clouddb is not None:
        ndict = {'email': email, 'name': name, 'password': generate_password_hash(password, method='sha256'), 
                        'role': role, 'viewAs': viewAs, 'lastPassRecovery': None, 'topLevelEntity': topLevelEntity, 'testEntity': testEntity}
        try:             
            with current_app.clouddb.connect() as conncloud:     
                table1 = Table('user', MetaData(), autoload=True, autoload_with=current_app.clouddb)
                clouddata = conncloud.execute(table1.select())
                cloudusers = [row['email'] for row in clouddata]
                if email not in cloudusers:
                    conncloud.execute(table1.insert(), ndict)
                    conncloud.close()
                clouddata.close()
        except OperationalError as err:
            current_app.logger.error(err)
        except BaseException as err:
            current_app.logger.error(err)

    login_user(new_user, remember=True)
    return redirect(url_for('main.sendfiles'))

@auth.route('/passrecovery',methods=['POST'])
def passrecovery():
    if current_app.yag is None:
        return "Password recovery not working in this machine. Please contact fpgaemuweb@gmail.com."
    email = request.form.get('email').strip()
    if email == "admin@fpgaemu":
        return "Can't recover password for this user."
    letters = string.ascii_lowercase
    randompass = ''.join(random.choice(letters) for i in range(6))
    randompasshash = generate_password_hash(randompass, method='sha256')

    userincloud = False
    if current_app.clouddb is not None:
        try:
            with current_app.clouddb.connect() as conncloud:     
                table1 = Table('user', MetaData(), autoload=True, autoload_with=current_app.clouddb)
                clouddata = conncloud.execute(table1.select().where(table1.c.email==email))
                usercloud = clouddata.first()  
                if usercloud is not None:
                    userincloud = True
                    if (usercloud.lastPassRecovery is not None) and ( datetime.now() < (usercloud.lastPassRecovery+timedelta(minutes=10)) ):
                        return "Password recovery allowed only after 10 minutes"
                    conncloud.execute(table1.update().where(table1.c.email==email).values(password=randompasshash,lastPassRecovery=datetime.now()))
                clouddata.close()
        except OperationalError as err:
            current_app.logger.error(err)
        except BaseException as err:
            current_app.logger.error(err)

    user = User.query.filter_by(email=email).first() # if this returns a user, then the email already exists in database
    if (user == None): # if a user is found, we want to redirect back to signup page so user can try again
        if (not userincloud):
            return 'User not found!'
    else: 
        if (user.lastPassRecovery is not None) and ( datetime.now() < (user.lastPassRecovery+timedelta(minutes=10)) ):
            return "Password recovery allowed only after 10 minutes"
        user.lastPassRecovery = datetime.now()
        user.password = randompasshash    
        db.session.commit()    

    current_app.yag.send(to=email,subject="FPGAEmuWeb: Password Recovery",
                         contents=f"Dear {email},\n\nYour FPGAEmuWeb password has been reset to \"{randompass}\".\n\nBest regards!")
    return "New password generated and sent to your email address, please check your inbox and spam box as well. In case of problems, please contact fpgaemuweb@gmail.com."


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
    
    if not check_password_hash(user.password, oldpass):
        flash("Old password is not correct!")
        return redirect(url_for('adm.profile'))    

    user.password = generate_password_hash(newpass, method='sha256')
    db.session.commit()

    if current_app.clouddb is not None:
        try:
            with current_app.clouddb.connect() as conncloud:     
                table1 = Table('user', MetaData(), autoload=True, autoload_with=current_app.clouddb)
                clouddata = conncloud.execute(table1.select().where(table1.c.email==email))
                usercloud = clouddata.first()                
                if usercloud is not None:
                    conncloud.execute(table1.update().where(table1.c.email==email).values(password=user.password))
                else:
                    ndict = {'email': email, 'name': user.name, 'password': user.password, 
                        'role': user.role, 'viewAs': user.viewAs, 'lastPassRecovery': None, 
                        'topLevelEntity': user.topLevelEntity, 'testEntity': user.testEntity}
                    conncloud.execute(table1.insert(), ndict)
                clouddata.close()
        except OperationalError as err:
            current_app.logger.error(err)
        except BaseException as err:
            current_app.logger.error(err)

    current_app.logger.info(f"Successful password chage for {email}.")

    flash("Password changed successfully.")    
    return redirect(url_for('adm.profile'))


@auth.route('/logout')
def logout():
    # print(current_user.email)
    # return "Uepa!"
    logout_user()
    # flash('User logged out.')
    return redirect(url_for('auth.login'))



