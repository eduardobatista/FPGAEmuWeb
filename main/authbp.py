from flask import current_app,render_template, redirect, url_for, request, flash
from appp import db
from werkzeug.security import generate_password_hash, check_password_hash
from . import auth
from flask_login import login_user, logout_user
from .models import User
from sqlalchemy.exc import OperationalError

@auth.route('/login')
def login():
    return render_template('login2.html')

@auth.route('/login', methods=['POST'])
def login_post():
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
    return render_template('signup2.html')

@auth.route('/signup', methods=['POST'])
def signup_post():
    email = request.form.get('email').strip()
    name = request.form.get('name').strip()
    password = request.form.get('password')

    for ff in [email,name,password]:
        if ff == "":
            flash("At least one field is empty.")
            return redirect(url_for('auth.signup'))
        

    try:
        user = User.query.filter_by(email=email).first() # if this returns a user, then the email already exists in database
    except OperationalError:
        current_app.logger.error("Database does not exist.")
        flash("Database does not exist.") 
        return redirect(url_for('auth.login'))

    if user: # if a user is found, we want to redirect back to signup page so user can try again
        flash('Email address already exists.')
        return redirect(url_for('auth.signup'))

    # create a new user with the form data. Hash the password so the plaintext version isn't saved.
    new_user = User(email=email, name=name, password=generate_password_hash(password, method='sha256'))

    # add the new user to the database
    db.session.add(new_user)
    db.session.commit()  

    login_user(new_user, remember=True)
    return redirect(url_for('main.sendfiles'))

@auth.route('/logout')
def logout():
    logout_user()
    # flash('User logged out.')
    return redirect(url_for('auth.login'))


