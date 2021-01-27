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

@auth.route('/login')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.sendfiles'))
    return render_template('login.html')

@auth.route('/login', methods=['POST'])
def login_post():
    if current_user.is_authenticated:
        return redirect(url_for('main.sendfiles'))
    email = request.form.get('email')
    password = request.form.get('password')
    # remember = True if request.form.get('remember') else False

    user = User.query.filter_by(email=email).first()

    # check if the user actually exists
    # take the user-supplied password, hash it, and compare it to the hashed password in the database
    if not user or not check_password_hash(user.password, password):
        flash('Please check your login details and try again.')
        return redirect(url_for('auth.login')) # if the user doesn't exist or password is wrong, reload the page

    # if the above check passes, then we know the user has the right credentials
    login_user(user, remember=True)
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
        if User.query.count() >= 300:
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

    # create a new user with the form data. Hash the password so the plaintext version isn't saved.
    new_user = User(email=email, name=name, password=generate_password_hash(password, method='sha256'), 
                    role=role, viewAs=viewAs, lastPassRecovery=None, topLevelEntity=topLevelEntity, testEntity=testEntity)

    # add the new user to the database
    db.session.add(new_user)
    db.session.commit()  

    login_user(new_user, remember=True)
    return redirect(url_for('main.sendfiles'))

@auth.route('/passrecovery',methods=['POST'])
def passrecovery():
    if current_app.yag is None:
        return "Password recovery not working in this machine. Please contact fpgaemuweb@gmail.com."
    email = request.form.get('email').strip()
    if email == "admin@fpgaemu":
        return "Can't recover password for this user."
    user = User.query.filter_by(email=email).first() # if this returns a user, then the email already exists in database
    if user == None: # if a user is found, we want to redirect back to signup page so user can try again
        return 'User not found!'
    if (user.lastPassRecovery is not None) and ( datetime.now() < (user.lastPassRecovery+timedelta(minutes=10)) ):
        return "Password recovery allowed only after 10 minutes"
    user.lastPassRecovery = datetime.now()
    letters = string.ascii_lowercase
    randompass = ''.join(random.choice(letters) for i in range(6))
    user.password = generate_password_hash(randompass, method='sha256')
    
    db.session.commit()
    current_app.yag.send(to=email,subject="FPGAEmuWeb: Password Recovery",
                         contents=f"Dear {user.name},\n\nYour FPGAEmuWeb password has been reset to \"{randompass}\".\n\nBest regards!")
    return "New password generated and sent to your email address, please check your inbox and spam box as well. In case of problems, please contact fpgaemuweb@gmail.com."


@auth.route('/logout')
def logout():
    logout_user()
    # flash('User logged out.')
    return redirect(url_for('auth.login'))



