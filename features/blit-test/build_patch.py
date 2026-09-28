#!/usr/bin/env python3
"""Build the "tuned blit" test image for the SMSL AO300 (on top of direct-select).

Test triggers, all only when powered on and on the home screen:

  remote Vol+ (NEC 0x0A) or NEC 0x16   tuned blit: 10 full-screen fills, new pixel loop
  remote Vol- (NEC 0x0B) or NEC 0x17   stock path: 10 full-screen fills with 0x51EE

Off the home screen (standby, menus, the volume page, the 5 s hold after a test)
Vol+/Vol- keep their stock function. On the home screen the remote no longer
changes the volume; the front knob (keys 0x5A/0x5B) still does.

Each test starts a stopwatch on the firmware's 10 ms tick, does its 10 fills, then
draws 8 colour bars through the same path and shows the elapsed tick count in big
digits at the volume-page position. Ten fills times 10 ms a tick means the number
reads directly as milliseconds per full-screen fill (tuned about 15, stock about
150). Five seconds later the stock return-home timer redraws the home screen.

Stopwatch: RAM 0x3F:0x40 is the 16-bit return-home countdown the Timer0 ISR
decrements every tick (0x3EDF); when it reaches zero the ISR sets page 1 and the
redraw flag. The test loads it with 0xFFFF, reads it back after the fills
(elapsed = 0xFFFF - value) and finally loads 500 ticks for the 5 s hold on page 0.

Hooks, both in direct-select's range check:
  0x9405 `jc not_select` (cmd < 0x10)       -> bt_low: Vol+/Vol- on home run a test,
                                               everything else goes to 0x942A
  0x940A `jnc not_select` (cmd-0x10 >= 6)   -> bt_entry: 0x16/0x17, else 0x942A
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools", "patch"))
from asm51 import Asm, rel, ab  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BASE_IMAGE = os.path.join(ROOT, "features", "direct-select", "build", "flash_patched.bin")
BASE_SHA = "bb468b29ea935150d2c43e00074a68184920329529077898011a0c334a76f43e"
OUT_IMAGE = os.path.join(HERE, "build", "flash_blittest.bin")
OUT_LISTING = os.path.join(HERE, "blit_test.asm")

# direct-select patch (features/direct-select/ir_direct_select.asm)
DS_RANGE_JC = 0x9405       # 40 23 : jc  not_select   (cmd < 0x10)
DS_RANGE_JNC = 0x940A      # 50 1E : jnc not_select   (A = cmd - 0x10 >= 6)
NEC_VOL_UP, NEC_VOL_DOWN = 0x0A, 0x0B    # table 0x9398 -> keys 0x1A (0x0D03 inc) / 0x1B (0x0ED2 dec)
RAM_CMD = 0x6A
DS_EAT = 0x9424            # R7 = 0xFF, clear 0x6F, ret
DS_NOTSEL = 0x942A         # normal table translate
CODE_ADDR = 0x9450

# stock routines
WINDOW = 0x4437            # x0 R2:R3, y0 R6:R7, y1 R4:R5, x1 in XDATA 0x2F:0x30
CLEAR = 0x51EE             # full-screen black through the stock pixel path
PIXEL = 0x5C7C             # one pixel, colour R6:R7, two calls of 0x567A
BIGNUM = 0x4384            # big digits: y R6:R7, x R4:R5, value R3, count XDATA[5]

RAM_POWER, RAM_PAGE = 0x4F, 0x45
RAM_T_HI, RAM_T_LO = 0x3F, 0x40
EA, ACC, DPL, DPH, P1 = 0xAF, 0xE0, 0x82, 0x83, 0x90
DC, WR, CS = 0x83, 0x85, 0x87            # bit addresses P0.3, P0.5, P0.7

V_MODE, V_TICKS = 0x0100, 0x0101         # XDATA, free from 0x0100
NFILLS = 10
HOLD_TICKS = 500
HOLD_PAGE = 0              # renderer draws nothing, read_key tail leaves keys alone

VERSION_TEXT = "v1.4 tbenr blit"
VERSION_PTR_ADDR = 0x22CA
VERSION_MAX_LEN = 20

COLOURS = [0xF800, 0x07E0, 0x001F, 0xFFFF, 0xFFE0, 0x07FF, 0xF81F, 0x7BEF]
COLOUR_NAMES = ["red", "green", "blue", "white", "yellow", "cyan", "magenta", "grey"]
BAND_W = 40


def build(a):
    a.comment("entry from direct-select at 0x940A: A = cmd - 0x10, already >= 6")
    a.L("bt_entry")
    a.i("cjne A,#6,bt_c7", 0xB4, 6, rel("bt_c7"))
    a.i("mov R1,#0            ; mode 0 = tuned blit", 0x79, 0)
    a.i("sjmp bt_go", 0x80, rel("bt_go"))
    a.L("bt_c7")
    a.i("cjne A,#7,bt_other", 0xB4, 7, rel("bt_other"))
    a.i("mov R1,#1            ; mode 1 = stock path", 0x79, 1)
    a.i("sjmp bt_go", 0x80, rel("bt_go"))
    a.L("bt_other")
    a.i("ljmp 0x%04X          ; direct-select not_select: normal translate" % DS_NOTSEL, 0x02, ab(DS_NOTSEL))
    a.L("bt_eat")
    a.i("ljmp 0x%04X          ; direct-select eat: R7 = 0xFF (no key)" % DS_EAT, 0x02, ab(DS_EAT))

    a.comment("entry from direct-select at 0x9405: raw command < 0x10")
    a.L("bt_low")
    a.i("mov A,g_ir_cmd", 0xE5, RAM_CMD)
    a.i("cjne A,#0x%02X,bt_l1    ; remote Vol+" % NEC_VOL_UP, 0xB4, NEC_VOL_UP, rel("bt_l1"))
    a.i("mov R1,#0            ; tuned", 0x79, 0)
    a.i("sjmp bt_lgo", 0x80, rel("bt_lgo"))
    a.L("bt_l1")
    a.i("cjne A,#0x%02X,bt_other ; remote Vol-" % NEC_VOL_DOWN, 0xB4, NEC_VOL_DOWN, rel("bt_other"))
    a.i("mov R1,#1            ; stock", 0x79, 1)
    a.L("bt_lgo")
    a.i("mov A,g_power_on", 0xE5, RAM_POWER)
    a.i("jz bt_other          ; standby: normal key", 0x60, rel("bt_other"))
    a.i("mov A,g_ui_page", 0xE5, RAM_PAGE)
    a.i("xrl A,#1", 0x64, 1)
    a.i("jnz bt_other         ; not home: normal volume key", 0x70, rel("bt_other"))
    a.i("sjmp bt_run", 0x80, rel("bt_run"))

    a.L("bt_go")
    a.i("mov A,g_power_on", 0xE5, RAM_POWER)
    a.i("jz bt_eat            ; standby: ignore", 0x60, rel("bt_eat"))
    a.i("mov A,g_ui_page", 0xE5, RAM_PAGE)
    a.i("xrl A,#1", 0x64, 1)
    a.i("jnz bt_eat           ; not home: ignore", 0x70, rel("bt_eat"))
    a.L("bt_run")
    a.i("mov DPTR,#V_MODE", 0x90, V_MODE >> 8, V_MODE & 0xFF)
    a.i("mov A,R1", 0xE9)
    a.i("movx @DPTR,A", 0xF0)

    a.comment("stopwatch: return-home countdown 0x3F:0x40 = 0xFFFF, ISR counts it down")
    a.i("mov C,EA", 0xA2, EA)
    a.i("clr EA", 0xC2, EA)
    a.i("mov 0x3F,#0xFF", 0x75, RAM_T_HI, 0xFF)
    a.i("mov 0x40,#0xFF", 0x75, RAM_T_LO, 0xFF)
    a.i("mov EA,C", 0x92, EA)

    a.i("mov A,#%d            ; full-screen fills" % NFILLS, 0x74, NFILLS)
    a.L("bt_meas")
    a.i("push ACC", 0xC0, ACC)
    a.i("mov DPTR,#V_MODE", 0x90, V_MODE >> 8, V_MODE & 0xFF)
    a.i("movx A,@DPTR", 0xE0)
    a.i("jnz bt_mstock", 0x70, rel("bt_mstock"))
    a.i("mov R2,#0            ; window x 0..319", 0x7A, 0)
    a.i("mov R3,#0", 0x7B, 0)
    a.i("mov R4,#0x01", 0x7C, 0x01)
    a.i("mov R5,#0x3F", 0x7D, 0x3F)
    a.i("lcall bt_win", 0x12, ab("bt_win"))
    a.i("pop ACC", 0xD0, ACC)
    a.i("push ACC", 0xC0, ACC)
    a.i("anl A,#7             ; colour index = counter & 7", 0x54, 7)
    a.i("rl A                 ; x2 bytes per colour", 0x23)
    a.i("mov R1,A", 0xF9)
    a.i("mov DPTR,#bt_colours", 0x90, ab("bt_colours"))
    a.i("movc A,@A+DPTR", 0x93)
    a.i("mov R2,A             ; colour high byte", 0xFA)
    a.i("mov A,R1", 0xE9)
    a.i("inc A", 0x04)
    a.i("movc A,@A+DPTR", 0x93)
    a.i("mov R3,A             ; colour low byte", 0xFB)
    a.i("mov R6,#0x1B         ; 6800 blocks of 8 = 54400 px", 0x7E, 0x1B)
    a.i("mov R7,#0x90", 0x7F, 0x90)
    a.i("lcall bt_fill", 0x12, ab("bt_fill"))
    a.i("sjmp bt_mnext", 0x80, rel("bt_mnext"))
    a.L("bt_mstock")
    a.i("lcall 0x%04X         ; stock full-screen clear" % CLEAR, 0x12, ab(CLEAR))
    a.L("bt_mnext")
    a.i("pop ACC", 0xD0, ACC)
    a.i("djnz ACC,bt_meas", 0xD5, ACC, rel("bt_meas"))

    a.comment("stop: elapsed ticks = 0xFFFF - countdown, saturated at 255")
    a.i("mov C,EA", 0xA2, EA)
    a.i("clr EA", 0xC2, EA)
    a.i("mov R6,0x3F", 0xAE, RAM_T_HI)
    a.i("mov R7,0x40", 0xAF, RAM_T_LO)
    a.i("mov EA,C", 0x92, EA)
    a.i("mov A,R6", 0xEE)
    a.i("cpl A", 0xF4)
    a.i("jnz bt_sat", 0x70, rel("bt_sat"))
    a.i("mov A,R7", 0xEF)
    a.i("cpl A", 0xF4)
    a.i("sjmp bt_store", 0x80, rel("bt_store"))
    a.L("bt_sat")
    a.i("mov A,#0xFF", 0x74, 0xFF)
    a.L("bt_store")
    a.i("mov DPTR,#V_TICKS", 0x90, V_TICKS >> 8, V_TICKS & 0xFF)
    a.i("movx @DPTR,A", 0xF0)

    a.comment("8 colour bars, 40 px wide, through the same path")
    a.i("mov DPTR,#bt_bands", 0x90, ab("bt_bands"))
    a.i("mov A,#8", 0x74, 8)
    a.L("bt_bar")
    a.i("push ACC", 0xC0, ACC)
    for reg, name in ((0xFA, "R2 = x0 hi"), (0xFB, "R3 = x0 lo"), (0xFC, "R4 = x1 hi"), (0xFD, "R5 = x1 lo")):
        a.i("clr A", 0xE4)
        a.i("movc A,@A+DPTR", 0x93)
        a.i("mov %s" % name.replace(" = ", ",A          ; "), reg)
        a.i("inc DPTR", 0xA3)
    a.i("push DPL", 0xC0, DPL)
    a.i("push DPH", 0xC0, DPH)
    a.i("lcall bt_win", 0x12, ab("bt_win"))
    a.i("pop DPH", 0xD0, DPH)
    a.i("pop DPL", 0xD0, DPL)
    for reg, name in ((0xFA, "R2 = colour hi"), (0xFB, "R3 = colour lo")):
        a.i("clr A", 0xE4)
        a.i("movc A,@A+DPTR", 0x93)
        a.i("mov %s" % name.replace(" = ", ",A          ; "), reg)
        a.i("inc DPTR", 0xA3)
    a.i("push DPL", 0xC0, DPL)
    a.i("push DPH", 0xC0, DPH)
    a.i("mov R6,#0x04         ; 850 blocks of 8 = 6800 px = 40 x 170", 0x7E, 0x04)
    a.i("mov R7,#0x52", 0x7F, 0x52)
    a.i("lcall bt_fill", 0x12, ab("bt_fill"))
    a.i("pop DPH", 0xD0, DPH)
    a.i("pop DPL", 0xD0, DPL)
    a.i("pop ACC", 0xD0, ACC)
    a.i("djnz ACC,bt_bar", 0xD5, ACC, rel("bt_bar"))

    a.comment("elapsed ticks as three big digits at the volume-page position 130,75")
    a.i("mov DPTR,#V_TICKS", 0x90, V_TICKS >> 8, V_TICKS & 0xFF)
    a.i("movx A,@DPTR", 0xE0)
    a.i("mov R3,A", 0xFB)
    a.i("mov R0,#5", 0x78, 5)
    a.i("mov A,#3             ; digit count", 0x74, 3)
    a.i("movx @R0,A", 0xF2)
    a.i("mov R6,#0", 0x7E, 0)
    a.i("mov R7,#75           ; y", 0x7F, 75)
    a.i("mov R4,#0", 0x7C, 0)
    a.i("mov R5,#130          ; x", 0x7D, 130)
    a.i("lcall 0x%04X         ; stock big-digit painter" % BIGNUM, 0x12, ab(BIGNUM))

    a.comment("hold on page 0 (unused after boot; page 2 would make read_key's tail at")
    a.comment("0x3DD6 turn our 'no key' into 0x15 = go home). The ISR returns home at 0.")
    a.i("mov g_ui_page,#HOLD_PAGE", 0x75, RAM_PAGE, HOLD_PAGE)
    a.i("mov C,EA", 0xA2, EA)
    a.i("clr EA", 0xC2, EA)
    a.i("mov 0x3F,#0x%02X" % (HOLD_TICKS >> 8), 0x75, RAM_T_HI, HOLD_TICKS >> 8)
    a.i("mov 0x40,#0x%02X      ; %d ticks = 5 s" % (HOLD_TICKS & 0xFF, HOLD_TICKS), 0x75, RAM_T_LO, HOLD_TICKS & 0xFF)
    a.i("mov EA,C", 0x92, EA)
    a.i("ljmp 0x%04X          ; direct-select eat: R7 = 0xFF (no key)" % DS_EAT, 0x02, ab(DS_EAT))

    a.comment("window x R2:R3 .. R4:R5, y 0..169, then RAMWR")
    a.L("bt_win")
    a.i("mov R0,#0x2F", 0x78, 0x2F)
    a.i("mov A,R4", 0xEC)
    a.i("movx @R0,A           ; x1 hi", 0xF2)
    a.i("inc R0", 0x08)
    a.i("mov A,R5", 0xED)
    a.i("movx @R0,A           ; x1 lo", 0xF2)
    a.i("clr A", 0xE4)
    a.i("mov R6,A             ; y0 = 0", 0xFE)
    a.i("mov R7,A", 0xFF)
    a.i("mov R4,A             ; y1 = 169", 0xFC)
    a.i("mov R5,#0xA9", 0x7D, 0xA9)
    a.i("ljmp 0x%04X          ; stock window: CASET, RASET, RAMWR" % WINDOW, 0x02, ab(WINDOW))

    a.comment("fill: colour R2:R3, R6:R7 blocks of 8 px (R6 = high + 1 when R7 != 0)")
    a.L("bt_fill")
    a.i("mov DPTR,#V_MODE", 0x90, V_MODE >> 8, V_MODE & 0xFF)
    a.i("movx A,@DPTR", 0xE0)
    a.i("jnz bt_sfill", 0x70, rel("bt_sfill"))
    a.i("setb P0.3            ; D/C = data for the whole block", 0xD2, DC)
    a.i("clr P0.7             ; CS low for the whole block", 0xC2, CS)
    a.L("bt_f8")
    for px in range(8):
        a.i("mov P1,R2            ; pixel %d high byte" % (px + 1), 0x8A, P1)
        a.i("clr P0.5", 0xC2, WR)
        a.i("setb P0.5            ; WR rises, panel latches", 0xD2, WR)
        a.i("mov P1,R3            ; pixel %d low byte" % (px + 1), 0x8B, P1)
        a.i("clr P0.5", 0xC2, WR)
        a.i("setb P0.5", 0xD2, WR)
    a.i("djnz R7,bt_f8", 0xDF, rel("bt_f8"))
    a.i("djnz R6,bt_f8", 0xDE, rel("bt_f8"))
    a.i("setb P0.7            ; CS high", 0xD2, CS)
    a.i("ret", 0x22)
    a.comment("the same pixels through the stock driver, one 0x5C7C call per pixel")
    a.L("bt_sfill")
    a.i("mov A,R6", 0xEE)
    a.i("mov R4,A", 0xFC)
    a.i("mov A,R7", 0xEF)
    a.i("mov R5,A", 0xFD)
    a.L("bt_s8")
    a.i("mov R1,#8", 0x79, 8)
    a.L("bt_s1")
    a.i("mov A,R2", 0xEA)
    a.i("mov R6,A", 0xFE)
    a.i("mov A,R3", 0xEB)
    a.i("mov R7,A", 0xFF)
    a.i("lcall 0x%04X" % PIXEL, 0x12, ab(PIXEL))
    a.i("djnz R1,bt_s1", 0xD9, rel("bt_s1"))
    a.i("djnz R5,bt_s8", 0xDD, rel("bt_s8"))
    a.i("djnz R4,bt_s8", 0xDC, rel("bt_s8"))
    a.i("ret", 0x22)

    a.L("bt_colours")
    for c, n in zip(COLOURS, COLOUR_NAMES):
        a.data("dw 0x%04X  ; %s" % (c, n), [c >> 8, c & 0xFF])
    a.L("bt_bands")
    for k, (c, n) in enumerate(zip(COLOURS, COLOUR_NAMES)):
        x0, x1 = k * BAND_W, k * BAND_W + BAND_W - 1
        a.data("x %3d..%3d  %s" % (x0, x1, n), [x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF, c >> 8, c & 0xFF])


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else BASE_IMAGE
    img = bytearray(open(src, "rb").read())
    sha = hashlib.sha256(img).hexdigest()
    if sha != BASE_SHA:
        raise SystemExit("base image is not the direct-select build (sha %s)" % sha)
    assert img[DS_RANGE_JNC:DS_RANGE_JNC + 2] == b"\x50\x1E", "direct-select range check not found"
    assert img[DS_RANGE_JC:DS_RANGE_JC + 2] == b"\x40\x23", "direct-select low-range branch not found"
    assert len(img) <= CODE_ADDR

    a = Asm(CODE_ADDR)
    build(a)
    code = a.resolve()
    img += b"\xFF" * (CODE_ADDR - len(img))
    img += code

    # repoint direct-select's "cmd - 0x10 >= 6" branch at the new dispatcher
    r = CODE_ADDR - (DS_RANGE_JNC + 2)
    assert 0 <= r <= 127
    img[DS_RANGE_JNC + 1] = r
    # repoint direct-select's "cmd < 0x10" branch at the Vol+/Vol- check
    r2 = a.labels["bt_low"] - (DS_RANGE_JC + 2)
    assert 0 <= r2 <= 127
    img[DS_RANGE_JC + 1] = r2

    # version string
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
        f.write("; tuned-blit test, generated by build_patch.py; do not edit\n")
        f.write("; 0x9405: 40 23 -> 40 %02X  (jc bt_low)\n" % r2)
        f.write("; 0x940A: 50 1E -> 50 %02X  (jnc bt_entry)\n" % r)
        f.write("; version string %r at 0x%04X, pointer 0x%04X repointed\n\n" % (VERSION_TEXT, ver, VERSION_PTR_ADDR))
        f.write(a.listing())
    print("code %d bytes at 0x%04X..0x%04X" % (len(code), CODE_ADDR, CODE_ADDR + len(code) - 1))
    print("labels:", ", ".join("%s=%04X" % kv for kv in a.labels.items()))
    print("version %r at 0x%04X" % (VERSION_TEXT, ver))
    print("wrote %s (%d bytes, sha256 %s)" % (OUT_IMAGE, len(img), hashlib.sha256(img).hexdigest()))


if __name__ == "__main__":
    main()
