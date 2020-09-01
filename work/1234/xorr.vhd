library ieee;
use ieee.std_logic_1164.all;

entity xorr is
port(
    	A:	in std_logic;
    	B:	in std_logic;
    	Y:  out std_logic
	);
end xorr;

architecture rtl of xorr is

begin

    Y <= A xor B;

end rtl;