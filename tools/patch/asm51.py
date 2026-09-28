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
