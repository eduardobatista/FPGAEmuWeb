# -*- coding: utf-8 -*-
import subprocess,time,os,select,sys,socket
import threading
from pathlib import Path
from flask import Flask, url_for, request, session, request, render_template, Response, send_from_directory
from flask_socketio import SocketIO, send, emit, disconnect
from werkzeug.utils import secure_filename
from random import randrange
from zipfile import ZipFile
import re
MAINPATH = os.path.dirname(os.path.abspath(__file__))

'''
    TODO:
        - Adicionar /opt/local/bin to path
        - Melhorar Timeouts: fazer inactivity para entrada e saída diferentes.
        - Botão "Delete All"
        x TIMEOUT sem interação do usuário.
        nn Matar outro processo do usuário na criação de um novo.
        x BUG!!!: Sem arquivo, parece estar compilando.
        x BUG!!!: Extração de ports na emulação dá erro se "end entity" ao invés de "end usertop".
        nn Controlar melhor processos de emulação.
        x Implementar Botões RENAME.
        - Implementar escolha para compilação.
        x Compilar backend quando servidor iniciar?
        - Limpar todos os "fpgatest" após compilação inicial?
        - Limpeza periódica dos diretórios de trabalho...
        x Dar msg de erro se tentar emular sem compilar.
        nn Desabilitar botões e chaves quando simulação não estiver rodando?
        x Após upload, dar refresh na página de uploads para aparecer lista ou puxar lista de arquivos.
        x Quando der "Save As" no Editor, abrir página com arquivo salvo aberto.
        - Disponibilizar template de usertop?
        x Proteger uploads de arquivos grandes.
        x Proteger salvamentos de arquivos grandes.
        - Melhorar gerenciamento de usuários.
        x Fazer About.
        - Manutenção de subdiretórios: apagar com certo tempo sem uso.
'''

app = Flask(__name__)
app.secret_key = b'_5#y2L"F4z\n\xec]/'
app.config['MAX_CONTENT_LENGTH'] = 1000000 
socketio = SocketIO(app)

newuserprefix = socket.gethostbyname(socket.gethostname())[-2:]

fpgatesttemplate = '''
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use ieee.std_logic_unsigned.all;
library work;
use work.fpgaemu.all;
entity fpgatest is
end fpgatest;
architecture archtest of fpgatest is
    signal ckbyte: unsigned(31 downto 0) := x"00000000";
    signal inbytes: std_logic_vector(31 downto 0) := x"00000000";
    signal part1: bit_vector(7 downto 0) := x"FF";
    signal part0: bit_vector(23 downto 0) := x"000000";
    signal outbytes0,outbytes1,outbytes2: bit_vector(31 downto 0) := x"00000000";
    signal CLOCK_50:       std_logic := '0';
    signal CLK_500Hz:      std_logic := '0';
    signal RKEY:           std_logic_vector(3 downto 0) := "1111";
    signal KEY:            std_logic_vector(3 downto 0) := "1111";
    signal RSW:            std_logic_vector(17 downto 0) := "000000000000000000";
    signal SW:             std_logic_vector(17 downto 0):= "000000000000000000";
    signal LEDR:           std_logic_vector(17 downto 0):= "000000000000000000" ;
    signal HEX0,HEX1,HEX2,HEX3,HEX4,HEX5,HEX6,HEX7 : std_logic_vector(6 downto 0) := "1111111";
begin
   process
   begin
	wait for 250 ns;
	ckbyte <= to_unsigned(vhdlck(0),32);
	CLK_500Hz <= ckbyte(0);
	vhdlout(0) := to_integer(signed(to_stdlogicvector(outbytes0)));
	vhdlout(1) := to_integer(signed(to_stdlogicvector(outbytes1)));
	vhdlout(2) := to_integer(signed(to_stdlogicvector(outbytes2)));
	inbytes <= std_logic_vector(to_unsigned(vhdlin(0),32));        
   end process;
   CLOCK_50 <= '0';
   RSW <= inbytes(17 downto 0); 
   SW <= inbytes(17 downto 0); 
   RKEY <= inbytes(23 downto 20); 
   KEY <= inbytes(23 downto 20);
   part1 <= to_bitvector('0' & HEX7,'1');
   part0 <= to_bitvector("000000" & LEDR,'0');
   outbytes0 <= part1 & part0;
   outbytes1 <= to_bitvector('0' & HEX3 & '0' & HEX4 & '0' & HEX5 & '0' & HEX6,'1');
   outbytes2 <= to_bitvector(x"00" & '0' & HEX0 & '0' & HEX1 & '0' & HEX2,'1');
   udut : entity work.usertop
   {{portmap}}
end archtest;
'''
# Default: {{portmap}} == port map(CLOCK_50,CLK_500Hz,RKEY,KEY,RSW,SW,LEDR,HEX0,HEX1,HEX2,HEX3,HEX4,HEX5,HEX6,HEX7);
availableports = "(CLOCK_50|CLK_500Hz|RKEY|KEY|RSW|SW|LEDR|HEX0|HEX1|HEX2|HEX3|HEX4|HEX5|HEX6|HEX7)" # ['CLOCK_50','CLK_500Hz','RKEY','KEY','RSW','SW','LEDR','HEX0','HEX1','HEX2','HEX3','HEX4','HEX5','HEX6','HEX7']
def createFpgaTest(sessionpath,toplevelfile):
    toplevel = Path(sessionpath,toplevelfile)
    if not toplevel.exists(): return False;
    fpgatestfile = Path(sessionpath,'fpgatest.aux')
    if fpgatestfile.exists(): fpgatestfile.unlink()
    toplevel = open(Path(sessionpath,toplevelfile), 'r')    
    data = toplevel.read().replace("\n"," ");
    toplevel.close();
    entityname = re.findall(r"entity \w+ is",data)[0][7:-3]
    aux = re.findall(rf"entity {entityname} is.*end {entityname}",data)
    if len(aux) == 0:
        return False
    foundports = re.findall(rf"{availableports}(:|,|\s)",aux[0])
    portmaptxt = "port map("
    for port in foundports:
        portmaptxt = portmaptxt + f"{port[0]} => {port[0]},"
    portmaptxt = portmaptxt[:-1] + ");"
    fpgatest = open(fpgatestfile,'w')
    fpgatest.write(fpgatesttemplate.replace('{{portmap}}',portmaptxt))
    fpgatest.close()
    return True

def createnewuser(basepath):
    subdirs = list(basepath.glob("*"))
    # print(subdirs)
    candidate = newuserprefix + str(randrange(10000))
    while candidate in subdirs:
        candidate = newuserprefix + str(randrange(10000)) 
    return candidate


@app.route('/')
def sendfiles():    
    basepath = Path(MAINPATH,'work')
    if 'username' not in session:               
        session['username'] = createnewuser(basepath)
    basepath = Path(MAINPATH,'work')
    sessionpath = Path(basepath, session['username'])
    aux = list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))
    filenames = [x.name for x in aux]
    return render_template('sendfiles.html',username=session['username'],filenames=filenames) # app.send_static_file('main.html')

@app.route('/help')
def hhelp():
    return render_template('help.html')

@app.route('/about')
def aabout():
    return render_template('about.html')

@app.route('/emulation')
def emular():
    basepath = Path(MAINPATH,'work')
    if 'username' not in session:               
        session['username'] = createnewuser(basepath)
    return render_template('emulation.html',username=session['username'])

@app.route('/editor')
def editor():    
    basepath = Path(MAINPATH,'work')
    if 'username' not in session:               
        session['username'] = createnewuser(basepath)    
    sessionpath = Path(basepath, session['username'])
    aux = list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))
    filenames = [x.name for x in aux]
    return render_template('editor.html',username=session['username'],filenames=filenames)

@app.route("/downloadfile")
def downloadfile():
    basepath = Path(MAINPATH,'work')
    sessionpath = Path(basepath, session['username'])
    aux = list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))
    filenames = [x.name for x in aux]
    zipname = Path(sessionpath,'VHDLFiles.zip')
    if zipname.exists(): 
        zipname.unlink()
    zipobj = ZipFile(zipname, 'w')
    for f in aux:
        zipobj.write(f,f.name)    
    zipobj.close()
    return send_from_directory(sessionpath, 'VHDLFiles.zip', as_attachment=True)

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        basepath = Path(MAINPATH,'work')
        sessionpath = Path(basepath, session['username'])
        if not sessionpath.exists():
            sessionpath.mkdir(parents=True,exist_ok=True)
        f = request.files.getlist("fileToUpload")
        for ff in f:
            ff.save(Path(sessionpath, secure_filename(ff.filename)))
        return "Done!"
    else:
        return "Fail..."

@app.route('/compilar', methods=['GET', 'POST'])
def compilar():
    if request.headers.get('accept') == 'text/event-stream':
        if proc is not None:
            print("Rodando!")
            proc = Popen("date", stdout=PIPE)        
        def events():
            rline = proc.stdout.readline()
            while rline != b'':
                yield "LINE="
                rline = proc.stdout.readline()
        return Response(events(), content_type='text/event-stream')
    return "Error: Event stream not accepted."
    # return "END!"
    #now = f.read()
    #return "Today is " + str(now)


@socketio.on('getfile', namespace='/stream') 
def getfile(filename):
    basepath = Path(MAINPATH,'work')
    sessionpath = Path(basepath, session['username'])
    fname = Path(sessionpath,filename)
    data = open(fname,'r').read()
    emit("filecontent",data)

@socketio.on('renamefile', namespace='/stream') 
def renamefile(dataa):
    basepath = Path(MAINPATH,'work')
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
    basepath = Path(MAINPATH,'work')
    sessionpath = Path(basepath, session['username'])
    if not sessionpath.exists():
        sessionpath.mkdir(parents=True,exist_ok=True)
    fname = Path(sessionpath,dataa['filename'])
    data = open(fname,'w').write(dataa['data'])
    emit("filesaved",dataa['filename'])

@socketio.on('deletefile', namespace='/stream') 
def deletefile(filename):
    if (str(filename).endswith('.vhd') or str(filename).endswith('.vhdl')):
        basepath = Path(MAINPATH,'work')
        sessionpath = Path(basepath, session['username'])
        fname = Path(sessionpath,filename)
        fname.unlink()
        emit("filedeleted",filename)
    else:
        emit("deleteerror","Only .vhd and .vhdl files allowed.")
    

@socketio.on('message', namespace='/stream') 
def stream(cmd):
    if cmd == "Compile":
        compilerpath = Path(MAINPATH,'backend','fpgacompileweb')
        basepath = Path(MAINPATH,'work')
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

procs = {};
fifowrite = {};

def closeEmul(username):
    procs[username].terminate()
    del procs[username]

@socketio.on('message', namespace='/emul') 
def stream(cmd):
    if cmd == "Parar":
        if session['username'] not in procs.keys():
            emit('error',f'Emulation not running for {session["username"]}.')
            return
        else:
            closeEmul(session['username'])
            emit('status',"Parado")
    elif cmd == "Emular":
        keysprocs = procs.keys()
        if len(keysprocs) >= 25:
            emit('error',f'Too many emulations running, please try again in a minute or two.')
            return
        elif session['username'] in keysprocs:
            emit('error',f'Emulation already running for {session["username"]}.')
            return
        else:
            emit('message','Starting emulation...')
        basepath = Path(MAINPATH,'work')
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
        procs[session['username']] = proc
        time.sleep(0.3)      
        # print("Opening FIFO...")
        fiforead = os.open(Path(sessionpath,'myfifo'+str(proc.pid)), os.O_RDONLY | os.O_NONBLOCK)
        select.select([fiforead], [], [fiforead]) # Blocks until ready to read
        # print("FIFO opened")
        print(os.read(fiforead,3).decode())
        time.sleep(0.3)
        fifowrite[session['username']] = os.open(Path(sessionpath,'myfifo2'+str(proc.pid)), os.O_WRONLY)  
        emit('started','Ok!')
        lasttime = time.time()       
        while True:
            aux,aux1,aux2 = select.select([fiforead], [fifowrite[session['username']]], [fiforead]) # Blocks until ready to read
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
                    closeEmul(session['username'])
                    emit('status','Parado')
            time.sleep(0.2)
        # print("Saiu!")
        os.close(fifowrite[session['username']])
        os.close(fiforead)
        del fifowrite[session['username']]
    disconnect()

@socketio.on('initstate', namespace='/emul')
def writeinitstate(msg):
    # return
    if session['username'] not in fifowrite.keys():
        return
    aux = []
    for k in range(3):
        aux.append(0x62) # Corresponde a 'b'
        aux.append(k)
        aux.append( (msg >> (k*8)) & 0xFF )
        aux.append(2) # Has more bytes
    aux[-1] = 1    
    select.select([], [fifowrite[session['username']]], [fifowrite[session['username']]])
    os.write(fifowrite[session['username']],bytes(aux))
    

@socketio.on('action', namespace='/emul') 
def action(msg):
    aux = list(msg.encode('utf-8'))
    aux[1] = aux[1] - 0x30
    if msg[0] == 's': 
        aux[2] = aux[2] - 0x30
    aux.append(1)
    select.select([], [fifowrite[session['username']]], [fifowrite[session['username']]])
    os.write(fifowrite[session['username']],bytes(aux))
    # print(msg,end=" ")
    # print(aux[1],end=" ")
    # print(aux[2])

@socketio.on('disconnect', namespace='/emul')
def test_disconnect():   
    if session['username'] in procs.keys():        
        closeEmul(session['username'])
        emit('status',"Parado") 

print('Compiling the backend...')
backendcompilerpath = Path(MAINPATH,'backend','compilebackend.sh')
backendcompilerpath.chmod(0o744)
subprocess.Popen(
                    [backendcompilerpath],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=Path(MAINPATH,'backend') 
            )
print('Backend compiled.')
dbg = True
if 'nodebug' in sys.argv:
    dbg = False
socketio.run(app,host='0.0.0.0',port=5000,debug=dbg)