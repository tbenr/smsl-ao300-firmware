#!/usr/bin/env python3
"""uikit: shared building blocks for AO300 UI themes (8051 patch code emitted into an asm51.Asm).

Extracted from features/house-numerals (hn4.1), which builds byte-identical with it. What is here:

  asm text     hi / lo / S / st_imm16 / ld16 / st16: write patch code as text lines (Asm.op).
  stock facts  addresses of the stock v1.4 routines, fonts, text buffers and UI variables the
               themes build on, and the catalogue of stock hook sites with their original bytes
               (STOCK_SITES, VOL_ENTRY_SITES). A theme picks the sites it hooks; build_image()
               asserts the bytes before patching.
  easing       ease_in_out(): per-tick positions for animations.
  fonts        descriptors and character maps of the two stock 1-bit fonts, in the column-major
               layout uk_paint reads (FONTS; new fonts only need an entry here plus glyph data).
  Kit          the routines, emitted into a theme's code at the place the theme chooses:
                 uk_fill       rectangle fill, ~9 clocks per pixel (the fast-lcd bus timing)
                 uk_acc        accent colour: the COLOR tint, a theme colour on the White tint
                 uk_paint      streaming text painter: stock fonts, ink and background colours,
                               an x clip window, scale 1 or 2; pixel-identical to the stock text
                 uk_home_x     page-1 text start as the stock renderers compute it, with the
                               left-align rule (x 16) of House Numerals' align hooks
                 uk_text       proportional text painter for pfont fonts (1-bit, or 4-level
                               anti-aliased run-length): alignment, letter spacing, x clip;
                               uk_avg mixes its middle colours, uk_tfetch reads its string
                 uk_tasks      the per-tick driver: runs after main_tick_tasks on every 10 ms tick
                               while the amp is on; the theme's step routine must follow it
               plus rect(), fp_setup() and tp_setup() to load their arguments.
  build_image  the common image build: base sha check, asserts, code placement, hooks,
               version string, listing.

Register use: every ui_* routine may clobber A, B, DPTR, PSW (F0, F1 included) and R0-R7.
Each Kit instance takes the XDATA it may use (fill_ws: 4 bytes, fp_base: 38 bytes, tp_base: 50
bytes within one 256-byte page, only for uk_text); the theme owns the rest of XDATA from 0x0100.
"""
import hashlib
import os

from asm51 import Asm, hi8, lo8  # noqa: F401  (hi8/lo8: used by emitted "dw label" data)

# ---- stock v1.4 facts ---------------------------------------------------------------------------
LCD_SET_WINDOW = 0x4437             # R6:R7 y0, R4:R5 y1, R2:R3 x0, XDATA 0x2F:0x30 x1; ends with RAMWR
FONT_SMALL = 0x5DAB                 # 14 x 24, 3 bytes per column, MSB = top pixel
FONT_BIG = 0x6A23                   # 30 x 32, 4 bytes per column
HOME_DRAW_VOLUME = 0x5916
HOME_DRAW_OUTPUT_ICON = 0x5744
HOME_DRAW_FORMAT_TAG = 0x41CA
HOME_DRAW_EQ_TAG = 0x49A1
HOME_REFRESH = 0x5C8B
UI_CLEAR_SCREEN = 0x5D42
CLEAR_SMALL_BUF = 0x5CBC
CLEAR_BIG_BUF = 0x5CCB
BIG_TEXT_LOAD = 0x4C8F
MAIN_TICK_TASKS = 0x3325
RENDER_DONE = 0x22FA
BIG_BUF, SMALL_BUF = 0x35, 0x50     # XDATA text buffers of big_text_render / small_text_render
NAME_Y, STATUS_Y = 75, 135          # stock y of the home input name and status line
# input names as home_draw_input_name 0x4A85 loads them (its table at 0x4A9B); input 7: none
INPUT_NAMES = [(1, 0x904F, "USB"), (2, 0x9053, "OPTICAL"), (3, 0x905B, "COAXIAL"),
               (4, 0x9048, "BT"), (5, 0x904B, "ARC"), (6, 0x9063, "AUX"), (8, 0x9067, "PHONO")]
P1 = 0x90
VERSION_PTR_ADDR = 0x22CA           # mov R2,#hi ; mov R1,#lo of the RESET page's version string
VERSION_MAX_LEN = 20
CODE_END = 0xF400                   # code/EEPROM split

# stock hook sites: name -> (address, original bytes). Hooks are 3 bytes (lcall/ljmp); the comment
# says what the stock instruction there is and where a hook must return to, if anywhere.
STOCK_SITES = {
    "page_clear": (0x2106, bytes([0x12, 0x5D, 0x42])),       # ui_render_page: lcall ui_clear_screen
    "page2_entry": (0x2143, bytes([0x02, 0x21, 0x67])),      # page 2 jump-table entry (ljmp 0x2167)
    "volpage_draw_volume": (0x5936, bytes([0xAB, 0x07, 0xE5])),  # R7 speaker volume; 0x2B/0x52 as stock
    "big_text_start_x": (0x2A25, bytes([0xE4, 0x78, 0x02])),   # clr A; mov R0,#2 -> back to 0x2A28
    "small_text_start_x": (0x3A82, bytes([0xE4, 0x78, 0x02])),  # same -> back to 0x3A85
    "home_refresh_tail": (0x5C99, bytes([0x02, 0x59, 0x16])),  # ljmp home_draw_volume (R7 = volume)
    "tick": (0x5B2A, bytes([0x12, 0x33, 0x25])),             # main_tasks_on: lcall main_tick_tasks
    "home_refresh_periodic": (0x4081, bytes([0x12, 0x5C, 0x8B])),  # lcall home_refresh; 0x4084 follows
    "ui_clear_screen": (0x5D42, bytes([0x12, 0x5C, 0xBC])),  # lcall ui_clear_small_buf; 0x5D45 follows
    "home_draw_input_name": (0x4A85, bytes([0xE5, 0x47, 0x14])),  # mov A,0x47; dec A; 0x4A88 follows
    "home_refresh_flag_path": (0x3FF8, bytes([0xC2, 0x0B, 0xC2])),  # clr 0x21.3; clr 0x20.6; ...
    # the home elements' painters (page 1); a theme that replaces one draws the element itself
    "home_draw_output_icon": (0x5744, bytes([0x30, 0x11, 0x0B])),  # jnb 0x22.1 (muted, red icon 1); icon 3
    #   speakers (g_output 0x2B = 1), 2 headphones; x 15, y 8; ends with ret (XDATA 6 = the icon)
    "home_draw_volume": (0x5916, bytes([0xAB, 0x07, 0xE5])),  # R7 speaker volume (0x52 on headphones);
    #   2 small digits at 48,9; ends with ret
    "eq_tag_paint": (0x4F18, bytes([0x7D, 0x0A, 0x7C])),     # only caller home_draw_eq_tag 0x4A0F: string
    #   R3:R2:R1 (generic pointer, 3 letters), small font at 266,10, then ret
    "format_tag_paint": (0x425D, bytes([0x12, 0x4F, 0x20])),  # home_draw_format_tag: lcall 0x4F20, string
    #   R3:R2:R1 ("PCM ", "DSD ", "DoP ", "MQA ", "MQA.") at 208,10; ret follows
    "format_tag_clear": (0x41E8, bytes([0x02, 0x00, 0x26])),  # ljmp 0x0026: clear the tag's box (inputs
    #   without a format: BT, ARC, AUX, PHONO)
    "format_tag_clear_changed": (0x41FC, bytes([0x12, 0x00, 0x26])),  # lcall 0x0026: the format changed
}

# where the volume keys open page 2 themselves (after `mov 0x45,#0x02`); 22 stock bytes each:
# lcall ui_clear_screen, load "volume", small_text_render at y 135. A theme replaces the first 5
# with `lcall <entry> ; sjmp site+0x16` (vol_entry_bytes).
VOL_ENTRY_SITES = (0x0D33, 0x0DB3, 0x0E5A, 0x0F02)
VOL_ENTRY_ORIG = bytes.fromhex("125d427bff7a937947e4fdff124d3a7f877e00123a53")


def vol_entry_bytes(target):
    return bytes([0x12, target >> 8, target & 0xFF, 0x80, len(VOL_ENTRY_ORIG) - 5])


def rgb565(r, g, b):
    return ((r * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5 | ((b * 31 + 127) // 255)


def ease_in_out(steps, span):
    """Positions span..0 for steps 0..steps along a cosine ease-in-out (symmetric)."""
    import math
    return [round(span * (1 + math.cos(math.pi * k / steps)) / 2) for k in range(steps + 1)]


# ---- asm text helpers ---------------------------------------------------------------------------
def hi(v):
    return "#0x%02X" % (v >> 8)


def lo(v):
    return "#0x%02X" % (v & 0xFF)


def S(a, text):
    """Assemble lines of text: `label:`, `; comment`, or an instruction (with an optional comment)."""
    for ln in text.strip("\n").split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith(";"):
            a.comment(ln[1:].strip())
        elif ln.split(";")[0].strip().endswith(":") and " " not in ln.split(";")[0].strip():
            a.L(ln.split(";")[0].strip()[:-1])
        else:
            a.op(ln)


def st_imm16(a, addr, v):
    S(a, "mov DPTR,#0x%04X\nmov A,%s\nmovx @DPTR,A\ninc DPTR\nmov A,%s\nmovx @DPTR,A" % (addr, hi(v), lo(v)))


def ld16(a, rh, rl, addr):
    S(a, "mov DPTR,#0x%04X\nmovx A,@DPTR\nmov %s,A\ninc DPTR\nmovx A,@DPTR\nmov %s,A" % (addr, rh, rl))


def st16(a, addr, rh, rl):
    S(a, "mov DPTR,#0x%04X\nmov A,%s\nmovx @DPTR,A\ninc DPTR\nmov A,%s\nmovx @DPTR,A" % (addr, rh, rl))

# ---- fonts --------------------------------------------------------------------------------------
# font descriptors: width, bytes per column, bytes per glyph, glyph data, character map, narrow advance
# The character map covers 0x20..0x7F: glyph index, bit 7 = narrow (advance by the narrow width).
# Characters the stock painters don't map (they reuse the previous glyph) draw as a blank here.
SMALL_MAP = {" ": 0, ".": 1, ":": 2, "-": 3, "+": 4, "=": 5, "<": 68, ">": 69, "{": 70, "}": 71,
             "(": 72, ")": 73, "!": 74, "'": 75}
SMALL_MAP.update({chr(0x30 + i): 6 + i for i in range(10)})
SMALL_MAP.update({chr(0x41 + i): 16 + i for i in range(26)})
SMALL_MAP.update({chr(0x61 + i): 42 + i for i in range(26)})
BIG_MAP = {" ": 0, ".": 1, ":": 2, "-": 3, "+": 4, "=": 5}
BIG_MAP.update({chr(0x30 + i): 6 + i for i in range(10)})
BIG_MAP.update({chr(0x41 + i): 16 + i for i in range(26)})
BIG_NARROW = " .-+=I"               # big_text_render: advance 17 (0x2A9E), centring +13 (0x29C8)
FONTS = {"font_small": (14, 3, 42, FONT_SMALL, "map_small", 0, SMALL_MAP, ""),
         "font_big": (30, 4, 120, FONT_BIG, "map_big", 17, BIG_MAP, BIG_NARROW)}


# ---- the kit -------------------------------------------------------------------------------------
class Kit:
    """Emits the ui_* routines. fill_ws: 4 bytes of XDATA for uk_fill; fp_base: 38 bytes for
    uk_paint's parameter block and work area (set FP_FONT..FP_SCALE with fp_setup)."""

    FP_OFFSETS = dict(FP=0, FP_FONT=0, FP_STR=2, FP_SPC=4, FP_X=5, FP_Y=7, FP_INK=8, FP_BG=10,
                      FP_CX0=12, FP_CX1=14, FP_SCALE=16, FP_W=17, FP_BPC=18, FP_BPG=19, FP_DATA=20,
                      FP_MAP=22, FP_NADV=24, FP_CUR=25, FP_END=27, FP_CW=29, FP_ADV=30, FP_GLY=31,
                      FP_VX0=33, FP_VX1=35, FP_OFF=37)
    FP_SIZE = 38

    # uk_text's block: parameters (tp_setup) up to SPACING, then its work area
    TP_OFFSETS = dict(FONT=0, STR=2, SPC=4, X=5, Y=7, INK=8, BG=10, CX0=12, CX1=14, ALIGN=16, SPACING=17,
                      H=18, BPC=19, FMT=20, FIRST=21, N=22, MAP=23, TAB=25, CUR=27, END=29, ADV=31,
                      GOFF=32, GW=33, GLY=34, VX0=36, VX1=38, C1=40, C2=42, L=44, S=45, I=46, T=47,
                      CNT=48)
    TP_SIZE = 50

    def __init__(self, fill_ws=0x0100, fp_base=0x0130, tp_base=None):
        self.fill_n = fill_ws           # pixel count (hi, lo) ...
        self.fill_c = fill_ws + 2       # ... immediately followed by the colour
        self.fp_base = fp_base
        for k, v in self.FP_OFFSETS.items():
            setattr(self, k, fp_base + v)
        self.tp_base = tp_base
        if tp_base is not None:
            assert (tp_base & 0xFF) + self.TP_SIZE <= 0x100, "uk_text's block must not cross a 256-byte page"
            addr = {k: tp_base + v for k, v in self.TP_OFFSETS.items()}
            self.TP = addr               # numeric addresses, for tests
            self.tp = {k: "0x%04X" % v for k, v in addr.items()}
            for k in ("STR", "X", "TAB", "CUR", "GLY", "CNT"):
                self.tp[k + "1"] = "0x%04X" % (addr[k] + 1)
            for k in ("VX0", "VX1"):
                self.tp[k + "1"] = "0x%04X" % (addr[k] + 1)
            for k in ("ADV", "H"):
                self.tp[k + "_LO"] = "0x%02X" % (addr[k] & 0xFF)
                self.tp[k + "_HI"] = "0x%02X" % (addr[k] >> 8)

    def fp_layout(self):
        return tuple(getattr(self, n) for n in ('FP', 'FP_FONT', 'FP_STR', 'FP_SPC', 'FP_X', 'FP_Y', 'FP_INK', 'FP_BG', 'FP_CX0', 'FP_CX1', 'FP_SCALE', 'FP_W', 'FP_BPC', 'FP_BPG', 'FP_DATA', 'FP_MAP', 'FP_NADV', 'FP_CUR', 'FP_END', 'FP_CW', 'FP_ADV', 'FP_GLY', 'FP_VX0', 'FP_VX1', 'FP_OFF'))

    def rect(self, a, x, w, y, h, colour=None):
        """Load uk_fill's arguments (colour None: R6:R7 already set)."""
        S(a, "mov R2,%s\nmov R3,%s\nmov R1,#%d\nmov R5,#%d\nmov R4,#%d" % (hi(x), lo(x), w, y, h))
        if colour is not None:
            S(a, "mov R6,%s\nmov R7,%s" % (hi(colour), lo(colour)))

    def fp_setup(self, a, font, string, space, x, y, ink, bg=0, clip=(0, 319), scale=1):
        """Fill uk_paint's parameter block. string: an address (int), a code label (str), or None
        (FP_STR already set);
        x: int, or None (set later, e.g. by uk_home_x); ink: int, "theme" (RAM 0x48:0x49) or "acc"
        (uk_acc, R6:R7)."""
        FP, FP_FONT, FP_STR, FP_SPC, FP_X, FP_Y, FP_INK, FP_BG, FP_CX0, FP_CX1, FP_SCALE, FP_W, FP_BPC, FP_BPG, FP_DATA, FP_MAP, FP_NADV, FP_CUR, FP_END, FP_CW, FP_ADV, FP_GLY, FP_VX0, FP_VX1, FP_OFF = self.fp_layout()
        """Fill uk_paint's parameter block. string: an address (int), a code label (str), or None
        (FP_STR already set);
        x: int, or None (set later, e.g. by uk_home_x); ink: int, "theme" (RAM 0x48:0x49) or "acc"
        (uk_acc, R6:R7)."""
        if ink == "acc":
            S(a, "lcall uk_acc")
        S(a, "mov DPTR,#0x%04X\nmov A,#hi(%s)\nmovx @DPTR,A\ninc DPTR\nmov A,#lo(%s)\nmovx @DPTR,A\ninc DPTR"
          % (FP_FONT, font, font))
        if isinstance(string, str):
            S(a, "mov A,#hi(%s)\nmovx @DPTR,A\ninc DPTR\nmov A,#lo(%s)\nmovx @DPTR,A\ninc DPTR" % (string, string))
        elif string is not None:
            S(a, "mov A,%s\nmovx @DPTR,A\ninc DPTR\nmov A,%s\nmovx @DPTR,A\ninc DPTR" % (hi(string), lo(string)))
        else:
            S(a, "inc DPTR\ninc DPTR")
        S(a, "mov A,#%d\nmovx @DPTR,A\ninc DPTR" % space)
        if x is not None:
            S(a, "mov A,%s\nmovx @DPTR,A\ninc DPTR\nmov A,%s\nmovx @DPTR,A\ninc DPTR" % (hi(x), lo(x)))
        else:
            S(a, "inc DPTR\ninc DPTR")
        S(a, "mov A,#%d\nmovx @DPTR,A\ninc DPTR" % y)
        if ink == "theme":
            S(a, "mov A,0x48\nmovx @DPTR,A\ninc DPTR\nmov A,0x49\nmovx @DPTR,A\ninc DPTR")
        elif ink == "acc":
            S(a, "mov A,R6\nmovx @DPTR,A\ninc DPTR\nmov A,R7\nmovx @DPTR,A\ninc DPTR")
        else:
            S(a, "mov A,%s\nmovx @DPTR,A\ninc DPTR\nmov A,%s\nmovx @DPTR,A\ninc DPTR" % (hi(ink), lo(ink)))
        for v in (bg, clip[0], clip[1]):
            S(a, "mov A,%s\nmovx @DPTR,A\ninc DPTR\nmov A,%s\nmovx @DPTR,A\ninc DPTR" % (hi(v), lo(v)))
        S(a, "mov A,#%d\nmovx @DPTR,A" % scale)

    def emit_font_data(self, a):
        """Descriptors (labels font_small, font_big) and character maps of FONTS."""
        for name, (w, bpc, bpg, data, mapl, nadv, cmap, narrow) in FONTS.items():
            a.comment("%s: width, bytes per column, bytes per glyph, glyph data, map, narrow advance" % name)
            a.L(name)
            a.data("db %d,%d,%d" % (w, bpc, bpg), [w, bpc, bpg])
            a.data("dw 0x%04X" % data, [data >> 8, data & 0xFF])
            a.i("dw %s" % mapl, hi8(mapl), lo8(mapl), data=True)
            a.data("db %d" % nadv, [nadv])
        for name, (w, bpc, bpg, data, mapl, nadv, cmap, narrow) in FONTS.items():
            a.comment("%s: glyph index per character 0x20..0x7F, bit 7 = narrow" % mapl)
            a.L(mapl)
            row = []
            for c in range(0x20, 0x80):
                v = cmap.get(chr(c), 0) | (0x80 if chr(c) in narrow else 0)
                row.append(v)
            for k in range(0, 96, 16):
                a.data("db " + ",".join("%d" % v for v in row[k:k + 16]), row[k:k + 16])

    def emit_fill(self, a):
        """uk_fill: R2:R3 x, R1 w (1..255), R5 y, R4 h (1..170), R6:R7 colour."""
        FILL_C, FILL_N = self.fill_c, self.fill_n
        S(a, """
    ; uk_fill: R2:R3 x, R1 w (1..255), R5 y, R4 h (1..170), R6:R7 colour
    uk_fill:
    mov DPTR,#0x%04X""" % FILL_C + """
    mov A,R6
    movx @DPTR,A
    inc DPTR
    mov A,R7
    movx @DPTR,A
    mov A,R1
    mov B,R4
    mul AB             ; B:A = w*h
    mov DPTR,#0x%04X""" % FILL_N + """
    xch A,B
    movx @DPTR,A       ; count hi
    inc DPTR
    xch A,B
    movx @DPTR,A       ; count lo
    mov A,R1
    dec A
    add A,R3           ; x1 = x + w - 1
    mov R0,#0x30
    movx @R0,A
    clr A
    addc A,R2
    dec R0
    movx @R0,A
    mov A,R5
    mov R7,A           ; y0
    mov R6,#0
    mov A,R4
    dec A
    add A,R5           ; y1 = y + h - 1
    mov R5,A
    mov R4,#0
    lcall 0x4437       ; lcd_set_window, ends with RAMWR
    mov DPTR,#0x%04X""" % FILL_N + """
    movx A,@DPTR
    mov R5,A           ; count hi
    inc DPTR
    movx A,@DPTR
    mov R4,A           ; count lo
    inc DPTR
    movx A,@DPTR
    mov R6,A           ; colour hi
    inc DPTR
    movx A,@DPTR
    mov R7,A           ; colour lo
    mov A,R4
    jz hf_go
    inc R5             ; djnz pair runs hi*256 + lo times
    hf_go:
    setb P0.3          ; D/C = data
    clr P0.7           ; CS low
    hf_px:
    mov P1,R6
    clr P0.5
    setb P0.5
    mov P1,R7
    clr P0.5
    setb P0.5
    djnz R4,hf_px
    djnz R5,hf_px
    setb P0.7          ; CS high
    ret
""")

    def emit_accent(self, a, white):
        """uk_acc: R6:R7 = the accent: the COLOR tint (RAM 0x48:0x49), `white` on the White tint."""
        S(a, """
; uk_acc: R6:R7 = the accent: the COLOR tint (RAM 0x48:0x49), the theme's own colour on White; keeps R1..R5
uk_acc:
mov A,0x48
anl A,0x49
cpl A              ; 0 only on the White theme
jnz ha_theme
mov R6,%s
mov R7,%s
ret
ha_theme:
mov R6,0x48
mov R7,0x49
ret
""" % (hi(white), lo(white)))

    def emit_painter(self, a):
        """uk_fp_load, uk_fetch, uk_map, uk_home_x, uk_paint, uk_cell: see their comments."""
        FP, FP_FONT, FP_STR, FP_SPC, FP_X, FP_Y, FP_INK, FP_BG, FP_CX0, FP_CX1, FP_SCALE, FP_W, FP_BPC, FP_BPG, FP_DATA, FP_MAP, FP_NADV, FP_CUR, FP_END, FP_CW, FP_ADV, FP_GLY, FP_VX0, FP_VX1, FP_OFF = self.fp_layout()
        S(a, """
    ; uk_fp_load: copy the font descriptor FP_FONT points to into FP_W..FP_NADV (8 bytes)
    uk_fp_load:
    mov DPTR,#0x%04X""" % FP_FONT + """
    movx A,@DPTR
    mov R6,A
    inc DPTR
    movx A,@DPTR
    mov R7,A
    mov R5,#0
    fl_next:
    mov DPH,R6
    mov DPL,R7
    mov A,R5
    movc A,@A+DPTR
    mov R4,A
    mov A,R5
    add A,%s""" % lo(FP_W) + """
    mov DPL,A
    mov DPH,%s""" % hi(FP_W) + """
    mov A,R4
    movx @DPTR,A
    inc R5
    cjne R5,#8,fl_next
    ret

    ; uk_fetch: next character of the FP_STR string (FP_SPC: 0 XDATA, 1 code) -> A, R5; FP_STR advanced
    ; unless it is the terminating 0
    uk_fetch:
    mov DPTR,#0x%04X""" % FP_STR + """
    movx A,@DPTR
    mov R6,A
    inc DPTR
    movx A,@DPTR
    mov R7,A
    inc DPTR
    movx A,@DPTR       ; FP_SPC
    mov DPH,R6
    mov DPL,R7
    jnz hft_code
    movx A,@DPTR
    sjmp hft_got
    hft_code:
    clr A
    movc A,@A+DPTR
    hft_got:
    mov R5,A
    jz hft_ret
    inc DPTR
    mov R6,DPH
    mov R7,DPL
    mov DPTR,#0x%04X""" % FP_STR + """
    mov A,R6
    movx @DPTR,A
    inc DPTR
    mov A,R7
    movx @DPTR,A
    mov A,R5
    hft_ret:
    ret

    ; uk_map: character R5 -> A = glyph index | 0x80 if narrow (0 outside 0x20..0x7F)
    uk_map:
    mov A,R5
    clr C
    subb A,#0x20
    jc hm_blank
    cjne A,#0x60,hm_cmp
    hm_cmp:
    jnc hm_blank
    mov R4,A
    mov DPTR,#0x%04X""" % FP_MAP + """
    movx A,@DPTR
    mov R6,A
    inc DPTR
    movx A,@DPTR
    mov DPL,A
    mov DPH,R6
    mov A,R4
    movc A,@A+DPTR
    ret
    hm_blank:
    clr A
    ret

    ; uk_home_x: FP_X = where the stock renderer starts the FP_STR string on page 1: centred as
    ; big_text_render / small_text_render compute it ((320 [+ w - narrow if any narrow char] - n*w) / 2),
    ; then moved to x 16 (as left-align hooks on 0x2A25 / 0x3A82 do) unless that is below 16. Keeps FP_STR.
    uk_home_x:
    lcall uk_fp_load
    mov DPTR,#0x%04X""" % FP_STR + """
    movx A,@DPTR
    push ACC
    inc DPTR
    movx A,@DPTR
    push ACC
    mov R2,#0          ; n
    mov R3,#0          ; any narrow character
    hx_scan:
    lcall uk_fetch
    jz hx_count
    inc R2
    lcall uk_map
    jnb ACC.7,hx_scan
    mov R3,#1
    sjmp hx_scan
    hx_count:
    mov DPTR,#0x%04X""" % FP_STR + """
    pop ACC
    mov R7,A
    pop ACC
    movx @DPTR,A
    inc DPTR
    mov A,R7
    movx @DPTR,A
    mov DPTR,#0x%04X""" % FP_W + """
    movx A,@DPTR
    mov R6,A           ; w
    mov B,R2
    mul AB             ; B:A = n*w
    mov R4,B
    mov R5,A
    mov R0,#0          ; extra: w - narrow advance when a narrow character is there
    mov A,R3
    jz hx_base
    mov DPTR,#0x%04X""" % FP_NADV + """
    movx A,@DPTR
    xch A,R6
    clr C
    subb A,R6
    mov R0,A
    hx_base:
    mov A,R0
    add A,#0x40
    mov R7,A
    clr A
    addc A,#0x01       ; R6:R7 = 320 + extra
    mov R6,A
    clr C
    mov A,R7
    subb A,R5
    mov R7,A
    mov A,R6
    subb A,R4
    clr C
    rrc A              ; logical shift right, as the stock code
    mov R6,A
    mov A,R7
    rrc A
    mov R7,A
    mov A,R6
    jnz hx_store       ; far off (never for our strings): keep
    mov A,R7
    clr C
    subb A,#16
    jc hx_store        ; wider than 288 px: stays centred
    mov R7,#16
    hx_store:
    mov DPTR,#0x%04X""" % FP_X + """
    mov A,R6
    movx @DPTR,A
    inc DPTR
    mov A,R7
    movx @DPTR,A
    ret
    """)
        S(a, """
    ; uk_paint: draw the string in the FP block: font FP_FONT, string FP_STR (FP_SPC 0 XDATA, 1 code),
    ; at FP_X, FP_Y, ink FP_INK on FP_BG, scale FP_SCALE (1 or 2), only the columns FP_CX0..FP_CX1.
    ; Each character is a cell of w*scale columns, drawn in full (background included), and the next
    ; one starts w*scale further on (narrow characters: the font's narrow advance * scale), as the stock
    ; text renderers do. FP_END is the last column of the last cell (FP_X - 1 for an empty string).
    ; An empty clip window (FP_CX0 > FP_CX1) draws nothing: a measurement.
    uk_paint:
    lcall uk_fp_load
    mov DPTR,#0x%04X""" % FP_X + """
    movx A,@DPTR
    mov R6,A
    inc DPTR
    movx A,@DPTR
    mov R7,A
    mov DPTR,#0x%04X""" % FP_CUR + """
    mov A,R6
    movx @DPTR,A
    inc DPTR
    mov A,R7
    movx @DPTR,A
    inc DPTR           ; FP_END = x - 1
    clr C
    mov A,R7
    subb A,#1
    mov R7,A
    mov A,R6
    subb A,#0
    movx @DPTR,A
    inc DPTR
    mov A,R7
    movx @DPTR,A
    mov DPTR,#0x%04X""" % FP_W + """
    movx A,@DPTR
    mov B,A
    mov DPTR,#0x%04X""" % FP_SCALE + """
    movx A,@DPTR
    mul AB
    mov DPTR,#0x%04X""" % FP_CW + """
    movx @DPTR,A
    hp_char:
    lcall uk_fetch
    jnz hp_have
    ret
    hp_have:
    lcall uk_map
    mov R4,A           ; index | narrow
    mov DPTR,#0x%04X""" % FP_W + """
    jnb ACC.7,hp_wide
    mov DPTR,#0x%04X""" % FP_NADV + """
    hp_wide:
    movx A,@DPTR
    mov B,A
    mov DPTR,#0x%04X""" % FP_SCALE + """
    movx A,@DPTR
    mul AB
    mov DPTR,#0x%04X""" % FP_ADV + """
    movx @DPTR,A
    mov A,R4
    anl A,#0x7F
    mov B,A
    mov DPTR,#0x%04X""" % FP_BPG + """
    movx A,@DPTR
    mul AB             ; B:A = glyph offset
    mov R7,A
    mov R6,B
    mov DPTR,#0x%04X""" % (FP_DATA + 1) + """
    movx A,@DPTR
    add A,R7
    mov R7,A
    mov DPTR,#0x%04X""" % FP_DATA + """
    movx A,@DPTR
    addc A,R6
    mov DPTR,#0x%04X""" % FP_GLY + """
    movx @DPTR,A
    inc DPTR
    mov A,R7
    movx @DPTR,A
    ; cell: R2:R3 = x0 = FP_CUR, R4:R5 = x1 = x0 + cw - 1
    mov DPTR,#0x%04X""" % FP_CUR + """
    movx A,@DPTR
    mov R2,A
    inc DPTR
    movx A,@DPTR
    mov R3,A
    mov DPTR,#0x%04X""" % FP_CW + """
    movx A,@DPTR
    dec A
    add A,R3
    mov R5,A
    clr A
    addc A,R2
    mov R4,A
    mov DPTR,#0x%04X""" % FP_END + """
    movx @DPTR,A
    inc DPTR
    mov A,R5
    movx @DPTR,A
    ; visible columns: vx0 = max(x0, cx0) in R2:R3, vx1 = min(x1, cx1) in R4:R5
    mov DPTR,#0x%04X""" % FP_CX0 + """
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
    jnc hp_c0          ; x0 >= cx0
    mov A,R6
    mov R2,A
    mov A,R7
    mov R3,A
    hp_c0:
    mov DPTR,#0x%04X""" % FP_CX1 + """
    movx A,@DPTR
    mov R6,A
    inc DPTR
    movx A,@DPTR
    mov R7,A
    clr C
    mov A,R7
    subb A,R5
    mov A,R6
    subb A,R4
    jnc hp_c1          ; cx1 >= x1
    mov A,R6
    mov R4,A
    mov A,R7
    mov R5,A
    hp_c1:
    clr C
    mov A,R5
    subb A,R3
    mov A,R4
    subb A,R2
    jc hp_skip         ; vx1 < vx0: nothing of this cell is visible
    mov DPTR,#0x%04X""" % FP_VX0 + """
    mov A,R2
    movx @DPTR,A
    inc DPTR
    mov A,R3
    movx @DPTR,A
    inc DPTR
    mov A,R4
    movx @DPTR,A
    inc DPTR
    mov A,R5
    movx @DPTR,A
    lcall uk_cell
    hp_skip:
    mov DPTR,#0x%04X""" % FP_ADV + """
    movx A,@DPTR
    mov R7,A
    mov DPTR,#0x%04X""" % (FP_CUR + 1) + """
    movx A,@DPTR
    add A,R7
    movx @DPTR,A
    mov DPTR,#0x%04X""" % FP_CUR + """
    movx A,@DPTR
    addc A,#0
    movx @DPTR,A
    ljmp hp_char
    """)
        # uk_cell: window, then stream the visible columns
        S(a, """
    ; uk_cell: the visible columns FP_VX0..FP_VX1 of the glyph at FP_GLY in the cell at FP_CUR
    uk_cell:
    mov DPTR,#0x%04X""" % (FP_CUR + 1) + """
    movx A,@DPTR
    mov R7,A
    mov DPTR,#0x%04X""" % (FP_VX0 + 1) + """
    movx A,@DPTR
    clr C
    subb A,R7          ; off = vx0 - x0 (0..59)
    mov DPTR,#0x%04X""" % FP_OFF + """
    movx @DPTR,A
    ; window: x vx0..vx1, y FP_Y .. FP_Y + 8*bpc*scale - 1
    mov DPTR,#0x%04X""" % (FP_VX1) + """
    movx A,@DPTR
    mov R0,#0x2F
    movx @R0,A
    inc DPTR
    movx A,@DPTR
    inc R0
    movx @R0,A
    mov DPTR,#0x%04X""" % FP_BPC + """
    movx A,@DPTR
    rl A
    rl A
    rl A               ; rows at scale 1
    mov B,A
    mov DPTR,#0x%04X""" % FP_SCALE + """
    movx A,@DPTR
    mul AB
    dec A
    mov R5,A
    mov DPTR,#0x%04X""" % FP_Y + """
    movx A,@DPTR
    mov R7,A
    add A,R5
    mov R5,A
    clr A
    addc A,#0
    mov R4,A           ; R4:R5 = y1
    mov R6,#0          ; R6:R7 = y0
    mov DPTR,#0x%04X""" % FP_VX0 + """
    movx A,@DPTR
    mov R2,A
    inc DPTR
    movx A,@DPTR
    mov R3,A
    lcall 0x4437       ; lcd_set_window, ends with RAMWR
    ; start column: glyph + (off >> (scale - 1)) * bpc; F1 = off & 1 at scale 2
    clr F1
    clr F0
    mov DPTR,#0x%04X""" % FP_SCALE + """
    movx A,@DPTR
    mov R0,A
    mov DPTR,#0x%04X""" % FP_OFF + """
    movx A,@DPTR
    cjne R0,#2,hc_s1
    setb F0
    clr C
    rrc A
    mov F1,C
    hc_s1:
    mov R0,A
    mov DPTR,#0x%04X""" % FP_BPC + """
    movx A,@DPTR
    mov B,A
    mov A,R0
    mul AB
    mov R0,A
    mov DPTR,#0x%04X""" % (FP_GLY + 1) + """
    movx A,@DPTR
    add A,R0
    mov R1,A
    mov DPTR,#0x%04X""" % FP_GLY + """
    movx A,@DPTR
    addc A,#0
    push ACC
    push 0x01          ; R1
    ; columns to draw: vx1 - vx0 + 1
    mov DPTR,#0x%04X""" % (FP_VX0 + 1) + """
    movx A,@DPTR
    mov R0,A
    mov DPTR,#0x%04X""" % (FP_VX1 + 1) + """
    movx A,@DPTR
    clr C
    subb A,R0
    inc A
    mov R7,A
    ; colours: R2:R3 ink, R4:R5 background; B = bytes per column
    mov DPTR,#0x%04X""" % FP_INK + """
    movx A,@DPTR
    mov R2,A
    inc DPTR
    movx A,@DPTR
    mov R3,A
    inc DPTR
    movx A,@DPTR
    mov R4,A
    inc DPTR
    movx A,@DPTR
    mov R5,A
    mov DPTR,#0x%04X""" % FP_BPC + """
    movx A,@DPTR
    mov B,A
    pop DPL
    pop DPH
    setb P0.3          ; D/C = data
    clr P0.7           ; CS low
    jnb F0,hc_col1
    ljmp hc_col2
    """)
        for scale in (1, 2):
            pfx = "c%d" % scale
            S(a, """
    hc_col%d:
    mov R0,B
    %s_byte:
    clr A
    movc A,@A+DPTR
    inc DPTR""" % (scale, pfx))
            for bit in range(8):
                S(a, "rlc A\njc %s_i%d" % (pfx, bit))
                for _ in range(scale):
                    S(a, "mov P1,R4\nclr P0.5\nsetb P0.5\nmov P1,R5\nclr P0.5\nsetb P0.5")
                S(a, "sjmp %s_n%d\n%s_i%d:" % (pfx, bit, pfx, bit))
                for _ in range(scale):
                    S(a, "mov P1,R2\nclr P0.5\nsetb P0.5\nmov P1,R3\nclr P0.5\nsetb P0.5")
                S(a, "%s_n%d:" % (pfx, bit))
            S(a, "djnz R0,%s_more\nsjmp %s_coldone\n%s_more:\nljmp %s_byte\n%s_coldone:" % ((pfx,) * 5))
            if scale == 1:
                S(a, "djnz R7,c1_again\nsetb P0.7\nret\nc1_again:\nljmp hc_col1")
            else:
                S(a, """
    ; at scale 2 every glyph column is sent twice: F1 = this was the first copy -> rewind
    cpl F1
    jnb F1,c2_adv
    mov A,DPL
    clr C
    subb A,B
    mov DPL,A
    mov A,DPH
    subb A,#0
    mov DPH,A
    c2_adv:
    djnz R7,c2_again
    setb P0.7
    clr F0
    clr F1
    ret
    c2_again:
    ljmp hc_col2
    """)

    # ---- proportional text (pfont fonts) ----
    def tp_setup(self, a, font, string, space, x, y, ink, bg=0, clip=(0, 319), align=0, spacing=0):
        """Fill uk_text's parameter block. font: a pfont label; string: an address (int), a code label
        (str) or None (TP_STR already set); space: 0 XDATA, 1 code; x: int or None (TP_X already
        set); y: the top row of the font's cell (baseline + PFont.top); ink / bg: int, "theme"
        (RAM 0x48:0x49) or "acc" (uk_acc; for the ink only); align 0 left (x = first column),
        1 right (x = last column), 2 centred; spacing: extra columns after every character."""
        T = self.TP
        if ink == "acc":
            S(a, "lcall uk_acc")
        S(a, "mov DPTR,#0x%04X\nmov A,#hi(%s)\nmovx @DPTR,A\ninc DPTR\nmov A,#lo(%s)\nmovx @DPTR,A\ninc DPTR"
          % (T["FONT"], font, font))
        if isinstance(string, str):
            S(a, "mov A,#hi(%s)\nmovx @DPTR,A\ninc DPTR\nmov A,#lo(%s)\nmovx @DPTR,A\ninc DPTR" % (string, string))
        elif string is not None:
            S(a, "mov A,%s\nmovx @DPTR,A\ninc DPTR\nmov A,%s\nmovx @DPTR,A\ninc DPTR" % (hi(string), lo(string)))
        else:
            S(a, "inc DPTR\ninc DPTR")
        S(a, "mov A,#%d\nmovx @DPTR,A\ninc DPTR" % space)
        if x is not None:
            S(a, "mov A,%s\nmovx @DPTR,A\ninc DPTR\nmov A,%s\nmovx @DPTR,A\ninc DPTR" % (hi(x), lo(x)))
        else:
            S(a, "inc DPTR\ninc DPTR")
        S(a, "mov A,#%d\nmovx @DPTR,A\ninc DPTR" % y)
        for v in (ink, bg):
            if v == "theme":
                S(a, "mov A,0x48\nmovx @DPTR,A\ninc DPTR\nmov A,0x49\nmovx @DPTR,A\ninc DPTR")
            elif v == "acc":
                S(a, "mov A,R6\nmovx @DPTR,A\ninc DPTR\nmov A,R7\nmovx @DPTR,A\ninc DPTR")
            else:
                S(a, "mov A,%s\nmovx @DPTR,A\ninc DPTR\nmov A,%s\nmovx @DPTR,A\ninc DPTR" % (hi(v), lo(v)))
        for v in clip:
            S(a, "mov A,%s\nmovx @DPTR,A\ninc DPTR\nmov A,%s\nmovx @DPTR,A\ninc DPTR" % (hi(v), lo(v)))
        S(a, "mov A,#%d\nmovx @DPTR,A\ninc DPTR\nmov A,#%d\nmovx @DPTR,A" % (align, spacing))

    def emit_text(self, a):
        """uk_text (with uk_tfetch, uk_avg): the proportional text painter; needs tp_base."""
        T = self.tp
        S(a, """
; uk_avg: R6:R7 = the per-channel average of the RGB565 colours R2:R3 and R4:R5 (rounded down);
; keeps R0..R5
uk_avg:
mov A,R3
xrl A,R5
anl A,#0xDE
mov R7,A
mov A,R2
xrl A,R4
anl A,#0xF7
clr C
rrc A
mov R6,A
mov A,R7
rrc A
mov R7,A
mov A,R3
anl A,R5
add A,R7
mov R7,A
mov A,R2
anl A,R4
addc A,R6
mov R6,A
ret

; uk_tfetch: next character of the TP_STR string (TP_SPC: 0 XDATA, 1 code) -> A, R5; TP_STR
; advanced unless it is the terminating 0
uk_tfetch:
mov DPTR,#{STR}
movx A,@DPTR
mov R6,A
inc DPTR
movx A,@DPTR
mov R7,A
inc DPTR
movx A,@DPTR
mov DPH,R6
mov DPL,R7
jnz tf_code
movx A,@DPTR
sjmp tf_got
tf_code:
clr A
movc A,@A+DPTR
tf_got:
mov R5,A
jz tf_ret
inc DPTR
mov R6,DPH
mov R7,DPL
mov DPTR,#{STR}
mov A,R6
movx @DPTR,A
inc DPTR
mov A,R7
movx @DPTR,A
mov A,R5
tf_ret:
ret

; tx_glyph: character R5 -> TP_ADV (advance + TP_SPACING), TP_GOFF, TP_GW, TP_GLY; C set when the
; font has no glyph for it. Keeps R0..R3.
tx_glyph:
mov DPTR,#{FIRST}
movx A,@DPTR
mov R4,A
mov A,R5
clr C
subb A,R4
jc tx_none
mov R4,A
mov DPTR,#{N}
movx A,@DPTR
mov R6,A
mov A,R4
clr C
subb A,R6
jnc tx_none
mov DPTR,#{MAP}
movx A,@DPTR
mov R6,A
inc DPTR
movx A,@DPTR
mov DPL,A
mov DPH,R6
mov A,R4
movc A,@A+DPTR
cjne A,#0xFF,tx_have
tx_none:
setb C
ret
tx_have:
mov B,#5
mul AB
mov R7,A
mov R6,B
mov DPTR,#{TAB1}
movx A,@DPTR
add A,R7
mov R7,A
mov DPTR,#{TAB}
movx A,@DPTR
addc A,R6
mov R6,A
mov R4,#0
tg_copy:
mov DPH,R6
mov DPL,R7
mov A,R4
movc A,@A+DPTR
mov B,A
mov A,R4
add A,#{ADV_LO}
mov DPL,A
mov DPH,#{ADV_HI}
mov A,B
movx @DPTR,A
inc R4
cjne R4,#5,tg_copy
mov DPTR,#{SPACING}
movx A,@DPTR
mov R6,A
mov DPTR,#{ADV}
movx A,@DPTR
add A,R6
movx @DPTR,A
clr C
ret

; uk_text: draw the string in the TP block: font TP_FONT (a pfont), string TP_STR (TP_SPC 0 XDATA,
; 1 code), at TP_X (TP_ALIGN 0: first column, 1: last column, 2: centre), rows TP_Y .. TP_Y + H - 1,
; ink TP_INK on TP_BG, TP_SPACING extra columns per character, only the columns TP_CX0..TP_CX1.
; Each character is a cell of its advance (+ spacing) columns, background included. TP_END is the
; last column of the last cell (x - 1 for an empty string). TP_CX0 > TP_CX1: a measurement.
uk_text:
mov DPTR,#{FONT}
movx A,@DPTR
mov R6,A
inc DPTR
movx A,@DPTR
mov R7,A
mov R4,#0
ut_desc:
mov DPH,R6
mov DPL,R7
mov A,R4
movc A,@A+DPTR
mov B,A
mov A,R4
add A,#{H_LO}
mov DPL,A
mov DPH,#{H_HI}
mov A,B
movx @DPTR,A
inc R4
cjne R4,#9,ut_desc
; 4-level fonts: TP_C1 = 1/4 ink, TP_C2 = 3/4 ink
mov DPTR,#{FMT}
movx A,@DPTR
cjne A,#2,ut_align
""".format(**T))
        ld16(a, "R2", "R3", self.TP["INK"])
        ld16(a, "R4", "R5", self.TP["BG"])
        S(a, "lcall uk_avg          ; half")
        st16(a, self.TP["C2"], "R6", "R7")
        S(a, "mov A,R6\nmov R2,A\nmov A,R7\nmov R3,A   ; bg + half")
        S(a, "lcall uk_avg")
        st16(a, self.TP["C1"], "R6", "R7")
        ld16(a, "R2", "R3", self.TP["INK"])
        ld16(a, "R4", "R5", self.TP["C2"])
        S(a, "lcall uk_avg          ; ink + half")
        st16(a, self.TP["C2"], "R6", "R7")
        S(a, """
ut_align:
mov DPTR,#{ALIGN}
movx A,@DPTR
jz ut_start
; measure: R2:R3 = the string's width
mov DPTR,#{STR}
movx A,@DPTR
push ACC
inc DPTR
movx A,@DPTR
push ACC
mov R2,#0
mov R3,#0
ut_meas:
lcall uk_tfetch
jz ut_measd
lcall tx_glyph
jc ut_meas
mov DPTR,#{ADV}
movx A,@DPTR
add A,R3
mov R3,A
clr A
addc A,R2
mov R2,A
sjmp ut_meas
ut_measd:
mov DPTR,#{STR1}
pop ACC
movx @DPTR,A
mov DPTR,#{STR}
pop ACC
movx @DPTR,A
mov DPTR,#{ALIGN}
movx A,@DPTR
cjne A,#2,ut_right
; centre: x -= width / 2
clr C
mov A,R2
rrc A
mov R2,A
mov A,R3
rrc A
mov R3,A
sjmp ut_sub
ut_right:
; right: x -= width - 1
mov A,R3
clr C
subb A,#1
mov R3,A
mov A,R2
subb A,#0
mov R2,A
ut_sub:
mov DPTR,#{X1}
movx A,@DPTR
clr C
subb A,R3
movx @DPTR,A
mov DPTR,#{X}
movx A,@DPTR
subb A,R2
movx @DPTR,A
ut_start:
; TP_CUR = x, TP_END = x - 1
mov DPTR,#{X}
movx A,@DPTR
mov R6,A
inc DPTR
movx A,@DPTR
mov R7,A
mov DPTR,#{CUR}
mov A,R6
movx @DPTR,A
inc DPTR
mov A,R7
movx @DPTR,A
inc DPTR
clr C
mov A,R7
subb A,#1
mov R7,A
mov A,R6
subb A,#0
movx @DPTR,A
inc DPTR
mov A,R7
movx @DPTR,A
ut_char:
lcall uk_tfetch
jnz ut_have
ret
ut_have:
lcall tx_glyph
jc ut_char
mov DPTR,#{ADV}
movx A,@DPTR
jz ut_char
; cell: R2:R3 = x0 = TP_CUR, R4:R5 = x1 = x0 + advance - 1 = TP_END
mov R0,A
mov DPTR,#{CUR}
movx A,@DPTR
mov R2,A
inc DPTR
movx A,@DPTR
mov R3,A
mov A,R0
dec A
add A,R3
mov R5,A
clr A
addc A,R2
mov R4,A
mov DPTR,#{END}
movx @DPTR,A
inc DPTR
mov A,R5
movx @DPTR,A
; visible columns: vx0 = max(x0, cx0) in R2:R3, vx1 = min(x1, cx1) in R4:R5
mov DPTR,#{CX0}
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
jnc ut_c0
mov A,R6
mov R2,A
mov A,R7
mov R3,A
ut_c0:
mov DPTR,#{CX1}
movx A,@DPTR
mov R6,A
inc DPTR
movx A,@DPTR
mov R7,A
clr C
mov A,R7
subb A,R5
mov A,R6
subb A,R4
jnc ut_c1
mov A,R6
mov R4,A
mov A,R7
mov R5,A
ut_c1:
clr C
mov A,R5
subb A,R3
mov A,R4
subb A,R2
jc ut_next
mov DPTR,#{VX0}
mov A,R2
movx @DPTR,A
inc DPTR
mov A,R3
movx @DPTR,A
inc DPTR
mov A,R4
movx @DPTR,A
inc DPTR
mov A,R5
movx @DPTR,A
lcall tx_cell
ut_next:
mov DPTR,#{ADV}
movx A,@DPTR
mov R7,A
mov DPTR,#{CUR1}
movx A,@DPTR
add A,R7
movx @DPTR,A
mov DPTR,#{CUR}
movx A,@DPTR
addc A,#0
movx @DPTR,A
ljmp ut_char

; tx_cell: the visible columns TP_VX0..TP_VX1 of the glyph in the cell at TP_CUR: r0..r1 relative to
; the cell split into TP_L background columns, TP_I glyph columns from glyph column TP_S, TP_T
; background columns
tx_cell:
mov DPTR,#{CUR1}
movx A,@DPTR
mov R7,A
mov DPTR,#{VX01}
movx A,@DPTR
clr C
subb A,R7
mov R2,A           ; r0
mov DPTR,#{VX11}
movx A,@DPTR
clr C
subb A,R7
inc A
mov R3,A           ; r1 + 1
mov DPTR,#{GOFF}
movx A,@DPTR
mov R4,A           ; off
inc DPTR
movx A,@DPTR
add A,R4
mov R5,A           ; e = off + w
; L = min(r1 + 1, off) - r0, at least 0
mov A,R3
clr C
subb A,R4
mov A,R4
jnc tc_l1
mov A,R3
tc_l1:
clr C
subb A,R2
jnc tc_l2
clr A
tc_l2:
mov DPTR,#{L}
movx @DPTR,A
; a = max(r0, off) in R6; I = min(r1 + 1, e) - a, at least 0; S = a - off
mov A,R2
clr C
subb A,R4
mov A,R2
jnc tc_a
mov A,R4
tc_a:
mov R6,A
clr C
subb A,R4
mov DPTR,#{S}
movx @DPTR,A
mov A,R3
clr C
subb A,R5
mov A,R5
jnc tc_b
mov A,R3
tc_b:
clr C
subb A,R6
jnc tc_i
clr A
tc_i:
mov DPTR,#{I}
movx @DPTR,A
; T = r1 + 1 - max(r0, e), at least 0
mov A,R2
clr C
subb A,R5
mov A,R2
jnc tc_t1
mov A,R5
tc_t1:
mov R6,A
mov A,R3
clr C
subb A,R6
jnc tc_t2
clr A
tc_t2:
mov DPTR,#{T}
movx @DPTR,A
; window: x vx0..vx1, y TP_Y .. TP_Y + H - 1
mov DPTR,#{VX1}
movx A,@DPTR
mov R0,#0x2F
movx @R0,A
inc DPTR
movx A,@DPTR
inc R0
movx @R0,A
mov DPTR,#{H}
movx A,@DPTR
dec A
mov R5,A
mov DPTR,#{Y}
movx A,@DPTR
mov R7,A
add A,R5
mov R5,A
clr A
addc A,#0
mov R4,A
mov R6,#0
mov DPTR,#{VX0}
movx A,@DPTR
mov R2,A
inc DPTR
movx A,@DPTR
mov R3,A
lcall 0x4437       ; lcd_set_window, ends with RAMWR
setb P0.3          ; D/C = data
clr P0.7           ; CS low
mov DPTR,#{L}
lcall tx_bgcols
mov DPTR,#{I}
movx A,@DPTR
jz tc_trail
mov DPTR,#{FMT}
movx A,@DPTR
cjne A,#1,tc_rle
lcall tx_p1
sjmp tc_trail
tc_rle:
lcall tx_rle
tc_trail:
mov DPTR,#{T}
lcall tx_bgcols
setb P0.7          ; CS high
ret

; tx_bgcols: (@DPTR) * H pixels of TP_BG
tx_bgcols:
movx A,@DPTR
jz tb_ret
mov B,A
mov DPTR,#{H}
movx A,@DPTR
mul AB
mov R0,A           ; count lo
mov R1,B           ; count hi
jz tb_go
inc R1             ; djnz pair runs hi*256 + lo times
tb_go:
mov DPTR,#{BG}
movx A,@DPTR
mov R4,A
inc DPTR
movx A,@DPTR
mov R5,A
tb_px:
mov P1,R4
clr P0.5
setb P0.5
mov P1,R5
clr P0.5
setb P0.5
djnz R0,tb_px
djnz R1,tb_px
tb_ret:
ret

; tx_gly_at: DPTR = TP_GLY + TP_S * B
tx_gly_at:
mov DPTR,#{S}
movx A,@DPTR
mul AB
mov R7,A
mov R6,B
mov DPTR,#{GLY1}
movx A,@DPTR
add A,R7
mov R7,A
mov DPTR,#{GLY}
movx A,@DPTR
addc A,R6
mov DPH,A
mov DPL,R7
ret

; tx_p1: 1 bit per pixel, TP_I columns of bpc bytes from glyph column TP_S
tx_p1:
mov DPTR,#{BPC}
movx A,@DPTR
push ACC
mov B,A
mov DPTR,#{I}
movx A,@DPTR
mul AB
mov R0,A           ; bytes lo
mov R1,B           ; bytes hi
jz t1_cnt
inc R1
t1_cnt:
""".format(**T))
        ld16(a, "R2", "R3", self.TP["INK"])
        ld16(a, "R4", "R5", self.TP["BG"])
        S(a, "pop B\nlcall tx_gly_at\nt1_byte:\nclr A\nmovc A,@A+DPTR\ninc DPTR")
        for bit in range(8):
            S(a, "rlc A\njc t1_i%d" % bit)
            S(a, "mov P1,R4\nclr P0.5\nsetb P0.5\nmov P1,R5\nclr P0.5\nsetb P0.5")
            S(a, "sjmp t1_n%d\nt1_i%d:" % (bit, bit))
            S(a, "mov P1,R2\nclr P0.5\nsetb P0.5\nmov P1,R3\nclr P0.5\nsetb P0.5")
            S(a, "t1_n%d:" % bit)
        S(a, """
djnz R0,t1_more
djnz R1,t1_more
ret
t1_more:
ljmp t1_byte

; tx_rle: 4-level run-length glyph: bytes level << 6 | length (1..63), a stream of the glyph's
; columns top to bottom, ended by a 0. Skips TP_S * H pixels, then sends TP_I * H.
tx_rle:
mov DPTR,#{H}
movx A,@DPTR
mov B,A
mov DPTR,#{I}
movx A,@DPTR
mul AB
mov DPTR,#{CNT}
xch A,B
movx @DPTR,A
inc DPTR
xch A,B
movx @DPTR,A
; pixels to skip: S * H in R6:R7; DPTR = the glyph's first run
mov DPTR,#{H}
movx A,@DPTR
mov B,A
mov DPTR,#{S}
movx A,@DPTR
mul AB
mov R7,A
mov R6,B
mov DPTR,#{GLY}
movx A,@DPTR
mov R4,A
inc DPTR
movx A,@DPTR
mov DPL,A
mov DPH,R4
clr F0
setb F1            ; count unless the whole glyph is visible (S = 0, I = w)
push DPH
push DPL
mov DPTR,#{S}
movx A,@DPTR
jnz tr_part_vis
mov DPTR,#{I}
movx A,@DPTR
mov R4,A
mov DPTR,#{GW}
movx A,@DPTR
xrl A,R4
jnz tr_part_vis
clr F1
tr_part_vis:
pop DPL
pop DPH
tr_skip:
mov A,R6
orl A,R7
jz tr_colours
clr A
movc A,@A+DPTR
inc DPTR
mov R1,A           ; the run
anl A,#0x3F
mov R0,A           ; its length
clr C
mov A,R7
subb A,R0
mov R3,A
mov A,R6
subb A,#0
jc tr_part         ; the run crosses the end of the skip
mov R6,A
mov A,R3
mov R7,A
sjmp tr_skip
tr_part:
clr A
clr C
subb A,R3          ; what is left of the run: length - skip
mov R0,A
mov A,R1
push ACC
push 0x00
lcall tr_load
pop 0x00
pop ACC
ljmp tr_got
tr_colours:
lcall tr_load
jb F1,tr_next
sjmp tr_fnext
tr_fdone:
ret
; whole glyph: runs up to the 0 that ends it, nothing to count
tr_fnext:
clr A
movc A,@A+DPTR
inc DPTR
jz tr_fdone
jb ACC.7,tr_fhi
jb ACC.6,tr_f1
anl A,#0x3F
mov R0,A
sjmp tr_e0
tr_f1:
anl A,#0x3F
mov R0,A
sjmp tr_e1
tr_fhi:
jb ACC.6,tr_f3
anl A,#0x3F
mov R0,A
sjmp tr_e2
tr_f3:
anl A,#0x3F
mov R0,A
sjmp tr_e3
; part of the glyph (F1): count the pixels off TP_CNT
tr_next:
clr A
movc A,@A+DPTR
inc DPTR
push ACC
anl A,#0x3F
mov R0,A
pop ACC
tr_got:
; A = run, R0 = pixels; count them off TP_CNT, cut the run at the end
push ACC
push DPH
push DPL
mov DPTR,#{CNT1}
movx A,@DPTR
clr C
subb A,R0
movx @DPTR,A
mov DPTR,#{CNT}
movx A,@DPTR
subb A,#0
movx @DPTR,A
jc tr_cut
jnz tr_ok
inc DPTR
movx A,@DPTR
jnz tr_ok
setb F0            ; exactly used up
sjmp tr_ok
tr_cut:
inc DPTR
movx A,@DPTR       ; 256 - overshoot
add A,R0
mov R0,A
setb F0
tr_ok:
pop DPL
pop DPH
pop ACC
cjne R0,#0,tr_send
sjmp tr_after
tr_send:
jb ACC.7,tr_hi
jb ACC.6,tr_e1
tr_e0:
mov P1,R4
clr P0.5
setb P0.5
mov P1,R5
clr P0.5
setb P0.5
djnz R0,tr_e0
sjmp tr_after
tr_e1:
mov P1,B
clr P0.5
setb P0.5
mov P1,R1
clr P0.5
setb P0.5
djnz R0,tr_e1
sjmp tr_after
tr_hi:
jb ACC.6,tr_e3
tr_e2:
mov P1,R6
clr P0.5
setb P0.5
mov P1,R7
clr P0.5
setb P0.5
djnz R0,tr_e2
sjmp tr_after
tr_e3:
mov P1,R2
clr P0.5
setb P0.5
mov P1,R3
clr P0.5
setb P0.5
djnz R0,tr_e3
tr_after:
jb F1,tr_counted
ljmp tr_fnext
tr_counted:
jb F0,tr_done
ljmp tr_next
tr_done:
clr F0
clr F1
ret

; tr_load: colours of the four levels: R4:R5 background, B:R1 1/4, R6:R7 3/4, R2:R3 ink; keeps DPTR
tr_load:
push DPH
push DPL
""".format(**T))
        ld16(a, "R2", "R3", self.TP["INK"])
        ld16(a, "R4", "R5", self.TP["BG"])
        ld16(a, "R6", "R7", self.TP["C2"])
        ld16(a, "B", "R1", self.TP["C1"])
        S(a, "pop DPL\npop DPH\nret")

    def emit_tick_driver(self, a, ret_label):
        """uk_tasks: hook it on STOCK_SITES["tick"] (lcall). On a tick it runs main_tick_tasks, then,
        if the amp is on (RAM 0x4F = 1), falls through into the code emitted right after it (the
        theme's step routine, ending in ret); ret_label must be a ret in that routine."""
        S(a, """
; uk_tasks: replaces main_tasks_on's lcall main_tick_tasks (0x5B2A). When a 10 ms tick is pending,
; main_tick_tasks handles it (countdowns, renders, the periodic refresh) and then, with the amp on,
; the step routine that follows runs once.
uk_tasks:
jb 0x20.7,ht_tick
ljmp 0x3325
ht_tick:
lcall 0x3325
mov A,0x4F
cjne A,#1,%s""" % ret_label)


def build_image(*, base_path, base_sha, code_addr, assemble, hooks, patches=(), asserts=(),
                version_text, out_image, out_listing, title, label_prefixes=("uk_",)):
    """Build a theme image. hooks: [(address, original 3 bytes, opcode, target label)];
    patches: [(address, original bytes, function(labels) -> new bytes, listing note)];
    asserts: [(address, expected bytes, message)] checked on the base image."""
    img = bytearray(open(base_path, "rb").read())
    sha = hashlib.sha256(img).hexdigest()
    if sha != base_sha:
        raise SystemExit("base image %s has sha %s, expected %s" % (base_path, sha, base_sha))
    for addr, orig, _, _ in hooks:
        assert img[addr:addr + 3] == orig, "bytes at 0x%04X not as expected" % addr
    for addr, orig, _, _ in patches:
        assert img[addr:addr + len(orig)] == orig, "bytes at 0x%04X not as expected" % addr
    for addr, want, msg in asserts:
        assert img[addr:addr + len(want)] == want, msg
    assert len(img) <= code_addr

    code, labels, a = assemble()
    img += b"\xFF" * (code_addr - len(img))
    img += code

    lines = []
    for addr, orig, op, target in hooks:
        t = labels[target]
        img[addr:addr + 3] = bytes([op, t >> 8, t & 0xFF])
        lines.append("; 0x%04X: %s -> %02x %02x %02x  (%s)" % (addr, orig.hex(" "), op, t >> 8, t & 0xFF, target))
    for addr, orig, fn, note in patches:
        new = fn(labels)
        lines.append("; 0x%04X: %s -> %s  (%s)" % (addr, orig[:len(new)].hex(" "), new.hex(" "), note))
        img[addr:addr + len(new)] = new

    assert len(version_text) <= VERSION_MAX_LEN
    assert img[VERSION_PTR_ADDR] == 0x7A and img[VERSION_PTR_ADDR + 2] == 0x79
    ver = len(img)
    img += version_text.encode("ascii") + b"\0"
    img[VERSION_PTR_ADDR + 1] = ver >> 8
    img[VERSION_PTR_ADDR + 3] = ver & 0xFF
    assert len(img) <= CODE_END

    os.makedirs(os.path.dirname(out_image), exist_ok=True)
    open(out_image, "wb").write(img)
    with open(out_listing, "w") as f:
        f.write("; %s, generated by build_patch.py; do not edit\n" % title)
        f.write("\n".join(lines) + ("\n" if lines else ""))
        f.write("; version string %r at 0x%04X, pointer 0x%04X repointed\n\n" % (version_text, ver, VERSION_PTR_ADDR))
        f.write(a.listing())
    print("code %d bytes at 0x%04X..0x%04X" % (len(code), code_addr, code_addr + len(code) - 1))
    print("\n".join(ln[2:] for ln in lines))
    print("labels: " + " ".join("%s=0x%04X" % (k, v) for k, v in labels.items() if k.startswith(label_prefixes)))
    print("version %r at 0x%04X" % (version_text, ver))
    print("wrote %s (%d bytes, sha256 %s)" % (out_image, len(img), hashlib.sha256(img).hexdigest()))
    return img
