#!/usr/bin/env python3
"""Emulator test for auto-switch stage 1 (to HDMI when the TV comes on, to Bluetooth when a
phone connects, from any input, only while the selected input is silent).

  * the image differs from stock only in the hooks, the included fixes' patches, the version
    pointer and the appended code;
  * the tick hook on the bare CPU: at each phase of stock's countdown exactly the intended bus
    transfers (the HDMI port set at 9, the expander read at 5, the result read and the DIR
    restored at 2, nothing on HDMI but the read), nothing in standby, the stock signal monitor
    still called;
  (Bluetooth is sensed but not in ENABLED by default: its scenarios then check that nothing
  switches; with Bluetooth enabled they check the switch.)
  * all 256 NEC commands through read_key and dispatch_key against a reference the test
    builds (stock plus the same fixes, build/reference.bin), in the states the key path reads:
    identical, the feature is not in the key path;
  * whole firmware from reset with the timer ISRs, the EEPROM model and the I2C model (the
    calculator answers per port, the expander line and the lock pins are set by the test):
      - Optical silent, the TV comes on: the amp goes to HDMI one hold-off later, through the
        same audio events as direct-select's HDMI command on the reference;
      - Optical playing, the TV comes on: no switch; the TV off and on again later, still none;
      - Bluetooth, phone off, the TV comes on: switch to HDMI, and every stock read of the
        result register saw the target on the DIR;
      - Optical silent, a phone connects: switch to Bluetooth; it disconnects: no switch back;
      - the TV already on at power-on: no switch; it goes off and on: a switch;
      - in a menu when the TV comes on: no switch, and none after returning home;
      - on HDMI with the TV off, a phone connects: switch to Bluetooth, and the target was
        never written on HDMI;
      - standby: no bus traffic from the feature; the recovery path untouched;
      - the only register the feature writes is the calculator target, with 2 and 0.
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "emu"))
sys.path.insert(0, HERE)
from emu8051 import Emu8051  # noqa: E402
from ao300 import Amp, CLOCK_HZ, NEC_POWER, NEC_MENU  # noqa: E402
from i2c import I2CBus       # noqa: E402
import build_patch as bp     # noqa: E402
import features              # noqa: E402  (tools/patch, on the path through build_patch)
import auto_switch as asw    # noqa: E402

INTEGRATION = True           # `emu_test.py --in <feature>`: the feature's promises in that image

TEST_IMG = bp.OUT_IMAGE
BASE_IMG = bp.BASE_IMAGE
READ_KEY, DISPATCH_KEY_IF_ANY = 0x3DA2, 0x5D6E
NJW_WRITE, DAC_WRITE, EXPANDER_WRITE_PIN = 0x54EA, 0x4D8A, 0x1A7C
RECEIVER, FS_TARGET, FS_RESULT, EXPANDER = 0x80, 0x37, 0x38, 0xB0
BT_READ_SITE = 0x5845        # bt_hold_mute_poll's read of the result register
EEPROM_READ_DATA, EEPROM_WRITE, EEPROM_ERASE = 0x5970, 0x58AF, 0x59D0
PRESENT = {0x62, 0x80, 0xB0, 0xC0}
ABSENT = {a for a in range(0, 256, 2)} - PRESENT
P4, LOCK_BIT, USB_BIT = 0xC0, 2, 5
NEC_SOURCE, NEC_DS_HDMI, NEC_DS_BT = 0x07, 0x14, 0x13
USB, OPTICAL, COAX, BT, HDMI, AUX = 1, 2, 3, 4, 5, 6
HOLD_S = asw.HOLD * 0.1
# what a used amp holds: magic and power-on flag (sector 0), the settings record (sector 0x0200)
FACTORY = {0x0001: 0x45, 0x0002: 1, 0x0201: 20, 0x0202: 1, 0x0203: 1, 0x0204: 0, 0x0205: 1, 0x0206: 9,
           0x0207: 9, 0x0208: 1, 0x0209: 20, 0x020A: 0, 0x020B: 1, 0x020C: 1}
EE_INPUT = 0x0202

fails = []


def check(name, ok, detail=""):
    print("  %-72s %s %s" % (name, "OK  " if ok else "FAIL", detail))
    if not ok:
        fails.append(name)


def reference_image():
    """Stock plus the fixes this image includes, without the feature (build/reference.bin)."""
    import uikit
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


# ---- the world: TV, phone, streams ------------------------------------------------------------------

class World:
    """What the chips report: the calculator's result per port, the expander's input port 0."""

    def __init__(self, bus):
        self.bus = bus
        self.tv_on = False               # the HDMI port carries a 44.1 kHz stream
        self.phone = False               # expander P0_5
        self.target_at_read = []         # (site, target) for every read of the result register
        bus.absent = set(ABSENT)
        bus.read_fn = self.read

    def read(self, dev, reg):
        if (dev, reg) == (RECEIVER, FS_RESULT):
            target = self.bus.regs.get((RECEIVER, FS_TARGET), 0)
            entry = self.bus.log[-1] if False else None   # noqa: F841  (site comes from the bus in _stop; see below)
            self.target_at_read.append(target)
            if target == asw.HDMI_PORT or target == 5:      # the HDMI I2S, or the main port fed by it on HDMI
                return (target << 4) | 8 if self.tv_on else 0x80
            if target == 0:                                  # the DIR: whatever the selected S/PDIF input carries
                return 0x80
            return (target << 4) | 0x0A                      # an idle port: the wandering code
        if (dev, reg) == (EXPANDER, 0x00):
            return 0x51 | (0x20 if self.phone else 0)
        return None


def bus_writes(bus, mark=0):
    """Register writes after mark, as (device, register, value)."""
    return [(dev, reg, v) for c, site, kind, dev, reg, v, ok in bus.log[mark:] if kind == "W" and reg is not None]


# ---- bare CPU: the tick hook ---------------------------------------------------------------------------

def cpu(image, inp, power, page, countdown):
    e = Emu8051(image)
    e.sfr[0x81] = 0x88
    e.sfr[0xA8] = 0x80
    e.iram[0x4F], e.iram[0x45], e.iram[0x47], e.iram[0x2B] = power, page, inp, 1
    e.iram[0x4B], e.iram[0x4C] = 0, countdown
    e.iram[0x20] |= 0x80                         # the tick flag: main_tick_tasks' tick path
    e.pins[P4] = (0x24, 0x24)                    # no lock, no USB activity
    e.bus = I2CBus(types.SimpleNamespace(e=e))
    e.world = World(e.bus)
    e.monitor = []
    e.hooks[asw.SIGNAL_MONITOR] = lambda em: (em.monitor.append(1), em.ret())
    e.hooks[asw.INPUT_APPLY] = lambda em: (em.monitor.append("apply %d" % em.iram[0x47]), em.ret())
    return e


def hook_test(img_path=TEST_IMG, label="the standalone image"):
    print("\nThe tick hook, %s: bus transfers per phase of the format-poll countdown" % label)
    image = open(img_path, "rb").read()
    want = {asw.SET_PHASE: [(RECEIVER, FS_TARGET, asw.HDMI_PORT)], asw.BT_PHASE: [],
            asw.READ_PHASE: [(RECEIVER, FS_TARGET, 0)], 7: [], 10: []}
    bad = []
    for inp in (USB, OPTICAL, COAX, BT, HDMI, AUX):
        for phase, writes in want.items():
            e = cpu(image, inp, 1, 1, phase)
            e.xram[asw.X_PHASE] = phase + 1 if inp == AUX else 0     # AUX keeps its own phase
            e.call(0x3438, max_steps=2_000_000)
            got = bus_writes(e.bus)
            reads = [(dev, reg) for c, s, k, dev, reg, v, ok in e.bus.log if k == "R"]
            exp_w = [] if inp == HDMI else writes
            exp_r = {asw.BT_PHASE: [(EXPANDER, 0)], asw.READ_PHASE: [(RECEIVER, FS_RESULT)]}.get(phase, [])
            if got != exp_w or reads != exp_r or e.monitor[:1] != [1]:
                bad.append((inp, phase, got, reads, e.monitor))
    check("per input and phase: the intended writes and reads, signal_monitor called first", not bad, str(bad[:3]))
    e = cpu(image, OPTICAL, 0, 1, asw.SET_PHASE)
    e.call(0x3438, max_steps=2_000_000)
    check("standby: no bus traffic, the state cleared", not e.bus.log and all(e.xram[x] == 0 for x in (
        asw.X_HDMI_CNT, asw.X_BT_CNT, asw.X_ACTIVE, asw.X_ARMED)))


def sweep():
    print("\nAll 256 NEC commands through read_key and dispatch_key vs the reference (stock + the same fixes)")
    ref, test = reference_image(), open(TEST_IMG, "rb").read()
    diffs = []
    for power, page in ((1, 1), (0, 1), (1, 2), (1, 3)):
        for cmd in range(256):
            r = []
            for image in (ref, test):
                e = cpu(image, OPTICAL, power, page, 7)
                e.iram[0x6A], e.iram[0x2D] = cmd, 0xFF
                e.iram[0x20] = (e.iram[0x20] & ~0x80) | 0x10
                e.capped = False
                try:
                    e.call(READ_KEY, max_steps=60_000_000)
                    e.call(DISPATCH_KEY_IF_ANY, max_steps=60_000_000)
                except RuntimeError:
                    e.capped = True
                r.append((e.capped, e.pc, bytes(e.iram[:0x89]), bytes(e.xram[:0x1D0]), e.lcd.pixels, bytes(e.sfr),
                          e.monitor))
            if r[0] != r[1]:
                diffs.append((cmd, power, page))
    check("identical to the reference for every command and state", not diffs, "(%d diffs) %s" % (len(diffs), diffs[:4]))


# ---- whole firmware -------------------------------------------------------------------------------

class Run:
    """One amp from reset on the EEPROM and I2C models; a cold power-up turns it on by itself."""

    def __init__(self, image, start_input=OPTICAL, boot=12.0, tv_on=False, phone=False):
        self.eeprom = dict(FACTORY)
        self.eeprom[EE_INPUT] = start_input
        self.amp = Amp(image)
        self.bus = I2CBus(self.amp)
        self.world = World(self.bus)
        self.world.tv_on, self.world.phone = tv_on, phone
        e = self.amp.e
        self.bt_reads = []                       # the calculator target at each stock read on Bluetooth

        def read(em):
            em.sfr[0xC2] = self.eeprom.get((em.sfr[0xC3] << 8) | em.sfr[0xC4], 0xFF)

        def write(em):
            self.eeprom[(em.R(6) << 8) | em.R(7)] = em.R(5)

        def erase(em):
            sector = ((em.R(6) << 8) | em.R(7)) & ~0x1FF
            for k in [k for k in self.eeprom if k & ~0x1FF == sector]:
                del self.eeprom[k]

        def bt_read(em):
            self.bt_reads.append(self.bus.regs.get((RECEIVER, FS_TARGET), 0))
        e.hooks[EEPROM_READ_DATA] = read
        e.hooks[EEPROM_WRITE] = write
        e.hooks[EEPROM_ERASE] = erase
        e.hooks[BT_READ_SITE] = bt_read
        self.switches = []
        e.hooks[asw.INPUT_APPLY] = lambda em: self.switches.append((em.cycles / CLOCK_HZ, em.iram[0x47]))
        self.lock(False)
        self.usb(False)
        self.amp.boot(boot)

    @property
    def input(self):
        return self.amp.e.iram[0x47]

    def lock(self, on):
        self.amp.set_pin(P4, LOCK_BIT, 0 if on else 1)
        self.bus.inputs[(RECEIVER, 0x39)] = 0x08 if on else 0x80

    def usb(self, on):
        self.amp.set_pin(P4, USB_BIT, 0 if on else 1)

    def key(self, cmd, wait=3.0):
        self.amp.press(cmd)
        self.amp.wait(wait)

    def mark(self):
        return len(self.amp.events), len(self.bus.log), len(self.switches)

    def audio(self, mark):
        return [(n, d) for c, n, d in self.amp.events[mark[0]:] if n in ("njw1194_write", "dac_i2c_write",
                                                                         "expander_write", "input_set_hw")]

    def feature_writes(self, mark):
        """Register writes after mark made from the appended code (the feature), as (device, register, value)."""
        return [(dev, reg, v) for c, site, kind, dev, reg, v, ok in self.bus.log[mark[1]:]
                if kind == "W" and reg is not None and site >= bp.CODE_ADDR]

    def audio_from(self, t):
        """Audio events from time t, consecutive repeats collapsed (the re-mute writes stock repeats every tick)."""
        out = []
        for c, n, d in self.amp.events:
            if c / CLOCK_HZ >= t and n in ("njw1194_write", "dac_i2c_write", "expander_write", "input_set_hw"):
                if not out or out[-1] != (n, d):
                    out.append((n, d))
        return out


def scenario_tv_on_from_optical_silent(image, ref):
    print("\nOptical silent, the TV comes on")
    r, f = Run(ref), Run(image)
    for run in (r, f):
        check("boots to Optical, powered", run.amp.powered and run.input == OPTICAL and run.amp.page == 1)
    m = f.mark()
    f.world.tv_on = True
    t0 = f.amp.t
    f.amp.wait(HOLD_S + 1.5)
    check("switched to HDMI once, about one hold-off after the TV came on",
          f.input == HDMI and len(f.switches) == 1 and HOLD_S - 0.3 <= f.switches[0][0] - t0 <= HOLD_S + 0.6,
          str([(round(t - t0, 2), i) for t, i in f.switches]))
    # the reference: direct-select's HDMI command; the same window after its press as after the feature's switch
    ts = f.switches[0][0] if f.switches else f.amp.t
    f.amp.wait(max(0.0, ts + 2.0 - f.amp.t))
    r.key(NEC_DS_HDMI, 2.0)
    tr = r.switches[-1][0] if r.switches else r.amp.t    # from the reference's input_apply, as from the feature's
    fe, re_ = f.audio_from(ts), r.audio_from(tr)
    check("the same audio events as direct-select's HDMI command", fe and fe == re_,
          "%d vs %d events" % (len(fe), len(re_)))
    fw = f.feature_writes(m)
    check("the feature wrote only the calculator target, with 2 and 0",
          fw and all(w[:2] == (RECEIVER, FS_TARGET) and w[2] in (asw.HDMI_PORT, 0) for w in fw), str(fw[:4]))
    check("on HDMI now: the target is stock's (the main port) and the feature leaves it",
          f.bus.regs.get((RECEIVER, FS_TARGET)) == 5)
    m = f.mark()
    f.amp.wait(3.0)
    check("on HDMI the target is never written", not f.feature_writes(m))


def scenario_tv_on_from_optical_playing(image):
    print("\nOptical playing, the TV comes on")
    f = Run(image)
    f.lock(True)
    f.amp.wait(2.0)
    f.world.tv_on = True
    f.amp.wait(HOLD_S + 2.0)
    check("no switch while Optical plays", f.input == OPTICAL and not f.switches, str(f.switches))
    f.world.tv_on = False
    f.amp.wait(2.0)
    f.world.tv_on = True
    f.amp.wait(HOLD_S + 2.0)
    check("still none when the TV goes off and on again", f.input == OPTICAL and not f.switches)
    f.lock(False)
    f.amp.wait(HOLD_S + 2.0)
    check("and none when Optical then falls silent (the activation was dropped)", f.input == OPTICAL and not f.switches)


def scenario_tv_on_from_bluetooth(image):
    print("\nBluetooth, phone off, the TV comes on")
    f = Run(image, start_input=BT)
    check("boots to Bluetooth", f.input == BT)
    f.amp.wait(2.0)
    f.world.tv_on = True
    f.amp.wait(HOLD_S + 2.0)
    check("switched to HDMI", f.input == HDMI and len(f.switches) == 1, str(f.switches))
    check("every stock read of the result register on Bluetooth saw the target on the DIR (%d reads)" % len(f.bt_reads),
          f.bt_reads and set(f.bt_reads) == {0}, str(set(f.bt_reads)))


def scenario_phone_connects(image, ref):
    print("\nOptical silent, a phone connects, later disconnects")
    r, f = Run(ref), Run(image)
    f.world.phone = True
    r.world.phone = True
    t0 = f.amp.t
    f.amp.wait(HOLD_S + 1.5)
    if BT in asw.ENABLED:
        check("switched to Bluetooth once, one hold-off after the connection",
              f.input == BT and len(f.switches) == 1 and HOLD_S - 0.3 <= f.switches[0][0] - t0 <= HOLD_S + 0.6, str(f.switches))
        ts = f.switches[0][0] if f.switches else f.amp.t
        f.amp.wait(max(0.0, ts + 2.0 - f.amp.t))
        r.key(NEC_DS_BT, 2.0)
        tr = r.switches[-1][0] if r.switches else r.amp.t
        fe, re_ = f.audio_from(ts), r.audio_from(tr)
        check("the same audio events as direct-select's Bluetooth command", fe and fe == re_,
              "%d vs %d events" % (len(fe), len(re_)))
        f.world.phone = False
        f.amp.wait(HOLD_S + 2.0)
        check("no switch when the phone disconnects", f.input == BT and len(f.switches) == 1)
        f.world.phone = True
        f.amp.wait(HOLD_S + 2.0)
        check("none when it reconnects (Bluetooth is selected)", f.input == BT and len(f.switches) == 1)
    else:
        check("Bluetooth not enabled: no switch when a phone connects (the line is still read)",
              f.input == OPTICAL and not f.switches and f.amp.e.xram[asw.X_BT_RAW] & 0x20, str(f.switches))
        f.world.phone = False
        f.amp.wait(HOLD_S + 2.0)
        check("and none when it leaves", f.input == OPTICAL and not f.switches)


def scenario_tv_already_on(image):
    print("\nThe TV already on at power-on")
    f2 = Run(image, tv_on=True)
    f2.amp.wait(HOLD_S + 3.0)
    check("no switch: a source on since before the power-on is not an activation",
          f2.input == OPTICAL and not f2.switches, str(f2.switches))
    f2.world.tv_on = False
    f2.amp.wait(1.0)
    f2.world.tv_on = True
    f2.amp.wait(HOLD_S + 2.0)
    check("the TV off and on again: a switch", f2.input == HDMI and len(f2.switches) == 1, str(f2.switches))


def scenario_menu(image):
    print("\nIn a menu when the TV comes on")
    f = Run(image)
    f.key(0x04, 1.0)
    check("in the menu (page %d)" % f.amp.page, f.amp.page == 3)
    f.world.tv_on = True
    f.amp.wait(HOLD_S + 2.0)
    check("no switch in the menu", f.input == OPTICAL and not f.switches)
    f.key(NEC_MENU, 2.0)
    f.amp.wait(HOLD_S + 2.0)
    check("none after returning home either (the activation was dropped)", f.amp.page == 1 and not f.switches)


def scenario_from_hdmi(image):
    print("\nOn HDMI with the TV off, a phone connects")
    f = Run(image, start_input=HDMI)
    check("boots to HDMI", f.input == HDMI)
    m = f.mark()
    f.amp.wait(3.0)
    check("on HDMI the target is never written", not f.feature_writes(m))
    f.world.phone = True
    f.amp.wait(HOLD_S + 2.0)
    if BT in asw.ENABLED:
        check("switched to Bluetooth", f.input == BT and len(f.switches) == 1, str(f.switches))
    else:
        check("Bluetooth not enabled: a phone connecting does not switch", f.input == HDMI and not f.switches)
    f2 = Run(image, start_input=HDMI)
    f2.world.tv_on = True
    f2.amp.wait(2.0)
    f2.world.phone = True
    f2.amp.wait(HOLD_S + 2.0)
    check("with the TV on (HDMI playing) a phone connecting does not switch either", f2.input == HDMI and not f2.switches)


def scenario_standby(image):
    print("\nStandby")
    f = Run(image)
    f.key(NEC_POWER, 3.0)
    check("standby", not f.amp.powered)
    m = f.mark()
    f.world.tv_on = True
    f.world.phone = True
    f.amp.wait(HOLD_S + 2.0)
    check("no bus traffic from the feature in standby", not f.feature_writes(m) and not f.switches,
          str(f.feature_writes(m)[:3]))
    check("standby's recovery path untouched", open(TEST_IMG, "rb").read()[0x3DB8:0x3DBB] == bytes([0x75, 0xC7, 0x60]))
    f.key(NEC_POWER, 12.0)
    check("power on with both sources already on: no switch (grace period)", f.input == OPTICAL and not f.switches)
    f.world.tv_on = False
    f.amp.wait(1.0)
    f.world.tv_on = True
    f.amp.wait(HOLD_S + 2.0)
    check("after that, the TV off and on again: a switch", f.input == HDMI and len(f.switches) == 1)


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
    check("main_tick_tasks' call goes to as_tick in the appended code",
          b[0x3438] == 0x12 and bp.CODE_ADDR <= (b[0x3439] << 8 | b[0x343A]) < len(b))
    check("every included fix's hook is installed", all(b[addr] == op for addr, _, op, _ in bp.HOOKS))


def finish():
    print("\n" + ("ALL PASS" if not fails else "FAILURES: %s" % ", ".join(fails)))
    sys.exit(1 if fails else 0)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--in":        # run_tests.py: the feature inside another image
        path = features.image(sys.argv[2])
        image = open(path, "rb").read()
        hook_test(path, sys.argv[2])
        scenario_tv_on_from_optical_playing(image)
        scenario_tv_on_from_bluetooth(image)
        scenario_tv_already_on(image)
        finish()
    image_diff()
    hook_test()
    sweep()
    image, ref = open(TEST_IMG, "rb").read(), reference_image()
    scenario_tv_on_from_optical_silent(image, ref)
    scenario_tv_on_from_optical_playing(image)
    scenario_tv_on_from_bluetooth(image)
    scenario_phone_connects(image, ref)
    scenario_tv_already_on(image)
    scenario_menu(image)
    scenario_from_hdmi(image)
    scenario_standby(image)
    finish()


if __name__ == "__main__":
    main()
