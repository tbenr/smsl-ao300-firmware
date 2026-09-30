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
import features  # noqa: E402
import uikit  # noqa: E402
import pfont  # noqa: E402
import uitest as ut  # noqa: E402
from asm51 import Asm  # noqa: E402
from ao300 import CLOCK_HZ  # noqa: E402

BASE_IMAGE = features.image("fast-lcd")
BASE_SHA = "b292a64855975584dda5fe3fb282103bfde77f7f7237ca9945ac4b5442dae859"
CODE_ADDR = 0x9800
WHITE_ACCENT = 0xFC43
W, H = ut.W, ut.H

TP_BASE = 0x0160
# proportional test fonts: both formats, large and small, a sparse map (a character in the range
# that is not in the font), glyphs with and without side bearings
PFONTS = {f.name: f for f in (
    pfont.PFont("tf_num84", "num84", "0123456789.- ", bpp=2, alias={"-": "\u2212"}),
    pfont.PFont("tf_disp52", "disp52", "ABCILOPSTUX ", bpp=2),
    pfont.PFont("tf_mono11", "mono11", pfont.ASCII, bpp=1),
    pfont.PFont("tf_mono11r", "mono11", pfont.ASCII, bpp=2),
    pfont.PFont("tf_num22", "num22", "0123456789", bpp=1),
)}

fails = []


def check(name, ok, detail=""):
    print("  %-72s %s %s" % (name, "OK  " if ok else "FAIL", detail))
    if not ok:
        fails.append(name)


def build():
    base = open(BASE_IMAGE, "rb").read()
    assert hashlib.sha256(base).hexdigest() == BASE_SHA, "fast-lcd image is not the registered build"
    kit = uikit.Kit(tp_base=TP_BASE)
    a = Asm(CODE_ADDR)
    kit.emit_font_data(a)
    kit.emit_fill(a)
    kit.emit_accent(a, WHITE_ACCENT)
    kit.emit_painter(a)
    kit.emit_text(a)
    for f in PFONTS.values():
        f.emit(a)
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


def ref_text(font, s, x, y, ink=0xFFFF, bg=0, clip=(0, 319), align=0, spacing=0, ground=0x1234, rows=(0, 255)):
    fb = [[ground] * W for _ in range(H)]
    end = PFONTS[font].render(fb, s, x, y, ink, bg, clip, align, spacing, rows)
    return fb, end


def same(e, fb):
    return all(ut.px(e, x, y) == fb[y][x] for y in range(H) for x in range(W))


def utext(font, s, x, y, ground=0x1234, **kw):
    e = emu(); ut.fill_screen(e, ground)
    t = ut.text(e, LAB, KIT, font, s, x, y, **kw)
    return e, t


def test_avg():
    print("\nuk_avg (the 2-bit fonts' middle colours)")
    import random
    rnd = random.Random(1)
    bad = []
    e = emu()
    for a_, b_ in [(0xFFFF, 0), (0, 0xFFFF), (0xF800, 0x07FF), (0xFC43, 0x0000), (0x0821, 0x0821)] + \
            [(rnd.randrange(65536), rnd.randrange(65536)) for _ in range(200)]:
        for n, v in ((2, a_ >> 8), (3, a_ & 0xFF), (4, b_ >> 8), (5, b_ & 0xFF)):
            e.setR(n, v)
        e.call(LAB["uk_avg"])
        if (e.R(6) << 8 | e.R(7)) != pfont.avg565(a_, b_) or (e.R(2) << 8 | e.R(3)) != a_:
            bad.append((a_, b_))
    check("205 colour pairs: the per-channel average, R2..R5 kept", not bad, str(bad[:3]))


def test_text_glyphs():
    print("\nuk_text: every glyph of the test fonts against pfont.render")
    for name, f in PFONTS.items():
        bad = []
        for ch in f.order:
            y = 20 if f.H > 40 else 60
            kw = dict(ink=0xFC43, bg=0x0841)
            e, _ = utext(name, ch, 100, y, **kw)
            fb, end = ref_text(name, ch, 100, y, **kw)
            inked = ch == " " or any(0xFC43 in row for row in fb)
            if not inked or not same(e, fb) or ut.tp_end(e, KIT) != end:
                bad.append(ch)
        check("%-10s format %d, %2d rows, %3d glyphs, %5d bytes: pixel-identical, TP_END"
              % (name, f.bpp, f.H, len(f.order), f.size()), not bad, str(bad[:8]))


def test_text_strings():
    print("\nuk_text: strings, alignment, spacing, missing characters, tints")
    cases = [
        ("tf_num84", "60", 304, 51, dict(align=1)),
        ("tf_num84", "-29.0", 304, 51, dict(align=1)),
        ("tf_num84", "7", 160, 51, dict(align=2)),
        ("tf_disp52", "OPTICAL", 16, 61, dict(spacing=1)),
        ("tf_disp52", "BLUETOOTH", 16, 61, dict(spacing=1)),      # E, H, N, O not all in the font
        ("tf_disp52", "USB", 160, 61, dict(align=2, spacing=1)),
        ("tf_mono11", "44.1kHz  No signal", 18, 68, {}),
        ("tf_mono11", "VOL", 158, 24, dict(spacing=3)),
        ("tf_mono11r", "max 60", 304, 148, dict(align=1)),
        ("tf_mono11r", "step 32 / 60", 16, 148, {}),
        ("tf_num22", "5", 36, 8, {}),
        ("tf_num22", "", 36, 8, {}),
        ("tf_mono11", "\x7f\x01", 36, 8, {}),                     # outside the map: skipped
    ]
    bad = []
    for font, s, x, y, kw in cases:
        for ink, bg in ((0xFFFF, 0x0000), (0xFC43, 0x0000), (0x07E0, 0x2104)):
            e, _ = utext(font, s, x, y, ink=ink, bg=bg, **kw)
            fb, end = ref_text(font, s, x, y, ink=ink, bg=bg, **kw)
            inked = s in ("", "\x7f\x01") or any(ink in row for row in fb)
            if not inked or not same(e, fb) or ut.tp_end(e, KIT) != end:
                bad.append((font, s, "%04X/%04X" % (ink, bg)))
    check("%d strings x 3 ink/background pairs: pixel-identical, TP_END" % len(cases), not bad, str(bad[:4]))
    e, _ = utext("tf_mono11", "", 40, 8)
    check("empty string: TP_END = x - 1, nothing drawn",
          ut.tp_end(e, KIT) == 39 and all(v == 0x1234 for v in e.lcd.gram))


def test_text_clip_and_speed():
    print("\nuk_text: clip windows (the run-length skip and cut paths), measurements, speed")
    bad = []
    for font, s, x, y, kw in (("tf_num84", "-48.5", 304, 51, dict(align=1)),
                              ("tf_disp52", "COAXIAL", 16, 61, dict(spacing=1)),
                              ("tf_mono11", "Analog input", 18, 68, {}),
                              ("tf_mono11r", "Analog input", 18, 68, {})):
        e0, _ = utext(font, s, x, y, clip=(0, 0xFFFF), **kw)
        _, end = ref_text(font, s, x, y, **kw)
        x0 = x if kw.get("align") != 1 else end - PFONTS[font].width(s, kw.get("spacing", 0)) + 1
        for c0, c1 in ((0, 319), (x0 + 1, x0 + 1), (x0 + 3, x0 + 40), (x0 + 17, 400), (0, x0 + 5),
                       (x0 + 30, x0 + 30), (x0 + 11, x0 + 62), (end, end), (end - 20, end - 2), (end + 1, 319)):
            e, _ = utext(font, s, x, y, clip=(c0, c1), **kw)
            fb, _ = ref_text(font, s, x, y, clip=(c0, c1), **kw)
            if not same(e, fb):
                bad.append((font, c0, c1))
    check("4 strings x 10 clip windows (mid-glyph, mid-run, one column): only those columns, same pixels",
          not bad, str(bad[:4]))
    e, _ = utext("tf_disp52", "OPTICAL", 16, 61, clip=(256, 0), spacing=1)
    _, end = ref_text("tf_disp52", "OPTICAL", 16, 61, spacing=1)
    check("empty clip window: nothing drawn, TP_END as drawn (%d)" % end,
          all(v == 0x1234 for v in e.lcd.gram) and ut.tp_end(e, KIT) == end)
    f84, f11 = PFONTS["tf_num84"], PFONTS["tf_mono11"]
    _, t1 = utext("tf_num84", "88", 16, 51)
    n1 = f84.width("88") * f84.H
    _, t2 = utext("tf_mono11", "2.8224MHz Connected", 16, 68)
    n2 = f11.width("2.8224MHz Connected") * f11.H
    _, t3 = utext("tf_mono11r", "2.8224MHz Connected", 16, 68)
    print("    88 (84 px, run-length, %d px) %.2f ms; 2.8224MHz Connected (11 px, %d px): 1-bit %.2f ms, "
          "run-length %.2f ms" % (n1, t1 * 1000 / CLOCK_HZ, n2, t2 * 1000 / CLOCK_HZ, t3 * 1000 / CLOCK_HZ))
    check("at most 16 clocks per pixel on large run-length glyphs, 24 on 11 px text (per-cell setup)",
          t1 / n1 <= 16 and t2 / n2 <= 24 and t3 / n2 <= 24, "(%.1f, %.1f, %.1f)" % (t1 / n1, t2 / n2, t3 / n2))


def test_text_rows():
    print("\nuk_textc: the row clip (TP_YC0..TP_YC1) against pfont.render(rows=...)")
    cases = [("tf_num84", "-48.5", 304, 51, dict(align=1)),
             ("tf_num84", "10", 304, 41, dict(align=1)),
             ("tf_disp52", "COAXIAL", 16, 61, dict(spacing=1)),
             ("tf_mono11", "Analog input", 18, 68, {}),
             ("tf_mono11r", "max 60", 304, 148, dict(align=1)),
             ("tf_num22", "0123", 36, 8, {})]
    bad, n = [], 0
    for font, s, x, y, kw in cases:
        h = PFONTS[font].H
        clips = [(y + 5, 255), (0, y + h - 6), (y + 3, y + h - 4), (y + h // 2, y + h // 2), (y + 1, y + 1),
                 (y + h - 1, y + h + 20), (0, y - 1), (y + h, 169), (y + 9, y + 3), (y, y + h - 1), (0, 255),
                 (max(0, y - 7), y + h // 3)]
        for rows in clips:
            for clip in ((0, 319), (x + 3 if kw.get("align") != 1 else x - 40, x + 30 if kw.get("align") != 1 else x - 9)):
                n += 1
                kw2 = dict(kw, ink=0xFC43, bg=0x0841, clip=clip)
                e, _ = utext(font, s, x, y, rows=rows, **kw2)
                fb, end = ref_text(font, s, x, y, rows=rows, **kw2)
                if not same(e, fb) or ut.tp_end(e, KIT) != end:
                    bad.append((font, s, rows, clip))
    check("%d draws (6 strings in both formats, 12 row clips: above, below, both, one row, outside, empty, "
          "the whole cell; x clips): only those rows and columns, same pixels, TP_END" % n, not bad, str(bad[:4]))
    bad = []
    for font, s, x, y, kw in cases:
        e0, t0 = utext(font, s, x, y, **kw)
        e1, t1 = utext(font, s, x, y, rows=(0, 255), **kw)
        e2, _ = utext(font, s, x, y, rows=(y, y + PFONTS[font].H - 1), **kw)
        if e0.lcd.gram != e1.lcd.gram or e0.lcd.gram != e2.lcd.gram or t1 - t0 > 20:
            bad.append((font, s, t1 - t0))
    check("uk_textc with every row (0..255, or exactly the cell's) = uk_text, in the same time", not bad, str(bad[:3]))
    f84 = PFONTS["tf_num84"]
    _, t0 = utext("tf_num84", "88", 16, 51)
    _, t1 = utext("tf_num84", "88", 16, 51, rows=(61, 169))
    n1 = f84.width("88") * (f84.H - 10)
    print("    88 (84 px) with the top 10 rows clipped: %.2f ms (%.1f clocks per drawn pixel), unclipped %.2f ms"
          % (t1 * 1000 / CLOCK_HZ, t1 / n1, t0 * 1000 / CLOCK_HZ))
    check("row-clipped run-length glyphs at most 24 clocks per drawn pixel", t1 / n1 <= 24, "(%.1f)" % (t1 / n1))


def main():
    print("uikit: %d bytes of kit code and test fonts at 0x%04X, XDATA 0x%04X..0x%04X, uk_text 0x%04X..0x%04X" %
          (len(IMG) - CODE_ADDR, CODE_ADDR, KIT.fill_n, KIT.FP + KIT.FP_SIZE - 1, TP_BASE, TP_BASE + KIT.TP_SIZE - 1))
    test_fill()
    test_accent()
    test_glyphs()
    test_strings()
    test_clip_and_speed()
    test_avg()
    test_text_glyphs()
    test_text_strings()
    test_text_clip_and_speed()
    test_text_rows()
    print("\nALL PASS" if not fails else "\nFAILURES: %s" % fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
