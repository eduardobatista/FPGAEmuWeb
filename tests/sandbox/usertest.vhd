library ieee;
use ieee.std_logic_1164.all;
entity usertest is end usertest;
architecture t of usertest is
  signal sw, led : std_logic_vector(17 downto 0) := (others => '0');
begin
  d : entity work.usertop port map (SW => sw, LEDR => led);
  process begin
    wait for 10 ns; sw(0) <= '1';
    wait for 10 ns; sw(0) <= '0';
    report "SIM_OK";
    wait;
  end process;
end t;
