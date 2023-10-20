from flask import current_app, render_template, redirect, url_for, request, flash,send_from_directory, session
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
from datetime import datetime
import subprocess
from sqlalchemy.exc import OperationalError
import shutil

from .tasks import doWorkBackup
from celery.result import AsyncResult

from .authbp import checkCeleryOn

@adm.route('/profile')
@login_required
def profile():    # return f'User {current_user.name} is logged in ({current_user.role} - {current_user.email}).'
    userlist = [arq.name for arq in current_app.WORKDIR.iterdir() if arq.is_dir()]
    userlist.remove(current_user.email)
    userlist.sort()
    # userlist = [row.email for row in User.query.filter_by(role='Student').order_by(asc(func.lower(User.email))).all()]
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
    session["CurrentProject"] = ""
    return redirect(url_for('main.sendfiles')) 

@adm.route('/killproc/<int:pid>', methods=['GET'])
@login_required
def killProc(pid):
    if (current_user.role == "Admin"):
        try:
            psutil.Process(pid).kill()
        except Exception as err:
            return str(err)
        return "Done."
    else:
        return "User not allowed."

@adm.route('/serverprocs', methods=['POST'])
@login_required
def serverProcs():
    if (current_user.role == "Admin"):
        ret = """
            <table class='table is-striped'>
            <thead>
            <tr><th>pid</th><th>Name</th><th>Status</th><th>CPU Use</th><th>Memory Usage</th><th>Memory RSS</th><th>Start Time</th>
            <th>Action</th>
            </thead>
            <tbody>
        """
        for pp in psutil.pids():
            try:
                ppp = psutil.Process(pp)
                ctime = datetime.fromtimestamp(ppp.create_time()).strftime("%Y-%m-%d %H:%M:%S")
                ret = ret + f"<tr><td>{pp}</td><td>{ppp.name()}</td><td>{ppp.status()}</td><td>{ppp.cpu_percent(interval=0.1)}</td>"
                ret = ret + f"<td>{ppp.memory_percent():.3f}%</td><td>{ppp.memory_info()[0]/(2**20):.2f} MB</td><td>{ctime}</td>\n"
                ret = ret + f"<td><button class='button is-danger is-small' onclick='killProc({pp});' style='height: 16px;'><i class='far fa-trash-alt'></button></td></tr>\n"
            except psutil.Error as err:
                current_app.logger.error(f"Psutil Error: {str(err)}.")
            except Exception as ex:
                current_app.logger.error(f"Psutil Error: {str(ex)}.")
        return ret + "</tbody></table>"
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
        file = Path(current_app.WORKDIR,"emulogs.log")
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
        file = Path(current_app.WORKDIR,"emulogs.log")
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
    recaptchafile = current_app.WORKDIR / "recaptcha.json"
    recapdata = ""
    if recaptchafile.exists():
        with open(recaptchafile,"r") as ff:
            recapdata = ff.read()
    return render_template('admin.html',clouddbinfo=current_app.config['CLOUDDBINFO'],emailinfo=current_app.config['EMAILINFO'],recaptchainfo=recapdata)


@adm.route('/getuserlist', methods=['POST'])
@login_required
def getuserlist():
    if current_user.role != "Admin":
        return redirect(url_for('main.sendfiles'))

    listtype = request.form.get('type')

    rendereduserlist = "Empty user list."
    if current_app.clouddb and (not listtype):        
        try:
            with current_app.clouddb.connect() as conncloud:     
                table1 = Table('user', MetaData(), autoload_with=current_app.clouddb)
                userlist = conncloud.execute(table1.select().order_by(table1.c.role,table1.c.name))
                rendereduserlist = render_template('userlist.html',userlist=userlist)
                userlist.close()
        except OperationalError as err:
            current_app.logger.error(err)
        except BaseException as err:
            current_app.logger.error(err)
    else:
        userlist = User.query
        rendereduserlist = render_template('userlist.html',userlist=userlist)
    
    return rendereduserlist


@adm.route('/clouddbinfo')
@login_required
def cloudinfo():
    if current_user.role != "Admin":
        return redirect(url_for('main.sendfiles'))
    if current_app.clouddb:
        try: 
            with current_app.clouddb.connect() as conncloud:  
                table1 = Table('user', MetaData(), autoload_with=current_app.clouddb)
                clouddata = conncloud.execute(table1.select())   
                userscloud = [row[0] for row in clouddata.columns('email')]
                print(userscloud)
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
    try:
        with open(current_app.WORKDIR / "clouddb.conf","w") as ff:
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
    oauthfile = current_app.WORKDIR / "oauth2_creds.json"
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

@adm.route('/saverecaptchainfo', methods=['POST'])
@login_required
def saverecaptchainfo():
    if current_user.role != "Admin":
        return redirect(url_for('main.sendfiles'))
    info = request.form.get('info')
    recaptchafile = current_app.WORKDIR / "recaptcha.json"
    with open(recaptchafile,"w") as ff:
        ff.write(info)
    try:
        data = json.loads(info) 
        current_app.config["RECAPTCHA_SITE_KEY"] = data['RECAPTCHA_SITE_KEY']
        current_app.config["RECAPTCHA_SECRET_KEY"] = data['RECAPTCHA_SECRET_KEY']
    except Exception as e:
        current_app.config["RECAPTCHA_SITE_KEY"] = "";
        current_app.config["RECAPTCHA_SECRET_KEY"] = "";
        return str(e)
    return "Done!"
    

@adm.route('/deleteuser', methods=['POST']) 
@login_required
def deleteuser():
    if current_user.role != "Admin":
        return redirect(url_for('main.sendfiles'))
    email = request.form.get('email')
    try:
        usertodelete = User.query.filter_by(email=email)
        if usertodelete:
            usertodelete.delete()
            db.session.commit()
        # TODO: Delete user folder !?

        if current_app.clouddb is not None:
            try:
                with current_app.clouddb.connect() as conncloud:     
                    table1 = Table('user', MetaData(), autoload_with=current_app.clouddb)
                    clouddata = conncloud.execute(table1.delete().where(table1.c.email==email))
                    conncloud.commit()
                    clouddata.close()
            except OperationalError as err:
                current_app.logger.error(err)
            except BaseException as err:
                current_app.logger.error(err)

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

    # Recording in local DB:
    user = User.query.filter_by(email=email).first()
    if user is not None:
        user.role = newrole
        db.session.commit()

    # Recording at Cloud DB
    if current_app.clouddb is not None:
        try:
            with current_app.clouddb.connect() as conncloud:     
                table1 = Table('user', MetaData(), autoload_with=current_app.clouddb)
                clouddata = conncloud.execute(table1.select().where(table1.c.email==email))
                usercloud = clouddata.first()
                if usercloud is not None:
                    conncloud.execute(table1.update().where(table1.c.email==email).values(role=newrole))
                else:
                    if user is not None:
                        ndict = {'email': email, 'name': user.name, 'password': user.password, 
                            'role': user.role, 'viewAs': user.viewAs, 'lastPassRecovery': None, 
                            'topLevelEntity': user.topLevelEntity, 'testEntity': user.testEntity}
                        conncloud.execute(table1.insert(), ndict)
                clouddata.close()
        except OperationalError as err:
            current_app.logger.error(err)
        except BaseException as err:
            current_app.logger.error(err)

    return "Role changed!"


@adm.route('/workbackup')
@login_required
def workbackup():    
    if current_user.role != "Admin":
        return "Error! Not an Admin."

    if checkCeleryOn():
        tempdir = Path(current_app.MAINPATH,"temp")
        if not tempdir.exists():
            tempdir.mkdir(parents=True,exist_ok=True)        
        task = doWorkBackup.delay(str(Path(current_app.MAINPATH,"work")),str(tempdir))        
        session["workbackup"] = task.id
        return "Starting"
    else:
        bckfile = Path(current_app.MAINPATH,"workbackup.tar")
        if bckfile.exists():
            bckfile.unlink()
        try: 
            shutil.make_archive("workbackup", 'tar', Path(current_app.MAINPATH,"work"))        
        except BaseException as ex:
            return (str(ex))
        return send_from_directory(current_app.MAINPATH, 'workbackup.tar', as_attachment=True, max_age=0)


@adm.route('/workbackupstatus')
def workbackupstatus(nocelery=False,resp=None):
    if ("workbackup" in session.keys()):       
        task = doWorkBackup.AsyncResult(session["workbackup"])
        if task.status == "PENDING":
            return "Running"
        elif task.status == "SUCCESS": 
            if 'workbackup' in session:
                del session['workbackup']
            if task.info['status'].startswith("Success"):
                current_app.logger.info(f"Workdir backup finished successfully.")                
                return "Success"                
            elif task.info["status"] == "Error":
                current_app.logger.info(f"Workdir backup error: {task.info['message']}.")                
                return "Failed = " + f"Workdir backup error: {task.info['message']}."
            else:
                return "Failed"
    else:
        return "Workbackup not running."


@adm.route('/workbackupdownload')
def workbackupdownload(nocelery=False,resp=None):
    if current_user.role != "Admin":
        return "Error! Not an Admin."
    temppath = Path(current_app.MAINPATH,"temp")
    return send_from_directory(temppath, "workbackup.tar", as_attachment=True, max_age=0)


@adm.route('/workcleanup')
@login_required
def workcleanup():    
    if current_user.role != "Admin":
        return "Error! Not an Admin."
    cleanuplogs = ["Starting cleanup..."]
    workdir = Path(current_app.WORKDIR)
    try:
        for dd in workdir.iterdir():
            if dd.is_dir() and (dd != workdir):
                is_empty = not any(dd.iterdir())
                if is_empty:
                    dd.rmdir()
                    cleanuplogs.append(f"Directory removed: {dd}.")
                else:
                    for ff in dd.rglob("*"):
                        if (not ff.is_dir()) and (ff.suffix not in [".vhd",".map"]) and (ff.name != ".config"):
                            ff.unlink()
                            cleanuplogs.append(f"File removed: {ff}.")
    except BaseException as ex:
        cleanuplogs.append(str(ex))
    cleanuplogs.append("Cleanup finished successfully.")
    return "<br>".join(cleanuplogs)
    
    

    