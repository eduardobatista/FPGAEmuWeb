import re,socket,time,subprocess,select,os
from datetime import datetime
from random import randrange
from pathlib import Path
import pkg_resources

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
    signal CLK_10Hz:       std_logic := '0';
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
    CLK_10Hz <= ckbyte(2);
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
   udut : entity work.{{toplevelentity}}
   {{portmap}}
end archtest;
'''
# Default: {{portmap}} == port map(CLOCK_50,CLK_500Hz,RKEY,KEY,RSW,SW,LEDR,HEX0,HEX1,HEX2,HEX3,HEX4,HEX5,HEX6,HEX7);
availableports = "(CLOCK_50|CLK_500Hz|CLK_1Hz|CLK_10Hz|RKEY|KEY|RSW|SW|LEDR|HEX0|HEX1|HEX2|HEX3|HEX4|HEX5|HEX6|HEX7)" # ['CLOCK_50','CLK_500Hz','RKEY','KEY','RSW','SW','LEDR','HEX0','HEX1','HEX2','HEX3','HEX4','HEX5','HEX6','HEX7']
validports = {'CLOCK_50':['in',1], 
              'CLK_500HZ':['in',1], 
              'CLK_1HZ':['in',1],
              'CLK_10HZ':['in',1],
              'KEY':['in',4],
              'RKEY':['in',4],
              'RSW':['in',18],
              'SW':['in',18],
              'LEDR':['out',18],
              'HEX0':['out',7],
              'HEX1':['out',7],
              'HEX2':['out',7],
              'HEX3':['out',7],
              'HEX4':['out',7],
              'HEX5':['out',7],
              'HEX6':['out',7],
              'HEX7':['out',7],              
             }
def createFpgaTest(sessionpath,toplevelentity):
    toplevel = Path(sessionpath,toplevelentity + ".vhd")
    if not toplevel.exists(): return f"Error: Top level entity not found.";
    fpgatestfile = Path(sessionpath,'fpgatest.aux')
    if fpgatestfile.exists(): fpgatestfile.unlink()
    toplevel = open(toplevel, 'r')    
    data = toplevel.read()
    data = re.sub("--.*?\n|\n"," ",data)
    data = re.sub("\s+"," ",data)
    data = re.sub("\s+;",";",data)
    toplevel.close()
    entityname = re.search(r"entity (\w+) is",data,re.IGNORECASE)
    if entityname is None: 
        return "Error: entity not found in usertop."
    entityname = entityname.group(1)
    # aux = re.search(rf"(entity {entityname} is.*end entity|entity {entityname} is.*end {entityname})",data,re.IGNORECASE)
    # aux = re.search(rf"entity {entityname} is.*port.*?(\((.+)\)).*?end entity(\s+|);|entity {entityname} is.*port.*?(\((.+)\)).*?end {entityname}(\s+|);",data,re.IGNORECASE)
    # aux = re.search(rf"entity {entityname} is.*port.*?(\((.+)\)).*?end entity;|entity {entityname} is.*port.*?(\((.+)\)).*?end {entityname};",data,re.IGNORECASE)
    aux = re.search(rf"entity {entityname} is(.*?)end entity;|entity {entityname} is(.*?)end {entityname};",data,re.IGNORECASE)
    if aux is None:
        return "Error: entity not found in usertop."
    # print(aux.groups)
    # print(aux.group(0))
    # print(aux.group(1))
    # print(aux.group(2))
    aux = re.search(rf".*port.*?(\((.+)\))",aux.group(0),re.IGNORECASE)
    if aux is None:
        return "Error: ports not found in usertop."
    # print(aux.group(1))
    aux2 = re.split(";\s+|;",aux.group(1)[1:-1])
    sepdots = re.compile(r"\s+:\s+|\s+:|:\s+|:")
    sepcomma = re.compile(r"\s+,\s+|\s+,|,\s+|,")
    sepspace = re.compile(r"\s+")
    validportkeys = validports.keys()
    # print(aux2)
    # foundports = []
    # foundsizes = []
    try:
        for item in aux2:
            aux3 = sepdots.split(item)
            if len(aux3) != 2:
                continue
            # print(aux3)
            dirtype = sepspace.split(aux3[1].strip(),maxsplit=1)
            typesize = 1
            if "std_logic_vector" in dirtype[1].lower():
                auxx = re.search(r"(\d+)\s.*?\s(\d+)",dirtype[1])
                if (auxx is None) or (len(auxx.groups()) < 2):
                    return "Error: Fail parsing " + dirtype[1] + "."
                typesize = int(auxx.group(1)) - int(auxx.group(2)) 
                if typesize < 0: typesize = -typesize
                typesize = typesize+1
            aux4 = sepcomma.split(aux3[0])
            for pp in aux4:
                ppp = pp.strip().upper()
                if ppp not in validportkeys:
                    return f"Error: {pp} is not a valid port for usertop entity."  
                if validports[ppp][1] != typesize:
                    return f"Error: Length of port {pp} does not match the corresponding Emulator port length."
                # if validports[ppp][1] > typesize:
                #     return f"Error: Port {pp} has more bits than the corresponding Emulator port length."
                # foundports.append(ppp)
                # foundsizes.append(typesize)
    except:
        return "Error parsing usertop ports."
    foundports = re.findall(rf"{availableports}(:|,|\s)",aux.group(0),re.IGNORECASE)
    # foundports2 = re.findall(rf"{availableports}(;|\))",aux.group(0),re.IGNORECASE)
    if len(foundports) == 0:
        return "Error: ports not found."
    portmaptxt = "port map("
    zz = 0
    # for port,tsize in zip(foundports,foundsizes):
    for port in foundports:
        portmaptxt = portmaptxt + f"{port[0]} => {port[0]},"
        # if tsize == 1:
        #     portmaptxt = portmaptxt + f"{port} => {port},"
        # else:            
        #     compl = '0'*3
        #     portmaptxt = portmaptxt + f'{port} => "{compl}" & {port}({tsize} downto 0),'
        # portmaptxt = portmaptxt + f"{port[0]}({}) => {port[0]},"
    portmaptxt = portmaptxt[:-1] + ");"
    # print(portmaptxt)
    fpgatest = open(fpgatestfile, 'w')
    fpgatest.write(fpgatesttemplate.replace('{{portmap}}',portmaptxt).replace('{{toplevelentity}}',toplevelentity))
    fpgatest.close()
    return "Ok!"

def createFpgaTest2(sessionpath,toplevelentity):
    toplevel = Path(sessionpath,toplevelentity + ".vhd")
    if not toplevel.exists(): return f"Error: Top level entity not found.";
    fpgatestfile = Path(sessionpath,'fpgatest.aux')
    if fpgatestfile.exists(): fpgatestfile.unlink()
    
    portmaptxt = None
    mapfile = Path(sessionpath,toplevelentity + ".vhd.map")
    if mapfile.exists():
        ff = open(mapfile,'r')
        portmap = ff.readline()
        if len(portmap) > 2:
            portmaptxt = "port map(" + portmap + ");"

    if not portmaptxt:
        toplevel = open(toplevel, 'r')    
        data = toplevel.read()
        data = re.sub("--.*?\n|\n"," ",data)
        data = re.sub("\s+"," ",data)
        data = re.sub("\s+;",";",data)
        toplevel.close()
        entityname = re.search(r"entity (\w+) is",data,re.IGNORECASE)
        if entityname is None: 
            return f"Error: entity not found in {toplevelentity}.vhd."
        entityname = entityname.group(1)
        aux = re.search(rf"entity {entityname} is(.*?)end entity;|entity {entityname} is(.*?)end {entityname};",data,re.IGNORECASE)
        if aux is None:
            return f"Error: entity not found in {toplevelentity}.vhd."
        aux = re.search(rf".*port.*?(\((.+)\))",aux.group(0),re.IGNORECASE)
        if aux is None:
            return f"Error: ports not found in {toplevelentity}.vhd."
        aux2 = re.split(";\s+|;",aux.group(1)[1:-1])
        sepdots = re.compile(r"\s+:\s+|\s+:|:\s+|:")
        sepcomma = re.compile(r"\s+,\s+|\s+,|,\s+|,")
        sepspace = re.compile(r"\s+")
        validportkeys = validports.keys()
        foundports = []
        foundsizes = []
        founddifs = []
        try:
            for item in aux2:
                aux3 = sepdots.split(item)
                if len(aux3) != 2:
                    continue
                dirtype = sepspace.split(aux3[1].strip(),maxsplit=1)
                typesize = 1
                if "std_logic_vector" in dirtype[1].lower():
                    auxx = re.search(r"(\d+)\s.*?\s(\d+)",dirtype[1])
                    if (auxx is None) or (len(auxx.groups()) < 2):
                        return "Error: Fail parsing " + dirtype[1] + "."
                    typesize = int(auxx.group(1)) - int(auxx.group(2)) 
                    if typesize < 0: typesize = -typesize
                    typesize = typesize+1
                aux4 = sepcomma.split(aux3[0])
                for pp in aux4:
                    ppp = pp.strip().upper()
                    if ppp not in validportkeys:
                        return f"Error: {pp} is not a valid port for a top level entity. You have to use the Mapper or SW, LEDR, KEY and HEX as port names."
                    if validports[ppp][1] < typesize:
                        return f"Error: Port {pp} has more bits than the corresponding Emulator port length."
                    foundports.append(ppp)
                    foundsizes.append(typesize)
                    founddifs.append(validports[ppp][1]-typesize)
        except:
            return "Error parsing usertop ports."
        if len(foundports) == 0:
            return "Error: ports not found."
        portmaptxt = "port map("
        for port,tsize,dif in zip(foundports,foundsizes,founddifs):
            
            if (tsize == 1) or (dif == 0):
                portmaptxt = portmaptxt + f"{port} => {port},"
            else:              
                portmaptxt = portmaptxt + f'{port}({tsize-1} downto 0) => {port}({tsize-1} downto 0),'
        portmaptxt = portmaptxt[:-1] + ");"
    
    fpgatest = open(fpgatestfile, 'w')
    fpgatest.write(fpgatesttemplate.replace('{{portmap}}',portmaptxt).replace('{{toplevelentity}}',toplevelentity))
    fpgatest.close()
    return "Ok!"


def getportlist(sessionpath,file):
    toplevel = Path(sessionpath,file)
    if not toplevel.exists(): return f"Error: Top level entity not found.";
    toplevel = open(toplevel, 'r')    
    data = toplevel.read()
    data = re.sub("--.*?\n|\n"," ",data)
    data = re.sub("\s+"," ",data)
    data = re.sub("\s+;",";",data)
    toplevel.close()
    entityname = re.search(r"entity (\w+) is",data,re.IGNORECASE)
    if entityname is None: 
        return "Error: entity not found in usertop."
    entityname = entityname.group(1)
    aux = re.search(rf"entity {entityname} is(.*?)end entity;|entity {entityname} is(.*?)end {entityname};",data,re.IGNORECASE)
    if aux is None:
        return "Error: entity not found in usertop."
    aux = re.search(rf".*port.*?(\((.+)\))",aux.group(0),re.IGNORECASE)
    if aux is None:
        return "Error: ports not found in usertop."
    aux2 = re.split(";\s+|;",aux.group(1)[1:-1])
    sepdots = re.compile(r"\s+:\s+|\s+:|:\s+|:")
    sepcomma = re.compile(r"\s+,\s+|\s+,|,\s+|,")
    sepspace = re.compile(r"\s+")
    try:
        myports = []
        for item in aux2:
            aux3 = sepdots.split(item)
            if len(aux3) != 2:
                continue
            dirtype = sepspace.split(aux3[1].strip(),maxsplit=1)
            typesize = 1
            if "std_logic_vector" in dirtype[1].lower():
                auxx = re.search(r"(\d+)\s.*?\s(\d+)",dirtype[1])
                if (auxx is None) or (len(auxx.groups()) < 2):
                    return "Error: Fail parsing " + dirtype[1] + "."
                typesize = int(auxx.group(1)) - int(auxx.group(2)) 
                if typesize < 0: typesize = -typesize
                typesize = typesize+1
            aux4 = sepcomma.split(aux3[0])
            for pp in aux4:
                ppp = {'name':pp.strip().upper(),'typesize':typesize,'direction':dirtype[0].lower().strip()}
                myports.append(ppp)
        return myports
    except:
        #return "Error parsing usertop ports."
        return []

def getexistingportmap(sessionpath,file):
    mapfile = Path(sessionpath,file + ".map")
    if not mapfile.exists():
        return ["nomap"]
    else:
        with open(mapfile,'r') as ff:
            if len(ff.readline()) <= 2:
                data = ["disabled"]
            else:
                data = ["enabled"]
            for ll in ff:
                if ll.endswith('\n'):
                    ll = ll[:-1]
                dd = ll.split(':')
                dd = [dd[0]] + dd[1].split(',')
                data.append(dd)
            return data
        return ["nomap"]


# def createnewuser(basepath):
#     subdirs = list(basepath.glob("*"))
#     # print(subdirs)
#     candidate = newuserprefix + str(randrange(10000))
#     while candidate in subdirs:
#         candidate = newuserprefix + str(randrange(10000)) 
#     return candidate

def getvhdfilelist(sessionpath, sort=True):
    if sort:
        return list(sorted(sessionpath.glob("*.vhd"))) #+ list(sessionpath.glob("*.vhdl"))
    else:
        return list(sessionpath.glob("*.vhd"))

def logactivity(sessionpath,userid,message):
    with open(Path(sessionpath,'activity.log'),'a') as ff:
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")
        print(timestamp)
        ff.write(f"{userid}\t{timestamp}\t{message}\n")
        ff.close()


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

def compilefile(sessionpath,sid,mainpath,userid,toplevelentity="usertop"):
    socketio.emit("message",f'Top level entity is <strong style="color:red">{toplevelentity}</strong>.',namespace="/stream",room=sid)
    compilerpath = Path(mainpath,'backend','fpgacompileweb')
    # basepath = Path(mainpath,'work')
    # sessionpath = Path(basepath, username)
    retcode = createFpgaTest2(sessionpath,toplevelentity)
    if retcode == "Ok!":
        pass
    else:
        socketio.emit('errors', retcode, namespace="/stream", room=sid)
        # socketio.disconnect(namespace="/stream", room=sid)
        return
    # elif retcode == 2:   
    #     socketio.emit('errors', "Error finding top level entity (usertop).",namespace="/stream",room=sid)
    #     socketio.disconnect(namespace="/stream",room=sid)
    #     return
    # elif retcode == 3:   
    #     socketio.emit('errors', "Bad port names in usertop: port names do not match those from the emulator.",namespace="/stream",room=sid)
    #     socketio.disconnect(namespace="/stream",room=sid)
    #     return
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
        socketio.emit("errors",aux.decode('unicode_escape').replace('\n','\n<br>'),namespace="/stream",room=sid)
        logactivity(sessionpath,userid,f"Compilation of {toplevelentity} with errors.")
    else:
        socketio.emit("success","done",namespace="/stream",room=sid);
        logactivity(sessionpath,userid,f"Successful compilation of {toplevelentity}.")
    # socketio.disconnect(namespace="/stream",room=sid)

def analyzefile(sessionpath,sid,mainpath,filename,userid):
    compilerpath = Path(mainpath,'backend','analyze.sh')
    basepath = Path(mainpath,'work')
    # sessionpath = Path(basepath, username)    
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
        socketio.emit("errors",aux.decode('unicode_escape').replace('\n','\n<br>'),namespace="/stream",room=sid)
        logactivity(sessionpath,userid,"Analysis with errors.")
    else:
        socketio.emit("asuccess","done",namespace="/stream",room=sid)
        logactivity(sessionpath,userid,"Successful analysis.")

def simulatefile(sessionpath,sid,mainpath,stoptime,userid,simentity="usertest"):
    simulatorpath = Path(mainpath,'backend','simulate.sh')
    # basepath = Path(mainpath,'work')
    # sessionpath = Path(basepath, username)
    if "ns" not in stoptime:
        socketio.emit("errors","Simulator limitation: stop time must be in nano seconds.",namespace="/stream",room=sid)
        return    
    stoptime = re.sub("\s+","",stoptime)
    aux = re.sub("ns","",stoptime)
    try:
        if int(aux) > 1000:
            socketio.emit("errors","Simulator limitation: stop time must be at most 1000 ns.",namespace="/stream",room=sid)
            return
    except:
        socketio.emit("errors","Error parsing stop time.",namespace="/stream",room=sid)
    aux = list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))
    # cleanfilelist(sessionpath,'usertop.vhd',aux)
    filenames = [x.name for x in aux]
    proc = subprocess.Popen(
                [simulatorpath,sessionpath,stoptime,simentity] + filenames,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
        )
    rline = 'start'
    hasError = False
    errmsgs = ""
    while rline != b'':
        rline = proc.stdout.readline()
        if ":error:" in rline.decode():
            hasError = True
            errmsgs += rline.decode() + "\n"
        else:
            socketio.emit("message",rline.decode(),namespace="/stream",room=sid)
        socketio.sleep(0.1)
    aux = proc.stderr.read()
    if aux != b'':
        socketio.emit("errors",aux.decode('unicode_escape').replace('\n','\n<br>'),namespace="/stream",room=sid)
        logactivity(sessionpath,userid,"Simulation with errors.")
    elif hasError:
        socketio.emit("errors",errmsgs,namespace="/stream",room=sid)
        logactivity(sessionpath,userid,"Simluation with errors.")
    else:
        socketio.emit("success","done",namespace="/stream",room=sid)
        logactivity(sessionpath,userid,"Successful simulation.")


emulprocs = {}
fifowrite = {}
def doEmulation(username,sid,mainpath,sessionpath):
    keysprocs = emulprocs.keys()
    if len(keysprocs) >= 25:
        socketio.emit('error',f'Too many emulations running, please try again in a minute or two.',namespace="/emul",room=sid)
        return
    elif username in keysprocs:
        socketio.emit('error',f'Emulation already running for {username}.',namespace="/emul",room=sid)
        return
    else:
        socketio.emit('message','Emulation started.',namespace="/emul",room=sid)
    basepath = Path(mainpath,'work')
    # sessionpath = Path(basepath, username)
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

def getsocketiofile():
    socketiofile = 'socket.io.3.js'
    if pkg_resources.get_distribution("python-socketio").version.startswith('4'):
        socketiofile = 'socket.io.js'
    return socketiofile

def getghwhierarchy(sessionpath,mainpath,filename):
    ghwhpath = Path(mainpath,'backend','ghwhierarchy.sh')   
    proc = subprocess.Popen(
                [ghwhpath,sessionpath,filename],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
        )
    rline = 'START\n'
    aux = b'aa'
    while aux != b'':
        aux = proc.stdout.readline()
        rline = rline + aux.decode('unicode_escape')
    aux = proc.stderr.read()
    if aux != b'':
        return f"Error reading {filename}."
    # else:
    #     rline = rline + "END!"
    #     return rline    
    # print(rline)
    filedata = rline.split('\n')
    # print(filedata)
    parentstring = ""
    lastinstance = None
    baselevel = None
    lastlevel = 0
    parentlist = []
    hierarchy = {}

    for ll in filedata:

        lls = ll.lstrip(' ')
        level = len(ll) - len(lls)

        if lastinstance:         
            if (level == (lastlevel+1)):
                parentstring = parentstring + "." + lastinstance
                hierarchy[parentstring] = {}
            else:
                parentstring = ".".join(parentstring.split('.')[:level-baselevel+1])
        parentlist.append(parentstring)

        if lls.startswith('instance'):
            instnameaux = re.search(r"instance (\w+):",lls,re.IGNORECASE)
            if instnameaux is None: 
                return "Error: entity not found in usertop."
            if not baselevel:
                baselevel = level
            lastinstance = instnameaux.group(1)
        elif lls.startswith("signal") or lls.startswith("port-in") or lls.startswith("port-out"):
            parts = lls.split(": ") # separate type-name / datatype / index
            p1 = parts[0].split(" ") # separate type / name
            hierarchy[parentstring][p1[1]] = {'type': p1[0], 'datatype': parts[1], 'idxs': parts[2]}

        lastlevel = level
   
    return hierarchy
        

def getghwsignals(sessionpath,mainpath,filename,groups):
    ghwhpath = Path(mainpath,'backend','ghwgetsignals.sh')   
    proc = subprocess.Popen(
                [ghwhpath,sessionpath,filename],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
        )
    rline = ''
    aux = b'aa'
    while aux != b'':
        aux = proc.stdout.readline()
        rline = rline + aux.decode('unicode_escape')
    aux = proc.stderr.read()
    if aux != b'':
        return f"Error reading {filename}: {aux.decode('unicode_escape')}."
       
    filedata = rline.split('Time is ')
    # Identifying signals
    data = filedata[1].split("\n") 
    inittime = data[0].split(" ")[0]
    snames = []
    vcds = {}
    tempvals = []
    for dd in data[1:-1]:
        aux = dd.split(': ')
        snames.append(aux[0])
        vcds[aux[0]] = [inittime,aux[1].split(' ')[0]]
        tempvals.append(vcds[aux[0]][1])
    groupindexes = []
    for gg in groups:
        idxs = gg.split('-')
        aux = (snames.index(idxs[0]),snames.index(idxs[1]))
        groupindexes.append(aux)
        val = "".join(tempvals[aux[0]:aux[1]+1]).replace("'","")
        vcds[gg] = [inittime,val]

    for tframe in filedata[2:-1]:
        data = tframe.split("\n") 
        ftime = data[0].split(" ")[0]
        tempvals = []
        for dd in data[1:-1]:
            aux = dd.split(': ')
            val = aux[1].split(' ')[0]
            tempvals.append(val)
            if ftime == vcds[aux[0]][-2]:  # Check if current time is the same as the last one and updates recorded value
                vcds[aux[0]][-1] = val
            elif vcds[aux[0]][-1] != val:  # Check if there is a change regarding the last value. If so, records...
                vcds[aux[0]].append(ftime)
                vcds[aux[0]].append(val)            
        for gg,aux in zip(groups,groupindexes):        
            val = "".join(tempvals[aux[0]:aux[1]+1]).replace("'","")
            if ftime == vcds[gg][-2]:  # Check if current time is the same as the last one and updates recorded value
                vcds[gg][-1] = val
            elif vcds[gg][-1] != val:  # Check if there is a change regarding the last value. If so, records...
                vcds[gg].append(ftime)
                vcds[gg].append(val)

    # Last time frame:
    tframe = filedata[-1]
    data = tframe.split("\n") 
    ftime = data[0].split(" ")[0]
    tempvals = []
    for dd in data[1:-1]:
        aux = dd.split(': ')
        val = aux[1].split(' ')[0]
        tempvals.append(val)
        if ftime == vcds[aux[0]][-2]:  # Check if current time is the same as the last one and updates recorded value
            vcds[aux[0]][-1] = val
        else:  # Check if there is a change regarding the last value. If so, records...
            vcds[aux[0]].append(ftime)
            vcds[aux[0]].append(val)
    for gg,aux in zip(groups,groupindexes):        
            val = "".join(tempvals[aux[0]:aux[1]+1]).replace("'","")
            if ftime == vcds[gg][-2]:  # Check if current time is the same as the last one and updates recorded value
                vcds[gg][-1] = val
            else:  # Check if there is a change regarding the last value. If so, records...
                vcds[gg].append(ftime)
                vcds[gg].append(val)

    return vcds