"""Label-resolving 8051 assembler for firmware patches.

Instructions are written as raw bytes plus symbolic operands, and each one keeps its
text for the generated listing:

    a = Asm(0x9450)
    a.L("loop")
    a.i("djnz R7,loop", 0xDF, rel("loop"))
    a.i("lcall 0x4437", 0x12, ab(0x4437))
    code = a.resolve()
    open("x.asm", "w").write(a.listing())

rel(label) is a relative byte counted from the end of the instruction, ab(label or
address) a 16-bit big-endian address.
"""


class Asm:
    """Label-resolving 8051 assembler; every instruction keeps its text for a listing."""

    def __init__(self, org):
        self.org = org
        self.buf = bytearray()
        self.labels = {}
        self.fix = []
        self.lines = []

    @property
    def pc(self):
        return self.org + len(self.buf)

    def L(self, name):
        self.labels[name] = self.pc
        self.lines.append(("label", name))

    def comment(self, text):
        self.lines.append(("comment", text))

    def i(self, text, *parts):
        start = self.pc
        rels = []
        for p in parts:
            if isinstance(p, tuple):
                kind, target = p
                if kind == "rel":
                    rels.append((len(self.buf), target))
                    self.buf.append(0)
                elif kind in ("hi", "lo"):
                    self.fix.append((kind, len(self.buf), target, None))
                    self.buf.append(0)
                else:
                    self.fix.append(("abs", len(self.buf), target, None))
                    self.buf += b"\0\0"
            else:
                self.buf.append(p & 0xFF)
        end = self.pc
        for pos, target in rels:
            self.fix.append(("rel", pos, target, end))
        self.lines.append(("ins", start, end, text))

    def data(self, text, bs):
        start = self.pc
        self.buf += bytes(bs)
        self.lines.append(("ins", start, self.pc, text))

    def resolve(self):
        for kind, pos, target, end in self.fix:
            addr = self.labels[target] if isinstance(target, str) else target
            if kind == "rel":
                rel = addr - end
                assert -128 <= rel <= 127, "branch to %s out of range (%d)" % (target, rel)
                self.buf[pos] = rel & 0xFF
            elif kind in ("hi", "lo"):
                self.buf[pos] = (addr >> 8) if kind == "hi" else (addr & 0xFF)
            else:
                self.buf[pos] = addr >> 8
                self.buf[pos + 1] = addr & 0xFF
        return bytes(self.buf)

    def listing(self):
        out = []
        for ln in self.lines:
            if ln[0] == "label":
                out.append("%s:" % ln[1])
            elif ln[0] == "comment":
                out.append("            ; %s" % ln[1])
            else:
                _, s, e, text = ln
                bs = self.buf[s - self.org:e - self.org]
                for k in range(0, len(bs), 8):
                    chunk = bs[k:k + 8]
                    out.append("  %04X: %-24s %s" % (s + k, chunk.hex(" "), text if k == 0 else ""))
        return "\n".join(out) + "\n"


def rel(lab):
    return ("rel", lab)


def ab(lab):
    return ("abs", lab)


def hi8(lab):
    return ("hi", lab)


def lo8(lab):
    return ("lo", lab)


# ---- text instructions ------------------------------------------------------
# Asm.op("mov A,R3 ; comment") encodes the subset of the 8051 instruction set the
# patches use from its text. Operands: A, C, B, DPTR, AB, R0..R7, @R0/@R1, @DPTR,
# @A+DPTR, #imm (a number, #hi(label) / #lo(label), or a label for mov DPTR), a direct address (number or SFR
# name), a bit (0x20.7, P0.3, ACC.7, F0, or a bit address as a number) and branch
# targets (labels or numbers).

SFR = {"ACC": 0xE0, "B": 0xF0, "PSW": 0xD0, "SP": 0x81, "DPL": 0x82, "DPH": 0x83,
       "P0": 0x80, "P1": 0x90, "P2": 0xA0, "P4": 0xC0, "IE": 0xA8}
BITS = {"F0": 0xD5, "F1": 0xD1, "EA": 0xAF}


def _num(s):
    s = s.strip()
    return int(s, 0)


def _is_num(s):
    try:
        _num(s)
        return True
    except ValueError:
        return False


def _direct(s):
    s = s.strip()
    if s.upper() in SFR:
        return SFR[s.upper()]
    v = _num(s)
    assert 0 <= v <= 0xFF, s
    return v


def _bit(s):
    s = s.strip()
    if s.upper() in BITS:
        return BITS[s.upper()]
    if "." in s:
        base, n = s.rsplit(".", 1)
        n = int(n)
        d = _direct(base)
        if d < 0x80:
            assert 0x20 <= d <= 0x2F, s
            return (d - 0x20) * 8 + n
        assert d % 8 == 0, s
        return d + n
    return _num(s)


def _target(s):
    s = s.strip()
    return _num(s) if _is_num(s) else s


def _reg(s):
    s = s.strip().upper()
    if len(s) == 2 and s[0] == "R" and s[1] in "01234567":
        return int(s[1])
    return None


def encode(text):
    """(mnemonic text) -> list of parts for Asm.i (bytes and rel()/ab() fix-ups)."""
    t = text.split(";")[0].strip()
    if " " in t:
        mn, rest = t.split(None, 1)
        ops = [o.strip() for o in rest.split(",")]
    else:
        mn, ops = t, []
    mn = mn.lower()
    U = [o.upper() for o in ops]
    r = [_reg(o) for o in ops]

    def imm(o):
        v = o[1:].strip()
        for f, k in (("hi(", "hi"), ("lo(", "lo")):
            if v.startswith(f) and v.endswith(")"):
                lab = v[3:-1].strip()
                if _is_num(lab):
                    return (_num(lab) >> 8) & 0xFF if k == "hi" else _num(lab) & 0xFF
                return (k, lab)
        return _num(v) & 0xFF

    if mn == "nop":
        return [0x00]
    if mn == "ret":
        return [0x22]
    if mn in ("lcall", "ljmp"):
        return [0x12 if mn == "lcall" else 0x02, ab(_target(ops[0]))]
    if mn == "sjmp":
        return [0x80, rel(_target(ops[0]))]
    if mn in ("jz", "jnz", "jc", "jnc"):
        return [{"jz": 0x60, "jnz": 0x70, "jc": 0x40, "jnc": 0x50}[mn], rel(_target(ops[0]))]
    if mn in ("jb", "jnb", "jbc"):
        return [{"jb": 0x20, "jnb": 0x30, "jbc": 0x10}[mn], _bit(ops[0]), rel(_target(ops[1]))]
    if mn == "djnz":
        if r[0] is not None:
            return [0xD8 + r[0], rel(_target(ops[1]))]
        return [0xD5, _direct(ops[0]), rel(_target(ops[1]))]
    if mn == "cjne":
        if U[0] == "A" and ops[1].startswith("#"):
            return [0xB4, imm(ops[1]), rel(_target(ops[2]))]
        if U[0] == "A":
            return [0xB5, _direct(ops[1]), rel(_target(ops[2]))]
        if r[0] is not None:
            return [0xB8 + r[0], imm(ops[1]), rel(_target(ops[2]))]
    if mn in ("push", "pop"):
        return [0xC0 if mn == "push" else 0xD0, _direct(ops[0])]
    if mn in ("mul", "div"):
        return [0xA4 if mn == "mul" else 0x84]
    if mn in ("rl", "rr", "rlc", "rrc", "swap", "cpl", "clr", "setb") and U and U[0] == "A":
        return [{"rl": 0x23, "rr": 0x03, "rlc": 0x33, "rrc": 0x13, "swap": 0xC4, "cpl": 0xF4, "clr": 0xE4}[mn]]
    if mn in ("clr", "setb", "cpl"):
        if U[0] == "C":
            return [{"clr": 0xC3, "setb": 0xD3, "cpl": 0xB3}[mn]]
        return [{"clr": 0xC2, "setb": 0xD2, "cpl": 0xB2}[mn], _bit(ops[0])]
    if mn in ("inc", "dec"):
        base = 0x04 if mn == "inc" else 0x14
        if U[0] == "A":
            return [base]
        if U[0] == "DPTR" and mn == "inc":
            return [0xA3]
        if r[0] is not None:
            return [base + 4 + r[0]]
        return [base + 1, _direct(ops[0])]
    if mn in ("add", "addc", "subb", "anl", "orl", "xrl") and U[0] == "A":
        base = {"add": 0x20, "addc": 0x30, "subb": 0x90, "anl": 0x50, "orl": 0x40, "xrl": 0x60}[mn]
        if ops[1].startswith("#"):
            return [base + 4, imm(ops[1])]
        if r[1] is not None:
            return [base + 8 + r[1]]
        return [base + 5, _direct(ops[1])]
    if mn == "xch":
        if r[1] is not None:
            return [0xC8 + r[1]]
        return [0xC5, _direct(ops[1])]
    if mn == "movc":
        return [0x93]
    if mn == "movx":
        if U[0] == "A":
            return [{"@DPTR": 0xE0, "@R0": 0xE2, "@R1": 0xE3}[U[1]]]
        return [{"@DPTR": 0xF0, "@R0": 0xF2, "@R1": 0xF3}[U[0]]]
    if mn == "mov":
        d, s = U
        if d == "DPTR":
            v = ops[1][1:]
            return [0x90, ab(_num(v) if _is_num(v) else v)]
        if d == "C":
            return [0xA2, _bit(ops[1])]
        if s == "C":
            return [0x92, _bit(ops[0])]
        if d == "A":
            if ops[1].startswith("#"):
                return [0x74, imm(ops[1])]
            if r[1] is not None:
                return [0xE8 + r[1]]
            return [0xE5, _direct(ops[1])]
        if r[0] is not None:
            if s == "A":
                return [0xF8 + r[0]]
            if ops[1].startswith("#"):
                return [0x78 + r[0], imm(ops[1])]
            return [0xA8 + r[0], _direct(ops[1])]
        dd = _direct(ops[0])
        if s == "A":
            return [0xF5, dd]
        if ops[1].startswith("#"):
            return [0x75, dd, imm(ops[1])]
        if r[1] is not None:
            return [0x88 + r[1], dd]
        return [0x85, _direct(ops[1]), dd]
    raise ValueError("cannot encode %r" % text)


def _op(self, text):
    self.i(text.strip(), *encode(text))


Asm.op = _op
