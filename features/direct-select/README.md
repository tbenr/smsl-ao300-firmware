# Direct input selection and idempotent power over IR

Eight new NEC commands (0x10..0x17, stock address bytes 0x12 0x34), so a home-automation
controller that gets nothing back from the amp can set its state without guessing: six select
one input directly instead of stepping through the Source key, and two set the power state
instead of toggling it. The command table, the conditions and the RAM they touch are in
`direct_select.py`'s docstring; the README at the top of the repository has the command table.

Since ds2 a command for the input already selected is ignored: re-applying it ran the stock
source switch again, which re-initialises the source and interrupts the audio.

Since ds3, 0x16 powers on and 0x17 powers off, each a no-op in the state it names. Both become
the stock Power key (0x1F) only when that key would do what the command says: 0x16 in standby
(`standby_key` powers on), 0x17 when on (`key_power_off`). On a menu page the stock Power key
only goes home, so 0x17 first calls the dispatcher's own go-home handler (`key_exit_to_home`,
0x0CE9) and then returns the Power key: one command does what stock needs two presses for.
In standby neither command ever becomes key 0x10, `read_key`'s Source-in-standby jump to the
bootloader.

Since ds4 an input command in standby powers the amp on, on that input, so one command reaches
"on, on this input" from any state. The hook writes the input number to 0x47 and returns the
Power key; nothing else is new. Stock's power-on then runs its own chip setup, which reads 0x47
for its one `input_set_hw` call (`audio_chips_init`, 0x50F9) while the outputs are still
muted, draws the home screen with the new input and saves the settings. The other order,
power on and then select, would need a deferred switch after the power-on: a second source
setup and an audio interruption a few seconds after the wake. With the amp on nothing changed:
the same input is a no-op, another input a plain switch.

The wake is a build-time config, `WAKE_ON_INPUT` (default 1). With 0 the input commands are
ignored in standby, as before ds4. It is one immediate byte that `ds_wake` tests, so both
values build the same code (`tools/build.py` checks that on every build, and the installer
asks for the value).

## Shape

A fix, like `fix-auto-off` and `strings`: `direct_select.py` exports `HOOK` (the 3 bytes at
`ir_cmd_to_key`, 0x5D10, become `ljmp ds_select`), `emit(a)` (the 101-byte routine),
`CONFIG` (`WAKE_ON_INPUT`) and `XDATA = []`. An image meant for the amp lists `"direct-select"` in `INCLUDES`; house-numerals
and phosphor-panel do. `build_patch.py` builds the standalone image, stock plus the fix, with
the routine at 0x9400 and the RESET page showing `v1.4 tbenr ds4`.

## Status

All of it is verified on the amp inside house-numerals hn19 (2026-11-14): the six input
commands, the same-input ignore, the power commands and the wake on an input command, with no
pop reported on the wake. Only the first version of the standalone image was ever flashed
(2026-09-28). See `docs/status.md`.

In the emulator the wake ends in the same audio state as a stock power-on with that input
already stored (15 pairs of previous and new input); the only difference is that the input
mux pins move during the chip setup, outputs muted, as at a cold power-up.

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
never written. An input command in standby: the amp powers on on the home page, the input
is the commanded one, `input_set_hw` ran once and with that input, and the settings save
wrote it to EEPROM 0x0202; the same command again does nothing, another input is a plain
switch, and after standby the input it was on wakes it as well. `WAKE_ON_INPUT` is swept
through `emit()`: 0 and 1 differ in one byte, bad values stop the build, with 0 the six
commands are ignored in standby (hook and whole firmware) while every command translates as
with 1 when the amp is on, and in standby only the stock Source becomes key 0x10 in either
build. With `--in <feature>` it checks the same behaviour in that feature's image
and that the hook jumps into the image's own code ("direct-select in house-numerals" in
`tools/run_tests.py`).
