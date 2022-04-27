import re,socket,time,subprocess,select,os,shutil
from datetime import datetime
from random import randrange
from pathlib import Path
import pkg_resources

from appp import socketio,logger,celery


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
    signal KEY:            std_logic_vector(3 downto 0) := "1111";
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
   SW <= inbytes(17 downto 0); 
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

validports = {'CLOCK_50':['in',1], 
              'CLK_500HZ':['in',1], 
              'CLK_1HZ':['in',1],
              'CLK_10HZ':['in',1],
              'KEY':['in',4],
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


def createFpgaTest2(sessionpath,temppath,toplevelentity):
    toplevel = Path(sessionpath,toplevelentity + ".vhd")
    if not toplevel.exists(): return f"Error: Top level entity not found.";
    fpgatestfile = Path(temppath,'fpgatest.aux')
    if fpgatestfile.exists(): fpgatestfile.unlink()

    try:
    
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
                            return f"Error: {pp} is not a valid port for a top level entity. You have to use the Mapper or SW, LEDR, KEY, HEX0, HEX1, etc as port names."
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
    
    except BaseException as err:
        return f"Error: {err}."


def getportlist(sessionpath,file):
    toplevel = Path(sessionpath,file)
    if not toplevel.exists(): 
        return f"Error: Top level entity not found."
    
    try:
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
            # print(myports)
            return myports
        except:
            #return "Error parsing usertop ports."
            return []

    except BaseException as err:
        return f"Error: {err}."

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

def getdirlist(sessionpath, sort=True):
    if sort:
        dirlist = [dd for dd in sessionpath.iterdir() if dd.is_dir()]
        return list(sorted(dirlist,key=lambda x: str.lower(x.name)))
    else:
        return dirlist        

def getvhdfilelist(sessionpath, sort=True, recursive=False):
    if recursive:
        if sort:
            return list(sorted(sessionpath.rglob("*.vhd"),key=lambda x: (x.relative_to(sessionpath).parent,str.lower(x.name))))
        else:
            return list(sessionpath.rglob("*.vhd"))
    else:
        if sort:
            return list(sorted(sessionpath.glob("*.vhd"),key=lambda x: str.lower(x.name))) #+ list(sessionpath.glob("*.vhdl"))
        else:
            return list(sessionpath.glob("*.vhd"))


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

def compilefile(sessionpath,mainpath,userid,toplevelentity="usertop"):
    socketio.emit("message",f'Top level entity is <strong style="color:red">{toplevelentity}</strong>.',namespace="/stream",room=userid)
    compilerpath = Path(mainpath,'backend','fpgacompileweb')
    curproject = ""
    temppath = Path(mainpath,"temp",userid)
    if "/" in toplevelentity:
        aux = toplevelentity.split("/")
        toplevelentity = aux[1]
        curproject = aux[0]  
        temppath = temppath / curproject 
        sessionpath = sessionpath / curproject
    temppath.mkdir(parents=True,exist_ok=True)
    retcode = createFpgaTest2(sessionpath,temppath,toplevelentity)
    if retcode == "Ok!":
        pass
    else:
        socketio.emit('errors', retcode, namespace="/stream", room=userid)
        return
    aux = list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))
    # cleanfilelist(sessionpath,'usertop.vhd',aux)
    filenames = [str(x) for x in aux]
    proc = subprocess.Popen(
                [compilerpath,temppath] + filenames + ['fpgatest.aux'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
        )
    rline = 'start'
    socketio.emit("message",'Compiling...',namespace="/stream",room=userid)
    socketio.sleep(0.1)
    try:
        outs, errs = proc.communicate(timeout=15)
        socketio.emit("message",outs.decode('unicode_escape').replace('\n','\n<br>'),namespace="/stream",room=userid)
        socketio.sleep(0.1)
        errstring = errs.decode('unicode_escape').replace('\n','\n<br>')
        errstring = errstring.replace(str(Path(filenames[0]).parent) + "/","")
        if errstring != "":            
            socketio.emit("errors",errstring,namespace="/stream",room=userid)
            logger.info(f"{userid}: Compilation of {toplevelentity} with errors.")
        else: 
            socketio.emit("success","done",namespace="/stream",room=userid)
            logger.info(f"{userid}: Successful compilation of {toplevelentity}.")
    except Exception as ex: # TimeoutExpired
        socketio.emit("errors",str(ex),namespace="/stream",room=userid)
    proc.kill()
    outs, errs = proc.communicate()


def analyzefile(sessionpath,mainpath,filename,userid):
    compilerpath = Path(mainpath,'backend','analyze.sh')
    proc = subprocess.Popen(
                [compilerpath,sessionpath,filename],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
        )
    rline = 'start'
    socketio.emit("message",'Analyzing...',namespace="/stream",room=userid)
    socketio.sleep(0.1)
    try:
        outs, errs = proc.communicate(timeout=10)
        socketio.emit("message",outs.decode('unicode_escape').replace('\n','\n<br>'),namespace="/stream",room=userid)
        socketio.sleep(0.1)
        errstring = errs.decode('unicode_escape').replace('\n','\n<br>')
        if errstring != "":            
            socketio.emit("errors",errstring,namespace="/stream",room=userid)
            logger.info(f"{userid}: Analysis of {filename} with errors.")
        else: 
            socketio.emit("asuccess","done",namespace="/stream",room=userid)
            logger.info(f"{userid}: Successful analysis of {filename}.")
    except Exception as ex: # TimeoutExpired
        socketio.emit("errors",str(ex),namespace="/stream",room=userid)    
    proc.kill()    
    outs, errs = proc.communicate()


def simulatefile(sessionpath,mainpath,stoptime,userid,simentity="usertest",curproject=""):
    simulatorpath = Path(mainpath,'backend','simulate.sh')
    if curproject == "":
        temppath = Path(mainpath,"temp",userid)
    else:
        temppath = Path(mainpath,"temp",userid,curproject)
    temppath.mkdir(parents=True,exist_ok=True)
    if "ns" not in stoptime:
        socketio.emit("errors","Simulator limitation: stop time must be in nano seconds.",namespace="/stream",room=userid)
        return    
    stoptime = re.sub("\s+","",stoptime)
    aux = re.sub("ns","",stoptime)
    try:
        if int(aux) > 2000:
            socketio.emit("errors","Simulator limitation: stop time must be at most 2000 ns.",namespace="/stream",room=userid)
            return
    except:
        socketio.emit("errors","Error parsing stop time.",namespace="/stream",room=userid)    
    aux = list((sessionpath / curproject).glob("*.vhd"))
    # cleanfilelist(sessionpath,'usertop.vhd',aux)
    filenames = [str(x) for x in aux]
    proc = subprocess.Popen(
                [simulatorpath,temppath,stoptime,simentity] + filenames,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
        )
    rline = 'start'
    socketio.emit("message",'Running simulation...',namespace="/stream",room=userid)
    socketio.sleep(0.1)
    hasError = False
    errmsgs = ""
    try:
        outs, errs = proc.communicate(timeout=15)
        outstring = outs.decode('unicode_escape').replace('\n','\n<br>')
        if ":error:" in outstring:
            hasError = True
            errmsgs = outstring
        else:
            socketio.emit("message",outstring,namespace="/stream",room=userid)
            socketio.sleep(0.1)
        errstring = errs.decode('unicode_escape').replace('\n','\n<br>')
        errstring = errstring.replace(str(Path(filenames[0]).parent) + "/","")
        if errstring != "":
            socketio.emit("errors",errstring,namespace="/stream",room=userid)
            logger.info(f"{userid}: Simulation of {simentity} with errors.")            
        elif hasError:
            socketio.emit("errors",errmsgs,namespace="/stream",room=userid)
            logger.info(f"{userid}: Simulation of {simentity} with errors.")
        else:
            if curproject != "":
                destfile = temppath.parent  / "output.ghw"
                if destfile.exists():
                    destfile.unlink()
                shutil.move(temppath / "output.ghw", destfile)
            socketio.emit("success","done",namespace="/stream",room=userid)
            logger.info(f"{userid}: Successful simulation of {simentity}.")
    except Exception as ex: # TimeoutExpired
        socketio.emit("errors",str(ex),namespace="/stream",room=userid)
    proc.kill()
    outs, errs = proc.communicate()


emulprocs = {}
fifowrite = {}
def doEmulation(username,mainpath,curproject="",toplevelentity=""):
    temppath = Path(mainpath,'temp',username)
    if curproject != "":
        temppath = temppath / curproject
    keysprocs = emulprocs.keys()
    if len(keysprocs) >= 25:
        socketio.emit('error',f'Too many emulations running, please try again in a minute or two.',namespace="/emul",room=username)
        socketio.emit('status','Parado',namespace="/emul", room=username)
        return
    elif username in keysprocs:
        socketio.emit('error',f'Emulation already running for {username}.',namespace="/emul",room=username)
        socketio.emit('status','Parado',namespace="/emul", room=username)
        return        
    try: 
        for k in temppath.rglob("myfifo*"):
            k.unlink();
    except Exception as ex:
        pass
    fpgatestpath = Path(temppath,'fpgatest')
    if not fpgatestpath.exists():
        socketio.emit('error',f'Compilation required before emulation.',namespace="/emul",room=username)
        socketio.emit('status','Parado',namespace="/emul", room=username)
        return
    logger.info(f"{username}: Starting emulation.")
    try:
        proc = subprocess.Popen(
                    [fpgatestpath],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=temppath 
            )
        emulprocs[username] = proc
        socketio.sleep(0.2)  

        fiforead = os.open(Path(temppath,'myfifo'+str(proc.pid)), os.O_RDONLY | os.O_NONBLOCK)
        # poller = select.epoll()
        poller = select.poll()
        poller.register(fiforead)
        poller.poll()
        os.read(fiforead,3).decode()
        socketio.sleep(0.2)
        fifowrite[username] = os.open(Path(temppath,'myfifo2'+str(proc.pid)), os.O_WRONLY | os.O_NONBLOCK) 
        lasttime = time.time()    
        run = True
        socketio.emit('message',f'Emulation of <strong>{toplevelentity}</strong> started.',namespace="/emul",room=username)
        socketio.emit('started','Ok!',namespace="/emul",room=username)
        # print("Running!!!!") 
        while run:
            events = poller.poll(50) 
            # print(events)
            if (len(events) > 0):   
                # logger.info(f"Event: {events[0][1]} - {select.POLLHUP}.{select.POLLERR}.{select.POLLNVAL}.{select.POLLRDHUP}.")             
                if (events[0][1] & (select.POLLHUP | select.POLLERR | select.POLLNVAL | select.POLLRDHUP | select.POLLOUT)) != 0:
                    run = False
                elif (events[0][1] & select.POLLIN) != 0:
                    data = os.read(fiforead,11)
                    socketio.emit('bytes', data, namespace="/emul", room=username)
                    lasttime = time.time()
            else:
                if ((time.time()-lasttime) >= 120 ):
                    socketio.emit('error','Inactivity timeout...',namespace="/emul", room=username)                
                    run = False
            socketio.sleep(0.1)
    except FileNotFoundError as err:
        socketio.emit('error','Error opening pipe.',namespace="/emul", room=username)  
    except Exception as ex:
        logger.error("Emulation crash:" + str(ex))
        socketio.emit('error',"Emulation crashed at the beginning. Check your code, especially regarding bounds and indices of ports and signals.",namespace="/emul", room=username)   
    except:
        logger.error("Unexpected error:", sys.exc_info()[0])
    closeEmul(username)
    socketio.emit('status','Parado',namespace="/emul", room=username)
    poller.unregister(fiforead)
    if username in fifowrite.keys():
        os.close(fifowrite[username])
        del fifowrite[username]
    os.close(fiforead)
    # socketio.disconnect(namespace="/emul",room=username)

def stopEmulation(username):
    if username not in emulprocs.keys():
        socketio.emit('error',f'Emulation not running for {username}.',namespace="/emul", room=username)
        return
    else:
        logger.info(f"{username}: Stopping emulation.")
        closeEmul(username)
        socketio.emit('status',"Parado",namespace="/emul", room=username)

def closeEmul(username):
    if username in emulprocs.keys():
        # emulprocs[username].kill()
        emulprocs[username].terminate()
        del emulprocs[username]

def getsocketiofile():
    socketiofile = 'socket.io.3.js'
    if pkg_resources.get_distribution("python-socketio").version.startswith('4'):
        socketiofile = 'socket.io.js'
    return socketiofile

def getghwhierarchy(username,mainpath,filename):
    ghwhpath = Path(mainpath,'backend','ghwhierarchy.sh')   
    temppath = Path(mainpath,'temp',username)
    proc = subprocess.Popen(
                [ghwhpath,temppath,filename],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
        )
    rline = 'START\n'
    try:
        outs, errs = proc.communicate(timeout=10)
        errstring = errs.decode('unicode_escape') #.replace('\n','\n<br>') 
        if errstring != "":
            proc.kill()
            outs, errs = proc.communicate()
            return f"Error 1 reading {filename}."
        else:
            rline = rline + outs.decode('unicode_escape')
    except Exception as ex:
        proc.kill()
        outs, errs = proc.communicate()
        return f"Error 2 reading {filename}."
    proc.kill()
    outs, errs = proc.communicate()

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
        

def getghwsignals(username,mainpath,filename,groups):
    ghwhpath = Path(mainpath,'backend','ghwgetsignals.sh')   
    temppath = Path(mainpath,'temp',username)
    proc = subprocess.Popen(
                [ghwhpath,temppath,filename],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
        )
    rline = ''
    try:
        outs, errs = proc.communicate(timeout=10)
        errstring = errs.decode('unicode_escape') #.replace('\n','\n<br>') 
        if errstring != "":
            proc.kill()
            outs, errs = proc.communicate()
            return f"Error 1 reading {filename}."
        else:
            rline = rline + outs.decode('unicode_escape')
    except Exception as ex:
        proc.kill()
        outs, errs = proc.communicate()
        return f"Error 2 reading {filename}."
    proc.kill()
    outs, errs = proc.communicate()
       
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