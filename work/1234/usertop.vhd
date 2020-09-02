library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity usertop is
    port (
        SW: in std_logic_vector (17 downto 0); -- bin:    in  std_logic_vector (7 downto 0);
        LEDR: out std_logic_vector (17 downto 0) -- bcd:    out std_logic_vector (11 downto 0)
    );
end usertop;

architecture struct of usertop is
    procedure add3 (signal bin: in  std_logic_vector (3 downto 0); 
                    signal bcd: out std_logic_vector (3 downto 0)) is
    variable is_gt_4:  std_logic;
    begin
        is_gt_4 := bin(3) or (bin(2) and (bin(1) or bin(0)));

        if is_gt_4 = '1' then
        -- if to_integer(unsigned (bin)) > 4 then
            bcd <= std_logic_vector(unsigned(bin) + "0011");
        else
            bcd <= bin;
        end if;
    end procedure;

    signal U0bin,U1bin,U2bin,U3bin,U4bin,U5bin,U6bin:
                std_logic_vector (3 downto 0);

    signal U0bcd,U1bcd,U2bcd,U3bcd,U4bcd,U5bcd,U6bcd:
                std_logic_vector (3 downto 0);       
begin
    U0bin <= '0' & SW (7 downto 5);
    U1bin <= U0bcd(2 downto 0) & SW(4);
    U2bin <= U1bcd(2 downto 0) & SW(3);
    U3bin <= U2bcd(2 downto 0) & SW(2);
    U4bin <= U3bcd(2 downto 0) & SW(1);

    U5bin <= '0' & U0bcd(3) & U1bcd(3) & U2bcd(3);
    U6bin <= U5bcd(2 downto 0) & U3bcd(3);

U0: add3(U0bin,U0bcd);

U1: add3(U1bin,U1bcd);

U2: add3(U2bin,U2bcd);

U3: add3(U3bin,U3bcd);

U4: add3(U4bin,U4bcd);

U5: add3(U5bin,U5bcd);

U6: add3(U6bin,U6bcd);

OUTP:
    LEDR(11 downto 0) <= '0' & '0' & U5bcd(3) & U6bcd & U4bcd & SW(0);

end architecture;