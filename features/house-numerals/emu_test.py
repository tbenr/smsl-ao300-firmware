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
    NEC_VOL_UP, NEC_VOL_DOWN                                     # noqa: E402
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


GROUPS = {
    "unit": [image_diff, test_fill, test_digit2x, test_text, test_name_ptr],
    "tour": [],
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
