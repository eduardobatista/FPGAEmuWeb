import time,os,traceback,re
from pathlib import Path
from flask import session, current_app, request
from flask_socketio import send, emit, disconnect, join_room, leave_room
from appp import socketio
from pathlib import Path
from .funcs import *
from flask_login import login_required, current_user
from appp import db
from .projectexporter import ProjectExporter

def getuserpath():
    if (current_user.viewAs is None) or (current_user.viewAs == ''):
        userpath = Path(current_app.WORKDIR,current_user.email)
    else:
        userpath = Path(current_app.WORKDIR,current_user.viewAs)
    if not userpath.exists():
        userpath.mkdir(parents=True)
    return userpath

def checklogged():
    if not current_user.is_authenticated:
        emit('notlogged',"")
        return False
    return True

@socketio.on('getfile', namespace='/stream') 
def getfile(filename):
    if checklogged():
        try:
            sessionpath = getuserpath()

            sepidx = filename.index("/")
            projname = filename[:sepidx]
            fname = filename[sepidx+1:]
            if re.search(r'[^a-zA-Z0-9_\.]',fname) or (fname.count('.') > 1) or (fname == ".vhd"):
                emit("error",f"<strong>Invalid filename: {fname}.</strong><br>Please remove any unusual characters, such as spaces, slashs, extra dots, etc.")
                return

            fname = Path(sessionpath,filename)   
            
            data = open(fname,'r').read()
            
            emit("filecontent",data)
        except TypeError as terror:
            emit("error",str(terror))
        except FileNotFoundError as fnf:
            emit("error",f'File not found: {filename}.<br>Refresh page and try again.')
        except Exception as ex:
            emit("error",traceback.format_exc())

@socketio.on('getmap', namespace='/stream') 
def getmap(filename):
    if checklogged():
        sessionpath = getuserpath()
        data = getportlist(sessionpath=sessionpath,file=filename)
        data2 = getexistingportmap(sessionpath=sessionpath,file=filename)
        emit("portlist",[data,data2])

@socketio.on('savemap', namespace='/stream') 
def savemap(dataa):
    if checklogged():
        if (current_user.viewAs != '') and (current_user.viewAs != current_user.email):
            emit("error","Not allowed while viewing as a different user.")
            return
        sessionpath = getuserpath()
        with open(sessionpath / (dataa['filename']+".map"),'w') as ff:
            ff.write(dataa['data'])
        emit("mapsavesuccess","ok!")

@socketio.on('renamefile', namespace='/stream') 
def renamefile(dataa):
    if checklogged():
        if (current_user.viewAs != '') and (current_user.viewAs != current_user.email):
            emit("error","Not allowed while viewing as a different user.")
            return
        sessionpath = getuserpath()
        if not sessionpath.exists():
            emit("error","Directory not found.")
            return
        filetorename = Path(sessionpath,dataa['filename'])
        filenameto = Path(sessionpath,dataa['filenameto'])
        if not filetorename.exists():
            emit("error","File to rename not found.")
            return
        if filenameto.suffix != filetorename.suffix:
            emit("error","New and old names must have the same suffix.")
            return
        if (filetorename.suffix == "") or (filetorename.suffix == ".vhd"): 
            filetorename.rename(Path(sessionpath,dataa['filenameto']))
            if filetorename.suffix == ".vhd":
                filetorenamemap = Path(sessionpath,dataa['filename'] + ".map")
                if filetorenamemap.exists():
                    filetorenamemap.rename(Path(sessionpath,dataa['filenameto'] + ".map"))
            emit("filerenamed",dataa['filenameto'])
        else: 
            emit("error",f"Renaming files with suffix {filetorename.suffix} is not allowed.")

@socketio.on('createproject', namespace='/stream') 
def createproject(dataa):
    if checklogged():
        if (current_user.viewAs != '') and (current_user.viewAs != current_user.email):
            emit("error","Not allowed while viewing as a different user.")
            return
        sessionpath = getuserpath()
        if not sessionpath.exists():
            emit("error","Directory not found.")
            return
        if dataa['projectname'] == "_OldFiles":
            emit("error","Project name not allowed.")
            return
        if re.search(r'[^a-zA-Z0-9_]',dataa['projectname']):
            emit("error","Project name must contain only letters, numbers or underline characters.")
            return
        newproject = Path(sessionpath,dataa['projectname'])
        if newproject.suffix != "":
            emit("error","Project name cannot have a suffix or extension.")
            return
        if newproject.exists():
            emit("error","Project already exists.")
            return
        newproject.mkdir(parents=True)
        emit("projectcreated",dataa['projectname'])

@socketio.on('savefile', namespace='/stream') 
def savefile(dataa):
    if checklogged():
        if (current_user.viewAs != '') and (current_user.viewAs != current_user.email):
            emit("error","Not allowed while viewing as a different user.")
            return
        if not dataa['filename'].endswith(".vhd"):
            emit("error","Only .vhd files are allowed.")
            return
        filename = dataa['filename']
        sepidx = filename.index("/")
        projname = filename[:sepidx]
        fname = filename[sepidx+1:]
        # Checking filename:
        if re.search(r'[^a-zA-Z0-9_\.]',fname) or (fname.count('.') > 1) or (fname == ".vhd"):
            emit("error",f"<strong>Invalid filename: {fname}.</strong><br>Please remove any unusual characters, such as spaces, slashs, extra dots, etc.")
            return
        sessionpath = getuserpath()
        if not sessionpath.exists():
            sessionpath.mkdir(parents=True,exist_ok=True)
        try:             
            fname = Path(sessionpath,dataa['filename'])
            if not fname.parent.exists():
                fname.parent.mkdir(parents=True,exist_ok=True)      
            data = open(fname,'w').write(dataa['data'])
            emit("filesaved",dataa['filename'])
        except Exception as ex:
            emit("error","File could not be saved. Check file name.")

        

@socketio.on('deletefile', namespace='/stream') 
def deletefile(filename):
    if checklogged():
        # if (current_user.viewAs != '') and (current_user.viewAs != current_user.email):
        #     emit("error","Not allowed while viewing as a different user.")
        #     return
        sessionpath = getuserpath()
        fpath = Path(sessionpath,filename)
        if (fpath.suffix == ".vhd"):
            try:                
                fpath.unlink()                
                fmap = Path(sessionpath,filename+".map")
                if fmap.exists():
                    fmap.unlink()
                emit("filedeleted",filename)
            except FileNotFoundError as fnf:
                emit("error",f"Could not delete: file {filename} not found.<br>Refresh page to update file list.")
            except BaseException as ex:
                emit("error",str(ex))
            except OSError as err:
                emit("error",str(err))
        elif fpath.is_dir():
            try:     
                for ff in fpath.glob("*"):
                    ff.unlink()           
                fpath.rmdir()
                emit("filedeleted",filename)
            except FileNotFoundError as fnf:
                emit("error",f"Could not delete: file {filename} not found.<br>Refresh page to update file list.")
            except BaseException as ex:
                emit("error",str(ex))
            except OSError as err:
                emit("error",str(err))
        else:
            emit("error","Only .vhd files or projects are allowed.")

@socketio.on('deleteallfiles', namespace='/stream') 
def deleteallfiles(pname):
    if checklogged():
        if (current_user.viewAs != '') and (current_user.viewAs != current_user.email):
            emit("error","Not allowed while viewing as a different user.")
            return
        try:
            sessionpath = getuserpath()
            fpath = sessionpath / pname
            aux = list(fpath.glob("*.vhd"))
            for ff in aux:
                ff.unlink()
            aux2 = list(fpath.glob("*.map"))
            for ff2 in aux2:
                ff2.unlink 
            emit("filedeleted","*")
        except:
            emit("error","Error deleting all files.")

@socketio.on('exportproject', namespace='/stream')
def exportproject(projname):
    if checklogged():
        # socketio.start_background_task(analyzefile,getuserpath(),current_app.MAINPATH,filename,current_user.email)
        if projname not in current_user.topLevelEntity:
            emit("error","Top level entity not in current project. Please set an entity in current project as top level.")
        emit("message",f"Top Level entity is <strong style='color:red;'>{current_user.topLevelEntity}</strong>.")
        sessionpath = getuserpath()
        projpath = sessionpath / projname        
        pexp = ProjectExporter(projname, current_user.topLevelEntity)
        projfiles = getvhdfilelist(projpath)
        pexp.addFiles(projfiles)
        temppath = Path(current_app.MAINPATH,'temp',current_user.email)
        
        msgs = pexp.generateProject(projpath,temppath)
        if len(msgs) > 0:
            if msgs[0].startswith("Error:"):
                emit("exporterror",msgs[0])
                return
            else:
                emit("message","<br>".join(msgs))            
        emit("exportsuccess",projname)
        return
    emit("error","User not logged.")
    return
        

@socketio.on('Analyze', namespace='/stream')
def analyze(filename):
    if checklogged():
        socketio.start_background_task(analyzefile,getuserpath(),current_app.MAINPATH,filename,current_user.email)

@socketio.on('Simulate', namespace='/stream')
def simulate(stoptime,testentity="usertest.vhd"):
    if checklogged():
        current_user.testEntity = testentity[:-4]
        db.session.commit()
        if ("/" not in testentity):
            curproject = ""
        else:
            aux = testentity.split("/")
            curproject = aux[0]
            testentity = aux[1]
        socketio.start_background_task(simulatefile,getuserpath(),current_app.MAINPATH,stoptime,current_user.email,testentity[:-4],curproject)

@socketio.on('message', namespace='/stream') 
def stream(cmd):
    if checklogged():
        if cmd == "Compile":
            socketio.start_background_task(compilefile,getuserpath(),current_app.MAINPATH,
                                        current_user.email,current_user.topLevelEntity)
        else: 
            disconnect()

@socketio.on('message', namespace='/emul') 
def stream2(cmd):
    if checklogged():    
        if cmd == "Parar":
            # current_app.logger.info(f"{current_user.email}: Stopping emulation.")
            stopEmulation(current_user.email)
        elif cmd == "Emular":
            current_app.logger.info(f"{current_user.email}: Starting emulation of {current_user.topLevelEntity}.")
            curproject = "" if ("/" not in current_user.topLevelEntity) else current_user.topLevelEntity.split("/")[0]
            socketio.start_background_task(doEmulation,current_user.email,current_app.MAINPATH,curproject,current_user.topLevelEntity)
        else:
            disconnect()

@socketio.on('initstate', namespace='/emul')
def writeinitstate(msg):
    if checklogged():
        if current_user.email not in fifowrite.keys():
            emit("error","Emulation not running.");
            return
        aux = []
        for k in range(3):
            aux.append(0x62) # Corresponde a 'b'
            aux.append(k)
            aux.append( (msg >> (k*8)) & 0xFF )
            aux.append(2) # Has more bytes
        aux[-1] = 1 
        try:
            # select.select([], [fifowrite[current_user.email]], [fifowrite[current_user.email]],2.0)
            os.write(fifowrite[current_user.email],bytes(aux))            
        except BrokenPipeError as e:
            emit("error","Broken pipe.")
            emit('status','Parado')
        except Exception as ex:
            emit('error',str(ex))

    

@socketio.on('action', namespace='/emul') 
def action(msg):
    if checklogged():
        if current_user.email not in fifowrite.keys():
            emit("error","Emulation not running.");
            return
        aux = list(msg.encode('utf-8'))
        aux[1] = aux[1] - 0x30
        if msg[0] == 's': 
            aux[2] = aux[2] - 0x30
        aux.append(1)
        try:
            # select.select([], [fifowrite[current_user.email]], [fifowrite[current_user.email]],2.0)
            os.write(fifowrite[current_user.email],bytes(aux))
        except BrokenPipeError as e:
            emit("error","Broken pipe.")
            emit('status','Parado')
        except Exception as ex:
            emit('error',str(ex))


@socketio.on('requestghwsignals', namespace='/stream') 
def requestghwsignals():
    if checklogged():
        sessionpath = getuserpath()
        data = getghwsignals(sessionpath,current_app.MAINPATH,'output.ghw',['#5-#6','#1-#3'])
        emit("ghwsignals",data)
        

@socketio.on('requestghwdata', namespace='/stream') 
def requestghwdata():
    if checklogged():
        sessionpath = getuserpath()
        hie = getghwhierarchy(current_user.email,current_app.MAINPATH,'output.ghw')
        groups = []
        for inst in hie:
            for sig in hie[inst]:
                aux = hie[inst][sig]['idxs']
                if "-" in aux:
                    groups.append(aux)
        data = [hie,getghwsignals(current_user.email,current_app.MAINPATH,'output.ghw',groups)]
        emit("ghwdata",data)


@socketio.on('disconnect', namespace='/emul')
def test_disconnect():   
    if checklogged():
        leave_room(current_user.email)
        if current_user.email in emulprocs.keys():        
            closeEmul(current_user.email)
            emit('error','Stopped on disconnect...')
            emit('status',"Parado")


@socketio.on('connect', namespace='/emul')
def connection():
    if checklogged():
        join_room(current_user.email)


@socketio.on('connect', namespace='/stream')
def connection():
    if checklogged():
        join_room(current_user.email)
