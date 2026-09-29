#!/usr/bin/env python3
"""Emulator tests for tools/patch/uikit.py, independent of any theme.

Builds fast-lcd + the kit's routines at 0x9800 in memory (no hooks: nothing in the stock firmware
calls them) and checks uk_fill, uk_acc and uk_paint / uk_home_x against the stock routines:
every character of both fonts, scale 2, whole strings (every input name, every string in the
firmware's string area, every sample-rate status) against the stock text renderers, clip windows
and speed. Needs features/fast-lcd/build/flash_fastlcd.bin (python3 features/fast-lcd/build_patch.py).

    python3 tools/patch/uikit_test.py
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools", "emu"))
import uikit  # noqa: E402
import uitest as ut  # noqa: E402
from asm51 import Asm  # noqa: E402
from ao300 import CLOCK_HZ  # noqa: E402

BASE_IMAGE = os.path.join(ROOT, "features", "fast-lcd", "build", "flash_fastlcd.bin")
BASE_SHA = "b292a64855975584dda5fe3fb282103bfde77f7f7237ca9945ac4b5442dae859"
CODE_ADDR = 0x9800
WHITE_ACCENT = 0xFC43
W, H = ut.W, ut.H

fails = []


def check(name, ok, detail=""):
    print("  %-72s %s %s" % (name, "OK  " if ok else "FAIL", detail))
    if not ok:
        fails.append(name)


def build():
    base = open(BASE_IMAGE, "rb").read()
    assert hashlib.sha256(base).hexdigest() == BASE_SHA, "fast-lcd image is not the registered build"
    kit = uikit.Kit()
    a = Asm(CODE_ADDR)
    kit.emit_font_data(a)
    kit.emit_fill(a)
    kit.emit_accent(a, WHITE_ACCENT)
    kit.emit_painter(a)
    code = a.resolve()
    img = bytearray(base) + b"\xFF" * (CODE_ADDR - len(base)) + code
    assert len(img) <= uikit.CODE_END
    return base, bytes(img), a.labels, kit


BASE, IMG, LAB, KIT = build()


def emu(theme=(0xFF, 0xFF)):
    return ut.emu(IMG, theme)


def paint(e, *args, **kw):
    return ut.paint(e, LAB, KIT, *args, **kw)


def test_fill():
    print("uk_fill")
    e = emu()

    def fill(x, w, y, h, c):
        for n, v in ((2, x >> 8), (3, x & 0xFF), (1, w), (5, y), (4, h), (6, c >> 8), (7, c & 0xFF)):
            e.setR(n, v)
        c0 = e.cycles
        e.call(LAB["uk_fill"])
        return e.cycles - c0
    t1 = fill(250, 40, 100, 20, 0xF81F)
    check("40x20 across x=256 in the exact colour",
          all(ut.px(e, x, y) == 0xF81F for x in range(250, 290) for y in range(100, 120)))
    check("nothing outside the rectangle", ut.stray(e, [(250, 100, 40, 20)]) == 0)
    t2 = fill(0, 80, 0, 20, 0x07E0)          # about the same window cost, 800 more pixels
    per_px = (t2 - t1) / 800
    check("fill loop at most 10 clocks per pixel", per_px <= 10, "(%.1f)" % per_px)
    fill(0, 2, 0, 170, 0x001F)
    check("2 x 170 column (count above 255)", all(ut.px(e, x, y) == 0x001F for x in (0, 1) for y in range(170)))
    check("theme colour untouched", (e.iram[0x48], e.iram[0x49]) == (0xFF, 0xFF))


def test_accent():
    print("\nui_acc")
    for theme, want in (((0xFF, 0xFF), WHITE_ACCENT), ((0xF8, 0x00), 0xF800), ((0x33, 0xBF), 0x33BF)):
        e = emu(theme)
        for n in range(1, 6):
            e.setR(n, 0x10 + n)
        e.call(LAB["uk_acc"])
        check("tint %02X%02X -> %04X, R1..R5 kept" % (theme + (want,)),
              ((e.R(6) << 8) | e.R(7)) == want and all(e.R(n) == 0x10 + n for n in range(1, 6)))


def stock_ok(font, ch):
    return ch in (uikit.SMALL_MAP if font == "font_small" else uikit.BIG_MAP)


def test_glyphs():
    print("\nui_paint against the stock glyph painters")
    for font, stock, w, h in (("font_small", ut.stock_small, 14, 24), ("font_big", ut.stock_big, 30, 32)):
        bad, blank = [], []
        for c in range(0x20, 0x80):
            ch = chr(c)
            e = emu(); ut.fill_screen(e, 0x1234)
            paint(e, font, text=ch, x=100, y=40, ink=0xF81F, bg=0x0841)
            if stock_ok(font, ch):
                ref = emu((0xF8, 0x1F)); ut.fill_screen(ref, 0x1234)
                stock(ref, ch, 100, 40)
                cell = all(ut.px(e, 100 + i, 40 + j) ==
                           (0xF81F if ut.px(ref, 100 + i, 40 + j) == 0xF81F else 0x0841)
                           for i in range(w) for j in range(h))
                if not cell or ut.stray(e, [(100, 40, w, h)]) != (W * H - w * h):
                    bad.append(ch)
            elif not all(ut.px(e, 100 + i, 40 + j) == 0x0841 for i in range(w) for j in range(h)):
                blank.append(ch)
        check("%s: every stock-mapped character 0x20..0x7F = the stock glyph, ink and background"
              % font, not bad, str(bad))
        check("%s: characters the stock font does not map draw blank" % font, not blank, str(blank))
    bad = []
    for ch in "0123456789AOIZ ":
        ref = ut.stock_glyph(IMG, ch)
        e = emu()
        paint(e, "font_big", text=ch, x=150, y=40, scale=2)
        if not ut.scaled_match(e, 150, 40, ref) or ut.stray(e, [(150, 40, 60, 64)]):
            bad.append(ch)
    check("big font at scale 2 = the stock glyph doubled (digits, letters, blank)", not bad, str(bad))


def test_strings():
    print("\nui_paint and uk_home_x against the stock text renderers (page 1)")
    names = [t for _, _, t in uikit.INPUT_NAMES]
    strings = ut.firmware_strings(BASE)
    big = sorted(set(names + [s for s in strings if all(c in uikit.BIG_MAP for c in s)]))
    small = sorted(set(strings + ut.sample_rate_strings(BASE)))
    small = [s for s in small if all(c in uikit.SMALL_MAP for c in s)]
    small += ["ABCDEFGHIJKLMNOPQRSTU", "ABCDEFGHIJKLMNOPQRST", "x"]   # 294 px: centred; 280 px: x 16
    for kind, font, strs, buf, y, stock_entry, start_at in (
            ("big", "font_big", big, uikit.BIG_BUF, uikit.NAME_Y, 0x298B, 0x2A25),
            ("small", "font_small", small, uikit.SMALL_BUF, uikit.STATUS_Y, 0x3A53, 0x3A82)):
        bad_px, bad_x = [], []
        for s in strs:
            for theme in ((0xFF, 0xFF), (0x07, 0xE0)):
                ref, new = emu(theme), emu(theme)
                for e in (ref, new):
                    e.iram[0x45] = 1
                    for k, ch in enumerate(s.encode() + b"\0"):
                        e.xram[buf + k] = ch
                start = []                    # the start x the stock renderer computed (XDATA 4:5)
                ref.hooks[start_at] = lambda em: start.append((em.xram[4] << 8) | em.xram[5])
                ref.setR(6, 0); ref.setR(7, y)
                ref.call(stock_entry)
                # uk_home_x: the stock start, moved to 16 unless that is below 16
                ut.set_fp(new, LAB, KIT, font, code_ptr=buf, x=0, y=y, ink=(theme[0] << 8) | theme[1])
                new.xram[KIT.FP_SPC] = 0                                    # the string is in XDATA
                new.call(LAB["uk_home_x"])
                hx = (new.xram[KIT.FP_X] << 8) | new.xram[KIT.FP_X + 1]
                # (wider than the screen: the stock start wraps above 255; uk_home_x keeps it)
                if hx != (16 if 16 <= start[0] <= 255 else start[0]):
                    bad_x.append((s, start[0], hx))
                # uk_paint at the stock start: the same pixels as the stock renderer
                new.xram[KIT.FP_X], new.xram[KIT.FP_X + 1] = start[0] >> 8, start[0] & 0xFF
                new.call(LAB["uk_paint"])
                if new.lcd.gram != ref.lcd.gram:
                    bad_px.append((s, theme))
        check("%s: %d strings x 2 tints, pixel-identical to the stock renderer" % (kind, len(strs)),
              not bad_px, str(bad_px[:4]))
        check("%s: uk_home_x = the stock start, left-aligned at 16 when it fits" % kind, not bad_x, str(bad_x[:4]))
    print("    big: %s" % ", ".join(big))
    print("    small: %s" % ", ".join(small))


def test_clip_and_speed():
    print("\nui_paint: clip windows, measurements, speed")
    bad = []
    for kw, cells, rows in ((dict(text="OPTICAL", x=16, y=75), (16, 212), (75, 107)),
                            (dict(text="47", x=184, y=42, scale=2), (184, 303), (42, 106))):
        ref = emu()
        paint(ref, "font_big", **kw)
        for c0, c1 in ((0, 319), (50, 60), (100, 100), (121, 400), (0, 15), (185, 200), (215, 250),
                       (243, 244), (245, 303), (304, 319), (212, 212)):
            e = emu(); ut.fill_screen(e, 0x1234)
            paint(e, "font_big", clip=(c0, c1), **kw)
            ok = all(ut.px(e, x, y) == (ut.px(ref, x, y) if c0 <= x <= c1 and cells[0] <= x <= cells[1] and
                                        rows[0] <= y < rows[1] else 0x1234)
                     for x in range(W) for y in range(H))
            if not ok:
                bad.append((kw["text"], c0, c1))
    check("clip windows (scale 1 and 2, odd edges, empty): only those columns, same pixels", not bad, str(bad))
    e = emu(); ut.fill_screen(e, 0x1234)
    paint(e, "font_big", text="OPTICAL", x=16, y=75, clip=(256, 0))
    check("empty clip window: nothing drawn, FP_END = 212 (OPTICAL at 16, narrow I)",
          all(v == 0x1234 for v in e.lcd.gram) and ut.fp_end(e, KIT) == 212, "(%d)" % ut.fp_end(e, KIT))
    e = emu()
    paint(e, "font_small", text="", x=16, y=0)
    check("empty string: FP_END = x - 1", ut.fp_end(e, KIT) == 15)
    e = emu()
    t1 = paint(e, "font_big", text="OPTICAL", x=16, y=75)
    t2 = paint(e, "font_big", text="47", x=184, y=42, scale=2)
    t3 = paint(e, "font_small", text="2.8224MHz", x=16, y=135)
    print("    OPTICAL (big, 6720 px) %.2f ms, 47 (scale 2, 7680 px) %.2f ms, 2.8224MHz (small, 3024 px) %.2f ms"
          % (t1 * 1000 / CLOCK_HZ, t2 * 1000 / CLOCK_HZ, t3 * 1000 / CLOCK_HZ))
    check("painter at most 14 clocks per pixel (scale 1) and 10 (scale 2)",
          t1 / 6720 <= 14 and t2 / 7680 <= 10, "(%.1f, %.1f)" % (t1 / 6720, t2 / 7680))


def main():
    print("uikit: %d bytes of kit code at 0x%04X, XDATA 0x%04X..0x%04X" %
          (len(IMG) - CODE_ADDR, CODE_ADDR, KIT.fill_n, KIT.FP + KIT.FP_SIZE - 1))
    test_fill()
    test_accent()
    test_glyphs()
    test_strings()
    test_clip_and_speed()
    print("\nALL PASS" if not fails else "\nFAILURES: %s" % fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
