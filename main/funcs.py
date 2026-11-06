import re
import time
import subprocess
import select
import os
import secrets
import shutil
import stat
import sys
from pathlib import Path

from appp import socketio,logger
from . import sandbox
from .sandbox import SandboxError


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
    try:

        portlist = getportlist(sessionpath,toplevelentity + ".vhd")
        if type(portlist) == str:
            return portlist
        elif type(portlist) != list:
            return "Error: ports could not be identified in {toplevelentity}.vhd."
        
        existingpmap = getexistingportmap(sessionpath,toplevelentity + ".vhd")
    
        portmaptxt = None
        mapfile = Path(sessionpath,toplevelentity + ".vhd.map")
        if existingpmap[0] != "nomap": #mapfile.exists():
            # Checking portmap coherence: 
            if (len(existingpmap)-1) != len(portlist):
                return "Error: incoherent port mapping, use the Mapper to fix it."
            for port in portlist:
                portok = False
                for emap in existingpmap[1:]:
                    if port['name'].upper() == emap[0].upper():
                        if (port['typesize'] == 1) and (len(emap) == 3):
                            portok = True
                        if (port['typesize'] > 1 ) and (len(emap) == 4):
                            if (int(emap[2])-int(emap[3])+1) == port['typesize']:  
                               portok = True
                        break
                if not portok:
                    return f"Error: incoherent port mapping for port {port['name']}."
            ff = open(mapfile,'r')
            portmap = ff.readline()
            if len(portmap) > 2:
                portmaptxt = "port map(" + portmap + ");"

        if not portmaptxt:
            portmaptxt = "port map("
            for port in portlist:
                if port["name"].strip().upper() not in validports.keys():
                    return f"Error: Port {port['name']} cannot be mapped automatically. Mapper is required."
                dif = validports[port["name"].strip().upper()][1] - port["typesize"]
                if (port['typesize'] == 1) or (dif == 0):
                    portmaptxt = portmaptxt + f" {port['name']} => {port['name']},"
                else:
                    portmaptxt = portmaptxt + f" {port['name']}({port['typesize']-1} downto 0) => {port['name']}({port['typesize']-1} downto 0),"
            portmaptxt = portmaptxt[:-1] + ");"

        sandbox.write_job_file(temppath, 'fpgatest.aux',
                               fpgatesttemplate.replace('{{portmap}}',portmaptxt).replace('{{toplevelentity}}',toplevelentity).encode())
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
        data = re.sub(r"\s+"," ",data)
        data = re.sub(r"\s+;",";",data)
        toplevel.close()
        entityname = re.search(r"entity (\w+) is",data,re.IGNORECASE)
        if entityname is None: 
            return "Error: entity not found in file."
        entityname = entityname.group(1)
        aux = re.search(rf"entity {entityname} is(.*?)end entity;|entity {entityname} is(.*?)end {entityname};",data,re.IGNORECASE)
        if aux is None:
            return "Error: entity not found in file."
        aux = re.search(rf".*port.*?(\((.+)\))",aux.group(0),re.IGNORECASE)
        if aux is None:
            return "Error: ports not found in entity."
        aux2 = re.split(r";\s+|;",aux.group(1)[1:-1])
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

def tempdir(mainpath):
    return Path(mainpath,"temp")

def gettemppath(mainpath,userid,clear=True):
    """Job directory of the user's build, emptied. See sandbox.py: the user's code writes there."""
    return sandbox.reset_user_build(tempdir(mainpath),userid)

def cleanmsg(data):
    """Tool output for the page, without the job's paths (the copy of the sources is in .src)."""
    return data.decode('unicode_escape').replace(sandbox.SRC_DIR + "/","").replace('\n','\n<br>')

def compilefile(sessionpath,mainpath,userid,toplevelentity="usertop"):
    socketio.emit("message",f'Top level entity is <strong style="color:red">{toplevelentity}</strong>.',namespace="/stream",room=userid)
    compilerpath = Path(mainpath,'backend','fpgacompileweb')
    curproject = ""
    temppath = gettemppath(mainpath,userid)
    if "/" in toplevelentity:
        aux = toplevelentity.split("/")
        toplevelentity = aux[1]
        curproject = aux[0]  
        sessionpath = sessionpath / curproject
    proc = None
    try:
        temppath = sandbox.project_dir(temppath,curproject)
        retcode = createFpgaTest2(sessionpath,temppath,toplevelentity)
        if retcode != "Ok!":
            socketio.emit('errors', retcode, namespace="/stream", room=userid)
            return
        aux = list(sessionpath.glob("*.vhd")) + list(sessionpath.glob("*.vhdl"))
        filenames = sandbox.stage_sources(aux,temppath)
        proc = sandbox.start("tool",[compilerpath,'.'] + filenames + ['fpgatest.aux'],temppath,timeout=20)
        socketio.emit("message",'Compiling...',namespace="/stream",room=userid)
        socketio.sleep(0.1)
        outs, errs = proc.communicate(timeout=15)
        socketio.emit("message",cleanmsg(outs),namespace="/stream",room=userid)
        socketio.sleep(0.1)
        errstring = cleanmsg(errs)
        if errstring != "":            
            socketio.emit("errors",errstring,namespace="/stream",room=userid)
            logger.info(f"{userid}: Compilation of {toplevelentity} with errors.")
        else: 
            socketio.emit("success","done",namespace="/stream",room=userid)
            logger.info(f"{userid}: Successful compilation of {toplevelentity}.")
    except SandboxError as ex:
        logger.error(f"Sandbox: {ex}")
        socketio.emit("errors",f"Compilation is unavailable: {ex}.",namespace="/stream",room=userid)
    except Exception as ex: # TimeoutExpired
        socketio.emit("errors",str(ex),namespace="/stream",room=userid)
    finally:
        if proc:
            proc.kill()


def analyzefile(sessionpath,mainpath,filename,userid):
    temppath = gettemppath(mainpath,userid)
    compilerpath = Path(mainpath,'backend','analyze.sh')
    source = Path(sessionpath,filename).absolute()
    proc = None
    try:
        files = sandbox.stage_sources([source],temppath)
        if not files:
            socketio.emit("errors",f"File {source.name} not found.",namespace="/stream",room=userid)
            return
        proc = sandbox.start("tool",[compilerpath,'.',files[0]],temppath,timeout=15)
        socketio.emit("message",'Analyzing...',namespace="/stream",room=userid)
        socketio.sleep(0.1)
        outs, errs = proc.communicate(timeout=10)
        socketio.emit("message",cleanmsg(outs),namespace="/stream",room=userid)
        socketio.sleep(0.1)
        errstring = cleanmsg(errs)
        if errstring != "":            
            socketio.emit("errors",errstring,namespace="/stream",room=userid)
            logger.info(f"{userid}: Analysis of {filename} with errors.")
        else: 
            socketio.emit("asuccess","done",namespace="/stream",room=userid)
            logger.info(f"{userid}: Successful analysis of {filename}.")
    except SandboxError as ex:
        logger.error(f"Sandbox: {ex}")
        socketio.emit("errors",f"Analysis is unavailable: {ex}.",namespace="/stream",room=userid)
    except Exception as ex: # TimeoutExpired
        socketio.emit("errors",str(ex),namespace="/stream",room=userid)
    finally:
        if proc:
            proc.kill()


def simulatefile(sessionpath,mainpath,stoptime,userid,simentity="usertest",curproject=""):
    simulatorpath = Path(mainpath,'backend','simulate.sh')
    temppath = gettemppath(mainpath,userid)
    if "ns" not in stoptime:
        socketio.emit("errors","Simulator limitation: stop time must be in nano seconds.",namespace="/stream",room=userid)
        return    
    stoptime = re.sub(r"\s+","",stoptime)
    aux = re.sub("ns","",stoptime)
    try:
        if int(aux) > 2000:
            socketio.emit("errors","Simulator limitation: stop time must be at most 2000 ns.",namespace="/stream",room=userid)
            return
    except:
        socketio.emit("errors","Error parsing stop time.",namespace="/stream",room=userid)    
        return
    proc = None
    try:
        temppath = sandbox.project_dir(temppath,curproject)
        filenames = sandbox.stage_sources((sessionpath / curproject).glob("*.vhd"),temppath)
        proc = sandbox.start("sim",[simulatorpath,'.',stoptime,simentity] + filenames,temppath,timeout=20)
        socketio.emit("message",'Running simulation...',namespace="/stream",room=userid)
        socketio.sleep(0.1)
        hasError = False
        errmsgs = ""
        outs, errs = proc.communicate(timeout=15)
        outstring = cleanmsg(outs)
        if ":error:" in outstring:
            hasError = True
            errmsgs = outstring
        else:
            socketio.emit("message",outstring,namespace="/stream",room=userid)
            socketio.sleep(0.1)
        errstring = cleanmsg(errs)
        if errstring != "":
            socketio.emit("errors",errstring,namespace="/stream",room=userid)
            logger.info(f"{userid}: Simulation of {simentity} with errors.")            
        elif hasError:
            socketio.emit("errors",errmsgs,namespace="/stream",room=userid)
            logger.info(f"{userid}: Simulation of {simentity} with errors.")
        else:
            # The web app serves this copy, in a place the user's code cannot touch.
            sandbox.copy_output(temppath,"output.ghw",sandbox.user_private_dir(tempdir(mainpath),userid) / "output.ghw")
            socketio.emit("success","done",namespace="/stream",room=userid)
            logger.info(f"{userid}: Successful simulation of {simentity}.")
    except SandboxError as ex:
        logger.error(f"Sandbox: {ex}")
        socketio.emit("errors",f"Simulation is unavailable: {ex}.",namespace="/stream",room=userid)
    except subprocess.TimeoutExpired as ex:
        socketio.emit("errors",str(ex),namespace="/stream",room=userid)
        logger.info(f"{userid}: Simulation of {simentity} with errors.")
    except Exception as ex: # TimeoutExpired
        socketio.emit("errors",str(ex),namespace="/stream",room=userid)
        logger.info(f"{userid}: Simulation of {simentity} with errors.")    
    finally:
        if proc:
            proc.kill()


emulprocs = {}
fifowrite = {}
def doEmulation(username,mainpath,curproject="",toplevelentity=""):
    keysprocs = emulprocs.keys()
    if len(keysprocs) >= 25:
        socketio.emit('error',f'Too many emulations running, please try again in a minute or two.',namespace="/emul",room=username)
        socketio.emit('status','Parado',namespace="/emul", room=username)
        return
    elif username in keysprocs:
        socketio.emit('error',f'Emulation already running for {username}.',namespace="/emul",room=username)
        socketio.emit('status','Parado',namespace="/emul", room=username)
        return        
    build = sandbox.user_build(tempdir(mainpath),username,create=False)
    temppath = None
    if build is not None:
        try:
            temppath = sandbox.project_dir(build,curproject)
        except SandboxError:
            pass
    try:
        if temppath is None or not stat.S_ISREG(os.lstat(temppath / 'fpgatest').st_mode):
            raise FileNotFoundError
    except OSError:
        socketio.emit('error',f'Compilation required before emulation.',namespace="/emul",room=username)
        socketio.emit('status','Parado',namespace="/emul", room=username)
        return
    logger.info(f"{username}: Starting emulation.")
    fiforead = None
    poller = None
    try:
        for k in os.listdir(temppath):
            if k.startswith("myfifo"):
                os.unlink(temppath / k)
        # myfifo<id> (emulator -> page) and myfifo2<id> (page -> emulator). In the sandbox the
        # emulator cannot tell its PID to this process, so it is told the id. Both ends are opened
        # here, before it starts: from then on, what the job does to these names does not matter.
        fifoid = secrets.randbelow(900000000) + 100000000
        fiforead = sandbox.open_fifo(sandbox.make_fifo(temppath,f'myfifo{fifoid}'),os.O_RDONLY)
        fifowrite[username] = sandbox.open_fifo(sandbox.make_fifo(temppath,f'myfifo2{fifoid}'),os.O_RDWR)
        proc = sandbox.start("emul",['./fpgatest'],temppath,env={"FPGAEMU_FIFO_ID":str(fifoid)},discard=True)
        emulprocs[username] = proc
        poller = select.poll()
        poller.register(fiforead)
        # Waits for the "ok" of init_gui(), which comes when the VHDL touches the first port.
        deadline = time.time() + 20
        while True:
            events = poller.poll(100)
            if (len(events) > 0) and ((events[0][1] & select.POLLIN) != 0):
                break
            if (proc.poll() is not None) or (time.time() >= deadline):
                raise RuntimeError("Emulator did not start.")
            socketio.sleep(0.05)
        os.read(fiforead,3).decode()
        lasttime = time.time()    
        run = True
        socketio.emit('message',f'Emulation of <strong>{toplevelentity}</strong> started.',namespace="/emul",room=username)
        socketio.emit('started','Ok!',namespace="/emul",room=username)
        while run:
            events = poller.poll(50) 
            if (len(events) > 0):   
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
    except SandboxError as ex:
        logger.error(f"Sandbox: {ex}")
        socketio.emit('error',f"Emulation is unavailable: {ex}.",namespace="/emul",room=username)
    except FileNotFoundError as err:
        socketio.emit('error','Error opening pipe.',namespace="/emul", room=username)  
    except Exception as ex:
        logger.error("Emulation crash:" + str(ex))
        socketio.emit('error',"Emulation crashed at the beginning. Check your code, especially regarding bounds and indices of ports and signals.",namespace="/emul", room=username)   
    except:
        logger.error("Unexpected error:", sys.exc_info()[0])
    closeEmul(username)
    socketio.emit('status','Parado',namespace="/emul", room=username)
    if poller and (fiforead is not None):
        poller.unregister(fiforead)
    if username in fifowrite.keys():
        os.close(fifowrite[username])
        del fifowrite[username]
    if fiforead is not None:
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
    # socketiofile = 'socket.io.3.js'
    # if pkg_resources.get_distribution("python-socketio").version.startswith('4'):
    socketiofile = 'socket.io.js'
    return socketiofile

def runghwdump(script,username,mainpath,filename):
    """Output of a ghwdump script on the user's simulation output, in a job with only a copy of it.
    None if it fails."""
    filename = Path(filename).name
    tdir = tempdir(mainpath)
    with sandbox.tempjob(tdir) as job:
        sandbox.write_job_file(job,filename,(tdir / username / filename).read_bytes())
        proc = sandbox.start("tool",[Path(mainpath,'backend',script),'.',filename],job,timeout=15)
        try:
            outs, errs = proc.communicate(timeout=10)
        finally:
            proc.kill()
    return None if errs.decode('unicode_escape') != "" else outs.decode('unicode_escape')

def getghwhierarchy(username,mainpath,filename):
    rline = 'START\n'
    try:
        aux = runghwdump('ghwhierarchy.sh',username,mainpath,filename)
        if aux is None:
            return f"Error 1 reading {filename}."
        rline = rline + aux
    except Exception as ex:
        return f"Error 2 reading {filename}."

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
    rline = ''
    try:
        aux = runghwdump('ghwgetsignals.sh',username,mainpath,filename)
        if aux is None:
            return f"Error 1 reading {filename}."
        rline = rline + aux
    except Exception as ex:
        return f"Error 2 reading {filename}."
       
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


def isTraversalSecure(filepath,mandatoryparent):
    try:
        filepath.resolve().relative_to(mandatoryparent.resolve())        
        return True
    except ValueError as ve:
        return False