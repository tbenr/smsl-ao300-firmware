#!/usr/bin/env python3
"""Emulator tests for House Numerals (see README.md).

  python3 emu_test.py unit    image diff, then every routine at its hook
  python3 emu_test.py tour    whole firmware from reset, lockstep with fast-lcd, then a volume
                              key after each input settles (Bluetooth, no signal, power-on, ...)
  python3 emu_test.py sweep   all 256 IR commands in five states, against fast-lcd
  python3 emu_test.py         all three
"""
import multiprocessing as mp
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "emu"))
sys.path.insert(0, HERE)
from emu8051 import Emu8051                                     # noqa: E402
from ao300 import Amp, CLOCK_HZ, NEC_POWER, NEC_DOWN, NEC_SOURCE, \
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
    for s in bp.VOL_ENTRY_SITES:
        new = bp.vol_entry_bytes(LAB["hn_enter_vol"])
        check("volume entry 0x%04X -> lcall hn_enter_vol ; sjmp 0x%04X" % (s, s + len(bp.VOL_ENTRY_ORIG)),
              NEW[s:s + 5] == new, NEW[s:s + 5].hex(" "))
        want |= {s + k for k in range(5) if bp.VOL_ENTRY_ORIG[k] != new[k]}
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
    e = emu(); e.iram[0x2B] = 1; e.setR(7, 25)
    wiped = []
    e.hooks[LAB["hn_wipe"]] = lambda em: wiped.append(em.cycles)
    e.call(0x5936)
    check("HN_PEND = 0: 0x5936 never calls hn_wipe", not wiped and e.xram[bp.HN_PEND] == 0)
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
    check("wipe takes 190-215 ms", 190 <= ms <= 215, "(%.0f ms)" % ms)
    check("page argument 0x59 kept, theme restored",
          e.iram[0x59] == 2 and (e.iram[0x48], e.iram[0x49]) == (0xFF, 0xFF))
    fills.clear(); seen.clear()
    e = emu()
    e.iram[0x59] = 3
    e.hooks[LAB["hn_fill"]] = on_fill
    e.hooks[0x51EE] = lambda em: seen.add(0x51EE)
    e.call(LAB["hn_clear"])
    check("other pages: stock clear, no wipe", 0x51EE in seen and not fills)
    # unmute countdown (RAM 0x43:0x44) at 1..HN_CD_MIN-1: the unmute falls due during the wipe, so
    # the page opens with the fast clear; 0 (not running) or HN_CD_MIN and up: the wipe
    for entry, page in (("hn_clear", 2), ("hn_wipe", 3)):
        for cd in (0x0001, bp.HN_CD_MIN - 1, bp.HN_CD_MIN, 0x001F, 0x0100):
            fills.clear(); seen.clear()
            e = emu()
            e.lcd.gram = [0xFFFF] * len(e.lcd.gram)
            e.iram[0x59] = page
            e.iram[0x43], e.iram[0x44] = cd >> 8, cd & 0xFF
            e.hooks[LAB["hn_fill"]] = on_fill
            for addr in (0x5CBC, 0x5CCB, 0x51EE):
                e.hooks[addr] = lambda em, addr=addr: seen.add(addr)
            c0 = e.cycles
            e.call(LAB[entry])
            ms = (e.cycles - c0) * 1000 / CLOCK_HZ
            edges = [x for x, w, c in fills if c == bp.ORANGE and w == 2]
            common = (not ink_in(e, 0, 0, W, H) and (e.iram[0x48], e.iram[0x49]) == (0xFF, 0xFF)
                      and {0x5CBC, 0x5CCB} <= seen)
            if cd < bp.HN_CD_MIN:
                check("%s, countdown %d: fast clear, no edge fills, black screen" % (entry, cd),
                      common and 0x51EE in seen and not fills, "(%.1f ms)" % ms)
            else:
                check("%s, countdown %d: the wipe, 318 down to 0, black screen" % (entry, cd),
                      common and 0x51EE not in seen and edges == list(range(318, -1, -2)), "(%.0f ms)" % ms)
            check("%s, countdown %d: countdown and tick flag untouched without ticks" % (entry, cd),
                  (e.iram[0x43] << 8 | e.iram[0x44]) == cd and not e.iram[0x20] & 0x80)
    # post_power_on still to run (0x20.3, a key queued during the power-on splash): fast clear
    for cd in (0, 300):
        fills.clear(); seen.clear()
        e = emu()
        e.iram[0x59] = 2
        e.iram[0x20] |= 0x08
        e.iram[0x43], e.iram[0x44] = cd >> 8, cd & 0xFF
        e.hooks[LAB["hn_fill"]] = on_fill
        e.hooks[0x51EE] = lambda em: seen.add(0x51EE)
        e.call(LAB["hn_clear"])
        check("hn_clear, 0x20.3 set, countdown %d: fast clear, no edge fills" % cd,
              0x51EE in seen and not fills and e.iram[0x20] & 0x08)


def test_tick():
    print("\nhn_tick and the wipe's tick compensation (unmute countdown RAM 0x43:0x44, tick flag 0x20.7)")
    # (flag, countdown, taken before) -> (flag, countdown, taken after)
    cases = [((0, 100, 0), (0, 100, 0)),      # no tick: nothing
             ((1, 0, 0), (1, 0, 0)),          # countdown not running: the tick stays with the main loop
             ((1, 1, 0), (1, 1, 0)),          # at 1: the main loop's own tick expires it (and unmutes)
             ((1, 1, 1), (1, 1, 1)),
             ((1, 2, 0), (0, 2, 1)),          # first tick taken: counted by the main loop after the wipe
             ((1, 2, 1), (0, 1, 1)),          # later ticks: counted here, never below 1
             ((1, 0x100, 1), (0, 0xFF, 1)),   # borrow into the high byte
             ((1, 300, 1), (0, 299, 1))]
    for (f0, c0, t0), want in cases:
        e = emu()
        e.iram[0x20] = 0x80 if f0 else 0
        e.iram[0x43], e.iram[0x44] = c0 >> 8, c0 & 0xFF
        e.xram[bp.HN_TICK] = t0
        e.call(LAB["hn_tick"])
        got = (e.iram[0x20] >> 7, (e.iram[0x43] << 8) | e.iram[0x44], e.xram[bp.HN_TICK])
        check("hn_tick flag %d, countdown %3d, taken %d -> flag %d, countdown %3d, taken %d" %
              ((f0, c0, t0) + want), got == want, str(got))

    # the re-mute request 0x21.4: answered once per wipe, as main_tick_tasks 0x3325 answers it
    for req, done, calls_want in ((0, 0, 0), (1, 0, 1), (1, 1, 0)):
        e = emu()
        e.iram[0x21] = 0x10 if req else 0
        e.iram[0x22] = 0x10                          # 0x22.4: unmuted
        e.xram[bp.HN_REMUTE] = done
        calls = []
        e.hooks[bp.AUDIO_APPLY_MUTE] = lambda em: calls.append(em.iram[0x22] & 0x10)
        e.call(LAB["hn_tick"])
        if calls_want:
            ok = calls == [0] and not e.iram[0x21] & 0x10 and e.xram[bp.HN_REMUTE] == 1
        else:
            ok = not calls and e.iram[0x21] & 0x10 == (0x10 if req else 0) and e.iram[0x22] & 0x10
        check("hn_tick re-mute request %d, answered before %d -> audio_apply_mute %s" %
              (req, done, "called with 0x22.4 clear, request cleared" if calls_want else "not called"), ok)

    def wipe_with_ticks(cd, poke=None, remute=False):
        """hn_wipe with a Timer0 that only sets the tick flag every 10 ms (no main loop runs); with
        remute it also raises the re-mute request 0x21.4 every tick, as on optical without lock."""
        e = emu()
        e.iram[0x59] = 3
        e.iram[0x43], e.iram[0x44] = cd >> 8, cd & 0xFF
        ticks, seen, calls = [], [], []
        e.tick_every = CLOCK_HZ // 100
        e.on_tick = lambda em: (ticks.append(em.cycles), em.iram.__setitem__(0x20, em.iram[0x20] | 0x80),
                                remute and em.iram.__setitem__(0x21, em.iram[0x21] | 0x10))
        e.hooks[LAB["hn_tick"]] = lambda em: (seen.append(((em.iram[0x43] << 8) | em.iram[0x44], len(ticks))),
                                              poke and poke(em, len(seen)))
        e.hooks[bp.AUDIO_APPLY_MUTE] = lambda em: calls.append(em.cycles)
        e.start_ticks()
        c0 = e.cycles
        e.call(LAB["hn_wipe"])
        return e, len(ticks), seen, [c - c0 for c in calls], (e.cycles - c0) * 1000 / CLOCK_HZ
    e, n, seen, calls, ms = wipe_with_ticks(100)
    cd = (e.iram[0x43] << 8) | e.iram[0x44]
    polled = seen[-1][1]                             # ticks the last hn_tick call could see
    check("wipe from countdown 100: %d ticks taken, %d counted here, one handed back to the main loop" %
          (polled, polled - 1), len(seen) == 160 and cd == 100 - (polled - 1) and e.iram[0x20] & 0x80
          and e.xram[bp.HN_TICK] == 1 and not calls, "(countdown %d, %d ticks in all)" % (cd, n))
    check("every tick seen: at most one per wipe step",
          all(b[1] - a[1] <= 1 for a, b in zip(seen, seen[1:])))
    check("wipe spans %d ticks; HN_CD_MIN %d covers them, one pending before it and the page after it" %
          (n, bp.HN_CD_MIN), n + 1 < bp.HN_CD_MIN)
    e, n, seen, calls, ms = wipe_with_ticks(100, remute=True)
    check("re-mute request every tick: audio_apply_mute once, within 2 ms of the first tick, the rest left set",
          len(calls) == 1 and calls[0] < (CLOCK_HZ // 100) * 1.2 and e.iram[0x21] & 0x10 and 190 <= ms <= 215,
          "(%d calls, at %.1f ms, wipe %.0f ms)" % (len(calls), calls[0] * 1000 / CLOCK_HZ if calls else -1, ms))
    e, n, seen, calls, ms = wipe_with_ticks(0)
    check("wipe with the countdown at 0: countdown untouched, tick flag left set",
          (e.iram[0x43], e.iram[0x44]) == (0, 0) and e.iram[0x20] & 0x80 and e.xram[bp.HN_TICK] == 0)
    # an interrupt lowers the countdown mid-wipe (none in the stock code goes below 30): it stops at 1
    e, n, seen, calls, ms = wipe_with_ticks(200, lambda em, k: k == 60 and (em.iram.__setitem__(0x43, 0),
                                                                em.iram.__setitem__(0x44, 3)))
    cd = (e.iram[0x43] << 8) | e.iram[0x44]
    check("countdown set to 3 mid-wipe: stops at 1, never 0, tick flag set for the main loop",
          cd == 1 and min(c for c, _ in seen) >= 1 and e.iram[0x20] & 0x80,
          "(countdown %d, min %d)" % (cd, min(c for c, _ in seen)))


def test_enter_vol():
    print("\nhn_enter_vol (the four volume-key sites) and the wipe drawn by 0x5936")
    ref = emu()
    ref.iram[0x47], ref.iram[0x2B] = 3, 1
    ref.call(LAB["hn_vol_static"])
    ref.setR(7, 7)
    ref.call(0x5936)
    e = emu()
    e.lcd.gram = [0xFFFF] * len(e.lcd.gram)
    e.iram[0x47], e.iram[0x2B] = 3, 1
    edges, fills, wipes = [], [], []
    e.hooks[LAB["hn_fill"]] = lambda em: (fills.append(em.cycles), edges.append((em.R(2) << 8) | em.R(3))
                                          if (em.R(1), (em.R(6) << 8) | em.R(7)) == (2, bp.ORANGE) else None)
    e.hooks[LAB["hn_wipe"]] = lambda em: wipes.append(em.cycles)
    e.call(LAB["hn_enter_vol"])
    check("hn_enter_vol draws nothing: screen still white, hn_fill never called",
          not fills and not wipes and all(px(e, x, y) == 0xFFFF for x in range(W) for y in range(H)))
    check("HN_PEND = 1 (volume page pending)", e.xram[bp.HN_PEND] == 1, "(%d)" % e.xram[bp.HN_PEND])
    e.setR(7, 7)
    e.call(0x5936)
    check("then 0x5936: edge wipe from x 318 to 0", edges == list(range(318, -1, -2)), str(edges[:3]))
    same = all(px(e, x, y) == px(ref, x, y) for x in range(W) for y in range(H))
    check("final screen = hn_vol_static + 0x5936 (R7 = 7) on black", same and ink_in(e, 16, 30, 98, 24))
    check("HN_PEND back to 0", e.xram[bp.HN_PEND] == 0)
    check("theme colour restored", (e.iram[0x48], e.iram[0x49]) == (0xFF, 0xFF))
    edges.clear(); wipes.clear()
    e.setR(7, 8)
    e.call(0x5936)
    check("a second 0x5936 call does no wipe", not edges and not wipes)
    e = emu()
    e.lcd.gram = [0xFFFF] * len(e.lcd.gram)
    e.iram[0x47], e.iram[0x2B] = 3, 1
    e.iram[0x43], e.iram[0x44] = 0, 20               # unmute due within the wipe (below HN_CD_MIN)
    edges, seen = [], set()
    e.hooks[LAB["hn_fill"]] = lambda em: edges.append((em.R(2) << 8) | em.R(3)) \
        if (em.R(1), (em.R(6) << 8) | em.R(7)) == (2, bp.ORANGE) else None
    e.hooks[0x51EE] = lambda em: seen.add(0x51EE)
    e.call(LAB["hn_enter_vol"])
    e.setR(7, 7)
    e.call(0x5936)
    check("countdown 20: 0x5936 fast-clears, no edge fills", 0x51EE in seen and not edges)
    same = all(px(e, x, y) == px(ref, x, y) for x in range(W) for y in range(H))
    check("countdown 20: same final screen, HN_PEND back to 0", same and e.xram[bp.HN_PEND] == 0)
    for s in bp.VOL_ENTRY_SITES:
        e = emu()
        e.iram[0x47] = 1
        seen = []
        e.hooks[LAB["hn_enter_vol"]] = lambda em: seen.append(em.cycles)
        e.hooks[0x3A53] = lambda em: seen.append("caption")
        e.pc = s
        e.push(0x00); e.push(0x00)                 # a return address the run never reaches
        e.run(s + len(bp.VOL_ENTRY_ORIG), 2_000_000)
        check("site 0x%04X: hn_enter_vol called, stock caption skipped" % s,
              len(seen) == 1 and seen[0] != "caption" and e.pc == s + len(bp.VOL_ENTRY_ORIG))


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
    e = emu(); e.iram[0x2B] = 1; e.setR(7, 37)
    e.xram[bp.HN_PEND] = 0xAA
    e.call(LAB["hn_home_tail"])
    check("HN_PEND 0xAA cleared by hn_home_tail", e.xram[bp.HN_PEND] == 0)


def text_render(img, page, entry, buf, text, y):
    e = emu(img=img)
    e.iram[0x45] = page
    for k, ch in enumerate(text.encode() + b"\0"):
        e.xram[buf + k] = ch
    e.setR(6, 0); e.setR(7, y)
    e.call(entry)
    return e


NEC_HDMI = 0x14                          # direct-select input 5
NEC_MENU_OPEN = 0x04                     # opens the menu from home (key_menu_nav @ 0x10FC, key code 0x0F
                                          # via the IR table); NEC_MENU (0x03, key code 0x5D) reaches
                                          # key_menu @ 0x144E, which is a no-op unless page is already >= 3
CHUNK = 0.01                             # lockstep granularity, one Timer0 tick
TOUR = [                                 # (step, NEC command or None, seconds, screen check)
    ("power_on", NEC_POWER, 8.0, "home"),
    ("vol_up", NEC_VOL_UP, 0.5, "vol"),
    ("vol_up2", NEC_VOL_UP, 0.5, "vol"),
    ("back_home", None, 2.5, "home"),
    ("source", NEC_SOURCE, 11.0, "home"),   # OPTICAL has no signal: ~10 s detect timeout, then wipe
    ("menu", NEC_MENU_OPEN, 1.5, "same"),   # opens the menu (page -> 3), screen identical to fast-lcd
    ("menu_down", NEC_DOWN, 1.0, "same"),   # navigates the cursor down inside the menu (RAM 0x17)
    ("menu_timeout", None, 9.5, "home"),    # ~9 s of inactivity in the menu returns home
    ("hdmi", NEC_HDMI, 3.0, "home"),
    ("vol_down", NEC_VOL_DOWN, 0.5, "vol"),
    ("vol_timeout", None, 2.5, "home"),
    ("standby", NEC_POWER, 3.0, "same"),
]
VOL_ENTRY_STEPS = ("vol_up", "vol_down")  # Vol keys pressed on the home page: they open page 2
HOME_BANDS = [(75, 32), (135, 24)]       # input name, status line


def state(amp):
    return (amp.page, amp.powered) + tuple(amp.e.iram[a] for a in (0x31, 0x52, 0x47, 0x2B))


def accent_of(amp):
    hi, lo = amp.e.iram[0x48], amp.e.iram[0x49]
    return bp.ORANGE if (hi, lo) == (0xFF, 0xFF) else (hi << 8) | lo


def volpage_reference(amp):
    """What hn_volpage draws for this amp's state, on a black screen."""
    e = emu((amp.e.iram[0x48], amp.e.iram[0x49]))
    for a in (0x31, 0x47, 0x2B, 0x52):
        e.iram[a] = amp.e.iram[a]
    e.call(LAB["hn_volpage"])
    return e.lcd.gram


def home_ours(x, y):
    """Pixels house-numerals draws differently from stock on page 1: the accent bar box,
    plus the two left-aligned text bands (HOME_BANDS)."""
    return any(y0 <= y < y0 + h for y0, h in HOME_BANDS) or (18 <= x < 46 and 114 <= y < 117)


def home_pixels_ok(new, ref):
    """Everything outside our bands: identical to fast-lcd (ref), pixel for pixel."""
    sp, rp = new.lcd.screen_pixel, ref.lcd.screen_pixel
    return all(sp(x, y) == rp(x, y) for x in range(W) for y in range(H) if not home_ours(x, y))


def home_bar_ok(new):
    """The 28x3 accent bar itself, painted in accent_of(new)."""
    sp, acc = new.lcd.screen_pixel, accent_of(new)
    return all(sp(x, y) == acc for x in range(18, 46) for y in range(114, 117))


def home_screen_ok(new, ref):
    """Whole page-1 screen as house-numerals should draw it: stock outside our bands, plus
    our accent bar. Used by the tour's home_checks and the sweep's per-command screen_ok."""
    return home_pixels_ok(new, ref) and home_bar_ok(new)


def home_checks(step, new, ref):
    check("%-12s home: icon, volume, tags as fast-lcd" % step, home_pixels_ok(new, ref))
    check("%-12s home: accent bar %04X" % (step, accent_of(new)), home_bar_ok(new))
    sp = new.lcd.screen_pixel
    for y0, h in HOME_BANDS:
        left = next((x for x in range(W) if any(sp(x, y) for y in range(y0, y0 + h))), None)
        check("%-12s home: text at y %d starts at x 16..29" % (step, y0),
              left is not None and 16 <= left < 30, "(x %s)" % left)


def draw_time(activity, quiet=10):
    for i in range(len(activity)):
        if not any(activity[i:i + quiet]):
            return i * CHUNK
    return len(activity) * CHUNK


def countdown(e):
    """The unmute countdown, RAM 0x43:0x44 (main-loop ticks of 10 ms)."""
    return (e.iram[0x43] << 8) | e.iram[0x44]


def watch_wipe(amp):
    """Log hn_wipe's calls (clock, unmute countdown and 0x20.3 on entry) and hn_fill's (clock, x, w, colour)."""
    wipes, fills = [], []
    amp.e.hooks[LAB["hn_wipe"]] = lambda em: wipes.append((em.cycles, countdown(em), bool(em.iram[0x20] & 0x08)))
    amp.e.hooks[LAB["hn_fill"]] = lambda em: fills.append(
        (em.cycles, (em.R(2) << 8) | em.R(3), em.R(1), (em.R(6) << 8) | em.R(7)))
    return wipes, fills


def entry_mark(amp, wipes, fills):
    return {"wipes": len(wipes), "events": len(amp.events), "fills": len(fills)}


def vol_entry_checks(step, new, entry, wipes, fills):
    """A volume-key entry from home. hn_wipe decides on what it finds: with post_power_on still to
    run (0x20.3) or the unmute countdown (RAM 0x43:0x44) at 1..HN_CD_MIN-1 (the unmute falls due
    within the wipe) the page opens with the fast clear; otherwise with the 160-step edge wipe. The NJW1194 volume write comes
    before the wipe routine either way, and before the first edge fill. Returns the kind."""
    edge_fills = [(c, x) for c, x, w, col in fills[entry["fills"]:] if w == 2 and col != 0]
    edges = [x for c, x in edge_fills]
    first = wipes[entry["wipes"]:entry["wipes"] + 1]
    cd = first[0][1] if first else None
    pending = bool(first) and first[0][2]
    fast = cd is not None and (pending or 1 <= cd < bp.HN_CD_MIN)
    print("    %-12s unmute countdown at hn_wipe: %s%s -> %s" % (step, cd, ", post_power_on pending" if pending else "",
                                                               "fast clear" if fast else "edge wipe") +
          ("" if fast or not (first and edge_fills) else
           ", last edge %.0f ms after hn_wipe" % ((edge_fills[-1][0] - first[0][0]) * 1000 / CLOCK_HZ)))
    if fast:
        check("%-12s %s: fast clear, no edge fills" %
              (step, "post_power_on pending" if pending else "countdown %d (unmute due within the wipe)" % cd),
              not edges, "(%d)" % len(edges))
    else:
        check("%-12s countdown %s: 160 edge steps, 318 down to 0" % (step, cd),
              bool(first) and edges == list(range(318, -1, -2)), "(%d steps)" % len(edges))
    vol_writes = [c for c, nm, d in new.events[entry["events"]:] if nm == "njw1194_write" and "R7=10" in d]
    check("%-12s NJW1194 volume write before the wipe routine" % step,
          bool(first) and bool(vol_writes) and vol_writes[0] < first[0][0],
          "(write at %s, wipe at %s clocks)" % (vol_writes[:1], first[:1]))
    if first and vol_writes:
        print("    %-12s volume write %.1f ms before the wipe routine" %
              (step, (first[0][0] - vol_writes[0]) * 1000 / CLOCK_HZ))
    if not fast:
        check("%-12s first edge fill after the volume write" % step,
              bool(vol_writes) and len(fills) > entry["fills"] and fills[entry["fills"]][0] > vol_writes[0])
    return "fast" if fast else "wipe"


BACKLIGHT = ("pin", "P0.6 backlight")


def audio_transitions(amp):
    out, last = [], None
    for c, st in amp.state_changes:
        st = tuple(kv for kv in st if kv[0] != BACKLIGHT)
        if st != last:
            out.append((c / CLOCK_HZ, st))
            last = st
    return out


def audio_checks(label, ref, new):
    """Every audio state fast-lcd went through, in the same order, none more than 0.10 s later."""
    tr_ref, tr_new = audio_transitions(ref), audio_transitions(new)
    same_order = [s for _, s in tr_ref] == [s for _, s in tr_new]
    check("%ssame sequence of audio states, in the same order" % label, same_order,
          "(%d vs %d states)" % (len(tr_ref), len(tr_new)))
    if same_order:
        late = [(tn - tr, tr) for (tr, _), (tn, _) in zip(tr_ref, tr_new) if tn - tr > 0.10]
        check("%sno audio state more than 0.10 s later than fast-lcd" % label, not late,
              "" if not late else "(%d, first %+.2f s at %.2f s)" % (len(late), late[0][0], late[0][1]))
        moved = [(tr, tn - tr) for (tr, _), (tn, _) in zip(tr_ref, tr_new) if abs(tn - tr) > 0.05]
        for tr, d in moved:
            print("    %saudio state at %7.2f s moves %+.2f s" % (label, tr, d))
    bl = [[d for _, nm, d in amp.events if nm == BACKLIGHT[1]] for amp in (ref, new)]
    check("%sbacklight switches the same way" % label, bl[0] == bl[1])


def tour():
    print("\nWhole firmware, lockstep with fast-lcd")
    amps = [Amp(BASE), Amp(NEW)]
    for amp in amps:
        amp.set_pin(0xC0, 5, 0)                         # USB audio present
        amp.boot()
    ref, new = amps
    wipes, fills = watch_wipe(new)
    entry = {}
    for step, cmd, secs, kind in TOUR:
        w0 = time.time()
        if step in VOL_ENTRY_STEPS:
            entry = entry_mark(new, wipes, fills)
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
            check("%-12s volume page exactly as hn_volpage draws it" % step,
                  new.page == 2 and new.lcd.gram == volpage_reference(new))
        else:
            check("%-12s screen identical to fast-lcd" % step, new.lcd.gram == ref.lcd.gram)
        if step in ("menu", "menu_down"):
            check("%-12s really in the menu (page >= 3)" % step, new.page >= 3, "(page %d)" % new.page)
        if step in VOL_ENTRY_STEPS:
            vol_entry_checks(step, new, entry, wipes, fills)
        if step in ("back_home", "vol_timeout"):
            # The page timer is armed after the volume write, which now follows the 200 ms
            # wipe and page draw, so home comes back that much later than on fast-lcd (0 to 0.30 s).
            both = None not in home_at
            check("%-12s home returns 0..0.30 s after fast-lcd" % step,
                  both and 0 <= home_at[1] - home_at[0] <= 0.30, str(home_at))
        new.lcd.save_png(os.path.join(HERE, "build", "tour_%s.png" % step))

    print("\n  Audio state, after every write that changes it")
    audio_checks("", ref, new)

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


NEC_USB, NEC_OPTICAL, NEC_BT = 0x10, 0x11, 0x13   # direct-select inputs 1, 2, 4 (NEC_HDMI: 5)
UNMUTE_CALL = 0x33FB                     # mute_timer_expired: mov R7,#1 ; lcall mute_state_set


def headphone_unplugged(amp):
    amp.e.iram[0x2B] = 2                 # headphone output
    amp.set_pin(0xA0, 6, 0)              # P2.6 low: Timer0 holds the countdown at 300 (0x3EE9)


# (name, what it shows, setup [(NEC command, callable or None, then wait s)], countdown, expected entry,
# seconds from the Vol+ press to the screen check, page then). Countdown "held": re-armed by the firmware,
# never expires (no unmute in either image); "runs": counts down to an unmute during the scenario.
# In "splash" post_power_on runs right after the key and returns to the home page, in both images.
SCENARIOS = [
    ("bt", "Bluetooth, no stream: 0x583F holds the countdown at 40..50",
     [(NEC_POWER, None, 9.0), (NEC_BT, None, 4.0)], "held", "wipe", 1.0, 2),
    ("optical", "Optical without signal: Timer0 holds the countdown at 100",
     [(NEC_POWER, None, 9.0), (NEC_OPTICAL, None, 4.0)], "held", "wipe", 1.0, 2),
    ("headphone", "headphone output, P2.6 low: Timer0 holds the countdown at 300",
     [(NEC_POWER, None, 9.0), (None, headphone_unplugged, 1.0)], "held", "wipe", 1.0, 2),
    ("power_on", "USB, Vol+ during the countdown after power-on",
     [(NEC_POWER, None, 7.4)], "runs", "wipe", 1.0, 2),
    ("hdmi_switch", "Vol+ 0.5 s after switching to HDMI",
     [(NEC_POWER, None, 9.0), (NEC_HDMI, None, 0.5)], "runs", "wipe", 1.0, 2),
    ("unmute_due", "USB, Vol+ when the unmute is due within the wipe",
     [(NEC_POWER, None, 8.15)], "runs", "fast", 1.0, 2),
    ("splash", "Vol+ during the power-on logo, dispatched just before post_power_on",
     [(NEC_POWER, None, 2.5)], "runs", "fast", 4.0, 1),      # the key waits for the logo (~2.5 s)
]


def input_scenarios():
    print("\nVolume key after each input settles, whole firmware, against fast-lcd")
    for name, what, setup, cd_kind, want, settle, page in SCENARIOS:
        w0 = time.time()
        print("  %s: %s" % (name, what))
        amps = [Amp(BASE), Amp(NEW)]
        ref, new = amps
        wipes, fills = watch_wipe(new)
        unmutes = [[], []]
        for k, amp in enumerate(amps):
            amp.e.hooks[UNMUTE_CALL] = lambda em, k=k: unmutes[k].append(em.cycles / CLOCK_HZ)
            amp.set_pin(0xC0, 5, 0)                     # USB audio present
            amp.boot()
            for cmd, fn, secs in setup:
                if cmd is not None:
                    amp.press(cmd)
                if fn is not None:
                    fn(amp)
                amp.wait(secs)
        label = "%-11s " % name
        before = [len(u) for u in unmutes]
        entry = entry_mark(new, wipes, fills)
        t_press = new.t
        for amp in amps:
            amp.press(NEC_VOL_UP)
            amp.wait(settle)
        kind = vol_entry_checks(name, new, entry, wipes, fills)
        check("%sentry as intended (%s)" % (label, want), kind == want, "(%s)" % kind)
        check("%ssame page, power, volumes, input, output" % label, state(ref) == state(new),
              "%s vs %s" % (state(ref), state(new)))
        check("%spage %d, screen as expected (volume: hn_volpage's render; home: fast-lcd outside our bands)" %
              (label, page), new.page == page and screen_ok(ref, new))
        new.lcd.save_png(os.path.join(HERE, "build", "inputs_%s.png" % name))
        for amp in amps:
            amp.wait(2.5)
        if cd_kind == "runs":
            for amp in amps:
                amp.wait(3.0)                           # the splash case unmutes 5.85 s after the press
        after = [u[b:] for u, b in zip(unmutes, before)]
        if cd_kind == "held":
            check("%scountdown held: no unmute in either image, still running at the end" % label,
                  after == [[], []] and countdown(ref.e) > 0 and countdown(new.e) > 0,
                  "(%s, %d / %d)" % (after, countdown(ref.e), countdown(new.e)))
        else:
            ok = len(after[0]) == 1 and len(after[1]) == 1
            shift = after[1][0] - after[0][0] if ok else None
            check("%sunmute %s after the press, no later than fast-lcd + 0.10 s" %
                  (label, "%.2f s" % (after[1][0] - t_press) if ok else "?"),
                  ok and shift <= 0.10, "(%s)" % ("%+.3f s" % shift if ok else after))
        audio_checks(label, ref, new)
        print("    %s: %.1f s" % (name, time.time() - w0), flush=True)


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


SWEEP_STATES = ["standby", "home", "volume", "volume_hp", "menu"]


# A key press arms a timer (RAM 0x37:0x38) whose expiry, in the main loop, clears the IR key
# state (0x492b). A command injected in the very iteration where it expires is lost (a race in
# the stock firmware too, it makes the key read as "go home" on page 2). Without the wipe the
# first Vol+ arms that timer at its press, so it expires exactly 0.5 s later; press the second
# key at 0.6 s, away from that instant, whichever image's timing.
VOL_SETTLE = 0.6


def reach(img, st):
    """A fresh amp driven from reset into state st (the C core's ctypes pointers can't be
    deep-copied, so every job replays from reset instead of cloning a snapshot)."""
    a = Amp(img, log_audio=False)
    a.set_pin(0xC0, 5, 0)                        # USB audio present
    a.boot()
    if st != "standby":
        a.press(NEC_POWER); a.wait(8.0)
    if st == "volume":
        a.press(NEC_VOL_UP); a.wait(VOL_SETTLE)
    elif st == "volume_hp":
        a.e.iram[0x2B] = 2                       # headphone branch of 0x5936
        a.press(NEC_VOL_UP); a.wait(VOL_SETTLE)
    elif st == "menu":
        a.press(NEC_MENU_OPEN); a.wait(1.5)      # see NEC_MENU_OPEN above the tour
    return a


def run(img, st, cmd):
    """A fresh amp reached into state st, cmd pressed and settled 0.5 s later (the 200 ms
    wipe and the page it draws take about 0.22 s; the volume page times out after 2 s and the
    menu after 9 s, so both still hold)."""
    amp = reach(img, st)
    amp.press(cmd)
    amp.wait(0.5)
    return amp


def outcome(amp):
    e = amp.e
    return (amp.page, amp.powered) + tuple(e.iram[a] for a in (0x31, 0x52, 0x47, 0x2B, 0x39, 0x17)) + \
        (e.sfr[0xA0], e.sfr[0x80] & 0x46, e.sfr[0xC0] & 0x41)


def screen_ok(base, new):
    """Whether new's screen is what we expect, given where both amps ended up: the stock
    home screen outside our bands and bar (both page 1, both powered), hn_volpage's exact
    render (both page 2, both powered), or bit-identical to base otherwise -- any other
    page (including the menu), a mismatched page pair (the outcome() check next to this one
    already catches that), or either amp mid power-off, where the whole screen (bar and
    all) blanks to black in both images alike, same as the tour's own "standby" step
    (kind "same", not "home") treats it."""
    if base.powered and new.powered:
        if new.page == 1 and base.page == 1:
            return home_screen_ok(new, base)
        if new.page == 2 and base.page == 2:
            return new.lcd.gram == volpage_reference(new)
    return new.lcd.gram == base.lcd.gram


def job(args):
    st, cmd = args
    base, new = run(BASE, st, cmd), run(NEW, st, cmd)
    return st, cmd, outcome(base), outcome(new), screen_ok(base, new)


def sweep():
    print("\nIR sweep: 256 commands x %d states, against fast-lcd" % len(SWEEP_STATES))
    t0 = time.time()
    pages = {st: (reach(NEW, st).page, reach(NEW, st).powered) for st in SWEEP_STATES}
    check("snapshots in the intended states", pages["standby"][1] is False and pages["home"] == (1, True)
          and pages["volume"][0] == 2 and pages["volume_hp"][0] == 2 and pages["menu"][0] >= 3, str(pages))
    a1, a2 = run(NEW, "volume", NEC_VOL_UP), run(NEW, "volume", NEC_VOL_UP)
    check("snapshot runs are repeatable", outcome(a1) == outcome(a2) and a1.lcd.gram == a2.lcd.gram)
    print("  reached all states in %.0f s" % (time.time() - t0), flush=True)
    jobs = [(st, cmd) for st in SWEEP_STATES for cmd in range(256)]
    with mp.get_context("fork").Pool() as pool:
        res = pool.map(job, jobs, chunksize=8)
    for st in SWEEP_STATES:
        diff = [c for s, c, a, b, ok in res if s == st and a != b]
        scr = [c for s, c, a, b, ok in res if s == st and not ok]
        check("%-10s 256 commands: same page, power, volumes, input, output, EQ, pins" % st, not diff,
              str(["%02X" % c for c in diff[:8]]))
        check("%-10s screens as expected (home: fast-lcd outside our bands; volume: hn_volpage; "
              "other: identical to fast-lcd)" % st, not scr, str(["%02X" % c for c in scr[:8]]))
    print("  sweep in %.0f s" % (time.time() - t0))


GROUPS = {
    "unit": [image_diff, test_fill, test_digit2x, test_text, test_name_ptr,
             test_draw_volume, test_volpage, test_wipe, test_tick, test_enter_vol, test_home_tail, test_align],
    "tour": [tour, input_scenarios],
    "sweep": [sweep],
}


def main():
    for g in sys.argv[1:] or ["unit", "tour", "sweep"]:
        for fn in GROUPS[g]:
            fn()
    print("\nALL PASS" if not fails else "\nFAILURES: %s" % fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
