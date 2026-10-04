"""Block diagrams of VHDL designs.

ghdl --synth (keeps the hierarchy) -> Verilog -> yosys (YoWASP, WebAssembly) -> JSON netlist,
rendered in the browser by netlistsvg. Two views:
  - "rtl": the yosys netlist as is (gates, muxes, adders, flip-flops and sub-blocks);
  - "blocks": in each module, all primitive cells are merged into one "logic" box, so only the
    entity, its ports and the instantiated sub-blocks remain, still connected through that box.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

GHDL_FLAGS = ["-fexplicit", "--ieee=synopsys"]   # same as backend/analyze.sh and simulate.sh
TIMEOUT = 60

ENTITY_RE = re.compile(r"^\s*entity\s+(\w+)\s+is\b", re.IGNORECASE | re.MULTILINE)
COMMENT_RE = re.compile(r"--.*$", re.MULTILINE)
# Names GHDL makes up for anonymous nets (n12, h1_n16): not worth showing in the blocks view.
AUTO_NET_RE = re.compile(r"(^|_)n\d+$")


class DiagramError(Exception):
    pass


# Verilog keywords that are valid VHDL identifiers: GHDL copies such names (an instance labelled
# `reg`, a port called `input`) into its Verilog output unescaped, which yosys rejects.
# (posedge/negedge/default/case* are left out: GHDL uses them inside statements.)
VERILOG_ONLY_KEYWORDS = ("reg wire input output inout assign always initial module endmodule "
                         "parameter integer real time task endtask edge tri tri0 tri1 "
                         "supply0 supply1 wand wor trireg specify endspecify event force release fork "
                         "join deassign defparam primitive endprimitive table endtable forever "
                         "endfunction realtime scalared vectored small medium large "
                         "strong0 strong1 pull0 pull1 weak0 weak1 highz0 highz1 cmos rcmos pmos nmos "
                         "rpmos rnmos tran rtran tranif0 tranif1 rtranif0 rtranif1 bufif0 bufif1 "
                         "notif0 notif1 pullup pulldown logic bit byte int").split()
_KW = "|".join(VERILOG_ONLY_KEYWORDS)
# Positions where GHDL puts identifiers: instance name, port connection, declared name.
_KW_AS_IDENT = [
    re.compile(rf"^\s*[A-Za-z_][\w$]*\s+({_KW})\s*\(", re.M),
    re.compile(rf"\.({_KW})\s*\("),
    re.compile(rf"^\s*\(?\s*(?:input|output|inout|wire|reg)\s*(?:\[[^\]]*\]\s*)?({_KW})\s*[;,)=]", re.M),
]


def _escape_verilog_keywords(text):
    """Turns keywords used as identifiers into escaped identifiers (`reg` -> `\\reg `)
    everywhere except as the first word of a line, where the real keywords are."""
    used = {m for rx in _KW_AS_IDENT for m in rx.findall(text)}
    if not used:
        return text
    word = re.compile(rf"(?<![\w$\\])({'|'.join(sorted(used))})(?![\w$])")
    lines = []
    for line in text.split("\n"):
        head = re.match(r"\s*\(?\s*[A-Za-z_][\w$]*", line)
        cut = head.end() if head else 0
        lines.append(line[:cut] + word.sub(r"\\\1 ", line[cut:]))
    return "\n".join(lines)


def list_entities(files, root):
    """[(relative file, entity name)] for the VHDL files."""
    res = []
    for f in files:
        try:
            text = COMMENT_RE.sub("", Path(f).read_text(errors="replace"))
        except OSError:
            continue
        for name in ENTITY_RE.findall(text):
            res.append((str(Path(f).relative_to(root)), name))
    return res


def _yosys():
    exe = Path(sys.executable).parent / "yowasp-yosys"
    return str(exe) if exe.exists() else (shutil.which("yowasp-yosys") or "yowasp-yosys")


def _run(cmd, cwd, timeout=TIMEOUT):
    try:
        p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise DiagramError(f"Timeout ({timeout} s) running {Path(cmd[0]).name}.")
    return p.returncode, p.stdout.decode("utf-8", "replace")


def synthesize(vhd_files, top, workdir):
    """Yosys JSON netlist of entity `top`, using all `vhd_files` (the project) as sources."""
    workdir = Path(workdir)
    if not re.fullmatch(r"\w+", top):
        raise DiagramError("Invalid entity name.")
    srcdirs = {str(Path(f).parent) + "/" for f in vhd_files}

    def clean(msg):
        for d in srcdirs:
            msg = msg.replace(d, "")
        return msg.replace(str(workdir) + "/", "").strip()

    # Analyze file by file, in passes: a file that uses `entity work.x` needs x analyzed first,
    # and a broken file the entity does not depend on must not prevent the diagram.
    pending, failed = [str(f) for f in vhd_files], {}
    while pending:
        failed = {}
        for f in pending:
            rc, out = _run(["ghdl", "-a"] + GHDL_FLAGS + [f], workdir)
            if rc != 0:
                failed[f] = out
        if len(failed) == len(pending):
            break
        pending = list(failed)
    with open(workdir / "design.v", "wb") as v:
        try:
            # --latches: student code often infers latches; they can still be drawn.
            p = subprocess.run(["ghdl", "--synth"] + GHDL_FLAGS + ["--latches", "--out=verilog", top], cwd=workdir,
                               stdout=v, stderr=subprocess.PIPE, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            raise DiagramError(f"Timeout ({TIMEOUT} s) synthesizing {top}.")
    if p.returncode != 0:
        msg = (f"Synthesis of '{top}' failed (only synthesizable code can be drawn; "
               f"testbenches with 'wait for' are not):\n" + clean(p.stderr.decode("utf-8", "replace")))
        if failed:
            msg += "\n\nFiles of the folder with errors (fix them if the entity uses them):\n" + \
                   "\n".join(clean(out) for out in failed.values())
        raise DiagramError(msg)
    vfile = workdir / "design.v"
    vfile.write_text(_escape_verilog_keywords(vfile.read_text(errors="replace")))
    # YoWASP runs sandboxed: it only sees the current directory, so use relative paths.
    rc, out = _run([_yosys(), "-q", "-p",
                    f"read_verilog design.v; hierarchy -top {top}; proc; opt_clean; write_json design.json"],
                   workdir, timeout=120)
    if rc != 0 or not (workdir / "design.json").exists():
        raise DiagramError("Netlist generation (yosys) failed:\n" + clean(out))
    return json.loads((workdir / "design.json").read_text())


def display_names(netlist, entities):
    """{module name: name to show}. GHDL names sub-modules <entity>_B<architecture>."""
    known = sorted({e.lower(): e for e in entities}.items(), key=lambda kv: -len(kv[0]))
    res = {}
    for mod in netlist["modules"]:
        low = mod.lower()
        name = next((e for k, e in known if low == k or low.startswith(k + "_b")), mod)
        res[mod] = name
    # Keep the GHDL names where two modules would get the same label (e.g. different generics).
    taken = {}
    for mod, name in res.items():
        taken.setdefault(name, []).append(mod)
    return {mod: (name if len(taken[name]) == 1 else mod) for mod, name in res.items()}


def _bit_names(module):
    """bit -> readable net name (VHDL signals first, GHDL's anonymous nets last)."""
    names = {}
    for name, net in sorted(module.get("netnames", {}).items(),
                            key=lambda kv: (kv[1].get("hide_name", 0), bool(AUTO_NET_RE.search(kv[0])), kv[0])):
        for i, b in enumerate(net["bits"]):
            if isinstance(b, int) and b not in names:
                names[b] = (name, i, len(net["bits"]))
    return names


def fix_blackboxes(netlist):
    """Instances of components without an implementation (their file is missing or has errors)
    come without port directions. Infer them (a net already driven by something else is an
    input of the block, otherwise an output) so they can be drawn, and return warnings."""
    warnings = set()
    for module in netlist["modules"].values():
        driven = set()
        for p in module["ports"].values():
            if p["direction"] == "input":
                driven.update(b for b in p["bits"] if isinstance(b, int))
        for c in module.get("cells", {}).values():
            for port, d in c.get("port_directions", {}).items():
                if d == "output":
                    driven.update(b for b in c["connections"].get(port, []) if isinstance(b, int))
        for c in module.get("cells", {}).values():
            if "port_directions" in c:
                continue
            c["port_directions"] = {
                port: "input" if all((not isinstance(b, int)) or b in driven for b in bits) else "output"
                for port, bits in c["connections"].items()}
            warnings.add(c["type"])
    return [f"Block '{t}' has no implementation (its file is missing or has errors): drawn as a black box, "
            f"port directions guessed." for t in sorted(warnings)]


def to_blocks(netlist):
    """Copy of the netlist where each module's primitive cells become a single 'logic' cell."""
    out = {"creator": netlist.get("creator", ""), "modules": {}}
    for mname, module in netlist["modules"].items():
        cells = module.get("cells", {})
        # yosys primitives ($and, $mux, $dff...) start with '$'; anything else is a block
        prim = {n: c for n, c in cells.items() if c["type"].startswith("$")}
        if not prim:
            out["modules"][mname] = module
            continue
        driven, read = set(), set()
        for c in prim.values():
            for port, bits in c["connections"].items():
                ints = {b for b in bits if isinstance(b, int)}
                (driven if c["port_directions"].get(port) == "output" else read).update(ints)
        # What the rest of the module (ports and sub-blocks) uses.
        used_outside = set()
        for p in module["ports"].values():
            if p["direction"] != "input":
                used_outside.update(b for b in p["bits"] if isinstance(b, int))
        for n, c in cells.items():
            if n not in prim:
                for port, bits in c["connections"].items():
                    if c["port_directions"].get(port) == "input":
                        used_outside.update(b for b in bits if isinstance(b, int))
        inputs = sorted(read - driven)
        outputs = sorted(driven & used_outside)
        names = _bit_names(module)

        def group(bits):
            """Group bits into ports named after their nets: {port name: [bits]}."""
            groups = {}
            for b in bits:
                name = names.get(b, (f"n{b}", 0, 1))[0]
                groups.setdefault(name, []).append(b)
            return groups

        conns, dirs = {}, {}
        for direction, bits in (("input", inputs), ("output", outputs)):
            for name, bs in group(bits).items():
                port = name if name not in conns else f"{name}_{direction[:2]}"
                conns[port] = bs
                dirs[port] = direction
        new_cells = {n: c for n, c in cells.items() if n not in prim}
        if conns:
            new_cells["logic"] = {"type": "logic", "port_directions": dirs, "connections": conns,
                                  "attributes": {"merged_cells": str(len(prim))}}
        out["modules"][mname] = dict(module, cells=new_cells)
    return out


def rename_modules(netlist, names):
    """Apply display names to module keys and to the cell types that reference them."""
    out = {"creator": netlist.get("creator", ""), "modules": {}}
    for mname, module in netlist["modules"].items():
        cells = {n: dict(c, type=names.get(c["type"], c["type"])) for n, c in module.get("cells", {}).items()}
        out["modules"][names.get(mname, mname)] = dict(module, cells=cells)
    return out
