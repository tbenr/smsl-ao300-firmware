"""Focused 8051 emulator to validate the IR direct-select patch.

Executes from the hook entry (0x5D10) on the patched image. The stock
"apply input" tail at 0x5640 is intercepted (recorded, not executed) so we
observe exactly what the patch decides without simulating the audio hardware.
The NOTSEL resume stub at 0x5D17 (mov R7,A; clr A; mov 0x6F,A; ret) is real code
and runs normally.
"""
import sys

APPLY_TAIL = 0x5640
import os
_default = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build", "flash_patched.bin")
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_stock = os.path.join(_root, "original", "extracted", "flash.bin")
INTEGRATION = True    # `emu_test.py --in <feature>`: direct-select's behaviour inside that image
IN = sys.argv[2] if len(sys.argv) == 3 and sys.argv[1] == "--in" else None
if IN:
    sys.path.insert(0, os.path.join(_root, "tools", "patch"))
    import features
    print("Integration: direct-select inside %s" % IN)
    IMG = bytearray(open(features.image(IN), "rb").read())
else:
    IMG = bytearray(open(sys.argv[1] if len(sys.argv) > 1 else _default, "rb").read())
CODE = bytes(IMG) + b"\xff" * (0x10000 - len(IMG))
STOCK = bytes(open(sys.argv[2] if len(sys.argv) > 2 and not IN else _stock, "rb").read())
STOCK += b"\xff" * (0x10000 - len(STOCK))


class CPU:
    def __init__(self, code):
        self.code = code
        self.ram = bytearray(256)
        self.A = 0
        self.C = 0
        self.DPTR = 0
        self.applied = None   # records (input_value) if APPLY_TAIL called

    def r(self, n):           # register n in bank 0
        return self.ram[n]

    def setr(self, n, v):
        self.ram[n] = v & 0xFF

    def run(self, pc, maxsteps=1000):
        depth = 0
        for _ in range(maxsteps):
            op = self.code[pc]
            if op == 0xE5:    # mov A,dir
                self.A = self.ram[self.code[pc + 1]]; pc += 2
            elif op == 0xF5:  # mov dir,A
                self.ram[self.code[pc + 1]] = self.A; pc += 2
            elif op == 0x75:  # mov dir,#i
                self.ram[self.code[pc + 1]] = self.code[pc + 2]; pc += 3
            elif op == 0x74:  # mov A,#i
                self.A = self.code[pc + 1]; pc += 2
            elif op == 0xFF:  # mov R7,A
                self.setr(7, self.A); pc += 1
            elif op == 0xAF:  # mov R7,dir
                self.setr(7, self.ram[self.code[pc + 1]]); pc += 2
            elif op == 0xEF:  # mov A,R7
                self.A = self.r(7); pc += 1
            elif op == 0x7F:  # mov R7,#i
                self.setr(7, self.code[pc + 1]); pc += 2
            elif op == 0xE4:  # clr A
                self.A = 0; pc += 1
            elif op == 0xC3:  # clr C
                self.C = 0; pc += 1
            elif op == 0x04:  # inc A
                self.A = (self.A + 1) & 0xFF; pc += 1
            elif op == 0x94:  # subb A,#i
                i = self.code[pc + 1]; res = self.A - i - self.C
                self.C = 1 if res < 0 else 0; self.A = res & 0xFF; pc += 2
            elif op == 0x64:  # xrl A,#i
                self.A ^= self.code[pc + 1]; pc += 2
            elif op == 0x90:  # mov DPTR,#a
                self.DPTR = (self.code[pc + 1] << 8) | self.code[pc + 2]; pc += 3
            elif op == 0x93:  # movc A,@A+DPTR
                self.A = self.code[(self.DPTR + self.A) & 0xFFFF]; pc += 1
            elif op in (0xB4, 0xB5):  # cjne A,#i,rel / cjne A,dir,rel
                i = self.code[pc + 1] if op == 0xB4 else self.ram[self.code[pc + 1]]
                rel = self.code[pc + 2]
                self.C = 1 if self.A < i else 0
                pc += 3
                if self.A != i:
                    pc = (pc + ((rel ^ 0x80) - 0x80)) & 0xFFFF
            elif op == 0x80:  # sjmp rel
                rel = self.code[pc + 1]; pc += 2
                pc = (pc + ((rel ^ 0x80) - 0x80)) & 0xFFFF
            elif op in (0x40, 0x50, 0x60, 0x70):  # jc/jnc/jz/jnz rel
                rel = self.code[pc + 1]; pc += 2
                take = {0x40: self.C == 1, 0x50: self.C == 0,
                        0x60: self.A == 0, 0x70: self.A != 0}[op]
                if take:
                    pc = (pc + ((rel ^ 0x80) - 0x80)) & 0xFFFF
            elif op == 0x02:  # ljmp
                pc = (self.code[pc + 1] << 8) | self.code[pc + 2]
            elif op == 0x12:  # lcall
                tgt = (self.code[pc + 1] << 8) | self.code[pc + 2]
                if tgt == APPLY_TAIL:
                    self.applied = self.ram[0x47]   # observe, don't execute
                    pc += 3
                else:
                    raise RuntimeError("unexpected call 0x%04X" % tgt)
            elif op == 0x22:  # ret
                if depth == 0:
                    return pc
                depth -= 1
            else:
                raise RuntimeError("unhandled opcode 0x%02X @0x%04X" % (op, pc))
        raise RuntimeError("runaway")


def scenario(name, cmd, power, page, expect_input, expect_apply, expect_key, current=0x99):
    c = CPU(CODE)
    c.ram[0x6A] = cmd
    c.ram[0x4F] = power
    c.ram[0x45] = page
    c.ram[0x47] = current       # sentinel 0x99: unchanged unless patch writes it
    c.run(0x5D10)
    got_input = c.ram[0x47]
    got_apply = c.applied
    got_key = c.r(7)
    ok = (got_apply == expect_apply and got_key == expect_key and
          (expect_input is None or got_input == expect_input))
    print("%-42s cmd=%02X pwr=%d pg=%d -> 0x47=%s apply=%s R7=%02X  %s" % (
        name, cmd, power, page,
        "%02X" % got_input, ("%d" % got_apply) if got_apply is not None else "-",
        got_key, "OK" if ok else "*** FAIL ***"))
    return ok


allok = True
# direct-select, powered on + home: input = cmd-0x10+1, apply called, key eaten
for k in range(6):
    allok &= scenario("select input %d" % (k + 1), 0x10 + k, 1, 1,
                      expect_input=k + 1, expect_apply=k + 1, expect_key=0xFF)
# the input already selected: ignored, no re-initialisation of the source
for k in range(6):
    allok &= scenario("select input %d while on input %d" % (k + 1, k + 1), 0x10 + k, 1, 1,
                      expect_input=k + 1, expect_apply=None, expect_key=0xFF, current=k + 1)
# a different input from a real current input (not the sentinel) still switches
allok &= scenario("select input 3 while on input 2", 0x12, 1, 1,
                  expect_input=3, expect_apply=3, expect_key=0xFF, current=2)
allok &= scenario("select input 1 while on input 6", 0x10, 1, 1,
                  expect_input=1, expect_apply=1, expect_key=0xFF, current=6)
# standby: ignored
allok &= scenario("select while standby", 0x10, 0, 1,
                  expect_input=0x99, expect_apply=None, expect_key=0xFF)
# not home: ignored
allok &= scenario("select while in menu", 0x10, 1, 2,
                  expect_input=0x99, expect_apply=None, expect_key=0xFF)
# just above range -> normal translate (table[0x16] = 0xFF past table)
allok &= scenario("cmd 0x16 (above range)", 0x16, 1, 1,
                  expect_input=0x99, expect_apply=None, expect_key=0xFF)
# stock Source (0x07) still maps to internal 0x10 unchanged
allok &= scenario("stock Source 0x07 -> internal", 0x07, 1, 1,
                  expect_input=0x99, expect_apply=None, expect_key=0x10)
# stock command 0x05 -> table[5]=0x24
allok &= scenario("stock cmd 0x05 -> internal 0x24", 0x05, 1, 1,
                  expect_input=0x99, expect_apply=None, expect_key=0x24)
# stock command 0x0e -> table[0x0e]=0x0a
allok &= scenario("stock cmd 0x0e -> internal 0x0a", 0x0E, 1, 1,
                  expect_input=0x99, expect_apply=None, expect_key=0x0A)

# Full sweep: every command 0x00..0xFF, on/home. Outside the six new commands the
# patched image must behave exactly like stock: same key, no input change, no apply.
# (Stock reads erased flash above the 15-entry table, so it returns 0xFF there; the
# patch must not let those commands read its own code bytes instead.)
bad = []
for cmd in range(256):
    st = CPU(STOCK); st.ram[0x6A] = cmd; st.ram[0x4F] = 1; st.ram[0x45] = 1; st.ram[0x47] = 0x99
    st.run(0x5D10)
    pt = CPU(CODE); pt.ram[0x6A] = cmd; pt.ram[0x4F] = 1; pt.ram[0x45] = 1; pt.ram[0x47] = 0x99
    pt.run(0x5D10)
    if 0x10 <= cmd <= 0x15:
        continue   # covered above
    if (st.r(7), st.ram[0x47], st.applied, st.ram[0x6F]) != (pt.r(7), pt.ram[0x47], pt.applied, pt.ram[0x6F]):
        bad.append((cmd, st.r(7), pt.r(7), pt.applied))
if bad:
    allok = False
    for cmd, sk, pk, ap in bad:
        print("sweep: cmd %02X stock key %02X patched key %02X apply=%s  *** FAIL ***" % (cmd, sk, pk, ap))
else:
    print("sweep 0x00..0xFF: patched == stock for all 250 non-select commands  OK")

# Version string on the RESET page: follow the R2:R1 pointer loaded at 0x22CA.
ptr = (CODE[0x22CB] << 8) | CODE[0x22CD]
end = CODE.index(b"\0", ptr)
text = CODE[ptr:end].decode("ascii", "replace")
vok = CODE[0x22CA] == 0x7A and CODE[0x22CC] == 0x79 and 0 < end - ptr <= 20 and ptr < len(IMG)
allok &= vok
print("version pointer 0x22CA -> 0x%04X %r  %s" % (ptr, text, "OK" if vok else "*** FAIL ***"))

# Only the intended bytes may differ from stock inside the stock image range:
# the 3-byte hook at 0x5D10 and the two pointer bytes at 0x22CB / 0x22CD.
stock_len = len(STOCK.rstrip(b"\xff"))
changed = sorted(i for i in range(stock_len) if STOCK[i] != CODE[i])
expected = [0x22CB, 0x22CD, 0x5D10, 0x5D11, 0x5D12]
if IN:      # images built on direct-select change more; its own hook must still be there
    own = open(_default, "rb").read()
    dok = CODE[0x5D10:0x5D13] == own[0x5D10:0x5D13] and CODE[0x9400:0x943D] == own[0x9400:0x943D]
    print("hook 0x5D10 and the code at 0x9400 as direct-select built them  %s" % ("OK" if dok else "*** FAIL ***"))
else:
    dok = changed == expected
    print("bytes changed in stock range: %s  %s" % ([hex(i) for i in changed], "OK" if dok else "*** FAIL ***"))
allok &= dok

print("\nALL PASS" if allok else "\nFAILURES PRESENT")
sys.exit(0 if allok else 1)
