#!/usr/bin/env python3
"""Emulator test for strings (stock texts corrected in place).

  * the image differs from direct-select only in the patched string bytes and the version
    pointer, and nothing is appended but the version string;
  * the stock status loader (0x4016) on HDMI ARC without a link puts "Disconnected" into the
    status buffer (XDATA 0x50); on the other inputs its texts are unchanged;
  * all 256 NEC commands through the IR translate hook (0x5D10) behave as in direct-select,
    in standby and on every page;
  * whole firmware from reset, base and fix side by side: direct-select HDMI ARC, then the
    status line reads "Disconnected" where the base shows "No Connected", with the same
    audio events and state.
  * --in <image> (run_tests.py, "strings in <image>"): the patched bytes are in that image,
    and the loader and the whole-firmware ARC scenario give "Disconnected" there.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "emu"))
sys.path.insert(0, HERE)
from emu8051 import Emu8051  # noqa: E402
from ao300 import Amp, NEC_POWER  # noqa: E402
import build_patch as bp     # noqa: E402
import features              # noqa: E402  (tools/patch, on the path through build_patch)

INTEGRATION = True           # `emu_test.py --in <feature>`: the fix's promises in that image
import strings as fx         # noqa: E402

TEST_IMG = bp.OUT_IMAGE
BASE_IMG = bp.BASE_IMAGE
STATUS_LOADER = 0x4016       # home_refresh_periodic's status loader: signal check, then the text
LOADER_END = 0x4081          # ... runs on into lcall home_refresh
HOME_REFRESH = 0x5C8B
SMALL_TEXT_RENDER = 0x3A53
SMALL_BUF = 0x50
APPLY_TAIL = 0x5640          # direct-select's input apply, needs real hardware
NEC_ARC = 0x14               # direct-select HDMI ARC (input 5)

fails = []


def check(name, ok, detail=""):
    print("  %-70s %s %s" % (name, "OK  " if ok else "FAIL", detail))
    if not ok:
        fails.append(name)


def buffer_text(e, addr=SMALL_BUF, n=25):
    return bytes(e.xram[addr:addr + n]).split(b"\0")[0].decode("latin-1")


def image_diff():
    print("\nImage diff vs direct-select")
    a = open(BASE_IMG, "rb").read()
    b = open(TEST_IMG, "rb").read()
    changed = {i for i in range(len(a)) if a[i] != b[i]}
    want = {addr + k for addr, orig, new, _ in fx.PATCHES for k in range(len(orig)) if orig[k] != new[k]}
    check("only the patched string bytes (%s) and the version pointer changed"
          % ", ".join("0x%04X" % addr for addr, _, _, _ in fx.PATCHES),
          want <= changed <= want | {0x22CB, 0x22CD}, str(sorted("%04X" % i for i in changed ^ want)))
    for addr, orig, new, note in fx.PATCHES:
        check("0x%04X: %r -> %r, same length, NUL-terminated" % (addr, orig, new),
              b[addr:addr + len(new)] == new and a[addr:addr + len(orig)] == orig and len(new) == len(orig)
              and new.endswith(b"\0"))
    check("nothing appended but the version string", b[len(a):bp.CODE_ADDR] == b"\xFF" * (bp.CODE_ADDR - len(a))
          and b[bp.CODE_ADDR:] == bp.VERSION_TEXT.encode() + b"\0")


def loader(img_path, inp, pins=None):
    """XDATA 0x50 after the stock status loader for input inp (the emulator's expander reports no
    HDMI link and no Bluetooth stream; pins: {port: (mask, value)} for the signal pins)."""
    e = Emu8051(open(img_path, "rb").read())
    e.sfr[0x81] = 0x88
    e.iram[0x47] = inp
    e.iram[0x45] = 1
    if pins:
        e.pins.update(pins)
    e.hooks[HOME_REFRESH] = lambda em: em.ret()
    e.hooks[SMALL_TEXT_RENDER] = lambda em: em.ret()
    e.hooks[LOADER_END] = lambda em: em.ret()       # the theme may have hooked 0x4081: stop there either way
    e.call(STATUS_LOADER, max_steps=2_000_000)
    return buffer_text(e)


def loader_test(img_path, label):
    print("\nThe status loader (0x4016), %s" % label)
    check("HDMI ARC (input 5) without a link: \"Disconnected\"", loader(img_path, 5) == "Disconnected",
          repr(loader(img_path, 5)))
    for inp, pins, text in ((2, {0xC0: (0x04, 0x04)}, "No signal"), (2, {0xC0: (0x04, 0x00)}, None),
                            (4, None, "Searching..."), (6, None, None)):
        got, base = loader(img_path, inp, pins), loader(BASE_IMG, inp, pins)
        check("input %d%s: as direct-select (%r)" % (inp, "" if pins is None else " P4.2 %d" % (pins[0xC0][1] >> 2), base),
              got == base and (text is None or got == text), repr(got))


def make(img_path, cmd, power, page):
    e = Emu8051(open(img_path, "rb").read())
    e.sfr[0x81] = 0x88                       # SP as set by the firmware
    e.sfr[0xA8] = 0x80                       # EA on, as in normal running
    e.iram[0x6A] = cmd
    e.iram[0x4F] = power
    e.iram[0x45] = page
    e.iram[0x47] = 0x99
    e.iram[0x2B] = 1
    e.iram[0x48], e.iram[0x49] = 0xFF, 0xFF  # theme text colour (white theme)
    e.applied = None

    def apply(em):
        em.applied = em.iram[0x47]
        em.ret()
    e.hooks[APPLY_TAIL] = apply
    return e


def sweep():
    print("\nAll 256 NEC commands vs the direct-select image")
    diffs = 0
    for power, page in ((1, 1), (0, 1), (1, 0), (1, 2), (1, 3)):
        for cmd in range(256):
            r = []
            for img in (BASE_IMG, TEST_IMG):
                e = make(img, cmd, power, page)
                e.call(0x5D10, max_steps=10_000)
                r.append((e.R(7), e.iram[0x47], e.applied, e.iram[0x6F], e.iram[0x45], e.lcd.pixels))
            if r[0] != r[1]:
                diffs += 1
                print("    cmd 0x%02X power %d page %d: %s vs %s" % (cmd, power, page, r[0], r[1]))
    check("identical results for every command, power and page", diffs == 0, "(%d diffs)" % diffs)


def arc_scenario(img_path, label, base_path=None):
    """Power on, direct-select HDMI ARC (no link in the emulator), 4 s: the status buffer."""
    print("\nWhole firmware, %s: direct-select HDMI ARC without a link" % label)
    amps = [Amp(open(p, "rb").read()) for p in ([base_path] if base_path else []) + [img_path]]
    for amp in amps:
        amp.boot()
        amp.press(NEC_POWER)
        amp.wait(9.5)
        amp.press(NEC_ARC)
        amp.wait(4.0)
    new = amps[-1]
    check("input 5, powered, the status line reads \"Disconnected\"",
          new.e.iram[0x47] == 5 and new.powered and buffer_text(new.e) == "Disconnected", repr(buffer_text(new.e)))
    if base_path:
        base = amps[0]
        same = [n for _, n, _ in base.events] == [n for _, n, _ in new.events] and base.state == new.state
        check("direct-select shows \"No Connected\" there; same audio events and state",
              buffer_text(base.e) == "No Connected" and same and base.page == new.page)


def integration(img_path, label):
    """What the fix promises in any image that contains it (run_tests.py: "strings in <feature>")."""
    img = open(img_path, "rb").read()
    print("\nIntegration, %s: the patched texts are in the image" % label)
    for addr, orig, new, note in fx.PATCHES:
        check("0x%04X holds %r" % (addr, new), img[addr:addr + len(new)] == new, img[addr:addr + len(new)].hex(" "))
    loader_test(img_path, label)
    arc_scenario(img_path, label)


def finish():
    print("\n" + ("ALL PASS" if not fails else "FAILURES: %s" % ", ".join(fails)))
    sys.exit(1 if fails else 0)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--in":        # run_tests.py: this fix inside another image
        integration(features.image(sys.argv[2]), sys.argv[2])
        finish()
    image_diff()
    loader_test(TEST_IMG, "the standalone image")
    sweep()
    arc_scenario(TEST_IMG, "the standalone image", BASE_IMG)
    finish()


if __name__ == "__main__":
    main()
