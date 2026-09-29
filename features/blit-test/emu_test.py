#!/usr/bin/env python3
"""Emulator test for the tuned-blit test image.

Runs the IR translate hook (0x5D10) of the built image in the full 8051 emulator
(tools/emu/emu8051.py), with STC8 clock counts and the LCD bus decoded into an
ST7789 model, and checks:

  * NEC 0x16 / 0x17 on the home screen: 10 full-screen fills, 8 colour bars with
    the right colours and edges, a 3-digit tick count, page 0 and a 500-tick hold,
    key eaten (R7 = 0xFF);
  * clocks per full-screen fill for both paths, and the number the amp will show;
  * the same commands in standby or in a menu do nothing;
  * every other NEC command behaves exactly as in the direct-select image;
  * whole firmware from reset (tools/emu/ao300.py Amp: the real Timer0 ISR every 10 ms and
    timer3_isr every 0.5 ms): boot, Power,
    Vol+ / Vol- on the home screen, then 7 s of main loop. The bars must stay
    untouched for the 5 s hold and the home screen must come back unchanged. (The
    hook-only checks above missed the read_key tail at 0x3DD6, which turned the
    first build's page-2 hold into an immediate "go home".)

Writes build/emu_tuned.png and build/emu_stock.png (the final test screens) and
build/boot_*.png (home before, bars during the hold, home after).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "emu"))
sys.path.insert(0, HERE)
from emu8051 import Emu8051  # noqa: E402
from ao300 import Amp        # noqa: E402
import build_patch as bp     # noqa: E402

CLOCK_HZ = 24_000_000
TICK = CLOCK_HZ // 100               # Timer0 ISR every 10 ms
TEST_IMG = bp.OUT_IMAGE
BASE_IMG = bp.BASE_IMAGE
APPLY_TAIL = 0x5640                  # direct-select's input apply, needs real hardware
FULL = 320 * 170

fails = []


def check(name, ok, detail=""):
    print("  %-58s %s %s" % (name, "OK  " if ok else "FAIL", detail))
    if not ok:
        fails.append(name)


def isr_tick(e):
    """What the Timer0 ISR does with the return-home countdown 0x3F:0x40 (0x3ED9)."""
    v = (e.iram[0x3F] << 8) | e.iram[0x40]
    if v:
        v -= 1
        e.iram[0x3F], e.iram[0x40] = v >> 8, v & 0xFF
        if v == 0:
            e.iram[0x45] = 1
            e.iram[0x22] |= 0x08             # bit 0x22.3: redraw page


def make(img_path, cmd, power=1, page=1):
    e = Emu8051(open(img_path, "rb").read())
    e.sfr[0x81] = 0x88                       # SP as set by the firmware
    e.sfr[0xA8] = 0x80                       # EA on, as in normal running
    e.iram[0x6A] = cmd
    e.iram[0x4F] = power
    e.iram[0x45] = page
    e.iram[0x47] = 0x99
    e.iram[0x2B] = 1
    e.iram[0x48], e.iram[0x49] = 0xFF, 0xFF  # theme text colour (white theme)
    e.applied = None

    def apply(em):
        em.applied = em.iram[0x47]
        em.ret()
    e.hooks[APPLY_TAIL] = apply
    e.tick_every = TICK
    e.on_tick = isr_tick
    e.start_ticks()
    return e


def run_test(cmd, label, png):
    print("\nNEC 0x%02X (%s), powered on, home screen" % (cmd, label))
    e = make(TEST_IMG, cmd)
    e.call(0x5D10)
    lcd = e.lcd
    ramwr = [c for c, v in lcd.log if v == 0x2C]
    fills = ramwr[:bp.NFILLS + 1]            # RAMWR of fill k .. fill k+1
    per_fill = [(b - a) for a, b in zip(fills, fills[1:])]
    clocks = sum(per_fill) / len(per_fill)
    ms = clocks / CLOCK_HZ * 1000
    ticks = e.xram[bp.V_TICKS]
    expect_ticks = min(255, int(round((ramwr[bp.NFILLS] - ramwr[0]) / TICK)))
    print("  clocks per full-screen fill: %.0f  (%.2f clocks/px, %.1f ms)" % (clocks, clocks / FULL, ms))
    check("key eaten (R7 = 0xFF)", e.R(7) == 0xFF)
    check("page left on %d for the hold" % bp.HOLD_PAGE, e.iram[0x45] == bp.HOLD_PAGE)
    hold = (e.iram[0x3F] << 8) | e.iram[0x40]
    check("return-home countdown loaded", 495 <= hold <= 500, "(%d)" % hold)
    npx = bp.NFILLS * FULL + 8 * 40 * 170
    check("pixels written >= 10 fills + bars", lcd.pixels >= npx, "(%d)" % lcd.pixels)
    check("digit value = measured ticks", abs(ticks - expect_ticks) <= 1, "(shows %d)" % ticks)
    for k, (c, n) in enumerate(zip(bp.COLOURS, bp.COLOUR_NAMES)):
        x0 = k * bp.BAND_W
        pts = [(x0, 0), (x0 + 39, 0), (x0, 169), (x0 + 39, 169), (x0 + 20, 20), (x0 + 20, 150)]
        got = [lcd.screen_pixel(x, y) for x, y in pts]
        check("band %d %-7s corners and centre" % (k, n), all(g == c for g in got),
              "" if all(g == c for g in got) else str(["%04X" % g for g in got]))
    ink = sum(1 for x in range(130, 220) for y in range(75, 105) if lcd.screen_pixel(x, y) == 0xFFFF)
    paper = sum(1 for x in range(130, 220) for y in range(75, 105) if lcd.screen_pixel(x, y) == 0x0000)
    check("digits drawn at 130,75 (white on black)", ink > 200 and paper > 200 and ink + paper == 90 * 30,
          "(%d ink, %d paper px)" % (ink, paper))
    lcd.save_png(png)
    print("  wrote", os.path.relpath(png, ROOT))
    return clocks, ticks


def ignored(cmd, power, page, what):
    e = make(TEST_IMG, cmd, power, page)
    e.call(0x5D10)
    check("0x%02X %s: no drawing, key eaten" % (cmd, what),
          e.lcd.pixels == 0 and not e.lcd.log and e.R(7) == 0xFF and e.iram[0x45] == page)


def sweep():
    print("\nAll other NEC commands vs the direct-select image")
    diffs = 0
    for power, page in ((1, 1), (0, 1), (1, 0), (1, 2), (1, 3)):
        for cmd in range(256):
            if cmd in (0x16, 0x17) or (cmd in (0x0A, 0x0B) and (power, page) == (1, 1)):
                continue
            r = []
            for img in (BASE_IMG, TEST_IMG):
                e = make(img, cmd, power, page)
                e.call(0x5D10, max_steps=10_000)
                r.append((e.R(7), e.iram[0x47], e.applied, e.iram[0x6F], e.lcd.pixels))
            if r[0] != r[1]:
                diffs += 1
                print("    cmd 0x%02X power %d page %d: %s vs %s" % (cmd, power, page, r[0], r[1]))
    check("identical results for all other commands and states", diffs == 0, "(%d diffs)" % diffs)


def boot_scenario(cmd, label):
    """Boot from reset, power on, press cmd on the home screen, watch 7 s of main loop."""
    print("\nFull firmware: boot, Power, then %s on the home screen" % label)
    amp = Amp(open(TEST_IMG, "rb").read(), log_audio=False)   # Timer0 and Timer3 ISRs
    e = amp.e
    press = amp.press

    e.run_for(1.0)
    check("boots to standby", e.iram[0x4F] == 0)
    press(0x01)                                       # Power
    e.run_for(8.0)
    check("powered on, home screen", e.iram[0x4F] == 1 and e.iram[0x45] == 1)
    home = list(e.lcd.gram)
    e.lcd.save_png(os.path.join(HERE, "build", "boot_home.png"))

    press(cmd)
    timeline = []                                     # (t, page, pixels in the step, result written)
    step = 0.05
    t = 0.0
    while t < 7.0:
        p0 = e.lcd.pixels
        e.run_for(step)
        t += step
        timeline.append((round(t, 2), e.iram[0x45], e.lcd.pixels - p0, e.xram[bp.V_TICKS] != 0))
        if abs(t - 4.5) < step / 2:
            e.lcd.save_png(os.path.join(HERE, "build", "boot_%s_hold.png" % label.split()[1].lower()))
            held = [e.lcd.screen_pixel(k * bp.BAND_W + 20, 20) for k in range(8)]
    # the test is over at the first quiet step after the result was written
    t_res = next(tt for tt, _, _, res in timeline if res)
    test_end = next(tt for tt, _, px, _ in timeline if tt >= t_res and px == 0) - step
    back = next((tt for tt, pg, _, _ in timeline if tt > test_end and pg == 1), None)
    drawn_in_hold = sum(px for tt, _, px, _ in timeline if test_end < tt <= test_end + 4.8)
    print("  test done at +%.2f s, page 1 again at +%s s" % (test_end, back))
    check("nothing drawn during the hold", drawn_in_hold == 0, "(%d px)" % drawn_in_hold)
    check("bars still on screen after 4.5 s", held == bp.COLOURS)
    check("home returns about 5 s after the test", back is not None and 4.8 <= back - test_end <= 5.3,
          "(%.2f s)" % ((back - test_end) if back else -1))
    same = sum(1 for a, b in zip(home, e.lcd.gram) if a == b) / len(home)
    check("home screen redrawn as before", same > 0.999, "(%.2f%% identical)" % (same * 100))
    e.lcd.save_png(os.path.join(HERE, "build", "boot_after.png"))


def image_diff():
    print("\nImage diff vs direct-select")
    a = open(BASE_IMG, "rb").read()
    b = open(TEST_IMG, "rb").read()
    changed = [i for i in range(len(a)) if a[i] != b[i]]
    check("only 0x9406, 0x940B (branches) and the version pointer changed",
          changed == [0x22CB, 0x22CD, 0x9406, 0x940B], str(["%04X" % i for i in changed]))
    check("new bytes appended after 0x%04X" % len(a), len(b) > len(a) and
          all(x == 0xFF for x in b[len(a):bp.CODE_ADDR]))


def main():
    image_diff()
    tuned, t_ticks = run_test(0x0A, "remote Vol+, tuned blit", os.path.join(HERE, "build", "emu_tuned.png"))
    stock, s_ticks = run_test(0x0B, "remote Vol-, stock path", os.path.join(HERE, "build", "emu_stock.png"))
    run_test(0x16, "tuned blit", os.path.join(HERE, "build", "emu_tuned_0x16.png"))
    run_test(0x17, "stock path", os.path.join(HERE, "build", "emu_stock_0x17.png"))
    print("\nSpeed-up per full-screen fill: %.1fx  (amp should show about %d and %d)"
          % (stock / tuned, t_ticks, s_ticks))
    print("\nIgnored states")
    for cmd in (0x16, 0x17):
        ignored(cmd, 0, 1, "in standby")
        ignored(cmd, 1, 3, "in a menu")
    print("  (Vol+/Vol- in standby and in menus are covered by the sweep below)")
    sweep()
    boot_scenario(0x0A, "remote Vol+")
    boot_scenario(0x0B, "remote Vol-")
    print("\nALL PASS" if not fails else "\nFAILURES: %s" % fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
