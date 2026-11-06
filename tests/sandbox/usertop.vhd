library ieee;
use ieee.std_logic_1164.all;
entity usertop is
  port (SW : in std_logic_vector(17 downto 0); LEDR : out std_logic_vector(17 downto 0));
end usertop;
architecture a of usertop is
  type st is (idle, run);
  signal s : st := idle;
begin
  LEDR <= SW;
  process (SW(0)) begin
    if rising_edge(SW(0)) then
      case s is
        when idle => s <= run;
        when run => s <= idle;
      end case;
    end if;
  end process;
end a;
