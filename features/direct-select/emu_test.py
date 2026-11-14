"""Focused 8051 emulator to validate the IR direct-select patch.

Executes from the hook entry (0x5D10) on the patched image (or, with --in <feature>, on
that feature's image, which includes the fix). The stock "apply input" tail at 0x5640 is
intercepted (recorded, not executed) so we observe exactly what the patch decides without
simulating the audio hardware. So is key_exit_to_home (0x0CE9), which the power-off command
calls on a menu page.
Then the whole firmware on Amp (tools/emu/ao300.py, real Timer0 and Timer3 ISRs): the
idempotent power commands 0x16 (on) and 0x17 (off) from standby, when on, twice in a row
and from a menu page, and that neither ever reaches the bootloader jump in standby; and an
input command in standby, which powers the amp on on that input with one source setup.
The build-time config WAKE_ON_INPUT is swept through emit(): 1 (the default) as above, 0
leaves the input commands ignored in standby, as ds3 did; both build the same code but for
the one byte.
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_patch as bp     # noqa: E402
import features              # noqa: E402  (tools/patch, on the path through build_patch)
from asm51 import Asm        # noqa: E402
import direct_select as ds   # noqa: E402
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
STOCK_RAW = STOCK
STOCK += b"\xff" * (0x10000 - len(STOCK))


def build_with(wake):
    """Stock plus the fix with this WAKE_ON_INPUT, in memory (no version string)."""
    img = bytearray(STOCK_RAW)
    addr, orig, op, label = ds.HOOK
    assert bytes(img[addr:addr + 3]) == orig
    a = Asm(bp.CODE_ADDR)
    ds.emit(a, wake)
    code = a.resolve()
    img += b"\xFF" * (bp.CODE_ADDR - len(img)) + code
    t = a.labels[label]
    img[addr:addr + 3] = bytes([op, t >> 8, t & 0xFF])
    return bytes(img)


def padded(img):
    return bytes(img) + b"\xff" * (0x10000 - len(img))


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


def scenario(name, cmd, power, page, expect_input, expect_apply, expect_key, current=0x99, expect_home=False,
             code=None):
    c = CPU(code or CODE)
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
# standby (WAKE_ON_INPUT 1, the default): the input is written and the Power key returned, so
# stock's power-on sets the amp up on that input; no apply here. The same input wakes as well.
for k in range(6):
    allok &= scenario("select input %d while standby: wake" % (k + 1), 0x10 + k, 0, 1,
                      expect_input=k + 1, expect_apply=None, expect_key=KEY_POWER)
allok &= scenario("select input 3 while standby on input 3: wake", 0x12, 0, 1,
                  expect_input=3, expect_apply=None, expect_key=KEY_POWER, current=3)
allok &= scenario("select input 5 while standby, page var 3: wake", 0x14, 0, 3,
                  expect_input=5, expect_apply=None, expect_key=KEY_POWER)
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


def source_keys(code, power):
    """The commands that translate to key 0x10 (in standby: read_key's bootloader jump)."""
    out = []
    for cmd in range(256):
        for page in (1, 2, 3):
            c = CPU(code); c.ram[0x6A] = cmd; c.ram[0x4F] = power; c.ram[0x45] = page; c.ram[0x47] = 0x99
            c.run(0x5D10)
            if c.r(7) == KEY_SOURCE and cmd not in out:
                out.append(cmd)
    return out


for power in (0, 1):
    got = source_keys(CODE, power)
    ok = got == [0x07]
    allok &= ok
    print("power %d: only the stock Source (0x07) becomes key 0x10: %s  %s"
          % (power, ["%02X" % c for c in got], "OK" if ok else "*** FAIL ***"))

# Whole firmware on Amp: the two power commands against the real standby and key paths.
POST_POWER_ON_TAIL = 0x55B9      # post_power_on done, ~1 s after the standby key


EEPROM_WRITE = 0x58AF            # R6:R7 address, R5 byte


def amp_run(img=None):
    amp = Amp(bytes(img or IMG))
    amp.power_ons = []
    amp.ee_writes = {}
    amp.e.hooks[EEPROM_WRITE] = lambda em: amp.ee_writes.__setitem__((em.R(6) << 8) | em.R(7), em.R(5))
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


def set_hw(amp, since):
    """input_set_hw's calls (the input each was given) since event index `since`."""
    return [int(v.split("R7=")[1][:2], 16) for c, n, v in amp.events[since:] if n == "input_set_hw"]


print("\nFull firmware: an input command in standby powers on, on that input")
amp = amp_run()
first = amp.e.iram[0x47]
target = 5 if first != 5 else 6
n0 = len(amp.events)
amp.press(0x10 + target - 1); amp.wait(12.0)
check("0x%02X in standby: powered on, home page, post_power_on ran once" % (0x10 + target - 1),
      amp.powered and amp.page == 1 and len(amp.power_ons) == 1)
check("the input is %d (was %d in standby)" % (target, first), amp.e.iram[0x47] == target)
check("one source setup, on input %d: %s" % (target, set_hw(amp, n0)), set_hw(amp, n0) == [target])
check("the settings save after the power-on stores input %d (EEPROM 0x0202)" % target,
      amp.ee_writes.get(0x0202) == target)
n1 = len(amp.events)
amp.press(0x10 + target - 1); amp.wait(3.0)
check("the same command while on: nothing (no source setup, no power-on)",
      amp.powered and set_hw(amp, n1) == [] and len(amp.power_ons) == 1)
other = 6 if target != 6 else 4
amp.press(0x10 + other - 1); amp.wait(6.0)
check("another input while on: a plain switch (one source setup, no power-on)",
      amp.powered and amp.e.iram[0x47] == other and set_hw(amp, n1) == [other] and len(amp.power_ons) == 1)
amp.press(CMD_OFF); amp.wait(3.0)
n2 = len(amp.events)
amp.press(0x10 + other - 1); amp.wait(12.0)
check("standby, then the input it was on: powered on, one source setup",
      amp.powered and amp.e.iram[0x47] == other and set_hw(amp, n2) == [other] and len(amp.power_ons) == 2)
check("never reset into the bootloader", not amp.boot_resets)

if not IN:
    # WAKE_ON_INPUT, the build-time config, through emit(): the same code but for its one byte
    print("\nWAKE_ON_INPUT 0 and 1 through emit()")
    on_img, off_img = build_with(1), build_with(0)
    built = bytes(IMG)
    check("the built image carries the default's code (WAKE_ON_INPUT %d)" % ds.WAKE_ON_INPUT,
          build_with(ds.WAKE_ON_INPUT)[bp.CODE_ADDR:] == built[bp.CODE_ADDR:len(on_img)])
    opt = ds.CONFIG["WAKE_ON_INPUT"]
    problems = features.config_diff(on_img, off_img, {("direct-select", "WAKE_ON_INPUT"): (1, 0, opt)})
    check("0 and 1 build the same size and differ in one byte (config promise) %s" % problems[:2], not problems)
    for bad in (2, -1, "1", 1.0, True, None):
        try:
            build_with(bad)
            stopped = False
        except SystemExit as ex:
            stopped = "WAKE_ON_INPUT" in str(ex)
        check("WAKE_ON_INPUT %r stops the build with a message" % (bad,), stopped)
    off = padded(off_img)
    for k in range(6):
        allok &= scenario("wake 0: select input %d while standby" % (k + 1), 0x10 + k, 0, 1,
                          expect_input=0x99, expect_apply=None, expect_key=NO_KEY, code=off)
    allok &= scenario("wake 0: power on while standby", CMD_ON, 0, 1,
                      expect_input=0x99, expect_apply=None, expect_key=KEY_POWER, code=off)
    # powered on, the two builds translate every command alike, on every page
    diff = []
    for page in (1, 2, 3, 8):
        for cmd in range(256):
            a_, b_ = CPU(padded(on_img)), CPU(off)
            for c in (a_, b_):
                c.ram[0x6A] = cmd; c.ram[0x4F] = 1; c.ram[0x45] = page; c.ram[0x47] = 0x99
                c.run(0x5D10)
            if (a_.r(7), a_.ram[0x47], a_.applied, a_.home) != (b_.r(7), b_.ram[0x47], b_.applied, b_.home):
                diff.append((cmd, page))
    check("powered on, wake 0 and wake 1 translate all 256 commands alike on 4 pages", not diff)
    got = source_keys(off, 0)
    check("wake 0, standby: only the stock Source becomes key 0x10", got == [0x07])
    amp = amp_run(off_img)
    first = amp.e.iram[0x47]
    amp.press(0x14); amp.wait(3.0)
    check("wake 0: 0x14 in standby is ignored (standby, input still %d, no reset)" % first,
          not amp.powered and amp.e.iram[0x47] == first and not amp.boot_resets)
    amp.press(CMD_ON); amp.wait(12.0)
    check("wake 0: 0x16 powers on, on the stored input", amp.powered and amp.e.iram[0x47] == first)

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
