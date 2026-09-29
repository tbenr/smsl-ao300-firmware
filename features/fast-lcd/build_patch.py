#!/usr/bin/env python3
"""Build the "fast LCD" image for the SMSL AO300 (on top of direct-select).

The stock UI keeps working as it is, but its two lowest-level pixel paths are
replaced with the tuned loop that the blit-test build verified on the panel (README, Bus timing):

  lcd_write_pixel 0x5C7C   stock: two calls of lcd_write_data 0x567A, each with its own
                           CS pulse and a delay call (about 55 clocks a pixel).
                           Now: both bytes inline under one CS pulse (13 clocks + call).
                           Every glyph, icon and rectangle fill goes through it.
  lcd_clear_black 0x51EE   stock: 54400 pixel calls in two 16-bit loops (about 147 ms).
                           The window setup at 0x51EE..0x5201 stays; its loop at 0x5202
                           becomes a same-byte black fill (P1 = 0, WR toggles only),
                           about 10 ms. Every page change starts with this clear.

Commands, window setup, LCD init and every other byte write still go through the
stock lcd_write_cmd 0x5C9C / lcd_write_data 0x567A, delay call included.

Register contract: the stock pixel routine returns with A = colour high byte and
R7 = 0 (0x001E counts R7 down), leaves R6 and every other register alone and writes
only its private 0x68/0x69. The replacement leaves A, R7 and the other registers the same
way; the clear tail leaves A = R6 = R7 = 0 and C = 0 like the stock loop's exit.
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "patch"))
import features  # noqa: E402
from asm51 import Asm, rel, ab  # noqa: E402

BASE = "direct-select"              # image this builds on (tools/patch/features.py)
INCLUDES = []                       # fix features linked into this image
BASE_IMAGE = features.image(BASE)
BASE_SHA = "bb468b29ea935150d2c43e00074a68184920329529077898011a0c334a76f43e"
OUT_IMAGE = os.path.join(HERE, "build", "flash_fastlcd.bin")
OUT_LISTING = os.path.join(HERE, "fast_lcd.asm")

# Placed after the old blit-test's code (0x9450..0x9632), so the Ghidra labels of each
# feature stayed distinct.
CODE_ADDR = 0x9700

PIXEL = 0x5C7C
PIXEL_ORIG = bytes([0x8E, 0x68, 0x8F])          # mov 0x68,R6 ; mov 0x69,...
CLEAR_LOOP = 0x5202
CLEAR_ORIG = bytes([0xE4, 0xF5, 0x5A])          # clr A ; mov 0x5A,A
CLEAR_WINDOW = bytes.fromhex("782f7401f208743ff2e4fbfa7da9fcfffe124437")  # 0x51EE..0x5201

P1 = 0x90
DC, WR, CS = 0x83, 0x85, 0x87                   # bit addresses P0.3, P0.5, P0.7

VERSION_TEXT = "v1.4 tbenr fast"
VERSION_PTR_ADDR = 0x22CA
VERSION_MAX_LEN = 20


def build(a):
    a.comment("replaces lcd_write_pixel 0x5C7C: colour R6:R7, both bytes under one CS pulse")
    a.L("fast_pixel")
    a.i("setb P0.3            ; D/C = data", 0xD2, DC)
    a.i("clr P0.7             ; CS low", 0xC2, CS)
    a.i("mov P1,R6            ; high byte", 0x8E, P1)
    a.i("clr P0.5", 0xC2, WR)
    a.i("setb P0.5            ; WR rises, panel latches", 0xD2, WR)
    a.i("mov P1,R7            ; low byte", 0x8F, P1)
    a.i("clr P0.5", 0xC2, WR)
    a.i("setb P0.5", 0xD2, WR)
    a.i("setb P0.7            ; CS high", 0xD2, CS)
    a.i("mov A,R6             ; stock exit state: A = high byte", 0xEE)
    a.i("mov R7,#0            ; stock exit state: R7 = 0", 0x7F, 0)
    a.i("ret", 0x22)

    a.comment("replaces lcd_clear_black's pixel loop at 0x5202; window already set")
    a.L("fast_clear")
    a.i("setb P0.3            ; D/C = data", 0xD2, DC)
    a.i("clr P0.7             ; CS low", 0xC2, CS)
    a.i("mov P1,#0x00         ; black: both bytes 0x00, set once", 0x75, P1, 0x00)
    a.i("mov R6,#0x1B         ; 6800 blocks of 8 px = 54400 px", 0x7E, 0x1B)
    a.i("mov R7,#0x90", 0x7F, 0x90)
    a.L("fc8")
    for k in range(16):
        a.i("clr P0.5             ; byte %d" % (k + 1), 0xC2, WR)
        a.i("setb P0.5", 0xD2, WR)
    a.i("djnz R7,fc8", 0xDF, rel("fc8"))
    a.i("djnz R6,fc8", 0xDE, rel("fc8"))
    a.i("setb P0.7            ; CS high", 0xD2, CS)
    a.i("clr A                ; stock exit state: A = R6 = R7 = 0, C = 0", 0xE4)
    a.i("mov R6,A", 0xFE)
    a.i("mov R7,A", 0xFF)
    a.i("clr C", 0xC3)
    a.i("ret", 0x22)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else BASE_IMAGE
    img = bytearray(open(src, "rb").read())
    sha = hashlib.sha256(img).hexdigest()
    if sha != BASE_SHA:
        raise SystemExit("base image is not the direct-select build (sha %s)" % sha)
    assert img[PIXEL:PIXEL + 3] == PIXEL_ORIG, "lcd_write_pixel not as expected"
    assert img[CLEAR_LOOP:CLEAR_LOOP + 3] == CLEAR_ORIG, "lcd_clear_black loop not as expected"
    assert img[0x51EE:CLEAR_LOOP] == CLEAR_WINDOW, "lcd_clear_black window setup not as expected"
    assert len(img) <= CODE_ADDR

    a = Asm(CODE_ADDR)
    build(a)
    code = a.resolve()
    img += b"\xFF" * (CODE_ADDR - len(img))
    img += code

    hooks = []
    for addr, target in ((PIXEL, "fast_pixel"), (CLEAR_LOOP, "fast_clear")):
        t = a.labels[target]
        old = bytes(img[addr:addr + 3])
        img[addr:addr + 3] = bytes([0x02, t >> 8, t & 0xFF])
        hooks.append("; 0x%04X: %s -> 02 %02x %02x  (ljmp %s)" % (addr, old.hex(" "), t >> 8, t & 0xFF, target))

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
        f.write("; fast LCD paths, generated by build_patch.py; do not edit\n")
        f.write("\n".join(hooks) + "\n")
        f.write("; version string %r at 0x%04X, pointer 0x%04X repointed\n\n" % (VERSION_TEXT, ver, VERSION_PTR_ADDR))
        f.write(a.listing())
    print("code %d bytes at 0x%04X..0x%04X" % (len(code), CODE_ADDR, CODE_ADDR + len(code) - 1))
    print("\n".join(h[2:] for h in hooks))
    print("version %r at 0x%04X" % (VERSION_TEXT, ver))
    print("wrote %s (%d bytes, sha256 %s)" % (OUT_IMAGE, len(img), hashlib.sha256(img).hexdigest()))


if __name__ == "__main__":
    main()
