#!/usr/bin/env python3
"""Build the "direct source-select" firmware patch for the SMSL AO300 (STC8C2K64S2).

Stock behaviour: the remote's Source button (NEC command 0x07) only steps to the
next input. This patch adds six NEW NEC commands that jump straight to one input,
so a home-automation controller can select an input deterministically.

Mechanism
---------
The firmware turns a raw NEC command byte (RAM 0x6A) into an internal key code in
routine at 0x5D10, using a 15-entry table at code address 0x9398. Raw commands
0x10..0x15 are unused (they read past the table into erased flash -> "no key").

We hook 0x5D10 with `LJMP patch`. The patch:
  * for raw 0x10..0x15, and only when powered on (RAM 0x4F != 0) and on the home
    screen (RAM 0x45 == 1), writes the target input number (1..6) to RAM 0x47 and
    calls the stock "apply input" tail at 0x5640 (same code a real Source press
    runs: switches the audio mux via 0x24D6, refreshes OSD/LEDs), then returns
    "no key" (0xFF) so the normal dispatcher does nothing else;
  * for raw 0x10..0x15 when not powered on / not home, just returns "no key";
  * for every other raw command, performs the original table lookup, but only
    for commands 0x00..0x0E (the real table). Stock reads erased flash (0xFF =
    "no key") for higher commands; since the patch code now occupies part of that
    span, the patch returns "no key" explicitly instead of reading its own bytes.

Input numbering (RAM 0x47), from the on-screen input-name table:
  1=USB audio  2=Optical  3=Coaxial  4=Bluetooth  5=HDMI(ARC)  6=AUX IN
so:  cmd 0x10->USB  0x11->Optical  0x12->Coaxial  0x13->Bluetooth
     0x14->HDMI(ARC)  0x15->AUX IN
(Confirm the exact order on hardware; change CMD_BASE / mapping below if needed.)
"""
import hashlib
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "tools", "patch"))
import features  # noqa: E402

# ---- place in the feature graph (tools/patch/features.py) ------------------
BASE = features.STOCK              # the stock v1.4 image, original/extracted/flash.bin
INCLUDES = []
BASE_IMAGE = features.image(BASE)
BASE_SHA = features.STOCK_SHA
OUT_IMAGE = os.path.join(HERE, "build", "flash_patched.bin")

# ---- addresses in the stock image -----------------------------------------
HOOK_ADDR   = 0x5D10   # start of IR-translate routine (we overwrite 3 bytes)
HOOK_RESUME = 0x5D17   # stock code continues here: mov R7,A / clr A / mov 0x6F,A / ret
TABLE_ADDR  = 0x9398   # 15-entry raw->internal key table
TABLE_LEN   = 15       # commands 0x00..0x0E are real; stock reads erased flash (0xFF) above
APPLY_TAIL  = 0x5640   # stock "apply input in 0x47 to hardware" sequence
PATCH_ADDR  = 0x9400   # where our new code lives (just past padded image)

RAM_CMD   = 0x6A       # raw NEC command byte
RAM_KEY   = 0x6F       # secondary key var cleared by stock routine
RAM_INPUT = 0x47       # current input number (1..6)
RAM_POWER = 0x4F       # 0 = standby, nonzero = on
RAM_PAGE  = 0x45       # 1 = home screen
RAM_OSD0  = 0x27       # OSD timer high byte (stock sets 0 on a Source press)
RAM_OSD1  = 0x28       # OSD timer low byte (stock sets 0xC8 on a Source press)

CMD_LO = 0x10          # first direct-select NEC command
NINPUTS = 6            # number of inputs (commands CMD_LO .. CMD_LO+NINPUTS-1)

# ---- version string shown on the RESET menu page ---------------------------
# Stock draws "v1.4" from a Keil code pointer (R2:R1) loaded at 0x22CA; the string
# itself has no slack, so we place a new one after the patch code and repoint.
VERSION_TEXT     = "v1.4 tbenr"
VERSION_PTR_ADDR = 0x22CA          # bytes: 7A hi 79 lo  (mov R2,#hi ; mov R1,#lo)
VERSION_OLD_STR  = 0x8EB3          # address of the stock "v1.4"
VERSION_MAX_LEN  = 20              # the hint row below it is 20 chars in the same font


# ---- tiny label-based 8051 assembler --------------------------------------
class Asm:
    def __init__(self, org):
        self.org = org
        self.buf = bytearray()
        self.labels = {}
        self.fix = []   # (pos, kind, label, next_addr)

    @property
    def pc(self):
        return self.org + len(self.buf)

    def label(self, name):
        self.labels[name] = self.pc

    def _b(self, *bs):
        self.buf.extend(bs)

    # absolute-immediate ops
    def mov_a_dir(self, d):      self._b(0xE5, d)
    def mov_dir_a(self, d):      self._b(0xF5, d)
    def mov_dir_imm(self, d, i): self._b(0x75, d, i)
    def mov_a_imm(self, i):      self._b(0x74, i)
    def mov_r7_a(self):          self._b(0xFF)
    def mov_a_r7(self):          self._b(0xEF)
    def mov_r7_imm(self, i):     self._b(0x7F, i)
    def clr_a(self):             self._b(0xE4)
    def clr_c(self):             self._b(0xC3)
    def inc_a(self):             self._b(0x04)
    def subb_a_imm(self, i):     self._b(0x94, i)
    def xrl_a_imm(self, i):      self._b(0x64, i)
    def mov_dptr(self, a):       self._b(0x90, (a >> 8) & 0xFF, a & 0xFF)
    def movc(self):              self._b(0x93)
    def ret(self):               self._b(0x22)
    def lcall(self, a):          self._b(0x12, (a >> 8) & 0xFF, a & 0xFF)
    def ljmp(self, a):           self._b(0x02, (a >> 8) & 0xFF, a & 0xFF)

    # relative branches to a label (resolved later)
    def jc(self, lab):    self._rel(0x40, lab)
    def jnc(self, lab):   self._rel(0x50, lab)
    def jz(self, lab):    self._rel(0x60, lab)
    def jnz(self, lab):   self._rel(0x70, lab)
    def cjne_a_imm_here(self, i):
        # cjne A,#i,$+3  -> never branches, only sets carry (C=1 if A<i)
        self._b(0xB4, i, 0x00)

    def _rel(self, op, lab):
        self._b(op, 0)
        self.fix.append((len(self.buf) - 1, lab, self.pc))

    def resolve(self):
        for pos, lab, nxt in self.fix:
            rel = self.labels[lab] - nxt
            assert -128 <= rel <= 127, "branch out of range to %s (%d)" % (lab, rel)
            self.buf[pos] = rel & 0xFF
        return bytes(self.buf)


def build_patch():
    a = Asm(PATCH_ADDR)
    a.mov_a_dir(RAM_CMD)            # A = raw command
    a.clr_c()
    a.subb_a_imm(CMD_LO)           # A = cmd - 0x10 ; C=1 if cmd < 0x10
    a.jc("NOTSEL")                 # below range -> normal translate
    a.cjne_a_imm_here(NINPUTS)     # sets C=1 if (cmd-0x10) < NINPUTS
    a.jnc("NOTSEL")                # >= NINPUTS -> above range -> normal translate
    a.mov_r7_a()                   # R7 = idx (0..5)
    a.mov_a_dir(RAM_POWER)
    a.jz("EAT")                    # standby -> ignore
    a.mov_a_dir(RAM_PAGE)
    a.xrl_a_imm(1)                 # A = page ^ 1 (0 iff page==1)
    a.jnz("EAT")                   # not home -> ignore
    a.mov_a_r7()                   # A = idx
    a.inc_a()                      # A = idx+1 = input number 1..6
    a.mov_dir_a(RAM_INPUT)         # 0x47 = target input
    a.mov_dir_imm(RAM_OSD0, 0x00)  # show OSD like a real press
    a.mov_dir_imm(RAM_OSD1, 0xC8)
    a.lcall(APPLY_TAIL)            # switch hardware + refresh
    a.label("EAT")
    a.mov_r7_imm(0xFF)             # return "no key"
    a.clr_a()
    a.mov_dir_a(RAM_KEY)           # clear 0x6F (stock side effect)
    a.ret()
    a.label("NOTSEL")
    a.mov_a_dir(RAM_CMD)           # original: A = raw command
    a.cjne_a_imm_here(TABLE_LEN)   # sets C=1 if raw < TABLE_LEN
    a.jnc("EAT")                   # raw >= TABLE_LEN: stock read erased flash here -> "no key".
                                   # Now the patch code sits in that span, so refuse explicitly.
    a.mov_dptr(TABLE_ADDR)
    a.movc()                       # A = table[raw]
    a.ljmp(HOOK_RESUME)            # continue in stock code (mov R7,A; clr A; mov 0x6F,A; ret)
    return a


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else BASE_IMAGE
    dst = sys.argv[2] if len(sys.argv) > 2 else OUT_IMAGE
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    img = bytearray(open(src, "rb").read())
    sha = hashlib.sha256(img).hexdigest()
    if sha != BASE_SHA:
        raise SystemExit("base image %s has sha %s, expected %s" % (src, sha, BASE_SHA))

    # pad image up to PATCH_ADDR with 0xFF (erased flash)
    if len(img) > PATCH_ADDR:
        raise SystemExit("image already extends past patch area 0x%X" % PATCH_ADDR)
    img += b"\xFF" * (PATCH_ADDR - len(img))

    a = build_patch()
    patch = a.resolve()
    img += patch

    # version string: append after the code, repoint the R2:R1 pointer load
    assert len(VERSION_TEXT) <= VERSION_MAX_LEN, "version text too long for the row"
    assert bytes(img[VERSION_PTR_ADDR:VERSION_PTR_ADDR + 4]) == bytes(
        [0x7A, VERSION_OLD_STR >> 8, 0x79, VERSION_OLD_STR & 0xFF]), "version pointer not where expected"
    ver_addr = len(img)
    img += VERSION_TEXT.encode("ascii") + b"\0"
    img[VERSION_PTR_ADDR + 1] = ver_addr >> 8
    img[VERSION_PTR_ADDR + 3] = ver_addr & 0xFF

    # install the hook: LJMP PATCH_ADDR at 0x5D10 (overwrites 3 bytes)
    hook = bytes([0x02, (PATCH_ADDR >> 8) & 0xFF, PATCH_ADDR & 0xFF])
    orig = bytes(img[HOOK_ADDR:HOOK_ADDR + 3])
    img[HOOK_ADDR:HOOK_ADDR + 3] = hook

    open(dst, "wb").write(img)
    print("patch %d bytes at 0x%04X" % (len(patch), PATCH_ADDR))
    print("version string %r at 0x%04X, pointer at 0x%04X repointed" % (VERSION_TEXT, ver_addr, VERSION_PTR_ADDR))
    print("hook  @0x%04X: %s -> %s" % (HOOK_ADDR, orig.hex(), hook.hex()))
    print("labels:", {k: hex(v) for k, v in a.labels.items()})
    print("patch bytes:", patch.hex())
    print("wrote", dst, "size", len(img))


if __name__ == "__main__":
    main()
