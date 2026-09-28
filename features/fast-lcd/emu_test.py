#!/usr/bin/env python3
"""Emulator test for the fast-LCD image: the stock UI, drawn faster, otherwise identical.

Two amps run in lockstep, whole firmware from reset with the real Timer0 ISR
(tools/emu/ao300.py): the direct-select image as reference and the fast-LCD image.
USB has a signal from boot (P4.5 low), so the unmute paths run too. The tour:

  Power, Source, Vol+ (volume page) and back home, Menu, Down, Down, Up, menu
  timeout, direct-select HDMI, direct-select USB, Vol- twice, Power off.

Checks:
  * the image differs from direct-select only in the two hooks and the version pointer;
  * the fast pixel and clear routines leave the registers as the stock ones do;
  * after every step, once both screens are idle, they are pixel-identical, and the
    page and power state agree;
  * the audio state (last value per NJW1194 / DAC / expander register, input, mute and
    mux pins, recorded after every write that changes it) goes through the same sequence of states in
    the same order, and never reaches a state later than stock; every change that
    moves by more than 50 ms is listed. Each writer receives the same set of argument
    tuples in both images. (Timers counted in the main loop lose ticks while stock
    drawing blocks it, so with fast drawing they run closer to nominal and the steps
    they pace come earlier.)
  * the unmute path was exercised.

Also prints the drawing time per step: press to the first 100 ms without LCD writes.
Writes build/tour_<step>.png.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "emu"))
sys.path.insert(0, HERE)
from emu8051 import Emu8051            # noqa: E402
from ao300 import Amp, CLOCK_HZ, NEC_POWER, NEC_UP, NEC_MENU, NEC_DOWN, NEC_SOURCE, \
    NEC_VOL_UP, NEC_VOL_DOWN            # noqa: E402
import build_patch as bp               # noqa: E402

NEC_USB, NEC_HDMI = 0x10, 0x14         # direct-select inputs 1 and 5
CHUNK = 0.01                           # lockstep granularity, one Timer0 tick

TOUR = [                               # (step name, NEC command or None, seconds)
    ("home", NEC_POWER, 8.0),
    ("source", NEC_SOURCE, 3.0),
    ("volume_page", NEC_VOL_UP, 1.0),
    ("home_again", None, 2.5),
    ("menu", NEC_MENU, 1.5),
    ("menu_down1", NEC_DOWN, 1.0),
    ("menu_down2", NEC_DOWN, 1.0),
    ("menu_up", NEC_UP, 1.0),
    ("menu_timeout", None, 10.5),
    ("hdmi", NEC_HDMI, 3.0),
    ("usb", NEC_USB, 4.0),
    ("vol_down1", NEC_VOL_DOWN, 0.4),
    ("vol_down2", NEC_VOL_DOWN, 3.0),
    ("standby", NEC_POWER, 3.0),
]

fails = []


def check(name, ok, detail=""):
    print("  %-62s %s %s" % (name, "OK  " if ok else "FAIL", detail))
    if not ok:
        fails.append(name)


def image_diff():
    print("Image diff vs direct-select")
    a = open(bp.BASE_IMAGE, "rb").read()
    b = open(bp.OUT_IMAGE, "rb").read()
    changed = [i for i in range(len(a)) if a[i] != b[i]]
    want = [0x22CB, 0x22CD, 0x5202, 0x5203, 0x5204, 0x5C7C, 0x5C7D, 0x5C7E]
    check("only the two hooks and the version pointer changed", changed == want,
          str(["%04X" % i for i in changed]))


def register_contract():
    print("\nRegister contract of the replaced routines")
    results = {}
    for img_path, label in ((bp.BASE_IMAGE, "stock"), (bp.OUT_IMAGE, "fast")):
        out = []
        for entry, setup in ((0x5C7C, {6: 0xF8, 7: 0x1F}), (0x5C79, {6: 0x12, 7: 0x34}), (0x51EE, {})):
            e = Emu8051(open(img_path, "rb").read())
            e.sfr[0x81] = 0x88
            for n in range(8):
                e.setR(n, 0x10 + n)
            for n, v in setup.items():
                e.setR(n, v)
            e.A = 0x5A
            e.sfr[0xF0] = 0xB5
            e.DPTR = 0x1234
            e.C = 1
            e.lcd.byte(False, 0x2C, 0)                  # RAMWR, so pixel bytes are counted
            e.call(entry)
            regs = tuple(e.R(n) for n in range(8)) + (e.A, e.sfr[0xF0], e.DPTR, e.C, e.sfr[0x81])
            screen = [e.lcd.screen_pixel(x, y) for x in (0, 159, 319) for y in (0, 85, 169)]
            out.append((regs, e.lcd.pixels, screen, e.sfr[0x80] | 0x57, e.sfr[0x90]))
        results[label] = out
    names = ["lcd_write_pixel 0x5C7C", "lcd_write_pixel_black 0x5C79", "lcd_clear_black 0x51EE"]
    for k, n in enumerate(names):
        s, f = results["stock"][k], results["fast"][k]
        check("%s: R0-R7, A, B, DPTR, C, SP as stock" % n, s[0] == f[0],
              "" if s[0] == f[0] else "stock %s fast %s" % (s[0], f[0]))
        check("%s: same pixels, bus left idle as stock" % n, s[1:] == f[1:], "(%d px)" % f[1])


def draw_time(activity, quiet=10):
    """Chunks from the press until the first `quiet` chunks with no LCD writes."""
    for i in range(len(activity)):
        if not any(activity[i:i + quiet]):
            return i * CHUNK
    return len(activity) * CHUNK


def lockstep_tour():
    amps = [Amp(open(p, "rb").read()) for p in (bp.BASE_IMAGE, bp.OUT_IMAGE)]
    for amp in amps:
        amp.set_pin(0xC0, 5, 0)                        # USB audio present
        amp.boot()
    rows = []
    for name, cmd, secs in TOUR:
        w0 = time.time()
        for amp in amps:
            if cmd is not None:
                amp.press(cmd)
        act = [[], []]
        for _ in range(int(round(secs / CHUNK))):
            for k, amp in enumerate(amps):
                p0, n0 = amp.lcd.pixels, len(amp.lcd.log)
                amp.wait(CHUNK)
                act[k].append(amp.lcd.pixels != p0 or len(amp.lcd.log) != n0)
        # compare once both screens have been idle for 30 ms (up to 1 s more)
        idle = 0
        for _ in range(100):
            if idle >= 3:
                break
            busy = False
            for amp in amps:
                p0, n0 = amp.lcd.pixels, len(amp.lcd.log)
                amp.wait(CHUNK)
                busy |= amp.lcd.pixels != p0 or len(amp.lcd.log) != n0
            idle = 0 if busy else idle + 1
        rows.append(dict(name=name, draw=[draw_time(a) for a in act],
                         same=amps[0].lcd.gram == amps[1].lcd.gram,
                         ndiff=sum(1 for x, y in zip(amps[0].lcd.gram, amps[1].lcd.gram) if x != y),
                         state=[(a.page, a.powered) for a in amps], gram=list(amps[1].lcd.gram)))
        print("    %-13s %5.1f s emulated x2 in %5.1f s" % (name, secs, time.time() - w0), flush=True)
    return amps, rows


def main():
    image_diff()
    register_contract()

    print("\nUI tour, both images in lockstep (reference: direct-select)")
    (ref, new), rows = lockstep_tour()
    print("\n  %-14s %10s %10s" % ("step", "stock ms", "fast ms"))
    for r in rows:
        print("  %-14s %10.0f %10.0f" % (r["name"], r["draw"][0] * 1000, r["draw"][1] * 1000))
    print()
    for r in rows:
        check("%-13s screens identical once idle" % r["name"], r["same"],
              "" if r["same"] else "(%d px differ)" % r["ndiff"])
        check("%-13s page %d, power %s in both" % (r["name"], r["state"][0][0], r["state"][0][1]),
              r["state"][0] == r["state"][1])
    os.makedirs(os.path.join(HERE, "build"), exist_ok=True)
    for r in rows:
        new.lcd.gram = r["gram"]
        new.lcd.save_png(os.path.join(HERE, "build", "tour_%s.png" % r["name"]))

    print("\nAudio state, after every write that changes it")
    BACKLIGHT = ("pin", "P0.6 backlight")             # display, compared separately below

    def transitions(amp):
        out, last = [], None
        for c, st in amp.state_changes:
            st = tuple(kv for kv in st if kv[0] != BACKLIGHT)
            if st != last:
                out.append((c / CLOCK_HZ * 100, st))  # time in ticks (10 ms units)
                last = st
        return out
    tr_ref, tr_new = transitions(ref), transitions(new)
    same_order = [st for _, st in tr_ref] == [st for _, st in tr_new]
    check("same sequence of audio states, in the same order", same_order,
          "(%d states)" % len(tr_ref) if same_order else "(%d vs %d states)" % (len(tr_ref), len(tr_new)))
    if same_order:
        shifts = [((kn - kr) * 0.01, kr * 0.01, dict(st)) for (kr, st), (kn, _) in zip(tr_ref, tr_new)]
        later = [x for x in shifts if x[0] > 0.01]
        check("no audio state reached later than in stock", not later,
              "" if not later else "(%d later, first at %.2f s)" % (len(later), later[0][1]))
        prev_ref = None
        print("  audio state changes that move by more than 50 ms (stock time -> shift):")
        for (kr, st), (kn, _) in zip(tr_ref, tr_new):
            d = (kn - kr) * 0.01
            if abs(d) > 0.05:
                changed = {k: v for k, v in st if prev_ref is None or dict(prev_ref).get(k) != v}
                print("    %7.2f s  %+6.2f s  %s" % (kr * 0.01, d, changed))
            prev_ref = st
    else:
        for k, ((kr, a), (kn, b)) in enumerate(zip(tr_ref, tr_new)):
            if a != b:
                da, db = dict(a), dict(b)
                print("    first different state #%d at %.2f / %.2f s: %s" % (k, kr * 0.01, kn * 0.01,
                      {key: (da.get(key), db.get(key)) for key in set(da) | set(db) if da.get(key) != db.get(key)}))
                break
    bl = [[(round(c / CLOCK_HZ, 2), d) for c, nm, d in amp.events if nm == BACKLIGHT[1]] for amp in (ref, new)]
    print("  backlight P0.6 changes, stock: %s" % bl[0])
    print("  backlight P0.6 changes, fast:  %s" % bl[1])
    check("backlight switches the same way (times may be earlier)",
          [d for _, d in bl[0]] == [d for _, d in bl[1]] and
          all(tf <= ts + 0.01 for (ts, _), (tf, _) in zip(bl[0], bl[1])))
    for name in sorted(set(ref.calls) | set(new.calls)):
        a, b = ref.calls.get(name, set()), new.calls.get(name, set())
        check("%-15s same argument sets (%d distinct)" % (name, len(a)), a == b,
              "" if a == b else "only stock: %s only fast: %s" % (sorted(a - b)[:3], sorted(b - a)[:3]))
    unmutes = [d for _, nm, d in new.events if nm == "njw1194_write" and "R5=FF" not in d]
    check("unmute path exercised (NJW1194 written with a volume)", len(unmutes) > 2,
          "(%d writes)" % len(unmutes))

    print("\nALL PASS" if not fails else "\nFAILURES: %s" % fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
