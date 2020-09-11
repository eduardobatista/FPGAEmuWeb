import subprocess,time,os,select
from pathlib import Path
from flask import session, current_app
from flask_socketio import send, emit, disconnect
from appp import socketio
from pathlib import Path
from .funcs import *

@socketio.on('getfile', namespace='/stream') 
def getfile(filename):
    basepath = Path(current_app.MAINPATH,'work')
    sessionpath = Path(basepath, session['username'])
    fname = Path(sessionpath,filename)
    data = open(fname,'r').read()
    emit("filecontent",data)

@socketio.on('renamefile', namespace='/stream') 
def renamefile(dataa):
    basepath = Path(current_app.MAINPATH,'work')
    sessionpath = Path(basepath, session['username'])
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
    basepath = Path(current_app.MAINPATH,'work')
    sessionpath = Path(basepath, session['username'])
    if not sessionpath.exists():
        sessionpath.mkdir(parents=True,exist_ok=True)
    fname = Path(sessionpath,dataa['filename'])
    data = open(fname,'w').write(dataa['data'])
    emit("filesaved",dataa['filename'])

@socketio.on('deletefile', namespace='/stream') 
def deletefile(filename):
    if (str(filename).endswith('.vhd') or str(filename).endswith('.vhdl')):
        basepath = Path(current_app.MAINPATH,'work')
        sessionpath = Path(basepath, session['username'])
        fname = Path(sessionpath,filename)
        fname.unlink()
        emit("filedeleted",filename)
    else:
        emit("deleteerror","Only .vhd and .vhdl files allowed.")
    

@socketio.on('message', namespace='/stream') 
def stream(cmd):
    if cmd == "Compile":
        compilerpath = Path(current_app.MAINPATH,'backend','fpgacompileweb')
        basepath = Path(current_app.MAINPATH,'work')
        sessionpath = Path(basepath, session['username'])
        if not createFpgaTest(sessionpath,'usertop.vhd'):
            emit('errors', "Could not find usertop.vhd, its ports or usertop entity.")
            disconnect()
            return
        aux = list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))
        filenames = [x.name for x in aux]
        proc = subprocess.Popen(
                    [compilerpath,sessionpath] + filenames + ['fpgatest.aux'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
            )
        rline = 'start'
        while rline != b'':
            rline = proc.stdout.readline()
            emit("message",rline.decode())
            time.sleep(0.5)
        aux = proc.stderr.read()
        if aux != b'':
            emit("errors",aux.decode().replace('\n','\n<br>'))
        else:
            emit("success","done");
    disconnect()

@socketio.on('message', namespace='/emul') 
def stream(cmd):
    if cmd == "Parar":
        if session['username'] not in current_app.procs.keys():
            emit('error',f'Emulation not running for {session["username"]}.')
            return
        else:
            closeEmul(current_app,session['username'])
            emit('status',"Parado")
    elif cmd == "Emular":
        keysprocs = current_app.procs.keys()
        if len(keysprocs) >= 25:
            emit('error',f'Too many emulations running, please try again in a minute or two.')
            return
        elif session['username'] in keysprocs:
            emit('error',f'Emulation already running for {session["username"]}.')
            return
        else:
            emit('message','Starting emulation...')
        basepath = Path(current_app.MAINPATH,'work')
        sessionpath = Path(basepath, session['username'])
        try: 
            for k in sessionpath.rglob("myfifo*"):
                k.unlink();
        except:
            pass
        fpgatestpath = Path(sessionpath, 'fpgatest')
        if not fpgatestpath.exists():
            emit('error',f'Compilation required before emulation.')
            return
        proc = subprocess.Popen(
                    [fpgatestpath],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=sessionpath 
            )
        current_app.procs[session['username']] = proc
        time.sleep(0.3)      
        # print("Opening FIFO...")
        fiforead = os.open(Path(sessionpath,'myfifo'+str(proc.pid)), os.O_RDONLY | os.O_NONBLOCK)
        select.select([fiforead], [], [fiforead]) # Blocks until ready to read
        # print("FIFO opened")
        print(os.read(fiforead,3).decode())
        time.sleep(0.3)
        current_app.fifowrite[session['username']] = os.open(Path(sessionpath,'myfifo2'+str(proc.pid)), os.O_WRONLY)  
        emit('started','Ok!')
        lasttime = time.time()       
        while True:
            aux,aux1,aux2 = select.select([fiforead], [current_app.fifowrite[session['username']]], [fiforead]) # Blocks until ready to read
            if len(aux) > 0:
                data = os.read(fiforead,11)
                # print(data)                
                if len(data) == 0:
                    # print("Writer closed.")
                    break
                emit('bytes', data)
                lasttime = time.time()
            else:
                if ((time.time()-lasttime) >= 120 ):
                    emit('error','Inactivity timeout...')
                    closeEmul(current_app,session['username'])
                    emit('status','Parado')
            time.sleep(0.2)
        # print("Saiu!")
        os.close(current_app.fifowrite[session['username']])
        os.close(fiforead)
        del current_app.fifowrite[session['username']]
    disconnect()

@socketio.on('initstate', namespace='/emul')
def writeinitstate(msg):
    # return
    if session['username'] not in current_app.fifowrite.keys():
        return
    aux = []
    for k in range(3):
        aux.append(0x62) # Corresponde a 'b'
        aux.append(k)
        aux.append( (msg >> (k*8)) & 0xFF )
        aux.append(2) # Has more bytes
    aux[-1] = 1    
    select.select([], [current_app.fifowrite[session['username']]], [current_app.fifowrite[session['username']]])
    os.write(current_app.fifowrite[session['username']],bytes(aux))
    

@socketio.on('action', namespace='/emul') 
def action(msg):
    aux = list(msg.encode('utf-8'))
    aux[1] = aux[1] - 0x30
    if msg[0] == 's': 
        aux[2] = aux[2] - 0x30
    aux.append(1)
    select.select([], [current_app.fifowrite[session['username']]], [current_app.fifowrite[session['username']]])
    os.write(current_app.fifowrite[session['username']],bytes(aux))
    # print(msg,end=" ")
    # print(aux[1],end=" ")
    # print(aux[2])

@socketio.on('disconnect', namespace='/emul')
def test_disconnect():   
    if session['username'] in current_app.procs.keys():        
        closeEmul(current_app,session['username'])
        emit('status',"Parado")