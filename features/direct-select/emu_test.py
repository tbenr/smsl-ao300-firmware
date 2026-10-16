"""Focused 8051 emulator to validate the IR direct-select patch.

Executes from the hook entry (0x5D10) on the patched image (or, with --in <feature>, on
that feature's image, which includes the fix). The stock "apply input" tail at 0x5640 is
intercepted (recorded, not executed) so we observe exactly what the patch decides without
simulating the audio hardware. So is key_exit_to_home (0x0CE9), which the power-off command
calls on a menu page.
Then the whole firmware on Amp (tools/emu/ao300.py, real Timer0 and Timer3 ISRs): the
idempotent power commands 0x16 (on) and 0x17 (off) from standby, when on, twice in a row
and from a menu page, and that neither ever reaches the bootloader jump in standby.
The NOTSEL resume stub at 0x5D17 (mov R7,A; clr A; mov 0x6F,A; ret) is real code
and runs normally.
"""
import sys

APPLY_TAIL = 0x5640
GO_HOME = 0x0CE9             # key_exit_to_home: page 1, clear the screen (the dispatcher's Power on a menu page)
CMD_ON, CMD_OFF = 0x16, 0x17
KEY_POWER, KEY_SOURCE, NO_KEY = 0x1F, 0x10, 0xFF
import os
_default = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build", "flash_patched.bin")
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_stock = os.path.join(_root, "original", "extracted", "flash.bin")
sys.path.insert(0, os.path.join(_root, "tools", "emu"))
from emu8051 import Emu8051  # noqa: E402
from ao300 import Amp, NEC_POWER  # noqa: E402
NEC_OPEN_MENU = 0x04         # opens the menu (page 3) from home; NEC_MENU 0x03 only navigates inside it
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
        self.home = False     # GO_HOME called

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
                elif tgt == GO_HOME:
                    self.home = True; self.ram[0x45] = 1   # observe; the page change is its visible effect
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


def scenario(name, cmd, power, page, expect_input, expect_apply, expect_key, current=0x99, expect_home=False):
    c = CPU(CODE)
    c.ram[0x6A] = cmd
    c.ram[0x4F] = power
    c.ram[0x45] = page
    c.ram[0x47] = current       # sentinel 0x99: unchanged unless patch writes it
    c.run(0x5D10)
    got_input = c.ram[0x47]
    got_apply = c.applied
    got_key = c.r(7)
    ok = (got_apply == expect_apply and got_key == expect_key and c.home == expect_home and
          c.ram[0x6F] == 0 and (expect_input is None or got_input == expect_input))
    print("%-42s cmd=%02X pwr=%d pg=%d -> 0x47=%s apply=%s home=%d R7=%02X  %s" % (
        name, cmd, power, page,
        "%02X" % got_input, ("%d" % got_apply) if got_apply is not None else "-",
        c.home, got_key, "OK" if ok else "*** FAIL ***"))
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
# idempotent power: 0x16 = on (the Power key only in standby), 0x17 = off (the Power key only
# when on; from a menu page through key_exit_to_home first, as the dispatcher's two presses)
allok &= scenario("power on while standby -> Power key", CMD_ON, 0, 1,
                  expect_input=0x99, expect_apply=None, expect_key=KEY_POWER)
for page in (1, 2, 3, 7):
    allok &= scenario("power on while on, page %d: ignored" % page, CMD_ON, 1, page,
                      expect_input=0x99, expect_apply=None, expect_key=NO_KEY)
allok &= scenario("power off while standby: ignored", CMD_OFF, 0, 1,
                  expect_input=0x99, expect_apply=None, expect_key=NO_KEY)
for page in (1, 2):
    allok &= scenario("power off while on, page %d -> Power key" % page, CMD_OFF, 1, page,
                      expect_input=0x99, expect_apply=None, expect_key=KEY_POWER)
for page in (3, 4, 7, 8):
    allok &= scenario("power off from menu page %d: home, Power" % page, CMD_OFF, 1, page,
                      expect_input=0x99, expect_apply=None, expect_key=KEY_POWER, expect_home=True)
# just above range -> normal translate (table[0x18] = 0xFF past table)
allok &= scenario("cmd 0x18 (above range)", 0x18, 1, 1,
                  expect_input=0x99, expect_apply=None, expect_key=NO_KEY)
# stock Source (0x07) still maps to internal 0x10 unchanged
allok &= scenario("stock Source 0x07 -> internal", 0x07, 1, 1,
                  expect_input=0x99, expect_apply=None, expect_key=0x10)
# stock command 0x05 -> table[5]=0x24
allok &= scenario("stock cmd 0x05 -> internal 0x24", 0x05, 1, 1,
                  expect_input=0x99, expect_apply=None, expect_key=0x24)
# stock command 0x0e -> table[0x0e]=0x0a
allok &= scenario("stock cmd 0x0e -> internal 0x0a", 0x0E, 1, 1,
                  expect_input=0x99, expect_apply=None, expect_key=0x0A)

# Full sweep: every command 0x00..0xFF, in every power and page state the patch reads.
# Outside the eight new commands the patched image must behave exactly like stock: same
# key, no input change, no apply, no go-home. (Stock reads erased flash above the 15-entry
# table, so it returns 0xFF there; the patch must not let those commands read its own code
# bytes instead.)
bad = []
for power, page in ((1, 1), (1, 2), (1, 3), (1, 8), (0, 1)):
    for cmd in range(256):
        st = CPU(STOCK); st.ram[0x6A] = cmd; st.ram[0x4F] = power; st.ram[0x45] = page; st.ram[0x47] = 0x99
        st.run(0x5D10)
        pt = CPU(CODE); pt.ram[0x6A] = cmd; pt.ram[0x4F] = power; pt.ram[0x45] = page; pt.ram[0x47] = 0x99
        pt.run(0x5D10)
        if 0x10 <= cmd <= 0x17:
            continue   # covered above
        if ((st.r(7), st.ram[0x47], st.applied, st.ram[0x6F], st.home) !=
                (pt.r(7), pt.ram[0x47], pt.applied, pt.ram[0x6F], pt.home)):
            bad.append((cmd, power, page, st.r(7), pt.r(7), pt.applied))
if bad:
    allok = False
    for cmd, power, page, sk, pk, ap in bad:
        print("sweep: cmd %02X pwr=%d pg=%d stock key %02X patched key %02X apply=%s  *** FAIL ***"
              % (cmd, power, page, sk, pk, ap))
else:
    print("sweep 0x00..0xFF in 5 power/page states: patched == stock for all 248 other commands  OK")
# in standby no command but the stock Source may become key 0x10: read_key's bootloader jump
boot = [cmd for cmd in range(256) if cmd != 0x07 and
        (lambda c: (c.run(0x5D10), c.r(7))[1])(CPU(CODE)) == KEY_SOURCE]
if boot:
    allok = False
    print("commands %s translate to key 0x10 (bootloader in standby)  *** FAIL ***" % ["%02X" % c for c in boot])

# Whole firmware on Amp: the two power commands against the real standby and key paths.
POST_POWER_ON_TAIL = 0x55B9      # post_power_on done, ~1 s after the standby key


def amp_run():
    amp = Amp(bytes(IMG))
    amp.power_ons = []
    amp.e.hooks[POST_POWER_ON_TAIL] = lambda em: amp.power_ons.append(amp.t)
    amp.boot_resets = []

    def iap(em, old, new):             # IAP_CONTR = 0x60: software reset into the bootloader
        if new == 0x60:
            amp.boot_resets.append(amp.t)
    amp.e.sfr_watch[0xC7] = iap
    amp.boot()
    return amp


def check(name, ok):
    global allok
    allok &= bool(ok)
    print("  %-70s %s" % (name, "OK" if ok else "*** FAIL ***"))


print("\nFull firmware: 0x16 (on) and 0x17 (off) from standby, on, twice, and from a menu page")
amp = amp_run()
check("boots to standby", not amp.powered)
amp.press(CMD_OFF); amp.wait(2.0)
check("0x17 in standby: still standby, no reset", not amp.powered and not amp.boot_resets)
amp.press(CMD_ON); amp.wait(10.0)
check("0x16 in standby: powered on, post_power_on ran once", amp.powered and len(amp.power_ons) == 1)
amp.press(CMD_ON); amp.wait(3.0)
check("0x16 while on: nothing (post_power_on not run again, page 1)",
      amp.powered and len(amp.power_ons) == 1 and amp.page == 1)
amp.press(CMD_OFF); amp.wait(3.0)
check("0x17 while on: standby", not amp.powered)
amp.press(CMD_OFF); amp.wait(3.0)
check("0x17 again: still standby, no reset", not amp.powered and not amp.boot_resets)
amp.press(CMD_ON); amp.wait(10.0)
check("0x16 again: powered on, post_power_on ran twice", amp.powered and len(amp.power_ons) == 2)
amp.press(NEC_OPEN_MENU); amp.wait(2.0)
check("Menu opens a menu page", amp.powered and amp.page >= 3)
menu_page = amp.page
amp.press(NEC_POWER); amp.wait(2.0)
check("stock Power on the menu page only goes home (still on)", amp.powered and amp.page == 1)
amp.press(NEC_OPEN_MENU); amp.wait(2.0)
check("Menu again: the menu page is back", amp.powered and amp.page == menu_page)
amp.press(CMD_OFF); amp.wait(3.0)
check("0x17 from the menu page: standby", not amp.powered)
check("never reset into the bootloader", not amp.boot_resets)

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
if IN:      # an image that includes the fix changes more; its hook must jump into that image's code
    target = (CODE[0x5D11] << 8) | CODE[0x5D12]
    dok = CODE[0x5D10] == 0x02 and stock_len <= target < len(IMG)
    print("hook 0x5D10 is ljmp 0x%04X, into the image's own code  %s" % (target, "OK" if dok else "*** FAIL ***"))
else:
    dok = changed == expected
    print("bytes changed in stock range: %s  %s" % ([hex(i) for i in changed], "OK" if dok else "*** FAIL ***"))
allok &= dok

print("\nALL PASS" if allok else "\nFAILURES PRESENT")
sys.exit(0 if allok else 1)
