import subprocess,time,os,select,threading
from pathlib import Path
from flask import session, current_app, request
from flask_socketio import send, emit, disconnect, join_room, leave_room
from appp import socketio
from pathlib import Path
from .funcs import *
from flask_login import login_required, current_user
from appp import db

def getuserpath():
    if (current_user.viewAs is None) or (current_user.viewAs == ''):
        userpath = Path(current_app.MAINPATH,'work',current_user.email)
    else:
        userpath = Path(current_app.MAINPATH,'work',current_user.viewAs)
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
            fname = Path(sessionpath,filename)
            data = open(fname,'r').read()
            emit("filecontent",data)
        except TypeError as terror:
            emit("error",str(terror))
        except FileNotFoundError as fnf:
            emit("error",f'File not found: {filename}.<br>Refresh page and try again.')
        except Exception as ex:
            emit("error",type(ex) + ":" + str(ex))

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
        if not filetorename.exists():
            emit("error","File to rename not found.")
            return
        filetorename.rename(Path(sessionpath,dataa['filenameto']))
        emit("filerenamed",dataa['filenameto'])

@socketio.on('savefile', namespace='/stream') 
def savefile(dataa):
    if checklogged():
        if (current_user.viewAs != '') and (current_user.viewAs != current_user.email):
            emit("error","Not allowed while viewing as a different user.")
            return
        sessionpath = getuserpath()
        if not sessionpath.exists():
            sessionpath.mkdir(parents=True,exist_ok=True)
        try: 
            fname = Path(sessionpath,dataa['filename'])
            data = open(fname,'w').write(dataa['data'])
            emit("filesaved",dataa['filename'])
        except Exception as ex:
            emit("error","File could not be saved. Check file name.")

        

@socketio.on('deletefile', namespace='/stream') 
def deletefile(filename):
    if checklogged():
        if (current_user.viewAs != '') and (current_user.viewAs != current_user.email):
            emit("error","Not allowed while viewing as a different user.")
            return
        if (str(filename).endswith('.vhd') or str(filename).endswith('.vhdl')):
            try:
                sessionpath = getuserpath()
                fname = Path(sessionpath,filename)
                fname.unlink()
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
        else:
            emit("error","Only .vhd and .vhdl files allowed.")

@socketio.on('deleteallfiles', namespace='/stream') 
def deleteallfiles(fname):
    if checklogged():
        if (current_user.viewAs != '') and (current_user.viewAs != current_user.email):
            emit("error","Not allowed while viewing as a different user.")
            return
        try:
            sessionpath = getuserpath()
            aux = list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))
            for ff in aux:
                ff.unlink()
            aux2 = list(sessionpath.glob("*.map"))
            for ff2 in aux2:
                ff2.unlink 
            emit("filedeleted","*")
        except:
            emit("error","Error deleting all files.")
    

@socketio.on('Analyze', namespace='/stream')
def analyze(filename):
    if checklogged():
        socketio.start_background_task(analyzefile,getuserpath(),current_app.MAINPATH,filename,current_user.email)

@socketio.on('Simulate', namespace='/stream')
def simulate(stoptime,testentity="usertest.vhd"):
    if checklogged():
        current_user.testEntity = testentity[:-4]
        db.session.commit()
        socketio.start_background_task(simulatefile,getuserpath(),current_app.MAINPATH,stoptime,current_user.email,testentity[:-4])

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
            current_app.logger.info(f"{current_user.email}: Stopping emulation.")
            stopEmulation(current_user.email)
        elif cmd == "Emular":
            current_app.logger.info(f"{current_user.email}: Starting emulation.")
            socketio.start_background_task(doEmulation,current_user.email,current_app.MAINPATH,getuserpath())
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
        hie = getghwhierarchy(sessionpath,current_app.MAINPATH,'output.ghw')
        groups = []
        for inst in hie:
            for sig in hie[inst]:
                aux = hie[inst][sig]['idxs']
                if "-" in aux:
                    groups.append(aux)
        data = [hie,getghwsignals(sessionpath,current_app.MAINPATH,'output.ghw',groups)]
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
