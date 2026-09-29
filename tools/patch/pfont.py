#!/usr/bin/env python3
"""pfont: proportional fonts for uk_text, packed from the browser rasters in tools/fonts/raster/.

A PFont is one raster (a face at one size, see tools/fonts/specs.json) cut down to the characters a
theme needs and quantised to 1 bit (ink or not) or 2 bits (4 levels: background, 1/4, 3/4, ink;
uk_text mixes the two middle colours). Glyph data is column-major like the stock fonts, each column
top to bottom:
    format 1 (bpp 1)  packed, bpc = H / 8 bytes per column, the first pixel in the high bit
    format 2 (bpp 2)  run-length: bytes level << 6 | length (1..63) over all the glyph's columns,
                      then a 0; about half the size of packed 2-bit pixels for large faces

In code (PFont.emit):
    <name>:      db H, bpc, format, first, n   H rows (format 1: a multiple of 8), bpc = H * bpp / 8
                 dw <name>_map, <name>_tab
    <name>_map:  n bytes, one per character first .. first + n - 1: its glyph index, 0xFF = not in
                 the font (uk_text skips it)
    <name>_tab:  5 bytes per glyph: db advance, off, w ; dw data
                 a glyph is a cell of `advance` columns: `off` background columns, `w` columns of
                 data, background up to the advance
The cell's rows start `top` rows from the baseline (top < 0: above it); PFont.top says where, so a
theme passes y = baseline + top to uk_text.

render() draws text the way uk_text does, for tests and previews.
"""
import json
import os

RASTER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts", "raster")
ASCII = "".join(chr(c) for c in range(0x20, 0x7F))


def load_raster(rid):
    with open(os.path.join(RASTER_DIR, rid + ".json")) as f:
        return json.load(f)


def level(v, bpp):
    """4-bit coverage (0..15) -> pixel level: 1 bpp 0/1 at half coverage; 2 bpp the nearest of
    0, 1/4, 3/4, 1 (the colours uk_text can mix with averages)."""
    if bpp == 1:
        return 1 if v >= 8 else 0
    return 0 if v <= 1 else 1 if v <= 7 else 2 if v <= 13 else 3


def avg565(a, b):
    """Per-channel average of two RGB565 colours, rounding down (uk_mix does the same)."""
    return (a & b) + (((a ^ b) & 0xF7DE) >> 1)


def ramp(ink, bg):
    """The colours of levels 0..3 for 2 bpp: background, 1/4 ink, 3/4 ink, ink."""
    half = avg565(ink, bg)
    return [bg, avg565(bg, half), avg565(ink, half), ink]


class PFont:
    """name: label prefix in code; raster: raster id; chars: characters to keep (the codes the
    firmware strings use); alias: {char: raster character to draw it with}, e.g. {"-": "−"}."""

    def __init__(self, name, raster, chars, bpp=2, alias=None):
        assert bpp in (1, 2)
        self.name, self.bpp = name, bpp
        r = load_raster(raster)
        self.raster, self.font = raster, r["font"]
        alias = alias or {}
        chars = sorted(set(chars))
        assert all(0x20 <= ord(c) < 0x80 for c in chars), "uk_text strings are 7-bit"
        self.first, self.last = ord(chars[0]), ord(chars[-1])
        self.notes = []
        src = {}
        for c in chars:
            s = alias.get(c, c)
            if s not in r["glyphs"]:
                raise SystemExit("%s: %r not in raster %s" % (name, s, raster))
            src[c] = r["glyphs"][s]
        inked = [g for g in src.values() if g["rows"]]
        top = min(g["y"] for g in inked)
        bot = max(g["y"] + len(g["rows"]) for g in inked)
        per = 8 if bpp == 1 else 1
        self.top = top
        self.H = (bot - top + per - 1) // per * per
        self.bpc = (self.H * bpp + 7) // 8
        self.glyphs = {}                      # char -> (adv, off, w, columns of levels)
        for c, g in src.items():
            adv = int(round(g["adv"]))
            if not g["rows"]:
                self.glyphs[c] = (adv, 0, 0, [])
                continue
            off, w = g["x"], len(g["rows"][0])
            if off < 0:
                self.notes.append("%r: ink starts %d px left of the pen, moved right" % (c, -off))
                off = 0
            if off + w > adv:
                self.notes.append("%r: ink ends %d px past the advance, advance widened" % (c, off + w - adv))
                adv = off + w
            cols = []
            for x in range(w):
                col = [0] * self.H
                for y, row in enumerate(g["rows"]):
                    col[g["y"] - top + y] = level(int(row[x], 16), bpp)
                cols.append(col)
            self.glyphs[c] = (adv, off, w, cols)
        self.order = sorted(self.glyphs)       # glyph index order

    # ---- metrics and reference rendering ----
    def width(self, text, spacing=0):
        return sum(self.glyphs[c][0] + spacing for c in text if c in self.glyphs)

    def glyph_bytes(self, c):
        cols = self.glyphs[c][3]
        if self.bpp == 1:
            out = []
            for col in cols:
                for k in range(0, self.H, 8):
                    v = 0
                    for p in col[k:k + 8]:
                        v = v << 1 | p
                    out.append(v)
            return out
        stream = [p for col in cols for p in col]
        out, i = [], 0
        while i < len(stream):
            j = i
            while j < len(stream) and stream[j] == stream[i] and j - i < 63:
                j += 1
            out.append(stream[i] << 6 | (j - i))
            i = j
        return out + [0]

    def size(self):
        """Bytes in code: descriptor, map, table, glyph data."""
        return 9 + (self.last - self.first + 1) + 5 * len(self.order) + \
            sum(len(self.glyph_bytes(c)) for c in self.glyphs)

    def render(self, fb, text, x, y, ink, bg, clip=(0, 319), align=0, spacing=0):
        """Draw as uk_text does into fb (a dict or 2-D list indexed fb[y][x], 320 x 170).
        align 0: x is the first column; 1: x is the last column; 2: x is the centre
        (the first column is x - width // 2). Returns the last column of the last cell."""
        wd = self.width(text, spacing)
        if align == 1:
            x = x - wd + 1
        elif align == 2:
            x = x - wd // 2
        cols = ramp(ink, bg) if self.bpp == 2 else [bg, ink]
        for c in text:
            if c not in self.glyphs:
                continue
            adv, off, w, gcols = self.glyphs[c]
            for r in range(adv + spacing):
                cx = x + r
                if not clip[0] <= cx <= clip[1]:
                    continue
                col = gcols[r - off] if off <= r < off + w else None
                for k in range(self.H):
                    fb[y + k][cx] = cols[col[k]] if col else bg
            x += adv + spacing
        return x - 1

    # ---- code ----
    def emit(self, a):
        from asm51 import hi8, lo8
        n = self.last - self.first + 1
        a.comment("%s: %s from raster %s, format %d, %d rows from baseline %+d, %d bytes"
                  % (self.name, self.font, self.raster, self.bpp, self.H, self.top, self.size()))
        a.L(self.name)
        a.data("db %d,%d,%d,%d,%d" % (self.H, self.bpc, self.bpp, self.first, n),
               [self.H, self.bpc, self.bpp, self.first, n])
        a.i("dw %s_map" % self.name, hi8(self.name + "_map"), lo8(self.name + "_map"))
        a.i("dw %s_tab" % self.name, hi8(self.name + "_tab"), lo8(self.name + "_tab"))
        a.L(self.name + "_map")
        row = [self.order.index(chr(c)) if chr(c) in self.glyphs else 0xFF for c in range(self.first, self.last + 1)]
        for k in range(0, n, 16):
            a.data("db " + ",".join("%d" % v for v in row[k:k + 16]), row[k:k + 16])
        a.L(self.name + "_tab")
        for i, c in enumerate(self.order):
            adv, off, w, _ = self.glyphs[c]
            lab = "%s_g%d" % (self.name, i)
            a.data("db %d,%d,%d ; %r" % (adv, off, w, c), [adv, off, w])
            a.i("dw %s" % lab, hi8(lab), lo8(lab))
        for i, c in enumerate(self.order):
            a.L("%s_g%d" % (self.name, i))
            data = self.glyph_bytes(c)
            for k in range(0, len(data), 16):
                a.data("db " + ",".join("0x%02X" % v for v in data[k:k + 16]), data[k:k + 16])
