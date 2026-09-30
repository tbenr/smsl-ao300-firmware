#!/usr/bin/env python3
"""Build the strings image: direct-select plus the corrected stock texts (strings.py).

Usage: build_patch.py [base_image]   (default features/direct-select/build/flash_patched.bin)
Writes build/flash_strings.bin and the listing strings.asm (patch notes only: no code).
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
import strings  # noqa: E402

BASE = "direct-select"              # image this builds on (tools/patch/features.py)
INCLUDES = []                       # fix features linked into this image
XDATA = strings.XDATA               # none
BASE_IMAGE = features.image(BASE)
BASE_SHA = "bb468b29ea935150d2c43e00074a68184920329529077898011a0c334a76f43e"
OUT_IMAGE = os.path.join(HERE, "build", "flash_strings.bin")
OUT_LISTING = os.path.join(HERE, "strings.asm")
CODE_ADDR = 0x96A0                  # after fix-auto-off (0x9680..0x969D); only the version string goes here
HOOKS = []
PATCHES = [(addr, orig, (lambda labels, new=new: new), note) for addr, orig, new, note in strings.PATCHES]
VERSION_TEXT = "v1.4 tbenr str1"


def assemble():
    a = Asm(CODE_ADDR)              # no code: the fix is in-place
    return a.resolve(), a.labels, a


def main():
    uikit.build_image(base_path=sys.argv[1] if len(sys.argv) > 1 else BASE_IMAGE, base_sha=BASE_SHA,
                      code_addr=CODE_ADDR, assemble=assemble, hooks=HOOKS, patches=PATCHES,
                      version_text=VERSION_TEXT, out_image=OUT_IMAGE, out_listing=OUT_LISTING,
                      title="strings patch", label_prefixes=("st_",))


if __name__ == "__main__":
    main()
