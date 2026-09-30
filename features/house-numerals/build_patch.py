#!/usr/bin/env python3
"""Build the "House Numerals" image for the SMSL AO300 (on top of fast-lcd), hn10.

A reduced build of study 3 in features/ui-theme/ui_themes.html:

  home      the mock's home, drawn by us in the mock's typefaces (uk_text, fonts packed from
            tools/fonts by pfont): the speaker icon (red with an X when muted, headphones on
            the headphone output) and the volume top left, the format and EQ tags as accent
            boxes with rounded corners top right, the input name in the display face, the
            status line in grey mono under it (reddish when the input has no signal) and a
            28x3 accent bar. Each stock painter of a home element is replaced by ours (icon
            0x5744, volume 0x5916, EQ tag 0x4F18, format tag 0x425D and its clears), and on
            page 1 the stock text renderers hand the name (big, y 75) and the status line
            (small, y 135) to us (0x2A25, 0x3A82). So every stock sequence that draws home
            parts draws ours. A shorter text clears the rest of the longer one. Sizes and
            positions come from layout.json (sizing.html writes it).
  volume    the mock's volume page: the input name (display face, 36 px) and the status line
            (loaded as the periodic refresh loads it) left of a divider, "VOL" over the
            volume right-aligned in 84-px numerals right of it, a 288-px position line, the
            level in dB below step 60 ("_39.5 dB", from the stock NJW1194 code table) and
            "max 60" under it. volpage_draw_volume 0x5936 is replaced: a knob or remote step
            redraws the dB caption, rolls the number (14 frames, one per tick: the old one
            slides out, the new one in, one number a frame in the mock's grey, in a clip box,
            uk_textc) and changes the target of the line's spring (the mock's k 200, c 28, as a
            fixed-point matrix per tick), which redraws only the columns it moved.
  wipes     a 2-px accent edge sweeps across the screen with the mock's cubic ease, STEPS (32)
            steps of one 10 ms main-loop tick each: right to left into the volume page, left to
            right back home. Nothing blocks: the main loop's tick path (main_tasks_on's
            lcall main_tick_tasks, 0x5B2A) runs one step after each tick it handles. Each
            step fills the band the edge swept with black, draws the edge and draws every
            element of the new page the edge has fully passed (hn_step).
  text      uk_text (the mock's faces) everywhere; the kit's stock-font painter uk_paint is
            not linked into this image.

Entry: the four volume-key sites and the page-2 renderer only start the animation
(hn_enter_vol); the key handler's tail still writes the volume before anything is drawn.
Exit: the Timer0 return home sets page 1 and 0x22.3; ui_render_page's clear (0x2106, hn_clear)
starts the exit instead of clearing, and home_refresh at 0x4081 (hn_hold) is held back while a
wipe runs. Any stock clear (ui_clear_screen 0x5D42, hn_cancel) cancels a wipe first; so does
the name draw 0x4A85 during an exit (Source and direct-select on page 1, hn_name_guard).

Per tick (uk_tasks, after the stock tick work, amp on): the wipe step, the spring, the roll.

Register use: every hn_* / hm_* / hv_* routine may clobber A, B, DPTR, PSW and R0-R7 (the stock
routines they replace or wrap do the same). RAM 0x48:0x49 (the theme colour) is only read.
New state lives in XDATA 0x0100..0x01C1.
"""
import hashlib
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "patch"))
import features  # noqa: E402
from asm51 import Asm, hi8, lo8  # noqa: E402,F401
import uikit  # noqa: E402
import pfont  # noqa: E402
from uikit import (hi, lo, S, st_imm16, ld16, st16, FONTS, SMALL_MAP, BIG_MAP, BIG_NARROW,  # noqa: E402,F401
                   LCD_SET_WINDOW, FONT_SMALL, FONT_BIG, HOME_DRAW_VOLUME, HOME_DRAW_OUTPUT_ICON,
                   HOME_DRAW_FORMAT_TAG, HOME_DRAW_EQ_TAG, HOME_REFRESH, UI_CLEAR_SCREEN,
                   CLEAR_SMALL_BUF, CLEAR_BIG_BUF, BIG_TEXT_LOAD, MAIN_TICK_TASKS, RENDER_DONE,
                   BIG_BUF, SMALL_BUF, NAME_Y, STATUS_Y, INPUT_NAMES, P1, STOCK_SITES,
                   VOL_ENTRY_SITES, VOL_ENTRY_ORIG, vol_entry_bytes, VERSION_PTR_ADDR, VERSION_MAX_LEN)

BASE = "fast-lcd"                   # image this builds on (tools/patch/features.py)
INCLUDES = ["fix-auto-off", "strings"]   # fix features linked into this image
BASE_IMAGE = features.image(BASE)
BASE_SHA = "6d186a817762b8d705f75ffe178089483e4584fc01ebe55884fbb88b114cec7d"
OUT_IMAGE = os.path.join(HERE, "build", "flash_house_numerals.bin")
OUT_LISTING = os.path.join(HERE, "house_numerals.asm")

CODE_ADDR = 0x9800                  # after fast-lcd (code 0x9700..0x976B, version string)

# colours (RGB565)
ORANGE = 0xFC43                     # #ff8a1f, accent on the White theme
DIVIDER = 0x2104                    # #222
TRACK = 0x18E3                      # #1d1d1d
WHITE = 0xFFFF
RED = 0xF800                        # #ff0000, the muted icon
FAINT = uikit.rgb565(0x4D, 0x52, 0x57)   # #4d5257, the volume page's "max 60"

# XDATA
HN_N = 0x0100                       # uk_fill's work area (4 bytes, see KIT below)
HN_VOL = 0x0104                     # volume being shown (0..60)
HN_NUM = 0x0105                     # its two characters and a NUL, for uk_paint
HN_MODE = 0x0108                    # 0 idle, 1 wipe into the volume page, 2 wipe back home
HN_VF = 0x0109                      # volume-page elements on screen (VF_* bits)
HN_HF = 0x010A                      # home elements drawn by the exit wipe (HF_* bits)
HN_STEP = 0x010B                    # wipe step 0..20
HN_SBUF = 0x010C                    # exit: the stock refresh has loaded the status buffer
HN_X = 0x010D                       # edge x (hi, lo)
HN_XP = 0x010F                      # step: the previous edge x
HN_LIM = 0x0111                     # step: reveal limit (entry: left >= it; exit: right < it)
HN_D0 = 0x0113                      # step: damaged columns (band and edge) from ...
HN_D1 = 0x0115                      # ... to
HN_B0 = 0x0117                      # step: band from ...
HN_B1 = 0x0119                      # ... to
HN_NAMER = 0x011B                   # exit: right end of the home input name
HN_S0 = 0x011D                      # hn_line_seg: columns from ...
HN_S1 = 0x011F                      # ... to
HN_SPL = 0x0121                     # the position line's split column on screen (the spring's, 16..304)
HN_STATR = 0x0123                   # exit: right end of the status line as drawn
TP_BASE = 0x015B                    # uk_text's parameter block and work area (55 bytes, up to HM_VS)
HM_VS = 0x0192                      # home volume as text (up to 2 digits and a NUL)
HM_TAG = 0x0196                     # a tag's text, trailing spaces cut (up to 5 characters and a NUL)
HM_TX = 0x019C                      # hm_tag: box x
HM_TW = 0x019D                      # hm_tag: box width
HM_TWD = 0x019E                     # hm_tag: text width
HM_RL = 0x019F                      # hm_rest: last column to clear (hi, lo)
HM_RY = 0x01A1                      # hm_rest: first row
HM_RH = 0x01A2                      # hm_rest: rows
HM_RX = 0x01A3                      # hm_rest: next column (hi, lo)
HM_TR = 0x01A5                      # hm_tag: the box ends before this column
HM_TL = 0x01A6                      # hm_tag: the tag's area starts at this column
HN_HF0 = 0x01A7                     # step: HN_HF / HN_VF when the step began (name and status don't share one)
HN_SLD = 0x01A8                     # hn_stat_load: the status loader runs for the volume page (hn_hold returns)
HV_DB = 0x01A9                      # volume page: the dB caption, 8 characters and a NUL
HN_SIG = 0x01B2                     # the status loader's signal check: 1 = signal (hn_signal); tints the status line.
                                    # Bit 1: the next page-1 draw at y 135 is the loader's text (hn_hold -> hm_status_r)
SP_P = 0x01B3                       # spring: position along the line, pixels * 64, signed (hi, lo)
SP_V = 0x01B5                       # spring: velocity, pixels * 64 per tick, signed
SP_T = 0x01B7                       # spring tick: the target * 64
SP_E = 0x01B9                       # spring tick: position - target
SP_W = 0x01BB                       # hn_sp_lin: its first product
HR_F = 0x01BD                       # number roll: the next frame 1..14, 0 idle
HR_DIR = 0x01BE                     # number roll: 0 up (the old number leaves upwards), 1 down
HR_OLD = 0x01BF                     # number roll: the previous target's text (up to 2 digits and a NUL)

# uk_fill's work area (HN_N, HN_C) and uk_paint's parameter block and work area (FP..FP_OFF)
# belong to the kit, placed where hn4.1 had them
KIT = uikit.Kit(fill_ws=HN_N, fp_base=0x0130, tp_base=TP_BASE)
XDATA_END = HR_OLD + 2
# XDATA this image's own code uses: the variables above and the kit's blocks (tools/build.py checks it)
XDATA = [(0x0100, XDATA_END + 1, "house-numerals variables, uikit fill/FP/TP blocks")]
(FP, FP_FONT, FP_STR, FP_SPC, FP_X, FP_Y, FP_INK, FP_BG, FP_CX0, FP_CX1, FP_SCALE, FP_W, FP_BPC, FP_BPG,
 FP_DATA, FP_MAP, FP_NADV, FP_CUR, FP_END, FP_CW, FP_ADV, FP_GLY, FP_VX0, FP_VX1, FP_OFF) = KIT.fp_layout()
assert FP + uikit.Kit.FP_SIZE - 1 < TP_BASE
assert TP_BASE + uikit.Kit.TP_SIZE <= HM_VS

# the home layout: layout.json, written by sizing.html (served by tools/fonts/rasterize.py), with
# every position explicit and the fonts named by their rasters in tools/fonts/raster
LAYOUT_FILE = os.path.join(HERE, "layout.json")
LAYOUT = json.load(open(LAYOUT_FILE))["home"]
NAME_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ .-"       # page-1 big text: input names, EQ preset names
TAG_CHARS = "ABCDFIKLMPQRSTUo. "                   # the format and EQ tags
STATUS_CHARS = " !'-.0123456789ABCDEFGHIKLMNOPQRSTUVXabcdeghiklmnoprstuvwyz"   # every firmware string
# (sizing.html keeps the same character sets, for its flash figures)
# the volume page's mono texts: the status line (any firmware string), "VOL", the dB caption
# ("_" draws the raster's minus sign, "~" its infinity) and "max 60"
MONO_CHARS = STATUS_CHARS + "x_~"
MONO_ALIAS = {"_": "−", "~": "∞"}
VNAME_CHARS = "".join(sorted(set("".join(t for _, _, t in INPUT_NAMES[:6]))))   # the volume page's name
assert set(TAG_CHARS) | set("VOL dBmax0123456789.") <= set(MONO_CHARS)


def layout_font(label, element, chars, alias=None):
    return raster_font(label, LAYOUT[element]["font"], chars, "layout.json, %s" % element, alias)


def raster_font(label, rid, chars, where, alias=None):
    if not os.path.exists(os.path.join(pfont.RASTER_DIR, rid + ".json")):
        raise SystemExit("font %s (%s) has no raster: open sizing.html (or raster.html?only=%s) through "
                         "python3 tools/fonts/rasterize.py and press Save" % (rid, where, rid))
    return pfont.PFont(label, rid, chars, bpp=2, alias=alias)


PF_NAME = layout_font("pf_name", "name", NAME_CHARS)
PF_STATUS = layout_font("pf_status", "status", STATUS_CHARS)
PF_MONO = layout_font("pf_mono", "tags", MONO_CHARS, MONO_ALIAS)   # the tags, and the volume page's small texts
PF_TAG = PF_MONO
PF_HVOL = layout_font("pf_hvol", "volume", "0123456789")
PF_ICON = layout_font("pf_icon", "icon", "SMH")
PF_BOX = pfont.PFont("pf_box", pfont.box_edges(LAYOUT["tags"]["height"]), "[]", bpp=2)   # the tag boxes' edges
PF_VNAME = raster_font("pf_vname", "disp36", VNAME_CHARS, "the volume page's name")
PF_VNUM = raster_font("pf_vnum", "num84", "0123456789", "the volume page's number")
PFONTS = (PF_NAME, PF_STATUS, PF_MONO, PF_HVOL, PF_ICON, PF_BOX, PF_VNAME, PF_VNUM)

# where things go: x, baseline -> the cell's top row y = baseline + the font's top
ICON_X, ICON_Y = LAYOUT["icon"]["x"], LAYOUT["icon"]["baseline"] + PF_ICON.top
HVOL_X, HVOL_Y = LAYOUT["volume"]["x"], LAYOUT["volume"]["baseline"] + PF_HVOL.top
ICON_END = HVOL_X - 2                               # icon cells are cleared up to here
HVOL_END = HVOL_X + max(PF_HVOL.width(str(v)) for v in range(61)) + 1   # the volume, cleared up to here
TAG_Y0 = LAYOUT["tags"]["top"]                      # the boxes' rows
TAG_Y1 = TAG_Y0 + LAYOUT["tags"]["height"] - 1
TAG_TY = LAYOUT["tags"]["baseline"] + PF_TAG.top    # the text's top row
TAG_PAD = LAYOUT["tags"]["pad"]                     # box edge to text, the edge included
EQ_RIGHT = LAYOUT["tags"]["right"]                  # the EQ box ends before this column ...
EQ_W = PF_TAG.width("SDB") + 2 * TAG_PAD            # ... (EQ tags are all 3 letters: one width)
EQ_X = EQ_RIGHT - EQ_W
FMT_RIGHT = EQ_X - LAYOUT["tags"]["gap"]            # the format box ends before this column
FMT_LEFT = FMT_RIGHT - (PF_TAG.width("MQA.") + 2 * TAG_PAD)   # the format tag's area (4 letters)
TAG_BASE = 192                                      # hm_tag keeps its columns as x - 192 (8 bits)
HNAME_X, HNAME_Y = LAYOUT["name"]["x"], LAYOUT["name"]["baseline"] + PF_NAME.top
NAME_SP = LAYOUT["name"]["spacing"]
STAT_X, STAT_Y = LAYOUT["status"]["x"], LAYOUT["status"]["baseline"] + PF_STATUS.top
STAT_SP = LAYOUT["status"]["spacing"]
DIM = uikit.rgb565(*(int(LAYOUT["status"]["colour"][k:k + 2], 16) for k in (1, 3, 5)))   # the status line
DIM_LOST = pfont.avg565(DIM, uikit.rgb565(0xFF, 0x50, 0x40))    # ... without a signal: the mock mixes in #ff5040
BAR_X, BAR_Y, BAR_W, BAR_H = (LAYOUT["bar"][k] for k in ("x", "y", "width", "height"))
assert all(PF_TAG.width(t) == PF_TAG.width("SDB") for t in ("DIR", "CUS", "BAS", "SBA", "RCK", "SFT", "CLR"))
assert FMT_LEFT >= TAG_BASE and EQ_RIGHT - TAG_BASE < 256 and 3 <= TAG_PAD
assert all((FMT_RIGHT - PF_TAG.width(t) - 2 * TAG_PAD) & 0xFF != 0xFF for t in ("PCM", "DSD", "DoP", "MQA", "MQA."))
assert TAG_Y0 < TAG_TY and TAG_TY + PF_TAG.H - 1 < TAG_Y1 and PF_BOX.H == TAG_Y1 - TAG_Y0 + 1
assert ICON_X + max(PF_ICON.width(c) for c in "SMH") - 1 <= ICON_END < HVOL_X and HVOL_END < FMT_LEFT
assert HNAME_Y + PF_NAME.H <= STAT_Y and STAT_Y + PF_STATUS.H <= BAR_Y and BAR_Y + BAR_H <= 170

# the volume page (the mock's, with the small texts in the tag size and the name at 36 px): the
# name and the status line left of a divider, "VOL" over the number right of it, the position line
# with the dB caption and "max 60" under it. x, baseline -> cell top row as above.
VNAME_X, VNAME_Y = 16, 64 + PF_VNAME.top
VNAME_SP = 1
VNAME_END = VNAME_X + max(PF_VNAME.width(t, VNAME_SP) for _, _, t in INPUT_NAMES[:6]) - 1
VSTAT_X, VSTAT_Y = 18, 90 + PF_MONO.top
VSTAT_SP = 0
VSTAT_END = VSTAT_X + PF_MONO.width("Digital input") - 1        # the widest status line
VDIV_X, VDIV_Y, VDIV_H = 150, 24, 92                            # the divider
VLBL_X, VLBL_Y, VLBL_SP = 164, 38 + PF_MONO.top, 3              # "VOL", letter-spaced, in the accent
VLBL_END = VLBL_X + PF_MONO.width("VOL", VLBL_SP) - 1
VNUM_RIGHT, VNUM_Y = 304, 112 + PF_VNUM.top                     # the number ends here (right-aligned)
VNUM_LEFT = VDIV_X + 6                                          # ... and its area starts here
VNUM_MAXW = max(PF_VNUM.width(str(v)) for v in range(61))
VLINE_X, VLINE_Y, VLINE_W, VLINE_H = 16, 136, 288, 3            # the position line: accent up to the split
VLINE_SPLIT = [VLINE_X + int(round(VLINE_W * v / 60)) for v in range(61)]   # first track column per volume
VLINE_MID = VLINE_X + 144                                        # hv_line fills the two halves separately (uk_fill: w <= 255)
VCAP_X, VCAP_Y = 16, 160 + PF_MONO.top                          # the dB caption, always 8 characters
VCAP_TEXTS = ("_75.5 dB", "  0.0 dB", "  _~ dB ")                 # the widest, the sign-less one, volume 0
VCAP_END = VCAP_X + max(PF_MONO.width(t) for t in VCAP_TEXTS) - 1
VCAPR_RIGHT = 304                                               # "max 60", right-aligned
VCAPR_X = VCAPR_RIGHT - PF_MONO.width("max 60") + 1
assert VNAME_END < VDIV_X and VSTAT_END < VDIV_X and VLBL_END < VNUM_RIGHT - VNUM_MAXW
assert VDIV_X < VNUM_LEFT <= VNUM_RIGHT - VNUM_MAXW and VNUM_RIGHT - VNUM_MAXW + 1 > VLBL_END
assert VLBL_Y + PF_MONO.H <= VNUM_Y and VNUM_Y + PF_VNUM.H <= VLINE_Y and VLINE_Y + VLINE_H <= VCAP_Y
assert VNAME_Y + PF_VNAME.H <= VSTAT_Y and VDIV_Y <= VLBL_Y and VSTAT_Y + PF_MONO.H <= VDIV_Y + VDIV_H
assert VCAP_Y + PF_MONO.H <= 170 and VCAP_END < VCAPR_X and VLINE_SPLIT[60] == VLINE_X + VLINE_W
assert VLINE_MID - VLINE_X <= 255 and VLINE_X + VLINE_W - VLINE_MID <= 255
assert all(PF_MONO.width(t) >= 8 * PF_MONO.width("0") for t in VCAP_TEXTS)   # 8 cells (the infinity is 1 px wider)

# ---- the number roll (the mock's this.k, 0.14 s): ROLL_FRAMES frames, one per tick. The panel is
# write-only and uk_text streams its cells, so two translucent numbers cannot be mixed: each frame
# draws one number on black, the old one while the mock's ease e < 0.5, then the new one, at the
# mock's offset for it (rounded to rows) and with its alpha as the ink (white * alpha, a grey), in
# the clip box ROLL_X0..ROLL_X1 x ROLL_Y0..ROLL_Y1 (the mock's 146..309 x 38..119, cut to the
# number's columns and to the rows between "VOL" and the position line).
ROLL_FRAMES = 14                                                # 0.14 s at one frame per 10 ms tick
ROLL_SHIFT = 20                                                 # the mock's shift, px
ROLL_X0, ROLL_X1 = VNUM_LEFT, VNUM_RIGHT
ROLL_Y0 = max(38, VLBL_Y + PF_MONO.H)                           # below "VOL"'s cell
ROLL_Y1 = min(38 + 82 - 1, VLINE_Y - 1)                         # above the position line


def roll_frames():
    """[(old?, dy for a step up, ink)] for frames 1..ROLL_FRAMES: e = 1 - (1 - k)^3, k = n / 14; the
    old number (alpha 1 - e, baseline - shift * e) while e < 0.5, else the new one (alpha e,
    baseline + shift * (1 - e)); a step down mirrors dy."""
    out = []
    for n in range(1, ROLL_FRAMES + 1):
        e = 1 - (1 - n / ROLL_FRAMES) ** 3
        old = e < 0.5
        dy = -ROLL_SHIFT * e if old else ROLL_SHIFT * (1 - e)
        g = int(math.floor(255 * ((1 - e) if old else e) + 0.5))
        out.append((old, int(math.floor(dy + 0.5)), uikit.rgb565(g, g, g)))
    return out


ROLL = roll_frames()
ROLL_OLD = sum(1 for f in ROLL if f[0])                          # frames 1..ROLL_OLD draw the old number
assert all(f[0] for f in ROLL[:ROLL_OLD]) and ROLL[-1] == (False, 0, WHITE)   # the last = hv_num's number
assert all(abs(dy) <= ROLL_SHIFT for _, dy, _ in ROLL)
# the box holds the number at every offset it is drawn at, and nothing else of the page
assert ROLL_Y0 <= VNUM_Y and VNUM_Y + PF_VNUM.H - 1 <= ROLL_Y1
assert VNUM_RIGHT - VNUM_MAXW + 1 > ROLL_X0       # hn_num_at fills the columns left of the number: never 0 wide
assert VLBL_Y + PF_MONO.H - 1 < ROLL_Y0 and ROLL_Y1 < VLINE_Y and VDIV_X < ROLL_X0
assert VCAP_Y > ROLL_Y1 and VNAME_END < ROLL_X0 and VSTAT_END < ROLL_X0
assert VNUM_RIGHT - min(PF_VNUM.width(str(v)) for v in range(61)) + 1 - ROLL_X0 <= 255   # uk_fill widths

# ---- the spring on the position line (the mock's spring(s, target, dt, 200, 28), integrated at
# 240 Hz): one step per 10 ms tick. Linear with the target fixed, so a tick is a 2 x 2 matrix on
# (position - target, velocity), composed from the mock's substeps; in fixed point: pixels * 64,
# velocity in pixels * 64 per tick, the products as Q16 fractions (hs_mulq). A tick with
# |error| < SPRING_SE and |velocity| < SPRING_SV settles on the target.
SPRING_K, SPRING_C, SPRING_DT = 200.0, 28.0, 0.01
SPRING_Q = 6
SPRING_SE, SPRING_SV = 32, 6


def spring_float_tick(x, v, target):
    """The mock's integrator over one 10 ms tick (x and v in pixels, pixels/s)."""
    n = math.ceil(SPRING_DT / (1 / 240))
    h = SPRING_DT / n
    for _ in range(n):
        acc = SPRING_K * (target - x) - SPRING_C * v
        v += acc * h
        x += v * h
    return x, v


def spring_matrix():
    m11, m21 = spring_float_tick(1.0, 0.0, 0.0)
    m12, m22 = spring_float_tick(0.0, 1 / SPRING_DT, 0.0)
    return m11, m12, m21 * SPRING_DT, m22 * SPRING_DT       # velocity in pixels per tick


_M = spring_matrix()
SPRING_K1 = int(round((1 - _M[0]) * 65536))                     # e' = e - e*K1 + V*K2
SPRING_K2 = int(round(_M[1] * 65536))
SPRING_K3 = int(round(-_M[2] * 65536))                          # V' = V*K4 - e*K3
SPRING_K4 = int(round(_M[3] * 65536))
assert all(0 < k < 65536 for k in (SPRING_K1, SPRING_K2, SPRING_K3, SPRING_K4))


def spring_target(v):
    """The line's fill for volume v in pixels, as hn_sp_t6 computes it: 4v + (4v + 2) / 5."""
    return 4 * v + (4 * v + 2) // 5


assert all(spring_target(v) == VLINE_SPLIT[v] - VLINE_X for v in range(61))

# volume-page elements: (bit, name, x0, x1); an element appears once the edge is left of x0
VF_NAME, VF_STAT, VF_DIV, VF_VOL, VF_NUM, VF_LINE, VF_CAP, VF_CAPR = 1, 2, 4, 8, 16, 32, 64, 128
VF_ALL = 255
VOL_ELEMENTS = [(VF_NAME, "hv_name", VNAME_X, VNAME_END), (VF_STAT, "hv_status", VSTAT_X, VSTAT_END),
                (VF_DIV, "hv_div", VDIV_X, VDIV_X), (VF_VOL, "hv_vol", VLBL_X, VLBL_END),
                (VF_NUM, "hv_num", VNUM_LEFT, VNUM_RIGHT), (VF_LINE, "hv_line", VLINE_X, VLINE_X + VLINE_W - 1),
                (VF_CAP, "hv_cap", VCAP_X, VCAP_END), (VF_CAPR, "hv_capr", VCAPR_X, VCAPR_RIGHT)]
# home elements: (bit, name, x0, x1); they appear once the edge is right of x1. The name and the
# status line end where their text ends: x1 is read from XDATA (HN_NAMER, HN_STATR) instead.
HF_ICON, HF_VOL, HF_BAR, HF_NAME, HF_FMT, HF_EQ, HF_STAT = 1, 2, 4, 8, 16, 32, 64
HF_ALL = 127
HOME_ELEMENTS = [(HF_ICON, "hh_icon", ICON_X, ICON_END), (HF_VOL, "hh_vol", HVOL_X, HVOL_END),
                 (HF_BAR, "hh_bar", 18, 45), (HF_NAME, "hh_name", 0, HN_NAMER),
                 (HF_FMT, "hh_fmt", FMT_LEFT, FMT_RIGHT - 1), (HF_EQ, "hh_eq", EQ_X, EQ_RIGHT - 1),
                 (HF_STAT, "hh_stat", 0, HN_STATR)]

STEPS = 32                          # ticks per wipe, both ways (the mock's entry: 0.32 s)
EDGE_MAX = 318
# the mock's cubic ease: edge x for entry step k (318 -> 0); the exit uses 318 - EASE[k]. Symmetric,
# so a reversal maps step k to STEPS - k at the same x. At both ends steps move the edge by 0 or
# 1 px: a step whose x is the previous x draws nothing (hn_step), so no band is ever 0 wide.
EASE = uikit.ease_cubic_in_out(STEPS, EDGE_MAX)
assert EASE[0] == EDGE_MAX and EASE[STEPS] == 0
assert all(EASE[k] + EASE[STEPS - k] == EDGE_MAX for k in range(STEPS + 1))
assert all(0 <= EASE[k] - EASE[k + 1] <= 253 for k in range(STEPS))    # bands of 0..253 (+ 2) columns
assert STEPS * 2 + 1 < 256                  # hn_step indexes the table with a byte

# (address, original bytes, new opcode, target label); the new bytes are opcode + target
HOOKS = [STOCK_SITES[site] + (op, target) for site, op, target in (
    ("page_clear", 0x12, "hn_clear"),
    ("page2_entry", 0x02, "hn_volpage"),
    ("volpage_draw_volume", 0x02, "hn_draw_volume"),
    ("big_text_start_x", 0x02, "hn_align_big"),
    ("small_text_start_x", 0x02, "hn_align_small"),
    ("home_refresh_tail", 0x02, "hn_home_tail"),
    ("tick", 0x12, "uk_tasks"),
    ("home_refresh_periodic", 0x02, "hn_hold"),
    ("ui_clear_screen", 0x02, "hn_cancel"),
    ("home_draw_input_name", 0x02, "hn_name_guard"),
    ("home_refresh_flag_path", 0x02, "hn_flag_path"),
    ("status_signal_check", 0x12, "hn_signal"),
    ("home_draw_output_icon", 0x02, "hm_icon"),
    ("home_draw_volume", 0x02, "hm_volume"),
    ("eq_tag_paint", 0x02, "hm_eq"),
    ("format_tag_paint", 0x12, "hm_fmt"),
    ("format_tag_clear", 0x02, "hm_fmt_clear"),
    ("format_tag_clear_changed", 0x12, "hm_fmt_clear"),
)]
HOOKS += features.hooks(INCLUDES)      # the fixes linked in: their hooks ...
FIX_PATCHES = features.patches(INCLUDES)   # ... and their in-place patches (strings: "Disconnected")
VERSION_TEXT = "v1.4 tbenr hn11.1"


rect = KIT.rect
fp_setup = KIT.fp_setup
tp_setup = KIT.tp_setup


# ---------------------------------------------------------------------------------------------
def build_data(a):
    a.comment("input-name pointers for inputs 1..6 (volume page), then the VOL label")
    a.L("names")
    for inp, addr, text in INPUT_NAMES[:6]:
        a.data("dw 0x%04X          ; input %d %s" % (addr, inp, text), [addr >> 8, addr & 0xFF])
    a.L("str_vol")
    a.data('db "VOL",0', b"VOL\0")
    a.L("str_max")
    a.data('db "max 60",0', b"max 60\0")
    a.L("str_dbinf")
    a.data('db "  _~ dB ",0     ; volume 0: minus infinity', b"  _~ dB \0")
    a.comment("number roll, frames 1..%d (frame %d is hv_num): cell row offset for a step up (a step down "
              "negates it), ink; frames 1..%d draw the old number" % (ROLL_FRAMES - 1, ROLL_FRAMES, ROLL_OLD))
    a.L("ro_tab")
    for n, (old, dy, ink) in enumerate(ROLL[:-1], 1):
        a.data("db %d,0x%02X,0x%02X ; frame %d: %s" % (dy, ink >> 8, ink & 0xFF, n, "old" if old else "new"),
               [dy & 0xFF, ink >> 8, ink & 0xFF])
    a.comment("spring constants (Q16): K2, K1 (position), K4, K3 (velocity), see hn_sp_lin")
    a.L("sp_kt")
    for k in (SPRING_K2, SPRING_K1, SPRING_K4, SPRING_K3):
        a.data("dw %d" % k, [k >> 8, k & 0xFF])
    a.comment("home_draw_input_name's strings for inputs 1..8 (0: none, the buffer is drawn as it is)")
    a.L("names8")
    tab = {inp: addr for inp, addr, _ in INPUT_NAMES}
    for inp in range(1, 9):
        v = tab.get(inp, 0)
        a.data("dw 0x%04X          ; input %d" % (v, inp), [v >> 8, v & 0xFF])
    a.comment("cubic-ease edge positions for the entry, steps 0..%d (the exit uses 318 - x)" % STEPS)
    a.L("ease")
    for k, v in enumerate(EASE):
        a.data("dw %d              ; step %d" % (v, k), [v >> 8, v & 0xFF])
    a.comment("icon and box-edge strings for uk_text")
    for lab, ch in (("hm_s_spk", "S"), ("hm_s_mute", "M"), ("hm_s_hp", "H"), ("hm_s_lb", "["), ("hm_s_rb", "]")):
        a.L(lab)
        a.data('db "%s",0' % ch, ch.encode() + b"\0")
    for f in PFONTS:
        f.emit(a)

def build_primitives(a):
    KIT.emit_fill(a)
    KIT.emit_accent(a, ORANGE)
    S(a, """
; hn_name_ptr: input 0x47 in 1..6 -> C=0, R2:R3 = name; else C=1
hn_name_ptr:
mov A,0x47
dec A
cjne A,#6,hnp_cmp  ; C = (input - 1 < 6)
hnp_cmp:
jnc hnp_none
rl A
mov B,A
mov DPTR,#names
movc A,@A+DPTR
mov R2,A
mov A,B
inc A
movc A,@A+DPTR
mov R3,A
clr C
ret
hnp_none:
setb C
ret
""")


def build_painter(a):
    assert all(f.bpp == 2 for f in PFONTS)
    KIT.emit_text(a, one_bit=False)     # uk_text only (run-length fonts): nothing here draws with the stock fonts


def build_volume_page(a):
    bit = {v: v.bit_length() - 1 for v in (VF_NUM, VF_LINE, VF_CAP)}
    S(a, """
; hn_draw_volume: replaces volpage_draw_volume 0x5936 (R7 speaker volume). Records the value
; (HN_VOL, HN_NUM; the text shown so far in HR_OLD). On the volume page, idle: the dB caption now,
; and a changed number rolls in from the next tick (hn_roll); the line's spring follows HN_VOL by
; itself (hn_spring). During a wipe: the number and the caption only if the wipe has revealed them
; (in their final state), else the wipe draws them when it reveals them. Page not on screen and no
; wipe: the number, the line and the caption at once (hn_dyn_now).
hn_draw_volume:
mov A,0x2B
xrl A,#1
jz hdv_spk
mov R7,0x52        ; headphone volume, as stock
hdv_spk:
mov A,R7
cjne A,#61,hdv_c
hdv_c:
jc hdv_ok
mov A,#60
hdv_ok:
mov R7,A
mov DPTR,#0x%04X""" % HN_NUM + """
movx A,@DPTR
mov R2,A
inc DPTR
movx A,@DPTR
mov R3,A
mov DPTR,#0x%04X""" % HR_OLD + """
mov A,R2
movx @DPTR,A
inc DPTR
mov A,R3
movx @DPTR,A
inc DPTR
clr A
movx @DPTR,A       ; HR_OLD = the text so far (two characters at most)
mov DPTR,#0x%04X""" % HN_VOL + """
movx A,@DPTR
mov R6,A           ; the volume so far
mov A,R7
movx @DPTR,A
inc DPTR           ; HN_NUM
lcall hn_dec2
mov R0,#5
mov A,#2
movx @R0,A         ; stock leaves the digit count 2 in XDATA 0x05
mov DPTR,#0x%04X""" % HN_MODE + """
movx A,@DPTR
jnz hdv_wipe
inc DPTR           ; HN_VF
movx A,@DPTR
cjne A,#%d,hn_dyn_now""" % VF_ALL + """
; the page is on screen: the number rolls if it changed (HR_DIR 1 when it went down)
mov A,R7
xrl A,R6
jz hdv_cap
mov A,R7
clr C
subb A,R6
clr A
rlc A
mov DPTR,#0x%04X""" % HR_DIR + """
movx @DPTR,A
mov DPTR,#0x%04X""" % HR_F + """
mov A,#1
movx @DPTR,A
hdv_cap:
ljmp hv_cap
hdv_wipe:
inc DPTR           ; HN_VF
movx A,@DPTR
push ACC
jnb ACC.%d,hdv_nonum""" % bit[VF_NUM] + """
lcall hv_num
hdv_nonum:
pop ACC
jnb ACC.%d,hdv_ret""" % bit[VF_CAP] + """
ljmp hv_cap
hdv_ret:
ret

; hn_dyn_now: the number, the line (the spring on its target) and the dB caption, at once
hn_dyn_now:
lcall hv_num
lcall hn_sp_snap
lcall hv_line
ljmp hv_cap

; hn_dec2: A (0..99) as decimal text at DPTR, no leading zero, then a NUL; DPTR ends after the NUL
hn_dec2:
mov B,#10
div AB             ; A tens, B ones
jz hd_one
add A,#0x30
movx @DPTR,A
inc DPTR
hd_one:
mov A,B
add A,#0x30
movx @DPTR,A
inc DPTR
clr A
movx @DPTR,A
inc DPTR
ret

; hn_roll: the number roll's frame for this tick (after hn_step and hn_spring): frame n of %d draws
; one number on black in the box %d..%d x %d..%d: the old one (HR_OLD) for n <= %d, then the new
; one (HN_NUM), shifted by ro_tab's rows (negated for a step down) in its grey; frame %d is hv_num.
; Only on the idle page (HN_MODE 0, HN_VF all); anything else stops it.
hn_roll:""" % (ROLL_FRAMES, ROLL_X0, ROLL_X1, ROLL_Y0, ROLL_Y1, ROLL_OLD, ROLL_FRAMES) + """
mov DPTR,#0x%04X""" % HR_F + """
movx A,@DPTR
jz ro_ret
mov R7,A
mov DPTR,#0x%04X""" % HN_MODE + """
movx A,@DPTR
jnz ro_stop
inc DPTR
movx A,@DPTR
cjne A,#%d,ro_stop""" % VF_ALL + """
mov A,R7
cjne A,#%d,ro_n""" % ROLL_FRAMES + """
ljmp hv_num        ; the last frame
ro_n:
jnc ro_stop        ; not a frame (XDATA after power-up)
inc A
mov DPTR,#0x%04X""" % HR_F + """
movx @DPTR,A
mov R2,%s""" % hi(HR_OLD) + """
mov R3,%s""" % lo(HR_OLD) + """
mov A,R7
cjne A,#%d,ro_c""" % (ROLL_OLD + 1) + """
ro_c:
jc ro_str
mov R2,%s""" % hi(HN_NUM) + """
mov R3,%s""" % lo(HN_NUM) + """
ro_str:
dec A
mov B,#3
mul AB
mov R5,A
mov DPTR,#ro_tab
movc A,@A+DPTR
mov R4,A           ; rows, for a step up
mov A,R5
inc A
movc A,@A+DPTR
mov R6,A
mov A,R5
inc A
inc A
movc A,@A+DPTR
mov R7,A           ; the ink
mov DPTR,#0x%04X""" % HR_DIR + """
movx A,@DPTR
jz ro_up
clr C
clr A
subb A,R4
mov R4,A
ro_up:
mov A,R4
add A,#%d""" % VNUM_Y + """
mov R4,A
sjmp hn_num_at
ro_stop:
clr A
mov DPTR,#0x%04X""" % HR_F + """
movx @DPTR,A
ro_ret:
ret

; hv_num: the number (HN_NUM) in the volume face, white, ending at x %d, cell top row %d (baseline
; %d), the rest of the box black; ends a roll
hv_num:""" % (VNUM_RIGHT, VNUM_Y, VNUM_Y - PF_VNUM.top) + """
clr A
mov DPTR,#0x%04X""" % HR_F + """
movx @DPTR,A
mov R2,%s""" % hi(HN_NUM) + """
mov R3,%s""" % lo(HN_NUM) + """
mov R4,#%d""" % VNUM_Y + """
mov R6,#0xFF
mov R7,#0xFF
; hn_num_at: the string at XDATA R2:R3 in the volume face, ink R6:R7 on black, right-aligned to end at
; x %d, cell top row R4, only inside the box %d..%d x %d..%d; then black in the rest of the box:
; columns %d up to the number over all its rows, the rows above and below the cell over the number's
hn_num_at:""" % (VNUM_RIGHT, ROLL_X0, ROLL_X1, ROLL_Y0, ROLL_Y1, ROLL_X0))
    tp_setup(a, "pf_vnum", None, 0, VNUM_RIGHT, 0, 0, clip=(ROLL_X0, ROLL_X1), align=1)
    S(a, """
mov DPTR,#0x%04X""" % KIT.TP["STR"] + """
mov A,R2
movx @DPTR,A
inc DPTR
mov A,R3
movx @DPTR,A
mov DPTR,#0x%04X""" % KIT.TP["Y"] + """
mov A,R4
movx @DPTR,A
inc DPTR
mov A,R6
movx @DPTR,A
inc DPTR
mov A,R7
movx @DPTR,A       ; TP_INK
mov DPTR,#0x%04X""" % KIT.TP["YC0"] + """
mov A,#%d""" % ROLL_Y0 + """
movx @DPTR,A
inc DPTR
mov A,#%d""" % ROLL_Y1 + """
movx @DPTR,A
lcall uk_textc     ; TP_X = the number's first column
; columns %d .. TP_X - 1, every row of the box""" % ROLL_X0 + """
mov DPTR,#0x%04X""" % (KIT.TP["X"] + 1) + """
movx A,@DPTR
clr C
subb A,%s""" % lo(ROLL_X0) + """
mov R1,A
mov R2,%s""" % hi(ROLL_X0) + """
mov R3,%s""" % lo(ROLL_X0) + """
mov R5,#%d""" % ROLL_Y0 + """
mov R4,#%d""" % (ROLL_Y1 - ROLL_Y0 + 1) + """
lcall hn_blk
; the rows above the cell: %d .. TP_Y - 1""" % ROLL_Y0 + """
mov DPTR,#0x%04X""" % KIT.TP["Y"] + """
movx A,@DPTR
clr C
subb A,#%d""" % ROLL_Y0 + """
jz hna_below
jc hna_below
mov R4,A
mov R5,#%d""" % ROLL_Y0 + """
lcall hna_fill
hna_below:
; the rows below it: TP_Y + H .. %d""" % ROLL_Y1 + """
mov DPTR,#0x%04X""" % KIT.TP["Y"] + """
movx A,@DPTR
add A,#%d""" % PF_VNUM.H + """
mov R5,A
mov A,#%d""" % (ROLL_Y1 + 1) + """
clr C
subb A,R5
jz hna_ret
jc hna_ret
mov R4,A
; hna_fill: black from TP_X to x %d, R4 rows from R5""" % ROLL_X1 + """
hna_fill:
mov DPTR,#0x%04X""" % KIT.TP["X"] + """
movx A,@DPTR
mov R2,A
inc DPTR
movx A,@DPTR
mov R3,A
mov A,%s""" % lo(ROLL_X1 + 1) + """
clr C
subb A,R3
mov R1,A           ; x %d - TP_X (under 256)""" % (ROLL_X1 + 1) + """
; hn_blk: uk_fill in black
hn_blk:
mov R6,#0
mov R7,#0
ljmp uk_fill
hna_ret:
ret
""")
    S(a, "; hv_name: the input name (inputs 1..6), display face at 36 px, white, at %d, baseline %d\nhv_name:"
         "\nlcall hn_name_ptr\njnc hvn_go\nret\nhvn_go:" % (VNAME_X, VNAME_Y - PF_VNAME.top))
    st16(a, KIT.TP["STR"], "R2", "R3")
    tp_setup(a, "pf_vname", None, 1, VNAME_X, VNAME_Y, WHITE, spacing=VNAME_SP)
    S(a, "ljmp uk_text")
    S(a, """
; hv_status: the status line, loaded as the periodic refresh loads it (hn_stat_load), mono, grey
; (reddish without a signal), at %d, baseline %d
hv_status:
lcall hn_stat_load""" % (VSTAT_X, VSTAT_Y - PF_MONO.top))
    tp_setup(a, "pf_mono", SMALL_BUF, 0, VSTAT_X, VSTAT_Y, DIM, spacing=VSTAT_SP)
    S(a, """
lcall hn_dim_ink
lcall uk_text
mov R6,%s""" % hi(VSTAT_END) + """
mov R7,%s""" % lo(VSTAT_END) + """
mov R5,#%d""" % VSTAT_Y + """
mov R4,#%d""" % PF_MONO.H + """
ljmp hq_go         ; black up to x %d (a redraw after a turned-round exit may be shorter), wipe or not""" % VSTAT_END + """

; hn_stat_load: XDATA 0x50 = the status line as home_refresh_periodic loads it (0x4016..0x407E: the
; signal check 0x5232, then the input's string or its sample rate). That code ends in the lcall
; home_refresh at 0x4081, which is hn_hold: with HN_SLD set it returns, to our caller.
hn_stat_load:
mov DPTR,#0x%04X""" % HN_SLD + """
mov A,#1
movx @DPTR,A
ljmp 0x4016

; hn_signal: replaces the status loader's lcall signal_check (0x4016): the check, its result kept
; in HN_SIG for the status line's colour (RAM 0x22.5 is reused by volume_apply, so it is not read
; back), C as the check left it
hn_signal:
lcall 0x5232
clr A
rlc A
mov DPTR,#0x%04X""" % HN_SIG + """
movx @DPTR,A
rrc A
ret

; hn_dim_ink: TP_INK = the status line's colour: DIM, or DIM_LOST when the loader's signal check found
; none (HN_SIG 0) on a digital input (0x47 not 6 or 8: the analogue inputs show "Analog input")
hn_dim_ink:
mov DPTR,#0x%04X""" % HN_SIG + """
movx A,@DPTR
jnz hdi_ret
mov A,0x47
cjne A,#6,hdi_n6
ret
hdi_n6:
cjne A,#8,hdi_lost
ret
hdi_lost:
mov DPTR,#0x%04X""" % KIT.TP["INK"] + """
mov A,%s""" % hi(DIM_LOST) + """
movx @DPTR,A
inc DPTR
mov A,%s""" % lo(DIM_LOST) + """
movx @DPTR,A
hdi_ret:
ret
""")
    S(a, "; hv_vol: \"VOL\" in the accent, mono, letter-spaced %d, at %d, baseline %d\nhv_vol:"
         % (VLBL_SP, VLBL_X, VLBL_Y - PF_MONO.top))
    tp_setup(a, "pf_mono", "str_vol", 1, VLBL_X, VLBL_Y, "acc", spacing=VLBL_SP)
    S(a, "ljmp uk_text")
    S(a, "; hv_capr: \"max 60\", mono, faint, ending at x %d, baseline %d\nhv_capr:" % (VCAPR_RIGHT, VCAP_Y - PF_MONO.top))
    tp_setup(a, "pf_mono", "str_max", 1, VCAPR_RIGHT, VCAP_Y, FAINT, align=1)
    S(a, "ljmp uk_text")
    S(a, "; hv_div: the divider, 1 x %d at %d,%d\nhv_div:" % (VDIV_H, VDIV_X, VDIV_Y))
    rect(a, VDIV_X, 1, VDIV_Y, VDIV_H, DIVIDER)
    S(a, "ljmp uk_fill")
    S(a, """
; hv_cap: the dB caption at %d, baseline %d, mono, grey: the volume's level below step 60 from the
; stock NJW1194 code table (0x9289: code = 35 + 2 * dB below step 60), as "_75.5 dB" .. "  0.0 dB"
; in HV_DB, always 8 characters (a shorter text draws its own background); "  _~ dB " at volume 0
hv_cap:""" % (VCAP_X, VCAP_Y - PF_MONO.top))
    tp_setup(a, "pf_mono", HV_DB, 0, VCAP_X, VCAP_Y, DIM)
    S(a, """
mov DPTR,#0x%04X""" % HN_VOL + """
movx A,@DPTR
jnz hvc_num""")
    st_imm16(a, KIT.TP["STR"], "str_dbinf")
    S(a, """
mov DPTR,#0x%04X""" % KIT.TP["SPC"] + """
mov A,#1
movx @DPTR,A       ; a code string
ljmp uk_text
hvc_num:
mov R7,A
mov A,#60
clr C
subb A,R7          ; 60 - volume
mov DPTR,#0x9289
movc A,@A+DPTR     ; the NJW1194 code
add A,#0xDD        ; - 35: half-dB steps below step 60 (0..151)
mov B,#2
div AB             ; A whole dB (0..75), B its half
mov R6,B
mov B,#10
div AB             ; A tens, B ones
mov DPTR,#0x%04X""" % HV_DB + """
mov R5,A
jnz hvc_tens
mov A,#0x20        ; under 10 dB: " _9.5 dB", or "  0.0 dB" at step 60
movx @DPTR,A
inc DPTR
mov A,B
orl A,R6
jnz hvc_sign
mov A,#0x20
sjmp hvc_ones
hvc_sign:
mov A,#0x5F        ; "_": the minus sign
sjmp hvc_ones
hvc_tens:
mov A,#0x5F
movx @DPTR,A
inc DPTR
mov A,R5
add A,#0x30
hvc_ones:
movx @DPTR,A
inc DPTR
mov A,B
add A,#0x30
movx @DPTR,A
inc DPTR
mov A,#0x2E        ; "."
movx @DPTR,A
inc DPTR
mov A,R6
jz hvc_half
mov A,#5
hvc_half:
add A,#0x30
movx @DPTR,A
inc DPTR
mov A,#0x20
movx @DPTR,A
inc DPTR
mov A,#0x64        ; "d"
movx @DPTR,A
inc DPTR
mov A,#0x42        ; "B"
movx @DPTR,A
inc DPTR
clr A
movx @DPTR,A
ljmp uk_text
""")
    S(a, "; hv_line: the whole position line, in two halves (uk_fill takes widths up to 255)\nhv_line:")
    st_imm16(a, HN_S0, VLINE_X)
    st_imm16(a, HN_S1, VLINE_MID - 1)
    S(a, "lcall hn_line_seg")
    st_imm16(a, HN_S0, VLINE_MID)
    st_imm16(a, HN_S1, VLINE_X + VLINE_W - 1)
    S(a, """
; hn_line_seg: the columns HN_S0..HN_S1 of the %d x %d position line at %d,%d: accent up to the split
; on screen (HN_SPL, the spring's), the track colour from it
hn_line_seg:""" % (VLINE_W, VLINE_H, VLINE_X, VLINE_Y) + """
; accent part: max(S0, %d) .. min(S1, split - 1)""" % VLINE_X + """
mov DPTR,#0x%04X""" % HN_S0 + """
movx A,@DPTR
mov R2,A
inc DPTR
movx A,@DPTR
mov R3,A
clr C
subb A,%s""" % lo(VLINE_X) + """
mov A,R2
subb A,%s""" % hi(VLINE_X) + """
jnc hl_a0
mov R2,%s""" % hi(VLINE_X) + """
mov R3,%s""" % lo(VLINE_X) + """
hl_a0:
mov DPTR,#0x%04X""" % HN_SPL + """
movx A,@DPTR
mov R4,A
inc DPTR
movx A,@DPTR
clr C
subb A,#1
mov R5,A
mov A,R4
subb A,#0
mov R4,A           ; R4:R5 = split - 1
lcall hl_minS1
lcall uk_acc
lcall hl_fill
; track part: max(S0, split) .. min(S1, %d)""" % (VLINE_X + VLINE_W - 1) + """
mov DPTR,#0x%04X""" % HN_SPL + """
movx A,@DPTR
mov R2,A
inc DPTR
movx A,@DPTR
mov R3,A
mov DPTR,#0x%04X""" % HN_S0 + """
movx A,@DPTR
mov R6,A
inc DPTR
movx A,@DPTR
mov R7,A
clr C
subb A,R3
mov A,R6
subb A,R2
jc hl_t0
mov A,R6
mov R2,A
mov A,R7
mov R3,A
hl_t0:
mov R4,%s""" % hi(VLINE_X + VLINE_W - 1) + """
mov R5,%s""" % lo(VLINE_X + VLINE_W - 1) + """
lcall hl_minS1
mov R6,%s""" % hi(TRACK) + """
mov R7,%s""" % lo(TRACK) + """
; hl_fill: fill R2:R3 .. R4:R5 (if not empty, at most 255 columns) at y %d, %d rows, colour R6:R7""" % (VLINE_Y, VLINE_H) + """
hl_fill:
clr C
mov A,R5
subb A,R3
mov R1,A
mov A,R4
subb A,R2
jc hl_none
inc R1
mov R5,#%d""" % VLINE_Y + """
mov R4,#%d""" % VLINE_H + """
ljmp uk_fill
hl_none:
ret
; hl_minS1: R4:R5 = min(R4:R5, HN_S1); keeps R2, R3
hl_minS1:
mov DPTR,#0x%04X""" % HN_S1 + """
movx A,@DPTR
mov R6,A
inc DPTR
movx A,@DPTR
mov R7,A
clr C
subb A,R5
mov A,R6
subb A,R4
jnc hl_m
mov A,R6
mov R4,A
mov A,R7
mov R5,A
hl_m:
ret

; hn_vol_static: the parts of the volume page that don't depend on the volume
hn_vol_static:
lcall hv_name
lcall hv_status
lcall hv_div
lcall hv_vol
ljmp hv_capr

; hn_volpage: page 2 renderer (replaces 0x2167). During a wipe it only records the volume. Idle: the
; whole page, the number and the line in their final state (no roll, the spring on its target).
hn_volpage:
mov DPTR,#0x%04X""" % HN_MODE + """
movx A,@DPTR
jnz hvp_wipe
inc DPTR
movx @DPTR,A       ; HN_VF 0: hn_draw_volume draws at once (hn_dyn_now)
lcall hn_vol_static
mov R7,0x31
lcall hn_draw_volume
mov DPTR,#0x%04X""" % HN_VF + """
mov A,#%d""" % VF_ALL + """
movx @DPTR,A
ljmp 0x22FA        ; clears 0x22.3, 0x32, 0x46 like every page
hvp_wipe:
mov R7,0x31
lcall hn_draw_volume
ljmp 0x22FA
""")
    S(a, """
; hn_spring: the line's spring, one tick (after hn_step): on the idle page (HN_MODE 0, HN_VF all)
; and during the entry towards the volume's fill (hn_sp_t6), during the exit towards 0. Position SP_P
; and velocity SP_V in pixels * 64; the tick is the mock's integrator over 10 ms as a matrix
; (hn_sp_lin, constants sp_kt); |error| < %d and |velocity| < %d settle on the target. Then the
; columns between the split on screen (HN_SPL) and the new one are redrawn (hn_line_seg); during a
; wipe only right of the edge (x + 2 on): the band's own draw uses HN_SPL.
hn_spring:""" % (SPRING_SE, SPRING_SV) + """
mov DPTR,#0x%04X""" % HN_MODE + """
movx A,@DPTR
jnz sp_w
inc DPTR
movx A,@DPTR
cjne A,#%d,sp_r""" % VF_ALL + """
sjmp sp_vol
sp_w:
cjne A,#2,sp_n2
mov R4,#0          ; exit: towards 0
mov R5,#0
sjmp sp_go
sp_r:
ret
sp_n2:
cjne A,#1,sp_r
sp_vol:
lcall hn_sp_t6
sp_go:
mov DPTR,#0x%04X""" % SP_T + """
mov A,R4
movx @DPTR,A
inc DPTR
mov A,R5
movx @DPTR,A
; SP_E = SP_P - target; nothing to do when it and SP_V are 0
mov DPTR,#0x%04X""" % SP_P + """
movx A,@DPTR
mov R2,A
inc DPTR
movx A,@DPTR
clr C
subb A,R5
mov R3,A
mov A,R2
subb A,R4
mov R2,A
mov DPTR,#0x%04X""" % SP_E + """
movx @DPTR,A
inc DPTR
mov A,R3
movx @DPTR,A
orl A,R2
mov R0,A
mov DPTR,#0x%04X""" % SP_V + """
movx A,@DPTR
orl A,R0
mov R0,A
inc DPTR
movx A,@DPTR
orl A,R0
jz sp_r
; the position's step (V K2 - e K1), then the new velocity (V K4 - e K3)
mov R0,#0
lcall hn_sp_lin
push 0x02
push 0x03
lcall hn_sp_lin
mov DPTR,#0x%04X""" % SP_V + """
mov A,R2
movx @DPTR,A
inc DPTR
mov A,R3
movx @DPTR,A
; F0: |V| < %d""" % SPRING_SV + """
clr F0
add A,#%d""" % (SPRING_SV - 1) + """
mov A,R2
addc A,#0
jnz sp_vbig
mov A,R3
add A,#%d""" % (SPRING_SV - 1) + """
clr C
subb A,#%d""" % (2 * SPRING_SV - 1) + """
jnc sp_vbig
setb F0
sp_vbig:
pop 0x03
pop 0x02
mov DPTR,#0x%04X""" % (SP_P + 1) + """
movx A,@DPTR
add A,R3
movx @DPTR,A
mov DPTR,#0x%04X""" % SP_P + """
movx A,@DPTR
addc A,R2
movx @DPTR,A       ; SP_P += step
; the new error, e + step: settled when |e| < %d and F0""" % SPRING_SE + """
mov DPTR,#0x%04X""" % (SP_E + 1) + """
movx A,@DPTR
add A,R3
mov R3,A
mov DPTR,#0x%04X""" % SP_E + """
movx A,@DPTR
addc A,R2
mov R2,A
mov A,R3
add A,#%d""" % (SPRING_SE - 1) + """
mov R3,A
mov A,R2
addc A,#0
jnz sp_draw
mov A,R3
clr C
subb A,#%d""" % (2 * SPRING_SE - 1) + """
jnc sp_draw
jnb F0,sp_draw
mov DPTR,#0x%04X""" % SP_T + """
movx A,@DPTR
mov R2,A
inc DPTR
movx A,@DPTR
mov DPTR,#0x%04X""" % (SP_P + 1) + """
movx @DPTR,A
mov DPTR,#0x%04X""" % SP_P + """
mov A,R2
movx @DPTR,A       ; on the target
inc DPTR
inc DPTR
clr A
movx @DPTR,A
inc DPTR
movx @DPTR,A       ; SP_V 0
sp_draw:
clr F0
mov DPTR,#0x%04X""" % SP_P + """
movx A,@DPTR
mov R2,A
inc DPTR
movx A,@DPTR
mov R3,A
lcall hn_sp_split     ; R6:R7 the new split
mov DPTR,#0x%04X""" % HN_SPL + """
movx A,@DPTR
mov R4,A
inc DPTR
movx A,@DPTR
mov R5,A           ; the split on screen
mov DPTR,#0x%04X""" % HN_SPL + """
mov A,R6
movx @DPTR,A
inc DPTR
mov A,R7
movx @DPTR,A
; the columns from the lower split to the higher one - 1
clr C
mov A,R7
subb A,R5
mov A,R6
subb A,R4
jnc sp_up
mov A,R6
xch A,R4
mov R6,A
mov A,R7
xch A,R5
mov R7,A
sp_up:
mov A,R4
mov R2,A
mov A,R5
mov R3,A           ; R2:R3 from
mov A,R7
clr C
subb A,#1
mov R7,A
mov A,R6
subb A,#0
mov R6,A           ; R6:R7 to
mov DPTR,#0x%04X""" % HN_MODE + """
movx A,@DPTR
jz sp_seg
; during a wipe from the edge's x + 2 on
mov DPTR,#0x%04X""" % HN_X + """
movx A,@DPTR
mov R4,A
inc DPTR
movx A,@DPTR
add A,#2
mov R5,A
clr A
addc A,R4
mov R4,A
clr C
mov A,R3
subb A,R5
mov A,R2
subb A,R4
jnc sp_seg
mov A,R4
mov R2,A
mov A,R5
mov R3,A
sp_seg:
clr C
mov A,R7
subb A,R3
mov A,R6
subb A,R2
jc sp_ret         ; nothing to draw
mov DPTR,#0x%04X""" % HN_S0 + """
mov A,R2
movx @DPTR,A
inc DPTR
mov A,R3
movx @DPTR,A
inc DPTR
mov A,R6
movx @DPTR,A
inc DPTR
mov A,R7
movx @DPTR,A
ljmp hn_line_seg
sp_ret:
ret

; hn_sp_lin: R2:R3 = SP_V * k[R0] - SP_E * k[R0 + 1] (sp_kt, Q16), R0 += 4
hn_sp_lin:
lcall hn_sp_k
mov DPTR,#0x%04X""" % SP_V + """
lcall hn_sp_mulx
mov DPTR,#0x%04X""" % SP_W + """
mov A,R2
movx @DPTR,A
inc DPTR
mov A,R3
movx @DPTR,A
lcall hn_sp_k
mov DPTR,#0x%04X""" % SP_E + """
lcall hn_sp_mulx
mov DPTR,#0x%04X""" % (SP_W + 1) + """
movx A,@DPTR
clr C
subb A,R3
mov R3,A
mov DPTR,#0x%04X""" % SP_W + """
movx A,@DPTR
subb A,R2
mov R2,A
ret
; hn_sp_k: R4:R5 = the constant at sp_kt + R0, R0 += 2
hn_sp_k:
mov DPTR,#sp_kt
mov A,R0
movc A,@A+DPTR
mov R4,A
inc R0
mov A,R0
movc A,@A+DPTR
mov R5,A
inc R0
ret
; hn_sp_mulx: R2:R3 = the signed word at DPTR * R4:R5 / 65536, rounded half away from 0; keeps R0
hn_sp_mulx:
movx A,@DPTR
mov R2,A
inc DPTR
movx A,@DPTR
mov R3,A
mov A,R2
mov C,ACC.7
mov F1,C
jnc spm_pos
clr C
clr A
subb A,R3
mov R3,A
clr A
subb A,R2
mov R2,A
spm_pos:
mov A,R3
mov B,R5
mul AB
mov R6,B           ; bits 8..15
mov A,R2
mov B,R5
mul AB
add A,R6
mov R6,A
mov A,B
addc A,#0
mov R7,A           ; bits 16..23
mov A,R3
mov B,R4
mul AB
add A,R6
mov R6,A
mov A,B
addc A,R7
mov R7,A
clr A
addc A,#0
mov R1,A           ; bits 24..31
mov A,R2
mov B,R4
mul AB
add A,R7
mov R7,A
mov A,B
addc A,R1
mov R1,A
mov A,R6
rlc A              ; C = bit 15: round
mov A,R7
addc A,#0
mov R3,A
mov A,R1
addc A,#0
mov R2,A
jnb F1,spm_ret
clr C
clr A
subb A,R3
mov R3,A
clr A
subb A,R2
mov R2,A
spm_ret:
clr F1
ret

; hn_sp_t6: R4:R5 = 64 * the line's fill for HN_VOL (4v + (4v + 2) / 5 = round(4.8 v))
hn_sp_t6:
mov DPTR,#0x%04X""" % HN_VOL + """
movx A,@DPTR
rl A
rl A
mov R7,A
add A,#2
mov B,#5
div AB
add A,R7
mov R5,A
clr A
rlc A
mov R4,A
mov R1,#6
spt_sh:
mov A,R5
add A,R5
mov R5,A
mov A,R4
rlc A
mov R4,A
djnz R1,spt_sh
ret

; hn_sp_split: R6:R7 = the split column for position R2:R3: 16 + round(position / 64), 0..288 px
hn_sp_split:
mov A,R3
add A,#%d""" % (1 << (SPRING_Q - 1)) + """
mov R3,A
mov A,R2
addc A,#0
jb ACC.7,sps_0
mov R2,A
mov A,R3
add A,R3
mov R3,A
mov A,R2
rlc A
mov R2,A
mov A,R3
add A,R3
mov A,R2
rlc A
mov R7,A
clr A
rlc A
mov R6,A           ; position / 64
clr C
mov A,%s""" % lo(VLINE_W) + """
subb A,R7
mov A,%s""" % hi(VLINE_W) + """
subb A,R6
jnc sps_ok
mov R6,%s""" % hi(VLINE_W) + """
mov R7,%s""" % lo(VLINE_W) + """
sps_ok:
mov A,R7
add A,#%d""" % VLINE_X + """
mov R7,A
mov A,R6
addc A,#0
mov R6,A
ret
sps_0:
mov R6,#0
mov R7,#%d""" % VLINE_X + """
ret

; hn_sp_snap: the spring on its target, still (SP_P, SP_V, HN_SPL); nothing drawn
hn_sp_snap:
lcall hn_sp_t6
mov DPTR,#0x%04X""" % SP_P + """
mov A,R4
mov R2,A
movx @DPTR,A
inc DPTR
mov A,R5
mov R3,A
movx @DPTR,A
inc DPTR
clr A
movx @DPTR,A
inc DPTR
movx @DPTR,A
lcall hn_sp_split
sjmp hn_sp_spl
; hn_sp_reset: the spring at 0, still, the line's split at x %d (the home: nothing of the line shown)""" % VLINE_X + """
hn_sp_reset:
mov DPTR,#0x%04X""" % SP_P + """
clr A
movx @DPTR,A
inc DPTR
movx @DPTR,A
inc DPTR
movx @DPTR,A
inc DPTR
movx @DPTR,A
mov R6,A
mov R7,#%d""" % VLINE_X + """
hn_sp_spl:
mov DPTR,#0x%04X""" % HN_SPL + """
mov A,R6
movx @DPTR,A
inc DPTR
mov A,R7
movx @DPTR,A
ret
""")


def build_wipe(a):
    S(a, """
; hn_enter_vol: page 2 is being opened (the four volume-key sites, and hn_clear with page 2).
; Draws nothing: starts the wipe from x 318, reverses a running exit at its x, or does nothing when
; the entry runs already or the page is on screen. Clears the text buffers as ui_clear_screen did.
hn_enter_vol:
mov DPTR,#0x%04X""" % HN_MODE + """
movx A,@DPTR
cjne A,#1,he_n1
ret                ; entering already
he_n1:
jnz he_rev         ; exiting: turn round
inc DPTR           ; HN_VF
movx A,@DPTR
cjne A,#%d,he_start""" % VF_ALL + """
ret                ; the page is on screen
he_start:
lcall hn_sp_reset  ; the line's fill grows from 0
mov DPTR,#0x%04X""" % HN_VF + """
clr A
movx @DPTR,A       ; nothing of the page drawn yet
mov DPTR,#0x%04X""" % HN_STEP + """
movx @DPTR,A
mov DPTR,#0x%04X""" % HN_X + """
mov A,#0x01
movx @DPTR,A
inc DPTR
mov A,#0x3E        ; x = 318
movx @DPTR,A
sjmp he_go
he_rev:
lcall hn_reverse
jz he_done         ; the exit had not drawn yet: the page is still on screen
he_go:
mov DPTR,#0x%04X""" % HN_MODE + """
mov A,#1
movx @DPTR,A
he_done:
lcall 0x5CBC       ; ui_clear_small_buf, as ui_clear_screen
ljmp 0x5CCB        ; ui_clear_big_buf

; hn_reverse: step = STEPS - step (the ease table is symmetric, so x stays); A = new step, and at
; STEPS (the running wipe had not stepped) the wipe stops: mode 0. The status line counts as not drawn:
; an exit clears its buffer, so an entry turned round from one loads and draws it again.
hn_reverse:
mov DPTR,#0x%04X""" % HN_VF + """
movx A,@DPTR
anl A,#0x%02X""" % (0xFF ^ VF_STAT) + """
movx @DPTR,A
mov DPTR,#0x%04X""" % HN_STEP + """
movx A,@DPTR
mov R7,A
mov A,#%d""" % STEPS + """
clr C
subb A,R7
movx @DPTR,A
cjne A,#%d,hr_ret""" % STEPS + """
mov DPTR,#0x%04X""" % HN_MODE + """
clr A
movx @DPTR,A
ret
hr_ret:
mov A,#1
ret

; hn_clear: replaces lcall ui_clear_screen at 0x2106 (ui_render_page); page in 0x59
hn_clear:
mov A,0x59
cjne A,#2,hc_n2
ljmp hn_enter_vol
hc_n2:
cjne A,#1,hc_stock
mov DPTR,#0x%04X""" % HN_MODE + """
movx A,@DPTR
cjne A,#2,hc_p1
sjmp hc_stock      ; an exit runs already: cancel it, stock clear
hc_p1:
jnz hc_rev         ; entering: turn round
inc DPTR           ; HN_VF
movx A,@DPTR
cjne A,#%d,hc_stock""" % VF_ALL + """
; the volume page is on screen: wipe back home from x 0; a roll ends on its last frame first
mov DPTR,#0x%04X""" % HR_F + """
movx A,@DPTR
jz hc_noroll
lcall hv_num
hc_noroll:
mov DPTR,#0x%04X""" % HN_STEP + """
clr A
movx @DPTR,A
mov DPTR,#0x%04X""" % HN_X + """
movx @DPTR,A
inc DPTR
movx @DPTR,A
sjmp hc_go
hc_rev:
lcall hn_reverse
jz hc_bufs
hc_go:
mov DPTR,#0x%04X""" % HN_MODE + """
mov A,#2
movx @DPTR,A
inc DPTR
inc DPTR           ; HN_HF
clr A
movx @DPTR,A
mov DPTR,#0x%04X""" % HN_SBUF + """
movx @DPTR,A       ; the stock refresh has not loaded the status line yet
hc_bufs:
lcall 0x5CBC       ; the text buffers, as ui_clear_screen
lcall 0x5CCB
; the input name as home_draw_input_name loads it, and where it ends
lcall hn_name_load
lcall hm_name_meas
mov DPTR,#0x%04X""" % KIT.TP["END"] + """
movx A,@DPTR
mov R6,A
inc DPTR
movx A,@DPTR
mov R7,A
mov DPTR,#0x%04X""" % HN_NAMER + """
mov A,R6
movx @DPTR,A
inc DPTR
mov A,R7
movx @DPTR,A
ret
hc_stock:
ljmp 0x5D42        ; ui_clear_screen (hn_cancel first)

; hn_stop: no wipe, no page drawn (HN_MODE, HN_VF, HN_HF 0), no roll, the spring at home
hn_stop:
mov DPTR,#0x%04X""" % HR_F + """
clr A
movx @DPTR,A
mov DPTR,#0x%04X""" % HN_MODE + """
movx @DPTR,A       ; HN_MODE
inc DPTR
movx @DPTR,A       ; HN_VF
inc DPTR
movx @DPTR,A       ; HN_HF
ljmp hn_sp_reset

; hn_cancel: ui_clear_screen's first instruction; every stock clear stops a wipe (and a roll) first
hn_cancel:
lcall hn_stop
lcall 0x5CBC       ; the instruction the hook replaced
ljmp 0x5D45

; hn_hold: replaces the periodic refresh's lcall home_refresh at 0x4081 (0x3FE3): while a wipe
; runs, skip home_refresh and the status line (0x4084..0x4088) and note that the status buffer
; (XDATA 0x50) has just been loaded. When hn_stat_load ran the loader (HN_SLD), return to its caller.
hn_hold:
mov DPTR,#0x%04X""" % HN_SLD + """
movx A,@DPTR
jz hh_refresh
clr A
movx @DPTR,A
ret                ; to hn_stat_load's caller
hh_refresh:
mov DPTR,#0x%04X""" % HN_MODE + """
movx A,@DPTR
jz hh_stock
mov DPTR,#0x%04X""" % HN_SBUF + """
mov A,#1
movx @DPTR,A
ret                ; 0x3FE3's own return (0x4088 is a tail jump)
; hh_stock: home_refresh, then the status line as the loader left it: the draw at 0x4084 is marked as
; the loader's (HN_SIG bit 1), so hm_status_r keeps the tint the signal check decided
hh_stock:
lcall 0x5C8B       ; home_refresh
mov DPTR,#0x%04X""" % HN_SIG + """
movx A,@DPTR
orl A,#2
movx @DPTR,A
ljmp 0x4084        ; mov R7,#0x87 ; mov R6,#0 ; ljmp small_text_render

; hn_name_guard: home_draw_input_name's entry. A name drawn on page 1 during an exit (Source,
; direct-select, input_apply, key_bt_function's home_refresh) would draw over the half-revealed
; screen, and the stock sequence may already have drawn other home parts. So the exit ends here
; with the whole home screen as the held-back refresh would draw it (hn_home_now), then the stock
; name draw goes on.
hn_name_guard:
mov DPTR,#0x%04X""" % HN_MODE + """
movx A,@DPTR
cjne A,#2,hg_go
lcall hn_home_now
hg_go:
mov A,0x47
dec A
ljmp 0x4A88

; hn_home_now: stop the wipe, black screen, then home_refresh and the status line from XDATA 0x50
; as home_refresh_periodic draws them (hh_stock; the text buffers are kept: the status line is the
; stock one, in the tint of the loader's last check)
hn_home_now:
lcall hn_stop      ; HN_MODE 0 first, so the name draw inside home_refresh passes the guard
lcall 0x51EE       ; lcd_clear_black
ljmp hh_stock

; hn_flag_path: home_refresh_periodic's flag path (0x3FF8, taken when 0x21.3, 0x21.1 or 0x20.6 is set,
; e.g. after Source: they stay set until this refresh, so across a volume page too). Stock clears the
; flags, sets page 1 and blacks out x 0..239, y 43..169 (0x412F, 125 ms) before loading the status
; line and drawing home. During a wipe that fill would erase parts the exit has revealed (and holes
; in the volume page right of the edge); the wipe owns the screen, so skip the fill and go on with
; the status line (0x4016) and the refresh, which hn_hold holds back: the exit draws the home.
hn_flag_path:
clr 0x21.3         ; the two instructions the hook replaced
clr 0x20.6
mov DPTR,#0x%04X""" % HN_MODE + """
movx A,@DPTR
jnz hfp_wipe
ljmp 0x3FFC
hfp_wipe:
clr 0x21.1         ; 0x3FFC..0x3FFF: clr 0x21.1, page 1; the fill (0x4001..0x4013) is skipped
mov 0x45,#1
ljmp 0x4016

; hn_name_load: XDATA 0x35 = the input name, as home_draw_input_name loads it (input 7 and out of
; range: the buffer is left as it is)
hn_name_load:
mov A,0x47
dec A
cjne A,#8,hnl_c
hnl_c:
jnc hnl_ret
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
jz hnl_ret
mov R3,#0xFF       ; code space
clr A
mov R5,A
mov R7,A
ljmp 0x4C8F        ; big_text_load
hnl_ret:
ret
""")
    S(a, """
; home elements, each as the stock routine for that part draws it
hh_icon:
ljmp 0x5744        ; home_draw_output_icon
hh_vol:
mov R7,0x31
ljmp 0x5916        ; home_draw_volume
hh_fmt:
ljmp 0x41CA        ; home_draw_format_tag
hh_eq:
ljmp 0x49A1        ; home_draw_eq_tag
hh_bar:
lcall uk_acc""")
    rect(a, BAR_X, BAR_W, BAR_Y, BAR_H)
    S(a, """
ljmp uk_fill
hh_name:
ljmp hm_name
""")

    # ---- the step ----
    KIT.emit_tick_driver(a, "hs_ret")        # uk_tasks falls through into hn_step
    S(a, """
; hn_step: one step of the running wipe; then, in every tick, the spring and the roll (hn_after).
; Order in a tick: the stock tick work (uk_tasks), the wipe step, the line's spring (it redraws only
; right of the edge the step has just drawn), the roll (idle page only: never in a wipe's tick).
hn_step:
mov DPTR,#0x%04X""" % HN_MODE + """
movx A,@DPTR
jz hs_idle
cjne A,#3,hs_mc
hs_mc:
jc hs_mok
clr A              ; not a mode: stop
movx @DPTR,A
hs_idle:
ljmp hn_after
hs_ret:
ret
hs_mok:
mov R7,A           ; mode
; the previous x
mov DPTR,#0x%04X""" % HN_X + """
movx A,@DPTR
mov R2,A
inc DPTR
movx A,@DPTR
mov R3,A
mov DPTR,#0x%04X""" % HN_XP + """
mov A,R2
movx @DPTR,A
inc DPTR
mov A,R3
movx @DPTR,A
; the next step and its x
mov DPTR,#0x%04X""" % HN_STEP + """
movx A,@DPTR
inc A
cjne A,#%d,hs_sc""" % (STEPS + 1) + """
hs_sc:
jc hs_sok
mov A,#%d""" % STEPS + """
hs_sok:
movx @DPTR,A
rl A
mov R6,A
mov DPTR,#ease
movc A,@A+DPTR
mov R4,A
mov A,R6
inc A
movc A,@A+DPTR
mov R5,A           ; R4:R5 = ease[step]
cjne R7,#2,hs_x
clr C              ; exit: 318 - ease[step]
mov A,#0x3E
subb A,R5
mov R5,A
mov A,#0x01
subb A,R4
mov R4,A
hs_x:
mov DPTR,#0x%04X""" % HN_X + """
mov A,R4
movx @DPTR,A
inc DPTR
mov A,R5
movx @DPTR,A
""")
    # band, damage, limit per mode
    S(a, """
mov DPTR,#0x%04X""" % HN_STEP + """
movx A,@DPTR
cjne A,#%d,hs_mid""" % STEPS + """
; last step: the band runs to the screen edge, no edge is drawn, everything is revealed
cjne R7,#1,hs_lastx
; entry: band 0 .. xp + 1, limit 0
mov R4,#0
mov R5,#0
lcall hs_xp1
mov R2,#0
mov R3,#0
sjmp hs_set
hs_lastx:
; exit: band xp .. 319, limit 320
lcall hs_xp
mov R6,#0x01
mov R7,#0x3F
mov R2,#0x01
mov R3,#0x40
sjmp hs_set
hs_mid:
; a step that does not move the edge (the cubic's ends: x = previous x) draws and reveals nothing
mov A,R5
xrl A,R3
jnz hs_moves       ; (x and previous x differ by less than 256)
ljmp hs_end
hs_moves:
cjne R7,#1,hs_midx
; entry: band x + 2 .. xp + 1, damage from x, limit x + 2
lcall hs_x2
mov A,R4
mov R2,A
mov A,R5
mov R3,A
lcall hs_xp1
sjmp hs_setd
hs_midx:
; exit: band xp .. x - 1, damage to x + 1, limit x
lcall hs_xp
mov DPTR,#0x%04X""" % HN_X + """
movx A,@DPTR
mov R2,A
inc DPTR
movx A,@DPTR
mov R3,A
clr C
subb A,#1
mov R7,A
mov A,R2
subb A,#0
mov R6,A
sjmp hs_setd
; R4:R5 band start, R6:R7 band end, R2:R3 limit; damage = band
hs_set:
lcall hs_store
lcall hs_dmg_band
sjmp hs_draw
hs_setd:
lcall hs_store
lcall hs_dmg_band
; the edge columns x, x + 1 are damaged too
mov DPTR,#0x%04X""" % HN_X + """
movx A,@DPTR
mov R2,A
inc DPTR
movx A,@DPTR
mov R3,A
mov DPTR,#0x%04X""" % HN_D0 + """
movx A,@DPTR
mov R4,A
inc DPTR
movx A,@DPTR
clr C
subb A,R3
mov A,R4
subb A,R2
jc hs_d0ok         ; d0 < x
mov DPTR,#0x%04X""" % HN_D0 + """
mov A,R2
movx @DPTR,A
inc DPTR
mov A,R3
movx @DPTR,A
hs_d0ok:
mov A,R3
add A,#1
mov R3,A
clr A
addc A,R2
mov R2,A           ; x + 1
mov DPTR,#0x%04X""" % HN_D1 + """
movx A,@DPTR
mov R4,A
inc DPTR
movx A,@DPTR
clr C
subb A,R3
mov A,R4
subb A,R2
jnc hs_draw        ; d1 >= x + 1
mov DPTR,#0x%04X""" % HN_D1 + """
mov A,R2
movx @DPTR,A
inc DPTR
mov A,R3
movx @DPTR,A
""")
    S(a, """
hs_draw:
; the new edge first (columns x, x+1, outside the band), unless this is the last step: the old
; edge is only erased by the band after it, so GRAM always holds a whole edge while the panel scans
mov DPTR,#0x%04X""" % HN_STEP + """
movx A,@DPTR
cjne A,#%d,hs_edge""" % STEPS + """
sjmp hs_band
hs_edge:
mov DPTR,#0x%04X""" % HN_X + """
movx A,@DPTR
mov R2,A
inc DPTR
movx A,@DPTR
mov R3,A
mov R1,#2
mov R5,#0
mov R4,#170
lcall uk_acc
lcall uk_fill
hs_band:
; the band, black, with the old edge's two columns last: on the way in they are the band's top
; end (uk_fill goes up in x); on the way out its bottom end, so the rest goes first
mov DPTR,#0x%04X""" % HN_B0 + """
movx A,@DPTR
mov R2,A
inc DPTR
movx A,@DPTR
mov R3,A
inc DPTR
inc DPTR
movx A,@DPTR       ; HN_B1 lo
clr C
subb A,R3
inc A
mov R1,A           ; width (2..255)
mov DPTR,#0x%04X""" % HN_MODE + """
movx A,@DPTR
cjne A,#2,hs_band1
mov A,R1
cjne A,#3,hs_bc
hs_bc:
jc hs_band1        ; 2 px: just the old edge
add A,#0xFE
mov R1,A           ; width - 2
mov A,R3
add A,#2
mov R3,A
clr A
addc A,R2
mov R2,A           ; from B0 + 2
lcall hs_black
mov DPTR,#0x%04X""" % HN_B0 + """
movx A,@DPTR
mov R2,A
inc DPTR
movx A,@DPTR
mov R3,A
mov R1,#2          ; then the old edge, B0 and B0 + 1
hs_band1:
lcall hs_black
""")
    # invalidate
    S(a, "; elements the band or the edge touched are no longer on screen")
    ld16(a, "R4", "R5", HN_D0)
    ld16(a, "R6", "R7", HN_D1)
    for flags, elems in ((HN_VF, VOL_ELEMENTS), (HN_HF, HOME_ELEMENTS)):
        for bit, name, x0, x1 in elems:
            skip = "inv_%s" % name
            S(a, """
clr C
mov A,R7
subb A,%s
mov A,R6
subb A,%s
jc %s""" % (lo(x0), hi(x0), skip))
            if name in ("hh_name", "hh_stat"):      # x1 in XDATA
                S(a, """
mov DPTR,#0x%04X
movx A,@DPTR
mov R2,A
inc DPTR
movx A,@DPTR
clr C
subb A,R5
mov A,R2
subb A,R4
jc %s""" % (x1, skip))
            else:
                S(a, """
clr C
mov A,%s
subb A,R5
mov A,%s
subb A,R4
jc %s""" % (lo(x1), hi(x1), skip))
            S(a, """
mov DPTR,#0x%04X
movx A,@DPTR
anl A,#0x%02X
movx @DPTR,A
%s:""" % (flags, 0xFF ^ bit, skip))
    S(a, """
mov DPTR,#0x%04X""" % HN_MODE + """
movx A,@DPTR
cjne A,#1,hs_noline
; entry: the part of the position line inside the band
mov DPTR,#0x%04X""" % HN_B0 + """
movx A,@DPTR
mov R4,A
inc DPTR
movx A,@DPTR
mov R5,A
inc DPTR
movx A,@DPTR
mov R6,A
inc DPTR
movx A,@DPTR
mov R7,A
mov DPTR,#0x%04X""" % HN_S0 + """
mov A,R4
movx @DPTR,A
inc DPTR
mov A,R5
movx @DPTR,A
inc DPTR
mov A,R6
movx @DPTR,A
inc DPTR
mov A,R7
movx @DPTR,A
lcall hn_line_seg
hs_noline:
hs_reveal:
mov DPTR,#0x%04X""" % HN_MODE + """
movx A,@DPTR
cjne A,#1,hs_to_rvx
sjmp hs_rve
hs_to_rvx:
ljmp hs_rvx
hs_rve:
""")
    # entry reveal
    S(a, """
; what the entry had drawn when this step began
mov DPTR,#0x%04X
movx A,@DPTR
mov DPTR,#0x%04X
movx @DPTR,A""" % (HN_VF, HN_HF0))
    for bit, name, x0, x1 in VOL_ELEMENTS:
        skip = "rv_%s" % name
        S(a, """
mov DPTR,#0x%04X
movx A,@DPTR
anl A,#0x%02X
jnz %s""" % (HN_VF, bit, skip))
        if name == "hv_status":
            S(a, """
; the name, the status line (with its load) and the line reach x 16..18 together: if the name was
; drawn in this step, the status line waits for the next one (the last step draws whatever is left)
mov DPTR,#0x%04X""" % HN_STEP + """
movx A,@DPTR
xrl A,#%d""" % STEPS + """
jz re_split_ok
mov DPTR,#0x%04X""" % HN_VF + """
movx A,@DPTR
mov R2,A
mov DPTR,#0x%04X""" % HN_HF0 + """
movx A,@DPTR
xrl A,R2
anl A,#0x%02X""" % VF_NAME + """
jnz %s""" % skip + """
re_split_ok:""")
        S(a, """
mov DPTR,#0x%04X
movx A,@DPTR
mov R6,A
inc DPTR
movx A,@DPTR
mov R7,A
clr C
mov A,%s
subb A,R7
mov A,%s
subb A,R6
jc %s
lcall %s
mov DPTR,#0x%04X
movx A,@DPTR
orl A,#0x%02X
movx @DPTR,A
%s:""" % (HN_LIM, lo(x0), hi(x0), skip, name, HN_VF, bit, skip))
    S(a, "ljmp hs_end\nhs_rvx:")
    S(a, """
; what the exit had drawn when this step began
mov DPTR,#0x%04X
movx A,@DPTR
mov DPTR,#0x%04X
movx @DPTR,A""" % (HN_HF, HN_HF0))
    # exit reveal
    for bit, name, x0, x1 in HOME_ELEMENTS:
        skip = "rv_%s" % name
        S(a, """
mov DPTR,#0x%04X
movx A,@DPTR
anl A,#0x%02X
jnz %s""" % (HN_HF, bit, skip))
        if name == "hh_name":
            ld16(a, "R2", "R3", HN_NAMER)
        elif name == "hh_stat":
            S(a, """
; the big name and the status line in one step take over 8 ms: if the name was drawn in this
; step, the status line waits for the next one (the last step draws whatever is left)
mov DPTR,#0x%04X""" % HN_STEP + """
movx A,@DPTR
xrl A,#%d""" % STEPS + """
jz rs_split_ok
mov DPTR,#0x%04X""" % HN_HF + """
movx A,@DPTR
mov R2,A
mov DPTR,#0x%04X""" % HN_HF0 + """
movx A,@DPTR
xrl A,R2
anl A,#0x%02X""" % HF_NAME + """
jnz %s""" % skip + """
rs_split_ok:
mov DPTR,#0x%04X""" % HN_SBUF + """
movx A,@DPTR
jnz rs_ready
mov DPTR,#0x%04X""" % HN_STEP + """
movx A,@DPTR
cjne A,#%d,%s""" % (STEPS, skip) + """
rs_ready:
lcall hm_stat_meas""")
            ld16(a, "R2", "R3", KIT.TP["END"])
        else:
            S(a, "mov R2,%s\nmov R3,%s" % (hi(x1), lo(x1)))
        S(a, """
mov DPTR,#0x%04X
movx A,@DPTR
mov R6,A
inc DPTR
movx A,@DPTR
mov R7,A
clr C
mov A,R3
subb A,R7
mov A,R2
subb A,R6
jnc %s""" % (HN_LIM, skip))
        if name == "hh_stat":
            st16(a, HN_STATR, "R2", "R3")
            S(a, "lcall hm_status")
        else:
            S(a, "lcall %s" % name)
        S(a, """
mov DPTR,#0x%04X
movx A,@DPTR
orl A,#0x%02X
movx @DPTR,A
%s:""" % (HN_HF, bit, skip))
    S(a, """
hs_end:
; the last step ends the wipe
mov DPTR,#0x%04X""" % HN_STEP + """
movx A,@DPTR
cjne A,#%d,hs_done""" % STEPS + """
mov DPTR,#0x%04X""" % HN_MODE + """
movx A,@DPTR
mov R7,A
clr A
movx @DPTR,A
inc DPTR           ; HN_VF
cjne R7,#2,hs_done
movx @DPTR,A       ; home: the volume page is gone
lcall hn_sp_reset     ; and the spring with it
hs_done:
; hn_after: the line's spring, then the number roll
hn_after:
lcall hn_spring
ljmp hn_roll

; step helpers
hs_xp:             ; R4:R5 = previous x
mov DPTR,#0x%04X""" % HN_XP + """
movx A,@DPTR
mov R4,A
inc DPTR
movx A,@DPTR
mov R5,A
ret
hs_xp1:            ; R6:R7 = previous x + 1
mov DPTR,#0x%04X""" % HN_XP + """
movx A,@DPTR
mov R6,A
inc DPTR
movx A,@DPTR
add A,#1
mov R7,A
clr A
addc A,R6
mov R6,A
ret
hs_x2:             ; R4:R5 = x + 2
mov DPTR,#0x%04X""" % HN_X + """
movx A,@DPTR
mov R4,A
inc DPTR
movx A,@DPTR
add A,#2
mov R5,A
clr A
addc A,R4
mov R4,A
ret
hs_store:          ; HN_B0 = R4:R5, HN_B1 = R6:R7, HN_LIM = R2:R3
mov DPTR,#0x%04X""" % HN_LIM + """
mov A,R2
movx @DPTR,A
inc DPTR
mov A,R3
movx @DPTR,A
mov DPTR,#0x%04X""" % HN_B0 + """
mov A,R4
movx @DPTR,A
inc DPTR
mov A,R5
movx @DPTR,A
inc DPTR
mov A,R6
movx @DPTR,A
inc DPTR
mov A,R7
movx @DPTR,A
ret
hs_black:          ; R2:R3 x, R1 width: full-height black
mov R5,#0
mov R4,#170
mov R6,#0
mov R7,#0
ljmp uk_fill
hs_dmg_band:       ; damage = band (HN_D0 = R4:R5, HN_D1 = R6:R7)
mov DPTR,#0x%04X""" % HN_D0 + """
mov A,R4
movx @DPTR,A
inc DPTR
mov A,R5
movx @DPTR,A
inc DPTR
mov A,R6
movx @DPTR,A
inc DPTR
mov A,R7
movx @DPTR,A
ret
""")


def build_home(a):
    S(a, """
; hn_home_tail: replaces home_refresh's ljmp 0x5916; adds the accent bar
hn_home_tail:
lcall 0x5916       ; the volume (hm_volume), R7 = volume
lcall uk_acc""")
    rect(a, BAR_X, BAR_W, BAR_Y, BAR_H)
    S(a, "ljmp uk_fill")
    for name, back, y, draw in (("hn_align_big", 0x2A28, NAME_Y, "hm_name"),
                                ("hn_align_small", 0x3A85, uikit.STATUS_Y, "hm_status_r")):
        S(a, """
; %s: on page 1, the text at the stock y %d is ours (%s, then return from the stock renderer:
; nothing is pushed at this point); other page-1 texts start at x 16 (XDATA 0x04:0x05)
%s:
mov A,0x45
cjne A,#1,%s_x
mov R0,#0
movx A,@R0         ; y hi
jnz %s_left
inc R0
movx A,@R0         ; y lo
cjne A,#%d,%s_left
ljmp %s
%s_left:
mov R0,#4
movx A,@R0         ; start x hi
jnz %s_x
inc R0
movx A,@R0         ; start x lo
clr C
subb A,#16
jc %s_x            ; wider than 288 px: keep it centred
mov A,#16
movx @R0,A         ; start x = 16
%s_x:
clr A              ; the two instructions the hook replaced
mov R0,#2
ljmp 0x%04X
""" % (name, y, draw, name, name, name, y, name, draw, name, name, name, name, back))

    S(a, "; hm_name: the input name (XDATA 0x35), display face, white, at x 16, baseline 104\nhm_name:")
    tp_setup(a, "pf_name", BIG_BUF, 0, HNAME_X, HNAME_Y, WHITE, spacing=NAME_SP)
    S(a, "lcall uk_text")
    S(a, "mov R6,#1\nmov R7,#0x3F\nmov R5,#%d\nmov R4,#%d\nljmp hm_rest" % (HNAME_Y, PF_NAME.H))
    S(a, "; hm_name_meas: TP_END = where hm_name's text ends (nothing drawn)\nhm_name_meas:")
    tp_setup(a, "pf_name", BIG_BUF, 0, HNAME_X, HNAME_Y, WHITE, clip=(0x100, 0), spacing=NAME_SP)
    S(a, "ljmp uk_text")
    S(a, """
; hm_status_r: small_text_render's hand-over on page 1 at y 135. The reddish tint belongs to the text
; the status loader decided with its signal check (HN_SIG 0). Only the periodic refresh's own draw
; shows that text (hh_stock marks it: HN_SIG bit 1). Every other caller has put its own text into
; XDATA 0x50 (input_apply's placeholder 0x4C29, the BT key 0x10A1, eq_show 0x396A, 0x532E): grey,
; HN_SIG 1, until the loader runs again. Falls into hm_status.
hm_status_r:
mov DPTR,#0x%04X""" % HN_SIG + """
movx A,@DPTR
jb ACC.1,hsr_loader
mov A,#1
hsr_loader:
anl A,#1
movx @DPTR,A""")
    S(a, "; hm_status: the status line (XDATA 0x50), mono, grey (reddish without a signal, hn_dim_ink), "
         "at x %d, baseline %d\nhm_status:" % (STAT_X, STAT_Y - PF_STATUS.top))
    tp_setup(a, "pf_status", SMALL_BUF, 0, STAT_X, STAT_Y, DIM, spacing=STAT_SP)
    S(a, "lcall hn_dim_ink\nlcall uk_text")
    S(a, "mov R6,#1\nmov R7,#0x3F\nmov R5,#%d\nmov R4,#%d\nljmp hm_rest" % (STAT_Y, PF_STATUS.H))
    S(a, "; hm_stat_meas: TP_END = where hm_status's text ends\nhm_stat_meas:")
    tp_setup(a, "pf_status", SMALL_BUF, 0, STAT_X, STAT_Y, DIM, clip=(0x100, 0), spacing=STAT_SP)
    S(a, "ljmp uk_text")

    S(a, """
; hm_rest: black from TP_END + 1 to R6:R7 (the element's last column), rows R5 .. R5 + R4 - 1: the
; rest of a shorter text than before. Not during a wipe: the wipe owns the screen, and its band
; is black already.
hm_rest:
mov DPTR,#0x%04X""" % HN_MODE + """
movx A,@DPTR
jz hq_go
ret
hq_go:
mov DPTR,#0x%04X""" % HM_RL + """
mov A,R6
movx @DPTR,A
inc DPTR
mov A,R7
movx @DPTR,A
inc DPTR
mov A,R5
movx @DPTR,A       ; HM_RY
inc DPTR
mov A,R4
movx @DPTR,A       ; HM_RH
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
hq_loop:
; done when x > limit
mov DPTR,#0x%04X""" % HM_RL + """
movx A,@DPTR
mov R6,A
inc DPTR
movx A,@DPTR
mov R7,A
clr C
subb A,R3
mov R1,A           ; limit - x (lo)
mov A,R6
subb A,R2
jc hq_ret
jnz hq_wide        ; 256 columns or more left
mov A,R1
inc A
jnz hq_w
hq_wide:
mov A,#255
hq_w:
mov R1,A           ; width
mov DPTR,#0x%04X""" % HM_RX + """
mov A,R1
add A,R3
mov R7,A
clr A
addc A,R2
movx @DPTR,A
inc DPTR
mov A,R7
movx @DPTR,A       ; HM_RX = x + width
mov DPTR,#0x%04X""" % HM_RY + """
movx A,@DPTR
mov R5,A
inc DPTR
movx A,@DPTR
mov R4,A
mov R6,#0
mov R7,#0
lcall uk_fill
mov DPTR,#0x%04X""" % HM_RX + """
movx A,@DPTR
mov R2,A
inc DPTR
movx A,@DPTR
mov R3,A
sjmp hq_loop
hq_ret:
ret

; hm_icon: replaces home_draw_output_icon 0x5744: the mock's speaker (red with an X when muted,
; 0x22.1) or headphones (g_output 0x2B not 1) at 12,9
hm_icon:
mov R0,#6
jnb 0x22.1,hmi_on
mov A,#1
movx @R0,A         ; XDATA 6 = the stock icon number, as stock
""")
    tp_setup(a, "pf_icon", "hm_s_mute", 1, ICON_X, ICON_Y, RED)
    S(a, "ljmp hmi_draw\nhmi_on:\nmov A,0x2B\nxrl A,#1\njz hmi_spk\nmov A,#2\nmovx @R0,A")
    tp_setup(a, "pf_icon", "hm_s_hp", 1, ICON_X, ICON_Y, WHITE)
    S(a, "ljmp hmi_draw\nhmi_spk:\nmov A,#3\nmovx @R0,A")
    tp_setup(a, "pf_icon", "hm_s_spk", 1, ICON_X, ICON_Y, WHITE)
    S(a, "hmi_draw:\nlcall uk_text")
    S(a, "mov R6,#0\nmov R7,#%d\nmov R5,#%d\nmov R4,#%d\nljmp hm_rest" % (ICON_END, ICON_Y, PF_ICON.H))

    S(a, """
; hm_volume: replaces home_draw_volume 0x5916 (R7 speaker volume; the headphone volume 0x52 when
; g_output is not 1): no leading zero, white, at 36, baseline 24
hm_volume:
mov A,0x2B
xrl A,#1
jz hmv_spk
mov R7,0x52
hmv_spk:
mov R0,#5
mov A,#2
movx @R0,A         ; XDATA 5 = 2, as stock
mov A,R7
mov DPTR,#0x%04X""" % HM_VS + """
lcall hn_dec2
""")
    tp_setup(a, "pf_hvol", HM_VS, 0, HVOL_X, HVOL_Y, WHITE)
    S(a, "lcall uk_text")
    S(a, "mov R6,#0\nmov R7,#%d\nmov R5,#%d\nmov R4,#%d\nljmp hm_rest" % (HVOL_END, HVOL_Y, PF_HVOL.H))

    S(a, """
; hm_eq: replaces the EQ tag's paint 0x4F18 (string R3:R2:R1): a box ending before x %d""" % EQ_RIGHT + """
hm_eq:
lcall hm_tag_copy
mov A,#%d""" % (EQ_RIGHT - TAG_BASE) + """
mov R6,#%d""" % (EQ_X - TAG_BASE) + """
sjmp hm_tag
; hm_fmt: replaces home_draw_format_tag's lcall 0x4F20 (string R3:R2:R1): a box ending before x %d""" % FMT_RIGHT + """
hm_fmt:
lcall hm_tag_copy
mov A,#%d""" % (FMT_RIGHT - TAG_BASE) + """
mov R6,#%d""" % (FMT_LEFT - TAG_BASE) + """
; hm_tag: the text in HM_TAG in the accent, mono, centred in a 1-px accent box 2 * TAG_PAD wider than it
; and ending before x A + 192; black from x R6 + 192 up to the box (HM_TR, HM_TL, HM_TX: x - 192)
hm_tag:
mov DPTR,#0x%04X""" % HM_TR + """
movx @DPTR,A
inc DPTR
mov A,R6
movx @DPTR,A       ; HM_TL
""")
    tp_setup(a, "pf_mono", HM_TAG, 0, 0, TAG_TY, WHITE, clip=(0x100, 0))
    S(a, """
lcall uk_text      ; measure: TP_END = width - 1
mov DPTR,#0x%04X""" % (KIT.TP["END"] + 1) + """
movx A,@DPTR
inc A
mov R7,A           ; text width
mov DPTR,#0x%04X""" % HM_TWD + """
movx @DPTR,A
add A,#%d""" % (2 * TAG_PAD) + """
mov R6,A           ; box width
mov DPTR,#0x%04X""" % HM_TW + """
movx @DPTR,A
mov DPTR,#0x%04X""" % HM_TR + """
movx A,@DPTR
clr C
subb A,R6
mov DPTR,#0x%04X""" % HM_TX + """
movx @DPTR,A       ; box x
; black from HM_TL to the box
mov R7,A
mov DPTR,#0x%04X""" % HM_TL + """
movx A,@DPTR
mov R6,A
mov A,R7
clr C
subb A,R6
jz ht_box
jc ht_box
mov R1,A
mov A,R6
add A,#%d""" % TAG_BASE + """
mov R3,A
clr A
addc A,#0
mov R2,A
mov R5,#%d""" % TAG_Y0 + """
mov R4,#%d""" % (TAG_Y1 - TAG_Y0 + 1) + """
mov R6,#0
mov R7,#0
lcall uk_fill
ht_box:
; the box, in the accent: its left and right edges with the rounded corners (ht_edges), then the
; top and bottom rows between them (x + 2 .. x + w - 3)
lcall ht_edges
lcall ht_xw2
mov R5,#%d""" % TAG_Y0 + """
mov R4,#1
lcall ht_acc
lcall ht_xw2
mov R5,#%d""" % TAG_Y1 + """
mov R4,#1
lcall ht_acc
; the inside around the text, black: the rows above and below the text's cell (if any) from x + 2
; to x + w - 3 (the edge glyphs cover x + 1 and x + w - 2), TAG_PAD - 2 columns left and right of it""")
    for y, rows in ((TAG_Y0 + 1, TAG_TY - TAG_Y0 - 1), (TAG_TY + PF_TAG.H, TAG_Y1 - TAG_TY - PF_TAG.H)):
        assert rows >= 0
        if rows:                                   # uk_fill takes no empty fill
            S(a, "lcall ht_xw2\nmov R5,#%d\nmov R4,#%d\nlcall ht_black" % (y, rows))
    S(a, """
lcall ht_xw2
mov R1,#%d""" % (TAG_PAD - 2) + """
mov R5,#%d""" % TAG_TY + """
mov R4,#%d""" % PF_TAG.H + """
lcall ht_black
lcall ht_xw
mov DPTR,#0x%04X""" % HM_TWD + """
movx A,@DPTR
add A,#%d""" % TAG_PAD + """
add A,R3
mov R3,A
clr A
addc A,R2
mov R2,A           ; x + pad + text width
mov R1,#%d""" % (TAG_PAD - 2) + """
mov R5,#%d""" % TAG_TY + """
mov R4,#%d""" % PF_TAG.H + """
lcall ht_black
; the text at x + pad""")
    tp_setup(a, "pf_mono", HM_TAG, 0, None, TAG_TY, "acc")
    S(a, """
mov DPTR,#0x%04X""" % HM_TX + """
movx A,@DPTR
add A,#%d""" % (TAG_PAD + TAG_BASE) + """
mov R7,A
clr A
addc A,#0
mov DPTR,#0x%04X""" % KIT.TP["X"] + """
movx @DPTR,A
inc DPTR
mov A,R7
movx @DPTR,A
ljmp uk_text
; ht_edges: the box's left and right edges, two columns each with corners of radius 2 (pf_box: "["
; at x, "]" at x + w - 2), in the accent
ht_edges:""")
    tp_setup(a, "pf_box", "hm_s_lb", 1, None, TAG_Y0, "acc")
    S(a, """
lcall ht_xw""")
    st16(a, KIT.TP["X"], "R2", "R3")
    S(a, "lcall uk_text")
    st_imm16(a, KIT.TP["STR"], "hm_s_rb")
    S(a, """
lcall ht_xw
mov A,R1
dec A
dec A
add A,R3
mov R3,A
clr A
addc A,R2
mov R2,A           ; x + w - 2""")
    st16(a, KIT.TP["X"], "R2", "R3")
    S(a, """
ljmp uk_text
; ht_xw: R2:R3 = box x, R1 = A = box width
ht_xw:
mov DPTR,#0x%04X""" % HM_TX + """
movx A,@DPTR
add A,#%d""" % TAG_BASE + """
mov R3,A
clr A
addc A,#0
mov R2,A
inc DPTR
movx A,@DPTR
mov R1,A
ret
; ht_xw2: R2:R3 = box x + 2, R1 = A = box width - 4 (the box is at least 2 * TAG_PAD wide)
ht_xw2:
lcall ht_xw
mov A,R3
add A,#2
mov R3,A
clr A
addc A,R2
mov R2,A
mov A,R1
add A,#0xFC
mov R1,A
ret
ht_acc:
push 0x01          ; uk_acc keeps R1..R5
lcall uk_acc
pop 0x01
ljmp uk_fill
ht_black:
mov R6,#0
mov R7,#0
ljmp uk_fill

; hm_tag_copy: HM_TAG = the string at R3:R2:R1 (R3 0xFF: code, else XDATA), at most 5 characters,
; trailing spaces cut
hm_tag_copy:
mov DPH,R2
mov DPL,R1
mov R4,#0          ; characters copied
mov R5,#0          ; length up to the last non-space
htc_loop:
cjne R3,#0xFF,htc_x
clr A
movc A,@A+DPTR
sjmp htc_got
htc_x:
movx A,@DPTR
htc_got:
jz htc_end
inc DPTR
mov R6,A
push DPH
push DPL
mov A,R4
add A,%s""" % lo(HM_TAG) + """
mov DPL,A
clr A
addc A,%s""" % hi(HM_TAG) + """
mov DPH,A
mov A,R6
movx @DPTR,A
pop DPL
pop DPH
inc R4
cjne R6,#0x20,htc_ns
sjmp htc_sp
htc_ns:
mov A,R4
mov R5,A
htc_sp:
cjne R4,#5,htc_loop
htc_end:
mov A,R5
add A,%s""" % lo(HM_TAG) + """
mov DPL,A
clr A
addc A,%s""" % hi(HM_TAG) + """
mov DPH,A
clr A
movx @DPTR,A
ret

; hm_fmt_clear: replaces home_draw_format_tag's clears (0x0026): the format tag's area, black
hm_fmt_clear:""")
    rect(a, FMT_LEFT, FMT_RIGHT - FMT_LEFT, TAG_Y0, TAG_Y1 - TAG_Y0 + 1, 0)
    S(a, "ljmp uk_fill")


def build(a):
    build_data(a)
    build_primitives(a)
    build_painter(a)
    build_volume_page(a)
    build_wipe(a)
    build_home(a)


def assemble():
    a = Asm(CODE_ADDR)
    build(a)
    features.emit(a, INCLUDES)
    code = a.resolve()
    return code, a.labels, a


def main():
    base = open(sys.argv[1] if len(sys.argv) > 1 else BASE_IMAGE, "rb").read()
    asserts = [(addr, text.encode() + b"\0", "input name %d moved" % inp) for inp, addr, text in INPUT_NAMES]
    asserts += [
        (0x2A28, b"\xF2", "movx @R0,A after the align hooks moved"),
        (0x3A85, b"\xF2", "movx @R0,A after the align hooks moved"),
        # the instructions the new hooks jump back past
        (0x4084, bytes.fromhex("7f877e00") + b"\x02", "0x4084 not as expected"),
        (0x5D45, bytes.fromhex("125ccb"), "ui_clear_screen's second call moved"),
        (0x4A88, bytes.fromhex("b40800"), "home_draw_input_name's cjne moved"),
        (0x3FF8, bytes.fromhex("c20bc206c209"), "home_refresh_periodic's flag path moved"),
        (0x4A9B + 3 * 6, bytes.fromhex("024aef"), "input 7 draws the buffer as it is"),
        # uk_tasks does main_tick_tasks' re-mute part itself and returns when no tick is due
        (0x3325, bytes.fromhex("300c07c20cc2141258d320070302345b"), "main_tick_tasks' re-mute request part moved"),
        (0x345B, b"\x22", "main_tick_tasks without a tick no longer only returns"),
    ]
    # home_draw_input_name's table (0x4A9B) loads the strings INPUT_NAMES lists
    for inp, addr, text in INPUT_NAMES:
        t = (base[0x4A9B + 3 * (inp - 1) + 1] << 8) | base[0x4A9B + 3 * (inp - 1) + 2]
        asserts.append((t, bytes([0x7B, 0xFF, 0x7A, addr >> 8, 0x79, addr & 0xFF]), "name table %d" % inp))
    patches = [(s, VOL_ENTRY_ORIG, lambda labels: vol_entry_bytes(labels["hn_enter_vol"]),
                "lcall hn_enter_vol ; sjmp 0x%04X" % (s + len(VOL_ENTRY_ORIG))) for s in VOL_ENTRY_SITES]
    patches += FIX_PATCHES
    uikit.build_image(base_path=sys.argv[1] if len(sys.argv) > 1 else BASE_IMAGE, base_sha=BASE_SHA,
                      code_addr=CODE_ADDR, assemble=assemble, hooks=HOOKS, patches=patches, asserts=asserts,
                      version_text=VERSION_TEXT, out_image=OUT_IMAGE, out_listing=OUT_LISTING,
                      title="House Numerals patch", label_prefixes=("hn_", "uk_"))


if __name__ == "__main__":
    main()
