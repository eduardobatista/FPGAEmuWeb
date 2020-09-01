library ieee;
use ieee.std_logic_1164.all;

entity usertop is
port(
	CLOCK_50:	in std_logic;
	CLK_500Hz:	in std_logic;
	RKEY:		in std_logic_vector(3 downto 0);
	KEY:		in std_logic_vector(3 downto 0);
	RSW:		in std_logic_vector(17 downto 0);
	SW:		in std_logic_vector(17 downto 0);
	LEDR:		out std_logic_vector(17 downto 0);
	HEX0,HEX1,HEX2,HEX3,HEX4,HEX5,HEX6,HEX7	: out std_logic_vector(6 downto 0)
	);
end usertop;

architecture rtl of usertop is

    signal Y0: std_logic;

    component xorr is
        port (A: in std_logic;
              B: in std_logic;
              Y: out std_logic);
    end component; 

begin

    X1: xorr port map (SW(0),SW(1),Y0); 

    LEDR(17 downto 2) <= SW(17 downto 2);
    LEDR(1) <= KEY(2);
    LEDR(0) <= Y0;
    HEX7 <= "1111111";
    HEX6 <= "1111111";
    HEX5 <= "1111111";
    HEX4 <= "1111111";
    HEX3 <= "0010010";
    HEX2 <= "1111001";
    HEX1 <= "1000000";
    HEX0 <= "0010010";

end rtl;
