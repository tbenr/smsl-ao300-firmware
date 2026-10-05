#!/usr/bin/env python3
"""Build the start-volume image: the stock v1.4 image plus the power-on volume cap (start_volume.py).

Usage: build_patch.py [base_image]   (default original/extracted/flash.bin)
Writes build/flash_startvolume.bin and the listing start_volume.asm.
The limits are set in start_volume.py (SPEAKER_LIMIT, HEADPHONE_LIMIT).
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
import start_volume  # noqa: E402

BASE = features.STOCK               # the stock v1.4 image (tools/patch/features.py)
INCLUDES = []                       # fix features linked into this image
XDATA = start_volume.XDATA          # this image's own code is the fix
BASE_IMAGE = features.image(BASE)
BASE_SHA = features.STOCK_SHA
OUT_IMAGE = os.path.join(HERE, "build", "flash_startvolume.bin")
OUT_LISTING = os.path.join(HERE, "start_volume.asm")
CODE_ADDR = 0x96B0                  # after strings' slot (0x96A0..0x96AF); free in every image (fast-lcd starts at 0x9700)
HOOKS = [start_volume.HOOK]
VERSION_TEXT = "v1.4 tbenr sv1"


def assemble():
    a = Asm(CODE_ADDR)
    start_volume.emit(a)
    return a.resolve(), a.labels, a


def main():
    uikit.build_image(base_path=sys.argv[1] if len(sys.argv) > 1 else BASE_IMAGE, base_sha=BASE_SHA,
                      code_addr=CODE_ADDR, assemble=assemble, hooks=HOOKS,
                      version_text=VERSION_TEXT, out_image=OUT_IMAGE, out_listing=OUT_LISTING,
                      title="start-volume patch", label_prefixes=("sv_",))


if __name__ == "__main__":
    main()
