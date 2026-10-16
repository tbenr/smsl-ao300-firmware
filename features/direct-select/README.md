# Direct input selection and idempotent power over IR

Eight new NEC commands (0x10..0x17, stock address bytes 0x12 0x34), so a home-automation
controller that gets nothing back from the amp can set its state without guessing: six select
one input directly instead of stepping through the Source key, and two set the power state
instead of toggling it. The command table, the conditions and the RAM they touch are in
`direct_select.py`'s docstring; the README at the top of the repository lists the inputs.

Since ds2 a command for the input already selected is ignored: re-applying it ran the stock
source switch again, which re-initialises the source and interrupts the audio.

Since ds3, 0x16 powers on and 0x17 powers off, each a no-op in the state it names. Both become
the stock Power key (0x1F) only when that key would do what the command says: 0x16 in standby
(`standby_key` powers on), 0x17 when on (`key_power_off`). On a menu page the stock Power key
only goes home, so 0x17 first calls the dispatcher's own go-home handler (`key_exit_to_home`,
0x0CE9) and then returns the Power key: one command does what stock needs two presses for.
In standby neither command ever becomes key 0x10, `read_key`'s Source-in-standby jump to the
bootloader.

## Shape

A fix, like `fix-auto-off` and `strings`: `direct_select.py` exports `HOOK` (the 3 bytes at
`ir_cmd_to_key`, 0x5D10, become `ljmp ds_select`), `emit(a)` (the 91-byte routine) and
`XDATA = []`. An image meant for the amp lists `"direct-select"` in `INCLUDES`; house-numerals
and phosphor-panel do. `build_patch.py` builds the standalone image, stock plus the fix, with
the routine at 0x9400 and the RESET page showing `v1.4 tbenr ds3`.

## Status

- Verified on the amp on 2026-09-28: the standalone image (then `v1.4 tbenr`, the first custom
  image). All six commands select the right input; the stock remote works unchanged.
- ds2 (the same-input ignore) verified on the amp on 2026-09-30 inside house-numerals hn11,
  hn11.1 and hn12 (the fix linked in through INCLUDES). The standalone ds2 image (sha `9b7e8b93…`)
  has not been flashed; it is byte-identical whether built by the old direct build or by the
  kit (checked on 2026-09-30).
- ds3 (the power commands, sha `425460c3…`), built on 2026-10-16: emulator-verified standalone
  and inside house-numerals hn18 and phosphor-panel pp3; not flashed yet.

## Tests

`emu_test.py` runs the hook on a focused 8051 interpreter, with the stock apply tail and
`key_exit_to_home` intercepted: the six input commands in every power and page state, the
same-input case, the two power commands in standby, on the home, volume and menu pages, the
stock translation of the other 248 commands against the stock image in five power/page
states, a check that no command but the stock Source becomes key 0x10, the version pointer
and an image diff limited to the hook and the pointer. Then the whole firmware on `Amp`
(real Timer0 and Timer3 ISRs): from standby, 0x17 does nothing and 0x16 powers on; 0x16
again changes nothing; 0x17 enters standby and 0x17 again does nothing; from a menu page
the stock Power key only goes home where 0x17 enters standby; and the bootloader reset is
never written. With `--in <feature>` it checks the same behaviour in that feature's image
and that the hook jumps into the image's own code ("direct-select in house-numerals" in
`tools/run_tests.py`).
