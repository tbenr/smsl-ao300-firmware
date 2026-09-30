#!/usr/bin/env python3
"""Build the direct-select image: the stock v1.4 image plus direct input selection over IR
(direct_select.py), and the RESET-page version string.

Usage: build_patch.py [base_image]   (default original/extracted/flash.bin)
Writes build/flash_patched.bin and the listing direct_select.asm.
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
import direct_select  # noqa: E402

BASE = features.STOCK               # the stock v1.4 image, original/extracted/flash.bin
INCLUDES = []                       # fix features linked into this image
XDATA = direct_select.XDATA         # this image's own code is the fix
BASE_IMAGE = features.image(BASE)
BASE_SHA = features.STOCK_SHA
OUT_IMAGE = os.path.join(HERE, "build", "flash_patched.bin")
OUT_LISTING = os.path.join(HERE, "direct_select.asm")
CODE_ADDR = 0x9400                  # just past the stock image (padded with 0xFF up to here)
HOOKS = [direct_select.HOOK]
VERSION_TEXT = "v1.4 tbenr ds2"


def assemble():
    a = Asm(CODE_ADDR)
    direct_select.emit(a)
    return a.resolve(), a.labels, a


def main():
    uikit.build_image(base_path=sys.argv[1] if len(sys.argv) > 1 else BASE_IMAGE, base_sha=BASE_SHA,
                      code_addr=CODE_ADDR, assemble=assemble, hooks=HOOKS,
                      version_text=VERSION_TEXT, out_image=OUT_IMAGE, out_listing=OUT_LISTING,
                      title="direct-select patch", label_prefixes=("ds_",))


if __name__ == "__main__":
    main()
