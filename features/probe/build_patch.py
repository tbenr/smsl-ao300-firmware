#!/usr/bin/env python3
"""Build the probe image: the stock v1.4 image plus the register dump over the header
(probe.py) and the fixes every image for the amp carries.

Usage: build_patch.py [base_image]   (default original/extracted/flash.bin)
Writes build/flash_probe.bin and the listing probe.asm.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "patch"))
sys.path.insert(0, HERE)
import features  # noqa: E402
from asm51 import Asm  # noqa: E402
import uikit  # noqa: E402
import probe  # noqa: E402

BASE = features.STOCK               # the stock v1.4 image (tools/patch/features.py)
INCLUDES = ["direct-select", "fix-auto-off", "strings", "start-volume", "fix-volume-pop", "fix-menu-input"]
XDATA = probe.XDATA                 # this image's own code is the probe
BASE_IMAGE = features.image(BASE)
BASE_SHA = features.STOCK_SHA
OUT_IMAGE = os.path.join(HERE, "build", "flash_probe.bin")
OUT_LISTING = os.path.join(HERE, "probe.asm")
CODE_ADDR = 0xF100                  # above house-numerals (hn16 ends at 0xF0D7), below the EEPROM split 0xF400; the probe plus the six fixes take 0x200
HOOKS = [probe.HOOK] + features.hooks(INCLUDES)
PATCHES = features.patches(INCLUDES)
VERSION_TEXT = "v1.4 tbenr pr4"      # pr1: the dump on NEC 0x16; pr2: on the FN button (0x08); pr3: the FS line


def assemble():
    a = Asm(CODE_ADDR)
    probe.emit(a)
    features.emit(a, INCLUDES)
    return a.resolve(), a.labels, a


def main():
    uikit.build_image(base_path=sys.argv[1] if len(sys.argv) > 1 else BASE_IMAGE, base_sha=BASE_SHA,
                      code_addr=CODE_ADDR, assemble=assemble, hooks=HOOKS, patches=PATCHES,
                      version_text=VERSION_TEXT, out_image=OUT_IMAGE, out_listing=OUT_LISTING,
                      title="probe patch", label_prefixes=("pr_",))


if __name__ == "__main__":
    main()
