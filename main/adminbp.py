from flask import current_app, render_template, redirect, url_for, request, flash
from werkzeug.security import generate_password_hash, check_password_hash
from .models import User
from . import adm
from appp import db
from flask_login import login_required, current_user
from sqlalchemy import Table,MetaData

@adm.route('/profile')
@login_required
def profile():    # return f'User {current_user.name} is logged in ({current_user.role} - {current_user.email}).'
    # TODO: Sort list and filter by student
    userlist = sorted([row.email for row in User.query.filter_by(role='Student')])
    userlist.insert(0,current_user.email)    
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

@adm.route('/clouddbinfo')
@login_required
def cloudinfo():
    if current_user.role != "Admin":
        return redirect(url_for('main.sendfiles'))
    if current_app.clouddb:
        try: 
            with current_app.clouddb.connect() as conncloud:      
                table1 = Table('user', MetaData() , autoload=True, autoload_with=current_app.clouddb)
                clouddata = conncloud.execute(table1.select())
                userscloud = [row['email'] for row in clouddata]
                ret = f"{len(userscloud)} users are registered in the CloudDb.<br>"
                ret += f"User list is: {userscloud}"
                conncloud.close()
                return ret
        except BaseException as err:
            return f"Could not reach the cloud database.<br>{str(err)}"
    else:
        return "CloudDb not set for this app (clouddb.conf is probably missing)."

@adm.route('/deleteuser', methods=['POST']) 
@login_required
def deleteuser():
    if current_user.role != "Admin":
        return redirect(url_for('main.sendfiles'))
    email = request.form.get('email')
    try:
        User.query.filter_by(email=email).delete()
        db.session.commit()
        # TODO: Delete user folder !?
        return f"User {email} deleted successfully."
    except Exception as e:
        current_app.logger.error(f"Error deleting user {email}: {str(e)}.")
        return f"Error deleteing user {email}."   


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