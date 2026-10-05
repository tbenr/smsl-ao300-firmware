#!/usr/bin/env python3
"""Build the auto-switch image: the stock v1.4 image plus auto-switch stage 1 (auto_switch.py)
and the fixes every image for the amp carries.

Usage: build_patch.py [base_image]   (default original/extracted/flash.bin)
Writes build/flash_autoswitch.bin and the listing auto_switch.asm.
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
import auto_switch  # noqa: E402

BASE = features.STOCK               # the stock v1.4 image (tools/patch/features.py)
INCLUDES = ["direct-select", "fix-auto-off", "strings", "start-volume", "fix-volume-pop", "fix-menu-input"]
XDATA = auto_switch.XDATA           # this image's own code is the feature
BASE_IMAGE = features.image(BASE)
BASE_SHA = features.STOCK_SHA
OUT_IMAGE = os.path.join(HERE, "build", "flash_autoswitch.bin")
OUT_LISTING = os.path.join(HERE, "auto_switch.asm")
CODE_ADDR = 0xF000                  # the feature and the six fixes; overlaps house-numerals' tail (0xF000..0xF0D7) and
                                    # nothing else: a different chain, so only a build.py warning
HOOKS = [auto_switch.HOOK] + features.hooks(INCLUDES)
PATCHES = features.patches(INCLUDES)
VERSION_TEXT = "v1.4 tbenr as2"      # as1: HDMI and Bluetooth enabled; as2: HDMI only (the module is off on other inputs)


def assemble():
    a = Asm(CODE_ADDR)
    auto_switch.emit(a)
    features.emit(a, INCLUDES)
    return a.resolve(), a.labels, a


def main():
    uikit.build_image(base_path=sys.argv[1] if len(sys.argv) > 1 else BASE_IMAGE, base_sha=BASE_SHA,
                      code_addr=CODE_ADDR, assemble=assemble, hooks=HOOKS, patches=PATCHES,
                      version_text=VERSION_TEXT, out_image=OUT_IMAGE, out_listing=OUT_LISTING,
                      title="auto-switch patch", label_prefixes=("as_",))


if __name__ == "__main__":
    main()
