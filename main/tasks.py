from appp import celery

# from .models import User
from sqlalchemy.exc import OperationalError
from sqlalchemy import Table,MetaData
from sqlalchemy import create_engine

from datetime import datetime,timedelta
from pathlib import Path
import shutil

class MyTaskResp:
    def __init__(self,status,info):
        self.status = status
        self.info = info

@celery.task()
def doLogin(userexists,email,password,clouddburl,loginkey):

    retorno = {'status':"NotFound" + ("ButExists" if userexists else "")}

    if (clouddburl is not None) and (clouddburl != ''):
        try:
            clouddb = create_engine(clouddburl,connect_args={'connect_timeout': 5})
            with clouddb.connect() as conncloud:     
                table1 = Table('user', MetaData(), autoload=True, autoload_with=clouddb)
                clouddata = conncloud.execute(table1.select().where(table1.c.email==email))       
                usercloud = clouddata.first() 
                if usercloud:
                    if not userexists:
                        retorno = {'status': 'NewUser', 'email': email, 'name': usercloud.name, 'password': usercloud.password, 'role': usercloud.role}
                    else:
                        retorno = {'status': 'Pass', 'password': usercloud.password }                     
                clouddata.close()
        except OperationalError as err:
            return {'status':"Error", 'message':f"OperationalError: {err}." }
        except BaseException as err:
            return {'status':"Error", 'message':f"BaseException: {err}." }
    
    return retorno


@celery.task()
def doChangePass(email,newpass,name,role,clouddburl):

    ret = {"status":"Failed"}

    if (clouddburl is not None) and (clouddburl != ''):
        try:
            clouddb = create_engine(clouddburl,connect_args={'connect_timeout': 5})
            with clouddb.connect() as conncloud:     
                table1 = Table('user', MetaData(), autoload=True, autoload_with=clouddb)
                clouddata = conncloud.execute(table1.select().where(table1.c.email==email))
                usercloud = clouddata.first()                
                if usercloud is not None:
                    conncloud.execute(table1.update().where(table1.c.email==email).values(password=newpass))
                    ret = {"status":"PassUpdated"}
                else:
                    ndict = {'email': email, 'name': name, 'password': newpass, 
                        'role': role, 'viewAs': email, 'lastPassRecovery': None, 
                        'topLevelEntity': "usertop", 'testEntity': "usertest"}
                    conncloud.execute(table1.insert(), ndict)
                    ret = {"status":"PassUpdatedUserInserted"}
                clouddata.close()
        except OperationalError as err:
            ret = {"status": "Error", "message":f"OperationalError: {err}"}
        except BaseException as err:
            ret = {"status": "Error", "message":f"Exception: {err}"}

    # current_app.logger.info(f"Successful password change for {email}.")

    return ret


@celery.task()
def doPassRecovery(email,randompasshash,clouddburl):

    ret = {"status":"Failed"}

    try:
        clouddb = create_engine(clouddburl,connect_args={'connect_timeout': 5})
        with clouddb.connect() as conncloud:     
            table1 = Table('user', MetaData(), autoload=True, autoload_with=clouddb)
            clouddata = conncloud.execute(table1.select().where(table1.c.email==email))
            usercloud = clouddata.first()  
            if usercloud is not None:
                userincloud = True
                if (usercloud.lastPassRecovery is not None) and ( datetime.now() < (usercloud.lastPassRecovery+timedelta(minutes=10)) ):
                    ret = {"status":"NotAllowed10Min"}
                    # return "Password recovery allowed only after 10 minutes"
                else:
                    conncloud.execute(table1.update().where(table1.c.email==email).values(password=randompasshash,lastPassRecovery=datetime.now()))
                    ret = {"status":"Success"}
            else:
                ret = {"status":"NotFoundInCloud"}
            clouddata.close()
    except OperationalError as err:
        ret = {"status": "Error", "message":f"OperationalError: {err}"}
    except BaseException as err:
        ret = {"status": "Error", "message":f"Exception: {err}"}
    
    return ret


@celery.task()
def doWorkBackup(workdir,destdir):

    ret = {"status":"Failed"}

    try:        
        bckfile = Path(destdir,"workbackup.tar")        
        if bckfile.exists():
            bckfile.unlink()
        shutil.make_archive(destdir + "/workbackup", 'tar', Path(workdir))        
        ret = {"status":"Success"}
    except BaseException as err:
        ret = {"status": "Error", "message":f"EException: {err}"}
    return ret