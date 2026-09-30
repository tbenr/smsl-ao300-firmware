# Direct input selection over IR

Six new NEC commands (0x10..0x15, stock address bytes 0x12 0x34) select one input directly,
so a home-automation controller can pick an input without stepping through the Source key.
The command table, the conditions and the RAM it touches are in `direct_select.py`'s
docstring; the README at the top of the repository lists the inputs.

Since ds2 a command for the input already selected is ignored: re-applying it ran the stock
source switch again, which re-initialises the source and interrupts the audio.

## Shape

A fix, like `fix-auto-off` and `strings`: `direct_select.py` exports `HOOK` (the 3 bytes at
`ir_cmd_to_key`, 0x5D10, become `ljmp ds_select`), `emit(a)` (the 61-byte routine) and
`XDATA = []`. An image meant for the amp lists `"direct-select"` in `INCLUDES`; house-numerals
does. `build_patch.py` builds the standalone image, stock plus the fix, with the routine at
0x9400 and the RESET page showing `v1.4 tbenr ds2`.

## Status

- Verified on the amp on 2026-09-28: the standalone image (then `v1.4 tbenr`, the first custom
  image). All six commands select the right input; the stock remote works unchanged.
- ds2 (the same-input ignore) verified on the amp on 2026-09-30 inside house-numerals hn11,
  hn11.1 and hn12 (the fix linked in through INCLUDES). The standalone ds2 image (sha `9b7e8b93…`) has not been flashed; it is byte-identical
  whether built by the old direct build or by the kit (checked on 2026-09-30).

## Tests

`emu_test.py` runs the hook on a focused 8051 interpreter, with the stock apply tail
intercepted: the six commands in every power and page state, the same-input case, the stock
translation of the other 250 commands against the stock image, the version pointer and an
image diff limited to the hook and the pointer. With `--in <feature>` it checks the same
behaviour in that feature's image and that the hook jumps into the image's own code
("direct-select in house-numerals" in `tools/run_tests.py`).
