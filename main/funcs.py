import re,socket
from random import randrange
from pathlib import Path

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
    entityname = re.search(r"entity (\w+) is",data,re.IGNORECASE).group(1)
    if entityname is None: 
        return False
    aux = re.search(rf"(entity {entityname} is.*end entity|entity {entityname} is.*end {entityname})",data,re.IGNORECASE)
    if aux is None:
        return False
    foundports = re.findall(rf"{availableports}(:|,|\s)",aux.group(0),re.IGNORECASE)
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

def closeEmul(app, username):
    app.procs[username].terminate()
    del app.procs[username]