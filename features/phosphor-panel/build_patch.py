#!/usr/bin/env python3
"""Build the "Phosphor Panel" image for the SMSL AO300 (on top of fast-lcd), pp2.

Study 2 of features/ui-theme/ui_themes.html (after Marantz, Pioneer and Accuphase VFDs), built
the way House Numerals is built; the design is docs/superpowers/specs/2026-10-10-phosphor-panel-
design.md. Everything lit is drawn in the phosphor `ph`: the COLOR tint, mint on the White tint
(uk_acc). Brightness is a ladder of eight levels made from ph with uk_avg (7 = ph, 6 = 3/4, 5 =
1/2, 4 = 3/8, 3 = 1/4, 2 = 3/16, 1 = 1/8 = the ghost of an unlit VFD segment, 0 = black).

  home      a row of indicator lamps along the top (the output icon and the volume, the input,
            the format tag and the EQ tag as the stock tags spell them, "MUTE" red when muted
            and dark red otherwise), the input name centred in the display face as a dot
            matrix (every third column and row of the screen grid black, baked into pf_name),
            the status line centred under it (red without a signal). Each stock painter of a
            home element is replaced by ours; the big and small text renderers hand the name
            (page 1, y 75: every big text) and the status line (page 1, y 135) to us.
  volume    the same row without the icon and volume slot; four seven-segment cells (the two
            left ones always ghosts, the two right ones the number shown), "VOL" lit and "dB"
            a ghost, a bar of 50 cells lit up to the number, the marks 0..60 under it. The
            number shown is a counter that steps towards the volume every 2 ticks (the mock's
            45/s); a segment or bar cell that lights goes to full at once, one that goes out
            fades a level every 4 ticks down to the ghost (afterglow). Muted: the digits blink
            (50 ticks lit, 40 out), no bar cell lit, the MUTE lamp red.
  moves     the mock's afterglow crossfade, sequenced for a write-only panel. A per-tick engine
            (uk_tasks -> pp_step) keeps a level and a target for the name, "VOL", the 28
            segments and the 50 bar cells and moves each one level at a time, repainting what
            changed. Entry: the slot and the status line go black and the marks and the ghost
            bar appear (tick 1); the name falls a level every 2 ticks while the bar scans in 3
            cells a tick; once the name is black, "dB" and the ghost cells appear and the digit
            cells and "VOL" rise a level every 2 ticks. Exit: the marks and "dB" go, every lit
            segment and bar cell and "VOL" fall; once every cell is black the name rises; then
            the slot and the status line are drawn and the engine settles. A key during an exit
            reverses it through the same targets, and the other way round. Any stock clear
            stops the engine; a page-1 draw during an exit ends the exit with the whole home
            screen first (pp_home_now).

Register use: every pp_* routine may clobber A, B, DPTR, PSW and R0-R7 (the stock routines
they replace do the same). RAM 0x48:0x49 (the COLOR tint) is only read. New state lives in
XDATA 0x0100..0x01F8.
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "patch"))
import features  # noqa: E402
from asm51 import Asm, hi8, lo8  # noqa: E402,F401
import uikit  # noqa: E402
import pfont  # noqa: E402
from uikit import (hi, lo, S, st_imm16, ld16, st16, LCD_SET_WINDOW, FONT_BIG,  # noqa: E402,F401
                   BIG_BUF, SMALL_BUF, NAME_Y, STATUS_Y, INPUT_NAMES, STOCK_SITES,
                   VOL_ENTRY_SITES, VOL_ENTRY_ORIG, vol_entry_bytes, VERSION_PTR_ADDR, VERSION_MAX_LEN)

BASE = "fast-lcd"                   # image this builds on (tools/patch/features.py)
INCLUDES = ["direct-select", "fix-auto-off", "strings", "start-volume", "fix-volume-pop",
            "fix-menu-input"]      # fix features linked into this image (auto-switch: not yet)
BASE_IMAGE = features.image(BASE)
BASE_SHA = "30c1e6fe785dc725037e5925d53f5b82305618037532b4a0cd7397a0774f560b"
OUT_IMAGE = os.path.join(HERE, "build", "flash_phosphor_panel.bin")
OUT_LISTING = os.path.join(HERE, "phosphor_panel.asm")
VERSION_TEXT = "v1.4 tbenr pp2"

CODE_ADDR = 0x9800                  # after fast-lcd (code 0x9700..0x977C, version string)

# ---- colours (RGB565) ---------------------------------------------------------------------------
MINT = uikit.rgb565(0x5A, 0xF5, 0xD8)       # #5af5d8: the phosphor on the White tint
RED_LIT = uikit.rgb565(0xFF, 0x5A, 0x48)    # #ff5a48: the muted icon, the MUTE lamp lit, no signal
RED_DARK = uikit.rgb565(0x2A, 0x0C, 0x09)   # #2a0c09: the MUTE lamp unlit
BLACK = 0
NLEV = 8                                    # brightness levels 0..7 (pp_ladder)
GHOST = 1                                   # the level of an unlit segment / bar cell / "dB"
LIT = 7


def ladder(ph):
    """The eight level colours for the phosphor ph, as pp_ladder computes them with uk_avg:
    7 ph, 6 3/4, 5 1/2, 4 3/8, 3 1/4, 2 3/16, 1 1/8, 0 black."""
    avg = pfont.avg565
    half = avg(ph, 0)
    quarter = avg(half, 0)
    eighth = avg(quarter, 0)
    return [0, eighth, avg(quarter, eighth), quarter, avg(half, quarter), half, avg(ph, half), ph]


def status_ink(ph):
    """The status line's colour with a signal: 7/8 ph (the mock's M(ph, bg, .15))."""
    return pfont.avg565(ph, ladder(ph)[6])


def marks_ink(ph):
    """The marks' colour: 5/8 ph (the mock's M(ghost, ph, .55))."""
    lad = ladder(ph)
    return pfont.avg565(lad[5], lad[6])


# ---- fonts --------------------------------------------------------------------------------------
NAME_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ .-"       # page-1 big text: input names, EQ preset names
ROW_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ.o dB"   # the row's lamps, VOL, dB, the marks
STATUS_CHARS = " !'-.0123456789ABCDEFGHIKLMNOPQRSTUVXabcdeghiklmnoprstuvwyz"   # every firmware string
NAME_SP = 3                                        # the mock's letter spacing of the name
GRID = 3                                           # the dot matrix: every GRIDth column and row black


def raster_font(label, rid, chars, where):
    if not os.path.exists(os.path.join(pfont.RASTER_DIR, rid + ".json")):
        raise SystemExit("font %s (%s) has no raster: open tools/fonts/raster.html?only=%s through "
                         "python3 tools/fonts/rasterize.py and press Save" % (rid, where, rid))
    return pfont.PFont(label, rid, chars, bpp=2)


def dot_matrix(pf, y_top, x_phase=1, spacing=NAME_SP):
    """Bake the mock's dot matrix into pf: every glyph's cell (advance + spacing) is padded to a
    multiple of GRID, and the pixels on the grid's black columns (screen x = 0 mod GRID, with the
    text starting at x = x_phase mod GRID) and rows (screen y = GRID - 1 mod GRID, the cell's top
    row at y_top) are cleared. Spacing is then 0 in uk_text. Each glyph is moved right by 0, 1 or
    2 px inside its cell to the position where the grid keeps the most ink (pp1 dropped the full
    column behind O's and C's faint anti-aliased edge: a cut-off look on the amp)."""
    for c, (adv, off, w, cols) in list(pf.glyphs.items()):
        adv2 = -(-(adv + spacing) // GRID) * GRID
        shift = max(range(GRID), key=lambda s: (sum(v for i, col in enumerate(cols) for v in col
                                                    if (x_phase + off + s + i) % GRID), -s))
        off += shift
        assert off + w <= adv2
        new = []
        for i, col in enumerate(cols):
            if (x_phase + off + i) % GRID == 0:
                new.append([0] * len(col))
            else:
                new.append([0 if (y_top + r) % GRID == GRID - 1 else v for r, v in enumerate(col)])
        pf.glyphs[c] = (adv2, off, w, new)
    pf.dotted = (y_top, x_phase)


PF_NAME = raster_font("pf_name", "disp54", NAME_CHARS, "the home name")
PF_ROW = raster_font("pf_row", "mono16", ROW_CHARS, "the row, VOL, dB, the marks")
PF_STATUS = raster_font("pf_status", "mono20", STATUS_CHARS, "the status line")
PF_ICON = raster_font("pf_icon", "icons16", "SMH", "the output icon")

# ---- layout -------------------------------------------------------------------------------------
# the row of lamps: baseline ROW_BASE; x, baseline -> the cell's top row y = baseline + the font's top
ROW_BASE = 23
ROW_TY = ROW_BASE + PF_ROW.top                      # the row texts' top row
ICON_X, ICON_Y = 12, ROW_BASE + PF_ICON.top
HVOL_X = 36                                         # the home volume
SLOT_X0, SLOT_X1 = ICON_X, 63                       # the icon and volume slot (black on the volume page)
SLOT_Y0 = min(ICON_Y, ROW_TY)
SLOT_Y1 = max(ICON_Y + PF_ICON.H, ROW_TY + PF_ROW.H) - 1
INP_X, INP_END = 72, 127                            # the input lamp's slot
FMT_X, FMT_END = 132, 187                           # the format lamp's slot
EQ_X, EQ_END = 192, 227                             # the EQ lamp's slot
MUTE_RIGHT = 308                                    # "MUTE", right-aligned
SHORT_NAMES = {1: "USB", 2: "OPT", 3: "COAX", 4: "BT", 5: "ARC", 6: "AUX", 8: "PHONO"}   # input 7: none
# the name: centred on x 160 at a start x of 1 mod GRID, baseline 104, dotted
HNAME_BASE = 104
HNAME_Y = HNAME_BASE + PF_NAME.top
dot_matrix(PF_NAME, HNAME_Y)
NAME_CX = 160
# the status line: centred, baseline 136
STAT_BASE = 136
STAT_Y = STAT_BASE + PF_STATUS.top
STAT_CX = 160
# the volume page
CELL_XS = [66, 110, 154, 198]                       # the four seven-segment cells (the mock's steps mode)
CELL_Y, CELL_W0, CELL_H, CELL_T, CELL_SKEW = 32, 30, 60, 6, 0.12
CELL_W = CELL_W0 + int(CELL_H * CELL_SKEW) + 1      # 38: the skew shifts the top row right
VOL_X, VOL_BASE = 18, 90                            # "VOL"
VOL_Y = VOL_BASE + PF_ROW.top
DB_X = 250                                          # "dB"
DB_W = PF_ROW.width("dB")
BAR_X0, BAR_PITCH, BAR_W, BAR_Y, BAR_H, BAR_N = 10, 6, 4, 118, 16, 50
MARK_BASE = 160
MARK_Y = MARK_BASE + PF_ROW.top
MARKS = [(str(v), int(BAR_X0 + v / 60 * 298 + 0.5)) for v in (0, 15, 30, 45, 60)]   # text, centre x
# the engine
RATE_RISE, RATE_FALL, RATE_GLOW = 2, 2, 4           # ticks per level (powers of 2: pp_move masks the tick)
SCAN_STEP = 3                                       # bar cells the entry's scan passes per tick
BLINK_ON, BLINK_PERIOD = 50, 90                     # muted: the digits lit for 50 ticks of 90
COUNT_EVERY = 2                                     # the counter steps every 2 ticks
EL_NAME, EL_VOL, EL_SEG, EL_BAR = 0, 1, 2, 30       # element indices (pp_lv): 28 segments, 50 bar cells
EL_N = EL_BAR + BAR_N
SEG_NAMES = "abcdefg"
SEGS = {0: "abcdef", 1: "bc", 2: "abdeg", 3: "abcdg", 4: "bcfg", 5: "acdfg", 6: "acdefg", 7: "abc",
        8: "abcdefg", 9: "abcdfg"}
SEG_TAB = [sum(1 << SEG_NAMES.index(s) for s in SEGS[d]) for d in range(10)]
BAR_LIT = [int(v * BAR_N / 60 + 0.5) for v in range(61)]    # the mock's Math.round(d / 60 * 50)
assert all(1 << (r.bit_length() - 1) == r for r in (RATE_RISE, RATE_FALL, RATE_GLOW)) and COUNT_EVERY == 2

assert ROW_TY + PF_ROW.H - 1 < CELL_Y and SLOT_Y1 < CELL_Y and ICON_Y >= 0
assert ICON_X + max(PF_ICON.width(c) for c in "SMH") - 1 < HVOL_X
assert HVOL_X + max(PF_ROW.width(str(v)) for v in range(61)) - 1 <= SLOT_X1 < INP_X
assert INP_X + max(PF_ROW.width(t) for t in SHORT_NAMES.values()) - 1 <= INP_END < FMT_X
assert FMT_X + PF_ROW.width("MQA.") - 1 <= FMT_END < EQ_X and EQ_X + PF_ROW.width("SDB") - 1 <= EQ_END
assert EQ_END < MUTE_RIGHT - PF_ROW.width("MUTE") + 1
assert STAT_Y + PF_STATUS.H <= MARK_Y and MARK_Y + PF_ROW.H <= 170           # the marks below the status
assert CELL_Y + CELL_H <= BAR_Y and BAR_Y + BAR_H <= MARK_Y                  # cells, bar, marks
assert VOL_Y >= CELL_Y and VOL_Y + PF_ROW.H <= BAR_Y and VOL_X + PF_ROW.width("VOL") < CELL_XS[0]
assert CELL_XS[3] + CELL_W < DB_X and DB_X + DB_W <= 320 and all(b - a >= CELL_W for a, b in zip(CELL_XS, CELL_XS[1:]))
assert BAR_X0 + (BAR_N - 1) * BAR_PITCH + BAR_W <= 320 and all(0 <= x - PF_ROW.width(t) // 2 and x + PF_ROW.width(t) // 2 < 320 for t, x in MARKS)
assert HNAME_Y + PF_NAME.H <= STAT_Y                                         # the name over the status
assert HNAME_Y <= CELL_Y + CELL_H - 1 and HNAME_Y + PF_NAME.H - 1 >= CELL_Y  # (they overlap: the engine's gate)
assert STAT_Y <= BAR_Y + BAR_H - 1 and STAT_Y + PF_STATUS.H - 1 >= BAR_Y     # (so does the status with the bar: cleared first)
assert SLOT_Y0 >= 0 and SLOT_X1 - SLOT_X0 + 1 <= 255 and EL_N <= 255
assert 0 <= PF_ROW.top + ROW_BASE and ROW_TY + PF_ROW.H - 1 <= SLOT_Y1


def name_x(width):
    """The name's start x as pp_name_x computes it: centred on NAME_CX, then moved left to 1 mod GRID
    (the dot matrix lines up with the screen grid), at least 1."""
    x = max(0, NAME_CX - width // 2)
    x -= (x + GRID - 1) % GRID
    return max(1, x)


def big_texts():
    """Every string the firmware can draw as big text at home (the input and EQ names: the
    capitalised strings of the stock string area), from the base image."""
    base = open(BASE_IMAGE, "rb").read()
    out, cur = [], b""
    for b in base[0x9040:0x9398]:
        if b == 0:
            t = cur.decode()
            if len(t) >= 2 and t == t.upper() and any(c.isalpha() for c in t):
                out.append(t)
            cur = b""
        elif 0x20 <= b < 0x7F:
            cur += bytes([b])
        else:
            cur = b""
    return sorted(set(out))


# the strings big_texts() finds include the RESET page's title and such, which the small font draws;
# the ones pf_name cannot spell lose those characters (uk_text skips them), the ones wider than the
# screen are clipped (and their right side is not cleared): neither is an input or EQ name
WIDE_TEXTS = [t for t in big_texts() if PF_NAME.width(t) > 318]
assert all(set(t) <= set(NAME_CHARS) and PF_NAME.width(t) <= 318 for _, _, t in INPUT_NAMES)
assert PF_STATUS.width("Digital input") < 320

# ---- the seven-segment cell map -----------------------------------------------------------------


def cell_polys():
    """The mock's seven segments of one cell, as polygons in cell coordinates (x right, y down,
    the cell's top-left at 0,0), skewed as drawVol does: X = x + (h - y) * skew."""
    w, h, t, skew = CELL_W0, CELL_H, CELL_T, CELL_SKEW

    def sk(pts):
        return [(x + (h - y) * skew, y) for x, y in pts]

    def hs(cx, cy, ln):
        return sk([(cx - ln / 2, cy), (cx - ln / 2 + t / 2, cy - t / 2), (cx + ln / 2 - t / 2, cy - t / 2),
                   (cx + ln / 2, cy), (cx + ln / 2 - t / 2, cy + t / 2), (cx - ln / 2 + t / 2, cy + t / 2)])

    def vs(cx, cy, ln):
        return sk([(cx, cy - ln / 2), (cx + t / 2, cy - ln / 2 + t / 2), (cx + t / 2, cy + ln / 2 - t / 2),
                   (cx, cy + ln / 2), (cx - t / 2, cy + ln / 2 - t / 2), (cx - t / 2, cy - ln / 2 + t / 2)])
    return {"a": hs(w / 2, t / 2, w - 3), "g": hs(w / 2, h / 2, w - 3), "d": hs(w / 2, h - t / 2, w - 3),
            "f": vs(t / 2, h / 4 + 1, h / 2 - 5), "b": vs(w - t / 2, h / 4 + 1, h / 2 - 5),
            "e": vs(t / 2, 3 * h / 4 - 1, h / 2 - 5), "c": vs(w - t / 2, 3 * h / 4 - 1, h / 2 - 5)}


def inside(poly, x, y):
    n, c = len(poly), False
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def cell_grid(ss=4):
    """[column][row] -> (segment index 0..6 or 7, coverage level 0..3) of the cell, from ss x ss
    samples per pixel (the segment with the most samples wins; the level as pfont quantises it)."""
    polys = cell_polys()
    grid = []
    for x in range(CELL_W):
        col = []
        for y in range(CELL_H):
            counts = [0] * 7
            for i in range(ss):
                for j in range(ss):
                    px, py = x + (i + 0.5) / ss, y + (j + 0.5) / ss
                    for s, name in enumerate(SEG_NAMES):
                        if inside(polys[name], px, py):
                            counts[s] += 1
                            break
            best = max(range(7), key=lambda s: counts[s])
            lv = pfont.level(round(counts[best] * 15 / (ss * ss)), 2)
            col.append((best, lv) if lv else (7, 0))
        grid.append(col)
    return grid


def cell_runs(grid):
    """The map as pp_cell streams it: column-major runs (value, length 1..255), value = segment * 4 +
    level (28 = background), then 0xFF."""
    stream = [s * 4 + lv for col in grid for s, lv in col]
    out, i = [], 0
    while i < len(stream):
        j = i
        while j < len(stream) and stream[j] == stream[i] and j - i < 255:
            j += 1
        out += [stream[i], j - i]
        i = j
    return out + [0xFF]


CELL_GRID = cell_grid()
CELL_MAP = cell_runs(CELL_GRID)
assert all(0 <= v <= 28 for v in CELL_MAP[0:-1:2]) and sum(CELL_MAP[1:-1:2]) == CELL_W * CELL_H
assert {s for col in CELL_GRID for s, _ in col} == set(range(8))     # every segment, and background


def cell_pixels(levels, ph, x0):
    """{(x, y): colour} of a cell at x0 whose seven segments are at `levels` (0..7), in the
    phosphor ph, as pp_cell paints it: each segment's colour from the ladder, its coverage
    ramp from pfont.ramp (uk_avg's halves)."""
    lad = ladder(ph)
    ramps = [pfont.ramp(lad[lv], 0) for lv in levels]
    out = {}
    for x in range(CELL_W):
        for y in range(CELL_H):
            s, lv = CELL_GRID[x][y]
            out[(x0 + x, CELL_Y + y)] = ramps[s][lv] if s < 7 else 0
    return out


class CellMap:
    """The map as a data item for the hole / the code (like a PFont: name, size(), emit())."""
    name = "pp_cellmap"
    font = "the seven-segment cell map"

    def size(self):
        return len(CELL_MAP)

    def emit(self, a):
        a.comment("pp_cellmap: the %d x %d seven-segment cell, column-major runs (segment * 4 + level, "
                  "length), 28 = background, 0xFF ends; %d bytes" % (CELL_W, CELL_H, len(CELL_MAP)))
        a.L(self.name)
        for k in range(0, len(CELL_MAP), 16):
            a.data("db " + ",".join("0x%02X" % v for v in CELL_MAP[k:k + 16]), CELL_MAP[k:k + 16])


PF_MAP = CellMap()
PFONTS = (PF_NAME, PF_ROW, PF_STATUS, PF_ICON, PF_MAP)

# The stock big font (font_big, 0x6A23..0x7DD3) is dead in this image: big_text_render hands every
# big text to pp_name (hook 0x2A25) and the stock number painters are unreachable, so no code reads
# its 5040 bytes (emu_test.py traps big_glyph_paint and bignum_digit on every run). The data that
# fills it best lives there; the rest stays in the code area.
FONT_HOLE, FONT_HOLE_END = uikit.FONT_BIG, 0x7DD3
FONT_HOLE_SHA = "e082a9f85587aa8e71b9ef1a7b425ca0531b64d296f557d535f2ab42e87b6c87"   # the stock glyphs


def hole_fonts(fonts, room):
    """The subset of fonts with the most bytes that fits in room (fewest fonts on a tie)."""
    best = ()
    for mask in range(1, 1 << len(fonts)):
        sub = tuple(f for k, f in enumerate(fonts) if mask >> k & 1)
        size = sum(f.size() for f in sub)
        if size <= room and (size, -len(sub)) > (sum(f.size() for f in best), -len(best)):
            best = sub
    return best


HOLE_FONTS = hole_fonts(PFONTS, FONT_HOLE_END - FONT_HOLE)
CODE_FONTS = tuple(f for f in PFONTS if f not in HOLE_FONTS)

# ---- XDATA --------------------------------------------------------------------------------------
PP_N = 0x0100                       # uk_fill's work area (4 bytes)
TP_BASE = 0x0104                    # uk_text's parameter block and work area (55 bytes)
PP_VOL = 0x013B                     # the volume (0..60), as volpage_draw_volume / home_draw_volume get it
PP_SHOW = 0x013C                    # the counter: the number shown (0..60)
PP_ST = 0x013D                      # 0 home, 1 entering the volume page, 2 the volume page, 3 exiting
PP_ACT = 0x013E                     # the engine runs (1) on ticks
PP_TICK = 0x013F                    # tick counter (wraps)
PP_BLINK = 0x0140                   # muted: blink phase 0..89
PP_FL = 0x0141                      # bit 1: "dB" shown; bit 2: the slot and the status line cleared and the
                                    # marks shown (the volume statics); bit 3: the status line drawn (pp_status_draw)
PP_SCAN = 0x0142                    # entry: bar cells the scan has passed (0..50)
PP_SIG = 0x0143                     # bit 0: the status loader's signal check found a signal; bit 1: the next
                                    # page-1 draw at y 135 is the loader's text (pp_hold -> pp_status)
PP_SBUF = 0x0144                    # exit: the stock refresh has loaded the status buffer
PP_INT = 0x0145                     # step: 1 while the volume page is wanted (PP_ST 1 or 2)
PP_MOV = 0x0146                     # step: 1 while some element is off its target
PP_DIRTY = 0x0147                   # step: cells to repaint (bits 0..3)
PP_LV = 0x0148                      # EL_N bytes: target << 4 | level of every faded element
PP_LAD = PP_LV + EL_N               # the ladder: 8 colours (0x0198)
PP_PAL = PP_LAD + 2 * NLEV          # pp_cell's palette: 32 colours, segment * 4 + coverage (0x01A8)
PP_VS = PP_PAL + 64                 # the home volume as text (2 digits and a NUL) (0x01E8)
PP_TAG = PP_VS + 3                  # a tag's text, trailing spaces cut (5 characters and a NUL)
PP_NX = PP_TAG + 6                  # the name's start x (hi, lo)
PP_NW = PP_NX + 2                   # the name's width (hi, lo)
PP_I = PP_NW + 2                    # pp_move: the element index; pp_cell: the cell
PP_T = PP_I + 1                     # scratch (3 bytes): pp_retarget's masks and limits
XDATA_END = PP_T + 3
assert XDATA_END <= 0x0200 and (TP_BASE & 0xFF) + uikit.Kit.TP_SIZE <= 0x100 and TP_BASE + uikit.Kit.TP_SIZE <= PP_VOL
KIT = uikit.Kit(fill_ws=PP_N, fp_base=0x0300, tp_base=TP_BASE)   # uk_paint is not linked: its block is unused
XDATA = [(0x0100, XDATA_END, "phosphor-panel variables, uikit fill/TP blocks")]
FL_DB, FL_VOL, FL_SLOT = 2, 4, 8

# ---- hooks --------------------------------------------------------------------------------------
HOOKS = [STOCK_SITES[site] + (op, target) for site, op, target in (
    ("page_clear", 0x12, "pp_clear"),
    ("page2_entry", 0x02, "pp_volpage"),
    ("volpage_draw_volume", 0x02, "pp_draw_volume"),
    ("big_text_start_x", 0x02, "pp_name"),        # every big text is the theme's: the stock big font is never read
    ("small_text_start_x", 0x02, "pp_align_small"),
    ("tick", 0x12, "uk_tasks"),
    ("home_refresh_periodic", 0x02, "pp_hold"),
    ("ui_clear_screen", 0x02, "pp_cancel"),
    ("home_draw_input_name", 0x02, "pp_name_guard"),
    ("home_refresh_flag_path", 0x02, "pp_flag_path"),
    ("status_signal_check", 0x12, "pp_signal"),
    ("home_draw_output_icon", 0x02, "pp_icon"),
    ("home_draw_volume", 0x02, "pp_hvol"),
    ("eq_tag_paint", 0x02, "pp_eq"),
    ("format_tag_paint", 0x12, "pp_fmt"),
    ("format_tag_clear", 0x02, "pp_fmt_clear"),
    ("format_tag_clear_changed", 0x12, "pp_fmt_clear"),
)]
# the mute key: its handler, and read_key's page-2 filter so the key reaches it on the open volume page
MUTE_KEY_SITE = (0x1047, bytes([0xE5, 0x45, 0x64]))     # key_1c: mov A,0x45 ; xrl A,#1 (the handler up to 0x106C)
KEY_P2_SITE = (0x3DD1, bytes([0xEB, 0x64, 0x1F]))       # read_key, IR, page 2: mov A,R3 ; xrl A,#0x1F
HOOKS += [MUTE_KEY_SITE + (0x02, "pp_mute_key"), KEY_P2_SITE + (0x02, "pp_key_p2")]
HOOKS += features.hooks(INCLUDES)
FIX_PATCHES = features.patches(INCLUDES)

rect = KIT.rect
tp_setup = KIT.tp_setup


def lv_addr(a):
    """DPTR = PP_LV + A."""
    S(a, "add A,%s\nmov DPL,A\nclr A\naddc A,%s\nmov DPH,A" % (lo(PP_LV), hi(PP_LV)))


# ---------------------------------------------------------------------------------------------
def build_data(a):
    a.comment("the four cells' x")
    a.L("cell_xs")
    for x in CELL_XS:
        a.data("dw %d" % x, [x >> 8, x & 0xFF])
    a.comment("bar cells lit per volume 0..60: round(50 v / 60)")
    a.L("bar_tab")
    for k in range(0, 61, 16):
        a.data("db " + ",".join("%d" % v for v in BAR_LIT[k:k + 16]), BAR_LIT[k:k + 16])
    a.comment("lit segments per digit: bit 0 a .. bit 6 g")
    a.L("seg_tab")
    a.data("db " + ",".join("0x%02X" % v for v in SEG_TAB), SEG_TAB)
    a.comment("the input lamps' strings for inputs 1..8 (7: empty), then their pointers")
    for inp in range(1, 9):
        t = SHORT_NAMES.get(inp, "")
        a.L("sn_%d" % inp)
        a.data('db "%s",0' % t, t.encode() + b"\0")
    a.L("sn_tab")
    for inp in range(1, 9):
        a.i("dw sn_%d" % inp, hi8("sn_%d" % inp), lo8("sn_%d" % inp))
    a.comment("home_draw_input_name's strings for inputs 1..8 (0: none, the buffer is drawn as it is)")
    a.L("names8")
    tab = {inp: addr for inp, addr, _ in INPUT_NAMES}
    for inp in range(1, 9):
        v = tab.get(inp, 0)
        a.data("dw 0x%04X          ; input %d" % (v, inp), [v >> 8, v & 0xFF])
    for lab, text in (("str_vol", "VOL"), ("str_db", "dB"), ("str_mute", "MUTE"),
                      ("str_spk", "S"), ("str_mspk", "M"), ("str_hp", "H")):
        a.L(lab)
        a.data('db "%s",0' % text, text.encode() + b"\0")
    a.comment("the marks: text, then centre x")
    for k, (t, x) in enumerate(MARKS):
        a.L("mk_%d" % k)
        a.data('db "%s",0' % t, t.encode() + b"\0")
    a.L("mk_tab")
    for k, (t, x) in enumerate(MARKS):
        a.i("dw mk_%d" % k, hi8("mk_%d" % k), lo8("mk_%d" % k))
        a.data("dw %d" % x, [x >> 8, x & 0xFF])
    for f in CODE_FONTS:
        f.emit(a)


def build_primitives(a):
    KIT.emit_fill(a)
    KIT.emit_accent(a, MINT)
    assert all(f.bpp == 2 for f in PFONTS if isinstance(f, pfont.PFont))
    KIT.emit_text(a, one_bit=False)     # uk_text only (run-length fonts): nothing here draws with the stock fonts
    S(a, """
; pp_ladder: the eight level colours of the phosphor (uk_acc) into PP_LAD: 7 ph, 5 1/2, 3 1/4, 1 1/8
; (halves of halves), 6, 4, 2 the averages between them, 0 black
pp_ladder:
lcall uk_acc
mov A,#7
lcall pl_st        ; L7 = ph
mov R4,#0
mov R5,#0
lcall pl_half      ; R6:R7 = half, R2:R3 = ph
mov A,#5
lcall pl_st
mov A,R6
mov R4,A
mov A,R7
mov R5,A
lcall uk_avg       ; avg(ph, half)
mov A,#6
lcall pl_st
mov A,R4
mov R2,A
mov A,R5
mov R3,A           ; R2:R3 = half
mov R4,#0
mov R5,#0
lcall uk_avg       ; quarter
mov A,#3
lcall pl_st
mov A,R6
mov R4,A
mov A,R7
mov R5,A
lcall uk_avg       ; avg(half, quarter)
mov A,#4
lcall pl_st
mov A,R4
mov R2,A
mov A,R5
mov R3,A           ; R2:R3 = quarter
mov R4,#0
mov R5,#0
lcall uk_avg       ; eighth
mov A,#1
lcall pl_st
mov A,R6
mov R4,A
mov A,R7
mov R5,A
lcall uk_avg       ; avg(quarter, eighth)
mov A,#2
lcall pl_st
mov R6,#0
mov R7,#0
clr A
; pl_st: PP_LAD[A] = R6:R7; keeps R2..R7
pl_st:
rl A
add A,%s""" % lo(PP_LAD) + """
mov DPL,A
clr A
addc A,%s""" % hi(PP_LAD) + """
mov DPH,A
mov A,R6
movx @DPTR,A
inc DPTR
mov A,R7
movx @DPTR,A
ret
; pl_half: R2:R3 = R6:R7, then R6:R7 = avg(R2:R3, R4:R5)
pl_half:
mov A,R6
mov R2,A
mov A,R7
mov R3,A
ljmp uk_avg

; pp_lad_ld: R6:R7 = PP_LAD[A] (A a level 0..7); keeps R0..R5
pp_lad_ld:
rl A
add A,%s""" % lo(PP_LAD) + """
mov DPL,A
clr A
addc A,%s""" % hi(PP_LAD) + """
mov DPH,A
movx A,@DPTR
mov R6,A
inc DPTR
movx A,@DPTR
mov R7,A
ret

; pp_dec2: A (0..99) as decimal text at DPTR, no leading zero, then a NUL
pp_dec2:
mov B,#10
div AB             ; A tens, B ones
jz pd_one
add A,#0x30
movx @DPTR,A
inc DPTR
pd_one:
mov A,B
add A,#0x30
movx @DPTR,A
inc DPTR
clr A
movx @DPTR,A
ret

; pp_rest: black from TP_END + 1 to R6:R7 (the last column), rows R5 .. R5 + R4 - 1: the rest of a
; slot after a shorter text (at most 255 columns)
pp_rest:
mov DPTR,#0x%04X""" % KIT.TP["END"] + """
movx A,@DPTR
mov R2,A
inc DPTR
movx A,@DPTR
add A,#1
mov R3,A
clr A
addc A,R2
mov R2,A           ; x = TP_END + 1
mov A,R7
clr C
subb A,R3
mov R1,A
mov A,R6
subb A,R2
jc pr_ret          ; x > limit
jnz pr_wide
mov A,R1
inc A
jz pr_wide
mov R1,A
sjmp pr_go
pr_wide:
mov R1,#255
pr_go:
mov R6,#0
mov R7,#0
ljmp uk_fill
pr_ret:
ret

; pp_name_x: PP_NW = the name's width (XDATA 0x35 in pf_name, measured), PP_NX = its start x:
; centred on %d, then left to 1 mod %d (the dot matrix lines up with the screen grid), at least 1
pp_name_x:""" % (NAME_CX, GRID))
    tp_setup(a, "pf_name", BIG_BUF, 0, 0, HNAME_Y, 0, clip=(0x100, 0))
    S(a, """
lcall uk_text      ; TP_END = width - 1
mov DPTR,#0x%04X""" % KIT.TP["END"] + """
movx A,@DPTR
mov R2,A
inc DPTR
movx A,@DPTR
add A,#1
mov R3,A
clr A
addc A,R2
mov R2,A           ; R2:R3 = width
mov DPTR,#0x%04X""" % PP_NW + """
mov A,R2
movx @DPTR,A
inc DPTR
mov A,R3
movx @DPTR,A
clr C
mov A,R2
rrc A
mov R2,A
mov A,R3
rrc A
mov R3,A           ; width / 2
mov A,R2
jnz pnx_one        ; 512 px or more: x 1
mov A,#%d""" % NAME_CX + """
clr C
subb A,R3          ; x = NAME_CX - width / 2
jc pnx_one         ; wider than the screen: x 1
jz pnx_one
mov R4,A
mov B,#%d""" % GRID + """
div AB             ; B = x mod GRID: 1 -> as it is, 2 -> x - 1, 0 -> x - 2
mov A,B
jz pnx_m0
dec A
jz pnx_keep
mov A,R4
dec A
sjmp pnx_st
pnx_m0:
mov A,R4
dec A
dec A
sjmp pnx_st
pnx_keep:
mov A,R4
pnx_st:
jz pnx_one
sjmp pnx_w
pnx_one:
mov A,#1
pnx_w:
mov DPTR,#0x%04X""" % (PP_NX + 1) + """
movx @DPTR,A
mov DPTR,#0x%04X""" % PP_NX + """
clr A
movx @DPTR,A
ret
""")


def build_painters(a):
    # ---- the name
    S(a, "; pp_name_lv: the name (XDATA 0x35) in pf_name at PP_NX, baseline %d, in the ladder's level A\npp_name_lv:"
         % HNAME_BASE)
    S(a, "lcall pp_lad_ld")
    tp_setup(a, "pf_name", BIG_BUF, 0, None, HNAME_Y, 0)
    st16(a, KIT.TP["INK"], "R6", "R7")
    ld16(a, "R2", "R3", PP_NX)
    st16(a, KIT.TP["X"], "R2", "R3")
    S(a, "ljmp uk_text")
    S(a, """
; pp_name: big_text_render's hook (0x2A25): every big text is drawn here as the home name (in
; practice only the input name, the EQ preset name and the output name at y 75 on page 1 reach it,
; so the stock big font is never read). During an exit the whole home comes first (pp_busy_home).
; The name at full brightness, centred (pp_name_x), the rest of its rows black on both sides, the
; element at level 7 = target; then the input lamp and the format lamp. Returns from the stock
; renderer (nothing is pushed at the hook).
pp_name:
lcall pp_busy_home
lcall pp_ladder    ; (the engine computes it per tick; a stock draw may come first, or after a COLOR change)
lcall pp_name_x
mov DPTR,#0x%04X""" % (PP_LV + EL_NAME) + """
mov A,#0x77
movx @DPTR,A
; left: x 0 .. NX - 1
mov DPTR,#0x%04X""" % (PP_NX + 1) + """
movx A,@DPTR
mov R1,A
mov R2,#0
mov R3,#0
mov R5,#%d""" % HNAME_Y + """
mov R4,#%d""" % PF_NAME.H + """
mov R6,#0
mov R7,#0
lcall uk_fill
; right: x NX + W .. 319
mov DPTR,#0x%04X""" % (PP_NX + 1) + """
movx A,@DPTR
mov R3,A
mov DPTR,#0x%04X""" % (PP_NW + 1) + """
movx A,@DPTR
add A,R3
mov R3,A
mov DPTR,#0x%04X""" % PP_NW + """
movx A,@DPTR
addc A,#0
mov R2,A           ; R2:R3 = NX + W
mov A,#0x40
clr C
subb A,R3
mov R1,A
mov A,#1
subb A,R2
jc pn_draw         ; past the screen: nothing to clear
jnz pn_draw        ; (cannot be 256 wide or more)
mov A,R1
jz pn_draw
mov R5,#%d""" % HNAME_Y + """
mov R4,#%d""" % PF_NAME.H + """
mov R6,#0
mov R7,#0
lcall uk_fill
pn_draw:
mov A,#7
lcall pp_name_lv
; pp_inp: the input lamp: SHORT_NAMES[0x47] in pf_row at x %d, the rest of the slot (to %d) black
pp_inp:""" % (INP_X, INP_END) + """
mov A,0x47
dec A
cjne A,#8,pi_c
pi_c:
jc pi_ok
mov A,#6           ; out of range: input 7's empty string
pi_ok:
rl A
mov R1,A
mov DPTR,#sn_tab
movc A,@A+DPTR
mov R2,A
mov A,R1
inc A
movc A,@A+DPTR
mov R3,A""")
    tp_setup(a, "pf_row", None, 1, INP_X, ROW_TY, "acc")
    st16(a, KIT.TP["STR"], "R2", "R3")
    S(a, "lcall uk_text\nmov R6,%s\nmov R7,%s\nmov R5,#%d\nmov R4,#%d\nlcall pp_rest"
         % (hi(INP_END), lo(INP_END), ROW_TY, PF_ROW.H))
    S(a, "; then the format lamp as the stock home_draw_format_tag decides it (through pp_fmt / pp_fmt_clear): the\n"
         "; stock sequences redraw the name at an input change at once but the tags only at the next refresh,\n"
         "; and the row stays on screen across the volume page\n"
         "ljmp 0x41CA")
    # ---- the status line
    S(a, """
; pp_status: small_text_render's hand-over on page 1 at y 135 (hook 0x3A82 -> pp_align_small). During an
; exit the whole home comes first. The red tint belongs to the text the status loader decided with
; its signal check (PP_SIG bit 0 clear); only the periodic refresh's own draw shows that text
; (pp_hold marks it: PP_SIG bit 1). Every other caller has put its own text into XDATA 0x50
; (input_apply's placeholder, the BT key, eq_show): lit, PP_SIG 1, until the loader runs again.
pp_status:
lcall pp_busy_home
mov DPTR,#0x%04X""" % PP_SIG + """
movx A,@DPTR
jb ACC.1,ps_loader
mov A,#1
ps_loader:
anl A,#1
movx @DPTR,A
; pp_status_draw: the status line (XDATA 0x50) in pf_status centred on x %d, baseline %d, 7/8 of the
; phosphor (red without a signal on a digital input: 0x47 not 6 or 8), the rest of its rows black
pp_status_draw:""" % (STAT_CX, STAT_BASE))
    S(a, "mov DPTR,#0x%04X\nmovx A,@DPTR\norl A,#%d\nmovx @DPTR,A" % (PP_FL, FL_SLOT))
    tp_setup(a, "pf_status", SMALL_BUF, 0, STAT_CX, STAT_Y, RED_LIT, align=2)
    S(a, """
mov DPTR,#0x%04X""" % PP_SIG + """
movx A,@DPTR
jb ACC.0,psd_lit
mov A,0x47
cjne A,#6,psd_n6
sjmp psd_lit
psd_n6:
cjne A,#8,psd_go   ; no signal on a digital input: red
psd_lit:
lcall pp_stat_ink""")
    st16(a, KIT.TP["INK"], "R6", "R7")
    S(a, """
psd_go:
lcall uk_text      ; TP_X = the first column, TP_END the last
mov DPTR,#0x%04X""" % (KIT.TP["X"] + 1) + """
movx A,@DPTR
mov R1,A           ; the first column (at most 160)
jz psd_right
mov R2,#0
mov R3,#0
mov R5,#%d""" % STAT_Y + """
mov R4,#%d""" % PF_STATUS.H + """
mov R6,#0
mov R7,#0
lcall uk_fill
psd_right:
mov R6,#1
mov R7,#0x3F
mov R5,#%d""" % STAT_Y + """
mov R4,#%d""" % PF_STATUS.H + """
ljmp pp_rest

; pp_stat_ink: R6:R7 = 7/8 of the phosphor: avg(ph, avg(ph, half))
pp_stat_ink:
lcall uk_acc
mov R4,#0
mov R5,#0
lcall pl_half      ; R6:R7 = half, R2:R3 = ph
mov A,R6
mov R4,A
mov A,R7
mov R5,A
lcall uk_avg       ; 3/4
mov A,R6
mov R4,A
mov A,R7
mov R5,A
ljmp uk_avg        ; 7/8
""")
    # ---- the row
    S(a, """
; pp_icon: replaces home_draw_output_icon 0x5744: the speaker (red with an X when muted, 0x22.1)
; or headphones (g_output 0x2B not 1) at %d, baseline %d, the rest up to x %d black; then the MUTE
; lamp. XDATA 6 = the stock icon number, as stock.
pp_icon:""" % (ICON_X, ROW_BASE, HVOL_X - 1) + """
mov R0,#6
jnb 0x22.1,pic_on
mov A,#1
movx @R0,A""")
    tp_setup(a, "pf_icon", "str_mspk", 1, ICON_X, ICON_Y, RED_LIT)
    S(a, "ljmp pic_draw\npic_on:\nmov A,0x2B\nxrl A,#1\njz pic_spk\nmov A,#2\nmovx @R0,A")
    tp_setup(a, "pf_icon", "str_hp", 1, ICON_X, ICON_Y, "acc")
    S(a, "ljmp pic_draw\npic_spk:\nmov A,#3\nmovx @R0,A")
    tp_setup(a, "pf_icon", "str_spk", 1, ICON_X, ICON_Y, "acc")
    S(a, "pic_draw:\nlcall uk_text\nmov R6,%s\nmov R7,%s\nmov R5,#%d\nmov R4,#%d\nlcall pp_rest"
         % (hi(HVOL_X - 1), lo(HVOL_X - 1), ICON_Y, PF_ICON.H))
    S(a, "; pp_lamp: \"MUTE\" right-aligned to x %d, baseline %d: red when muted, dark red otherwise\npp_lamp:"
         % (MUTE_RIGHT, ROW_BASE))
    tp_setup(a, "pf_row", "str_mute", 1, MUTE_RIGHT, ROW_TY, RED_DARK, align=1)
    S(a, "jnb 0x22.1,pla_go")
    st_imm16(a, KIT.TP["INK"], RED_LIT)
    S(a, "pla_go:\nljmp uk_text")
    S(a, """
; pp_hvol: replaces home_draw_volume 0x5916 (R7 speaker volume; the headphone volume 0x52 when
; g_output is not 1): no leading zero, in the phosphor at x %d, baseline %d, the rest of the slot
; black. With the engine idle (PP_ST 0) the counter and the volume follow it.
pp_hvol:""" % (HVOL_X, ROW_BASE) + """
mov A,0x2B
xrl A,#1
jz phv_spk
mov R7,0x52
phv_spk:
mov R0,#5
mov A,#2
movx @R0,A         ; XDATA 5 = 2, as stock
mov A,R7
cjne A,#61,phv_c
phv_c:
jc phv_ok
mov A,#60
phv_ok:
mov R7,A
mov DPTR,#0x%04X""" % PP_ST + """
movx A,@DPTR
jnz phv_txt
mov DPTR,#0x%04X""" % PP_VOL + """
mov A,R7
movx @DPTR,A
inc DPTR
movx @DPTR,A       ; PP_SHOW
phv_txt:
mov A,R7
mov DPTR,#0x%04X""" % PP_VS + """
lcall pp_dec2""")
    tp_setup(a, "pf_row", PP_VS, 0, HVOL_X, ROW_TY, "acc")
    S(a, "lcall uk_text\nmov R6,%s\nmov R7,%s\nmov R5,#%d\nmov R4,#%d\nljmp pp_rest"
         % (hi(SLOT_X1), lo(SLOT_X1), ROW_TY, PF_ROW.H))
    S(a, """
; pp_eq: replaces the EQ tag's paint 0x4F18 (string R3:R2:R1): the lamp at x %d, the slot to %d
pp_eq:""" % (EQ_X, EQ_END) + """
lcall pp_tag_copy
mov R6,%s""" % hi(EQ_END) + """
mov R7,%s""" % lo(EQ_END) + """
mov R2,%s""" % hi(EQ_X) + """
mov R3,%s""" % lo(EQ_X) + """
sjmp pp_lamp_at
; pp_fmt: replaces home_draw_format_tag's lcall 0x4F20 (string R3:R2:R1): the lamp at x %d, the slot to %d
pp_fmt:""" % (FMT_X, FMT_END) + """
lcall pp_tag_copy
mov R6,%s""" % hi(FMT_END) + """
mov R7,%s""" % lo(FMT_END) + """
mov R2,%s""" % hi(FMT_X) + """
mov R3,%s""" % lo(FMT_X) + """
; pp_lamp_at: PP_TAG in pf_row at R2:R3, baseline %d, in the phosphor; the rest of the slot (to R6:R7) black
pp_lamp_at:""" % ROW_BASE + """
push 0x06
push 0x07""")
    tp_setup(a, "pf_row", PP_TAG, 0, None, ROW_TY, "acc")
    st16(a, KIT.TP["X"], "R2", "R3")
    S(a, "lcall uk_text\npop 0x07\npop 0x06\nmov R5,#%d\nmov R4,#%d\nljmp pp_rest" % (ROW_TY, PF_ROW.H))
    S(a, """
; pp_tag_copy: PP_TAG = the string at R3:R2:R1 (R3 0xFF: code, else XDATA), at most 5 characters,
; trailing spaces cut
pp_tag_copy:
mov DPH,R2
mov DPL,R1
mov R4,#0          ; characters copied
mov R5,#0          ; length up to the last non-space
ptc_loop:
cjne R3,#0xFF,ptc_x
clr A
movc A,@A+DPTR
sjmp ptc_got
ptc_x:
movx A,@DPTR
ptc_got:
jz ptc_end
inc DPTR
mov R6,A
push DPH
push DPL
mov A,R4
add A,%s""" % lo(PP_TAG) + """
mov DPL,A
clr A
addc A,%s""" % hi(PP_TAG) + """
mov DPH,A
mov A,R6
movx @DPTR,A
pop DPL
pop DPH
inc R4
cjne R6,#0x20,ptc_ns
sjmp ptc_sp
ptc_ns:
mov A,R4
mov R5,A
ptc_sp:
cjne R4,#5,ptc_loop
ptc_end:
mov A,R5
add A,%s""" % lo(PP_TAG) + """
mov DPL,A
clr A
addc A,%s""" % hi(PP_TAG) + """
mov DPH,A
clr A
movx @DPTR,A
ret

; pp_fmt_clear: replaces home_draw_format_tag's clears (0x0026): the format lamp's slot, black
pp_fmt_clear:""")
    rect(a, FMT_X, FMT_END - FMT_X + 1, ROW_TY, PF_ROW.H, 0)
    S(a, "ljmp uk_fill")
    S(a, "; pp_slot_clear: the icon and volume slot, black\npp_slot_clear:")
    rect(a, SLOT_X0, SLOT_X1 - SLOT_X0 + 1, SLOT_Y0, SLOT_Y1 - SLOT_Y0 + 1, 0)
    S(a, "ljmp uk_fill")
    S(a, "; pp_slot_draw: the icon (and the MUTE lamp) and the volume, as the stock home draws them\npp_slot_draw:\n"
         "lcall pp_icon\nmov R7,0x31\nljmp pp_hvol")
    S(a, "; pp_stat_clear: the status line's rows, black (two fills)\npp_stat_clear:")
    rect(a, 0, 160, STAT_Y, PF_STATUS.H, 0)
    S(a, "lcall uk_fill")
    rect(a, 160, 160, STAT_Y, PF_STATUS.H, 0)
    S(a, "ljmp uk_fill")
    # ---- the volume page's texts
    S(a, "; pp_vol_lv: \"VOL\" at %d, baseline %d, in the ladder's level A\npp_vol_lv:\nlcall pp_lad_ld" % (VOL_X, VOL_BASE))
    tp_setup(a, "pf_row", "str_vol", 1, VOL_X, VOL_Y, 0)
    st16(a, KIT.TP["INK"], "R6", "R7")
    S(a, "ljmp uk_text")
    S(a, "; pp_db: \"dB\" at %d, baseline %d, a ghost (level %d)\npp_db:\nmov A,#%d\nlcall pp_lad_ld" % (DB_X, VOL_BASE, GHOST, GHOST))
    tp_setup(a, "pf_row", "str_db", 1, DB_X, VOL_Y, 0)
    st16(a, KIT.TP["INK"], "R6", "R7")
    S(a, "ljmp uk_text")
    S(a, "; pp_db_clear: \"dB\"'s cell, black\npp_db_clear:")
    rect(a, DB_X, DB_W, VOL_Y, PF_ROW.H, 0)
    S(a, "ljmp uk_fill")
    S(a, "; pp_marks: \"0 15 30 45 60\" centred under the bar at baseline %d, 5/8 of the phosphor\npp_marks:" % MARK_BASE)
    S(a, "mov A,#5\nlcall pp_lad_ld\nmov A,R6\nmov R2,A\nmov A,R7\nmov R3,A\nmov A,#6\nlcall pp_lad_ld\n"
         "mov A,R6\nmov R4,A\nmov A,R7\nmov R5,A\nlcall uk_avg")
    tp_setup(a, "pf_row", None, 1, None, MARK_Y, 0, align=2)
    st16(a, KIT.TP["INK"], "R6", "R7")
    S(a, "mov R0,#0\npmk_loop:\nmov A,R0\nmov DPTR,#mk_tab\nmovc A,@A+DPTR\nmov R2,A\nmov A,R0\ninc A\nmovc A,@A+DPTR\nmov R3,A\n"
         "mov A,R0\nadd A,#2\nmovc A,@A+DPTR\nmov R4,A\nmov A,R0\nadd A,#3\nmovc A,@A+DPTR\nmov R5,A\npush 0x00")
    st16(a, KIT.TP["STR"], "R2", "R3")
    st16(a, KIT.TP["X"], "R4", "R5")
    S(a, "lcall uk_text\npop 0x00\nmov A,R0\nadd A,#4\nmov R0,A\ncjne R0,#%d,pmk_loop\nret" % (4 * len(MARKS)))
    S(a, "; pp_marks_clear: the marks' rows, black (two fills)\npp_marks_clear:")
    rect(a, 0, 160, MARK_Y, PF_ROW.H, 0)
    S(a, "lcall uk_fill")
    rect(a, 160, 160, MARK_Y, PF_ROW.H, 0)
    S(a, "ljmp uk_fill")
    # ---- the bar and the cells
    S(a, """
; pp_bar: bar cell A (0..%d), %d x %d at x %d + %d A, y %d, in the colour R6:R7
pp_bar:""" % (BAR_N - 1, BAR_W, BAR_H, BAR_X0, BAR_PITCH, BAR_Y) + """
mov B,#%d""" % BAR_PITCH + """
mul AB
add A,#%d""" % BAR_X0 + """
mov R3,A
mov A,B
addc A,#0
mov R2,A
mov R1,#%d""" % BAR_W + """
mov R5,#%d""" % BAR_Y + """
mov R4,#%d""" % BAR_H + """
ljmp uk_fill

; pp_cell: cell A (0..3) at cell_xs[A], rows %d..%d: the seven segments at their levels (PP_LV), each
; in its ladder colour with the coverage ramp 1/4, 3/4, 1 (uk_avg), the rest black; the map
; pp_cellmap streamed through the palette PP_PAL (segment * 4 + coverage)
pp_cell:""" % (CELL_Y, CELL_Y + CELL_H - 1) + """
mov DPTR,#0x%04X""" % PP_I + """
movx @DPTR,A
mov R0,#0          ; the segment
pcl_seg:
mov DPTR,#0x%04X""" % PP_I + """
movx A,@DPTR
mov B,#7
mul AB
add A,R0
add A,#%d""" % EL_SEG)
    lv_addr(a)
    S(a, """
movx A,@DPTR
anl A,#7
lcall pp_lad_ld    ; R6:R7 = the segment's colour C
mov A,R0
rl A
rl A
add A,#3
lcall pcl_st       ; [4 s + 3] = C
mov R4,#0
mov R5,#0
lcall pl_half      ; R6:R7 = half, R2:R3 = C
mov A,R6
mov R4,A
mov A,R7
mov R5,A
lcall uk_avg       ; 3/4
mov A,R0
rl A
rl A
add A,#2
lcall pcl_st
mov A,R4
mov R2,A
mov A,R5
mov R3,A
mov R4,#0
mov R5,#0
lcall uk_avg       ; 1/4
mov A,R0
rl A
rl A
inc A
lcall pcl_st
inc R0
cjne R0,#7,pcl_seg
mov R6,#0
mov R7,#0
mov A,#28
lcall pcl_st       ; the background
; the window
mov DPTR,#0x%04X""" % PP_I + """
movx A,@DPTR
rl A
mov R1,A
mov DPTR,#cell_xs
movc A,@A+DPTR
mov R2,A
mov A,R1
inc A
movc A,@A+DPTR
mov R3,A           ; x0
add A,#%d""" % (CELL_W - 1) + """
mov R0,#0x30
movx @R0,A
clr A
addc A,R2
dec R0
movx @R0,A         ; x1
mov R6,#0
mov R7,#%d""" % CELL_Y + """
mov R4,#0
mov R5,#%d""" % (CELL_Y + CELL_H - 1) + """
lcall 0x%04X""" % LCD_SET_WINDOW + """
mov R2,#hi(pp_cellmap)
mov R3,#lo(pp_cellmap)
setb P0.3          ; D/C = data
clr P0.7           ; CS low
pcl_run:
mov DPH,R2
mov DPL,R3
clr A
movc A,@A+DPTR     ; the run's value
cjne A,#0xFF,pcl_go
setb P0.7          ; CS high
ret
pcl_go:
rl A
add A,%s""" % lo(PP_PAL) + """
mov DPL,A
clr A
addc A,%s""" % hi(PP_PAL) + """
mov DPH,A
movx A,@DPTR
mov R6,A
inc DPTR
movx A,@DPTR
mov R7,A           ; the colour
mov DPH,R2
mov DPL,R3
mov A,#1
movc A,@A+DPTR
mov R5,A           ; the length
mov A,R3
add A,#2
mov R3,A
clr A
addc A,R2
mov R2,A
pcl_px:
mov P1,R6
clr P0.5
setb P0.5
mov P1,R7
clr P0.5
setb P0.5
djnz R5,pcl_px
sjmp pcl_run
; pcl_st: PP_PAL[A] = R6:R7; keeps R0..R7
pcl_st:
rl A
add A,%s""" % lo(PP_PAL) + """
mov DPL,A
clr A
addc A,%s""" % hi(PP_PAL) + """
mov DPH,A
mov A,R6
movx @DPTR,A
inc DPTR
mov A,R7
movx @DPTR,A
ret
""")


def build_engine(a):
    KIT.emit_tick_driver(a, "ps_ret")        # uk_tasks falls through into pp_step
    S(a, """
; pp_step: one tick of the engine (after the stock tick work, amp on), while PP_ACT: the tick count,
; the ladder, the counter, the blink, the scan, the statics, the targets, the moves, the settling.
pp_step:
mov DPTR,#0x%04X""" % PP_ACT + """
movx A,@DPTR
jnz ps_go
ps_ret:
ret
ps_go:
mov DPTR,#0x%04X""" % PP_TICK + """
movx A,@DPTR
inc A
movx @DPTR,A
lcall pp_ladder
; the counter: every %d ticks one step towards the volume""" % COUNT_EVERY + """
mov DPTR,#0x%04X""" % PP_TICK + """
movx A,@DPTR
jb ACC.0,ps_int
mov DPTR,#0x%04X""" % PP_SHOW + """
movx A,@DPTR
mov R7,A
mov DPTR,#0x%04X""" % PP_VOL + """
movx A,@DPTR
clr C
subb A,R7
jz ps_int
mov A,R7
jc ps_down
inc A
sjmp ps_cnt
ps_down:
dec A
ps_cnt:
mov DPTR,#0x%04X""" % PP_SHOW + """
movx @DPTR,A
ps_int:
; PP_INT: the volume page is wanted (PP_ST 1 or 2)
mov DPTR,#0x%04X""" % PP_ST + """
movx A,@DPTR
mov R7,A
clr A
cjne R7,#1,ps_i2
inc A
ps_i2:
cjne R7,#2,ps_i3
inc A
ps_i3:
mov DPTR,#0x%04X""" % PP_INT + """
movx @DPTR,A
; the blink: muted on the volume page, phase 0..%d""" % (BLINK_PERIOD - 1) + """
mov DPTR,#0x%04X""" % PP_BLINK + """
jnb 0x22.1,ps_blk0
movx A,@DPTR
inc A
cjne A,#%d,ps_blk
""" % BLINK_PERIOD + """
ps_blk0:
clr A
ps_blk:
movx @DPTR,A
; the scan (entering): %d more bar cells a tick, up to %d""" % (SCAN_STEP, BAR_N) + """
cjne R7,#1,ps_stat
mov DPTR,#0x%04X""" % PP_SCAN + """
movx A,@DPTR
add A,#%d""" % SCAN_STEP + """
cjne A,#%d,ps_sc""" % (BAR_N + 1) + """
ps_sc:
jc ps_scok
mov A,#%d""" % BAR_N + """
ps_scok:
movx @DPTR,A
ps_stat:
lcall pp_statics   ; A = 1 when they painted
jz ps_move
lcall pp_retarget
mov DPTR,#0x%04X""" % PP_MOV + """
mov A,#1
movx @DPTR,A       ; no move in a tick that painted a static (one heavy draw per tick), nothing settles
ret
ps_move:
lcall pp_retarget
lcall pp_move
ljmp pp_settle

; pp_statics: the parts that are not faded. Volume page wanted: the slot and the status line black
; and the marks (once, FL_VOL), then "dB" once the name is black (FL_DB). Home wanted: "dB" black,
; then the marks black (one a tick). A = 1 when something was painted.
pp_statics:
mov DPTR,#0x%04X""" % PP_INT + """
movx A,@DPTR
jz pst_home
mov DPTR,#0x%04X""" % PP_FL + """
movx A,@DPTR
jb ACC.%d,pst_db""" % (FL_VOL.bit_length() - 1) + """
orl A,#%d""" % FL_VOL + """
anl A,#0x%02X""" % (0xFF ^ FL_SLOT) + """
movx @DPTR,A
lcall pp_slot_clear
lcall pp_stat_clear
lcall pp_marks
; the bar: every cell painted at its level (a black one goes to the ghost level 1 first, its target
; nibble kept): the status line's clear just went over its rows, and so the first move tick (the
; name's first fall) does not paint 50 cells too
mov DPTR,#0x%04X""" % PP_I + """
clr A
movx @DPTR,A
pst_gb:
mov DPTR,#0x%04X""" % PP_I + """
movx A,@DPTR
mov R3,A
add A,#%d""" % EL_BAR)
    lv_addr(a)
    S(a, """
movx A,@DPTR
anl A,#7
jnz pst_gbl
movx A,@DPTR
inc A
movx @DPTR,A
mov A,#%d""" % GHOST + """
pst_gbl:
lcall pp_lad_ld
mov A,R3
lcall pp_bar
mov DPTR,#0x%04X""" % PP_I + """
movx A,@DPTR
inc A
movx @DPTR,A
cjne A,#%d,pst_gb""" % BAR_N + """
pst_one:
mov A,#1
ret
pst_db:
jb ACC.%d,pst_ret""" % (FL_DB.bit_length() - 1) + """
mov DPTR,#0x%04X""" % (PP_LV + EL_NAME) + """
movx A,@DPTR
anl A,#7
jnz pst_ret        ; the name is not black yet
mov DPTR,#0x%04X""" % PP_FL + """
movx A,@DPTR
orl A,#%d""" % FL_DB + """
movx @DPTR,A
lcall pp_db
sjmp pst_one
pst_home:
mov DPTR,#0x%04X""" % PP_FL + """
movx A,@DPTR
jnb ACC.%d,pst_marks""" % (FL_DB.bit_length() - 1) + """
anl A,#0x%02X""" % (0xFF ^ FL_DB) + """
movx @DPTR,A
lcall pp_db_clear
sjmp pst_one
pst_marks:
jnb ACC.%d,pst_ret""" % (FL_VOL.bit_length() - 1) + """
anl A,#0x%02X""" % (0xFF ^ FL_VOL) + """
movx @DPTR,A
lcall pp_marks_clear
sjmp pst_one
pst_ret:
clr A
ret

; pp_retarget: every element's target (the high nibble of PP_LV[i]) for this tick:
;   the name: 0 while the volume page is wanted; else 7 once every cell, "VOL" and "dB" are black
;   "VOL", the cells: 0 unless the volume page is wanted and the name is black; then "VOL" 7, cells 0
;   and 1 all ghosts (1), cells 2 and 3 the counter's tens (blank below 10) and ones: lit segments 7
;   (none while the blink is off: muted, phase >= %d), the rest 1
;   the bar: 0 unless the volume page is wanted; cell i 7 when i < round(50 shown / 60) (muted: 0)
;   and i < the scan, else 1
pp_retarget:""" % BLINK_ON + """
; PP_T: cells black (1) ; PP_T + 1: name black (1)
mov R6,#1
mov R0,#%d""" % EL_VOL + """
prt_blk:
mov A,R0
""")
    lv_addr(a)
    S(a, """
movx A,@DPTR
anl A,#7
jz prt_bn
mov R6,#0
prt_bn:
inc R0
cjne R0,#%d,prt_blk""" % EL_BAR + """
mov DPTR,#0x%04X""" % PP_FL + """
movx A,@DPTR
jnb ACC.%d,prt_bok""" % (FL_DB.bit_length() - 1) + """
mov R6,#0          ; "dB" shown: not black
prt_bok:
mov DPTR,#0x%04X""" % PP_T + """
mov A,R6
movx @DPTR,A
mov DPTR,#0x%04X""" % (PP_LV + EL_NAME) + """
movx A,@DPTR
anl A,#7
jz prt_nb1
clr A
sjmp prt_nbs
prt_nb1:
mov A,#1
prt_nbs:
mov DPTR,#0x%04X""" % (PP_T + 1) + """
movx @DPTR,A       ; the name is black
mov DPTR,#0x%04X""" % PP_INT + """
movx A,@DPTR
jnz prt_vol
; home wanted: the name's target 7 once the cells are black; the ghost cells 0 and 1 stay ghosts
; (1) until the digit cells 2 and 3 are black (so they fall in a tick of their own); every other 0
mov DPTR,#0x%04X""" % PP_T + """
movx A,@DPTR
jz prt_n0
mov A,#0x70
prt_n0:
mov DPTR,#0x%04X""" % (PP_LV + EL_NAME) + """
lcall prt_set
mov R6,#0          ; the ghost cells' target: 0x10 while a digit cell's segment is lit
mov R0,#%d""" % (EL_SEG + 14) + """
prt_lb:
mov A,R0
""")
    lv_addr(a)
    S(a, """
movx A,@DPTR
anl A,#7
jz prt_lbn
mov R6,#0x10
prt_lbn:
inc R0
cjne R0,#%d,prt_lb""" % EL_BAR + """
mov R0,#%d""" % EL_VOL + """
prt_z:
mov A,R0
""")
    lv_addr(a)
    S(a, """
clr A
cjne R0,#%d,prt_zc""" % EL_SEG + """
prt_zc:
jc prt_zs          ; "VOL"
mov A,R0
cjne A,#%d,prt_zg""" % (EL_SEG + 14) + """
prt_zg:
jnc prt_zz         ; a digit cell's segment or a bar cell: 0
mov A,R6
sjmp prt_zs
prt_zz:
clr A
prt_zs:
lcall prt_set
inc R0
cjne R0,#%d,prt_z""" % EL_N + """
ret
prt_vol:
; the volume page wanted: the name 0
mov DPTR,#0x%04X""" % (PP_LV + EL_NAME) + """
clr A
lcall prt_set
; "VOL" and the cells: 0 until the name is black
mov DPTR,#0x%04X""" % (PP_T + 1) + """
movx A,@DPTR
jnz prt_lit
mov R0,#%d""" % EL_VOL + """
prt_z2:
mov A,R0
""")
    lv_addr(a)
    S(a, """
clr A
lcall prt_set
inc R0
cjne R0,#%d,prt_z2""" % EL_BAR + """
sjmp prt_bar
prt_lit:
mov DPTR,#0x%04X""" % (PP_LV + EL_VOL) + """
mov A,#0x70
lcall prt_set
; the digits' masks: PP_T = the tens', PP_T + 1 = the ones'
mov DPTR,#0x%04X""" % PP_SHOW + """
movx A,@DPTR
mov B,#10
div AB             ; A tens, B ones
mov R6,#0
jz prt_t0
mov DPTR,#seg_tab
movc A,@A+DPTR
mov R6,A
prt_t0:
mov A,B
mov DPTR,#seg_tab
movc A,@A+DPTR
mov R7,A
jnb 0x22.1,prt_msk
mov DPTR,#0x%04X""" % PP_BLINK + """
movx A,@DPTR
clr C
subb A,#%d""" % BLINK_ON + """
jc prt_msk
mov R6,#0          ; the blink's off phase
mov R7,#0
prt_msk:
mov DPTR,#0x%04X""" % PP_T + """
mov A,R6
movx @DPTR,A
inc DPTR
mov A,R7
movx @DPTR,A
; cells 0..3, segments 0..6: R0 = the element, R1 = the cell, R2 = the segment bit
mov R0,#%d""" % EL_SEG + """
mov R1,#0
prt_cell:
mov R2,#1
prt_seg:
mov A,#0x10        ; a ghost
cjne R1,#2,prt_c2
mov DPTR,#0x%04X""" % PP_T + """
sjmp prt_cm
prt_c2:
jc prt_cst         ; cells 0 and 1
mov DPTR,#0x%04X""" % (PP_T + 1) + """
prt_cm:
movx A,@DPTR
anl A,R2
jz prt_ghost
mov A,#0x70
sjmp prt_cst
prt_ghost:
mov A,#0x10
prt_cst:
mov R3,A
mov A,R0
""")
    lv_addr(a)
    S(a, """
mov A,R3
lcall prt_set
inc R0
mov A,R2
rl A
mov R2,A
cjne R2,#0x80,prt_seg
inc R1
cjne R1,#4,prt_cell
prt_bar:
; the bar: PP_T + 2 = min(round(50 shown / 60) (bar_tab), scan); muted: 0
mov R6,#0
jb 0x22.1,prt_lim
mov DPTR,#0x%04X""" % PP_SHOW + """
movx A,@DPTR
mov DPTR,#bar_tab
movc A,@A+DPTR     ; round(50 shown / 60)
mov R6,A
mov DPTR,#0x%04X""" % PP_SCAN + """
movx A,@DPTR
clr C
subb A,R6
jnc prt_lim
movx A,@DPTR
mov R6,A           ; the scan is behind
prt_lim:
mov DPTR,#0x%04X""" % (PP_T + 2) + """
mov A,R6
movx @DPTR,A
mov R0,#%d""" % EL_BAR + """
prt_b:
mov A,R0
clr C
subb A,#%d""" % EL_BAR + """
mov R7,A           ; the bar cell
mov DPTR,#0x%04X""" % (PP_T + 2) + """
movx A,@DPTR
mov R6,A
mov A,R7
clr C
subb A,R6          ; i - limit: C when i < limit
mov A,#0x70
jc prt_bst
mov A,#0x10
prt_bst:
mov R3,A
mov A,R0
""")
    lv_addr(a)
    S(a, """
mov A,R3
lcall prt_set
inc R0
cjne R0,#%d,prt_b""" % EL_N + """
ret
; prt_set: the element at DPTR gets the target A (a high nibble); keeps R0..R7
prt_set:
mov B,A
movx A,@DPTR
anl A,#0x0F
orl A,B
movx @DPTR,A
ret

; pp_move: every element one level towards its target and repainted. Rising: the name, and "VOL" and
; the segments while entering, a level every %d ticks; everything else jumps. Falling: a level every
; %d ticks on the open page (afterglow), every %d during a transition. PP_MOV: something is still
; off its target; PP_DIRTY: the cells to repaint, painted last.
pp_move:""" % (RATE_RISE, RATE_GLOW, RATE_FALL) + """
mov DPTR,#0x%04X""" % PP_MOV + """
clr A
movx @DPTR,A
inc DPTR
movx @DPTR,A       ; PP_DIRTY
mov DPTR,#0x%04X""" % PP_I + """
movx @DPTR,A
pm_next:
mov DPTR,#0x%04X""" % PP_I + """
movx A,@DPTR
cjne A,#%d,pm_el""" % EL_N + """
ljmp pm_cells
pm_el:
mov R0,A
""")
    lv_addr(a)
    S(a, """
movx A,@DPTR
mov R1,A
anl A,#7
mov R2,A           ; the level
mov A,R1
swap A
anl A,#7
mov R3,A           ; the target
xrl A,R2
jnz pm_mv
pm_skip:
mov DPTR,#0x%04X""" % PP_I + """
movx A,@DPTR
inc A
movx @DPTR,A
sjmp pm_next
pm_mv:
mov DPTR,#0x%04X""" % PP_MOV + """
mov A,#1
movx @DPTR,A
mov DPTR,#0x%04X""" % PP_TICK + """
movx A,@DPTR
mov R4,A           ; the tick
mov DPTR,#0x%04X""" % PP_ST + """
movx A,@DPTR
mov R5,A           ; the state
clr C
mov A,R2
subb A,R3
jnc pm_fall
; rising: a ramp for the name, and for "VOL" and the segments while entering; else a jump
mov A,R0
jz pm_ramp
cjne R5,#1,pm_jump
mov A,R0
cjne A,#%d,pm_rc""" % EL_BAR + """
pm_rc:
jnc pm_jump
pm_ramp:
mov A,R4
anl A,#%d""" % (RATE_RISE - 1) + """
jnz pm_skip
mov A,R2
inc A
sjmp pm_set
pm_jump:
mov A,R3
sjmp pm_set
pm_fall:
mov A,R4
cjne R5,#2,pm_fr
anl A,#%d""" % (RATE_GLOW - 1) + """
sjmp pm_ft
pm_fr:
anl A,#%d""" % (RATE_FALL - 1) + """
pm_ft:
jnz pm_skip
mov A,R2
dec A
pm_set:
mov R2,A
mov A,R1
anl A,#0xF0
orl A,R2
mov R1,A
mov A,R0
""")
    lv_addr(a)
    S(a, """
mov A,R1
movx @DPTR,A
; paint it
mov A,R0
jnz pm_p1
mov A,R2
lcall pp_name_lv
sjmp pm_back
pm_p1:
cjne R0,#%d,pm_pseg""" % EL_VOL + """
mov A,R2
lcall pp_vol_lv
pm_back:
ljmp pm_skip
pm_pseg:
mov A,R0
clr C
subb A,#%d""" % EL_BAR + """
jnc pm_pbar
mov A,R0
clr C
subb A,#%d""" % EL_SEG + """
mov B,#7
div AB             ; A = the cell
mov R4,A
mov R3,#1
pm_sh:
mov A,R4
jz pm_bitok
mov A,R3
rl A
mov R3,A
dec R4
sjmp pm_sh
pm_bitok:
mov DPTR,#0x%04X""" % PP_DIRTY + """
movx A,@DPTR
orl A,R3
movx @DPTR,A
sjmp pm_back
pm_pbar:
mov R3,A           ; the bar cell
mov A,R2
lcall pp_lad_ld
mov A,R3
lcall pp_bar
ljmp pm_skip
pm_cells:
; the dirty cells, lowest first (PP_DIRTY shifted right each time, PP_I the cell)
mov DPTR,#0x%04X""" % PP_I + """
clr A
movx @DPTR,A
pmc_loop:
mov DPTR,#0x%04X""" % PP_DIRTY + """
movx A,@DPTR
jz pmc_ret
clr C
rrc A
movx @DPTR,A
jnc pmc_next
mov DPTR,#0x%04X""" % PP_I + """
movx A,@DPTR
lcall pp_cell
pmc_next:
mov DPTR,#0x%04X""" % PP_I + """
movx A,@DPTR
inc A
movx @DPTR,A
sjmp pmc_loop
pmc_ret:
ret
""")


def build_engine_tail(a):
    S(a, """
; pp_settle: nothing moving: entering -> the volume page once the scan is through and "dB" is shown;
; exiting -> the slot and the status line (from the buffer the held-back refresh loaded), then home
; with the engine off
pp_settle:
mov DPTR,#0x%04X""" % PP_MOV + """
movx A,@DPTR
jnz pse_ret
mov DPTR,#0x%04X""" % PP_ST + """
movx A,@DPTR
cjne A,#1,pse_n1
mov DPTR,#0x%04X""" % PP_SCAN + """
movx A,@DPTR
cjne A,#%d,pse_ret""" % BAR_N + """
mov DPTR,#0x%04X""" % PP_FL + """
movx A,@DPTR
anl A,#%d""" % (FL_DB | FL_VOL) + """
cjne A,#%d,pse_ret""" % (FL_DB | FL_VOL) + """
mov DPTR,#0x%04X""" % PP_ST + """
mov A,#2
movx @DPTR,A
pse_ret:
ret
pse_n1:
cjne A,#3,pse_ret
mov DPTR,#0x%04X""" % PP_FL + """
movx A,@DPTR
anl A,#%d""" % (FL_DB | FL_VOL) + """
jnz pse_ret        ; the marks or "dB" still shown
mov DPTR,#0x%04X""" % PP_ST + """
clr A
movx @DPTR,A       ; PP_ST 0 (the painters see an idle engine)
inc DPTR
movx @DPTR,A       ; PP_ACT 0
lcall pp_slot_draw
ljmp pp_status_draw
""")


def build_plumbing(a):
    S(a, """
; pp_enter_vol: page 2 is being opened (the four volume-key sites, pp_clear with page 2, the page-2
; renderer, the mute key). Entering or on the page: nothing. From home or an exit: enter (the scan
; from 0, or over the bar as it is after an exit), the engine on, the status buffer cleared as
; ui_clear_screen clears it (the name buffer stays: the name fades from it).
pp_enter_vol:
mov DPTR,#0x%04X""" % PP_ST + """
movx A,@DPTR
cjne A,#1,pev_n1
ret
pev_n1:
cjne A,#2,pev_n2
ret
pev_n2:
mov R7,A
mov A,#%d""" % BAR_N + """
cjne R7,#3,pev_sc
sjmp pev_sc2
pev_sc:
clr A
pev_sc2:
mov DPTR,#0x%04X""" % PP_SCAN + """
movx @DPTR,A
mov DPTR,#0x%04X""" % PP_ST + """
mov A,#1
movx @DPTR,A
inc DPTR
movx @DPTR,A       ; PP_ACT
ljmp 0x5CBC        ; ui_clear_small_buf

; pp_exit: page 1 is being rendered over the volume page (or an entry): exit (the engine on), the
; stock refresh not yet through, the text buffers as ui_clear_screen leaves them, the name reloaded
; as home_draw_input_name loads it and measured (PP_NX for the rise)
pp_exit:
mov DPTR,#0x%04X""" % PP_ST + """
mov A,#3
movx @DPTR,A
inc DPTR
mov A,#1
movx @DPTR,A       ; PP_ACT
mov DPTR,#0x%04X""" % PP_SBUF + """
clr A
movx @DPTR,A
lcall 0x5CBC
lcall 0x5CCB
lcall pp_name_load
ljmp pp_name_x

; pp_clear: replaces lcall ui_clear_screen at 0x2106 (ui_render_page); page in 0x59. Page 2: the
; entry. Page 1 over the volume page or an entry: the exit; during an exit or at home: the stock clear
; (pp_cancel stops the engine first).
pp_clear:
mov A,0x59
cjne A,#2,pc_n2
ljmp pp_enter_vol
pc_n2:
cjne A,#1,pc_stock
mov DPTR,#0x%04X""" % PP_ST + """
movx A,@DPTR
jz pc_stock
cjne A,#3,pc_exit
pc_stock:
ljmp 0x5D42        ; ui_clear_screen
pc_exit:
ljmp pp_exit

; pp_volpage: page 2 renderer (replaces 0x2167): the entry unless it runs or the page is on, the
; volume recorded, then the page's common tail
pp_volpage:
lcall pp_enter_vol
mov R7,0x31
lcall pp_draw_volume
ljmp 0x22FA        ; clears 0x22.3, 0x32, 0x46 like every page

; pp_draw_volume: replaces volpage_draw_volume 0x5936 (R7 speaker volume; 0x52 on headphones):
; the volume for the counter (the counter follows at once while the engine is idle), XDATA 5 = 2 as
; stock, and the MUTE lamp (a volume key unmutes first)
pp_draw_volume:
mov A,0x2B
xrl A,#1
jz pdv_spk
mov R7,0x52
pdv_spk:
mov R0,#5
mov A,#2
movx @R0,A
mov A,R7
cjne A,#61,pdv_c
pdv_c:
jc pdv_ok
mov A,#60
pdv_ok:
mov DPTR,#0x%04X""" % PP_VOL + """
movx @DPTR,A
mov R7,A
mov DPTR,#0x%04X""" % PP_ST + """
movx A,@DPTR
jnz pdv_lamp
mov DPTR,#0x%04X""" % PP_SHOW + """
mov A,R7
movx @DPTR,A
pdv_lamp:
ljmp pp_lamp

; pp_stop: the engine off and empty: PP_ST 0, every element black at a black target, no flags, the
; counter on the active output's volume
pp_stop:
mov DPTR,#0x%04X""" % PP_ST + """
clr A
movx @DPTR,A
inc DPTR
movx @DPTR,A       ; PP_ACT
inc DPTR
inc DPTR
movx @DPTR,A       ; PP_BLINK
inc DPTR
movx @DPTR,A       ; PP_FL
inc DPTR
movx @DPTR,A       ; PP_SCAN
mov DPTR,#0x%04X""" % PP_SBUF + """
movx @DPTR,A
mov DPTR,#0x%04X""" % PP_LV + """
mov R0,#%d""" % EL_N + """
pso_z:
movx @DPTR,A
inc DPTR
djnz R0,pso_z
mov A,0x2B
cjne A,#1,pso_hp
mov A,0x31
sjmp pso_v
pso_hp:
mov A,0x52
pso_v:
cjne A,#61,pso_c
pso_c:
jc pso_vok
mov A,#60
pso_vok:
mov DPTR,#0x%04X""" % PP_VOL + """
movx @DPTR,A
inc DPTR
movx @DPTR,A       ; PP_SHOW
ret

; pp_cancel: ui_clear_screen's first instruction; every stock clear stops the engine first
pp_cancel:
lcall pp_stop
lcall 0x5CBC       ; the instruction the hook replaced
ljmp 0x5D45

; pp_hold: replaces the periodic refresh's lcall home_refresh at 0x4081 (0x3FE3): while a transition
; runs, skip home_refresh and the status line (0x4084..0x4088) and note that the status buffer
; (XDATA 0x50) has just been loaded (the exit's end draws it).
pp_hold:
mov DPTR,#0x%04X""" % PP_ST + """
movx A,@DPTR
jz hh_stock
cjne A,#2,hh_held
hh_stock:
; hh_stock: home_refresh, then the status line as the loader left it: the draw at 0x4084 is marked as
; the loader's (PP_SIG bit 1), so pp_status keeps the tint the signal check decided
lcall 0x5C8B       ; home_refresh
mov DPTR,#0x%04X""" % PP_SIG + """
movx A,@DPTR
orl A,#2
movx @DPTR,A
ljmp 0x4084        ; mov R7,#0x87 ; mov R6,#0 ; ljmp small_text_render
hh_held:
mov DPTR,#0x%04X""" % PP_SBUF + """
mov A,#1
movx @DPTR,A
ret                ; 0x3FE3's own return (0x4088 is a tail jump)

; pp_busy_home: during an exit, end it now with the whole home screen (every page-1 draw of a stock
; sequence comes through here first, so the sequence draws over a whole home)
pp_busy_home:
mov DPTR,#0x%04X""" % PP_ST + """
movx A,@DPTR
cjne A,#3,pbh_ret
; pp_home_now: stop the engine, black screen, then home_refresh and the status line from XDATA 0x50
; as home_refresh_periodic draws them (hh_stock; the text buffers are kept)
pp_home_now:
lcall pp_stop      ; PP_ST 0 first, so the draws inside pass this test
lcall 0x51EE       ; lcd_clear_black
ljmp hh_stock
pbh_ret:
ret

; pp_name_guard: home_draw_input_name's entry (Source, direct-select, input_apply, the BT key's
; home_refresh): during an exit the whole home first, then the stock name draw goes on
pp_name_guard:
lcall pp_busy_home
mov A,0x47
dec A
ljmp 0x4A88

; pp_flag_path: home_refresh_periodic's flag path (0x3FF8, taken when 0x21.3, 0x21.1 or 0x20.6 is set,
; e.g. after Source). Stock clears the flags, sets page 1 and blacks out x 0..239, y 43..169 (0x412F)
; before loading the status line and drawing home. During a transition that fill would erase parts
; the engine owns: skip it and go on with the status line (0x4016) and the refresh, which pp_hold
; holds back.
pp_flag_path:
clr 0x21.3         ; the two instructions the hook replaced
clr 0x20.6
mov DPTR,#0x%04X""" % PP_ST + """
movx A,@DPTR
jz pfp_stock
cjne A,#2,pfp_busy
pfp_stock:
ljmp 0x3FFC
pfp_busy:
clr 0x21.1         ; 0x3FFC..0x3FFF: clr 0x21.1, page 1; the fill (0x4001..0x4013) is skipped
mov 0x45,#1
ljmp 0x4016

; pp_signal: replaces the status loader's lcall signal_check (0x4016): the check, its result kept in
; PP_SIG for the status line's colour (RAM 0x22.5 is reused by volume_apply, so it is not read
; back), C as the check left it
pp_signal:
lcall 0x5232
clr A
rlc A
mov DPTR,#0x%04X""" % PP_SIG + """
movx @DPTR,A
rrc A
ret

; pp_name_load: XDATA 0x35 = the input name, as home_draw_input_name loads it (input 7 and out of
; range: the buffer is left as it is)
pp_name_load:
mov A,0x47
dec A
cjne A,#8,pnl_c
pnl_c:
jnc pnl_ret
rl A
mov B,A
mov DPTR,#names8
movc A,@A+DPTR
mov R2,A
mov A,B
inc A
movc A,@A+DPTR
mov R1,A
orl A,R2
jz pnl_ret
mov R3,#0xFF       ; code space
clr A
mov R5,A
mov R7,A
ljmp 0x4C8F        ; big_text_load
pnl_ret:
ret

; pp_align_small: small_text_render's hook (0x3A82): on page 1 the text at the stock y %d is the
; status line (pp_status, then return from the stock renderer: nothing is pushed at this point);
; every other text goes on as stock
pp_align_small:""" % STATUS_Y + """
mov A,0x45
cjne A,#1,pas_x
mov R0,#0
movx A,@R0         ; y hi
jnz pas_x
inc R0
movx A,@R0         ; y lo
cjne A,#%d,pas_x""" % STATUS_Y + """
ljmp pp_status
pas_x:
clr A              ; the two instructions the hook replaced
mov R0,#2
ljmp 0x3A85

; pp_mute_key: replaces the mute key's handler key_1c (0x1047; reached on pages 1 and 2 only: a menu
; turns the key into "home" at 0x0C23, and read_key did so on page 2 until pp_key_p2). Stock went
; home (page 1, render) and toggled; this toggles the same way (0x1052..0x1065: muted ->
; mute_state_set(0), P2.5 low; unmuted -> the unmute countdown at 10 ticks) and then shows the
; volume page as the volume keys do: page 2 through pp_enter_vol unless it is open, then their tail
; 0x0F50: volpage_draw_volume (pp_draw_volume: the MUTE lamp), 0x27:0x28 = 0x3F:0x40 = 200.
pp_mute_key:
cpl 0x22.1
jnb 0x22.1,pmk_on
clr A
mov R7,A
lcall 0x5A62       ; mute_state_set(0)
clr P2.5
sjmp pmk_page
pmk_on:
mov 0x43,#0
mov 0x44,#0x0A
pmk_page:
mov A,0x45
xrl A,#2
jz pmk_tail
mov 0x45,#2
lcall pp_enter_vol
pmk_tail:
ljmp 0x0F50

; pp_key_p2: read_key's page-2 filter for IR keys (0x3DC6..0x3DD6: every key but 0x1A, 0x1B, 0x1F
; becomes 0x15, "home"), from its last test on. The mute key 0x1C is kept as well, so it toggles on
; the open volume page instead of only closing it.
pp_key_p2:
mov A,R3
xrl A,#0x1F
jz pkp_keep
mov A,R3
xrl A,#0x1C
jz pkp_keep
ljmp 0x3DD6        ; mov R7,#0x15
pkp_keep:
ljmp 0x3DD8
""")


def build(a):
    build_data(a)
    build_primitives(a)
    build_painters(a)
    build_engine(a)
    build_engine_tail(a)
    build_plumbing(a)


def assemble_hole():
    """HOLE_FONTS assembled in the stock big font's place; their labels go into the code's assembler."""
    fa = Asm(FONT_HOLE)
    fa.comment("data in the stock big font's place, 0x%04X..0x%04X (dead in this image)" % (FONT_HOLE, FONT_HOLE_END - 1))
    for f in HOLE_FONTS:
        f.emit(fa)
    data = fa.resolve()
    assert len(data) <= FONT_HOLE_END - FONT_HOLE, "hole data %d bytes, room %d" % (len(data), FONT_HOLE_END - FONT_HOLE)
    return data, fa


def assemble():
    hole, fa = assemble_hole()
    a = Asm(CODE_ADDR)
    a.labels.update(fa.labels)
    build(a)
    features.emit(a, INCLUDES)
    code = a.resolve()
    base = open(BASE_IMAGE, "rb").read()
    assert hashlib.sha256(base[FONT_HOLE:FONT_HOLE_END]).hexdigest() == FONT_HOLE_SHA, "stock big font not as expected"
    blocks = [(FONT_HOLE, base[FONT_HOLE:FONT_HOLE + len(hole)], hole, fa.listing())]
    return code, a.labels, a, blocks


def main():
    base = open(sys.argv[1] if len(sys.argv) > 1 else BASE_IMAGE, "rb").read()
    asserts = [(addr, text.encode() + b"\0", "input name %d moved" % inp) for inp, addr, text in INPUT_NAMES]
    asserts += [
        (0x2A28, b"\xF2", "movx @R0,A after the align hooks moved"),
        (0x3A85, b"\xF2", "movx @R0,A after the align hooks moved"),
        (0x4084, bytes.fromhex("7f877e00") + b"\x02", "0x4084 not as expected"),
        (0x5D45, bytes.fromhex("125ccb"), "ui_clear_screen's second call moved"),
        (0x4A88, bytes.fromhex("b40800"), "home_draw_input_name's cjne moved"),
        (0x3FF8, bytes.fromhex("c20bc206c209"), "home_refresh_periodic's flag path moved"),
        (0x4A9B + 3 * 6, bytes.fromhex("024aef"), "input 7 draws the buffer as it is"),
        (0x3325, bytes.fromhex("300c07c20cc2141258d320070302345b"), "main_tick_tasks' re-mute request part moved"),
        (0x345B, b"\x22", "main_tick_tasks without a tick no longer only returns"),
        (0x1047, bytes.fromhex("e545640160057545 01d213b211301109 e4ff125a62c2a580 06754300 75440a 752700 75280a 22"),
         "key_1c (the mute key) not as expected"),
        (0x0CB3, bytes.fromhex("10471c"), "the key switch's entry for 0x1C moved"),
        (0x0C23, bytes.fromhex("eb641c70027b15"), "the menus' mute key -> home filter moved"),
        (0x0F50, bytes.fromhex("af31125936 752700 7528c8 753f00 7540c8 22"), "the volume keys' tail moved"),
        (0x5A5E, bytes.fromhex("c2117f01ef7008c2141258d3d2a222"), "mute_state_set not as expected"),
        (0x3DC6, bytes.fromhex("effb641a600ceb641b6007eb641f60027f15c3ed9403"), "read_key's page-2 filter moved"),
        (0x4260, b"\x22", "home_draw_format_tag's ret after its paint call moved"),
    ]
    for inp, addr, text in INPUT_NAMES:
        t = (base[0x4A9B + 3 * (inp - 1) + 1] << 8) | base[0x4A9B + 3 * (inp - 1) + 2]
        asserts.append((t, bytes([0x7B, 0xFF, 0x7A, addr >> 8, 0x79, addr & 0xFF]), "name table %d" % inp))
    patches = [(s, VOL_ENTRY_ORIG, lambda labels: vol_entry_bytes(labels["pp_enter_vol"]),
                "lcall pp_enter_vol ; sjmp 0x%04X" % (s + len(VOL_ENTRY_ORIG))) for s in VOL_ENTRY_SITES]
    patches += FIX_PATCHES
    uikit.build_image(base_path=sys.argv[1] if len(sys.argv) > 1 else BASE_IMAGE, base_sha=BASE_SHA,
                      code_addr=CODE_ADDR, assemble=assemble, hooks=HOOKS, patches=patches, asserts=asserts,
                      version_text=VERSION_TEXT, out_image=OUT_IMAGE, out_listing=OUT_LISTING,
                      title="Phosphor Panel patch", label_prefixes=("pp_", "uk_"))


if __name__ == "__main__":
    main()
