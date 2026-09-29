"""What 8051 instructions touch: code they jump into, RAM they read or write, XDATA they point at.

    r = Refs()
    r.scan(image, start, end)       # one instruction or a run of them (never data)
    r.code                          # absolute code targets (jumps, calls, branches)
    r.ram                           # {byte: set of "r" / "w"}: direct RAM and SFRs, bits by their byte
    r.xdata                         # {address: [instruction address]} from mov DPTR,#imm

Only instructions are decoded: take the ranges from an assembler (Asm.code_ranges) or from a
recursive descent (tools/disasm/d51.py). Decoding data linearly reads font tables as bit
instructions on RAM 0x29, among other things.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "disasm"))
import d51  # noqa: E402

XDATA_OWNED = (0x0100, 0x0800)     # XDATA features allocate; page 0 is the stock firmware's

# direct-address operand: opcode -> access to the byte in operand 1 ("r", "w", "rw")
DIRECT = {0x05: "rw", 0x15: "rw", 0x25: "r", 0x35: "r", 0x45: "r", 0x55: "r", 0x65: "r", 0x95: "r",
          0xE5: "r", 0xC5: "rw", 0xD5: "rw", 0xB5: "r", 0xC0: "r", 0xD0: "w", 0xF5: "w",
          0x42: "rw", 0x43: "rw", 0x52: "rw", 0x53: "rw", 0x62: "rw", 0x63: "rw", 0x75: "w",
          0x86: "w", 0x87: "w",                         # mov direct,@Ri
          0xA6: "r", 0xA7: "r"}                         # mov @Ri,direct
DIRECT.update({op: "w" for op in range(0x88, 0x90)})    # mov direct,Rn
DIRECT.update({op: "r" for op in range(0xA8, 0xB0)})    # mov Rn,direct
# bit operand in operand 1
BIT = {0x10: "rw", 0x20: "r", 0x30: "r", 0x72: "r", 0x82: "r", 0xA0: "r", 0xB0: "r",
       0x92: "w", 0xA2: "r", 0xB2: "rw", 0xC2: "w", 0xD2: "w"}


def bit_byte(b):
    """The byte that holds bit address b (0x20..0x2F for RAM bits, the SFR for b >= 0x80)."""
    return 0x20 + (b >> 3) if b < 0x80 else b & 0xF8


class Refs:
    def __init__(self):
        self.code = set()
        self.ram = {}
        self.xdata = {}

    def _ram(self, addr, access):
        self.ram.setdefault(addr, set()).update(access)

    def scan(self, image, start, end):
        pc = start
        while pc < end:
            ln, _, targets, _ = d51.decode(image, pc)
            op = image[pc]
            b1 = image[pc + 1] if ln > 1 else None
            self.code.update(targets)
            if op in DIRECT:
                self._ram(b1, DIRECT[op])
            elif op == 0x85:                            # mov dst,src is encoded 85 src dst
                self._ram(b1, "r")
                self._ram(image[pc + 2], "w")
            elif op in BIT:
                self._ram(bit_byte(b1), BIT[op])
            elif op == 0x90:                            # mov DPTR,#imm
                x = (b1 << 8) | image[pc + 2]
                if XDATA_OWNED[0] <= x < XDATA_OWNED[1]:
                    self.xdata.setdefault(x, []).append(pc)
            pc += ln
        return self

    def writes(self):
        return {a for a, acc in self.ram.items() if "w" in acc}


def reach(image, entry):
    """Every code byte reachable from entry (jumps and calls followed, as d51 does)."""
    seen, _ = d51.disasm(image, [entry])
    out = set()
    for pc, (ln, _, _) in seen.items():
        out.update(range(pc, pc + ln))
    return out
