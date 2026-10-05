#!/usr/bin/env python3
"""Emulator test for the probe (a read-only register dump over the header on the FN button).

  * the image differs from stock only in the hook's target bytes (0x3DAA..0x3DAB), the
    included fixes' hooks and patches, the version pointer and the appended code;
  * the hook, run from read_key with the I2C slave model answering for four chips, a seeded
    register file and a model of the receiver's rate calculator (a result per port, one port
    that never finishes, a stale result right after each target change): the text on UART1
    is exactly the dump the model implies (scan, the three register files, the FS line, ports,
    RAM), every byte leaves with P_SW1 on the header pins and ES off, P_SW1 and IE come back,
    the bus saw reads, address probes and writes of the calculator target only, that target
    is back at stock's value, no audio chip was written, and the amp's state afterwards is
    stock's for a command it ignores (the Dimmer setting untouched);
  * all 256 NEC commands through read_key and dispatch_key against a reference the test
    builds (stock plus the same fixes, without the probe; build/reference.bin), on the home
    and volume pages, in a menu, in standby and on page 0: identical but for FN on the
    home page with the amp on, which dumps and then reads as "no key";
  * whole firmware from reset with the real timer ISRs, the I2C slave model and an EEPROM
    model: the dump after a cold power-up, the amp alive afterwards (volume key, XMOS
    message, P_SW1 back on the XMOS line, ES on), nothing sent in standby or in a menu, and
    nothing written to any chip during the dump.
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "emu"))
sys.path.insert(0, HERE)
from emu8051 import Emu8051  # noqa: E402
from ao300 import Amp, NEC_POWER, NEC_VOL_UP, NEC_MENU  # noqa: E402
from i2c import I2CBus       # noqa: E402
import build_patch as bp     # noqa: E402
import features              # noqa: E402  (tools/patch, on the path through build_patch)
import probe as pr           # noqa: E402

INTEGRATION = True           # `emu_test.py --in <feature>`: the probe's promises in that image

TEST_IMG = bp.OUT_IMAGE
BASE_IMG = bp.BASE_IMAGE
READ_KEY, DISPATCH_KEY_IF_ANY = 0x3DA2, 0x5D6E
NJW_WRITE, DAC_WRITE, EXPANDER_WRITE_PIN = 0x54EA, 0x4D8A, 0x1A7C
RECEIVER, FS_TARGET, FS_RESULT = 0x80, 0x37, 0x38
# the calculator model: the port's rate code, or None for a port that never finishes (bit 7 stays set)
FS_RATES = {0: 9, 1: None, 2: 8, 3: 0xC, 4: None, 5: 8, 6: None, 7: None}
SBUF, SCON, P_SW1, IE = 0x99, 0x98, 0xA2, 0xA8
NO_KEY = 0x16                # a command stock ignores: the reference for the state after a dump
PRESENT = {0x62, 0x80, 0xB0, 0xC0}
ABSENT = {a for a in range(0, 256, 2)} - PRESENT
EEPROM_READ_DATA, EEPROM_WRITE, EEPROM_ERASE = 0x5970, 0x58AF, 0x59D0
# what a used amp holds: magic and power-on flag (sector 0), the settings record (sector 0x0200)
FACTORY = {0x0001: 0x45, 0x0002: 1, 0x0201: 20, 0x0202: 1, 0x0203: 1, 0x0204: 0, 0x0205: 1, 0x0206: 9,
           0x0207: 9, 0x0208: 1, 0x0209: 20, 0x020A: 0, 0x020B: 1, 0x020C: 1}

fails = []


def reference_image():
    """Stock plus the fixes this image includes, without the probe: the behaviour reference for
    the sweep, so that only the probe differs (the image diff still runs against stock)."""
    import uikit                                                 # tools/patch, on the path
    from asm51 import Asm
    path = os.path.join(HERE, "build", "reference.bin")

    def assemble():
        a = Asm(bp.CODE_ADDR)
        features.emit(a, bp.INCLUDES)
        return a.resolve(), a.labels, a
    uikit.build_image(base_path=bp.BASE_IMAGE, base_sha=bp.BASE_SHA, code_addr=bp.CODE_ADDR, assemble=assemble,
                      hooks=features.hooks(bp.INCLUDES), patches=features.patches(bp.INCLUDES),
                      version_text="ref", out_image=path, out_listing=path + ".asm",
                      title="reference: stock + %s" % ", ".join(bp.INCLUDES), label_prefixes=())
    return open(path, "rb").read()


def check(name, ok, detail=""):
    print("  %-72s %s %s" % (name, "OK  " if ok else "FAIL", detail))
    if not ok:
        fails.append(name)


# ---- the UART, the chips and the expected text ----------------------------------------------------

def uart(e):
    """Record every SBUF write as (byte, P_SW1 bit 6, ES) and complete it at once (TI)."""
    out = []

    def watch(em, old, new):
        out.append((new, em.sfr[P_SW1] & 0x40, em.sfr[IE] & 0x10))
        em.sfr[SCON] |= 0x02
    e.sfr_watch[SBUF] = watch
    return out


def text(out):
    return bytes(b for b, _, _ in out).decode("ascii", "replace")


def seed(bus):
    """A register file with a different value in every register the dump reads."""
    bus.absent = set(ABSENT)
    for dev, first, count in pr.DEVICES:
        for reg in range(first, first + count):
            bus.inputs[(dev, reg)] = (dev * 3 + reg * 7 + 1) & 0xFF
    bus.inputs.pop((RECEIVER, FS_TARGET), None)        # the target reads back as written
    calculator(bus)


def calculator(bus, stale_reads=1):
    """Model of the receiver's rate calculator behind register 0x38: the result for the port in
    0x37 (FS_RATES), 0x80 (calculating) for a port with no result; for the first reads after a
    target change, the previous target's finished result (what a real one hands back before it
    restarts)."""
    state = {"target": bus.regs.get((RECEIVER, FS_TARGET), bus.inputs.get((RECEIVER, FS_TARGET), 0)),
             "reads": 99, "last": None}

    def result(port):
        rate = FS_RATES.get(port)
        return 0x80 if rate is None else (port << 4) | rate

    def read_fn(dev, reg):
        if dev != RECEIVER or reg != FS_RESULT:
            return None
        target = bus.regs.get((RECEIVER, FS_TARGET), state["target"])
        if target != state["target"]:
            state["last"] = result(state["target"]) if FS_RATES.get(state["target"]) is not None else None
            state["target"], state["reads"] = target, 0
        state["reads"] += 1
        if state["reads"] <= stale_reads and state["last"] is not None:
            return state["last"]
        return result(target)
    bus.read_fn = read_fn
    bus.fs_result = result
    bus.fs_expected = "".join(" %02X" % result(port) for port in range(pr.FS_PORTS))


def ports(e):
    out = []
    for sfr in pr.PORTS:
        m, v = e.pins.get(sfr, (0, 0))
        out.append((e.sfr[sfr] & ~m & 0xFF) | (v & m))
    return out


def expected(bus, e, ram=None):
    s = pr.HEAD + "".join(" %02X" % a for a in sorted(PRESENT))
    for dev, first, count in pr.DEVICES:
        for reg in range(first, first + count):
            if reg % 16 == 0:
                s += pr.CRLF + "%02X %02X:" % (dev, reg)
            if (dev, reg) == (RECEIVER, FS_RESULT):          # the calculator's result for stock's target
                s += " %02X" % bus.fs_result(bus.regs.get((RECEIVER, FS_TARGET), 0))
            else:
                s += " %02X" % bus.inputs.get((dev, reg), bus.regs.get((dev, reg), 0))
    s += pr.FS + bus.fs_expected
    s += pr.PINS + "".join(" %02X" % p for p in ports(e))
    s += pr.RAM + "".join(" %02X" % (e.iram[a] if ram is None else ram[a]) for a in pr.RAM_LIST)
    return s + pr.END


def bus_problems(bus, mark=0):
    """Transfers after mark that are not a register read, an address-only probe, or a write of the
    receiver's calculator target."""
    bad = []
    for entry in bus.log[mark:]:
        kind, dev, reg, v = entry[2:6]
        if kind == "R" or (reg is None and v == ()) or (dev, reg) == (RECEIVER, FS_TARGET):
            continue
        bad.append(I2CBus.format(entry))
    return bad


def target_writes(bus, mark=0):
    return [v for c, site, kind, dev, reg, v, ok in bus.log[mark:] if kind == "W" and (dev, reg) == (RECEIVER, FS_TARGET)]


# ---- bare CPU: one command through read_key (and dispatch_key) ---------------------------------------

def cpu(image, cmd, power, page):
    e = Emu8051(image)
    e.sfr[0x81] = 0x88                       # SP as set by the firmware
    e.sfr[IE] = 0x90                         # EA and ES on, as uart1_init leaves them
    e.sfr[P_SW1] = 0x40 if power else 0x00   # UART1 on P3.6/P3.7 with the amp on, the header in standby
    e.sfr[0xA0], e.sfr[0xC0] = 0x5B, 0xFF    # P2 playing on speakers; P4 idle
    e.iram[0x4F], e.iram[0x45], e.iram[0x47], e.iram[0x2B] = power, page, 1, 1
    e.iram[0x31], e.iram[0x52], e.iram[0x39], e.iram[0x2C], e.iram[0x29] = 20, 18, 1, 1, 1
    e.iram[0x35], e.iram[0x2A], e.iram[0x3D], e.iram[0x75], e.iram[0x73] = 9, 9, 1, 2, 3
    e.iram[0x48], e.iram[0x49] = 0xFF, 0xFF  # theme text colour (white theme)
    e.iram[0x6A] = cmd
    e.iram[0x20] |= 0x10                     # 0x20.4: new IR command
    e.iram[0x2D] = 0xFF                      # encoder idle
    e.pins[0xC0] = (0x04, 0x04)              # P4.2 high: no lock
    e.bus = I2CBus(types.SimpleNamespace(e=e))
    seed(e.bus)
    e.out = uart(e)
    e.writes = []
    for addr, name in ((NJW_WRITE, "njw"), (DAC_WRITE, "dac"), (EXPANDER_WRITE_PIN, "expander")):
        e.hooks[addr] = lambda em, name=name: em.writes.append(name)
    return e


def same_after(s, f):
    """State after the command, stock s (given NO_KEY) vs probe f (given the dump command), ignoring
    what a bus read and the dump leave: bank-0 registers, the stack above SP, SBUF, SCON, ACC, B,
    DPTR, PSW, and the command byte itself (0x6A)."""
    sp = s.sfr[0x81]
    keep = lambda e: (bytes(e.iram[0x08:0x6A]), bytes(e.iram[0x6B:sp + 1]), bytes(e.xram), e.lcd.pixels, e.sfr[0x81],    # noqa: E731
                      bytes(e.sfr[0x80:0x81]), e.sfr[0x90], e.sfr[0xA0], e.sfr[0xC0], e.sfr[0xC8], e.sfr[P_SW1],
                      e.sfr[IE], e.sfr[SCON] & ~0x02, e.pc)
    return keep(s) == keep(f)


def through(image, cmd, power, page, dispatch=True, steps=4_000_000):
    e = cpu(image, cmd, power, page)
    e.capped = False
    try:
        e.call(READ_KEY, max_steps=steps)
        if dispatch:
            e.call(DISPATCH_KEY_IF_ANY, max_steps=steps)
    except RuntimeError:                     # a handler that waits on hardware: compared where it stopped
        e.capped = True
    return e


def hook_test(img_path=TEST_IMG, base_path=BASE_IMG, label="the standalone image"):
    print("\nThe hook from read_key, %s: FN (0x%02X), amp on, home page" % (label, pr.COMMAND))
    image = open(img_path, "rb").read()
    f = through(image, pr.COMMAND, 1, 1, dispatch=False, steps=60_000_000)
    want = expected(f.bus, f)
    got = text(f.out)
    check("the dump is exactly what the chips and the RAM hold (%d bytes)" % len(got), got == want,
          "" if got == want else "\n    got  %r\n    want %r" % (got[:120], want[:120]))
    check("every byte leaves with P_SW1 on the header pins and ES off",
          f.out and all(sw == 0 and es == 0 for _, sw, es in f.out))
    check("P_SW1 and IE restored", f.sfr[P_SW1] == 0x40 and f.sfr[IE] == 0x90, "%02X %02X" % (f.sfr[P_SW1], f.sfr[IE]))
    bad = bus_problems(f.bus)
    check("the bus saw reads, address probes and the calculator target only (%d transfers)" % len(f.bus.log),
          not bad, str(bad[:3]))
    tw = target_writes(f.bus)
    check("the calculator target: ports 0..7, then stock's value back", tw == list(range(pr.FS_PORTS)) + [0], str(tw))
    check("no audio chip written", not f.writes, str(f.writes[:4]))
    check("the Dimmer setting untouched (stock's FN toggles it)", f.iram[0x29] == 1, "%d" % f.iram[0x29])
    check("ran to the end of read_key", not f.capped, "" if not f.capped else "steps capped")
    print("    dump: %.0f ms of main-loop time, %d bus transfers" % (f.cycles / 24_000, len(f.bus.log)))
    if base_path:
        s = through(open(base_path, "rb").read(), NO_KEY, 1, 1, dispatch=False)
        check("afterwards the amp's state is stock's for a command it ignores", same_after(s, f) and not s.out)


def sweep():
    print("\nAll 256 NEC commands through read_key and dispatch_key vs the reference (stock + the same fixes)")
    base, test = reference_image(), open(TEST_IMG, "rb").read()
    diffs, dumps, capped = [], [], []
    for power, page in ((1, 1), (0, 1), (1, 2), (1, 3), (1, 0)):
        for cmd in range(256):
            acts = cmd == pr.COMMAND and power == 1 and page == 1
            steps = 60_000_000
            s = through(base, NO_KEY if acts else cmd, power, page, steps=steps)
            f = through(test, cmd, power, page, steps=steps)
            if acts:
                dumps.append(text(f.out).startswith(pr.HEAD) and text(f.out).endswith(pr.END)
                             and same_after(s, f) and not s.out)
            else:
                # not cycles (pr_key's test costs a few), not the stack above SP (return addresses into
                # the fixes' code, which sits at other addresses in the two images)
                same = (s.capped, s.pc, bytes(s.iram[:0x89]), bytes(s.xram), s.lcd.pixels, bytes(s.sfr),
                        s.writes, s.out) == (f.capped, f.pc, bytes(f.iram[:0x89]), bytes(f.xram), f.lcd.pixels,
                                            bytes(f.sfr), f.writes, f.out)
                if s.capped and f.capped:          # both stuck on hardware: stopped a few steps apart
                    same = (s.lcd.pixels, s.writes, s.out) == (f.lcd.pixels, f.writes, f.out)
                    capped.append(cmd)
                if not same:
                    diffs.append((cmd, power, page))
    check("identical to the reference for every command and state but FN on the home page, amp on",
          not diffs, "(%d diffs) %s" % (len(diffs), diffs[:4]))
    if capped:
        print("    capped on hardware waits in both images: commands %s" % sorted({"%02X" % c for c in capped}))
    check("FN on the home page, amp on: the dump, then the amp as a command it ignores", dumps == [True])


# ---- whole firmware -------------------------------------------------------------------------------

class Run:
    """One amp from reset, on an EEPROM model behind the stock IAP routines and the I2C slave
    model with the four chips present. A cold power-up turns it on by itself, on USB."""

    def __init__(self, image):
        self.eeprom = dict(FACTORY)
        self.amp = Amp(image)
        self.bus = I2CBus(self.amp, absent=ABSENT)
        e = self.amp.e

        def read(em):
            em.sfr[0xC2] = self.eeprom.get((em.sfr[0xC3] << 8) | em.sfr[0xC4], 0xFF)

        def write(em):
            self.eeprom[(em.R(6) << 8) | em.R(7)] = em.R(5)

        def erase(em):
            sector = ((em.R(6) << 8) | em.R(7)) & ~0x1FF
            for k in [k for k in self.eeprom if k & ~0x1FF == sector]:
                del self.eeprom[k]
        e.hooks[EEPROM_READ_DATA] = read
        e.hooks[EEPROM_WRITE] = write
        e.hooks[EEPROM_ERASE] = erase
        self.out = uart(e)
        calculator(self.bus)
        self.bus.inputs[(0x80, 0x39)] = 0x00
        self.amp.set_pin(0xC0, 2, 1)                  # no lock
        self.amp.boot(12.0)

    def key(self, cmd, wait=3.0):
        self.amp.press(cmd)
        self.amp.wait(wait)

    def mark(self):
        return len(self.out), len(self.amp.events), len(self.bus.log)

    def sent(self, mark):
        return text(self.out[mark[0]:])

    def audio_writes(self, mark):
        return [(n, d) for c, n, d in self.amp.events[mark[1]:] if n in ("njw1194_write", "dac_i2c_write",
                                                                         "expander_write", "input_set_hw")]


def scenario(img_path, label):
    print("\nWhole firmware, %s: cold power-up, the dump, then keys, standby, a menu" % label)
    r = Run(open(img_path, "rb").read())
    e = r.amp.e
    check("powered on, home page, USB, after the cold power-up", r.amp.powered and r.amp.page == 1 and e.iram[0x47] == 1)
    check("UART1 on the XMOS line (P_SW1 = 0x40), ES on", e.sfr[P_SW1] == 0x40 and e.sfr[IE] & 0x10)
    m = r.mark()
    ram = bytes(e.iram)
    r.key(pr.COMMAND, 3.0)
    got = r.sent(m)
    want = expected(r.bus, e, ram)
    # the P and R lines hold what the dump read mid-way (the LCD strobes and timers move on): the
    # register files are compared exactly, those two lines on their shape
    strip = lambda t: t.split(pr.PINS)[0]   # noqa: E731
    check("the dump arrived: scan and the three register files as the chips hold them (%d bytes)" % len(got),
          strip(got) == strip(want) and got.endswith(pr.END),
          "" if strip(got) == strip(want) else "\n    got  %r\n    want %r" % (got[-300:], want[-300:]))
    pline = got.split(pr.PINS)[1].split(pr.CRLF)[0] if pr.PINS in got else ""
    check("the P line has one byte per port", len(pline.split()) == len(pr.PORTS), pline)
    rline = got.split(pr.RAM)[1].split(pr.CRLF)[0] if pr.RAM in got else ""
    check("the R line has one byte per RAM address, page 1, input 1, powered",
          rline.split()[:3] == ["01", "01", "01"] and len(rline.split()) == len(pr.RAM_LIST), rline)
    check("every byte left with P_SW1 on the header pins and ES off",
          all(sw == 0 and es == 0 for _, sw, es in r.out[m[0]:]))
    check("P_SW1 back on the XMOS line, ES on", e.sfr[P_SW1] == 0x40 and e.sfr[IE] & 0x10)
    check("nothing written to any chip during the dump but the calculator target",
          not r.audio_writes(m) and not bus_problems(r.bus, m[2]), str(r.audio_writes(m)[:3] + bus_problems(r.bus, m[2])[:3]))
    check("the calculator target is back at stock's value (USB: 00)", r.bus.regs.get((RECEIVER, FS_TARGET)) == 0
          and target_writes(r.bus, m[2])[-1] == 0, str(target_writes(r.bus, m[2])))
    check("the Dimmer setting untouched by the dump", e.iram[0x29] == 1, "%d" % e.iram[0x29])
    v = e.iram[0x31]
    r.key(NEC_VOL_UP, 2.0)
    check("the amp is alive: Vol+ raises the volume", e.iram[0x31] == v + 1, "%d -> %d" % (v, e.iram[0x31]))
    e.iram[0x76], e.iram[0x77], e.iram[0x78] = 1, 4, 0xFF          # an XMOS message, as uart1_isr leaves it
    r.amp.wait(2.0)
    check("XMOS messages are consumed again (format poll)", e.iram[0x75] == 1 and e.iram[0x73] == 4,
          "%02X %02X" % (e.iram[0x75], e.iram[0x73]))
    m = r.mark()
    r.key(NEC_POWER, 3.0)
    check("standby", not r.amp.powered)
    r.key(pr.COMMAND, 2.0)
    check("nothing sent in standby", not r.sent(m), repr(r.sent(m)[:40]))
    check("standby's recovery path untouched: Source in standby still goes to the bootloader",
          open(img_path, "rb").read()[0x3DB8:0x3DBB] == bytes([0x75, 0xC7, 0x60]))
    r.key(NEC_POWER, 12.0)
    m = r.mark()
    r.key(0x04, 1.0)                                  # the menu
    check("in a menu (page %d)" % r.amp.page, r.amp.page == 3)
    r.key(pr.COMMAND, 2.0)
    check("nothing sent in a menu", not r.sent(m), repr(r.sent(m)[:40]))
    r.key(NEC_MENU, 1.5)
    m = r.mark()
    r.key(pr.COMMAND, 3.0)
    check("back home: the dump again", r.amp.page == 1 and r.sent(m).startswith(pr.HEAD) and r.sent(m).endswith(pr.END))


def image_diff():
    print("\nImage diff vs stock")
    a = open(BASE_IMG, "rb").read()
    b = open(TEST_IMG, "rb").read()
    changed = {i for i in range(len(a)) if a[i] != b[i]}
    allowed = set(features.VERSION_PTR_BYTES)
    for addr, orig, op, _ in bp.HOOKS:
        allowed |= {addr, addr + 1, addr + 2}
    for addr, orig, fn, note in bp.PATCHES:
        allowed |= set(range(addr, addr + len(orig)))
    check("only the hooks, the included fixes' patches and the version pointer changed",
          changed <= allowed, str(["%04X" % i for i in sorted(changed - allowed)][:8]))
    check("read_key's call goes to pr_key in the appended code",
          b[0x3DA9] == 0x12 and bp.CODE_ADDR <= (b[0x3DAA] << 8 | b[0x3DAB]) < len(b))
    check("gap up to 0x%04X is 0xFF" % bp.CODE_ADDR, all(x == 0xFF for x in b[len(a):bp.CODE_ADDR]))
    check("every included fix's hook is installed", all(b[addr] == op for addr, _, op, _ in bp.HOOKS))


def finish():
    print("\n" + ("ALL PASS" if not fails else "FAILURES: %s" % ", ".join(fails)))
    sys.exit(1 if fails else 0)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--in":        # run_tests.py: the probe inside another image
        path = features.image(sys.argv[2])
        hook_test(path, None, sys.argv[2])
        scenario(path, sys.argv[2])
        finish()
    image_diff()
    hook_test()
    sweep()
    scenario(TEST_IMG, "the standalone image")
    finish()


if __name__ == "__main__":
    main()
