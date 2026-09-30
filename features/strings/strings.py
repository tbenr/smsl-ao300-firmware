"""Fix: stock texts corrected in place.

Stock v1.4 shows "No Connected" for HDMI ARC without a link: the status loader's no-signal
branch for input 5 (0x406D) loads the string at 0x91ED. The strings sit back to back
("Searching...\\0No Connected\\0No signal\\0"), so a replacement must fit its slot: at most as
many characters as the original, NUL-padded to the original length. Nothing else in the
firmware reads that string, so the whole fix is the 13 bytes at 0x91ED, no code, no XDATA.

Other builds list "strings" in INCLUDES and take the patches through features.patches(INCLUDES)
(tools/patch/features.py; README, "Feature graph"). Later renames go into STRINGS as well; the
input names (0x904F.., uikit.INPUT_NAMES) would also need house-numerals' fonts to carry the new
letters (it builds them from those texts).
"""
# (address, stock text, new text, note)
STRINGS = [
    (0x91ED, "No Connected", "Disconnected", "HDMI ARC without a link: the status loader's text for input 5 (0x406D)"),
]
XDATA = []                            # no code, no state


def _slot(addr, old, new, note):
    if len(new) > len(old) or not new.isascii() or not old.isascii():
        raise SystemExit("strings: %r does not fit the slot of %r at 0x%04X" % (new, old, addr))
    return addr, old.encode() + b"\0", new.encode() + b"\0" * (len(old) - len(new) + 1), note


PATCHES = [_slot(*row) for row in STRINGS]
