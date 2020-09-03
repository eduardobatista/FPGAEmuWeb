library ieee;
use ieee.std_logic_1164.all;

entity usertop is
port(
	KEY:		in std_logic_vector(3 downto 0);
	SW:		in std_logic_vector(17 downto 0);
	LEDR:		out std_logic_vector(17 downto 0);
	HEX0,HEX1,HEX2,HEX3,HEX4,HEX5,HEX6,HEX7	: out std_logic_vector(6 downto 0)
	);
end usertop;

architecture rtl of usertop is
begin
    
    LEDR(0) <= SW(0);
    LEDR(1) <= SW(1);
    LEDR(2) <= SW(2);
    LEDR(3) <= SW(3);
    
    LEDR(16) <= KEY(0);
    LEDR(17) <= KEY(1);
    
    HEX3 <= "0010010";
    HEX2 <= "0000000";
    HEX1 <= "1000000";
    HEX0 <= "0010010";

end rtl;
