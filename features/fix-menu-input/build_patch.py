#!/usr/bin/env python3
"""Build the fix-menu-input image: the stock v1.4 image plus the menu input fix (fix_menu_input.py).

Usage: build_patch.py [base_image]   (default original/extracted/flash.bin)
Writes build/flash_fixmenuinput.bin and the listing fix_menu_input.asm.
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
import fix_menu_input  # noqa: E402

BASE = features.STOCK               # the stock v1.4 image (tools/patch/features.py)
INCLUDES = []                       # fix features linked into this image
XDATA = fix_menu_input.XDATA        # this image's own code is the fix
BASE_IMAGE = features.image(BASE)
BASE_SHA = features.STOCK_SHA
OUT_IMAGE = os.path.join(HERE, "build", "flash_fixmenuinput.bin")
OUT_LISTING = os.path.join(HERE, "fix_menu_input.asm")
CODE_ADDR = 0x9650                  # between direct-select (0x9400..0x944B) and fix-auto-off (0x9680); free in every image
HOOKS = [fix_menu_input.HOOK]
VERSION_TEXT = "v1.4 tbenr mi1"


def assemble():
    a = Asm(CODE_ADDR)
    fix_menu_input.emit(a)
    return a.resolve(), a.labels, a


def main():
    uikit.build_image(base_path=sys.argv[1] if len(sys.argv) > 1 else BASE_IMAGE, base_sha=BASE_SHA,
                      code_addr=CODE_ADDR, assemble=assemble, hooks=HOOKS,
                      version_text=VERSION_TEXT, out_image=OUT_IMAGE, out_listing=OUT_LISTING,
                      title="fix-menu-input patch", label_prefixes=("mi_",))


if __name__ == "__main__":
    main()
