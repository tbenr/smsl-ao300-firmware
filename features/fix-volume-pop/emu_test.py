#!/usr/bin/env python3
"""Emulator test for fix-volume-pop (a volume key on Optical or Coaxial without a signal
leaves the audio hardware alone).

  * the image differs from stock only in the four key heads, the tail's call target, the
    version pointer and the appended code;
  * the four volume handlers, run from their entries with unmute_now and volume_apply
    recorded: on Optical and Coaxial without lock the patched ones call neither, leave P2
    as it is, clear the mute key's flag and arm the re-mute request with its countdown;
    the volume, the page, the timers and the screen are as stock. With lock, and on every
    other input, they are stock in everything;
  * all 256 NEC commands through read_key and dispatch_key (0x3DA2, 0x5D6E) against stock,
    for every input class, lock and mute-key state the patch reads, on the home and volume
    pages, in a menu and in standby: only a volume key without lock differs, as above;
  * whole firmware from reset with the real timer ISRs, the I2C slave model and an EEPROM
    model, stock and patched:
      - Source to Optical or Coaxial with nothing connected, then volume keys: stock flips
        P2.7 and P2.2 on the first key and opens the NJW1194 for a tick; the patch changes
        no pin, sends the NJW1194 only its mute code and the DAC only its mute value, on
        speakers and on headphones. The number, the page and the screen are stock's;
      - the signal arrives: the unmute applies the new volume; chips and pins end as stock's;
      - the signal drops while playing, then volume keys: nothing either;
      - mute key on, no signal, a volume key: the mute flag goes, the hardware stays;
      - lock seen low by the key's head and high by its tail: the volume still reaches the
        chip, through the re-mute and unmute the fix arms;
      - USB, Bluetooth, AUX, and Optical with a signal: the same audio events as stock.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "emu"))
sys.path.insert(0, HERE)
from emu8051 import Emu8051  # noqa: E402
from ao300 import Amp, CLOCK_HZ, TICK, NEC_SOURCE, NEC_VOL_UP, NEC_VOL_DOWN  # noqa: E402
from i2c import I2CBus       # noqa: E402
import build_patch as bp     # noqa: E402
import features              # noqa: E402  (tools/patch, on the path through build_patch)

INTEGRATION = True           # `emu_test.py --in <feature>`: the fix's promises in that image
import fix_volume_pop as vp  # noqa: E402

TEST_IMG = bp.OUT_IMAGE
BASE_IMG = bp.BASE_IMAGE
READ_KEY, DISPATCH_KEY_IF_ANY = 0x3DA2, 0x5D6E
UNMUTE_NOW = 0x5A5E                  # clr 0x22.1, mute_state_set(1)
VOLUME_APPLY = 0x4DDC                # R7 = g_volume
NJW_WRITE = 0x54EA                   # R5 data, R7 select
TAIL, TAIL_AFTER_APPLY = 0x0F48, 0x0F4D   # vol_key_tail: mov R7,0x31 / lcall volume_apply / here
HEAD_OFFSET = 0x0C                   # the head's branch on the mute flag and lock, from a handler's entry
EEPROM_READ_DATA, EEPROM_WRITE, EEPROM_ERASE = 0x5970, 0x58AF, 0x59D0
VOL_TABLE, VOL_MAX, MUTE_CODE = 0x9289, 60, 0xFF
DAC, DAC_MUTE_REG, DAC_MUTED, DAC_PLAYING = 0x62, 0x090003, 0xA3, 0xA0
RECEIVER, RATE_REG = 0x80, 0x39
P2, P4, LOCK_BIT = 0xA0, 0xC0, 2     # P4.2 low: the receiver has lock
NEC_MUTE = 0x09
MUTE_PINS = ("P2.2 amp mute", "P2.5 hp", "P2.7 hp")
OPTICAL, COAX = 2, 3
# what a used amp holds: magic and power-on flag (sector 0), the settings record (sector 0x0200)
FACTORY = {0x0001: 0x45, 0x0002: 1, 0x0201: 20, 0x0202: 1, 0x0203: 1, 0x0204: 0, 0x0205: 1, 0x0206: 9,
           0x0207: 9, 0x0208: 1, 0x0209: 20, 0x020A: 0, 0x020B: 1, 0x020C: 1}
EE_OUTPUT = 0x0203

fails = []


def check(name, ok, detail=""):
    print("  %-72s %s %s" % (name, "OK  " if ok else "FAIL", detail))
    if not ok:
        fails.append(name)


def code_of(image, step):
    return image[VOL_TABLE + VOL_MAX - step]


def image_diff():
    print("\nImage diff vs stock")
    a = open(BASE_IMG, "rb").read()
    b = open(TEST_IMG, "rb").read()
    changed = {i for i in range(len(a)) if a[i] != b[i]}
    heads = {entry + HEAD_OFFSET + k for entry in vp.VOLUME_KEYS for k in (0, 1, 3, 4, 5, 6)}
    want = heads | {TAIL + 3, TAIL + 4}
    check("only the four key heads, the tail's call target and the version pointer changed",
          want <= changed <= want | {0x22CB, 0x22CD}, str(["%04X" % i for i in sorted(changed ^ want)]))
    check("gap up to 0x%04X is 0xFF" % bp.CODE_ADDR, all(x == 0xFF for x in b[len(a):bp.CODE_ADDR]))
    check("the tail's call is lcall vp_apply, into the appended code",
          b[TAIL + 2] == 0x12 and bp.CODE_ADDR <= (b[TAIL + 3] << 8 | b[TAIL + 4]) < len(b))


# ---- bare CPU: one key handler, or one command through read_key and dispatch_key ------------------

def cpu(image, inp, lock, muted, output, page, power=1):
    e = Emu8051(image)
    e.sfr[0x81] = 0x88                       # SP as set by the firmware
    e.sfr[0xA8] = 0x80                       # EA on, as in normal running
    e.iram[0x4F], e.iram[0x45], e.iram[0x47], e.iram[0x2B] = power, page, inp, output
    e.iram[0x31], e.iram[0x52] = 20, 18
    e.iram[0x48], e.iram[0x49] = 0xFF, 0xFF  # theme text colour (white theme)
    e.iram[0x22] = 0x02 if muted else 0x00   # 0x22.1: the mute key is on
    e.iram[0x21] = 0x00 if lock else 0x10    # 0x21.4: Timer0 keeps the re-mute request up without lock
    e.iram[0x43], e.iram[0x44] = (0, 0) if lock else (0, 77)
    e.sfr[P2] = 0x5B if output == 1 else 0xFF          # playing: P2.2, P2.5, P2.7 low on speakers, high on headphones
    e.pins[P4] = (1 << LOCK_BIT, 0 if lock else 1 << LOCK_BIT)
    e.p2_start, e.p2_writes, e.njw, e.calls = e.sfr[P2], [], [], []
    e.sfr_watch_mask[P2] = 0xA4
    e.sfr_watch[P2] = lambda em, old, new: em.p2_writes.append(new & 0xA4)
    return e


def others(e, skip):
    return bytes(b for i, b in enumerate(bytes(e.iram)) if i not in skip)


# flags and countdown the fix sets; temporaries of volume_apply (0x5B), njw1194_write (0x5C, 0x5D) and its shifter (0x5E..0x61)
ACTS_SKIP = {0x21, 0x22, 0x43, 0x44, 0x5B, 0x5C, 0x5D, 0x5E, 0x5F, 0x60, 0x61}
ACTS_SKIP |= set(range(0x89, 0x100))     # above SP: return addresses left by stock's deeper calls (unmute_now, the I2C writes)


def acts(inp, lock):
    return inp in (OPTICAL, COAX) and not lock


def quiet_problems(s, f, muted):
    """A patched run f of a volume key without lock against the stock run s: what is wrong."""
    bad = []
    if f.calls or f.njw:
        bad.append("touches the chips: %s %s" % (f.calls, ["%02X" % x for x in f.njw]))
    if f.p2_writes or f.sfr[P2] != f.p2_start:
        bad.append("P2 changed (%02X -> %02X)" % (f.p2_start, f.sfr[P2]))
    if f.iram[0x22] & 0x02:
        bad.append("mute flag 0x22.1 still set")
    if not f.iram[0x21] & 0x10 or (f.iram[0x43], f.iram[0x44]) != (0, 100):
        bad.append("re-mute not armed (0x21=%02X, countdown %d)" % (f.iram[0x21], f.iram[0x43] << 8 | f.iram[0x44]))
    if (f.iram[0x21] ^ s.iram[0x21]) & ~0x10 or (f.iram[0x22] ^ s.iram[0x22]) & ~0x32:
        bad.append("other flags in 0x21, 0x22 differ from stock")
    if others(f, ACTS_SKIP) != others(s, ACTS_SKIP) or f.lcd.pixels != s.lcd.pixels:
        bad.append("volume, page, timers or screen not as stock")
    if not muted and bytes(f.xram) != bytes(s.xram):
        bad.append("XDATA not as stock")
    return bad


def at_handler(image, entry, inp, lock, muted, output, page):
    """Run one volume handler to its return; unmute_now and volume_apply are recorded, not run."""
    e = cpu(image, inp, lock, muted, output, page)

    def unmute_now(em):
        em.calls.append("unmute_now")
        em.iram[0x22] &= ~0x02
        em.ret()

    def volume_apply(em):
        em.calls.append("volume_apply %d" % em.R(7))
        em.ret()
    e.hooks[UNMUTE_NOW] = unmute_now
    e.hooks[VOLUME_APPLY] = volume_apply
    e.call(entry, max_steps=20_000_000)
    return e


def hook_test():
    print("\nThe four volume handlers from their entries, every input, lock, mute flag, output, page")
    stock, fixed = open(BASE_IMG, "rb").read(), open(TEST_IMG, "rb").read()
    quiet_bad, same_bad, stock_plain, stock_muted, n_quiet, n_same = [], [], [], [], 0, 0
    for entry in vp.VOLUME_KEYS:
        for inp in range(1, 7):
            for lock in (0, 1):
                for muted in (0, 1):
                    for output in (1, 2):
                        for page in (1, 2):
                            case = (entry, inp, lock, muted, output, page)
                            s, f = at_handler(stock, *case), at_handler(fixed, *case)
                            if acts(inp, lock):
                                n_quiet += 1
                                bad = quiet_problems(s, f, muted)
                                if bad:
                                    quiet_bad.append(("%04X" % entry,) + case[1:] + (bad,))
                                # the stock behaviour the fix removes
                                if muted:
                                    stock_muted.append(s.calls[:1] == ["unmute_now"] and len(s.calls) == 2)
                                else:
                                    stock_plain.append(s.sfr[P2] & 0xA4 == 0x84 and len(s.calls) == 1)
                            else:
                                n_same += 1
                                if (s.calls, bytes(s.iram), bytes(s.xram), s.sfr[P2], s.p2_writes, s.lcd.pixels,
                                        s.sfr[0x81]) != (f.calls, bytes(f.iram), bytes(f.xram), f.sfr[P2],
                                                         f.p2_writes, f.lcd.pixels, f.sfr[0x81]):
                                    same_bad.append(("%04X" % entry,) + case[1:])
    check("stock, no lock: P2.5 low, P2.7 and P2.2 high, then volume_apply", stock_plain and all(stock_plain))
    check("stock, no lock, mute key on: unmute_now, then volume_apply", stock_muted and all(stock_muted))
    check("patch, Optical/Coaxial without lock: no chip call, P2 kept, re-mute armed (%d cases)" % n_quiet,
          not quiet_bad, str(quiet_bad[:2]))
    check("patch, with lock and on the other inputs: stock in everything (%d cases)" % n_same,
          not same_bad, str(same_bad[:3]))


def through_dispatch(image, cmd, inp, lock, muted, page, power):
    e = cpu(image, inp, lock, muted, 1, page, power)
    e.iram[0x6A] = cmd
    e.iram[0x20] |= 0x10                     # 0x20.4: new IR command
    e.iram[0x2D] = 0xFF                      # encoder idle
    e.visited, e.capped = [], False
    for entry in vp.VOLUME_KEYS:
        e.hooks[entry] = lambda em, entry=entry: em.visited.append(entry)
    e.hooks[NJW_WRITE] = lambda em: em.njw.append(em.R(5))
    try:
        e.call(READ_KEY, max_steps=3_000_000)
        e.call(DISPATCH_KEY_IF_ANY, max_steps=3_000_000)
    except RuntimeError:                     # a handler that waits on hardware: compared where it stopped
        e.capped = True
    return e


def sweep():
    print("\nAll 256 NEC commands through read_key and dispatch_key vs the stock image")
    stock, fixed = open(BASE_IMG, "rb").read(), open(TEST_IMG, "rb").read()
    states = [(inp, lock, muted, page, 1) for page in (1, 2) for inp in (1, OPTICAL, COAX)
              for lock in (0, 1) for muted in (0, 1)]
    states += [(OPTICAL, 0, 0, 1, 0), (OPTICAL, 0, 0, 3, 1), (COAX, 0, 1, 5, 1), (1, 0, 0, 3, 1)]   # standby, menus
    diffs, quiet_bad, volume_cmds, n_quiet = [], [], set(), 0
    for inp, lock, muted, page, power in states:
        for cmd in range(256):
            s = through_dispatch(stock, cmd, inp, lock, muted, page, power)
            f = through_dispatch(fixed, cmd, inp, lock, muted, page, power)
            if s.visited:
                volume_cmds.add(cmd)
            if s.visited and acts(inp, lock):
                n_quiet += 1
                bad = quiet_problems(s, f, muted) + (["not the same handler"] if f.visited != s.visited else [])
                if bad:
                    quiet_bad.append((cmd, inp, lock, muted, page, power, bad))
            else:
                same = (s.visited, s.capped, s.pc, bytes(s.iram), bytes(s.xram), s.njw, s.p2_writes, s.lcd.pixels,
                        bytes(s.sfr)) == (f.visited, f.capped, f.pc, bytes(f.iram), bytes(f.xram), f.njw,
                                          f.p2_writes, f.lcd.pixels, bytes(f.sfr))
                if not same or (not s.visited and s.cycles != f.cycles):
                    diffs.append((cmd, inp, lock, muted, page, power))
    check("the remote's volume commands reach the volume handlers", {NEC_VOL_UP, NEC_VOL_DOWN} <= volume_cmds,
          str(sorted(volume_cmds)))
    check("identical to stock for every command and state but a volume key without lock",
          not diffs, "(%d diffs) %s" % (len(diffs), diffs[:4]))
    check("a volume key without lock: nothing sent, P2 kept, the rest as stock (%d cases)" % n_quiet,
          n_quiet and not quiet_bad, str(quiet_bad[:2]))


# ---- whole firmware -------------------------------------------------------------------------------

class Run:
    """One amp from reset, on an EEPROM model behind the stock IAP routines and the I2C slave
    model. A cold power-up turns it on by itself, on USB, at volume 20."""

    def __init__(self, image, output=1, boot=12.0):
        self.image = image
        self.eeprom = dict(FACTORY)
        self.eeprom[EE_OUTPUT] = output
        self.output = output
        self.amp = Amp(image)
        self.bus = I2CBus(self.amp)
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
        self.lock(False)
        self.amp.boot(boot)

    @property
    def volume(self):
        return self.amp.e.iram[0x31 if self.output == 1 else 0x52]

    @property
    def muted_flag(self):
        return bool(self.amp.e.iram[0x22] & 0x02)

    def lock(self, on):
        self.amp.set_pin(P4, LOCK_BIT, 0 if on else 1)
        self.bus.inputs[(RECEIVER, RATE_REG)] = 0x08 if on else 0x00

    def key(self, cmd, wait=3.0):
        self.amp.press(cmd)
        self.amp.wait(wait)

    def source(self, presses, wait=6.0):
        for _ in range(presses - 1):
            self.key(NEC_SOURCE, 0.5)
        self.key(NEC_SOURCE, wait)

    def mark(self):
        return len(self.amp.events), len(self.bus.log)

    def since(self, mark):
        """(mute pin changes, NJW1194 volume codes, DAC mute register values) after mark."""
        pins, codes = [], []
        for c, name, v in self.amp.events[mark[0]:]:
            if name in MUTE_PINS:
                pins.append("%s=%s" % (name[:4], v))
            elif name == "njw1194_write" and int(v.split("R7=")[1][:2], 16) >> 4 in (0, 1):
                codes.append(int(v.split("R5=")[1][:2], 16))
        dac = [x[5][1] for x in self.bus.log[mark[1]:] if x[2] == "W" and x[3] == DAC and x[4] == DAC_MUTE_REG]
        return pins, codes, dac

    def pins(self):
        p = self.amp.e.sfr[P2]
        return p >> 2 & 1, p >> 5 & 1, p >> 7 & 1

    def chips(self):
        """(NJW1194 volume code, DAC mute register) as last written."""
        return self.amp.state.get(("njw", 0x00)), self.bus.regs.get((DAC, DAC_MUTE_REG))

    def playing(self):
        return (self.pins() == ((0, 0, 0) if self.output == 1 else (1, 1, 1))
                and self.chips() == (code_of(self.image, self.volume), DAC_PLAYING))

    def quiet(self, mark):
        pins, codes, dac = self.since(mark)
        return not pins and set(codes) <= {MUTE_CODE} and set(dac) <= {DAC_MUTED}


def show(run, mark):
    pins, codes, dac = run.since(mark)
    return "pins %s, NJW %s, DAC %s" % (pins, sorted({"%02X" % c for c in codes}), sorted({"%02X" % d for d in dac}))


def no_signal_cases(image, label, fixed, cases):
    """Source to an input with nothing connected, three volume keys, then the signal arrives."""
    for inp, name, output in cases:
        what = "%s, %s, %s" % (label, name, "speakers" if output == 1 else "headphones")
        r = Run(image, output)
        check("%s: playing on USB after the cold power-up" % what, r.amp.powered and r.playing(),
              "%s %s" % (r.pins(), r.chips()))
        r.source(inp - 1)
        before = r.pins()
        m = r.mark()
        r.key(NEC_VOL_UP, 0.5)
        opened = r.amp.e.iram[0x47] == inp and r.amp.page == 2 and r.volume == 21
        r.amp.wait(2.5)
        first = r.since(m)
        if fixed:
            check("%s: first Vol+ shows 21 on the volume page" % what, opened)
            check("%s: first Vol+ changes no pin, NJW1194 and DAC stay muted" % what, r.quiet(m), show(r, m))
        else:                                # on headphones those two are high already; stock drops P2.5 instead
            moved = {"P2.7=1", "P2.2=1"} if output == 1 else {"P2.5=0"}
            check("%s: first Vol+ sets %s and opens the NJW1194 (the bug)" % (what, ", ".join(sorted(moved))),
                  opened and moved == set(first[0]) and code_of(image, 21) in first[1], show(r, m))
        m = r.mark()
        r.key(NEC_VOL_UP)
        r.key(NEC_VOL_DOWN)
        r.key(NEC_VOL_UP)
        if fixed:
            check("%s: three more keys: volume 22, still nothing" % what,
                  r.volume == 22 and r.quiet(m) and r.pins() == before, show(r, m))
        m = r.mark()
        r.lock(True)
        r.amp.wait(3.0)
        check("%s: the signal arrives: unmuted at volume %d" % (what, r.volume), r.playing(),
              "%s %s" % (r.pins(), r.chips()))
        yield what, r


def scenario_no_signal():
    print("\nFull firmware: Source to an input with nothing connected, then volume keys")
    cases = [(OPTICAL, "Optical", 1), (COAX, "Coaxial", 1), (OPTICAL, "Optical", 2), (COAX, "Coaxial", 2)]
    stock = dict(no_signal_cases(open(BASE_IMG, "rb").read(), "stock", False, cases))
    patch = dict(no_signal_cases(open(TEST_IMG, "rb").read(), "patch", True, cases))
    for (ws, s), (wp, p) in zip(stock.items(), patch.items()):
        check("%s: chips, pins, RAM volume and screen end as stock's" % wp,
              s.amp.state == p.amp.state and s.volume == p.volume and s.amp.lcd.gram == p.amp.lcd.gram)


def signal_drop(image, label, fixed):
    for output in (1, 2):
        what = "%s, %s" % (label, "speakers" if output == 1 else "headphones")
        r = Run(image, output)
        r.lock(True)
        r.source(OPTICAL - 1)
        check("%s: playing on Optical with a signal" % what, r.playing(), "%s %s" % (r.pins(), r.chips()))
        r.lock(False)
        r.amp.wait(3.0)
        m = r.mark()
        r.key(NEC_VOL_DOWN)
        r.key(NEC_VOL_DOWN)
        if fixed:
            check("%s: signal lost, two Vol-: volume 18, no pin, chips muted" % what,
                  r.volume == 18 and r.quiet(m), show(r, m))
        else:                                # on headphones the signal-loss mute has the pins there already
            check("%s: signal lost, Vol- opens the NJW1194%s (the bug)" % (what, ", moves P2.7 and P2.2" if output == 1 else ""),
                  not r.quiet(m) and (output == 2 or {"P2.7=1", "P2.2=1"} == set(r.since(m)[0])), show(r, m))
        r.lock(True)
        r.amp.wait(3.0)
        check("%s: the signal is back: unmuted at volume %d" % (what, r.volume), r.playing(),
              "%s %s" % (r.pins(), r.chips()))


def scenario_signal_drop():
    print("\nFull firmware: the signal drops while playing on Optical, then volume keys")
    signal_drop(open(BASE_IMG, "rb").read(), "stock", False)
    signal_drop(open(TEST_IMG, "rb").read(), "patch", True)


def mute_key(image, label, fixed):
    r = Run(image)
    r.source(OPTICAL - 1)
    r.key(NEC_MUTE, 1.0)
    check("%s: mute key on Optical without a signal: flag set" % label, r.muted_flag)
    m = r.mark()
    r.key(NEC_VOL_UP)
    if fixed:
        check("%s: Vol+ clears the mute flag, changes no pin, chips stay muted" % label,
              not r.muted_flag and r.volume == 21 and r.quiet(m), show(r, m))
    else:
        check("%s: Vol+ releases P2.2 and unmutes the DAC without a signal (the bug)" % label,
              not r.muted_flag and "P2.2=0" in r.since(m)[0] and DAC_PLAYING in r.since(m)[2], show(r, m))
    r.lock(True)
    r.amp.wait(3.0)
    check("%s: the signal arrives: unmuted at volume 21" % label, r.playing() and r.volume == 21,
          "%s %s" % (r.pins(), r.chips()))


def scenario_mute_key():
    print("\nFull firmware: mute key on, no signal, then a volume key")
    mute_key(open(BASE_IMG, "rb").read(), "stock", False)
    mute_key(open(TEST_IMG, "rb").read(), "patch", True)


def scenario_lock_flap():
    print("\nFull firmware: lock low at the key's head, high at its tail")
    for label, path in (("stock", BASE_IMG), ("patch", TEST_IMG)):
        r = Run(open(path, "rb").read())
        r.lock(True)
        r.source(OPTICAL - 1)
        e = r.amp.e
        e.hooks[TAIL] = lambda em: r.amp.set_pin(P4, LOCK_BIT, 1)
        e.hooks[TAIL_AFTER_APPLY] = lambda em: r.amp.set_pin(P4, LOCK_BIT, 0)
        r.key(NEC_VOL_UP, 4.0)
        check("%s: volume 21 reaches the NJW1194 and the amp is playing" % label, r.volume == 21 and r.playing(),
              "%s %s" % (r.pins(), r.chips()))


def scenario_same_as_stock():
    print("\nFull firmware, with a signal and on the other inputs: identical to stock")
    for name, presses, lock in (("USB", 0, False), ("Optical with lock", 1, True), ("Coaxial with lock", 2, True),
                                ("Bluetooth", 3, False), ("AUX", 5, False)):
        for output in (1, 2):
            runs = [Run(open(img, "rb").read(), output) for img in (BASE_IMG, TEST_IMG)]
            for r in runs:
                r.lock(lock)
                if presses:
                    r.source(presses)
                r.key(NEC_VOL_UP, 0.4)
                r.key(NEC_VOL_UP, 3.0)
                r.key(NEC_VOL_DOWN, 1.0)
                r.key(NEC_MUTE, 1.0)
                r.key(NEC_VOL_UP, 4.0)
            b, f = runs
            # the tail's extra clocks can move a tick-driven action into the next 10 ms tick
            near = len(b.amp.events) == len(f.amp.events) and all(
                n1 == n2 and v1 == v2 and abs(c1 - c2) < 2 * TICK for (c1, n1, v1), (c2, n2, v2)
                in zip(b.amp.events, f.amp.events))
            what = "%s, output %d" % (name, output)
            check("%s: same audio events in order" % what, near,
                  "(%d vs %d events)" % (len(b.amp.events), len(f.amp.events)))
            # writes in order; the polls' reads can fall on either side of a write
            writes = [[x[3:] for x in r.bus.log if x[2] == "W"] for r in runs]
            reads = [{x[3:5] for x in r.bus.log if x[2] == "R"} for r in runs]
            check("%s: same I2C writes in order, registers read, volume, EEPROM and screen" % what,
                  writes[0] == writes[1] and reads[0] == reads[1] and b.volume == f.volume
                  and b.eeprom == f.eeprom and b.amp.lcd.gram == f.amp.lcd.gram,
                  "(%d vs %d writes)" % (len(writes[0]), len(writes[1])))


def integration(img_path, label):
    """What the fix promises in any image that contains it, on that image alone (run_tests.py runs
    this as "fix-volume-pop in <feature>" for every image that includes the fix)."""
    print("\nIntegration, %s: volume keys without a signal leave the audio hardware alone" % label)
    image = open(img_path, "rb").read()
    list(no_signal_cases(image, "image", True, [(OPTICAL, "Optical", 1), (COAX, "Coaxial", 2)]))
    signal_drop(image, "image", True)
    mute_key(image, "image", True)


def finish():
    print("\n" + ("ALL PASS" if not fails else "FAILURES: %s" % ", ".join(fails)))
    sys.exit(1 if fails else 0)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--in":        # run_tests.py: this fix inside another image
        integration(features.image(sys.argv[2]), sys.argv[2])
        finish()
    image_diff()
    hook_test()
    sweep()
    scenario_no_signal()
    scenario_signal_drop()
    scenario_mute_key()
    scenario_lock_flap()
    scenario_same_as_stock()
    integration(TEST_IMG, "the standalone image")
    finish()


if __name__ == "__main__":
    main()
