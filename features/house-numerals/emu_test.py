#!/usr/bin/env python3
"""Emulator tests for House Numerals (see README.md).

  python3 emu_test.py unit    image diff, then every routine at its hook
  python3 emu_test.py tour    whole firmware from reset, lockstep with fast-lcd
  python3 emu_test.py sweep   all 256 IR commands in five states, against fast-lcd
  python3 emu_test.py         all three
"""
import copy
import multiprocessing as mp
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "emu"))
sys.path.insert(0, HERE)
from emu8051 import Emu8051                                     # noqa: E402
from ao300 import Amp, CLOCK_HZ, NEC_POWER, NEC_MENU, NEC_DOWN, NEC_SOURCE, \
    NEC_VOL_UP, NEC_VOL_DOWN, STATE_KEY                          # noqa: E402
import build_patch as bp                                         # noqa: E402

BASE = open(bp.BASE_IMAGE, "rb").read()
NEW = open(bp.OUT_IMAGE, "rb").read()
LAB = bp.assemble()[1]
W, H = 320, 170
fails = []


def check(name, ok, detail=""):
    print("  %-66s %s %s" % (name, "OK  " if ok else "FAIL", detail))
    if not ok:
        fails.append(name)


def emu(theme=(0xFF, 0xFF), img=NEW):
    e = Emu8051(img)
    e.sfr[0x81] = 0x88                       # SP as the firmware sets it
    e.iram[0x48], e.iram[0x49] = theme
    return e


def px(e, x, y):
    return e.lcd.screen_pixel(x, y)


def ink_in(e, x0, y0, w, h):
    return any(px(e, x, y) for x in range(x0, x0 + w) for y in range(y0, y0 + h))


def stray(e, boxes):
    """Lit pixels outside every (x, y, w, h) box."""
    n = 0
    for x in range(W):
        for y in range(H):
            if px(e, x, y) and not any(bx <= x < bx + bw and by <= y < by + bh
                                       for bx, by, bw, bh in boxes):
                n += 1
    return n


def stock_small(e, ch, x, y):
    e.setR(6, 0); e.setR(7, y); e.setR(4, x >> 8); e.setR(5, x & 0xFF); e.setR(3, ord(ch))
    e.call(bp.SMALL_GLYPH)


def stock_glyph(ch, theme=(0xFF, 0xFF)):
    """30 x 32 bitmap of a big-font character, painted by the stock big_glyph_paint."""
    e = emu(theme)
    e.setR(6, 0); e.setR(7, 10); e.setR(4, 0); e.setR(5, 10); e.setR(3, ord(ch))
    e.call(bp.BIG_GLYPH)
    return [[px(e, 10 + i, 10 + j) for j in range(32)] for i in range(30)]


_GLYPHS = {}


def glyphs():
    if not _GLYPHS:
        _GLYPHS.update({d: stock_glyph(str(d)) for d in range(10)})
    return _GLYPHS


def scaled_match(e, x0, y0, ref):
    return all(px(e, x0 + 2 * i + a, y0 + 2 * j + b) == ref[i][j]
               for i in range(30) for j in range(32) for a in (0, 1) for b in (0, 1))


def image_diff():
    print("Image diff vs fast-lcd")
    vp = bp.VERSION_PTR_ADDR
    want = set()
    for addr, orig, op, target in bp.HOOKS:
        new = bytes([op, LAB[target] >> 8, LAB[target] & 0xFF])
        check("hook 0x%04X -> %s" % (addr, target), NEW[addr:addr + 3] == new, NEW[addr:addr + 3].hex(" "))
        want |= {addr + k for k in range(3) if orig[k] != new[k]}
    changed = {i for i in range(len(BASE)) if BASE[i] != NEW[i]} - {vp + 1, vp + 3}
    check("inside the base image only the hooks changed (plus version pointer)", changed == want,
          str(sorted("%04X" % i for i in changed ^ want)))
    ver = (NEW[vp + 1] << 8) | NEW[vp + 3]
    check("version pointer -> %r" % bp.VERSION_TEXT,
          NEW[ver:ver + len(bp.VERSION_TEXT) + 1] == bp.VERSION_TEXT.encode() + b"\0")
    check("gap up to 0x%04X left erased" % bp.CODE_ADDR, all(b == 0xFF for b in NEW[len(BASE):bp.CODE_ADDR]))
    check("image ends below 0xF400", len(NEW) <= 0xF400, "(%d bytes)" % len(NEW))


def test_fill():
    print("\nhn_fill")
    e = emu()

    def fill(x, w, y, h, c):
        for n, v in ((2, x >> 8), (3, x & 0xFF), (1, w), (5, y), (4, h), (6, c >> 8), (7, c & 0xFF)):
            e.setR(n, v)
        c0 = e.cycles
        e.call(LAB["hn_fill"])
        return e.cycles - c0
    t1 = fill(250, 40, 100, 20, 0xF81F)
    check("40x20 across x=256 in the exact colour",
          all(px(e, x, y) == 0xF81F for x in range(250, 290) for y in range(100, 120)))
    check("nothing outside the rectangle", stray(e, [(250, 100, 40, 20)]) == 0)
    t2 = fill(0, 80, 0, 20, 0x07E0)          # about the same window cost, 800 more pixels
    per_px = (t2 - t1) / 800
    check("fill loop at most 10 clocks per pixel", per_px <= 10, "(%.1f)" % per_px)
    fill(0, 2, 0, 170, 0x001F)
    check("2 x 170 column (count above 255)", all(px(e, x, y) == 0x001F for x in (0, 1) for y in range(170)))
    check("theme colour untouched", (e.iram[0x48], e.iram[0x49]) == (0xFF, 0xFF))


def test_digit2x():
    print("\nhn_digit2x against the stock big font")
    bad = []
    for d in range(10):
        ref = stock_glyph(str(d), (0x07, 0xE0))
        e = emu((0x07, 0xE0))
        e.setR(3, d); e.setR(5, 100); e.setR(7, 20)
        e.call(LAB["hn_digit2x"])
        if not (any(any(col) for col in ref) and scaled_match(e, 100, 20, ref)
                and stray(e, [(100, 20, 60, 64)]) == 0):
            bad.append(d)
    check("digits 0-9: stock glyphs at 2x, nothing else drawn", not bad, str(bad))
    e = emu()
    e.setR(3, 8); e.setR(5, 244); e.setR(7, 42)
    e.call(LAB["hn_digit2x"])
    check("digit at x 244 (window ends at 303)", scaled_match(e, 244, 42, glyphs()[8]))


def test_text():
    print("\nhn_text against the stock small font")
    ref = emu()
    for k, ch in enumerate("OPTICAL"):
        stock_small(ref, ch, 16 + 14 * k, 30)
    e = emu()
    e.setR(2, 0x90); e.setR(3, 0x53); e.setR(4, 0); e.setR(5, 16); e.setR(7, 30)
    e.call(LAB["hn_text"])
    check("OPTICAL at 16,30 identical to seven stock glyph calls",
          e.lcd.gram == ref.lcd.gram and ink_in(e, 16, 30, 98, 24))


def test_name_ptr():
    print("\nhn_name_ptr")
    for inp, addr, text in bp.INPUT_NAMES:
        e = emu()
        e.iram[0x47] = inp
        e.call(LAB["hn_name_ptr"])
        check("input %d -> 0x%04X %s" % (inp, addr, text), e.C == 0 and ((e.R(2) << 8) | e.R(3)) == addr)
    for inp in (0, 7, 8, 0xFF):
        e = emu()
        e.iram[0x47] = inp
        e.call(LAB["hn_name_ptr"])
        check("input %d -> no name (C=1)" % inp, e.C == 1)


def expect_volume(e, v, acc):
    """Number box and position line as hn_draw_volume leaves them for volume v."""
    g = glyphs()
    v = min(v, 60)
    tens, ones = divmod(v, 10)
    ok = scaled_match(e, 244, 42, g[ones])
    ok = ok and ((not ink_in(e, 184, 42, 60, 64)) if tens == 0 else scaled_match(e, 184, 42, g[tens]))
    w = 4 * v
    return ok and all(px(e, x, y) == (acc if x < 40 + w else bp.TRACK)
                      for x in range(40, 280) for y in range(136, 139))


def test_draw_volume():
    print("\nhn_draw_volume (the 0x5936 hook): every step, three themes")
    for theme, acc in (((0xFF, 0xFF), bp.ORANGE), ((0xF8, 0x00), 0xF800), ((0x33, 0xBF), 0x33BF)):
        bad = []
        for v in range(61):
            e = emu(theme)
            e.iram[0x2B] = 1
            e.setR(7, v)
            e.call(0x5936)
            if not (expect_volume(e, v, acc) and (e.iram[0x48], e.iram[0x49]) == theme):
                bad.append(v)
        check("theme %02X%02X: steps 0-60, accent %04X, theme restored" % (theme + (acc,)), not bad, str(bad[:5]))
    e = emu(); e.iram[0x2B] = 1; e.setR(7, 25); e.call(0x5936)
    check("only the number box and the line are drawn", stray(e, [(184, 42, 120, 64), (40, 136, 240, 3)]) == 0)
    check("XDATA 0x05 = 2 as stock", e.xram[5] == 2)
    e = emu(); e.iram[0x2B] = 2; e.iram[0x52] = 33; e.setR(7, 10); e.call(0x5936)
    check("headphone output draws RAM 0x52 (33), as stock", expect_volume(e, 33, bp.ORANGE))
    e = emu(); e.iram[0x2B] = 1; e.setR(7, 75); e.call(0x5936)
    check("a value above 60 is drawn as 60", expect_volume(e, 60, bp.ORANGE))
    e = emu(); e.iram[0x2B] = 1
    e.setR(7, 45); e.call(0x5936)
    e.setR(7, 44); e.call(0x5936)
    check("redraw 45 -> 44 leaves nothing behind", expect_volume(e, 44, bp.ORANGE))
    e.setR(7, 4); e.call(0x5936)
    check("redraw 44 -> 4 blanks the tens digit", expect_volume(e, 4, bp.ORANGE))


def test_volpage():
    print("\nhn_volpage (page 2 renderer, jump-table entry 0x2143)")
    e = emu()
    e.iram[0x47], e.iram[0x2B], e.iram[0x31] = 2, 1, 25
    e.iram[0x22] |= 0x08
    e.iram[0x32] = e.iram[0x46] = 1
    e.call(LAB["hn_volpage"])
    ref = emu()
    for k, ch in enumerate("OPTICAL"):
        stock_small(ref, ch, 16 + 14 * k, 30)
    check("input name in white at 16,30", ink_in(e, 16, 30, 98, 24) and
          all(px(e, x, y) == px(ref, x, y) for x in range(16, 114) for y in range(30, 54)))
    check("divider 1x104 at 140,14", all(px(e, 140, y) == bp.DIVIDER for y in range(14, 118)))
    ref = emu((bp.ORANGE >> 8, bp.ORANGE & 0xFF))
    for k, ch in enumerate("VOL"):
        stock_small(ref, ch, 158 + 14 * k, 14)
    check("VOL in the accent at 158,14",
          all(px(e, x, y) == px(ref, x, y) for x in range(158, 200) for y in range(14, 38)))
    check("number and line for 25", expect_volume(e, 25, bp.ORANGE))
    check("nothing else drawn", stray(e, [(16, 30, 98, 24), (140, 14, 1, 104), (158, 14, 42, 24),
                                           (184, 42, 120, 64), (40, 136, 240, 3)]) == 0)
    check("render flags cleared as by 0x22FA",
          not e.iram[0x22] & 0x08 and e.iram[0x32] == 0 and e.iram[0x46] == 0)
    check("theme colour restored", (e.iram[0x48], e.iram[0x49]) == (0xFF, 0xFF))
    e.lcd.save_png(os.path.join(HERE, "build", "unit_volpage.png"))
    e = emu()
    e.iram[0x47], e.iram[0x2B], e.iram[0x31] = 7, 1, 5
    e.call(LAB["hn_volpage"])
    check("input 7 (no name): name area empty, number drawn",
          not ink_in(e, 0, 0, 140, 130) and expect_volume(e, 5, bp.ORANGE))


def test_wipe():
    print("\nhn_clear (the 0x2106 hook): edge wipe into page 2")
    fills, seen = [], set()

    def on_fill(em):
        fills.append((((em.R(2) << 8) | em.R(3)), em.R(1), (em.R(6) << 8) | em.R(7)))
    e = emu()
    e.lcd.gram = [0xFFFF] * len(e.lcd.gram)
    e.iram[0x59] = 2
    e.hooks[LAB["hn_fill"]] = on_fill
    for addr in (0x5CBC, 0x5CCB, 0x51EE):
        e.hooks[addr] = lambda em, addr=addr: seen.add(addr)
    c0 = e.cycles
    e.call(LAB["hn_clear"])
    ms = (e.cycles - c0) * 1000 / CLOCK_HZ
    edges = [x for x, w, c in fills if c == bp.ORANGE and w == 2]
    blacks = [x for x, w, c in fills if c == 0 and w == 2]
    check("edge steps from x 318 to 0, 2 px at a time", edges == list(range(318, -1, -2)), str(edges[:3]))
    check("black 2 px behind the edge, then over x 0", blacks == list(range(318, 0, -2)) + [0], str(blacks[:3]))
    check("screen fully black afterwards", not ink_in(e, 0, 0, W, H))
    check("text buffers cleared as by ui_clear_screen", {0x5CBC, 0x5CCB} <= seen and 0x51EE not in seen)
    check("wipe takes 30-200 ms", 30 <= ms <= 200, "(%.0f ms)" % ms)
    check("page argument 0x59 kept, theme restored",
          e.iram[0x59] == 2 and (e.iram[0x48], e.iram[0x49]) == (0xFF, 0xFF))
    fills.clear(); seen.clear()
    e = emu()
    e.iram[0x59] = 3
    e.hooks[LAB["hn_fill"]] = on_fill
    e.hooks[0x51EE] = lambda em: seen.add(0x51EE)
    e.call(LAB["hn_clear"])
    check("other pages: stock clear, no wipe", 0x51EE in seen and not fills)


def test_home_tail():
    print("\nhn_home_tail (home_refresh's tail, 0x5C99)")
    for theme, acc in (((0xFF, 0xFF), bp.ORANGE), ((0x07, 0xE0), 0x07E0)):
        e = emu(theme); e.iram[0x2B] = 1; e.setR(7, 37)
        e.call(LAB["hn_home_tail"])
        ref = emu(theme, BASE); ref.iram[0x2B] = 1; ref.setR(7, 37)
        ref.call(0x5916)
        bar = all(px(e, x, y) == acc for x in range(18, 46) for y in range(114, 117))
        rest = all(px(e, x, y) == px(ref, x, y) for x in range(W) for y in range(H)
                   if not (18 <= x < 46 and 114 <= y < 117))
        check("theme %02X%02X: volume as stock, accent bar 28x3 at 18,114" % theme, bar and rest)
        check("theme %02X%02X: theme colour restored" % theme, (e.iram[0x48], e.iram[0x49]) == theme)


def text_render(img, page, entry, buf, text, y):
    e = emu(img=img)
    e.iram[0x45] = page
    for k, ch in enumerate(text.encode() + b"\0"):
        e.xram[buf + k] = ch
    e.setR(6, 0); e.setR(7, y)
    e.call(entry)
    return e


NEC_HDMI = 0x14                          # direct-select input 5
CHUNK = 0.01                             # lockstep granularity, one Timer0 tick
TOUR = [                                 # (step, NEC command or None, seconds, screen check)
    ("power_on", NEC_POWER, 8.0, "home"),
    ("vol_up", NEC_VOL_UP, 0.5, "vol"),
    ("vol_up2", NEC_VOL_UP, 0.5, "vol"),
    ("back_home", None, 2.5, "home"),
    ("source", NEC_SOURCE, 11.0, "home"),   # OPTICAL has no signal: ~10 s detect timeout, then wipe
    ("menu", NEC_MENU, 1.5, "home"),      # a single tap doesn't open the menu (page stays 1,
    ("menu_down", NEC_DOWN, 1.0, "home"),  # confirmed by fast-lcd's own tour); still the home screen
    ("menu_timeout", None, 10.5, "home"),
    ("hdmi", NEC_HDMI, 3.0, "home"),
    ("vol_down", NEC_VOL_DOWN, 0.5, "vol"),
    ("vol_timeout", None, 2.5, "home"),
    ("standby", NEC_POWER, 3.0, "same"),
]
HOME_BANDS = [(75, 32), (135, 24)]       # input name, status line


def state(amp):
    return (amp.page, amp.powered) + tuple(amp.e.iram[a] for a in (0x31, 0x52, 0x47, 0x2B))


def accent_of(amp):
    hi, lo = amp.e.iram[0x48], amp.e.iram[0x49]
    return bp.ORANGE if (hi, lo) == (0xFF, 0xFF) else (hi << 8) | lo


def current_volume(amp):
    return amp.e.iram[0x52] if amp.e.iram[0x2B] == 2 else amp.e.iram[0x31]


VOL_BOXES = [(184, 42, 120, 64), (40, 136, 240, 3)]      # our number box, position line
STOCK_DIGIT_BAND = (0, 0, W, 110)                        # stock's own centred, un-doubled
                                                          # digit: page 2 draws nothing
                                                          # else up here (no icons on this
                                                          # screen -- see tour_vol_up.png)


def volume_checks(step, new, ref):
    """Pressing a volume key shows the quick number+line toast (hn_draw_volume, 0x5936),
    not the full hn_volpage screen (0x2143) -- that jump-table entry is a separate,
    menu-driven page. Confirmed by tour_vol_up.png: no input name / VOL heading / divider,
    just the number and position line over an otherwise fast-lcd-identical screen. Below
    that, fast-lcd draws its own (un-doubled, centred) digit in the same band -- excluded
    here since its x position moves with the value -- and the "volume" caption, which is
    untouched by the patch and must still match fast-lcd exactly."""
    v, acc = current_volume(new), accent_of(new)
    boxes = VOL_BOXES + [STOCK_DIGIT_BAND]
    outside = all(new.lcd.screen_pixel(x, y) == ref.lcd.screen_pixel(x, y)
                  for x in range(W) for y in range(H)
                  if not any(bx <= x < bx + bw and by <= y < by + bh for bx, by, bw, bh in boxes))
    check("%-12s volume: number and line as hn_draw_volume draws it" % step,
          new.page == 2 and expect_volume(new, v, acc))
    check("%-12s volume: caption below identical to fast-lcd" % step, outside)


def home_checks(step, new, ref):
    sp, rp = new.lcd.screen_pixel, ref.lcd.screen_pixel
    acc = accent_of(new)

    def ours(x, y):
        return any(y0 <= y < y0 + h for y0, h in HOME_BANDS) or (18 <= x < 46 and 114 <= y < 117)
    check("%-12s home: icon, volume, tags as fast-lcd" % step,
          all(sp(x, y) == rp(x, y) for x in range(W) for y in range(H) if not ours(x, y)))
    check("%-12s home: accent bar %04X" % (step, acc),
          all(sp(x, y) == acc for x in range(18, 46) for y in range(114, 117)))
    for y0, h in HOME_BANDS:
        left = next((x for x in range(W) if any(sp(x, y) for y in range(y0, y0 + h))), None)
        check("%-12s home: text at y %d starts at x 16..29" % (step, y0),
              left is not None and 16 <= left < 30, "(x %s)" % left)


def draw_time(activity, quiet=10):
    for i in range(len(activity)):
        if not any(activity[i:i + quiet]):
            return i * CHUNK
    return len(activity) * CHUNK


def tour():
    print("\nWhole firmware, lockstep with fast-lcd")
    amps = [Amp(BASE), Amp(NEW)]
    for amp in amps:
        amp.set_pin(0xC0, 5, 0)                         # USB audio present
        amp.boot()
    ref, new = amps
    for step, cmd, secs, kind in TOUR:
        w0 = time.time()
        for amp in amps:
            if cmd is not None:
                amp.press(cmd)
        act, home_at = [[], []], [None, None]
        for n in range(int(round(secs / CHUNK))):
            for k, amp in enumerate(amps):
                p0, n0 = amp.lcd.pixels, len(amp.lcd.log)
                amp.wait(CHUNK)
                act[k].append(amp.lcd.pixels != p0 or len(amp.lcd.log) != n0)
                if home_at[k] is None and amp.page == 1:
                    home_at[k] = n * CHUNK
        print("    %-12s %5.1f s emulated x2 in %5.1f s, drawing %4.0f / %4.0f ms" %
              (step, secs, time.time() - w0, draw_time(act[0]) * 1000, draw_time(act[1]) * 1000), flush=True)
        check("%-12s same page, power, volumes, input, output" % step, state(ref) == state(new),
              "%s vs %s" % (state(ref), state(new)))
        if kind == "home":
            home_checks(step, new, ref)
        elif kind == "vol":
            volume_checks(step, new, ref)
        else:
            check("%-12s screen identical to fast-lcd" % step, new.lcd.gram == ref.lcd.gram)
        if step == "vol_up":
            check("vol_up       wipe and page drawn within 350 ms", draw_time(act[1]) <= 0.35,
                  "(%.0f ms)" % (draw_time(act[1]) * 1000))
        if step in ("back_home", "vol_timeout"):
            both = None not in home_at
            check("%-12s home returns within 0.1 s of fast-lcd" % step,
                  both and abs(home_at[0] - home_at[1]) <= 0.1, str(home_at))
        new.lcd.save_png(os.path.join(HERE, "build", "tour_%s.png" % step))

    print("\n  Audio state, after every write that changes it")
    backlight = ("pin", "P0.6 backlight")

    def transitions(amp):
        out, last = [], None
        for c, st in amp.state_changes:
            st = tuple(kv for kv in st if kv[0] != backlight)
            if st != last:
                out.append((c / CLOCK_HZ, st))
                last = st
        return out
    tr_ref, tr_new = transitions(ref), transitions(new)
    same_order = [s for _, s in tr_ref] == [s for _, s in tr_new]
    check("same sequence of audio states, in the same order", same_order,
          "(%d vs %d states)" % (len(tr_ref), len(tr_new)))
    if same_order:
        late = [(tn - tr, tr) for (tr, _), (tn, _) in zip(tr_ref, tr_new) if tn - tr > 0.10]
        check("no audio state more than 0.10 s later than fast-lcd", not late,
              "" if not late else "(%d, first %+.2f s at %.2f s)" % (len(late), late[0][0], late[0][1]))
        moved = [(tr, tn - tr) for (tr, _), (tn, _) in zip(tr_ref, tr_new) if abs(tn - tr) > 0.05]
        for tr, d in moved:
            print("    audio state at %7.2f s moves %+.2f s" % (tr, d))
    bl = [[d for _, nm, d in amp.events if nm == backlight[1]] for amp in amps]
    check("backlight switches the same way", bl[0] == bl[1])

    def semantic_args(name, regs):
        """The part of a writer's logged R3/R4/R5/R7 that reaches the chip, per
        ao300.STATE_KEY's own field selection: R3/R4 double as scratch/loop-counter
        registers at some call sites (e.g. a signal-lock retry loop around input
        switches) and can differ, by one incidental value, from a harmless timing
        shift -- house-numerals's extra hooks change how many main-loop iterations
        fit in a second -- without changing what the chip is told."""
        r = [0] * 8
        for kv in regs.split():
            r[int(kv[1])] = int(kv[3:], 16)
        return STATE_KEY[name](r)
    for name in sorted(set(ref.calls) | set(new.calls)):
        a = {semantic_args(name, regs) for regs in ref.calls.get(name, set())}
        b = {semantic_args(name, regs) for regs in new.calls.get(name, set())}
        check("%-15s same argument sets (%d distinct)" % (name, len(a)), a == b)


def test_align():
    print("\nleft-aligned text on page 1 (hooks 0x2A25 big, 0x3A82 small)")
    cases = (("big", 0x298B, 0x35, "USB", 75, 32, 30), ("small", 0x3A53, 0x50, "No signal", 135, 24, 14))
    for kind, entry, buf, text, y, h, cw in cases:
        n1, b1 = text_render(NEW, 1, entry, buf, text, y), text_render(BASE, 1, entry, buf, text, y)
        n3, b3 = text_render(NEW, 3, entry, buf, text, y), text_render(BASE, 3, entry, buf, text, y)
        tw = len(text) * cw
        shift = (W - tw) // 2 - 16
        moved = all(px(n1, x, yy) == px(b1, x + shift, yy) for x in range(16, 16 + tw) for yy in range(y, y + h))
        check("%s: page 1 text moved to x 16, same glyphs" % kind, moved and ink_in(n1, 16, y, tw, h))
        check("%s: page 1 margins left and right cleared" % kind,
              not ink_in(n1, 0, y, 16, h) and not ink_in(n1, 16 + tw, y, W - 16 - tw, h))
        check("%s: page 3 (menus) unchanged, centred" % kind, n3.lcd.gram == b3.lcd.gram)
    e = text_render(NEW, 1, 0x298B, 0x35, "COAXIAL", 75)
    check("big COAXIAL (narrow-glyph centring path) starts at x 16",
          not ink_in(e, 0, 75, 16, 32) and ink_in(e, 16, 75, 30, 32))
    wide = "ABCDEFGHIJKLMNOPQRSTU"                    # 21 x 14 = 294 px: stays centred
    check("small text wider than 288 px stays centred on page 1",
          text_render(NEW, 1, 0x3A53, 0x50, wide, 135).lcd.gram ==
          text_render(BASE, 1, 0x3A53, 0x50, wide, 135).lcd.gram)


GROUPS = {
    "unit": [image_diff, test_fill, test_digit2x, test_text, test_name_ptr,
             test_draw_volume, test_volpage, test_wipe, test_home_tail, test_align],
    "tour": [tour],
    "sweep": [],
}


def main():
    for g in sys.argv[1:] or ["unit", "tour", "sweep"]:
        for fn in GROUPS[g]:
            fn()
    print("\nALL PASS" if not fails else "\nFAILURES: %s" % fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
