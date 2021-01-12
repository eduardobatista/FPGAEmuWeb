from flask import current_app, render_template, redirect, url_for, request, flash
from werkzeug.security import generate_password_hash, check_password_hash
from .models import User
from . import adm
from appp import db
from flask_login import login_required, current_user

@adm.route('/profile')
@login_required
def profile():
    # return f'User {current_user.name} is logged in ({current_user.role} - {current_user.email}).'
    print(current_user.viewAs)
    userlist = User.query
    return render_template('profile.html',userlist=userlist)

@adm.route('/setViewAs', methods=['POST'])
@login_required
def setViewAs():
    if (current_user.role == "Student"):
        return redirect(url_for('main.sendfiles'))
    email = request.form.get('viewAsSelect')
    current_user.viewAs = email
    db.session.commit()
    return redirect(url_for('main.sendfiles')) 


@adm.route('/admin')
@login_required
def admin():
    if current_user.role != "Admin":
        return redirect(url_for('main.sendfiles'))
    userlist = User.query
    # return f'User {current_user.name} is logged in ({current_user.role} - {current_user.email}).'
    return render_template('admin.html',userlist=userlist)

@adm.route('/deleteuser', methods=['POST']) 
@login_required
def deleteuser():
    if current_user.role != "Admin":
        return redirect(url_for('main.sendfiles'))


@adm.route('/changerole', methods=['POST']) 
@login_required
def changerole():
    if current_user.role != "Admin":
        return "Error! Not an Admin."
    email = request.form.get('email')
    newrole = request.form.get('newrole')
    user = User.query.filter_by(email=email).first()
    user.role = newrole
    db.session.commit()
    return "Role changed!"

@adm.route('/changepass', methods=['POST'])
def changepass():
    oldpass = request.form.get('oldpass')
    newpass = request.form.get('newpass')
    repeatnew = request.form.get('repeatnew')
    email = request.form.get('email')

    user = User.query.filter_by(email=email).first()

    if newpass != repeatnew:
        flash("New passes do not match!")
        return redirect(url_for('adm.profile'))
    
    if not check_password_hash(user.password, oldpass):
        flash("Old password is not correct!")
        return redirect(url_for('adm.profile'))

    if newpass == "":
        flash("New pass is empty.")
        return redirect(url_for('adm.profile'))

    user.password = generate_password_hash(newpass, method='sha256')
    db.session.commit()
    flash("Password changed successfully.")    
    return redirect(url_for('adm.profile'))