#!/usr/bin/env python3
"""Build the fix-volume-pop image: the stock v1.4 image plus the volume-key fix (fix_volume_pop.py).

Usage: build_patch.py [base_image]   (default original/extracted/flash.bin)
Writes build/flash_fixvolumepop.bin and the listing fix_volume_pop.asm.
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
import fix_volume_pop  # noqa: E402

BASE = features.STOCK               # the stock v1.4 image (tools/patch/features.py)
INCLUDES = []                       # fix features linked into this image
XDATA = fix_volume_pop.XDATA        # this image's own code is the fix
BASE_IMAGE = features.image(BASE)
BASE_SHA = features.STOCK_SHA
OUT_IMAGE = os.path.join(HERE, "build", "flash_fixvolumepop.bin")
OUT_LISTING = os.path.join(HERE, "fix_volume_pop.asm")
CODE_ADDR = 0x96D6                  # after start-volume (0x96B0..0x96D5); free in every image (fast-lcd starts at 0x9700)
HOOKS = [fix_volume_pop.HOOK] if hasattr(fix_volume_pop, "HOOK") else []
PATCHES = [(addr, orig, (lambda labels, new=new: new), note) for addr, orig, new, note in fix_volume_pop.PATCHES]
VERSION_TEXT = "v1.4 tbenr vp1"


def assemble():
    a = Asm(CODE_ADDR)
    fix_volume_pop.emit(a)
    return a.resolve(), a.labels, a


def main():
    uikit.build_image(base_path=sys.argv[1] if len(sys.argv) > 1 else BASE_IMAGE, base_sha=BASE_SHA,
                      code_addr=CODE_ADDR, assemble=assemble, hooks=HOOKS, patches=PATCHES,
                      version_text=VERSION_TEXT, out_image=OUT_IMAGE, out_listing=OUT_LISTING,
                      title="fix-volume-pop patch", label_prefixes=("vp_",))


if __name__ == "__main__":
    main()
