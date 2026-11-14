# Strings: stock texts corrected in place

Stock v1.4 shows **"No Connected"** on the status line when HDMI ARC has no link. This fix
replaces it with **"Disconnected"** in the firmware's own string table, so every image that
includes the fix shows it wherever the stock code shows that status: the home screen, and the
House Numerals volume page. The standalone image is stock plus the fix; the RESET page
shows `v1.4 tbenr str3` (str1 and str2 were the same patch on direct-select).

## Status

On the amp inside the theme images since house-numerals hn10.1 (2026-09-30): works. The
standalone image has not been flashed. See `docs/status.md`.

## How it works

- The status loader (`home_refresh_periodic`'s 0x4016) picks a text per input when its signal
  check finds none; for input 5 (ARC) the branch at 0x406D loads the string at 0x91ED. Nothing
  else in the firmware refers to that string.
- The strings sit back to back (`Searching...\0No Connected\0No signal\0`), so a replacement
  must fit its slot: at most as many characters as the original, NUL-padded to the original
  length. "Disconnected" is exactly 12 characters, like "No Connected".
- The whole fix is those 13 bytes, patched in place (`strings.py`, `PATCHES`): no code, no
  hook, no XDATA. The standalone image appends only its version string.
- `STRINGS` in `strings.py` is the table: `(address, stock text, new text, note)`. Later
  renames go there too. Renaming an input (the names at 0x904F.., `uikit.INPUT_NAMES`) would
  also need House Numerals' fonts to carry the new letters, since it rasterises them from those
  texts.

## Including it

A build lists `"strings"` in `INCLUDES` and takes the patches through
`features.patches(INCLUDES)` (see `docs/development.md`, "Feature graph"). `tools/build.py` checks
that every included patch is applied. House Numerals includes it from hn10.1.

## Tests

`emu_test.py`:
- image diff: only the 13 bytes at 0x91ED and the version pointer differ from stock;
- the stock loader on ARC without a link fills the status buffer with "Disconnected"; the other
  inputs' texts are as in stock;
- all 256 NEC commands in five power/page states, against stock;
- whole firmware from reset, base and fix side by side: Source round to ARC, then the status reads
  "Disconnected" where the base shows "No Connected", with the same audio events and state;
- `--in <image>`: the bytes, the loader and the ARC scenario in any image that includes the fix.

## Memory

No code: the image is stock plus 16 bytes of version string at 0x96A0. No XDATA.
