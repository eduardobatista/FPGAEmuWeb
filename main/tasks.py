from appp import huey

from sqlalchemy.exc import OperationalError
from sqlalchemy import Table,MetaData
from sqlalchemy import create_engine

from datetime import datetime,timedelta
from pathlib import Path
import shutil

@huey.task()
def doLogin(userexists,email,password,clouddburl,loginkey):

    retorno = {'status':"NotFound" + ("ButExists" if userexists else "")}

    if (clouddburl is not None) and (clouddburl != ''):
        try:
            clouddb = create_engine(clouddburl,connect_args={'connect_timeout': 10})
            with clouddb.connect() as conncloud:     
                table1 = Table('user', MetaData(), autoload_with=clouddb)
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


@huey.task()
def doChangePass(email,newpass,name,role,clouddburl):

    ret = {"status":"Failed"}

    if (clouddburl is not None) and (clouddburl != ''):
        try:
            clouddb = create_engine(clouddburl,connect_args={'connect_timeout': 10})
            with clouddb.connect() as conncloud:     
                table1 = Table('user', MetaData(), autoload_with=clouddb)
                clouddata = conncloud.execute(table1.select().where(table1.c.email==email))
                usercloud = clouddata.first()   
                if usercloud is not None:
                    stmt = table1.update().where(table1.c.email==email).values(password=newpass)
                    conncloud.execute(stmt)
                    conncloud.commit()
                    ret = {"status":"PassUpdated"}
                else:
                    ndict = {'email': email, 'name': name, 'password': newpass, 
                        'role': role, 'viewAs': email, 'lastPassRecovery': None, 
                        'topLevelEntity': "usertop", 'testEntity': "usertest"}
                    conncloud.execute(table1.insert(), ndict)
                    conncloud.commit()
                    ret = {"status":"PassUpdatedUserInserted"}
                clouddata.close()
        except OperationalError as err:
            ret = {"status": "Error", "message":f"OperationalError: {err}"}
        except BaseException as err:
            ret = {"status": "Error", "message":f"Exception: {err}"}

    return ret


@huey.task()
def doPassRecovery(email,randompasshash,clouddburl):

    ret = {"status":"Failed"}

    try:
        clouddb = create_engine(clouddburl,connect_args={'connect_timeout': 10})
        with clouddb.connect() as conncloud:     
            table1 = Table('user', MetaData(), autoload_with=clouddb)
            clouddata = conncloud.execute(table1.select().where(table1.c.email==email))
            usercloud = clouddata.first()  
            if usercloud is not None:
                if (usercloud.lastPassRecovery is not None) and ( datetime.now() < (usercloud.lastPassRecovery+timedelta(minutes=10)) ):
                    ret = {"status":"NotAllowed10Min"}
                else:
                    conncloud.execute(table1.update().where(table1.c.email==email).values(password=randompasshash,lastPassRecovery=datetime.now()))
                    conncloud.commit()
                    ret = {"status":"Success"}
            else:
                ret = {"status":"NotFoundInCloud"}
            clouddata.close()
    except OperationalError as err:
        ret = {"status": "Error", "message":f"OperationalError: {err}"}
    except BaseException as err:
        ret = {"status": "Error", "message":f"Exception: {err}"}
    
    return ret


def writeWorkBackup(workdir, destfile):
    """tar.gz of the work dir. SQLite databases are added as consistent snapshots (backup API),
    since the app may be writing to them; their journal/WAL files and old backups are skipped."""
    import os
    import sqlite3
    import tarfile
    import tempfile
    workdir, destfile = Path(workdir), Path(destfile)
    destfile.parent.mkdir(parents=True, exist_ok=True)
    part = destfile.with_name(destfile.name + ".part")
    with tempfile.TemporaryDirectory(dir=destfile.parent) as snapdir, tarfile.open(part, "w:gz") as tar:
        for p in sorted(workdir.iterdir()):
            name = p.name
            if name.startswith("workbackup") or name.endswith(("-journal", "-wal", "-shm")):
                continue
            if p.is_file() and p.suffix in (".sqlite", ".db"):
                snap = Path(snapdir, name)
                try:
                    src = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=30)
                    dst = sqlite3.connect(snap)
                    try:
                        src.backup(dst)
                    finally:
                        dst.close()
                        src.close()
                    tar.add(snap, arcname=name)
                    continue
                except sqlite3.Error:
                    pass  # not a valid database: store the raw file
            tar.add(p, arcname=name)
    os.replace(part, destfile)


@huey.task()
def doWorkBackup(workdir,destfile):

    ret = {"status":"Failed"}

    try:
        writeWorkBackup(workdir, destfile)
        ret = {"status":"Success"}
    except BaseException as err:
        ret = {"status": "Error", "message":f"Exception: {err}"}
    return ret
