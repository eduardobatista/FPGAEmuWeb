from flask import current_app, render_template, redirect, url_for, request, flash
from werkzeug.security import generate_password_hash, check_password_hash
from .models import User
from . import adm
from appp import db
from flask_login import login_required, current_user
from sqlalchemy import Table,MetaData
from pathlib import Path
from sqlalchemy import create_engine,func,asc
import psutil
import json

@adm.route('/profile')
@login_required
def profile():    # return f'User {current_user.name} is logged in ({current_user.role} - {current_user.email}).'
    # TODO: Sort list and filter by student
    userlist = [row.email for row in User.query.filter_by(role='Student').order_by(asc(func.lower(User.email))).all()]
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


@adm.route('/serverprocs', methods=['POST'])
@login_required
def serverProcs():
    if (current_user.role == "Admin"):
        ret = ""
        for pp in psutil.pids():
            ppp = psutil.Process(pp)
            ret = ret + f"{ppp.name()} - {ppp.status()} - {ppp.cpu_percent(interval=0.1)}<br>"
        return ret
    else:
        return "Only for admins." 

@adm.route('/checkstdout', methods=['POST'])
@login_required
def checkStdOut():
    if (current_user.role == "Admin"):
        file = Path("/home","stdout.log")
        if file.exists():
            with open(file,"r") as ff:
                return ff.read().replace('\n','\n<br>') 
        else:
            return "File not found."
    else:
        return "Only for admins." 

@adm.route('/checkstderr', methods=['POST'])
@login_required
def checkStdErr():
    if (current_user.role == "Admin"):
        file = Path("/home","stderr.log")
        if file.exists():
            with open(file,"r") as ff:
                return ff.read().replace('\n','\n<br>') 
        else:
            return "File not found."
    else:
        return "Only for admins." 

@adm.route('/checklogs', methods=['POST'])
@login_required
def checkLogs():
    if (current_user.role == "Admin"):
        file = Path(current_app.MAINPATH,'work',"emulogs.log")
        if file.exists():
            with open(file,"r") as ff:
                return ff.read().replace('\n','\n<br>') 
        else:
            return "File not found."
    else:
        return "Only for admins." 

@adm.route('/deleteemulogs', methods=['POST'])
@login_required
def deleteEmuLogs():
    if (current_user.role == "Admin"):
        file = Path(current_app.MAINPATH,'work',"emulogs.log")
        if file.exists():
            file.unlink()
            return "File deleted." 
        else:
            return "File not found."
    else:
        return "Only for admins."


@adm.route('/admin')
@login_required
def admin():
    if current_user.role != "Admin":
        return redirect(url_for('main.sendfiles'))
    userlist = User.query
    # return f'User {current_user.name} is logged in ({current_user.role} - {current_user.email}).'
    return render_template('admin.html',userlist=userlist,clouddbinfo=current_app.config['CLOUDDBINFO'],emailinfo=current_app.config['EMAILINFO'])

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

@adm.route('/saveclouddbinfo', methods=['POST'])
@login_required
def savecloudinfo():
    if current_user.role != "Admin":
        return redirect(url_for('main.sendfiles'))
    info = request.form.get('info')
    workdir = Path(current_app.MAINPATH,'work')
    try:
        with open(workdir / "clouddb.conf","w") as ff:
            ff.write(info)
            current_app.config['CLOUDDBINFO'] = info
            current_app.clouddb = create_engine(info, connect_args={'connect_timeout': 5})
    except Exception as e:
        return str(e)
        current_app.config['CLOUDDBINFO'] = ''
        current_app.clouddb = None
    return "Done!"

@adm.route('/saveemailinfo', methods=['POST'])
@login_required
def saveemailinfo():
    if current_user.role != "Admin":
        return redirect(url_for('main.sendfiles'))
    info = request.form.get('info')
    workdir = Path(current_app.MAINPATH,'work')
    oauthfile = workdir / "oauth2_creds.json"
    with open(oauthfile,"w") as ff:
        ff.write(info)
        current_app.config['EMAILINFO'] = info
    try:        
        from yagmail import SMTP  
        data = json.loads(info)        
        current_app.yag = SMTP(data["email_address"], oauth2_file=oauthfile)
    except ImportError as e:       
        current_app.yag = None
        return "YagMail module missing."
    except Exception as e:
        return str(e)
    return "Done!"
    

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