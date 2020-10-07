import re,socket,time,subprocess,select,os
from random import randrange
from pathlib import Path

from appp import socketio

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
    signal CLK_1Hz:        std_logic := '0';
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
    CLK_1Hz <= ckbyte(1);
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
availableports = "(CLOCK_50|CLK_500Hz|CLK_1Hz|RKEY|KEY|RSW|SW|LEDR|HEX0|HEX1|HEX2|HEX3|HEX4|HEX5|HEX6|HEX7)" # ['CLOCK_50','CLK_500Hz','RKEY','KEY','RSW','SW','LEDR','HEX0','HEX1','HEX2','HEX3','HEX4','HEX5','HEX6','HEX7']
def createFpgaTest(sessionpath,toplevelfile):
    toplevel = Path(sessionpath,toplevelfile)
    if not toplevel.exists(): return 1;
    fpgatestfile = Path(sessionpath,'fpgatest.aux')
    if fpgatestfile.exists(): fpgatestfile.unlink()
    toplevel = open(Path(sessionpath,toplevelfile), 'r')    
    data = toplevel.read().replace("\n"," ");
    toplevel.close();
    entityname = re.search(r"entity (\w+) is",data,re.IGNORECASE)
    if entityname is None: 
        return 2
    entityname = entityname.group(1)
    aux = re.search(rf"(entity {entityname} is.*end entity|entity {entityname} is.*end {entityname})",data,re.IGNORECASE)
    if aux is None:
        return 2
    foundports = re.findall(rf"{availableports}(:|,|\s)",aux.group(0),re.IGNORECASE)
    if len(foundports) == 0:
        return 3
    portmaptxt = "port map("
    for port in foundports:
        portmaptxt = portmaptxt + f"{port[0]} => {port[0]},"
    portmaptxt = portmaptxt[:-1] + ");"
    fpgatest = open(fpgatestfile,'w')
    fpgatest.write(fpgatesttemplate.replace('{{portmap}}',portmaptxt))
    fpgatest.close()
    return 0

def createnewuser(basepath):
    subdirs = list(basepath.glob("*"))
    # print(subdirs)
    candidate = newuserprefix + str(randrange(10000))
    while candidate in subdirs:
        candidate = newuserprefix + str(randrange(10000)) 
    return candidate

def cleanfilelist(sessionpath,toplevelfile,filelist):
    filesleft = [toplevelfile]
    foundcomponents = [toplevelfile[:-4]]
    while len(filesleft) > 0:
        myfile = open(Path(sessionpath,filesleft[0]), 'r')    
        data = myfile.read().replace("\n"," ")
        found = re.findall(rf'component [\w\d\s]* is',data,re.IGNORECASE)
        # print(found)
        for ff in found:
            foundcomponents.append(ff[9:-2].strip().lower())
            filesleft.append(foundcomponents[-1] + ".vhd")
        filesleft.pop(0)
    # print(foundcomponents)
    for k in range(len(filelist)-1,-1,-1):
        if filelist[k].name[:-4].lower() not in foundcomponents:
            filelist.pop(k) 
    # print(filelist)

def compilefile(username,sid,mainpath):
    compilerpath = Path(mainpath,'backend','fpgacompileweb')
    basepath = Path(mainpath,'work')
    sessionpath = Path(basepath, username)
    retcode = createFpgaTest(sessionpath,'usertop.vhd')
    if retcode == 0:
        pass
    elif retcode == 1:
        socketio.emit('errors', "Could not find top level file: usertop.vhd.",namespace="/stream",room=sid)
        socketio.disconnect(namespace="/stream",room=sid)
        return
    elif retcode == 2:   
        socketio.emit('errors', "Error finding top level entity (usertop).",namespace="/stream",room=sid)
        socketio.disconnect(namespace="/stream",room=sid)
        return
    elif retcode == 3:   
        socketio.emit('errors', "Bad port names in usertop: port names do not match those from the emulator.",namespace="/stream",room=sid)
        socketio.disconnect(namespace="/stream",room=sid)
        return
    aux = list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))
    # cleanfilelist(sessionpath,'usertop.vhd',aux)
    filenames = [x.name for x in aux]
    proc = subprocess.Popen(
                [compilerpath,sessionpath] + filenames + ['fpgatest.aux'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
        )
    rline = 'start'
    while rline != b'':
        rline = proc.stdout.readline()
        socketio.emit("message",rline.decode(),namespace="/stream",room=sid)
        socketio.sleep(0.1)
    aux = proc.stderr.read()
    if aux != b'':
        socketio.emit("errors",aux.decode().replace('\n','\n<br>'),namespace="/stream",room=sid)
    else:
        socketio.emit("success","done",namespace="/stream",room=sid);
    # socketio.disconnect(namespace="/stream",room=sid)

def analyzefile(username,sid,mainpath,filename):
    compilerpath = Path(mainpath,'backend','analyze.sh')
    basepath = Path(mainpath,'work')
    sessionpath = Path(basepath, username)    
    proc = subprocess.Popen(
                [compilerpath,sessionpath,filename],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
        )
    rline = 'start'
    while rline != b'':
        rline = proc.stdout.readline()
        socketio.emit("message",rline.decode(),namespace="/stream",room=sid)
        socketio.sleep(0.1)
    aux = proc.stderr.read()
    if aux != b'':
        socketio.emit("errors",aux.decode().replace('\n','\n<br>'),namespace="/stream",room=sid)
    else:
        socketio.emit("asuccess","done",namespace="/stream",room=sid);


emulprocs = {}
fifowrite = {}
def doEmulation(username,sid,mainpath):
    keysprocs = emulprocs.keys()
    if len(keysprocs) >= 25:
        socketio.emit('error',f'Too many emulations running, please try again in a minute or two.',namespace="/emul",room=sid)
        return
    elif username in keysprocs:
        socketio.emit('error',f'Emulation already running for {username}.',namespace="/emul",room=sid)
        return
    else:
        socketio.emit('message','Starting emulation...',namespace="/emul",room=sid)
    basepath = Path(mainpath,'work')
    sessionpath = Path(basepath, username)
    try: 
        for k in sessionpath.rglob("myfifo*"):
            k.unlink();
    except:
        pass
    fpgatestpath = Path(sessionpath, 'fpgatest')
    if not fpgatestpath.exists():
        socketio.emit('error',f'Compilation required before emulation.',namespace="/emul",room=sid)
        return
    proc = subprocess.Popen(
                [fpgatestpath],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=sessionpath 
        )
    emulprocs[username] = proc
    socketio.sleep(0.2)      
    # print("Opening FIFO...")
    fiforead = os.open(Path(sessionpath,'myfifo'+str(proc.pid)), os.O_RDONLY | os.O_NONBLOCK)
    poller = select.epoll()
    poller.register(fiforead)
    poller.poll()
    # select.select([fiforead], [], [fiforead]) # Blocks until ready to read
    os.read(fiforead,3).decode()
    # print(os.read(fiforead,3).decode())
    socketio.sleep(0.2)
    fifowrite[username] = os.open(Path(sessionpath,'myfifo2'+str(proc.pid)), os.O_WRONLY)  
    socketio.emit('started','Ok!',namespace="/emul",room=sid)
    lasttime = time.time()     
    run = True  
    while run:
        # aux,aux1,aux2 = select.select([fiforead], [fifowrite[username]], [fiforead]) # Blocks until ready to read
        # aux,aux1,aux2 = select.select([fiforead], [], [fiforead], 1) # Blocks until ready to read
        events = poller.poll(0) 
        # print(events)          
        # if len(aux) > 0:
        if (len(events) > 0):
            if (events[0][1] & select.EPOLLHUP) != 0:                
                run = False
            elif (events[0][1] & select.EPOLLIN) != 0:
                data = os.read(fiforead,11)
                socketio.emit('bytes', data, namespace="/emul", room=sid)
                lasttime = time.time()
        else:
            if ((time.time()-lasttime) >= 120 ):
                socketio.emit('error','Inactivity timeout...',namespace="/emul", room=sid)
                closeEmul(username)
                socketio.emit('status','Parado',namespace="/emul", room=sid)
        socketio.sleep(0.2)
        # print(".")
    # print("Saiu!")
    poller.close()
    os.close(fifowrite[username])
    os.close(fiforead)
    del fifowrite[username]
    # socketio.disconnect(namespace="/emul",room=sid)

def stopEmulation(username,sid):
    if username not in emulprocs.keys():
        socketio.emit('error',f'Emulation not running for {username}.',namespace="/emul", room=sid)
        return
    else:
        closeEmul(username)
        socketio.emit('status',"Parado",namespace="/emul", room=sid)

def closeEmul(username):
    if username in emulprocs.keys():
        emulprocs[username].terminate()
        del emulprocs[username]