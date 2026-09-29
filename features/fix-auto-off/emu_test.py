#!/usr/bin/env python3
"""Emulator test for fix-auto-off (Dimmer Auto OFF armed after a power-on).

  * the hook: post_power_on's tail (0x55B9) arms g_screen_off (0x2F:0x30) = 0x01F4 with
    Dimmer on Auto OFF (0x29 = 2) and changes nothing else; with Always ON it is the stock
    tail call;
  * all 256 NEC commands through the IR translate hook (0x5D10) behave as in direct-select,
    in standby and on every page, with either Dimmer setting;
  * the image differs from direct-select only in the hook, the version pointer and the
    appended code;
  * whole firmware from reset with the real Timer0 ISR, base and fix side by side. Dimmer is
    seeded into the emulated EEPROM read (offset 0x020B). Amp runs timer3_isr as well, so
    the idle encoder key 0x2D is 0xFF and read_key does not re-arm the countdown on its own.
    With Auto OFF, after the cold power-up the fix turns the backlight (P0.6) off 500 main
    ticks (~6 s) after post_power_on, where stock stays lit. A key press afterwards times out
    the same on both. After standby -> on the two match as well: the Power key that entered
    standby armed the countdown in stock too. With Always ON both images produce the same
    events.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "emu"))
sys.path.insert(0, HERE)
from emu8051 import Emu8051  # noqa: E402
from ao300 import Amp, CLOCK_HZ, TICK, NEC_POWER, NEC_VOL_UP  # noqa: E402
import build_patch as bp     # noqa: E402
import fix_auto_off as fx    # noqa: E402

TEST_IMG = bp.OUT_IMAGE
BASE_IMG = bp.BASE_IMAGE
APPLY_TAIL = 0x5640                  # direct-select's input apply, needs real hardware
POST_POWER_ON_TAIL = 0x55B9         # post_power_on (0x5585) is done, ~1 s after entry
IAP_READ_DATA = 0x5970               # eeprom_read: mov R7,IAP_DATA
DIMMER_EEPROM = (0x02, 0x0B)         # EEPROM offset of g_dimmer_mode (loaded at 0x306F)
BACKLIGHT = "P0.6 backlight"

fails = []


def check(name, ok, detail=""):
    print("  %-62s %s %s" % (name, "OK  " if ok else "FAIL", detail))
    if not ok:
        fails.append(name)


def image_diff():
    print("\nImage diff vs direct-select")
    a = open(BASE_IMG, "rb").read()
    b = open(TEST_IMG, "rb").read()
    changed = [i for i in range(len(a)) if a[i] != b[i]]
    check("only the hook target (0x55BA, 0x55BB) and version pointer changed",
          {0x55BA, 0x55BB} <= set(changed) <= {0x22CB, 0x22CD, 0x55BA, 0x55BB},
          str(["%04X" % i for i in changed]))
    check("gap up to 0x%04X is 0xFF" % bp.CODE_ADDR, all(x == 0xFF for x in b[len(a):bp.CODE_ADDR]))
    check("hook is ljmp fx_auto_off",
          b[0x55B9] == 0x02 and b[0x55BA:0x55BC] == bytes([bp.CODE_ADDR >> 8, bp.CODE_ADDR & 0xFF]))


def hook_state(img_path, dimmer, preset):
    e = Emu8051(open(img_path, "rb").read())
    e.sfr[0x81] = 0x88
    e.iram[0x29] = dimmer
    e.iram[0x2F], e.iram[0x30] = preset >> 8, preset & 0xFF
    e.iram[0x4F], e.iram[0x45] = 1, 1
    e.call(0x55B9, max_steps=5_000_000)                # post_power_on's tail
    return e


def hook_test():
    print("\nThe hook: post_power_on's tail at 0x55B9")
    for dimmer in (0, 1, 2, 3):
        for preset in (0x0000, 0x0123):
            b = hook_state(BASE_IMG, dimmer, preset)
            t = hook_state(TEST_IMG, dimmer, preset)
            want = fx.SCREEN_OFF_TICKS if dimmer == 2 else preset
            got = (t.iram[0x2F] << 8) | t.iram[0x30]
            others = [i for i in range(256) if i not in (0x2F, 0x30) and b.iram[i] != t.iram[i]]
            check("dimmer %d, countdown 0x%04X -> 0x%04X" % (dimmer, preset, want), got == want,
                  "(0x%04X)" % got)
            check("dimmer %d: other RAM, SP, screen as stock" % dimmer,
                  not others and b.sfr[0x81] == t.sfr[0x81] and b.lcd.gram == t.lcd.gram
                  and b.lcd.pixels == t.lcd.pixels, str(["%02X" % i for i in others]))
            check("dimmer %d: base leaves the countdown alone" % dimmer,
                  (b.iram[0x2F] << 8) | b.iram[0x30] == preset)


def make(img_path, cmd, power, page, dimmer):
    e = Emu8051(open(img_path, "rb").read())
    e.sfr[0x81] = 0x88                       # SP as set by the firmware
    e.sfr[0xA8] = 0x80                       # EA on, as in normal running
    e.iram[0x6A] = cmd
    e.iram[0x4F] = power
    e.iram[0x45] = page
    e.iram[0x29] = dimmer
    e.iram[0x47] = 0x99
    e.iram[0x2B] = 1
    e.iram[0x48], e.iram[0x49] = 0xFF, 0xFF  # theme text colour (white theme)
    e.applied = None

    def apply(em):
        em.applied = em.iram[0x47]
        em.ret()
    e.hooks[APPLY_TAIL] = apply
    return e


def sweep():
    print("\nAll 256 NEC commands vs the direct-select image")
    diffs = 0
    for dimmer in (1, 2):
        for power, page in ((1, 1), (0, 1), (1, 0), (1, 2), (1, 3)):
            for cmd in range(256):
                r = []
                for img in (BASE_IMG, TEST_IMG):
                    e = make(img, cmd, power, page, dimmer)
                    e.call(0x5D10, max_steps=10_000)
                    r.append((e.R(7), e.iram[0x47], e.applied, e.iram[0x6F], e.iram[0x2F], e.iram[0x30],
                              e.lcd.pixels))
                if r[0] != r[1]:
                    diffs += 1
                    print("    cmd 0x%02X dimmer %d power %d page %d: %s vs %s"
                          % (cmd, dimmer, power, page, r[0], r[1]))
    check("identical results for every command, power, page, dimmer", diffs == 0, "(%d diffs)" % diffs)


class Run:
    """One amp from reset, with Dimmer seeded into the EEPROM read and post_power_on logged."""

    def __init__(self, img_path, dimmer):
        self.amp = Amp(open(img_path, "rb").read())
        e = self.amp.e
        self.power_ons = []

        def iap(em):
            if (em.iram[0x58], em.iram[0x59]) == DIMMER_EEPROM:
                em.sfr[0xC2] = dimmer           # IAP_DATA
        e.hooks[IAP_READ_DATA] = iap
        e.hooks[POST_POWER_ON_TAIL] = lambda em: self.power_ons.append(em.cycles / CLOCK_HZ)
        self.amp.boot()

    def backlight(self, since=0.0):
        return [(c / CLOCK_HZ, v) for c, n, v in self.amp.events if n == BACKLIGHT and c / CLOCK_HZ >= since]

    def lit(self):
        return (self.amp.e.sfr[0x80] >> 6) & 1


def scenario_auto_off():
    print("\nFull firmware, Dimmer Auto OFF: power on, wait, Vol+, standby, power on again")
    runs = {name: Run(img, 2) for name, img in (("base", BASE_IMG), ("fix", TEST_IMG))}
    for name, r in runs.items():
        check("%s boots to standby with dimmer 2" % name,
              r.amp.e.iram[0x4F] == 0 and r.amp.e.iram[0x29] == 2)

    for r in runs.values():
        r.amp.press(NEC_POWER)
        r.amp.wait(15.0)
    b, f = runs["base"], runs["fix"]
    check("both powered on, post_power_on ran once", all(r.amp.powered and len(r.power_ons) == 1
                                                          for r in runs.values()))
    t_on = f.power_ons[0]
    lit_at = [t for t, v in f.backlight() if v == "1"]
    off = [t for t, v in f.backlight(t_on) if v == "0"]
    print("  fix: post_power_on done at %.2f s, backlight on at %s, off at %s"
          % (t_on, ["%.2f" % t for t in lit_at], ["%.2f" % t for t in off]))
    check("fix: backlight off 500 main ticks (5-6.5 s) after power-on",
          len(off) == 1 and 5.0 <= off[0] - t_on <= 6.5 and not f.lit(),
          "(%.2f s)" % (off[0] - t_on) if off else "")
    check("base: backlight still on 15 s after Power (the stock bug)",
          b.lit() and not [v for t, v in b.backlight(b.power_ons[0]) if v == "0"])

    # a key press: both light up and arm the same 5 s countdown
    t_key = {}
    for name, r in runs.items():
        t_key[name] = r.amp.t
        r.amp.press(NEC_VOL_UP)
        r.amp.wait(9.0)
    delays = {}
    for name, r in runs.items():
        ev = r.backlight(t_key[name])
        on = [t for t, v in ev if v == "1"]
        of = [t for t, v in ev if v == "0"]
        delays[name] = (of[-1] - t_key[name]) if of else None
        check("%s: Vol+ lights the screen, off again after 5-6.5 s" % name,
              (name == "base" or on) and of and 5.0 <= of[-1] - t_key[name] <= 6.5 and not r.lit(),
              "(%.2f s)" % delays[name] if delays[name] else "")
    check("same key-press timeout on both", delays["base"] is not None and delays["fix"] is not None
          and abs(delays["base"] - delays["fix"]) < 0.05)
    check("fix: power-on timeout matches the key-press timeout", off and delays["fix"] is not None
          and abs((off[0] - t_on) - delays["fix"]) < 0.5)

    # standby, then Power again: the fix arms again
    for r in runs.values():
        r.amp.press(NEC_POWER)
        r.amp.wait(3.0)
    check("both in standby", not b.amp.powered and not f.amp.powered)
    for r in runs.values():
        r.amp.press(NEC_POWER)
        r.amp.wait(18.0)
    check("second power-on ran post_power_on", len(f.power_ons) == 2 and len(b.power_ons) == 2)
    t2 = f.power_ons[1]
    off2 = [t for t, v in f.backlight(t2) if v == "0"]
    print("  fix: second power-on done at %.2f s, backlight off at %s" % (t2, ["%.2f" % t for t in off2]))
    check("fix: second power-on, backlight off 5-6.5 s later",
          len(off2) == 1 and 5.0 <= off2[0] - t2 <= 6.5 and not f.lit(),
          "(%.2f s)" % (off2[0] - t2) if off2 else "")
    # stock is not stuck here: the Power key that entered standby went through the key dispatcher
    # (0x0BBD) and armed the countdown, which froze in standby and drains again once on
    off2b = [t for t, v in b.backlight(b.power_ons[1]) if v == "0"]
    print("  base: second power-on done at %.2f s, backlight off at %s"
          % (b.power_ons[1], ["%.2f" % t for t in off2b]))
    check("base: second power-on times out on the standby key's leftover countdown",
          len(off2b) == 1 and off2b[0] - b.power_ons[1] <= 6.5 and not b.lit())


def scenario_always_on():
    print("\nFull firmware, Dimmer Always ON: identical to stock")
    runs = [Run(img, 1) for img in (BASE_IMG, TEST_IMG)]
    for r in runs:
        r.amp.press(NEC_POWER)
        r.amp.wait(10.0)
        r.amp.press(NEC_VOL_UP)
        r.amp.wait(8.0)
    b, f = runs
    check("both powered on with the backlight on", all(r.amp.powered and r.lit() for r in runs))
    same = [(c, n, v) for c, n, v in b.amp.events] == [(c, n, v) for c, n, v in f.amp.events]
    near = len(b.amp.events) == len(f.amp.events) and all(
        n1 == n2 and v1 == v2 and abs(c1 - c2) < TICK for (c1, n1, v1), (c2, n2, v2)
        in zip(b.amp.events, f.amp.events))
    check("same audio and backlight events in order", same or near,
          "(%d vs %d events)" % (len(b.amp.events), len(f.amp.events)))
    check("countdown never armed", (f.amp.e.iram[0x2F], f.amp.e.iram[0x30]) == (0, 0))


def main():
    image_diff()
    hook_test()
    sweep()
    scenario_auto_off()
    scenario_always_on()
    print("\n" + ("ALL PASS" if not fails else "FAILURES: %s" % ", ".join(fails)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
