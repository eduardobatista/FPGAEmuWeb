#!/usr/bin/env python3
"""End-to-end test, run INSIDE a test container against the real app (see run.sh).
Users are fictional. Checks that the app works and that a malicious VHDL gets nothing."""
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
import socketio

BASE = "http://127.0.0.1:5000"
HERE = Path(__file__).resolve().parent
APP = Path("/home/fpgaemuweb")
ATTACKER = "aluno1@example.invalid"
VICTIM = "aluno2@example.invalid"
PASSWORD = "test-password-1"
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{str(detail)[:300]}]" if detail and not ok else ""), flush=True)


class User:
    def __init__(self, email):
        self.email = email
        self.http = requests.Session()
        self.http.post(BASE + "/signup", data={"email": email, "name": "Test", "password": PASSWORD})
        r = self.http.post(BASE + "/login", data={"email": email, "password": PASSWORD})
        self.logged = r.status_code == 200 and "/login" not in r.url
        self.log = []
        self.transcript = []     # everything received since the last clear(); wait() does not consume it
        self.sio = socketio.Client(http_session=self.http)
        for ns in ("/stream", "/emul"):
            for ev in ("message", "errors", "error", "success", "asuccess", "started", "status", "bytes", "ghwdata", "filesaved"):
                self.sio.on(ev, self._rec(ns, ev), namespace=ns)
        self.sio.connect(BASE, namespaces=["/stream", "/emul"], transports=["polling"])

    def _rec(self, ns, ev):
        def f(*a):
            self.log.append((ns, ev, a[0] if a else None))
            self.transcript.append(str(a[0]) if a else "")
        return f

    def wait(self, ns, evs, timeout=40):
        end = time.time() + timeout
        while time.time() < end:
            for i, (n, e, d) in enumerate(self.log):
                if n == ns and e in evs:
                    del self.log[:i + 1]
                    return e, d
            time.sleep(0.05)
        return None, None

    def alltext(self):
        return "\n".join(self.transcript)

    def clear(self):
        self.log.clear()
        self.transcript.clear()

    def save(self, name, text):
        self.sio.emit("savefile", {"filename": f"proj/{name}", "data": text}, namespace="/stream")
        time.sleep(0.5)

    def project(self):
        self.sio.emit("createproject", {"projectname": "proj"}, namespace="/stream")
        time.sleep(0.5)

    def settop(self, name):
        return self.http.post(BASE + "/settoplevel", data={"toplevelfile": name})


def procs():
    """Command lines of all processes (the image has no ps)."""
    res = []
    for p in Path("/proc").iterdir():
        if p.name.isdigit():
            try:
                res.append((p / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace"))
            except OSError:
                pass
    return "\n".join(res)


def main():
    args = json.loads(os.environ["E2E_ARGS"])
    workdir, canaries = args["workdir"], args["canaries"]
    alice = User(ATTACKER)
    bob = User(VICTIM)
    check("login", alice.logged and bob.logged)

    # ---------------------------------------- normal use
    alice.project()
    bob.project()
    alice.save("usertop.vhd", (HERE / "usertop.vhd").read_text())
    alice.save("usertest.vhd", (HERE / "usertest.vhd").read_text())
    alice.settop("proj/usertop")
    alice.clear()
    alice.sio.emit("Analyze", "proj/usertop.vhd", namespace="/stream")
    ev, d = alice.wait("/stream", ("asuccess", "errors"))
    check("analysis", ev == "asuccess", d)
    if ev != "asuccess":
        print("The sandbox does not work: the attack results below would mean nothing.")
        return 1
    alice.sio.send("Compile", namespace="/stream")
    ev, d = alice.wait("/stream", ("success", "errors"), 60)
    check("compilation", ev == "success", d)

    alice.clear()
    alice.sio.send("Emular", namespace="/emul")
    ev, d = alice.wait("/emul", ("started", "error"), 40)
    check("emulation starts (FIFO)", ev == "started", d)
    if ev == "started":
        first = alice.wait("/emul", ("bytes",), 10)[0]
        check("emulation: output arrives", first == "bytes")
        alice.sio.emit("initstate", "x", namespace="/emul")
        alice.clear()
        alice.sio.emit("action", "s01", namespace="/emul")
        check("emulation: input changes output", alice.wait("/emul", ("bytes",), 10)[0] == "bytes")
        alice.sio.send("Parar", namespace="/emul")
        ev, d = alice.wait("/emul", ("status",), 15)
        check("emulation stops", ev == "status", d)
        time.sleep(1.5)
        check("emulation: job gone", "fpgatest" not in procs())

    alice.clear()
    alice.sio.emit("Simulate", ("500 ns", "proj/usertest.vhd"), namespace="/stream")
    ev, d = alice.wait("/stream", ("success", "errors"), 40)
    check("simulation", ev == "success", d)
    r = alice.http.get(BASE + "/output.ghw")
    check("simulation: download output.ghw", r.status_code == 200 and r.content[:8] == b"GHDLwave", r.status_code)
    alice.clear()
    alice.sio.emit("requestghwdata", namespace="/stream")
    ev, d = alice.wait("/stream", ("ghwdata",), 30)
    check("simulation: signals", ev == "ghwdata" and isinstance(d, list) and isinstance(d[1], dict) and any(k for k in d[1]), str(d)[:200])

    r = alice.http.get(BASE + "/diagram/data", params={"file": "proj/usertop.vhd", "entity": "usertop"}, timeout=200).json()
    check("block diagram", "rtl" in r and "blocks" in r, r.get("error"))
    r = alice.http.get(BASE + "/diagram/fsm", params={"file": "proj/usertop.vhd", "entity": "usertop"}, timeout=200).json()
    check("state diagram", "fsms" in r and len(r["fsms"]) == 1, r)
    check("job directories cleaned", len(list((APP / "temp" / ".jobs").iterdir())) <= 2 if os.access(APP / "temp/.jobs", os.R_OK) else True)

    # bob: a build of another user, to look for
    bob.save("usertop.vhd", (HERE / "usertop.vhd").read_text().replace("LEDR <= SW;", "LEDR <= SW; -- " + canaries["victim_build"]))
    bob.settop("proj/usertop")
    bob.sio.send("Compile", namespace="/stream")
    check("second user compiles", bob.wait("/stream", ("success", "errors"), 60)[0] == "success")

    # ---------------------------------------- attacks
    targets = {
        "SECKEY": f"{workdir}/seckeyb", "DIAGKEY": f"{workdir}/.diagkey", "DBFILE": f"{workdir}/dbb.sqlite",
        "OTHERUSER": f"{workdir}/{VICTIM}/proj/usertop.vhd", "CANARY": f"{workdir}/{args['canary_rel']}",
        "NFS_SECKEY": f"{APP}/work/seckeyb", "NFS_OTHER": f"{APP}/work/{args['canary_rel']}",
        "SHADOW": "/etc/shadow", "ENV": "/proc/1/environ", "SELFENV": "/proc/self/environ", "PASSWD": "/etc/passwd",
        "HUEY": f"{APP}/.worksync/huey.db", "WS": f"{APP}/.worksync/status.json",
        "OTHERTEMP": f"{APP}/temp/{VICTIM}/.buildtoken", "APPCODE": f"{APP}/start.py",
    }
    reads = "\n".join(f'    try_read("{k}", "{v}");' for k, v in targets.items())
    probe = ("sh -c '" + f"cd {APP}/temp 2>/dev/null && ls -a > /dev/null && echo LSOK; "
             f"for f in {workdir}/seckeyb {workdir}/.diagkey; do cat $f 2>/dev/null; done; "
             f"ls {workdir} 2>/dev/null; ls {APP}/temp/.jobs 2>/dev/null; "
             "id; "
             f"ln -s {workdir}/seckeyb pwn_symlink 2>&1; ls -la pwn_symlink 2>&1 | head -1; "
             "(python3 -S -c \"import socket;socket.socket()\" 2>&1 | tail -1); "
             "kill -9 1 2>&1; echo SHELL_DONE'")
    assert len(probe) < 890, len(probe)
    tb = (HERE / "attack_tmpl.vhd").read_text().replace("@READS@", reads).replace("@SHELL@", probe.replace('"', '""'))
    alice.save("attack.vhd", tb)
    alice.save("usertest.vhd", (HERE / "usertest.vhd").read_text())
    alice.clear()
    alice.sio.emit("Simulate", ("100 ns", "proj/attack.vhd"), namespace="/stream")
    alice.wait("/stream", ("success", "errors"), 60)
    time.sleep(1)
    r = alice.http.get(BASE + "/output.ghw")
    text = alice.alltext()
    print("---- attack output ----\n" + text[:4000].replace(VICTIM, "<victim>").replace(ATTACKER, "<attacker>") + "\n----")
    # What is sent to the user during the attack: full transcript kept in `seen`.
    seen = text
    # Without Landlock a job does see its own /proc/self/environ (clean: only PATH, HOME, TMPDIR, LANG).
    for k in ("SECKEY", "DIAGKEY", "DBFILE", "OTHERUSER", "CANARY", "NFS_SECKEY", "NFS_OTHER", "SHADOW", "ENV",
              "HUEY", "WS", "OTHERTEMP") + (() if args.get("mode") == "nolandlock" else ("SELFENV",)):
        check(f"textio cannot read {k}", f"LEAK {k}" not in seen)
    check("attack actually ran", "ATTACK_DONE" in seen or "DENIED" in seen, seen[:300])
    for name, value in canaries.items():
        check(f"no canary in any output: {name}", value not in seen)
    check("VHPIDIRECT socket() denied", "SOCKET_FD=-1" in seen, re.findall(r"SOCKET_FD=\S+", seen))
    check("no shell listing of keys", "FAKE" not in seen)
    check("symlink not created", "pwn_symlink ->" not in seen)
    check("app alive after attack", alice.http.get(BASE + "/login").status_code == 200)

    # ---------------------------------------- the same attacks through the diagrams: ghdl --synth
    # evaluates constants when elaborating, and that includes reading files with textio.
    def synth_attack(path):
        return f"""library ieee; use ieee.std_logic_1164.all; library std; use std.textio.all;
entity leak is port (a : in std_logic; b : out std_logic); end leak;
architecture x of leak is
  function rd return integer is
    file f : text; variable l : line; variable st : file_open_status; variable c : character; variable n : integer := 0;
  begin
    file_open(st, f, "{path}", read_mode);
    if st /= open_ok then return -1; end if;
    readline(f, l); read(l, c); file_close(f);
    return character'pos(c);
  end function;
  constant k : integer := rd;
  attribute dummy : string;
begin
  b <= '1' when k = 67 else a;   -- 67 is 'C' of CANARY
  assert k = -1 report "SYNTH_READ_OK value=" & integer'image(k) severity failure;
end x;
"""
    for name, path in (("other user's file", f"{workdir}/{args['canary_rel']}"), ("seckey", f"{workdir}/seckeyb")):
        alice.save("leak.vhd", synth_attack(path))
        time.sleep(0.3)
        r = alice.http.get(BASE + "/diagram/data", params={"file": "proj/leak.vhd", "entity": "leak"}, timeout=200).json()
        check(f"diagram: --synth cannot read {name}", "SYNTH_READ_OK" not in json.dumps(r), json.dumps(r)[:300])
    # Control: the same code does read a file that exists for it, so the check above means something.
    alice.save("leak.vhd", synth_attack(".src/usertop.vhd"))
    time.sleep(0.3)
    r = alice.http.get(BASE + "/diagram/data", params={"file": "proj/leak.vhd", "entity": "leak"}, timeout=200).json()
    check("diagram control: --synth does read a file it may read", "SYNTH_READ_OK" in json.dumps(r), json.dumps(r)[:300])
    alice.sio.emit("deletefile", "proj/leak.vhd", namespace="/stream")
    time.sleep(0.5)

    # ---------------------------------------- and inside the emulation
    evil_top = (HERE / "usertop.vhd").read_text()
    shell = ("sh -c 'id > emu_result; "
             f"cat {workdir}/seckeyb >> emu_result 2>&1; cat {workdir}/{args['canary_rel']} >> emu_result 2>&1; cat {workdir}/.diagkey >> emu_result 2>&1; "
             "bash -c \"exec 3<>/dev/tcp/127.0.0.1/5000 && echo EMU_NET_OPEN\" >> emu_result 2>&1; "
             "ls /proc/1 >> emu_result 2>&1; echo EMU_DONE >> emu_result'")
    evil_top = evil_top.replace("architecture a of usertop is", f"""architecture a of usertop is
  subtype cmd_t is string(1 to 900);
  function c_system(c: cmd_t) return integer;
  attribute foreign of c_system : function is "VHPIDIRECT system";
  function c_system(c: cmd_t) return integer is begin return -1; end;
  function pad(s: string) return cmd_t is
    variable r: cmd_t := (others => ' ');
  begin r(1 to s'length) := s; r(s'length+1) := character'val(0); return r; end;""").replace(
        "  LEDR <= SW;", '  process\n    variable rc: integer;\n  begin\n    rc := c_system(pad("' + shell.replace('"', '""') + '"));\n    wait;\n  end process;\n  LEDR <= SW;')
    alice.save("attack.vhd", (HERE / "usertest.vhd").read_text())
    alice.sio.emit("deletefile", "proj/attack.vhd", namespace="/stream")
    alice.save("usertop.vhd", evil_top)
    alice.clear()
    alice.sio.send("Compile", namespace="/stream")
    ev, d = alice.wait("/stream", ("success", "errors"), 60)
    check("malicious design compiles", ev == "success", d)
    alice.clear()
    alice.sio.send("Emular", namespace="/emul")
    ev, d = alice.wait("/emul", ("started", "error"), 40)
    check("malicious design emulates", ev == "started", d)
    time.sleep(4)
    found = list((APP / "temp/.jobs").rglob("emu_result"))
    res = found[0].read_text() if found else ""
    alice.sio.send("Parar", namespace="/emul")
    alice.wait("/emul", ("status",), 15)
    print("---- emulation attack ----\n" + res[:800] + "\n----")
    check("emulation: attack ran as the sandbox user", "uid=61002" in res and "EMU_DONE" in res, res[:200])
    check("emulation: no canary or key", not any(v in res for v in canaries.values()) and "FAKE" not in res, res[:300])
    check("emulation: no connection to the web app", "EMU_NET_OPEN" not in res and ("not permitted" in res or "unreachable" in res), res[:300])
    alice.save("usertop.vhd", (HERE / "usertop.vhd").read_text())

    # ---------------------------------------- planted output: symlink to the key, then download
    ghw_attack = (HERE / "attack_tmpl.vhd").read_text().replace("@READS@", "").replace(
        "@SHELL@", f"sh -c 'rm -f output.ghw; mkfifo output.ghw 2>&1; echo FIFO_PLANTED'")
    alice.save("attack.vhd", ghw_attack)
    alice.clear()
    alice.sio.emit("Simulate", ("100 ns", "proj/attack.vhd"), namespace="/stream")
    alice.wait("/stream", ("success", "errors"), 60)
    check("app did not hang on a planted FIFO", alice.http.get(BASE + "/login", timeout=10).status_code == 200)

    # ---------------------------------------- what a job leaves behind reaches the web app safely
    import importlib.util
    spec = importlib.util.spec_from_file_location("sb", APP / "main" / "sandbox.py")
    sb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sb)
    with sb.tempjob(APP / "temp") as job:
        key = f"{workdir}/seckeyb"
        os.symlink(key, job / "output.ghw")
        os.symlink(workdir, job / "dirlink")
        os.mkfifo(job / "plainfifo")
        (job / "real").mkdir()
        (job / "real" / "ok").write_bytes(b"fine")
        def refused(fn, *a):
            try:
                fn(*a)
                return False
            except OSError:
                return True
        check("web layer: symlink output refused", refused(sb.read_output, job, "output.ghw"))
        check("web layer: symlinked directory refused", refused(sb.read_output, job, "dirlink/seckeyb"))
        check("web layer: FIFO output refused without blocking", refused(sb.read_output, job, "plainfifo"))
        check("web layer: normal output readable", sb.read_output(job, "real/ok") == b"fine")
        check("web layer: symlink instead of a FIFO refused", refused(sb.open_fifo, job / "output.ghw", os.O_RDONLY))
        check("web layer: regular file instead of a FIFO refused", refused(sb.open_fifo, job / "real" / "ok", os.O_RDONLY))
        sb.write_job_file(job, "output.ghw", b"replaced")
        check("web layer: writing replaces a symlink, not its target",
              not (job / "output.ghw").is_symlink() and Path(key).stat().st_size == 16)

    # A job makes its directory inaccessible to the web app: the next compilation must still work.
    src = (HERE / "attack_tmpl.vhd").read_text().replace("@READS@", "").replace(
        "@SHELL@", "sh -c 'mkdir -p d/e; touch d/e/f; chmod 000 d/e; chmod 000 d; echo LOCKED'")
    alice.save("attack.vhd", src)
    alice.clear()
    alice.sio.emit("Simulate", ("100 ns", "proj/attack.vhd"), namespace="/stream")
    alice.wait("/stream", ("success", "errors"), 60)
    check("job really locked a directory", "LOCKED" in alice.alltext(), alice.alltext()[:200])
    alice.clear()
    alice.sio.send("Compile", namespace="/stream")
    alice.wait("/stream", ("success", "errors"), 60)
    check("next build cleans it", not any(True for j in (APP / "temp/.jobs").iterdir() if (j / "proj" / "d").exists()))

    # ---------------------------------------- limits
    def bomb(tag, shell, stop="100 ns", timeout=45):
        src = (HERE / "attack_tmpl.vhd").read_text().replace("@READS@", "").replace("@SHELL@", shell)
        alice.save("attack.vhd", src)
        alice.clear()
        t = time.time()
        alice.sio.emit("Simulate", (stop, "proj/attack.vhd"), namespace="/stream")
        ev, d = alice.wait("/stream", ("success", "errors"), timeout)
        return ev, time.time() - t, alice.alltext()

    ev, secs, _ = bomb("loop", "sh -c 'while :; do :; done'")
    check("infinite loop stopped by the time limit", ev is not None and secs < 30, (ev, secs))
    time.sleep(1)
    check("loop job killed", "while :" not in procs())
    ev, secs, _ = bomb("disk", "sh -c 'dd if=/dev/zero of=big bs=1M count=500 2>&1; ls -la big'")
    size = max((f.stat().st_size for f in (APP / "temp/.jobs").rglob("big")), default=0) if os.access(APP / "temp/.jobs", os.R_OK) else 0
    check("file size limited", size <= 64 * 2**20, size)
    ev, secs, text = bomb("mem", "python3 -S -c 'x=bytearray(6*1024**3);print(len(x))'")
    check("memory limited", "6442450944" not in text, text[-200:])
    ev, secs, text = bomb("fork", "sh -c 'i=0; while [ $i -lt 2000 ]; do (sleep 3) & i=$((i+1)); done; wait; echo FORK_END'")
    time.sleep(4)
    check("fork bomb contained, app alive", alice.http.get(BASE + "/login", timeout=15).status_code == 200)
    alice.sio.emit("Analyze", "proj/usertop.vhd", namespace="/stream")
    alice.clear()
    check("still works after the attacks", alice.wait("/stream", ("asuccess", "errors"), 40)[0] == "asuccess")

    # ---------------------------------------- closing the connection kills the job
    alice.save("attack.vhd", (HERE / "attack_tmpl.vhd").read_text().replace("@READS@", "").replace("@SHELL@", "sleep 987"))
    alice.clear()
    alice.sio.emit("Simulate", ("100 ns", "proj/attack.vhd"), namespace="/stream")
    time.sleep(6)
    running = "sleep 987" in procs()
    alice.wait("/stream", ("success", "errors"), 30)
    time.sleep(2)
    check("slow job visible, then killed at the time limit", running and "sleep 987" not in procs(), running)

    # ---------------------------------------- admin page: kills jobs, not the service
    def pids(text):
        res = []
        for p in Path("/proc").iterdir():
            if p.name.isdigit():
                try:
                    if text in (p / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace"):
                        res.append(int(p.name))
                except OSError:
                    pass
        return res
    alice.save("attack.vhd", (HERE / "attack_tmpl.vhd").read_text().replace("@READS@", "").replace("@SHELL@", "sleep 876"))
    alice.clear()
    alice.sio.emit("Simulate", ("100 ns", "proj/attack.vhd"), namespace="/stream")
    time.sleep(5)
    target = pids("sleep 876")
    check("admin: kills a job of the sandbox user", target and sb.kill_pid(target[-1]) and not pids("sleep 876"), target)
    alice.wait("/stream", ("success", "errors"), 25)
    service = pids("sandboxd.py")
    check("admin: cannot kill the sandbox service", service and not sb.kill_pid(min(service)) and pids("sandboxd.py"), service)

    alice.sio.disconnect()
    bob.sio.disconnect()
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed" + (f"; FAILED: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
