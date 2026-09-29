#!/usr/bin/env python3
"""Build the "House Numerals" image for the SMSL AO300 (on top of fast-lcd).

A reduced first build of study 3 in features/ui-theme/ui_themes.html:

  home      stock content; on page 1 the input name and the status line are
            left-aligned at x 16 (hooks in big_text_render 0x2A25 and
            small_text_render 0x3A82), and a 28x3 accent bar sits at 18,114
            (hook on home_refresh's tail 0x5C99).
  volume    entering page 2, a 2-px accent edge sweeps from x 318 to 0 with black
            behind it (hook on ui_render_page's clear call 0x2106). The page
            (jump-table entry 0x2143) shows the input name, a divider, "VOL",
            the volume in the stock big digits at 2x and a 240-px position line.
            volpage_draw_volume 0x5936 is replaced, so knob and remote steps
            redraw only the number and the line. Page 2 is actually entered from
            the four volume-key sites (0x0D33, 0x0DB3, 0x0E5A, 0x0F02), not through
            the page renderer alone; those sites get `lcall hn_enter_vol ; sjmp`
            past the stock "volume" caption. hn_enter_vol only sets a pending flag
            (HN_PEND). The key handler's common tail (0x0F48) writes the volume to the
            NJW1194 first, then calls 0x5936, and hn_draw_volume sees the flag, runs
            the wipe (about 200 ms, WIPE_DELAY_N) and the static page, then draws the
            number and the line. So the sound changes at once and only the picture
            takes its time. The page-2 renderer path (0x2106 / 0x2143) is unchanged
            and wipes too.
  unmute    the wipe blocks the main loop, which counts the unmute countdown RAM 0x43:0x44
            down once per 10 ms tick flag (0x20.7) and unmutes when it reaches 0. On
            Bluetooth without a stream (0x583F), optical/coax without lock and the
            headphone output with P2.6 low (Timer0) the firmware keeps re-arming it, so it
            never expires there; after power-on and input switches it runs out. hn_wipe:
            - countdown 1..HN_CD_MIN-1 (25 ticks): the unmute falls due during the wipe and
              the page after it, so the page opens with the fast clear, as in hn2; the same
              while post_power_on is still to run (0x20.3): a key pressed during the power-on
              logo is dispatched just before it, and its sequence must not wait;
            - otherwise it wipes, and hn_tick, called on each of the 160 steps, stands in for
              the main loop: it takes the tick flag and counts the countdown down, never
              below 1, handing the first tick back at the end so every tick is counted once
              and the main loop still runs the expiry itself. It also answers the first
              re-mute request 0x21.4 in the wipe (audio_apply_mute 0x58D3), as the main loop
              would: on optical/coax without lock the key handler's volume write is undone
              at the next tick.
            So the page wipes on every input once the unmute countdown is not about to
            expire, and the unmute comes at most one tick later than on fast-lcd (emulator:
            +0.01 s at worst). Other main-loop timers still stop for the 200 ms (README, Risks).

Accent: the theme colour (RAM 0x48:0x49), SMSL orange 0xFC43 on the White theme.
Everything goes through the fast pixel path of fast-lcd; hn_fill and hn_digit2x
stream bytes themselves, the text goes through the stock glyph painters.

Register use: every hn_* routine may clobber A, B, DPTR, PSW and R0-R7 (the stock
routines they replace or wrap do the same). 0x48:0x49 is saved and restored
around every drawing sequence. New state lives in XDATA 0x0100..0x0112.
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "patch"))
from asm51 import Asm, rel, ab  # noqa: E402

BASE_IMAGE = os.path.join(ROOT, "features", "fast-lcd", "build", "flash_fastlcd.bin")
BASE_SHA = "b292a64855975584dda5fe3fb282103bfde77f7f7237ca9945ac4b5442dae859"
OUT_IMAGE = os.path.join(HERE, "build", "flash_house_numerals.bin")
OUT_LISTING = os.path.join(HERE, "house_numerals.asm")

CODE_ADDR = 0x9800                  # after fast-lcd (code 0x9700..0x976B, version string)
NAMES = CODE_ADDR                   # 6 big-endian pointers, inputs 1..6
STR_VOL = CODE_ADDR + 12            # "VOL\0"

# stock routines and data
LCD_SET_WINDOW = 0x4437
SMALL_GLYPH = 0x2DF8
BIG_GLYPH = 0x3F3C
FONT_BIG = 0x6A23
HOME_DRAW_VOLUME = 0x5916
UI_CLEAR_SCREEN = 0x5D42
CLEAR_SMALL_BUF = 0x5CBC
CLEAR_BIG_BUF = 0x5CCB
RENDER_DONE = 0x22FA
LCD_CLEAR_BLACK = 0x51EE
INPUT_NAMES = [(1, 0x904F, "USB"), (2, 0x9053, "OPTICAL"), (3, 0x905B, "COAXIAL"),
               (4, 0x9048, "BT"), (5, 0x904B, "ARC"), (6, 0x9063, "AUX")]

P1 = 0x90
DC, WR, CS = 0x83, 0x85, 0x87       # bit addresses P0.3, P0.5, P0.7

# colours (RGB565)
ORANGE = 0xFC43                     # #ff8a1f, accent on the White theme
DIVIDER = 0x2104                    # #222
TRACK = 0x18E3                      # #1d1d1d

# XDATA
HN_THEME = 0x0100                   # saved 0x48:0x49
HN_ACC = 0x0102                     # accent colour
HN_N = 0x0104                       # hn_fill pixel count (hi, lo) ...
HN_C = 0x0106                       # ... immediately followed by its colour
HN_SP = 0x0108                      # hn_text: string pointer, x (2), y (1)
HN_TX = 0x010A
HN_TY = 0x010C
HN_VOL = 0x010D                     # volume being drawn (0..60)
HN_WX = 0x010E                      # wipe position (hi, lo)
HN_PEND = 0x0110                    # volume page pending: set by hn_enter_vol, cleared by hn_draw_volume
HN_TICK = 0x0111                    # hn_wipe: a main-loop tick has been taken (handed back at the end)
HN_REMUTE = 0x0112                  # hn_wipe: the main loop's re-mute request 0x21.4 answered once

POWER_ON_BIT = 0x03                 # bit 0x20.3: power-on path (0x55E4) set it, main_tasks_on runs post_power_on
TICK_BIT = 0x07                     # bit 0x20.7: Timer0 sets it every 10 ms, main_tick_10ms (0x3335) clears it
REMUTE_BIT = 0x0C                   # bit 0x21.4: re-mute request (Timer0 while optical/coax has no lock, INT1)
UNMUTED_BIT = 0x14                  # bit 0x22.4: audio unmuted (mute_state_set, audio_apply_mute read it)
AUDIO_APPLY_MUTE = 0x58D3           # 0x22.4 set: volume_apply; clear: NJW1194 to the mute code; then the DAC
# unmute countdown RAM 0x43:0x44 (main-loop ticks). At 1..HN_CD_MIN-1 the unmute falls due within the
# wipe (at most 21 ticks, plus one already pending) and the page drawn after it: no wipe then.
HN_CD_MIN = 25

# hn_wipe delay per 2-px step: `mov R6,#N ; d1: mov R7,#0 ; d2: djnz R7,d2 ; djnz R6,d1` is about
# 772 clocks per N (24 MHz). With N = 30 the 160 steps take about 200 ms in all.
WIPE_DELAY_N = 30

# (address, original bytes, new opcode, target label); the new bytes are opcode + target
HOOKS = [
    (0x2106, bytes([0x12, 0x5D, 0x42]), 0x12, "hn_clear"),        # lcall ui_clear_screen
    (0x2143, bytes([0x02, 0x21, 0x67]), 0x02, "hn_volpage"),      # page 2 jump-table entry
    (0x5936, bytes([0xAB, 0x07, 0xE5]), 0x02, "hn_draw_volume"),  # volpage_draw_volume entry
    (0x2A25, bytes([0xE4, 0x78, 0x02]), 0x02, "hn_align_big"),    # big_text_render: clr A; mov R0,#2
    (0x3A82, bytes([0xE4, 0x78, 0x02]), 0x02, "hn_align_small"),  # small_text_render: same
    (0x5C99, bytes([0x02, 0x59, 0x16]), 0x02, "hn_home_tail"),    # home_refresh: ljmp home_draw_volume
]

# where the volume keys open page 2 themselves (after `mov 0x45,#0x02`); 22 stock bytes each:
# lcall ui_clear_screen, load "volume", small_text_render at y 135. The first 5 become
# `lcall hn_enter_vol ; sjmp site+0x16`.
VOL_ENTRY_SITES = (0x0D33, 0x0DB3, 0x0E5A, 0x0F02)
VOL_ENTRY_ORIG = bytes.fromhex("125d427bff7a937947e4fdff124d3a7f877e00123a53")


def vol_entry_bytes(target):
    return bytes([0x12, target >> 8, target & 0xFF, 0x80, len(VOL_ENTRY_ORIG) - 5])


VERSION_TEXT = "v1.4 tbenr hn3"
VERSION_PTR_ADDR = 0x22CA
VERSION_MAX_LEN = 20


def mov_dptr(a, v):
    a.i("mov DPTR,#0x%04X" % v, 0x90, v >> 8, v & 0xFF)


def call(a, target, note=""):
    t = target if isinstance(target, str) else "0x%04X" % target
    a.i("lcall %s" % t + ("   ; " + note if note else ""), 0x12, ab(target))


def jump(a, target, note=""):
    t = target if isinstance(target, str) else "0x%04X" % target
    a.i("ljmp %s" % t + ("   ; " + note if note else ""), 0x02, ab(target))


def movr(a, n, v):
    a.i("mov R%d,#0x%02X" % (n, v), 0x78 + n, v)


def rect(a, x, w, y, h, colour=None):
    """Load hn_fill's arguments (colour None: R6:R7 already set)."""
    movr(a, 2, x >> 8); movr(a, 3, x & 0xFF); movr(a, 1, w); movr(a, 5, y); movr(a, 4, h)
    if colour is not None:
        movr(a, 6, colour >> 8); movr(a, 7, colour & 0xFF)


def xstore(a, *regs):
    """movx the named registers to consecutive XDATA from DPTR (DPTR already set)."""
    ops = {"R2": 0xEA, "R3": 0xEB, "R4": 0xEC, "R5": 0xED, "R6": 0xEE, "R7": 0xEF}
    for k, r in enumerate(regs):
        a.i("mov A,%s" % r, ops[r])
        a.i("movx @DPTR,A", 0xF0)
        if k < len(regs) - 1:
            a.i("inc DPTR", 0xA3)


def build_data(a):
    a.comment("input-name pointers for inputs 1..6 (stock strings), then the VOL label")
    a.L("names")
    for inp, addr, text in INPUT_NAMES:
        a.data("dw 0x%04X          ; input %d %s" % (addr, inp, text), [addr >> 8, addr & 0xFF])
    a.L("str_vol")
    a.data('db "VOL",0', b"VOL\0")


def build_primitives(a):
    a.comment("hn_fill: R2:R3 x, R1 w (1..255), R5 y, R4 h (1..170), R6:R7 colour")
    a.L("hn_fill")
    mov_dptr(a, HN_C)
    xstore(a, "R6", "R7")
    a.i("mov A,R1", 0xE9)
    a.i("mov B,R4", 0x8C, 0xF0)
    a.i("mul AB            ; B:A = w*h", 0xA4)
    mov_dptr(a, HN_N)
    a.i("xch A,B", 0xC5, 0xF0)
    a.i("movx @DPTR,A      ; count hi", 0xF0)
    a.i("inc DPTR", 0xA3)
    a.i("xch A,B", 0xC5, 0xF0)
    a.i("movx @DPTR,A      ; count lo", 0xF0)
    a.i("mov A,R1", 0xE9)
    a.i("dec A", 0x14)
    a.i("add A,R3          ; x1 = x + w - 1", 0x2B)
    a.i("mov R0,#0x30", 0x78, 0x30)
    a.i("movx @R0,A", 0xF2)
    a.i("clr A", 0xE4)
    a.i("addc A,R2", 0x3A)
    a.i("dec R0", 0x18)
    a.i("movx @R0,A", 0xF2)
    a.i("mov A,R5", 0xED)
    a.i("mov R7,A          ; y0", 0xFF)
    a.i("mov R6,#0", 0x7E, 0x00)
    a.i("mov A,R4", 0xEC)
    a.i("dec A", 0x14)
    a.i("add A,R5          ; y1 = y + h - 1", 0x2D)
    a.i("mov R5,A", 0xFD)
    a.i("mov R4,#0", 0x7C, 0x00)
    call(a, LCD_SET_WINDOW, "lcd_set_window, ends with RAMWR")
    mov_dptr(a, HN_N)
    a.i("movx A,@DPTR", 0xE0); a.i("mov R5,A          ; count hi", 0xFD); a.i("inc DPTR", 0xA3)
    a.i("movx A,@DPTR", 0xE0); a.i("mov R4,A          ; count lo", 0xFC); a.i("inc DPTR", 0xA3)
    a.i("movx A,@DPTR", 0xE0); a.i("mov R6,A          ; colour hi", 0xFE); a.i("inc DPTR", 0xA3)
    a.i("movx A,@DPTR", 0xE0); a.i("mov R7,A          ; colour lo", 0xFF)
    a.i("mov A,R4", 0xEC)
    a.i("jz hf_go", 0x60, rel("hf_go"))
    a.i("inc R5            ; djnz pair runs hi*256 + lo times", 0x0D)
    a.L("hf_go")
    a.i("setb P0.3          ; D/C = data", 0xD2, DC)
    a.i("clr P0.7           ; CS low", 0xC2, CS)
    a.L("hf_px")
    a.i("mov P1,R6", 0x8E, P1)
    a.i("clr P0.5", 0xC2, WR)
    a.i("setb P0.5", 0xD2, WR)
    a.i("mov P1,R7", 0x8F, P1)
    a.i("clr P0.5", 0xC2, WR)
    a.i("setb P0.5", 0xD2, WR)
    a.i("djnz R4,hf_px", 0xDC, rel("hf_px"))
    a.i("djnz R5,hf_px", 0xDD, rel("hf_px"))
    a.i("setb P0.7          ; CS high", 0xD2, CS)
    a.i("ret", 0x22)

    a.comment("hn_begin: save the theme colour, work out the accent")
    a.L("hn_begin")
    mov_dptr(a, HN_THEME)
    a.i("mov A,0x48", 0xE5, 0x48); a.i("movx @DPTR,A", 0xF0); a.i("inc DPTR", 0xA3)
    a.i("mov A,0x49", 0xE5, 0x49); a.i("movx @DPTR,A", 0xF0)
    a.i("inc DPTR          ; HN_ACC", 0xA3)
    a.i("mov A,0x48", 0xE5, 0x48)
    a.i("anl A,0x49", 0x55, 0x49)
    a.i("cpl A             ; 0 only on the White theme", 0xF4)
    a.i("jnz hb_theme", 0x70, rel("hb_theme"))
    a.i("mov A,#0x%02X" % (ORANGE >> 8), 0x74, ORANGE >> 8); a.i("movx @DPTR,A", 0xF0); a.i("inc DPTR", 0xA3)
    a.i("mov A,#0x%02X" % (ORANGE & 0xFF), 0x74, ORANGE & 0xFF); a.i("movx @DPTR,A", 0xF0)
    a.i("ret", 0x22)
    a.L("hb_theme")
    a.i("mov A,0x48", 0xE5, 0x48); a.i("movx @DPTR,A", 0xF0); a.i("inc DPTR", 0xA3)
    a.i("mov A,0x49", 0xE5, 0x49); a.i("movx @DPTR,A", 0xF0)
    a.i("ret", 0x22)

    a.comment("hn_end: restore the theme colour")
    a.L("hn_end")
    mov_dptr(a, HN_THEME)
    a.i("movx A,@DPTR", 0xE0); a.i("mov 0x48,A", 0xF5, 0x48); a.i("inc DPTR", 0xA3)
    a.i("movx A,@DPTR", 0xE0); a.i("mov 0x49,A", 0xF5, 0x49)
    a.i("ret", 0x22)

    a.comment("hn_accent: ink and R6:R7 = accent; keeps R1..R5")
    a.L("hn_accent")
    mov_dptr(a, HN_ACC)
    a.i("movx A,@DPTR", 0xE0); a.i("mov 0x48,A", 0xF5, 0x48); a.i("mov R6,A", 0xFE); a.i("inc DPTR", 0xA3)
    a.i("movx A,@DPTR", 0xE0); a.i("mov 0x49,A", 0xF5, 0x49); a.i("mov R7,A", 0xFF)
    a.i("ret", 0x22)

    a.comment("hn_white: ink = white")
    a.L("hn_white")
    a.i("mov 0x48,#0xFF", 0x75, 0x48, 0xFF)
    a.i("mov 0x49,#0xFF", 0x75, 0x49, 0xFF)
    a.i("ret", 0x22)

    a.comment("hn_name_ptr: input 0x47 in 1..6 -> C=0, R2:R3 = name; else C=1")
    a.L("hn_name_ptr")
    a.i("mov A,0x47", 0xE5, 0x47)
    a.i("dec A", 0x14)
    a.i("cjne A,#6,hnp_cmp ; C = (input - 1 < 6)", 0xB4, 0x06, rel("hnp_cmp"))
    a.L("hnp_cmp")
    a.i("jnc hnp_none", 0x50, rel("hnp_none"))
    a.i("rl A", 0x23)
    a.i("mov B,A", 0xF5, 0xF0)
    a.i("mov DPTR,#names", 0x90, ab("names"))
    a.i("movc A,@A+DPTR", 0x93); a.i("mov R2,A", 0xFA)
    a.i("mov A,B", 0xE5, 0xF0); a.i("inc A", 0x04)
    a.i("movc A,@A+DPTR", 0x93); a.i("mov R3,A", 0xFB)
    a.i("clr C", 0xC3)
    a.i("ret", 0x22)
    a.L("hnp_none")
    a.i("setb C", 0xD3)
    a.i("ret", 0x22)

    a.comment("hn_text: R2:R3 code string, R4:R5 x, R7 y; ink 0x48:0x49, 14 px per character")
    a.L("hn_text")
    mov_dptr(a, HN_SP)
    xstore(a, "R2", "R3", "R4", "R5", "R7")          # HN_SP, HN_TX, HN_TY
    a.L("ht_next")
    mov_dptr(a, HN_SP)
    a.i("movx A,@DPTR", 0xE0); a.i("mov R6,A", 0xFE); a.i("inc DPTR", 0xA3); a.i("movx A,@DPTR", 0xE0)
    a.i("mov DPL,A", 0xF5, 0x82)
    a.i("mov DPH,R6", 0x8E, 0x83)
    a.i("clr A", 0xE4)
    a.i("movc A,@A+DPTR", 0x93)
    a.i("jz ht_done", 0x60, rel("ht_done"))
    a.i("mov R3,A          ; character", 0xFB)
    a.i("inc DPTR", 0xA3)
    a.i("mov R6,DPH", 0xAE, 0x83)
    a.i("mov R7,DPL", 0xAF, 0x82)
    mov_dptr(a, HN_SP)
    a.i("mov A,R6", 0xEE); a.i("movx @DPTR,A", 0xF0); a.i("inc DPTR", 0xA3)
    a.i("mov A,R7", 0xEF); a.i("movx @DPTR,A", 0xF0); a.i("inc DPTR", 0xA3)
    a.i("movx A,@DPTR", 0xE0); a.i("mov R4,A          ; x", 0xFC); a.i("inc DPTR", 0xA3)
    a.i("movx A,@DPTR", 0xE0); a.i("mov R5,A", 0xFD); a.i("inc DPTR", 0xA3)
    a.i("movx A,@DPTR", 0xE0); a.i("mov R7,A          ; y", 0xFF)
    a.i("mov R6,#0", 0x7E, 0x00)
    call(a, SMALL_GLYPH, "small_glyph_paint(R6:R7 y, R4:R5 x, R3 char)")
    mov_dptr(a, HN_TX + 1)
    a.i("movx A,@DPTR", 0xE0); a.i("add A,#14", 0x24, 14); a.i("movx @DPTR,A", 0xF0)
    mov_dptr(a, HN_TX)
    a.i("movx A,@DPTR", 0xE0); a.i("addc A,#0", 0x34, 0x00); a.i("movx @DPTR,A", 0xF0)
    a.i("sjmp ht_next", 0x80, rel("ht_next"))
    a.L("ht_done")
    a.i("ret", 0x22)

    a.comment("hn_digit2x: R3 digit, R5 x, R7 y; stock big glyph at 2x (60x64), ink on black")
    a.L("hn_digit2x")
    a.i("mov A,R5", 0xED)
    a.i("add A,#59         ; x1 = x + 59", 0x24, 59)
    a.i("mov R0,#0x30", 0x78, 0x30); a.i("movx @R0,A", 0xF2)
    a.i("clr A", 0xE4); a.i("addc A,#0", 0x34, 0x00)
    a.i("dec R0", 0x18); a.i("movx @R0,A", 0xF2)
    a.i("mov A,R3", 0xEB)
    a.i("push ACC          ; digit", 0xC0, 0xE0)
    a.i("mov A,R5", 0xED); a.i("mov R3,A          ; x0", 0xFB); a.i("mov R2,#0", 0x7A, 0x00)
    a.i("mov A,R7", 0xEF); a.i("add A,#63         ; y1", 0x24, 63); a.i("mov R5,A", 0xFD)
    a.i("mov R4,#0", 0x7C, 0x00); a.i("mov R6,#0", 0x7E, 0x00)
    call(a, LCD_SET_WINDOW)
    a.i("pop ACC", 0xD0, 0xE0)
    a.i("add A,#6          ; font index of the digit", 0x24, 6)
    a.i("mov B,#120", 0x75, 0xF0, 120)
    a.i("mul AB", 0xA4)
    a.i("add A,#0x%02X" % (FONT_BIG & 0xFF), 0x24, FONT_BIG & 0xFF)
    a.i("mov DPL,A", 0xF5, 0x82)
    a.i("mov A,B", 0xE5, 0xF0)
    a.i("addc A,#0x%02X" % (FONT_BIG >> 8), 0x34, FONT_BIG >> 8)
    a.i("mov DPH,A", 0xF5, 0x83)
    a.i("mov R2,0x48", 0xAA, 0x48)
    a.i("mov R3,0x49", 0xAB, 0x49)
    a.i("setb P0.3", 0xD2, DC)
    a.i("clr P0.7", 0xC2, CS)
    a.i("mov R4,#30        ; glyph columns", 0x7C, 30)
    a.L("d2_col")
    a.i("mov R0,#2         ; every column twice", 0x78, 2)
    a.L("d2_rep")
    a.i("push DPL", 0xC0, 0x82)
    a.i("push DPH", 0xC0, 0x83)
    a.i("mov R5,#4         ; 4 bytes = 32 rows", 0x7D, 4)
    a.L("d2_byte")
    a.i("clr A", 0xE4); a.i("movc A,@A+DPTR", 0x93); a.i("inc DPTR", 0xA3); a.i("mov R6,A", 0xFE)
    a.i("mov R1,#8", 0x79, 8)
    a.L("d2_bit")
    a.i("mov A,R6", 0xEE)
    a.i("rlc A             ; top pixel first", 0x33)
    a.i("mov R6,A", 0xFE)
    a.i("jc d2_ink", 0x40, rel("d2_ink"))
    a.i("mov P1,#0         ; 2 black pixels = 4 zero bytes", 0x75, P1, 0x00)
    for _ in range(4):
        a.i("clr P0.5", 0xC2, WR)
        a.i("setb P0.5", 0xD2, WR)
    a.i("sjmp d2_next", 0x80, rel("d2_next"))
    a.L("d2_ink")
    for _ in range(2):
        a.i("mov P1,R2", 0x8A, P1); a.i("clr P0.5", 0xC2, WR); a.i("setb P0.5", 0xD2, WR)
        a.i("mov P1,R3", 0x8B, P1); a.i("clr P0.5", 0xC2, WR); a.i("setb P0.5", 0xD2, WR)
    a.L("d2_next")
    a.i("djnz R1,d2_bit", 0xD9, rel("d2_bit"))
    a.i("djnz R5,d2_byte", 0xDD, rel("d2_byte"))
    a.i("pop DPH", 0xD0, 0x83)
    a.i("pop DPL", 0xD0, 0x82)
    a.i("djnz R0,d2_rep", 0xD8, rel("d2_rep"))
    for _ in range(4):
        a.i("inc DPTR          ; next glyph column", 0xA3)
    a.i("djnz R4,d2_col", 0xDC, rel("d2_col"))
    a.i("setb P0.7", 0xD2, CS)
    a.i("ret", 0x22)


def build_volume_page(a):
    a.comment("hn_draw_volume: replaces volpage_draw_volume 0x5936 (R7 speaker volume)")
    a.L("hn_draw_volume")
    a.i("mov A,0x2B", 0xE5, 0x2B)
    a.i("xrl A,#1", 0x64, 0x01)
    a.i("jz hdv_spk", 0x60, rel("hdv_spk"))
    a.i("mov R7,0x52       ; headphone volume, as stock", 0xAF, 0x52)
    a.L("hdv_spk")
    a.i("mov A,R7", 0xEF)
    a.i("cjne A,#61,hdv_c", 0xB4, 61, rel("hdv_c"))
    a.L("hdv_c")
    a.i("jc hdv_ok", 0x40, rel("hdv_ok"))
    a.i("mov A,#60", 0x74, 60)
    a.L("hdv_ok")
    mov_dptr(a, HN_VOL)
    a.i("movx @DPTR,A", 0xF0)
    mov_dptr(a, HN_PEND)
    a.i("movx A,@DPTR      ; page opened by a volume key? wipe first", 0xE0)
    a.i("jz hdv_draw", 0x60, rel("hdv_draw"))
    a.i("clr A", 0xE4)
    a.i("movx @DPTR,A", 0xF0)
    call(a, "hn_wipe")
    call(a, "hn_vol_static")
    a.L("hdv_draw")
    a.i("mov R0,#5", 0x78, 0x05)
    a.i("mov A,#2", 0x74, 0x02)
    a.i("movx @R0,A        ; stock leaves the digit count 2 in XDATA 0x05", 0xF2)
    call(a, "hn_begin")
    call(a, "hn_white")
    mov_dptr(a, HN_VOL)
    a.i("movx A,@DPTR", 0xE0)
    a.i("mov B,#10", 0x75, 0xF0, 10)
    a.i("div AB            ; A tens, B ones", 0x84)
    a.i("push B", 0xC0, 0xF0)
    a.i("jnz hdv_tens", 0x70, rel("hdv_tens"))
    rect(a, 184, 60, 42, 64, 0x0000)
    call(a, "hn_fill", "blank tens digit")
    a.i("sjmp hdv_ones", 0x80, rel("hdv_ones"))
    a.L("hdv_tens")
    a.i("mov R3,A", 0xFB); movr(a, 5, 184); movr(a, 7, 42)
    call(a, "hn_digit2x")
    a.L("hdv_ones")
    a.i("pop ACC", 0xD0, 0xE0)
    a.i("mov R3,A", 0xFB); movr(a, 5, 244); movr(a, 7, 42)
    call(a, "hn_digit2x")
    mov_dptr(a, HN_VOL)
    a.i("movx A,@DPTR", 0xE0)
    a.i("rl A", 0x23)
    a.i("rl A              ; filled width = 4 px per step (<= 240)", 0x23)
    a.i("jz hdv_rest", 0x60, rel("hdv_rest"))
    a.i("push ACC", 0xC0, 0xE0)
    a.i("mov R1,A", 0xF9)
    call(a, "hn_accent")
    movr(a, 2, 0); movr(a, 3, 40); movr(a, 5, 136); movr(a, 4, 3)
    call(a, "hn_fill", "filled part of the line")
    a.i("pop ACC", 0xD0, 0xE0)
    a.L("hdv_rest")
    a.i("cjne A,#240,hdv_r2", 0xB4, 240, rel("hdv_r2"))
    a.i("sjmp hdv_done", 0x80, rel("hdv_done"))
    a.L("hdv_r2")
    a.i("mov R0,A", 0xF8)
    a.i("add A,#40", 0x24, 40); a.i("mov R3,A", 0xFB)
    a.i("clr A", 0xE4); a.i("addc A,#0", 0x34, 0x00); a.i("mov R2,A          ; x = 40 + filled", 0xFA)
    a.i("clr C", 0xC3); a.i("mov A,#240", 0x74, 240); a.i("subb A,R0", 0x98); a.i("mov R1,A", 0xF9)
    movr(a, 5, 136); movr(a, 4, 3); movr(a, 6, TRACK >> 8); movr(a, 7, TRACK & 0xFF)
    call(a, "hn_fill", "rest of the line")
    a.L("hdv_done")
    jump(a, "hn_end")

    a.comment("hn_vol_static: the parts of the volume page that don't depend on the volume")
    a.L("hn_vol_static")
    call(a, "hn_begin")
    call(a, "hn_white")
    call(a, "hn_name_ptr")
    a.i("jc hvp_noname", 0x40, rel("hvp_noname"))
    movr(a, 4, 0); movr(a, 5, 16); movr(a, 7, 30)
    call(a, "hn_text", "input name")
    a.L("hvp_noname")
    rect(a, 140, 1, 14, 104, DIVIDER)
    call(a, "hn_fill", "divider")
    call(a, "hn_accent")
    movr(a, 2, STR_VOL >> 8); movr(a, 3, STR_VOL & 0xFF); movr(a, 4, 0); movr(a, 5, 158); movr(a, 7, 14)
    call(a, "hn_text", "VOL")
    jump(a, "hn_end")

    a.comment("hn_volpage: page 2 renderer (replaces 0x2167)")
    a.L("hn_volpage")
    call(a, "hn_vol_static")
    a.i("mov R7,0x31", 0xAF, 0x31)
    call(a, "hn_draw_volume")
    jump(a, RENDER_DONE, "clears 0x22.3, 0x32, 0x46 like every page")

    a.comment("hn_enter_vol: where a volume key opens page 2 (4 sites): only flag it; the wipe and the")
    a.comment("static page are drawn by hn_draw_volume, after the key handler has written the volume")
    a.L("hn_enter_vol")
    mov_dptr(a, HN_PEND)
    a.i("mov A,#1", 0x74, 0x01)
    a.i("movx @DPTR,A", 0xF0)
    a.i("ret", 0x22)

    a.comment("hn_clear: replaces lcall ui_clear_screen at 0x2106; page in 0x59")
    a.L("hn_clear")
    a.i("mov A,0x59", 0xE5, 0x59)
    a.i("cjne A,#2,hc_stock", 0xB4, 0x02, rel("hc_stock"))
    a.i("sjmp hn_wipe", 0x80, rel("hn_wipe"))
    a.L("hc_stock")
    jump(a, UI_CLEAR_SCREEN, "other pages: stock clear")
    a.comment("hn_wipe: clear the text buffers, then the accent edge from x 318 to 0")
    a.L("hn_wipe")
    call(a, CLEAR_SMALL_BUF, "as ui_clear_screen")
    call(a, CLEAR_BIG_BUF)
    a.comment("fast clear instead of the wipe (1) while post_power_on is still to run (0x20.3: a key queued")
    a.comment("during the power-on logo is dispatched first; its audio sequence and the unmute countdown")
    a.comment("must not wait), (2) with the unmute countdown (RAM 0x43:0x44) at 1..HN_CD_MIN-1: the unmute")
    a.comment("falls due during the wipe and the page after it")
    a.i("jb 0x20.3,hw_fast   ; post_power_on pending", 0x20, POWER_ON_BIT, rel("hw_fast"))
    a.i("mov A,0x43", 0xE5, 0x43)
    a.i("jnz hw_go         ; 256 or more", 0x70, rel("hw_go"))
    a.i("mov A,0x44", 0xE5, 0x44)
    a.i("jz hw_go          ; 0: not running", 0x60, rel("hw_go"))
    a.i("clr C", 0xC3)
    a.i("subb A,#%d        ; C = countdown < HN_CD_MIN" % HN_CD_MIN, 0x94, HN_CD_MIN)
    a.i("jnc hw_go", 0x50, rel("hw_go"))
    a.L("hw_fast")
    jump(a, LCD_CLEAR_BLACK, "the fast clear ui_clear_screen ends with; returns to our caller")
    a.L("hw_go")
    mov_dptr(a, HN_TICK)
    a.i("clr A             ; no main-loop tick taken yet", 0xE4)
    a.i("movx @DPTR,A", 0xF0)
    a.i("inc DPTR          ; HN_REMUTE: no re-mute answered yet", 0xA3)
    a.i("movx @DPTR,A", 0xF0)
    call(a, "hn_begin")
    mov_dptr(a, HN_WX)
    a.i("mov A,#0x01", 0x74, 0x01); a.i("movx @DPTR,A", 0xF0); a.i("inc DPTR", 0xA3)
    a.i("mov A,#0x3E       ; x = 318", 0x74, 0x3E); a.i("movx @DPTR,A", 0xF0)
    a.L("hc_step")
    call(a, "hn_tick", "count the unmute countdown down while the main loop waits")
    call(a, "hn_accent")
    call(a, "hc_load")
    movr(a, 1, 2); movr(a, 5, 0); movr(a, 4, 170)
    call(a, "hn_fill", "2-px edge at x")
    call(a, "hc_load")
    a.i("mov A,R2", 0xEA)
    a.i("jz hc_black       ; x < 256", 0x60, rel("hc_black"))
    a.i("cjne R3,#0x3E,hc_black", 0xBB, 0x3E, rel("hc_black"))
    a.i("sjmp hc_dec       ; x = 318: nothing right of the edge yet", 0x80, rel("hc_dec"))
    a.L("hc_black")
    a.i("mov A,R3", 0xEB); a.i("add A,#2", 0x24, 2); a.i("mov R3,A", 0xFB)
    a.i("clr A", 0xE4); a.i("addc A,R2", 0x3A); a.i("mov R2,A", 0xFA)
    movr(a, 1, 2); movr(a, 5, 0); movr(a, 4, 170); movr(a, 6, 0); movr(a, 7, 0)
    call(a, "hn_fill", "black where the edge was")
    a.L("hc_dec")
    a.comment("delay: R6, R7 are free here (hc_load reloads them); N = WIPE_DELAY_N for a ~200 ms wipe")
    movr(a, 6, WIPE_DELAY_N)
    a.L("hc_d1")
    movr(a, 7, 0)
    a.L("hc_d2")
    a.i("djnz R7,hc_d2", 0xDF, rel("hc_d2"))
    a.i("djnz R6,hc_d1", 0xDE, rel("hc_d1"))
    call(a, "hc_load")
    a.i("mov A,R2", 0xEA); a.i("orl A,R3", 0x4B)
    a.i("jz hc_last", 0x60, rel("hc_last"))
    a.i("clr C", 0xC3)
    a.i("mov A,R3", 0xEB); a.i("subb A,#2", 0x94, 2); a.i("mov R3,A", 0xFB)
    a.i("mov A,R2", 0xEA); a.i("subb A,#0", 0x94, 0); a.i("mov R2,A", 0xFA)
    mov_dptr(a, HN_WX)
    xstore(a, "R2", "R3")
    jump(a, "hc_step")
    a.L("hc_last")
    rect(a, 0, 2, 0, 170, 0x0000)
    call(a, "hn_fill", "the edge leaves at x 0")
    a.comment("the first tick hn_tick took is handed back: the main loop runs it (all its countdowns) once")
    mov_dptr(a, HN_TICK)
    a.i("movx A,@DPTR", 0xE0)
    a.i("jz hc_end", 0x60, rel("hc_end"))
    a.i("setb 0x20.7        ; main-loop tick flag", 0xD2, TICK_BIT)
    a.L("hc_end")
    jump(a, "hn_end")

    a.comment("hn_tick: once per wipe step (1.25 ms), stands in for the two main-loop duties that touch the")
    a.comment("audio. First the re-mute request 0x21.4 (main_tick_tasks 0x3325 answers it on every pass): the key")
    a.comment("handler has just written the new volume to the NJW1194, and on optical/coax without lock Timer0")
    a.comment("asks for the mute again at the next tick. The first request in the wipe is answered here; after it")
    a.comment("0x22.4 stays clear until the wipe ends, so repeats would write the same values (5.2 ms each) and")
    a.comment("wait for the main loop instead.")
    a.L("hn_tick")
    a.i("jnb 0x21.4,ht_tick ; no re-mute request", 0x30, REMUTE_BIT, rel("ht_tick"))
    mov_dptr(a, HN_REMUTE)
    a.i("movx A,@DPTR", 0xE0)
    a.i("jnz ht_tick        ; answered once in this wipe", 0x70, rel("ht_tick"))
    a.i("inc A", 0x04)
    a.i("movx @DPTR,A", 0xF0)
    a.i("clr 0x21.4         ; as main_tick_tasks 0x3325..0x332C", 0xC2, REMUTE_BIT)
    a.i("clr 0x22.4", 0xC2, UNMUTED_BIT)
    call(a, AUDIO_APPLY_MUTE, "audio_apply_mute: NJW1194 to the mute code, DAC")
    a.L("ht_tick")
    a.comment("Then the tick (1.25 ms per step, so no 10 ms tick is missed). While the unmute countdown")
    a.comment("runs, take the main loop's tick flag 0x20.7 and count 0x43:0x44 down as the main loop would,")
    a.comment("never below 1: the tick that takes it to 0 (and unmutes) stays with the main loop. The first")
    a.comment("tick taken is not counted here; hn_wipe sets the flag again at the end and the main loop counts")
    a.comment("it, so the countdown sees every tick exactly once and the other countdowns one, as before.")
    a.i("jnb 0x20.7,ht_ret  ; no tick since the last step", 0x30, TICK_BIT, rel("ht_ret"))
    a.i("mov A,0x43", 0xE5, 0x43)
    a.i("jnz ht_take", 0x70, rel("ht_take"))
    a.i("mov A,0x44", 0xE5, 0x44)
    a.i("clr C", 0xC3)
    a.i("subb A,#2", 0x94, 2)
    a.i("jc ht_ret          ; 0 (not running) or 1: leave the tick to the main loop", 0x40, rel("ht_ret"))
    a.L("ht_take")
    a.i("clr 0x20.7", 0xC2, TICK_BIT)
    mov_dptr(a, HN_TICK)
    a.i("movx A,@DPTR", 0xE0)
    a.i("jnz ht_dec", 0x70, rel("ht_dec"))
    a.i("inc A", 0x04)
    a.i("movx @DPTR,A       ; first tick: counted by the main loop after the wipe", 0xF0)
    a.i("ret", 0x22)
    a.L("ht_dec")
    a.i("mov A,0x44", 0xE5, 0x44)
    a.i("jnz ht_lo", 0x70, rel("ht_lo"))
    a.i("dec 0x43", 0x15, 0x43)
    a.L("ht_lo")
    a.i("dec 0x44           ; countdown >= 2 here, so it stays >= 1", 0x15, 0x44)
    a.L("ht_ret")
    a.i("ret", 0x22)
    a.L("hc_load")
    mov_dptr(a, HN_WX)
    a.i("movx A,@DPTR", 0xE0); a.i("mov R2,A", 0xFA); a.i("inc DPTR", 0xA3)
    a.i("movx A,@DPTR", 0xE0); a.i("mov R3,A", 0xFB)
    a.i("ret", 0x22)


def build_home(a):
    a.comment("hn_home_tail: replaces home_refresh's ljmp 0x5916; adds the accent bar")
    a.L("hn_home_tail")
    mov_dptr(a, HN_PEND)
    a.i("clr A             ; no volume page pending on the home screen", 0xE4)
    a.i("movx @DPTR,A", 0xF0)
    call(a, HOME_DRAW_VOLUME, "as before, R7 = volume")
    call(a, "hn_begin")
    call(a, "hn_accent")
    rect(a, 18, 28, 114, 3)
    call(a, "hn_fill", "accent bar under the input name")
    jump(a, "hn_end")

    for name, back in (("hn_align_big", 0x2A28), ("hn_align_small", 0x3A85)):
        a.comment("%s: on page 1 move the stored start x (XDATA 0x04:0x05) to 16" % name)
        a.L(name)
        a.i("mov A,0x45", 0xE5, 0x45)
        a.i("cjne A,#1,%s_x" % name, 0xB4, 0x01, rel(name + "_x"))
        a.i("mov R0,#4", 0x78, 0x04)
        a.i("movx A,@R0        ; start x hi", 0xE2)
        a.i("jnz %s_x" % name, 0x70, rel(name + "_x"))
        a.i("inc R0", 0x08)
        a.i("movx A,@R0        ; start x lo", 0xE2)
        a.i("clr C", 0xC3)
        a.i("subb A,#16", 0x94, 16)
        a.i("jc %s_x         ; wider than 288 px: keep it centred" % name, 0x40, rel(name + "_x"))
        a.i("mov A,#16", 0x74, 16)
        a.i("movx @R0,A        ; start x = 16", 0xF2)
        a.L(name + "_x")
        a.i("clr A             ; the two instructions the hook replaced", 0xE4)
        a.i("mov R0,#2", 0x78, 0x02)
        jump(a, back)


def build(a):
    build_data(a)
    build_primitives(a)
    build_volume_page(a)
    build_home(a)


def assemble():
    a = Asm(CODE_ADDR)
    build(a)
    code = a.resolve()
    assert a.labels["names"] == NAMES and a.labels["str_vol"] == STR_VOL
    return code, a.labels, a


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else BASE_IMAGE
    img = bytearray(open(src, "rb").read())
    sha = hashlib.sha256(img).hexdigest()
    if sha != BASE_SHA:
        raise SystemExit("base image is not the fast-lcd build (sha %s)" % sha)
    for addr, orig, _, _ in HOOKS:
        assert img[addr:addr + 3] == orig, "bytes at 0x%04X not as expected" % addr
    for s in VOL_ENTRY_SITES:
        assert img[s:s + len(VOL_ENTRY_ORIG)] == VOL_ENTRY_ORIG, "volume entry at 0x%04X not as expected" % s
    for inp, addr, text in INPUT_NAMES:
        assert img[addr:addr + len(text) + 1] == text.encode() + b"\0", "input name %d moved" % inp
    assert len(img) <= CODE_ADDR
    assert img[0x2A28] == 0xF2 and img[0x3A85] == 0xF2, "movx @R0,A after the align hooks moved"

    code, labels, a = assemble()
    img += b"\xFF" * (CODE_ADDR - len(img))
    img += code

    lines = []
    for addr, orig, op, target in HOOKS:
        t = labels[target]
        img[addr:addr + 3] = bytes([op, t >> 8, t & 0xFF])
        lines.append("; 0x%04X: %s -> %02x %02x %02x  (%s)" % (addr, orig.hex(" "), op, t >> 8, t & 0xFF, target))

    for s in VOL_ENTRY_SITES:
        new = vol_entry_bytes(labels["hn_enter_vol"])
        lines.append("; 0x%04X: %s -> %s  (lcall hn_enter_vol ; sjmp 0x%04X)" %
                     (s, VOL_ENTRY_ORIG[:5].hex(" "), new.hex(" "), s + len(VOL_ENTRY_ORIG)))
        img[s:s + 5] = new

    assert len(VERSION_TEXT) <= VERSION_MAX_LEN
    assert img[VERSION_PTR_ADDR] == 0x7A and img[VERSION_PTR_ADDR + 2] == 0x79
    ver = len(img)
    img += VERSION_TEXT.encode("ascii") + b"\0"
    img[VERSION_PTR_ADDR + 1] = ver >> 8
    img[VERSION_PTR_ADDR + 3] = ver & 0xFF
    assert len(img) <= 0xF400

    os.makedirs(os.path.dirname(OUT_IMAGE), exist_ok=True)
    open(OUT_IMAGE, "wb").write(img)
    with open(OUT_LISTING, "w") as f:
        f.write("; House Numerals patch, generated by build_patch.py; do not edit\n")
        f.write("\n".join(lines) + ("\n" if lines else ""))
        f.write("; version string %r at 0x%04X, pointer 0x%04X repointed\n\n" % (VERSION_TEXT, ver, VERSION_PTR_ADDR))
        f.write(a.listing())
    print("code %d bytes at 0x%04X..0x%04X" % (len(code), CODE_ADDR, CODE_ADDR + len(code) - 1))
    print("\n".join(ln[2:] for ln in lines))
    print("labels: " + " ".join("%s=0x%04X" % (k, v) for k, v in labels.items() if k.startswith("hn_")))
    print("version %r at 0x%04X" % (VERSION_TEXT, ver))
    print("wrote %s (%d bytes, sha256 %s)" % (OUT_IMAGE, len(img), hashlib.sha256(img).hexdigest()))


if __name__ == "__main__":
    main()
