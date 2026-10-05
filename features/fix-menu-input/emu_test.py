#!/usr/bin/env python3
"""Emulator test for fix-menu-input (an input chosen in the menu is switched as the Source
key switches it: no supply cycle on P4.0, no second chip setup).

  * the image differs from stock only in the hook (0x5892..0x5894), the version pointer and
    the appended code;
  * input_menu_select (0x588B) run from its entry for every input, with audio_apply_mute and
    input_set_hw recorded: the patched one mutes, arms the format poll and the unmute
    countdown as the Source key's path does, and calls input_set_hw with the input; P4.0
    stays high and the re-init countdown 0x41:0x42 is not armed. Page, list state, save
    timer and screen are stock's;
  * all 256 NEC commands through read_key and dispatch_key against stock, on the INPUT page
    with the cursor on every row, on the other pages and in standby, and all 256 key codes
    through dispatch_key on the INPUT page (front panel and encoder keys): only what reaches
    input_menu_select differs, as above;
  * whole firmware from reset with the real timer ISRs, the I2C slave model, an EEPROM model
    and a signal on every input, stock and patched:
      - stock, an input chosen in the menu: P4.0 low for about 3 s, then the resets, the
        expander and the clock generator set up again, with P2.2 low until the end (the bug);
      - patch, all 30 input pairs through the menu: P4.0, P2.1 and the expander's setup
        registers are not touched, no clock generator write, expander P0_4 stays high, the
        amp plays again within 3.5 s. Pins, NJW1194 words and I2C registers end as stock's
        (but P0_4, and the DAC on AUX, which stock resets), and so does the screen;
      - patch, the six pairs the Source key can do: the audio events and I2C writes after
        the menu's Enter are those after the Source key;
      - the current input chosen again: muted and unmuted as after a switch, nothing else;
      - keys that do not choose an input in the menu (Source, volume, an Output change in
        the menu): identical to stock, clock for clock.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "emu"))
sys.path.insert(0, HERE)
from emu8051 import Emu8051  # noqa: E402
from ao300 import Amp, CLOCK_HZ, NEC_UP, NEC_MENU, NEC_DOWN, NEC_SOURCE, NEC_VOL_UP  # noqa: E402
from i2c import I2CBus       # noqa: E402
import build_patch as bp     # noqa: E402
import features              # noqa: E402  (tools/patch, on the path through build_patch)

INTEGRATION = True
# `emu_test.py --in <feature>`: the fix's promises in that image
STOCK_CODE_END = 0x9400      # patch code starts here in every image: writes from it are a feature's, not stock's
import fix_menu_input as mi  # noqa: E402

TEST_IMG = bp.OUT_IMAGE
BASE_IMG = bp.BASE_IMAGE
NEC_ENTER = 0x04
READ_KEY, DISPATCH_KEY_IF_ANY = 0x3DA2, 0x5D6E
INPUT_MENU_SELECT = 0x588B           # R7 = input
HOOK_SITE = 0x5892                   # its lcall audio_apply_mute
AUDIO_APPLY_MUTE, INPUT_SET_HW = 0x58D3, 0x24D6
EEPROM_READ_DATA, EEPROM_WRITE, EEPROM_ERASE = 0x5970, 0x58AF, 0x59D0
VOL_TABLE, VOL_MAX = 0x9289, 60
EXPANDER, RECEIVER, CLKGEN, DAC = 0xB0, 0x80, 0xC0, 0x62
DAC_MUTE_REG, DAC_PLAYING = 0x090003, 0xA0
EXP_OUT0, EXP_RESET, BT_CLEAR_LINE = 0x02, 0x7F, 0x10     # expander output port 0; its soft reset; P0_4 in port 0
P2, P4 = 0xA0, 0xC0
PAGE_INPUT, CURSOR = 4, 0x17         # the menu's INPUT list; the selected row
NAMES = {1: "USB", 2: "Optical", 3: "Coaxial", 4: "Bluetooth", 5: "HDMI", 6: "AUX"}
AUX = 6
UNMUTE_WITHIN = 3.5                  # the 2 s countdown, then the format the XMOS reports 1 s after the key sets the DAC up again (stock: 4.2 to 5.8 s)
# what a used amp holds: magic and power-on flag (sector 0), the settings record (sector 0x0200)
FACTORY = {0x0001: 0x45, 0x0002: 1, 0x0201: 20, 0x0202: 1, 0x0203: 1, 0x0204: 0, 0x0205: 1, 0x0206: 9,
           0x0207: 9, 0x0208: 1, 0x0209: 20, 0x020A: 0, 0x020B: 1, 0x020C: 1}
EE_INPUT = 0x0202

fails = []


def check(name, ok, detail=""):
    print("  %-78s %s %s" % (name, "OK  " if ok else "FAIL", detail))
    if not ok:
        fails.append(name)


def image_diff():
    print("\nImage diff vs stock")
    a = open(BASE_IMG, "rb").read()
    b = open(TEST_IMG, "rb").read()
    changed = {i for i in range(len(a)) if a[i] != b[i]}
    want = {HOOK_SITE, HOOK_SITE + 1, HOOK_SITE + 2}
    check("only the hook (0x5892..0x5894) and the version pointer changed",
          want <= changed <= want | {0x22CB, 0x22CD}, str(["%04X" % i for i in sorted(changed ^ want)]))
    check("gap up to 0x%04X is 0xFF" % bp.CODE_ADDR, all(x == 0xFF for x in b[len(a):bp.CODE_ADDR]))
    check("hook is ljmp mi_switch, into the appended code",
          b[HOOK_SITE] == 0x02 and bp.CODE_ADDR <= (b[HOOK_SITE + 1] << 8 | b[HOOK_SITE + 2]) < len(b))


# ---- bare CPU -------------------------------------------------------------------------------------

def cpu(image, inp, page=PAGE_INPUT, cursor=0, power=1):
    e = Emu8051(image)
    e.sfr[0x81] = 0x88                       # SP as set by the firmware
    e.sfr[0xA8] = 0x80                       # EA on, as in normal running
    e.iram[0x4F], e.iram[0x45], e.iram[0x47], e.iram[0x2B] = power, page, inp, 1
    e.iram[CURSOR], e.iram[0x16] = cursor, 0
    e.iram[0x31], e.iram[0x52] = 20, 18
    e.iram[0x48], e.iram[0x49] = 0xFF, 0xFF  # theme text colour (white theme)
    e.iram[0x22] = 0x30                      # 0x22.4, 0x22.5: playing
    e.iram[0x43], e.iram[0x44], e.iram[0x4B], e.iram[0x4C] = 0, 0, 0, 7
    e.sfr[P2], e.sfr[P4] = 0x5B, 0xFF        # playing on speakers; P4.0 high
    e.calls, e.visited = [], []
    return e


TIMERS = {0x41, 0x42, 0x43, 0x44, 0x4B, 0x4C}      # re-init countdown (stock), unmute and format-poll countdowns (the fix)


def others(e, skip):
    return bytes(b for i, b in enumerate(bytes(e.iram)) if i not in skip)


def at_select(image, inp):
    """input_menu_select to its return; audio_apply_mute and input_set_hw are recorded, not run."""
    e = cpu(image, inp)

    def mute(em):
        em.calls.append("mute, 0x22.4=%d" % (em.iram[0x22] >> 4 & 1))
        em.ret()

    def set_hw(em):
        em.calls.append("input_set_hw %d" % em.R(7))
        em.ret()
    e.hooks[AUDIO_APPLY_MUTE] = mute
    e.hooks[INPUT_SET_HW] = set_hw
    e.setR(7, inp)
    e.call(INPUT_MENU_SELECT, max_steps=20_000_000)
    return e


def timers(e):
    i = e.iram
    return i[0x41] << 8 | i[0x42], i[0x43] << 8 | i[0x44], i[0x4B] << 8 | i[0x4C]


def hook_test():
    print("\ninput_menu_select from its entry, every input")
    stock, fixed = open(BASE_IMG, "rb").read(), open(TEST_IMG, "rb").read()
    stock_ok, patch_ok, rest_ok = [], [], []
    for inp in range(1, 7):
        s, f = at_select(stock, inp), at_select(fixed, inp)
        stock_ok.append(s.calls == ["mute, 0x22.4=0"] and not s.sfr[P4] & 1 and timers(s) == (300, 0, 7))
        patch_ok.append(f.calls == ["mute, 0x22.4=0", "input_set_hw %d" % inp] and f.sfr[P4] == 0xFF
                        and timers(f) == (0, 200, 10))
        rest_ok.append(others(s, TIMERS) == others(f, TIMERS) and bytes(s.xram) == bytes(f.xram)
                       and s.lcd.pixels == f.lcd.pixels and s.sfr[0x81] == f.sfr[0x81] and s.sfr[P2] == f.sfr[P2])
    check("stock: mute, P4.0 low, re-init countdown 300, no input_set_hw", all(stock_ok), str(stock_ok))
    check("patch: mute, input_set_hw(input), unmute countdown 200, format poll in 10, P4.0 kept", all(patch_ok),
          str(patch_ok))
    check("patch: page, list state, save timer, other RAM, XDATA, SP and screen as stock", all(rest_ok), str(rest_ok))


def through_dispatch(image, inp, page, cursor, power, cmd=None, key=None):
    e = cpu(image, inp, page, cursor, power)
    e.iram[0x2D] = 0xFF                      # encoder idle
    e.hooks[INPUT_MENU_SELECT] = lambda em: em.visited.append(em.R(7))
    e.hooks[INPUT_SET_HW] = lambda em: em.calls.append(em.R(7))
    e.capped = False
    try:
        if cmd is not None:
            e.iram[0x6A] = cmd
            e.iram[0x20] |= 0x10             # 0x20.4: new IR command
            e.call(READ_KEY, max_steps=3_000_000)
        else:
            e.setR(7, key)
        e.call(DISPATCH_KEY_IF_ANY, max_steps=3_000_000)
    except RuntimeError:                     # a handler that waits on hardware: compared where it stopped
        e.capped = True
    return e


def select_problems(s, f):
    """A patched run f that reached input_menu_select against the stock run s: what is wrong."""
    bad = []
    if f.visited != s.visited or f.capped or s.capped:
        bad.append("not the same call (%s vs %s)" % (s.visited, f.visited))
    if s.sfr[P4] & 1 or timers(s)[0] != 300:
        bad.append("stock did not start the P4.0 cycle")
    if not f.sfr[P4] & 1 or timers(f)[0] != 0:
        bad.append("patch: P4.0 low or re-init armed")
    if timers(f)[1:] != (200, 10) or f.calls != [f.iram[0x47]] or s.calls:
        bad.append("patch: countdowns %s, input_set_hw %s" % (timers(f)[1:], f.calls))
    if (f.iram[0x47], f.iram[0x45], f.iram[CURSOR], f.lcd.pixels) != (s.iram[0x47], s.iram[0x45], s.iram[CURSOR], s.lcd.pixels):
        bad.append("input, page, cursor or screen not as stock")
    return bad


def sweep():
    print("\nAll 256 NEC commands (read_key, dispatch_key) and all 256 key codes (dispatch_key) vs the stock image")
    stock, fixed = open(BASE_IMG, "rb").read(), open(TEST_IMG, "rb").read()
    states = [(inp, PAGE_INPUT, cursor, 1) for cursor in range(6) for inp in (1, 4)]
    states += [(2, 1, 0, 1), (2, 2, 0, 1), (2, 3, 0, 1), (2, 5, 1, 1), (2, 1, 0, 0)]      # home, volume, menu, OUTPUT, standby
    diffs, bad, n_select, selectors = [], [], 0, set()
    runs = [(st, {"cmd": c}) for st in states for c in range(256)]
    runs += [((3, PAGE_INPUT, 2, 1), {"key": k}) for k in range(256)]
    for (inp, page, cursor, power), how in runs:
        s = through_dispatch(stock, inp, page, cursor, power, **how)
        f = through_dispatch(fixed, inp, page, cursor, power, **how)
        if s.visited:
            n_select += 1
            selectors.add(tuple(how.items())[0])
            p = select_problems(s, f)
            if p:
                bad.append((how, inp, page, cursor, p))
        elif (s.capped, s.pc, bytes(s.iram), bytes(s.xram), s.calls, s.lcd.pixels, bytes(s.sfr), s.cycles) != (
                f.capped, f.pc, bytes(f.iram), bytes(f.xram), f.calls, f.lcd.pixels, bytes(f.sfr), f.cycles):
            diffs.append((how, inp, page, cursor, power))
    check("Enter on the INPUT page reaches input_menu_select", ("cmd", NEC_ENTER) in selectors, str(sorted(selectors)))
    check("identical to stock, clock for clock, for everything that does not reach it", not diffs,
          "(%d diffs) %s" % (len(diffs), diffs[:4]))
    check("what reaches it: P4.0 kept, input_set_hw(input), the rest as stock (%d cases)" % n_select,
          n_select and not bad, str(bad[:2]))


# ---- whole firmware -------------------------------------------------------------------------------

class Run:
    """One amp from reset, on an EEPROM model behind the stock IAP routines and the I2C slave
    model, with a signal on every input. A cold power-up turns it on by itself, at volume 20,
    on the stored input."""

    def __init__(self, image, inp=1, boot=14.0):
        self.image = image
        self.eeprom = dict(FACTORY)
        self.eeprom[EE_INPUT] = inp
        self.amp = Amp(image)
        self.bus = I2CBus(self.amp)
        self.pins = []                       # (cycle, "P4.0=0") for the supply and reset pins
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
        for sfr, name, bits in ((P4, "P4", (0, 3, 4)), (P2, "P2", (1, 2, 5, 7))):
            prev = e.sfr_watch.get(sfr)
            e.sfr_watch_mask[sfr] = e.sfr_watch_mask.get(sfr, 0) | sum(1 << b for b in bits)

            def watch(em, old, new, name=name, bits=bits, prev=prev):
                if prev:
                    prev(em, old, new)
                for b in bits:
                    if (old ^ new) & (1 << b):
                        self.pins.append((em.cycles, "%s.%d=%d" % (name, b, new >> b & 1)))
            e.sfr_watch[sfr] = watch
        self.signals()
        self.amp.boot(boot)
        self.signals()
        self.amp.wait(1.0)                   # the format poll takes the XMOS message and sets the DAC up before any key

    @property
    def input(self):
        return self.amp.e.iram[0x47]

    def signals(self):
        """Something playing on every input: USB activity and an XMOS message, receiver lock and
        rate, the Bluetooth and HDMI signal lines."""
        a, i, sig = self.amp, self.amp.e.iram, self.bus.inputs
        a.set_pin(P4, 5, 0)
        a.set_pin(P4, 2, 0)
        sig[(EXPANDER, 1)], sig[(EXPANDER, 0)] = 0x30, 0x20
        sig[(RECEIVER, 0x39)], sig[(RECEIVER, 0x38)] = 0x08, 0x09
        i[0x76], i[0x77], i[0x78] = 1, 1, 0xFF

    def key(self, cmd, wait):
        self.amp.press(cmd)
        self.amp.wait(wait)

    def mark(self):
        return len(self.amp.events), len(self.bus.log), len(self.pins), self.amp.t

    def switched(self, after=9.0):
        """After the key that switches: the XMOS answers 1 s later, then the amp settles."""
        self.amp.wait(1.0)
        self.signals()
        self.amp.wait(after - 1.0)

    def menu_select(self, target, home=True):
        """Open the menu, the INPUT list, move to the target's row; returns the mark before the Enter that chooses it."""
        e = self.amp.e
        self.key(NEC_ENTER, 0.8)
        for _ in range(12):
            if e.iram[CURSOR] == 0:
                break
            self.key(NEC_UP, 0.4)
        self.key(NEC_ENTER, 0.8)
        opened = self.amp.page == PAGE_INPUT
        for _ in range(8):
            if e.iram[CURSOR] == target - 1:
                break
            self.key(NEC_DOWN if e.iram[CURSOR] < target - 1 else NEC_UP, 0.4)
        m = self.mark()
        self.amp.press(NEC_ENTER)
        self.switched()
        if home:
            self.key(NEC_MENU, 1.0)
            self.key(NEC_MENU, 4.0)
        return m if opened and e.iram[0x47] == target else None

    def pin_events(self, m):
        return [(round((c / CLOCK_HZ) - m[3], 2), p) for c, p in self.pins[m[2]:]]

    def writes(self, m, dev=None):
        """Register writes after the mark, from stock code only: a feature that polls a chip on its
        own schedule (auto-switch's calculator target) is not part of either switching sequence."""
        return [x[3:6] for x in self.bus.log[m[1]:] if x[2] == "W" and (dev is None or x[3] == dev)
                and x[1] < STOCK_CODE_END]

    def audio(self, m):
        """Audio events after the mark, without their times. An NJW1194 write is its data and
        select bytes (R5, R7); the harness also logs R3 and R4, which the writer does not read."""
        return [(n, v[12:] if n == "njw1194_write" else v) for c, n, v in self.amp.events[m[0]:] if "backlight" not in n]

    def playing(self):
        vol = self.image[VOL_TABLE + VOL_MAX - self.amp.e.iram[0x31]]
        return (self.amp.e.sfr[P2] & 0xA4 == 0 and self.amp.state.get(("njw", 0x00)) == vol
                and self.bus.regs.get((DAC, DAC_MUTE_REG)) == DAC_PLAYING)

    def unmute_time(self, m):
        t = [x[0] / CLOCK_HZ - m[3] for x in self.bus.log[m[1]:]
             if x[2] == "W" and x[3] == DAC and x[4] == DAC_MUTE_REG and x[5][1] == DAC_PLAYING]
        return t[-1] if t else None

    def end_state(self):
        e = self.amp.e
        ports = tuple(e.sfr[p] & mask for p, mask in ((0x80, 0x57), (P2, 0xFE), (0xB0, 0x7F), (P4, 0xFD)))
        njw = {k: v for k, v in self.amp.state.items() if k[0] == "njw"}
        regs = {k: v for k, v in self.bus.regs.items() if k != (0x80, 0x37)}   # the calculator target: a feature
        return ports, regs, njw                                                  # (auto-switch) moves it on its own clock


def stock_cycle():
    print("\nFull firmware, stock: an input chosen in the menu (the bug)")
    image = open(BASE_IMG, "rb").read()
    for frm, to in ((1, AUX), (AUX, 1)):
        r = Run(image, frm)
        m = r.menu_select(to)
        pins = r.pin_events(m) if m else []
        low = [t for t, p in pins if p == "P4.0=0"]
        high = [t for t, p in pins if p == "P4.0=1"]
        mute = [t for t, p in pins if p == "P2.2=1"]
        what = "stock, %s to %s" % (NAMES[frm], NAMES[to])
        check("%s: P4.0 low at the key, high 3 to 4 s later" % what,     # 300 main ticks; the DAC setup on USB stretches them
              len(low) == 1 and len(high) == 1 and low[0] < 0.05 and 2.9 < high[0] - low[0] < 4.5, str(pins[:4]))
        check("%s: then the P2.1 reset, expander reset and clock generator writes" % what,
              bool(m) and ("P2.1=0" in [p for t, p in pins]) and (EXPANDER, EXP_RESET, 0) in r.writes(m, EXPANDER)
              and len(r.writes(m, CLKGEN)) > 40)
        check("%s: P2.2 stays low until after P4.0 is back" % what, bool(mute) and bool(high) and min(mute) > high[0],
              str(mute[:2]))
        check("%s: expander P0_4 is left low" % what, not r.bus.regs.get((EXPANDER, EXP_OUT0), 0) & BT_CLEAR_LINE)


def quiet_switch(r, m, what):
    """A patched menu choice: nothing of the stock cycle, and playing again soon."""
    pins = [p for t, p in r.pin_events(m)] if m else ["no switch"]
    exp = r.writes(m, EXPANDER) if m else []
    check("%s: P4.0 and P2.1 untouched, no expander setup, no clock generator write" % what,
          bool(m) and not [p for p in pins if p[:4] in ("P4.0", "P2.1")] and not r.writes(m, CLKGEN)
          and all(reg == EXP_OUT0 or reg == 0x03 for d, reg, v in exp), "%s %s" % (pins[:4], exp[:3]))
    t = r.unmute_time(m) if m else None
    check("%s: expander P0_4 still high, playing again within %.1f s" % (what, UNMUTE_WITHIN),
          bool(m) and bool(r.bus.regs.get((EXPANDER, EXP_OUT0), 0) & BT_CLEAR_LINE) and r.playing()
          and t is not None and t < UNMUTE_WITHIN, "(unmute at %s s)" % (None if t is None else round(t, 2)))


def same_end(s, p, target):
    """Pins, NJW1194 words and I2C registers of a patched run against the stock run, apart from
    what the stock cycle resets: expander P0_4, and on AUX the DAC (which AUX does not use)."""
    sp, sr, sn = s.end_state()
    pp, pr, pn = p.end_state()
    for regs in (sr, pr):
        regs[(EXPANDER, EXP_OUT0)] = regs.get((EXPANDER, EXP_OUT0), 0) & ~BT_CLEAR_LINE
        if target == AUX:
            for k in [k for k in regs if k[0] == DAC]:
                del regs[k]
    diff = [k for k in set(sr) | set(pr) if sr.get(k) != pr.get(k)]
    return (sp, sn) == (pp, pn) and not diff, "%s %s" % ([hex(x) for x in pp], sorted(diff, key=repr)[:3])


def scenario_pairs():
    print("\nFull firmware: all 30 input pairs through the menu, patch against stock")
    stock, fixed = open(BASE_IMG, "rb").read(), open(TEST_IMG, "rb").read()
    quiet, ends, screens, bad = 0, 0, 0, []
    for frm in range(1, 7):
        for to in range(1, 7):
            if frm == to:
                continue
            s, p = Run(stock, frm), Run(fixed, frm)
            ms, mp = s.menu_select(to), p.menu_select(to)
            what = "%s to %s" % (NAMES[frm], NAMES[to])
            pins = [x for t, x in p.pin_events(mp)] if mp else ["no switch"]
            t = p.unmute_time(mp) if mp else None
            ok = (mp and ms and not [x for x in pins if x[:4] in ("P4.0", "P2.1")] and not p.writes(mp, CLKGEN)
                  and (EXPANDER, EXP_RESET, 0) not in p.writes(mp, EXPANDER)
                  and p.bus.regs.get((EXPANDER, EXP_OUT0), 0) & BT_CLEAR_LINE and p.playing() and t is not None and t < UNMUTE_WITHIN)
            quiet += bool(ok)
            end, detail = same_end(s, p, to)
            ends += end
            screen = s.amp.page == p.amp.page == 1 and s.amp.lcd.gram == p.amp.lcd.gram
            screens += screen
            if not (ok and end and screen):
                bad.append((what, bool(ok), pins[:3], t, end, detail, screen))
    check("patch: no P4.0 or P2.1 change, no chip re-setup, P0_4 high, playing within %.1f s (30 pairs)" % UNMUTE_WITHIN,
          quiet == 30,
          "(%d) %s" % (quiet, bad[:2]))
    check("patch: pins, NJW1194 and I2C registers end as stock's, but P0_4 and the DAC on AUX (30 pairs)", ends == 30,
          "(%d) %s" % (ends, bad[:2]))
    check("patch: home screen afterwards as stock's (30 pairs)", screens == 30, "(%d) %s" % (screens, bad[:2]))


def as_source_key(image, label):
    """The six switches the Source key can do: through the menu the amp sees the same events."""
    same, bad = 0, []
    for frm in range(1, 7):
        to = frm % 6 + 1
        k, m = Run(image, frm), Run(image, frm)
        mk = k.mark()
        k.amp.press(NEC_SOURCE)
        k.switched()
        mm = m.menu_select(to, home=False)
        ok = (mm and k.input == to and k.audio(mk) == m.audio(mm) and k.writes(mk) == m.writes(mm)
              and [x for t, x in k.pin_events(mk)] == [x for t, x in m.pin_events(mm)]      # each path starts a few ms after its key
              and k.end_state() == m.end_state())
        same += bool(ok)
        if not ok:
            bad.append((NAMES[frm], NAMES[to], len(k.audio(mk)), len(m.audio(mm)) if mm else None))
    check("%s: menu choice = Source key: same audio events, I2C writes, pin changes and end state (6 pairs)" % label,
          same == 6, "(%d) %s" % (same, bad[:3]))


def same_input(image, label):
    r = Run(image, 1)
    m = r.menu_select(1)
    quiet_switch(r, m, "%s, USB chosen again" % label)


def scenario_other_keys():
    print("\nFull firmware, keys that do not choose an input in the menu: identical to stock")
    runs = [Run(open(img, "rb").read(), 1) for img in (BASE_IMG, TEST_IMG)]
    for r in runs:
        r.amp.press(NEC_SOURCE)
        r.switched(5.0)
        r.key(NEC_VOL_UP, 3.0)
        r.key(NEC_ENTER, 0.8)                # menu
        r.key(NEC_DOWN, 0.4)                 # Output
        r.key(NEC_ENTER, 0.8)
        r.key(NEC_DOWN, 0.4)                 # Headphones
        r.key(NEC_ENTER, 4.0)
        r.key(NEC_MENU, 1.0)
        r.key(NEC_MENU, 3.0)
    b, f = runs
    check("Source, Vol+, Output to Headphones in the menu: same events and I2C transfers at the same clocks",
          b.amp.e.iram[0x2B] == 2 and b.amp.events == f.amp.events and b.bus.log == f.bus.log and b.pins == f.pins
          and b.amp.lcd.gram == f.amp.lcd.gram and b.eeprom == f.eeprom,
          "(%d vs %d events, output %d)" % (len(b.amp.events), len(f.amp.events), b.amp.e.iram[0x2B]))


def integration(img_path, label):
    """What the fix promises in any image that contains it, on that image alone (run_tests.py runs
    this as "fix-menu-input in <feature>" for every image that includes the fix)."""
    print("\nIntegration, %s: an input chosen in the menu is switched as the Source key switches it" % label)
    image = open(img_path, "rb").read()
    for frm, to in ((1, AUX), (AUX, 1), (1, 2), (5, 4)):
        r = Run(image, frm)
        m = r.menu_select(to)
        quiet_switch(r, m, "image, %s to %s" % (NAMES[frm], NAMES[to]))
        check("image, %s to %s: back on the home page" % (NAMES[frm], NAMES[to]), r.amp.page == 1)
    same_input(image, "image")
    as_source_key(image, "image")


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
    stock_cycle()
    scenario_pairs()
    scenario_other_keys()
    integration(TEST_IMG, "the standalone image")
    finish()


if __name__ == "__main__":
    main()
