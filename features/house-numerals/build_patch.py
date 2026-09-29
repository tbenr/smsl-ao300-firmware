#!/usr/bin/env python3
"""Build the "House Numerals" image for the SMSL AO300 (on top of fast-lcd), hn5.

A reduced build of study 3 in features/ui-theme/ui_themes.html:

  home      the mock's home, drawn by us in the mock's typefaces (uk_text, fonts packed from
            tools/fonts by pfont): the speaker icon (red with an X when muted, headphones on
            the headphone output) and the volume top left, the format and EQ tags as accent
            boxes top right, the input name in the display face, the status line in grey mono
            under it and a 28x3 accent bar at 18,144. Each stock painter of a home element is
            replaced by ours (icon 0x5744, volume 0x5916, EQ tag 0x4F18, format tag 0x425D and
            its clears), and on page 1 the stock text renderers hand the name (big, y 75) and
            the status line (small, y 135) to us (0x2A25, 0x3A82). So every stock sequence that
            draws home parts draws ours. A shorter text clears the rest of the longer one.
  volume    the input name, a divider, "VOL", the volume in the stock big digits at
            2x and a 240-px position line. volpage_draw_volume 0x5936 is replaced, so
            knob and remote steps redraw only the number and the line.
  wipes     a 2-px accent edge sweeps across the screen with an ease-in-out, 20 steps of
            one 10 ms main-loop tick each: right to left into the volume page, left to
            right back home. Nothing blocks: the main loop's tick path (main_tasks_on's
            lcall main_tick_tasks, 0x5B2A) runs one step after each tick it handles. Each
            step fills the band the edge swept with black, draws the edge and draws every
            element of the new page the edge has fully passed (hn_step).
  text      uk_text (the mock's faces) for the home; uk_paint (the stock fonts) for the
            volume page's name, "VOL" and number.

Entry: the four volume-key sites and the page-2 renderer only start the animation
(hn_enter_vol); the key handler's tail still writes the volume before anything is drawn.
Exit: the Timer0 return home sets page 1 and 0x22.3; ui_render_page's clear (0x2106, hn_clear)
starts the exit instead of clearing, and home_refresh at 0x4081 (hn_hold) is held back while a
wipe runs. Any stock clear (ui_clear_screen 0x5D42, hn_cancel) cancels a wipe first; so does
the name draw 0x4A85 during an exit (Source and direct-select on page 1, hn_name_guard).

Register use: every hn_* / hm_* routine may clobber A, B, DPTR, PSW and R0-R7 (the stock
routines they replace or wrap do the same). RAM 0x48:0x49 (the theme colour) is only read.
New state lives in XDATA 0x0100..0x01A6.
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
INCLUDES = ["fix-auto-off"]         # fix features linked into this image
BASE_IMAGE = features.image(BASE)
BASE_SHA = "b292a64855975584dda5fe3fb282103bfde77f7f7237ca9945ac4b5442dae859"
OUT_IMAGE = os.path.join(HERE, "build", "flash_house_numerals.bin")
OUT_LISTING = os.path.join(HERE, "house_numerals.asm")

CODE_ADDR = 0x9800                  # after fast-lcd (code 0x9700..0x976B, version string)

# colours (RGB565)
ORANGE = 0xFC43                     # #ff8a1f, accent on the White theme
DIVIDER = 0x2104                    # #222
TRACK = 0x18E3                      # #1d1d1d
WHITE = 0xFFFF
RED = 0xF800                        # #ff0000, the muted icon

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
HN_SPL = 0x0121                     # hn_line_seg: 40 + 4 * volume
HN_STATR = 0x0123                   # exit: right end of the status line as drawn
TP_BASE = 0x0160                    # uk_text's parameter block and work area (50 bytes)
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

# uk_fill's work area (HN_N, HN_C) and uk_paint's parameter block and work area (FP..FP_OFF)
# belong to the kit, placed where hn4.1 had them
KIT = uikit.Kit(fill_ws=HN_N, fp_base=0x0130, tp_base=TP_BASE)
# XDATA this image's own code uses: the variables above and the kit's blocks (tools/build.py checks it)
XDATA = [(0x0100, HM_TL + 1, "house-numerals variables, uikit fill/FP/TP blocks")]
(FP, FP_FONT, FP_STR, FP_SPC, FP_X, FP_Y, FP_INK, FP_BG, FP_CX0, FP_CX1, FP_SCALE, FP_W, FP_BPC, FP_BPG,
 FP_DATA, FP_MAP, FP_NADV, FP_CUR, FP_END, FP_CW, FP_ADV, FP_GLY, FP_VX0, FP_VX1, FP_OFF) = KIT.fp_layout()
assert FP + uikit.Kit.FP_SIZE - 1 < TP_BASE
XDATA_END = HM_TL
assert TP_BASE + uikit.Kit.TP_SIZE <= HM_VS

# the home layout: layout.json, written by sizing.html (served by tools/fonts/rasterize.py), with
# every position explicit and the fonts named by their rasters in tools/fonts/raster
LAYOUT_FILE = os.path.join(HERE, "layout.json")
LAYOUT = json.load(open(LAYOUT_FILE))["home"]
NAME_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ .-"       # page-1 big text: input names, EQ preset names
TAG_CHARS = "ABCDFIKLMPQRSTUo. "                   # the format and EQ tags
STATUS_CHARS = " !'-.0123456789ABCDEFGHIKLMNOPQRSTUVXabcdeghiklmnoprstuvwyz"   # every firmware string
# (sizing.html keeps the same character sets, for its flash figures)


def layout_font(label, element, chars):
    rid = LAYOUT[element]["font"]
    if not os.path.exists(os.path.join(pfont.RASTER_DIR, rid + ".json")):
        raise SystemExit("font %s (layout.json, %s) has no raster: open sizing.html through "
                         "python3 tools/fonts/rasterize.py and press Save" % (rid, element))
    return pfont.PFont(label, rid, chars, bpp=2)


PF_NAME = layout_font("pf_name", "name", NAME_CHARS)
PF_STATUS = layout_font("pf_status", "status", STATUS_CHARS)
PF_TAG = layout_font("pf_tag", "tags", TAG_CHARS)
PF_HVOL = layout_font("pf_hvol", "volume", "0123456789")
PF_ICON = layout_font("pf_icon", "icon", "SMH")
PFONTS = (PF_NAME, PF_STATUS, PF_TAG, PF_HVOL, PF_ICON)

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
BAR_X, BAR_Y, BAR_W, BAR_H = (LAYOUT["bar"][k] for k in ("x", "y", "width", "height"))
assert all(PF_TAG.width(t) == PF_TAG.width("SDB") for t in ("DIR", "CUS", "BAS", "SBA", "RCK", "SFT", "CLR"))
assert FMT_LEFT >= TAG_BASE and EQ_RIGHT - TAG_BASE < 256 and 2 <= TAG_PAD
assert all((FMT_RIGHT - PF_TAG.width(t) - 2 * TAG_PAD) & 0xFF != 0xFF for t in ("PCM", "DSD", "DoP", "MQA", "MQA."))
assert TAG_Y0 < TAG_TY and TAG_TY + PF_TAG.H - 1 < TAG_Y1
assert ICON_X + max(PF_ICON.width(c) for c in "SMH") - 1 <= ICON_END < HVOL_X and HVOL_END < FMT_LEFT
assert HNAME_Y + PF_NAME.H <= STAT_Y and STAT_Y + PF_STATUS.H <= BAR_Y and BAR_Y + BAR_H <= 170

# volume-page elements: (bit, name, x0, x1); an element appears once the edge is left of x0
VF_NAME, VF_DIV, VF_VOL, VF_NUM, VF_LINE = 1, 2, 4, 8, 16
VF_ALL = 31
VOL_ELEMENTS = [(VF_NAME, "hv_name", 16, 16 + 14 * 7 - 1), (VF_DIV, "hv_div", 140, 140),
                (VF_VOL, "hv_vol", 158, 158 + 3 * 14 - 1), (VF_NUM, "hv_num", 184, 303),
                (VF_LINE, "hv_line", 40, 279)]
# home elements: (bit, name, x0, x1); they appear once the edge is right of x1. The name and the
# status line end where their text ends: x1 is read from XDATA (HN_NAMER, HN_STATR) instead.
HF_ICON, HF_VOL, HF_BAR, HF_NAME, HF_FMT, HF_EQ, HF_STAT = 1, 2, 4, 8, 16, 32, 64
HF_ALL = 127
HOME_ELEMENTS = [(HF_ICON, "hh_icon", ICON_X, ICON_END), (HF_VOL, "hh_vol", HVOL_X, HVOL_END),
                 (HF_BAR, "hh_bar", 18, 45), (HF_NAME, "hh_name", 0, HN_NAMER),
                 (HF_FMT, "hh_fmt", FMT_LEFT, FMT_RIGHT - 1), (HF_EQ, "hh_eq", EQ_X, EQ_RIGHT - 1),
                 (HF_STAT, "hh_stat", 0, HN_STATR)]

STEPS = 20
EDGE_MAX = 318
# ease-in-out: edge x for entry step k (318 -> 0); the exit uses 318 - EASE[k]. Symmetric, so a
# reversal maps step k to 20 - k at the same x.
EASE = uikit.ease_in_out(STEPS, EDGE_MAX)
assert all(EASE[k] + EASE[STEPS - k] == EDGE_MAX for k in range(STEPS + 1))
assert all(EASE[k] - EASE[k + 1] >= 2 for k in range(STEPS))

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
    ("home_draw_output_icon", 0x02, "hm_icon"),
    ("home_draw_volume", 0x02, "hm_volume"),
    ("eq_tag_paint", 0x02, "hm_eq"),
    ("format_tag_paint", 0x12, "hm_fmt"),
    ("format_tag_clear", 0x02, "hm_fmt_clear"),
    ("format_tag_clear_changed", 0x12, "hm_fmt_clear"),
)]
HOOKS += [f.HOOK for f in features.fixes(INCLUDES)]    # the fixes linked in
VERSION_TEXT = "v1.4 tbenr hn6.1"


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
    a.comment("home_draw_input_name's strings for inputs 1..8 (0: none, the buffer is drawn as it is)")
    a.L("names8")
    tab = {inp: addr for inp, addr, _ in INPUT_NAMES}
    for inp in range(1, 9):
        v = tab.get(inp, 0)
        a.data("dw 0x%04X          ; input %d" % (v, inp), [v >> 8, v & 0xFF])
    a.comment("ease-in-out edge positions for the entry, steps 0..20 (the exit uses 318 - x)")
    a.L("ease")
    for k, v in enumerate(EASE):
        a.data("dw %d              ; step %d" % (v, k), [v >> 8, v & 0xFF])
    KIT.emit_font_data(a)
    a.comment("icon strings for uk_text")
    for lab, ch in (("hm_s_spk", "S"), ("hm_s_mute", "M"), ("hm_s_hp", "H")):
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
    KIT.emit_painter(a)
    KIT.emit_text(a)


def build_volume_page(a):
    S(a, """
; hn_draw_volume: replaces volpage_draw_volume 0x5936 (R7 speaker volume). Records the value
; (HN_VOL, HN_NUM); draws the number and the line when no wipe runs, or when the wipe has already
; revealed them; otherwise the wipe draws them when it reveals them.
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
mov DPTR,#0x%04X""" % HN_VOL + """
movx @DPTR,A
mov B,#10
div AB             ; A tens, B ones
inc DPTR           ; HN_NUM
jnz hdv_tens
mov A,#0x4F        ; blank tens digit: 0x7F after the add, a blank as wide as a digit (' ' is narrow)
hdv_tens:
add A,#0x30
movx @DPTR,A
inc DPTR
mov A,B
add A,#0x30
movx @DPTR,A
inc DPTR
clr A
movx @DPTR,A
mov R0,#5
mov A,#2
movx @R0,A         ; stock leaves the digit count 2 in XDATA 0x05
mov DPTR,#0x%04X""" % HN_MODE + """
movx A,@DPTR
jz hdv_all
inc DPTR           ; HN_VF
movx A,@DPTR
push ACC
jnb ACC.3,hdv_nonum
lcall hv_num
hdv_nonum:
pop ACC
jnb ACC.4,hdv_ret
ljmp hv_line
hdv_ret:
ret
hdv_all:
lcall hv_num
ljmp hv_line
""")
    S(a, "; hv_num: the number, stock big digits at 2x, white, at 184,42 (leading zero blank)\nhv_num:")
    fp_setup(a, "font_big", HN_NUM, 0, 184, 42, WHITE, scale=2)
    S(a, "ljmp uk_paint")
    S(a, "; hv_name: the input name, small font, white, at 16,30 (inputs 1..6)\nhv_name:\nlcall hn_name_ptr\njnc hvn_go\nret\nhvn_go:")
    S(a, "mov DPTR,#0x%04X\nmov A,R2\nmovx @DPTR,A\ninc DPTR\nmov A,R3\nmovx @DPTR,A" % FP_STR)
    fp_setup(a, "font_small", None, 1, 16, 30, WHITE)
    S(a, "ljmp uk_paint")
    S(a, "; hv_vol: \"VOL\" in the accent, small font, at 158,14\nhv_vol:")
    fp_setup(a, "font_small", "str_vol", 1, 158, 14, "acc")
    S(a, "ljmp uk_paint")
    S(a, "; hv_div: the divider, 1 x 104 at 140,14\nhv_div:")
    rect(a, 140, 1, 14, 104, DIVIDER)
    S(a, "ljmp uk_fill")
    S(a, "; hv_line: the whole position line\nhv_line:")
    st_imm16(a, HN_S0, 40)
    st_imm16(a, HN_S1, 279)
    S(a, """
; hn_line_seg: the columns HN_S0..HN_S1 of the 240 x 3 position line at 40,136: accent up to
; 40 + 4 * volume, 0x18E3 after it
hn_line_seg:
mov DPTR,#0x%04X""" % HN_VOL + """
movx A,@DPTR
rl A
rl A
add A,#40
mov R7,A
clr A
addc A,#0
mov DPTR,#0x%04X""" % HN_SPL + """
movx @DPTR,A
inc DPTR
mov A,R7
movx @DPTR,A
; accent part: max(S0, 40) .. min(S1, split - 1)
mov DPTR,#0x%04X""" % HN_S0 + """
movx A,@DPTR
mov R2,A
inc DPTR
movx A,@DPTR
mov R3,A
clr C
subb A,#40
mov A,R2
subb A,#0
jnc hl_a0
mov R2,#0
mov R3,#40
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
; track part: max(S0, split) .. min(S1, 279)
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
mov R4,#0x01
mov R5,#0x17       ; 279
lcall hl_minS1
mov R6,%s""" % hi(TRACK) + """
mov R7,%s""" % lo(TRACK) + """
; hl_fill: fill R2:R3 .. R4:R5 (if not empty) at y 136, 3 rows, colour R6:R7
hl_fill:
clr C
mov A,R5
subb A,R3
mov R1,A
mov A,R4
subb A,R2
jc hl_none
inc R1             ; width <= 240
mov R5,#136
mov R4,#3
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
lcall hv_div
ljmp hv_vol

; hn_volpage: page 2 renderer (replaces 0x2167). During a wipe it only records the volume.
hn_volpage:
mov DPTR,#0x%04X""" % HN_MODE + """
movx A,@DPTR
jnz hvp_wipe
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

; hn_reverse: step = 20 - step (the ease table is symmetric, so x stays); A = new step, and at 20
; (the running wipe had drawn nothing) the wipe stops: mode 0
hn_reverse:
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
; the volume page is on screen: wipe back home from x 0
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

; hn_cancel: ui_clear_screen's first instruction; every stock clear stops a wipe first
hn_cancel:
mov DPTR,#0x%04X""" % HN_MODE + """
clr A
movx @DPTR,A       ; HN_MODE
inc DPTR
movx @DPTR,A       ; HN_VF
inc DPTR
movx @DPTR,A       ; HN_HF
lcall 0x5CBC       ; the instruction the hook replaced
ljmp 0x5D45

; hn_hold: replaces the periodic refresh's lcall home_refresh at 0x4081 (0x3FE3): while a wipe
; runs, skip home_refresh and the status line (0x4084..0x4088) and note that the status buffer
; (XDATA 0x50) has just been loaded
hn_hold:
mov DPTR,#0x%04X""" % HN_MODE + """
movx A,@DPTR
jz hh_stock
mov DPTR,#0x%04X""" % HN_SBUF + """
mov A,#1
movx @DPTR,A
ret                ; 0x3FE3's own return (0x4088 is a tail jump)
hh_stock:
lcall 0x5C8B       ; home_refresh
ljmp 0x4084

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
; as home_refresh_periodic draws them (the text buffers are kept: the status line is the stock one)
hn_home_now:
mov DPTR,#0x%04X""" % HN_MODE + """
clr A
movx @DPTR,A       ; HN_MODE (so the name draw inside home_refresh passes the guard)
inc DPTR
movx @DPTR,A       ; HN_VF
inc DPTR
movx @DPTR,A       ; HN_HF
lcall 0x51EE       ; lcd_clear_black
lcall 0x5C8B       ; home_refresh
mov R7,#0x87
mov R6,#0
ljmp 0x3A53        ; small_text_render, y 135

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
; hn_step: one step of the running wipe
hn_step:
mov DPTR,#0x%04X""" % HN_MODE + """
movx A,@DPTR
jz hs_ret
cjne A,#3,hs_mc
hs_mc:
jc hs_mok
clr A              ; not a mode: stop
movx @DPTR,A
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
    for bit, name, x0, x1 in VOL_ELEMENTS:
        skip = "rv_%s" % name
        S(a, """
mov DPTR,#0x%04X
movx A,@DPTR
anl A,#0x%02X
jnz %s
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
%s:""" % (HN_VF, bit, skip, HN_LIM, lo(x0), hi(x0), skip, name, HN_VF, bit, skip))
    S(a, "ljmp hs_end\nhs_rvx:")
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
hs_done:
ret

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
                                ("hn_align_small", 0x3A85, uikit.STATUS_Y, "hm_status")):
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
    S(a, "; hm_status: the status line (XDATA 0x50), mono, grey, at x 18, baseline 132\nhm_status:")
    tp_setup(a, "pf_status", SMALL_BUF, 0, STAT_X, STAT_Y, DIM, spacing=STAT_SP)
    S(a, "lcall uk_text")
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
mov B,#10
div AB             ; A tens, B ones
mov DPTR,#0x%04X""" % HM_VS + """
jz hmv_one
add A,#0x30
movx @DPTR,A
inc DPTR
hmv_one:
mov A,B
add A,#0x30
movx @DPTR,A
inc DPTR
clr A
movx @DPTR,A
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
    tp_setup(a, "pf_tag", HM_TAG, 0, 0, TAG_TY, WHITE, clip=(0x100, 0))
    S(a, """
lcall uk_text      ; measure: TP_END = width - 1
""")
    st_imm16(a, KIT.TP["STR"], HM_TAG)
    S(a, """mov DPTR,#0x%04X""" % (KIT.TP["END"] + 1) + """
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
; the box: top and bottom rows, left and right columns, in the accent
lcall ht_xw
mov R5,#%d""" % TAG_Y0 + """
mov R4,#1
lcall ht_acc
lcall ht_xw
mov R5,#%d""" % TAG_Y1 + """
mov R4,#1
lcall ht_acc
lcall ht_xw
mov R1,#1
mov R5,#%d""" % (TAG_Y0 + 1) + """
mov R4,#%d""" % (TAG_Y1 - TAG_Y0 - 1) + """
lcall ht_acc
lcall ht_xw
dec A
add A,R3
mov R3,A
clr A
addc A,R2
mov R2,A           ; x + w - 1
mov R1,#1
mov R5,#%d""" % (TAG_Y0 + 1) + """
mov R4,#%d""" % (TAG_Y1 - TAG_Y0 - 1) + """
lcall ht_acc
; the inside around the text, black: rows above and below it, TAG_PAD - 1 columns left and right
lcall ht_xw
inc R3
dec R1
dec R1
mov R5,#%d""" % (TAG_Y0 + 1) + """
mov R4,#%d""" % (TAG_TY - TAG_Y0 - 1) + """
lcall ht_black
lcall ht_xw
inc R3
dec R1
dec R1
mov R5,#%d""" % (TAG_TY + PF_TAG.H) + """
mov R4,#%d""" % (TAG_Y1 - TAG_TY - PF_TAG.H) + """
lcall ht_black
lcall ht_xw
inc R3
mov R1,#%d""" % (TAG_PAD - 1) + """
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
mov R2,A           ; x + 5 + text width
mov R1,#%d""" % (TAG_PAD - 1) + """
mov R5,#%d""" % TAG_TY + """
mov R4,#%d""" % PF_TAG.H + """
lcall ht_black
; the text at x + pad
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
lcall uk_acc
mov DPTR,#0x%04X""" % KIT.TP["INK"] + """
mov A,R6
movx @DPTR,A
inc DPTR
mov A,R7
movx @DPTR,A
mov DPTR,#0x%04X""" % KIT.TP["CX0"] + """
clr A
movx @DPTR,A
inc DPTR
movx @DPTR,A
inc DPTR
inc A
movx @DPTR,A
inc DPTR
mov A,#0x3F
movx @DPTR,A       ; clip 0..319
ljmp uk_text
; ht_xw: R2:R3 = box x, R1 = A = box width (the box never starts at x 255 or 511: inc R3 is safe)
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
    for f in features.fixes(INCLUDES):
        f.emit(a)
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
    ]
    # home_draw_input_name's table (0x4A9B) loads the strings INPUT_NAMES lists
    for inp, addr, text in INPUT_NAMES:
        t = (base[0x4A9B + 3 * (inp - 1) + 1] << 8) | base[0x4A9B + 3 * (inp - 1) + 2]
        asserts.append((t, bytes([0x7B, 0xFF, 0x7A, addr >> 8, 0x79, addr & 0xFF]), "name table %d" % inp))
    patches = [(s, VOL_ENTRY_ORIG, lambda labels: vol_entry_bytes(labels["hn_enter_vol"]),
                "lcall hn_enter_vol ; sjmp 0x%04X" % (s + len(VOL_ENTRY_ORIG))) for s in VOL_ENTRY_SITES]
    uikit.build_image(base_path=sys.argv[1] if len(sys.argv) > 1 else BASE_IMAGE, base_sha=BASE_SHA,
                      code_addr=CODE_ADDR, assemble=assemble, hooks=HOOKS, patches=patches, asserts=asserts,
                      version_text=VERSION_TEXT, out_image=OUT_IMAGE, out_listing=OUT_LISTING,
                      title="House Numerals patch", label_prefixes=("hn_", "uk_"))


if __name__ == "__main__":
    main()
