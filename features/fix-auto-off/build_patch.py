#!/usr/bin/env python3
"""Build the fix-auto-off image: direct-select plus the Auto OFF power-on fix (fix_auto_off.py).

Usage: build_patch.py [base_image]   (default features/direct-select/build/flash_patched.bin)
Writes build/flash_fixautooff.bin and the listing fix_auto_off.asm.
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
import fix_auto_off  # noqa: E402

BASE = "direct-select"              # image this builds on (tools/patch/features.py)
INCLUDES = []                       # fix features linked into this image
XDATA = fix_auto_off.XDATA           # this image's own code is the fix
BASE_IMAGE = features.image(BASE)
BASE_SHA = "9b7e8b930d0b9f038d1996445e888ae08db4e928e2ec6755acb2564113912046"
OUT_IMAGE = os.path.join(HERE, "build", "flash_fixautooff.bin")
OUT_LISTING = os.path.join(HERE, "fix_auto_off.asm")
CODE_ADDR = 0x9680                  # after direct-select; free in every image (fast-lcd starts at 0x9700)
HOOKS = [fix_auto_off.HOOK]
VERSION_TEXT = "v1.4 tbenr aof2"


def assemble():
    a = Asm(CODE_ADDR)
    fix_auto_off.emit(a)
    return a.resolve(), a.labels, a


def main():
    uikit.build_image(base_path=sys.argv[1] if len(sys.argv) > 1 else BASE_IMAGE, base_sha=BASE_SHA,
                      code_addr=CODE_ADDR, assemble=assemble, hooks=HOOKS,
                      version_text=VERSION_TEXT, out_image=OUT_IMAGE, out_listing=OUT_LISTING,
                      title="fix-auto-off patch", label_prefixes=("fx_",))


if __name__ == "__main__":
    main()
