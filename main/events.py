import subprocess,time,os,select,threading
from pathlib import Path
from flask import session, current_app, request
from flask_socketio import send, emit, disconnect
from appp import socketio
from pathlib import Path
from .funcs import *
from flask_login import login_required, current_user

def getuserpath():
    if (current_user.viewAs is None) or (current_user.viewAs == ''):
        userpath = Path(current_app.MAINPATH,'work',current_user.email)
    else:
        userpath = Path(current_app.MAINPATH,'work',current_user.viewAs)
    if not userpath.exists():
        userpath.mkdir(parents=True)
    return userpath

@socketio.on('getfile', namespace='/stream') 
def getfile(filename):
    sessionpath = getuserpath()
    fname = Path(sessionpath,filename)
    data = open(fname,'r').read()
    emit("filecontent",data)

@socketio.on('renamefile', namespace='/stream') 
def renamefile(dataa):
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
    if (current_user.viewAs != '') and (current_user.viewAs != current_user.email):
        emit("error","Not allowed while viewing as a different user.")
        return
    sessionpath = getuserpath()
    if not sessionpath.exists():
        sessionpath.mkdir(parents=True,exist_ok=True)
    fname = Path(sessionpath,dataa['filename'])
    data = open(fname,'w').write(dataa['data'])
    emit("filesaved",dataa['filename'])

@socketio.on('deletefile', namespace='/stream') 
def deletefile(filename):
    if (current_user.viewAs != '') and (current_user.viewAs != current_user.email):
        emit("error","Not allowed while viewing as a different user.")
        return
    if (str(filename).endswith('.vhd') or str(filename).endswith('.vhdl')):
        sessionpath = getuserpath()
        fname = Path(sessionpath,filename)
        fname.unlink()
        emit("filedeleted",filename)
    else:
        emit("deleteerror","Only .vhd and .vhdl files allowed.")

@socketio.on('deleteallfiles', namespace='/stream') 
def deleteallfiles(fname):
    if (current_user.viewAs != '') and (current_user.viewAs != current_user.email):
        emit("error","Not allowed while viewing as a different user.")
        return
    try:
        sessionpath = getuserpath()
        aux = list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))
        for ff in aux:
            ff.unlink()
        emit("filedeleted","*")
    except:
        emit("deleteerror","Error deleting all files.")
    

@socketio.on('Analyze', namespace='/stream')
def analyze(filename):
    socketio.start_background_task(analyzefile,getuserpath(),request.sid,current_app.MAINPATH,filename,current_user.id)

@socketio.on('Simulate', namespace='/stream')
def simulate(stoptime):
    socketio.start_background_task(simulatefile,getuserpath(),request.sid,current_app.MAINPATH,stoptime,current_user.id)

@socketio.on('message', namespace='/stream') 
def stream(cmd):
    if cmd == "Compile":
        # compthread = threading.Thread(target=compilefile,args=(current_user.email,request.sid,current_app))
        # compthread.start()
        socketio.start_background_task(compilefile,getuserpath(),request.sid,current_app.MAINPATH,current_user.id)
    #     compilerpath = Path(current_app.MAINPATH,'backend','fpgacompileweb')
    #     basepath = Path(current_app.MAINPATH,'work')
    #     sessionpath = Path(basepath, current_user.email)
    #     if not createFpgaTest(sessionpath,'usertop.vhd'):
    #         emit('errors', "Could not find usertop.vhd, its ports or usertop entity.")
    #         disconnect()
    #         return
    #     aux = list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))
    #     filenames = [x.name for x in aux]
    #     proc = subprocess.Popen(
    #                 [compilerpath,sessionpath] + filenames + ['fpgatest.aux'],
    #                 stdout=subprocess.PIPE,
    #                 stderr=subprocess.PIPE
    #         )
    #     rline = 'start'
    #     while rline != b'':
    #         rline = proc.stdout.readline()
    #         emit("message",rline.decode())
    #         time.sleep(0.5)
    #     aux = proc.stderr.read()
    #     if aux != b'':
    #         emit("errors",aux.decode().replace('\n','\n<br>'))
    #     else:
    #         emit("success","done");
    else: 
        disconnect()

@socketio.on('message', namespace='/emul') 
def stream2(cmd):
    if cmd == "Parar":
        current_app.logger.info(f"Stoping emulation for {current_user.email}.")
        stopEmulation(current_user.email,request.sid)
        # if current_user.email not in current_app.procs.keys():
        #     emit('error',f'Emulation not running for {session["username"]}.')
        #     return
        # else:
        #     closeEmul(current_app,current_user.email)
        #     emit('status',"Parado")
    elif cmd == "Emular":
        current_app.logger.info(f"Starting emulation for {current_user.email}.")
        socketio.start_background_task(doEmulation,current_user.email,request.sid,current_app.MAINPATH,getuserpath())
        # keysprocs = current_app.procs.keys()
        # if len(keysprocs) >= 25:
        #     emit('error',f'Too many emulations running, please try again in a minute or two.')
        #     return
        # elif current_user.email in keysprocs:
        #     emit('error',f'Emulation already running for {session["username"]}.')
        #     return
        # else:
        #     emit('message','Starting emulation...')
        # basepath = Path(current_app.MAINPATH,'work')
        # sessionpath = Path(basepath, current_user.email)
        # try: 
        #     for k in sessionpath.rglob("myfifo*"):
        #         k.unlink();
        # except:
        #     pass
        # fpgatestpath = Path(sessionpath, 'fpgatest')
        # if not fpgatestpath.exists():
        #     emit('error',f'Compilation required before emulation.')
        #     return
        # proc = subprocess.Popen(
        #             [fpgatestpath],
        #             stdout=subprocess.PIPE,
        #             stderr=subprocess.PIPE,
        #             cwd=sessionpath 
        #     )
        # current_app.procs[current_user.email] = proc
        # time.sleep(0.3)      
        # # print("Opening FIFO...")
        # fiforead = os.open(Path(sessionpath,'myfifo'+str(proc.pid)), os.O_RDONLY | os.O_NONBLOCK)
        # select.select([fiforead], [], [fiforead]) # Blocks until ready to read
        # # print("FIFO opened")
        # print(os.read(fiforead,3).decode())
        # time.sleep(0.3)
        # current_app.fifowrite[current_user.email] = os.open(Path(sessionpath,'myfifo2'+str(proc.pid)), os.O_WRONLY)  
        # emit('started','Ok!')
        # lasttime = time.time()       
        # while True:
        #     aux,aux1,aux2 = select.select([fiforead], [current_app.fifowrite[current_user.email]], [fiforead]) # Blocks until ready to read
        #     if len(aux) > 0:
        #         data = os.read(fiforead,11)
        #         # print(data)                
        #         if len(data) == 0:
        #             # print("Writer closed.")
        #             break
        #         emit('bytes', data)
        #         lasttime = time.time()
        #     else:
        #         if ((time.time()-lasttime) >= 120 ):
        #             emit('error','Inactivity timeout...')
        #             closeEmul(current_app,current_user.email)
        #             emit('status','Parado')
        #     time.sleep(0.2)
        # # print("Saiu!")
        # os.close(current_app.fifowrite[current_user.email])
        # os.close(fiforead)
        # del current_app.fifowrite[current_user.email]
    else:
        disconnect()

@socketio.on('initstate', namespace='/emul')
def writeinitstate(msg):
    # return
    # if current_user.email not in current_app.fifowrite.keys():
    if current_user.email not in fifowrite.keys():
        return
    aux = []
    for k in range(3):
        aux.append(0x62) # Corresponde a 'b'
        aux.append(k)
        aux.append( (msg >> (k*8)) & 0xFF )
        aux.append(2) # Has more bytes
    aux[-1] = 1    
    select.select([], [fifowrite[current_user.email]], [fifowrite[current_user.email]])
    os.write(fifowrite[current_user.email],bytes(aux))
    

@socketio.on('action', namespace='/emul') 
def action(msg):
    if current_user.email not in fifowrite.keys():
        # emit('error',"Emulation not running.")
        return
    aux = list(msg.encode('utf-8'))
    aux[1] = aux[1] - 0x30
    if msg[0] == 's': 
        aux[2] = aux[2] - 0x30
    aux.append(1)
    select.select([], [fifowrite[current_user.email]], [fifowrite[current_user.email]])
    os.write(fifowrite[current_user.email],bytes(aux))
    # print(msg,end=" ")
    # print(aux[1],end=" ")
    # print(aux[2])

@socketio.on('disconnect', namespace='/emul')
def test_disconnect():   
    if current_user.email in emulprocs.keys():        
        closeEmul(current_user.email)
        emit('error','Stopped on disconnect...')
        emit('status',"Parado")