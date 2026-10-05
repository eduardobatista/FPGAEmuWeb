"""State diagrams of VHDL state machines.

The FSMs are read from the analyzed VHDL itself (`ghdl --file-to-xml`), not from the synthesized
netlist: synthesis encodes the states in binary and yosys' FSM detection does not recognize the
netlists GHDL produces. The analyzed tree keeps the enumeration literals, the `case` over the state
and the `if` conditions, so the diagram uses the names and conditions the student wrote.

Recognized: a signal of an enumerated type assigned under a clock edge (rising_edge, falling_edge,
'event) is a state register; with two processes, the signal it is loaded from (`state <= next`) is
its next state. Transitions come from the `case` over the state (or `if state = X` chains); the
conditions of the enclosing if/elsif/else become the labels. The reset/initial state is the literal
assigned outside the `case` in the clocked process, or the declared initial value.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .diagram import GHDL_FLAGS, DiagramError, _run, analyze_files

EDGE_FUNCTIONS = {"rising_edge", "falling_edge"}
PROCESS_KINDS = {"sensitized_process_statement", "process_statement"}
THEN_RE = re.compile(r"\bthen\b", re.IGNORECASE)
IF_RE = re.compile(r"\b(?:els)?if\b", re.IGNORECASE)


class _Tree:
    """The XML of one analyzed file, with id lookup and source text access."""

    def __init__(self, xml_text, root_dir):
        self.root = ET.fromstring(xml_text)
        self.ids = {e.get("id"): e for e in self.root.iter() if e.get("id")}
        self.root_dir = Path(root_dir)
        self._lines = {}

    def ref(self, e, tag):
        c = e.find(tag) if e is not None else None
        return self.ids.get(c.get("ref")) if c is not None else None

    def lines(self, fname):
        if fname not in self._lines:
            p = Path(fname)
            p = p if p.is_absolute() else self.root_dir / p
            try:
                # GHDL counts columns with tabs expanded to 8 (students indent with tabs)
                self._lines[fname] = [l.expandtabs(8) for l in p.read_text(errors="replace").splitlines()]
            except OSError:
                self._lines[fname] = []
        return self._lines[fname]

    def source_name(self, e):
        """Identifier as written in the source (the XML has it in lower case)."""
        ident = e.get("identifier") or ""
        try:
            line = self.lines(e.get("file"))[int(e.get("line")) - 1]
            col = int(e.get("col")) - 1
            text = line[col:col + len(ident)]
            if text.lower() == ident.lower():
                return text
        except (TypeError, ValueError, IndexError):
            pass
        return ident

    def condition_text(self, cond):
        """Source text of an if/elsif condition: from its first token up to `then`."""
        pos = [(int(n.get("line")), int(n.get("col"))) for n in cond.iter()
               if n.get("line") and n.get("col") and n.get("file") == cond.get("file")]
        lines = self.lines(cond.get("file"))
        if not pos or not lines:
            return "?"
        line, col = min(pos)
        # The first token GHDL records can be inside a parenthesis, `if (a = '1') and (b = '0')`:
        # start right after the `if`/`elsif` keyword when it is on the same line.
        start = col - 1
        kw = list(IF_RE.finditer(lines[line - 1][:col - 1]))
        if kw:
            start = kw[-1].end()
        text, i = lines[line - 1][start:], line
        m = THEN_RE.search(text)
        while not m and i < len(lines) and i < line + 8:
            text += " " + lines[i]
            i += 1
            m = THEN_RE.search(text)
        text = text[:m.start()] if m else text
        text = " ".join(re.sub(r"--.*", "", text).split())
        return _balance(text) or "?"


def _balance(text):
    """Fixes the parentheses of a condition cut from the source (`if (a = '1') then` starts inside
    the parenthesis) and drops a pair that encloses the whole condition."""
    while text.count(")") > text.count("(") and text.endswith(")"):
        text = text[:-1].rstrip()
    while text.count("(") > text.count(")") and text.startswith("("):
        text = text[1:].lstrip()
    while text.startswith("(") and text.endswith(")"):
        depth = 0
        for i, ch in enumerate(text):
            depth += (ch == "(") - (ch == ")")
            if depth == 0 and i < len(text) - 1:
                return text
        text = text[1:-1].strip()
    return text


def _join(conds):
    """`and` of the conditions; one with or/xor gets parentheses so the precedence stays right."""
    if len(conds) < 2:
        return "".join(conds)
    out = []
    for c in conds:
        if re.search(r"\b(?:or|xor|nor)\b", c, re.IGNORECASE) and not c.startswith("not ("):
            c = "(" + c + ")"
        out.append(c)
    return " and ".join(out)


def _is_edge(t, cond):
    for n in cond.iter():
        k = n.get("kind")
        if k == "event_attribute":
            return True
        if k == "function_call":
            prefix = n.find("prefix")
            if prefix is not None and (prefix.get("identifier") or "").lower() in EDGE_FUNCTIONS:
                return True
    return False


def _named(t, e):
    """The declaration a simple name refers to."""
    if e is None or e.get("kind") != "simple_name":
        return None
    return t.ref(e, "named_entity")


def _statements(e, tag="sequential_statement_chain"):
    c = e.find(tag)
    return list(c) if c is not None else []


def _assignments(stmts):
    """All signal assignment statements (recursively, through if/case/loops)."""
    for s in stmts:
        if s.get("kind") == "simple_signal_assignment_statement":
            yield s
        for chain in ("sequential_statement_chain", "associated_chain"):
            for sub in s.iter(chain):
                for x in _assignments(list(sub)):
                    yield x


def _value(a):
    w = a.find("waveform_chain")
    el = w[0] if w is not None and len(w) else None
    return el.find("we_value") if el is not None else None


class _Fsm:
    def __init__(self, t, sig, literals):
        self.t, self.sig = t, sig
        self.literals = literals            # id -> source name, in declaration order
        self.next_sigs = {sig.get("id")}    # signals whose literal assignments are transitions
        self.initial = None
        self.transitions = []               # (from, to, [conditions])
        self.warnings = []

    def literal(self, e):
        d = _named(self.t, e)
        return self.literals.get(d.get("id")) if d is not None else None


def _walk(fsm, stmts, states, conds, case_seen):
    """Collects transitions. `states`: the source states of this point (None = any/unknown)."""
    t = fsm.t
    for s in stmts:
        k = s.get("kind")
        if k == "simple_signal_assignment_statement":
            target = _named(t, s.find("target"))
            if target is None or target.get("id") not in fsm.next_sigs:
                continue
            lit = fsm.literal(_value(s))
            if lit is None:
                continue                      # e.g. next <= state ("stay")
            if states is None:
                if not case_seen and fsm.initial is None and conds:
                    fsm.initial = lit         # assignment under the reset condition
            else:
                for st in states:
                    fsm.transitions.append((st, lit, list(conds)))
        elif k == "if_statement":
            prev = []
            node = s
            while node is not None:
                cond = node.find("condition")
                sub_states, extra = states, []
                if cond is not None:
                    # `if state = X then` selects a source state instead of adding a condition
                    lit = None
                    if cond.get("kind") == "equality_operator":
                        l, r = cond.find("left"), cond.find("right")
                        for a, b in ((l, r), (r, l)):
                            if _named(t, a) is not None and _named(t, a).get("id") == fsm.sig.get("id"):
                                lit = fsm.literal(b)
                    if lit is not None:
                        sub_states = [lit]
                    elif _is_edge(t, cond):
                        pass
                    else:
                        extra = [t.condition_text(cond)]
                neg = ["not (" + c + ")" for c in prev]
                had_initial = fsm.initial is not None
                _walk(fsm, _statements(node), sub_states, conds + neg + extra, case_seen)
                # Later branches are "not (this condition)", except after the reset branch: writing
                # "not (reset = '1')" on every transition would only clutter the diagram.
                is_reset_branch = not had_initial and fsm.initial is not None
                if extra and not is_reset_branch:
                    prev = prev + extra
                node = node.find("else_clause")
        elif k == "case_statement":
            expr = _named(t, s.find("expression"))
            alts = s.find("case_statement_alternative_chain")
            if alts is None:
                continue
            groups, cur = [], None
            for alt in alts:
                if alt.get("same_alternative_flag") == "true" and cur is not None:
                    cur[0].append(alt)
                else:
                    cur = ([alt], alt.find("associated_chain"))
                    groups.append(cur)
            on_state = expr is not None and expr.get("id") == fsm.sig.get("id")
            seen = []
            for choices, chain in groups:
                body = list(chain) if chain is not None else []
                if on_state:
                    src = []
                    for c in choices:
                        if c.get("kind") == "choice_by_others":
                            src += [n for n in fsm.literals.values() if n not in seen and n not in src]
                        else:
                            lit = fsm.literal(c.find("choice_expression"))
                            if lit:
                                src.append(lit)
                    seen += src
                    _walk(fsm, body, src, conds, True)
                else:
                    sel = t.source_name(s.find("expression")) if s.find("expression") is not None else "?"
                    labels = []
                    for c in choices:
                        if c.get("kind") == "choice_by_others":
                            labels.append("others")
                        else:
                            ce = c.find("choice_expression")
                            labels.append(t.condition_text(ce) if ce is not None else "?")
                    _walk(fsm, body, states, conds + [sel + " = " + " | ".join(labels)], case_seen)
        else:
            for chain in ("sequential_statement_chain",):
                if s.find(chain) is not None:
                    _walk(fsm, _statements(s, chain), states, conds, case_seen)


def _enum_literals(t, decl):
    td = t.ref(decl, "type")
    while td is not None and td.get("kind") != "enumeration_type_definition":
        nxt = t.ref(td, "parent_type") or t.ref(td, "type")
        if nxt is None or nxt is td:
            return None
        td = nxt
    if td is None:
        return None
    lits = td.find("enumeration_literal_list")
    return {l.get("id"): t.source_name(l) for l in lits} if lits is not None else None


def _find_fsms(t, entity):
    arch = None
    for e in t.root.iter():
        if e.get("kind") == "architecture_body":
            name = e.find("entity_name")
            if name is not None and (name.get("identifier") or "").lower() == entity.lower():
                arch = e
    if arch is None:
        raise DiagramError(f"Architecture of '{entity}' not found.")
    decls = arch.find("declaration_chain")
    enum_sigs = {}
    for d in (list(decls) if decls is not None else []):
        if d.get("kind") == "signal_declaration":
            lits = _enum_literals(t, d)
            if lits and len(lits) > 1:
                enum_sigs[d.get("id")] = (d, lits)
    procs = [p for p in arch.iter() if p.get("kind") in PROCESS_KINDS and p.find("process_origin") is None]

    # state registers: enum signals assigned under a clock edge
    fsms = {}
    for p in procs:
        for ifs in p.iter():
            if ifs.get("kind") != "if_statement" and ifs.tag != "else_clause":
                continue
            cond = ifs.find("condition")
            if cond is None or not _is_edge(t, cond):
                continue
            for a in _assignments(_statements(ifs)):
                d = _named(t, a.find("target"))
                if d is not None and d.get("id") in enum_sigs and d.get("id") not in fsms:
                    sig, lits = enum_sigs[d.get("id")]
                    fsms[d.get("id")] = _Fsm(t, sig, lits)
                if d is not None and d.get("id") in fsms:
                    src = _named(t, _value(a))       # state <= next
                    if src is not None and src.get("id") in enum_sigs and src.get("id") != d.get("id"):
                        fsms[d.get("id")].next_sigs.add(src.get("id"))
    # a "next state" signal is not a state machine of its own
    for f in list(fsms.values()):
        for n in f.next_sigs - {f.sig.get("id")}:
            fsms.pop(n, None)

    result = []
    for f in fsms.values():
        for p in procs:
            _walk(f, _statements(p), None, [], False)
        if f.initial is None:
            dv = f.sig.find("default_value")
            if dv is not None and dv.get("ref"):        # `signal a, b : t := X`: b refers to a's value
                dv = t.ids.get(dv.get("ref"))
            f.initial = f.literal(dv) if dv is not None else None
        seen, uniq = set(), []
        for a, b, c in f.transitions:
            cond = _join(c)
            if (a, b, cond) not in seen:
                seen.add((a, b, cond))
                uniq.append({"from": a, "to": b, "cond": cond})
        if not uniq:
            f.warnings.append("No transitions found (the next state is not assigned with state names).")
        result.append({"signal": t.source_name(f.sig), "states": list(f.literals.values()),
                       "initial": f.initial, "transitions": uniq, "warnings": f.warnings})
    return result


def extract_fsms(vhd_files, entity_file, entity, workdir):
    """State machines of `entity` (declared in `entity_file`), using `vhd_files` as the project."""
    if not re.fullmatch(r"\w+", entity):
        raise DiagramError("Invalid entity name.")
    workdir = Path(workdir)
    failed = analyze_files(vhd_files, workdir)
    rc, out = _run(["ghdl", "--file-to-xml"] + GHDL_FLAGS + [str(entity_file)], workdir)
    if rc != 0 or not out.lstrip().startswith("<"):
        msg = out.replace(str(Path(entity_file).parent) + "/", "").strip()
        if str(entity_file) in failed:
            msg = failed[str(entity_file)].replace(str(Path(entity_file).parent) + "/", "").strip()
        raise DiagramError(f"Could not read '{Path(entity_file).name}':\n{msg[-2000:]}")
    return _find_fsms(_Tree(out, workdir), entity)
